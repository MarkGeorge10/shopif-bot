"""
Shopify OAuth service: HMAC verification, token exchange, encryption/decryption.
Access tokens are encrypted at rest using Fernet symmetric encryption.
"""
import hashlib
import hmac
import base64
import secrets

import httpx
from cryptography.fernet import Fernet

from app.config import get_settings

settings = get_settings()


def _fernet() -> Fernet:
    """Return a Fernet instance using the secret key from env."""
    return Fernet(settings.fernet_secret_key.encode())


def encrypt_token(plaintext_token: str) -> str:
    """Encrypt a Shopify access token for database storage."""
    return _fernet().encrypt(plaintext_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a Shopify access token retrieved from the database."""
    return _fernet().decrypt(encrypted_token.encode()).decode()


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
