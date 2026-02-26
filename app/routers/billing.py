"""
Billing router: Stripe checkout, portal, status, and webhook handler.
POST /billing/create-checkout  — start Stripe Checkout (requires auth)
POST /billing/portal           — open Stripe Customer Portal (requires auth)
GET  /billing/status           — return subscription status (requires auth)
POST /billing/webhook          — Stripe webhook (no auth, signature verified)
"""
import stripe
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.subscription import Subscription, SubscriptionStatus
from app.schemas.billing import (
    CreateCheckoutResponse,
    BillingPortalResponse,
    SubscriptionStatusResponse,
)
from app.services.stripe_service import (
    create_checkout_session,
    create_billing_portal_session,
    construct_webhook_event,
    handle_subscription_event,
)

router = APIRouter(prefix="/billing", tags=["Billing"])
settings = get_settings()


@router.post("/create-checkout", response_model=CreateCheckoutResponse)
def create_checkout(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a Stripe Checkout Session for $20/month. Returns redirect URL."""
    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer linked. Please contact support.",
        )
    session = create_checkout_session(
        stripe_customer_id=current_user.stripe_customer_id,
        success_url=f"{settings.app_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_url}/billing/canceled",
    )
    return CreateCheckoutResponse(checkout_url=session.url)


@router.post("/portal", response_model=BillingPortalResponse)
def billing_portal(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Open the Stripe Customer Portal (manage/cancel subscription, update payment)."""
    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer linked.",
        )
    portal = create_billing_portal_session(
        stripe_customer_id=current_user.stripe_customer_id,
        return_url=f"{settings.app_url}/dashboard",
    )
    return BillingPortalResponse(portal_url=portal.url)


@router.get("/status", response_model=SubscriptionStatusResponse)
def subscription_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the current user's subscription status and dates."""
    sub = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription found.")
    return SubscriptionStatusResponse(
        status=sub.status.value,
        trial_ends_at=sub.trial_ends_at,
        current_period_end=sub.current_period_end,
        stripe_subscription_id=sub.stripe_subscription_id,
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, db: Annotated[Session, Depends(get_db)]):
    """
    Receive and verify Stripe webhook events.
    Updates subscription status in the database based on Stripe lifecycle events.
    No auth — Stripe signature is verified instead.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Normalize the event into a flat dict
    update = handle_subscription_event(event)
    if not update:
        # Unhandled event type — acknowledge to prevent Stripe retries
        return {"received": True}

    # Find the user by Stripe customer ID
    stripe_customer_id = update.get("stripe_customer_id")
    if not stripe_customer_id:
        return {"received": True}

    user = db.query(User).filter(User.stripe_customer_id == stripe_customer_id).first()
    if not user:
        return {"received": True}

    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not sub:
        return {"received": True}

    # Apply updates
    if update.get("stripe_subscription_id"):
        sub.stripe_subscription_id = update["stripe_subscription_id"]
    if update.get("status"):
        sub.status = SubscriptionStatus(update["status"])
    if update.get("current_period_end") is not None:
        sub.current_period_end = update["current_period_end"]

    db.commit()
    return {"received": True}
