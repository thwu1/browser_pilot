import asyncio
import concurrent.futures
import json
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from urllib.parse import urljoin

import httpx
import matplotlib.pyplot as plt
import pandas as pd
import pytest
import requests
import uvloop

# Server configuration
SERVER_HOST = "localhost"
SERVER_PORT = 9999
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


@pytest.fixture(scope="module", autouse=True)
def start_server():
    """Start the server before running tests"""
    server_process = subprocess.Popen(["python", "src/v1/entrypoint/server_v1.py"])

    # Wait for server to be ready by checking health endpoint
    max_retries = 20
    for i in range(max_retries):
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=1)
            if response.status_code == 200 and response.json().get("status") == "up":
                break
        except requests.RequestException:
            pass
        time.sleep(0.5)
        if i == max_retries - 1:
            server_process.terminate()
            raise RuntimeError("Server failed to start within timeout period")

    yield
    # Send SIGTERM for graceful shutdown
    server_process.terminate()
    # Wait up to 10 seconds for shutdown
    start_time = time.time()
    while time.time() - start_time < 10:
        if server_process.poll() is not None:  # Process has exited
            break
        time.sleep(0.5)
    # Force kill if still running
    if server_process.poll() is None:
        server_process.kill()


async def create_context_async(client=None):
    if client is None:
        async with httpx.AsyncClient(timeout=60) as temp_client:
            return await _create_context_async(temp_client)
    else:
        return await _create_context_async(client)


async def _create_context_async(client):
    response = await client.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "create_context",
            "context_id": f"context_{uuid.uuid4().hex[:8]}",
        },
    )
    return response


async def navigate_async(context_id, page_id, url, client=None):
    if client is None:
        async with httpx.AsyncClient(timeout=60) as temp_client:
            return await _navigate_async(context_id, page_id, url, temp_client)
    else:
        return await _navigate_async(context_id, page_id, url, client)


async def _navigate_async(context_id, page_id, url, client):
    response = await client.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "browser_navigate",
            "context_id": context_id,
            "page_id": page_id,
            "params": {"url": url, "timeout": 60000},
        },
    )
    return response


async def get_observation_async(context_id, page_id, observation_type, client=None):
    if client is None:
        async with httpx.AsyncClient(timeout=30) as temp_client:
            return await _get_observation_async(
                context_id, page_id, observation_type, temp_client
            )
    else:
        return await _get_observation_async(
            context_id, page_id, observation_type, client
        )


async def _get_observation_async(context_id, page_id, observation_type, client):
    response = await client.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "browser_observation",
            "context_id": context_id,
            "page_id": page_id,
            "params": {"observation_type": observation_type},
        },
    )
    return response


async def close_context(context_id, client=None):
    if client is None:
        async with httpx.AsyncClient(timeout=30) as temp_client:
            return await _close_context_async(context_id, temp_client)
    else:
        return await _close_context_async(context_id, client)


async def _close_context_async(context_id, client):
    response = await client.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "close_context",
            "context_id": context_id,
        },
    )
    return response


async def test_navigate_async(client=None):
    use_shared_client = client is not None
    if not use_shared_client:
        # Create a dedicated client for this test
        client = httpx.AsyncClient(
            timeout=60.0,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=32),
        )

    try:
        responses = []
        cmds = ["create_context"]
        response = await create_context_async(client)
        context_id = response.json()["result"]["result"]["context_id"]
        responses.append(response.json())

        cmds.append("navigate")
        response = await navigate_async(
            context_id, None, "https://www.youtube.com", client
        )
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]
        page_id = response.json()["result"]["page_id"]

        cmds.append("get_observation")
        response = await get_observation_async(context_id, page_id, "html", client)
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        cmds.append("navigate")
        response = await navigate_async(
            context_id, page_id, "https://www.bilibili.com", client
        )
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        cmds.append("get_observation")
        response = await get_observation_async(context_id, page_id, "html", client)
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        cmds.append("navigate")
        response = await navigate_async(
            context_id, page_id, "https://www.reddit.com", client
        )
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        cmds.append("get_observation")
        response = await get_observation_async(context_id, page_id, "html", client)
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        cmds.append("navigate")
        response = await navigate_async(
            context_id, page_id, "https://www.amazon.com", client
        )
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        cmds.append("get_observation")
        response = await get_observation_async(context_id, page_id, "html", client)
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        cmds.append("close_context")
        response = await close_context(context_id, client)
        responses.append(response.json())
        assert response.status_code == 200, response
        assert response.json()["result"]["success"]

        return responses, cmds
    finally:
        # Close the client if we created it
        if not use_shared_client:
            await client.aclose()


async def test_navigate_concurrent_async(parallel=256, batch_size=256):
    # Create a single shared client with a large connection pool
    async with httpx.AsyncClient(
        timeout=60.0,
        limits=httpx.Limits(
            max_connections=batch_size, max_keepalive_connections=batch_size
        ),
        http2=True,  # Enable HTTP/2 for better multiplexing if your server supports it
    ) as client:
        all_responses = []
        all_cmds = []

        # Process in batches to avoid overwhelming resources
        for i in range(0, parallel, batch_size):
            current_batch_size = min(batch_size, parallel - i)
            print(
                f"Processing batch {i//batch_size + 1}/{(parallel+batch_size-1)//batch_size}, size: {current_batch_size}"
            )

            # Create tasks for this batch
            tasks = [test_navigate_async(client) for _ in range(current_batch_size)]

            # Run this batch of tasks concurrently
            batch_responses = await asyncio.gather(*tasks)

            # Collect results
            for response, cmds in batch_responses:
                all_responses.extend(response)
                all_cmds.extend(cmds)

        return all_responses, all_cmds


def create_context():
    response = requests.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "create_context",
            "context_id": f"context_{uuid.uuid4().hex[:8]}",
        },
    )
    return response


def navigate(context_id, page_id, url):
    response = requests.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "browser_navigate",
            "context_id": context_id,
            "page_id": page_id,
            "params": {"url": url, "timeout": 60000},
        },
    )
    return response


def get_observation(context_id, page_id, observation_type):
    response = requests.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "browser_observation",
            "context_id": context_id,
            "page_id": page_id,
            "params": {"observation_type": observation_type},
        },
    )
    return response


def test_create_context():
    response = create_context()
    print("create_context response: ", response.json())
    assert response.status_code == 200
    assert response.json()["result"]["success"]


def test_navigate():
    responses = []
    cmds = []
    response = create_context()
    responses.append(response.json())
    cmds.append("create_context")
    context_id = response.json()["result"]["result"]["context_id"]
    response = navigate(context_id, None, "https://www.youtube.com")
    responses.append(response.json())
    cmds.append("navigate")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]
    page_id = response.json()["result"]["page_id"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    cmds.append("get_observation")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.bilibili.com")
    responses.append(response.json())
    cmds.append("navigate")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    cmds.append("get_observation")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.reddit.com")
    responses.append(response.json())
    cmds.append("navigate")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    cmds.append("get_observation")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.amazon.com")
    responses.append(response.json())
    cmds.append("navigate")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    cmds.append("get_observation")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    return responses, cmds


def test_navigate_threaded(threads=32):
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(test_navigate) for _ in range(threads)]
        all_responses = []
        all_cmds = []
        for future in futures:
            responses, cmds = future.result()
            all_responses.extend(responses)
            all_cmds.extend(cmds)
    return all_responses, all_cmds


def test_navigate_concurrent(parallel=32, num_processes=8):
    num_processes = min(num_processes, parallel)
    num_threads = parallel // num_processes
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_processes) as executor:
        futures = [
            executor.submit(test_navigate_threaded, num_threads)
            for _ in range(num_processes)
        ]
        all_responses = []
        all_cmds = []
        for future in futures:
            responses, cmds = future.result()
            all_responses.extend(responses)
            all_cmds.extend(cmds)
    return all_responses, all_cmds


def check_profile_completed(output):
    try:
        if output["result"]["profile"] is None:
            return False
        if output["result"]["profile"]["engine_recv_timestamp"] is None:
            return False
        if output["result"]["profile"]["engine_send_timestamp"] is None:
            return False
        if output["result"]["profile"]["worker_recv_timestamp"] is None:
            return False
        if output["result"]["profile"]["worker_start_process_timestamp"] is None:
            return False
        if output["result"]["profile"]["worker_finish_timestamp"] is None:
            return False
        if output["result"]["profile"]["worker_send_timestamp"] is None:
            return False
        if output["result"]["profile"]["engine_set_future_timestamp"] is None:
            return False
        if output["result"]["profile"]["app_init_timestamp"] is None:
            return False
        if output["result"]["profile"]["app_recv_timestamp"] is None:
            return False
    except KeyError as e:
        print(f"Missing key in output: {e}, output: {output}")
        return False
    return True


def calculate_metrics(outputs, cmds):
    df = pd.DataFrame(
        columns=[
            "app_init",
            "engine_recv",
            "engine_send",
            "worker_recv",
            "worker_start",
            "worker_finish",
            "worker_send",
            "engine_set_future",
            "app_recv",
            "cmds",
        ]
    )
    for output in outputs:
        if not check_profile_completed(output):
            print(output["result"]["profile"])
    try:
        app_init = [
            output["result"]["profile"]["app_init_timestamp"] for output in outputs
        ]
        engine_recv = [
            output["result"]["profile"]["engine_recv_timestamp"] for output in outputs
        ]
        engine_send = [
            output["result"]["profile"]["engine_send_timestamp"] for output in outputs
        ]
        worker_recv = [
            output["result"]["profile"]["worker_recv_timestamp"] for output in outputs
        ]
        worker_start = [
            output["result"]["profile"]["worker_start_process_timestamp"]
            for output in outputs
        ]
        worker_finish = [
            output["result"]["profile"]["worker_finish_timestamp"] for output in outputs
        ]
        worker_send = [
            output["result"]["profile"]["worker_send_timestamp"] for output in outputs
        ]
        engine_set_future = [
            output["result"]["profile"]["engine_set_future_timestamp"]
            for output in outputs
        ]
        app_recv = [
            output["result"]["profile"]["app_recv_timestamp"] for output in outputs
        ]
    except KeyError as e:
        print(f"Missing key in output: {e}, output: {outputs[0]}")
        return None

    df["app_init"] = app_init
    df["engine_recv"] = engine_recv
    df["engine_send"] = engine_send
    df["worker_recv"] = worker_recv
    df["worker_start"] = worker_start
    df["worker_finish"] = worker_finish
    df["worker_send"] = worker_send
    df["engine_set_future"] = engine_set_future
    df["app_recv"] = app_recv
    print(len(df))
    print(len(cmds))
    df["cmds"] = cmds
    return df


def summary(df):
    # Calculate time differences
    df["app_to_engine"] = df["engine_recv"] - df["app_init"]
    df["schedule_time"] = df["engine_send"] - df["engine_recv"]
    df["send_communication_time"] = df["worker_recv"] - df["engine_send"]
    df["worker_input_queue_time"] = df["worker_start"] - df["worker_recv"]
    df["worker_process_time"] = df["worker_finish"] - df["worker_start"]
    df["worker_output_queue_time"] = df["worker_send"] - df["worker_finish"]
    df["recv_communication_time"] = df["engine_set_future"] - df["worker_send"]
    df["engine_to_app"] = df["app_recv"] - df["engine_set_future"]
    df["total_time"] = df["app_recv"] - df["app_init"]

    # Create bar plot
    time_columns = [
        "app_to_engine",
        "schedule_time",
        "send_communication_time",
        "worker_input_queue_time",
        "worker_process_time",
        "worker_output_queue_time",
        "recv_communication_time",
        "engine_to_app",
    ]
    df[time_columns].mean().plot(kind="bar")

    plt.title("Average Time Distribution")
    plt.ylabel("Time (seconds)")
    plt.tight_layout()
    plt.savefig("time_distribution.png")
    plt.close()

    # Calculate percentages
    percentages = df[time_columns].sum() / df["total_time"].sum() * 100

    print("Percentage of total time for each stage:")
    for col, percentage in percentages.items():
        print(f"{col}: {percentage:.2f}%")

    print(
        "Total time calculated by summing individual tasks' time:",
        df["total_time"].sum(),
    )

    return df


if __name__ == "__main__":
    # Set higher ulimit for more open files (run this or a similar command in your shell)
    # import resource
    # resource.setrlimit(resource.RLIMIT_NOFILE, (10000, 10000))

    # Disable excessive logging
    # logging.basicConfig(level=logging.WARNING)

    # Use uvloop for faster event loop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    print(f"Running with 24 concurrent requests, optimized for speed...")
    start_time = time.time()
    outputs, cmds = asyncio.run(test_navigate_concurrent_async(24, batch_size=8))
    end_time = time.time()
    print(f"Time taken: {end_time - start_time} seconds")
    df = calculate_metrics(outputs, cmds)
    df = summary(df)
    df.to_csv(f"server_v1_async_{os.getpid()}.csv", index=False)

    # start_time = time.time()
    # outputs, cmds = test_navigate_threaded(8)
    # end_time = time.time()
    # df = calculate_metrics(outputs, cmds)
    # df = summary(df)
    # df.to_csv(f"server_v1_sync_{os.getpid()}.csv", index=False)
