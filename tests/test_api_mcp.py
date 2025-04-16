# #!/usr/bin/env python3
# """
# Test script for Playwright MCP-compatible commands

# This script tests the newly added Playwright MCP commands in our API server.
# """

# import asyncio
# import json
# import logging
# import requests
# import time
# import os


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


# def test_mcp_commands():
#     """Test the Playwright MCP command compatibility"""
#     logger.info("Starting MCP command compatibility test")
    
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
    
#     session_id = response.json()["session_id"]
#     logger.info(f"Session created: {session_id}")
    
#     try:
#         # Test 1: Navigate to a website using browser_navigate
#         logger.info("Test 1: Using browser_navigate to go to Mozilla.org...")
#         command_data = {
#             "command": "browser_navigate",
#             "params": {"url": "https://www.mozilla.org", "wait_until": "networkidle"}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Navigation failed: {response.status_code} - {response.text}")
#             return
#         logger.info(f"Navigation result: {response.json()}")
        
#         # Test 2: Navigate to another website
#         logger.info("Test 2: Navigating to example.com...")
#         command_data = {
#             "command": "browser_navigate",
#             "params": {"url": "https://example.com", "wait_until": "networkidle"}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Navigation failed: {response.status_code} - {response.text}")
#             return
#         logger.info(f"Navigation result: {response.json()}")
        
#         # Test 3: Test browser_navigate_back
#         logger.info("Test 3: Testing browser_navigate_back...")
#         command_data = {
#             "command": "browser_navigate_back",
#             "params": {}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Navigation back failed: {response.status_code} - {response.text}")
#             return
#         logger.info(f"Navigation back result: {response.json()}")
        
#         # Test 4: Test browser_navigate_forward
#         logger.info("Test 4: Testing browser_navigate_forward...")
#         command_data = {
#             "command": "browser_navigate_forward",
#             "params": {}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Navigation forward failed: {response.status_code} - {response.text}")
#             return
#         logger.info(f"Navigation forward result: {response.json()}")
        
#         # Test 5: Test browser_press_key
#         logger.info("Test 5: Testing browser_press_key...")
#         command_data = {
#             "command": "browser_press_key",
#             "params": {"key": "Tab"}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Key press failed: {response.status_code} - {response.text}")
#             return
#         logger.info(f"Key press result: {response.json()}")
        
#         # Test 6: Test browser_wait
#         logger.info("Test 6: Testing browser_wait...")
#         command_data = {
#             "command": "browser_wait",
#             "params": {"time": 2}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Wait failed: {response.status_code} - {response.text}")
#             return
#         logger.info(f"Wait result: {response.json()}")
        
#         # Test 7: Test browser_pdf_save
#         logger.info("Test 7: Testing browser_pdf_save...")
#         command_data = {
#             "command": "browser_pdf_save",
#             "params": {}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"PDF save failed: {response.status_code} - {response.text}")
#             return
        
#         # Save the PDF to a file
#         with open("example_page.pdf", "wb") as pdf_file:
#             pdf_file.write(response.content)
#         logger.info("PDF saved to example_page.pdf")
        
#         # Get the page title to verify current page
#         logger.info("Getting page title...")
#         command_data = {
#             "command": "evaluate",
#             "params": {"script": "document.title"}
#         }
#         response = requests.post(f"{API_BASE}/sessions/{session_id}/commands", json=command_data)
#         if response.status_code != 200:
#             logger.error(f"Failed to get title: {response.status_code} - {response.text}")
#         else:
#             logger.info(f"Page title: {response.json()}")
        
#     finally:
#         # Clean up the session
#         logger.info(f"Deleting session {session_id}...")
#         response = requests.delete(f"{API_BASE}/sessions/{session_id}")
#         if response.status_code == 200:
#             logger.info("Session deleted successfully")
#         else:
#             logger.error(f"Failed to delete session: {response.status_code} - {response.text}")


# if __name__ == "__main__":
#     test_mcp_commands()
