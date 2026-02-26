"""
Stripe service: customer creation, checkout sessions, portal, webhook processing.
All Stripe API calls go through this module to keep routers thin.
"""
from datetime import datetime, timezone

import stripe

from app.config import get_settings

settings = get_settings()

# Configure Stripe SDK — key comes from env, never hardcoded
stripe.api_key = settings.stripe_secret_key


def create_stripe_customer(email: str, name: str | None = None) -> stripe.Customer:
    """Create a new Stripe customer and return the object."""
    kwargs: dict = {"email": email}
    if name:
        kwargs["name"] = name
    return stripe.Customer.create(**kwargs)


def create_checkout_session(
    stripe_customer_id: str,
    success_url: str,
    cancel_url: str,
) -> stripe.checkout.Session:
    """
    Create a Stripe Checkout Session for the $20/month subscription.
    Returns the session object (caller should redirect to session.url).
    """
    return stripe.checkout.Session.create(
        customer=stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
    )


def create_billing_portal_session(
    stripe_customer_id: str,
    return_url: str,
) -> stripe.billing_portal.Session:
    """Create a Stripe Customer Portal session for self-service subscription management."""
    return stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify the Stripe webhook signature and parse the event."""
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )


def handle_subscription_event(event: stripe.Event) -> dict:
    """
    Parse key subscription lifecycle events and return a normalized dict
    for the router to apply to the database.
    """
    event_type = event["type"]
    data = event["data"]["object"]

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        status_map = {
            "trialing": "trialing",
            "active": "active",
            "past_due": "past_due",
            "canceled": "canceled",
            "incomplete": "incomplete",
            "incomplete_expired": "canceled",
            "unpaid": "past_due",
        }
        stripe_status = data.get("status", "canceled")
        current_period_end = data.get("current_period_end")
        return {
            "stripe_customer_id": data.get("customer"),
            "stripe_subscription_id": data.get("id"),
            "status": status_map.get(stripe_status, "canceled"),
            "current_period_end": (
                datetime.fromtimestamp(current_period_end, tz=timezone.utc)
                if current_period_end
                else None
            ),
        }

    if event_type == "invoice.payment_failed":
        return {
            "stripe_customer_id": data.get("customer"),
            "stripe_subscription_id": data.get("subscription"),
            "status": "past_due",
            "current_period_end": None,
        }

    return {}
