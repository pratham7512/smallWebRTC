import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict

import uvicorn
from bot import run_bot
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pipecat.transports.network.webrtc_connection import SmallWebRTCConnection
from mongodb_handler import mongodb_handler

# Load environment variables
load_dotenv(override=True)

logger = logging.getLogger("pc")

app = FastAPI()

# Store connections by pc_id
pcs_map: Dict[str, SmallWebRTCConnection] = {}

class ConnectionRequest(BaseModel):
    sdp: str
    type: str
    user_id: str
    chat_id: str

@app.post("/api/offer")
async def offer(request: ConnectionRequest, background_tasks: BackgroundTasks):
    pc_id = request.chat_id  # Use chat_id as pc_id for tracking

    if pc_id and pc_id in pcs_map:
        pipecat_connection = pcs_map[pc_id]
        logger.info(f"Reusing existing connection for pc_id: {pc_id}")
        await pipecat_connection.renegotiate(sdp=request.sdp, type=request.type)
    else:
        pipecat_connection = SmallWebRTCConnection()
        await pipecat_connection.initialize(sdp=request.sdp, type=request.type)

        @pipecat_connection.event_handler("closed")
        async def handle_disconnected(webrtc_connection: SmallWebRTCConnection):
            logger.info(f"Discarding peer connection for pc_id: {webrtc_connection.pc_id}")
            pcs_map.pop(webrtc_connection.pc_id, None)

        # Store user_id and chat_id in the connection object
        pipecat_connection.user_id = request.user_id
        pipecat_connection.chat_id = request.chat_id
        
        background_tasks.add_task(run_bot, pipecat_connection)

    answer = pipecat_connection.get_answer()
    # Updating the peer connection inside the map
    pcs_map[answer["pc_id"]] = pipecat_connection

    return answer

@app.get("/")
async def index():
    return FileResponse("index.html")

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # Run app
    coros = [pc.close() for pc in pcs_map.values()]
    await asyncio.gather(*coros)
    pcs_map.clear()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC demo")
    parser.add_argument(
        "--host", default="localhost", help="Host for HTTP server (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=7860, help="Port for HTTP server (default: 7860)"
    )
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    uvicorn.run(app, host="0.0.0.0", port=args.port)
