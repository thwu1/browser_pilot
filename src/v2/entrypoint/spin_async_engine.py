import asyncio
import logging
import signal

import uvloop
import yaml

from async_engine import BrowserEngine
from engine import BrowserEngineConfig

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_CONFIG = yaml.safe_load(open("src/entrypoint/config.yaml"))

if __name__ == "__main__":
    engine_config = DEFAULT_CONFIG

    # Create and start the engine
    logger.info("Creating new AsyncBrowserEngine instance")

    # Setup uvloop-based event loop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    engine = BrowserEngine.make_engine(BrowserEngineConfig(**engine_config))
    loop.create_task(engine.start())

    def shutdown_handler(signum, frame):
        logger.info("Signal received, shutting down engine")
        engine.shutdown()
        loop.stop()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("Starting engine event loop, press Ctrl+C to exit")
    loop.run_forever()
