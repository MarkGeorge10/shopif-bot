"""
Auth router: register, login, get profile, update profile.
POST /auth/register — creates user + 14-day trial + Stripe customer
POST /auth/token    — returns JWT
GET  /auth/me       — current user + subscription
PATCH /auth/me      — update name fields
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base
from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.subscription import Subscription, SubscriptionStatus
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserOut,
    UpdateProfileRequest,
)
from app.services.auth_service import hash_password, verify_password, create_access_token
from app.services.stripe_service import create_stripe_customer

router = APIRouter(prefix="/auth", tags=["Auth"])
settings = get_settings()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Annotated[Session, Depends(get_db)]):
    """
    Register a new user.
    - Creates a Stripe customer for future billing.
    - Creates a 14-day free trial subscription automatically.
    - Returns a JWT access token.
    """
    # Check duplicate email
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # Create Stripe customer
    full_name = " ".join(filter(None, [body.first_name, body.last_name])) or None
    try:
        stripe_customer = create_stripe_customer(email=body.email, name=full_name)
        stripe_customer_id = stripe_customer.id
    except Exception:
        # Non-fatal: proceed without Stripe customer (can be linked later)
        stripe_customer_id = None

    # Create user
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        stripe_customer_id=stripe_customer_id,
    )
    db.add(user)
    db.flush()  # Get user.id before committing

    # Create 14-day trial subscription
    trial_end = datetime.now(timezone.utc) + timedelta(days=settings.trial_days)
    subscription = Subscription(
        user_id=user.id,
        status=SubscriptionStatus.TRIALING,
        trial_ends_at=trial_end,
    )
    db.add(subscription)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.id)
    return TokenResponse(access_token=token)


@router.post("/token", response_model=TokenResponse)
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    """Authenticate with email and password. Returns a JWT."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    token = create_access_token(subject=user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def get_me(current_user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    """Return the authenticated user's profile and subscription status."""
    db.refresh(current_user)
    return current_user


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update first/last name on the user profile."""
    if body.first_name is not None:
        current_user.first_name = body.first_name
    if body.last_name is not None:
        current_user.last_name = body.last_name
    db.commit()
    db.refresh(current_user)
    return current_user
