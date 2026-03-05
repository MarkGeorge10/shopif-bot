# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Builder — install system packages and Python dependencies
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System dependencies needed by psycopg2, torch, Pillow, and httpx
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a local prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Pre-download the embedding model at build time ──────────────────────────
# This bakes the model into the image so Cloud Run never needs to reach
# HuggingFace at runtime (avoids 429 rate-limits on cold starts).
ENV SENTENCE_TRANSFORMERS_HOME=/model_cache
RUN PYTHONPATH=/install/lib/python3.11/site-packages \
    python -c "\
    import os; \
    os.makedirs('/model_cache', exist_ok=True); \
    from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('clip-ViT-B-32', cache_folder='/model_cache'); \
    print('Model clip-ViT-B-32 pre-downloaded successfully.') \
    "


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Runtime image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system libraries only (no build tools)
# libatomic1 is required by Prisma's embedded Node.js binary (used by `prisma generate`)
# openssl is required by the Prisma query engine binary at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libatomic1 \
    openssl \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Create a non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Prisma Python downloads a query-engine binary during `prisma generate`.
# Set PRISMA_BINARY_CACHE_DIR so it downloads into /app/.cache instead of /root/.cache
ENV PRISMA_BINARY_CACHE_DIR=/app/.cache/prisma-python/binaries
RUN mkdir -p /app/.cache/prisma-python/binaries && \
    prisma generate && \
    chown -R appuser:appgroup /app/.cache

# ── HuggingFace / SentenceTransformers — bundled model, offline mode ───────────
# clip-ViT-B-32 is pre-downloaded at build time into /model_cache (from builder).
# HF_HUB_OFFLINE=1 prevents any attempt to reach hub.huggingface.co at runtime.
# HF_HOME / HF_HUB_CACHE / TRANSFORMERS_CACHE still point to /tmp for any
# auxiliary files the libraries may try to write at runtime.
COPY --from=builder /model_cache /model_cache
ENV HF_HOME=/tmp/huggingface \
    HF_HUB_CACHE=/tmp/huggingface/hub \
    TRANSFORMERS_CACHE=/tmp/huggingface/transformers \
    SENTENCE_TRANSFORMERS_HOME=/model_cache \
    HF_HUB_OFFLINE=1

USER appuser

# ─────────────────────────────────────────────────────────────────────────────
# Default command — single worker (Cloud Run scales via instances, not workers)
# Override CMD for the Celery worker service.
# ─────────────────────────────────────────────────────────────────────────────
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"]
