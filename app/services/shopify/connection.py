"""
Shopify connection service — tenant-safe token loading.

Loads the user's Store from Prisma, enforces ownership,
checks is_active, and decrypts tokens for use with the GraphQL client.
"""
import logging

from fastapi import HTTPException, status

from app.core.database import prisma
from app.services.shopify.client import ShopifyGraphQLClient, ShopifyClientMode

logger = logging.getLogger("shopify.connection")


async def get_active_shop_connection(
    user_id: str,
    store_id: str | None = None,
    mode: ShopifyClientMode | None = None,
) -> ShopifyGraphQLClient:
    """
    Load the user's connected Shopify store and return a ready-to-use
    GraphQL client with decrypted tokens.

    Enforces:
    - Tenant isolation (user_id must own the store)
    - Store must be active (is_active == True)

    Args:
        user_id:  The authenticated user's ID.
        store_id: Optional specific store ID. If None, loads the user's
                  first active store.
        mode:     ``"admin"`` or ``"storefront"``. If omitted, the store's
                  saved ``default_mode`` is used.

    Returns:
        A ShopifyGraphQLClient instance configured for the requested mode.

    Raises:
        HTTPException 404: No store connected
        HTTPException 403: Store is inactive/uninstalled
    """
    if store_id:
        store = await prisma.store.find_first(
            where={"id": store_id, "userId": user_id}
        )
    else:
        # Multi-store: pick the first active store for this user
        store = await prisma.store.find_first(
            where={"userId": user_id, "is_active": True},
            order={"createdAt": "asc"},
        )

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "store_not_found",
                "message": "No Shopify store connected. Please connect your store first.",
            },
        )

    # Tenant isolation: if store_id was given, double-check userId
    if store.userId != user_id:
        logger.warning(
            "tenant_isolation_violation",
            extra={"user_id": user_id, "store_id": store.id},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "store_not_found", "message": "Store not found."},
        )

    if not store.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "store_inactive",
                "message": f"Store {store.shopify_domain} is uninstalled or disabled.",
            },
        )

    return _build_client(store, mode=mode)


async def get_shop_connection_by_slug(
    slug: str,
    mode: ShopifyClientMode | None = None,
) -> ShopifyGraphQLClient:
    """
    Load a store by its public slug (no auth required).
    Used by public-facing endpoints.

    Args:
        slug: The store's public slug.
        mode: ``"admin"`` or ``"storefront"``. If omitted, the store's
              saved ``default_mode`` is used.

    Raises:
        HTTPException 404: Store not found or inactive
    """
    store = await prisma.store.find_unique(where={"slug": slug})

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "store_not_found", "message": "Store not found."},
        )

    if not store.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "store_inactive", "message": "This store is currently unavailable."},
        )

    return _build_client(store, mode=mode)


def _build_client(store, mode: ShopifyClientMode | None = None) -> ShopifyGraphQLClient:
    """Decrypt tokens and build a ShopifyGraphQLClient for the given mode.

    If ``mode`` is None, the store's saved ``default_mode`` value is used
    (falls back to ``"storefront"`` if the field is absent).
    """
    resolved_mode: ShopifyClientMode = mode or getattr(store, "default_mode", None) or "storefront"
    storefront_token = store.shopify_storefront_token
    admin_token = store.shopify_admin_token

    logger.info(
        "shop_connection_loaded",
        extra={"shop": store.shopify_domain, "slug": store.slug, "mode": resolved_mode},
    )

    return ShopifyGraphQLClient(
        shop_domain=store.shopify_domain,
        store_id=store.id,
        storefront_token=storefront_token,
        admin_token=admin_token,
        mode=resolved_mode,
    )
