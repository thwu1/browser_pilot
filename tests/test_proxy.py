import asyncio
import json
import logging

import aiohttp
import websockets
from aiohttp import web

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Echo server port - changed to avoid conflict
ECHO_SERVER_PORT = 9999


# Simple echo server using aiohttp
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info("Echo server: Client connected")

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            logger.info(f"Echo server received: {msg.data}")
            await ws.send_str(f"Echo: {msg.data}")
        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f"Echo server connection error: {ws.exception()}")

    logger.info("Echo server: Client disconnected")
    return ws


async def start_echo_server():
    """Start the echo server using aiohttp"""
    app = web.Application()
    app.router.add_get("/", websocket_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", ECHO_SERVER_PORT)
    await site.start()
    logger.info(f"Echo server started on http://localhost:{ECHO_SERVER_PORT}")

    return runner


async def test_proxy_connection():
    """Test the WebSocket proxy connection using aiohttp"""
    session = None
    try:
        # Create WebSocket client session
        session = aiohttp.ClientSession()

        # Connect to proxy server
        async with session.ws_connect("ws://localhost:8000/") as ws:
            # Send test message
            test_message = "Hello, WebSocket!"
            logger.info(f"Test client sending: {test_message}")
            await ws.send_str(test_message)

            # Receive response
            resp = await ws.receive()
            if resp.type == aiohttp.WSMsgType.TEXT:
                response = resp.data
                logger.info(f"Test client received: {response}")

                assert response == f"Echo: {test_message}"
                logger.info("✅ Test passed!")
                return True
            else:
                logger.error(f"❌ Unexpected message type: {resp.type}")
                return False

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise
    finally:
        # Ensure the session is properly closed
        if session:
            await session.close()
            # Force the event loop to process the session cleanup
            await asyncio.sleep(0.1)


async def start_proxy_server():
    """Start proxy server as a separate process"""
    import subprocess
    import sys

    # Start the proxy with our echo server as the target
    target_endpoints = [f"ws://localhost:{ECHO_SERVER_PORT}"]

    cmd = [
        sys.executable,
        "-c",
        f"""
import sys
sys.path.append('.')
from src.proxy import create_app
import uvicorn

target_endpoints = {target_endpoints}
app = create_app(target_endpoints)
uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
           """,
    ]

    process = subprocess.Popen(cmd)
    logger.info("Started proxy server on ws://localhost:8000")

    # Return process object for cleanup
    return process


async def main():
    # Start echo server
    echo_server = await start_echo_server()

    # Start proxy server
    proxy_process = await start_proxy_server()

    # Wait for servers to start
    await asyncio.sleep(2)

    try:
        # Run test
        success = await test_proxy_connection()
        if success:
            exit_code = 0
        else:
            exit_code = 1
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        exit_code = 1
    finally:
        # Cleanup
        await echo_server.cleanup()
        proxy_process.terminate()
        proxy_process.wait()

    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
