import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.core.database import prisma
from app.services.rag.indexer import _index_store_products_async

async def main():
    await prisma.connect()
    try:
        store = await prisma.store.find_first()
        if store:
            print(f"Indexing Store: {store.id}")
            print(f"Targeting Shopify Domain: {store.shopify_domain}")
            
            # Temporary override for testing if the DB has a bad URL
            if "localhost" in store.shopify_domain or not store.shopify_domain or not "." in store.shopify_domain:
                 print("WARNING: db domain looks invalid. Ensure you have a real Shopify test store hooked up.")
                 
            try:
                await _index_store_products_async(store.id)
                print("Successfully executed indexing!")
            except Exception as e:
                print(f"Failed during indexing: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("No stores found in DB to index.")
    finally:
        await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
