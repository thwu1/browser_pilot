from worker import AsyncBrowserWorkerProcess

from worker_client import BrowserWorkerClient

import multiprocessing as mp
import time
import uuid
import asyncio
import zmq

worker_id = "test_worker_cfa378c0"

# Define ports for ZMQ communication
task_port = 47281
result_port = 47221

client = BrowserWorkerClient(worker_id, task_port, result_port)

if __name__ == "__main__":
    process = mp.Process(target=AsyncBrowserWorkerProcess.run_background_loop, args=(worker_id, task_port, result_port))
    process.daemon = True
    process.start()

    async def test():
        for i in range(100):
            await client.add_request({
                "command": "create_context",
                "task_id": f"task_{uuid.uuid4().hex[:8]}",
                "context_id": f"{uuid.uuid4().hex[:8]}"
            })

            result = None
            while result is None or "hello" in result:
                result = await client.get_result()

            print("client received result: ", result)
    
    asyncio.run(test())
    
    
