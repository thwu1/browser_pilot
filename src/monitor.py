#!/usr/bin/env python3
"""
Resource Monitoring for Browser Automation

This module provides resource monitoring capabilities for the browser automation service,
tracking memory usage, CPU utilization, and other metrics for browser workers and contexts.
"""

import asyncio
import logging
import os
import time
import psutil
from typing import Dict, Any, List, Optional
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import ContextState enum for state checking
try:
    from async_worker import ContextState
except ImportError:
    # Fallback definition if async_worker module is not available
    class ContextState(Enum):
        """States for a browser context"""
        INITIALIZING = "initializing"
        ACTIVE = "active"
        IDLE = "idle"
        HIBERNATED = "hibernated"
        FAILED = "failed"
        TERMINATED = "terminated"

class ResourceMonitor:
    """Monitor system resources for a process"""
    
    def __init__(self, worker_id: str):
        """Initialize the resource monitor
        
        Args:
            worker_id: ID of the worker to monitor
        """
        self.worker_id = worker_id
        self.process = psutil.Process()
        self.start_time = time.time()
        self.baseline_memory = self.process.memory_info().rss
        self.metrics_history = []
        self.max_history_entries = 100  # Store up to 100 historical entries
        
        # For accurate CPU measurement
        self._last_cpu_times = None
        self._last_cpu_time = None
        
        # For accurate child CPU measurement
        self._child_cpu_times = None
        self._child_last_time = None
        
        # For CPU averaging
        self._cpu_samples = []
        self._cpu_samples_max = 10  # Number of samples to keep for averaging
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system resource usage metrics using more accurate sampling"""
        process = self.process
        
        try:
            # Get accurate memory usage from our new method
            main_memory_mb, child_memory_mb, memory_mb = self._get_accurate_memory_usage()
            
            # Get accurate CPU usage
            cpu_percent = self._get_accurate_cpu_percent()
            
            # Get IO counters if available
            io_metrics = {}
            try:
                # First check if this platform supports IO counters
                if hasattr(psutil, 'Process') and hasattr(psutil.Process, 'io_counters'):
                    io_stats = self.process.io_counters()
                    if io_stats:
                        io_metrics = {
                            "io_read_bytes": io_stats.read_bytes,
                            "io_write_bytes": io_stats.write_bytes,
                            "io_read_count": io_stats.read_count,
                            "io_write_count": io_stats.write_count
                        }
                        logger.debug(f"IO metrics collected: read={io_stats.read_bytes/1024/1024:.2f}MB, write={io_stats.write_bytes/1024/1024:.2f}MB")
            except Exception as e:
                # This is expected on some platforms, so downgrade to debug level
                logger.debug(f"IO counters not available: {e}")
            
            # Get all child processes since browsers spawn multiple processes
            children = process.children(recursive=True)
            
            # Calculate CPU using delta method (similar to htop)
            current_time = time.time()
            current_cpu_times = process.cpu_times()
            
            # Initialize CPU metrics
            main_cpu_percent = 0.0
            
            # Calculate main process CPU
            if self._last_cpu_times is not None:
                delta_time = current_time - self._last_cpu_time
                if delta_time > 0:
                    delta_user = current_cpu_times.user - self._last_cpu_times.user
                    delta_system = current_cpu_times.system - self._last_cpu_times.system
                    delta_cpu_time = delta_user + delta_system
                
                    # Calculate percentage - keep consistent with how htop calculates
                    # For a 16-core system, 100% means one full core is utilized
                    main_cpu_percent = (delta_cpu_time / delta_time) * 100.0
            
            # Update for next time
            self._last_cpu_times = current_cpu_times
            self._last_cpu_time = current_time
            
            # Get child process CPU usage - similar approach to main process
            child_cpu_percent = 0.0
            current_children_info = []
            
            # Process each child
            for child in children:
                try:
                    child_times = child.cpu_times()
                    child_pid = child.pid
                    current_children_info.append((child_pid, child_times))
                except Exception as e:
                    logger.error(f"Error getting CPU times for child {child_pid}: {e}")
                    continue
                
            # If we have previous measurements, calculate deltas
            if self._child_cpu_times:
                # Create a lookup of previous measurements by PID
                prev_children_dict = dict(self._child_cpu_times)
            
                # Calculate CPU for each child that was present in previous measurement
                for pid, times in current_children_info:
                    if pid in prev_children_dict:
                        prev_times = prev_children_dict[pid]
                        # Calculate deltas
                        try:
                            delta_time = current_time - self._child_last_time
                            if delta_time > 0:
                                delta_user = times.user - prev_times.user
                                delta_system = times.system - prev_times.system
                                delta_cpu_time = delta_user + delta_system
                            
                                # Add to total child CPU percent
                                child_delta_percent = (delta_cpu_time / delta_time) * 100.0
                                child_cpu_percent += child_delta_percent
                        except Exception as e:
                            logger.error(f"Error calculating CPU delta for child {pid}: {e}")
                            # Skip this child if calculation fails
                            pass
            
            # Store current children info for next time
            self._child_cpu_times = current_children_info
            self._child_last_time = current_time
            
            # Total CPU percentage (main process + child processes)
            total_cpu_percent = main_cpu_percent + child_cpu_percent
            
            # Also calculate a per-core normalized value (useful for alerting)
            normalized_cpu_percent = total_cpu_percent / psutil.cpu_count()
            
            # Update CPU samples for averaging
            self._cpu_samples.append(total_cpu_percent)
            # Keep only the most recent samples
            while len(self._cpu_samples) > self._cpu_samples_max:
                self._cpu_samples.pop(0)
            
            # Calculate average CPU usage from samples
            avg_cpu_percent = sum(self._cpu_samples) / len(self._cpu_samples) if self._cpu_samples else 0
            avg_normalized_cpu_percent = avg_cpu_percent / psutil.cpu_count()
            
            # Build main metrics
            metrics = {
                "worker_id": self.worker_id,
                "timestamp": time.time(),
                "uptime_seconds": time.time() - self.start_time,
                "memory_mb": memory_mb,
                "memory_increase_mb": (memory_mb - self.baseline_memory / (1024 * 1024)),
                "virtual_memory_mb": process.memory_info().vms / (1024 * 1024),
                "cpu_percent": total_cpu_percent,
                "cpu_percent_avg": avg_cpu_percent,
                "cpu_percent_normalized": normalized_cpu_percent,
                "cpu_percent_normalized_avg": avg_normalized_cpu_percent,
                "open_files": len(process.open_files()),
                "threads": len(process.threads()),
                "connections": len(process.connections()),
                "cmdline": process.cmdline()[0] if process.cmdline() else "",
                "child_processes": len(children),
                "child_memory_mb": child_memory_mb,
                "child_cpu_percent": child_cpu_percent,
                "main_cpu_percent": main_cpu_percent,
                **io_metrics
            }
            
            # Add system-wide metrics
            sys_metrics = {
                "system_cpu_percent": psutil.cpu_percent(interval=None),
                "system_cpu_count": psutil.cpu_count(),
                "system_memory_percent": psutil.virtual_memory().percent,
                "system_memory_available_mb": psutil.virtual_memory().available / (1024 * 1024),
                "system_memory_used_mb": psutil.virtual_memory().used / (1024 * 1024),
                "system_swap_percent": psutil.swap_memory().percent
            }
            
            # Combine metrics
            metrics.update(sys_metrics)
            
            return metrics
        except Exception as e:
            logger.error(f"Error getting system metrics: {e}")
            # Return minimal metrics in case of error
            return {
                "worker_id": self.worker_id,
                "timestamp": time.time(),
                "uptime_seconds": time.time() - self.start_time,
                "memory_mb": 0,
                "cpu_percent": 0,
                "error": str(e)
            }
    
    def _get_accurate_memory_usage(self) -> tuple:
        """Get accurate memory usage including all child processes
        
        Returns:
            Tuple of (main_process_memory_mb, child_processes_memory_mb, total_memory_mb)
        """
        # Get memory from main process
        try:
            main_memory = self.process.memory_info().rss / (1024 * 1024)
            logger.debug(f"Main process {self.process.pid} ({self.process.name()}) memory: {main_memory:.2f}MB")
        except Exception as e:
            logger.error(f"Error getting main process memory: {e}")
            main_memory = 0
            
        # Important: Use a proper process tracking approach
        # Track unique processes to prevent double counting
        counted_pids = set()
        counted_pids.add(self.process.pid)  # Add the main process to counted set
        
        # Track browser process groups for more accurate reporting
        browser_processes = []
        child_memory = 0
        
        # First look for direct children (most reliable)
        try:
            # Get only our direct children
            children = []
            try:
                children = self.process.children(recursive=True)
                logger.debug(f"Found {len(children)} direct children of process {self.process.pid}")
            except Exception as e:
                logger.error(f"Error getting children: {e}")
                
            # Track memory from direct child processes
            for child in children:
                try:
                    pid = child.pid
                    if pid not in counted_pids:
                        if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                            # Get memory info using RSS (Resident Set Size)
                            mem = child.memory_info().rss / (1024 * 1024)
                            name = child.name()
                            
                            # Only count browser-related processes for child memory
                            # This prevents counting system processes that happen to be children
                            is_browser = any(browser in name.lower() for browser in 
                                           ['chrome', 'chromium', 'firefox', 'webkit', 'playwright', 'headless'])
                            
                            if is_browser:
                                logger.debug(f"Browser child process {pid} ({name}): {mem:.2f}MB")
                                child_memory += mem
                                browser_processes.append((pid, name, mem))
                            else:
                                logger.debug(f"Non-browser child process {pid} ({name}): {mem:.2f}MB")
                                
                            # Add to tracked PIDs regardless
                            counted_pids.add(pid)
                except Exception as e:
                    logger.debug(f"Error processing child {pid}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error in direct children memory calculation: {e}")
            
        # Next, find potential browser processes that might not be direct children
        try:
            # Get system-wide info on browser processes
            # Focus only on processes likely to be browser-related
            browser_keywords = ['chrome', 'chromium', 'firefox', 'webkit', 'playwright', 'headless']
            
            for proc in psutil.process_iter(['pid', 'name', 'ppid']):
                try:
                    pid = proc.pid
                    
                    # Skip if already counted
                    if pid in counted_pids:
                        continue
                    
                    # Check if browser-related by name
                    name = proc.name().lower()
                    if not any(keyword in name for keyword in browser_keywords):
                        continue
                        
                    # Get additional process info
                    try:
                        p = psutil.Process(pid)
                        if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                            continue
                            
                        # Get memory info and add to browser processes tracking
                        try:
                            mem = p.memory_info().rss / (1024 * 1024)
                            logger.debug(f"Found additional browser process: {pid} ({name}): {mem:.2f}MB")
                            browser_processes.append((pid, name, mem))
                            
                            # Don't add to child_memory yet - we need to determine if it's related
                            # to our main process first
                            counted_pids.add(pid)
                        except Exception as e:
                            logger.debug(f"Error getting memory for {pid}: {e}")
                    except Exception as e:
                        logger.debug(f"Error processing process {pid}: {e}")
                except Exception as e:
                    continue
        except Exception as e:
            logger.error(f"Error finding additional browser processes: {e}")
                
        # Handle if we're running inside container or virtual environment
        # where process relationships might not be properly tracked
        context_count = 0
        try:
            # Get browser context count if available
            if hasattr(self, 'worker') and hasattr(self.worker, 'contexts'):
                context_count = len(self.worker.contexts)
                logger.debug(f"Found {context_count} browser contexts")
        except Exception as e:
            logger.debug(f"Error getting context count: {e}")
        
        # Log all browser processes we found
        if browser_processes:
            browser_processes.sort(key=lambda x: x[2], reverse=True)
            browser_total = sum(mem for _, _, mem in browser_processes)
            browser_count = len(browser_processes)
            logger.info(f"Found {browser_count} browser processes using {browser_total:.2f}MB")
            
            # Categorize by process type
            by_type = {}
            for pid, name, mem in browser_processes:
                name_lower = name.lower()
                ptype = 'other'
                
                for key in ['chrome', 'chromium', 'firefox', 'webkit', 'playwright']:
                    if key in name_lower:
                        ptype = key
                        break
                        
                if ptype not in by_type:
                    by_type[ptype] = []
                by_type[ptype].append((pid, name, mem))
                
            # Log breakdown by type
            for ptype, procs in by_type.items():
                type_total = sum(mem for _, _, mem in procs)
                logger.info(f"  {ptype}: {len(procs)} processes, {type_total:.2f}MB")
                
            # Log top memory consumers
            logger.info("Top browser processes by memory:")
            for i, (pid, name, mem) in enumerate(browser_processes[:5]):
                logger.info(f"  {i+1}. PID {pid}: {name}: {mem:.2f}MB")
        
        # Sanity checks based on typical browser usage
        # This helps catch measurement errors and align with htop
        system_memory = psutil.virtual_memory()
        system_total_gb = system_memory.total / (1024**3)
        system_used_percent = system_memory.percent
        
        # Calculate expected memory usage based on context count and browser type
        # Roughly 250-350MB per browser context is typical
        if context_count > 0:
            # Validate our measurement against expected ranges
            expected_min = context_count * 200  # Minimum expected MB
            expected_max = context_count * 400  # Maximum expected MB
            
            logger.debug(f"Expected memory range for {context_count} contexts: " 
                       f"{expected_min:.2f}MB - {expected_max:.2f}MB")
            
            # Check if measured memory is outside reasonable range
            is_low = child_memory < expected_min
            is_high = child_memory > expected_max * 2  # Allow some leeway
            
            if is_low and browser_total > expected_min:
                logger.warning(f"Measured child memory ({child_memory:.2f}MB) is lower than expected "
                             f"({expected_min:.2f}MB). Using browser total ({browser_total:.2f}MB) instead.")
                child_memory = browser_total
            elif is_high:
                logger.warning(f"Measured child memory ({child_memory:.2f}MB) is unusually high compared "
                             f"to expected max ({expected_max:.2f}MB). May be measurement error.")
                
                # Cap at reasonable maximum to avoid wildly incorrect values
                # This helps align more closely with what htop reports
                reasonable_max = min(expected_max * 2, system_memory.total / (1024 * 1024) * 0.25)
                if child_memory > reasonable_max:
                    logger.warning(f"Capping child memory at reasonable maximum: {reasonable_max:.2f}MB")
                    child_memory = reasonable_max
        
        # Calculate total
        total_memory = main_memory + child_memory
        
        # Log summary
        logger.info(f"Memory totals: main={main_memory:.2f}MB, child={child_memory:.2f}MB, total={total_memory:.2f}MB")
        
        return main_memory, child_memory, total_memory

    def _get_accurate_cpu_percent(self) -> float:
        """Get accurate CPU percentage by calculating deltas between measurements"""
        # Get current CPU times
        current_time = time.time()
        current_cpu_times = self.process.cpu_times()
        
        # If this is the first call, set baseline and return 0
        if self._last_cpu_times is None:
            self._last_cpu_times = current_cpu_times
            self._last_cpu_time = current_time
            return 0.0
        
        # Calculate delta time
        delta_time = current_time - self._last_cpu_time
        if delta_time <= 0:
            return 0.0
        
        # Calculate CPU usage as change in CPU times divided by wall time
        delta_user = current_cpu_times.user - self._last_cpu_times.user
        delta_system = current_cpu_times.system - self._last_cpu_times.system
        delta_cpu_time = delta_user + delta_system
        
        # Calculate percentage - report total usage across all cores (like htop)
        # Don't divide by cpu_count to get a percentage that aligns with htop
        cpu_percent = (delta_cpu_time / delta_time) * 100.0
        
        # Update last values for next calculation
        self._last_cpu_times = current_cpu_times
        self._last_cpu_time = current_time
        
        return cpu_percent

    def store_metrics_snapshot(self, metrics: Dict[str, Any]):
        """Store a snapshot of metrics for historical tracking
        
        Args:
            metrics: Metrics to store
        """
        self.metrics_history.append(metrics)
        
        # Keep history size within limits
        if len(self.metrics_history) > self.max_history_entries:
            self.metrics_history.pop(0)

    def get_metrics_history(self) -> List[Dict[str, Any]]:
        """Get historical metrics
        
        Returns:
            List of historical metrics entries
        """
        return self.metrics_history


class BrowserContextMonitor:
    """Monitor resources for browser contexts"""
    
    def __init__(self, worker):
        """Initialize the browser context monitor
        
        Args:
            worker: BrowserWorker instance to monitor
        """
        self.worker = worker
        self.context_metrics_history = {}
    
    async def get_context_metrics(self) -> List[Dict[str, Any]]:
        """Get metrics for all browser contexts
        
        Returns:
            List of metrics for each context
        """
        context_metrics = []
        
        # Get all contexts from the worker
        for context_id, context_info in self.worker.contexts.items():
            metrics = {
                "context_id": context_id,
                "state": context_info.state.value,
                "creation_time": context_info.creation_time,
                "uptime_seconds": time.time() - context_info.creation_time,
                "last_activity_seconds": time.time() - context_info.last_activity_time,
            }
            
            # Add detailed metrics for active contexts
            if context_info.state == ContextState.ACTIVE and context_info.browser_context:
                try:
                    # Get page count
                    page_count = len(context_info.pages)
                    metrics["page_count"] = page_count
                    
                    # Get active page details
                    page_details = []
                    for page_id, page in context_info.pages.items():
                        try:
                            page_metrics = {
                                "page_id": page_id,
                                "url": await page.evaluate("window.location.href"),
                                "title": await page.evaluate("document.title")
                            }
                            page_details.append(page_metrics)
                        except Exception as e:
                            logger.error(f"Error getting metrics for page {page_id}: {e}")
                    
                    metrics["pages"] = page_details
                except Exception as e:
                    logger.error(f"Error getting detailed metrics for context {context_id}: {e}")
            
            # Add hibernation data size for hibernated contexts
            if context_info.state == ContextState.HIBERNATED and context_info.hibernation_data:
                try:
                    # Get approximate size of hibernation data
                    import sys
                    metrics["hibernation_data_size_kb"] = sys.getsizeof(
                        context_info.hibernation_data) / 1024
                except Exception as e:
                    logger.error(f"Error getting hibernation data size for context {context_id}: {e}")
            
            context_metrics.append(metrics)
        
        return context_metrics


class WorkerMonitor:
    """Comprehensive monitor for browser workers"""
    
    def __init__(self, worker, monitoring_interval: int = 60):
        """Initialize the worker monitor
        
        Args:
            worker: BrowserWorker instance to monitor
            monitoring_interval: Interval in seconds between monitoring runs
        """
        self.worker = worker
        self.worker_id = worker.worker_id
        self.resource_monitor = ResourceMonitor(worker.worker_id)
        self.context_monitor = BrowserContextMonitor(worker)
        self.monitoring_interval = monitoring_interval
        self.monitoring_task = None
        
        # Initialize background monitoring thread for continuous sampling
        self.continuous_sampling = False
        self.continuous_thread = None
        self.cpu_samples = []
        self.memory_samples = []
        self.max_samples = 60  # Keep 1 minute of samples at 1 per second
        self.sample_lock = asyncio.Lock()
    
    async def get_complete_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics for the worker and all contexts
        
        Returns:
            Dictionary containing system metrics and context metrics
        """
        # Get system metrics
        system_metrics = self.resource_monitor.get_system_metrics()
        
        # Get context metrics
        context_metrics = await self.context_monitor.get_context_metrics()
        
        # Add averaged metrics from continuous sampling if available
        async with self.sample_lock:
            if self.cpu_samples:
                system_metrics["cpu_percent_avg"] = sum(self.cpu_samples) / len(self.cpu_samples)
                system_metrics["cpu_percent_max"] = max(self.cpu_samples)
                system_metrics["cpu_percent_min"] = min(self.cpu_samples)
            
            if self.memory_samples:
                system_metrics["memory_mb_avg"] = sum(self.memory_samples) / len(self.memory_samples)
                system_metrics["memory_mb_max"] = max(self.memory_samples)
                system_metrics["memory_mb_min"] = min(self.memory_samples)
        
        # Combine metrics
        complete_metrics = {
            **system_metrics,
            "context_count": len(self.worker.contexts),
            "contexts": context_metrics
        }
        
        # Store metrics snapshot
        self.resource_monitor.store_metrics_snapshot(complete_metrics)
        
        return complete_metrics
    
    async def start_monitoring(self):
        """Start the monitoring background task and continuous sampling"""
        logger.info(f"Starting resource monitoring for worker {self.worker_id}")
        
        # Start continuous sampling in a separate thread
        await self.start_continuous_sampling()
        
        # Start main monitoring task
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        return self.monitoring_task
    
    async def start_continuous_sampling(self):
        """Start continuous sampling of CPU and memory in a separate thread"""
        import threading
        
        # Set flag to keep sampling thread running
        self.continuous_sampling = True
        
        # Store the event loop from the main thread
        main_loop = asyncio.get_running_loop()
        
        # Create a local reference to the resource monitor that will be captured in the thread's closure
        resource_monitor = self.resource_monitor
        
        # Define sampling function that will run in thread
        def sampling_thread():
            process = psutil.Process()
            # Initialize for main process monitoring
            last_cpu_times = process.cpu_times()
            last_cpu_time = time.time()
            
            # Initialize for child process monitoring
            last_children_info = []  # List of (pid, cpu_times) tuples
            
            # For CPU averaging
            cpu_samples = []
            cpu_samples_max = 10  # Keep same number as the main metrics function
            
            # Create local buffer for samples to minimize lock contention
            local_cpu_samples = []
            local_memory_samples = []
            
            while self.continuous_sampling:
                try:
                    # Use the captured resource_monitor reference to access memory function
                    main_memory_mb, child_memory_mb, total_memory_mb = resource_monitor._get_accurate_memory_usage()
                    
                    # Calculate CPU using delta method (similar to htop)
                    current_time = time.time()
                    current_cpu_times = process.cpu_times()
                    
                    delta_time = current_time - last_cpu_time
                    if delta_time > 0:
                        # Main process CPU - collect per-process stats
                        delta_user = current_cpu_times.user - last_cpu_times.user
                        delta_system = current_cpu_times.system - last_cpu_times.system
                        delta_cpu_time = delta_user + delta_system
                        
                        # Calculate percentage without dividing by core count
                        # For per-core monitoring, this would need to be converted
                        main_cpu_percent = (delta_cpu_time / delta_time) * 100.0
                        
                        # Process all child processes
                        child_cpu_percent = 0.0
                        current_children_info = []
                        
                        # Calculate for each child process
                        for child in process.children(recursive=True):
                            try:
                                child_times = child.cpu_times()
                                child_pid = child.pid
                                current_children_info.append((child_pid, child_times))
                                
                                # If we have a previous sample for this pid, calculate delta
                                if last_children_info:
                                    # Create lookup dictionary for faster access
                                    prev_children_dict = dict(last_children_info)
                                    
                                    if child_pid in prev_children_dict:
                                        prev_times = prev_children_dict[child_pid]
                                        # Calculate deltas
                                        try:
                                            delta_time = current_time - last_cpu_time
                                            if delta_time > 0:
                                                delta_user = child_times.user - prev_times.user
                                                delta_system = child_times.system - prev_times.system
                                                delta_cpu_time = delta_user + delta_system
                                            
                                                # Add to total child CPU percent
                                                child_delta_percent = (delta_cpu_time / delta_time) * 100.0
                                                child_cpu_percent += child_delta_percent
                                        except Exception as e:
                                            logger.error(f"Error calculating CPU delta for child {child_pid}: {e}")
                                            # Skip this child if calculation fails
                                            pass
                            except:
                                continue  # Skip this child if there's an error
                        
                        # Store current children info for next iteration
                        last_children_info = current_children_info
                        
                        # Total CPU (main process + children)
                        total_cpu_percent = main_cpu_percent + child_cpu_percent
                        
                        # Average CPU usage (same approach as in get_system_metrics)
                        cpu_samples.append(total_cpu_percent)
                        while len(cpu_samples) > cpu_samples_max:
                            cpu_samples.pop(0)
                        
                        avg_cpu_percent = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
                        
                        # Also calculate normalized per-core value
                        normalized_cpu_percent = total_cpu_percent / psutil.cpu_count()
                        
                        # Add to local buffer
                        local_cpu_samples.append(total_cpu_percent)
                        local_memory_samples.append(total_memory_mb)
                        
                        # Keep local buffer limited
                        if len(local_cpu_samples) > 5:  # Send in batches of 5
                            # Create a copy of the current samples
                            cpu_samples_copy = local_cpu_samples.copy()
                            memory_samples_copy = local_memory_samples.copy()
                            
                            # Clear local buffer
                            local_cpu_samples = []
                            local_memory_samples = []
                            
                            # Schedule safe update on the main thread
                            main_loop.call_soon_threadsafe(
                                self._update_samples_from_thread, 
                                cpu_samples_copy, 
                                memory_samples_copy
                            )
                        
                        # Update last values for next calculation
                        last_cpu_times = current_cpu_times
                        last_cpu_time = current_time
                    
                    # Sleep for 1 second (htop-like sampling rate)
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Error in continuous sampling thread: {e}")
                    time.sleep(1)  # Avoid tight loop on error
        
        # Start thread
        self.continuous_thread = threading.Thread(target=sampling_thread, daemon=True)
        self.continuous_thread.start()
        logger.info(f"Started continuous resource sampling for worker {self.worker_id}")
    
    def _update_samples_from_thread(self, cpu_samples, memory_samples):
        """Update samples from the continuous sampling thread
        This method is called in the main thread via call_soon_threadsafe
        """
        try:
            # Add all samples
            self.cpu_samples.extend(cpu_samples)
            self.memory_samples.extend(memory_samples)
            
            # Keep samples within limit
            while len(self.cpu_samples) > self.max_samples:
                self.cpu_samples.pop(0)
            while len(self.memory_samples) > self.max_samples:
                self.memory_samples.pop(0)
        except Exception as e:
            logger.error(f"Error updating samples from thread: {e}")
    
    async def stop_monitoring(self):
        """Stop the monitoring background task and continuous sampling"""
        logger.info(f"Stopping resource monitoring for worker {self.worker_id}")
        
        # Stop continuous sampling
        self.continuous_sampling = False
        if self.continuous_thread:
            self.continuous_thread.join(timeout=2)
            self.continuous_thread = None
        
        # Stop monitoring task
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None
        
        logger.info(f"Stopped resource monitoring for worker {self.worker_id}")
    
    async def _monitoring_loop(self):
        """Background monitoring loop"""
        try:
            while True:
                try:
                    metrics = await self.get_complete_metrics()
                    
                    # Log summary metrics
                    logger.info(
                        f"Worker {self.worker_id} metrics: "
                        f"Memory: {metrics['memory_mb']:.2f}MB, "
                        f"CPU: {metrics['cpu_percent']:.1f}%, "
                        f"Contexts: {metrics['context_count']}"
                    )
                    
                    # Check for concerning metrics
                    self._check_for_alerts(metrics)
                    
                except Exception as e:
                    logger.error(f"Error in monitoring loop: {e}")
                
                # Wait for next monitoring interval
                await asyncio.sleep(self.monitoring_interval)
        except asyncio.CancelledError:
            logger.info(f"Monitoring loop for worker {self.worker_id} cancelled")
            raise
    
    def _check_for_alerts(self, metrics: Dict[str, Any]):
        """Check metrics for concerning values and log alerts
        
        Args:
            metrics: Current metrics
        """
        # Memory alerts
        if metrics['memory_mb'] > 1000:  # Alert if using more than 1GB
            logger.warning(
                f"Worker {self.worker_id} high memory usage: {metrics['memory_mb']:.2f}MB"
            )
        
        # CPU alerts
        if metrics['cpu_percent'] > 80:
            logger.warning(
                f"Worker {self.worker_id} high CPU usage: {metrics['cpu_percent']:.1f}%"
            )
        
        # Context alerts
        if metrics['context_count'] > 10:
            logger.warning(
                f"Worker {self.worker_id} has many contexts: {metrics['context_count']}"
            )
        
        # Check individual contexts
        for context in metrics['contexts']:
            # Check for contexts with many pages
            if context.get('page_count', 0) > 5:
                logger.warning(
                    f"Context {context['context_id']} has many pages: {context['page_count']}"
                )
            
            # Check for long-idle contexts
            if context.get('last_activity_seconds', 0) > 1800:  # 30 minutes
                logger.warning(
                    f"Context {context['context_id']} idle for "
                    f"{context['last_activity_seconds']:.0f}s"
                )


# API integration functions
def register_metrics_endpoints(app, worker_monitor: WorkerMonitor):
    """Register metrics endpoints with the FastAPI app
    
    Args:
        app: FastAPI application
        worker_monitor: WorkerMonitor instance
    """
    @app.get("/metrics")
    async def get_metrics():
        """Get current metrics for the browser worker"""
        metrics = await worker_monitor.get_complete_metrics()
        
        # Format the metrics for display
        cpu_percent = metrics.get("cpu_percent", 0)
        cpu_avg = metrics.get("cpu_percent_avg", 0)
        memory_mb = metrics.get("memory_mb", 0)
        contexts = metrics.get("context_count", 0)
        
        # Log the metrics to the console for monitoring
        logger.info(f"Worker {worker_monitor.worker_id} metrics: Memory: {memory_mb:.2f}MB, CPU: {cpu_percent:.1f}% (Avg: {cpu_avg:.1f}%), Contexts: {contexts}")
        
        # Check for concerning values
        if cpu_percent > 80:
            logger.warning(f"Worker {worker_monitor.worker_id} high CPU usage: {cpu_percent:.1f}%")
            
        if memory_mb > 500:
            logger.warning(f"Worker {worker_monitor.worker_id} high memory usage: {memory_mb:.2f}MB")
        
        return metrics
    
    @app.get("/metrics/history")
    async def get_metrics_history():
        """Get historical metrics for the browser worker"""
        try:
            history = worker_monitor.resource_monitor.get_metrics_history()
            return {"history": history}
        except Exception as e:
            logger.error(f"Error getting metrics history: {e}")
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Error getting metrics history: {str(e)}")


async def setup_worker_monitoring(worker, app=None, interval=60):
    """Set up monitoring for a browser worker
    
    Args:
        worker: BrowserWorker instance to monitor
        app: Optional FastAPI app to register endpoints with
        interval: Monitoring interval in seconds
        
    Returns:
        WorkerMonitor instance
    """
    # Create worker monitor
    monitor = WorkerMonitor(worker, monitoring_interval=interval)
    
    # Start monitoring task
    await monitor.start_monitoring()
    
    # Register API endpoints if app provided
    if app:
        register_metrics_endpoints(app, monitor)
    
    return monitor


if __name__ == "__main__":
    # Example usage
    async def example():
        # Mock worker for testing
        class MockWorker:
            def __init__(self):
                self.worker_id = "test-worker"
                self.contexts = {}
        
        worker = MockWorker()
        monitor = ResourceMonitor(worker.worker_id)
        metrics = monitor.get_system_metrics()
        print(f"System Metrics: {metrics}")
    
    asyncio.run(example())
