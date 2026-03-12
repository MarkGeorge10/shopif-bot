import logging
import asyncio
from typing import List, Dict, Any, Optional
from app.services.shopify.client import ShopifyGraphQLClient
from app.services.search.providers import ShopifyNativeSearchProvider, PineconeSearchProvider
from app.core.database import prisma

logger = logging.getLogger(__name__)

async def unified_search(
    store_id: str,
    client: ShopifyGraphQLClient,
    query: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    constraints: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Orchestrate search across Native Shopify and Pinecone Vector DB.
    Merges and de-duplicates results.
    """
    constraints = constraints or {}
    
    # 1. Fetch store config
    store = await prisma.store.find_unique(where={"id": store_id})
    enhanced_enabled = store.enhanced_search_enabled if store else False
    
    tasks = []
    
    # 2. Always run Native Search if possible (unless it's an image-only search that Native can't do)
    if query or not image_bytes:
        native_provider = ShopifyNativeSearchProvider()
        tasks.append(native_provider.search(
            store_id=store_id,
            client=client,
            query=query,
            constraints=constraints
        ))
    else:
        # Placeholder for native when it can't run
        async def empty_search(): return []
        tasks.append(empty_search())

    # 3. Process Pinecone if enabled
    if enhanced_enabled:
        pinecone_provider = PineconeSearchProvider()
        tasks.append(pinecone_provider.search(
            store_id=store_id,
            client=client,
            query=query,
            image_bytes=image_bytes,
            constraints=constraints
        ))
    else:
        async def empty_search(): return []
        tasks.append(empty_search())

    # 4. Execute concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    native_products = results[0] if not isinstance(results[0], Exception) else []
    if isinstance(results[0], Exception):
        logger.error(f"Native search failed: {results[0]}")
        
    pinecone_products = results[1] if len(results) > 1 and not isinstance(results[1], Exception) else []
    if len(results) > 1 and isinstance(results[1], Exception):
        logger.error(f"Pinecone search failed: {results[1]}")

    # 5. Merge and De-duplicate
    # We prioritize Pinecone results for relevance if they exist
    merged = []
    seen_ids = set()
    
    # Add Pinecone results first
    for p in pinecone_products:
        pid = p.get("id")
        if pid and pid not in seen_ids:
            merged.append(p)
            seen_ids.add(pid)
            
    # Add Native results
    for p in native_products:
        pid = p.get("id")
        if pid and pid not in seen_ids:
            merged.append(p)
            seen_ids.add(pid)
            
    logger.info(f"Unified search: native={len(native_products)}, pinecone={len(pinecone_products)} -> total={len(merged)}")
    return merged
