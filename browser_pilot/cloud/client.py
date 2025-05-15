import asyncio
import collections
import concurrent.futures
import queue
import struct
import threading
import time
import uuid
from concurrent.futures import Future
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
import uvloop

from browser_pilot.utils import Serializer


class MsgType:
    INITIALIZE = "__init__"
    CLOSE = "close"
    RESET = "reset"
    STEP = "step"


class CloudClient:
    def __init__(self, url: str = "ws://localhost:9999/send_and_wait"):
        self._serializer = Serializer(serializer="orjson")

        self._session = None
        self._url = url
        self._ws = None
        self._max_msg_size = 1024 * 1024 * 100
        self._send_queue = queue.Queue()

        self._msg_id_to_future = {}
        self._waiting_queue = collections.deque()  # (timestamp, msg_id)
        self._loop: asyncio.AbstractEventLoop = None
        self._is_running = False
        self._num_threads = 1
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._num_threads
        )

        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()

    def send(self, msg: Any) -> None:
        msg_id = str(uuid.uuid4())
        self._msg_id_to_future[msg_id] = Future()
        self._waiting_queue.append((time.time(), msg_id))
        self._send_queue.put(self._serializer.dumps([msg_id, msg]))
        return self._msg_id_to_future[msg_id]

    def close(self, timeout=5):
        self._is_running = False
        for _ in range(2 * self._num_threads):
            self._send_queue.put("__SHUTDOWN__")

        async def cleanup():
            if self._ws and not self._ws.closed:
                await self._ws.close()
            if self._session and not self._session.closed:
                await self._session.close()

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
                    print(f"Error waiting for tasks to complete: {e}")

        if self._loop and self._loop.is_running():
            try:
                cleanup_future = asyncio.run_coroutine_threadsafe(cleanup(), self._loop)
                cleanup_future.result(timeout=timeout)
            except Exception as e:
                print(f"Error in cleanup: {e}")

        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception as e:
                print(f"Error stopping loop: {e}")

        start_time = time.time()
        while self._loop and self._loop.is_running():
            if time.time() - start_time > timeout:
                print(
                    "Loop still running despite attempts to stop, trying to forcefully stop"
                )
                try:
                    self._loop.stop()
                except Exception as e:
                    print(f"Error forcefully stopping loop: {e}")
                break

        if self._loop and not self._loop.is_closed():
            try:
                self._loop.close()
            except Exception as e:
                print(f"Error closing loop: {e}")

        if self._loop and not self._loop.is_closed():
            print(
                "Cannot close loop, last resort to gc, this might lead to OSError if happen too often"
            )

        self._loop = None

        if self._executor and not self._executor._shutdown:
            self._executor.shutdown(wait=False, cancel_futures=True)

        if self._thread.is_alive():
            self._thread.join(timeout)

        if self._thread.is_alive():
            print(
                f"Thread did not terminate within {timeout}s timeout, cannot forcefully terminate thread in Python"
            )

        self._send_queue = None
        for future in self._msg_id_to_future.values():
            future.set_exception(Exception("Cloud client is closed"))
        self._msg_id_to_future = None

    def _run_async_loop(self):
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        connect_future = asyncio.ensure_future(self._connect())
        self._loop.run_until_complete(connect_future)
        self._is_running = True

        if connect_future.result():
            self._loop.create_task(self._send_loop())
            self._loop.create_task(self._recv_loop())
        else:
            raise Exception("Failed to connect to the server")

        try:
            self._loop.run_forever()
        except Exception as e:
            print(f"Error in the event loop: {e}")

    async def _connect(self):
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(
            self._url, max_msg_size=self._max_msg_size
        )
        return True

    async def _send_loop(self):
        while self._is_running:
            if self._send_queue.empty():
                msg = await self._loop.run_in_executor(
                    self._executor, self._send_queue.get
                )
            else:
                msg = self._send_queue.get()
            if msg == "__SHUTDOWN__":
                break
            await self._ws.send_str(msg)

    async def _recv_loop(self):
        while self._is_running:
            if self._waiting_queue:
                start_time, msg_id = self._waiting_queue[0]
                if time.time() - start_time > 60:
                    self._waiting_queue.popleft()
                    future = self._msg_id_to_future.pop(msg_id, None)
                    if future:
                        future.set_exception(Exception("Timeout waiting for response"))
                        continue
            try:
                msg = await self._ws.receive(timeout=5)
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
                    self._is_running = False
                    break
                else:
                    print("Received message of unknown type:", msg.type)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                import traceback

                print("Unexpected error in recv loop:", e, traceback.format_exc())
