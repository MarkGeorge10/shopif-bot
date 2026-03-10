"""
Multimodal Embedding Service — Cloud Run / multiprocess safe.

Lifecycle contract
──────────────────
• import time  : zero side-effects (no model download, no network I/O)
• first call to get_embedding_model() : model is downloaded / loaded once,
  result is cached by lru_cache for the lifetime of the process
• DIMENSION     : resolved via get_embedding_dimension() — also lazy, cached

Design notes
────────────
• lru_cache is process-local; each Uvicorn worker loads the model once.
• /tmp is writable on Cloud Run; all HF libraries write there automatically.
• The module-level `embedding_service` singleton is a cheap proxy — its
  constructor does NOT load the model.  Call .embed_text() / .embed_image()
  and the model is initialised on demand.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import List

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ── Cloud Run writable cache — set before any HuggingFace sub-library imports ──
_HF_BASE = os.getenv("HF_HOME", "/tmp/huggingface")
os.environ.setdefault("HF_HOME",                    _HF_BASE)
os.environ.setdefault("HF_HUB_CACHE",               os.path.join(_HF_BASE, "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE",          os.path.join(_HF_BASE, "transformers"))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME",  "/tmp/sentence_transformers")

for _d in [
    os.environ["HF_HOME"],
    os.environ["HF_HUB_CACHE"],
    os.environ["TRANSFORMERS_CACHE"],
    os.environ["SENTENCE_TRANSFORMERS_HOME"],
]:
    os.makedirs(_d, exist_ok=True)

# ── Model selection ────────────────────────────────────────────────────────────
# Override via env var to switch models without a code change.
# Default: clip-ViT-B-32 → 512 dims, multimodal (text + image via CLIP).
# For text-only (no image embedding): EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2 (384 dims)
_MODEL_NAME: str = os.getenv(
    "EMBED_MODEL_NAME",
    "clip-ViT-B-32",
)

# ── Offline mode — never reach out to HuggingFace at runtime ────────────────
# The model is pre-baked into the Docker image. Setting HF_HUB_OFFLINE=1
# prevents any attempt to contact hub.huggingface.co (avoids 429 on cold starts).
# Override with HF_HUB_OFFLINE=0 in local dev if you need model updates.
os.environ.setdefault("HF_HUB_OFFLINE", "1")


# ─────────────────────────────────────────────────────────────────────────────
# Lazy factories — cached per process, never executed at import time
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Load SentenceTransformer exactly once per worker process.
    Subsequent calls return the cached instance with no overhead.
    """
    # Deferred import keeps sentence_transformers out of the import graph
    # so the module loads instantly even when the package is heavy.
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    logger.info(f"[EMBED] Loading model '{_MODEL_NAME}' (first request)…")
    model = SentenceTransformer(_MODEL_NAME)
    logger.info(
        f"[EMBED] Model '{_MODEL_NAME}' ready — "
        f"dim={model.get_sentence_embedding_dimension()}"
    )
    return model


@lru_cache(maxsize=1)
def get_embedding_dimension() -> int:
    """
    Return the vector dimension of the active embedding model.
    Loads the model if not already loaded (same lru_cache slot).
    """
    return get_embedding_model().get_sentence_embedding_dimension()


@lru_cache(maxsize=1)
def get_embedding_service() -> "MultimodalEmbeddingService":
    """Return the cached singleton EmbeddingService instance."""
    return MultimodalEmbeddingService()


# ─────────────────────────────────────────────────────────────────────────────
# Service class — constructor is intentionally a no-op
# ─────────────────────────────────────────────────────────────────────────────

class MultimodalEmbeddingService:
    """
    Thin wrapper around the cached SentenceTransformer model.

    Constructor is a no-op — safe to instantiate at module level.
    Model loading happens on the first call to any embed_* method.
    """

    # ── DIMENSION property: resolved lazily, cached after first access ──────
    _dimension: int | None = None

    @property
    def DIMENSION(self) -> int:
        """
        Vector dimension for the active model.
        Triggers model load on first access, then caches locally.
        """
        if self._dimension is None:
            self._dimension = get_embedding_dimension()
        return self._dimension

    @property
    def model(self):
        """Active SentenceTransformer instance (loaded on first access)."""
        return get_embedding_model()

    # ── CLIP token-limit constant ──────────────────────────────────────────────
    _CLIP_MAX_TOKENS = 77

    def _truncate_for_clip(self, text: str) -> str:
        """Pre-truncate *text* so that its token count stays within CLIP's
        77-token limit (including special tokens).

        The CLIPModel in sentence-transformers v3.4.x does **not** honour
        ``max_seq_length`` or ``truncate=True`` in ``encode()``.  We therefore
        tokenise → truncate → decode the text ourselves using the underlying
        CLIP processor before handing it to ``SentenceTransformer.encode()``.
        """
        clip_module = self.model._modules.get("0")  # CLIPModel layer
        if clip_module is None or not hasattr(clip_module, "processor"):
            # Fallback: crude character-level trim (≈ 4 chars per BPE token)
            return text[: self._CLIP_MAX_TOKENS * 3]

        processor = clip_module.processor
        tokens = processor.tokenizer(
            text,
            truncation=True,
            max_length=self._CLIP_MAX_TOKENS,
            return_tensors=None,
        )
        return processor.tokenizer.decode(
            tokens["input_ids"],
            skip_special_tokens=True,
        )

    # ── Public embedding API ─────────────────────────────────────────────────

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text string → float list.

        CLIP has a hard limit of 77 tokens.  We pre-truncate the text so
        that the tokenised sequence never exceeds the position-embedding
        table and avoids a ``RuntimeError`` at forward time.
        """
        safe_text = self._truncate_for_clip(text)
        return (
            self.model.encode([safe_text])[0]
            .astype("float32")
            .tolist()
        )

    def embed_image(self, image: Image.Image) -> List[float]:
        """Embed a PIL Image → float list."""
        return self.model.encode([image])[0].astype("float32").tolist()

    def combine_vectors(
        self,
        img_vec: List[float],
        txt_vec: List[float],
        w_img: float = 0.7,
        w_txt: float = 0.3,
    ) -> List[float]:
        """
        Weighted blend of image + text vectors, L2-normalised so cosine
        similarity remains meaningful in the shared embedding space.
        """
        v_img = np.array(img_vec, dtype="float32")
        v_txt = np.array(txt_vec, dtype="float32")
        combined = (v_img * w_img) + (v_txt * w_txt)
        norm = np.linalg.norm(combined)
        if norm > 0:
            combined = combined / norm
        return combined.tolist()


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton — safe: constructor does nothing
# All existing call sites continue to work unchanged.
# ─────────────────────────────────────────────────────────────────────────────
embedding_service = MultimodalEmbeddingService()
