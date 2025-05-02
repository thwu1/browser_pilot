import os

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from monitoring.store import CentralMonitorStore

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="src/monitoring/static"), name="static")

# Create monitor store instance
monitor_store = CentralMonitorStore()


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the monitoring dashboard HTML"""
    with open("src/monitoring/static/dashboard.html", "r") as f:
        return f.read()


@app.get("/status")
async def get_status():
    """Get the current status of all workers"""
    try:
        websocket_status, task_status = await monitor_store.get_aggregated_status()
        return JSONResponse(
            {"websocket_status": websocket_status, "task_tracker_status": task_status}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when shutting down"""
    await monitor_store.close()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
