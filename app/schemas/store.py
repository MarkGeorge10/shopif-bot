from pydantic import BaseModel

class StoreConnectInput(BaseModel):
    shopify_domain: str
    shopify_storefront_token: str
    shopify_admin_token: str

class StoreResponse(BaseModel):
    id: str
    shopify_domain: str
    
    class Config:
        from_attributes = True
