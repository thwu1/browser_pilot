import os
import time
import subprocess
import uuid
import requests
import pytest
import signal
import json
from urllib.parse import urljoin
import threading
import concurrent.futures

# Server configuration
SERVER_HOST = "localhost"
SERVER_PORT = 9999
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


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
    response = create_context()
    # print("create_context response: ", response.json())
    context_id = response.json()["result"]["result"]["context_id"]
    # print("create_context response: ", context_id)
    response = navigate(context_id, None, "https://www.youtube.com")
    # print("navigate response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]
    page_id = response.json()["result"]["page_id"]

    response = get_observation(context_id, page_id, "html")
    # print("get_observation response: ", response.json())
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.bilibili.com")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.nytimes.com")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.reddit.com")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = navigate(context_id, page_id, "https://www.amazon.com")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]

    response = get_observation(context_id, page_id, "html")
    assert response.status_code == 200, response
    assert response.json()["result"]["success"]


def test_navigate_concurrent():
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as executor:
        for _ in range(64):
            executor.submit(test_navigate)


if __name__ == "__main__":
    #     # Send a create context request
    #     test_create_context()
    start_time = time.time()
    test_navigate_concurrent()
    end_time = time.time()
    print(f"Time taken: {end_time - start_time} seconds")
