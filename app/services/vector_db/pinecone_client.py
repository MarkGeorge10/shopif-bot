"""
Pinecone Vector DB client — Cloud Run / multiprocess safe.

Lifecycle contract
──────────────────
• import time  : zero side-effects (no API call, no embedding load)
• first call to get_pinecone_client() : PineconeClient() is constructed once,
  but stays dormant until .initialize() is called explicitly
• .initialize()  : called from the FastAPI lifespan event (main.py) or from
  indexer tasks — connects to Pinecone and creates the index if missing

The module-level `pinecone_client` name is a lazy proxy so all existing
import-and-use call sites (indexer.py, providers.py, main.py) work
without modification.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Client class
# ─────────────────────────────────────────────────────────────────────────────

class PineconeClient:
    """
    Lazy Pinecone client.

    Construction is a no-op — no network calls, no embedding model load.
    Callers must explicitly call .initialize() before using .index.
    initialize() is idempotent and safe to call multiple times.
    """

    def __init__(self) -> None:
        self.api_key: str = settings.PINECONE_API_KEY
        self.index_name: str = settings.PINECONE_INDEX_NAME
        self.pc: Optional[Pinecone] = None
        self.index = None
        # Dimension is resolved lazily from the embedding service — NOT here.
        self._dimension: Optional[int] = None

    # ── Lazy dimension ──────────────────────────────────────────────────────
    @property
    def dimension(self) -> int:
        """
        Resolve embedding dimension on first access.
        Deferred import prevents embedding model from loading at import time.
        """
        if self._dimension is None:
            from app.services.vector_db.embedding import get_embedding_dimension  # noqa: PLC0415
            self._dimension = get_embedding_dimension()
        return self._dimension

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def initialize(self) -> None:
        """
        Connect to Pinecone and ensure the index exists.
        Safe to call multiple times — skips work if already initialised.
        """
        if self.index is not None:
            return  # already initialised — idempotent

        if not self.api_key or not self.index_name:
            logger.warning(
                "[PINECONE] API key or index name not configured — "
                "Pinecone client will remain inactive."
            )
            return

        logger.info(
            f"[PINECONE] Initialising client (gRPC) for index '{self.index_name}'…"
        )
        
        # Only initialize the client once to prevent connection leaks
        if self.pc is None:
            self.pc = Pinecone(api_key=self.api_key)

        # Retry list_indexes up to 3 times to handle intermittent network timeouts
        import time
        existing = []
        for attempt in range(3):
            try:
                indexes = self.pc.list_indexes()
                # Handle both pinecone v6 (IndexModel) and older dict representations
                existing = [getattr(idx, "name", idx.get("name") if isinstance(idx, dict) else None) for idx in indexes]
                break
            except Exception as e:
                logger.warning(f"[PINECONE] list_indexes error (attempt {attempt+1}): {e}")
                if attempt == 2:
                    raise
                time.sleep(2)
                
        if self.index_name not in existing:
            dim = self.dimension  # triggers model load only if index is missing
            logger.info(
                f"[PINECONE] Creating index '{self.index_name}' "
                f"(dim={dim}, metric=cosine)…"
            )
            self.pc.create_index(
                name=self.index_name,
                dimension=dim,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=settings.PINECONE_CLOUD,
                    region=settings.PINECONE_REGION,
                ),
            )

        self.index = self.pc.Index(self.index_name)
        logger.info("[PINECONE] Client initialised successfully.")

    # ── Helpers ──────────────────────────────────────────────────────────────
    def get_store_namespace(self, store_id: str) -> str:
        """Return the isolated Pinecone namespace for a specific store."""
        return f"{settings.PINECONE_NAMESPACE_PREFIX}{store_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Lazy singleton factory
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_pinecone_client() -> PineconeClient:
    """
    Return the cached PineconeClient instance.
    Construction only happens on first call — safe to import everywhere.
    """
    return PineconeClient()


# ─────────────────────────────────────────────────────────────────────────────
# Module-level alias — preserves backward compatibility with all existing
# call sites: `from app.services.vector_db.pinecone_client import pinecone_client`
# ─────────────────────────────────────────────────────────────────────────────
pinecone_client = get_pinecone_client()
