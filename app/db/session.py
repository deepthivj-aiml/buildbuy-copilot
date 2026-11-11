"""Database session / engine helpers — LEGACY / FUTURE STORAGE ONLY.

Live-data-only (2026-11-10): the live flow (``app/live.py`` + the
Streamlit session) NEVER imports or calls this module — no table is
created, no row is read or written, because there is no storage to
store in. This module exists only for the legacy stored-data API
(``app/api/routes.py``) and the internal eval / observability
rollups, which tests call explicitly via ``init_db()``. It is kept,
not deleted, so those internal paths still work — but the deployed
app does not use it. ``init_db()`` runs on backend startup ONLY when
``STORAGE_ENABLED=true`` (see ``app/main.py``).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base


def get_engine():
    settings = get_settings()
    url = settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create all tables (safe to call repeatedly)."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
