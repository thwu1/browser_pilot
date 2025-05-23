import asyncio
import logging
import multiprocessing as mp
import time
import uuid

from worker import AsyncBrowserWorkerProc
from worker_client import WorkerClient


def test_worker_heartbeat_basic():
    input_path = "ipc://input_sync.sock"
    output_path = "ipc://output_sync.sock"
    num_workers = 1

    client = WorkerClient(input_path, output_path, num_workers)

    for _ in range(5):
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "create_context",
                    "task_id": task_id,
                    "context_id": f"{uuid.uuid4().hex[:8]}",
                }
            ],
            index=0,
        )
    for _ in range(5):
        client.get_output()
    time.sleep(1.1)
    worker_status = client.get_worker_status_no_wait()
    assert worker_status[0]["num_finished_tasks"] == 5, worker_status
    assert worker_status[0]["num_contexts"] == 5, worker_status
    assert worker_status[0]["num_pages"] == 0, worker_status
    client.close()


def test_worker_heartbeat_multi_worker():
    input_path = "ipc://input_sync.sock"
    output_path = "ipc://output_sync.sock"
    num_workers = 3

    client = WorkerClient(input_path, output_path, num_workers)

    for _ in range(3):
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "create_context",
                    "task_id": task_id,
                    "context_id": f"{uuid.uuid4().hex[:8]}",
                }
            ],
            index=0,
        )
    for _ in range(4):
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "create_context",
                    "task_id": task_id,
                    "context_id": f"{uuid.uuid4().hex[:8]}",
                }
            ],
            index=1,
        )

    for _ in range(7):
        client.get_output()
    time.sleep(1.1)
    worker_status = client.get_worker_status_no_wait()
    assert worker_status[0]["num_finished_tasks"] == 3, worker_status
    assert worker_status[1]["num_finished_tasks"] == 4, worker_status
    assert worker_status[2]["num_finished_tasks"] == 0, worker_status

    client.close()


def test_heartbeat_pages():
    input_path = "ipc://input_sync.sock"
    output_path = "ipc://output_sync.sock"
    num_workers = 1

    client = WorkerClient(input_path, output_path, num_workers)

    async def test():
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        context_id = f"{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "create_context",
                    "task_id": task_id,
                    "context_id": context_id,
                }
            ],
            index=0,
        )
        result = await client.get_output_with_task_id(task_id, timeout=1000)
        time.sleep(1.1)
        worker_status = client.get_worker_status_no_wait()
        assert worker_status[0]["num_contexts"] == 1, worker_status
        assert worker_status[0]["num_pages"] == 0, worker_status

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "browser_navigate",
                    "task_id": task_id,
                    "context_id": context_id,
                    "params": {"url": "https://www.example.com", "timeout": 30000},
                }
            ],
            index=0,
        )
        result = await client.get_output_with_task_id(task_id)

        page_id = result["page_id"]
        time.sleep(1.1)
        worker_status = client.get_worker_status_no_wait()
        assert worker_status[0]["num_contexts"] == 1, worker_status
        assert worker_status[0]["num_pages"] == 1, worker_status
        assert worker_status[0]["num_finished_tasks"] == 2, worker_status

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "browser_close",
                    "task_id": task_id,
                    "context_id": context_id,
                    "params": {"page_id": page_id},
                }
            ],
            index=0,
        )
        result = await client.get_output_with_task_id(task_id)
        time.sleep(1.1)
        worker_status = client.get_worker_status_no_wait()
        assert worker_status[0]["num_contexts"] == 1, worker_status
        assert worker_status[0]["num_pages"] == 0, worker_status
        assert worker_status[0]["num_finished_tasks"] == 3, worker_status

    asyncio.run(test())
    client.close()
