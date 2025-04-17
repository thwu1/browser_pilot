from worker_client import WorkerClient
import uuid
import time
import multiprocessing as mp
from worker import AsyncBrowserWorkerProc
import logging


# logging.basicConfig(level=logging.INFO)


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

    time.sleep(3)
    assert client.output_queue.qsize() == 5
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

    time.sleep(3)

    assert client.output_queue.qsize() == 1

    result = client.output_queue.get()
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

    time.sleep(3)
    assert client.output_queue.qsize() == 1
    result = client.output_queue.get()
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
    time.sleep(3)
    assert client.output_queue.qsize() == 1
    result = client.output_queue.get()
    assert result[1]["result"]["success"] ==True, result
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

    time.sleep(5)
    assert client.output_queue.qsize() == 15
    client.close()
