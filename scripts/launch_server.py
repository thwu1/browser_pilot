import subprocess
import time
from contextlib import contextmanager

from util import config_loader


@contextmanager
def launch_n_servers(num_servers: int, type: str, start_port: int):
    assert type in ["playwright", "cdp"]
    processes = []
    for i in range(num_servers):
        if type == "playwright":
            process = subprocess.Popen(
                [
                    "playwright",
                    "run-server",
                    "--port",
                    str(start_port + i),
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
                    f"--remote-debugging-port={start_port+i}",
                ]
            )
        processes.append(process)

    try:
        yield [f"ws://localhost:{start_port + i}" for i in range(num_servers)]
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
    parser.add_argument("--port", type=int, default=9214)
    args = parser.parse_args()
    with launch_n_servers(args.n, args.type, args.port) as endpoints:
        print(f"Started {args.n} servers with endpoints: {endpoints}")
        try:
            while True:
                time.sleep(600)
        except KeyboardInterrupt:
            print("Shutting down gracefully...")
