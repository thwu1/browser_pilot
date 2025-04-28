import requests

# from playwright_client.sync_api.browser import Browser
# from playwright_client.sync_api.browser import Browser
from playwright_client.sync_api.page import Page


class BrowserContext:
    def __init__(self, context_id: str, browser: "Browser"):
        self._context_id = context_id
        self._browser = browser
        self._pages = []
        self.base_url = self._browser.base_url

    def new_page(self):
        response = requests.post(
            f"{self.base_url}/send_and_wait",
            json={"command": "create_page", "context_id": self._context_id},
        ).json()

        status = response["status"]
        if status == "finished":
            page_id = response["result"]["page_id"]
            page = Page(page_id, context=self)
            self._pages.append(page)
            return page
        else:
            raise Exception(response["error"])

    def close(self):
        response = requests.post(
            f"{self.base_url}/send_and_wait",
            json={"command": "close_context", "context_id": self._context_id},
        ).json()
        status = response["status"]
        if status == "finished":
            return
        else:
            raise Exception(response["error"])
