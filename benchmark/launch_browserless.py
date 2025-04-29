import subprocess
import asyncio
from contextlib import contextmanager
import time

@contextmanager
def launch_n_servers(num_servers:int):
    processes = []
    for i in range(num_servers):
        process = subprocess.Popen(
            [
                "docker", "run", "-p", f"{9213+i}:3000", "-e", "CONCURRENT=40", "ghcr.io/browserless/chromium"
            ]
        )
        processes.append(process)
    
    try:
        yield [f"ws://localhost:{9213 + i}" for i in range(num_servers)]
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
    with launch_n_servers(32) as endpoints:
        print(endpoints)
        time.sleep(1000000)

