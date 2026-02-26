"""Pydantic schemas for Shopify OAuth endpoints."""
from datetime import datetime
from pydantic import BaseModel


class ShopifyOAuthStartRequest(BaseModel):
    shop: str  # e.g. "mystore.myshopify.com"


class ShopifyConnectionOut(BaseModel):
    id: str
    shop_domain: str
    scopes: str
    installed_at: datetime

    model_config = {"from_attributes": True}
