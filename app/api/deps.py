from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from datetime import datetime

from prisma.models import User
from app.core.config import settings

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login"
)

async def get_current_user(token: str = Depends(reusable_oauth2)) -> User:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        token_data = payload.get("sub")
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    
    # Needs to import Prisma Client inside function or globally
    from app.core.database import prisma
    
    user = await prisma.user.find_unique(where={"id": token_data})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Check if the user has an active Stripe subscription OR an active 14-day trial.
    """
    now = datetime.utcnow()
    
    # Give priority to an active Stripe subscription
    if current_user.is_pro:
        return current_user
        
    # Check if they are still within the 14-day trial
    # Both are naive or both timezone-aware. Let's ensure UTC comparison.
    # Prisma returns aware datetimes. Let's make 'now' aware to compare safely:
    import pytz
    now_aware = datetime.utcnow().replace(tzinfo=pytz.UTC)
    
    trial_ends = current_user.trial_ends_at
    if trial_ends.tzinfo is None:
        trial_ends = trial_ends.replace(tzinfo=pytz.UTC)
    
    if now_aware > trial_ends:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Trial has expired and no active subscription was found. Please upgrade to Pro."
        )
        
    return current_user
