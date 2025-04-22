# #!/usr/bin/env python3
# """
# Test script for the Browser API

# This script demonstrates how to use the API server to control browsers remotely.
# """

# import asyncio
# import json
# import logging
# import requests
# import time


# import sys
# import os

# # Add parent directory to path so we can import modules
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# # Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)

# # API base URL
# API_BASE = "http://localhost:8000"


# def test_api():
#     """Run a test of the browser API"""
#     logger.info("Starting browser API test")

#     # Check API status
#     logger.info("Checking API status...")
#     response = requests.get(f"{API_BASE}/status")
#     if response.status_code == 200:
#         logger.info("API is running")
#     else:
#         logger.error(f"API status check failed: {response.status_code} - {response.text}")
#         return

#     # Create a session
#     logger.info("Creating a browser session...")
#     session_data = {
#         "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
#         "viewport": {"width": 1920, "height": 1080},
#         "persistent": True
#     }
#     response = requests.post(f"{API_BASE}/sessions", json=session_data)
#     if response.status_code != 200:
#         logger.error(f"Failed to create session: {response.status_code} - {response.text}")
#         return

#     session_info = response.json()
#     session_id = session_info["session_id"]
#     logger.info(f"Session created: {session_id}")

#     try:
#         # Navigate to a complex website (Twitter)
#         logger.info("Navigating to Twitter...")
#         command_data = {
#             "command": "browser_navigate",
#             "params": {"url": "https://twitter.com/elonmusk", "wait_until": "networkidle"}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Navigation failed: {response.status_code} - {response.text}")
#             return

#         logger.info(f"Navigation result: {response.json()}")

#         # Wait a moment to let the complex site fully load
#         logger.info("Waiting for page to fully load...")
#         time.sleep(5)

#         # Get page title
#         logger.info("Getting page title...")
#         command_data = {
#             "command": "browser_evaluate",
#             "params": {"script": "document.title"}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Failed to get title: {response.status_code} - {response.text}")
#             return

#         title_info = response.json()
#         logger.info(f"Page title: {title_info}")

#         # Take a screenshot
#         logger.info("Taking a screenshot...")
#         command_data = {
#             "command": "browser_screenshot",
#             "params": {"full_page": True}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Screenshot failed: {response.status_code} - {response.text}")
#             return

#         # Save the screenshot to a file
#         screenshot_filename = "twitter_screenshot.png"
#         with open(screenshot_filename, "wb") as f:
#             f.write(response.content)
#         logger.info(f"Screenshot saved to {screenshot_filename}")

#         # Get HTML content
#         logger.info("Getting HTML content...")
#         observation_data = {
#             "observation_type": "html",
#             "params": {}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/observations", json=observation_data)
#         if response.status_code != 200:
#             logger.error(f"Failed to get HTML: {response.status_code} - {response.text}")
#             return

#         html_content = response.json().get("html", "")
#         logger.info(f"HTML content length: {len(html_content)}")

#         # Hibernate the session
#         logger.info("Hibernating the session...")
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/hibernate")
#         if response.status_code != 200:
#             logger.error(f"Hibernation failed: {response.status_code} - {response.text}")
#             return

#         logger.info(f"Hibernation result: {response.json()}")

#         # Wait a moment
#         logger.info("Waiting 2 seconds...")
#         time.sleep(2)

#         # Reactivate the session
#         logger.info("Reactivating the session...")
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/reactivate")
#         if response.status_code != 200:
#             logger.error(f"Reactivation failed: {response.status_code} - {response.text}")
#             return

#         logger.info(f"Reactivation result: {response.json()}")

#         # Navigate to another website
#         logger.info("Navigating to mozilla.org...")
#         command_data = {
#             "command": "browser_navigate",
#             "params": {"url": "https://www.mozilla.org"}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Navigation failed: {response.status_code} - {response.text}")
#             return

#         logger.info(f"Navigation result: {response.json()}")

#         # Get session info
#         logger.info("Getting session info...")
#         response = requests.get(f"{API_BASE}/sessions/{session_id}")
#         if response.status_code != 200:
#             logger.error(f"Failed to get session info: {response.status_code} - {response.text}")
#             return

#         logger.info(f"Session info: {response.json()}")

#     finally:
#         # Delete the session
#         logger.info(f"Deleting session {session_id}...")
#         response = requests.delete(f"{API_BASE}/sessions/{session_id}")
#         if response.status_code == 200:
#             logger.info("Session deleted successfully")
#         else:
#             logger.error(f"Failed to delete session: {response.status_code} - {response.text}")


# if __name__ == "__main__":
#     test_api()
