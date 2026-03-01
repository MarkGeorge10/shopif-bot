"""
RAG Indexer — orchestrates product embedding and Pinecone upserts.

Design:
- GraphQL queries live in app/services/shopify/repository.py
- Image download is async (httpx) with timeout + size guard
- Celery tasks are thin shims; actual logic is in async helpers
- On failure, Store.rag_index_status is set to "error" without crashing the API
"""
import asyncio
import io
import logging
from datetime import datetime, timezone

import httpx
from PIL import Image

from app.core.celery_app import celery_app
from app.core.database import prisma
from app.services.shopify.connection import get_shop_connection_by_slug
from app.services.shopify import repository
from app.services.vector_db.pinecone_client import pinecone_client
from app.services.vector_db.embedding import embedding_service
from app.services.rag.mapping import build_canonical_product_text

logger = logging.getLogger(__name__)

_IMAGE_TIMEOUT_SEC = 10
_IMAGE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


# ── Image utilities ───────────────────────────────────────────────────────────

async def _download_image_async(url: str) -> Image.Image | None:
    """
    Async image downloader with timeout and max-size guard.
    Only use inside Celery tasks / background jobs — never in the API request path.
    """
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT_SEC) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                # Guard against oversized images
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > _IMAGE_MAX_BYTES:
                    logger.warning(f"Image too large ({content_length} bytes), skipping: {url}")
                    return None

                chunks = []
                total = 0
                async for chunk in response.aiter_bytes(chunk_size=32768):
                    total += len(chunk)
                    if total > _IMAGE_MAX_BYTES:
                        logger.warning(f"Image exceeded size limit mid-stream, skipping: {url}")
                        return None
                    chunks.append(chunk)

        raw = b"".join(chunks)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        logger.warning(f"Failed to download image {url}: {exc}")
        return None


# ── Core indexing logic ───────────────────────────────────────────────────────

async def _index_store_products_async(store_id: str) -> None:
    store = await prisma.store.find_unique(where={"id": store_id})
    if not store:
        logger.error(f"Cannot index RAG for unknown store: {store_id}")
        return

    if not store.slug:
        logger.error(f"Store {store_id} has no slug — cannot build connection.")
        await prisma.store.update(where={"id": store_id}, data={"rag_index_status": "error"})
        return

    await prisma.store.update(where={"id": store_id}, data={"rag_index_status": "building"})

    try:
        pinecone_client.initialize()

        # ✅ Use slug-based connection — tokens are properly decrypted this way
        client = await get_shop_connection_by_slug(store.slug)

        logger.info(f"====== STARTING PINECONE RAG INDEXING FOR {store.shopify_domain} ======")
        logger.info("1/3 Fetching all active products from Shopify Storefront API...")

        # ✅ Paginate through ALL products using the Storefront API (same as working notebook)
        all_products: list[dict] = []
        cursor = None
        page_num = 0

        while True:
            page_num += 1
            raw = await repository.storefront_search_products(client, query="", first=50, after=cursor)
            edges = raw.get("edges", [])

            for edge in edges:
                node = edge.get("node", {})
                if node:
                    all_products.append(node)

            page_info = raw.get("pageInfo", {})
            logger.info(f"    -> Page {page_num}: got {len(edges)} products (total so far: {len(all_products)})")

            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        logger.info(f"    -> Pulled {len(all_products)} total products.")

        logger.info("2/3 Generating CLIP & Text Embeddings...")
        vectors: list[tuple] = []

        for p in all_products:
            p_id = p.get("id", "")
            if not p_id:
                continue

            title = p.get("title", "")
            desc = p.get("description", "")
            # Storefront API uses 'vendor' in product type nodes
            vendor = p.get("vendor", "")
            product_type = p.get("productType", "")
            tags = p.get("tags", [])

            # Storefront variant nodes have price.amount
            variant_edges = p.get("variants", {}).get("edges", [])
            price = 0.0
            in_stock = False
            if variant_edges:
                v_node = variant_edges[0].get("node", {})
                price_obj = v_node.get("price", {})
                price = float(price_obj.get("amount", 0)) if isinstance(price_obj, dict) else float(price_obj or 0)
                in_stock = v_node.get("availableForSale", False)

            image_url = None
            imgs = p.get("images", {}).get("edges", [])
            if imgs:
                image_url = imgs[0].get("node", {}).get("url")

            canonical_text = build_canonical_product_text(title, desc, vendor, product_type, tags)
            logger.info(f"    -> Embedding: {title}")
            txt_emb = embedding_service.embed_text(canonical_text)

            metadata = {
                "title": title,
                "vendor": vendor,
                "product_type": product_type,
                "price": price,
                "in_stock": in_stock,
                "tags": tags if isinstance(tags, list) else [],
                "shopify_product_id": p_id,
            }

            vectors.append((f"{p_id}#text", txt_emb, {**metadata, "modality": "text"}))

            img = await _download_image_async(image_url)
            if img:
                img_emb = embedding_service.embed_image(img)
                vectors.append((f"{p_id}#image", img_emb, {**metadata, "modality": "image"}))

        namespace = pinecone_client.get_store_namespace(store_id)
        batch_size = 50

        if pinecone_client.index:
            total_batches = max(1, (len(vectors) + batch_size - 1) // batch_size)
            logger.info(f"3/3 Pushing {len(vectors)} embeddings to Pinecone namespace '{namespace}'...")
            for i in range(0, len(vectors), batch_size):
                batch_num = (i // batch_size) + 1
                logger.info(f"    -> Upserting batch {batch_num}/{total_batches}...")
                pinecone_client.index.upsert(vectors=vectors[i : i + batch_size], namespace=namespace)
            logger.info(f"====== PINECONE RAG INDEXING COMPLETE FOR {store.shopify_domain} ======")
        else:
            logger.warning("Pinecone index not initialized. Skipping upsert.")

        await prisma.store.update(
            where={"id": store_id},
            data={"rag_index_status": "ready", "rag_last_indexed_at": datetime.now(timezone.utc)},
        )

    except Exception:
        logger.exception(f"Failed to index RAG for store {store_id}")
        await prisma.store.update(where={"id": store_id}, data={"rag_index_status": "error"})
        # Do NOT re-raise — background jobs must not crash the API


# ── Single-product webhook helpers ────────────────────────────────────────────

async def _index_single_product_sync_async(store_id: str, payload: dict) -> None:
    pinecone_client.initialize()
    if not pinecone_client.index:
        return

    p_id = payload.get("admin_graphql_api_id")
    if not p_id:
        return

    title = payload.get("title", "")
    desc = payload.get("body_html", "") or ""
    vendor = payload.get("vendor", "")
    product_type = payload.get("product_type", "")
    tags = payload.get("tags", "")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    variants = payload.get("variants", [])
    price = 0.0
    in_stock = False
    if variants:
        price = float(variants[0].get("price", 0))
        in_stock = sum(v.get("inventory_quantity", 0) for v in variants) > 0

    image_url = None
    images = payload.get("images", [])
    if images:
        image_url = images[0].get("src")

    canonical_text = build_canonical_product_text(title, desc, vendor, product_type, tags)
    txt_emb = embedding_service.embed_text(canonical_text)

    metadata = {
        "title": title,
        "vendor": vendor,
        "product_type": product_type,
        "price": price,
        "in_stock": in_stock,
        "tags": tags,
        "shopify_product_id": p_id,
    }

    namespace = pinecone_client.get_store_namespace(store_id)
    vectors: list[tuple] = [(f"{p_id}#text", txt_emb, {**metadata, "modality": "text"})]

    img = await _download_image_async(image_url)
    if img:
        img_emb = embedding_service.embed_image(img)
        vectors.append((f"{p_id}#image", img_emb, {**metadata, "modality": "image"}))

    pinecone_client.index.upsert(vectors=vectors, namespace=namespace)


# ── Celery task entrypoints ───────────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=3)
def task_index_store_products(self, store_id: str):
    """Celery entrypoint for full store text+image backfill."""

    async def _run():
        await prisma.connect()
        try:
            await _index_store_products_async(store_id)
        finally:
            await prisma.disconnect()

    asyncio.run(_run())


@celery_app.task(bind=True, max_retries=3)
def task_index_product(self, store_id: str, product_payload: dict):
    """Celery task triggered by products/update and products/create webhooks."""

    async def _run():
        await prisma.connect()
        try:
            await _index_single_product_sync_async(store_id, product_payload)
        finally:
            await prisma.disconnect()

    asyncio.run(_run())


@celery_app.task(bind=True, max_retries=3)
def task_delete_product_vector(self, store_id: str, product_id: str):
    pinecone_client.initialize()
    if not pinecone_client.index:
        return
    namespace = pinecone_client.get_store_namespace(store_id)
    pinecone_client.index.delete(
        ids=[f"{product_id}#text", f"{product_id}#image"],
        namespace=namespace,
    )
