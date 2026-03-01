"""
Shopify GraphQL Repository — the ONLY place that contains raw GQL strings.

All callers (endpoints, indexer, tools) MUST import from here instead of
constructing their own query strings. This keeps the codebase DRY and makes
upgrading the Shopify API version a one-file change.

All functions:
  - Accept a ShopifyGraphQLClient instance (already has decrypted tokens)
  - Return raw Shopify JSON dicts (parsing into Pydantic schemas remains in the API layer)
  - Are fully async
"""
import logging
from typing import Optional

from app.services.shopify.client import ShopifyGraphQLClient

logger = logging.getLogger(__name__)

# ── Shared GQL fragment ────────────────────────────────────────────────────────

PRODUCT_FIELDS = """
    id
    title
    description
    images(first: 1) { edges { node { url } } }
    variants(first: 30) {
      edges {
        node {
          id
          title
          availableForSale
          price { amount currencyCode }
          selectedOptions { name value }
          image { url }
        }
      }
    }
"""

# ── Admin API ─────────────────────────────────────────────────────────────────

async def admin_list_products(client: ShopifyGraphQLClient, first: int = 50, after: Optional[str] = None) -> dict:
    """
    Fetch a single page of products from the Shopify Admin API.
    Returns the raw `products` dict including `edges` and `pageInfo`.
    """
    cursor_arg = f', after: "{after}"' if after else ""
    gql = f"""
    query getProducts {{
      products(first: {first}{cursor_arg}) {{
        pageInfo {{ hasNextPage endCursor }}
        edges {{
          node {{
            id
            title
            description
            vendor
            productType
            tags
            updatedAt
            status
            images(first: 1) {{
              edges {{
                node {{
                  url
                }}
              }}
            }}
            variants(first: 1) {{
              edges {{
                node {{
                  price
                  inventoryQuantity
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """
    data = await client.execute_admin(gql)
    return data.get("products", {})


async def admin_fetch_all_products(client: ShopifyGraphQLClient) -> list[dict]:
    """
    Paginate through ALL products in the Admin API.
    Returns a flat list of product nodes.
    """
    all_products: list[dict] = []
    cursor: Optional[str] = None

    while True:
        page = await admin_list_products(client, first=50, after=cursor)
        edges = page.get("edges", [])

        for edge in edges:
            all_products.append(edge["node"])

        page_info = page.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    logger.info(f"admin_fetch_all_products: fetched {len(all_products)} total products")
    return all_products


# ── Storefront API ────────────────────────────────────────────────────────────

async def storefront_search_products(
    client: ShopifyGraphQLClient,
    query: str = "",
    first: int = 12,
    after: Optional[str] = None,
) -> dict:
    """
    Search/browse products via Storefront API.
    Returns the raw `products` dict with `edges` and `pageInfo`.
    """
    after_arg = f', after: "{after}"' if after else ""
    query_filter = f', query: "{query} available_for_sale:true"' if query.strip() else ""

    gql = f"""
    query searchProducts {{
      products(first: {first}{after_arg}{query_filter}) {{
        pageInfo {{ hasNextPage endCursor }}
        edges {{
          node {{
            {PRODUCT_FIELDS}
          }}
        }}
      }}
    }}
    """
    data = await client.execute_storefront(gql)
    return data.get("products", {})


async def storefront_list_collections(client: ShopifyGraphQLClient, first: int = 20) -> dict:
    """
    List all collections via Storefront API.
    Returns the raw `collections` dict.
    """
    gql = f"""
    query getCollections {{
      collections(first: {first}) {{
        edges {{
          node {{
            id
            title
            handle
          }}
        }}
      }}
    }}
    """
    data = await client.execute_storefront(gql)
    return data.get("collections", {})


async def storefront_collection_products(
    client: ShopifyGraphQLClient,
    collection_id: str,
    first: int = 12,
    after: Optional[str] = None,
) -> dict:
    """
    Fetch products in a specific collection via Storefront API.
    Returns the raw `collection` dict (containing `products`).
    """
    after_arg = f', after: "{after}"' if after else ""
    gql = f"""
    query getCollectionProducts($id: ID!) {{
      collection(id: $id) {{
        title
        products(first: {first}{after_arg}, filters: {{ available: true }}) {{
          pageInfo {{ hasNextPage endCursor }}
          edges {{
            node {{
              {PRODUCT_FIELDS}
            }}
          }}
        }}
      }}
    }}
    """
    data = await client.execute_storefront(gql, {"id": collection_id})
    return data.get("collection", {})


async def storefront_product_details(client: ShopifyGraphQLClient, product_id: str) -> Optional[dict]:
    """
    Fetch a single product's details via Storefront API.
    Returns the raw product node dict, or None if not found.
    """
    gql = """
    query getProductDetails($id: ID) {
      product(id: $id) {
        id
        title
        description
        vendor
        productType
        images(first: 1) { edges { node { url } } }
        variants(first: 30) {
          edges {
            node {
              id
              title
              availableForSale
              price { amount currencyCode }
              selectedOptions { name value }
              image { url }
            }
          }
        }
      }
    }
    """
    data = await client.execute_storefront(gql, {"id": product_id})
    return data.get("product")


async def storefront_nodes_products(client: ShopifyGraphQLClient, ids: list[str]) -> list[dict]:
    """
    Batch-fetch products by a list of Shopify GID strings via Storefront API.
    Returns a list of raw product node dicts (None entries are filtered out).
    """
    if not ids:
        return []

    gql = """
    query nodesFetch($ids: [ID!]!) {
      nodes(ids: $ids) {
        ... on Product {
          id
          title
          description
          images(first: 1) { edges { node { url } } }
          variants(first: 1) {
            edges {
              node {
                id
                price { amount currencyCode }
                availableForSale
              }
            }
          }
        }
      }
    }
    """
    data = await client.execute_storefront(gql, {"ids": ids})
    nodes = data.get("nodes", [])
    return [n for n in nodes if n]  # filter out null entries
