from scheduler import make_scheduler, SchedulerOutput
import asyncio
import json
import logging
import multiprocessing as mp
from typing import Dict, List, Set, Any, Optional, Tuple
from dataclasses import dataclass
from worker_client import BrowserWorkerClient, make_client
import signal
import queue

logger = logging.getLogger(__name__)

@dataclass
class BrowserEngineConfig:
    worker_client_config: Dict[str, Any]
    worker_config: Dict[str, Any]
    scheduler_config: Optional[Dict[str, Any]] = None

class BrowserEngine:
    """Browser engine that manages multiple browser workers in separate processes"""

    def __init__(self, config: BrowserEngineConfig):
        """Initialize the browser engine with the specified configuration"""
        self.config = config
        self.scheduler = make_scheduler(self.config.scheduler_config)
        self.worker_client: BrowserWorkerClient = make_client(self.config.worker_client_config)
        self._running = False

        self.waiting_queue = queue.Queue()
        self.task_tracker = {}

        self.output_dict = {}
    
    def _execute_scheduler_output(self, scheduler_output: SchedulerOutput):
        pass
        
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
    
    def _update_task_tracker_with_scheduler_output(self, scheduler_output: SchedulerOutput):
        pass

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

            # TODO: update task tracker
            self.task_tracker[task_id]