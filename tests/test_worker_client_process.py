# #!/usr/bin/env python3
# """
# Test for the communication between BrowserWorkerClient and AsyncBrowserWorkerProcess.

# This test verifies that:
# 1. A client can send requests to a worker process
# 2. The worker process can execute those requests
# 3. The client can receive results back from the worker process
# """

# import os
# import sys
# import asyncio
# import unittest
# import logging
# import time
# import multiprocessing
# import uuid
# import json
# import zmq
# import tempfile
# from typing import Dict, Any, List, Tuple, Optional, Callable

# # Add parent directory to path
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# # Import the modules to test
# from worker_client import BrowserWorkerClient
# from worker import AsyncBrowserWorkerProcess

# # Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)


# class TestWorkerClientProcess(unittest.TestCase):
#     """Test the communication between worker client and process"""
    
#     def setUp(self):
#         """Set up test environment"""
#         # Generate random worker ID
#         self.worker_id = f"test_worker_{uuid.uuid4().hex[:8]}"
        
#         # Define ports for ZMQ communication
#         self.task_port = 5555
#         self.result_port = 5556
        
#         # Start worker process
#         self.worker_process = None
#         self.client = None
        
#     def tearDown(self):
#         """Clean up after test"""
#         # Close client if it exists
#         if self.client:
#             try:
#                 # Don't use asyncio.run in tearDown as it could be inside an event loop
#                 # Just close the socket connections directly
#                 if hasattr(self.client, 'task_socket') and self.client.task_socket:
#                     self.client.task_socket.close()
#                 if hasattr(self.client, 'result_socket') and self.client.result_socket:
#                     self.client.result_socket.close()
#                 self.client = None
#                 logger.info("Closed BrowserWorkerClient")
#             except Exception as e:
#                 logger.error(f"Error closing client: {e}")
        
#         # Terminate worker process if running
#         if self.worker_process and self.worker_process.is_alive():
#             logger.info(f"Terminating worker process (PID: {self.worker_process.pid})")
            
#             # First try to send a shutdown message
#             try:
#                 # Create a temporary client to send shutdown message
#                 context = zmq.Context()
#                 socket = context.socket(zmq.PUSH)
#                 socket.connect(f"tcp://127.0.0.1:{self.task_port}")
                
#                 # Send shutdown message
#                 shutdown_msg = {
#                     "type": "shutdown",
#                     "task_id": f"shutdown_{uuid.uuid4().hex[:8]}",
#                     "worker_id": self.worker_id
#                 }
#                 socket.send_string(json.dumps(shutdown_msg))
#                 logger.info("Sent shutdown message to worker")
                
#                 # Give it a moment to process
#                 time.sleep(1)
                
#                 # Close socket
#                 socket.close()
#                 context.term()
#             except Exception as e:
#                 logger.error(f"Error sending shutdown message: {e}")
            
#             # If process is still alive, terminate it
#             if self.worker_process.is_alive():
#                 self.worker_process.terminate()
#                 logger.info("Forcefully terminated worker process")
            
#             # Wait for process to exit
#             self.worker_process.join(timeout=2)
            
#             # If still alive after join timeout, kill it
#             if self.worker_process.is_alive():
#                 logger.warning("Worker process did not exit cleanly, killing it")
#                 try:
#                     import os
#                     import signal
#                     os.kill(self.worker_process.pid, signal.SIGKILL)
#                 except Exception as e:
#                     logger.error(f"Error killing worker process: {e}")
                    
#         logger.info("Teardown complete")

#     async def _start_worker_and_client(self):
#         """Start the worker process and create a client"""
#         # Start worker process
#         await self._start_worker_process()
        
#         # Create client
#         self.client = BrowserWorkerClient(self.worker_id, self.task_port, self.result_port)
#         logger.info("Created BrowserWorkerClient")
        
#         return self.client
        
#     async def _start_worker_process(self):
#         """Start the worker process in a separate process"""
#         # Create and start process
#         self.worker_process = multiprocessing.Process(
#             target=AsyncBrowserWorkerProcess.run_worker_process,
#             args=(self.worker_id, self.task_port, self.result_port)
#         )
#         self.worker_process.daemon = True
#         self.worker_process.start()
#         logger.info(f"Started worker process (PID: {self.worker_process.pid})")
        
#         # Wait for process to initialize (give it time to bind ports)
#         await asyncio.sleep(2)
    
#     async def _create_context(self, client):
#         """Create a browser context and return its ID"""
#         # Send create context request
#         logger.info("Creating browser context")
#         request = {
#             "type": "create_context",
#             "task_id": f"task_{uuid.uuid4().hex[:8]}"
#         }
        
#         task_id = await client.add_request(request)
#         logger.info(f"Sent context creation request with task_id: {task_id}")
        
#         # Wait for and get result
#         context_id = None
#         for _ in range(10):  # Try up to 10 times
#             result = await client.get_result(timeout=1.0)
#             if result and result.get("task_id") == task_id:
#                 logger.info(f"Received result: {result}")
#                 self.assertTrue(result.get("success"), "Create context should succeed")
#                 context_id = result.get("result", {}).get("context_id")
#                 self.assertIsNotNone(context_id, "Context ID should be returned")
#                 break
#             await asyncio.sleep(0.5)
            
#         self.assertIsNotNone(context_id, "Failed to get context ID")
#         return context_id
    
#     async def _execute_command(self, client, context_id, command, params, wait_time=15):
#         """Execute a command on a browser context and return the result"""
#         # Send command request
#         logger.info(f"Executing {command} command")
#         request = {
#             "type": "execute_command",
#             "task_id": f"task_{uuid.uuid4().hex[:8]}",
#             "context_id": context_id,
#             "command": command,
#             "params": params
#         }
        
#         task_id = await client.add_request(request)
#         logger.info(f"Sent command execution request with task_id: {task_id}")
        
#         # Wait for and get result
#         result = None
#         for _ in range(wait_time * 2):  # Try for the specified wait time
#             try:
#                 response = await client.get_result(timeout=0.5)
#                 logger.info(f"Got response: {response}")
#                 if response and response.get("task_id") == task_id:
#                     logger.info(f"Received matching result for {command}: {response}")
#                     result = response
#                     break
#             except Exception as e:
#                 logger.error(f"Error getting result: {e}")
                
#             await asyncio.sleep(0.5)
            
#         self.assertIsNotNone(result, f"Failed to get result for {command}")
#         self.assertTrue(result.get("success", False), f"Command {command} failed: {result}")
#         return result
    
#     async def _terminate_context(self, client, context_id):
#         """Terminate a browser context"""
#         # Send terminate context request
#         logger.info("Terminating browser context")
#         request = {
#             "type": "terminate_context",
#             "task_id": f"task_{uuid.uuid4().hex[:8]}",
#             "context_id": context_id
#         }
        
#         task_id = await client.add_request(request)
#         logger.info(f"Sent context termination request with task_id: {task_id}")
        
#         # Wait for and get result
#         success = False
#         for _ in range(10):  # Try up to 10 times
#             result = await client.get_result(timeout=1.0)
#             if result and result.get("task_id") == task_id:
#                 logger.info(f"Received result: {result}")
#                 success = result.get("success", False)
#                 break
#             await asyncio.sleep(0.5)
            
#         self.assertTrue(success, "Terminate context should succeed")
    
#     # Now implement all the tests from test_async_worker.py
    
#     async def _test_worker_create_context(self):
#         """Test creating a browser context"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
#         self.assertIsNotNone(context_id, "Context creation failed")
    
#     async def _test_worker_create_context_and_terminate(self):
#         """Test creating and terminating a browser context"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
#         await self._terminate_context(client, context_id)
    
#     async def _test_navigation_commands(self):
#         """Test navigate, navigate_back, navigate_forward commands"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Test browser_navigate to example.com
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://example.com"}
#             )
            
#             # Get current URL to verify navigation
#             url_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "window.location.href"}
#             )
#             self.assertIn("example.com", url_result["result"]["result"], 
#                          f"Navigation failed, current URL: {url_result}")
            
#             # Navigate to a second page
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://mozilla.org"}
#             )
            
#             # Verify we navigated to the second page
#             url_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "window.location.href"}
#             )
#             logger.info(f"After navigation to mozilla.org, URL is: {url_result['result']['result']}")
            
#             # Test browser_navigate_back
#             await self._execute_command(
#                 client, context_id, "browser_navigate_back", {}
#             )
            
#             # Verify we're back at the first page
#             url_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "window.location.href"}
#             )
#             logger.info(f"After back navigation, URL is: {url_result['result']['result']}")
            
#             # Test browser_navigate_forward
#             await self._execute_command(
#                 client, context_id, "browser_navigate_forward", {}
#             )
            
#             # Verify we're forward to the second page
#             title_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "document.title"}
#             )
#             logger.info(f"After forward navigation, page title is: {title_result['result']['result']}")
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _test_interaction_commands(self):
#         """Test click, type, and press_key commands"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Navigate to a test page with form elements
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://wikipedia.org"}
#             )
            
#             # Test browser_click on the search input
#             await self._execute_command(
#                 client, context_id, "browser_click", {"selector": 'input#searchInput'}
#             )
            
#             # Test browser_type to type in the search box
#             await self._execute_command(
#                 client, context_id, "browser_type", {
#                     "selector": 'input#searchInput', 
#                     "text": "Playwright automation"
#                 }
#             )
            
#             # Test browser_press_key to press Enter
#             await self._execute_command(
#                 client, context_id, "browser_press_key", {"key": "Enter"}
#             )
            
#             # Get page title to verify the search
#             title_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "document.title"}
#             )
#             logger.info(f"After search, page title is: {title_result['result']['result']}")
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _test_file_operations(self):
#         """Test file_upload and pdf_save commands"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Navigate to a simple page for PDF testing
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://example.com"}
#             )
            
#             # Test browser_pdf_save
#             pdf_result = await self._execute_command(
#                 client, context_id, "browser_pdf_save", {}
#             )
            
#             # Verify PDF data is returned
#             self.assertIn("result", pdf_result, "PDF result missing")
#             self.assertIn("pdf", pdf_result["result"], "PDF data not returned")
            
#             # Save the PDF to verify it's valid
#             pdf_data = pdf_result["result"]["pdf"]
#             # The data comes as base64-encoded string, decode it
#             import base64
#             binary_pdf_data = base64.b64decode(pdf_data)
            
#             with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
#                 temp_file.write(binary_pdf_data)
#                 temp_path = temp_file.name
            
#             logger.info(f"Saved PDF to temporary file: {temp_path}")
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _test_utility_commands(self):
#         """Test screenshot, wait, evaluate, and close commands"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Navigate to a test page
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://example.com"}
#             )
            
#             # Test browser_wait
#             await self._execute_command(
#                 client, context_id, "browser_wait", {"time": 1}
#             )
            
#             # Test browser_screenshot
#             screenshot_result = await self._execute_command(
#                 client, context_id, "browser_screenshot", {}
#             )
            
#             # Verify screenshot data is returned
#             self.assertIn("result", screenshot_result, "Screenshot result missing")
#             self.assertIn("screenshot", screenshot_result["result"], "Screenshot data not returned")
            
#             # Save the screenshot to verify it's valid
#             screenshot_data = screenshot_result["result"]["screenshot"]
#             # The data comes as base64-encoded string, decode it
#             import base64
#             binary_screenshot_data = base64.b64decode(screenshot_data)
            
#             with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
#                 temp_file.write(binary_screenshot_data)
#                 temp_path = temp_file.name
            
#             logger.info(f"Saved screenshot to temporary file: {temp_path}")
            
#             # Test browser_evaluate
#             eval_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "document.title + ' - ' + document.URL"}
#             )
            
#             # Verify evaluation result
#             self.assertIn("result", eval_result, "Evaluation result missing")
#             self.assertIn("result", eval_result["result"], "Evaluation result data not returned")
#             self.assertIn("Example", eval_result["result"]["result"], 
#                          f"Unexpected evaluation result: {eval_result}")
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _test_click_navigation(self):
#         """Test that clicking on links properly handles navigation"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Navigate to a page with links
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://example.com"}
#             )
            
#             # Add a link to the page that we can click
#             await self._execute_command(
#                 client, context_id, "browser_evaluate", {
#                     "script": """
#                         const link = document.createElement('a');
#                         link.href = 'https://mozilla.org';
#                         link.id = 'test-link';
#                         link.textContent = 'Click me to navigate';
#                         document.body.appendChild(link);
#                     """
#                 }
#             )
            
#             # First verify we're on example.com
#             url_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "window.location.href"}
#             )
#             initial_url = url_result["result"]["result"]
#             logger.info(f"Initial URL: {initial_url}")
#             self.assertIn("example.com", initial_url, "Should start on example.com")
            
#             # Click the link which should trigger navigation
#             await self._execute_command(
#                 client, context_id, "browser_click", {"selector": "#test-link"}
#             )
            
#             # Check for navigation completion - we may need to wait a bit longer
#             url_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "window.location.href"},
#                 wait_time=30
#             )
#             new_url = url_result["result"]["result"]
#             logger.info(f"URL after clicking link: {new_url}")
            
#             # Check if URL changed to verify navigation occurred
#             self.assertIn("mozilla.org", new_url, "Navigation did not occur after clicking link")
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _test_type_submit_navigation(self):
#         """Test that typing in a form with auto-submit handles navigation properly"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Navigate to a page where we can add a form
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://example.com"}
#             )
            
#             # Add a form that submits after typing is complete
#             await self._execute_command(
#                 client, context_id, "browser_evaluate", {
#                     "script": """
#                         const form = document.createElement('form');
#                         form.id = 'test-form';
#                         form.action = 'https://mozilla.org';
#                         form.method = 'get';
                        
#                         const input = document.createElement('input');
#                         input.type = 'text';
#                         input.id = 'test-input';
#                         input.name = 'q';
                        
#                         // Add a button that we'll click to submit after typing
#                         const button = document.createElement('button');
#                         button.type = 'submit';
#                         button.id = 'submit-button';
#                         button.textContent = 'Search';
                        
#                         form.appendChild(input);
#                         form.appendChild(button);
#                         document.body.appendChild(form);
#                     """
#                 }
#             )
            
#             # First verify we're on example.com
#             url_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "window.location.href"}
#             )
#             initial_url = url_result["result"]["result"]
#             logger.info(f"Initial URL: {initial_url}")
#             self.assertIn("example.com", initial_url, "Should start on example.com")
            
#             # Type text into the input field (no auto-submit)
#             await self._execute_command(
#                 client, context_id, "browser_type", {
#                     "selector": "#test-input",
#                     "text": "test query"
#                 }
#             )
            
#             # Now click the submit button to trigger navigation
#             await self._execute_command(
#                 client, context_id, "browser_click", {"selector": "#submit-button"}
#             )
            
#             # Check if URL changed to verify navigation occurred
#             url_result = await self._execute_command(
#                 client, context_id, "browser_evaluate", {"script": "window.location.href"},
#                 wait_time=30
#             )
#             new_url = url_result["result"]["result"]
#             logger.info(f"URL after form submission: {new_url}")
            
#             # Verify navigation occurred
#             self.assertIn("mozilla.org", new_url, "Navigation did not occur after form submission")
#             self.assertIn("q=test+query", new_url, "Form data was not properly submitted")
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _test_worker_execute_command(self):
#         """Test executing a specific command"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Navigate to a page first
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://www.youtube.com"}
#             )
            
#             # Then navigate to another page (the actual test)
#             await self._execute_command(
#                 client, context_id, "browser_navigate", {"url": "https://www.example.com"}
#             )
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _test_spinup_loop(self):
#         """Test adding a task directly"""
#         client = await self._start_worker_and_client()
#         context_id = await self._create_context(client)
        
#         try:
#             # Add a navigation task
#             request = {
#                 "type": "execute_command",
#                 "task_id": "test_task",
#                 "context_id": context_id,
#                 "command": "browser_navigate",
#                 "params": {"url": "https://www.youtube.com"}
#             }
            
#             await client.add_request(request)
            
#             # Wait for result
#             success = False
#             for _ in range(30):  # Try for 15 seconds
#                 result = await client.get_result(timeout=0.5)
#                 if result and result.get("task_id") == "test_task":
#                     logger.info(f"Received result for test_task: {result}")
#                     success = result.get("success", False)
#                     break
#                 await asyncio.sleep(0.5)
                
#             self.assertTrue(success, "Task execution should succeed")
            
#         finally:
#             await self._terminate_context(client, context_id)
    
#     async def _run_single_test(self, test_func, *args):
#         """Helper to run a single test function"""
#         try:
#             await test_func(*args)
#             return True
#         except Exception as e:
#             logger.error(f"Test {test_func.__name__} failed with error: {e}")
#             import traceback
#             logger.error(traceback.format_exc())
#             return False
    
#     # Test case 1: Basic context creation
#     def test_01_worker_create_context(self):
#         """Test creating a browser context"""
#         asyncio.run(self._test_worker_create_context())
    
#     # Test case 2: Context creation and termination
#     def test_02_worker_create_context_and_terminate(self):
#         """Test creating and terminating a browser context"""
#         asyncio.run(self._test_worker_create_context_and_terminate())
    
#     # Test case 3: Navigation commands
#     def test_03_navigation_commands(self):
#         """Test navigation commands"""
#         asyncio.run(self._test_navigation_commands())
    
#     # Test case 4: Interaction commands
#     def test_04_interaction_commands(self):
#         """Test interaction commands"""
#         asyncio.run(self._test_interaction_commands())
    
#     # Test case 5: File operations
#     def test_05_file_operations(self):
#         """Test file operations"""
#         asyncio.run(self._test_file_operations())
    
#     # Test case 6: Utility commands
#     def test_06_utility_commands(self):
#         """Test utility commands"""
#         asyncio.run(self._test_utility_commands())
    
#     # Test case 7: Click navigation
#     def test_07_click_navigation(self):
#         """Test click navigation"""
#         asyncio.run(self._test_click_navigation())
    
#     # Test case 8: Type and submit navigation
#     def test_08_type_submit_navigation(self):
#         """Test form submission navigation"""
#         asyncio.run(self._test_type_submit_navigation())
    
#     # Test case 9: Execute specific command
#     def test_09_worker_execute_command(self):
#         """Test executing a specific command"""
#         asyncio.run(self._test_worker_execute_command())
    
#     # Test case 10: Spinup loop test
#     def test_10_spinup_loop(self):
#         """Test spin-up loop"""
#         asyncio.run(self._test_spinup_loop())

# # Run the tests
# if __name__ == "__main__":
#     unittest.main()
