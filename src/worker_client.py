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
from utils import make_zmq_socket, JsonEncoder, JsonDecoder
import weakref
import multiprocessing as mp
from worker import AsyncBrowserWorkerProc
from typing import List
import queue
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WorkerClient:
    def __init__(self, input_path: str, output_path: str, num_workers: int):
        self.input_path = input_path
        self.output_path = output_path
        self.num_workers = num_workers

        self.output_queue = queue.Queue()

        self.zmq_context = zmq.Context()
        self.input_socket = make_zmq_socket(
            self.zmq_context, self.input_path, zmq.ROUTER, bind=True
        )
        self.output_socket = make_zmq_socket(
            self.zmq_context, self.output_path, zmq.PULL, bind=True
        )
        self.encoder = JsonEncoder()
        self.decoder = JsonDecoder()

        self.workers_status: Dict[int, bool] = {
            i: {"ready": False} for i in range(self.num_workers)
        }
        self._start_workers()

        self._wait_for_workers_ready()

        self.recv_thread = threading.Thread(target=self._recv_thread)
        self._recv_thread_running = True
        self.recv_thread.start()

    def _start_workers(self):
        self.worker_processes = []
        for worker_id in range(self.num_workers):
            # Create process for each worker
            process = mp.Process(
                target=AsyncBrowserWorkerProc.run_background_loop,
                args=(worker_id, self.input_path, self.output_path),
                daemon=True,  # Optional: makes process exit when main process exits
            )
            process.start()
            self.worker_processes.append(process)

    def _wait_for_workers_ready(self, timeout: float = 10):
        waiting_workers = set(range(self.num_workers))
        start_time = time.time()
        while waiting_workers and time.time() - start_time < timeout:
            idx, msg = self._recv()
            if msg:
                if msg[0] == "READY":
                    waiting_workers.remove(idx)
                    self.workers_status[idx]["ready"] = True
                else:
                    raise ValueError(f"Worker {idx} returned {msg}")
        if waiting_workers:
            raise ValueError(
                f"Timeout after {timeout} seconds, {waiting_workers} workers are not ready"
            )
        else:
            logger.info(f"All workers {self.num_workers} are ready")

    def send(self, msg: List[Dict[str, Any]], index: int):
        self._send(msg, index)

    def _send(self, msg: List[Dict[str, Any]], index: int) -> str:
        assert isinstance(msg, list)
        self.input_socket.send_multipart(
            [str(index).encode(), self.encoder(msg)], flags=zmq.NOBLOCK
        )

    def _recv(self):
        try:
            msg = self.output_socket.recv_multipart(flags=zmq.NOBLOCK)
            assert len(msg) == 2, f"Expected 2 parts, got {len(msg)}"
            index = int(msg[0])
            return index, self.decoder(msg[1])
        except zmq.Again:
            # time.sleep(1)
            return None, None

    def _recv_thread(self):
        while self._recv_thread_running:
            idx, msg = self._recv()
            if msg:
                for m in msg:
                    logger.info(f"Received message from worker {idx}: {m}")
                    self.output_queue.put((idx, m))
            else:
                logger.debug(f"No message received from worker {idx}")

    def close(self):
        for worker_process in self.worker_processes:
            worker_process.terminate()
        self._recv_thread_running = False
        self.input_socket.close()
        self.output_socket.close()
        self.zmq_context.term()
        self.recv_thread.join()
