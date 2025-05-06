from abc import ABC, abstractmethod
from typing import Any
from cloud_client import CloudClient, MsgType
import uuid


class CloudEnv(ABC):
    def __init__(self, **kwargs):
        self._client = CloudClient()
        self._initialized = False
        self._kwargs = kwargs

    # @abstractmethod
    # def __reset__(self) -> None:
    #     raise NotImplementedError("__reset__ is not implemented")

    # # @abstractmethod
    # def __step__(self, action: Any) -> Any:
    #     raise NotImplementedError("__step__ is not implemented")

    # # @abstractmethod
    # def __close__(self) -> None:
    #     raise NotImplementedError("__close__ is not implemented")

    # async def __areset__(self) -> None:
    #     raise NotImplementedError("__areset__ is not implemented")

    # async def __astep__(self, action: Any) -> Any:
    #     raise NotImplementedError("__astep__ is not implemented")

    # async def __aclose__(self) -> None:
    #     raise NotImplementedError("__aclose__ is not implemented")

    # async def __ainit__(self) -> None:
    #     raise NotImplementedError("__ainit__ is not implemented")

    def step(self, action: Any, timeout: float = 30.0) -> Any:
        msg = {
            "task_id": str(uuid.uuid4()),
            "method": "step",
            "params": {"action": action},
        }
        future = self._client.send(msg)
        return future.result(timeout=timeout)

    def reset(self, timeout: float = 30.0) -> None:
        if self._initialized:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "reset",
                "params": {},
            }
            future = self._client.send(msg)
            result = future.result(timeout=timeout)
            return result
        else:
            msg = {
                "task_id": str(uuid.uuid4()),
                "method": "__init__",
                "params": self._kwargs,
            }
            future = self._client.send(msg)
            result = future.result(timeout=timeout)
            self._initialized = True
            return result

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
    # print(result)
    result = env.reset()
    # print(result)

    result = env.step("Click on the button")
    # print(result)
    env.step("Click on the button")
    env.close()
