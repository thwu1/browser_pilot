#!/usr/bin/env python3
"""
Scheduler Module

This module implements task scheduling strategies for distributing tasks 
across multiple browser workers.
"""

import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Union

logger = logging.getLogger(__name__)

class SchedulerType(Enum):
    """Types of scheduling strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CONTEXT_AFFINITY = "context_affinity"

class RoundRobinScheduler:
    """
    Implements a simple round-robin scheduling strategy.
    Tasks are assigned to workers in circular order, regardless of worker load.
    """
    
    def __init__(self, worker_ids: List[str]):
        """
        Initialize the round-robin scheduler
        
        Args:
            worker_ids: List of worker IDs available for scheduling
        """
        self.worker_ids = worker_ids
        self.current_index = 0
        self.worker_contexts = {worker_id: set() for worker_id in worker_ids}
        self.context_to_worker = {}
        
        logger.info(f"Initialized round-robin scheduler with {len(worker_ids)} workers")
    
    def get_next_worker(self) -> str:
        """
        Get the next worker in round-robin fashion
        
        Returns:
            Worker ID to use for the next task
        """
        if not self.worker_ids:
            raise ValueError("No workers available for scheduling")
            
        worker_id = self.worker_ids[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.worker_ids)
        
        return worker_id
    
    def assign_task(self, context_id: Optional[str] = None) -> str:
        """
        Assign a task to a worker
        
        Args:
            context_id: Optional context ID for the task
            
        Returns:
            Worker ID to execute the task
        """
        # If context already exists, use the worker that owns it
        if context_id and context_id in self.context_to_worker:
            return self.context_to_worker[context_id]
            
        # Otherwise get the next worker in rotation
        return self.get_next_worker()
    
    def register_context(self, context_id: str, worker_id: str) -> None:
        """
        Register a new context with its worker
        
        Args:
            context_id: ID of the context
            worker_id: ID of the worker that owns the context
        """
        if worker_id not in self.worker_ids:
            raise ValueError(f"Worker {worker_id} is not registered with this scheduler")
            
        self.worker_contexts[worker_id].add(context_id)
        self.context_to_worker[context_id] = worker_id
        logger.debug(f"Registered context {context_id} with worker {worker_id}")
    
    def unregister_context(self, context_id: str) -> None:
        """
        Unregister a context when it's terminated
        
        Args:
            context_id: ID of the context to unregister
        """
        if context_id in self.context_to_worker:
            worker_id = self.context_to_worker[context_id]
            self.worker_contexts[worker_id].discard(context_id)
            del self.context_to_worker[context_id]
            logger.debug(f"Unregistered context {context_id} from worker {worker_id}")
    
    def add_worker(self, worker_id: str) -> None:
        """
        Add a new worker to the scheduler
        
        Args:
            worker_id: ID of the worker to add
        """
        if worker_id not in self.worker_ids:
            self.worker_ids.append(worker_id)
            self.worker_contexts[worker_id] = set()
            logger.info(f"Added worker {worker_id} to scheduler")
    
    def remove_worker(self, worker_id: str) -> Set[str]:
        """
        Remove a worker from the scheduler
        
        Args:
            worker_id: ID of the worker to remove
            
        Returns:
            Set of context IDs that were owned by this worker
        """
        if worker_id not in self.worker_ids:
            return set()
            
        # Remove worker from rotation
        self.worker_ids.remove(worker_id)
        
        # Reset the index if needed
        if self.current_index >= len(self.worker_ids) and self.worker_ids:
            self.current_index = 0
            
        # Get contexts owned by this worker
        contexts = self.worker_contexts.pop(worker_id, set())
        
        # Remove context mappings
        for context_id in contexts:
            if context_id in self.context_to_worker:
                del self.context_to_worker[context_id]
                
        logger.info(f"Removed worker {worker_id} from scheduler, orphaned {len(contexts)} contexts")
        return contexts
    
    def get_worker_count(self) -> int:
        """Get the number of workers in the scheduler"""
        return len(self.worker_ids)
    
    def get_worker_load(self, worker_id: str) -> int:
        """
        Get the number of contexts assigned to a worker
        
        Args:
            worker_id: ID of the worker
            
        Returns:
            Number of contexts assigned to the worker
        """
        if worker_id not in self.worker_contexts:
            return 0
        return len(self.worker_contexts[worker_id])


class LeastLoadedScheduler(RoundRobinScheduler):
    """
    Implements a least-loaded scheduling strategy.
    Tasks are assigned to the worker with the fewest contexts.
    Inherits from RoundRobinScheduler for basic functionality.
    """
    
    def __init__(self, worker_ids: List[str]):
        """Initialize the least-loaded scheduler"""
        super().__init__(worker_ids)
        logger.info(f"Initialized least-loaded scheduler with {len(worker_ids)} workers")
    
    def get_next_worker(self) -> str:
        """
        Get the least loaded worker based on context count
        
        Returns:
            Worker ID to use for the next task
        """
        if not self.worker_ids:
            raise ValueError("No workers available for scheduling")
            
        # Find worker with the fewest contexts
        worker_id = min(
            self.worker_ids,
            key=lambda wid: len(self.worker_contexts.get(wid, set()))
        )
        
        return worker_id


# Factory function to create scheduler instances
def create_scheduler(scheduler_type: SchedulerType, worker_ids: List[str]):
    """
    Create a scheduler instance based on the specified type
    
    Args:
        scheduler_type: Type of scheduler to create
        worker_ids: List of worker IDs available for scheduling
        
    Returns:
        Scheduler instance
    """
    if scheduler_type == SchedulerType.ROUND_ROBIN:
        return RoundRobinScheduler(worker_ids)
    elif scheduler_type == SchedulerType.LEAST_LOADED:
        return LeastLoadedScheduler(worker_ids)
    elif scheduler_type == SchedulerType.CONTEXT_AFFINITY:
        # TODO: Implement context affinity scheduler
        # This would prioritize assigning tasks to workers that already
        # have related contexts for better caching and performance
        logger.warning("Context affinity scheduler not implemented, using round-robin instead")
        return RoundRobinScheduler(worker_ids)
    else:
        logger.warning(f"Unknown scheduler type {scheduler_type}, using round-robin")
        return RoundRobinScheduler(worker_ids)