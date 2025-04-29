import argparse
import datetime
import time
from concurrent.futures import ProcessPoolExecutor

import pandas as pd
from benchmark_server_v1 import test_server_v1
from benchmark_server_v2 import test_server_v2
from multiprocess_async_playwright import test_async_playwright
from multiprocess_sync_playwright import test_sync_playwright
from multiprocess_async_playwright_server import test_async_playwright_server

if __name__ == "__main__":
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
    if args.method == "async":
        with ProcessPoolExecutor(num_proc) as executor:
            dfs = list(executor.map(test_async_playwright, [8] * (size // 8)))
    elif args.method == "sync":
        with ProcessPoolExecutor(num_proc) as executor:
            dfs = list(executor.map(test_sync_playwright, [None] * size))
    elif args.method == "server_v1":
        with ProcessPoolExecutor(num_proc) as executor:
            dfs = list(executor.map(test_server_v1, [size // num_proc] * num_proc))
    elif args.method == "server_v2":
        with ProcessPoolExecutor(num_proc) as executor:
            dfs = list(executor.map(test_server_v2, [size // num_proc] * num_proc))
    elif args.method == "async_playwright_server":
        with ProcessPoolExecutor(num_proc) as executor:
            dfs = list(
                executor.map(
                    test_async_playwright_server,
                    [8] * (size // 8),
                    [f"ws://localhost:{9213 + i}" for i in range(num_proc)]
                    * (size // 256),
                )
            )
    elif args.method == "browserless":
        with ProcessPoolExecutor(num_proc) as executor:
            dfs = list(
                executor.map(
                    test_async_playwright_server,
                    [8] * (size // 8),
                    [
                        f"ws://localhost:{9213 + i}/chromium/playwright"
                        for i in range(num_proc)
                    ]
                    * (size // 256),
                )
            )
    elif args.method == "through_proxy":
        with ProcessPoolExecutor(num_proc) as executor:
            dfs = list(
                executor.map(
                    test_async_playwright_server,
                    [8] * (size // 8),
                    [f"ws://localhost:8000"] * (size // 8),
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
