"""
Public (unauthenticated) endpoints — scoped by store slug.

These power the customer-facing chatbot storefront that merchants
share with their end users. No JWT required.

GET  /api/public/{slug}/products          — search products
GET  /api/public/{slug}/collections       — list collections
GET  /api/public/{slug}/collections/{id}  — collection products
GET  /api/public/{slug}/product/{id}      — product details
POST /api/public/{slug}/chat              — send chat message
POST /api/public/{slug}/cart/create       — create cart
POST /api/public/{slug}/cart/add          — add to cart
POST /api/public/{slug}/cart/update       — update cart line
POST /api/public/{slug}/cart/remove       — remove from cart
"""
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import prisma
from app.services.shopify.connection import get_shop_connection_by_slug
from app.services.ai.orchestrator import process_chat_message
from app.services.ai.multimodal_live import MultimodalLiveManager
from app.services.shopify.client import ShopifyGraphQLClient

logger = logging.getLogger("api.public")
router = APIRouter()


# ── Reuse product parsing from products module ───────────────────────────────
from app.api.endpoints.products import (
    _parse_products,
    _parse_page_info,
    ProductSearchResponse,
    CollectionsResponse,
    CollectionItem,
)
from app.services.shopify import repository

_PAGE_SIZE = 12


# ── Store Info ────────────────────────────────────────────────────────────────

class PublicStoreInfo(BaseModel):
    name: str
    slug: str
    shopify_domain: str


@router.get("/{slug}/info", response_model=PublicStoreInfo)
async def get_store_info(slug: str):
    """Get basic store info by slug (for page title/branding)."""
    store = await prisma.store.find_unique(where={"slug": slug})
    if not store or not store.is_active:
        raise HTTPException(status_code=404, detail="Store not found")
    return PublicStoreInfo(name=store.name, slug=store.slug, shopify_domain=store.shopify_domain)


# ── Products ─────────────────────────────────────────────────────────────────

@router.get("/{slug}/products", response_model=ProductSearchResponse)
async def public_search_products(
    slug: str,
    q: str = Query("", description="Search query"),
    after: str | None = Query(None),
):
    client = await get_shop_connection_by_slug(slug)
    products_data = await repository.storefront_search_products(client, query=q, first=_PAGE_SIZE, after=after)
    return ProductSearchResponse(
        products=_parse_products(products_data.get("edges", [])),
        page_info=_parse_page_info(products_data.get("pageInfo", {})),
    )


@router.get("/{slug}/collections", response_model=CollectionsResponse)
async def public_list_collections(slug: str):
    client = await get_shop_connection_by_slug(slug)
    collections_data = await repository.storefront_list_collections(client)
    collections = [
        CollectionItem(id=e["node"]["id"], title=e["node"]["title"], handle=e["node"]["handle"])
        for e in collections_data.get("edges", [])
    ]
    return CollectionsResponse(collections=collections)


@router.get("/{slug}/collections/{collection_id:path}", response_model=ProductSearchResponse)
async def public_collection_products(slug: str, collection_id: str, after: str | None = Query(None)):
    client = await get_shop_connection_by_slug(slug)
    collection = await repository.storefront_collection_products(client, collection_id, first=_PAGE_SIZE, after=after)
    products_data = collection.get("products", {})
    return ProductSearchResponse(
        products=_parse_products(products_data.get("edges", [])),
        page_info=_parse_page_info(products_data.get("pageInfo", {})),
    )


@router.get("/{slug}/product/{product_id:path}")
async def public_product_details(slug: str, product_id: str):
    client = await get_shop_connection_by_slug(slug)
    product = await repository.storefront_product_details(client, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

from fastapi import File, UploadFile, Form
import os

@router.post("/{slug}/search/image", response_model=ProductSearchResponse)
async def public_visual_search(
    slug: str,
    image: UploadFile = File(...),
    q: str | None = Form(None)
):
    """
    Public visual search endpoint.
    Accepts an uploaded image and an optional text query.
    Returns composite multimodal search results from Pinecone.
    """
    from app.services.search.providers import PineconeSearchProvider
    
    store = await prisma.store.find_unique(where={"slug": slug})
    if not store or not store.is_active:
        raise HTTPException(status_code=404, detail="Store not found")
        
    if not store.enhanced_search_enabled:
        raise HTTPException(status_code=400, detail="Enhanced visual search is not enabled for this store.")

    # 1. Store image temporarily
    tmp_dir = "/tmp/shopify_ai_images"
    os.makedirs(tmp_dir, exist_ok=True)
    file_path = os.path.join(tmp_dir, f"{uuid.uuid4()}_{image.filename}")
    
    try:
        content = await image.read()
        with open(file_path, "wb") as f:
            f.write(content)
            
        # 2. Execute Multimodal Search
        client = await get_shop_connection_by_slug(slug)
        provider = PineconeSearchProvider()
        
        products = await provider.search(
            store_id=store.id,
            client=client,
            query=q,
            image_bytes=content,
            constraints={}
        )
        
        return ProductSearchResponse(
            products=products,
            page_info={"has_next_page": False, "end_cursor": None}
        )
        
    except Exception as e:
        logger.error(f"Visual search failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process visual search.")
        
    finally:
        # 3. Cleanup temp file
        if os.path.exists(file_path):
            os.remove(file_path)



# ── Chat ─────────────────────────────────────────────────────────────────────

class PublicChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    current_page: str | None = None
    image_base64: str | None = None
    shopper_email: str | None = None


class PublicChatResponse(BaseModel):
    session_id: str
    message: str
    tool_calls: list[dict] = []


@router.post("/{slug}/chat", response_model=PublicChatResponse)
async def public_chat(slug: str, body: PublicChatRequest):
    """Public chat — uses the store owner's account for AI orchestration."""
    if not body.message.strip() and not body.image_base64:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    store = await prisma.store.find_unique(where={"slug": slug})
    if not store or not store.is_active:
        raise HTTPException(status_code=404, detail="Store not found")

    result = await process_chat_message(
        user_id=store.userId,
        session_id=body.session_id,
        message=body.message.strip(),
        store_id=store.id,
        current_page=body.current_page,
        image_base64=body.image_base64,
        shopper_email=body.shopper_email,
    )

    return PublicChatResponse(
        message=result["reply"],
        session_id=result["session_id"],
        tool_calls=result.get("tool_calls")
    )

@router.websocket("/{slug}/live-chat")
async def public_live_chat(
    websocket: WebSocket,
    slug: str,
    shopper_email: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time multimodal (voice) chat with Gemini.
    """
    await websocket.accept()
    
    # Get store
    store = await prisma.store.find_first(where={"slug": slug})
    if not store:
        await websocket.close(code=4004)
        return

    # Get connection
    try:
        from app.services.shopify.connection import get_active_shop_connection
        # For simplicity, we assume user_id 1 for public storefront (system owner)
        # In multi-tenant this would be the store's owner
        client = await get_active_shop_connection(store.userId, store.id)
    except Exception as e:
        logger.error(f"Live chat connection error: {e}")
        await websocket.close(code=4001)
        return

    manager = MultimodalLiveManager(shop_domain=store.shopify_domain, shopper_email=shopper_email)
    
    try:
        await manager.stream(websocket, client)
    except WebSocketDisconnect:
        logger.info(f"Live chat disconnected for {slug}")
    except Exception as e:
        logger.error(f"Live chat error: {e}")
        await websocket.close(code=4000)


# ── Cart ─────────────────────────────────────────────────────────────────────

class CartCreateRequest(BaseModel):
    variant_id: str | None = None
    quantity: int = 1

class CartAddRequest(BaseModel):
    cart_id: str
    variant_id: str
    quantity: int = 1

class CartUpdateRequest(BaseModel):
    cart_id: str
    line_id: str
    quantity: int

class CartRemoveRequest(BaseModel):
    cart_id: str
    line_id: str

class CartSyncRequest(BaseModel):
    customer_access_token: str
    cart_id: str | None = None

# Reuse cart GQL from the cart module
from app.api.endpoints.cart import (
    CART_FIELDS,
    _parse_cart,
)

@router.post("/{slug}/cart/sync")
async def public_cart_sync(slug: str, body: CartSyncRequest):
    """
    Syncs a cart for a logged-in user.
    If cart_id is provided, attaches the customer's identity to it.
    If no cart_id, fetches the customer's existing saved cart.
    Returns the active cart.
    """
    client = await get_shop_connection_by_slug(slug)
    
    # 1. If we have a local cart, link it to the buyer identity
    if body.cart_id:
        mutation = f"""
        mutation cartBuyerIdentityUpdate($cartId: ID!, $buyerIdentity: CartBuyerIdentityInput!) {{
          cartBuyerIdentityUpdate(cartId: $cartId, buyerIdentity: $buyerIdentity) {{
            cart {{ {CART_FIELDS} }}
            userErrors {{ field message }}
          }}
        }}
        """
        vars = {
            "cartId": body.cart_id,
            "buyerIdentity": {
                "customerAccessToken": body.customer_access_token
            }
        }
        res = await client.execute_storefront(mutation, vars)
        cart_data = res.get("cartBuyerIdentityUpdate", {}).get("cart")
        
        # If the mutation fails (e.g. invalid cart_id), we fall through to fetching their existing cart
        if cart_data:
            return {"cart": _parse_cart(cart_data)}

    # 2. If no local cart (or linking failed), validate the token.
    # Note: Storefront API does not support fetching carts directly by customerAccessToken.
    query = f"""
    query validateCustomer($customerAccessToken: String!) {{
      customer(customerAccessToken: $customerAccessToken) {{
        id
      }}
    }}
    """
    res = await client.execute_storefront(query, {"customerAccessToken": body.customer_access_token})
    customer_data = res.get("customer")
    
    if not customer_data:
        raise HTTPException(status_code=401, detail="Invalid customer access token")
        
    # 3. Since we can't fetch a saved cart from the customer directly, return empty 
    # to let the frontend know.
    return {"cart": None}
    


@router.post("/{slug}/cart/create")
async def public_cart_create(slug: str, body: CartCreateRequest):
    client = await get_shop_connection_by_slug(slug)
    lines = ""
    if body.variant_id:
        lines = f', lines: [{{ merchandiseId: "{body.variant_id}", quantity: {body.quantity} }}]'
    gql = f"""
    mutation cartCreate {{
      cartCreate(input: {{{lines}}}) {{
        cart {{ {CART_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await client.execute_storefront(gql)
    result = data.get("cartCreate", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])
    return _parse_cart(result.get("cart", {}))


@router.post("/{slug}/cart/add")
async def public_cart_add(slug: str, body: CartAddRequest):
    client = await get_shop_connection_by_slug(slug)
    gql = f"""
    mutation cartLinesAdd {{
      cartLinesAdd(cartId: "{body.cart_id}", lines: [{{ merchandiseId: "{body.variant_id}", quantity: {body.quantity} }}]) {{
        cart {{ {CART_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await client.execute_storefront(gql)
    result = data.get("cartLinesAdd", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])
    return _parse_cart(result.get("cart", {}))


@router.post("/{slug}/cart/update")
async def public_cart_update(slug: str, body: CartUpdateRequest):
    client = await get_shop_connection_by_slug(slug)
    gql = f"""
    mutation cartLinesUpdate {{
      cartLinesUpdate(cartId: "{body.cart_id}", lines: [{{ id: "{body.line_id}", quantity: {body.quantity} }}]) {{
        cart {{ {CART_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await client.execute_storefront(gql)
    result = data.get("cartLinesUpdate", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])
    return _parse_cart(result.get("cart", {}))


@router.post("/{slug}/cart/remove")
async def public_cart_remove(slug: str, body: CartRemoveRequest):
    client = await get_shop_connection_by_slug(slug)
    gql = f"""
    mutation cartLinesRemove {{
      cartLinesRemove(cartId: "{body.cart_id}", lineIds: ["{body.line_id}"]) {{
        cart {{ {CART_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await client.execute_storefront(gql)
    result = data.get("cartLinesRemove", {})
    if result.get("userErrors"):
        raise HTTPException(status_code=400, detail=result["userErrors"])
    return _parse_cart(result.get("cart", {}))


# ── Customer Auth ────────────────────────────────────────────────────────────

class CustomerLoginRequest(BaseModel):
    email: str
    password: str

class CustomerRegisterRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str

class CustomerAuthResponse(BaseModel):
    access_token: str
    expires_at: str
    customer: dict

@router.post("/{slug}/customer/register", response_model=CustomerAuthResponse)
async def public_customer_register(slug: str, body: CustomerRegisterRequest):
    """Register a new customer on the Shopify store and return an access token."""
    client = await get_shop_connection_by_slug(slug)
    
    # 1. Create Customer
    gql_create = """
    mutation customerCreate($input: CustomerCreateInput!) {
      customerCreate(input: $input) {
        customer { id firstName lastName email }
        customerUserErrors { field message }
      }
    }
    """
    data_create = await client.execute_storefront(gql_create, {
        "input": {
            "firstName": body.first_name,
            "lastName": body.last_name,
            "email": body.email,
            "password": body.password
        }
    })
    create_result = data_create.get("customerCreate", {})
    
    if create_result.get("customerUserErrors"):
        errs = create_result["customerUserErrors"]
        raise HTTPException(status_code=400, detail=errs[0]["message"])
        
    customer = create_result.get("customer")
    if not customer:
        raise HTTPException(status_code=400, detail="Failed to create customer")
        
    # 2. Get Access Token
    gql_token = """
    mutation customerAccessTokenCreate($input: CustomerAccessTokenCreateInput!) {
      customerAccessTokenCreate(input: $input) {
        customerAccessToken { accessToken expiresAt }
        customerUserErrors { field message }
      }
    }
    """
    data_token = await client.execute_storefront(gql_token, {
        "input": {
            "email": body.email,
            "password": body.password
        }
    })
    token_result = data_token.get("customerAccessTokenCreate", {})
    
    if token_result.get("customerUserErrors"):
        errs = token_result["customerUserErrors"]
        raise HTTPException(status_code=400, detail=errs[0]["message"])
        
    token_info = token_result.get("customerAccessToken")
    if not token_info:
        raise HTTPException(status_code=400, detail="Failed to generate access token")
        
    return CustomerAuthResponse(
        access_token=token_info["accessToken"],
        expires_at=token_info["expiresAt"],
        customer=customer
    )


@router.post("/{slug}/customer/login", response_model=CustomerAuthResponse)
async def public_customer_login(slug: str, body: CustomerLoginRequest):
    """Login a customer and return an access token."""
    client = await get_shop_connection_by_slug(slug)
    
    gql_token = """
    mutation customerAccessTokenCreate($input: CustomerAccessTokenCreateInput!) {
      customerAccessTokenCreate(input: $input) {
        customerAccessToken { accessToken expiresAt }
        customerUserErrors { field message }
      }
    }
    """
    data_token = await client.execute_storefront(gql_token, {
        "input": {
            "email": body.email,
            "password": body.password
        }
    })
    token_result = data_token.get("customerAccessTokenCreate", {})
    
    if token_result.get("customerUserErrors"):
        errs = token_result["customerUserErrors"]
        raise HTTPException(status_code=400, detail=errs[0]["message"])
        
    token_info = token_result.get("customerAccessToken")
    if not token_info:
        raise HTTPException(status_code=400, detail="Invalid email or password")
        
    # Get customer details to return
    gql_customer = """
    query getCustomer($customerAccessToken: String!) {
      customer(customerAccessToken: $customerAccessToken) {
        id firstName lastName email
      }
    }
    """
    data_customer = await client.execute_storefront(gql_customer, {"customerAccessToken": token_info["accessToken"]})
    customer = data_customer.get("customer")
    
    if not customer:
         raise HTTPException(status_code=400, detail="Failed to fetch customer details")

    return CustomerAuthResponse(
        access_token=token_info["accessToken"],
        expires_at=token_info["expiresAt"],
        customer=customer
    )


from fastapi import Header

@router.get("/{slug}/customer/me")
async def public_customer_me(slug: str, authorization: str = Header(...)):
    """Get customer details using their Shopify access token."""
    client = await get_shop_connection_by_slug(slug)
    
    # Expected format: "Bearer <token>"
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
        
    token = authorization.split(" ")[1]
    
    gql_customer = """
    query getCustomer($customerAccessToken: String!) {
      customer(customerAccessToken: $customerAccessToken) {
        id firstName lastName email
      }
    }
    """
    data = await client.execute_storefront(gql_customer, {"customerAccessToken": token})
    customer = data.get("customer")
    
    if not customer:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
        
    return customer
