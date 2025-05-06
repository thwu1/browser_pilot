import os
import pathlib
from time import time

import bs4
import gymnasium as gym
import pytest

# register openended gym environments
import browsergym.async_core
import browsergym.async_core.action
from browsergym.async_core.action.highlevel import HighLevelActionSet
from browsergym.async_core.action.python import PythonActionSet
from browsergym.async_core.constants import BROWSERGYM_ID_ATTRIBUTE as BID_ATTR
from browsergym.utils.obs import flatten_dom_to_str
from cloud.env import CloudEnv

__SLOW_MO = 1000 if "DISPLAY_BROWSER" in os.environ else None
__HEADLESS = False if "DISPLAY_BROWSER" in os.environ else True
__TIMEOUT = 500

__DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
TEST_PAGE = f"file://{__DATA_DIR}/test_page.html"
BASIC_IFRAME_PAGE = f"file://{__DATA_DIR}/basic_iframe_site/basic_iframe_2.html"


def test_gym_env():
    env = CloudEnv(
        id="browsergym_async/openended",
        task_kwargs={"start_url": TEST_PAGE},
        headless=__HEADLESS,
        slow_mo=__SLOW_MO,
        timeout=__TIMEOUT,
        action_mapping={"type": "PythonActionSet"},
    )
    obs, info = env.reset()

    assert not obs["last_action_error"]

    obs, reward, term, trunc, info = env.step(
        f"""\
await page.get_by_label("Name:").click()
await page.get_by_label("Name:").fill("Janice")
await page.get_by_label("Name:").press("Tab")
await page.get_by_label("Email:").fill("janice@mail.com")
await page.get_by_label("Email:").press("Tab")
await page.get_by_label("Age:", exact=True).fill("21")
await page.get_by_label("Age:", exact=True).press("Tab")
"""
    )

    assert obs["last_action_error"] == ""
    assert reward == 0
    assert term == False
    assert trunc == False

    obs, reward, term, trunc, info = env.step(
        f"""\
await page.get_by_label("Message:").fill("Hello")
await page.get_by_label("Message:").press("Tab")
await page.get_by_label("Subscribe to newsletter").check()
await page.get_by_label("Subscribe to newsletter").press("Tab")
await page.get_by_role("button", name="Submit").press("Enter")
"""
    )

    assert obs["last_action_error"] == ""
    assert reward == 0
    assert term == False
    assert trunc == False

    obs, reward, term, trunc, info = env.step(
        f"""\
await page.get_by_label("LABEL DOES NOT EXIST:").fill("Hello")
await page.get_by_role("button", name="Submit").press("Enter")
"""
    )

    assert obs["last_action_error"] != ""
    assert reward == 0
    assert term == False
    assert trunc == False

    env.close()


def test_max_episode_steps():
    # no max_steps
    env = CloudEnv(
        id="browsergym_async/openended",
        task_kwargs={"start_url": TEST_PAGE},
        headless=__HEADLESS,
        slow_mo=__SLOW_MO,
        timeout=__TIMEOUT,
    )
    obs, info = env.reset()

    obs, reward, term, trunc, info = env.step("")

    assert term == False
    assert trunc == False

    obs, reward, term, trunc, info = env.step("")

    assert term == False
    assert trunc == False

    # # max_steps = 2
    # env = gym.make(
    #     "browsergym_async/openended",
    #     task_kwargs={"start_url": TEST_PAGE},
    #     headless=__HEADLESS,
    #     slow_mo=__SLOW_MO,
    #     timeout=__TIMEOUT,
    #     max_episode_steps=2,
    # )
    # obs, info = await env.reset()

    # obs, reward, term, trunc, info = await env.step("")

    # assert term == False
    # assert trunc == False

    # obs, reward, term, trunc, info = await env.step("")

    # assert term == False
    # assert trunc == True

    env.close()


def test_active_page():
    env = CloudEnv(
        id="browsergym_async/openended",
        task_kwargs={"start_url": TEST_PAGE},
        headless=__HEADLESS,
        slow_mo=__SLOW_MO,
        timeout=__TIMEOUT,
        action_mapping={"type": "PythonActionSet"},
    )
    obs, info = env.reset()

    assert len(obs["open_pages_urls"]) == 1
    assert obs["active_page_index"][0] == 0

    obs, reward, term, trunc, info = env.step("await page.context.new_page()")

    assert len(obs["open_pages_urls"]) == 2
    assert obs["active_page_index"][0] == 1

    obs, reward, term, trunc, info = env.step(
        "await page.context.pages[0].mouse.click(5, 5)"
    )

    assert len(obs["open_pages_urls"]) == 2
    assert obs["active_page_index"][0] == 0

    obs, reward, term, trunc, info = env.step(
        "await page.context.pages[1].mouse.click(5, 5)"
    )

    assert len(obs["open_pages_urls"]) == 2
    assert obs["active_page_index"][0] == 1

    obs, reward, term, trunc, info = env.step("await page.context.pages[1].close()")

    assert len(obs["open_pages_urls"]) == 1
    assert obs["active_page_index"][0] == 0

    obs, reward, term, trunc, info = env.step("await page.close()")

    assert len(obs["open_pages_urls"]) == 1
    assert obs["active_page_index"][0] == 0

    obs, reward, term, trunc, info = env.step("await page.context.new_page()")

    assert len(obs["open_pages_urls"]) == 2
    assert obs["active_page_index"][0] == 1

    obs, reward, term, trunc, info = env.step("await page.close()")

    assert len(obs["open_pages_urls"]) == 1
    assert obs["active_page_index"][0] == 0

    env.close()


def test_nested_iframes_default_demo_mode():
    demo_mode = "default"
    env = CloudEnv(
        id="browsergym_async/openended",
        task_kwargs={"start_url": BASIC_IFRAME_PAGE},
        headless=__HEADLESS,
        slow_mo=__SLOW_MO,
        timeout=__TIMEOUT,
        action_mapping={"type": "HighLevelActionSet", "demo_mode": demo_mode},
    )
    obs, info = env.reset()
    assert not obs["last_action_error"]

    soup = bs4.BeautifulSoup(flatten_dom_to_str(obs["dom_object"]), "lxml")
    inner_checkbox = soup.find("input", attrs={"id": "checkbox_2"})

    assert inner_checkbox.has_attr("checked")
    # click box
    action = f"""\
click({repr(inner_checkbox.get(BID_ATTR))})
"""
    click_start = time()
    obs, _, _, _, _ = env.step(action)
    click_end = time()
    # clicking should be slow in demo mode
    assert click_end - click_start > 1

    soup = bs4.BeautifulSoup(flatten_dom_to_str(obs["dom_object"]), "lxml")
    inner_checkbox = soup.find("input", attrs={"id": "checkbox_2"})
    # box is not checked; meaning it was clicked by the previous action
    assert not inner_checkbox.has_attr("checked")

    env.close()


# @pytest.mark.parametrize("global_demo_mode", [True, False])
# @pytest.mark.parametrize(
#     "demo_mode", [None, "off", "default", "only_visible_elements", "all_blue"]
# )
# def test_demo_mode(global_demo_mode: bool, demo_mode: str):
#     browsergym.async_core.action.set_global_demo_mode(global_demo_mode)

#     demo_mode_active = (global_demo_mode and demo_mode is None) or (
#         demo_mode is not None and demo_mode != "off"
#     )

#     env = gym.make(
#         "browsergym_async/openended",
#         task_kwargs={"start_url": TEST_PAGE},
#         headless=__HEADLESS,
#         slow_mo=__SLOW_MO,
#         timeout=__TIMEOUT,
#         action_mapping={"type": "HighLevelActionSet", "demo_mode": demo_mode},
#     )
#     obs, info = env.reset()
#     assert not obs["last_action_error"]

#     soup = bs4.BeautifulSoup(flatten_dom_to_str(obs["dom_object"]), "lxml")
#     email_field = soup.find("input", attrs={"id": "email"})
#     checkbox = soup.find("input", attrs={"id": "subscribe"})

#     # check that the email field is empty
#     assert email_field.get("value") == ""

#     # check that the box is not checked
#     assert not checkbox.has_attr("checked")

#     # click box
#     action = f"""\
# click({repr(checkbox.get(BID_ATTR))})
# """
#     obs, reward, terminated, truncated, info = env.step(action)
#     assert not obs["last_action_error"]

#     soup = bs4.BeautifulSoup(flatten_dom_to_str(obs["dom_object"]), "lxml")
#     checkbox = soup.find("input", attrs={"type": "checkbox", "id": "subscribe"})

#     # check that the box is checked
#     assert checkbox.has_attr("checked")

#     # clicking should be slow (only in demo mode)
#     action_time = info["action_exec_stop"] - info["action_exec_start"]
#     if demo_mode_active:
#         assert action_time > 2
#     else:
#         assert action_time <= 1.5

#     # fill box
#     action = f"""\
# fill({repr(email_field.get(BID_ATTR))}, "test@test")
# """
#     obs, reward, terminated, truncated, info = env.step(action)
#     assert not obs["last_action_error"]

#     soup = bs4.BeautifulSoup(flatten_dom_to_str(obs["dom_object"]), "lxml")

#     # email field has been filled correctly
#     email_field = soup.find("input", attrs={"id": "email"})
#     assert email_field.get("value") == "test@test"

#     # typing should be slow (only in demo mode)
#     action_time = info["action_exec_stop"] - info["action_exec_start"]
#     if demo_mode_active:
#         assert action_time > 2
#     else:
#         assert action_time <= 1.5

#     env.close()


@pytest.mark.parametrize("resizeable_window", (True, False))
@pytest.mark.parametrize("size", ((1600, 1200), (800, 800)))
def test_resizeable_window(resizeable_window, size):
    env = CloudEnv(
        id="browsergym_async/openended",
        task_kwargs={"start_url": TEST_PAGE},
        headless=__HEADLESS,
        slow_mo=__SLOW_MO,
        timeout=__TIMEOUT,
        viewport={"width": size[0], "height": size[1]},
        resizeable_window=resizeable_window,
    )
    obs, info = env.reset()
    assert not obs["last_action_error"]

    import numpy as np

    obs["screenshot"] = np.array(obs["screenshot"])

    assert (obs["screenshot"].shape[1], obs["screenshot"].shape[0]) == size

    env.close()


# if __name__ == "__main__":
#     # python -m tests.async.core.test_gym_envs
#     from ..utils import run_multiple_tests_concurrently
#     import asyncio

#     tests = [
#         test_gym_env(),
#         test_max_episode_steps(),
#         test_active_page(),
#         test_nested_iframes_default_demo_mode(),
#     ]

#     # Add all combinations for test_resizeable_window
#     for resizeable_window in [True, False]:
#         for size in [(1600, 1200), (800, 800)]:
#             tests.append(
#                 test_resizeable_window(resizeable_window=resizeable_window, size=size)
#             )

#     # Run all tests concurrently
#     run_multiple_tests_concurrently(tests)

#     # # Add all combinations for test_demo_mode
#     asyncio.run(test_demo_mode(global_demo_mode=True, demo_mode=None))
#     asyncio.run(test_demo_mode(global_demo_mode=False, demo_mode=None))
#     # asyncio.run(test_demo_mode(global_demo_mode=True, demo_mode="all_blue"))
#     # asyncio.run(test_demo_mode(global_demo_mode=False, demo_mode="all_blue"))
#     # asyncio.run(test_demo_mode(global_demo_mode=True, demo_mode="only_visible_elements"))
#     # asyncio.run(test_demo_mode(global_demo_mode=False, demo_mode="only_visible_elements"))
#     # asyncio.run(test_demo_mode(global_demo_mode=True, demo_mode="default"))
#     # asyncio.run(test_demo_mode(global_demo_mode=False, demo_mode="default"))
#     # asyncio.run(test_demo_mode(global_demo_mode=True, demo_mode="off"))
#     # asyncio.run(test_demo_mode(global_demo_mode=False, demo_mode="off"))
#     # for global_demo_mode in [True, False]:
#     #     tests = []
#     #     for demo_mode in [None, "off", "default", "only_visible_elements", "all_blue"]:
#     #         tests.append(test_demo_mode(global_demo_mode=global_demo_mode, demo_mode=demo_mode))
#     # run_multiple_tests_concurrently(tests)
