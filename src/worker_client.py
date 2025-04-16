"""
Browser Worker Client Module

This module implements the client that runs in the engine process and handles
communication with browser workers running in separate processes.
"""

import asyncio
import logging
import time
import uuid
import zmq
import zmq.asyncio
from typing import Dict, Any, Optional
from utils import make_zmq_socket

# Configure logging
logger = logging.getLogger(__name__)


class BrowserWorkerClient:
    """
    Client for communicating with a browser worker process.
    
    This client runs in the engine process and sends requests to
    and receives results from a worker process running AsyncBrowserWorker.
    """
    
    def __init__(self, worker_id: str, input_path: str, output_path: str):
        """
        Initialize the browser worker client
        
        Args:
            worker_id: Unique identifier for this worker
            input_path: Path to send tasks to the worker process
            output_path: Path to receive results from the worker process
        """
        self.worker_id = worker_id
        self.input_path = input_path
        self.output_path = output_path
        
        # Track pending tasks
        self.pending_tasks: Dict[str, Dict[str, Any]] = {}
        self.finished_tasks: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"BrowserWorkerClient {worker_id} initialized")
    
        # Create ZMQ context
        self.zmq_context = zmq.Context()
        self.input_socket = make_zmq_socket(self.zmq_context, self.input_path, zmq.PUSH, bind=False)
        self.output_socket = make_zmq_socket(self.zmq_context, self.output_path, zmq.PULL, bind=False)
    
    async def add_request(self, request_data: Dict[str, Any]) -> str:
        """
        Add a request to be processed by the worker
        
        Args:
            request_data: Request data containing command and parameters
            
        Returns:
            Task ID that can be used to retrieve the result
        """

        if "task_id" not in request_data:
            request_data["task_id"] = str(uuid.uuid4())
        
        task_id = request_data["task_id"]
        request_data["timestamp"] = time.time()
        
        self.pending_tasks[task_id] = {
            "request": request_data,
            "timestamp": time.time()
        }
        
        sent = False
        while not sent:
            try:
                self.input_socket.send_json(request_data)
                sent = True
            except zmq.Again:
                await asyncio.sleep(0.1)
        logger.debug(f"Sent request {task_id} to worker {self.worker_id}")
        
        return task_id
    
    async def _get_result_step(self, task_id: str) -> Optional[Dict[str, Any]]:
        try:
            if task_id in self.finished_tasks:
                result = self.finished_tasks[task_id]
                del self.finished_tasks[task_id]
                return result

            result = self.output_socket.recv_json(flags=zmq.NOBLOCK)
            ret_task_id = result.get("task_id")
            if ret_task_id and ret_task_id in self.pending_tasks:
                del self.pending_tasks[ret_task_id]
                self.finished_tasks[ret_task_id] = result
            
            return None
        except zmq.Again:
            await asyncio.sleep(0.1)
            return None
        except Exception as e:
            logger.error(f"get_result error: {e}")
            await asyncio.sleep(0.1)
            return None
    
    async def get_result(self, task_id: str, timeout: float = 300) -> Optional[Dict[str, Any]]:
        """
        Get a result from the worker, if available
        
        Args:
            task_id: ID of the task to retrieve the result for
            
        Returns:
            Result data or None if no result is available
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = await self._get_result_step(task_id)
            if result:
                return result
        
        logger.error(f"Timeout waiting for result {task_id}")
        return None
        
    def close(self):
        self.input_socket.close()
        self.output_socket.close()
        self.zmq_context.term()
