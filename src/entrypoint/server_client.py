import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import uvicorn
import uvloop
import zmq
import zmq.asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from utils import (
    MsgpackDecoder,
    MsgpackEncoder,
    MsgType,
    ZstdMsgpackDecoder,
    ZstdMsgpackEncoder,
    make_zmq_socket,
)
from worker import BrowserWorkerTask

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
    force=True,
)
logger = logging.getLogger(__name__)


ctx = None
sockets = None
num_sockets = 64
encoder = MsgpackEncoder()
decoder = MsgpackDecoder()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global ctx, sockets
    ctx = zmq.asyncio.Context(io_threads=1)
    sockets = asyncio.Queue()
    for _ in range(num_sockets):
        sockets.put_nowait(
            make_zmq_socket(
                ctx,
                "ipc://app_to_engine.sock",
                zmq.DEALER,
                bind=False,
                identity=str(uuid.uuid4().hex[:8]).encode(),
            )
        )
    logger.info(f"Created {num_sockets} sockets for engine")
    try:
        yield
    except asyncio.CancelledError:
        logger.info("Lifespan cancelled, exiting without error")
    finally:
        logger.info("App shutdown event, cleaning up ZMQ sockets and context")

        while not sockets.empty():
            sock = await sockets.get()
            try:
                sock.close()
            except Exception:
                logger.warning("Error closing socket during shutdown", exc_info=True)

        try:
            ctx.term()
        except Exception:
            logger.warning(
                "Error terminating ZMQ context during shutdown", exc_info=True
            )
        logger.info("ZMQ cleanup on shutdown complete")


app = FastAPI(
    title="Browser Pilot API",
    description="API for browser automation",
    lifespan=lifespan,
)


class TaskRequest(BaseModel):
    """Request model for creating a task"""

    command: str
    context_id: Optional[str] = None
    page_id: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class TaskStatusResponse(BaseModel):
    """Response model for task status"""

    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None


@app.post("/send_and_wait", response_model=TaskStatusResponse)
async def send_and_wait(task_request: TaskRequest, timeout: int = 60):
    """Send a task and wait for its result"""

    global sockets

    initial_time = time.time()
    task_id = f"{uuid.uuid4().hex[:8]}"

    socket = await sockets.get()
    task = BrowserWorkerTask(
        task_id=task_id,
        command=task_request.command,
        context_id=task_request.context_id,
        page_id=task_request.page_id,
        params=task_request.params,
    )
    task_bytes = encoder(task.to_dict())
    await socket.send_multipart([MsgType.TASK, task_bytes])

    try:
        result_bytes = await asyncio.wait_for(socket.recv_multipart(), timeout=timeout)
        result = decoder(result_bytes[1])
        await sockets.put(socket)
        socket = None
        final_time = time.time()
        result["profile"]["app_init_timestamp"] = initial_time
        result["profile"]["app_recv_timestamp"] = final_time
        return TaskStatusResponse(task_id=task_id, status="finished", result=result)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Task timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    finally:
        if socket:
            await sockets.put(socket)


if __name__ == "__main__":
    # uvicorn src.entrypoint.server_client:app --host 0.0.0.0 --port 9999 --workers 4

    uvicorn.run(
        "src.entrypoint.server_client:app",
        host="0.0.0.0",
        port=9999,
        log_level="debug",
        workers=4,
        lifespan="on",
    )
