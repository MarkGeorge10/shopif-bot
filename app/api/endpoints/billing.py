import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from datetime import datetime
import pytz

from app.api.deps import get_current_user
from app.core.config import settings
from prisma.models import User

# Needs app global Prisma
from app.core.database import prisma

router = APIRouter()
stripe.api_key = settings.STRIPE_SECRET_KEY

@router.post("/checkout")
async def create_checkout_session(current_user: User = Depends(get_current_user)):
    """
    Creates a Stripe Checkout Session for the user to subscribe ($20/month).
    """
    try:
        # Check if user already has a Stripe customer ID, if not create one
        customer_id = current_user.stripe_customer_id
        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                metadata={"user_id": current_user.id}
            )
            customer_id = customer.id
            await prisma.user.update(
                where={"id": current_user.id},
                data={"stripe_customer_id": customer_id}
            )

        # Create the checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": settings.STRIPE_PRICE_ID,
                    "quantity": 1,
                },
            ],
            mode="subscription",
            success_url=f"{settings.APP_URL}/dashboard?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.APP_URL}/billing",
            client_reference_id=current_user.id,
        )
        return {"checkout_url": checkout_session.url}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Handle Stripe Webhooks (e.g., checkout.session.completed)
    to upgrade the user to Pro.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # client_reference_id contains the database User ID
        user_id = session.get("client_reference_id")
        subscription_id = session.get("subscription")
        
        if user_id:
            # Upgrade user to PRO
            await prisma.user.update(
                where={"id": user_id},
                data={"is_pro": True}
            )
            
            # Fetch subscription details from Stripe
            subscription = stripe.Subscription.retrieve(subscription_id)
            current_period_end = datetime.utcfromtimestamp(subscription.current_period_end)
            
            # Upsert the subscription record
            existing_sub = await prisma.subscription.find_unique(where={"userId": user_id})
            if existing_sub:
                await prisma.subscription.update(
                    where={"id": existing_sub.id},
                    data={
                        "stripe_subscription_id": subscription_id,
                        "status": subscription.status,
                        "current_period_end": current_period_end.replace(tzinfo=pytz.UTC),
                    }
                )
            else:
                await prisma.subscription.create(
                    data={
                        "userId": user_id,
                        "stripe_subscription_id": subscription_id,
                        "status": subscription.status,
                        "current_period_end": current_period_end.replace(tzinfo=pytz.UTC),
                    }
                )

    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        subscription_id = invoice.get("subscription")
        
        # If payment fails, set the subscription status to past_due / unpaid
        # and downgrade the user.
        if subscription_id:
            sub = await prisma.subscription.find_unique(where={"stripe_subscription_id": subscription_id})
            if sub:
                await prisma.user.update(
                    where={"id": sub.userId},
                    data={"is_pro": False}
                )
                await prisma.subscription.update(
                    where={"id": sub.id},
                    data={"status": "past_due"}
                )

    return Response(status_code=200)
