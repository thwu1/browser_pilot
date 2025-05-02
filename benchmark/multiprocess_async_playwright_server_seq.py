import asyncio
import os
import random
import time

import pandas as pd
import uvloop
from playwright.async_api import async_playwright


async def setup(endpoint):
    playwright = await async_playwright().start()

    browser = await playwright.chromium.connect(endpoint)

    return browser, playwright


timeout = 240000


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
        options["viewport"] = {
            "width": random.randint(1000, 1920),
            "height": random.randint(1000, 1080),
        }

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


async def navigate(context, page, url, wait_until="domcontentloaded", timeout=timeout):
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


async def run_one_traj(browser, urls):
    try:
        cmds = ["create_context"]
        times = [time.time()]
        context = await create_context({}, browser=browser)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, None, urls[0])
        times.append(time.time())
        cmds.append("get_observation")
        observation = await get_observation(page)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, page, urls[1])
        times.append(time.time())
        cmds.append("get_observation")
        observation = await get_observation(page)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, page, urls[2])
        times.append(time.time())
        cmds.append("get_observation")
        observation = await get_observation(page)
        times.append(time.time())
        cmds.append("navigate")
        page = await navigate(context, page, urls[3])
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


async def _test_async_playwright(concurrency, browser):
    urls = [
        "https://www.youtube.com",
        "https://www.bilibili.com",
        "https://www.reddit.com",
        "https://www.amazon.com",
        "https://www.google.com",
        "https://www.facebook.com",
        "https://www.twitter.com",
        "https://www.instagram.com",
        # "https://www.netflix.com",
        # "https://www.microsoft.com",
        "https://www.apple.com",
        "https://www.yahoo.com",
        "https://www.wikipedia.org",
        "https://www.linkedin.com",
        "https://www.github.com",
        "https://www.stackoverflow.com",
        "https://www.twitch.tv",
        "https://www.pinterest.com",
        "https://www.ebay.com",
        "https://www.walmart.com",
        "https://www.nytimes.com",
        "https://www.cnn.com",
        "https://www.tiktok.com",
        "https://www.spotify.com",
        "https://www.discord.com",
        "https://www.whatsapp.com",
        "https://www.zoom.us",
        "https://www.dropbox.com",
        "https://www.medium.com",
        "https://www.quora.com",
        "https://www.tumblr.com",
        "https://www.vimeo.com",
        "https://www.dailymotion.com",
        "https://www.craigslist.org",
        "https://www.imdb.com",
        "https://www.yelp.com",
        "https://www.etsy.com",
        "https://www.alibaba.com",
        "https://www.indeed.com",
        "https://www.glassdoor.com",
    ]
    start_time = time.time()
    results = await asyncio.gather(
        *[run_one_traj(browser, urls[i * 4 : (i + 1) * 4]) for i in range(concurrency)]
    )
    end_time = time.time()
    print(
        f"Total time: {end_time - start_time} seconds, finished {sum([result != False for result in results])} trajectories"
    )

    durations = []
    cmds = []
    start_time = []
    for times, cmd in results:
        cmds.extend(cmd)
        durations.extend([times[i + 1] - times[i] for i in range(len(times) - 1)])
        start_time.extend(times[:-1])

    return pd.DataFrame({"cmds": cmds, "duration": durations, "start_time": start_time})


def test_async_playwright_server(concurrency, *args):
    # print(f"test_async_playwright_server {concurrency} {args}")
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    return _test_async_playwright(concurrency, *args)


if __name__ == "__main__":

    async def main():
        browser, playwright = await setup("ws://localhost:8000")
        await test_async_playwright_server(1, browser)
        await test_async_playwright_server(1, browser)
        await browser.close()
        await playwright.stop()

    asyncio.run(main())

# durations = []
# cmds = []
# start_time = []
# for times, cmd in results:
#     cmds.extend(cmd)
#     durations.extend([times[i + 1] - times[i] for i in range(len(times) - 1)])
#         start_time.extend(times[:-1])

#     import pandas as pd

#     df = pd.DataFrame({"cmds": cmds, "duration": durations, "start_time": start_time})
#     df.to_csv(f"multiprocess_async_playwright_{os.getpid()}.csv", index=False)
