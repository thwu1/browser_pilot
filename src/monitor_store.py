from typing import Union

import msgpack
import redis.asyncio as redis_async

# docker run --name my-redis -d -p 6379:6379 redis


class MonitorClient:
    def __init__(self, identity: str):
        self.redis_client = redis_async.Redis(host="localhost", port=6379, db=0)
        self.identity = identity

    async def set_websocket_status(self, status: dict):
        await self.redis_client.set(f"{self.identity}-websocket", msgpack.packb(status))

    async def set_task_tracker_status(self, status: dict):
        await self.redis_client.set(
            f"{self.identity}-task-tracker", msgpack.packb(status)
        )

    async def get_websocket_status(self) -> dict:
        result = await self.redis_client.get(f"{self.identity}-websocket")
        return msgpack.unpackb(result) if result else {}

    async def get_task_tracker_status(self) -> dict:
        result = await self.redis_client.get(f"{self.identity}-task-tracker")
        return msgpack.unpackb(result) if result else {}

    async def close(self):
        await self.redis_client.aclose()


class CentralMonitorStore:
    def __init__(self):
        self.redis_client = redis_async.Redis(host="localhost", port=6379, db=0)

    async def get_aggregated_status(self) -> dict:
        """Get aggregated status for all workers across all identities"""
        # Get all keys
        all_keys = await self.redis_client.keys("*")

        websocket_results = {}
        task_tracker_results = {}
        for key in all_keys:
            key_str = key.decode()
            if not key_str.endswith("-websocket") and not key_str.endswith(
                "-task-tracker"
            ):
                continue

            identity = key_str.replace("-websocket", "")
            if key_str.endswith("-websocket"):
                if not identity in websocket_results:
                    websocket_results[identity] = {}

                status = await self.redis_client.get(key)
                if status:
                    websocket_results[identity] = msgpack.unpackb(status)
            elif key_str.endswith("-task-tracker"):
                if not identity in task_tracker_results:
                    task_tracker_results[identity] = {}

                status = await self.redis_client.get(key)
                if status:
                    task_tracker_results[identity] = msgpack.unpackb(status)

        return websocket_results, task_tracker_results

    async def close(self):
        await self.redis_client.aclose()


if __name__ == "__main__":
    import asyncio

    async def main():
        monitor_store = CentralMonitorStore()
        try:
            print(await monitor_store.get_aggregated_status())
        finally:
            await monitor_store.close()

    asyncio.run(main())
