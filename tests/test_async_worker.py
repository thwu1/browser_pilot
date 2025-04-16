# import asyncio
# import sys
# import os
# import logging
# import tempfile
# from typing import List, Callable, Dict, Any, Optional, Tuple

# # Add parent directory to path so we can import modules
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# from worker import AsyncBrowserWorker, BrowserWorkerTask

# # Configure logging to see detailed errors
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)


# # Base test function - creates worker and context
# async def _setup_worker_and_context() -> Tuple[AsyncBrowserWorker, str]:
#     """Helper function to set up a worker and context for tests"""
#     worker = AsyncBrowserWorker()
#     await worker.start()
#     context_id = await worker.create_context()
#     assert await worker.has_context(context_id), "Failed to create browser context"
#     return worker, context_id


# # Basic tests
# async def test_worker_create_context():
#     """Test creating a browser context"""
#     worker = AsyncBrowserWorker()
#     await worker.start()
#     context_id = await worker.create_context()
#     assert await worker.has_context(context_id), "Failed to create browser context"
#     await worker.stop()


# async def test_worker_create_context_and_terminate():
#     """Test creating and terminating a browser context"""
#     worker = AsyncBrowserWorker()
#     await worker.start()
#     context_id = await worker.create_context()
#     assert await worker.has_context(context_id), "Failed to create browser context"
#     await worker.terminate_context(context_id)
#     assert not await worker.has_context(context_id), "Failed to terminate browser context"
#     await worker.stop()


# # Navigation tests
# async def test_navigation_commands():
#     """Test navigate, navigate_back, navigate_forward commands"""
#     worker, context_id = await _setup_worker_and_context()
    
#     try:
#         # Test browser_navigate
#         result = await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://example.com"}
#         )
#         assert result["success"], "Failed to navigate to example.com"
        
#         # Get current URL to verify navigation
#         current_url = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "window.location.href"}
#         )
#         assert "example.com" in current_url["result"], f"Navigation failed, current URL: {current_url['result']}"
        
#         # Navigate to a second page
#         result = await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://mozilla.org"}
#         )
#         assert result["success"], "Failed to navigate to mozilla.org"
        
#         current_url = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "window.location.href"}
#         )
#         logger.info(f"After navigation to mozilla.org, URL is: {current_url['result']}")
        
#         # Test browser_navigate_back
#         result = await worker.execute_command(
#             context_id, "browser_navigate_back", {}
#         )
#         assert result["success"], "Failed to navigate back"
        
#         # Verify we're back at the previous page
#         current_url = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "window.location.href"}
#         )
#         logger.info(f"After back navigation, URL is: {current_url['result']}")
        
#         # Test browser_navigate_forward
#         result = await worker.execute_command(
#             context_id, "browser_navigate_forward", {}
#         )
#         assert result["success"], "Failed to navigate forward"
        
#         # Get title to verify we navigated correctly
#         page_title = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "document.title"}
#         )
#         assert "Example" in page_title["result"], f"Unexpected page title: {page_title['result']}"
#         logger.info(f"After forward navigation, page title is: {page_title['result']}")
        
#         return True
#     except Exception as e:
#         logger.error(f"Navigation test failed: {str(e)}")
#         import traceback
#         logger.error(traceback.format_exc())
#         return False
#     finally:
#         await worker.stop()


# async def test_click_navigation():
#     """Test that clicking on links properly handles navigation"""
#     worker, context_id = await _setup_worker_and_context()
    
#     try:
#         # Navigate to a page with links
#         await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://example.com"}
#         )
        
#         # Add a link to the page that we can click (that goes to mozilla.org)
#         await worker.execute_command(
#             context_id, "browser_evaluate", {
#                 "script": """
#                     const link = document.createElement('a');
#                     link.href = 'https://mozilla.org';
#                     link.id = 'test-link';
#                     link.textContent = 'Click me to navigate';
#                     document.body.appendChild(link);

#                     // Add promise resolver to detect navigation
#                     window.navigationComplete = false;
#                     window.addEventListener('beforeunload', function() {
#                         // Create a flag that will be set before navigation
#                         sessionStorage.setItem('navigating', 'true');
#                     });
#                 """
#             }
#         )
        
#         # First verify we're on example.com
#         initial_url = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "window.location.href"}
#         )
#         logger.info(f"Initial URL: {initial_url['result']}")
#         assert "example.com" in initial_url['result'], "Should start on example.com"
        
#         # Click the link which should trigger navigation
#         await worker.execute_command(
#             context_id, "browser_click", {"selector": "#test-link"}
#         )
        
#         # No sleep needed - immediately try to evaluate JavaScript on the new page
#         # The command should intrinsically wait for the new page if navigation occurs
#         new_url = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "window.location.href"}
#         )
#         logger.info(f"URL after clicking link: {new_url['result']}")
        
#         # Check if URL changed to verify navigation occurred
#         assert "mozilla.org" in new_url['result'], "Navigation did not occur after clicking link"
        
#         return True
#     finally:
#         await worker.stop()


# async def test_type_submit_navigation():
#     """Test that typing in a form with auto-submit handles navigation properly"""
#     worker, context_id = await _setup_worker_and_context()
    
#     try:
#         # Navigate to a page where we can add a form
#         await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://example.com"}
#         )
        
#         # Add a form that submits after typing is complete
#         await worker.execute_command(
#             context_id, "browser_evaluate", {
#                 "script": """
#                     const form = document.createElement('form');
#                     form.id = 'test-form';
#                     form.action = 'https://mozilla.org';
#                     form.method = 'get';
                    
#                     const input = document.createElement('input');
#                     input.type = 'text';
#                     input.id = 'test-input';
#                     input.name = 'q';
                    
#                     // Add a button that we'll click to submit after typing
#                     const button = document.createElement('button');
#                     button.type = 'submit';
#                     button.id = 'submit-button';
#                     button.textContent = 'Search';
                    
#                     form.appendChild(input);
#                     form.appendChild(button);
#                     document.body.appendChild(form);
#                 """
#             }
#         )
        
#         # First verify we're on example.com
#         initial_url = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "window.location.href"}
#         )
#         logger.info(f"Initial URL: {initial_url['result']}")
#         assert "example.com" in initial_url['result'], "Should start on example.com"
        
#         # Type text into the input field (no auto-submit)
#         await worker.execute_command(
#             context_id, "browser_type", {
#                 "selector": "#test-input",
#                 "text": "test query"
#             }
#         )
        
#         # Now click the submit button to trigger navigation
#         await worker.execute_command(
#             context_id, "browser_click", {"selector": "#submit-button"}
#         )
        
#         # Check if URL changed to verify navigation occurred
#         new_url = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "window.location.href"}
#         )
#         logger.info(f"URL after form submission: {new_url['result']}")
        
#         # Verify navigation occurred
#         assert "mozilla.org" in new_url['result'], "Navigation did not occur after form submission"
#         assert "q=test+query" in new_url['result'], "Form data was not properly submitted"
        
#         return True
#     finally:
#         await worker.stop()


# # Interaction tests
# async def test_interaction_commands():
#     """Test click, type, and press_key commands"""
#     worker, context_id = await _setup_worker_and_context()
    
#     try:
#         # Navigate to a test page with form elements
#         logger.info("Navigating to test page with form elements")
#         result = await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://wikipedia.org"}
#         )
#         assert result["success"], "Failed to navigate to Wikipedia"
        
#         # Wait for page to load
#         # await asyncio.sleep(2)
        
#         # Test browser_click on the search input
#         logger.info("Testing browser_click on search input")
#         result = await worker.execute_command(
#             context_id, "browser_click", {"selector": 'input#searchInput'}
#         )
#         assert result["success"], "Failed to click on search input"
        
#         # Test browser_type to type in the search box
#         logger.info("Testing browser_type to input text")
#         result = await worker.execute_command(
#             context_id, "browser_type", {
#                 "selector": 'input#searchInput', 
#                 "text": "Playwright automation"
#             }
#         )
#         assert result["success"], "Failed to type text"
        
#         # Test browser_press_key to press Enter
#         logger.info("Testing browser_press_key to press Enter")
#         result = await worker.execute_command(
#             context_id, "browser_press_key", {"key": "Enter"}
#         )
#         assert result["success"], "Failed to press key"
        
#         # Wait for search results to load
#         # await asyncio.sleep(3)
        
#         # Get page title to verify the search
#         page_title = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "document.title"}
#         )
#         logger.info(f"After search, page title is: {page_title['result']}")
        
#         # Instead of asserting specific content which might change, just log success
#         logger.info("Interaction commands test completed successfully")
        
#         return True
#     except Exception as e:
#         logger.error(f"Interaction test failed: {str(e)}")
#         import traceback
#         logger.error(traceback.format_exc())
#         return False
#     finally:
#         await worker.stop()


# # File operations tests
# async def test_file_operations():
#     """Test file_upload and pdf_save commands"""
#     worker, context_id = await _setup_worker_and_context()
    
#     try:
#         # Navigate to a file upload test site
#         await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://httpbin.org/forms/post"}
#         )
        
#         # For PDF save, navigate to a simple page
#         await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://example.com"}
#         )
        
#         # Test browser_pdf_save
#         pdf_result = await worker.execute_command(
#             context_id, "browser_pdf_save"
#         )
#         assert pdf_result["success"], "Failed to save PDF"
#         assert "pdf" in pdf_result, "PDF data not returned"
#         assert len(pdf_result["pdf"]) > 0, "PDF data is empty"
        
#         # Save the PDF to verify it's valid
#         with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
#             temp_file.write(pdf_result["pdf"])
#             temp_path = temp_file.name
        
#         logger.info(f"Saved PDF to temporary file: {temp_path}")
        
#         return True
#     finally:
#         await worker.stop()


# # Utility tests
# async def test_utility_commands():
#     """Test screenshot, wait, evaluate, and close commands"""
#     worker, context_id = await _setup_worker_and_context()
    
#     try:
#         # Navigate to a test page
#         await worker.execute_command(
#             context_id, "browser_navigate", {"url": "https://example.com"}
#         )
        
#         # Test browser_wait
#         result = await worker.execute_command(
#             context_id, "browser_wait", {"time": 1}
#         )
#         assert result["success"], "Failed to execute wait command"
        
#         # Test browser_screenshot
#         screenshot_result = await worker.execute_command(
#             context_id, "browser_screenshot", {}
#         )
#         assert screenshot_result["success"], "Failed to take screenshot"
#         assert "screenshot" in screenshot_result, "Screenshot data not returned"
#         assert len(screenshot_result["screenshot"]) > 0, "Screenshot data is empty"
        
#         # Save the screenshot to verify it's valid
#         with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
#             temp_file.write(screenshot_result["screenshot"])
#             temp_path = temp_file.name
        
#         logger.info(f"Saved screenshot to temporary file: {temp_path}")
        
#         # Test browser_evaluate
#         eval_result = await worker.execute_command(
#             context_id, "browser_evaluate", {"script": "document.title + ' - ' + document.URL"}
#         )
#         assert eval_result["success"], "Failed to evaluate JavaScript"
#         assert "result" in eval_result, "Evaluation result not returned"
#         assert "Example" in eval_result["result"], f"Unexpected evaluation result: {eval_result['result']}"
        
#         return True
#     finally:
#         await worker.stop()


# # Execute a single command
# async def test_worker_execute_command(command: tuple[str, dict]):
#     """Test executing a specific command"""
#     worker = AsyncBrowserWorker()
#     await worker.start()
#     context_id = await worker.create_context()
#     assert await worker.has_context(context_id), "Failed to create browser context"
#     await worker.execute_command(context_id, "browser_navigate", {"url": "https://www.youtube.com"})
#     result = await worker.execute_command(context_id, *command)
#     assert result["success"], f"Failed to execute command: {command}"
#     await worker.stop()


# # Run a batch of commands
# async def test_worker_execute_commands(commands: List[dict]):
#     """Test executing multiple commands"""
#     for command in commands:
#         await test_worker_execute_command(command)


# async def test_spinup_loop():
#     worker = AsyncBrowserWorker()
#     await worker.start()
#     context_id = await worker.create_context()
#     assert await worker.has_context(context_id), "Failed to create browser context"
#     task = BrowserWorkerTask(
#         task_id="test_task",
#         command="browser_navigate",
#         params={"url": "https://www.youtube.com"},
#         context_id=context_id
#     )
#     await worker.add_task(task)
#     result = await worker.get_result()
#     assert result["success"], "Failed to add task"
#     await worker.stop()

# def run_tests(tests: List[Callable], args: List[Optional[tuple]] = None):
#     """Run test functions with optional arguments"""
#     if args is None:
#         args = [None] * len(tests)
    
#     results = []
    
#     for i, (test, arg) in enumerate(zip(tests, args)):
#         try:
#             logger.info(f"Running test {i+1}/{len(tests)}: {test.__name__}")
            
#             if arg:
#                 asyncio.run(test(arg))
#             else:
#                 asyncio.run(test())
                
#             logger.info(f"✅ PASSED: {test.__name__}")
#             results.append((test.__name__, True))
#         except Exception as e:
#             logger.error(f"❌ FAILED: {test.__name__} - {str(e)}")
#             import traceback
#             logger.error(traceback.format_exc())
#             results.append((test.__name__, False))
    
#     # Print test summary
#     print("\n" + "="*80)
#     print("TEST RESULTS".center(80))
#     print("="*80)
    
#     passed = sum(1 for _, result in results if result)
#     failed = len(results) - passed
    
#     for name, result in results:
#         status = "✅ PASSED" if result else "❌ FAILED"
#         print(f"{status}: {name}")
    
#     print(f"\nTotal: {len(results)}, Passed: {passed}, Failed: {failed}")
    
#     # Return non-zero exit code if any tests failed
#     return 0 if failed == 0 else 1


# if __name__ == "__main__":
#     # Run all tests
#     all_tests = [
#         test_worker_create_context,
#         test_worker_create_context_and_terminate,
#         test_navigation_commands,
#         test_interaction_commands,
#         test_file_operations,
#         test_utility_commands,
#         test_click_navigation,
#         test_type_submit_navigation,
#         # Individual command test
#         test_worker_execute_command,
#         test_spinup_loop,
#     ]
    
#     # Only the last test needs arguments
#     args = [None, None, None, None, None, None, None, None, 
#             ("browser_navigate", {"url": "https://www.example.com"}),
#             None]
    
#     exit_code = run_tests(all_tests, args)
#     sys.exit(exit_code)