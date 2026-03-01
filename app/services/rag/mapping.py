from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

def build_pinecone_metadata_filters(constraints: Dict[str, Any]) -> dict:
    """
    Translates LLM-supplied constraints (like price_min, price_max, vendor)
    into Pinecone's MongoDB-like filter syntax. Assumes flat metadata fields.
    """
    filter_expr = {}
    if not constraints:
        return filter_expr

    # Handle Vendor matching (case-insensitive usually, but here we do exact match per Pinecone limits)
    if "vendor" in constraints:
        filter_expr["vendor"] = {"$eq": constraints["vendor"]}

    # Product Type
    if "product_type" in constraints:
        filter_expr["product_type"] = {"$eq": constraints["product_type"]}

    # Handle Price constraints
    price_min = constraints.get("price_min")
    price_max = constraints.get("price_max")
    
    if price_min is not None or price_max is not None:
        price_filter = {}
        if price_min is not None:
            price_filter["$gte"] = float(price_min)
        if price_max is not None:
            price_filter["$lte"] = float(price_max)
        filter_expr["price"] = price_filter

    # Handle In-Stock constraints (usually boolean)
    if "in_stock" in constraints:
        filter_expr["in_stock"] = {"$eq": bool(constraints["in_stock"])}

    # Handle Arrays (Tags, Collections)
    if "tags" in constraints:
        tags = constraints["tags"]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if tags:
            filter_expr["tags"] = {"$in": tags}
            
    if "collections" in constraints:
        collections = constraints["collections"]
        if isinstance(collections, str):
            collections = [c.strip() for c in collections.split(",") if c.strip()]
        if collections:
            filter_expr["collections"] = {"$in": collections}
            
    # Optional Attributes
    if "color" in constraints:
        filter_expr["color"] = {"$eq": constraints["color"]}
    if "size" in constraints:
        filter_expr["size"] = {"$eq": constraints["size"]}

    return filter_expr

def build_canonical_product_text(title: str, description: str, vendor: str, product_type: str, tags: list) -> str:
    """
    Combines Shopify product fields into a rich string for embedding generation.
    """
    components = []
    if title: components.append(f"Title: {title}")
    if vendor: components.append(f"Brand: {vendor}")
    if product_type: components.append(f"Category: {product_type}")
    if tags: components.append(f"Tags: {', '.join(tags)}")
    if description: components.append(f"Description: {description}")
    
    return " | ".join(components)
