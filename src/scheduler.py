import logging
from typing import Dict, List, Optional, Any
from worker import BrowserWorkerTask
from type.scheduler_type import SchedulerType, SchedulerOutput

"""
Define the output of the scheduler
scheduler_output = {
    "task_id_001": "worker_alpha",
    "task_id_002": "worker_beta",
    "task_id_003": "worker_alpha",
    "task_id_004": "worker_gamma",
    # ... mapping for all n input tasks
}
"""

logger = logging.getLogger(__name__)


def make_scheduler(scheduler_config):
    assert scheduler_config["type"] == SchedulerType.ROUND_ROBIN
    return RoundRobinScheduler(
        batch_size=scheduler_config["max_batch_size"],
        n_workers=scheduler_config["n_workers"],
    )


class RoundRobinScheduler:
    def __init__(self, batch_size: int, n_workers: int):
        """
        Initialize the round-robin scheduler
        """
        self.scheduler_type = SchedulerType.ROUND_ROBIN
        self.batch_size = batch_size
        self.n_workers = n_workers

        def _iterator(n_workers: int):
            worker_id = 0
            while True:
                yield worker_id
                worker_id = (worker_id + 1) % n_workers

        self.iterator = _iterator(n_workers)

    def schedule(
        self,
        all_tasks: List[BrowserWorkerTask],
        last_assigned_worker: List[str],
        n_workers: int,
        worker_status: Optional[List[Dict[str, Any]]] = None,
    ) -> SchedulerOutput:
        """
        Assign tasks to workers in a round-robin manner
        """
        assert len(all_tasks) == len(last_assigned_worker)
        assert worker_status is None or len(worker_status) == n_workers

        schedule_output = SchedulerOutput()
        for i in range(len(all_tasks)):
            task_id = all_tasks[i].task_id
            worker_id = last_assigned_worker[i]
            if last_assigned_worker[i] == -1:
                worker_id = next(self.iterator)
            else:
                worker_id = last_assigned_worker[i]
            schedule_output.task_assignments[task_id] = worker_id

        return all_tasks, schedule_output


# Test the round-robin scheduler
if __name__ == "__main__":
    #     # Create a sample scheduler output with multiple assignments
    #     scheduler_output = SchedulerOutput.from_dict({"task_1": "worker_1", "task_2": "worker_2", "task_3": "worker_3"})

    #     print(scheduler_output)
    #     # Convert the dataclass instance to a dictionary using asdict
    #     scheduler_output_dict = asdict(scheduler_output)
    #     print(scheduler_output_dict)

    #     scheduler = RoundRobinScheduler(batch_size=5, n_workers=3)
    #     tasks = ["task_1", "task_2", "task_3", "task_4", "task_5", "task_6"]
    #     last_assigned_worker = [-1, -1, 2, 2, -1, 1]
    #     n_workers = 3
    #     worker_status = [{"task_id": None, "status": "idle"} for _ in range(n_workers)]
    #     all_tasks, schedule_output = scheduler.schedule(tasks, last_assigned_worker, n_workers, worker_status)
    #     print("all_tasks", all_tasks)
    #     print("schedule_output", schedule_output)

    scheduler = RoundRobinScheduler(batch_size=5, n_workers=3)

    # Create test tasks
    tasks = [
        BrowserWorkerTask(task_id=f"task_{i}", command="test_command") for i in range(5)
    ]

    # Test with all new tasks (no previous worker assignments)
    last_assigned_workers = [-1] * len(tasks)
    worker_status = [{"status": "idle"} for _ in range(3)]
    print("tasks", tasks)
    scheduled_tasks, output = scheduler.schedule(
        tasks, last_assigned_workers, 3, worker_status  # n_workers
    )

    # Verify output structure
    assert isinstance(output, SchedulerOutput)
    assert len(output.task_assignments) == len(tasks)

    # Verify round-robin assignment
    expected_assignments = {
        "task_0": 0,
        "task_1": 1,
        "task_2": 2,
        "task_3": 0,
        "task_4": 1,
    }
    # print("output.task_assignments", output.task_assignments)
    assert output.task_assignments == expected_assignments
