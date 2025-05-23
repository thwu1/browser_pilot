import os
import time

import pandas as pd
from playwright.sync_api import sync_playwright

# playwright = sync_playwright().start()

# # Launch browser with appropriate options
# browser_type = playwright.chromium
# browser = browser_type.launch(headless=True)

timeout = 30000


def setup():
    playwright = sync_playwright().start()

    # Launch browser with appropriate options
    browser_type = playwright.chromium
    browser = browser_type.launch(headless=True)

    return browser, playwright


def create_context(context_options={}, browser=None):
    # Create browser context with provided options
    options = context_options or {}

    # Set default user agent to a modern browser if not provided
    if "user_agent" not in options:
        options["user_agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )

    # Set default viewport if not provided
    if "viewport" not in options:
        options["viewport"] = {"width": 1920, "height": 1080}

    # Add device scale factor to make the browser look more realistic
    if "device_scale_factor" not in options:
        options["device_scale_factor"] = 1

    # Enable JavaScript by default
    options["java_script_enabled"] = options.get("java_script_enabled", True)

    browser_context = browser.new_context(**options)

    # Add script to override navigator properties to avoid detection
    browser_context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en', 'es']
        });
        window.chrome = {
            runtime: {}
        };
    """
    )

    return browser_context


def navigate(context, page, url, wait_until="load", timeout=timeout):
    if page is None:
        page = context.new_page()
    page.goto(url, wait_until=wait_until, timeout=timeout)
    return page


def get_observation(page, observation_type="html"):
    if observation_type == "html":
        content = page.content()
        return {"html": content}
    elif observation_type == "accessibility":
        accessibility = page.accessibility.snapshot()
        return {"accessibility": accessibility}
    else:
        raise ValueError(f"Unknown observation type: {observation_type}")


def single_traj(browser):
    times = [time.time()]
    cmds = ["create_context"]
    context = create_context(browser=browser)

    times.append(time.time())
    cmds.append("navigate")
    page = navigate(context, None, "https://www.youtube.com")

    times.append(time.time())
    cmds.append("get_observation")
    observation = get_observation(page)

    times.append(time.time())
    cmds.append("navigate")
    page = navigate(context, page, "https://www.bilibili.com")

    times.append(time.time())
    cmds.append("get_observation")
    observation = get_observation(page)

    times.append(time.time())
    cmds.append("navigate")
    page = navigate(context, page, "https://www.reddit.com")

    times.append(time.time())
    cmds.append("get_observation")
    observation = get_observation(page)

    times.append(time.time())
    cmds.append("navigate")
    page = navigate(context, page, "https://www.amazon.com")

    times.append(time.time())
    cmds.append("get_observation")
    observation = get_observation(page)

    times.append(time.time())
    cmds.append("close_context")
    context.close()
    times.append(time.time())

    return times, cmds


def test_sync_playwright(*args):

    time_ = time.time()
    browser, playwright = setup()
    times, cmds = single_traj(browser)
    print(f"Time taken: {time.time() - time_}")
    durations = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    start_time = times[:-1]
    assert len(durations) == len(start_time)

    df = pd.DataFrame({"cmds": cmds, "duration": durations, "start_time": start_time})
    browser.close()
    playwright.stop()
    return df


# if __name__ == "__main__":
#     time_ = time.time()
#     times, cmds = single_traj()
#     print(f"Time taken: {time.time() - time_}")
#     durations = [times[i + 1] - times[i] for i in range(len(times) - 1)]
#     start_time = times[:-1]
#     assert len(durations) == len(start_time)
#     import pandas as pd


#     df = pd.DataFrame({"cmds": cmds, "duration": durations, "start_time": start_time})
#     df.to_csv(f"multiprocess_async_playwright_{os.getpid()}.csv", index=False)
