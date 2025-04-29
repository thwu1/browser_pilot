import asyncio
import logging
import signal

import uvloop
from async_engine import AsyncBrowserEngine
from engine import BrowserEngine, BrowserEngineConfig
from scheduler import SchedulerType

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_CONFIG = {
    "worker_client_config": {
        "input_path": "ipc://input_fastapi.sock",
        "output_path": "ipc://output_fastapi.sock",
        "num_workers": 32,
    },
    "scheduler_config": {
        "type": SchedulerType.ROUND_ROBIN,
        "max_batch_size": 128,
        "n_workers": 32,
    },
}

if __name__ == "__main__":
    engine_config = DEFAULT_CONFIG

    # Create and start the engine
    logger.info("Creating new AsyncBrowserEngine instance")

    # Setup uvloop-based event loop
    # asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    # loop = asyncio.new_event_loop()
    # asyncio.set_event_loop(loop)

    engine = BrowserEngine(BrowserEngineConfig(**engine_config))
    engine._running = True

    engine.engine_core_loop()

    def shutdown_handler(signum, frame):
        logger.info("Signal received, shutting down engine")
        engine._shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("Starting engine event loop, press Ctrl+C to exit")
