"""BuildBuy Copilot — FastAPI app entrypoint.

Run locally:  ``uvicorn app.main:app --reload --port 8000``
Docs:         http://localhost:8000/docs
Health:       http://localhost:8000/health

Structured JSON logging with a ``request_id`` on every line; CORS open
for the local Streamlit frontend (restrict ``allow_origins`` in deploy).
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agents.graph import LANGGRAPH_AVAILABLE
from app.api.routes import router
from app.config import get_settings, load_env_file
from app.db.session import init_db
from app.logging_setup import new_request_id, request_id_var, setup_logging

load_env_file()
settings = get_settings()
logger = setup_logging("DEBUG" if settings.debug else "INFO")

app = FastAPI(
    title="BuildBuy Copilot",
    description=(
        "One buyer workflow: plan Q&A, takeoff, supplier search, "
        "digital-twin simulation, buyer agent (email), human approval, "
        "orders, delivery chase and invoice tracking. "
        "Nothing is ordered or paid without human approval; "
        "no supplier, quote, contact or invoice is ever invented."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Assign a request_id, time the request, log one JSON line."""
    rid = request.headers.get("X-Request-Id") or new_request_id()
    token = request_id_var.set(rid)
    started = time.monotonic()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    latency_ms = int((time.monotonic() - started) * 1000)
    response.headers["X-Request-Id"] = rid
    logger.info(
        "request",
        extra={"fields": {
            "method": request.method, "path": request.url.path,
            "status": response.status_code, "latency_ms": latency_ms,
        }},
    )
    return response


@app.on_event("startup")
def on_startup() -> None:
    # LIVE-DATA-ONLY (2026-11-10): do NOT create a database on
    # startup unless storage was explicitly enabled. The live flow
    # (app/live.py + the Streamlit session) uses no storage at all.
    if settings.storage_enabled:
        init_db()
    logger.info(
        "startup",
        extra={"fields": {
            "email_backend": "mock" if settings.is_mock_email else "smtp",
            "storage": ("enabled" if settings.storage_enabled
                        else "none — live, session-only"),
            "graph": "langgraph" if LANGGRAPH_AVAILABLE else "local-runner",
        }},
    )


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "buildbuy-copilot",
        "email_backend": "mock" if settings.is_mock_email else "smtp",
        "storage": ("postgres" if settings.storage_enabled
                    and settings.database_url.startswith("postgres")
                    else ("sqlite (legacy, enabled)" if settings.storage_enabled
                          else "none — live, session-only")),
        "graph_available": LANGGRAPH_AVAILABLE,
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error — the request was logged, no order was placed",
                 "error_type": "internal_error",
                 "request_id": request_id_var.get()},
    )


app.include_router(router)
