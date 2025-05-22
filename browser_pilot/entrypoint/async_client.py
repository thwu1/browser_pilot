import asyncio
import collections
import concurrent.futures
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Any, Dict, Optional

import aiohttp
import uvloop

from browser_pilot.utils import Serializer

import logging
import asyncio

logger = logging.getLogger(__name__)


class MsgType:
    INITIALIZE = "__init__"
    CLOSE = "close"
    RESET = "reset"
    STEP = "step"


class AsyncCloudClient:
    def __init__(
        self,
        url: str = "ws://localhost:9999/send_and_wait",
        max_concurrency: Optional[int] = None,
    ):
        self._serializer = Serializer(serializer="orjson")

        self._session = None
        self._url = url
        self._max_concurrency = max_concurrency
        self._wss: Dict[str, aiohttp.ClientWebSocketResponse] = {}
        self._max_msg_size = 1024 * 1024 * 100
        self._send_queue = asyncio.Queue()  # (msg, wsid)

        self._msg_id_to_future: Dict[str, asyncio.Future] = {}
        self._waiting_queue = collections.deque()  # (timestamp, msg_id)
        self._loop: asyncio.AbstractEventLoop = None
        self._send_running = False
        self._recv_running = {}

        self._receive_timeout = 5
        self._future_timeout = 60

        self._lock = threading.Lock()
        self._started_background_task = False

    async def send(self, msg: Any, wsid: str) -> asyncio.Future:
        msg_id = str(uuid.uuid4())
        self._msg_id_to_future[msg_id] = asyncio.Future()
        self._waiting_queue.append((time.time(), msg_id))
        await self._send_queue.put((self._serializer.dumps([msg_id, msg]), wsid))
        return self._msg_id_to_future[msg_id]

    async def register_env(self, env_uuid: str, timeout=5):
        self._loop = asyncio.get_running_loop()
        try:
            await self._connect(env_uuid)
        except Exception as e:
            await self.unregister_env(env_uuid, timeout=timeout)
            raise e

        logger.debug(f"Connected to {env_uuid} via ws {self._wss[env_uuid]}")

        start_event = asyncio.Event()
        self._recv_running[env_uuid] = True
        asyncio.create_task(self._recv_loop(env_uuid, start_event))
        await start_event.wait()

        logger.debug(f"Registered env {env_uuid}")

    async def unregister_env(self, env_uuid: str, timeout=5):
        self._recv_running[env_uuid] = False
        ws = self._wss.pop(env_uuid, None)
        if ws and not ws.closed:
            await ws.close()
        assert ws.closed
        logger.debug(f"Unregistered env {env_uuid}")

    async def close(self, timeout=5):
        self._send_running = False
        for key in self._recv_running:
            self._recv_running[key] = False

        await self._send_queue.put(("__SHUTDOWN__", None))
        await self._close_wss_and_session()

        self._send_queue = None
        for future in self._msg_id_to_future.values():
            if not future.done():
                future.set_exception(RuntimeError("Cloud client is closed"))
        self._msg_id_to_future = None

    def maybe_start_background_task(self):
        if self._started_background_task:
            return

        with self._lock:
            if self._started_background_task:
                return
            self._started_background_task = True

            self._loop = asyncio.get_running_loop()

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
            if self._session is None:
                self._session = aiohttp.ClientSession(
                    loop=self._loop, connector=connector
                )

                self._send_running = True
                self._loop.create_task(self._send_loop())
                self._loop.create_task(self._future_timeout_loop())

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

    async def _connect(self, wsid: str):
        self._wss[wsid] = await self._session.ws_connect(
            self._url, max_msg_size=self._max_msg_size
        )

    async def _send_loop(self):
        while self._send_running:
            msg, wsid = await self._send_queue.get()
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
            while self._waiting_queue:
                start_time, msg_id = self._waiting_queue[0]
                if time.time() - start_time <= self._future_timeout:
                    break

                self._waiting_queue.popleft()
                future = self._msg_id_to_future.pop(msg_id, None)
                if future and not future.done():
                    logger.debug(
                        f"Future timeout waiting for {time.time() - start_time} seconds, response {msg_id}"
                    )
                    future.set_exception(Exception("Timeout waiting for response"))

    async def _recv_loop(self, wsid, start_event: asyncio.Event):
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
