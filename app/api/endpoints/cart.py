"""
Cart REST endpoints — direct Shopify Storefront API, no AI/chat involved.

POST /api/cart/create   — create a new Storefront cart
POST /api/cart/add      — add line items to an existing cart
POST /api/cart/update   — update quantity for a line item
POST /api/cart/remove   — remove a line item
GET  /api/cart/{cart_id} — fetch full cart summary
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from prisma.models import User

from app.api.deps import get_current_active_user
from app.services.shopify.connection import get_active_shop_connection
from app.schemas.cart import (
    CartCreateRequest,
    CartAddRequest,
    CartUpdateRequest,
    CartRemoveRequest,
    CartResponse,
    CartLineItem,
    CartCost,
)

logger = logging.getLogger("api.cart")
router = APIRouter()

# ── Shared GraphQL fragment ──────────────────────────────────────────────────

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


def _parse_cart(data: dict) -> CartResponse:
    """Convert raw Shopify cart data into our CartResponse schema."""
    cart_data = data if "id" in data else {}
    lines = []
    for edge in (cart_data.get("lines", {}).get("edges", [])):
        node = edge["node"]
        merch = node.get("merchandise", {})
        lines.append(CartLineItem(
            line_id=node["id"],
            variant_id=merch.get("id", ""),
            title=merch.get("title", ""),
            quantity=node["quantity"],
            price=merch.get("price", {}).get("amount", "0.00"),
            currency=merch.get("price", {}).get("currencyCode", "USD"),
            image_url=merch.get("image", {}).get("url") if merch.get("image") else None,
        ))

    cost_data = cart_data.get("cost", {})
    cost = None
    if cost_data:
        cost = CartCost(
            subtotal=cost_data.get("subtotalAmount", {}).get("amount", "0.00"),
            total=cost_data.get("totalAmount", {}).get("amount", "0.00"),
            currency=cost_data.get("totalAmount", {}).get("currencyCode", "USD"),
        )

    return CartResponse(
        cart_id=cart_data.get("id", ""),
        checkout_url=cart_data.get("checkoutUrl"),
        lines=lines,
        cost=cost,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create", response_model=CartResponse)
async def create_cart(
    body: CartCreateRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Create a new Storefront cart, optionally with an initial line item."""
    client = await get_active_shop_connection(current_user.id)

    lines_input = []
    if body.variant_id:
        lines_input = [{"merchandiseId": body.variant_id, "quantity": body.quantity}]

    mutation = f"""
    mutation cartCreate($input: CartInput) {{
      cartCreate(input: $input) {{
        cart {{ {CART_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await client.execute_storefront(
        mutation, {"input": {"lines": lines_input}}
    )

    result = data.get("cartCreate", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])

    return _parse_cart(result.get("cart", {}))


@router.post("/add", response_model=CartResponse)
async def add_to_cart(
    body: CartAddRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Add a line item to an existing cart."""
    client = await get_active_shop_connection(current_user.id)

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
        {
            "cartId": body.cart_id,
            "lines": [{"merchandiseId": body.variant_id, "quantity": body.quantity}],
        },
    )

    result = data.get("cartLinesAdd", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])

    return _parse_cart(result.get("cart", {}))


@router.post("/update", response_model=CartResponse)
async def update_cart(
    body: CartUpdateRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Update the quantity of a line item in a cart."""
    client = await get_active_shop_connection(current_user.id)

    mutation = f"""
    mutation cartLinesUpdate($cartId: ID!, $lines: [CartLineUpdateInput!]!) {{
      cartLinesUpdate(cartId: $cartId, lines: $lines) {{
        cart {{ {CART_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await client.execute_storefront(
        mutation,
        {
            "cartId": body.cart_id,
            "lines": [{"id": body.line_id, "quantity": body.quantity}],
        },
    )

    result = data.get("cartLinesUpdate", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])

    return _parse_cart(result.get("cart", {}))


@router.post("/remove", response_model=CartResponse)
async def remove_from_cart(
    body: CartRemoveRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Remove a line item from a cart."""
    client = await get_active_shop_connection(current_user.id)

    mutation = f"""
    mutation cartLinesRemove($cartId: ID!, $lineIds: [ID!]!) {{
      cartLinesRemove(cartId: $cartId, lineIds: $lineIds) {{
        cart {{ {CART_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await client.execute_storefront(
        mutation,
        {"cartId": body.cart_id, "lineIds": [body.line_id]},
    )

    result = data.get("cartLinesRemove", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])

    return _parse_cart(result.get("cart", {}))


@router.get("/{cart_id}", response_model=CartResponse)
async def get_cart(
    cart_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Fetch the current state of a cart."""
    client = await get_active_shop_connection(current_user.id)

    query = f"""
    query getCart($id: ID!) {{
      cart(id: $id) {{
        {CART_FIELDS}
      }}
    }}
    """
    data = await client.execute_storefront(query, {"id": cart_id})
    cart_data = data.get("cart")
    if not cart_data:
        raise HTTPException(status_code=404, detail="Cart not found.")

    return _parse_cart(cart_data)
