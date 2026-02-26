import sys
import os
import asyncio
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), '..', '.env'))

from app.core.database import prisma
from app.api.endpoints.public import public_search_products


async def fetch_all_products():
    all_products = []
    has_next_page = True
    cursor = None
    
    while has_next_page:
        res = await public_search_products(slug="mobile-development-store-bf16b6", q="", after=cursor)
        
        for p in res.products:
            # We convert Pydantic models back to simple dicts for easy pandas processing
            all_products.append(p.model_dump())
            
        has_next_page = res.page_info.has_next_page
        cursor = res.page_info.end_cursor
        
        print(f"Fetched {len(all_products)} products so far...")
            
    return all_products

def prepare_product_documents(products):
    docs = []
    for p in products:
        p_id = p.get("id", "").split("/")[-1]
        
        title = p.get("title", "")
        desc = p.get("description", "")
        
        # Public schema variants
        variants = p.get("variants", [])
        price = variants[0].get("price", "0") if variants else "0"
        
        # Text block to be embedded by the AI model
        embedding_text = f"Product: {title}.\nDescription: {desc}"
        
        docs.append({
            "id": p_id,
            "title": title,
            "embedding_text": embedding_text.strip(),
            "image_url": p.get("image_url"),
            "metadata": {
                "price": price
            }
        })
    return pd.DataFrame(docs)

async def main():
    await prisma.connect()
    try:
        print("Fetching products directly from internal backend logic...")
        products = await fetch_all_products()
        print(f"Total Products Fetched: {len(products)}")
        
        df_products = prepare_product_documents(products)
        df_products.to_csv("shopify_products_prep.csv", index=False)
        print("Saved prepared products to shopify_products_prep.csv")
    finally:
        await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
