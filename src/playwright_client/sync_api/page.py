import requests

# from playwright_client.sync_api.context import BrowserContext


class Page:
    def __init__(self, page_id: str, context: "BrowserContext"):
        self._page_id = page_id
        self._context = context
        self._browser = context._browser
        self.base_url = self._browser.base_url

    def goto(
        self,
        url: str,
        timeout: float = None,
        wait_until: str = None,
        referer: str = None,
    ):
        response = requests.post(
            f"{self.base_url}/send_and_wait",
            json={
                "command": "browser_navigate",
                "context_id": self._context._context_id,
                "page_id": self._page_id,
                "params": {
                    "url": url,
                    "timeout": timeout,
                    "wait_until": wait_until,
                    "referer": referer,
                },
            },
        ).json()
        status = response["status"]
        if status == "finished":
            return self
        else:
            raise Exception(response["error"])

    def go_back(self, timeout: float = None, wait_until: str = None):
        response = requests.post(
            f"{self.base_url}/send_and_wait",
            json={
                "command": "browser_navigate_back",
                "context_id": self._context._context_id,
                "page_id": self._page_id,
                "params": {"timeout": timeout, "wait_until": wait_until},
            },
        ).json()
        status = response["status"]
        if status == "finished":
            return self
        else:
            raise Exception(response["error"])

    def content(self):
        response = requests.post(
            f"{self.base_url}/send_and_wait",
            json={
                "command": "browser_observation",
                "context_id": self._context._context_id,
                "page_id": self._page_id,
                "params": {"observation_type": "html"},
            },
        ).json()
        status = response["status"]
        if status == "finished":
            return response["result"]["result"]["observation"]
        else:
            raise Exception(response["error"])
