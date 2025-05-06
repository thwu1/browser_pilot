#!/usr/bin/env python3
"""
API Server for Remote Browser Automation Service

This module implements a simple API server that interacts with the browser worker
to provide remote browser automation capabilities.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

from async_worker import AsyncBrowserWorker
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from monitor import setup_worker_monitoring
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Remote Browser Automation Service",
    description="API for controlling and observing web browsers remotely",
    version="0.1.0",
)

# Global worker instance
worker: Optional[AsyncBrowserWorker] = None
# Session storage
sessions: Dict[str, Dict[str, Any]] = {}


class SessionRequest(BaseModel):
    """Request model for creating a session"""

    user_agent: Optional[str] = None
    viewport: Optional[Dict[str, int]] = None
    persistent: bool = False


class CommandRequest(BaseModel):
    """Request model for executing a command"""

    command: str
    params: Dict[str, Any] = Field(default_factory=dict)


class ObservationRequest(BaseModel):
    """Request model for getting an observation"""

    observation_type: str
    params: Dict[str, Any] = Field(default_factory=dict)


@app.on_event("startup")
async def startup_event():
    """Initialize the worker on startup"""
    global worker
    worker = AsyncBrowserWorker()
    await worker.start()

    # Set up resource monitoring
    monitor = await setup_worker_monitoring(worker, app, interval=60)

    logger.info("API server started with browser worker and monitoring")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the worker on shutdown"""
    global worker
    if worker:
        await worker.stop()
    logger.info("API server shutting down")


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Remote Browser Automation Service API"}


@app.get("/status")
async def get_status():
    """Get the status of the worker and sessions"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    worker_status = await worker.get_status()
    return {
        "worker": worker_status,
        "sessions": {
            session_id: {
                "context_id": info["context_id"],
                "created_at": info["created_at"],
                "last_activity": info["last_activity"],
            }
            for session_id, info in sessions.items()
        },
    }


@app.post("/sessions")
async def create_session(request: SessionRequest):
    """Create a new browser session"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    # Prepare context options
    context_options = {}
    if request.user_agent:
        context_options["user_agent"] = request.user_agent
    if request.viewport:
        context_options["viewport"] = request.viewport

    try:
        # Create browser context
        context_id = await worker.create_context(context_options=context_options)

        # Create session
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            "context_id": context_id,
            "created_at": asyncio.get_event_loop().time(),
            "last_activity": asyncio.get_event_loop().time(),
            "persistent": request.persistent,
        }

        return {
            "session_id": session_id,
            "context_id": context_id,
            "message": "Session created successfully",
        }
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a browser session"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Get context ID
        context_id = sessions[session_id]["context_id"]

        # Terminate browser context
        await worker.terminate_context(context_id)

        # Remove session
        del sessions[session_id]

        return {"message": f"Session {session_id} deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/commands")
async def execute_command(session_id: str, request: CommandRequest):
    """Execute a command in a browser session"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update last activity time
    sessions[session_id]["last_activity"] = asyncio.get_event_loop().time()

    try:
        # Get context ID
        context_id = sessions[session_id]["context_id"]

        # Special handling for binary response commands
        if request.command == "browser_screenshot":
            result = await worker.execute_command(
                context_id, request.command, request.params
            )

            # Check if the result contains binary data
            if "screenshot" in result and isinstance(result["screenshot"], bytes):
                # Return as a binary response instead of JSON
                return Response(content=result["screenshot"], media_type="image/png")

            return result

        elif request.command == "browser_pdf_save":
            result = await worker.execute_command(
                context_id, request.command, request.params
            )

            # Check if the result contains PDF data
            if "pdf" in result and isinstance(result["pdf"], bytes):
                # Return as a binary response
                return Response(
                    content=result["pdf"],
                    media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=page.pdf"},
                )

            return result

        # Execute command for other commands
        result = await worker.execute_command(
            context_id, request.command, request.params
        )

        return result
    except Exception as e:
        logger.error(f"Error executing command in session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/observations")
async def get_observation(session_id: str, request: ObservationRequest):
    """Get an observation from a browser session"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update last activity time
    sessions[session_id]["last_activity"] = asyncio.get_event_loop().time()

    try:
        # Get context ID
        context_id = sessions[session_id]["context_id"]

        # Get observation
        result = await worker.get_observation(
            context_id, request.observation_type, request.params
        )

        return result
    except Exception as e:
        logger.error(f"Error getting observation from session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/hibernate")
async def hibernate_session(session_id: str, background_tasks: BackgroundTasks):
    """Hibernate a browser session"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Get context ID
        context_id = sessions[session_id]["context_id"]

        # Hibernate context
        hibernation_data = await worker.hibernate_context(context_id)

        return {
            "message": f"Session {session_id} hibernated successfully",
            "hibernation_data_size": len(json.dumps(hibernation_data)),
        }
    except Exception as e:
        logger.error(f"Error hibernating session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/reactivate")
async def reactivate_session(session_id: str):
    """Reactivate a hibernated browser session"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update last activity time
    sessions[session_id]["last_activity"] = asyncio.get_event_loop().time()

    try:
        # Get context ID
        context_id = sessions[session_id]["context_id"]

        # Reactivate context
        success = await worker.reactivate_context(context_id)

        if success:
            return {"message": f"Session {session_id} reactivated successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to reactivate session")
    except Exception as e:
        logger.error(f"Error reactivating session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get information about a browser session"""
    global worker
    if not worker:
        raise HTTPException(status_code=503, detail="Worker not initialized")

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Get context ID
        context_id = sessions[session_id]["context_id"]

        # Get worker status
        worker_status = await worker.get_status()

        # Get context status
        context_status = worker_status["contexts"].get(context_id, {"state": "unknown"})

        return {
            "session_id": session_id,
            "context_id": context_id,
            "created_at": sessions[session_id]["created_at"],
            "last_activity": sessions[session_id]["last_activity"],
            "persistent": sessions[session_id]["persistent"],
            "state": context_status.get("state", "unknown"),
        }
    except Exception as e:
        logger.error(f"Error getting session {session_id} info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
