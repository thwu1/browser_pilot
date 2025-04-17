from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Union
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
@dataclass
class ScheduleOutput:
    """
    Represents the output of the scheduler, mapping task IDs to assigned worker IDs.
    """
    # Use field to initialize with an empty dict if no assignments are provided
    task_assignments: Dict[str, str] = field(default_factory=dict) 
    # Optional field for any extra metadata you might want to include
    metadata: Union[Dict[str, Any], None] = None 

def create_scheduler_output(task_id: str, worker_id: str) -> ScheduleOutput:
    return ScheduleOutput(task_assignments={task_id: worker_id})

def create_scheduler_output_from_dict(data: Dict[str, str]) -> ScheduleOutput:
    return ScheduleOutput(task_assignments=data)

# Test the scheduler output
if __name__ == "__main__":
    # Create a sample scheduler output with multiple assignments
    scheduler_output = create_scheduler_output("task_1", "worker_1")
    scheduler_output.task_assignments["task_2"] = "worker_2"
    scheduler_output.task_assignments["task_3"] = "worker_3"
    
    print(scheduler_output)
    # Convert the dataclass instance to a dictionary using asdict
    scheduler_output_dict = asdict(scheduler_output)
    print(scheduler_output_dict)
    