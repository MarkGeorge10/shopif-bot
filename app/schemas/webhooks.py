"""Pydantic schemas for Shopify webhook endpoint."""
from datetime import datetime
from pydantic import BaseModel


class WebhookLogOut(BaseModel):
    id: str
    topic: str
    shop_domain: str
    status: str
    received_at: datetime
    processed_at: datetime | None = None

    class Config:
        from_attributes = True
