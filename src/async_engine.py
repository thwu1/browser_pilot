import asyncio
import logging
import time
import uuid
from abc import ABC
from collections import defaultdict
from typing import Dict, List

import zmq
import zmq.asyncio

from engine import BrowserEngineConfig, BrowserWorkerTask
from scheduler import SchedulerOutput, make_scheduler
from timer_util import Timer
from utils import MsgpackDecoder, MsgpackEncoder, MsgType, make_zmq_socket
from worker_client import WorkerClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BrowserEngine(ABC):
    @staticmethod
    def make_engine(config: BrowserEngineConfig):
        if config.worker_client_config["type"] == "sync":
            return AsyncBrowserEngineSyncClient(config)
        elif config.worker_client_config["type"] == "async":
            return AsyncBrowserEngineAsyncClient(config)
        else:
            raise ValueError(
                f"Invalid worker client type: {config.worker_client_config['type']}"
            )

    async def add_task_async(self, task: BrowserWorkerTask):
        raise NotImplementedError

    async def start(self):
        raise NotImplementedError

    def shutdown(self):
        raise NotImplementedError


class AsyncBrowserEngineSyncClient(BrowserEngine):
    def __init__(self, config: BrowserEngineConfig):
        self.config = config
        self.engine_config = self.config.engine_config
        self.scheduler = make_scheduler(self.config.scheduler_config)
        self.worker_client = WorkerClient.make_client(self.config.worker_client_config)
        self._running = False

        self.task_tracker = {}
        self.context_tracker = {}

        self.batch_size = self.config.scheduler_config["max_batch_size"]
        self.n_workers = self.config.worker_client_config["num_workers"]
        self.waiting_queue = asyncio.Queue()

        self.task_id_to_identity = {}
        self.zmq = zmq.asyncio.Context(io_threads=1)
        self.socket = make_zmq_socket(
            self.zmq, self.engine_config["app_to_engine_socket"], zmq.ROUTER, bind=True
        )

        self.encoder = MsgpackEncoder()
        self.decoder = MsgpackDecoder()

    async def add_task_async(self, task: BrowserWorkerTask):
        if not task.context_id:
            context_id = f"{uuid.uuid4().hex[:8]}"
            task.context_id = context_id
            self.context_tracker[context_id] = -1
        else:
            if task.context_id not in self.context_tracker:
                self.context_tracker[task.context_id] = -1

        task.engine_recv_timestamp = time.time()
        await self.waiting_queue.put(task)
        logger.info(f"added task {task.task_id} to waiting queue")

    async def start(self):
        self._running = True
        loop = asyncio.get_running_loop()
        loop.create_task(self._recv_loop())
        loop.create_task(self._engine_core_loop())

    async def _recv(self):
        msg = await self.socket.recv_multipart()
        assert len(msg) == 3
        identity = msg[0]
        msg_type = msg[1]
        return identity, msg_type, self.decoder(msg[2])

    async def _send(self, msg, identity, msg_type):
        await self.socket.send_multipart([identity, msg_type, self.encoder(msg)])

    async def _recv_loop(self):
        while self._running:
            identity, msg_type, msg = await self._recv()
            if msg_type == MsgType.TASK:
                task = BrowserWorkerTask(**msg)
                task_id = task.task_id
                self.task_id_to_identity[task_id] = identity
                await self.add_task_async(task)
            else:
                raise ValueError(f"Unknown message type: {msg_type}")

    async def _engine_core_loop(self):
        """Main engine loop that processes tasks and manages workers"""
        try:
            while self._running:
                tasks = []
                prev_workers = []
                while not self.waiting_queue.empty() and len(tasks) < self.batch_size:
                    task = await self.waiting_queue.get()
                    tasks.append(task)
                    prev_workers.append(self.context_tracker[task.context_id])

                if not tasks:
                    await self._process_output_and_update_tracker()
                    continue

                worker_status = self.worker_client.get_worker_status_no_wait()
                logger.info(f"worker_status: {worker_status}")

                scheduled_tasks, scheduler_output = self.scheduler.schedule(
                    tasks, prev_workers, self.n_workers, worker_status
                )
                logger.debug(f"scheduled {len(scheduled_tasks)} tasks")
                self._update_task_tracker_with_scheduler_output(
                    scheduled_tasks, scheduler_output
                )

                await self._process_output_and_update_tracker()
                await self._execute_scheduler_output(scheduled_tasks, scheduler_output)

        except Exception as e:
            logger.error(f"Exception in engine core loop: {e}")
            raise
        finally:
            logger.info("Received shutdown signal, call engine shutdown")
            self.shutdown()

    def shutdown(self):
        logger.info("Shutting down engine")
        self._running = False
        logger.info("Sending shutdown signal to worker client")
        try:
            loop = asyncio.get_running_loop()
            tasks = [
                t
                for t in asyncio.all_tasks(loop)
                if t is not asyncio.current_task()
                and not t.get_name().startswith("Server")
            ]  # Don't cancel uvicorn server tasks

            if tasks:
                logger.info(f"Cancelling {len(tasks)} pending tasks...")
                for task in tasks:
                    task.cancel()

                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        except RuntimeError:
            logger.warning(
                "No running loop found, seems like the engine is not running"
            )
        finally:
            self.worker_client.close()
            self.socket.close()
            self.zmq.term()

    async def _execute_scheduler_output(
        self, scheduled_tasks: BrowserWorkerTask, scheduler_output: SchedulerOutput
    ):
        """
        Allocate tasks to workers.
        """
        worker_tasks = defaultdict(list)

        for task in scheduled_tasks:
            worker_id = scheduler_output.task_assignments[task.task_id]
            task.engine_send_timestamp = time.time()
            worker_tasks[worker_id].append(task.to_dict())

        # Send batched tasks to each worker
        for worker_id, task_batch in worker_tasks.items():
            self.worker_client.send(task_batch, worker_id)
            logger.debug(f"sent batch of {len(task_batch)} tasks to worker {worker_id}")

        await asyncio.sleep(0)

    async def _process_output_and_update_tracker(self):
        output_queue_len = self.worker_client.get_output_queue_len()
        if output_queue_len == 0:
            await asyncio.sleep(0)
            return

        output_queue_len = min(output_queue_len, self.batch_size)
        while self.worker_client.get_output_queue_len() > 0:
            idx, msg = self.worker_client.get_output_nowait()
            logger.debug(f"received task {msg['task_id']} from worker {idx}")
            if msg["success"]:
                logger.debug(f"task {msg['task_id']} finished")
            else:
                logger.warning(f"task {msg['task_id']} failed")
            assert "task_id" in msg
            task_id = msg["task_id"]
            self.task_tracker[task_id]["status"] = "finished"
            msg["profile"]["engine_set_future_timestamp"] = time.time()
            await self._send(msg, self.task_id_to_identity[task_id], MsgType.REPLY)
            self.task_id_to_identity.pop(task_id)
            logger.debug(f"updated task {task_id} status to finished")
        await asyncio.sleep(0)

    def _update_task_tracker_with_scheduler_output(
        self, tasks: List[BrowserWorkerTask], scheduler_output: SchedulerOutput
    ):
        for task in tasks:
            self.task_tracker[task.task_id] = {
                "worker_id": scheduler_output.task_assignments[task.task_id],
                "task": task,
                "status": "pending",
            }
            self.context_tracker[task.context_id] = scheduler_output.task_assignments[
                task.task_id
            ]


class AsyncBrowserEngineAsyncClient(BrowserEngine):
    def __init__(self, config: BrowserEngineConfig):
        self.config = config
        self.engine_config = self.config.engine_config
        self.scheduler = make_scheduler(self.config.scheduler_config)
        self.worker_client = WorkerClient.make_client(self.config.worker_client_config)
        self._running = False

        self.task_tracker = {}
        self.context_tracker = {}

        self.batch_size = self.config.scheduler_config["max_batch_size"]
        self.n_workers = self.config.worker_client_config["num_workers"]
        self.waiting_queue = asyncio.Queue()

        self.task_id_to_identity = {}
        self.zmq = zmq.asyncio.Context(io_threads=1)
        self.socket = make_zmq_socket(
            self.zmq, self.engine_config["app_to_engine_socket"], zmq.ROUTER, bind=True
        )

        self.encoder = MsgpackEncoder()
        self.decoder = MsgpackDecoder()

    async def add_task_async(self, task: BrowserWorkerTask):
        if not task.context_id:
            context_id = f"{uuid.uuid4().hex[:8]}"
            task.context_id = context_id
            self.context_tracker[context_id] = -1
        else:
            if task.context_id not in self.context_tracker:
                self.context_tracker[task.context_id] = -1

        task.engine_recv_timestamp = time.time()
        await self.waiting_queue.put(task)
        logger.info(f"added task {task.task_id} to waiting queue")

    async def _recv(self):
        msg = await self.socket.recv_multipart()
        assert len(msg) == 3
        identity = msg[0]
        msg_type = msg[1]
        return identity, msg_type, self.decoder(msg[2])

    async def _send(self, msg, identity, msg_type):
        await self.socket.send_multipart([identity, msg_type, self.encoder(msg)])

    async def _recv_loop(self):
        while self._running:
            identity, msg_type, msg = await self._recv()
            if msg_type == MsgType.TASK:
                task = BrowserWorkerTask(**msg)
                task_id = task.task_id
                self.task_id_to_identity[task_id] = identity
                await self.add_task_async(task)
            else:
                raise ValueError(f"Unknown message type: {msg_type}")

    async def _send_loop(self):
        while self._running:
            await self._process_output_and_update_tracker()

    async def _engine_core_loop(self):
        """Main engine loop that processes tasks and manages workers"""
        try:
            while self._running:
                tasks = []
                prev_workers = []

                if self.waiting_queue.empty():
                    task = await self.waiting_queue.get()
                    tasks.append(task)
                    prev_workers.append(self.context_tracker[task.context_id])

                # assert tasks, "No tasks in waiting queue, this should not happen"
                while not self.waiting_queue.empty() and len(tasks) < self.batch_size:
                    task = self.waiting_queue.get_nowait()
                    tasks.append(task)
                    prev_workers.append(self.context_tracker[task.context_id])

                worker_status = self.worker_client.get_worker_status_no_wait()

                scheduled_tasks, scheduler_output = self.scheduler.schedule(
                    tasks, prev_workers, self.n_workers, worker_status
                )
                logger.debug(
                    f"scheduled_tasks: {scheduled_tasks}, scheduler_output: {scheduler_output}"
                )

                self._update_task_tracker_with_scheduler_output(
                    scheduled_tasks, scheduler_output
                )
                await self._execute_scheduler_output(scheduled_tasks, scheduler_output)

        except Exception as e:
            logger.error(f"Exception in engine core loop: {e}")
            raise
        finally:
            logger.info("Received shutdown signal, call engine shutdown")
            self.shutdown()

    async def start(self):
        self._running = True
        loop = asyncio.get_running_loop()

        await self.worker_client.wait_for_workers_ready()

        loop.create_task(self._recv_loop())
        loop.create_task(self._send_loop())
        loop.create_task(self._engine_core_loop())
        loop.create_task(self.worker_client.run_recv_loop())

    def shutdown(self):
        logger.info("Shutting down engine")
        self._running = False
        logger.info("Sending shutdown signal to worker client")
        try:
            loop = asyncio.get_running_loop()
            tasks = [
                t
                for t in asyncio.all_tasks(loop)
                if t is not asyncio.current_task()
                and not t.get_name().startswith("Server")
            ]  # Don't cancel uvicorn server tasks

            if tasks:
                logger.info(f"Cancelling {len(tasks)} pending tasks...")
                for task in tasks:
                    task.cancel()

                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        except RuntimeError:
            logger.warning(
                "No running loop found, seems like the engine is not running"
            )
        finally:
            self.worker_client.close()
            self.socket.close()
            self.zmq.term()

    async def _execute_scheduler_output(
        self, scheduled_tasks: BrowserWorkerTask, scheduler_output: SchedulerOutput
    ):
        """
        Allocate tasks to workers.
        """
        worker_tasks = defaultdict(list)

        for task in scheduled_tasks:
            worker_id = scheduler_output.task_assignments[task.task_id]
            task.engine_send_timestamp = time.time()
            worker_tasks[worker_id].append(task.to_dict())

        # Send batched tasks to each worker
        for worker_id, task_batch in worker_tasks.items():
            await self.worker_client.send(task_batch, worker_id)
            logger.debug(f"sent batch of {len(task_batch)} tasks to worker {worker_id}")

    async def _process_output_and_update_tracker(self):
        idx, msg = await self.worker_client.get_output()
        logger.debug(f"received task {msg['task_id']} from worker {idx}")
        if msg["success"]:
            logger.debug(f"task {msg['task_id']} finished")
        else:
            logger.warning(f"task {msg['task_id']} failed")
        assert "task_id" in msg
        task_id = msg["task_id"]
        self.task_tracker[task_id]["status"] = "finished"
        msg["profile"]["engine_set_future_timestamp"] = time.time()
        await self._send(msg, self.task_id_to_identity[task_id], MsgType.REPLY)
        self.task_id_to_identity.pop(task_id)

    def _update_task_tracker_with_scheduler_output(
        self, tasks: List[BrowserWorkerTask], scheduler_output: SchedulerOutput
    ):
        for task in tasks:
            self.task_tracker[task.task_id] = {
                "worker_id": scheduler_output.task_assignments[task.task_id],
                "task": task,
                "status": "pending",
            }
            self.context_tracker[task.context_id] = scheduler_output.task_assignments[
                task.task_id
            ]
