#!/usr/bin/env python3
"""
Test script for htop-like resource monitoring accuracy

This script demonstrates the enhanced monitoring system with continuous sampling
that provides accuracy comparable to htop.
"""

import asyncio
import json
import logging
import time
import psutil
import matplotlib.pyplot as plt
import numpy as np

import sys
import os

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime

from async_worker import BrowserWorker
from monitor import setup_worker_monitoring, WorkerMonitor, ResourceMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def generate_cpu_load(duration_seconds=5):
    """Generate CPU load to test monitoring accuracy"""
    logger.info(f"Generating CPU load for {duration_seconds} seconds...")
    start_time = time.time()
    
    # Compute-intensive task
    while time.time() - start_time < duration_seconds:
        # Calculate prime numbers to generate load
        [i**2 for i in range(10000)]
        
        # Small yield to allow other tasks to run
        await asyncio.sleep(0.001)
    
    logger.info("CPU load generation complete")


async def generate_memory_load(mb_to_allocate=100, duration_seconds=5):
    """Generate memory load to test monitoring accuracy"""
    logger.info(f"Allocating {mb_to_allocate}MB memory for {duration_seconds} seconds...")
    
    # Allocate memory (1MB is roughly 1 million bytes)
    data = bytearray(mb_to_allocate * 1024 * 1024)
    
    # Hold the memory for specified duration
    await asyncio.sleep(duration_seconds)
    
    # Release memory (by removing reference)
    data = None
    logger.info("Memory allocation released")


async def test_monitoring_accuracy():
    """Test the htop-like accuracy of our resource monitoring"""
    logger.info("Starting enhanced monitoring accuracy test")
    
    # Create a worker to monitor
    worker = BrowserWorker()
    await worker.start()
    
    try:
        # Setup monitoring with 1-second sampling interval (like htop)
        monitor = await setup_worker_monitoring(worker, interval=5)
        logger.info("Enhanced monitoring started with continuous background sampling")
        
        # Wait for initial samples to accumulate
        logger.info("Collecting baseline metrics for 10 seconds...")
        await asyncio.sleep(10)
        
        # Collect baseline metrics
        baseline = await monitor.get_complete_metrics()
        logger.info(f"Baseline CPU: {baseline['cpu_percent']:.2f}% (Point) / "
                   f"{baseline.get('cpu_percent_avg', 0):.2f}% (Avg from {len(monitor.cpu_samples)} samples)")
        logger.info(f"Baseline Memory: {baseline['memory_mb']:.2f}MB (Point) / "
                   f"{baseline.get('memory_mb_avg', 0):.2f}MB (Avg from {len(monitor.memory_samples)} samples)")
        
        # Store metrics for graphing
        timestamps = [time.time()]
        cpu_points = [baseline['cpu_percent']]
        cpu_avgs = [baseline.get('cpu_percent_avg', baseline['cpu_percent'])]
        mem_points = [baseline['memory_mb']]
        mem_avgs = [baseline.get('memory_mb_avg', baseline['memory_mb'])]
        
        # Create a context (should show in monitoring)
        logger.info("Creating browser context...")
        context_id = await worker.create_context()
        logger.info(f"Created context: {context_id}")
        
        # Test CPU load monitoring
        logger.info("Testing CPU load monitoring...")
        # Start CPU load and collect metrics simultaneously
        cpu_task = asyncio.create_task(generate_cpu_load(duration_seconds=15))
        
        # Collect metrics every second during CPU load
        for _ in range(20):  # Collect for 20 seconds (overlapping with load)
            metrics = await monitor.get_complete_metrics()
            logger.info(f"CPU: {metrics['cpu_percent']:.2f}% (Point) / "
                       f"{metrics.get('cpu_percent_avg', 0):.2f}% (Avg) / "
                       f"Min: {metrics.get('cpu_percent_min', 0):.2f}% / "
                       f"Max: {metrics.get('cpu_percent_max', 0):.2f}%")
            
            timestamps.append(time.time())
            cpu_points.append(metrics['cpu_percent'])
            cpu_avgs.append(metrics.get('cpu_percent_avg', metrics['cpu_percent']))
            mem_points.append(metrics['memory_mb'])
            mem_avgs.append(metrics.get('memory_mb_avg', metrics['memory_mb']))
            
            await asyncio.sleep(1)
        
        await cpu_task  # Ensure CPU task completes
        
        # Test memory load monitoring
        logger.info("Testing memory load monitoring...")
        mem_task = asyncio.create_task(generate_memory_load(mb_to_allocate=200, duration_seconds=15))
        
        # Collect metrics every second during memory load
        for _ in range(20):  # Collect for 20 seconds (overlapping with load)
            metrics = await monitor.get_complete_metrics()
            logger.info(f"Memory: {metrics['memory_mb']:.2f}MB (Point) / "
                       f"{metrics.get('memory_mb_avg', 0):.2f}MB (Avg) / "
                       f"Min: {metrics.get('memory_mb_min', 0):.2f}MB / "
                       f"Max: {metrics.get('memory_mb_max', 0):.2f}MB")
            
            timestamps.append(time.time())
            cpu_points.append(metrics['cpu_percent'])
            cpu_avgs.append(metrics.get('cpu_percent_avg', metrics['cpu_percent']))
            mem_points.append(metrics['memory_mb'])
            mem_avgs.append(metrics.get('memory_mb_avg', metrics['memory_mb']))
            
            await asyncio.sleep(1)
        
        await mem_task  # Ensure memory task completes
        
        # Create visualization of the data
        # Normalize timestamps for x-axis
        start_time = timestamps[0]
        time_points = [(t - start_time) for t in timestamps]
        
        # Plot CPU metrics
        plt.figure(figsize=(12, 10))
        
        plt.subplot(2, 1, 1)
        plt.plot(time_points, cpu_points, 'b-', label='Point CPU %')
        plt.plot(time_points, cpu_avgs, 'r-', label='Avg CPU % (htop-like)')
        plt.xlabel('Time (seconds)')
        plt.ylabel('CPU %')
        plt.title('CPU Usage: Point Measurements vs. Continuous Sampling (htop-like)')
        plt.legend()
        plt.grid(True)
        
        # Plot Memory metrics
        plt.subplot(2, 1, 2)
        plt.plot(time_points, mem_points, 'g-', label='Point Memory (MB)')
        plt.plot(time_points, mem_avgs, 'm-', label='Avg Memory (MB) (htop-like)')
        plt.xlabel('Time (seconds)')
        plt.ylabel('Memory (MB)')
        plt.title('Memory Usage: Point Measurements vs. Continuous Sampling (htop-like)')
        plt.legend()
        plt.grid(True)
        
        plt.tight_layout()
        
        # Save the figure
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"monitoring_accuracy_{timestamp}.png"
        plt.savefig(filename)
        logger.info(f"Visualization saved to {filename}")
        
        # Final metrics
        final = await monitor.get_complete_metrics()
        logger.info("Final metrics summary:")
        logger.info(f"- CPU: {final['cpu_percent']:.2f}% (Point) / "
                  f"{final.get('cpu_percent_avg', 0):.2f}% (Avg)")
        logger.info(f"- Memory: {final['memory_mb']:.2f}MB (Point) / "
                  f"{final.get('memory_mb_avg', 0):.2f}MB (Avg)")
        logger.info(f"- Contexts: {final['context_count']}")
        
        # Compare with direct psutil measurement
        direct_cpu = psutil.Process().cpu_percent(interval=1.0)
        logger.info(f"Direct psutil CPU measurement: {direct_cpu:.2f}%")
        logger.info(f"Enhanced monitoring CPU: {final.get('cpu_percent_avg', 0):.2f}%")
        logger.info(f"Difference: {abs(direct_cpu - final.get('cpu_percent_avg', 0)):.2f}%")
        
    finally:
        # Clean up
        logger.info("Stopping monitoring...")
        await monitor.stop_monitoring()
        
        logger.info("Stopping worker...")
        await worker.stop()
        
        logger.info("Test completed")


if __name__ == "__main__":
    # Install matplotlib if missing
    try:
        import matplotlib
    except ImportError:
        import subprocess
        logger.info("Installing matplotlib for visualization...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "matplotlib"])
        logger.info("Matplotlib installed successfully")
    
    asyncio.run(test_monitoring_accuracy())
