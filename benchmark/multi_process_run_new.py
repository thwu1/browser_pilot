import argparse
import atexit
import datetime
import os
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError

import pandas as pd
import psutil
from benchmark_server_v1 import test_server_v1
from benchmark_server_v2 import test_server_v2
from multiprocess_async_cdp import test_async_cdp
from multiprocess_async_cdp_ind import test_async_cdp_ind
from multiprocess_async_playwright import test_async_playwright
from multiprocess_async_playwright_server import test_async_playwright_server
from multiprocess_async_playwright_server_ind import test_async_playwright_server_ind
from multiprocess_sync_playwright import test_sync_playwright


def cleanup_processes():
    """Cleanup any remaining child processes"""
    current_process = psutil.Process()
    children = current_process.children(recursive=True)
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass

    # Give them some time to terminate gracefully
    _, alive = psutil.wait_procs(children, timeout=3)

    # Force kill any remaining processes
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def signal_handler(signum, frame):
    """Handle termination signals"""
    print(f"\nReceived signal {signum}. Cleaning up processes...")
    cleanup_processes()
    sys.exit(1)


if __name__ == "__main__":
    # Register cleanup handlers
    atexit.register(cleanup_processes)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser()
    parser.add_argument("--num-proc", type=int, default=32, help="Number of processes")
    parser.add_argument("--total-size", type=int, default=-1, help="Batch size")
    parser.add_argument(
        "--method",
        type=str,
        default="sync",
    )
    args = parser.parse_args()
    num_proc = args.num_proc
    size = args.total_size
    if size == -1:
        size = num_proc

    start = time.time()
    executor = ProcessPoolExecutor(num_proc)
    try:
        if args.method == "async":
            dfs = list(executor.map(test_async_playwright, [8] * (size // 8)))
        elif args.method == "sync":
            dfs = list(executor.map(test_sync_playwright, [None] * size))
        elif args.method == "server_v1":
            dfs = list(executor.map(test_server_v1, [size // num_proc] * num_proc))
        elif args.method == "server_v2":
            dfs = list(executor.map(test_server_v2, [size // num_proc] * num_proc))
        elif args.method == "async_playwright_server":
            dfs = list(
                executor.map(
                    test_async_playwright_server,
                    [8] * (size // 8),
                    [f"ws://localhost:{9214 + i}" for i in range(num_proc)]
                    * (size // 256),
                )
            )
        elif args.method == "browserless":
            dfs = list(
                executor.map(
                    test_async_playwright_server,
                    [8] * (size // 8),
                    [
                        f"ws://localhost:{9214+i}/chromium/playwright?timeout=240000"
                        for i in range(num_proc)
                    ]
                    * (size // 256),
                )
            )
        elif args.method == "browserless_ind":
            dfs = list(
                executor.map(
                    test_async_playwright_server_ind,
                    [8] * (size // 8),
                    [
                        f"ws://localhost:{9214+i}/chromium/playwright?timeout=240000"
                        for i in range(num_proc)
                    ]
                    * (size // 256),
                )
            )
        elif args.method == "through_proxy":
            dfs = list(
                executor.map(
                    test_async_playwright_server,
                    [8] * (size // 8),
                    [f"ws://localhost:8000"] * (size // 8),
                )
            )
        elif args.method == "through_proxy_ind":
            dfs = list(
                executor.map(
                    test_async_playwright_server_ind,
                    [8] * (size // 8),
                    [f"ws://localhost:8000"] * (size // 8),
                )
            )
        elif args.method == "async_playwright_server_ind":
            dfs = list(
                executor.map(
                    test_async_playwright_server_ind,
                    [8] * (size // 8),
                    [f"ws://localhost:{9214 + i}" for i in range(num_proc)]
                    * (size // 256),
                )
            )
        elif args.method == "async_cdp_ind":
            dfs = list(
                executor.map(
                    test_async_cdp_ind,
                    [8] * (size // 8),
                    [f"http://localhost:{9214 + i}" for i in range(num_proc)]
                    * (size // 256),
                )
            )
        elif args.method == "async_cdp":
            dfs = list(
                executor.map(
                    test_async_cdp,
                    [8] * (size // 8),
                    [f"http://localhost:{9214 + i}" for i in range(num_proc)]
                    * (size // 256),
                )
            )
        else:
            raise ValueError(f"Unknown method: {args.method}")

        end = time.time()
        print(f"Total time: {end - start:.2f} seconds")

        merged_df = pd.concat(dfs, ignore_index=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        merged_filename = f"logs/{args.method}_merged_{timestamp}.csv"
        merged_df.to_csv(merged_filename, index=False)
        print(f"Merged CSV saved as {merged_filename}")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        raise
    finally:
        print("Shutting down executor...")
        executor.shutdown(wait=False)
        cleanup_processes()
