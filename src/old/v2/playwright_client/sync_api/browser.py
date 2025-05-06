import uuid

import requests
from playwright_client.sync_api.context import BrowserContext

SERVER_HOST = "localhost"
SERVER_PORT = 9999
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


class Browser:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self._contexts = []

    def new_context(self) -> BrowserContext:
        response = requests.post(
            f"{self.base_url}/send_and_wait",
            json={
                "command": "create_context",
                "context_id": f"context_{uuid.uuid4().hex[:8]}",
            },
        ).json()
        status = response["status"]
        if status == "finished":
            context_id = response["result"]["context_id"]
            context = BrowserContext(context_id, browser=self)
            self._contexts.append(context)
        return context

    @property
    def contexts(self):
        return self._contexts.copy()

    def close(self):
        for context in self._contexts:
            context.close()
