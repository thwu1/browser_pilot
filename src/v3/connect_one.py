import argparse
import asyncio
import json
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Union

import aiohttp
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocketState
from task_tracker import TaskTracker

from monitoring.store import MonitorClient

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[logging.StreamHandler(), logging.FileHandler("connect_one.log")],
)
logger = logging.getLogger(__name__)


class ResponseType:
    EVENT = "event"
    RESULT = "result"
    ERROR = "error"


class NtoOneProxy:
    def __init__(self, target_ws: str):
        self.persistent_session = None
        self.persistent_ws = None
        self.target_ws = target_ws

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await self.start_connection()
            asyncio.create_task(self.request_consumer())
            asyncio.create_task(self.response_consumer())
            yield

        self.app = FastAPI(lifespan=lifespan)
        self.app.websocket("/")(self.connect)

        self.gid = 0

        self.to_gid = {}  # (local id, wsid) -> global id
        self.gid_to_lid_wsid = {}  # global id -> (local id, wsid)
        self.guid_to_wsid = {}
        self.wsid_to_ws = {}

        self.request_queue = asyncio.Queue()

        self.unresolved_queue = asyncio.Queue()

        self.initialize_msg_reply = []  # get this from target_ws

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
            "host": "localhost:8000",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
        }

        self.persistent_ws = await self.persistent_session.ws_connect(
            self.target_ws, headers=header
        )
        self.gid += 1

        await self.persistent_ws.send_str(
            json.dumps(
                {
                    "id": self.gid,
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
        logger.info("Sent initialize message")
        async for msg in self.persistent_ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                logger.info(f"Received initialize message: {data}")
                if data.get("id", None) is None:
                    self.initialize_msg_reply.append(msg.data)
                elif data.get("id", None) == self.gid:
                    self.initialize_msg_reply.append(msg.data)
                    break
                else:
                    raise ValueError(f"Unknown message: {msg.data}")
            else:
                raise ValueError(f"Unknown message type: {msg.type}")

    async def connect(self, websocket: WebSocket):
        await websocket.accept()

        wsid = str(id(websocket))
        self.wsid_to_ws[wsid] = websocket

        try:
            while True:
                msg = await websocket.receive()

                if msg["type"] == "websocket.disconnect":
                    break

                if msg["type"] == "websocket.receive":
                    if "text" in msg and msg["text"]:
                        text_msg = msg["text"]
                        data = json.loads(text_msg)
                        await self.request_queue.put((wsid, data))
                    elif "bytes" in msg and msg["bytes"]:
                        logger.error(
                            f"Forwarding binary message: {len(msg['bytes'])} bytes"
                        )
                        break
                    else:
                        raise ValueError(f"Unknown message type: {msg}")
        except WebSocketDisconnect:
            logger.info(f"Client disconnected for wsid: {wsid}")
        except Exception as e:
            logger.error(f"Error in connect: {e}")
            raise e
        finally:
            self.wsid_to_ws.pop(wsid)
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()

    async def handle_request(self, wsid: str, data: dict):
        if data.get("method", None) == "initialize":
            local_id = data["id"]
            ws = self.wsid_to_ws[wsid]
            logger.debug(f"BACKWARD: {self.initialize_msg_reply[:-1]}")
            for msg in self.initialize_msg_reply[:-1]:
                await ws.send_text(msg)

            data = json.loads(self.initialize_msg_reply[-1])
            data["id"] = local_id
            logger.debug(f"BACKWARD: {data}")
            await ws.send_text(json.dumps(data))
            return

        self.gid += 1
        assert data.get("id", None) is not None
        self.to_gid[(wsid, data["id"])] = self.gid
        self.gid_to_lid_wsid[self.gid] = (data["id"], wsid)

        if data.get("method", None) == "newContext":
            await self.unresolved_queue.put((wsid, data))

        guids = []
        await self.parse_guid_from_nested_data(data, guids)
        for guid in guids:
            if "browser@" in guid:
                continue
            self.guid_to_wsid[guid] = wsid

        data["id"] = self.gid
        logger.debug(f"FORWARD: {data}")
        await self.persistent_ws.send_str(json.dumps(data))

    async def parse_guid_from_nested_data(self, data: Union[dict, list], ls: List[str]):
        if not isinstance(data, dict) and not isinstance(data, list):
            return
        if isinstance(data, dict):
            if "guid" in data and data["guid"] != "":
                ls.append(data["guid"])
            for k, v in data.items():
                await self.parse_guid_from_nested_data(v, ls)
        elif isinstance(data, list):
            for item in data:
                await self.parse_guid_from_nested_data(item, ls)

    async def response_type(self, data: dict):
        if data.get("id", None) is not None:
            return ResponseType.RESULT
        elif data.get("method", None) is not None:
            return ResponseType.EVENT
        elif data.get("error", None) is not None:
            return ResponseType.ERROR
        else:
            raise ValueError(f"Unknown message type: {data}")

    async def request_consumer(self):
        while True:
            wsid, data = await self.request_queue.get()
            logger.info(f"Received request: {data} from {wsid}")
            await self.handle_request(wsid, data)

    async def findout_wsid_from_guids(self, guids: List[str]):
        for guid in guids:
            if "browser@" in guid:
                continue
            wsid = self.guid_to_wsid.get(guid, None)
            if wsid is not None:
                logger.debug(f"FOUND by connect: {guids} -> {wsid}")
                return wsid

        # now its unresolved
        assert self.unresolved_queue.qsize() > 0
        wsid, _ = await self.unresolved_queue.get()
        logger.debug(f"FOUND by unresolved: {guids} -> {wsid}")
        for guid in guids:
            if "browser@" in guid:
                continue
            self.guid_to_wsid[guid] = wsid
        return wsid

    async def update_guid(self, wsid, guids: List[str]):
        for guid in guids:
            if "browser@" in guid:
                continue
            self.guid_to_wsid[guid] = wsid

    async def response_consumer(self):
        async for msg in self.persistent_ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                response_type = await self.response_type(data)
                if response_type == ResponseType.RESULT:
                    local_id, wsid = self.gid_to_lid_wsid[data["id"]]
                    ws = self.wsid_to_ws[wsid]
                    guids = []
                    await self.parse_guid_from_nested_data(data, guids)
                    for guid in guids:
                        if "browser@" in guid:
                            continue
                        self.guid_to_wsid[guid] = wsid

                    # modify the id
                    data["id"] = local_id
                    logger.debug(f"BACKWARD: {data}")
                    await ws.send_text(json.dumps(data))
                elif response_type == ResponseType.EVENT:
                    guids = []
                    await self.parse_guid_from_nested_data(data, guids)
                    wsid = await self.findout_wsid_from_guids(guids)
                    await self.update_guid(wsid, guids)
                    ws = self.wsid_to_ws[wsid]
                    logger.debug(f"BACKWARD: {data}")
                    await ws.send_text(msg.data)
                elif response_type == ResponseType.ERROR:
                    logger.error(f"Error: {data}")

            else:
                raise ValueError(f"Unknown message type: {msg.type}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--target-ws", type=str, default="ws://localhost:9214")
    args = parser.parse_args()
    proxy = NtoOneProxy(args.target_ws)
    proxy.app.add_middleware(CORSMiddleware, allow_origins=["*"])
    uvicorn.run(proxy.app, host="0.0.0.0", port=args.port)
