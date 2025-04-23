import logging
from scheduler import SchedulerType
from async_engine import AsyncBrowserEngine
from engine import BrowserEngineConfig

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
    # engine_config = BrowserEngineConfig(**engine_config)

    # Create and start the engine
    logger.info("Creating new AsyncBrowserEngine instance")
    AsyncBrowserEngine.spin_up_engine(engine_config)