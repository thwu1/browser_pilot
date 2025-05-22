import uuid
from abc import ABC
from typing import Any

from browser_pilot.entrypoint.async_client import AsyncCloudClient
import logging


logger = logging.getLogger(__name__)


class AsyncCloudEnv(ABC):
    def __init__(
        self,
        url: str = "ws://localhost:9999/send_and_wait",
        client: AsyncCloudClient = None,
        env_uuid: str = None,
        **kwargs,
    ):
        self._share_client = False if client is None else True
        self._client = client if self._share_client else AsyncCloudClient(url)
        self._initialized = False
        self._kwargs = kwargs

        self._env_uuid = str(uuid.uuid4()) if env_uuid is None else env_uuid
        self._env_registered = False
        self._client.maybe_start_background_task()

    @property
    def env_id(self):
        return self._kwargs["id"]

    async def step(self, action: Any, timeout: float = 30.0) -> Any:
        msg = {
            "task_id": str(uuid.uuid4()),
            "method": "step",
            "params": {"action": action},
        }
        future = await self._client.send(msg, self._env_uuid)
        result = await asyncio.wait_for(future, timeout=timeout)
        return tuple(result["result"])

    async def reset(self, timeout: float = 30.0) -> None:
        if not self._env_registered:
            await self._client.register_env(self._env_uuid)
            self._env_registered = True

        if self._initialized:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "reset",
                "params": {},
            }
            future = await self._client.send(msg, self._env_uuid)
            result = await asyncio.wait_for(future, timeout=timeout)
            return tuple(result["result"])
        else:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "__init__",
                "params": self._kwargs,
            }
            future = await self._client.send(msg, self._env_uuid)
            result = await asyncio.wait_for(future, timeout=timeout)
            self._initialized = True

            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "reset",
                "params": {},
            }
            future = await self._client.send(msg, self._env_uuid)
            result = await asyncio.wait_for(future, timeout=timeout)
            return tuple(result["result"])

    async def close(self, timeout: float = 30.0):
        msg = {
            "task_id": str(uuid.uuid4()),
            "method": "close",
            "params": {},
        }
        self._env_registered = False
        try:
            future = await self._client.send(msg, self._env_uuid)
            await asyncio.wait_for(future, timeout=timeout)
        except Exception as e:
            logger.error("Failed to close env {}: {}".format(self.env_id, e))

        if not self._share_client:
            await self._client.close()
            logger.debug("Successfully closed env {}".format(self.env_id))
        else:
            await self._client.unregister_env(self._env_uuid)
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

    concurrency = 128
    tasks = 1000

    share_client = True
    import asyncio

    if share_client:
        clients = [AsyncCloudClient(max_concurrency=None) for _ in range(1)]
    else:
        clients = [None]

    async def execute_task(id):
        env = AsyncCloudEnv(
            id="browsergym_async/openended",
            client=clients[id % len(clients)],
            env_uuid=str(id),
            task_kwargs={"start_url": "https://www.example.com"},
            headless=True,
            slow_mo=0,
            timeout=10,
        )
        await env.reset()
        await env.close()
        print(f"Finished {id}")

    sema = asyncio.Semaphore(concurrency)

    async def run_task_with_sema(id, sema):
        async with sema:
            await execute_task(id)

    async def main():
        await asyncio.gather(*[run_task_with_sema(id, sema) for id in range(tasks)])
        for client in clients:
            await client.close()

    time_start = time.time()
    asyncio.run(main())
    time_end = time.time()
    print(f"Time taken: {time_end - time_start} seconds")
