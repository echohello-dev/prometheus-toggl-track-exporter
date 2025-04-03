import base64
import os
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Optional

import requests
from prometheus_client import Counter, Gauge, start_http_server

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

# User metrics
TOGGL_USER_INFO = Gauge(
    "toggl_user_info",
    "User information from the /me endpoint",
    ["user_id", "email", "fullname", "timezone"],
)
TOGGL_USER_ACTIVE = Gauge(
    "toggl_user_active",
    "Indicates if the user account is active (1=active, 0=inactive)",
    ["user_id"],
)
TOGGL_USER_HAS_PASSWORD = Gauge(
    "toggl_user_has_password",
    "Indicates if the user has a password set (1=yes, 0=no)",
    ["user_id"],
)
# Gauges for boolean-like settings (treat strings like 'true'/'false' as 1/0)
TOGGL_USER_SEND_PRODUCT_EMAILS = Gauge(
    "toggl_user_send_product_emails",
    "User preference for receiving product emails (1=yes, 0=no)",
    ["user_id"],
)
TOGGL_USER_SEND_TIMER_NOTIFICATIONS = Gauge(
    "toggl_user_send_timer_notifications",
    "User preference for receiving timer notifications (1=yes, 0=no)",
    ["user_id"],
)
TOGGL_USER_SEND_WEEKLY_REPORT = Gauge(
    "toggl_user_send_weekly_report",
    "User preference for receiving weekly reports (1=yes, 0=no)",
    ["user_id"],
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
TOGGL_PROJECT_INFO = Gauge(
    "toggl_project_info",
    "Information about individual projects",
    [
        "workspace_id",
        "project_id",
        "project_name",
        "client_id",
        "client_name",
        "active",
        "billable",
        "is_private",
        "color",
    ],
)
TOGGL_CLIENTS_TOTAL = Gauge(
    "toggl_clients_total", "Total number of clients", ["workspace_id"]
)
TOGGL_CLIENT_INFO = Gauge(
    "toggl_client_info",
    "Information about individual clients",
    ["workspace_id", "client_id", "client_name"],
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

# --- New Time Entry Performance Metrics ---
PERFORMANCE_LABELS = [
    "workspace_id",
    "timeframe",  # e.g., "24h"
]
TOGGL_TIME_ENTRIES_AVG_DURATION_SECONDS = Gauge(
    "toggl_time_entries_avg_duration_seconds",
    "Average duration of completed time entries in the lookback period",
    PERFORMANCE_LABELS,
)
TOGGL_TIME_ENTRIES_BILLABLE_RATIO = Gauge(
    "toggl_time_entries_billable_ratio",
    "Ratio of billable time duration to total time duration in the lookback period (0.0 to 1.0)",
    PERFORMANCE_LABELS,
)
TOGGL_DAYS_WITH_TIME_ENTRIES_COUNT = Gauge(
    "toggl_days_with_time_entries_count",
    "Number of distinct days with completed time entries in the lookback period",
    PERFORMANCE_LABELS,
)
TOGGL_TIME_ENTRIES_UNTAGGED_DURATION_SECONDS = Gauge(
    "toggl_time_entries_untagged_duration_seconds",
    "Total duration of completed time entries with no tags in the lookback period",
    PERFORMANCE_LABELS,
)
TOGGL_TIME_ENTRIES_UNTAGGED_COUNT = Gauge(
    "toggl_time_entries_untagged_count",
    "Number of completed time entries with no tags in the lookback period",
    PERFORMANCE_LABELS,
)

# --- Helper Functions ---


def _get_auth_header() -> dict[str, str]:
    """Generates the Basic Auth header for Toggl API."""
    if not TOGGL_API_TOKEN:
        # Ignore TRY003 for this specific informative message
        raise ValueError("TOGGL_API_TOKEN not set.")  # noqa: TRY003
    credentials = f"{TOGGL_API_TOKEN}:api_token"
    encoded_creds = base64.b64encode(credentials.encode()).decode("ascii")
    return {"Authorization": f"Basic {encoded_creds}"}


def _make_toggl_request(
    endpoint: str, method: str = "GET", params: Optional[dict] = None
) -> Optional[dict]:
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
        else:
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


def update_user_metrics(me_data: Optional[dict]) -> Optional[int]:
    """Updates metrics based on the /me endpoint data."""
    if not me_data or "id" not in me_data:
        print("Cannot update user metrics: Missing or invalid /me data.")
        # Clear potentially stale user metrics if data is missing after success
        TOGGL_USER_INFO.clear()
        TOGGL_USER_ACTIVE.clear()
        TOGGL_USER_HAS_PASSWORD.clear()
        TOGGL_USER_SEND_PRODUCT_EMAILS.clear()
        TOGGL_USER_SEND_TIMER_NOTIFICATIONS.clear()
        TOGGL_USER_SEND_WEEKLY_REPORT.clear()
        return None

    user_id = str(me_data["id"])
    email = me_data.get("email", "unknown")
    fullname = me_data.get("fullname", "unknown")
    timezone = me_data.get("timezone", "unknown")

    # Set informational gauge
    # Clear previous labels for this metric before setting new ones
    TOGGL_USER_INFO.clear()
    TOGGL_USER_INFO.labels(
        user_id=user_id, email=email, fullname=fullname, timezone=timezone
    ).set(1)

    # Helper to convert boolean/string flags to 0 or 1
    def _flag_to_float(value) -> float:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, str):
            return 1.0 if value.lower() == "true" else 0.0
        # Default to 0 if type is unexpected or value is missing/None
        return 0.0

    # Update specific gauges
    TOGGL_USER_ACTIVE.labels(user_id=user_id).set(_flag_to_float(me_data.get("active")))
    TOGGL_USER_HAS_PASSWORD.labels(user_id=user_id).set(
        _flag_to_float(me_data.get("hasPassword"))
    )
    TOGGL_USER_SEND_PRODUCT_EMAILS.labels(user_id=user_id).set(
        _flag_to_float(me_data.get("send_product_emails"))
    )
    TOGGL_USER_SEND_TIMER_NOTIFICATIONS.labels(user_id=user_id).set(
        _flag_to_float(me_data.get("send_timer_notifications"))
    )
    TOGGL_USER_SEND_WEEKLY_REPORT.labels(user_id=user_id).set(
        _flag_to_float(
            me_data.get("send_weekly_report")
        )  # Note: API doc shows send_weekly_reports (plural)
    )

    print(f"Updated user metrics for user ID: {user_id}")
    return me_data.get("default_workspace_id")


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

    # --- Clients ---
    clients = get_clients(workspace_id)
    client_map: dict[int, str] = {}
    # Clear previous client info for this workspace before setting new ones
    TOGGL_CLIENT_INFO.clear()
    # Need to selectively clear based on workspace_id if supporting multiple
    # For now, assumes single workspace context per run.

    if clients is not None:
        TOGGL_CLIENTS_TOTAL.labels(workspace_id=ws_label).set(len(clients))
        for client in clients:
            client_id = client.get("id")
            client_name = client.get("name", "unknown")
            if client_id is not None:
                client_map[client_id] = client_name
                TOGGL_CLIENT_INFO.labels(
                    workspace_id=ws_label,
                    client_id=str(client_id),
                    client_name=client_name,
                ).set(1)
    else:
        TOGGL_CLIENTS_TOTAL.labels(workspace_id=ws_label).set(0)
        print(f"Could not fetch clients for workspace {ws_label}.")

    # --- Projects ---
    projects = get_projects(workspace_id)
    # Clear previous project info for this workspace
    TOGGL_PROJECT_INFO.clear()
    # Need selective clear if supporting multiple workspaces simultaneously.

    if projects is not None:
        TOGGL_PROJECTS_TOTAL.labels(workspace_id=ws_label).set(len(projects))
        for project in projects:
            project_id = project.get("id")
            if project_id is None:
                continue

            project_name = project.get("name", "unknown")
            client_id = project.get("client_id")  # Can be null
            client_name = client_map.get(client_id, "none") if client_id else "none"
            active = project.get("active", True)  # Default to True if missing?
            billable = project.get("billable", False)
            is_private = project.get("is_private", True)  # Check default
            color = project.get("color", "unknown")

            TOGGL_PROJECT_INFO.labels(
                workspace_id=ws_label,
                project_id=str(project_id),
                project_name=project_name,
                client_id=str(client_id) if client_id else "none",
                client_name=client_name,
                active=str(active),
                billable=str(billable),
                is_private=str(is_private),
                color=color,
            ).set(1)
    else:
        TOGGL_PROJECTS_TOTAL.labels(workspace_id=ws_label).set(0)
        print(f"Could not fetch projects for workspace {ws_label}.")

    # --- Tags ---
    tags = get_tags(workspace_id)
    # Note: No TOGGL_TAG_INFO gauge defined currently
    if tags is not None:
        TOGGL_TAGS_TOTAL.labels(workspace_id=ws_label).set(len(tags))
    else:
        TOGGL_TAGS_TOTAL.labels(workspace_id=ws_label).set(0)

    print(f"Updated aggregate metrics for workspace ID: {ws_label}")


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

    if entries is None:
        print("Failed to fetch time entries, skipping update.")
        return

    # --- Aggregation Setup ---
    # For existing detailed metrics
    aggregated_durations: dict[tuple, float] = {}
    aggregated_counts: dict[tuple, int] = {}

    # For new performance metrics (aggregated per workspace)
    ws_performance: dict[str, dict] = {}
    # Structure: { "workspace_id_str": { "total_duration": float, "total_count": int, "billable_duration": float, "untagged_duration": float, "untagged_count": int, "entry_dates": set() }}

    for entry in entries:
        # We only care about completed entries (duration > 0)
        duration = entry.get("duration", 0)
        if duration <= 0:
            continue

        ws_id = entry.get("workspace_id")
        if ws_id is None:
            continue  # Skip entries without workspace ID for performance metrics
        ws_id_str = str(ws_id)

        # Initialize workspace performance dict if first time seen
        if ws_id_str not in ws_performance:
            ws_performance[ws_id_str] = {
                "total_duration": 0.0,
                "total_count": 0,
                "billable_duration": 0.0,
                "untagged_duration": 0.0,
                "untagged_count": 0,
                "entry_dates": set(),
            }

        proj_id = entry.get("project_id")
        proj_name = entry.get("project_name")
        task_id = entry.get("task_id")
        task_name = entry.get("task_name")
        tags_list = entry.get("tags", [])
        tags = ",".join(sorted(tags_list))
        billable = entry.get("billable", False)
        start_time_str = entry.get("start")

        # --- Update Performance Aggregates ---
        perf_data = ws_performance[ws_id_str]
        perf_data["total_duration"] += duration
        perf_data["total_count"] += 1
        if billable:
            perf_data["billable_duration"] += duration
        if not tags_list:  # Check original list before joining
            perf_data["untagged_duration"] += duration
            perf_data["untagged_count"] += 1
        start_dt = parse_iso_datetime(start_time_str)
        if start_dt:
            # Store date part only to count unique days
            perf_data["entry_dates"].add(start_dt.date())

        # --- Update Detailed Aggregates (existing logic) ---
        proj_id_label = str(proj_id) if proj_id is not None else "none"
        task_id_label = str(task_id) if task_id is not None else "none"
        proj_name_label = proj_name if proj_name is not None else "none"
        task_name_label = task_name if task_name is not None else "none"

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

    # Set the detailed gauges from aggregated data
    for label_key, total_duration in aggregated_durations.items():
        label_dict = dict(zip(TIME_ENTRY_LABELS, label_key))
        TOGGL_TIME_ENTRIES_DURATION_SECONDS.labels(**label_dict).set(total_duration)

    for label_key, count in aggregated_counts.items():
        label_dict = dict(zip(TIME_ENTRY_LABELS, label_key))
        TOGGL_TIME_ENTRIES_COUNT.labels(**label_dict).set(count)

    # --- Set Performance Metrics Gauges ---
    for ws_id_str, perf_data in ws_performance.items():
        performance_label_dict = {
            "workspace_id": ws_id_str,
            "timeframe": timeframe_label,
        }
        total_count = perf_data["total_count"]
        total_duration = perf_data["total_duration"]

        # Average Duration
        avg_duration = total_duration / total_count if total_count > 0 else 0
        TOGGL_TIME_ENTRIES_AVG_DURATION_SECONDS.labels(**performance_label_dict).set(
            avg_duration
        )

        # Billable Ratio
        billable_ratio = (
            perf_data["billable_duration"] / total_duration if total_duration > 0 else 0
        )
        TOGGL_TIME_ENTRIES_BILLABLE_RATIO.labels(**performance_label_dict).set(
            billable_ratio
        )

        # Distinct Days
        distinct_days = len(perf_data["entry_dates"])
        TOGGL_DAYS_WITH_TIME_ENTRIES_COUNT.labels(**performance_label_dict).set(
            distinct_days
        )

        # Untagged Metrics
        TOGGL_TIME_ENTRIES_UNTAGGED_DURATION_SECONDS.labels(
            **performance_label_dict
        ).set(perf_data["untagged_duration"])
        TOGGL_TIME_ENTRIES_UNTAGGED_COUNT.labels(**performance_label_dict).set(
            perf_data["untagged_count"]
        )

    print(
        f"Updated time entry metrics for {len(aggregated_counts)} detailed label sets "
        f"and {len(ws_performance)} workspaces ({timeframe_label})"
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

        # --- Update User Metrics ---
        # This function now extracts default_workspace_id as well
        default_workspace_id = update_user_metrics(me_data)

        # --- Update Running Timer Metrics ---
        update_running_timer_metrics(current_entry)

        # --- Update Workspace Aggregate & Time Entry Metrics ---
        if default_workspace_id:
            print(f"Using default workspace ID: {default_workspace_id}")
            update_aggregate_metrics(default_workspace_id)
            update_time_entries_metrics(TIME_ENTRIES_LOOKBACK_HOURS)
        else:
            print(
                "Could not determine default workspace ID. "
                "Skipping workspace-specific metrics."
            )
            # Clear aggregate & time entry metrics if workspace ID is missing
            print(
                "Clearing aggregate and time entry metrics due to missing workspace ID."
            )
            TOGGL_PROJECTS_TOTAL.clear()
            TOGGL_CLIENTS_TOTAL.clear()
            TOGGL_TAGS_TOTAL.clear()
            TOGGL_TIME_ENTRIES_DURATION_SECONDS.clear()
            TOGGL_TIME_ENTRIES_COUNT.clear()
            # Also clear new performance metrics
            TOGGL_TIME_ENTRIES_AVG_DURATION_SECONDS.clear()
            TOGGL_TIME_ENTRIES_BILLABLE_RATIO.clear()
            TOGGL_DAYS_WITH_TIME_ENTRIES_COUNT.clear()
            TOGGL_TIME_ENTRIES_UNTAGGED_DURATION_SECONDS.clear()
            TOGGL_TIME_ENTRIES_UNTAGGED_COUNT.clear()

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
