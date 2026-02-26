"""
Tests for AI tool schema validation.
Ensures that Pydantic schemas for cart operations enforce required fields.
"""
import pytest
from pydantic import ValidationError

from app.schemas.cart import (
    CartCreateRequest,
    CartAddRequest,
    CartUpdateRequest,
    CartRemoveRequest,
)


def test_cart_create_defaults():
    """CartCreateRequest should have sensible defaults."""
    req = CartCreateRequest()
    assert req.variant_id is None
    assert req.quantity == 1


def test_cart_create_with_variant():
    """CartCreateRequest with explicit variant."""
    req = CartCreateRequest(variant_id="gid://shopify/ProductVariant/123", quantity=2)
    assert req.variant_id == "gid://shopify/ProductVariant/123"
    assert req.quantity == 2


def test_cart_add_requires_cart_id():
    """CartAddRequest must have cart_id and variant_id."""
    with pytest.raises(ValidationError):
        CartAddRequest(variant_id="gid://shopify/ProductVariant/123")


def test_cart_add_requires_variant_id():
    """CartAddRequest must have variant_id."""
    with pytest.raises(ValidationError):
        CartAddRequest(cart_id="gid://shopify/Cart/456")


def test_cart_add_valid():
    """Valid CartAddRequest."""
    req = CartAddRequest(
        cart_id="gid://shopify/Cart/456",
        variant_id="gid://shopify/ProductVariant/123",
        quantity=3,
    )
    assert req.cart_id == "gid://shopify/Cart/456"
    assert req.quantity == 3


def test_cart_update_requires_all():
    """CartUpdateRequest requires cart_id, line_id, and quantity."""
    with pytest.raises(ValidationError):
        CartUpdateRequest(cart_id="cart-1", line_id="line-1")


def test_cart_update_valid():
    """Valid CartUpdateRequest."""
    req = CartUpdateRequest(cart_id="cart-1", line_id="line-1", quantity=5)
    assert req.quantity == 5


def test_cart_remove_requires_fields():
    """CartRemoveRequest requires cart_id and line_id."""
    with pytest.raises(ValidationError):
        CartRemoveRequest(cart_id="cart-1")


def test_cart_remove_valid():
    """Valid CartRemoveRequest."""
    req = CartRemoveRequest(cart_id="cart-1", line_id="line-1")
    assert req.line_id == "line-1"
