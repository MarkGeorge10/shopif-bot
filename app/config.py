"""
Application configuration using Pydantic Settings.
All values are loaded from environment variables (or .env file).
No secrets are hardcoded here.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days

    # Encryption (Shopify tokens at rest)
    fernet_secret_key: str

    # Stripe
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_price_id: str

    # Shopify OAuth
    shopify_client_id: str
    shopify_client_secret: str
    shopify_scopes: str = "read_products,write_cart,read_orders,read_customers"

    # App
    app_url: str
    allowed_origins: str = "http://localhost:3000"

    # Trial
    trial_days: int = 14

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
