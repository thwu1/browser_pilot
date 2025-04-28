import asyncio
from datetime import datetime
import json
import logging
import signal
import sys
import time
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
import math

import yaml
import zmq
import zmq.asyncio
from utils import MsgpackDecoder, MsgType, make_zmq_socket

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Constants ---
# Define a reasonable maximum memory for scaling the bar (e.g., 1GB or 2GB)
# Adjust this based on your typical worker memory usage
MAX_EXPECTED_MEMORY_MB = 1024
# Define a maximum error rate for scaling the bar (e.g., 10% = 0.1)
MAX_EXPECTED_ERROR_RATE = 0.10  # 10%
# Heartbeat timeout in seconds - consider worker disconnected after this time
HEARTBEAT_TIMEOUT_SECONDS = 15
# Global status dict
worker_status = {}

# Create FastAPI app
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
decoder = MsgpackDecoder()

# ZMQ setup
config = yaml.safe_load(open("src/entrypoint/config.yaml"))
ctx = zmq.asyncio.Context()

status_socket = None

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup
    global status_socket, ctx
    status_socket = make_zmq_socket(
        ctx, config["worker_client_config"]["monitor_path"], zmq.PULL, bind=True
    )
    status_task = asyncio.create_task(collect_status())

    yield

    # Shutdown
    status_task.cancel()
    try:
        await status_task
    except asyncio.CancelledError:
        pass

    if status_socket:
        status_socket.close()
    ctx.term()


app = FastAPI(lifespan=lifespan)


async def collect_status():
    """Background task to collect worker status updates"""
    global worker_status, decoder, status_socket

    while True:
        try:
            status_bytes = await status_socket.recv_multipart()
            identity = status_bytes[0].decode()
            msg_type = status_bytes[1]

            if msg_type == MsgType.STATUS:
                status = decoder(status_bytes[2])
                worker_status[identity] = status
                logger.debug(f"Updated status for worker {identity}")
        except Exception as e:
            logger.error(f"Error collecting status: {e}")
            await asyncio.sleep(0.1)


@app.get("/status")
async def get_status():
    """Return current worker status as JSON"""
    return worker_status


# --- Helper Functions ---
def format_timestamp(ts):
    """Helper function to format UNIX timestamp"""
    if ts is None or math.isnan(ts):
        return "N/A"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return "Invalid Date"


def safe_get(data, key, default=0):
    """Safely get a numeric value, returning default if None or NaN."""
    val = data.get(key, default)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return val


def calculate_bar_width(value, max_value):
    if max_value == 0:
        return 0
    percentage = (value / max_value) * 100
    return max(0, min(percentage, 100))


@app.get("/status/html", response_class=HTMLResponse)
async def status_html():
    """Display worker status as HTML table with auto-refresh"""

    current_time = time.time()  # Get current time once for comparison

    # --- Calculate Summary Statistics ---
    active_workers = 0
    disconnected_workers = 0  # Add counter for disconnected
    total_running_tasks = 0
    total_waiting_tasks = 0
    total_finished_tasks = 0
    total_cpu_usage = 0.0
    total_memory_usage = 0.0
    num_workers_for_avg = 0
    for worker_id, status in worker_status.items():
        is_running = status.get("running", False)
        last_heartbeat = status.get("last_heartbeat")
        is_disconnected = False
        if last_heartbeat is not None:
            if (current_time - last_heartbeat) > HEARTBEAT_TIMEOUT_SECONDS:
                is_disconnected = True

        if (
            is_running and not is_disconnected
        ):  # Only count truly active workers for averages
            active_workers += 1
            total_cpu_usage += safe_get(status, "cpu_usage_percent")
            total_memory_usage += safe_get(status, "memory_usage_mb")
            num_workers_for_avg += 1
        elif is_disconnected:
            disconnected_workers += 1

        # Still include tasks from all reported workers
        total_running_tasks += safe_get(status, "num_running_tasks")
        total_waiting_tasks += safe_get(status, "num_waiting_tasks")
        total_finished_tasks += safe_get(status, "num_finished_tasks")
    total_tasks = total_running_tasks + total_waiting_tasks + total_finished_tasks
    avg_cpu = (
        (total_cpu_usage / num_workers_for_avg) if num_workers_for_avg > 0 else 0.0
    )
    avg_memory = (
        (total_memory_usage / num_workers_for_avg) if num_workers_for_avg > 0 else 0.0
    )

    # --- Build Table Rows ---
    table_rows = ""
    sorted_worker_ids = sorted(worker_status.keys(), key=lambda x: int(x))
    for worker_id in sorted_worker_ids:
        status = worker_status.get(worker_id, {})
        is_running = status.get("running", False)
        last_heartbeat = status.get("last_heartbeat")

        # Check if disconnected based on heartbeat
        is_disconnected = False
        if last_heartbeat is not None:
            if (current_time - last_heartbeat) > HEARTBEAT_TIMEOUT_SECONDS:
                is_disconnected = True
        elif (
            not is_running
        ):  # Consider stopped workers without heartbeat as effectively disconnected
            # Or you could treat them simply as 'Stopped' if preferred
            # is_disconnected = True
            pass

        # Determine status text and class
        if is_disconnected:
            status_text = "Disconnected"
            status_class = "status-disconnected"
            row_class = "worker-disconnected"
        elif is_running:
            status_text = "Running"
            status_class = "status-running"
            row_class = ""
        else:  # Not running and not considered disconnected (e.g., explicitly stopped)
            status_text = "Stopped"
            status_class = "status-stopped"
            row_class = "worker-stopped"

        index = status.get("index", "N/A")
        last_activity_fmt = format_timestamp(status.get("last_activity"))
        last_heartbeat_fmt = format_timestamp(last_heartbeat)  # Use the variable
        running_t = safe_get(status, "num_running_tasks")
        waiting_t = safe_get(status, "num_waiting_tasks")
        finished_t = safe_get(status, "num_finished_tasks")
        tasks_str = f"{running_t} / {waiting_t} / {finished_t}"
        avg_latency = safe_get(status, "avg_latency_ms")
        throughput = safe_get(status, "throughput_per_sec")
        cpu_usage = safe_get(status, "cpu_usage_percent")
        mem_usage = safe_get(status, "memory_usage_mb")
        error_rate = safe_get(status, "error_rate")
        cpu_bar_width = calculate_bar_width(cpu_usage, 100)
        mem_bar_width = calculate_bar_width(mem_usage, MAX_EXPECTED_MEMORY_MB)
        error_bar_width = calculate_bar_width(error_rate, MAX_EXPECTED_ERROR_RATE)

        # Apply faded style if disconnected
        style_override = "opacity: 0.6;" if is_disconnected else ""

        table_rows += f"""
        <tr class="{row_class}" style="{style_override}">
            <td>{index}</td>
            <td class="{status_class}"><span class="status-indicator"></span>{status_text}</td>
            <td>{tasks_str}</td>
            <td>{avg_latency:.2f} ms</td>
            <td>{throughput:.6f}</td>
            <td>
                <div>{cpu_usage:.1f}%</div>
                <div class="metric-bar cpu-bar">
                    <div class="metric-fill" style="width: {cpu_bar_width:.1f}%"></div>
                </div>
            </td>
            <td>
                <div>{mem_usage:.1f} MB</div>
                <div class="metric-bar memory-bar">
                    <div class="metric-fill" style="width: {mem_bar_width:.1f}%"></div>
                </div>
            </td>
            <td>
                <div>{error_rate:.2%}</div>
                <div class="metric-bar error-bar">
                    <div class="metric-fill" style="width: {error_bar_width:.1f}%"></div>
                </div>
            </td>
            <td>{last_activity_fmt}</td>
            <td>{last_heartbeat_fmt}</td>
        </tr>
        """

    # --- Create Full HTML Structure ---
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="5">
        <title>Worker Status Dashboard</title>
        {'''
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        '''}
        <style>
            /* --- CSS BLOCK STARTS (with escaped {{ and }}) --- */
            :root {{
                --primary-color: #4361ee;
                --success-color: #2ecc71;
                --danger-color: #e74c3c;
                --warning-color: #f39c12;
                --purple-color: #9b59b6;
                --text-primary: #2d3748;
                --text-secondary: #4a5568;
                --text-muted: #718096;
                --bg-light: #f7fafc;
                --bg-white: #ffffff;
                --border-color: #e2e8f0;
                --shadow-sm: 0 1px 3px rgba(0,0,0,0.05);
                --shadow-md: 0 4px 6px rgba(0,0,0,0.05);
                --radius-sm: 4px;
                --radius-md: 8px;
                --disconnected-color: #a0aec0; /* Added grey for disconnected */
            }}

            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; /* Updated Font Family */
                background-color: var(--bg-light);
                color: var(--text-primary);
                line-height: 1.5;
                font-size: 14px;
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
            }}

            .dashboard-container {{
                max-width: 1600px;
                margin: 24px auto;
                padding: 0 24px;
            }}

            .dashboard-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 24px;
                padding-bottom: 16px;
                border-bottom: 1px solid var(--border-color);
            }}

            h1 {{
                color: var(--primary-color);
                font-size: 28px;
                font-weight: 700;
                letter-spacing: -0.5px;
            }}

            .refresh-info {{
                font-size: 13px;
                color: var(--text-muted);
                background-color: var(--bg-white);
                padding: 6px 12px;
                border-radius: var(--radius-sm);
                border: 1px solid var(--border-color);
                font-weight: 500;
            }}

            .summary-stats {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 16px;
                margin-bottom: 28px;
            }}

            .stat-card {{
                background-color: var(--bg-white);
                border-radius: var(--radius-md);
                padding: 20px;
                box-shadow: var(--shadow-sm);
                border: 1px solid var(--border-color);
                transition: transform 0.2s, box-shadow 0.2s;
            }}

            .stat-card:hover {{
                transform: translateY(-2px);
                box-shadow: var(--shadow-md);
            }}
            
            /* --- Add new stat card for disconnected workers --- */
            .stat-card.disconnected {{
                 border-left: 4px solid var(--disconnected-color); /* Add visual cue */
            }}

            .stat-title {{
                font-size: 12px;
                color: var(--text-muted);
                margin-bottom: 8px;
                text-transform: uppercase;
                letter-spacing: 0.7px;
                font-weight: 600;
            }}

            .stat-value {{
                font-size: 24px;
                font-weight: 700;
                color: var(--text-primary);
                line-height: 1.2;
            }}

            .table-container {{
                overflow-x: auto;
                background-color: var(--bg-white);
                border-radius: var(--radius-md);
                box-shadow: var(--shadow-sm);
                border: 1px solid var(--border-color);
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
            }}

            th, td {{
                padding: 14px 16px;
                text-align: left;
                vertical-align: middle;
                white-space: nowrap;
            }}

            th {{
                background-color: var(--primary-color);
                color: white;
                font-weight: 600;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.7px;
                position: sticky;
                top: 0;
                z-index: 10;
            }}

            .table-container th:first-child {{
                border-top-left-radius: var(--radius-sm);
            }}

            .table-container th:last-child {{
                border-top-right-radius: var(--radius-sm);
            }}

            tbody tr {{
                border-bottom: 1px solid var(--border-color);
                transition: background-color 0.15s;
            }}

            tbody tr:last-child {{
                border-bottom: none;
            }}

            tbody tr:nth-child(even) {{
                background-color: rgba(247, 250, 252, 0.5);
            }}

            tbody tr:hover {{
                background-color: rgba(237, 242, 247, 0.7);
            }}

            td {{
                font-size: 13px;
                color: var(--text-secondary);
            }}

            .status-indicator {{
                display: inline-block;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                margin-right: 8px;
                vertical-align: middle;
                box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.8);
            }}

            .status-running {{
                color: var(--success-color);
                font-weight: 600;
            }}

            .status-running .status-indicator {{
                background-color: var(--success-color);
                box-shadow: 0 0 0 2px rgba(46, 204, 113, 0.2);
            }}

            .status-stopped {{
                color: var(--danger-color);
                font-weight: 600;
            }}

            .status-stopped .status-indicator {{
                background-color: var(--danger-color);
                box-shadow: 0 0 0 2px rgba(231, 76, 60, 0.2);
            }}
            
            /* --- Add Styles for Disconnected Status --- */
            .status-disconnected {{
                color: var(--disconnected-color);
                font-weight: 600;
            }}
            .status-disconnected .status-indicator {{
                background-color: var(--disconnected-color);
                box-shadow: 0 0 0 2px rgba(160, 174, 192, 0.2); /* Grey shadow */
            }}
            .worker-disconnected td {{
                color: var(--text-muted);
                opacity: 0.7; /* Slightly fade disconnected rows */
            }}
            .worker-disconnected .status-disconnected {{
                color: var(--disconnected-color);
                opacity: 1; /* Keep status text fully visible */
            }}
            .worker-disconnected:nth-child(even) {{
                background-color: rgba(237, 242, 247, 0.4); /* Slightly different even bg */
            }}
            .worker-disconnected:hover {{
                background-color: rgba(226, 232, 240, 0.6); /* Slightly different hover */
            }}

            .worker-stopped td {{
                color: var(--text-muted);
            }}

            .worker-stopped .status-stopped {{
                color: var(--danger-color);
            }}

            .worker-stopped:nth-child(even) {{
                background-color: rgba(253, 245, 246, 0.5);
            }}

            .worker-stopped:hover {{
                background-color: rgba(252, 235, 235, 0.7);
            }}

            td div:first-child {{
                font-size: 13px;
                margin-bottom: 4px;
                font-weight: 500;
            }}

            .metric-bar {{
                height: 6px;
                background-color: #edf2f7;
                border-radius: 3px;
                overflow: hidden;
                min-width: 80px;
            }}

            .metric-fill {{
                height: 100%;
                transition: width 0.3s ease-in-out;
            }}

            .cpu-bar .metric-fill {{
                background-color: var(--warning-color);
            }}

            .memory-bar .metric-fill {{
                background-color: var(--purple-color);
            }}

            .error-bar .metric-fill {{
                background-color: var(--danger-color);
            }}

            .footer {{
                margin-top: 28px;
                padding-top: 16px;
                border-top: 1px solid var(--border-color);
                font-size: 13px;
                color: var(--text-muted);
                text-align: center;
            }}

            /* Responsive adjustments */
            @media (max-width: 768px) {{
                .dashboard-container {{
                    padding: 0 16px;
                    margin: 16px auto;
                }}

                h1 {{
                    font-size: 22px;
                }}

                .stat-value {{
                    font-size: 20px;
                }}

                .summary-stats {{
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                }}
            }}
            /* --- CSS BLOCK ENDS --- */
        </style>
    </head>
    <body>
        <div class="dashboard-container">
            <div class="dashboard-header">
                <h1>Worker Status Dashboard</h1>
                <div class="refresh-info">Auto-refreshes every 5 seconds</div>
            </div>

            <div class="summary-stats">
                <div class="stat-card">
                    <div class="stat-title">Active Workers</div>
                    <div class="stat-value">{active_workers}</div>
                </div>
                <div class="stat-card disconnected">
                    <div class="stat-title">Disconnected Workers</div>
                    <div class="stat-value">{disconnected_workers}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Total Tasks (R/W/F)</div>
                    <div class="stat-value">{total_running_tasks} / {total_waiting_tasks} / {total_finished_tasks}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Avg CPU (Active)</div>
                    <div class="stat-value">{avg_cpu:.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Avg Memory (Active)</div>
                    <div class="stat-value">{avg_memory:.1f} MB</div>
                </div>
            </div>

            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Index</th>
                            <th>Status</th>
                            <th>Tasks (R/W/F)</th>
                            <th>Avg Latency</th>
                            <th>Throughput</th>
                            <th>CPU Usage</th>
                            <th>Memory</th>
                            <th>Error Rate</th>
                            <th>Last Activity</th>
                            <th>Last Heartbeat</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows}
                    </tbody>
                </table>
            </div>

            <div class="footer">
                Last updated: {current_time_str}
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=html)


if __name__ == "__main__":
    # Run the server
    uvicorn.run("status_monitor:app", host="0.0.0.0", port=8000, log_level="info")
