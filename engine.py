from async_worker import AsyncBrowserWorker, BrowserWorkerTask
from monitor import ResourceMonitor
from scheduler import RoundRobinScheduler, SchedulerType, create_scheduler
import asyncio
import json
import logging
import multiprocessing as mp
from typing import Dict, List, Set, Any, Optional, Tuple
import uuid
import time
import zmq
import os
import base64
import signal
import sys
import traceback

logger = logging.getLogger(__name__)


class BrowserEngine:
    """Browser engine that manages multiple browser workers in separate processes"""

    def __init__(self, config=None):
        """Initialize the browser engine with the specified configuration"""
