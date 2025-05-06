import logging
import time
from contextlib import ContextDecorator


class Timer(ContextDecorator):
    def __init__(self, name=None, logger=None, log_file="scheduler_timing.log"):
        self.name = name
        self.logger = logger
        self.log_file = log_file
        self.start_time = None
        self.end_time = None
        self.elapsed = None
        if self.logger is None and self.log_file:
            # Set up a file logger if not provided
            self.file_logger = logging.getLogger(f"TimerLogger_{self.log_file}")
            if not self.file_logger.handlers:
                handler = logging.FileHandler(self.log_file)
                formatter = logging.Formatter("%(asctime)s %(message)s")
                handler.setFormatter(formatter)
                self.file_logger.addHandler(handler)
                self.file_logger.setLevel(logging.INFO)
            self.logger = self.file_logger

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        self.elapsed = self.end_time - self.start_time
        msg = f"[Timer] {self.name or ''} Elapsed: {self.elapsed:.6f} seconds"
        if self.logger:
            self.logger.info(msg)
        else:
            print(msg)
        return False
