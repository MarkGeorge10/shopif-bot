"""
Tool Registry — Gemini function declarations and dispatch.

This module defines all tool declarations that Gemini can call, and provides
a dispatch function that routes tool calls to their implementations.

Tool declarations are ported directly from the frontend's lib/shopify.ts.
"""
import logging
from typing import Any

from google.genai.types import Type

from app.services.shopify.client import ShopifyGraphQLClient

logger = logging.getLogger("ai.tool_registry")


# ── Tool Declarations (for Gemini) ────────────────────────────────────────────
# Ported from frontend lib/shopify.ts — same names and schemas.

SEARCH_PRODUCTS = {
    "name": "search_products",
    "description": (
        "Search the Shopify catalog for products using keywords and filters. "
        'Use this for general discovery like "Find red running shoes under $120".'
    ),
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "query": {
                "type": Type.STRING,
                "description": 'Keywords to search for (e.g., "waterproof boots").',
            },
        },
        "required": ["query"],
    },
}

GET_PRODUCT_DETAILS = {
    "name": "get_product_details",
    "description": (
        "Retrieve full details for a specific product, including all variants, "
        "availability, and description."
    ),
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "product_id": {
                "type": Type.STRING,
                "description": 'The Shopify Global ID of the product.',
            },
            "handle": {
                "type": Type.STRING,
                "description": 'The URL-friendly handle of the product.',
            },
        },
        "required": [],
    },
}

GET_POLICY = {
    "name": "get_policy",
    "description": "Get store policies such as shipping, returns, and terms of service.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "type": {
                "type": Type.STRING,
                "enum": ["privacyPolicy", "refundPolicy", "shippingPolicy", "termsOfService"],
                "description": "The type of policy to retrieve.",
            },
        },
        "required": ["type"],
    },
}

GET_COLLECTIONS = {
    "name": "get_collections",
    "description": "List product collections available in the store.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {},
    },
}

GET_PRODUCTS_IN_COLLECTION = {
    "name": "get_products_in_collection",
    "description": "Fetch products belonging to a specific collection.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "collection_id": {
                "type": Type.STRING,
                "description": "The Shopify Global ID of the collection.",
            },
        },
        "required": ["collection_id"],
    },
}

MANAGE_CART = {
    "name": "manage_cart",
    "description": "Create or update a shopping cart.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "action": {
                "type": Type.STRING,
                "enum": ["create", "add_lines", "remove_lines", "get"],
                "description": "The action to perform on the cart.",
            },
            "cart_id": {
                "type": Type.STRING,
                "description": "The existing cart ID (if applicable).",
            },
            "variant_id": {
                "type": Type.STRING,
                "description": "The variant ID to add/remove.",
            },
            "quantity": {
                "type": Type.NUMBER,
                "description": "Quantity of the variant.",
            },
        },
        "required": ["action"],
    },
}

CREATE_CHECKOUT = {
    "name": "create_checkout",
    "description": "Generate a direct checkout URL for a specific product variant.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "variant_id": {
                "type": Type.STRING,
                "description": "The Shopify Global ID of the ProductVariant.",
            },
            "quantity": {
                "type": Type.NUMBER,
                "description": "The quantity to purchase.",
            },
        },
        "required": ["variant_id", "quantity"],
    },
}

GET_MENU = {
    "name": "get_menu",
    "description": "Fetch the navigation menu structure of the store.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "handle": {
                "type": Type.STRING,
                "description": 'The menu handle (e.g., "main-menu").',
            },
        },
        "required": ["handle"],
    },
}

GET_ORDER_STATUS = {
    "name": "get_order_status",
    "description": "Retrieve tracking and fulfillment status for a specific order.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "order_number": {
                "type": Type.STRING,
                "description": 'The order number (e.g., "#1001").',
            },
            "email": {
                "type": Type.STRING,
                "description": "The email address used for the purchase.",
            },
        },
        "required": ["order_number", "email"],
    },
}

GET_INVENTORY = {
    "name": "get_inventory",
    "description": "Check physical stock levels for a product variant.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "variant_id": {
                "type": Type.STRING,
                "description": "The variant ID to check.",
            },
        },
        "required": ["variant_id"],
    },
}

GET_CUSTOMER_HISTORY = {
    "name": "get_customer_history",
    "description": "Retrieve the customer's purchase history to provide personalized recommendations.",
    "parameters": {
        "type": Type.OBJECT,
        "properties": {
            "email": {
                "type": Type.STRING,
                "description": "The customer's email address.",
            },
        },
        "required": ["email"],
    },
}


# ── All declarations as a list ────────────────────────────────────────────────

ALL_TOOL_DECLARATIONS = [
    SEARCH_PRODUCTS,
    GET_PRODUCT_DETAILS,
    GET_POLICY,
    GET_COLLECTIONS,
    GET_PRODUCTS_IN_COLLECTION,
    MANAGE_CART,
    CREATE_CHECKOUT,
    GET_MENU,
    GET_ORDER_STATUS,
    GET_INVENTORY,
    GET_CUSTOMER_HISTORY,
]


def get_tool_declarations() -> list[dict]:
    """Return all tool declarations for Gemini function calling."""
    return ALL_TOOL_DECLARATIONS


# ── Dispatch ──────────────────────────────────────────────────────────────────

async def dispatch_tool_call(
    tool_name: str,
    args: dict[str, Any],
    client: ShopifyGraphQLClient,
    cart_id: str | None = None,
) -> dict[str, Any]:
    """
    Route a Gemini tool call to the correct Shopify tool implementation.

    Args:
        tool_name: The function name from Gemini's response
        args: The arguments dict from Gemini
        client: A tenant-authenticated ShopifyGraphQLClient
        cart_id: Current session cart ID (for cart operations)

    Returns:
        A dict to send back to Gemini as the function response.
    """
    from app.services.ai.tools_shopify import (
        tool_search_products,
        tool_get_product_details,
        tool_get_policy,
        tool_get_collections,
        tool_get_products_in_collection,
        tool_manage_cart,
        tool_create_checkout,
        tool_get_menu,
        tool_get_order_status,
        tool_get_inventory,
        tool_get_customer_history,
    )

    handlers = {
        "search_products": tool_search_products,
        "get_product_details": tool_get_product_details,
        "get_policy": tool_get_policy,
        "get_collections": tool_get_collections,
        "get_products_in_collection": tool_get_products_in_collection,
        "manage_cart": tool_manage_cart,
        "create_checkout": tool_create_checkout,
        "get_menu": tool_get_menu,
        "get_order_status": tool_get_order_status,
        "get_inventory": tool_get_inventory,
        "get_customer_history": tool_get_customer_history,
    }

    handler = handlers.get(tool_name)
    if not handler:
        logger.warning(f"Unknown tool call: {tool_name}")
        return {"error": f"Unknown tool: {tool_name}"}

    logger.info(
        "tool_call_dispatch",
        extra={"tool": tool_name, "shop": client.shop_domain},
    )

    try:
        # Pop cart_id from args to avoid duplicate keyword — Gemini sometimes
        # provides it in args AND we pass it explicitly as the session cart.
        # The AI-provided value takes precedence; fall back to the session value.
        ai_cart_id = args.pop("cart_id", None)
        effective_cart_id = ai_cart_id or cart_id

        # Normalize variant_id / merchandiseId — Gemini may send a bare numeric
        # ID instead of the full Shopify GID. Fix it so the Storefront API accepts it.
        for key in ("variant_id", "merchandiseId"):
            raw = args.get(key)
            if raw and isinstance(raw, str) and not raw.startswith("gid://"):
                args[key] = f"gid://shopify/ProductVariant/{raw}"

        result = await handler(client=client, cart_id=effective_cart_id, **args)
        return result
    except Exception as e:
        logger.error(
            "tool_call_error",
            extra={"tool": tool_name, "error": str(e)},
            exc_info=True,
        )
        return {"error": f"Tool {tool_name} failed: {str(e)}"}
