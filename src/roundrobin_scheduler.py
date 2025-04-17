#!/usr/bin/env python3
"""
Scheduler Module

This module implements task scheduling strategies for distributing tasks 
across multiple browser workers.
"""

import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Union
from schedular_output import ScheduleOutput
logger = logging.getLogger(__name__)

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

    def schedule(self, all_tasks: List[Dict[str, Any]], last_assigned_worker: List[str], n_workers: int, worker_status: Optional[List[Dict[str, Any]]] = None) -> ScheduleOutput:
        """
        Assign tasks to workers in a round-robin manner
        """
        assert len(all_tasks) == len(last_assigned_worker)
        assert worker_status is None or len(worker_status) == n_workers

        schedule_output = ScheduleOutput()
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
    scheduler = RoundRobinScheduler(n_workers=3)
    tasks = ["task_1", "task_2", "task_3", "task_4", "task_5", "task_6"]
    last_assigned_worker = [-1, -1, 2, 2, -1, 1]
    n_workers = 3
    worker_status = [{"task_id": None, "status": "idle"} for _ in range(n_workers)]
    schedule_output = scheduler.schedule(tasks, last_assigned_worker, n_workers, worker_status)
    print(schedule_output)
