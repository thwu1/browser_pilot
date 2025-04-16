# #!/usr/bin/env python3
# """
# Concurrent resource-heavy page test for browser automation system.
# This test runs multiple contexts concurrently in a single browser instance.

# Usage:
#   python concurrent_resource_test.py             # Run with default settings (headless mode)
#   python concurrent_resource_test.py --gui       # Run with GUI mode to monitor execution
#   python concurrent_resource_test.py --sites 2   # Test only 2 sites (first 2 in the list)
#   python concurrent_resource_test.py --debug     # Enable debug logging
# """

# import time
# import logging
# import asyncio
# import argparse
# import psutil

# import sys
# import os

# # Add parent directory to path so we can import modules
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# from datetime import datetime
# from playwright.async_api import async_playwright



# # Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)

# # Track resource usage
# class ResourceMonitor:
#     def __init__(self):
#         self.process = psutil.Process()
#         self.start_time = time.time()
#         # Get initial CPU to enable delta measurements
#         self.process.cpu_percent()
#         self.start_memory = self.process.memory_info().rss / (1024 * 1024)  # MB
#         self.measurements = []
        
#     def measure(self):
#         """Take a resource measurement"""
#         # Get CPU and memory usage for this process and all children (total across all cores)
#         cpu_percent = self.process.cpu_percent()
        
#         # Include children processes
#         child_procs = self.process.children(recursive=True)
#         for child in child_procs:
#             try:
#                 # This returns relative to one CPU core, we need to keep that in mind
#                 child_cpu = child.cpu_percent()
#                 if child_cpu is not None:
#                     cpu_percent += child_cpu
#             except (psutil.NoSuchProcess, psutil.AccessDenied):
#                 pass
        
#         # Get memory usage (RSS)
#         memory_mb = self.process.memory_info().rss / (1024 * 1024)
        
#         # Include children processes
#         for child in child_procs:
#             try:
#                 memory_mb += child.memory_info().rss / (1024 * 1024)
#             except (psutil.NoSuchProcess, psutil.AccessDenied):
#                 pass
                
#         timestamp = time.time()
        
#         self.measurements.append({
#             "timestamp": timestamp,
#             "cpu": cpu_percent,
#             "memory_mb": memory_mb
#         })
        
#         return {
#             "timestamp": timestamp,
#             "cpu": cpu_percent,
#             "memory_mb": memory_mb
#         }
        
#     def report(self):
#         """Report resource usage"""
#         if not self.measurements:
#             return
            
#         # Calculate statistics
#         current_time = time.time()
#         elapsed = current_time - self.start_time
        
#         cpu_values = [m["cpu"] for m in self.measurements]
#         memory_values = [m["memory_mb"] for m in self.measurements]
        
#         avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0
#         max_cpu = max(cpu_values) if cpu_values else 0
#         avg_memory = sum(memory_values) / len(memory_values) if memory_values else 0
#         max_memory = max(memory_values) if memory_values else 0
#         current_memory = self.process.memory_info().rss / (1024 * 1024)
        
#         logger.info(f"Resource usage over {elapsed:.1f} seconds:")
#         logger.info(f"CPU: avg={avg_cpu:.1f}%, max={max_cpu:.1f}%")
#         logger.info(f"Memory: avg={avg_memory:.1f}MB, max={max_memory:.1f}MB, current={current_memory:.1f}MB")
        
#         return {
#             "elapsed": elapsed,
#             "avg_cpu": avg_cpu,
#             "max_cpu": max_cpu,
#             "avg_memory": avg_memory,
#             "max_memory": max_memory,
#             "current_memory": current_memory
#         }

# class TestResult:
#     """Class to track test results with detailed information"""
    
#     def __init__(self, site):
#         self.site = site
#         self.start_time = time.time()
#         self.end_time = None
#         self.total_duration = 0
#         self.actions = []
#         self.success = False
#         self.error = None
#         self.metrics = {}
    
#     def add_action(self, action_name, success, duration_ms, details=None, error=None):
#         self.actions.append({
#             "name": action_name,
#             "success": success,
#             "duration_ms": duration_ms,
#             "details": details or {},
#             "error": error
#         })
    
#     def set_complete(self, success, error=None, metrics=None):
#         self.end_time = time.time()
#         self.total_duration = self.end_time - self.start_time
#         self.success = success
#         self.error = error
#         self.metrics = metrics or {}
    
#     def summary(self):
#         """Return a summary of the test results"""
#         success_count = sum(1 for a in self.actions if a["success"])
#         return {
#             "site": self.site,
#             "success": self.success,
#             "total_duration_ms": self.total_duration * 1000,
#             "action_count": len(self.actions),
#             "success_count": success_count,
#             "success_rate": success_count / len(self.actions) if self.actions else 0,
#             "error": self.error,
#             "metrics": self.metrics
#         }

# async def test_site_with_context(context, page, site, site_config, monitor=None, context_id=None):
#     """Test a resource-heavy page with detailed validation using a provided context"""
#     result = TestResult(site)
#     action_start = time.time()
    
#     logger.info(f"[Context {context_id}] Testing {site}")
    
#     try:
#         # Enable request/response logging if metrics requested
#         resource_metrics = {
#             "request_count": 0,
#             "response_count": 0,
#             "failed_requests": 0,
#             "resource_types": {},
#             "largest_resources": [],
#             "total_download_size": 0
#         }
        
#         async def log_request(request):
#             resource_metrics["request_count"] += 1
#             resource_type = request.resource_type
#             resource_metrics["resource_types"][resource_type] = resource_metrics["resource_types"].get(resource_type, 0) + 1
        
#         async def log_response(response):
#             resource_metrics["response_count"] += 1
#             if not response.ok:
#                 resource_metrics["failed_requests"] += 1
            
#             # Try to get response size
#             try:
#                 body = await response.body()
#                 size = len(body) if body else 0
#                 resource_metrics["total_download_size"] += size
                
#                 # Track largest resources
#                 resource_metrics["largest_resources"].append({
#                     "url": response.url,
#                     "size": size,
#                     "type": response.request.resource_type
#                 })
                
#                 # Keep only top 5 largest resources
#                 resource_metrics["largest_resources"] = sorted(
#                     resource_metrics["largest_resources"], 
#                     key=lambda x: x["size"], 
#                     reverse=True
#                 )[:5]
#             except:
#                 pass
        
#         page.on("request", log_request)
#         page.on("response", log_response)
        
#         # NAVIGATION - Go to the page
#         logger.info(f"[Context {context_id}] Navigating to {site}")
#         action_start = time.time()
        
#         # Use "load" instead of "networkidle" for more reliable navigation
#         # For Google Maps specifically, use domcontentloaded since it's especially heavy
#         wait_strategy = "domcontentloaded" if "maps" in site else "load"
#         response = await page.goto(site, wait_until=wait_strategy)
        
#         # Validate page loaded correctly
#         status = response.status
#         url = page.url
#         title = await page.title()
        
#         navigation_time = time.time() - action_start
#         navigation_success = status >= 200 and status < 400
        
#         result.add_action(
#             "navigate", 
#             navigation_success, 
#             navigation_time * 1000,
#             {
#                 "status": status,
#                 "actual_url": url,
#                 "title": title
#             }
#         )
        
#         logger.info(f"[Context {context_id}] Navigation result: status={status}, title='{title}', time={navigation_time*1000:.1f}ms")
        
#         # Take a resource measurement
#         if monitor:
#             measurement = monitor.measure()
#             logger.info(f"[Context {context_id}] After navigation: CPU: {measurement['cpu']:.1f}%, Memory: {measurement['memory_mb']:.1f}MB")
        
#         # Wait additional time for any delayed resources to load
#         logger.info(f"[Context {context_id}] Waiting for any delayed resources...")
#         await asyncio.sleep(1)  # Shorter wait for concurrent tests
        
#         # INTERACTION - Perform site-specific test actions
#         for action_def in site_config.get("actions", []):
#             action_name = action_def["name"]
#             action_params = action_def.get("params", {})
#             validation = action_def.get("validation", {})
            
#             logger.info(f"[Context {context_id}] Performing action: {action_name}")
#             action_start = time.time()
#             action_success = False
#             action_details = {}
#             action_error = None
            
#             try:
#                 if action_name == "click":
#                     selector = action_params.get("selector")
                    
#                     # Validation: Check if element exists before clicking
#                     element = await page.query_selector(selector)
#                     if element:
#                         is_visible = await element.is_visible()
#                         action_details["element_found"] = True
#                         action_details["is_visible"] = is_visible
                        
#                         if is_visible:
#                             await page.click(selector)
#                             action_success = True
#                         else:
#                             action_error = f"Element {selector} is not visible"
#                     else:
#                         action_error = f"Element {selector} not found"
#                         action_details["element_found"] = False
                
#                 elif action_name == "fill":
#                     selector = action_params.get("selector")
#                     value = action_params.get("value", "")
                    
#                     # Validation: Check if element exists before filling
#                     element = await page.query_selector(selector)
#                     if element:
#                         is_visible = await element.is_visible()
#                         is_enabled = await element.is_enabled()
#                         action_details["element_found"] = True
#                         action_details["is_visible"] = is_visible
#                         action_details["is_enabled"] = is_enabled
                        
#                         if is_visible and is_enabled:
#                             await page.fill(selector, value)
#                             action_success = True
#                         else:
#                             action_error = f"Element {selector} is not visible or enabled"
#                     else:
#                         action_error = f"Element {selector} not found"
#                         action_details["element_found"] = False
                
#                 elif action_name == "get_text":
#                     selector = action_params.get("selector")
                    
#                     # Validation: Check if element exists before getting text
#                     element = await page.query_selector(selector)
#                     if element:
#                         action_details["element_found"] = True
#                         text = await element.text_content()
#                         text_length = len(text) if text else 0
#                         text_sample = text[:100] if text else ""
                        
#                         action_details["text_length"] = text_length
#                         action_details["text_sample"] = text_sample
#                         action_success = True
                        
#                         # Perform additional validation if specified
#                         if "contains" in validation:
#                             contains_text = validation["contains"]
#                             has_text = contains_text in text
#                             action_details["contains_validation"] = has_text
#                             if not has_text:
#                                 action_error = f"Text does not contain '{contains_text}'"
#                                 action_success = False
#                     else:
#                         action_error = f"Element {selector} not found"
#                         action_details["element_found"] = False
                
#                 elif action_name == "scroll":
#                     target = action_params.get("target", "bottom")
                    
#                     if target == "bottom":
#                         # Scroll to bottom of page
#                         await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
#                         action_details["scrolled_to"] = "bottom"
#                         action_success = True
#                     elif target == "top":
#                         # Scroll to top of page
#                         await page.evaluate("window.scrollTo(0, 0)")
#                         action_details["scrolled_to"] = "top"
#                         action_success = True
#                     elif isinstance(target, dict) and "selector" in target:
#                         # Scroll to element
#                         selector = target["selector"]
#                         element = await page.query_selector(selector)
#                         if element:
#                             action_details["element_found"] = True
#                             await element.scroll_into_view_if_needed()
#                             action_success = True
#                         else:
#                             action_error = f"Element {selector} not found"
#                             action_details["element_found"] = False
#                     else:
#                         action_error = f"Invalid scroll target: {target}"
                
#                 elif action_name == "wait":
#                     duration = action_params.get("duration", 1)
#                     # Use shorter waits for concurrent tests
#                     duration = min(duration, 1)  
#                     await asyncio.sleep(duration)
#                     action_details["waited_seconds"] = duration
#                     action_success = True
                
#                 elif action_name == "evaluate":
#                     expression = action_params.get("expression")
#                     result_value = await page.evaluate(expression)
#                     action_details["result"] = str(result_value)
#                     action_success = True
                    
#                     # Perform additional validation if specified
#                     if "expected" in validation:
#                         expected = validation["expected"]
#                         matches = str(result_value) == str(expected)
#                         action_details["expected_validation"] = matches
#                         if not matches:
#                             action_error = f"Result '{result_value}' does not match expected '{expected}'"
#                             action_success = False
                
#                 elif action_name == "screenshot":
#                     path = action_params.get("path", f"/tmp/concurrent_{context_id}_{site.replace('https://', '').replace('/', '_')}.png")
#                     await page.screenshot(path=path)
#                     action_details["screenshot_path"] = path
#                     action_success = True
                    
#                 else:
#                     action_error = f"Unknown action: {action_name}"
            
#             except Exception as e:
#                 action_error = str(e)
#                 logger.error(f"[Context {context_id}] Error in action {action_name}: {action_error}")
            
#             action_duration = time.time() - action_start
#             result.add_action(action_name, action_success, action_duration * 1000, action_details, action_error)
            
#             status_text = "SUCCESS" if action_success else "FAILED"
#             logger.info(f"[Context {context_id}] Action {action_name} {status_text} in {action_duration*1000:.1f}ms")
#             if action_error:
#                 logger.error(f"[Context {context_id}] Action error: {action_error}")
            
#             # Take a resource measurement after each action
#             if monitor:
#                 measurement = monitor.measure()
#                 logger.info(f"[Context {context_id}] After {action_name}: CPU: {measurement['cpu']:.1f}%, Memory: {measurement['memory_mb']:.1f}MB")
            
#             # If action failed and is marked critical, abort the test
#             if not action_success and action_def.get("critical", False):
#                 logger.error(f"[Context {context_id}] Critical action {action_name} failed. Aborting test.")
#                 break
        
#         # Performance metrics - get page performance timing
#         logger.info(f"[Context {context_id}] Collecting performance metrics...")
#         performance_metrics = await page.evaluate("""() => {
#             const timing = performance.timing;
#             const navigation = performance.getEntriesByType('navigation')[0];
#             const paint = performance.getEntriesByType('paint');
            
#             return {
#                 navigationStart: timing.navigationStart,
#                 domContentLoaded: timing.domContentLoadedEventEnd - timing.navigationStart,
#                 load: timing.loadEventEnd - timing.navigationStart,
#                 firstPaint: paint.find(p => p.name === 'first-paint')?.startTime,
#                 firstContentfulPaint: paint.find(p => p.name === 'first-contentful-paint')?.startTime,
#                 resourceCount: performance.getEntriesByType('resource').length,
#             };
#         }""")
        
#         # Memory usage - get JS heap size
#         memory_usage = await page.evaluate("""() => {
#             if (window.performance && performance.memory) {
#                 return {
#                     usedJSHeapSize: performance.memory.usedJSHeapSize / (1024 * 1024),
#                     totalJSHeapSize: performance.memory.totalJSHeapSize / (1024 * 1024),
#                     jsHeapSizeLimit: performance.memory.jsHeapSizeLimit / (1024 * 1024),
#                 };
#             } else {
#                 return { note: 'Memory API not available' };
#             }
#         }""")
        
#         # Build metrics object with collected data
#         metrics = {
#             "performance": performance_metrics,
#             "memory": memory_usage,
#             "resources": resource_metrics
#         }
        
#         # Log basic resource metrics
#         logger.info(f"[Context {context_id}] Resource metrics: {len(resource_metrics['largest_resources'])} largest resources tracked")
#         logger.info(f"[Context {context_id}] Total requests: {resource_metrics['request_count']}, responses: {resource_metrics['response_count']}")
#         logger.info(f"[Context {context_id}] Failed requests: {resource_metrics['failed_requests']}")
#         logger.info(f"[Context {context_id}] Total download size: {resource_metrics['total_download_size'] / (1024*1024):.2f} MB")
        
#         # Set result as complete
#         success_actions = sum(1 for a in result.actions if a["success"])
#         overall_success = success_actions == len(result.actions)
#         result.set_complete(overall_success, metrics=metrics)
        
#         logger.info(f"[Context {context_id}] Test completed for {site}: {success_actions}/{len(result.actions)} actions successful")
        
#         return result
        
#     except Exception as e:
#         logger.error(f"[Context {context_id}] Test failed for {site}: {e}")
#         result.set_complete(False, error=str(e))
#         return result

# async def run_concurrent_tests(sites, headless=True, slow_mo=0):
#     """Run tests for multiple sites concurrently in a single browser with multiple contexts"""
#     # Start resource monitoring
#     monitor = ResourceMonitor()
    
#     logger.info(f"Starting concurrent tests for {len(sites)} sites")
#     logger.info("================================")
    
#     # Take initial measurement
#     monitor.measure()
    
#     # Start playwright and a single browser
#     async with async_playwright() as playwright:
#         browser = await playwright.chromium.launch(
#             headless=headless,
#             slow_mo=slow_mo
#         )
        
#         # Create a context and page for each site
#         contexts = []
#         pages = []
#         site_configs = []
#         site_urls = []
        
#         for i, (site, config) in enumerate(sites.items()):
#             # Create browser context
#             context = await browser.new_context(
#                 viewport={"width": 1280, "height": 800},
#                 user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
#             )
            
#             # Set longer timeouts for resource-heavy pages
#             context.set_default_navigation_timeout(60000)  # 60 seconds
#             context.set_default_timeout(30000)  # 30 seconds
            
#             # Create page
#             page = await context.new_page()
            
#             contexts.append(context)
#             pages.append(page)
#             site_configs.append(config)
#             site_urls.append(site)
        
#         # Create async tasks for each site test
#         tasks = [
#             test_site_with_context(contexts[i], pages[i], site_urls[i], site_configs[i], monitor, i) 
#             for i in range(len(site_urls))
#         ]
        
#         # Measure peak resource usage during concurrent execution
#         async def measure_resource_usage():
#             while True:
#                 try:
#                     monitor.measure()
#                     await asyncio.sleep(0.5)  # Sample every 500ms
#                 except:
#                     break
        
#         # Start resource measurement task
#         measure_task = asyncio.create_task(measure_resource_usage())
        
#         # Run all tests concurrently
#         start_time = time.time()
#         results = await asyncio.gather(*tasks)
#         end_time = time.time()
        
#         # Cancel measurement task
#         measure_task.cancel()
        
#         # Close all contexts and browser
#         for context in contexts:
#             await context.close()
#         await browser.close()
        
#         # Calculate summary statistics
#         total_actions = sum(len(result.actions) for result in results)
#         successful_actions = sum(sum(1 for a in result.actions if a["success"]) for result in results)
#         success_rate = successful_actions / total_actions if total_actions > 0 else 0
        
#         # Report final resource usage
#         resource_stats = monitor.report()
        
#         logger.info("\n=== CONCURRENT TEST RESULTS ===")
#         logger.info(f"Sites tested: {len(results)}")
#         logger.info(f"Total actions: {total_actions}")
#         logger.info(f"Successful actions: {successful_actions}")
#         logger.info(f"Overall success rate: {success_rate * 100:.1f}%")
#         logger.info(f"Total elapsed time: {end_time - start_time:.1f} seconds")
        
#         # Return all results
#         return results, resource_stats

# async def main():
#     # Parse command line arguments
#     parser = argparse.ArgumentParser(description='Run concurrent browser tests')
#     parser.add_argument('--gui', action='store_true', 
#                         help='Run in GUI mode (non-headless) to monitor execution')
#     parser.add_argument('--sites', type=int, default=0,
#                         help='Number of sites to test (0 for all)')
#     parser.add_argument('--debug', action='store_true',
#                         help='Enable debug logging')
#     parser.add_argument('--slow-mo', type=int, default=0,
#                         help='Slow down Playwright operations by the specified amount of milliseconds')
#     args = parser.parse_args()
    
#     # Configure logging based on debug flag
#     if args.debug:
#         logger.setLevel(logging.DEBUG)
#         logging.getLogger().setLevel(logging.DEBUG)
    
#     # Print configuration
#     headless = not args.gui
#     logger.info(f"Running with configuration:")
#     logger.info(f"- Headless mode: {headless}")
#     logger.info(f"- Slow motion: {args.slow_mo}ms")
#     logger.info(f"- Debug logging: {args.debug}")
    
#     # Configure resource-heavy websites with validation steps
#     sites = {
#         "https://www.youtube.com": {
#             "actions": [
#                 {"name": "get_text", "params": {"selector": "title"}, "validation": {"contains": "YouTube"}},
#                 {"name": "wait", "params": {"duration": 1}},
#                 {"name": "scroll", "params": {"target": "bottom"}},
#                 {"name": "scroll", "params": {"target": "top"}},
#                 {"name": "evaluate", "params": {"expression": "document.querySelectorAll('ytd-rich-grid-media').length"}},
#                 {"name": "screenshot"}
#             ]
#         },
#         "https://www.reddit.com": {
#             "actions": [
#                 {"name": "get_text", "params": {"selector": "title"}, "validation": {"contains": "Reddit"}},
#                 {"name": "wait", "params": {"duration": 1}},
#                 {"name": "scroll", "params": {"target": "bottom"}},
#                 {"name": "scroll", "params": {"target": "top"}},
#                 {"name": "evaluate", "params": {"expression": "document.querySelectorAll('[data-testid=\"post\"]').length"}},
#                 {"name": "screenshot"}
#             ]
#         },
#         "https://www.nytimes.com": {
#             "actions": [
#                 {"name": "get_text", "params": {"selector": "title"}, "validation": {"contains": "The New York Times"}},
#                 {"name": "wait", "params": {"duration": 1}},
#                 {"name": "scroll", "params": {"target": "bottom"}},
#                 {"name": "scroll", "params": {"target": "top"}},
#                 {"name": "evaluate", "params": {"expression": "document.querySelectorAll('article').length"}},
#                 {"name": "screenshot"}
#             ]
#         },
#         "https://www.google.com/maps": {
#             "actions": [
#                 {"name": "get_text", "params": {"selector": "title"}, "validation": {"contains": "Google Maps"}},
#                 {"name": "wait", "params": {"duration": 1}},
#                 {"name": "evaluate", "params": {"expression": "document.querySelector('#searchboxinput') !== null"}, "validation": {"expected": "True"}},
#                 {"name": "fill", "params": {"selector": "#searchboxinput", "value": "San Francisco"}},
#                 {"name": "screenshot"}
#             ]
#         }
#     }
    
#     # Limit number of sites if specified
#     if args.sites > 0 and args.sites < len(sites):
#         site_keys = list(sites.keys())[:args.sites]
#         sites = {k: sites[k] for k in site_keys}
#         logger.info(f"Testing {len(sites)} sites (limited by --sites argument):")
#     else:
#         logger.info(f"Testing all {len(sites)} sites:")
    
#     for site in sites:
#         logger.info(f"- {site}")
    
#     # Run concurrent tests with specified headless mode
#     await run_concurrent_tests(sites, headless=headless, slow_mo=args.slow_mo)

# if __name__ == "__main__":
#     asyncio.run(main())
