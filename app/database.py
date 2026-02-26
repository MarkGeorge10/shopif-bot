"""
SQLAlchemy engine and session factory.
Session is provided via FastAPI dependency injection.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,      # Verify connections before using
    pool_recycle=3600,       # Recycle connections every hour
    connect_args={"sslmode": "require"} if "supabase" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass
