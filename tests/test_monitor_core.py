#!/usr/bin/env python3
"""
Test script for resource monitoring

This script demonstrates how to use the monitoring system to track resource usage
of browser workers and contexts.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any

import sys
import os

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


from async_worker import BrowserWorker
from monitor import setup_worker_monitoring

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_worker_monitoring():
    """Test the worker monitoring functionality"""
    logger.info("Starting browser worker with monitoring")
    
    # Create and start a browser worker
    worker = BrowserWorker()
    await worker.start()
    
    try:
        # Set up monitoring
        monitor = await setup_worker_monitoring(worker, interval=10)  # Check every 10 seconds for testing
        logger.info("Monitoring started")
        
        # Create a browser context
        logger.info("Creating browser context...")
        context_id = await worker.create_context()
        logger.info(f"Created context: {context_id}")
        
        # Navigate to a website to generate some load
        logger.info("Navigating to example.com...")
        result = await worker.execute_command(
            context_id=context_id,
            command="browser_navigate",
            params={"url": "https://www.example.com"}
        )
        logger.info(f"Navigation result: {result}")
        
        # Wait a bit for the monitoring to collect some data
        logger.info("Waiting for 15 seconds for monitoring data collection...")
        await asyncio.sleep(15)
        
        # Get current metrics
        metrics = await monitor.get_complete_metrics()
        logger.info("Current metrics:")
        print(json.dumps(metrics, indent=2, default=str))
        
        # Create more contexts to see how monitoring handles multiple contexts
        logger.info("Creating additional contexts...")
        context_ids = []
        for i in range(3):
            ctx_id = await worker.create_context()
            context_ids.append(ctx_id)
            logger.info(f"Created context: {ctx_id}")
            
            # Navigate to different sites
            urls = [
                "https://www.mozilla.org",
                "https://github.com",
                "https://www.wikipedia.org"
            ]
            await worker.execute_command(
                context_id=ctx_id,
                command="browser_navigate",
                params={"url": urls[i]}
            )
        
        # Wait for more monitoring data
        logger.info("Waiting for 15 more seconds...")
        await asyncio.sleep(15)
        
        # Get updated metrics
        metrics = await monitor.get_complete_metrics()
        logger.info("Updated metrics with multiple contexts:")
        print(json.dumps(metrics, indent=2, default=str))
        
        # Check history
        history = monitor.resource_monitor.get_metrics_history()
        logger.info(f"Collected {len(history)} historical metrics entries")
        
        # Hibernate some contexts to see hibernation stats
        logger.info("Hibernating contexts...")
        for ctx_id in context_ids[:2]:
            await worker.hibernate_context(ctx_id)
            logger.info(f"Hibernated context: {ctx_id}")
        
        # Wait for monitoring to update
        await asyncio.sleep(10)
        
        # Get final metrics
        metrics = await monitor.get_complete_metrics()
        logger.info("Final metrics with hibernated contexts:")
        print(json.dumps(metrics, indent=2, default=str))
        
    finally:
        # Clean up
        logger.info("Stopping monitoring...")
        await monitor.stop_monitoring()
        
        logger.info("Stopping worker...")
        await worker.stop()
        
        logger.info("Test completed")


if __name__ == "__main__":
    asyncio.run(test_worker_monitoring())
