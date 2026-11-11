"""Structured JSON logging with a ``request_id`` on every line.

One request ID per user action follows the request through API -> agents
-> email, so a bad answer can be traced back to the exact step that
produced it (plan §9.2). No PII is logged: values are redacted before
logging (see :func:`redact_pii`).
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import uuid
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?1?[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{4}")
_CARD_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")


def new_request_id() -> str:
    """Generate a fresh request ID (UUID4 hex, short form)."""
    return uuid.uuid4().hex[:12]


def redact_pii(text: str) -> str:
    """Replace emails / phones / card numbers with ``[REDACTED]``.

    Cheap deterministic redaction for logs. Full Presidio redaction lives
    in the guardrails module (other worker); this is the log-layer safety
    net so a raw value never lands in a log line by accident.
    """
    text = _EMAIL_RE.sub("[REDACTED-EMAIL]", text)
    text = _CARD_RE.sub("[REDACTED-CARD]", text)
    text = _PHONE_RE.sub("[REDACTED-PHONE]", text)
    return text


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "message": redact_pii(record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update({k: redact_pii(str(v)) for k, v in extra.items()})
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure the root logger with the JSON formatter (idempotent)."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").handlers = [handler]
    return logging.getLogger("buildbuy")


def log_event(logger: logging.Logger, step: str, **fields: object) -> None:
    """Log one structured event line for a pipeline step.

    ``fields`` are redacted automatically. Never pass raw prompts, plan
    text, or email bodies here — IDs and hashes only.
    """
    logger.info(step, extra={"fields": {"step": step, **fields}})
