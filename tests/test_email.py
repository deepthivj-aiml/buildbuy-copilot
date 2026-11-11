"""Tests for the email service (app/email/).

MockSMTP by default: nothing real is ever sent. Same idempotency key
returns "duplicate" without re-sending.

Run alone:  .venv/bin/python -m pytest tests/test_email.py -v
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "test_email.db")
os.environ["EMAIL_PROVIDER"] = "mock"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal, init_db  # noqa: E402
from app.email import EmailService, drain_outbox, idempotency_key  # noqa: E402
from app.email.service import mock_mail_dir  # noqa: E402

init_db()


def test_mock_send_and_idempotent_duplicate():
    db = SessionLocal()
    service = EmailService(db)
    first = service.send(to="supplier@example.invalid", subject="Quote request",
                         body="Please quote 50 steel brackets.",
                         deal_id="deal-1", supplier_id="sup-1")
    assert first["status"] == "mock_sent"
    assert first["idempotency_key"] == idempotency_key("deal-1", "sup-1", 1)
    assert Path(first["file"]).exists()
    assert "X-Mock: true" in Path(first["file"]).read_text()
    second = service.send(to="supplier@example.invalid", subject="Quote request",
                          body="Please quote 50 steel brackets.",
                          deal_id="deal-1", supplier_id="sup-1")
    assert second["status"] == "duplicate"  # same key: no second send
    db.close()


def test_draft_quote_and_outbox_drain():
    db = SessionLocal()
    service = EmailService(db)
    draft = EmailService.draft_quote(
        buyer_name="the buyer",
        items=[{"item": "steel brackets", "quantity": 50, "unit": "units"}],
        location="Fremont, CA", deadline="2026-11-14", max_price=400,
        share_contact=False)
    assert "steel brackets" in draft
    assert "deepthiag26@gmail.com" not in draft  # contact sharing OFF
    service.queue_outbox(deal_id="deal-2", supplier_id="sup-2",
                         kind="quote_request",
                         payload={"to": "s@example.invalid", "subject": "Q",
                                  "body": draft})
    drained = drain_outbox(db)
    assert drained["sent"] >= 1
    db.close()
