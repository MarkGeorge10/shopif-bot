"""
Unit tests for app/services/shopify/repository.py

Tests:
- admin_fetch_all_products pagination (mocked responses)
- storefront_search_products (mocked response)
- storefront_nodes_products filtering of null nodes
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.shopify.repository import (
    admin_fetch_all_products,
    storefront_search_products,
    storefront_list_collections,
    storefront_collection_products,
    storefront_product_details,
    storefront_nodes_products,
)


def _make_product(product_id: str, title: str) -> dict:
    return {
        "id": product_id,
        "title": title,
        "description": "A product",
        "vendor": "Acme",
        "productType": "Widget",
        "tags": ["tag1"],
        "updatedAt": "2024-01-01T00:00:00Z",
        "status": "ACTIVE",
        "images": {"edges": []},
        "variants": {"edges": [{"node": {"price": "9.99", "inventoryQuantity": 5}}]},
    }


def _make_admin_page(products: list[dict], has_next: bool, end_cursor: str | None = None) -> dict:
    """Build a mock Admin API `products` page response."""
    return {
        "products": {
            "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
            "edges": [{"node": p} for p in products],
        }
    }


@pytest.mark.asyncio
async def test_admin_fetch_all_products_single_page():
    """Repository correctly handles a single-page non-paginated response."""
    mock_client = MagicMock()
    products = [_make_product("gid://1", "Product A"), _make_product("gid://2", "Product B")]
    mock_client.execute_admin = AsyncMock(
        return_value=_make_admin_page(products, has_next=False)
    )

    result = await admin_fetch_all_products(mock_client)

    assert len(result) == 2
    assert result[0]["id"] == "gid://1"
    assert result[1]["title"] == "Product B"
    mock_client.execute_admin.assert_called_once()


@pytest.mark.asyncio
async def test_admin_fetch_all_products_pagination():
    """Repository correctly paginates through multiple pages using cursors."""
    mock_client = MagicMock()

    page1_products = [_make_product("gid://1", "P1"), _make_product("gid://2", "P2")]
    page2_products = [_make_product("gid://3", "P3")]

    mock_client.execute_admin = AsyncMock(side_effect=[
        _make_admin_page(page1_products, has_next=True, end_cursor="cursor_abc"),
        _make_admin_page(page2_products, has_next=False),
    ])

    result = await admin_fetch_all_products(mock_client)

    assert len(result) == 3
    assert result[0]["id"] == "gid://1"
    assert result[2]["id"] == "gid://3"
    assert mock_client.execute_admin.call_count == 2

    # Verify cursor was passed in the second call
    second_call_gql = mock_client.execute_admin.call_args_list[1][0][0]
    assert 'after: "cursor_abc"' in second_call_gql


@pytest.mark.asyncio
async def test_admin_fetch_all_products_empty_store():
    """Repository returns empty list when store has no products."""
    mock_client = MagicMock()
    mock_client.execute_admin = AsyncMock(
        return_value=_make_admin_page([], has_next=False)
    )

    result = await admin_fetch_all_products(mock_client)
    assert result == []


@pytest.mark.asyncio
async def test_storefront_search_products():
    """Repository sends correct query filter and parses response."""
    mock_client = MagicMock()
    mock_client.execute_storefront = AsyncMock(return_value={
        "products": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "edges": [{"node": {"id": "gid://sf1", "title": "Shirt"}}],
        }
    })

    result = await storefront_search_products(mock_client, query="shirt", first=10)

    assert "pageInfo" in result
    assert result["edges"][0]["node"]["title"] == "Shirt"

    # Verify query string was included
    call_gql = mock_client.execute_storefront.call_args[0][0]
    assert "available_for_sale:true" in call_gql
    assert "shirt" in call_gql


@pytest.mark.asyncio
async def test_storefront_nodes_products_filters_nulls():
    """storefront_nodes_products must filter out null entries from the nodes list."""
    mock_client = MagicMock()
    mock_client.execute_storefront = AsyncMock(return_value={
        "nodes": [
            {"id": "gid://1", "title": "Widget"},
            None,  # Shopify returns null for deleted products
            {"id": "gid://2", "title": "Gadget"},
        ]
    })

    result = await storefront_nodes_products(mock_client, ids=["gid://1", "gid://deleted", "gid://2"])

    assert len(result) == 2
    assert result[0]["id"] == "gid://1"
    assert result[1]["id"] == "gid://2"


@pytest.mark.asyncio
async def test_storefront_nodes_products_empty_ids():
    """storefront_nodes_products must return empty list without making API calls."""
    mock_client = MagicMock()
    mock_client.execute_storefront = AsyncMock()

    result = await storefront_nodes_products(mock_client, ids=[])

    assert result == []
    mock_client.execute_storefront.assert_not_called()
