"""Pydantic schemas for billing / Stripe endpoints."""
from datetime import datetime
from pydantic import BaseModel


class CreateCheckoutResponse(BaseModel):
    checkout_url: str


class BillingPortalResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    status: str
    trial_ends_at: datetime
    current_period_end: datetime | None = None
    stripe_subscription_id: str | None = None
