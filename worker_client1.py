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
import json
from typing import Dict, Any, Optional, List
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
            task_port: Port to send tasks to the worker process
            result_port: Port to receive results from the worker process
        """
        self.worker_id = worker_id
        self.input_path = input_path
        self.output_path = output_path
        
        # # Track pending tasks
        # self.pending_tasks: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"BrowserWorkerClient {worker_id} initialized")

        self.zmq_context = zmq.Context(io_threads=2)
        
        self.input_socket = make_zmq_socket(self.zmq_context, input_path, zmq.PUSH, bind=False)
        self.output_socket = make_zmq_socket(self.zmq_context, output_path, zmq.PULL, bind=False)
    
    def add_request(self, request_data: Dict[str, Any]) -> str:
        """
        Add a request to be processed by the worker
        
        Args:
            request_data: Request data containing command and parameters
            
        Returns:
            Task ID that can be used to retrieve the result
        """
        # # Ensure task_id exists
        # if "task_id" not in request_data:
        #     request_data["task_id"] = str(uuid.uuid4())
        
        # task_id = request_data["task_id"]
        
        # # Add timestamp
        # request_data["timestamp"] = time.time()
        
        # # Track pending task
        # self.pending_tasks[task_id] = {
        #     "request": request_data,
        #     "timestamp": time.time()
        # }
        
        # Send request to worker process
        # sent = False
        # while not sent:
        self.input_socket.send_json(request_data)

        logger.debug(f"Sent request {request_data} to worker {self.worker_id}")
        
        return True
    
    def get_result(self) -> Optional[Dict[str, Any]]:
        """
        Get a result from the worker, if available
        
        Args:
            timeout: Time to wait for a result (seconds)
            
        Returns:
            Result data or None if no result is available
        """
        try:
            # Try to receive with timeout
            logger.debug("Waiting for result...")
            result = self.output_socket.recv_json(flags=zmq.NOBLOCK)

            return result
        except zmq.Again:
            logger.debug("No message to receive")
            return None
        except Exception as e:
            logger.error(f"get_result error: {e}")
            return None