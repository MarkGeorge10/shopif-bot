"""
Gemini Multimodal Live API Service.

Relays real-time audio and messages between the client (via WebSocket)
and Gemini's Multimodal Live API. Handles asynchronous tool calling
to update the storefront in real-time.

Reference: https://ai.google.dev/gemini-api/docs/live
"""
import asyncio
import logging

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.shopify.client import ShopifyGraphQLClient
from app.services.ai.tool_registry import get_tool_declarations, dispatch_tool_call

logger = logging.getLogger(__name__)

# Model that supports the Live / bidiGenerateContent API
LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"


class MultimodalLiveManager:
    """Manages a single real-time session with Gemini Multimodal Live."""

    def __init__(self, shop_domain: str, shopper_email: str | None = None):
        self.shop_domain = shop_domain
        self.shopper_email = shopper_email
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _build_config(self, system_instruction: str) -> dict:
        """Build the LiveConnectConfig as a plain dict."""
        return {
            "response_modalities": ["AUDIO"],
            "system_instruction": system_instruction,
            "tools": [{"function_declarations": get_tool_declarations()}],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {"voice_name": "Aoede"}
                }
            },
        }

    async def stream(self, websocket, shop_client: ShopifyGraphQLClient):
        """Main relay loop between the browser WebSocket and Gemini Live API."""

        from app.services.ai.orchestrator import _build_system_prompt
        system_instruction = _build_system_prompt(
            self.shop_domain, shopper_email=self.shopper_email
        )
        config = self._build_config(system_instruction)

        logger.info(f"Starting Live session for {self.shop_domain} with model {LIVE_MODEL}")

        async with self.client.aio.live.connect(
            model=LIVE_MODEL,
            config=config,
        ) as session:

            async def send_to_gemini():
                """
                Read raw PCM bytes from the browser WebSocket and forward to Gemini.
                Also accepts JSON text messages (e.g. {"type": "text", "text": "..."}).
                """
                try:
                    while True:
                        message = await websocket.receive()

                        if message["type"] == "websocket.disconnect":
                            logger.info("Browser disconnected — stopping send")
                            break

                        if "bytes" in message and message["bytes"]:
                            # Raw PCM audio from microphone
                            await session.send_realtime_input(
                                audio={"data": message["bytes"], "mime_type": "audio/pcm"}
                            )
                        elif "text" in message and message["text"]:
                            try:
                                import json
                                data = json.loads(message["text"])
                                if data.get("type") == "text" and data.get("text"):
                                    await session.send_client_content(
                                        turns=[{"role": "user", "parts": [{"text": data["text"]}]}],
                                        turn_complete=True,
                                    )
                            except Exception:
                                pass  # Skip malformed control messages

                except Exception as e:
                    logger.error(f"[send_to_gemini] {e}")

            async def receive_from_gemini():
                """
                Read responses from Gemini across multiple turns and relay to the browser.
                Uses the while-True pattern so the session stays open after each AI turn.
                """
                try:
                    while True:
                        turn = session.receive()
                        ai_text_parts = []

                        async for response in turn:

                            # ── Tool calls ────────────────────────────────
                            if response.tool_call:
                                tool_responses = []
                                for call in response.tool_call.function_calls:
                                    logger.info(f"Live tool call: {call.name}")
                                    result = await dispatch_tool_call(
                                        tool_name=call.name,
                                        args=dict(call.args),
                                        client=shop_client,
                                    )
                                    tool_responses.append(
                                        types.FunctionResponse(
                                            id=call.id,
                                            name=call.name,
                                            response=result,
                                        )
                                    )
                                    # Push to frontend for real-time UI sync
                                    await websocket.send_json({
                                        "type": "tool_call",
                                        "name": call.name,
                                        "result": result,
                                    })

                                await session.send_tool_response(
                                    function_responses=tool_responses
                                )

                            # ── Audio from Gemini ─────────────────────────
                            if response.server_content and response.server_content.model_turn:
                                for part in response.server_content.model_turn.parts:
                                    if part.inline_data and isinstance(part.inline_data.data, bytes):
                                        await websocket.send_bytes(part.inline_data.data)
                                    if part.text:
                                        ai_text_parts.append(part.text)

                            # ── Interruption: clear queued audio ──────────
                            if (response.server_content
                                    and response.server_content.interrupted):
                                # Signal browser to stop playing audio
                                await websocket.send_json({"type": "interrupted"})
                                ai_text_parts.clear()

                        # ── Turn complete: flush any text transcript ───────
                        if ai_text_parts:
                            full_text = "".join(ai_text_parts)
                            await websocket.send_json({
                                "type": "text",
                                "text": full_text,
                            })

                        await websocket.send_json({"type": "turn_complete"})

                except Exception as e:
                    logger.error(f"[receive_from_gemini] {e}")

            # Run both directions concurrently until either side closes
            await asyncio.gather(send_to_gemini(), receive_from_gemini())
