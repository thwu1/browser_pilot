import uuid
from abc import ABC
from typing import Any

from browser_pilot.entrypoint.client import CloudClient
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("env.log")],
    force=True,
)
logger = logging.getLogger(__name__)


class CloudEnv(ABC):
    def __init__(
        self,
        url: str = "ws://localhost:9999/send_and_wait",
        client: CloudClient = None,
        env_uuid: str = None,
        **kwargs,
    ):
        self._share_client = False if client is None else True
        self._client = client if self._share_client else CloudClient(url)
        self._initialized = False
        self._kwargs = kwargs

        self._env_uuid = str(uuid.uuid4()) if env_uuid is None else env_uuid
        # self._client.register_env(self._env_uuid)
        self._env_registered = False

    @property
    def env_id(self):
        return self._kwargs["id"]

    def step(self, action: Any, timeout: float = 30.0) -> Any:
        msg = {
            "task_id": str(uuid.uuid4()),
            "method": "step",
            "params": {"action": action},
        }
        future = self._client.send(msg, self._env_uuid)
        result = future.result(timeout=timeout)
        return tuple(result["result"])

    def reset(self, timeout: float = 30.0) -> None:
        if not self._env_registered:
            self._client.register_env(self._env_uuid)
            self._env_registered = True

        if self._initialized:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "reset",
                "params": {},
            }
            future = self._client.send(msg, self._env_uuid)
            result = future.result(timeout=timeout)
            return tuple(result["result"])
        else:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "__init__",
                "params": self._kwargs,
            }
            future = self._client.send(msg, self._env_uuid)
            result = future.result(timeout=timeout)
            self._initialized = True

            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "reset",
                "params": {},
            }
            future = self._client.send(msg, self._env_uuid)
            result = future.result(timeout=timeout)
            return tuple(result["result"])

    def close(self, timeout: float = 30.0):
        msg = {
            "task_id": str(uuid.uuid4()),
            "method": "close",
            "params": {},
        }
        self._env_registered = False
        try:
            future = self._client.send(msg, self._env_uuid)
            future.result(timeout=timeout)
        except Exception as e:
            logger.error("Failed to close env {}: {}".format(self.env_id, e))

        if not self._share_client:
            self._client.close()
            logger.debug("Successfully closed env {}".format(self.env_id))
        else:
            self._client.unregister_env(self._env_uuid)
            logger.debug("Successfully unregistered env {}".format(self.env_id))


if __name__ == "__main__":
    import time

    # env = CloudEnv(
    #     id="browsergym_async/openended",
    #     task_kwargs={"start_url": "https://www.example.com"},
    #     headless=True,
    #     slow_mo=0,
    #     timeout=10,
    # )

    concurrency = 64
    tasks = 1500

    share_client = True
    import asyncio

    if share_client:
        clients = [CloudClient(max_concurrency=None) for _ in range(1)]
    else:
        clients = [None]

    async def execute_task(id):
        env = CloudEnv(
            id="browsergym_async/openended",
            client=clients[id % len(clients)],
            env_uuid=str(id),
            task_kwargs={"start_url": "https://www.example.com"},
            headless=True,
            slow_mo=0,
            timeout=10,
        )
        try:
            await asyncio.to_thread(env.reset)
            await asyncio.to_thread(env.close)
            print(f"Finished {id}")
        except Exception as e:
            await asyncio.to_thread(env.close)
            print(f"Failed {id}")
        # def reset_and_close():
        #     env.reset()
        #     env.close()

        # await asyncio.to_thread(reset_and_close)

    sema = asyncio.Semaphore(concurrency)

    async def run_task_with_sema(id, sema):
        async with sema:
            await execute_task(id)

    async def main():
        await asyncio.gather(*[run_task_with_sema(id, sema) for id in range(tasks)])

    time_start = time.time()
    asyncio.run(main())
    time_end = time.time()
    print(f"Time taken: {time_end - time_start} seconds")
    if share_client:
        for client in clients:
            client.close()
