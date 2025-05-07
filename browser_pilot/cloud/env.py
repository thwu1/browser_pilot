import uuid
from abc import ABC, abstractmethod
from typing import Any

from browser_pilot.cloud.client import CloudClient


class CloudEnv(ABC):
    def __init__(self, url: str = "ws://localhost:9999/send_and_wait", **kwargs):
        self._client = CloudClient(url)
        self._initialized = False
        self._kwargs = kwargs

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
        future.result(timeout=timeout)
        self._client.close()


if __name__ == "__main__":
    env = CloudEnv(
        id="browsergym_async/openended",
        task_kwargs={"start_url": "https://www.example.com"},
        headless=True,
        slow_mo=0,
        timeout=10,
    )
    result = env.reset()
    assert isinstance(
        result, tuple
    ), f"result is not a tuple: {type(result)}, {result.keys()}"
    assert len(result) == 2
    # print(result)

    result = env.step("Click on the button")
    assert isinstance(result, tuple)
    assert len(result) == 5
    # print(result)
    result = env.step("Click on the button")
    assert isinstance(result, tuple)
    assert len(result) == 5
    # print(result)
    env.close()
