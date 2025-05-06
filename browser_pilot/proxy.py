import asyncio
import concurrent.futures
import logging
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Dict, Optional

import uvicorn
import uvloop
import yaml
import zmq.asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from browser_pilot.type.task_type import WorkerOutput, WorkerTask
from browser_pilot.utils import Serializer
from browser_pilot.worker_client import WorkerClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
    force=True,
)
logger = logging.getLogger(__name__)


client = None
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
serializer = Serializer(serializer="orjson")

task_id_to_future = {}

config = yaml.safe_load(
    open("/home/tianhao/browser_pilot/browser_pilot/old/v2/entrypoint/config.yaml")
)
status_socket = None
num_workers = config["worker_client_config"]["num_workers"]


class RoundRobinWorkerIterator:
    def __init__(self, num_workers: int):
        self.num_workers = num_workers
        self.current_worker = 0

    def __iter__(self):
        return self

    def __next__(self):
        worker = self.current_worker
        self.current_worker = (self.current_worker + 1) % self.num_workers
        return worker


worker_iter = iter(RoundRobinWorkerIterator(num_workers))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global client
    client = WorkerClient.make_client(config["worker_client_config"])
    recv_task = asyncio.create_task(recv_output_loop(), name="recv_output_loop")
    try:
        yield
    except asyncio.CancelledError:
        logger.info("Lifespan cancelled, exiting without error")
    finally:
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

        client.close()
        logger.info("App shutdown event, cleaning up")


app = FastAPI(
    title="Browser Pilot API",
    description="API for browser automation",
    lifespan=lifespan,
    websocket_max_size=1024 * 1024 * 100,
)


class TaskStatus(str, Enum):
    FINISHED = "finished"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class TaskStatusResponse(BaseModel):
    """Response model for task status"""

    # task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None


async def recv_output_loop():
    is_running = True

    @app.on_event("shutdown")
    async def shutdown_handler():
        nonlocal is_running
        is_running = False
        # Put sentinel value to unblock queue.get if needed
        client.output_queue.put((0, "__SHUTDOWN__"))

    while is_running:
        if client.output_queue.empty():
            idx, output = await asyncio.get_event_loop().run_in_executor(
                executor, client.output_queue.get
            )
        else:
            idx, output = client.output_queue.get()
        if output == "__SHUTDOWN__":
            break
        assert "task_id" in output
        task_id = output["task_id"]
        task_id_to_future[task_id].set_result(output)


@app.websocket("/send_and_wait")
async def send_and_wait(websocket: WebSocket):
    """Send a task and wait for its result"""
    await websocket.accept()

    env_id = str(uuid.uuid4())
    assigned_worker = next(worker_iter)

    try:
        while True:
            data = await websocket.receive_text()
            initial_time = time.time()
            msg_id, data = serializer.loads(data)
            logger.info(f"Received message: {msg_id}, {data}")
            task = WorkerTask(
                task_id=msg_id,
                env_id=env_id,
                method=data["method"],
                params=data["params"],
                engine_recv_timestamp=time.time(),
            )
            task_id_to_future[msg_id] = asyncio.Future()
            client.send([task.to_dict()], assigned_worker)
            result = await asyncio.wait_for(task_id_to_future[msg_id], timeout=30)
            result["profile"]["app_init_timestamp"] = initial_time
            result["profile"]["app_recv_timestamp"] = time.time()
            task_id_to_future.pop(msg_id)
            await websocket.send_text(serializer.dumps(result))
    except WebSocketDisconnect:
        logger.info("Connection closed")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    # uvicorn src.entrypoint.server_client:app --host 0.0.0.0 --port 9999 --workers 4 --loop uvloop

    uvicorn.run(
        "proxy:app",
        host="0.0.0.0",
        port=9999,
        log_level="debug",
        workers=1,
        lifespan="on",
        ws_max_size=1024 * 1024 * 100,
        ws_ping_interval=None,
    )
