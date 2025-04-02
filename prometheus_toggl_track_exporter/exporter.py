from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from prometheus_client import Counter, Gauge, start_http_server
from typing import Any, Optional
import base64
import os
import requests
import time

# --- Configuration ---
TOGGL_API_TOKEN = os.environ.get("TOGGL_API_TOKEN")
# Toggl API V9 Base URL
TOGGL_API_BASE_URL = "https://api.track.toggl.com/api/v9"
EXPORTER_PORT = int(os.environ.get("EXPORTER_PORT", "9090"))
# Note: prometheus_client ignores this path
METRICS_PATH = os.environ.get("METRICS_PATH", "/metrics")
COLLECTION_INTERVAL = int(os.environ.get("COLLECTION_INTERVAL", "60"))
TIME_ENTRIES_LOOKBACK_HOURS = int(os.environ.get("TIME_ENTRIES_LOOKBACK_HOURS", "24"))

# --- Metrics Definitions ---
TOGGL_API_ERRORS = Counter(
    "toggl_api_errors", "Number of Toggl API errors encountered", ["endpoint"]
)
TOGGL_SCRAPE_DURATION = Gauge(
    "toggl_scrape_duration_seconds", "Time taken to collect Toggl metrics"
)

# Currently running time entry metrics
TOGGL_TIME_ENTRY_RUNNING = Gauge(
    "toggl_time_entry_running",
    "Indicates if a time entry is currently running (1=running, 0=stopped)",
    [
        "workspace_id",
        "project_id",
        "project_name",
        "task_id",
        "task_name",
        "description",
        "tags",
        "billable",
    ],
)
TOGGL_TIME_ENTRY_START_TIMESTAMP = Gauge(
    "toggl_time_entry_start_timestamp",
    "Start time of the current running time entry (Unix timestamp)",
    [
        "workspace_id",
        "project_id",
        "project_name",
        "task_id",
        "task_name",
        "description",
        "tags",
        "billable",
    ],
)

# Aggregate metrics
TOGGL_PROJECTS_TOTAL = Gauge(
    "toggl_projects_total", "Total number of projects", ["workspace_id"]
)
TOGGL_CLIENTS_TOTAL = Gauge(
    "toggl_clients_total", "Total number of clients", ["workspace_id"]
)
TOGGL_TAGS_TOTAL = Gauge("toggl_tags_total", "Total number of tags", ["workspace_id"])

# Time Entry Aggregates (over lookback period)
TIME_ENTRY_LABELS = [
    "workspace_id",
    "project_id",
    "project_name",
    "task_id",
    "task_name",
    "tags",
    "billable",
    "timeframe",  # e.g., "24h"
]
TOGGL_TIME_ENTRIES_DURATION_SECONDS = Gauge(
    "toggl_time_entries_duration_seconds",
    "Total duration of completed time entries in the lookback period",
    TIME_ENTRY_LABELS,
)
TOGGL_TIME_ENTRIES_COUNT = Gauge(
    "toggl_time_entries_count",
    "Number of completed time entries in the lookback period",
    TIME_ENTRY_LABELS,
)

# --- Helper Functions ---


def _get_auth_header() -> dict[str, str]:
    """Generates the Basic Auth header for Toggl API."""
    if not TOGGL_API_TOKEN:
        raise ValueError("TOGGL_API_TOKEN environment variable not set.")
    credentials = f"{TOGGL_API_TOKEN}:api_token"
    encoded_creds = base64.b64encode(credentials.encode()).decode("ascii")
    return {"Authorization": f"Basic {encoded_creds}"}


def _make_toggl_request(
    endpoint: str, method: str = "GET", params: Optional[dict] = None
) -> Optional[Any]:
    """Makes a request to the Toggl API."""
    url = f"{TOGGL_API_BASE_URL}{endpoint}"
    try:
        headers = _get_auth_header()
        headers["Content-Type"] = "application/json"

        response = requests.request(
            method, url, headers=headers, params=params, timeout=30
        )
        # Raise HTTPError for bad responses (4xx or 5xx)
        response.raise_for_status()

        # Handle potential empty response for success codes like 204
        if response.status_code == HTTPStatus.NO_CONTENT:
            return None
        if response.content:
            return response.json()
        return None

    except requests.exceptions.RequestException as e:
        print(f"Error making Toggl API request to {endpoint}: {e}")
        if isinstance(e, requests.exceptions.HTTPError):
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        # Use first path part as endpoint label
        endpoint_label = endpoint.lstrip("/").split("/")[0]
        TOGGL_API_ERRORS.labels(endpoint=endpoint_label).inc()
        return None
    except ValueError as e:  # Handle missing API token
        print(f"Configuration error: {e}")
        # Optionally increment a configuration error counter if needed
        return None
    except Exception as e:  # Catch unexpected errors
        err_msg = f"Unexpected error during API request to {endpoint}: {e}"
        print(err_msg)
        # Use first path part as endpoint label
        endpoint_label = endpoint.lstrip("/").split("/")[0]
        TOGGL_API_ERRORS.labels(endpoint=endpoint_label).inc()
        return None


def get_me() -> Optional[dict]:
    """Fetches details for the authenticated user."""
    return _make_toggl_request("/me")


def get_current_time_entry() -> Optional[dict]:
    """Fetches the currently running time entry."""
    return _make_toggl_request("/me/time_entries/current")


def get_projects(workspace_id: int) -> Optional[list]:
    """Fetches projects for a given workspace."""
    return _make_toggl_request(f"/workspaces/{workspace_id}/projects")


def get_clients(workspace_id: int) -> Optional[list]:
    """Fetches clients for a given workspace."""
    # Note: The clients endpoint might be deprecated or changed in v9.
    # Documentation mainly shows /workspaces/{workspace_id}/clients/{client_id}
    # Assuming a list endpoint exists, otherwise this needs adjustment.
    # If fetching all isn't directly supported, might need
    # iteration or reports API.
    return _make_toggl_request(f"/workspaces/{workspace_id}/clients")


def get_tags(workspace_id: int) -> Optional[list]:
    """Fetches tags for a given workspace."""
    return _make_toggl_request(f"/workspaces/{workspace_id}/tags")


def get_time_entries(start_date: str, end_date: str) -> Optional[list]:
    """Fetches time entries between start_date and end_date (RFC3339 format)."""
    params = {"start_date": start_date, "end_date": end_date}
    return _make_toggl_request("/me/time_entries", params=params)


# --- Data Processing and Metric Updates ---


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parses ISO 8601 datetime string with timezone."""
    if not dt_str:
        return None
    try:
        # Handle potential 'Z' for UTC and timezone offsets
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except ValueError:
        print(f"Could not parse datetime string: {dt_str}")
        return None


def update_running_timer_metrics(entry: Optional[dict]) -> None:
    """Updates metrics based on the current time entry."""
    # Resetting metrics with dynamic labels is complex.
    # prometheus_client doesn't easily remove labels by wildcard.
    # We rely on the scrape interval; if a timer stops, the next scrape
    # won't set these metrics, and Prometheus marks them stale.

    if entry and entry.get("id"):
        # Extract data, providing defaults for missing optional fields
        ws_id = entry.get("workspace_id", "unknown")
        proj_id = entry.get("project_id")  # Can be null
        proj_name = entry.get("project_name")
        task_id = entry.get("task_id")  # Can be null
        task_name = entry.get("task_name")
        desc = entry.get("description", "")
        # Join tags into a sorted string
        tags = ",".join(sorted(entry.get("tags", [])))
        billable = entry.get("billable", False)
        start_time_str = entry.get("start")

        # Convert project/task IDs to string for labels, handle None
        proj_id_label = str(proj_id) if proj_id is not None else "none"
        task_id_label = str(task_id) if task_id is not None else "none"
        proj_name_label = proj_name if proj_name is not None else "none"
        task_name_label = task_name if task_name is not None else "none"

        label_values = {
            "workspace_id": str(ws_id),
            "project_id": proj_id_label,
            "project_name": proj_name_label,
            "task_id": task_id_label,
            "task_name": task_name_label,
            "description": desc,
            "tags": tags,
            "billable": str(billable),
        }

        TOGGL_TIME_ENTRY_RUNNING.labels(**label_values).set(1)

        start_dt = parse_iso_datetime(start_time_str)
        if start_dt:
            start_timestamp = start_dt.timestamp()
            TOGGL_TIME_ENTRY_START_TIMESTAMP.labels(**label_values).set(start_timestamp)
        else:
            # If start time is invalid, don't set the timestamp gauge
            # Consider how to handle this - maybe remove the old metric?
            pass

    else:
        # No running timer.
        # We rely on Prometheus staleness marking for metrics that are no
        # longer present in the scrape.
        # To explicitly set a gauge to 0, one might need to track previous
        # labels or use a simpler gauge like TOGGL_ANY_TIME_ENTRY_RUNNING.
        pass


def update_aggregate_metrics(workspace_id: int) -> None:
    """Fetches and updates aggregate metrics like project, client, tag counts."""
    if not workspace_id:
        print("Cannot update aggregate metrics without a workspace ID.")
        return

    ws_label = str(workspace_id)

    projects = get_projects(workspace_id)
    if projects is not None:  # API returns list or null on error
        TOGGL_PROJECTS_TOTAL.labels(workspace_id=ws_label).set(len(projects))
    else:
        # Optionally clear or set to 0 if needed, depends on desired
        # behavior on error
        TOGGL_PROJECTS_TOTAL.labels(workspace_id=ws_label).set(0)

    clients = get_clients(workspace_id)
    if clients is not None:
        TOGGL_CLIENTS_TOTAL.labels(workspace_id=ws_label).set(len(clients))
    else:
        TOGGL_CLIENTS_TOTAL.labels(workspace_id=ws_label).set(0)

    tags = get_tags(workspace_id)
    if tags is not None:
        TOGGL_TAGS_TOTAL.labels(workspace_id=ws_label).set(len(tags))
    else:
        TOGGL_TAGS_TOTAL.labels(workspace_id=ws_label).set(0)


def update_time_entries_metrics(lookback_hours: int) -> None:
    """Fetches and updates metrics for time entries in the lookback period."""
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=lookback_hours)
    start_date_str = start_time.isoformat(timespec="seconds")
    end_date_str = now.isoformat(timespec="seconds")
    timeframe_label = f"{lookback_hours}h"

    print(
        f"Fetching time entries from {start_date_str} to {end_date_str} "
        f"({timeframe_label})"
    )

    entries = get_time_entries(start_date=start_date_str, end_date=end_date_str)

    # Reset metrics for this timeframe before aggregation
    # This requires finding all label combinations used with the timeframe
    # which is complex. A simpler approach is to not reset and rely on
    # Prometheus staleness, or reset ALL labels (less ideal).
    # For now, we accumulate into potentially existing values from previous scrapes.
    # A better approach might be to use a Counter for total counts/duration
    # if exact point-in-time counts for the window are not strictly needed.

    # Alternative: Explicitly clear specific timeframe labels if possible (hard)
    # TOGGL_TIME_ENTRIES_DURATION_SECONDS.remove(..., timeframe=timeframe_label)
    # TOGGL_TIME_ENTRIES_COUNT.remove(..., timeframe=timeframe_label)

    if entries is None:
        print("Failed to fetch time entries, skipping update.")
        # Optionally set counts/duration to 0 for this timeframe?
        return

    aggregated_durations: dict[tuple, float] = {}
    aggregated_counts: dict[tuple, int] = {}

    for entry in entries:
        # We only care about completed entries (duration > 0)
        duration = entry.get("duration", 0)
        if duration <= 0:
            continue

        ws_id = entry.get("workspace_id", "unknown")
        proj_id = entry.get("project_id")
        proj_name = entry.get("project_name")
        task_id = entry.get("task_id")
        task_name = entry.get("task_name")
        tags = ",".join(sorted(entry.get("tags", [])))
        billable = entry.get("billable", False)

        proj_id_label = str(proj_id) if proj_id is not None else "none"
        task_id_label = str(task_id) if task_id is not None else "none"
        proj_name_label = proj_name if proj_name is not None else "none"
        task_name_label = task_name if task_name is not None else "none"

        # Create a unique key for aggregation based on labels
        label_key = (
            str(ws_id),
            proj_id_label,
            proj_name_label,
            task_id_label,
            task_name_label,
            tags,
            str(billable),
            timeframe_label,
        )

        aggregated_durations[label_key] = (
            aggregated_durations.get(label_key, 0) + duration
        )
        aggregated_counts[label_key] = aggregated_counts.get(label_key, 0) + 1

    # Set the gauges from aggregated data
    for label_key, total_duration in aggregated_durations.items():
        label_dict = dict(zip(TIME_ENTRY_LABELS, label_key))
        TOGGL_TIME_ENTRIES_DURATION_SECONDS.labels(**label_dict).set(total_duration)

    for label_key, count in aggregated_counts.items():
        label_dict = dict(zip(TIME_ENTRY_LABELS, label_key))
        TOGGL_TIME_ENTRIES_COUNT.labels(**label_dict).set(count)

    print(
        f"Updated time entry metrics for {len(aggregated_counts)} label sets "
        f"({timeframe_label})"
    )


# --- Main Collection Logic ---


def collect_metrics() -> None:
    """Collects and exposes all Toggl metrics."""
    with TOGGL_SCRAPE_DURATION.time():
        if not TOGGL_API_TOKEN:
            print("Error: TOGGL_API_TOKEN environment variable not set.")
            # Consider setting an error gauge
            return

        print("Collecting Toggl metrics...")

        # --- Fetch Data ---
        me_data = get_me()
        current_entry = get_current_time_entry()

        default_workspace_id = None
        if me_data and me_data.get("default_workspace_id"):
            default_workspace_id = me_data["default_workspace_id"]
            print(f"Using default workspace ID: {default_workspace_id}")
        else:
            print("Could not determine default workspace ID from /me endpoint.")
            # Decide how to handle this: maybe skip aggregate metrics?

        # --- Update Metrics ---
        update_running_timer_metrics(current_entry)

        if default_workspace_id:
            update_aggregate_metrics(default_workspace_id)
            update_time_entries_metrics(TIME_ENTRIES_LOOKBACK_HOURS)
        else:
            # Reset aggregate & time entry metrics if workspace ID is lost
            print(
                "Clearing aggregate and time entry metrics due to missing workspace ID."
            )
            TOGGL_PROJECTS_TOTAL.clear()  # Clear all labels
            TOGGL_CLIENTS_TOTAL.clear()
            TOGGL_TAGS_TOTAL.clear()
            TOGGL_TIME_ENTRIES_DURATION_SECONDS.clear()
            TOGGL_TIME_ENTRIES_COUNT.clear()

        print("Finished collecting Toggl metrics.")


def main() -> None:
    """Main function to run the exporter."""
    # The default registry is used, exposing metrics at /metrics
    start_http_server(EXPORTER_PORT)
    print(f"Toggl Track Prometheus exporter started on port {EXPORTER_PORT}")

    if not TOGGL_API_TOKEN:
        print(
            "Warning: TOGGL_API_TOKEN environment variable is not set. "
            "Exporter will not collect metrics."
        )

    # Collect metrics on a schedule
    while True:
        collect_metrics()
        print(f"Next collection in {COLLECTION_INTERVAL} seconds.")
        time.sleep(COLLECTION_INTERVAL)


if __name__ == "__main__":
    main()
