import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import prisma

async def check():
    await prisma.connect()
    
    store = await prisma.store.find_first()
    if store:
        print("DOMAIN: ", store.shopify_domain)
        print("ADMIN: ", store.shopify_admin_token)
        print("STOREFRONT:", store.shopify_storefront_token)
    
    await prisma.disconnect()

asyncio.run(check())
