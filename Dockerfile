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

# ── HuggingFace / SentenceTransformers — Cloud Run safe paths ──────────────────
# All HF libraries write to /tmp which is always writable on Cloud Run.
# Models are loaded lazily at first request — NOT during container startup.
ENV HF_HOME=/tmp/huggingface \
    HF_HUB_CACHE=/tmp/huggingface/hub \
    TRANSFORMERS_CACHE=/tmp/huggingface/transformers \
    SENTENCE_TRANSFORMERS_HOME=/tmp/sentence_transformers

USER appuser

# ─────────────────────────────────────────────────────────────────────────────
# Default command — single worker (Cloud Run scales via instances, not workers)
# Override CMD for the Celery worker service.
# ─────────────────────────────────────────────────────────────────────────────
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"]
