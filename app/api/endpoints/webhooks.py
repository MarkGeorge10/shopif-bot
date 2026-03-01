"""
Shopify Webhook endpoint — HMAC-verified, with event logging.

POST /api/webhooks/shopify — receives Shopify webhook events.

Handled topics:
- app/uninstalled: mark Store as inactive, wipe encrypted tokens
- (future) products/update, orders/create
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Header, HTTPException, status
import json

from app.core.config import settings
from app.core.database import prisma
from app.services.rag.indexer import task_index_product, task_delete_product_vector

logger = logging.getLogger("api.webhooks")
router = APIRouter()

# ... existing code ...

@router.post("/shopify")
async def shopify_webhook(
    request: Request,
    x_shopify_topic: str = Header(..., alias="X-Shopify-Topic"),
    x_shopify_shop_domain: str = Header(..., alias="X-Shopify-Shop-Domain"),
    x_shopify_hmac_sha256: str = Header(..., alias="X-Shopify-Hmac-Sha256"),
    x_shopify_webhook_id: str = Header(None, alias="X-Shopify-Webhook-Id"),
):
    """
    Receive and process Shopify webhook events.
    """
    raw_body = await request.body()

    # ── HMAC verification ──────────────────────────────────────────────────
    if not _verify_shopify_hmac(raw_body, x_shopify_hmac_sha256):
        logger.warning(
            "webhook_hmac_failed",
            extra={"topic": x_shopify_topic, "shop": x_shopify_shop_domain},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    # ── Idempotency Check ──────────────────────────────────────────────────
    # If Shopify sends the exact same webhook_id again, we already processed it.
    if x_shopify_webhook_id:
        existing = await prisma.webhooklog.find_unique(where={"webhook_id": x_shopify_webhook_id})
        if existing:
            logger.info(f"Duplicate webhook skipped: {x_shopify_webhook_id}")
            return {"status": "ok", "message": "already processed"}

    # ── Parse Payload ──────────────────────────────────────────────────────
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        payload = {}
        
    reference_id = str(payload.get("admin_graphql_api_id") or payload.get("id") or "")

    # ── Log the webhook event ──────────────────────────────────────────────
    log_entry = await prisma.webhooklog.create(
        data={
            "webhook_id": x_shopify_webhook_id,
            "topic": x_shopify_topic,
            "shop_domain": x_shopify_shop_domain,
            "payload_hash": payload_hash,
            "reference_id": reference_id,
            "status": "received",
        }
    )

    logger.info(
        "webhook_received",
        extra={
            "topic": x_shopify_topic,
            "shop": x_shopify_shop_domain,
            "log_id": log_entry.id,
        },
    )

    # ── Dispatch by topic ──────────────────────────────────────────────────
    try:
        if x_shopify_topic == "app/uninstalled":
            await _handle_app_uninstalled(x_shopify_shop_domain)
            
        elif x_shopify_topic in ["products/create", "products/update"]:
            await _handle_products_upsert(x_shopify_shop_domain, payload)
            
        elif x_shopify_topic == "products/delete":
            await _handle_products_delete(x_shopify_shop_domain, payload)

        # Mark as processed
        await prisma.webhooklog.update(
            where={"id": log_entry.id},
            data={
                "status": "processed",
                "processed_at": datetime.now(timezone.utc),
            },
        )

    except Exception as e:
        logger.error(
            "webhook_processing_failed",
            extra={
                "topic": x_shopify_topic,
                "shop": x_shopify_shop_domain,
                "error": str(e),
            },
        )
        await prisma.webhooklog.update(
            where={"id": log_entry.id},
            data={"status": "failed", "error_msg": str(e)},
        )

    return {"status": "ok"}


# ── Topic handlers ────────────────────────────────────────────────────────────

async def _handle_products_upsert(shop_domain: str, payload: dict):
    store = await prisma.store.find_first(where={"shopify_domain": shop_domain})
    if not store or not store.enhanced_search_enabled:
        return
        
    # Send CPU-bound multimodal extraction to Celery queue immediately
    task_index_product.delay(store.id, payload)

async def _handle_products_delete(shop_domain: str, payload: dict):
    store = await prisma.store.find_first(where={"shopify_domain": shop_domain})
    if not store or not store.enhanced_search_enabled:
        return
        
    p_id = payload.get("admin_graphql_api_id")
    if p_id:
        task_delete_product_vector.delay(store.id, p_id)

async def _handle_app_uninstalled(shop_domain: str):
    """
    When Shopify sends app/uninstalled:
    1. Find the Store for this shop domain
    2. Set is_active = False
    3. Wipe encrypted tokens (they're revoked anyway)
    """
    store = await prisma.store.find_first(
        where={"shopify_domain": shop_domain}
    )
    if not store:
        logger.warning(f"app/uninstalled for unknown shop: {shop_domain}")
        return

    await prisma.store.update(
        where={"id": store.id},
        data={
            "is_active": False,
            "shopify_storefront_token": "",
            "shopify_admin_token": "",
        },
    )

    logger.info(
        "store_deactivated",
        extra={"shop": shop_domain, "store_id": store.id},
    )
