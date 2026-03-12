import asyncio
import os
import json
from dotenv import load_dotenv
from app.services.shopify.connection import get_shop_connection_by_slug
from app.services.ai.tools_shopify import tool_manage_cart
from app.core.database import prisma

load_dotenv()

async def debug_cart():
    await prisma.connect()
    slug = "mobile-development-store-bf16b6"
    client = await get_shop_connection_by_slug(slug)

    # Variant ID from previous search
    variant_id = "gid://shopify/ProductVariant/48194801172726"
    
    print(f"Testing tool_manage_cart(action='create', variant_id='{variant_id}')")
    result = await tool_manage_cart(
        client=client,
        action="create",
        variant_id=variant_id,
        quantity=1
    )
    print("Result:")
    print(json.dumps(result, indent=2))

    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(debug_cart())
