import asyncio
import logging
import time
import uuid
from typing import Dict, Any, Optional
from functools import partial

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager

from async_engine import AsyncBrowserEngine
from engine import BrowserEngineConfig
from scheduler import SchedulerType
from worker import BrowserWorkerTask
import uvicorn
import signal


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Global engine instance and shutdown flag
engine = None
should_exit = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: initialize the engine
    await start()
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

# Engine configuration
DEFAULT_CONFIG = {
    "worker_client_config": {
        "input_path": "ipc://input_fastapi",
        "output_path": "ipc://output_fastapi",
        "num_workers": 4,
    },
    "scheduler_config": {
        "type": SchedulerType.ROUND_ROBIN,
        "max_batch_size": 10,
        "n_workers": 4,
    },
}


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
    engine_config = config or DEFAULT_CONFIG

    # Create and start the engine
    logger.info("Creating new AsyncBrowserEngine instance")
    engine = AsyncBrowserEngine(BrowserEngineConfig(**engine_config))

    # Start the engine core loop as a background task with a name
    logger.info("Starting engine core loop")
    core_loop = asyncio.create_task(engine.engine_core_loop(), name="engine_core_loop")

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
        await engine._shutdown()

        # Cancel engine core loop task if it exists
        loop = asyncio.get_running_loop()
        engine_tasks = [
            t
            for t in asyncio.all_tasks(loop)
            if t.get_name().startswith("engine_core_loop")
        ]

        for task in engine_tasks:
            logger.info("Cancelling engine core loop...")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

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
async def send_and_wait(task_request: TaskRequest, timeout: int = 30):
    """Send a task and wait for its result"""
    # Log the task creation
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    logger.info(
        f"Created task {task_id} with send_and_wait, waiting for result (timeout: {timeout}s)"
    )

    task_future = await engine.add_task(
        BrowserWorkerTask(
            task_id=task_id,
            command=task_request.command,
            context_id=task_request.context_id,
            page_id=task_request.page_id,
            params=task_request.params,
        )
    )

    try:
        result = await asyncio.wait_for(task_future, timeout=timeout)
        return TaskStatusResponse(task_id=task_id, status="finished", result=result)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Task timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    global engine

    if engine is None:
        return {"status": "down", "message": "Engine is not running"}

    return {
        "status": "up",
        "tasks": {
            "pending": engine.waiting_queue.qsize(),
            "completed": len(engine.output_dict),
        },
        "contexts": len(engine.context_tracker),
    }


if __name__ == "__main__":
    # Get the event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Setup signal handlers
    for signame in ("SIGINT", "SIGTERM"):
        loop.add_signal_handler(
            getattr(signal, signame), partial(signal_handler, signame, loop)
        )

    # Configure and run uvicorn with modified server settings
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=9999,
        loop=loop,
        log_level="info",
        timeout_keep_alive=30,
        timeout_graceful_shutdown=30,
    )
    server = uvicorn.Server(config)

    try:
        # Run the server
        loop.run_until_complete(server.serve())
    except asyncio.CancelledError:
        logger.info("Server loop cancelled")
        pass
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        # Let uvicorn handle its own shutdown
        loop.run_until_complete(shutdown("SERVER_STOP"))
        loop.close()
