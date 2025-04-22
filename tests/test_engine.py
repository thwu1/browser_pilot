import asyncio
import threading
import time
import uuid

from async_engine import AsyncBrowserEngine
from engine import BrowserEngine, BrowserEngineConfig
from scheduler import SchedulerType
from worker import BrowserWorkerTask


def test_engine_basic():
    """Test that contexts maintain worker affinity and can be properly closed"""

    config = {
        "worker_client_config": {
            "input_path": "ipc://test_input_sync_affinity",
            "output_path": "ipc://test_output_sync_affinity",
            "num_workers": 3,
        },
        "scheduler_config": {
            "type": SchedulerType.ROUND_ROBIN,
            "max_batch_size": 5,
            "n_workers": 3,
        },
    }

    engine = BrowserEngine(BrowserEngineConfig(**config))
    engine_thread = threading.Thread(target=engine.engine_core_loop)
    engine_thread.daemon = True
    engine_thread.start()

    try:
        # First batch: Create 5 contexts
        first_batch_contexts = []
        for _ in range(5):
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            context_id = f"{uuid.uuid4().hex[:8]}"
            first_batch_contexts.append(context_id)
            engine.add_task(
                BrowserWorkerTask(
                    task_id=task_id, command="create_context", context_id=context_id
                )
            )

        # Wait for first batch to complete
        max_wait = 30
        start_time = time.time()
        while len(engine.output_dict) < 5 and time.time() - start_time < max_wait:
            time.sleep(0.1)

        assert engine.waiting_queue.qsize() == 0, "First batch tasks not processed"

        # Store the worker assignments for first batch
        prev_context_worker_mapping = {}
        for task_id, task in engine.task_tracker.items():
            prev_context_worker_mapping[task["task"].context_id] = task["worker_id"]

        # Verify all first batch tasks completed successfully
        for task_id, msg in engine.output_dict.items():
            assert msg["result"]["success"], f"Task {task_id} failed"

        # Second batch: Create 7 new contexts and close the previous ones
        for _ in range(7):
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            context_id = f"{uuid.uuid4().hex[:8]}"
            engine.add_task(
                BrowserWorkerTask(
                    task_id=task_id, command="create_context", context_id=context_id
                )
            )

        # Add close commands for first batch contexts
        for context_id in first_batch_contexts:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            engine.add_task(
                BrowserWorkerTask(
                    task_id=task_id, command="browser_close", context_id=context_id
                )
            )

        # Wait for all tasks to complete
        total_tasks = 5 + 7 + 5  # First batch + Second batch + Close commands
        start_time = time.time()
        while (
            len(engine.output_dict) < total_tasks
            and time.time() - start_time < max_wait
        ):
            time.sleep(0.1)

        assert engine.waiting_queue.qsize() == 0, "Not all tasks were processed"

        # Get final context to worker mapping
        context_worker_mapping = {}
        for context_id in engine.context_tracker:
            context_worker_mapping[context_id] = engine.context_tracker[context_id]

        # Verify context affinity was maintained
        for context_id in first_batch_contexts:
            assert (
                prev_context_worker_mapping[context_id]
                == context_worker_mapping[context_id]
            ), f"Context {context_id} changed workers"

        # Verify all tasks completed successfully
        assert len(engine.output_dict) == total_tasks, "Not all tasks completed"
        for task_id, task in engine.task_tracker.items():
            assert task["status"] == "finished", f"Task {task_id} did not finish"

        for task_id, msg in engine.output_dict.items():
            assert msg["result"]["success"], f"Task {task_id} failed"

    finally:
        engine._shutdown()
        engine_thread.join(timeout=5)


def test_async_engine_basic():
    config = {
        "worker_client_config": {
            "input_path": "ipc://test_input_sync_affinity",
            "output_path": "ipc://test_output_sync_affinity",
            "num_workers": 3,
        },
        "scheduler_config": {
            "type": SchedulerType.ROUND_ROBIN,
            "max_batch_size": 5,
            "n_workers": 3,
        },
    }

    engine = AsyncBrowserEngine(BrowserEngineConfig(**config))
    loop = asyncio.get_event_loop()
    loop.create_task(engine.engine_core_loop())

    async def test_task():
        future = await engine.add_task(
            BrowserWorkerTask(
                task_id="test_task_1",
                command="create_context",
                context_id="test_context_1",
            )
        )

        result = await asyncio.wait_for(future, timeout=20)
        assert result["result"]["success"], "Create context failed"

        future = await engine.add_task(
            BrowserWorkerTask(
                task_id="test_task_2",
                command="browser_navigate",
                context_id="test_context_1",
                params={"url": "https://www.example.com"},
            )
        )

        result = await asyncio.wait_for(future, timeout=20)
        assert result["result"]["success"], "Navigate failed"

        future = await engine.add_task(
            BrowserWorkerTask(
                task_id="test_task_3",
                command="browser_observation",
                context_id="test_context_1",
                params={"observation_type": "html"},
            )
        )
        result = await asyncio.wait_for(future, timeout=20)
        assert result["result"]["success"], "Observe failed"

    loop.run_until_complete(test_task())
    loop.run_until_complete(engine._shutdown())
    loop.close()


# if __name__ == "__main__":
#     test_async_engine_basic()
