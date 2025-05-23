import asyncio
import os
import time

import pandas as pd
import uvloop
from playwright.async_api import async_playwright


async def setup():
    playwright = await async_playwright().start()

    # Launch browser with appropriate options
    browser_type = playwright.chromium
    browser = await browser_type.launch(headless=True)

    return browser, playwright


timeout = 30000


async def create_context(context_options, browser):
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

    browser_context = await browser.new_context(**options)

    # Add script to override navigator properties to avoid detection
    await browser_context.add_init_script(
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


async def navigate(context, page, url, wait_until="load", timeout=timeout):
    if page is None:
        page = await context.new_page()
    await page.goto(url, wait_until=wait_until, timeout=timeout)
    return page


async def get_observation(page, observation_type="html"):
    if observation_type == "html":
        content = await page.content()
        return {"html": content}
    elif observation_type == "accessibility":
        accessibility = await page.accessibility.snapshot()
        return {"accessibility": accessibility}
    else:
        raise ValueError(f"Unknown observation type: {observation_type}")


async def run_one_traj(browser):
    try:
        cmds = ["create_context"]
        times = [time.time()]
        context = await create_context({}, browser=browser)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, None, "https://www.youtube.com")
        times.append(time.time())
        cmds.append("get_observation")
        observation = await get_observation(page)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, page, "https://www.bilibili.com")
        times.append(time.time())
        cmds.append("get_observation")
        observation = await get_observation(page)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, page, "https://www.reddit.com")
        times.append(time.time())
        cmds.append("get_observation")
        observation = await get_observation(page)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, page, "https://www.amazon.com")
        times.append(time.time())
        cmds.append("get_observation")
        observation = await get_observation(page)
        times.append(time.time())
        cmds.append("close_context")
        await context.close()
        times.append(time.time())
        return times, cmds
    except Exception as e:
        print(f"Error in run_one_traj: {e}")
        return False


async def _test_async_playwright(concurrency):
    start_time = time.time()
    browser, playwright = await setup()
    results = await asyncio.gather(*[run_one_traj(browser) for _ in range(concurrency)])
    end_time = time.time()
    print(
        f"Total time: {end_time - start_time} seconds, finished {sum([result != False for result in results])} trajectories"
    )
    await browser.close()
    await playwright.stop()

    durations = []
    cmds = []
    start_time = []
    for times, cmd in results:
        cmds.extend(cmd)
        durations.extend([times[i + 1] - times[i] for i in range(len(times) - 1)])
        start_time.extend(times[:-1])

    return pd.DataFrame({"cmds": cmds, "duration": durations, "start_time": start_time})


def test_async_playwright(concurrency, *args):
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    return asyncio.run(_test_async_playwright(concurrency))


# if __name__ == "__main__":
#     asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
#     results = asyncio.run(main())

#     durations = []
#     cmds = []
#     start_time = []
#     for times, cmd in results:
#         cmds.extend(cmd)
#         durations.extend([times[i + 1] - times[i] for i in range(len(times) - 1)])
#         start_time.extend(times[:-1])

#     import pandas as pd

#     df = pd.DataFrame({"cmds": cmds, "duration": durations, "start_time": start_time})
#     df.to_csv(f"multiprocess_async_playwright_{os.getpid()}.csv", index=False)
