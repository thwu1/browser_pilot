"""
Browser Worker Module

This module implements the browser worker component of the Remote Browser Automation Service.
It manages browser processes and contexts, handles commands and observations, and provides
reliability features for browser automation.
"""

import asyncio
import logging
import os
import signal
import sys
import time
import uuid
import base64
import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Set, Union

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import zmq
import traceback
from utils import make_zmq_socket
from utils import JsonEncoder, JsonDecoder
from utils import MSG_TYPE_READY, MSG_TYPE_STATUS, MSG_TYPE_OUTPUT
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("worker.log")],
)
logger = logging.getLogger(__name__)

# Constants
MAX_CONTEXTS_PER_PROCESS = int(os.environ.get("MAX_CONTEXTS_PER_PROCESS", "5"))
CONTEXT_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("CONTEXT_IDLE_TIMEOUT_SECONDS", "300")
)  # 5 minutes
HEALTH_CHECK_INTERVAL_SECONDS = int(
    os.environ.get("HEALTH_CHECK_INTERVAL_SECONDS", "30")
)
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "True").lower() == "true"


class ContextState(Enum):
    """States for a browser context"""

    INITIALIZING = "initializing"
    ACTIVE = "active"
    IDLE = "idle"
    HIBERNATED = "hibernated"
    FAILED = "failed"
    TERMINATED = "terminated"


@dataclass
class BrowserWorkerTask:
    """Task for browser worker execution"""

    task_id: str = ""
    context_id: Optional[str] = None
    page_id: Optional[str] = None
    command: str = ""
    params: Dict[str, Any] = None

    engine_recv_timestamp: float = 0
    engine_send_timestamp: float = 0
    worker_recv_timestamp: float = 0
    worker_start_process_timestamp: float = 0
    worker_finish_process_timestamp: float = 0
    worker_send_timestamp: float = 0

    def __post_init__(self):
        assert self.task_id != "", "task_id must be specified"
        assert self.command != "", "command must be specified"
        # assert self.engine_recv_timestamp != 0, "engine_recv_timestamp must be specified"
        # assert self.engine_send_timestamp != 0, "engine_send_timestamp must be specified"
        if self.params is None:
            self.params = {}
        if self.worker_recv_timestamp == 0:
            self.worker_recv_timestamp = time.time()


@dataclass
class ContextInfo:
    """Information about a browser context"""

    context_id: str
    browser_context: Optional[BrowserContext] = None
    state: ContextState = ContextState.INITIALIZING
    pages: Dict[str, Page] = None
    last_activity_time: float = 0
    creation_time: float = 0
    hibernation_data: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.pages is None:
            self.pages = {}
        if self.creation_time == 0:
            self.creation_time = time.time()
        self.last_activity_time = time.time()

@dataclass
class WorkerStatus:
    index: int
    ready: bool
    num_running_tasks: int
    num_waiting_tasks: int
    num_finished_tasks: int
    num_contexts: int
    num_pages: int
    avg_latency_ms: float
    throughput_per_sec: float
    cpu_usage_percent: float
    memory_usage_mb: float
    error_rate: float
    last_activity: float
    last_heartbeat: float

    def to_dict(self):
        return json.dumps(self.__dict__)

class AsyncBrowserWorker:
    """
    Browser Worker manages a single browser process with multiple browser contexts.
    It handles browser commands, observations, and provides reliability features.
    """

    def __init__(self, index: int = None):
        """Initialize the browser worker"""
        self.index = index
        self.browser: Optional[Browser] = None
        self.playwright = None
        self.contexts: Dict[str, ContextInfo] = {}
        self.running = False
        self.last_health_check = 0
        self.event_loop = None

        # Task queue system
        self.input_queue = asyncio.Queue()
        self.output_queue = asyncio.Queue()

        # status
        self.lam = 0.9
        self.ready = False
        self.num_running_tasks = 0
        self.num_finished_tasks = 0
        self.num_contexts = 0
        self.num_pages = 0
        self.avg_latency_ms = 0
        self.throughput_per_sec = 0
        self.error_rate = 0
        self.last_activity_time = time.time()

        logger.info(f"Initializing BrowserWorker with ID: {self.index}")

    async def start(self):
        """Start the browser worker and launch a browser process"""
        if self.running:
            return

        logger.info(f"Starting BrowserWorker {self.index}")
        self.running = True
        self.event_loop = asyncio.get_running_loop()

        try:
            # Launch playwright browser
            self.playwright = await async_playwright().start()

            # Launch browser with appropriate options
            browser_type = self.playwright.chromium
            self.browser = await browser_type.launch(headless=BROWSER_HEADLESS)

            self.ready = True
            logger.info(f"BrowserWorker {self.index} started successfully")
        except Exception as e:
            self.running = False
            logger.error(f"Error starting BrowserWorker: {e}")
            if self.playwright:
                await self.playwright.stop()
            raise e
    
    def is_ready(self) -> bool:
        return self.ready

    async def add_task(self, task: Dict):
        """Add a task to the queue for execution"""
        if not self.running:
            raise RuntimeError("Worker is not running")

        logger.info(f"Adding task to queue: {task}")

        self.input_queue.put_nowait(task)
        return task.task_id

    async def process_task_queue_loop(self):
        """Process tasks from the queue in the background"""
        while self.running:
            logger.info(
                f"Processing task queue loop, input queue size: {self.input_queue.qsize()}, output queue size: {self.output_queue.qsize()}"
            )
            try:
                # Wait for tasks when the queue is empty
                while self.input_queue.qsize() == 0:
                    logger.debug(
                        f"Waiting for tasks, input queue size is 0, inside blocking get"
                    )
                    task = await self.input_queue.get()
                    logger.debug(
                        f"Received task {task.task_id}, step out of blocking get"
                    )
                    self.event_loop.create_task(self._execute_task(task))
                    self.num_running_tasks += 1
                    logger.debug(
                        f"Start executing task {task.task_id}, input queue size: {self.input_queue.qsize()}"
                    )

                # Process all available tasks without blocking
                while self.input_queue.qsize() > 0:
                    logger.debug(
                        f"Processing available tasks, input queue size: {self.input_queue.qsize()}"
                    )
                    task = self.input_queue.get_nowait()
                    self.event_loop.create_task(self._execute_task(task))
                    self.num_running_tasks += 1
                    logger.debug(
                        f"Start executing task {task.task_id}, input queue size: {self.input_queue.qsize()}"
                    )

            except asyncio.CancelledError:
                logger.info("Task processor cancelled")
                return
            except Exception as e:
                logger.error(f"Error in task processor: {str(e)}")
                await asyncio.sleep(0.1)  # Brief pause to avoid CPU spinning

    async def _execute_task(self, task: BrowserWorkerTask):
        """Execute a single task and put result in result queue"""
        try:
            logger.debug(f"Executing task {task.task_id}")
            result = await self.execute_command(
                task.context_id, task.page_id, task.command, task.params
            )

            # Put result in the result queue
            finish_timestamp = time.time()
            self.output_queue.put_nowait(
                {
                    "task_id": task.task_id,
                    "page_id": result.get("page_id", None),
                    "result": result,
                    "success": True,
                    "timestamp": finish_timestamp,
                }
            )
            self.last_activity_time = time.time()
            self.num_finished_tasks += 1
            self.avg_latency_ms = self.lam * self.avg_latency_ms + (finish_timestamp - task.worker_recv_timestamp) * (1 - self.lam)
            self.error_rate = self.lam * self.error_rate + (1 - self.lam)

        except Exception as e:
            # Log error and queue error result
            logger.error(f"Error executing task {task.task_id}: {str(e)}")
            self.output_queue.put_nowait(
                {
                    "task_id": task.task_id,
                    "error": str(e),
                    "success": False,
                    "timestamp": time.time(),
                }
            )
            self.error_rate = self.lam * self.error_rate + (1 - self.lam)
        finally:
            self.num_running_tasks -= 1

    # async def stop(self):
    #     """Stop the browser worker and cleanup resources"""
    #     if not self.running:
    #         return

    #     logger.info(f"Stopping BrowserWorker {self.worker_id}")
    #     self.running = False

    #     # Cancel the task processor
    #     if self._task_processor:
    #         self._task_processor.cancel()
    #         try:
    #             await self._task_processor
    #         except asyncio.CancelledError:
    #             pass

    #     # Terminate all remaining contexts
    #     for context_id in list(self.contexts.keys()):
    #         try:
    #             await self.terminate_context(context_id)
    #         except Exception as e:
    #             logger.error(f"Error terminating context {context_id}: {e}")

    #     # Close browser and stop playwright
    #     if self.browser:
    #         try:
    #             await self.browser.close()
    #         except Exception as e:
    #             logger.error(f"Error closing browser: {e}")

    #     if self.playwright:
    #         try:
    #             await self.playwright.stop()
    #         except Exception as e:
    #             logger.error(f"Error stopping playwright: {e}")

    #     self.browser = None
    #     self.playwright = None
    #     logger.info(f"BrowserWorker {self.worker_id} stopped")

    async def create_context(
        self, context_id: str, context_options: Dict[str, Any] = None
    ) -> str:
        if not self.running or not self.browser:
            await self.start()

        # Check if we have capacity for a new context
        # if len(self.contexts) >= MAX_CONTEXTS_PER_PROCESS:
        #     raise RuntimeError(f"Maximum number of contexts ({MAX_CONTEXTS_PER_PROCESS}) reached")

        assert (
            context_id and context_id not in self.contexts
        ), f"Context {context_id} already exists"

        # Create context info
        context_info = ContextInfo(
            context_id=context_id,
            state=ContextState.INITIALIZING,
        )
        self.contexts[context_id] = context_info

        try:
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

            browser_context = await self.browser.new_context(**options)

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

            # Update context info
            context_info.browser_context = browser_context
            context_info.state = ContextState.ACTIVE
            context_info.last_activity_time = time.time()

            logger.info(
                f"Created browser context {context_id}, context info: {context_info}"
            )
            return context_id
        except Exception as e:
            if context_id in self.contexts:
                del self.contexts[context_id]
            logger.error(f"Failed to create browser context: {e}")
            raise

    async def has_context(self, context_id: str) -> bool:
        return context_id in self.contexts

    async def terminate_context(self, context_id: str):
        if context_id not in self.contexts:
            logger.warning(f"Context {context_id} not found for termination")
            return

        context_info = self.contexts[context_id]

        try:
            # Close the browser context if it exists
            if context_info.browser_context:
                await context_info.browser_context.close()

            # Update state and remove from contexts
            context_info.state = ContextState.TERMINATED
            del self.contexts[context_id]

            logger.info(f"Terminated browser context {context_id}")
        except Exception as e:
            logger.error(f"Error terminating context {context_id}: {e}")
            # Mark as failed but still remove from contexts
            context_info.state = ContextState.FAILED
            if context_id in self.contexts:
                del self.contexts[context_id]
            raise

    # async def hibernate_context(self, context_id: str) -> Dict[str, Any]:
    #     """
    #     Hibernate a browser context by saving its state and closing it

    #     Args:
    #         context_id: ID of the context to hibernate

    #     Returns:
    #         Dictionary containing hibernation state data
    #     """
    #     if context_id not in self.contexts:
    #         raise ValueError(f"Context {context_id} not found")

    #     context_info = self.contexts[context_id]

    #     if context_info.state not in (ContextState.ACTIVE, ContextState.IDLE):
    #         raise ValueError(f"Cannot hibernate context in state {context_info.state}")

    #     try:
    #         # Collect state data (cookies, storage, etc.)
    #         # In a real implementation, this would capture more state
    #         cookies = await context_info.browser_context.cookies()
    #         storage_state = await context_info.browser_context.storage_state()

    #         hibernation_data = {
    #             "cookies": cookies,
    #             "storage_state": storage_state,
    #             "timestamp": time.time()
    #         }

    #         # Close the browser context
    #         await context_info.browser_context.close()

    #         # Update context info
    #         context_info.browser_context = None
    #         context_info.hibernation_data = hibernation_data
    #         context_info.state = ContextState.HIBERNATED

    #         logger.info(f"Hibernated browser context {context_id}")
    #         return hibernation_data
    #     except Exception as e:
    #         logger.error(f"Failed to hibernate context {context_id}: {e}")
    #         context_info.state = ContextState.FAILED
    #         raise

    # async def reactivate_context(self, context_id: str, hibernation_data: Dict[str, Any] = None) -> bool:
    #     """
    #     Reactivate a hibernated browser context

    #     Args:
    #         context_id: ID of the context to reactivate
    #         hibernation_data: Optional hibernation data if not stored in context_info

    #     Returns:
    #         True if reactivation was successful
    #     """
    #     if context_id not in self.contexts:
    #         raise ValueError(f"Context {context_id} not found")

    #     context_info = self.contexts[context_id]

    #     if context_info.state != ContextState.HIBERNATED:
    #         raise ValueError(f"Cannot reactivate context in state {context_info.state}")

    #     # Use provided hibernation data or data from context_info
    #     data = hibernation_data or context_info.hibernation_data
    #     if not data:
    #         raise ValueError("No hibernation data available")

    #     try:
    #         # Create a new browser context
    #         browser_context = await self.browser.new_context()

    #         # Restore state from hibernation data
    #         if "storage_state" in data:
    #             await browser_context.add_cookies(data.get("cookies", []))

    #             # Additional state restoration would go here
    #             # This is a simplified implementation

    #         # Update context info
    #         context_info.browser_context = browser_context
    #         context_info.state = ContextState.ACTIVE
    #         context_info.last_activity_time = time.time()
    #         context_info.hibernation_data = None  # Clear hibernation data

    #         # Reset pages dictionary since we need new page objects
    #         context_info.pages = {}

    #         logger.info(f"Reactivated browser context {context_id}")
    #         return True
    #     except Exception as e:
    #         logger.error(f"Failed to reactivate context {context_id}: {e}")
    #         context_info.state = ContextState.FAILED
    #         raise

    async def execute_command(
        self, context_id: str, page_id: str, command: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Execute a browser command in the specified context

        Args:
            context_id: ID of the context to execute the command in
            command: Command to execute
            params: Parameters for the command

        Returns:
            Result of the command execution
        """
        if context_id not in self.contexts and command != "create_context":
            raise ValueError(f"Context {context_id} not found")

        if command != "create_context":
            context_info = self.contexts[context_id]

            # Reactivate if hibernated
            if context_info.state == ContextState.HIBERNATED:
                await self.reactivate_context(context_id)

            if context_info.state != ContextState.ACTIVE:
                raise ValueError(
                    f"Context {context_id} is not active (state: {context_info.state})"
                )

            context_info.last_activity_time = time.time()

        # Execute command
        try:
            params = params or {}
            result = {}

            logger.debug(f"Executing command: {command} with params: {params}")

            if command == "create_context":
                await self.create_context(context_id, params)
                result = {"success": True, "context_id": context_id, "page_id": None}
                context_info = self.contexts[context_id]
                context_info.state = ContextState.ACTIVE
                context_info.last_activity_time = time.time()

            elif command == "browser_navigate":
                page, page_id = await self._get_or_create_page(
                    context_id, params.get("page_id")
                )
                # Use 'load' state and timeout
                wait_until = params.get("wait_until", "load")
                timeout = params.get("timeout", 2000)
                await page.goto(params["url"], wait_until=wait_until, timeout=timeout)
                # Add a small safety delay for the page to stabilize
                await asyncio.sleep(0.1)
                result = {
                    "success": True,
                    "url": page.url,
                    "page_id": page_id,
                    "context_id": context_id,
                }

            elif command == "browser_navigate_back":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                timeout = params.get("timeout", 2000)
                await page.go_back()
                try:
                    await page.wait_for_load_state("load", timeout=timeout)
                except Exception as e:
                    logger.warning(
                        f"Timeout or error waiting for load state after navigate_back: {e}"
                    )
                await asyncio.sleep(0.1)
                result = {
                    "success": True,
                    "page_id": page_id,
                    "context_id": context_id,
                    "url": page.url,
                }

            elif command == "browser_navigate_forward":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                timeout = params.get("timeout", 2000)
                await page.go_forward()
                try:
                    await page.wait_for_load_state("load", timeout=timeout)
                except Exception as e:
                    logger.warning(
                        f"Timeout or error waiting for load state after navigate_forward: {e}"
                    )
                await asyncio.sleep(0.1)
                result = {
                    "success": True,
                    "url": page.url,
                    "page_id": page_id,
                    "context_id": context_id,
                }

            elif command == "browser_click":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                timeout = params.get("timeout", 2000)

                # Clicking might trigger navigation
                try:
                    async with page.expect_navigation(
                        wait_until="load", timeout=timeout
                    ) as navigation_info:
                        await page.click(
                            params["selector"],
                            **{
                                k: v
                                for k, v in params.items()
                                if k not in ("selector", "page_id", "timeout")
                            },
                        )
                        try:
                            # Wait for navigation if it occurs
                            await navigation_info.value
                            # Navigation occurred, add a small delay for stability
                            await asyncio.sleep(0.1)
                            logger.info(
                                f"Navigation detected after clicking {params['selector']}"
                            )
                        except Exception as e:
                            # No navigation occurred, which is fine
                            if "Timeout" not in str(e):
                                logger.warning(
                                    f"Unexpected error during navigation wait after clicking: {str(e)}"
                                )
                except Exception as e:
                    # If expect_navigation fails entirely, fall back to regular click
                    logger.warning(
                        f"Could not set up navigation detection for clicking: {str(e)}"
                    )
                    await page.click(
                        params["selector"],
                        **{
                            k: v
                            for k, v in params.items()
                            if k not in ("selector", "page_id", "timeout")
                        },
                    )

                result = {"success": True, "page_id": page_id, "context_id": context_id}

            elif command == "browser_type":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                timeout = params.get("timeout", 2000)

                # There's a possibility that typing might trigger form submission
                # especially in forms with onchange events or auto-submit functionality
                try:
                    async with page.expect_navigation(
                        wait_until="load", timeout=timeout
                    ) as navigation_info:
                        # Type the text which may trigger navigation via form auto-submit
                        await page.type(
                            params["selector"],
                            params["text"],
                            **{
                                k: v
                                for k, v in params.items()
                                if k not in ("selector", "text", "page_id", "timeout")
                            },
                        )

                        try:
                            # Wait for navigation if it occurs
                            await navigation_info.value
                            # Navigation occurred, add a small delay for stability
                            await asyncio.sleep(0.1)
                            logger.info(
                                f"Navigation detected after typing in {params['selector']}"
                            )
                        except Exception as e:
                            # No navigation occurred, which is fine
                            if "Timeout" not in str(e):
                                logger.warning(
                                    f"Unexpected error during navigation wait after typing: {str(e)}"
                                )
                except Exception as e:
                    # If expect_navigation fails entirely, fall back to regular typing
                    logger.warning(
                        f"Could not set up navigation detection for typing: {str(e)}"
                    )
                    await page.type(
                        params["selector"],
                        params["text"],
                        **{
                            k: v
                            for k, v in params.items()
                            if k not in ("selector", "text", "page_id", "timeout")
                        },
                    )

                result = {"success": True, "page_id": page_id, "context_id": context_id}

            elif command == "browser_press_key":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                timeout = params.get("timeout", 2000)

                # Keys that commonly trigger navigation
                navigation_keys = ["Enter", "NumpadEnter", " ", "Space"]
                is_navigation_key = params["key"] in navigation_keys

                if is_navigation_key:
                    # For navigation-triggering keys, set up a navigation promise
                    # to detect if navigation occurs
                    async with page.expect_navigation(
                        wait_until="load", timeout=timeout
                    ) as navigation_info:
                        await page.keyboard.press(params["key"])
                        try:
                            # Try to wait for navigation if it happens
                            await navigation_info.value
                            # Navigation occurred, add a small delay for stability
                            await asyncio.sleep(0.1)
                            logger.info(
                                f"Navigation detected after pressing {params['key']}"
                            )
                        except Exception as e:
                            # No navigation occurred, which is fine too
                            if "Timeout" not in str(e):
                                logger.warning(
                                    f"Unexpected error during navigation wait: {str(e)}"
                                )
                else:
                    # For non-navigation keys, just press normally
                    await page.keyboard.press(params["key"])

                result = {"success": True, "page_id": page_id, "context_id": context_id}

            elif command == "browser_file_upload":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                if "selector" in params:
                    element_handle = await page.query_selector(params["selector"])
                    await element_handle.set_input_files(params["paths"])
                else:
                    # Find file input and upload to it
                    file_inputs = await page.query_selector_all('input[type="file"]')
                    if file_inputs:
                        await file_inputs[0].set_input_files(params["paths"])
                    else:
                        raise ValueError("No file input found on page")
                result = {"success": True, "page_id": page_id, "context_id": context_id}

            elif command == "browser_pdf_save":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                pdf_options = {k: v for k, v in params.items() if k != "page_id"}
                pdf_data = await page.pdf(**pdf_options)
                result = {
                    "success": True,
                    "pdf": pdf_data,
                    "page_id": page_id,
                    "context_id": context_id,
                }

            elif command == "browser_wait":
                wait_time = min(params.get("time", 1), 10)  # Cap at 10 seconds
                await asyncio.sleep(wait_time)
                result = {"success": True, "page_id": page_id, "context_id": context_id}

            elif command == "browser_close":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                await page.close()
                # Remove page from pages dictionary
                for page_id, p in list(context_info.pages.items()):
                    if p == page:
                        del context_info.pages[page_id]
                        break
                result = {"success": True, "page_id": page_id, "context_id": context_id}

            elif command == "browser_screenshot":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                # Convert camelCase params to snake_case for Playwright compatibility
                screenshot_params = {}
                for k, v in params.items():
                    if k == "page_id":
                        continue
                    if k == "fullPage":
                        screenshot_params["full_page"] = v
                    else:
                        screenshot_params[k] = v

                screenshot = await page.screenshot(**screenshot_params)
                result = {
                    "success": True,
                    "screenshot": screenshot,
                    "page_id": page_id,
                    "context_id": context_id,
                }

            elif command == "browser_evaluate":
                page, page_id = await self._get_page(context_id, params.get("page_id"))
                eval_result = await page.evaluate(params["script"], params.get("arg"))
                result = {
                    "success": True,
                    "result": eval_result,
                    "page_id": page_id,
                    "context_id": context_id,
                }
            elif command == "browser_observation":
                observation = await self._get_observation(
                    context_id, params["observation_type"], params
                )
                result = {
                    "success": True,
                    "observation": observation,
                    "page_id": page_id,
                    "context_id": context_id,
                }

            else:
                valid_commands = [
                    "browser_navigate",
                    "browser_navigate_back",
                    "browser_navigate_forward",
                    "browser_click",
                    "browser_type",
                    "browser_press_key",
                    "browser_file_upload",
                    "browser_pdf_save",
                    "browser_wait",
                    "browser_close",
                    "browser_screenshot",
                    "browser_evaluate",
                    "browser_observation",
                ]
                if command not in valid_commands:
                    raise ValueError(
                        f"Unknown command: {command}. Valid commands: {', '.join(valid_commands)}"
                    )
                else:
                    raise ValueError(
                        f"Command {command} is recognized but not properly implemented"
                    )

            logger.info(f"Executed command {command} in context {context_id}")
            return result

        except Exception as e:
            logger.error(
                f"Error executing command {command} in context {context_id}: {e}"
            )
            if "Target closed" in str(e) or "Session closed" in str(e):
                context_info.state = ContextState.FAILED
            raise

    async def _get_observation(
        self, context_id: str, observation_type: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Get an observation from the specified context

        Args:
            context_id: ID of the context to get the observation from
            observation_type: Type of observation to get
            params: Parameters for the observation

        Returns:
            Observation data
        """
        if context_id not in self.contexts:
            raise ValueError(f"Context {context_id} not found")

        context_info = self.contexts[context_id]

        # Reactivate if hibernated
        if context_info.state == ContextState.HIBERNATED:
            await self.reactivate_context(context_id)

        if context_info.state != ContextState.ACTIVE:
            raise ValueError(
                f"Context {context_id} is not active (state: {context_info.state})"
            )
        context_info.last_activity_time = time.time()

        # Get observation
        try:
            params = params or {}
            result = {}

            if observation_type == "html":
                page = await self._get_page(context_id, params.get("page_id"))
                content = await page.content()
                result = {"html": content}

            elif observation_type == "accessibility":
                page = await self._get_page(context_id, params.get("page_id"))
                accessibility = await page.accessibility.snapshot()
                result = {"accessibility": accessibility}
            else:
                raise ValueError(f"Unknown observation type: {observation_type}")

            logger.info(f"Got observation {observation_type} from context {context_id}")
            return result

        except Exception as e:
            logger.error(
                f"Error getting observation {observation_type} from context {context_id}: {e}"
            )
            if "Target closed" in str(e) or "Session closed" in str(e):
                context_info.state = ContextState.FAILED
            raise

    def get_status(self) -> WorkerStatus:
        return WorkerStatus(
            index=self.index,
            ready=self.ready,
            num_running_tasks=self.num_running_tasks,
            num_waiting_tasks=self.input_queue.qsize(),
            num_finished_tasks=self.num_finished_tasks,
            num_contexts=len(self.contexts),
            num_pages=sum(len(context_info.pages) for context_info in self.contexts.values()),
            avg_latency_ms=self.avg_latency_ms,
            throughput_per_sec=0,
            cpu_usage_percent=0,
            memory_usage_mb=0,
            error_rate=self.error_rate,
            last_heartbeat=0,   
            last_activity=self.last_activity_time,
        )
        

    async def _get_or_create_page(self, context_id: str, page_id: str = None) -> Page:
        """
        Get an existing page or create a new one

        Args:
            context_id: ID of the context
            page_id: Optional ID of the page

        Returns:
            Page object
        """
        context_info = self.contexts[context_id]

        if not context_info.browser_context:
            raise ValueError(f"No browser context available for {context_id}")

        page_id = page_id or str(uuid.uuid4())

        if page_id in context_info.pages:
            return context_info.pages[page_id]

        page = await context_info.browser_context.new_page()
        context_info.pages[page_id] = page

        return page, page_id

    async def _get_page(self, context_id: str, page_id: str = None) -> Page:
        """
        Get an existing page

        Args:
            context_id: ID of the context
            page_id: Optional ID of the page (uses first page if not provided)

        Returns:
            Page object
        """
        context_info = self.contexts[context_id]

        if not context_info.browser_context:
            raise ValueError(f"No browser context available for {context_id}")

        if not page_id:
            if not context_info.pages:
                return await self._get_or_create_page(context_id)
            return next(iter(context_info.pages.values()))

        if page_id not in context_info.pages:
            raise ValueError(f"Page {page_id} not found in context {context_id}")

        return context_info.pages[page_id], page_id


class AsyncBrowserWorkerProc:
    """
    Process implementation that runs an AsyncBrowserWorker and handles ZMQ communication.

    This class manages the worker process side of communication - binding ZMQ sockets,
    receiving tasks from the engine, and sending results back.
    """

    def __init__(self, index: int, input_path: str, output_path: str):
        logger.info(f"Initializing AsyncBrowserWorkerProc {index}")
        self.index = index
        self.identity = str(index).encode()
        self.input_path = input_path
        self.output_path = output_path

        self.ctx = zmq.Context()
        self.input_socket = make_zmq_socket(
            self.ctx,
            self.input_path,
            zmq.DEALER,
            bind=False,
            identity=self.identity,
        )
        self.output_socket = make_zmq_socket(
            self.ctx, self.output_path, zmq.PUSH, bind=False
        )

        self.worker = AsyncBrowserWorker(index)
        self.encoder = JsonEncoder()
        self.decoder = JsonDecoder()

    def close(self):
        self.input_socket.close()
        self.output_socket.close()
        self.ctx.term()
        self.worker.close()

    def _send_ready(self):
        assert self.worker.is_ready()
        self.output_socket.send_multipart(
            [self.identity, MSG_TYPE_READY, self.encoder(["READY"])], flags=zmq.NOBLOCK
        )

    @classmethod
    def run_background_loop(cls, index: int, input_path: str, output_path: str):
        """
        Run a worker process in the background with ZMQ communication

        Args:
            index: Unique identifier for this worker
            input_path: Path to receive tasks from
            output_path: Path to send results back to
        """
        proc = cls(index, input_path, output_path)
        worker = proc.worker

        async def main_loop():
            await worker.start()
            logger.info(
                f"Worker started with input_path={input_path}, output_path={output_path}"
            )
            # if worker.is_ready():
            proc._send_ready()

            tasks = [
                worker.process_task_queue_loop(),
                proc.process_incoming_socket_loop(),
                proc.process_outgoing_socket_loop(),
                proc.send_heartbeat_loop(),
            ]
            await asyncio.gather(*tasks)

        try:
            asyncio.run(main_loop())
        except KeyboardInterrupt:
            logger.info("Worker stopped by keyboard interrupt")
        except Exception as e:
            logger.error(f"Fatal error in worker: {e}")
            logger.error(traceback.format_exc())
        finally:
            proc.close()

    async def _recv(self):
        try:
            msg = self.input_socket.recv_multipart(flags=zmq.NOBLOCK)
            assert len(msg) == 1
            return self.decoder(msg[0])
        except zmq.Again:
            logger.debug(
                f"process_incoming_socket_loop running, input queue size: {self.worker.input_queue.qsize()}, output queue size: {self.worker.output_queue.qsize()}"
            )
            await asyncio.sleep(0.1)
            return None
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return None

    async def _send(self, outputs: List[Dict[str, Any]], msg_type: bytes):
        assert isinstance(outputs, list)
        self.output_socket.send_multipart([self.identity, msg_type, self.encoder(outputs)])

    async def process_incoming_socket_loop(self):
        while self.worker.running:
            try:
                tasks = await self._recv()
                if not tasks:
                    continue
                for task in tasks:
                    self.worker.input_queue.put_nowait(BrowserWorkerTask(**task))
                logger.debug(
                    f"Received {len(tasks)} tasks from client, first task: {tasks[0]}, input queue size: {self.worker.input_queue.qsize()}, output queue size: {self.worker.output_queue.qsize()}"
                )
            except zmq.Again:
                await asyncio.sleep(0.1)
                logger.debug(
                    f"process_incoming_socket_loop running, input queue size: {self.worker.input_queue.qsize()}, output queue size: {self.worker.output_queue.qsize()}"
                )
            except Exception as e:
                logger.error(f"Error processing incoming socket loop: {e}")
                await asyncio.sleep(0.1)

    async def process_outgoing_socket_loop(self):
        while self.worker.running:
            while self.worker.output_queue.qsize() == 0:
                logger.debug(
                    f"process_outgoing_socket_loop running, output queue size is 0"
                )
                await asyncio.sleep(0.1)

            outputs = []
            while self.worker.output_queue.qsize() > 0:
                outputs.append(self.worker.output_queue.get_nowait())
            assert len(outputs) > 0, "No outputs to send, this should not happen"
            logger.debug(f"Sending {len(outputs)} outputs to client")
            await self._send(outputs, MSG_TYPE_OUTPUT)

    async def send_heartbeat_loop(self):
        prev_num_finished_tasks = 0
        prev_time = time.time()
        while self.worker.running:
            await asyncio.sleep(1)
            status = self.worker.get_status()
            status.last_heartbeat = time.time()
            status.memory_usage_mb = psutil.Process().memory_info().rss / 1024 / 1024
            status.cpu_usage_percent = psutil.Process().cpu_percent()
            status.throughput_per_sec = (status.num_finished_tasks - prev_num_finished_tasks) / (time.time() - prev_time)

            prev_num_finished_tasks = status.num_finished_tasks
            prev_time = time.time()
            await self._send([status.to_dict()], MSG_TYPE_STATUS)


    def stop(self):
        self.worker.running = False
