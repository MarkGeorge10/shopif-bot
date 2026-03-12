import asyncio
import os
import json
from dotenv import load_dotenv
from app.services.shopify.connection import get_shop_connection_by_slug
from app.services.search.unified import unified_search
from app.core.database import prisma

load_dotenv()

async def debug_search():
    await prisma.connect()
    slug = "mobile-development-store-bf16b6"
    store = await prisma.store.find_unique(where={"slug": slug})
    if not store:
        print("Store not found")
        return

    client = await get_shop_connection_by_slug(slug)

    query = "NIKE | SWOOSH PRO FLAT PEAK CAP"
    print(f"Searching for: {query}")
    results = await unified_search(
        store_id=store.id,
        client=client,
        query=query
    )
    
    print(f"Found {len(results)} products:")
    for p in results:
        print(f"- {p.get('title')} (ID: {p.get('id')})")
        variants = p.get('variants', [])
        print(f"  Variants: {len(variants)}")
        for v in variants:
            print(f"    - {v.get('title')} (ID: {v.get('id')})")

    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(debug_search())
