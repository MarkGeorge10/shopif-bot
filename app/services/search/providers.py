from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import io
import logging
import time

from app.services.shopify.client import ShopifyGraphQLClient
from app.services.vector_db.pinecone_client import pinecone_client
from app.services.vector_db.embedding import embedding_service
from app.services.rag.mapping import build_pinecone_metadata_filters

logger = logging.getLogger(__name__)


async def _log_search_event(
    store_id: str,
    query: Optional[str],
    has_image: bool,
    provider: str,
    results_count: int,
    latency_ms: int,
    pinecone_scores: List[float] = None,
    fallback_used: bool = False,
    session_id: Optional[str] = None,
):
    """Fire-and-forget: write a SearchLog row. Never raises."""
    try:
        from app.core.database import prisma
        await prisma.searchlog.create(data={
            "storeId": store_id,
            "sessionId": session_id,
            "query": query,
            "hasImage": has_image,
            "provider": provider,
            "resultsCount": results_count,
            "pineconeScores": pinecone_scores or [],
            "fallbackUsed": fallback_used,
            "latencyMs": latency_ms,
        })
    except Exception as e:
        logger.warning(f"Failed to write SearchLog: {e}")

class SearchProvider(ABC):
    @abstractmethod
    async def search(self, store_id: str, client: ShopifyGraphQLClient, query: str = None, image_bytes: bytes = None, constraints: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        pass

class ShopifyNativeSearchProvider(SearchProvider):
    async def search(self, store_id: str, client: ShopifyGraphQLClient, query: str = None, image_bytes: bytes = None, constraints: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        from app.services.ai.tools_shopify import _PRODUCT_FIELDS, _parse_products
        
        t0 = time.monotonic()
        safe_query = query or ""
        
        gql = f"""
        query searchProducts($query: String!, $first: Int!) {{
          products(first: $first, query: $query) {{
            edges {{
              node {{
                {_PRODUCT_FIELDS}
              }}
            }}
          }}
        }}
        """
        data = await client.execute_storefront(
            gql, {"query": f"{safe_query} available_for_sale:true", "first": 12}
        )
        products_data = data.get("products", {})
        products = _parse_products(products_data.get("edges", []))
        
        latency_ms = int((time.monotonic() - t0) * 1000)
        await _log_search_event(
            store_id=store_id,
            query=query,
            has_image=bool(image_bytes),
            provider="shopify_native",
            results_count=len(products),
            latency_ms=latency_ms,
        )
        return products

class PineconeSearchProvider(SearchProvider):
    async def search(self, store_id: str, client: ShopifyGraphQLClient, query: str = None, image_bytes: bytes = None, constraints: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        from app.services.ai.tools_shopify import _PRODUCT_FIELDS, _parse_products
        
        t0 = time.monotonic()
        
        if not pinecone_client.index:
            return []
            
        if not query and not image_bytes:
            logger.warning("PineconeSearchProvider called with neither query nor image.")
            return []
            
        namespace = pinecone_client.get_store_namespace(store_id)
        
        # 1. Embed Query
        query_vec = None
        if query and image_bytes:
            from PIL import Image
            try:
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                img_emb = embedding_service.embed_image(img)
                txt_emb = embedding_service.embed_text(query)
                query_vec = embedding_service.combine_vectors(img_emb, txt_emb, w_img=0.7, w_txt=0.3)
            except Exception as e:
                logger.error(f"Failed to process combined multimodal embedding: {e}")
                query_vec = embedding_service.embed_text(query)
                
        elif image_bytes:
            from PIL import Image
            try:
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                query_vec = embedding_service.embed_image(img)
            except Exception as e:
                logger.error(f"Failed to process image embedding: {e}")
                return []
        
        elif query:
            query_vec = embedding_service.embed_text(query)
        
        if not query_vec:
            return []

        # 2. Build metadata filters
        filters = build_pinecone_metadata_filters(constraints)
        
        # 3. Query Pinecone
        res = pinecone_client.index.query(
            namespace=namespace,
            vector=query_vec,
            filter=filters,
            top_k=12
        )
        
        # Extract scores for logging
        matches = res.get("matches", [])
        scores = [float(m.get("score", 0)) for m in matches]
        
        # 4. Clean Suffixes (e.g. `gid://shopify/Product/123#image` -> `gid://shopify/Product/123`)
        matched_ids = []
        for match in matches:
            raw_id = match["id"]
            clean_id = raw_id.split("#")[0]
            if clean_id not in matched_ids:
                matched_ids.append(clean_id)
                
        if not matched_ids:
            latency_ms = int((time.monotonic() - t0) * 1000)
            await _log_search_event(
                store_id=store_id, query=query, has_image=bool(image_bytes),
                provider="pinecone", results_count=0, latency_ms=latency_ms,
                pinecone_scores=scores,
            )
            return []
            
        # 5. Batch fetch real-time data from Shopify Storefront API using `nodes`
        gql = f"""
        query getBatchProducts($ids: [ID!]!) {{
          nodes(ids: $ids) {{
            ... on Product {{
              {_PRODUCT_FIELDS}
            }}
          }}
        }}
        """
        data = await client.execute_storefront(gql, {"ids": matched_ids})
        nodes = data.get("nodes", [])
        
        edges = [{"node": node} for node in nodes if node]
        products = _parse_products(edges)
        
        latency_ms = int((time.monotonic() - t0) * 1000)
        await _log_search_event(
            store_id=store_id,
            query=query,
            has_image=bool(image_bytes),
            provider="pinecone",
            results_count=len(products),
            latency_ms=latency_ms,
            pinecone_scores=scores[:10],  # store top 10
        )
        score_str = f"{scores[0]:.3f}" if scores else "n/a"
        logger.info(f"Pinecone search: '{query}' → {len(products)} results, top score={score_str}, latency={latency_ms}ms")
        return products
