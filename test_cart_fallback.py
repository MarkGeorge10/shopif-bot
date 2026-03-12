import asyncio
import os
import json
from dotenv import load_dotenv
from app.services.shopify.connection import get_shop_connection_by_slug
from app.services.ai.tools_shopify import tool_manage_cart
from app.core.database import prisma

load_dotenv()

async def test_fallback():
    await prisma.connect()
    slug = "mobile-development-store-bf16b6"
    client = await get_shop_connection_by_slug(slug)

    # Variant ID
    variant_id = "gid://shopify/ProductVariant/48194801172726"
    
    print("Testing tool_manage_cart(action='add_lines', cart_id=None)")
    # This should now fall back to 'create' instead of returning error
    result = await tool_manage_cart(
        client=client,
        action="add_lines",
        cart_id=None,
        variant_id=variant_id,
        quantity=1
    )
    print("Result:")
    print(json.dumps(result, indent=2))
    
    # Check if it returned a cart (meaning it succeeded)
    if "cart" in result:
        print("\nSUCCESS: Fallback to 'create' worked.")
    else:
        print("\nFAILURE: Fallback failed.")

    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(test_fallback())
