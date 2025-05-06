import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

import msgpack
import redis
import redis.asyncio as redis_async

from util import config_loader

config = config_loader()

# docker run --name my-redis -d -p 6379:6379 redis

# Constants
HEARTBEAT_TIMEOUT = config["monitor"]["heartbeat_timeout"]  # seconds
CLEANUP_INTERVAL = config["monitor"]["cleanup_interval"]  # seconds
REDIS_HOST = config["monitor"]["redis_host"]
REDIS_PORT = config["monitor"]["redis_port"]


class MonitorClient:
    def __init__(self, identity: str):
        self.redis_client = redis_async.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
        self.identity = identity
        self.last_cleanup = time.time()

    async def set_status(self, status: dict):
        websocket_status = status["websocket"]
        task_status = status["task"]
        await asyncio.gather(
            self.set_websocket_status(websocket_status),
            self.set_task_tracker_status(task_status),
        )

    async def set_websocket_status(self, status: dict):
        """Store websocket status using Redis hashes"""
        pipe = await self.redis_client.pipeline()
        current_time = time.time()

        # Store each endpoint's metrics in a hash
        for endpoint, metrics in status.items():
            hash_key = f"ws:{endpoint}"
            # Store this worker's metrics with worker ID prefix
            for metric_name, value in metrics.items():
                field = f"{self.identity}:{metric_name}"
                await pipe.hset(hash_key, field, value)

            # Update last heartbeat
            await pipe.hset(hash_key, f"{self.identity}:last_heartbeat", current_time)

        await pipe.execute()

    async def set_task_tracker_status(self, status: dict):
        """Store task tracker status using Redis hashes"""
        pipe = await self.redis_client.pipeline()
        current_time = time.time()

        # Store each endpoint's task metrics in a hash
        for endpoint, metrics in status.items():
            hash_key = f"task:{endpoint}"
            # Store this worker's metrics with worker ID prefix
            for metric_name, value in metrics.items():
                # Ensure we're using the right field names
                if metric_name == "pending_tasks":
                    metric_name = "pending_tasks"  # Keep as is
                elif metric_name == "completed_tasks":
                    metric_name = "completed_tasks"  # Keep as is
                elif metric_name == "avg_completion_time":
                    metric_name = "avg_completion_time"  # Keep as is

                field = f"{self.identity}:{metric_name}"
                await pipe.hset(hash_key, field, value)

            # Update last heartbeat
            await pipe.hset(hash_key, f"{self.identity}:last_heartbeat", current_time)

        await pipe.execute()

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
        self.redis_client = redis_async.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
        self.last_cleanup = time.time()

    async def _cleanup_old_data(self):
        """Remove data from workers that haven't sent a heartbeat recently"""
        current_time = time.time()
        if current_time - self.last_cleanup < CLEANUP_INTERVAL:
            return

        self.last_cleanup = current_time
        cutoff_time = current_time - HEARTBEAT_TIMEOUT

        # Get all keys
        ws_keys = await self.redis_client.keys("ws:*")
        task_keys = await self.redis_client.keys("task:*")

        pipe = await self.redis_client.pipeline()

        # Clean up old websocket data
        for key in ws_keys:
            values = await self.redis_client.hgetall(key)
            for field in values:
                worker_id = field.decode().split(":", 1)[0]
                heartbeat_field = f"{worker_id}:last_heartbeat"
                last_heartbeat = float(values.get(heartbeat_field.encode(), 0))
                if last_heartbeat < cutoff_time:
                    # Remove all fields for this worker
                    worker_fields = [
                        f for f in values if f.decode().startswith(f"{worker_id}:")
                    ]
                    if worker_fields:
                        await pipe.hdel(key, *worker_fields)

        # Clean up old task data
        for key in task_keys:
            values = await self.redis_client.hgetall(key)
            for field in values:
                worker_id = field.decode().split(":", 1)[0]
                heartbeat_field = f"{worker_id}:last_heartbeat"
                last_heartbeat = float(values.get(heartbeat_field.encode(), 0))
                if last_heartbeat < cutoff_time:
                    # Remove all fields for this worker
                    worker_fields = [
                        f for f in values if f.decode().startswith(f"{worker_id}:")
                    ]
                    if worker_fields:
                        await pipe.hdel(key, *worker_fields)

        await pipe.execute()

    async def get_aggregated_status(self) -> tuple[dict, dict]:
        """Get aggregated status for all workers across all identities"""
        await self._cleanup_old_data()
        current_time = time.time()

        # Get all websocket and task keys
        ws_keys = await self.redis_client.keys("ws:*")
        task_keys = await self.redis_client.keys("task:*")

        pipe = await self.redis_client.pipeline()
        for key in ws_keys + task_keys:
            await pipe.hgetall(key)
        all_values = await pipe.execute()

        # Process websocket results - first group by endpoint and identity
        websocket_by_endpoint = {}
        for key, values in zip(ws_keys, all_values[: len(ws_keys)]):
            endpoint = key.decode().split(":", 1)[1]
            if endpoint not in websocket_by_endpoint:
                websocket_by_endpoint[endpoint] = {}

            # Group metrics by identity first
            for field, value in values.items():
                identity, metric = field.decode().split(":", 1)
                if identity not in websocket_by_endpoint[endpoint]:
                    websocket_by_endpoint[endpoint][identity] = {}
                websocket_by_endpoint[endpoint][identity][metric] = float(value)

        # Now aggregate across identities for each endpoint
        websocket_results = {}
        for endpoint, identities in websocket_by_endpoint.items():
            websocket_results[endpoint] = {
                "active_connections": 0,
                "finished_connections": 0,
                "error_connections": 0,
                "active_workers": 0,
                "last_heartbeat": 0,
            }

            for identity, metrics in identities.items():
                # Check if worker is active based on heartbeat
                last_heartbeat = metrics.get("last_heartbeat", 0)
                if (current_time - last_heartbeat) < HEARTBEAT_TIMEOUT:
                    websocket_results[endpoint]["active_workers"] += 1

                # Always sum the connections if the worker was active recently
                if (
                    current_time - last_heartbeat
                ) < HEARTBEAT_TIMEOUT * 2:  # Give extra time for connections to be counted
                    websocket_results[endpoint]["active_connections"] += int(
                        metrics.get("active_connections", 0)
                    )
                    websocket_results[endpoint]["finished_connections"] += int(
                        metrics.get("finished_connections", 0)
                    )
                    websocket_results[endpoint]["error_connections"] += int(
                        metrics.get("error_connections", 0)
                    )

                websocket_results[endpoint]["last_heartbeat"] = max(
                    websocket_results[endpoint]["last_heartbeat"], last_heartbeat
                )

        # Similar process for task tracker results
        task_by_endpoint = {}
        for key, values in zip(task_keys, all_values[len(ws_keys) :]):
            endpoint = key.decode().split(":", 1)[1]
            if endpoint not in task_by_endpoint:
                task_by_endpoint[endpoint] = {}

            # Group by identity first
            for field, value in values.items():
                identity, metric = field.decode().split(":", 1)
                if identity not in task_by_endpoint[endpoint]:
                    task_by_endpoint[endpoint][identity] = {}
                task_by_endpoint[endpoint][identity][metric] = float(value)

        # Aggregate task metrics across identities
        task_results = {}
        for endpoint, identities in task_by_endpoint.items():
            task_results[endpoint] = {
                "total_completed": 0,
                "total_pending": 0,
                "avg_completion_time": 0,
                "active_workers": 0,
                "last_heartbeat": 0,
            }

            total_completed = 0
            weighted_time_sum = 0

            for identity, metrics in identities.items():
                last_heartbeat = metrics.get("last_heartbeat", 0)
                if (current_time - last_heartbeat) < HEARTBEAT_TIMEOUT:
                    task_results[endpoint]["active_workers"] += 1
                    completed = int(metrics.get("completed_tasks", 0))
                    task_results[endpoint]["total_completed"] += completed
                    task_results[endpoint]["total_pending"] += int(
                        metrics.get("pending_tasks", 0)
                    )

                    # Weight avg_completion_time by number of completed tasks
                    if completed > 0:
                        avg_time = metrics.get("avg_completion_time", 0)
                        if avg_time > 0:
                            weighted_time_sum += avg_time * completed
                            total_completed += completed

                task_results[endpoint]["last_heartbeat"] = max(
                    task_results[endpoint]["last_heartbeat"], last_heartbeat
                )

            # Calculate weighted average completion time
            if total_completed > 0:
                task_results[endpoint]["avg_completion_time"] = (
                    weighted_time_sum / total_completed
                )

        return websocket_results, task_results

    async def close(self):
        await self.redis_client.aclose()


if __name__ == "__main__":

    async def main():
        monitor_store = CentralMonitorStore()
        try:
            websocket_status, task_tracker_status = (
                await monitor_store.get_aggregated_status()
            )
            print(websocket_status)
            print(task_tracker_status)
        finally:
            await monitor_store.close()

    # redis.Redis(host="localhost", port=6379, db=0).flushall()
    asyncio.run(main())
