import argparse
import datetime
import glob
import multiprocessing as mp
import os
import subprocess
import time

import pandas as pd


def run_python_in_subprocess(idx, args):
    # Run the naive.py script as a subprocess
    proc = subprocess.Popen(["python", args.file])
    pid = proc.pid
    proc.wait()
    return pid


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-proc", type=int, default=32, help="Number of processes")
    parser.add_argument(
        "--file",
        type=str,
        default="/home/tianhao/browser_pilot/benchmark/multiprocess_async.py",
        help="Command to run",
    )
    args = parser.parse_args()
    num_proc = args.num_proc
    start = time.time()
    with mp.Pool(num_proc) as pool:
        pids = pool.starmap(
            run_python_in_subprocess, [(i, args) for i in range(num_proc)]
        )
    end = time.time()
    print(f"Total time: {end - start:.2f} seconds")

    # Search for CSV files ending with PID
    csv_files = glob.glob("*.csv")
    csv_files = [f for f in csv_files if any(pid in f for pid in map(str, pids))]
    print(f"Found {len(csv_files)} CSV files")
    assert len(csv_files) == num_proc

    # Merge all CSVs into one DataFrame with debug print
    dfs = []
    for f in csv_files:
        df = pd.read_csv(f)
        print(f"{f}: columns = {df.columns.tolist()}")  # Debug: show columns
        dfs.append(df)
    # Optionally, align columns explicitly if you know them:
    # expected_columns = ["col1", "col2", ...]
    # dfs = [df[expected_columns] for df in dfs]
    merged_df = pd.concat(dfs, ignore_index=True)
    # Choose an appropriate merged filename based on input file and timestamp
    base_name = os.path.splitext(os.path.basename(args.file))[0]
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_filename = f"{base_name}_merged_{timestamp}.csv"
    merged_df.to_csv(merged_filename, index=False)
    print(f"Merged CSV saved as {merged_filename}")
    for f in csv_files:
        os.remove(f)
