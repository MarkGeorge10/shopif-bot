"""
FastAPI dependency providers for DB session and authenticated user.
"""
from typing import Generator, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.auth_service import decode_access_token
from app.models.user import User

security = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and ensure it closes after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """
    Decode the JWT from the Authorization header and return the User.
    Raises 401 if the token is invalid or the user does not exist.
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


def require_active_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """
    Ensure the user has an active subscription (trialing or active).
    Raises 403 with a machine-readable error code if not.
    """
    from datetime import datetime, timezone
    from app.models.subscription import Subscription, SubscriptionStatus

    sub = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "subscribe_required", "message": "No subscription found."},
        )

    now = datetime.now(timezone.utc)

    if sub.status == SubscriptionStatus.TRIALING:
        if sub.trial_ends_at < now:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "trial_expired", "message": "Your free trial has ended. Please subscribe."},
            )
        return current_user

    if sub.status == SubscriptionStatus.ACTIVE:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "subscribe_required", "message": f"Subscription status: {sub.status.value}"},
    )
