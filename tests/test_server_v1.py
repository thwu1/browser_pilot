import concurrent.futures
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from urllib.parse import urljoin

import matplotlib.pyplot as plt
import pandas as pd
import pytest
import requests

# Server configuration
SERVER_HOST = "localhost"
SERVER_PORT = 9999
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


@pytest.fixture(scope="module", autouse=True)
def start_server():
    """Start the server before running tests"""
    server_process = subprocess.Popen(["python", "src/entrypoint/server_v1.py"])

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


def create_context():
    context_id = f"context_{uuid.uuid4().hex[:8]}"
    response = requests.post(
        urljoin(BASE_URL, "send_and_wait"),
        json={
            "command": "create_context",
            "context_id": context_id,
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
            "params": {"url": url, "timeout": 30000},
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
    response = create_context()
    responses.append(response.json())
    # print("create_context response: ", response.json())
    context_id = response.json()["result"]["result"]["context_id"]
    # print("create_context response: ", context_id)
    response = navigate(context_id, None, "https://www.youtube.com")
    responses.append(response.json())
    # print("navigate response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]
    page_id = response.json()["result"]["page_id"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    # print("get_observation response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.bilibili.com")
    responses.append(response.json())
    # print("navigate response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    # print("get_observation response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.nytimes.com")
    responses.append(response.json())
    # print("navigate response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    # print("get_observation response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.reddit.com")
    responses.append(response.json())
    # print("navigate response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    # print("get_observation response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.amazon.com")
    responses.append(response.json())
    # print("navigate response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    responses.append(response.json())
    # print("get_observation response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    return responses


def test_navigate_concurrent(parallel=32):
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = [executor.submit(test_navigate) for _ in range(parallel)]
        all_responses = []
        for future in futures:
            responses = future.result()
            all_responses.extend(responses)

    return all_responses


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
    except KeyError as e:
        print(f"Missing key in output: {e}, output: {output}")
        return False
    return True


def calculate_metrics(outputs):
    df = pd.DataFrame(
        columns=[
            "engine_recv",
            "engine_send",
            "worker_recv",
            "worker_start",
            "worker_finish",
            "worker_send",
        ]
    )
    for output in outputs:
        if not check_profile_completed(output):
            print(output["result"]["profile"])
    try:
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
    except KeyError as e:
        print(f"Missing key in output: {e}, output: {outputs[0]}")
        return None
    df["engine_recv"] = engine_recv
    df["engine_send"] = engine_send
    df["worker_recv"] = worker_recv
    df["worker_start"] = worker_start
    df["worker_finish"] = worker_finish
    df["worker_send"] = worker_send
    # df.to_csv("profile.csv", index=False)
    return df


def summary(df):
    # Calculate time differences
    df["schedule_time"] = df["engine_send"] - df["engine_recv"]
    df["send_communication_time"] = df["worker_recv"] - df["engine_send"]
    df["worker_input_queue_time"] = df["worker_start"] - df["worker_recv"]
    df["worker_process_time"] = df["worker_finish"] - df["worker_start"]
    df["worker_output_queue_time"] = df["worker_send"] - df["worker_finish"]
    df["total_time"] = df["worker_send"] - df["engine_recv"]

    # Create bar plot
    time_columns = [
        "schedule_time",
        "send_communication_time",
        "worker_input_queue_time",
        "worker_process_time",
        "worker_output_queue_time",
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

    return df


if __name__ == "__main__":
    #     # Send a create context request
    #     test_create_context()
    parallel = 64
    start_time = time.time()
    outputs = test_navigate_concurrent(parallel)
    end_time = time.time()
    print(f"Time taken: {end_time - start_time} seconds")
    df = calculate_metrics(outputs)
    df.to_csv(f"server_v1_{parallel}_profile.csv", index=False)
    summary(df)
