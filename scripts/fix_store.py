import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import prisma
from app.core.crypto import encrypt_token

async def fix_store():
    await prisma.connect()
    
    store = await prisma.store.find_first()
    if store:
        # 1. Provide the CORRECT FULL DOMAIN
        correct_domain = "mobile-development-store.myshopify.com"
        
        # 2. Provide the CORRECT ADMIN TOKEN (starts with shpat_)
        correct_admin_token = "INSERT_VALID_ADMIN_TOKEN_HERE"
        
        # 3. Provide the CORRECT STOREFRONT TOKEN
        correct_storefront_token = "INSERT_VALID_STOREFRONT_TOKEN_HERE"
        
        print(f"Updating Store: {store.id}")
        await prisma.store.update(
            where={"id": store.id},
            data={
                "shopify_domain": correct_domain,
                "shopify_admin_token": encrypt_token(correct_admin_token) if correct_admin_token != "INSERT_VALID_ADMIN_TOKEN_HERE" else store.shopify_admin_token,
                "shopify_storefront_token": encrypt_token(correct_storefront_token) if correct_storefront_token != "INSERT_VALID_STOREFRONT_TOKEN_HERE" else store.shopify_storefront_token
            }
        )
        print("Done!")
    else:
        print("No stores found in DB to fix.")
        
    await prisma.disconnect()

asyncio.run(fix_store())
