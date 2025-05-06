import argparse
import asyncio
import json
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import aiohttp
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from monitoring.store import MonitorClient
from v3.task_tracker import TaskTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("proxy.log")],
)
logger = logging.getLogger(__name__)

REPORT_STATUS = True
REPORT_STATUS_INTERVAL = 5


class WebSocketPool:
    def __init__(self, target_endpoints: List[str]):
        self.target_endpoints = target_endpoints
        self.current_index = 0
        self.active_connections: Dict[str, aiohttp.ClientWebSocketResponse] = {}
        self.sessions: Dict[str, aiohttp.ClientSession] = (
            {}
        )  # Store sessions separately
        self.connection_lock = asyncio.Lock()

        self.websocket_status = {
            endpoint: {
                "active_connections": 0,
                "finished_connections": 0,
                "error_connections": 0,
            }
            for endpoint in self.target_endpoints
        }

    def get_websocket_status(self) -> dict:
        return self.websocket_status

    def update_websocket_status(self, endpoint: str, type: str):
        assert type in ["connect", "disconnect", "error"]
        if type == "connect":
            self.websocket_status[endpoint]["active_connections"] += 1
        elif type == "disconnect":
            self.websocket_status[endpoint]["active_connections"] -= 1
            self.websocket_status[endpoint]["finished_connections"] += 1
        elif type == "error":
            self.websocket_status[endpoint]["error_connections"] += 1
            self.websocket_status[endpoint]["active_connections"] -= 1
            self.websocket_status[endpoint]["finished_connections"] += 1

    def get_next_endpoint(self) -> str:
        """Get next endpoint using round-robin"""
        endpoint = self.target_endpoints[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.target_endpoints)
        return endpoint

    async def get_target_connection(
        self, client_id: str, target_endpoint: str
    ) -> aiohttp.ClientWebSocketResponse:
        """Get or create a connection to target endpoint"""
        async with self.connection_lock:
            if client_id not in self.active_connections:
                # Create a new session and store it separately
                session = aiohttp.ClientSession()
                self.sessions[client_id] = session

                # Connect to the target endpoint
                ws = await session.ws_connect(target_endpoint)
                self.active_connections[client_id] = ws
            return self.active_connections[client_id]

    async def remove_connection(self, client_id: str):
        """Remove and close a connection"""
        async with self.connection_lock:
            if client_id in self.active_connections:
                ws = self.active_connections[client_id]
                await ws.close()
                del self.active_connections[client_id]

            if client_id in self.sessions:
                session = self.sessions[client_id]
                await session.close()
                del self.sessions[client_id]


class ProxyServer:
    def __init__(self, target_endpoints: List[str]):
        self.identity = str(uuid.uuid4())[:8]
        self.app = FastAPI(lifespan=self.lifespan)
        self.pool = WebSocketPool(target_endpoints)

        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self.app.websocket("/")(self.websocket_endpoint)

        self.monitor_client = MonitorClient(self.identity)

        self.task_tracker = TaskTracker()

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        if REPORT_STATUS:
            self.report_status_task = asyncio.create_task(
                self.report_status_periodically(), name="report_status"
            )
        yield
        await self.monitor_client.close()
        if hasattr(self, "report_status_task"):
            self.report_status_task.cancel()
            try:
                await self.report_status_task
            except asyncio.CancelledError:
                pass

    async def report_status_periodically(self):
        await asyncio.sleep(random.randint(0, REPORT_STATUS_INTERVAL))
        while True:
            logger.info(f"Reporting status for {self.identity}")
            await asyncio.sleep(REPORT_STATUS_INTERVAL)
            await self.monitor_client.set_websocket_status(
                self.pool.get_websocket_status()
            )
            await self.monitor_client.set_task_tracker_status(
                self.task_tracker.get_status()
            )

    async def forward_messages(
        self,
        ws: WebSocket,
        target_ws: aiohttp.ClientWebSocketResponse,
        client_id: str,
        target_endpoint: str,
    ):
        """Forward messages between client and target WebSocket"""
        try:
            while True:
                message = await ws.receive()

                if message["type"] == "websocket.disconnect":
                    logger.debug(f"Client {client_id} disconnected")
                    break

                if message["type"] == "websocket.receive":
                    if "text" in message and message["text"]:
                        text_msg = message["text"]

                        data = json.loads(text_msg)
                        msg_id = data.get("id", "unknown")
                        msg_method = data.get("method", "unknown")
                        logger.info(f"Forward: {text_msg}")
                        assert msg_id != "unknown"
                        self.task_tracker.register_task(
                            client_id, msg_id, target_endpoint
                        )
                        await target_ws.send_str(text_msg)
                    elif "bytes" in message and message["bytes"]:
                        binary_msg = message["bytes"]
                        logger.info(
                            f"Forwarding binary message: {len(binary_msg)} bytes"
                        )
                        self.task_tracker.register_data_message()
                        await target_ws.send_bytes(binary_msg)
                    else:
                        raise ValueError(f"Unknown message type: {message}")

        except WebSocketDisconnect:
            logger.info(f"Client {client_id} disconnected")
            await self.pool.remove_connection(client_id)
            self.task_tracker.cleanup_connection(client_id)
        except Exception as e:
            logger.error(f"Error forwarding client->target for {client_id}: {e}")
            await self.pool.remove_connection(client_id)
            self.task_tracker.cleanup_connection(client_id)

    async def backward_messages(
        self, ws: WebSocket, target_ws: aiohttp.ClientWebSocketResponse, client_id: str
    ):
        """Forward messages from target back to client"""
        try:
            async for msg in target_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:

                    data = json.loads(msg.data)
                    msg_id = data.get("id", "unknown")
                    if "result" in data:
                        self.task_tracker.complete_task(client_id, msg_id, True)
                    elif "error" in data:
                        self.task_tracker.complete_task(client_id, msg_id, False)
                        error_msg = (
                            data.get("error", {})
                            .get("error", {})
                            .get("message", "unknown error")
                        )
                    else:
                        self.task_tracker.register_data_message()
                    logger.info(f"Backward: {msg.data}")
                    await ws.send_text(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    self.task_tracker.register_data_message()
                    logger.info(f"Forwarding binary message: {len(msg.data)} bytes")
                    await ws.send_bytes(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except WebSocketDisconnect:
            logger.info(f"Target disconnected for client {client_id}")
            await self.pool.remove_connection(client_id)
            self.task_tracker.cleanup_connection(client_id)
        except Exception as e:
            logger.error(f"Error forwarding target->client for {client_id}: {e}")
            await self.pool.remove_connection(client_id)
            self.task_tracker.cleanup_connection(client_id)

    async def websocket_endpoint(self, websocket: WebSocket):
        await websocket.accept()
        client_id = str(id(websocket))
        logger.info(f"New client connected: {client_id}")

        try:
            # Get target endpoint and establish connection
            target_endpoint = self.pool.get_next_endpoint()
            self.pool.update_websocket_status(target_endpoint, "connect")
            logger.info(f"Connecting client {client_id} to target {target_endpoint}")

            # Forward all headers and subprotocols from the client to the target
            client_headers = dict(websocket.headers)
            # Add important headers for Playwright
            client_headers.update(
                {
                    "Upgrade": "websocket",
                    "Connection": "Upgrade",
                }
            )

            # Get subprotocols if any
            subprotocols = websocket.scope.get("subprotocols", [])

            logger.info(
                f"Connecting to target {target_endpoint} with headers: {client_headers} and subprotocols: {subprotocols}"
            )

            # Connect with full headers and subprotocols
            session = aiohttp.ClientSession()
            self.pool.sessions[client_id] = session

            try:
                target_ws = await session.ws_connect(
                    target_endpoint,
                    headers=client_headers,
                    protocols=subprotocols,
                    max_msg_size=0,  # No limit on message size
                )
                self.pool.active_connections[client_id] = target_ws
            except Exception as e:
                logger.error(f"Failed to connect to target {target_endpoint}: {e}")
                await websocket.close(1001, f"Failed to connect to target: {e}")
                await session.close()
                del self.pool.sessions[client_id]
                self.task_tracker.cleanup_connection(client_id)
                return

            logger.info(f"Successfully connected to target: {target_endpoint}")

            # Create tasks for bidirectional message forwarding
            forward_task = asyncio.create_task(
                self.forward_messages(websocket, target_ws, client_id, target_endpoint)
            )
            backward_task = asyncio.create_task(
                self.backward_messages(websocket, target_ws, client_id)
            )

            # Wait for either direction to complete
            done, pending = await asyncio.wait(
                [forward_task, backward_task], return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel the remaining task
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"Error in WebSocket endpoint for {client_id}: {e}")
        finally:
            await self.pool.remove_connection(client_id)
            self.pool.update_websocket_status(target_endpoint, "disconnect")
            self.task_tracker.cleanup_connection(client_id)


def create_app(target_endpoints: List[str]) -> FastAPI:
    proxy = ProxyServer(target_endpoints)
    return proxy.app


# Default app instance for workers to import
# This will be used when --workers > 1
# The 'factory=True' option in uvicorn.run() ensures this is called per worker
# Get target endpoints from environment variables when running as worker
default_start_port = int(os.environ.get("TARGET_START_PORT", "9214"))
default_count = int(os.environ.get("TARGET_ENDPOINTS_COUNT", "32"))
default_target_endpoints = [
    f"ws://localhost:{port}"
    for port in range(default_start_port, default_start_port + default_count)
]
app = create_app(default_target_endpoints)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebSocket Proxy Server")
    parser.add_argument(
        "--workers", type=int, default=1, help="Number of worker processes"
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument(
        "--target-start-port",
        type=int,
        default=9214,
        help="Start port for target endpoints",
    )
    parser.add_argument(
        "--target-count", type=int, default=32, help="Number of target endpoints"
    )
    args = parser.parse_args()

    # Set environment variables for worker processes
    os.environ["TARGET_START_PORT"] = str(args.target_start_port)
    os.environ["TARGET_ENDPOINTS_COUNT"] = str(args.target_count)

    if args.workers > 1:
        try:
            import multiprocessing

            # For MacOS compatibility
            multiprocessing.set_start_method("fork")
        except RuntimeError:
            # Already set, which is fine
            pass

        logger.info(
            f"Starting proxy with {args.workers} workers, targeting {args.target_count} endpoints starting at port {args.target_start_port}"
        )
        uvicorn.run(
            "proxy:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level="info",
            loop="uvloop",
        )
    else:
        target_endpoints = [
            f"ws://localhost:{port}"
            for port in range(
                args.target_start_port, args.target_start_port + args.target_count
            )
        ]
        app = create_app(target_endpoints)
        logger.info(
            f"Starting proxy with 1 worker, targeting {args.target_count} endpoints starting at port {args.target_start_port}"
        )
        uvicorn.run(app, host=args.host, port=args.port)
