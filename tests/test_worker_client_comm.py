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

    time.sleep(5)
    assert client.output_queue.qsize() == 5
    client.close()


test_worker_client_communication_sync()
