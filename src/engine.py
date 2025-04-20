from scheduler import make_scheduler, SchedulerOutput, SchedulerType
import asyncio
import json
import logging
import multiprocessing as mp
from typing import Dict, List, Set, Any, Optional, Tuple
from dataclasses import dataclass
from worker_client import WorkerClient, make_client
import signal
import queue
from worker import BrowserWorkerTask
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

@dataclass
class BrowserEngineConfig:
    worker_client_config: Dict[str, Any]
    scheduler_config: Optional[Dict[str, Any]] = None

class BrowserEngine:
    """Browser engine that manages multiple browser workers in separate processes"""

    def __init__(self, config: BrowserEngineConfig):
        """Initialize the browser engine with the specified configuration"""
        self.config = config
        self.scheduler = make_scheduler(self.config.scheduler_config)
        self.worker_client: WorkerClient = make_client(self.config.worker_client_config)
        self._running = False

        self.waiting_queue = queue.Queue()
        self.task_tracker = {}
        self.context_tracker = {}

        self.output_dict = {}
        self.batch_size = self.config.scheduler_config["max_batch_size"]
        self.n_workers = self.config.worker_client_config["num_workers"]

    def _check_command_validity(self, task: BrowserWorkerTask):
        """
        Check if command is valid.
        """
        if task.command in ["create_context"]:
            if task.context_id:
                raise ValueError(f"Context ID {task.context_id} is not allowed for create_context command")
        elif task.command in ["close_context"]:
            if not task.context_id:
                raise ValueError("Context ID is required for close_context command")
            
        pass
    
    def _check_task_validity(self, task: BrowserWorkerTask):
        """
        Check if the task is valid.
        """
        self._check_command_validity(task)
        pass


    def add_task(self, task: BrowserWorkerTask):
        """
        Add a task to the waiting queue
        """

        # self._check_task_validity(task)

        self.waiting_queue.put(task)

        # check if context_id in context_tracker (key is context_id, value is the worker_id)
        if not task.context_id:
            self.context_tracker[task.context_id] = -1
        else:
            if task.context_id not in self.context_tracker:
                raise ValueError(f"Context ID {task.context_id} not found in context_tracker. New context worker mapping should be created by scheduler.")  

        # Add engine recv timestamp
        task.engine_recv_timestamp = time.time()



    def add_batch_tasks(self, tasks: List[BrowserWorkerTask]):
        """
        Add a batch of tasks to the waiting queue
        """
        for task in tasks:
            self.add_task(task)
        return
        
    def _shutdown(self):
        self._running = False
        self.worker_client.close()

    def engine_core_loop(self):
        self._running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        try:

            while self._running:
                tasks = []
                prev_workers = []
                while not self.waiting_queue.empty() and len(tasks) < self.batch_size:
                    task = self.waiting_queue.get()
                    tasks.append(task)
                    prev_workers.append(self.context_id_to_worker_id_map[task.context_id])

                if not tasks:
                    self._process_output_and_update_tracker()
                    continue

                worker_status = self.worker_client.get_worker_status_no_wait()

                scheduled_tasks, scheduler_output = self.scheduler.schedule(tasks, prev_workers, self.n_workers, worker_status)

                self._execute_scheduler_output(scheduled_tasks, scheduler_output)

                self._update_task_tracker_with_scheduler_output(scheduled_tasks, scheduler_output)

                self._process_output_and_update_tracker()

        except Exception as e:
            logger.error(f"Exception in engine core loop: {e}")
        finally:
            self._shutdown()
    
    def _update_task_tracker_with_scheduler_output(self, tasks, scheduler_output: SchedulerOutput):

        for task in tasks:
            self.task_tracker[task.task_id] = {"worker_id": scheduler_output.task_assignments[task.task_id], "task": task, "status": "pending"}
        return

        # for task_id, worker_id in scheduler_output.task_assignments.items():
        #     self.task_tracker[task_id] = worker_id
    
    def _execute_scheduler_output(self, tasks, scheduler_output: SchedulerOutput):
        """
        Allocate tasks to workers.
        """
        for task in tasks:
            worker_id = scheduler_output.task_assignments[task.task_id]
            task.engine_send_timestamp = time.time()
            self.worker_client.send_task(task, worker_id)

        return

    def _process_output_and_update_tracker(self):
        output_queue_len = self.worker_client.get_output_queue_len()
        if output_queue_len == 0:
            return
        
        for _ in range(output_queue_len):
            idx, msg = self.worker_client.get_output_nowait()
            assert "task_id" in msg
            task_id = msg["task_id"]
            assert task_id not in self.output_dict
            self.output_dict[task_id] = msg
            self.context_tracker[msg["context_id"]] = idx
            self.task_tracker[task_id]["status"] = "finished"

        return

    def engine_core_loop_old(self):
        self._running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        try:

            while self._running:
                tasks = []
                while not self.waiting_queue.empty():
                    tasks.append(self.waiting_queue.get())
                
                if not tasks:
                    self._process_output_and_update_tracker()
                    continue

                worker_status = self.worker_client.get_worker_status()

                scheduler_output = self.scheduler.schedule(tasks, self.task_tracker, worker_status)
                self._execute_scheduler_output(scheduler_output)

                self._update_task_tracker_with_scheduler_output(scheduler_output)

                self._process_output_and_update_tracker()

        except Exception as e:
            logger.error(f"Exception in engine core loop: {e}")
        finally:
            self._shutdown()


if __name__ == "__main__":
    config = {
        "worker_client_config": {"input_path": "ipc://input_sync", "output_path": "ipc://output_sync", "num_workers": 3},
        "scheduler_config": {"type": SchedulerType.ROUND_ROBIN, "max_batch_size": 5, "n_workers": 3}
    }
    scheduler = make_scheduler(config["scheduler_config"])
    engine = BrowserEngine(BrowserEngineConfig(**config))
    engine.engine_core_loop()
