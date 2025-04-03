import base64
import unittest
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
import requests
from prometheus_client import REGISTRY

# Import the Toggl exporter module
from prometheus_toggl_track_exporter import exporter

# Constants for tests
# Use placeholder values for testing
TEST_API_TOKEN = "test_toggl_token"  # noqa: S105
TEST_WORKSPACE_ID = 123456
TEST_PROJECT_ID = 987654
TEST_PROJECT_NAME = "Test Project"
TEST_TASK_ID = 112233
TEST_TASK_NAME = "Test Task"
TEST_CLIENT_ID = 554433
TEST_CLIENT_NAME = "Test Client"
TEST_TAG_NAME = "test-tag"


class TestTogglExporter(unittest.TestCase):
    def setUp(self):
        # Reset metrics before each test
        for name, collector in list(REGISTRY._names_to_collectors.items()):
            # Unregister collectors directly using the list of collectors
            # This avoids issues if a collector is registered under multiple names
            try:
                REGISTRY.unregister(collector)
            except KeyError:
                # Skip metrics that aren't properly registered or already unregistered
                print(f"Metric {name} already unregistered or not found.")

        # Set API token for tests
        # Patching the constant directly in the module
        self.api_token_patcher = patch(
            "prometheus_toggl_track_exporter.exporter.TOGGL_API_TOKEN", TEST_API_TOKEN
        )
        self.mock_api_token = self.api_token_patcher.start()

        # Register Toggl metrics
        self.api_errors = exporter.TOGGL_API_ERRORS
        self.scrape_duration = exporter.TOGGL_SCRAPE_DURATION
        self.time_entry_running = exporter.TOGGL_TIME_ENTRY_RUNNING
        self.time_entry_start_timestamp = exporter.TOGGL_TIME_ENTRY_START_TIMESTAMP
        self.projects_total = exporter.TOGGL_PROJECTS_TOTAL
        self.clients_total = exporter.TOGGL_CLIENTS_TOTAL
        self.tags_total = exporter.TOGGL_TAGS_TOTAL
        self.time_entries_duration = exporter.TOGGL_TIME_ENTRIES_DURATION_SECONDS
        self.time_entries_count = exporter.TOGGL_TIME_ENTRIES_COUNT

        # New performance metrics
        self.time_entries_avg_duration = (
            exporter.TOGGL_TIME_ENTRIES_AVG_DURATION_SECONDS
        )
        self.time_entries_billable_ratio = exporter.TOGGL_TIME_ENTRIES_BILLABLE_RATIO
        self.time_entries_distinct_days = exporter.TOGGL_DAYS_WITH_TIME_ENTRIES_COUNT
        self.time_entries_untagged_duration = (
            exporter.TOGGL_TIME_ENTRIES_UNTAGGED_DURATION_SECONDS
        )
        self.time_entries_untagged_count = exporter.TOGGL_TIME_ENTRIES_UNTAGGED_COUNT

        # Clear any potential leftover metric values (important for Gauges)
        self.api_errors.clear()
        self.scrape_duration.set(0)  # Set gauge to 0
        self.time_entry_running.clear()
        self.time_entry_start_timestamp.clear()
        self.projects_total.clear()
        self.clients_total.clear()
        self.tags_total.clear()
        self.time_entries_duration.clear()
        self.time_entries_count.clear()
        self.time_entries_avg_duration.clear()
        self.time_entries_billable_ratio.clear()
        self.time_entries_distinct_days.clear()
        self.time_entries_untagged_duration.clear()
        self.time_entries_untagged_count.clear()

    def tearDown(self):
        # Stop the patcher
        self.api_token_patcher.stop()

    @patch("prometheus_toggl_track_exporter.exporter._make_toggl_request")
    def test_get_me_success(self, mock_make_request):
        # Mock API response
        mock_response = {
            "id": 1,
            "email": "user@example.com",
            "default_workspace_id": TEST_WORKSPACE_ID,
        }
        mock_make_request.return_value = mock_response

        # Test function
        result = exporter.get_me()

        # Verify results
        mock_make_request.assert_called_once_with("/me")
        assert result == mock_response

    @patch("prometheus_toggl_track_exporter.exporter._make_toggl_request")
    def test_get_me_error(self, mock_make_request):
        # Mock API error (returns None)
        mock_make_request.return_value = None

        # Test function
        result = exporter.get_me()

        # Verify results
        mock_make_request.assert_called_once_with("/me")
        assert result is None
        # Error count is incremented within _make_toggl_request,
        # so we'd test that separately

    @patch("prometheus_toggl_track_exporter.exporter._make_toggl_request")
    def test_get_current_time_entry_success(self, mock_make_request):
        # Mock API response
        mock_response = {
            "id": 123,
            "workspace_id": TEST_WORKSPACE_ID,
            "project_id": TEST_PROJECT_ID,
            "start": datetime.now(timezone.utc).isoformat(),
            "duration": -1,  # Indicates running timer
            "description": "Working on tests",
            "tags": [TEST_TAG_NAME],
            "billable": True,
        }
        mock_make_request.return_value = mock_response

        # Test function
        result = exporter.get_current_time_entry()

        # Verify results
        mock_make_request.assert_called_once_with("/me/time_entries/current")
        assert result == mock_response

    @patch("prometheus_toggl_track_exporter.exporter._make_toggl_request")
    def test_get_current_time_entry_none_running(self, mock_make_request):
        # Mock API response (no entry running)
        mock_make_request.return_value = None

        # Test function
        result = exporter.get_current_time_entry()

        # Verify results
        mock_make_request.assert_called_once_with("/me/time_entries/current")
        assert result is None

    def test_get_auth_header_success(self):
        # Test with the patched token
        expected_creds = f"{TEST_API_TOKEN}:api_token"
        expected_encoded = base64.b64encode(expected_creds.encode()).decode("ascii")
        expected_header = {"Authorization": f"Basic {expected_encoded}"}

        header = exporter._get_auth_header()
        assert header == expected_header

    def test_get_auth_header_no_token(self):
        # Temporarily stop the patcher to simulate missing token
        self.api_token_patcher.stop()
        expected_error_msg = "TOGGL_API_TOKEN not set."
        with (
            patch("prometheus_toggl_track_exporter.exporter.TOGGL_API_TOKEN", None),
            pytest.raises(ValueError, match=expected_error_msg),
        ):
            exporter._get_auth_header()
        # Restart patcher if other tests in the same class need it
        self.api_token_patcher.start()

    @patch("prometheus_toggl_track_exporter.exporter.requests.request")
    def test_make_toggl_request_success(self, mock_request):
        # Mock requests.request response
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = {"data": "success"}
        mock_response.content = b'{"data": "success"}'  # Ensure content is present
        mock_request.return_value = mock_response

        # Test function
        result = exporter._make_toggl_request("/test/endpoint")

        # Verify results
        expected_url = f"{exporter.TOGGL_API_BASE_URL}/test/endpoint"
        mock_request.assert_called_once()
        call_args, call_kwargs = mock_request.call_args
        assert call_args[0] == "GET"  # Default method
        assert call_args[1] == expected_url
        assert "Authorization" in call_kwargs["headers"]
        assert result == {"data": "success"}
        # Check error metric was NOT incremented
        assert self.api_errors.labels(endpoint="test")._value.get() == 0

    @patch("prometheus_toggl_track_exporter.exporter.requests.request")
    def test_make_toggl_request_http_error(self, mock_request):
        # Mock requests.request response for HTTP error
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.NOT_FOUND
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_response.text = "Not Found"
        mock_request.return_value = mock_response

        # Test function
        result = exporter._make_toggl_request("/invalid/endpoint")

        # Verify results
        expected_url = f"{exporter.TOGGL_API_BASE_URL}/invalid/endpoint"
        mock_request.assert_called_once()
        call_args, call_kwargs = mock_request.call_args
        assert call_args[1] == expected_url
        assert result is None
        # Check error metric was incremented
        # The endpoint label is the first part of the path
        assert self.api_errors.labels(endpoint="invalid")._value.get() == 1

    @patch("prometheus_toggl_track_exporter.exporter.requests.request")
    def test_make_toggl_request_connection_error(self, mock_request):
        # Mock requests.request to raise ConnectionError
        mock_request.side_effect = requests.exceptions.ConnectionError("Cannot connect")

        # Test function
        result = exporter._make_toggl_request("/test/conn")

        # Verify results
        expected_url = f"{exporter.TOGGL_API_BASE_URL}/test/conn"
        mock_request.assert_called_once()
        call_args, call_kwargs = mock_request.call_args
        assert call_args[1] == expected_url
        assert result is None
        # Check error metric was incremented
        assert self.api_errors.labels(endpoint="test")._value.get() == 1

    @patch("prometheus_toggl_track_exporter.exporter._make_toggl_request")
    def test_collect_metrics_no_token(self, mock_make_request):
        # Stop the patcher to simulate missing token
        self.api_token_patcher.stop()
        with (
            patch("prometheus_toggl_track_exporter.exporter.TOGGL_API_TOKEN", None),
            patch("builtins.print") as mock_print,
        ):
            exporter.collect_metrics()
            # Verify _make_toggl_request was not called
            mock_make_request.assert_not_called()
            # Verify error was printed
            mock_print.assert_any_call(
                "Error: TOGGL_API_TOKEN environment variable not set."
            )
        # Restart patcher
        self.api_token_patcher.start()

    @patch("prometheus_toggl_track_exporter.exporter.get_me")
    @patch("prometheus_toggl_track_exporter.exporter.get_current_time_entry")
    @patch("prometheus_toggl_track_exporter.exporter.update_running_timer_metrics")
    @patch("prometheus_toggl_track_exporter.exporter.update_aggregate_metrics")
    @patch("prometheus_toggl_track_exporter.exporter.update_time_entries_metrics")
    def test_collect_metrics_success_flow(
        self,
        mock_update_time_entries,
        mock_update_aggregate,
        mock_update_running,
        mock_get_current,
        mock_get_me,
    ):
        # Mock return values
        mock_get_me.return_value = {"id": 1, "default_workspace_id": TEST_WORKSPACE_ID}
        mock_current_entry = {"id": 123, "workspace_id": TEST_WORKSPACE_ID}
        mock_get_current.return_value = mock_current_entry

        # Run collection
        exporter.collect_metrics()

        # Verify functions were called
        mock_get_me.assert_called_once()
        mock_get_current.assert_called_once()
        mock_update_running.assert_called_once_with(mock_current_entry)
        mock_update_aggregate.assert_called_once_with(TEST_WORKSPACE_ID)
        # Check that update_time_entries_metrics was called for each lookback hour
        expected_calls = [
            unittest.mock.call(TEST_WORKSPACE_ID, hour)
            for hour in exporter.TIME_ENTRIES_LOOKBACK_HOURS_LIST
        ]
        mock_update_time_entries.assert_has_calls(expected_calls, any_order=True)
        assert mock_update_time_entries.call_count == len(expected_calls)

        # Verify scrape duration was measured (value > 0)
        assert exporter.TOGGL_SCRAPE_DURATION.collect()[0].samples[0].value > 0

    @patch("prometheus_toggl_track_exporter.exporter.get_me")
    @patch("prometheus_toggl_track_exporter.exporter.get_current_time_entry")
    @patch("prometheus_toggl_track_exporter.exporter.update_running_timer_metrics")
    @patch("prometheus_toggl_track_exporter.exporter.update_aggregate_metrics")
    @patch("prometheus_toggl_track_exporter.exporter.update_time_entries_metrics")
    @patch("prometheus_toggl_track_exporter.exporter.TOGGL_PROJECTS_TOTAL")
    @patch("prometheus_toggl_track_exporter.exporter.TOGGL_CLIENTS_TOTAL")
    @patch("prometheus_toggl_track_exporter.exporter.TOGGL_TAGS_TOTAL")
    @patch(
        "prometheus_toggl_track_exporter.exporter.TOGGL_TIME_ENTRIES_DURATION_SECONDS"
    )
    @patch("prometheus_toggl_track_exporter.exporter.TOGGL_TIME_ENTRIES_COUNT")
    @patch(
        "prometheus_toggl_track_exporter.exporter.TOGGL_TIME_ENTRIES_AVG_DURATION_SECONDS"
    )
    @patch("prometheus_toggl_track_exporter.exporter.TOGGL_TIME_ENTRIES_BILLABLE_RATIO")
    @patch(
        "prometheus_toggl_track_exporter.exporter.TOGGL_DAYS_WITH_TIME_ENTRIES_COUNT"
    )
    @patch(
        "prometheus_toggl_track_exporter.exporter.TOGGL_TIME_ENTRIES_UNTAGGED_DURATION_SECONDS"
    )
    @patch("prometheus_toggl_track_exporter.exporter.TOGGL_TIME_ENTRIES_UNTAGGED_COUNT")
    def test_collect_metrics_no_workspace_id(  # noqa: PLR0913
        self,
        mock_untagged_count,
        mock_untagged_duration,
        mock_distinct_days,
        mock_billable_ratio,
        mock_avg_duration,
        mock_time_count,
        mock_time_duration,
        mock_tags_total,
        mock_clients_total,
        mock_projects_total,
        mock_update_time_entries,
        mock_update_aggregate,
        mock_update_running,
        mock_get_current,
        mock_get_me,
    ):
        # Mock return values
        mock_get_me.return_value = {
            "some_other_data": "value"
        }  # No default_workspace_id
        mock_current_entry = {"id": 123}  # Assume running entry exists
        mock_get_current.return_value = mock_current_entry

        # Run collection
        exporter.collect_metrics()

        # Verify functions were called correctly
        mock_get_me.assert_called_once()
        mock_get_current.assert_called_once()
        mock_update_running.assert_called_once_with(mock_current_entry)
        # Verify aggregate/time entry updates were NOT called
        mock_update_aggregate.assert_not_called()
        mock_update_time_entries.assert_not_called()

        # Verify metrics were cleared
        mock_projects_total.clear.assert_called_once()
        mock_clients_total.clear.assert_called_once()
        mock_tags_total.clear.assert_called_once()
        mock_time_duration.clear.assert_called_once()
        mock_time_count.clear.assert_called_once()
        mock_avg_duration.clear.assert_called_once()
        mock_billable_ratio.clear.assert_called_once()
        mock_distinct_days.clear.assert_called_once()
        mock_untagged_duration.clear.assert_called_once()
        mock_untagged_count.clear.assert_called_once()

    def test_update_running_timer_metrics_running(self):
        """Test updating metrics when a timer is running."""
        start_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        entry = {
            "id": 999,
            "workspace_id": TEST_WORKSPACE_ID,
            "project_id": TEST_PROJECT_ID,
            "project_name": TEST_PROJECT_NAME,
            "task_id": TEST_TASK_ID,
            "task_name": TEST_TASK_NAME,
            "start": start_time.isoformat(),
            "duration": -1234,  # Negative duration indicates running
            "description": "Testing running timer",
            "tags": ["billing", TEST_TAG_NAME],  # Unsorted tags
            "billable": True,
        }

        exporter.update_running_timer_metrics(entry)

        expected_labels = {
            "workspace_id": str(TEST_WORKSPACE_ID),
            "project_id": str(TEST_PROJECT_ID),
            "project_name": TEST_PROJECT_NAME,
            "task_id": str(TEST_TASK_ID),
            "task_name": TEST_TASK_NAME,
            "description": "Testing running timer",
            "tags": f"billing,{TEST_TAG_NAME}",  # Tags should be sorted
            "billable": "True",
        }

        # Check running gauge
        running_value = self.time_entry_running.labels(**expected_labels)._value.get()
        assert running_value == 1

        # Check timestamp gauge
        timestamp_value = self.time_entry_start_timestamp.labels(
            **expected_labels
        )._value.get()
        assert round(timestamp_value) == round(start_time.timestamp())

    def test_update_running_timer_metrics_none_running(self):
        """Test updating metrics when no timer is running."""
        # First, set a metric to simulate a previously running timer
        start_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        old_labels = {
            "workspace_id": str(TEST_WORKSPACE_ID),
            "project_id": "old_project",
            "project_name": "Old Project",
            "task_id": "old_task",
            "task_name": "Old Task",
            "description": "Old timer",
            "tags": "old_tag",
            "billable": "False",
        }
        self.time_entry_running.labels(**old_labels).set(1)
        self.time_entry_start_timestamp.labels(**old_labels).set(start_time.timestamp())

        # Now, call the update function with None (no timer running)
        exporter.update_running_timer_metrics(None)

        # Verify the old metric is *not* actively set to 0 by our function.
        # Prometheus handles staleness. We check the value remains.
        running_value = self.time_entry_running.labels(**old_labels)._value.get()
        assert running_value == 1
        timestamp_value = self.time_entry_start_timestamp.labels(
            **old_labels
        )._value.get()
        assert round(timestamp_value) == round(start_time.timestamp())

        # Ensure no *new* metrics were set (e.g., with default labels).
        # Testing this directly is hard; the main check is that the function doesn't
        # crash and doesn't incorrectly clear metrics.

    @patch("prometheus_toggl_track_exporter.exporter.get_projects")
    @patch("prometheus_toggl_track_exporter.exporter.get_clients")
    @patch("prometheus_toggl_track_exporter.exporter.get_tags")
    def test_update_aggregate_metrics_success(
        self, mock_get_tags, mock_get_clients, mock_get_projects
    ):
        """Test updating aggregate metrics successfully."""
        # Define expected counts
        expected_project_count = 2
        expected_client_count = 1
        expected_tag_count = 3

        # Mock API responses
        mock_get_projects.return_value = [
            {"id": 1, "name": "P1"},
            {"id": 2, "name": "P2"},
        ]
        mock_get_clients.return_value = [{"id": 10, "name": "C1"}]
        mock_get_tags.return_value = [
            {"id": 100, "name": "T1"},
            {"id": 101, "name": "T2"},
            {"id": 102, "name": "T3"},
        ]

        # Run the function
        exporter.update_aggregate_metrics(TEST_WORKSPACE_ID)

        # Verify calls
        mock_get_projects.assert_called_once_with(TEST_WORKSPACE_ID)
        mock_get_clients.assert_called_once_with(TEST_WORKSPACE_ID)
        mock_get_tags.assert_called_once_with(TEST_WORKSPACE_ID)

        # Verify metrics
        ws_label = str(TEST_WORKSPACE_ID)
        assert (
            self.projects_total.labels(workspace_id=ws_label)._value.get()
            == expected_project_count
        )
        assert (
            self.clients_total.labels(workspace_id=ws_label)._value.get()
            == expected_client_count
        )
        assert (
            self.tags_total.labels(workspace_id=ws_label)._value.get()
            == expected_tag_count
        )

    @patch("prometheus_toggl_track_exporter.exporter.get_projects")
    @patch("prometheus_toggl_track_exporter.exporter.get_clients")
    @patch("prometheus_toggl_track_exporter.exporter.get_tags")
    def test_update_aggregate_metrics_api_errors(
        self, mock_get_tags, mock_get_clients, mock_get_projects
    ):
        """Test updating aggregate metrics when API calls fail."""
        # Define expected counts on error
        expected_count_on_error = 0
        # Mock API responses (returning None indicating failure)
        mock_get_projects.return_value = None
        mock_get_clients.return_value = None
        mock_get_tags.return_value = None

        # Run the function
        exporter.update_aggregate_metrics(TEST_WORKSPACE_ID)

        # Verify calls
        mock_get_projects.assert_called_once_with(TEST_WORKSPACE_ID)
        mock_get_clients.assert_called_once_with(TEST_WORKSPACE_ID)
        mock_get_tags.assert_called_once_with(TEST_WORKSPACE_ID)

        # Verify metrics are set to 0 on failure
        ws_label = str(TEST_WORKSPACE_ID)
        assert (
            self.projects_total.labels(workspace_id=ws_label)._value.get()
            == expected_count_on_error
        )
        assert (
            self.clients_total.labels(workspace_id=ws_label)._value.get()
            == expected_count_on_error
        )
        assert (
            self.tags_total.labels(workspace_id=ws_label)._value.get()
            == expected_count_on_error
        )

    @patch("prometheus_toggl_track_exporter.exporter.get_time_entries")
    @patch("prometheus_toggl_track_exporter.exporter.get_projects")
    @patch("prometheus_toggl_track_exporter.exporter.get_tasks")
    def test_update_time_entries_metrics_success(
        self, mock_get_tasks, mock_get_projects, mock_get_time_entries
    ):
        """Test updating time entry aggregate metrics successfully."""
        lookback_hours = 24
        timeframe_label = f"{lookback_hours}h"
        now = datetime.now(timezone.utc)
        start_iso = (now - timedelta(hours=lookback_hours)).isoformat(
            timespec="seconds"
        )
        end_iso = now.isoformat(timespec="seconds")

        # Define expected values
        entry1_duration = 3600  # 1 hour
        entry2_duration = 1800  # 0.5 hours
        entry3_duration = 7200  # 2 hours
        entry4_duration = 900  # 15 mins
        expected_agg_duration_1_2 = entry1_duration + entry2_duration
        expected_agg_count_1_2 = 2
        expected_agg_count_3 = 1
        expected_agg_count_4 = 1
        # Calculate performance metric expectations
        total_duration = (
            entry1_duration + entry2_duration + entry3_duration + entry4_duration
        )
        total_count = (
            expected_agg_count_1_2 + expected_agg_count_3 + expected_agg_count_4
        )
        billable_duration = entry1_duration + entry2_duration
        untagged_duration = entry4_duration
        untagged_count = expected_agg_count_4
        expected_avg_duration = total_duration / total_count if total_count else 0
        expected_billable_ratio = (
            billable_duration / total_duration if total_duration else 0
        )
        expected_distinct_days = 1  # All entries are within the same 'now' day

        # Mock project/task data
        mock_projects_data = [
            {"id": TEST_PROJECT_ID, "name": TEST_PROJECT_NAME},
            {"id": 55555, "name": "Project B"},
        ]
        mock_tasks_data = [{"id": TEST_TASK_ID, "name": TEST_TASK_NAME}]
        mock_get_projects.return_value = mock_projects_data
        mock_get_tasks.return_value = mock_tasks_data

        # Mock API response for time entries
        mock_entries = [
            # Entry 1: Project A, Task 1, Tag1, Billable
            {
                "id": 1001,
                "workspace_id": TEST_WORKSPACE_ID,
                "project_id": TEST_PROJECT_ID,
                "project_name": TEST_PROJECT_NAME,
                "task_id": TEST_TASK_ID,
                "task_name": TEST_TASK_NAME,
                "tags": [TEST_TAG_NAME],  # Single tag
                "billable": True,
                "duration": entry1_duration,
                "start": (now - timedelta(hours=2)).isoformat(),
                "stop": (now - timedelta(hours=1)).isoformat(),
            },
            # Entry 2: Project A, Task 1, Tag1, Billable (aggregation check)
            {
                "id": 1002,
                "workspace_id": TEST_WORKSPACE_ID,
                "project_id": TEST_PROJECT_ID,
                "project_name": TEST_PROJECT_NAME,
                "task_id": TEST_TASK_ID,
                "task_name": TEST_TASK_NAME,
                "tags": [TEST_TAG_NAME],
                "billable": True,
                "duration": entry2_duration,
                "start": (now - timedelta(hours=4)).isoformat(),
                "stop": (now - timedelta(hours=3.5)).isoformat(),
            },
            # Entry 3: Project B, No Task, Tag2, Non-billable
            {
                "id": 1003,
                "workspace_id": TEST_WORKSPACE_ID,
                "project_id": 55555,
                "project_name": "Project B",
                "task_id": None,
                "task_name": None,
                "tags": ["internal", "dev"],  # Multiple tags
                "billable": False,
                "duration": entry3_duration,
                "start": (now - timedelta(hours=6)).isoformat(),
                "stop": (now - timedelta(hours=4)).isoformat(),
            },
            # Entry 4: No Project, No Task, No Tags, Non-billable
            {
                "id": 1004,
                "workspace_id": TEST_WORKSPACE_ID,
                "project_id": None,
                "project_name": None,
                "task_id": None,
                "task_name": None,
                "tags": [],
                "billable": False,
                "duration": entry4_duration,
                "start": (now - timedelta(hours=8)).isoformat(),
                "stop": (now - timedelta(hours=7.75)).isoformat(),
            },
            # Entry 5: Running timer - should be ignored (duration <= 0)
            {
                "id": 1005,
                "workspace_id": TEST_WORKSPACE_ID,
                "project_id": TEST_PROJECT_ID,
                "duration": -12345,
            },
            # Entry 6: Zero duration timer - should be ignored
            {
                "id": 1006,
                "workspace_id": TEST_WORKSPACE_ID,
                "project_id": TEST_PROJECT_ID,
                "duration": 0,
            },
        ]
        mock_get_time_entries.return_value = mock_entries

        # Run the function
        exporter.update_time_entries_metrics(TEST_WORKSPACE_ID, lookback_hours)

        # Verify API calls
        mock_get_projects.assert_called_once_with(TEST_WORKSPACE_ID)
        mock_get_tasks.assert_called_once_with(TEST_WORKSPACE_ID)
        mock_get_time_entries.assert_called_once_with(
            start_date=start_iso, end_date=end_iso
        )

        # Verify metrics for Entry 1 & 2 (aggregated)
        labels1 = {
            "workspace_id": str(TEST_WORKSPACE_ID),
            "project_id": str(TEST_PROJECT_ID),
            "project_name": TEST_PROJECT_NAME,
            "task_id": str(TEST_TASK_ID),
            "task_name": TEST_TASK_NAME,
            "tags": TEST_TAG_NAME,
            "billable": "True",
            "timeframe": timeframe_label,
        }
        assert (
            self.time_entries_duration.labels(**labels1)._value.get()
            == expected_agg_duration_1_2
        )
        assert (
            self.time_entries_count.labels(**labels1)._value.get()
            == expected_agg_count_1_2
        )

        # Verify metrics for Entry 3
        labels3 = {
            "workspace_id": str(TEST_WORKSPACE_ID),
            "project_id": "55555",
            "project_name": "Project B",
            "task_id": "none",  # Handled None
            "task_name": "none",
            "tags": "dev,internal",  # Sorted tags
            "billable": "False",
            "timeframe": timeframe_label,
        }
        assert (
            self.time_entries_duration.labels(**labels3)._value.get() == entry3_duration
        )
        assert (
            self.time_entries_count.labels(**labels3)._value.get()
            == expected_agg_count_3
        )

        # Verify metrics for Entry 4
        labels4 = {
            "workspace_id": str(TEST_WORKSPACE_ID),
            "project_id": "none",
            "project_name": "none",
            "task_id": "none",
            "task_name": "none",
            "tags": "",  # Empty tags
            "billable": "False",
            "timeframe": timeframe_label,
        }
        assert (
            self.time_entries_duration.labels(**labels4)._value.get() == entry4_duration
        )
        assert (
            self.time_entries_count.labels(**labels4)._value.get()
            == expected_agg_count_4
        )

        # --- Verify Performance Metrics ---
        perf_labels = {
            "workspace_id": str(TEST_WORKSPACE_ID),
            "timeframe": timeframe_label,
        }
        assert (
            self.time_entries_avg_duration.labels(**perf_labels)._value.get()
            == expected_avg_duration
        )
        assert (
            self.time_entries_billable_ratio.labels(**perf_labels)._value.get()
            == expected_billable_ratio
        )
        assert (
            self.time_entries_distinct_days.labels(**perf_labels)._value.get()
            == expected_distinct_days
        )
        assert (
            self.time_entries_untagged_duration.labels(**perf_labels)._value.get()
            == untagged_duration
        )
        assert (
            self.time_entries_untagged_count.labels(**perf_labels)._value.get()
            == untagged_count
        )

    @patch("prometheus_toggl_track_exporter.exporter.get_time_entries")
    @patch("prometheus_toggl_track_exporter.exporter.get_projects")
    @patch("prometheus_toggl_track_exporter.exporter.get_tasks")
    def test_update_time_entries_metrics_api_error(
        self, mock_get_tasks, mock_get_projects, mock_get_time_entries
    ):
        """Test time entry metrics update when API call fails."""
        lookback_hours = 1
        expected_dummy_count = 5
        mock_get_time_entries.return_value = None  # Simulate API error
        mock_get_projects.return_value = []  # Need to mock these even if time entries fail  # noqa: E501
        mock_get_tasks.return_value = []

        # Set some dummy values first to ensure they aren't cleared (unless designed to)
        dummy_labels = {
            "workspace_id": "1",
            "project_id": "1",
            "project_name": "p",
            "task_id": "1",
            "task_name": "t",
            "tags": "",
            "billable": "False",
            "timeframe": f"{lookback_hours}h",
        }
        self.time_entries_count.labels(**dummy_labels).set(expected_dummy_count)

        # Run the function - it should NOT raise an exception when API returns None
        exporter.update_time_entries_metrics(TEST_WORKSPACE_ID, lookback_hours)

        # Verify API call was made
        assert mock_get_time_entries.called

        # Verify dummy metric was NOT cleared or reset (based on current logic)
        assert (
            self.time_entries_count.labels(**dummy_labels)._value.get()
            == expected_dummy_count
        )


# --- Remove old Todoist tests ---
# [ All test methods starting with `test_collect_...` from the original
#   Todoist exporter file are removed here. ]

# Keep the main execution block
if __name__ == "__main__":
    unittest.main()
