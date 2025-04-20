
import os
import sys

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.deepgram import DeepgramSTTService

from pipecat.transports.base_transport import TransportParams
from pipecat.services.groq import GroqLLMService
from pipecat.services.elevenlabs import ElevenLabsTTSService
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport

from mongodb_handler import mongodb_handler

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


SYSTEM_INSTRUCTION = f"""
"You are Gemini Chatbot, a friendly, helpful robot.

Your goal is to demonstrate your capabilities in a succinct way.

Your output will be converted to audio so don't include special characters in your answers.

Respond to what the user said in a creative and helpful way. Keep your responses brief. One or two sentences at most.
"""


async def run_bot(webrtc_connection):
    pipecat_transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
            audio_out_10ms_chunks=2,
        ),
    )

    llm = GroqLLMService(
        api_key=os.getenv("GROQ_API_KEY"),
        model="meta-llama/llama-4-scout-17b-16e-instruct"
    )
    
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY")
    )
    
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id="gs0tAILXbY5DNrJrsM6F",
        output_format="pcm_24000",
        model="eleven_flash_v2_5",
        params=ElevenLabsTTSService.InputParams(
            auto_mode=True,
            optimize_streaming_latency="4"
        )
    )

    context = OpenAILLMContext(
        [
            {
                "role": "system",
                "content": "You are a helpful LLM in a WebRTC call. Your goal is to demonstrate your capabilities in a succinct way. Your output will be converted to audio so don't include special characters in your answers. Respond to what the user said in a creative and helpful way.",
            },
        ],
    )

    
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            pipecat_transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            pipecat_transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
        ),
    )

    @pipecat_transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat Client connected")
        # Kick off the conversation.
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @pipecat_transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat Client disconnected")
        # Save messages when client disconnects
        session_id = webrtc_connection.pc_id
        messages = context.get_messages()
        # Save to MongoDB using the stored user_id and chat_id
        mongodb_handler.save_chat(
            user_id=webrtc_connection.user_id,
            chat_id=webrtc_connection.chat_id,
            messages=messages
        )
        logger.info(f"Saved messages for session {session_id}")

    @pipecat_transport.event_handler("on_client_closed")
    async def on_client_closed(transport, client):
        logger.info("Pipecat Client closed")
        # Save messages when client closes
        session_id = webrtc_connection.pc_id
        messages = context.get_messages()
        # Save to MongoDB using the stored user_id and chat_id
        mongodb_handler.save_chat(
            user_id=webrtc_connection.user_id,
            chat_id=webrtc_connection.chat_id,
            messages=messages
        )
        logger.info(f"Saved messages for session {session_id}")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)