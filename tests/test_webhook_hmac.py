"""
Tests for Shopify webhook HMAC verification.
"""
import hashlib
import hmac
import base64


def compute_hmac(body: bytes, secret: str) -> str:
    """Compute the expected HMAC for a given body and secret."""
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


def test_valid_hmac():
    """Valid HMAC should pass verification."""
    secret = "test-shopify-secret"
    body = b'{"topic": "app/uninstalled", "shop": "test.myshopify.com"}'
    expected = compute_hmac(body, secret)

    computed = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

    assert hmac.compare_digest(computed, expected), "Valid HMAC should match"


def test_invalid_hmac():
    """Tampered body should fail HMAC verification."""
    secret = "test-shopify-secret"
    body = b'{"topic": "app/uninstalled"}'
    expected = compute_hmac(body, secret)

    # Tamper with the body
    tampered = b'{"topic": "app/uninstalled", "extra": true}'
    computed = base64.b64encode(
        hmac.new(secret.encode("utf-8"), tampered, hashlib.sha256).digest()
    ).decode("utf-8")

    assert not hmac.compare_digest(computed, expected), "Tampered HMAC should NOT match"


def test_wrong_secret():
    """Wrong secret should fail HMAC verification."""
    real_secret = "real-secret"
    wrong_secret = "wrong-secret"
    body = b'{"test": true}'

    expected = compute_hmac(body, real_secret)
    computed = compute_hmac(body, wrong_secret)

    assert not hmac.compare_digest(computed, expected), "Wrong secret should NOT match"


def test_empty_body():
    """Empty body should still produce a valid HMAC."""
    secret = "test-secret"
    body = b""
    hmac_val = compute_hmac(body, secret)
    assert len(hmac_val) > 0, "HMAC should be non-empty even for empty body"
