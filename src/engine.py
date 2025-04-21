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
import uuid
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
        logger.info(f"added task {task.task_id} to waiting queue")

        if not task.context_id:
            context_id = f"{uuid.uuid4().hex[:8]}"
            task.context_id = context_id
            self.context_tracker[context_id] = -1
        else:
            if task.context_id not in self.context_tracker:
                self.context_tracker[task.context_id] = -1

        # # check if context_id in context_tracker (key is context_id, value is the worker_id)
        # if not task.context_id:
        #     self.context_tracker[task.context_id] = -1
        # else:
        #     if task.context_id not in self.context_tracker:
        #         raise ValueError(f"Context ID {task.context_id} not found in context_tracker. New context worker mapping should be created by scheduler.")  

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
        """Main engine loop that processes tasks and manages workers"""
        self._running = True

        try:
            while self._running:
                tasks = []
                prev_workers = []
                while not self.waiting_queue.empty() and len(tasks) < self.batch_size:
                    task = self.waiting_queue.get()
                    tasks.append(task)
                    prev_workers.append(self.context_tracker[task.context_id])

                if not tasks:
                    self._process_output_and_update_tracker()
                    time.sleep(0.1)  # Small sleep to prevent busy waiting
                    continue

                worker_status = self.worker_client.get_worker_status_no_wait()

                scheduled_tasks, scheduler_output = self.scheduler.schedule(tasks, prev_workers, self.n_workers, worker_status)
                logger.info(f"scheduled_tasks: {scheduled_tasks}")
                logger.info(f"scheduler_output: {scheduler_output}")

                self._execute_scheduler_output(scheduled_tasks, scheduler_output)

                self._update_task_tracker_with_scheduler_output(scheduled_tasks, scheduler_output)

                self._process_output_and_update_tracker()

        except Exception as e:
            logger.error(f"Exception in engine core loop: {e}")
            raise
        finally:
            self._shutdown()

    def _update_task_tracker_with_scheduler_output(self, tasks, scheduler_output: SchedulerOutput):

        for task in tasks:
            self.task_tracker[task.task_id] = {"worker_id": scheduler_output.task_assignments[task.task_id], "task": task, "status": "pending"}
            self.context_tracker[task.context_id] = scheduler_output.task_assignments[task.task_id]
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

            # Convert BrowserWorkerTask to dict
            task_dict = task.to_dict()
            self.worker_client.send([task_dict], worker_id)
            logger.info(f"sent task {task.task_id} to worker {worker_id}")

        return

    def _process_output_and_update_tracker(self):
        output_queue_len = self.worker_client.get_output_queue_len()
        if output_queue_len == 0:
            return
        
        for _ in range(output_queue_len):
            idx, msg = self.worker_client.get_output_nowait()
            logger.info(f"received task {msg['task_id']} from worker {idx}")
            if not msg["success"]:
                logger.warning(f"task {msg['task_id']} failed")
            assert "task_id" in msg
            task_id = msg["task_id"]
            assert task_id not in self.output_dict
            self.output_dict[task_id] = msg
            self.task_tracker[task_id]["status"] = "finished"
            logger.info(f"updated task {task_id} status to finished")
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

                scheduled_tasks, scheduler_output = self.scheduler.schedule(tasks, self.task_tracker, worker_status)
                self._execute_scheduler_output(scheduled_tasks, scheduler_output)

                self._update_task_tracker_with_scheduler_output(scheduled_tasks, scheduler_output)

                self._process_output_and_update_tracker()

        except Exception as e:
            logger.error(f"Exception in engine core loop: {e}")
        finally:
            self._shutdown()


if __name__ == "__main__":
    import threading
    config = {
        "worker_client_config": {"input_path": "ipc://input_sync", "output_path": "ipc://output_sync", "num_workers": 3},
        "scheduler_config": {"type": SchedulerType.ROUND_ROBIN, "max_batch_size": 5, "n_workers": 3}
    }
    scheduler = make_scheduler(config["scheduler_config"])
    engine = BrowserEngine(BrowserEngineConfig(**config))

    # Set up signal handlers in main thread
    def signal_handler(signum, frame):
        engine._shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    engine_thread = threading.Thread(target=engine.engine_core_loop)
    engine_thread.start()

    for _ in range(5):
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        print(f"adding task {task_id} to engine")
        context_id = f"{uuid.uuid4().hex[:8]}"
        print(f"context_id: {context_id}")
        engine.add_task(BrowserWorkerTask(task_id=task_id, command="create_context", context_id=context_id))

    # print(engine.waiting_queue.qsize())
    # # print(engine.task_tracker)
    # print(engine.context_tracker)
    # print(engine.output_dict)

    # wait for engine to finish
    time.sleep(10)

    # print engine status
    print(engine.waiting_queue.qsize())
    # print(engine.task_tracker)
    prev_context_worker_mapping = {}
    for task_id, task in engine.task_tracker.items():
        prev_context_worker_mapping[task['task'].context_id] = task['worker_id']
    print(prev_context_worker_mapping)
    # print(engine.output_dict)
    prev_context_ids = []
    for context_id in engine.context_tracker:
        prev_context_ids.append(context_id)

    # add new create_context task and add close_context task
    for _ in range(7):
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        context_id = f"{uuid.uuid4().hex[:8]}"
        print(f"adding task {task_id} to engine")
        print(f"context_id: {context_id}")
        engine.add_task(BrowserWorkerTask(task_id=task_id, command="create_context", context_id=context_id))
    for context_id in prev_context_ids:
        engine.add_task(BrowserWorkerTask(task_id=f"task_{uuid.uuid4().hex[:8]}", command="browser_close", context_id=context_id))

    time.sleep(10)

    print(engine.waiting_queue.qsize())
    # print(engine.task_tracker)
    for task_id, task in engine.task_tracker.items():
        print(f"context_id: {task['task'].context_id}, worker_id: {task['worker_id']}") 
    context_worker_mapping = {}
    for context_id in engine.context_tracker:
        context_worker_mapping[context_id] = engine.context_tracker[context_id]
    print(prev_context_worker_mapping)
    print(context_worker_mapping)

    # Check if prev_context_id are scheduled to the same worker
    for context_id in prev_context_ids:
        assert prev_context_worker_mapping[context_id] == context_worker_mapping[context_id]
    
    print(engine.output_dict)

    # stop engine
    engine._shutdown()