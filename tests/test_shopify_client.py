"""
Tests for the Shopify GraphQL client with mocked httpx responses.
"""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


@pytest.fixture
def mock_settings():
    """Provide minimal settings for testing."""
    with patch("app.services.shopify.client.settings") as mock:
        mock.SHOPIFY_API_VERSION = "2026-01"
        yield mock


@pytest.mark.asyncio
async def test_storefront_success(mock_settings):
    """Successful Storefront API call should return data."""
    from app.services.shopify.client import ShopifyGraphQLClient

    client = ShopifyGraphQLClient(
        shop_domain="test.myshopify.com",
        storefront_token="sf-test-token",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"products": {"edges": []}},
    }
    mock_response.headers = {}

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await client.execute_storefront(
            "query { products(first:1) { edges { node { id } } } }"
        )

    assert "products" in result
    assert result["products"]["edges"] == []


@pytest.mark.asyncio
async def test_rate_limit_raises(mock_settings):
    """HTTP 429 should raise ShopifyRateLimitError."""
    from app.services.shopify.client import ShopifyGraphQLClient
    from app.core.exceptions import ShopifyRateLimitError

    client = ShopifyGraphQLClient(
        shop_domain="test.myshopify.com",
        storefront_token="sf-test-token",
    )

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "2.0"}

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        with pytest.raises(ShopifyRateLimitError):
            # Disable tenacity retry for test (it would retry 5 times)
            client._execute.retry.stop = lambda *a, **kw: True
            await client.execute_storefront("query { shop { name } }")


@pytest.mark.asyncio
async def test_graphql_error_raises(mock_settings):
    """GraphQL errors in response body should raise ShopifyAPIError."""
    from app.services.shopify.client import ShopifyGraphQLClient
    from app.core.exceptions import ShopifyAPIError

    client = ShopifyGraphQLClient(
        shop_domain="test.myshopify.com",
        storefront_token="sf-test-token",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "errors": [{"message": "Field 'nonexistent' doesn't exist"}]
    }
    mock_response.headers = {}

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        with pytest.raises(ShopifyAPIError):
            await client.execute_storefront("query { nonexistent }")
