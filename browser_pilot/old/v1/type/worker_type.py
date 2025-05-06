from typing import Optional

from pydantic import BaseModel, Field


class WorkerStatus(BaseModel):
    """Status information for a browser worker

    Contains metrics and state information about the worker, including task counts,
    resource usage, and performance metrics. Use EMA continuous metrics.
    """

    index: int  # Worker index/ID
    running: bool  # Whether the worker is running
    num_contexts: int  # Number of browser contexts
    num_pages: int  # Total number of pages across all contexts
    error_rate: float  # Rate of task errors
    last_activity: float  # Timestamp of last activity
    last_heartbeat: float  # Timestamp of last heartbeat
    num_running_tasks: int  # Number of tasks currently being executed
    num_waiting_tasks: int  # Number of tasks waiting in the queue
    num_finished_tasks: int  # Total number of tasks completed
    avg_latency_ms: float  # Average task execution latency in milliseconds
    throughput_per_sec: float  # Tasks completed per second
    cpu_usage_percent: Optional[float] = Field(default=None)  # CPU usage percentage
    memory_usage_mb: Optional[float] = Field(default=None)  # Memory usage in MB

    def to_dict(self):
        """Convert the status to a dictionary"""
        return self.__dict__
