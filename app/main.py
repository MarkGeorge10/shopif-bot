import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import prisma

from app.api.endpoints import auth, store, billing, cart, webhooks, chat, products, public
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Structured logging setup ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to the database on startup
    try:
        await prisma.connect()
        logger.info("Connected to Prisma database.")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
    
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

# Set all CORS enabled origins
cors_origins = settings.BACKEND_CORS_ORIGINS or ["http://localhost:3000"]
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

