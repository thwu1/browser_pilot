import asyncio
import collections
import concurrent.futures
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Any, Optional

import aiohttp
import uvloop

from browser_pilot.utils import Serializer

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("client.log")],
    force=True,
)
logger = logging.getLogger(__name__)


class MsgType:
    INITIALIZE = "__init__"
    CLOSE = "close"
    RESET = "reset"
    STEP = "step"


class CloudClient:
    def __init__(
        self,
        url: str = "ws://localhost:9999/send_and_wait",
        max_concurrency: Optional[int] = None,
    ):
        self._serializer = Serializer(serializer="orjson")

        self._session = None
        self._url = url
        self._max_concurrency = max_concurrency
        self._wss = {}
        self._max_msg_size = 1024 * 1024 * 100
        self._send_queue = queue.Queue()  # (msg, wsid)

        self._msg_id_to_future = {}
        self._waiting_queue = collections.deque()  # (timestamp, msg_id)
        self._loop: asyncio.AbstractEventLoop = None
        self._send_running = False
        self._recv_running = {}
        self._num_threads = 1
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._num_threads
        )
        self._receive_timeout = 5
        self._future_timeout = 60
        self._loop_started = threading.Event()

        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()
        self._loop_started.wait()

    def send(self, msg: Any, wsid: str) -> Future:
        msg_id = str(uuid.uuid4())
        self._msg_id_to_future[msg_id] = Future()
        self._waiting_queue.append((time.time(), msg_id))
        self._send_queue.put((self._serializer.dumps([msg_id, msg]), wsid))
        return self._msg_id_to_future[msg_id]

    def register_env(self, env_uuid: str, timeout=5):
        connect_fut = asyncio.run_coroutine_threadsafe(
            self._connect(env_uuid), self._loop
        )
        try:
            connect_fut.result(timeout=timeout)
        except Exception as e:
            connect_fut.cancel()
            self.unregister_env(env_uuid, timeout=timeout)
            raise e

        start_event = threading.Event()
        self._recv_running[env_uuid] = True
        asyncio.run_coroutine_threadsafe(
            self._recv_loop(env_uuid, start_event), self._loop
        )
        start_event.wait()

        logger.debug(f"Registered env {env_uuid}")

    def unregister_env(self, env_uuid: str, timeout=5):
        self._recv_running[env_uuid] = False
        ws = self._wss.pop(env_uuid, None)
        if ws and not ws.closed:
            fut = asyncio.run_coroutine_threadsafe(ws.close(), self._loop)
            fut.result(timeout=timeout)
        logger.debug(f"Unregistered env {env_uuid}")

    def close(self, timeout=5):
        self._send_running = False
        for key in self._recv_running:
            self._recv_running[key] = False

        for _ in range(2 * self._num_threads):
            self._send_queue.put(("__SHUTDOWN__", None))

        self._stop_and_close_loop(timeout)

        if self._executor and not self._executor._shutdown:
            self._executor.shutdown(wait=False, cancel_futures=True)

        if self._thread.is_alive():
            self._thread.join(timeout)

        if self._thread.is_alive():
            logger.warning(
                f"Thread did not terminate within {timeout}s timeout, cannot forcefully terminate thread in Python, this might lead to OSError"
            )

        self._send_queue = None
        for future in self._msg_id_to_future.values():
            if not future.done():
                future.set_exception(RuntimeError("Cloud client is closed"))
        self._msg_id_to_future = None

    async def _close_wss_and_session(self):
        tasks = []
        for ws in self._wss.values():
            if ws and not ws.closed:
                tasks.append(ws.close())
        if tasks:
            await asyncio.gather(*tasks)

        self._wss = None

        if self._session and not self._session.closed:
            await self._session.close()

        self._session = None

    def _stop_and_close_loop(self, timeout=5):
        async def cleanup():
            await self._close_wss_and_session()

            tasks = [
                t
                for t in asyncio.all_tasks(self._loop)
                if t is not asyncio.current_task()
            ]
            if tasks:
                for task in tasks:
                    task.cancel()

                try:
                    await asyncio.wait(tasks, timeout=timeout)
                except Exception as e:
                    logger.error(f"Error waiting for tasks to complete: {e}")

        if self._loop and self._loop.is_running():
            try:
                cleanup_future = asyncio.run_coroutine_threadsafe(cleanup(), self._loop)
                cleanup_future.result(timeout=timeout)
            except Exception as e:
                logger.error(f"Error in cleanup: {e}")

        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception as e:
                logger.error(f"Error stopping loop: {e}")

        start_time = time.time()
        while self._loop and self._loop.is_running():
            if time.time() - start_time > timeout:
                logger.warning(
                    "Loop still running despite attempts to stop, trying to forcefully stop"
                )
                try:
                    self._loop.stop()
                except Exception as e:
                    logger.error(f"Error forcefully stopping loop: {e}")
                break

        if self._loop and not self._loop.is_closed():
            try:
                self._loop.close()
            except Exception as e:
                logger.error(f"Error closing loop: {e}")

        if self._loop and not self._loop.is_closed():
            logger.warning(
                "Cannot close loop, last resort to gc, this might lead to OSError if happen too often"
            )

        self._loop = None

    def _run_async_loop(self):
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        if self._max_concurrency:
            connector = aiohttp.TCPConnector(
                limit=self._max_concurrency,
                limit_per_host=self._max_concurrency,
                loop=self._loop,
                enable_cleanup_closed=True,
            )
        else:
            # default connector, has limit of 100
            connector = None
        self._session = aiohttp.ClientSession(loop=self._loop, connector=connector)

        self._send_running = True
        self._loop.create_task(self._send_loop())
        self._loop.create_task(self._future_timeout_loop())

        try:
            self._loop.run_forever()
        except Exception as e:
            logger.error(f"Error in the event loop: {e}")

    async def _connect(self, wsid: str):
        self._wss[wsid] = await self._session.ws_connect(
            self._url, max_msg_size=self._max_msg_size
        )

    async def _send_loop(self):
        self._loop_started.set()
        while self._send_running:
            if self._send_queue.empty():
                msg, wsid = await self._loop.run_in_executor(
                    self._executor, self._send_queue.get
                )
            else:
                msg, wsid = self._send_queue.get()
            logger.debug(f"[SEND] {msg} to {wsid}")
            if msg == "__SHUTDOWN__":
                break
            if wsid in self._wss and not self._wss[wsid].closed:
                await self._wss[wsid].send_str(msg)
            else:
                logger.warning(
                    f"WebSocket {wsid} might have been closed, shouldn't send message"
                )

    async def _future_timeout_loop(self):
        while self._send_running:
            await asyncio.sleep(10)
            logger.debug(f"wss: {self._wss}, {time.time()}")
            if self._waiting_queue:
                start_time, msg_id = self._waiting_queue[0]
                if time.time() - start_time > self._future_timeout:
                    self._waiting_queue.popleft()
                    future = self._msg_id_to_future.pop(msg_id, None)
                    if future and not future.done():
                        future.set_exception(Exception("Timeout waiting for response"))

    async def _recv_loop(self, wsid, start_event: threading.Event):
        ws = self._wss[wsid]
        start_event.set()
        logger.debug(f"Received loop for {wsid} started")
        while self._recv_running[wsid]:
            try:
                msg = await ws.receive()
                logger.debug(f"[RECV] msg.type = {msg.type} from {wsid}")
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = self._serializer.loads(msg.data)
                    future = self._msg_id_to_future.pop(data["task_id"], None)
                    if future is None:
                        continue
                    future.set_result(data)
                elif (
                    msg.type == aiohttp.WSMsgType.CLOSED
                    or msg.type == aiohttp.WSMsgType.CLOSE
                    or msg.type == aiohttp.WSMsgType.ERROR
                    or msg.type == 256
                ):
                    self._recv_running[wsid] = False
                    break
                else:
                    logger.warning(f"Received message of unknown type: {msg.type}")
            except Exception as e:
                logger.error(
                    f"Receive Loop for {wsid} failed due to {e}, likely it's been closed"
                )
                break
        logger.debug(f"Received loop for {wsid} stopped")
