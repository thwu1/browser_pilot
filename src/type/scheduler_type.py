from typing import Dict, Any, Union
from pydantic import BaseModel, Field
from enum import Enum

class SchedulerType(Enum):
    """Types of scheduling strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CONTEXT_AFFINITY = "context_affinity"



class SchedulerOutput(BaseModel):
    """
    Represents the output of the scheduler, mapping task IDs to assigned worker IDs.
    """
    # Use field to initialize with an empty dict if no assignments are provided
    task_assignments: Dict[str, int] = Field(default_factory=dict) 
    # Optional field for any extra metadata you might want to include
    metadata: Union[Dict[str, Any], None] = None 

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> "SchedulerOutput":
        return cls(task_assignments=data)
