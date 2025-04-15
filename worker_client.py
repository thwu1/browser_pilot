#!/usr/bin/env python3
"""
Browser Worker Client Module

This module implements the client that runs in the engine process and handles
communication with browser workers running in separate processes.
"""

import asyncio
import logging
import time
import uuid
import base64
import zmq
import zmq.asyncio
import json
from typing import Dict, Any, Optional, List

# Configure logging
logger = logging.getLogger(__name__)


class BrowserWorkerClient:
    """
    Client for communicating with a browser worker process.
    
    This client runs in the engine process and sends requests to
    and receives results from a worker process running AsyncBrowserWorker.
    """
    
    def __init__(self, worker_id: str, task_port: int, result_port: int):
        """
        Initialize the browser worker client
        
        Args:
            worker_id: Unique identifier for this worker
            task_port: Port to send tasks to the worker process
            result_port: Port to receive results from the worker process
        """
        self.worker_id = worker_id
        self.task_port = task_port
        self.result_port = result_port
        
        # Track pending tasks
        self.pending_tasks: Dict[str, Dict[str, Any]] = {}
        
        # ZMQ setup
        self._setup_zmq()
        logger.info(f"BrowserWorkerClient {worker_id} initialized")
    
    def _setup_zmq(self):
        """Set up ZMQ sockets for communication"""
        # Create ZMQ context
        self.zmq_context = zmq.Context()
        
        # Socket to send tasks (PUSH)
        self.task_socket = self.zmq_context.socket(zmq.PUSH)
        self.task_socket.setsockopt(zmq.LINGER, 5000)  # Don't wait for pending messages on close
        self.task_socket.connect(f"tcp://localhost:{self.task_port}")
        
        # Socket to receive results (PULL)
        self.result_socket = self.zmq_context.socket(zmq.PULL)
        self.result_socket.setsockopt(zmq.LINGER, 5000)  # Don't wait for pending messages on close
        self.result_socket.setsockopt(zmq.RCVHWM, 10000)
        self.result_socket.connect(f"tcp://localhost:{self.result_port}")
    
    async def add_request(self, request_data: Dict[str, Any]) -> str:
        """
        Add a request to be processed by the worker
        
        Args:
            request_data: Request data containing command and parameters
            
        Returns:
            Task ID that can be used to retrieve the result
        """
        # Ensure task_id exists
        if "task_id" not in request_data:
            request_data["task_id"] = str(uuid.uuid4())
        
        task_id = request_data["task_id"]
        
        # Add timestamp
        request_data["timestamp"] = time.time()
        
        # Track pending task
        self.pending_tasks[task_id] = {
            "request": request_data,
            "timestamp": time.time()
        }
        
        # Send request to worker process
        sent = False
        while not sent:
            try:
                self.task_socket.send_json(request_data)
                sent = True
            except zmq.Again:
                await asyncio.sleep(0.1)
        logger.debug(f"Sent request {task_id} to worker {self.worker_id}")
        
        return task_id
    
    async def get_result(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """
        Get a result from the worker, if available
        
        Args:
            timeout: Time to wait for a result (seconds)
            
        Returns:
            Result data or None if no result is available
        """
        try:
            # Try to receive with timeout
            print("Waiting for result...")
            result = self.result_socket.recv_json(flags=zmq.NOBLOCK)
            # Remove from pending tasks if present
            task_id = result.get("task_id")
            if task_id and task_id in self.pending_tasks:
                del self.pending_tasks[task_id]
            
            return result
        except zmq.Again:
            print("No message to receive ======================")
            await asyncio.sleep(0.1)
            return None
        except Exception as e:
            logger.error(f"get_result error: {e}")
            await asyncio.sleep(0.1)
            return None
