"""Pydantic schemas for Shopify cart REST endpoints."""
from pydantic import BaseModel


# ── Requests ──────────────────────────────────────────────────────────────────

class CartCreateRequest(BaseModel):
    variant_id: str | None = None
    quantity: int = 1


class CartAddRequest(BaseModel):
    cart_id: str
    variant_id: str
    quantity: int = 1


class CartUpdateRequest(BaseModel):
    cart_id: str
    line_id: str
    quantity: int


class CartRemoveRequest(BaseModel):
    cart_id: str
    line_id: str


# ── Responses ─────────────────────────────────────────────────────────────────

class CartLineItem(BaseModel):
    line_id: str
    variant_id: str
    title: str
    quantity: int
    price: str
    currency: str
    image_url: str | None = None


class CartCost(BaseModel):
    subtotal: str
    total: str
    currency: str


class CartResponse(BaseModel):
    cart_id: str
    checkout_url: str | None = None
    lines: list[CartLineItem] = []
    cost: CartCost | None = None
