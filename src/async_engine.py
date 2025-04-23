import asyncio
import logging
import time
import uuid
from collections import defaultdict
from typing import Dict, List

from engine import BrowserEngine, BrowserEngineConfig, BrowserWorkerTask
from scheduler import SchedulerOutput
from timer_util import Timer
import zmq
from utils import make_zmq_socket, MsgpackDecoder, MsgpackEncoder, MsgType

import traceback
import uvloop

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AsyncBrowserEngine(BrowserEngine):
    def __init__(self, config: BrowserEngineConfig):
        super().__init__(config)
        self.waiting_queue = asyncio.Queue()
        # self.task_id_to_future: Dict[str, asyncio.Future] = {}
        self.task_id_to_identity = {}
        self.zmq = zmq.asyncio.Context(io_threads=1)
        self.socket = make_zmq_socket(
            self.zmq, "ipc://app_to_engine.sock", zmq.ROUTER, bind=True
        )

        self.encoder = MsgpackEncoder()
        self.decoder = MsgpackDecoder()

    async def add_task(self, task: BrowserWorkerTask):
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

        # self.task_id_to_future[task.task_id] = asyncio.Future()
        # return self.task_id_to_future[task.task_id]

    async def add_batch_tasks(self, tasks: List[BrowserWorkerTask]):
        futures = [self.add_task(task) for task in tasks]
        return await asyncio.gather(*futures)

    async def _recv(self):
        msg = await self.socket.recv_multipart()
        assert len(msg) == 3
        identity = msg[0]
        msg_type = msg[1]
        return identity, msg_type, self.decoder(msg[2])

    async def _send(self, msg, identity, msg_type):
        await self.socket.send_multipart([identity, msg_type, self.encoder(msg)])

    async def process_incoming(self):
        while self._running:
            identity, msg_type, msg = await self._recv()
            if msg_type == MsgType.TASK:
                task = BrowserWorkerTask(**msg)
                task_id = task.task_id
                self.task_id_to_identity[task_id] = identity
                await self.add_task(task)
            else:
                raise ValueError(f"Unknown message type: {msg_type}")

    # async def process_outgoing(self):
    #     while self._running:

    async def engine_core_loop(self):
        """Main engine loop that processes tasks and manages workers"""
        self._running = True

        try:
            while self._running:
                tasks = []
                prev_workers = []
                while not self.waiting_queue.empty() and len(tasks) < self.batch_size:
                    logger.debug(f"waiting queue size: {self.waiting_queue.qsize()}")
                    task = await self.waiting_queue.get()
                    tasks.append(task)
                    prev_workers.append(self.context_tracker[task.context_id])

                if not tasks:
                    logger.debug(f"no tasks in waiting queue, processing outputs")
                    await self._process_output_and_update_tracker()
                    continue

                worker_status = self.worker_client.get_worker_status_no_wait()

                # with Timer(
                #     "Scheduler.schedule", log_file="timer_scheduler.log"
                # ):  # Monitor scheduler timing
                scheduled_tasks, scheduler_output = self.scheduler.schedule(
                    tasks, prev_workers, self.n_workers, worker_status
                )
                logger.debug(f"scheduled_tasks: {scheduled_tasks}")
                logger.debug(f"scheduler_output: {scheduler_output}")

                # with Timer(
                #     "_execute_scheduler_output",
                #     log_file="timer_execute_scheduler_output.log",
                # ):
                await self._execute_scheduler_output(scheduled_tasks, scheduler_output)

                # with Timer(
                #     "_update_task_tracker_with_scheduler_output",
                #     log_file="timer_update_task_tracker_with_scheduler_output.log",
                # ):
                self._update_task_tracker_with_scheduler_output(
                    scheduled_tasks, scheduler_output
                )

                await self._process_output_and_update_tracker()

        except Exception as e:
            logger.error(f"Exception in engine core loop: {e}")
            raise
        finally:
            logger.info("Received shutdown signal, call engine shutdown")
            await self._shutdown()

    @classmethod
    def spin_up_engine(cls, config: Dict):
        engine = cls(BrowserEngineConfig(**config))

        async def run():
            # asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            tasks = [
                engine.engine_core_loop(),
                engine.process_incoming(),
            ]
            await asyncio.gather(*tasks)

        try:
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            asyncio.run(run())
        except Exception as e:
            logger.error(f"Fatal error in engine: {e}, {traceback.format_exc()}")
        finally:
            engine._shutdown()

    async def _shutdown(self):
        logger.info("Shutting down engine")
        self._running = False
        logger.info("Sending shutdown signal to worker client")
        self.worker_client.close()

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
            task_dict = task.to_dict()
            worker_tasks[worker_id].append(task_dict)

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

        # with Timer(
        #     "_process_output_and_update_tracker",
        #     log_file="timer_process_output_and_update_tracker.log",
        # ):
        output_queue_len = min(output_queue_len, 128)
        # for _ in range(output_queue_len):
        while self.worker_client.get_output_queue_len() > 0:
            idx, msg = self.worker_client.get_output_nowait()
            logger.debug(f"received task {msg['task_id']} from worker {idx}")
            if not msg["result"]["success"]:
                logger.warning(f"task {msg['task_id']} failed")
            assert "task_id" in msg
            task_id = msg["task_id"]
            assert task_id not in self.output_dict
            self.output_dict[task_id] = msg
            self.task_tracker[task_id]["status"] = "finished"
            msg["profile"]["engine_set_future_timestamp"] = time.time()
            await self._send(msg, self.task_id_to_identity[task_id], MsgType.REPLY)
            self.task_id_to_identity.pop(task_id)
            logger.debug(f"updated task {task_id} status to finished")
        await asyncio.sleep(0)
