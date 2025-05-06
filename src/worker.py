"""
Browser Worker Module

This module implements the browser worker component of the Remote Browser Automation Service.
It manages browser processes and contexts, handles commands and observations, and provides
reliability features for browser automation.
"""

import asyncio
import logging
import os
import time
import traceback
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import browsergym
import gymnasium as gym
import uvloop
import zmq
import zmq.asyncio
from browsergym.async_core.action.highlevel import HighLevelActionSet
from playwright.async_api import Browser, async_playwright

from type.task_type import WorkerOutput, WorkerTask
from type.worker_type import WorkerStatus
from utils import MsgType, Serializer, make_zmq_socket, numpy_safe_serializer

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("worker.log")],
)
logger = logging.getLogger(__name__)

# Constants
CONTEXT_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("CONTEXT_IDLE_TIMEOUT_SECONDS", "300")
)
HEALTH_CHECK_INTERVAL_SECONDS = int(
    os.environ.get("HEALTH_CHECK_INTERVAL_SECONDS", "30")
)
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "True").lower() == "true"


class AsyncBrowserWorker:
    """
    Browser Worker manages a single browser process with multiple browser contexts.
    It handles browser commands, observations, and provides reliability features.
    """

    def __init__(self, index: int = None, ema_factor: float = 0.9):
        """Initialize the browser worker"""
        self.index = index
        self.browser: Optional[Browser] = None
        self.playwright = None
        self.env_map: Dict[str, Any] = {}
        self.last_health_check = 0
        self.event_loop = None

        # Task queue system
        self.input_queue = asyncio.Queue()
        self.output_queue = asyncio.Queue()

        # status
        self.ema_factor = ema_factor  # Exponential moving average factor
        self.running = False
        self.num_running_tasks = 0
        self.num_finished_tasks = 0
        self.num_error_tasks = 0  # Track number of tasks that resulted in errors
        self.num_contexts = 0
        self.num_pages = 0
        self.avg_latency_ms = 0
        self.error_rate = 0
        self.last_activity_time = time.time()

        logger.info(f"Initializing BrowserWorker with ID: {self.index}")

    async def start(self):
        """Start the browser worker and launch a browser process"""
        if self.running:
            return

        logger.info(f"Starting BrowserWorker {self.index}")
        self.running = True
        self.event_loop = asyncio.get_running_loop()

        try:
            # Launch playwright browser
            self.playwright = await async_playwright().start()

            # Launch browser with appropriate options
            browser_type = self.playwright.chromium
            self.browser = await browser_type.launch(headless=BROWSER_HEADLESS)

            self.running = True
            logger.info(f"BrowserWorker {self.index} started successfully")
        except Exception as e:
            self.running = False
            logger.error(f"Error starting BrowserWorker: {e}")
            if self.playwright:
                await self.playwright.stop()
            raise e

    def is_ready(self) -> bool:
        return self.running

    async def add_task(self, task: Dict):
        """Add a task to the queue for execution"""
        if not self.running:
            raise RuntimeError("Worker is not running")

        logger.info(f"Adding task to queue: {task}")

        self.input_queue.put_nowait(task)
        return task.task_id

    async def process_task_queue_loop(self):
        """Process tasks from the queue in the background"""
        while self.running:
            try:
                # Wait for tasks when the queue is empty
                while self.input_queue.qsize() == 0:
                    task = await self.input_queue.get()
                    self.event_loop.create_task(self._execute_task(task))
                    self.num_running_tasks += 1

                # Process all available tasks without blocking
                while self.input_queue.qsize() > 0:
                    task = self.input_queue.get_nowait()
                    self.event_loop.create_task(self._execute_task(task))
                    self.num_running_tasks += 1

            except asyncio.CancelledError:
                logger.info("Task processor cancelled")
                return
            except Exception as e:
                logger.error(f"Error in task processor: {str(e)}")
                await asyncio.sleep(0.1)

    async def _execute_task(self, task: WorkerTask):
        """Execute a single task and put result in result queue"""
        logger.info(f"Executing task {task.to_dict()}")
        task.worker_start_process_timestamp = time.time()
        try:
            result = await self._execute_method(task.env_id, task.method, task.params)
            logger.info(f"Task {task.task_id} finished with result: {result}")

            result = numpy_safe_serializer(result)

            finish_timestamp = time.time()
            self.output_queue.put_nowait(
                WorkerOutput(
                    task_id=task.task_id,
                    result=result,
                    success=True,
                    profile={
                        "engine_recv_timestamp": task.engine_recv_timestamp,
                        "engine_send_timestamp": task.engine_send_timestamp,
                        "worker_recv_timestamp": task.worker_recv_timestamp,
                        "worker_start_process_timestamp": task.worker_start_process_timestamp,
                        "worker_finish_timestamp": finish_timestamp,
                    },
                )
            )
            self.last_activity_time = finish_timestamp
            self.num_finished_tasks += 1
            self.error_rate *= self.ema_factor
            self.avg_latency_ms = self.ema_factor * self.avg_latency_ms + (
                finish_timestamp - task.worker_recv_timestamp
            ) * 1000 * (1 - self.ema_factor)

        except Exception as e:

            logger.error(f"Error executing task {task}: {str(e)}", exc_info=True)
            self.output_queue.put_nowait(
                WorkerOutput(
                    task_id=task.task_id,
                    result=str(e) + "\n" + traceback.format_exc(),
                    success=False,
                    profile={
                        "engine_recv_timestamp": task.engine_recv_timestamp,
                        "engine_send_timestamp": task.engine_send_timestamp,
                        "worker_recv_timestamp": task.worker_recv_timestamp,
                        "worker_start_process_timestamp": task.worker_start_process_timestamp,
                        "worker_finish_timestamp": time.time(),
                    },
                )
            )
            self.num_error_tasks += 1
            self.error_rate = self.ema_factor * self.error_rate + (1 - self.ema_factor)
        finally:
            self.num_running_tasks -= 1

    def shutdown(self):
        logger.info(f"Shutting down worker {self.index}")
        self.running = False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.info("No running loop found, skipping shutdown")
            return

        if self.playwright:
            loop.create_task(self.playwright.stop(), name="playwright_shutdown")
        if self.browser:
            loop.create_task(self.browser.close(), name="browser_shutdown")

        # Cancel all tasks that are not shutdown-related
        for task in asyncio.all_tasks(loop):
            if task.get_name() not in ["playwright_shutdown", "browser_shutdown"]:
                task.cancel()

        self.browser = None
        self.playwright = None

        # Wait for the loop to stop with a timeout
        try:
            wait_start = time.time()
            while (
                loop.is_running() and time.time() - wait_start < 5
            ):  # 5-second timeout
                time.sleep(0.1)
            if loop.is_running():
                logger.warning("Loop did not stop within the timeout period")
        except asyncio.CancelledError:
            pass

        loop.close()

    async def _execute_method(
        self, env_id: str, method: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Execute a browser command in the specified context

        Args:
            context_id: ID of the context to execute the command in
            command: Command to execute
            params: Parameters for the command

        Returns:
            Result of the command execution
        """
        if method == "SHUTDOWN":
            self.shutdown()
            return "SHUTDOWN"
        if method != "__init__":
            assert (
                env_id in self.env_map
            ), "Environment not initialized, should not step"
            env = self.env_map[env_id]
            func = getattr(env, method)
            result = await func(**params)
            return result
        else:
            assert (
                env_id not in self.env_map
            ), "Environment already exists, should not initialize again"
            action_set = HighLevelActionSet()
            params["action_mapping"] = action_set.to_python_code
            env = gym.make(**params)
            env = env.unwrapped
            self.env_map[env_id] = env
            return "Initialized"

    def get_status(self) -> WorkerStatus:
        """Get the current status of the worker

        Returns a WorkerStatus object with the current state of the worker,
        including metrics like number of tasks, contexts, and performance data.
        Some fields (CPU, memory, throughput) are populated by the heartbeat loop.
        """

        return WorkerStatus(
            index=self.index,
            running=self.running,
            num_running_tasks=self.num_running_tasks,
            num_waiting_tasks=self.input_queue.qsize(),
            num_finished_tasks=self.num_finished_tasks,
            num_envs=len(self.env_map),
            num_pages=self.num_pages,
            avg_latency_ms=self.avg_latency_ms,
            error_rate=self.error_rate,
            last_activity=self.last_activity_time,
            # The following fields will be updated by the heartbeat loop
            throughput_per_sec=0,
            cpu_usage_percent=0,
            memory_usage_mb=0,
            last_heartbeat=0,
        )


class AsyncBrowserWorkerProc:
    """
    Process implementation that runs an AsyncBrowserWorker and handles ZMQ communication.

    This class manages the worker process side of communication - binding ZMQ sockets,
    receiving tasks from the engine, and sending results back.
    """

    def __init__(
        self,
        index: int,
        input_path: str,
        output_path: str,
        report_cpu_and_memory: bool = False,
        monitor: bool = True,
        monitor_path: str = "ipc://worker_status.sock",
    ):
        self.index = index
        self.identity = str(index).encode()
        self.input_path = input_path
        self.output_path = output_path
        self.report_cpu_and_memory = report_cpu_and_memory
        self.monitor = monitor
        self.monitor_path = monitor_path
        logger.info(f"Initializing AsyncBrowserWorkerProc {index}")

        self.ctx = zmq.asyncio.Context(io_threads=1)
        self.input_socket = make_zmq_socket(
            self.ctx,
            self.input_path,
            zmq.DEALER,
            bind=False,
            identity=self.identity,
        )
        self.output_socket = make_zmq_socket(
            self.ctx, self.output_path, zmq.PUSH, bind=False
        )
        if self.monitor:
            self.worker_status_socket = make_zmq_socket(
                self.ctx, self.monitor_path, zmq.PUSH, bind=False
            )

        self.worker = AsyncBrowserWorker(index)
        self.serializer = Serializer(serializer="msgpack")

    async def _send_ready(self):
        assert self.worker.is_ready()
        await self.output_socket.send_multipart(
            [self.identity, MsgType.READY, self.serializer.dumps(["READY"])]
        )

    @classmethod
    def run_background_loop(
        cls,
        index: int,
        input_path: str,
        output_path: str,
        report_cpu_and_memory: bool = False,
        monitor: bool = True,
        monitor_path: str = "ipc://worker_status.sock",
    ):
        """
        Run a worker process in the background with ZMQ communication

        Args:
            index: Unique identifier for this worker
            input_path: Path to receive tasks from
            output_path: Path to send results back to
        """
        proc = cls(
            index,
            input_path,
            output_path,
            report_cpu_and_memory,
            monitor,
            monitor_path,
        )
        worker = proc.worker

        async def main_loop():
            await worker.start()
            logger.info(
                f"Worker started with input_path={input_path}, output_path={output_path}"
            )
            if worker.is_ready():
                await proc._send_ready()

            tasks = [
                worker.process_task_queue_loop(),
                proc.process_incoming_socket_loop(),
                proc.process_outgoing_socket_loop(),
                # proc.send_heartbeat_loop(),
            ]
            await asyncio.gather(*tasks)

        try:
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            asyncio.run(main_loop())
        except Exception as e:
            logger.error(f"Fatal error in worker: {e}, {traceback.format_exc()}")
        finally:
            proc.shutdown()

    async def _recv(self):
        msg = await self.input_socket.recv_multipart()
        assert len(msg) == 1
        return self.serializer.loads(msg[0])

    async def _send(self, outputs: List[Dict[str, Any]], msg_type: bytes):
        assert isinstance(outputs, list)
        logger.debug(f"Sending {len(outputs)} outputs to client")
        await self.output_socket.send_multipart(
            [self.identity, msg_type, self.serializer.dumps(outputs)]
        )

    async def process_incoming_socket_loop(self):
        while self.worker.running:
            try:
                logger.debug("waiting for tasks")
                tasks = await self._recv()
                assert len(tasks) > 0, "Received empty tasks, this should not happen"

                for task in tasks:
                    task = WorkerTask(**task)
                    task.worker_recv_timestamp = time.time()
                    self.worker.input_queue.put_nowait(task)

                logger.debug(
                    f"Received {len(tasks)} tasks from client, input queue size: {self.worker.input_queue.qsize()}, output queue size: {self.worker.output_queue.qsize()}"
                )
            except Exception as e:
                logger.error(f"Error processing incoming socket loop: {e}")

    async def process_outgoing_socket_loop(self):
        while self.worker.running:
            output = (await self.worker.output_queue.get()).to_dict()
            output["profile"]["worker_send_timestamp"] = time.time()

            outputs = [output]
            while not self.worker.output_queue.empty():
                output = self.worker.output_queue.get_nowait().to_dict()
                output["profile"]["worker_send_timestamp"] = time.time()
                outputs.append(output)

            assert len(outputs) > 0, "No outputs to send, this should not happen"
            await self._send(outputs, MsgType.OUTPUT)

    async def send_heartbeat_loop(self):
        """Send periodic heartbeat status updates to the client

        We fetch status from the worker, and update (Optionally)
        CPU usage, memory usage, throughput, and last heartbeat time.
        """

        heartbeat_interval = 1.0  # Send heartbeat every second
        resource_check_interval = 5  # Check CPU/memory every 5 heartbeats
        heartbeat_count = 0

        prev_time = time.time()
        prev_num_finished_tasks = 0
        prev_throughput_per_sec = 0

        if self.report_cpu_and_memory:
            import psutil

            process = psutil.Process()
            process.cpu_percent()

            cached_cpu_percent = 0
            cached_memory_mb = 0

        logger.info(f"Starting heartbeat loop for worker {self.worker.index}")

        try:
            while self.worker.running:
                # Wait for the heartbeat interval
                await asyncio.sleep(heartbeat_interval)
                current_time = time.time()
                heartbeat_count += 1

                status = self.worker.get_status()
                status.last_heartbeat = current_time

                # Only check resource usage periodically to reduce overhead
                if self.report_cpu_and_memory:
                    if heartbeat_count % resource_check_interval == 0:
                        memory_info = process.memory_info()
                        cached_memory_mb = memory_info.rss / (
                            1024 * 1024
                        )  # Convert bytes to MB
                        cached_cpu_percent = process.cpu_percent(interval=None)

                    status.memory_usage_mb = cached_memory_mb
                    status.cpu_usage_percent = cached_cpu_percent

                new_tasks_completed = (
                    status.num_finished_tasks - prev_num_finished_tasks
                )
                status.throughput_per_sec = (
                    prev_throughput_per_sec * self.worker.ema_factor
                    + new_tasks_completed * (1 - self.worker.ema_factor)
                )

                # Update tracking variables for next iteration
                prev_num_finished_tasks = status.num_finished_tasks
                prev_throughput_per_sec = status.throughput_per_sec
                prev_time = current_time

                await self._send([status.to_dict()], MsgType.STATUS)
                if self.monitor:
                    await self.worker_status_socket.send_multipart(
                        [
                            self.identity,
                            MsgType.STATUS,
                            self.serializer.dumps(status.to_dict()),
                        ]
                    )
                logger.debug(
                    f"Heartbeat worker {self.worker.index}: "
                    + f"CPU: {status.cpu_usage_percent:.1f}%, "
                    + f"Memory: {status.memory_usage_mb:.1f}MB, "
                    + f"Tasks: {status.num_finished_tasks}, "
                    + f"Throughput: {status.throughput_per_sec:.2f}/s, "
                    + f"Latency: {status.avg_latency_ms:.2f}ms"
                )

        except asyncio.CancelledError:
            logger.info(f"Heartbeat loop for worker {self.worker.index} cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in heartbeat loop: {e}")
            raise

    async def _send_shutdown_status_async(self):
        status = self.worker.get_status()
        status.running = False
        status.last_activity = time.time()
        status.last_heartbeat = time.time()
        await self._send([status.to_dict()], MsgType.STATUS)
        if self.monitor:
            await self.worker_status_socket.send_multipart(
                [self.identity, MsgType.STATUS, self.serializer.dumps(status.to_dict())]
            )

    def shutdown(self):
        logger.info(f"Shutting down worker {self.worker.index}")
        try:
            loop = asyncio.get_event_loop_policy().get_event_loop()
            if loop:
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._send_shutdown_status_async(), loop
                    )
                    future.result()
                else:
                    asyncio.run(self._send_shutdown_status_async())
        except Exception as e:
            asyncio.run(self._send_shutdown_status_async())

        self.worker.shutdown()
        self.input_socket.close()
        self.output_socket.close()
        if self.monitor:
            self.worker_status_socket.close()
        self.ctx.term()


if __name__ == "__main__":
    worker = AsyncBrowserWorker(index=0)

    async def main():
        await worker.start()
        asyncio.create_task(worker.process_task_queue_loop())

        worker_task = WorkerTask(
            task_id=str(0),
            env_id="test1",
            method="__init__",
            params={
                "id": "browsergym_async/openended",
                "task_kwargs": {"start_url": "https://www.example.com"},
                "headless": True,
                "slow_mo": 0,
                "timeout": 10,
            },
        )
        worker_task.worker_recv_timestamp = time.time()
        await worker.input_queue.put(worker_task)
        result = await worker.output_queue.get()
        # print(result)
        # for i in range(10000):
        task = WorkerTask(
            task_id=str(1),
            env_id="test1",
            method="reset",
            params={},
        )
        task.worker_recv_timestamp = time.time()
        await worker.input_queue.put(task)
        result = await worker.output_queue.get()
        # print(result)

        task = WorkerTask(
            task_id=str(2),
            env_id="test1",
            method="step",
            params={"action": "click [123]"},
        )
        task.worker_recv_timestamp = time.time()
        await worker.input_queue.put(task)
        result = await worker.output_queue.get()

    asyncio.run(main())

    # action_set = HighLevelActionSet()
    # env = gym.make(
    #     "browsergym_async/openended",
    #     task_kwargs={"start_url": "https://www.example.com"},
    #     headless=True,
    #     slow_mo=0,
    #     timeout=10,
    #     action_mapping=action_set.to_python_code,
    # )
    # env = env.unwrapped

    # async def main():
    #     obs, info = await env.reset()
    #     print(obs["axtree_object"])

    # asyncio.run(main())
