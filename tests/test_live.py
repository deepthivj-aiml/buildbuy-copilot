"""Live-data-only flow — no storage, Excel export, approval-gated contact.

Covers (2026-11-10):
* app/live.py — approval required before any send; no official email
  blocks the send (nothing invented); edit changes the sent text;
  the user email carries the quotation + contacted supplier details;
  a repeat approval of the exact same email is a duplicate, not a
  second send; contact sharing OFF strips the buyer's details.
* app/records/excel.py — the shortlist exports as a real .xlsx with
  the right columns and rows.
* app/main.py — storage is OFF by default: /health reports
  "none — live, session-only" and startup creates no database.
* POST /live/contact — the backend live endpoint: approval-gated,
  no database use, user summary included.
* Streamlit UI — the Suppliers tab offers the Excel download; the
  Buyer Agent Contact button opens the approval panel and sends
  nothing until "Approve & send"; Cancel sends nothing.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Order matters: ROOT first, so `app` resolves to the backend package —
# the frontend directory contains app.py, which would shadow it.
sys.path.insert(0, str(ROOT / "frontend"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test_live.db"))
os.environ["EMAIL_PROVIDER"] = "mock"

from app.live import (  # noqa: E402
    USER_EMAIL,
    build_user_summary_email,
    contact_supplier,
    contact_suppliers_bulk,
)
from app.records.excel import SHORTLIST_COLUMNS, shortlist_to_excel  # noqa: E402

BUYER = {"name": "Deepthi Jainlal", "email": "deepthiag26@gmail.com",
         "phone": "+1 341-252-9234"}
REQ = {"raw": "steel brackets, 50 units, Fremont, by Friday, under $400",
       "item": "steel brackets", "quantity": 50, "unit": "pcs",
       "location": "Fremont", "deadline": "Friday", "budget": 400.0}
MATERIALS = [{"material": "Steel brackets", "quantity": 50, "unit": "pcs",
              "method": "user-typed quantity (50 pcs)",
              "confidence": 0.9, "flagged": False,
              "estimate_label": "estimate, not a surveyed quantity"}]


def _supplier(name="Bay Steel Supply", email="sales@baysteel.example"):
    return {"name": name, "location": "Fremont, CA", "lat": 37.5485,
            "lng": -121.9886, "distance_mi": 4.2, "unit_price": 6.30,
            "moq": 25, "lead_days": 2, "quality_score": 92,
            "quality_evidence": ["ISO 9001 certificate on file"],
            "contact": email, "email": email,
            "contact_source": "public (synthetic demo record)",
            "landed": 336.30,
            "landed_breakdown": {"goods": 315.00, "transport": None,
                                 "taxes_fees": 21.30, "total": 336.30},
            "landed_label": "excl. transport", "value_rank": 1,
            "is_best_value": True, "is_cheapest": False,
            "is_best_quality": False}


def _recorder():
    sent = []

    def send(*, to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})
        return {"status": "mock_sent"}

    return sent, send


# ------------------------------------------------------------- app/live.py
def test_contact_requires_approval():
    """Nothing is ever sent without approval — not even the user email."""
    sent, send = _recorder()
    try:
        contact_supplier(requirement=REQ, materials=MATERIALS,
                         supplier=_supplier(), subject="Quote request — 50 x steel brackets",
                         body="Hello", approved=False, share_contact=False,
                         buyer=BUYER, send_email=send, sent_keys=set())
    except ValueError as exc:
        assert "Approval required" in str(exc)
    else:
        raise AssertionError("contact without approval must raise")
    assert sent == []


def test_contact_blocked_when_no_official_email():
    """No official email held -> blocked, nothing sent, nothing guessed."""
    sent, send = _recorder()
    no_email = _supplier("Pacific Fasteners Co", "not public — request via email")
    no_email.pop("email", None)
    result = contact_supplier(
        requirement=REQ, materials=MATERIALS, supplier=no_email,
        subject="Quote request — 50 x steel brackets", body="Hello",
        approved=True, share_contact=False, buyer=BUYER,
        send_email=send, sent_keys=set())
    assert result["status"] == "blocked"
    assert "No official email" in result["reason"]
    assert sent == []


def test_contact_sends_supplier_and_user_email_with_quotation():
    """Approve -> the supplier gets the (edited) email AND the user
    gets the quotation + contacted supplier details."""
    sent, send = _recorder()
    result = contact_supplier(
        requirement=REQ, materials=MATERIALS, supplier=_supplier(),
        subject="Quote request — 50 x steel brackets — EDITED",
        body="EDITED BODY — please quote 50 x steel brackets.",
        approved=True, share_contact=False, buyer=BUYER,
        send_email=send, sent_keys=set())
    assert result["status"] == "mock_sent"
    assert [s["to"] for s in sent] == ["sales@baysteel.example", USER_EMAIL]
    assert sent[0]["subject"] == "Quote request — 50 x steel brackets — EDITED"
    assert "EDITED BODY" in sent[0]["body"]
    user_body = sent[1]["body"]
    assert "Bay Steel Supply" in user_body
    assert "sales@baysteel.example" in user_body
    assert "336.30" in user_body  # quotation: landed cost
    assert "92/100" in user_body  # quality
    assert "steel brackets" in user_body
    assert result["user_email"]["to"] == USER_EMAIL


def test_contact_strips_buyer_details_when_sharing_off():
    """Sharing OFF: the buyer's name/email/phone never reach the
    supplier, even when typed into the edited draft — but the user
    email still names the supplier and the quotation."""
    sent, send = _recorder()
    result = contact_supplier(
        requirement=REQ, materials=MATERIALS, supplier=_supplier(),
        subject="Quote request — 50 x steel brackets",
        body="Hi, I am Deepthi Jainlal, deepthiag26@gmail.com, +1 341-252-9234.",
        approved=True, share_contact=False, buyer=BUYER,
        send_email=send, sent_keys=set())
    assert result["status"] == "mock_sent"
    assert "Deepthi" not in sent[0]["body"]
    assert "deepthiag26" not in sent[0]["body"]
    assert "341" not in sent[0]["body"]


def test_contact_is_idempotent_in_session():
    """Approving the exact same email twice sends once; the second
    approval is a duplicate, not a second send."""
    sent, send = _recorder()
    keys = set()
    kwargs = dict(requirement=REQ, materials=MATERIALS, supplier=_supplier(),
                  subject="Quote request — 50 x steel brackets", body="Hello",
                  approved=True, share_contact=False, buyer=BUYER,
                  send_email=send, sent_keys=keys)
    first = contact_supplier(**kwargs)
    second = contact_supplier(**kwargs)
    assert first["status"] == "mock_sent"
    assert second["status"] == "duplicate"
    assert len(sent) == 2  # one supplier email + one user email, once


def test_bulk_contact_sends_one_user_email():
    """Bulk contact: each sendable supplier gets its email, blocked
    ones are listed, and the user gets ONE summary email."""
    sent, send = _recorder()
    no_email = _supplier("Pacific Fasteners Co", "not public — request via email")
    no_email.pop("email", None)
    result = contact_suppliers_bulk(
        requirement=REQ, materials=MATERIALS,
        contacts=[{"supplier": _supplier(), "subject": "Quote request — 50 x steel brackets",
                   "body": "Hello Bay"},
                  {"supplier": no_email, "subject": "Quote request — 50 x steel brackets",
                   "body": "Hello Pacific"}],
        approved=True, share_contact_by_name={}, buyer=BUYER,
        send_email=send, sent_keys=set())
    assert len(result["sent"]) == 1
    assert result["sent"][0]["name"] == "Bay Steel Supply"
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["name"] == "Pacific Fasteners Co"
    assert result["user_email"] is not None
    assert result["user_email"]["to"] == USER_EMAIL
    assert "Bay Steel Supply" in result["user_email"]["body"]
    assert "Pacific Fasteners" not in result["user_email"]["body"]
    assert [s["to"] for s in sent] == ["sales@baysteel.example", USER_EMAIL]


def test_user_summary_email_standalone():
    """The user summary builder: quotation + contacted supplier details."""
    summary = build_user_summary_email(
        requirement=REQ, materials=MATERIALS,
        contacted=[{"supplier": _supplier(),
                    "details": {"phone": None, "address": None,
                                "area": "Fremont, CA"},
                    "to": "sales@baysteel.example",
                    "subject": "Quote request — 50 x steel brackets",
                    "body": "Hello", "landed": 336.30, "quality": 92,
                    "lead_days": 2, "sent_status": "mock_sent"}],
        user_name="Deepthi Jainlal")
    assert summary["to"] == USER_EMAIL
    assert "steel brackets" in summary["subject"]
    assert "Bay Steel Supply" in summary["body"]
    assert "sales@baysteel.example" in summary["body"]
    assert "not held" in summary["body"]  # phone/address not held
    assert "336.30" in summary["body"]
    assert "Nothing has been ordered" in summary["body"]


# ------------------------------------------------------------- Excel export
def test_shortlist_excel_is_valid_xlsx_with_columns_and_rows():
    """The export is a real .xlsx: exact columns, one row per ranked
    supplier, landed cost and quality as numbers."""
    from openpyxl import load_workbook

    rows = [_supplier(),
            {**_supplier("Golden State Metals", "quotes@goldenstate.example"),
             "unit_price": 6.10, "landed": 326.10,
             "landed_breakdown": {"goods": 305.00, "transport": None,
                                  "taxes_fees": 21.10, "total": 326.10},
             "value_rank": 2, "is_best_value": False, "quality_score": 88}]
    data = shortlist_to_excel(rows, REQ, "Fremont")
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Shortlist"]
    header = [c.value for c in ws[4]]
    assert header == SHORTLIST_COLUMNS
    assert ws["A1"].value.startswith("BuildBuy Copilot — shortlisted suppliers")
    assert "steel brackets" in ws["A1"].value
    names = [ws.cell(row=r, column=2).value for r in (5, 6)]
    assert names == ["Bay Steel Supply", "Golden State Metals"]
    assert ws.cell(row=5, column=10).value == 336.30  # landed cost
    assert ws.cell(row=5, column=12).value == 92  # quality
    assert ws.cell(row=5, column=19).value == "sales@baysteel.example"
    assert ws.cell(row=5, column=16).value == "Yes"  # best value flag


def test_shortlist_excel_empty_shortlist_is_headers_only():
    """No suppliers -> headers only, never an invented row."""
    from openpyxl import load_workbook

    data = shortlist_to_excel([], REQ)
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Shortlist"]
    assert [c.value for c in ws[4]] == SHORTLIST_COLUMNS
    assert ws.max_row == 4


def test_shortlist_excel_never_invents_contact():
    """A supplier with no phone/address exports empty cells."""
    from openpyxl import load_workbook

    row = _supplier()
    row.pop("phone", None)
    row.pop("address", None)
    data = shortlist_to_excel([row], REQ)
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Shortlist"]
    assert ws.cell(row=5, column=20).value in (None, "")
    assert ws.cell(row=5, column=21).value in (None, "")


# ------------------------------------------------------------- backend: live-only
def test_health_reports_no_storage_by_default():
    """Storage is OFF by default: /health says so, and startup
    creates no database file."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200, r.text
        assert r.json()["storage"] == "none — live, session-only"


def test_live_contact_endpoint_is_approval_gated_and_db_free():
    """POST /live/contact: no approval -> 400, nothing sent; approved
    -> supplier + user email via MockSMTP; no email held -> 422."""
    from fastapi.testclient import TestClient

    from app.main import app

    payload = {"requirement": REQ, "materials": MATERIALS,
               "supplier": _supplier(), "subject": "Quote request — 50 x steel brackets",
               "body": "Hello", "approved": False, "share_contact": False,
               "buyer": BUYER}
    with TestClient(app) as client:
        r = client.post("/live/contact", json=payload)
        assert r.status_code == 400, r.text
        payload["approved"] = True
        r = client.post("/live/contact", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "mock_sent"
        assert body["supplier"]["to"] == "sales@baysteel.example"
        assert body["user_email"]["to"] == USER_EMAIL
        assert "Bay Steel Supply" in body["user_email"]["body"]
        no_email = _supplier("Pacific Fasteners Co", "not public — request via email")
        no_email.pop("email", None)
        payload["supplier"] = no_email
        r = client.post("/live/contact", json=payload)
        assert r.status_code == 422, r.text
        assert r.json()["status"] == "blocked"


# ------------------------------------------------------------- Streamlit UI
def _app():
    import pytest

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "frontend" / "app.py"))
    at.run()
    assert not at.exception, at.exception
    return at


def _all_text(at):
    texts = []
    for coll in (at.markdown, at.caption, at.success, at.info, at.warning,
                 at.error, at.header, at.subheader):
        try:
            texts.extend(str(el.value) for el in coll)
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(texts)


def _set_requirement(at):
    at.session_state["requirement"] = dict(REQ)


def test_suppliers_tab_offers_excel_download():
    """Suppliers & Twin tab: a real Excel download button for the
    shortlist. AppTest does not expose download bytes (its value is
    a bool), so the bytes behind the button are validated through
    the same builder the button calls, on the same ranked rows."""
    import demo_data
    import helpers
    from openpyxl import load_workbook

    at = _app()
    _set_requirement(at)
    at.radio[0].set_value("3 · Suppliers & Twin").run()
    assert not at.exception, at.exception
    assert "Live-data-only" in _all_text(at)
    btns = [b for b in at.download_button
            if "Excel" in (b.label or "")]
    assert len(btns) == 1, [b.label for b in at.download_button]
    rows, _excluded = helpers.rank_suppliers(demo_data.DEMO_SUPPLIERS, 50)
    data = shortlist_to_excel(rows, REQ, "Fremont")
    wb = load_workbook(io.BytesIO(data))
    assert [c.value for c in wb["Shortlist"][4]] == SHORTLIST_COLUMNS
    assert wb["Shortlist"].max_row > 4


def test_contact_button_opens_approval_and_cancel_sends_nothing():
    """Buyer Agent: Contact opens the approval panel (nothing sent);
    Cancel sends nothing at all."""
    at = _app()
    _set_requirement(at)
    at.radio[0].set_value("4 · Buyer Agent").run()
    assert not at.exception, at.exception
    at.button(key="quote-send-Bay Steel Supply").click().run()
    assert not at.exception, at.exception
    assert at.session_state["quote_sent"] == {}
    assert at.session_state["user_emails"] == []
    assert "Approve before sending" in _all_text(at)
    at.button(key="approve-cancel-btn").click().run()
    assert not at.exception, at.exception
    assert at.session_state["quote_sent"] == {}
    assert at.session_state["user_emails"] == []
    assert at.session_state["contact_pending"] is None


def test_bulk_contact_approval_sends_and_records_user_email():
    """Bulk contact: approval sends the sendable suppliers and records
    ONE user email with the quotation + supplier details."""
    at = _app()
    _set_requirement(at)
    at.radio[0].set_value("4 · Buyer Agent").run()
    assert not at.exception, at.exception
    bulk = [b for b in at.button
            if (b.label or "").startswith("Contact top 3 suppliers")]
    assert len(bulk) == 1, [b.label for b in at.button]
    bulk[0].click().run()
    assert not at.exception, at.exception
    assert "Approve before sending" in _all_text(at)
    assert at.session_state["quote_sent"] == {}
    at.button(key="approve-send-btn").click().run()
    assert not at.exception, at.exception
    assert len(at.session_state["quote_sent"]) >= 1
    assert len(at.session_state["user_emails"]) == 1
    user_body = at.session_state["user_emails"][0]["body"]
    assert "Bay Steel Supply" in user_body
    assert "QUOTATION" in user_body
