import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

from util import config_loader

# Get the project root directory for absolute paths
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

config = config_loader()


def main():
    print("Starting all services according to config:", config)
    processes = []

    # Check Redis if monitor is enabled
    if config["monitor"]["use_monitor"]:
        import redis

        redis_client = redis.Redis(
            host=config["monitor"]["redis_host"],
            port=config["monitor"]["redis_port"],
            db=0,
        )
        if not redis_client.ping():
            print("Redis is not running, exiting...")
            return

    try:
        # launch server
        print("Starting server processes...")
        server_process = subprocess.Popen(
            [
                "python",
                "scripts/launch_server.py",
                "--type",
                config["server"]["type"],
                "--n",
                str(config["server"]["num_servers"]),
                "--port",
                str(config["server"]["start_port"]),
            ],
            stderr=subprocess.PIPE,  # Capture stderr for error reporting
            cwd=PROJECT_ROOT,
        )
        processes.append(("server", server_process))

        # launch proxy
        print("Starting proxy server...")
        proxy_process = subprocess.Popen(
            [
                "uvicorn",
                "src.proxy_multiplex:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(config["proxy"]["port"]),
                "--workers",
                str(config["proxy"]["num_workers"]),
            ],
            stderr=subprocess.PIPE,  # Capture stderr for error reporting
            cwd=PROJECT_ROOT,  # Set working directory for uvicorn
        )
        processes.append(("proxy", proxy_process))

        # launch monitor
        if config["monitor"]["use_monitor"]:
            print("Starting monitoring server...")
            monitor_process = subprocess.Popen(
                [
                    "python",
                    "src/monitoring/server.py",
                    "--port",
                    str(config["monitor"]["port"]),
                ],
                stderr=subprocess.PIPE,  # Capture stderr for error reporting
                cwd=PROJECT_ROOT,
            )
            processes.append(("monitor", monitor_process))

        print("All services started. Press Ctrl+C to gracefully shut down.")

        # Register signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            print("\nReceived shutdown signal, terminating all processes...")
            shutdown_processes(processes)
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Handle kill command

        # Main loop - periodically check if processes are still alive
        while all(process.poll() is None for _, process in processes):
            time.sleep(30)

        # If we get here, one of the processes died unexpectedly
        print("One or more processes terminated unexpectedly.")
        for name, process in processes:
            if process.poll() is not None:
                print(f"Process {name} exited with code {process.returncode}")
                # Print stderr output from the failed process
                stderr_output = process.stderr.read().decode("utf-8", errors="replace")
                if stderr_output:
                    print(f"Error output from {name}: {stderr_output}")

        # Terminate all remaining processes
        shutdown_processes(processes)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        print("Detailed traceback:")
        traceback.print_exc()
        shutdown_processes(processes)
        sys.exit(1)


def shutdown_processes(processes):
    """Gracefully terminate all processes in reverse order of creation"""
    print("Shutting down all services...")

    # Shutdown in reverse order (typically monitor → proxy → server)
    for name, process in reversed(processes):
        if process.poll() is None:  # Process is still running
            print(f"Terminating {name} process...")
            try:
                # Send SIGTERM for graceful shutdown (same as Ctrl+C for most processes)
                process.terminate()

                # Wait up to 5 seconds for process to terminate
                for _ in range(50):
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)

                # If process is still running, force kill it
                if process.poll() is None:
                    print(f"{name} process not responding, forcing kill...")
                    process.kill()
                    process.wait()
            except Exception as e:
                print(f"Error shutting down {name}: {e}")
                traceback.print_exc()

    print("All services stopped.")


if __name__ == "__main__":
    main()
