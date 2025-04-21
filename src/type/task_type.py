import time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator


class BrowserWorkerTask(BaseModel):
    """
    Task for browser worker execution
    task_id and command are required fields
    all other fields are optional or will be set by the engine or worker
    """

    task_id: str
    context_id: Optional[str] = Field(default=None)
    page_id: Optional[str] = Field(default=None)
    command: str
    params: Optional[Dict[str, Any]] = Field(default=None)

    engine_recv_timestamp: Optional[float] = Field(default=None)
    engine_send_timestamp: Optional[float] = Field(default=None)
    worker_recv_timestamp: Optional[float] = Field(default=None)
    worker_start_process_timestamp: Optional[float] = Field(default=None)
    worker_finish_process_timestamp: Optional[float] = Field(default=None)
    worker_send_timestamp: Optional[float] = Field(default=None)

    def to_dict(self):
        return self.__dict__


if __name__ == "__main__":

    task = BrowserWorkerTask(
        task_id="task_1",
        command="create_context",
        params={"url": "https://www.example.com"},
    )
    print(task)
