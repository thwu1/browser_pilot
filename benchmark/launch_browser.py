import subprocess
import time
from contextlib import contextmanager


@contextmanager
def launch_n_servers(num_servers: int, type: str = "playwright"):
    processes = []
    for i in range(num_servers):
        if type == "playwright":
            process = subprocess.Popen(
                [
                    "playwright",
                    "run-server",
                    "--port",
                    str(9214 + i),
                    "--host",
                    "localhost",
                ]
            )
        elif type == "cdp":
            process = subprocess.Popen(
                [
                    "/home/tianhao/.cache/ms-playwright/chromium_headless_shell-1161/chrome-linux/headless_shell",
                    "--no-sandbox",
                    "--user-data-dir=/tmp/pw-chrome-cdp-profile-{}".format(i),
                    "--headless",
                    f"--remote-debugging-port={9214+i}",
                ]
            )
        processes.append(process)

    try:
        yield [f"ws://localhost:{9214 + i}" for i in range(num_servers)]
    finally:
        for process in processes:
            process.send_signal(subprocess.signal.SIGINT)  # Send CTRL+C (SIGINT)
            process.wait()  # Wait for process to terminate
            if process.poll() is None:  # If process is still running
                process.terminate()  # Send SIGTERM
                process.wait()
                if process.poll() is None:  # If still running after SIGTERM
                    process.kill()  # Force kill as last resort
                    process.wait()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--type", type=str, default="playwright")
    parser.add_argument("--n", type=int, default=1)
    args = parser.parse_args()
    try:
        with launch_n_servers(args.n, args.type) as endpoints:
            print(endpoints)
            # Replace sleep with infinite loop
            while True:
                time.sleep(60)  # Sleep in smaller intervals to be more responsive
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
