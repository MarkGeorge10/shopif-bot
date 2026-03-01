"""
Products endpoints — search, collections, and collection products.

These hit the Shopify Storefront API via the repository layer and return data
in the format expected by the frontend's useProducts hook.

GET /api/products/search?q=&after=         — search products (paginated)
GET /api/products/collections              — list all collections
GET /api/products/collections/{id}?after=  — products in a collection (paginated)
GET /api/products/{product_id}             — single product details
"""
import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from prisma.models import User

from app.api.deps import get_current_active_user
from app.services.shopify.connection import get_active_shop_connection
from app.services.shopify import repository

logger = logging.getLogger("api.products")
router = APIRouter()

_PAGE_SIZE = 12


# ── Response Schemas ──────────────────────────────────────────────────────────

class VariantOption(BaseModel):
    name: str
    value: str


class VariantItem(BaseModel):
    id: str
    title: str = ""
    available: bool = True
    price: str = "0.00"
    currency: str = "USD"
    image_url: str | None = None
    options: list[VariantOption] = []


class ProductItem(BaseModel):
    id: str
    title: str
    description: str = ""
    image_url: str | None = None
    price: str = "0.00"
    currency: str = "USD"
    variant_id: str | None = None
    variants: list[VariantItem] = []
    option_names: list[str] = []


class PageInfoOut(BaseModel):
    has_next_page: bool = False
    end_cursor: str | None = None


class ProductSearchResponse(BaseModel):
    products: list[ProductItem] = []
    page_info: PageInfoOut = PageInfoOut()


class CollectionItem(BaseModel):
    id: str
    title: str
    handle: str


class CollectionsResponse(BaseModel):
    collections: list[CollectionItem] = []


# ── Shared parse helpers ──────────────────────────────────────────────────────

def _parse_variants(variant_edges: list[dict]) -> list[VariantItem]:
    variants = []
    for edge in variant_edges:
        v = edge.get("node", {})
        variants.append(VariantItem(
            id=v.get("id", ""),
            title=v.get("title", ""),
            available=v.get("availableForSale", True),
            price=v.get("price", {}).get("amount", "0.00"),
            currency=v.get("price", {}).get("currencyCode", "USD"),
            image_url=v.get("image", {}).get("url") if v.get("image") else None,
            options=[
                VariantOption(name=o["name"], value=o["value"])
                for o in v.get("selectedOptions", [])
            ],
        ))
    return variants


def _parse_products(edges: list[dict]) -> list[ProductItem]:
    """Parse Shopify product edges into our response schema."""
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

        option_names: list[str] = []
        if variants and variants[0].options:
            option_names = [o.name for o in variants[0].options]

        products.append(ProductItem(
            id=node.get("id", ""),
            title=node.get("title", ""),
            description=(node.get("description", "") or "")[:200],
            image_url=first_image,
            price=first_variant.price if first_variant else "0.00",
            currency=first_variant.currency if first_variant else "USD",
            variant_id=first_variant.id if first_variant else None,
            variants=variants,
            option_names=option_names,
        ))
    return products


def _parse_page_info(pi: dict) -> PageInfoOut:
    return PageInfoOut(
        has_next_page=pi.get("hasNextPage", False),
        end_cursor=pi.get("endCursor"),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/search", response_model=ProductSearchResponse)
async def search_products(
    q: str = Query("", description="Search query"),
    after: str | None = Query(None, description="Cursor for pagination"),
    current_user: User = Depends(get_current_active_user),
):
    """Search products via Storefront API. Empty query returns featured products."""
    client = await get_active_shop_connection(current_user.id)
    products_data = await repository.storefront_search_products(client, query=q, first=_PAGE_SIZE, after=after)

    return ProductSearchResponse(
        products=_parse_products(products_data.get("edges", [])),
        page_info=_parse_page_info(products_data.get("pageInfo", {})),
    )


@router.get("/collections", response_model=CollectionsResponse)
async def list_collections(
    current_user: User = Depends(get_current_active_user),
):
    """List all product collections."""
    client = await get_active_shop_connection(current_user.id)
    collections_data = await repository.storefront_list_collections(client)

    collections = [
        CollectionItem(
            id=e["node"]["id"],
            title=e["node"]["title"],
            handle=e["node"]["handle"],
        )
        for e in collections_data.get("edges", [])
    ]
    return CollectionsResponse(collections=collections)


@router.get("/collections/{collection_id:path}", response_model=ProductSearchResponse)
async def get_collection_products(
    collection_id: str,
    after: str | None = Query(None, description="Cursor for pagination"),
    current_user: User = Depends(get_current_active_user),
):
    """Get products in a specific collection (paginated)."""
    client = await get_active_shop_connection(current_user.id)
    collection = await repository.storefront_collection_products(client, collection_id, first=_PAGE_SIZE, after=after)
    products_data = collection.get("products", {})

    return ProductSearchResponse(
        products=_parse_products(products_data.get("edges", [])),
        page_info=_parse_page_info(products_data.get("pageInfo", {})),
    )


@router.get("/{product_id:path}")
async def get_product_details(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get full product details including all variants and images."""
    client = await get_active_shop_connection(current_user.id)
    product = await repository.storefront_product_details(client, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product
