import pytest
from app.services.rag.mapping import build_pinecone_metadata_filters, build_canonical_product_text

def test_build_canonical_product_text():
    title = "Test Shirt"
    desc = "A nice cotton shirt."
    vendor = "Acme Corp"
    product_type = "Apparel"
    tags = ["summer", "sale"]
    
    result = build_canonical_product_text(title, desc, vendor, product_type, tags)
    
    assert "Title: Test Shirt" in result
    assert "Brand: Acme Corp" in result
    assert "Category: Apparel" in result
    assert "Tags: summer, sale" in result
    assert "Description: A nice cotton shirt." in result
    assert result == "Title: Test Shirt | Brand: Acme Corp | Category: Apparel | Tags: summer, sale | Description: A nice cotton shirt."

def test_build_pinecone_metadata_filters_empty():
    assert build_pinecone_metadata_filters({}) == {}
    assert build_pinecone_metadata_filters(None) == {}

def test_build_pinecone_metadata_filters_vendor():
    constraints = {"vendor": "Nike"}
    result = build_pinecone_metadata_filters(constraints)
    assert result == {"vendor": {"$eq": "Nike"}}

def test_build_pinecone_metadata_filters_price():
    constraints = {"price_min": 50, "price_max": "100.5"}
    result = build_pinecone_metadata_filters(constraints)
    assert result["price"]["$gte"] == 50.0
    assert result["price"]["$lte"] == 100.5
    
    # Just min
    res_min = build_pinecone_metadata_filters({"price_min": 10})
    assert res_min["price"]["$gte"] == 10.0
    assert "$lte" not in res_min["price"]

def test_build_pinecone_metadata_filters_combined():
    constraints = {
        "vendor": "Adidas",
        "price_max": 200,
        "in_stock": True,
        "tags": "sale, clearance ",
        "product_type": "Shoes",
        "color": "Red",
        "collections": ["Spring"]
    }
    result = build_pinecone_metadata_filters(constraints)
    assert result == {
        "vendor": {"$eq": "Adidas"},
        "product_type": {"$eq": "Shoes"},
        "price": {"$lte": 200.0},
        "in_stock": {"$eq": True},
        "tags": {"$in": ["sale", "clearance"]},
        "collections": {"$in": ["Spring"]},
        "color": {"$eq": "Red"}
    }

