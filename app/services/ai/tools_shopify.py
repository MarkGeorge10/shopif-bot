"""
Shopify tool implementations — called by the Tool Registry during AI chat.

Each tool function receives a ShopifyGraphQLClient and the tool arguments,
executes the appropriate Shopify GraphQL query, and returns a normalized dict
that gets sent back to Gemini as the function response.

All GraphQL queries are ported from the frontend's app/actions.ts.
"""
import logging
from typing import Any

from app.services.shopify.client import ShopifyGraphQLClient

logger = logging.getLogger("ai.tools_shopify")


# ── Shared GQL fragment and Parsers ──────────────────────────────────────────

_PRODUCT_FIELDS = """
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


def _parse_variants(variant_edges: list[dict]) -> list[dict]:
    variants = []
    for edge in variant_edges:
        v = edge.get("node", {})
        variants.append({
            "id": v.get("id", ""),
            "title": v.get("title", ""),
            "available": v.get("availableForSale", True),
            "price": v.get("price", {}).get("amount", "0.00"),
            "currency": v.get("price", {}).get("currencyCode", "USD"),
            "image_url": v.get("image", {}).get("url") if v.get("image") else None,
            "options": [
                {"name": o["name"], "value": o["value"]}
                for o in v.get("selectedOptions", [])
            ],
        })
    return variants


def _parse_products(edges: list[dict]) -> list[dict]:
    products = []
    for edge in edges:
        node = edge.get("node", {})
        variant_edges = node.get("variants", {}).get("edges", [])
        variants = _parse_variants(variant_edges)

        first_variant = variants[0] if variants else None
        first_image = None
        image_edges = node.get("images", {}).get("edges", [])
        if image_edges:
            first_image = image_edges[0].get("node", {}).get("url")

        option_names = []
        if variants and variants[0].get("options"):
            option_names = [o["name"] for o in variants[0]["options"]]

        products.append({
            "id": node.get("id", ""),
            "title": node.get("title", ""),
            "description": (node.get("description", "") or "")[:200],
            "image_url": first_image,
            "price": first_variant["price"] if first_variant else "0.00",
            "currency": first_variant["currency"] if first_variant else "USD",
            "variant_id": first_variant["id"] if first_variant else None,
            "variants": variants,
            "option_names": option_names,
        })
    return products


# ── search_products ───────────────────────────────────────────────────────────

async def tool_search_products(
    client: ShopifyGraphQLClient,
    query: str = "",
    **kwargs,
) -> dict[str, Any]:
    """Search the Shopify catalog for products. Supports constraints mapping for enhanced search engines."""
    from app.core.database import prisma
    from app.services.search.providers import ShopifyNativeSearchProvider, PineconeSearchProvider
    
    # 1. Look up the Store to determine the search engine
    store = None
    if client.store_id:
        store = await prisma.store.find_unique(where={"id": client.store_id})
        
    enhanced = store.enhanced_search_enabled if store else False
    image_bytes = kwargs.get("image_bytes")
    
    # 2. Select Provider
    products = []
    
    if enhanced:
        constraints = kwargs.get("constraints", {})
        try:
            # Try Pinecone first
            pinecone_provider = PineconeSearchProvider()
            products = await pinecone_provider.search(
                store_id=client.store_id, 
                client=client, 
                query=query, 
                image_bytes=image_bytes,
                constraints=constraints
            )
            
            # Fallback condition: 
            # If we didn't get results AND it's a text-only query, OR the index is still building
            if (len(products) == 0 or store.rag_index_status != "ready") and not image_bytes:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Pinecone returned {len(products)} results (Status: {store.rag_index_status}). Falling back to native search.")
                
                native_provider = ShopifyNativeSearchProvider()
                native_products = await native_provider.search(
                    store_id=client.store_id, 
                    client=client, 
                    query=query, 
                    image_bytes=None,
                    constraints={}
                )
                
                if len(products) == 0:
                    products = native_products
                else:
                    seen = {p.get("id") for p in products if p.get("id")}
                    for np in native_products:
                        if np.get("id") not in seen:
                            products.append(np)
                            seen.add(np.get("id"))
                            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Pinecone search failed ({e}). Falling back to native search.")
            if not image_bytes:
                native_provider = ShopifyNativeSearchProvider()
                products = await native_provider.search(
                    store_id=client.store_id, 
                    client=client, 
                    query=query, 
                    image_bytes=None,
                    constraints={}
                )
    else:
        native_provider = ShopifyNativeSearchProvider()
        products = await native_provider.search(
            store_id=client.store_id, 
            client=client, 
            query=query, 
            image_bytes=None,
            constraints={}
        )
    
    # We no longer rely strictly on pageInfo for vector searches, but we keep the schema stable
    return {
        "productsFound": len(products), 
        "products": products,
        "page_info": {
            "has_next_page": False,
            "end_cursor": None,
        }
    }


# ── get_product_details ───────────────────────────────────────────────────────

async def tool_get_product_details(
    client: ShopifyGraphQLClient,
    product_id: str | None = None,
    handle: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Get full details for a specific product."""
    if not product_id and not handle:
        return {"error": "You must provide either a product_id or a handle to retrieve product details."}
    if handle:
        gql = """
        query getProductDetails($handle: String!) {
          product(handle: $handle) {
            id
            title
            description
            vendor
            productType
            images(first: 5) { edges { node { url } } }
            variants(first: 20) {
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
        data = await client.execute_storefront(gql, {"handle": handle})
    else:
        gql = """
        query getProductDetails($id: ID!) {
          product(id: $id) {
            id
            title
            description
            vendor
            productType
            images(first: 5) { edges { node { url } } }
            variants(first: 20) {
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
        # Ensure it's a valid GID if it just came as a number
        clean_id = product_id
        if clean_id and "gid://" not in clean_id:
            clean_id = f"gid://shopify/Product/{clean_id}"
            
        data = await client.execute_storefront(gql, {"id": clean_id})
    return data.get("product") or {"error": "Product not found"}


# ── get_policy ────────────────────────────────────────────────────────────────

async def tool_get_policy(
    client: ShopifyGraphQLClient,
    type: str = "shippingPolicy",
    **kwargs,
) -> dict[str, Any]:
    """Get store policies (shipping, refund, privacy, terms)."""
    gql = """
    query getShopPolicies {
      shop {
        privacyPolicy { title body }
        refundPolicy { title body }
        shippingPolicy { title body }
        termsOfService { title body }
      }
    }
    """
    data = await client.execute_storefront(gql)
    shop = data.get("shop", {})
    return {"policies": shop}


# ── get_collections ───────────────────────────────────────────────────────────

async def tool_get_collections(
    client: ShopifyGraphQLClient,
    **kwargs,
) -> dict[str, Any]:
    """List available product collections."""
    gql = """
    query getCollections {
      collections(first: 15) {
        edges {
          node {
            id
            title
            handle
          }
        }
      }
    }
    """
    data = await client.execute_storefront(gql)
    collections = [
        {"id": e["node"]["id"], "title": e["node"]["title"], "handle": e["node"]["handle"]}
        for e in data.get("collections", {}).get("edges", [])
    ]
    return {"collections": collections}


# ── get_products_in_collection ────────────────────────────────────────────────

async def tool_get_products_in_collection(
    client: ShopifyGraphQLClient,
    collection_id: str,
    after: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Get products within a specific collection."""
    after_arg = f', after: "{after}"' if after else ""
    gql = f"""
    query getCollectionProducts($id: ID!) {{
      collection(id: $id) {{
        products(first: 12{after_arg}) {{
          pageInfo {{ hasNextPage endCursor }}
          edges {{
            node {{
              {_PRODUCT_FIELDS}
            }}
          }}
        }}
      }}
    }}
    """
    data = await client.execute_storefront(gql, {"id": collection_id})
    products_data = data.get("collection", {}).get("products", {})
    products = _parse_products(products_data.get("edges", []))
    
    return {
        "productsFound": len(products), 
        "products": products,
        "page_info": {
            "has_next_page": products_data.get("pageInfo", {}).get("hasNextPage", False),
            "end_cursor": products_data.get("pageInfo", {}).get("endCursor"),
        }
    }


# ── manage_cart ───────────────────────────────────────────────────────────────

CART_FIELDS = """
    id
    checkoutUrl
    lines(first: 50) {
      edges {
        node {
          id
          quantity
          merchandise {
            ... on ProductVariant {
              id
              title
              price { amount currencyCode }
              image { url }
            }
          }
        }
      }
    }
    cost {
      subtotalAmount { amount currencyCode }
      totalAmount { amount currencyCode }
    }
"""

async def tool_manage_cart(
    client: ShopifyGraphQLClient,
    action: str = "create",
    cart_id: str | None = None,
    variant_id: str | None = None,
    quantity: int = 1,
    **kwargs,
) -> dict[str, Any]:
    """Create or update a shopping cart via Storefront API."""
    # Enforce integer quantity
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1

    # Use the session cart_id if the tool doesn't provide one
    effective_cart_id = cart_id or kwargs.get("cart_id")

    if action in ["add_lines", "remove_lines"] and not variant_id:
        return {"error": f"You must provide a variant_id to {action}."}

    if action == "create":
        mutation = f"""
        mutation cartCreate($input: CartInput) {{
          cartCreate(input: $input) {{
            cart {{ {CART_FIELDS} }}
            userErrors {{ field message }}
          }}
        }}
        """
        lines = [{"merchandiseId": variant_id, "quantity": quantity}] if variant_id else []
        input_data = {"lines": lines}
        
        # If the AI knows the user's email, auto-link the cart to them
        shopper_email = kwargs.get("shopper_email")
        if shopper_email:
            input_data["buyerIdentity"] = {"email": shopper_email}

        data = await client.execute_storefront(mutation, {"input": input_data})
        return data.get("cartCreate", {})

    elif action == "add_lines" and effective_cart_id:
        mutation = f"""
        mutation cartLinesAdd($cartId: ID!, $lines: [CartLineInput!]!) {{
          cartLinesAdd(cartId: $cartId, lines: $lines) {{
            cart {{ {CART_FIELDS} }}
            userErrors {{ field message }}
          }}
        }}
        """
        data = await client.execute_storefront(
            mutation,
            {"cartId": effective_cart_id, "lines": [{"merchandiseId": variant_id, "quantity": quantity}]},
        )
        return data.get("cartLinesAdd", {})

    elif action == "remove_lines" and effective_cart_id:
        mutation = f"""
        mutation cartLinesRemove($cartId: ID!, $lineIds: [ID!]!) {{
          cartLinesRemove(cartId: $cartId, lineIds: $lineIds) {{
            cart {{ {CART_FIELDS} }}
            userErrors {{ field message }}
          }}
        }}
        """
        data = await client.execute_storefront(
            mutation, {"cartId": effective_cart_id, "lineIds": [variant_id]}
        )
        return data.get("cartLinesRemove", {})

    elif action == "get" and effective_cart_id:
        query = f"""
        query getCart($id: ID!) {{
          cart(id: $id) {{ {CART_FIELDS} }}
        }}
        """
        data = await client.execute_storefront(query, {"id": effective_cart_id})
        return {"cart": data.get("cart")}

    return {"error": f"Invalid cart action: {action}"}


# ── create_checkout ───────────────────────────────────────────────────────────

async def tool_create_checkout(
    client: ShopifyGraphQLClient,
    variant_id: str = "",
    quantity: int = 1,
    **kwargs,
) -> dict[str, Any]:
    """Generate a direct checkout URL via cartCreate."""
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1

    mutation = """
    mutation cartCreate($input: CartInput!) {
      cartCreate(input: $input) {
        cart { id checkoutUrl }
        userErrors { field message }
      }
    }
    """
    data = await client.execute_storefront(
        mutation,
        {"input": {"lines": [{"merchandiseId": variant_id, "quantity": quantity}]}},
    )
    cart = data.get("cartCreate", {}).get("cart", {})
    return {"checkoutUrl": cart.get("checkoutUrl"), "cartId": cart.get("id")}


# ── get_menu ──────────────────────────────────────────────────────────────────

async def tool_get_menu(
    client: ShopifyGraphQLClient,
    handle: str = "main-menu",
    **kwargs,
) -> dict[str, Any]:
    """Fetch the navigation menu structure."""
    gql = """
    query getMenu($handle: String!) {
      menu(handle: $handle) {
        id
        title
        items {
          title
          url
          items { title url }
        }
      }
    }
    """
    data = await client.execute_storefront(gql, {"handle": handle})
    return data.get("menu") or {"error": "Menu not found"}


# ── get_order_status (Admin API) ──────────────────────────────────────────────

async def tool_get_order_status(
    client: ShopifyGraphQLClient,
    order_number: str = "",
    email: str = "",
    **kwargs,
) -> dict[str, Any]:
    """Retrieve order tracking and fulfillment status via Admin API."""
    if not email:
        return {"error": "Email address is required to look up orders."}
        
    # If order_number is provided, search for that specific order.
    # Otherwise, fetch the most recent order for this email.
    if order_number:
        # Clean the order number (e.g., #1001 -> 1001)
        clean_name = order_number.strip()
        if not clean_name.startswith("#"):
            clean_name = f"#{clean_name}"
        query = f"name:'{clean_name}'"
    else:
        query = f"email:{email}"
        
    gql = """
    query getOrders($query: String!) {
      orders(first: 1, query: $query, sortKey: CREATED_AT, reverse: true) {
        edges {
          node {
            id
            name
            email
            createdAt
            displayFinancialStatus
            displayFulfillmentStatus
            statusPageUrl
            fulfillments(first: 1) {
              trackingInfo { number url company }
            }
          }
        }
      }
    }
    """
    data = await client.execute_admin(gql, {"query": query})
    edges = data.get("orders", {}).get("edges", [])
    
    if not edges:
        return {"error": f"No orders found for {order_number or email}."}
        
    order = edges[0].get("node")

    # Security: verify email matches (especially important for guest order_number lookups)
    if order.get("email", "").lower() != email.lower():
        return {"error": "Email address does not match this order record."}

    return order


async def tool_get_customer_history(
    client: ShopifyGraphQLClient,
    email: str,
    **kwargs,
) -> dict[str, Any]:
    """Retrieve the customer's purchase history to provide personalized recommendations."""
    if not email:
        return {"error": "Email address is required to fetch history."}

    gql = """
    query getCustomerHistory($query: String!) {
      orders(first: 10, query: $query, sortKey: CREATED_AT, reverse: true) {
        edges {
          node {
            id
            createdAt
            lineItems(first: 20) {
              edges {
                node {
                  title
                  product {
                    id
                    productType
                    tags
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    data = await client.execute_admin(gql, {"query": f"email:{email}"})
    edges = data.get("orders", {}).get("edges", [])
    
    history = []
    for edge in edges:
        order = edge.get("node", {})
        items = []
        for item_edge in order.get("lineItems", {}).get("edges", []):
            item = item_edge.get("node", {})
            prod = item.get("product") or {}
            items.append({
                "title": item.get("title"),
                "type": prod.get("productType"),
                "tags": prod.get("tags", []),
            })
        history.append({
            "order_date": order.get("createdAt"),
            "items": items,
        })

    return {"purchaseHistory": history}


# ── get_inventory (Admin API) ─────────────────────────────────────────────────

async def tool_get_inventory(
    client: ShopifyGraphQLClient,
    variant_id: str = "",
    **kwargs,
) -> dict[str, Any]:
    """Check physical stock levels via Admin API."""
    gql = """
    query getInventory($id: ID!) {
      productVariant(id: $id) {
        id
        title
        inventoryQuantity
        inventoryItem {
          id
          tracked
        }
      }
    }
    """
    data = await client.execute_admin(gql, {"id": variant_id})
    return data.get("productVariant") or {"error": "Variant not found"}
