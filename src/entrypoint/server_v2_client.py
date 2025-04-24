import asyncio
import logging
import multiprocessing as mp
import signal
import time
import uuid
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Dict, Optional

import uvicorn
import uvloop
import zmq
import zmq.asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from async_engine import AsyncBrowserEngine
from engine import BrowserEngineConfig
from scheduler import SchedulerType
from utils import MsgpackDecoder, MsgpackEncoder, MsgType, make_zmq_socket
from worker import BrowserWorkerTask

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("server_v2.log")],
)
# logger = logging.getLogger(__name__)
logger = logging.getLogger()

# Global engine instance and shutdown flag
engine = None
should_exit = False

ctx = None
sockets = None
encoder = MsgpackEncoder()
decoder = MsgpackDecoder()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: initialize the engine
    await start()
    global ctx, sockets
    ctx = zmq.asyncio.Context(io_threads=1)
    sockets = asyncio.Queue()
    for _ in range(64):
        sockets.put_nowait(
            make_zmq_socket(
                ctx,
                "ipc://app_to_engine.sock",
                zmq.DEALER,
                bind=False,
                identity=str(uuid.uuid4().hex[:8]).encode(),
            )
        )
    logger.info(f"Created {64} sockets for engine")
    try:
        yield
    except asyncio.CancelledError:
        # swallow the cancellation so Starlette doesn't log it
        logger.info("Lifespan cancelled, exiting without error")
    finally:
        await stop()


app = FastAPI(
    title="Browser Pilot API",
    description="API for browser automation",
    lifespan=lifespan,
)


# API Models
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


async def start(config: Dict[str, Any] = None):
    """Start the AsyncBrowserEngine with the given configuration"""
    global engine

    if engine is not None:
        logger.warning("Engine is already running")
        return

    # Use provided config or default
    # engine_config = config or DEFAULT_CONFIG
    # # engine_config = BrowserEngineConfig(**engine_config)

    # # Create and start the engine
    # logger.info("Creating new AsyncBrowserEngine instance")
    # engine = mp.Process(target=AsyncBrowserEngine.spin_up_engine, args=(engine_config,))
    # engine.start()

    # Wait a bit for the engine to initialize
    await asyncio.sleep(1)
    logger.info("AsyncBrowserEngine started successfully")


async def stop():
    """Stop the AsyncBrowserEngine with proper cleanup"""
    global engine

    if engine is None:
        logger.warning("Engine is not running")
        return

    try:
        logger.info("Shutting down AsyncBrowserEngine...")

        # Stop the engine
        engine.kill()

        # Clear engine reference
        engine = None
        logger.info("AsyncBrowserEngine stopped successfully")

    except Exception as e:
        logger.error(f"Error stopping engine: {e}")
        raise


async def shutdown(signal_name=None):
    """Graceful shutdown sequence"""
    global should_exit, engine

    if should_exit:
        logger.warning("Forced shutdown initiated...")
        return  # Return instead of sys.exit to allow proper cleanup

    should_exit = True
    logger.info(f"Received signal {signal_name}. Initiating graceful shutdown...")

    try:
        # Stop the engine first
        if engine is not None:
            await stop()
            engine = None  # Prevent multiple shutdown attempts

        # Cancel all remaining tasks except the server
        loop = asyncio.get_running_loop()
        tasks = [
            t
            for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task() and not t.get_name().startswith("Server")
        ]  # Don't cancel uvicorn server tasks

        if tasks:
            logger.info(f"Cancelling {len(tasks)} pending tasks...")
            for task in tasks:
                task.cancel()

            # Wait for tasks to cancel
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Shutdown completed successfully")

    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


def signal_handler(signame, loop):
    """Handle signals by scheduling shutdown in the event loop"""
    logger.info(f"Received signal {signame}")
    asyncio.create_task(shutdown(signame))


@app.post("/send_and_wait", response_model=TaskStatusResponse)
async def send_and_wait(task_request: TaskRequest, timeout: int = 60):
    """Send a task and wait for its result"""
    # Log the task creation
    global sockets

    initial_time = time.time()
    task_id = f"{uuid.uuid4().hex[:8]}"
    logger.info(
        f"Created task {task_id} with send_and_wait, waiting for result (timeout: {timeout}s)"
    )

    socket = await sockets.get()
    task = BrowserWorkerTask(
        task_id=task_id,
        command=task_request.command,
        context_id=task_request.context_id,
        page_id=task_request.page_id,
        params=task_request.params,
    )
    task_bytes = encoder(task.to_dict())
    logger.info(f"Sending task {task_id} to engine")
    await socket.send_multipart([MsgType.TASK, task_bytes])
    logger.info(f"Task {task_id} sent to engine")

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


# @app.get("/health")
# async def health_check():
#     """Health check endpoint"""
#     global engine

#     if engine is None:
#         return {"status": "down", "message": "Engine is not running"}

#     return {
#         "status": "up",
#         "tasks": {
#             "pending": engine.waiting_queue.qsize(),
#             "completed": len(engine.output_dict),
#         },
#         "contexts": len(engine.context_tracker),
#     }


if __name__ == "__main__":
    import uvicorn
    import uvloop
    from uvicorn.config import LOGGING_CONFIG

    # Use uvloop for a faster event loop
    # uvloop.install()
    # # Ensure we have a file handler in the Uvicorn logging config
    # LOGGING_CONFIG.setdefault("handlers", {}).update({
    #     "file": {
    #         "class": "logging.FileHandler",
    #         "formatter": "default",
    #         "filename": "server_v2.log",
    #     }
    # })
    # LOGGING_CONFIG.setdefault("root", {"handlers": [], "level": "INFO"})
    # if "file" not in LOGGING_CONFIG["root"].get("handlers", []):
    #     LOGGING_CONFIG["root"]["handlers"].append("file")
    # Start the FastAPI app via Uvicorn
    uvicorn.run(
        "src.entrypoint.server_v2:app",
        host="0.0.0.0",
        port=9999,
        log_level="debug",
        # log_config=LOGGING_CONFIG,
        workers=4,
    )
