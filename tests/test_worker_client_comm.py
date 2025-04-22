import asyncio
import logging
import multiprocessing as mp
import time
import uuid

from worker import AsyncBrowserWorkerProc
from worker_client import WorkerClient


def test_worker_client_communication_sync():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
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
        client.get_output(timeout=2)
    client.close()


def test_worker_client_communication_sync_multi_step():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
    num_workers = 1

    client = WorkerClient(input_path, output_path, num_workers)
    context_id = f"{uuid.uuid4().hex[:8]}"

    task_id = f"task_{uuid.uuid4().hex[:8]}"
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

    result = client.get_output(timeout=2)
    assert result[1]["result"]["success"] == True, result

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    client.send(
        [
            {
                "command": "browser_navigate",
                "task_id": task_id,
                "context_id": context_id,
                "params": {"url": "https://www.example.com"},
            }
        ],
        index=0,
    )

    result = client.get_output(timeout=2)
    assert result[1]["result"]["success"] == True, result
    page_id = result[1]["page_id"]

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    client.send(
        [
            {
                "command": "browser_observation",
                "task_id": task_id,
                "context_id": context_id,
                "page_id": page_id,
                "params": {"observation_type": "accessibility"},
            }
        ],
        index=0,
    )
    result = client.get_output(timeout=2)
    assert result[1]["result"]["success"] == True, result
    result = result[1]["result"]
    assert result["observation"] is not None, result["observation"]
    assert "accessibility" in result["observation"], result["observation"]

    client.close()


def test_multi_worker_client_communication_sync():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
    num_workers = 3

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
            index=2,
        )

    for _ in range(15):
        client.get_output(timeout=2)
    client.close()


def test_multi_worker_multi_step():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
    num_workers = 3

    client = WorkerClient(input_path, output_path, num_workers)

    async def run_three_steps(index: int):
        context_id = f"{uuid.uuid4().hex[:8]}"
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "create_context",
                    "task_id": task_id,
                    "context_id": context_id,
                }
            ],
            index=index,
        )
        result = await client.get_output_with_task_id(task_id)
        assert result["result"]["success"] == True

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
            index=index,
        )
        result = await client.get_output_with_task_id(task_id)
        assert result["result"]["success"] == True
        page_id = result["page_id"]

        task_id = f"task_{uuid.uuid4().hex[:8]}"
        client.send(
            [
                {
                    "command": "browser_observation",
                    "task_id": task_id,
                    "context_id": context_id,
                    "page_id": page_id,
                    "params": {"observation_type": "accessibility"},
                }
            ],
            index=index,
        )
        result = await client.get_output_with_task_id(task_id)
        assert result["result"]["success"] == True
        result = result["result"]
        assert "observation" in result, result
        assert "accessibility" in result["observation"], result["observation"]

    async def main():
        tasks = []
        for i in range(num_workers):
            task = asyncio.create_task(run_three_steps(i))
            tasks.append(task)
        await asyncio.gather(*tasks)

    asyncio.run(main())
    client.close()


def test_async_worker_shutdown():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
    num_workers = 2

    client = WorkerClient(input_path, output_path, num_workers)

    time.sleep(1)

    client.send(
        [
            {
                "command": "shutdown",
                "task_id": f"shutdown_{uuid.uuid4().hex[:8]}",
                "context_id": None,
                "page_id": None,
            }
        ],
        index=0,
    )
    time.sleep(1)

    client.send(
        [
            {
                "command": "create_context",
                "task_id": f"{uuid.uuid4().hex[:8]}",
                "context_id": f"{uuid.uuid4().hex[:8]}",
                "page_id": None,
            }
        ],
        index=0,
    )
    try:
        client.get_output(timeout=2)
        assert False, "Should have timed out"
    except TimeoutError:
        assert True

    client.send(
        [
            {
                "command": "create_context",
                "task_id": f"{uuid.uuid4().hex[:8]}",
                "context_id": f"{uuid.uuid4().hex[:8]}",
                "page_id": None,
            }
        ],
        index=1,
    )
    client.get_output(timeout=2)

    client.close()


if __name__ == "__main__":
    test_async_worker_shutdown()
