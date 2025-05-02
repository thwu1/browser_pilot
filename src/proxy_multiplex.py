import argparse
import asyncio
from collections import defaultdict
from serializer import Serializer
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp
from fastapi.websockets import WebSocketState
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from monitoring.store import MonitorClient
from task_tracker import TaskTracker
from util import get_worker_id
import uvloop

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("proxy_multiplex_8192.log"),
    ],
)
logger = logging.getLogger(__name__)


class ResponseType:
    EVENT = "event"
    RESULT = "result"
    ERROR = "error"


class NtoMProxy:
    def __init__(self, target_wss: List[str], port: int):
        self.target_wss = target_wss
        self.port = port
        self.persistent_session = None
        self.persistent_wss = [None] * len(target_wss)
        self.serializer = Serializer()

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await self.start_connection()
            asyncio.create_task(self.request_consumer())
            for tsid in range(len(self.target_wss)):
                asyncio.create_task(self.response_consumer(tsid))
            yield
            await self.close_connection()

        self.app = FastAPI(lifespan=lifespan)
        self.app.websocket("/")(self.connect)

        self.gids = [0] * len(self.target_wss)

        self.gid_tsid_to_lid_wsid: Dict[Tuple[int, int], Tuple[int, int]] = (
            {}
        )  # (global id, target socket id) -> (local id, wsid)
        self.wsid_to_guids = defaultdict(set)
        self.guid_to_wsid: Dict[str, int] = {}
        self.wsid_to_ws: Dict[int, WebSocket] = {}
        self.wsid_to_tsid: Dict[int, int] = (
            {}
        )  # assignment of a client to a target socket
        self.tsid_active_count = [0] * len(self.target_wss)

        self.request_queue: asyncio.Queue[Tuple[int, int, dict]] = asyncio.Queue()

        self.wait_for_trace_queue: List[asyncio.Queue[Tuple[int, dict]]] = [
            asyncio.Queue() for _ in range(len(self.target_wss))
        ]
        self.wait_for_artifact_queue: List[asyncio.Queue[Tuple[int, dict]]] = [
            asyncio.Queue() for _ in range(len(self.target_wss))
        ]

        self.initialize_msg_reply = [
            [] for _ in range(len(self.target_wss))
        ]  # get this from target_ws

    async def assign(self, wsid: int):
        least_connect_tsid = self.tsid_active_count.index(min(self.tsid_active_count))
        self.wsid_to_tsid[wsid] = least_connect_tsid
        self.tsid_active_count[least_connect_tsid] += 1
        logger.debug(f"ASSIGN: {wsid} -> {least_connect_tsid}")
        return least_connect_tsid

    async def start_connection(self):
        if self.persistent_session is None:
            self.persistent_session = aiohttp.ClientSession()

        header = {
            "user-agent": "Playwright/1.51.1 (x64; ubuntu 24.04) python/3.11",
            "x-playwright-proxy": "",
            "x-playwright-browser": "chromium",
            "sec-websocket-version": "13",
            "sec-websocket-key": "NSWDAUixXVERPOVHHFe3lg==",
            "connection": "Upgrade",
            "upgrade": "websocket",
            "sec-websocket-extensions": "permessage-deflate; client_no_context_takeover; client_max_window_bits",
            "host": f"localhost:{self.port}",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
        }

        self.persistent_wss = [
            await self.persistent_session.ws_connect(self.target_wss[i], headers=header)
            for i in range(len(self.target_wss))
        ]

        for i in range(len(self.target_wss)):
            self.gids[i] += 1
            await self.persistent_wss[i].send_str(
                self.serializer.dumps(
                    {
                        "id": self.gids[i],
                        "guid": "",
                        "method": "initialize",
                        "params": {"sdkLanguage": "python"},
                        "metadata": {
                            "wallTime": time.time(),
                            "apiName": "Connection.init",
                            "internal": False,
                            "location": {
                                "file": "/home/tianhao/miniconda3/envs/agentlab/lib/python3.11/asyncio/runners.py",
                                "line": 118,
                                "column": 0,
                            },
                        },
                    }
                )
            )
        logger.debug("Sent initialize message")

        async def listen_to_ws(i):
            logger.debug(f"Listening to {self.target_wss[i]}")
            async for msg in self.persistent_wss[i]:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    raise ValueError(f"Unknown message type: {msg.type}")

                data = self.serializer.loads(msg.data)
                msg_id = data.get("id", None)
                if msg_id is None or msg_id == self.gids[i]:
                    self.initialize_msg_reply[i].append(msg.data)
                    if msg_id == self.gids[i]:
                        break
                else:
                    raise ValueError(f"Unknown message: {msg.data}")
            logger.debug(f"Received all initialize messages from {i}")

        await asyncio.gather(*[listen_to_ws(i) for i in range(len(self.target_wss))])

    async def close_connection(self):
        tasks = [
            ws.close()
            for ws in self.wsid_to_ws.values()
            if ws.client_state == WebSocketState.CONNECTED
        ]
        await asyncio.gather(*tasks)
        await self.persistent_session.close()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()

        wsid = id(websocket)
        self.wsid_to_ws[wsid] = websocket
        tsid = await self.assign(wsid)

        try:
            while True:
                msg = await websocket.receive()

                if msg["type"] == "websocket.disconnect":
                    break

                if msg["type"] == "websocket.receive":
                    if "text" in msg and msg["text"]:
                        text_msg = msg["text"]
                        data = self.serializer.loads(text_msg)
                        await self.request_queue.put((wsid, tsid, data))
                    elif "bytes" in msg and msg["bytes"]:
                        logger.error(
                            f"Forwarding binary message: {len(msg['bytes'])} bytes"
                        )
                        break
                    else:
                        raise ValueError(f"Unknown message type: {msg}")
        except WebSocketDisconnect:
            logger.debug(f"Client disconnected for wsid: {wsid}")
        except Exception as e:
            logger.error(f"Error in connect: {e}")
            raise e
        finally:
            logger.debug(f"Client disconnected for wsid: {wsid}")
            self.wsid_to_ws.pop(wsid)
            self.tsid_active_count[tsid] -= 1
            assert self.tsid_active_count[tsid] >= 0
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
            for guid in self.wsid_to_guids[wsid]:
                self.guid_to_wsid.pop(guid)
            self.wsid_to_guids.pop(wsid)

    async def handle_request(self, wsid: str, tsid: int, data: dict):
        if data.get("method", None) == "initialize":
            local_id = data["id"]
            ws = self.wsid_to_ws[wsid]
            for msg in self.initialize_msg_reply[tsid][:-1]:
                await ws.send_text(msg)

            reply = self.serializer.loads(self.initialize_msg_reply[tsid][-1])
            reply["id"] = local_id
            await ws.send_text(self.serializer.dumps(reply))
            return

        self.gids[tsid] += 1
        gid = self.gids[tsid]
        assert data.get("id", None) is not None
        self.gid_tsid_to_lid_wsid[(gid, tsid)] = (data["id"], wsid)

        # listen for trace or artifact, they'll return new guids never seen before
        if data.get("method", None) == "newContext":
            logger.debug(f"UNRESOLVED: {data} from {wsid}")
            await self.wait_for_trace_queue[tsid].put((wsid, data))
            if data.get("params", {}).get("recordVideo", None) is not None:
                await self.wait_for_artifact_queue[tsid].put((wsid, data))

        guids = []
        self.parse_guid_from_nested_data(data, guids)
        await self.update_guid(wsid, guids)

        data["id"] = gid
        logger.debug(f"FORWARD: {data}")
        await self.persistent_wss[tsid].send_str(self.serializer.dumps(data))

    async def handle_response(self, msg: aiohttp.WSMsgType, tsid: int):
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = self.serializer.loads(msg.data)
            response_type = await self.response_type(data)
            if response_type == ResponseType.RESULT:
                local_id, wsid = self.gid_tsid_to_lid_wsid.pop((data["id"], tsid))
                ws = self.wsid_to_ws[wsid]
                guids = []
                self.parse_guid_from_nested_data(data, guids)
                await self.update_guid(wsid, guids)
                # modify the id
                data["id"] = local_id
                logger.debug(f"BACKWARD: {data}")
                await ws.send_text(self.serializer.dumps(data))
            elif response_type == ResponseType.EVENT:
                guids = []
                self.parse_guid_from_nested_data(data, guids)
                wsid = await self.findout_wsid_from_guids(guids, tsid, data)
                if wsid is None:
                    logger.warn(f"Failed to find wsid for {data}")
                    return
                await self.update_guid(wsid, guids)
                ws = self.wsid_to_ws[wsid]
                logger.debug(f"BACKWARD: {data}")
                await ws.send_text(msg.data)
            elif response_type == ResponseType.ERROR:
                logger.error(
                    f"Error: {data}, shouldn't happen as error should come with an id."
                )

    def parse_guid_from_nested_data(self, data: Union[dict, list], ls: List[str]):
        if isinstance(data, dict):
            if "guid" in data and data["guid"] != "":
                ls.append(data["guid"])
            for v in data.values():
                if isinstance(v, dict) or isinstance(v, list):
                    self.parse_guid_from_nested_data(v, ls)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) or isinstance(item, list):
                    self.parse_guid_from_nested_data(item, ls)

    async def response_type(self, data: dict):
        if data.get("id", None) is not None:
            return ResponseType.RESULT
        elif data.get("method", None) is not None:
            return ResponseType.EVENT
        elif data.get("error", None) is not None:
            return ResponseType.ERROR
        else:
            raise ValueError(f"Unknown message type: {data}")

    async def findout_wsid_from_guids(self, guids: List[str], tsid: int, data: dict):
        for guid in guids:
            if "browser@" in guid:
                continue
            wsid = self.guid_to_wsid.get(guid, None)
            if wsid is not None:
                logger.debug(f"FOUND by connect: {guids} -> {wsid}")
                return wsid

        # now its unresolved
        logger.debug(
            f"Unresolved: {data}\n"
            f"Wait for trace queue for {tsid} is {self.wait_for_trace_queue[tsid].qsize()}\n"
            f"Wait for artifact queue for {tsid} is {self.wait_for_artifact_queue[tsid].qsize()}"
        )
        if (
            data.get("method", None) == "__create__"
            and data.get("params", {}).get("type", None) == "Tracing"
        ):
            wsid, _ = await asyncio.wait_for(
                self.wait_for_trace_queue[tsid].get(), timeout=1
            )
            logger.debug(f"FOUND by unresolved: {guids} -> {wsid}")
            return wsid
        elif (
            data.get("method", None) == "__create__"
            and data.get("params", {}).get("type", None) == "Artifact"
        ):
            wsid, _ = await asyncio.wait_for(
                self.wait_for_artifact_queue[tsid].get(), timeout=1
            )
            logger.debug(f"FOUND by unresolved: {guids} -> {wsid}")
            return wsid
        else:
            return None

    async def update_guid(self, wsid: int, guids: List[str]):
        for guid in guids:
            if "browser@" in guid:
                continue
            self.guid_to_wsid[guid] = wsid
            self.wsid_to_guids[wsid].add(guid)

    async def request_consumer(self):
        while True:
            wsid, tsid, data = await self.request_queue.get()
            try:
                await self.handle_request(wsid, tsid, data)
            except Exception as e:
                logger.error(f"Error in request_consumer: {e}")

    async def response_consumer(self, tsid: int):
        async for msg in self.persistent_wss[tsid]:
            try:
                await self.handle_response(msg, tsid)
            except Exception as e:
                logger.error(f"Error in response_consumer: {e}")


# uvicorn src.proxy_multiplex:app --host 0.0.0.0 --port 8000 --workers 8

NUM_WORKERS = 8
TOTAL_TARGETS = 32
worker_id = get_worker_id() % NUM_WORKERS
each_worker_num_targets = TOTAL_TARGETS // NUM_WORKERS
targets = [
    f"ws://localhost:{9214 + i}"
    for i in range(
        worker_id * each_worker_num_targets, (worker_id + 1) * each_worker_num_targets
    )
]

proxy = NtoMProxy(targets, 8000)
app = proxy.app
app.add_middleware(CORSMiddleware, allow_origins=["*"])
