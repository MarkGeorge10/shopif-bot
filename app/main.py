import logging
import os
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import prisma

from app.api.endpoints import auth, store, billing, cart, webhooks, chat, products, public
from app.core.config import settings
from app.services.vector_db.pinecone_client import pinecone_client

# ── Structured logging setup ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

_cloud_run = bool(os.getenv("K_SERVICE"))  # set automatically by Cloud Run
logger.info("[BOOT] API starting")
logger.info("[BOOT] Lazy embedding enabled — model loads on first request")
if _cloud_run:
    logger.info("[BOOT] Cloud Run mode detected")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to the database on startup
    try:
        # Connect to the database on startup with an extended timeout
        await prisma.connect(timeout=30)
        logger.info("Connected to Prisma database.")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        logger.error(traceback.format_exc())
        raise RuntimeError(f"FATAL: Database connection failed during startup: {e}")
        
    # Initialize Pinecone (non-blocking — errors are logged, not raised)
    try:
        pinecone_client.initialize()
        logger.info("[BOOT] Pinecone client initialized")
    except Exception as e:
        logger.error(f"[BOOT] Failed to initialize Pinecone: {e}")

    logger.info("[BOOT] Startup complete — listening for requests")

    
    yield
    
    # Disconnect from the database on shutdown
    try:
        await prisma.disconnect()
        logger.info("Disconnected from Prisma database.")
    except Exception as e:
        logger.error(f"Failed to disconnect from database: {e}")

app = FastAPI(
    title="Shopify AI Concierge Backend",
    description="Backend API for the Shopify AI Concierge SaaS App",
    version="2.0.0",
    lifespan=lifespan
)

# Set all CORS enabled origins — read from settings, fall back to env var directly,
# then guarantee localhost:3000 is always present for local dev.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
cors_origins: list[str] = (
    settings.BACKEND_CORS_ORIGINS
    or [o.strip() for o in _raw_origins.split(",") if o.strip()]
    or ["http://localhost:3000"]
)
if "http://localhost:3000" not in cors_origins:
    cors_origins.append("http://localhost:3000")

logger.info(f"[BOOT] CORS origins: {cors_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ─────────────────────────────────────────────────
# Ensures unhandled exceptions return JSON (not bare 500) so CORS headers are set.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Include API Routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(store.router, prefix="/api/store", tags=["store"])
app.include_router(billing.router, prefix="/api/billing", tags=["billing"])
app.include_router(cart.router, prefix="/api/cart", tags=["cart"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(public.router, prefix="/api/public", tags=["public"])

@app.get("/")
async def root():
    return {"message": "Welcome to the Shopify AI Concierge API"}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}

