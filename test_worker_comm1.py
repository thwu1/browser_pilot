from worker import AsyncBrowserWorkerProcess

from worker_client import BrowserWorkerClient

import multiprocessing as mp
import time
import uuid
import asyncio




worker_id = "test_worker_cfa378c0"

# Define ports for ZMQ communication
input_path = "tcp://localhost:6274"
output_path = "tcp://localhost:32751"

client = BrowserWorkerClient(worker_id, input_path, output_path)

if __name__ == "__main__":
    process = mp.Process(target=AsyncBrowserWorkerProcess.run_background_loop, args=(worker_id, input_path, output_path))
    # process.daemon = True
    process.start()

    time.sleep(2)
    # count = 0

    for i in range(100):
        client.add_request({
            "command": "create_context",
            "task_id": f"{4542+i}",
            "context_id": f"1234"
        })

        result = None
        while result is None:
            time.sleep(1)
            result = client.get_result()

        print("***********client received result: ", result)
    
    
    
    
