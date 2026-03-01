"""
Shopify OAuth router.
GET    /shopify/oauth/start      — redirect to Shopify OAuth consent
GET    /shopify/oauth/callback   — exchange code, store encrypted token
GET    /shopify/connection       — return connected store info
DELETE /shopify/connection       — remove the connection
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, require_active_subscription
from app.models.user import User
from app.models.shopify_connection import ShopifyConnection
from app.schemas.shopify import ShopifyConnectionOut
from app.services.shopify_service import (
    build_oauth_url,
    generate_state,
    verify_hmac,
    exchange_code_for_token,
)
from app.core.crypto import encrypt_token
from app.config import get_settings

router = APIRouter(prefix="/shopify", tags=["Shopify"])
settings = get_settings()

# In-memory state store (use Redis in production for multi-instance deployments)
_oauth_states: dict[str, str] = {}  # state -> user_id


@router.get("/oauth/start")
def oauth_start(
    shop: str = Query(..., description="e.g. mystore.myshopify.com"),
    current_user: User = Depends(require_active_subscription),
):
    """
    Initiate the Shopify OAuth flow.
    Redirects the user to the Shopify consent screen.
    A CSRF state token is generated and associated with the user.
    """
    if not shop.endswith(".myshopify.com"):
        raise HTTPException(status_code=400, detail="Invalid shop domain.")

    state = generate_state()
    _oauth_states[state] = current_user.id

    redirect_url = build_oauth_url(shop=shop, state=state)
    return RedirectResponse(url=redirect_url)


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str = Query(...),
    shop: str = Query(...),
    state: str = Query(...),
    hmac: str = Query(...),
):
    """
    Shopify OAuth callback.
    - Verifies HMAC and state to prevent CSRF.
    - Exchanges auth code for a permanent access token.
    - Stores the encrypted token in the database.
    """
    # Verify CSRF state
    user_id = _oauth_states.pop(state, None)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")

    # Verify Shopify HMAC signature
    all_params = dict(request.query_params)
    if not verify_hmac(all_params):
        raise HTTPException(status_code=400, detail="HMAC verification failed.")

    # Exchange code for access token
    access_token = await exchange_code_for_token(shop=shop, code=code)
    if not access_token:
        raise HTTPException(status_code=400, detail="Failed to exchange code for token.")

    # Upsert ShopifyConnection
    conn = db.query(ShopifyConnection).filter(ShopifyConnection.user_id == user_id).first()
    if conn:
        conn.shop_domain = shop
        conn.encrypted_access_token = encrypt_token(access_token)
        conn.scopes = settings.shopify_scopes
    else:
        conn = ShopifyConnection(
            user_id=user_id,
            shop_domain=shop,
            encrypted_access_token=encrypt_token(access_token),
            scopes=settings.shopify_scopes,
        )
        db.add(conn)

    db.commit()

    # Redirect back to the frontend dashboard
    frontend_origin = settings.allowed_origins_list[0]
    return RedirectResponse(url=f"{frontend_origin}/dashboard?shopify=connected")


@router.get("/connection", response_model=ShopifyConnectionOut)
def get_connection(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the current user's connected Shopify store (without the token)."""
    conn = db.query(ShopifyConnection).filter(ShopifyConnection.user_id == current_user.id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="No Shopify store connected.")
    return conn


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Remove the Shopify connection for the current user."""
    conn = db.query(ShopifyConnection).filter(ShopifyConnection.user_id == current_user.id).first()
    if conn:
        db.delete(conn)
        db.commit()
