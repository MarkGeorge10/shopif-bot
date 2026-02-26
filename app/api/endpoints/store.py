"""
Store management CRUD endpoints.

POST   /api/store/connect         — create/add a new store
GET    /api/store/list             — list all stores for current user
GET    /api/store/config           — get first store config (backwards compat)
GET    /api/store/{store_id}       — get specific store
PUT    /api/store/{store_id}       — update store name/domain/tokens
DELETE /api/store/{store_id}       — delete a store
GET    /api/store/policies         — get store policies
"""
import re
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from prisma.models import User

from app.api.deps import get_current_active_user
from app.core.security import encrypt_token
from app.core.database import prisma

logger = logging.getLogger("api.store")
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class StoreConnectInput(BaseModel):
    shopify_domain: str
    shopify_storefront_token: str
    shopify_admin_token: str
    name: str = "My Store"


class StoreUpdateInput(BaseModel):
    name: str | None = None
    shopify_domain: str | None = None
    shopify_storefront_token: str | None = None
    shopify_admin_token: str | None = None


class StoreResponse(BaseModel):
    id: str
    name: str
    slug: str
    shopify_domain: str
    is_active: bool
    public_url: str = ""

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_slug(domain: str) -> str:
    """Generate a URL-friendly slug from a Shopify domain."""
    # Extract store name from domain (e.g. "my-store.myshopify.com" → "my-store")
    base = domain.replace(".myshopify.com", "").replace(".com", "")
    slug = re.sub(r"[^a-z0-9-]", "-", base.lower()).strip("-")
    # Add short unique suffix to avoid collisions
    suffix = uuid.uuid4().hex[:6]
    return f"{slug}-{suffix}"


def _make_response(store, app_url: str = "") -> dict:
    return {
        "id": store.id,
        "name": store.name,
        "slug": store.slug,
        "shopify_domain": store.shopify_domain,
        "is_active": store.is_active,
        "public_url": f"/s/{store.slug}",
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/connect", response_model=StoreResponse)
async def connect_store(
    store_in: StoreConnectInput,
    current_user: User = Depends(get_current_active_user),
):
    """Add a new Shopify store to the current user's account."""
    encrypted_storefront = encrypt_token(store_in.shopify_storefront_token)
    encrypted_admin = encrypt_token(store_in.shopify_admin_token)

    slug = _generate_slug(store_in.shopify_domain)

    # Ensure slug is unique (retry if collision)
    for _ in range(5):
        existing = await prisma.store.find_unique(where={"slug": slug})
        if not existing:
            break
        slug = _generate_slug(store_in.shopify_domain)

    store = await prisma.store.create(
        data={
            "userId": current_user.id,
            "name": store_in.name,
            "slug": slug,
            "shopify_domain": store_in.shopify_domain,
            "shopify_storefront_token": encrypted_storefront,
            "shopify_admin_token": encrypted_admin,
        }
    )

    return _make_response(store)


@router.get("/list", response_model=list[StoreResponse])
async def list_stores(
    current_user: User = Depends(get_current_active_user),
):
    """List all stores for the current user."""
    stores = await prisma.store.find_many(
        where={"userId": current_user.id},
        order={"createdAt": "asc"},
    )
    return [_make_response(s) for s in stores]


@router.get("/config", response_model=StoreResponse)
async def get_store_config(current_user: User = Depends(get_current_active_user)):
    """Return first store config (backwards compatibility)."""
    store = await prisma.store.find_first(
        where={"userId": current_user.id, "is_active": True},
        order={"createdAt": "asc"},
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not configured")
    return _make_response(store)


@router.get("/{store_id}")
async def get_store(
    store_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get a specific store by ID."""
    store = await prisma.store.find_first(
        where={"id": store_id, "userId": current_user.id}
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return _make_response(store)


@router.put("/{store_id}", response_model=StoreResponse)
async def update_store(
    store_id: str,
    body: StoreUpdateInput,
    current_user: User = Depends(get_current_active_user),
):
    """Update a store's name, domain, or tokens."""
    store = await prisma.store.find_first(
        where={"id": store_id, "userId": current_user.id}
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    update_data: dict = {}
    if body.name is not None:
        update_data["name"] = body.name
    if body.shopify_domain is not None:
        update_data["shopify_domain"] = body.shopify_domain
    if body.shopify_storefront_token is not None:
        update_data["shopify_storefront_token"] = encrypt_token(body.shopify_storefront_token)
    if body.shopify_admin_token is not None:
        update_data["shopify_admin_token"] = encrypt_token(body.shopify_admin_token)

    if update_data:
        store = await prisma.store.update(
            where={"id": store.id},
            data=update_data,
        )

    return _make_response(store)


@router.delete("/{store_id}", status_code=204)
async def delete_store(
    store_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a store."""
    store = await prisma.store.find_first(
        where={"id": store_id, "userId": current_user.id}
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    await prisma.store.delete(where={"id": store.id})


@router.get("/{store_id}/policies")
async def get_policies(
    store_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Return store policies (shipping, refund, privacy, terms)."""
    from app.services.shopify.connection import get_active_shop_connection

    client = await get_active_shop_connection(current_user.id, store_id=store_id)
    gql = """
    query getShopPolicies {
      shop {
        privacyPolicy { title body }
        refundPolicy { title body }
        shippingPolicy { title body }
        termsOfService { title body }
      }
    }
    """
    data = await client.execute_storefront(gql)
    return data.get("shop", {})
