"""
Shopify OAuth service: HMAC verification, token exchange, encryption/decryption.
Access tokens are encrypted at rest using Fernet symmetric encryption.
"""
import hashlib
import hmac
import base64
import secrets

import httpx

from app.config import get_settings
from app.core.crypto import encrypt_token, decrypt_token

settings = get_settings()


def build_oauth_url(shop: str, state: str) -> str:
    """
    Build the Shopify OAuth authorization URL.
    State is a random nonce to prevent CSRF — store it in the user session.
    """
    redirect_uri = f"{settings.app_url}/shopify/oauth/callback"
    scopes = settings.shopify_scopes
    client_id = settings.shopify_client_id
    return (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )


def generate_state() -> str:
    """Generate a cryptographically secure OAuth state token."""
    return secrets.token_urlsafe(32)


def verify_hmac(params: dict[str, str]) -> bool:
    """
    Verify the HMAC signature that Shopify attaches to the OAuth callback.
    Only the 'hmac' param is excluded from the message.
    """
    received_hmac = params.pop("hmac", None)
    if not received_hmac:
        return False

    message = "&".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    computed = hmac.new(
        settings.shopify_client_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, received_hmac)


async def exchange_code_for_token(shop: str, code: str) -> str | None:
    """
    Exchange the OAuth authorization code for a permanent access token.
    Returns the plaintext token or None if the exchange fails.
    """
    url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": settings.shopify_client_id,
        "client_secret": settings.shopify_client_secret,
        "code": code,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            return None
        data = response.json()
        return data.get("access_token")
