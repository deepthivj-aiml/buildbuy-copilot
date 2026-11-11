"""Tests for records / exports (app/records/).

Requirement -> invoice audit trail as CSV / JSON / summary. Invoices are
recorded only from supplier-supplied data — nothing is invented here.

Run alone:  .venv/bin/python -m pytest tests/test_records.py -v
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "test_records.db")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import Invoice, Requirement, User  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.records import build_export, build_records, to_csv, to_json  # noqa: E402

init_db()


def _seed():
    import uuid

    db = SessionLocal()
    # Unique email per seed: all test files share one temp DB per pytest
    # run (settings are cached), so a fixed email collides on 2nd use.
    user = User(email=f"records-{uuid.uuid4().hex[:8]}@example.com")
    db.add(user)
    db.commit()
    req = Requirement(user_id=user.id, source_type="typed",
                      raw_text="steel brackets, 50 units",
                      items=[{"item": "steel brackets", "quantity": 50, "unit": "units"}])
    db.add(req)
    db.commit()
    return db, req


def test_build_records_and_csv_json_roundtrip():
    db, req = _seed()
    records = build_records(req, db)
    assert records["requirement"]["id"] == req.id
    assert records["requirement"]["raw_text"] == "steel brackets, 50 units"
    csv_bytes = to_csv(records)
    assert b"steel brackets" in csv_bytes
    json_bytes = to_json(records)
    assert req.id.encode() in json_bytes
    db.close()


def test_invoice_appears_only_when_recorded():
    db, req = _seed()
    records = build_records(req, db)
    assert records["invoices"] == []  # no invoice invented
    db.add(Invoice(requirement_id=req.id, invoice_number="INV-2026-001",
                   amount=300, currency="USD", supplier_id="sup-1"))
    db.commit()
    records = build_records(req, db)
    assert len(records["invoices"]) == 1
    assert records["invoices"][0]["invoice_number"] == "INV-2026-001"
    assert b"INV-2026-001" in to_csv(records)
    export = build_export(req, db)
    assert export["summary_filename"].endswith((".pdf", ".txt"))
    assert b"INV-2026-001" in export["csv"]
    db.close()
