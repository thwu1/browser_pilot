from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Union
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Union

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
    assert scheduler_config.get("type") == SchedulerType.ROUND_ROBIN
    return RoundRobinScheduler(n_workers=scheduler_config.get("n_workers"))

@dataclass
class SchedulerOutput:
    """
    Represents the output of the scheduler, mapping task IDs to assigned worker IDs.
    """
    # Use field to initialize with an empty dict if no assignments are provided
    task_assignments: Dict[str, str] = field(default_factory=dict) 
    # Optional field for any extra metadata you might want to include
    metadata: Union[Dict[str, Any], None] = None 

def create_scheduler_output(task_id: str, worker_id: str) -> SchedulerOutput:
    return SchedulerOutput(task_assignments={task_id: worker_id})

def create_scheduler_output_from_dict(data: Dict[str, str]) -> SchedulerOutput:
    return SchedulerOutput(task_assignments=data)

class SchedulerType(Enum):
    """Types of scheduling strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CONTEXT_AFFINITY = "context_affinity"


class RoundRobinScheduler:
    def __init__(self, n_workers: int):
        """
        Initialize the round-robin scheduler
        """
        self.scheduler_type = SchedulerType.ROUND_ROBIN
        self.n_workers = n_workers

        def _iterator(n_workers: int):
            worker_id = 0
            while True:
                yield worker_id
                worker_id = (worker_id + 1) % n_workers

        self.iterator = _iterator(n_workers)

    def schedule(self, all_tasks: List[Dict[str, Any]], last_assigned_worker: List[str], n_workers: int, worker_status: Optional[List[Dict[str, Any]]] = None) -> SchedulerOutput:
        """
        Assign tasks to workers in a round-robin manner
        """
        assert len(all_tasks) == len(last_assigned_worker)
        assert worker_status is None or len(worker_status) == n_workers

        schedule_output = SchedulerOutput()
        for i in range(len(all_tasks)):
            task_id = all_tasks[i]
            worker_id = last_assigned_worker[i]
            if last_assigned_worker[i] == -1:
                worker_id = next(self.iterator)    
            else:
                worker_id = last_assigned_worker[i]
            schedule_output.task_assignments[task_id] = worker_id
        return schedule_output
    
# Test the round-robin scheduler
if __name__ == "__main__":
    # Create a sample scheduler output with multiple assignments
    scheduler_output = create_scheduler_output("task_1", "worker_1")
    scheduler_output.task_assignments["task_2"] = "worker_2"
    scheduler_output.task_assignments["task_3"] = "worker_3"
    
    print(scheduler_output)
    # Convert the dataclass instance to a dictionary using asdict
    scheduler_output_dict = asdict(scheduler_output)
    print(scheduler_output_dict)

    scheduler = RoundRobinScheduler(n_workers=3)
    tasks = ["task_1", "task_2", "task_3", "task_4", "task_5", "task_6"]
    last_assigned_worker = [-1, -1, 2, 2, -1, 1]
    n_workers = 3
    worker_status = [{"task_id": None, "status": "idle"} for _ in range(n_workers)]
    schedule_output = scheduler.schedule(tasks, last_assigned_worker, n_workers, worker_status)
    print(schedule_output)
