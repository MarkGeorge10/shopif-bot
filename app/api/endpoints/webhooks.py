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

from app.core.config import settings
from app.core.database import prisma

logger = logging.getLogger("api.webhooks")
router = APIRouter()


def _verify_shopify_hmac(body: bytes, hmac_header: str) -> bool:
    """
    Verify the X-Shopify-Hmac-Sha256 header against the raw request body.
    Uses the app's SHOPIFY_CLIENT_SECRET as the HMAC key.
    """
    if not settings.SHOPIFY_CLIENT_SECRET:
        logger.warning("SHOPIFY_CLIENT_SECRET not set — cannot verify webhook HMAC")
        return False

    computed = hmac.new(
        settings.SHOPIFY_CLIENT_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()

    import base64
    computed_b64 = base64.b64encode(computed).decode("utf-8")
    return hmac.compare_digest(computed_b64, hmac_header)


@router.post("/shopify")
async def shopify_webhook(
    request: Request,
    x_shopify_topic: str = Header(..., alias="X-Shopify-Topic"),
    x_shopify_shop_domain: str = Header(..., alias="X-Shopify-Shop-Domain"),
    x_shopify_hmac_sha256: str = Header(..., alias="X-Shopify-Hmac-Sha256"),
):
    """
    Receive and process Shopify webhook events.

    - HMAC signature is verified (no JWT auth — Shopify can't send bearer tokens)
    - Every event is logged to the WebhookLog table for observability
    - Dispatches to topic-specific handlers
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

    # ── Payload hash for dedup / debugging ─────────────────────────────────
    payload_hash = hashlib.sha256(raw_body).hexdigest()

    # ── Log the webhook event ──────────────────────────────────────────────
    log_entry = await prisma.webhooklog.create(
        data={
            "topic": x_shopify_topic,
            "shop_domain": x_shopify_shop_domain,
            "payload_hash": payload_hash,
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

        # Future handlers:
        # elif x_shopify_topic == "products/update":
        #     await _handle_products_update(payload)
        # elif x_shopify_topic == "orders/create":
        #     await _handle_orders_create(payload)

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
            data={"status": "failed"},
        )

    return {"status": "ok"}


# ── Topic handlers ────────────────────────────────────────────────────────────

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
