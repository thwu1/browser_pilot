from worker_client import WorkerClient
import uuid
import time
import multiprocessing as mp
from worker import AsyncBrowserWorkerProc
import logging
import asyncio


def test_worker_heartbeat_basic():
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
    time.sleep(2)
    worker_status = client.get_worker_status_no_wait()
    assert worker_status[0]["num_finished_tasks"] == 5, worker_status
    assert worker_status[0]["num_contexts"] == 5, worker_status
    assert worker_status[0]["num_pages"] == 0, worker_status
    client.close()

def test_worker_heartbeat_multi_worker():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
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
    
    time.sleep(2)
    worker_status = client.get_worker_status_no_wait()
    assert worker_status[0]["num_finished_tasks"] == 3, worker_status
    assert worker_status[1]["num_finished_tasks"] == 4, worker_status
    assert worker_status[2]["num_finished_tasks"] == 0, worker_status
    
    client.close()

def test_heartbeat_pages():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
    num_workers = 1

    client = WorkerClient(input_path, output_path, num_workers)

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
    time.sleep(2)
    worker_status = client.get_worker_status_no_wait()
    assert worker_status[0]["num_contexts"] == 1, worker_status
    assert worker_status[0]["num_pages"] == 0, worker_status
    client.get_output()
    
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
    time.sleep(2)
    index, result = client.get_output()
    page_id = result["page_id"]
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
    time.sleep(2)
    worker_status = client.get_worker_status_no_wait()
    print(worker_status)
    assert worker_status[0]["num_contexts"] == 1, worker_status
    assert worker_status[0]["num_pages"] == 0, worker_status
    assert worker_status[0]["num_finished_tasks"] == 3, worker_status
    client.close()

if __name__ == "__main__":
    # test_worker_heartbeat_basic()
    # test_worker_heartbeat_multi_worker()
    test_heartbeat_pages()
