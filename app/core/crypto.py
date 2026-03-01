from cryptography.fernet import Fernet
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

fernet = Fernet(settings.FERNET_SECRET_KEY)

def encrypt_token(token: str) -> str:
    """Encrypts a string (e.g. Shopify Token) for DB storage"""
    if not token:
        return token
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypts a string from DB storage"""
    if not encrypted_token:
        return encrypted_token
    # Handle the case where the string isn't encrypted (dev environments or old unmigrated data)
    # Fernet tokens start with gAAAAA...
    if not encrypted_token.startswith("gAAAAA"):
        return encrypted_token
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        logger.warning(f"Failed to decrypt token. This may cause authentication to fail. Err: {e}")
        return encrypted_token
