from typing import List, Optional, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Shopify AI Concierge Backend"
    
    # Security
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    FERNET_SECRET_KEY: str
    
    # Database
    DATABASE_URL: str
    
    # Stripe
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_PRICE_ID: str
    
    # Gemini AI
    GEMINI_API_KEY: str = ""

    # Shopify
    SHOPIFY_API_VERSION: str = "2026-01"
    SHOPIFY_CLIENT_SECRET: str = ""

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = ""
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"
    PINECONE_NAMESPACE_PREFIX: str = "store_"

    # App Settings
    APP_URL: str = ""  # Set to Cloud Run URL after first deploy
    TRIAL_DAYS: int = 14
    
    # Celery & Redis
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8000,https://shopify-ai-concierge.vercel.app"
    
    @property
    def BACKEND_CORS_ORIGINS(self) -> List[str]:
        if isinstance(self.ALLOWED_ORIGINS, str):
            return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]
        return []

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra="ignore")


settings = Settings()
