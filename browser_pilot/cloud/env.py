import uuid
from abc import ABC, abstractmethod
from typing import Any

from browser_pilot.cloud.client import CloudClient


class CloudEnv(ABC):
    def __init__(self, url: str = "ws://localhost:9999/send_and_wait", **kwargs):
        self._client = CloudClient(url)
        self._initialized = False
        self._kwargs = kwargs

    @property
    def env_id(self):
        return self._kwargs["id"]

    def step(self, action: Any, timeout: float = 30.0) -> Any:
        msg = {
            "task_id": str(uuid.uuid4()),
            "method": "step",
            "params": {"action": action},
        }
        future = self._client.send(msg)
        result = future.result(timeout=timeout)
        return tuple(result["result"])

    def reset(self, timeout: float = 30.0) -> None:
        if self._initialized:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "reset",
                "params": {},
            }
            future = self._client.send(msg)
            result = future.result(timeout=timeout)
            return tuple(result["result"])
        else:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "__init__",
                "params": self._kwargs,
            }
            future = self._client.send(msg)
            result = future.result(timeout=timeout)
            self._initialized = True

            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "reset",
                "params": {},
            }
            future = self._client.send(msg)
            result = future.result(timeout=timeout)
            return tuple(result["result"])

    def close(self, timeout: float = 30.0):
        msg = {
            "task_id": str(uuid.uuid4()),
            "method": "close",
            "params": {},
        }
        future = self._client.send(msg)
        try:
            future.result(timeout=timeout)
        except Exception as e:
            print("Failed to close env {}: {}".format(self.env_id, e))
        self._client.close()
        print("Successfully closed env {}.".format(self.env_id))


if __name__ == "__main__":
    # env = CloudEnv(
    #     id="browsergym_async/openended",
    #     task_kwargs={"start_url": "https://www.example.com"},
    #     headless=True,
    #     slow_mo=0,
    #     timeout=10,
    # )

    concurrency = 32
    tasks = 812
    import asyncio

    async def execute_task(id):
        env = CloudEnv(
            id="browsergym_async/openended",
            task_kwargs={"start_url": "https://www.example.com"},
            headless=True,
            slow_mo=0,
            timeout=10,
        )
        await asyncio.to_thread(env.reset)
        await asyncio.to_thread(env.close)
        print(f"Finished {id}")

    sema = asyncio.Semaphore(concurrency)

    async def run_task_with_sema(id, sema):
        async with sema:
            await execute_task(id)

    async def main():
        await asyncio.gather(*[run_task_with_sema(id, sema) for id in range(tasks)])

    asyncio.run(main())
