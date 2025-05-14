import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator
from browser_pilot.type.error_type import ErrorInfo


class WorkerTask(BaseModel):
    """
    Task for browser worker execution
    task_id and command are required fields
    all other fields are optional or will be set by the engine or worker
    """

    task_id: str
    env_id: Optional[str] = Field(default=None)
    method: str
    params: Optional[Dict[str, Any]] = Field(default=None)

    engine_recv_timestamp: Optional[float] = Field(default=None)
    engine_send_timestamp: Optional[float] = Field(default=None)
    worker_recv_timestamp: Optional[float] = Field(default=None)
    worker_start_process_timestamp: Optional[float] = Field(default=None)
    worker_finish_process_timestamp: Optional[float] = Field(default=None)
    worker_send_timestamp: Optional[float] = Field(default=None)

    def to_dict(self):
        return self.__dict__


class WorkerOutput(BaseModel):
    task_id: str
    success: bool
    result: Optional[Any] = Field(default=None)
    error_info: Optional[Dict[Any, Any]] = Field(default=None)
    profile: Optional[Dict[str, Any]] = Field(default=None)

    def to_dict(self):
        return self.model_dump(mode="json", exclude_none=True)


if __name__ == "__main__":
    task = WorkerTask(
        task_id="task_1",
        method="create_context",
        params={"url": "https://www.example.com"},
    )
    print(task)
