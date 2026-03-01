import os
from celery import Celery
from app.core.config import settings

# Initialize Celery
# Note: we use sync execution in Celery workers, so we don't mix complex asyncio loops unless necessary.
celery_app = Celery(
    "shopify_ai_concierge",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.services.rag.indexer"] # Discover tasks here
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,       # Max 1 hour per task
    task_soft_time_limit=3300,
)
