"""
Chat Orchestrator — the core AI pipeline.

Flow:
1. Load session + prior messages from DB
2. Build system prompt with shop context (domain)
3. Call Gemini with tool declarations
4. If tool calls returned → execute via registry → send results back to Gemini
5. Persist all messages (user, tool calls, assistant) to session
6. Return final reply + structured actions

Ported from the frontend's hooks/useChat.ts — now fully server-side.
"""
import json
import logging
import base64

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings
from app.core.database import prisma
from app.services.shopify.connection import get_active_shop_connection
from app.services.ai.tool_registry import get_tool_declarations, dispatch_tool_call

logger = logging.getLogger("ai.orchestrator")

# Maximum tool call loops to prevent infinite recursion
_MAX_TOOL_ROUNDS = 5


def _build_system_prompt(
    shop_domain: str,
    current_page: str | None = None,
    shopper_email: str | None = None,
    enhanced_search_enabled: bool = False,
) -> str:
    """Build the system instruction for Gemini, parameterized by shop."""
    base_prompt = (
        f"You are a helpful AI shopping concierge for the Shopify store: {shop_domain}.\n\n"
        "Use the tools provided to help the user find products, browse collections, "
        "check store policies, navigate the menu, manage their cart, and track orders.\n\n"
        "CRITICAL RULES FOR VOICE/CHAT INTERACTION:\n"
        "1. NEVER recite or display raw Shopify IDs (like gid://shopify/ProductVariant/...) to the user. These are for internal tool use ONLY.\n"
        "2. Avoid reciting full URLs or links verbally. The ONLY link you should ever provide is the checkout link when the user is ready to pay.\n"
        "3. Keep your verbal/text responses extremely concise, conversational, and friendly.\n"
        "4. When you trigger an action (like adding to cart, or searching), just confirm it briefly (e.g., \"I've added the white hoodie to your cart\" or \"Here are some white hoodies I found\"). The storefront UI will automatically update on the user's screen; you don't need to explain the UI to them.\n"
        "5. Do NOT invent products or data — always rely on tool responses.\n"
        "6. If the user asks for order status, use tool_get_order_status. If you lack their email, ask for it.\n"
        "7. If the user asks for recommendations, use tool_get_customer_history if they are logged in. Otherwise offer general top-sellers.\n"
        "8. Image search: If the user provides an image, extract 2-3 key terms and use search_products.\n"
        "9. Search fallbacks: If search_products returns 0 results, ALWAYS try 1-2 more times with different/broader keywords before giving up.\n"
        "10. NEVER reply with just punctuation or empty dashes like '--'. Always use natural spoken sentences, even if short.\n"
        "11. If a search yields 0 products after retrying, concisely and politely tell the user you couldn't find exactly what they were looking for, but you are ready to help them search for something else.\n"
    )

    if enhanced_search_enabled:
        base_prompt += (
            "\nENHANCED SEARCH IS ACTIVE: This store has a semantic product index. "
            "When calling search_products you MAY pass a structured 'constraints' object to filter results precisely. "
            "Use it whenever the user mentions any of the following:\n"
            "  • A price limit or range  → set price_min and/or price_max (numbers, no currency symbol)\n"
            "  • A brand or vendor name  → set vendor (exact name as the user said it)\n"
            "  • A product category      → set product_type\n"
            "  • In-stock / availability → set in_stock: true\n"
            "  • Tags or labels          → set tags as a comma-separated string\n"
            "Always keep the 'query' field as the natural-language keyword description; "
            "do NOT duplicate filter information inside the query string.\n"
        )

    if shopper_email:
        base_prompt += f"\nIdentity Context: The current user is logged in as \"{shopper_email}\". Use this for tool_get_order_status and tool_get_customer_history.\n"

    if current_page:
        base_prompt += (
            f"\nContext: The user is currently viewing the following page/product context: \"{current_page}\". "
            "If they say 'this product' or 'the current product', assume they mean the one on this page. "
            "You can still offer to search for other products if that is what they are looking for."
        )

    return base_prompt


async def process_chat_message(
    user_id: str,
    session_id: str | None = None,
    message: str = "",
    store_id: str | None = None,
    current_page: str | None = None,
    image_base64: str | None = None,
    shopper_email: str | None = None,
) -> dict[str, Any]:
    """
    Process a user chat message through the full AI pipeline.

    Args:
        user_id: Authenticated user ID
        session_id: Existing session ID (or None to create new)
        message: The user's message
        store_id: Optional specific store ID
        current_page: Context of the page the user is viewing

    Returns:
        {
            "session_id": str,
            "reply": str,
            "tool_calls": [{name, args, result}],
            "structured_actions": {}
        }
    """
    # ── 1. Get shop connection ──────────────────────────────────────────────
    client = await get_active_shop_connection(user_id, store_id)

    # ── 1b. Look up store settings (enhanced search flag) ──────────────────
    enhanced_search_enabled = False
    if client.store_id:
        store_record = await prisma.store.find_unique(where={"id": client.store_id})
        if store_record:
            enhanced_search_enabled = bool(store_record.enhanced_search_enabled)

    # ── 2. Load or create session ───────────────────────────────────────────
    if session_id:
        session = await prisma.chatsession.find_first(
            where={"id": session_id, "userId": user_id}
        )
        if not session:
            session = await _create_session(user_id, client.store_id)
    else:
        session = await _create_session(user_id, client.store_id)

    # Load history
    history = session.messages if isinstance(session.messages, list) else json.loads(session.messages or "[]")

    # ── 3. Initialize Gemini ────────────────────────────────────────────────
    ai_client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # Build history in Gemini format
    gemini_history = []
    for msg in history:
        if msg.get("role") in ("user", "model"):
            gemini_history.append(
                types.Content(
                    role=msg["role"],
                    parts=[types.Part.from_text(text=msg["content"])],
                )
            )

    chat = ai_client.chats.create(
        model="gemini-2.5-pro",
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(
                client.shop_domain,
                current_page,
                shopper_email,
                enhanced_search_enabled,
            ),
            tools=[types.Tool(function_declarations=get_tool_declarations())],
            temperature=0.8,
        ),
        history=gemini_history,
    )

    # ── 4. Send user message to Gemini ──────────────────────────────────────
    message_parts = []
    
    # If the user only sent an image without text, provide a default instruction
    actual_message = message if message.strip() else ""
    if not actual_message and image_base64:
        actual_message = "Identify the products in this image and search for similar items in the store."
        
    if actual_message:
        message_parts.append(types.Part.from_text(text=actual_message))
    
    if image_base64:
        try:
            # Handle data:image/...;base64, prefix
            if "," in image_base64:
                header, encoded = image_base64.split(",", 1)
                mime_type = header.split(";")[0].split(":")[1]
                image_data = base64.b64decode(encoded)
            else:
                mime_type = "image/jpeg" # fallback
                image_data = base64.b64decode(image_base64)
                
            message_parts.append(
                types.Part.from_bytes(data=image_data, mime_type=mime_type)
            )
        except Exception as e:
            logger.error(f"Failed to decode image: {e}")

    response = chat.send_message(message_parts)

    # Track all tool calls for observability
    all_tool_calls = []
    rounds = 0

    # ── 5. Tool call loop ───────────────────────────────────────────────────
    while response.function_calls and rounds < _MAX_TOOL_ROUNDS:
        rounds += 1
        response_parts = []
        
        for fn_call in response.function_calls:
            tool_name = fn_call.name
            tool_args = dict(fn_call.args) if fn_call.args else {}

            logger.info(
                "tool_call_execute",
                extra={
                    "session_id": session.id,
                    "tool": tool_name,
                    "round": rounds,
                    "shop": client.shop_domain,
                },
            )

            # Execute tool
            tool_result = await dispatch_tool_call(
                tool_name=tool_name,
                args=tool_args,
                client=client,
                cart_id=_extract_cart_id(history),
            )

            all_tool_calls.append({
                "name": tool_name,
                "args": tool_args,
                "result": tool_result,
            })

            # Append tool result to the list of parts for this round
            response_parts.append(types.Part.from_function_response(
                name=tool_name,
                response=tool_result,
            ))

        # Send all tool results back to Gemini in a single message
        if response_parts:
            response = chat.send_message(response_parts)

    # ── 6. Extract final reply ──────────────────────────────────────────────
    final_reply = response.text or "I'm sorry, I couldn't process that request."

    # ── 7. Persist to DB ────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()

    # Add user message
    history.append({"role": "user", "content": message, "timestamp": now})

    # Add tool calls if any
    for tc in all_tool_calls:
        history.append({
            "role": "tool",
            "content": json.dumps({"name": tc["name"], "args": tc["args"], "result": tc["result"]}),
            "timestamp": now,
        })

    # Add assistant reply
    history.append({"role": "model", "content": final_reply, "timestamp": now})

    # Auto-title from first user message
    title = session.title
    if (not title or title == "New Chat") and message:
        title = message[:80]

    await prisma.chatsession.update(
        where={"id": session.id},
        data={"messages": json.dumps(history), "title": title},
    )

    logger.info(
        "chat_completed",
        extra={
            "session_id": session.id,
            "tool_calls": len(all_tool_calls),
            "reply_length": len(final_reply),
        },
    )

    return {
        "session_id": session.id,
        "reply": final_reply,
        "tool_calls": all_tool_calls,
        "structured_actions": _extract_structured_actions(all_tool_calls),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_session(user_id: str, store_id: str | None) -> Any:
    """Create a new chat session in the database."""
    return await prisma.chatsession.create(
        data={
            "userId": user_id,
            "store_id": store_id,
            "title": "New Chat",
            "messages": json.dumps([]),
        }
    )


def _extract_cart_id(history: list[dict]) -> str | None:
    """Extract the most recent cart_id from tool call history."""
    for msg in reversed(history):
        if msg.get("role") == "tool":
            try:
                data = json.loads(msg["content"])
                result = data.get("result", {})
                if isinstance(result, dict):
                    cart = result.get("cart", result)
                    if isinstance(cart, dict) and "id" in cart:
                        return cart["id"]
            except (json.JSONDecodeError, KeyError):
                continue
    return None


def _extract_structured_actions(tool_calls: list[dict]) -> dict:
    """
    Extract structured UI actions from tool results.
    E.g., if search_products succeeded, return the product IDs.
    """
    actions = {}
    for tc in tool_calls:
        if tc["name"] == "search_products" and isinstance(tc["result"], dict):
            products = tc["result"].get("products", [])
            actions["suggested_product_ids"] = [p.get("id") for p in products if p.get("id")]

        if tc["name"] in ("manage_cart", "create_checkout"):
            result = tc["result"]
            if isinstance(result, dict):
                cart = result.get("cart", result)
                if isinstance(cart, dict) and cart.get("checkoutUrl"):
                    actions["checkout_url"] = cart["checkoutUrl"]
                if isinstance(cart, dict) and cart.get("id"):
                    actions["cart_id"] = cart["id"]

    return actions
