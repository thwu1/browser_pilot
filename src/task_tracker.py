import time
from collections import defaultdict
from typing import Dict


class TaskTracker:
    """Track Playwright task statuses"""

    def __init__(self):
        # Only keep active tasks
        self.pending_tasks = {}  # (connection_id, task_id) -> timestamp
        self.endpoint_map = (
            {}
        )  # (connection_id, task_id) -> endpoint for pending tasks only
        self.all_task_ids = {}  # connection_id -> set of task IDs

        # Online statistics per endpoint
        self.endpoint_stats = defaultdict(
            lambda: {
                "total_completed": 0,
                "total_failed": 0,
                "total_duration": 0.0,
                "num_pending": 0,
            }
        )

        self.data_messages = 0  # Count of non-task messages

    def register_task(self, connection_id: str, task_id: str, endpoint: str):
        """Register a new task being sent to target"""
        if connection_id not in self.all_task_ids:
            self.all_task_ids[connection_id] = set()

        if task_id in self.all_task_ids[connection_id]:
            raise ValueError(
                f"Task ID {task_id} has already been registered for connection {connection_id}"
            )

        task_key = (connection_id, task_id)
        self.pending_tasks[task_key] = time.time()
        self.endpoint_map[task_key] = endpoint
        self.endpoint_stats[endpoint]["num_pending"] += 1
        self.all_task_ids[connection_id].add(task_id)

    def complete_task(self, connection_id: str, task_id: str, success: bool):
        """Mark a task as completed and clean up"""
        task_key = (connection_id, task_id)
        if task_key in self.pending_tasks:
            start_time = self.pending_tasks.pop(task_key)
            duration = time.time() - start_time

            endpoint = self.endpoint_map.pop(task_key)
            stats = self.endpoint_stats[endpoint]
            stats["num_pending"] -= 1

            if success:
                stats["total_completed"] += 1
                stats["total_duration"] += duration
            else:
                stats["total_failed"] += 1

    def register_data_message(self):
        """Register a non-task message"""
        self.data_messages += 1

    def get_status(self) -> Dict:
        """Get current task status grouped by endpoint"""
        endpoint_stats = {}
        # Include all endpoints that have any statistics
        for endpoint, stats in self.endpoint_stats.items():
            if (
                stats["total_completed"] > 0
                or stats["total_failed"] > 0
                or stats["num_pending"] > 0
            ):
                avg_time = (
                    stats["total_duration"] / stats["total_completed"]
                    if stats["total_completed"] > 0
                    else 0
                )

                endpoint_stats[endpoint] = {
                    "pending_tasks": stats["num_pending"],
                    "total_completed": stats["total_completed"],
                    "total_failed": stats["total_failed"],
                    "average_completion_time": avg_time,
                    "total_tasks_historical": stats["total_completed"]
                    + stats["total_failed"],
                }

        return endpoint_stats

    def cleanup_connection(self, connection_id: str):
        """Clean up all tasks for a connection when it closes"""
        if connection_id in self.all_task_ids:
            # Clean up task tracking
            del self.all_task_ids[connection_id]

            # Clean up any pending tasks for this connection
            keys_to_remove = [
                (conn_id, task_id)
                for (conn_id, task_id) in self.pending_tasks.keys()
                if conn_id == connection_id
            ]
            for key in keys_to_remove:
                if key in self.pending_tasks:
                    del self.pending_tasks[key]
                if key in self.endpoint_map:
                    endpoint = self.endpoint_map[key]
                    self.endpoint_stats[endpoint]["num_pending"] -= 1
                    del self.endpoint_map[key]


def test_task_tracker():
    """Test TaskTracker functionality"""
    tracker = TaskTracker()

    # Test task registration
    tracker.register_task("conn1", "task1", "endpoint1")
    tracker.register_task("conn1", "task2", "endpoint1")
    tracker.register_task("conn1", "task3", "endpoint2")

    # Verify initial state
    status = tracker.get_status()
    assert "endpoint1" in status
    assert "endpoint2" in status
    assert status["endpoint1"]["pending_tasks"] == 2
    assert status["endpoint2"]["pending_tasks"] == 1
    assert status["endpoint1"]["total_completed"] == 0
    assert status["endpoint2"]["total_completed"] == 0

    # Test task completion
    time.sleep(0.1)  # Ensure measurable duration
    tracker.complete_task("conn1", "task1", True)

    # Verify after completion
    status = tracker.get_status()
    assert status["endpoint1"]["pending_tasks"] == 1
    assert status["endpoint1"]["total_completed"] == 1
    assert status["endpoint1"]["total_failed"] == 0
    assert status["endpoint1"]["average_completion_time"] > 0

    # Test failed task
    tracker.complete_task("conn1", "task2", False)
    status = tracker.get_status()
    assert status["endpoint1"]["pending_tasks"] == 0
    assert status["endpoint1"]["total_failed"] == 1

    # Test multiple endpoints
    tracker.register_task("conn1", "task4", "endpoint2")
    status = tracker.get_status()
    assert status["endpoint2"]["pending_tasks"] == 2

    # Test completion of all tasks for an endpoint
    tracker.complete_task("conn1", "task3", True)
    tracker.complete_task("conn1", "task4", True)
    status = tracker.get_status()
    assert status["endpoint2"]["pending_tasks"] == 0
    assert status["endpoint2"]["total_completed"] == 2

    print("All tests passed!")


def test_edge_cases():
    """Test edge cases and error conditions"""
    tracker = TaskTracker()

    # Test completing non-existent task
    tracker.complete_task("conn1", "nonexistent", True)  # Should not raise error

    # Test multiple tasks same endpoint
    for i in range(100):
        tracker.register_task("conn1", f"task{i}", "endpoint1")
    assert tracker.get_status()["endpoint1"]["pending_tasks"] == 100

    # Complete all tasks
    for i in range(100):
        tracker.complete_task("conn1", f"task{i}", True)
    status = tracker.get_status()
    assert status["endpoint1"]["pending_tasks"] == 0
    assert status["endpoint1"]["total_completed"] == 100

    # Test duplicate task ID
    tracker.register_task("conn1", "duplicate_task", "endpoint1")
    try:
        tracker.register_task("conn1", "duplicate_task", "endpoint2")
        assert False, "Should have raised ValueError for duplicate task ID"
    except ValueError:
        pass  # Expected behavior

    # Test data messages
    tracker.register_data_message()
    assert tracker.data_messages == 1

    print("All edge case tests passed!")


if __name__ == "__main__":
    test_task_tracker()
    test_edge_cases()
