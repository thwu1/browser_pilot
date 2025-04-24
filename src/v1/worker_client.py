"""
Browser Worker Client Module

This module implements the client that runs in the engine process and handles
communication with browser workers running in separate processes.
"""

import asyncio
import logging
import multiprocessing as mp
import queue
import threading
import time
import uuid
import weakref
from typing import Any, Dict, List, Optional

import zmq
import zmq.asyncio

from timer_util import Timer
from utils import (
    JsonDecoder,
    JsonEncoder,
    MsgpackDecoder,
    MsgpackEncoder,
    MsgType,
    make_zmq_socket,
)
from worker import AsyncBrowserWorkerProc

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s - %(processName)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def make_client(config: Dict[str, Any]):
    try:
        return WorkerClient(
            config["input_path"], config["output_path"], config["num_workers"]
        )
    except Exception as e:
        logger.error(f"Error making client: {e}")
        raise e


class WorkerClient:
    def __init__(self, input_path: str, output_path: str, num_workers: int):
        self.input_path = input_path
        self.output_path = output_path
        self.num_workers = num_workers

        self.output_queue = queue.Queue()

        self.zmq_context = zmq.Context(io_threads=1)
        self.input_socket = make_zmq_socket(
            self.zmq_context, self.input_path, zmq.ROUTER, bind=True
        )
        self.output_socket = make_zmq_socket(
            self.zmq_context, self.output_path, zmq.PULL, bind=True
        )
        self.encoder = MsgpackEncoder()
        self.decoder = MsgpackDecoder()

        self.worker_status = {worker_id: {} for worker_id in range(num_workers)}

        self._start_workers()
        self._wait_for_workers_ready()

        self.recv_thread = threading.Thread(target=self._recv_thread)
        self._recv_thread_running = True
        self.recv_thread.start()

        self.finished_tasks = {}

    def _start_workers(self):
        self.worker_processes = []
        for worker_id in range(self.num_workers):
            # Create process for each worker
            process = mp.Process(
                target=AsyncBrowserWorkerProc.run_background_loop,
                args=(worker_id, self.input_path, self.output_path),
                daemon=True,
            )
            process.start()
            self.worker_processes.append(process)

    def _wait_for_workers_ready(self, timeout: float = 10):
        waiting_workers = set(range(self.num_workers))
        start_time = time.time()
        while waiting_workers and time.time() - start_time < timeout:
            idx, msg_type, msg = self._recv()
            if msg_type == MsgType.READY:
                waiting_workers.remove(idx)
            logger.debug(f"Received message from worker {idx}: {msg}")
        if waiting_workers:
            raise ValueError(
                f"Timeout after {timeout} seconds, {waiting_workers} workers are not ready"
            )
        else:
            logger.info(f"All workers {self.num_workers} are ready")

    def send(self, msg: List[Dict[str, Any]], index: int):
        # with Timer("_send", log_file="timer_client_send.log"):
        self._send(msg, index)

    async def get_output_with_task_id(self, task_id, timeout: float = 20):
        """For testing only"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if task_id in self.finished_tasks:
                return self.finished_tasks[task_id]
            if self.output_queue.qsize() > 0:
                idx, msg = self.output_queue.get_nowait()
                assert "task_id" in msg
                self.finished_tasks[msg["task_id"]] = msg
            await asyncio.sleep(0.1)

        if task_id not in self.finished_tasks:
            return None
        return self.finished_tasks[task_id]

    def get_output_nowait(self):
        if self.output_queue.qsize() > 0:
            return self.output_queue.get_nowait()
        return None

    def get_output(self, timeout: float = 20):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.output_queue.qsize() > 0:
                return self.output_queue.get()
            time.sleep(0.1)

        raise TimeoutError("Timeout waiting for output")

    def get_output_queue_len(self):
        return self.output_queue.qsize()

    def _send(self, msg: List[Dict[str, Any]], index: int) -> str:
        assert isinstance(msg, list)
        self.input_socket.send_multipart(
            [str(index).encode(), self.encoder(msg)], flags=zmq.NOBLOCK
        )

    def _recv(self):
        # try:
        msg = self.output_socket.recv_multipart()
        assert len(msg) == 3, f"Expected 3 parts, got {len(msg)}, {msg}"
        index = int(msg[0])
        msg_type = msg[1]
        return index, msg_type, self.decoder(msg[2])
        # except zmq.Again:
        #     return None, None, None

    def _recv_thread(self):
        while self._recv_thread_running:
            idx, msg_type, msg = self._recv()
            if msg_type == MsgType.OUTPUT and msg:
                for m in msg:
                    logger.debug(f"Received message from worker {idx}: {m}")
                    assert isinstance(m, dict)
                    self.output_queue.put((idx, m))
            elif msg_type == MsgType.STATUS and msg:
                assert isinstance(msg, list)
                assert isinstance(msg[0], dict)
                logger.debug(f"Received status from worker {idx}: {msg[0]}")
                self.worker_status[idx] = msg[0]

    def get_worker_status_no_wait(self):
        return self.worker_status.copy()

    def close(self):
        logger.info("Received close signal, closing worker client")
        try:
            # Send shutdown signal to all workers
            logger.info("Sending shutdown signal to all workers")
            for worker_idx in range(self.num_workers):
                try:
                    self._send(
                        [
                            {
                                "command": "shutdown",
                                "task_id": f"shutdown_{worker_idx}",
                                "context_id": None,
                                "page_id": None,
                            }
                        ],
                        worker_idx,
                    )
                except Exception as e:
                    logger.error(f"Error sending shutdown to worker {worker_idx}: {e}")

            # Give workers a moment to process shutdown
            time.sleep(0.5)

            # Stop the receive thread
            self._recv_thread_running = False

            # Terminate and wait for worker processes
            logger.info("Terminating worker processes")
            for worker_process in self.worker_processes:
                worker_process.terminate()
                worker_process.join(timeout=1.0)  # Wait up to 1 second for each process
                if worker_process.is_alive():
                    logger.warning(
                        f"Worker process {worker_process.pid} still alive, killing..."
                    )
                    worker_process.kill()  # Force kill if still alive
                    worker_process.join(timeout=0.5)

            # Close sockets and terminate context
            logger.info("Closing ZMQ sockets")
            self.input_socket.close()
            self.output_socket.close()
            self.zmq_context.term()

            # Wait for receive thread
            logger.info("Waiting for receive thread")
            self.recv_thread.join(timeout=1.0)

            logger.info("Worker client closed successfully")
        except Exception as e:
            logger.error(f"Error during worker client shutdown: {e}")
