"""Tests for the buyer-agent identity / escalation / contact-sharing
update (user, 2026-11-10).

- Every supplier email identifies the agent as "BuildBuy Copilot,
  acting as the buying agent for [customer]" and enquires about the
  specific part + quantity.
- A supplier question the agent cannot answer escalates: NO supplier
  reply is sent, the customer is emailed, and only after the customer
  replies does the supplier get an answer — in the customer's words.
- Contact sharing is per supplier, default OFF: OFF hides name/email/
  phone entirely; ON includes them.

MockSMTP only — no real email is ever sent.

Run alone:  .venv/bin/python -m pytest tests/test_escalation.py -v
"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "test_escalation.db")
os.environ["EMAIL_PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import init_db  # noqa: E402
from app.email.service import EmailService, mock_mail_dir  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app, raise_server_exceptions=False)

HEADERS = {"X-User-Email": "deepthiag26@gmail.com"}


def _requirement():
    r = client.post("/requirements", json={
        "source_type": "typed",
        "raw_text": "steel brackets, 50 units, Fremont, by Friday, under $400",
        "items": [{"item": "steel brackets", "quantity": 50, "unit": "units"}],
        "location": "Fremont, CA",
        "deadline": "2026-11-14",
        "budget": 400,
        "max_price": 400,
    }, headers=HEADERS)
    assert r.status_code == 201, r.text
    return r.json()


def _supplier(req_id, name="Bay Steel Supply"):
    r = client.post(f"/requirements/{req_id}/suppliers", json={
        "name": name, "location": "Fremont, CA",
        "email": "sales@baysteel.example",
        "contact_source": "public",
        "contact_source_url": "https://example.com/supplier",
        "lead_time_days": 2,
    }, headers=HEADERS)
    assert r.status_code == 201, r.text
    return r.json()


def _set_customer():
    r = client.patch("/settings", json={
        "name": "Deepthi Jainlal", "phone": "+1 341-252-9234"}, headers=HEADERS)
    assert r.status_code == 200, r.text


def _mock_files(pattern=""):
    if pattern:
        return list(mock_mail_dir().glob(f"*{pattern}*"))
    return list(mock_mail_dir().glob("*"))


# ------------------------------------------------------------ identity
def test_draft_quote_identifies_agent_and_enquires_part_quantity():
    draft = EmailService.draft_quote(
        buyer_name="Deepthi Jainlal",
        items=[{"item": "steel brackets", "quantity": 50, "unit": "units"}],
        location="Fremont, CA", deadline="2026-11-14", max_price=400,
        share_contact=False, buyer_email="deepthiag26@gmail.com",
        buyer_phone="+1 341-252-9234")
    assert "BuildBuy Copilot, acting as the buying agent for a customer" in draft
    assert "50" in draft and "steel brackets" in draft
    assert "Deepthi Jainlal" not in draft
    assert "deepthiag26@gmail.com" not in draft
    assert "341-252-9234" not in draft


def test_draft_quote_sharing_on_includes_customer_contact():
    draft = EmailService.draft_quote(
        buyer_name="Deepthi Jainlal",
        items=[{"item": "steel brackets", "quantity": 50, "unit": "units"}],
        location="Fremont, CA", deadline="2026-11-14", max_price=400,
        share_contact=True, buyer_email="deepthiag26@gmail.com",
        buyer_phone="+1 341-252-9234")
    assert "acting as the buying agent for Deepthi Jainlal" in draft
    assert "deepthiag26@gmail.com" in draft
    assert "341-252-9234" in draft


def test_buyer_send_off_hides_contact_end_to_end():
    _set_customer()
    req = _requirement()
    sup = _supplier(req["id"])
    r = client.post(f"/requirements/{req['id']}/buyer/draft", json={}, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert "acting as the buying agent for a customer" in r.json()["draft"]
    assert "Deepthi Jainlal" not in r.json()["draft"]
    r = client.post(f"/requirements/{req['id']}/buyer/send",
                    json={"share_contact": {}}, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["status"] == "queued"
    assert r.json()["results"][0]["contact_shared"] is False
    # The mock-recorded supplier email must carry the agent identity
    # and no customer contact at all.
    sent = [f for f in _mock_files("email") if "quote_request" in f.name or True]
    body = "".join(f.read_text(errors="ignore") for f in _mock_files()
                   if sup["id"] in f.name)
    assert "acting as the buying agent for a customer" in body
    assert "Deepthi Jainlal" not in body
    assert "deepthiag26@gmail.com" not in body
    assert "341-252-9234" not in body


def test_buyer_send_on_shares_contact_end_to_end():
    _set_customer()
    req = _requirement()
    sup = _supplier(req["id"], "Golden State Metals")
    client.post(f"/requirements/{req['id']}/buyer/draft", json={}, headers=HEADERS)
    r = client.post(f"/requirements/{req['id']}/buyer/send",
                    json={"share_contact": {sup["id"]: True}}, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["contact_shared"] is True
    body = "".join(f.read_text(errors="ignore") for f in _mock_files()
                   if sup["id"] in f.name)
    assert "acting as the buying agent for Deepthi Jainlal" in body
    assert "deepthiag26@gmail.com" in body
    assert "341-252-9234" in body


# ---------------------------------------------------------- escalation
def test_answerable_question_is_answered_from_requirement():
    req = _requirement()
    sup = _supplier(req["id"], "Answerable Steel")
    r = client.post(f"/requirements/{req['id']}/buyer/supplier-question", json={
        "supplier_id": sup["id"],
        "question": "Just confirming — how many steel brackets do you need, and where should they be delivered?"},
        headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "answered_from_requirement"
    assert "50" in r.json()["answer"] and "steel brackets" in r.json()["answer"]
    # No escalation was opened.
    r = client.get(f"/requirements/{req['id']}/buyer/escalations", headers=HEADERS)
    assert r.status_code == 200
    assert all(e["supplier_id"] != sup["id"] for e in r.json())


def test_unanswerable_question_escalates_then_customer_reply_reaches_supplier():
    _set_customer()
    req = _requirement()
    sup = _supplier(req["id"], "Escalation Steel")
    before = set(p.name for p in _mock_files("escalation"))
    question = "Can you pay 50% upfront before dispatch?"
    r = client.post(f"/requirements/{req['id']}/buyer/supplier-question", json={
        "supplier_id": sup["id"], "question": question}, headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "needs_customer"
    assert body["customer_email"] == "deepthiag26@gmail.com"
    esc_id = body["escalation_id"]

    # The customer was emailed; the supplier was NOT replied to.
    after = set(p.name for p in _mock_files("escalation"))
    assert after - before, "no customer escalation email was recorded"
    esc_mail = "".join(
        (mock_mail_dir() / n).read_text(errors="ignore") for n in (after - before))
    assert question in esc_mail
    assert "cannot answer" in esc_mail.lower() or "needs your help" in esc_mail
    r = client.get(f"/requirements/{req['id']}/buyer/escalations", headers=HEADERS)
    assert r.status_code == 200
    assert any(e["escalation_id"] == esc_id for e in r.json())

    # Replying to an unknown escalation is refused.
    r = client.post(f"/requirements/{req['id']}/buyer/escalations/nope/reply",
                    json={"answer": "Yes."}, headers=HEADERS)
    assert r.status_code == 404

    # The customer answers; the supplier gets it in the customer's words,
    # with the agent identity line and NO contact (sharing OFF).
    answer = "No upfront payment — I pay in full on delivery, as agreed."
    r = client.post(
        f"/requirements/{req['id']}/buyer/escalations/{esc_id}/reply",
        json={"answer": answer}, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SENT"
    assert r.json()["contact_shared"] is False
    supplier_body = "".join(f.read_text(errors="ignore") for f in _mock_files()
                            if sup["id"] in f.name and "supplier_reply" not in f.name
                            and "escalation" not in f.name)
    assert answer in supplier_body
    assert "acting as the buying agent for a customer" in supplier_body
    assert "Deepthi Jainlal" not in supplier_body
    assert "deepthiag26@gmail.com" not in supplier_body

    # Escalation is closed — a second reply to the same question is refused.
    r = client.get(f"/requirements/{req['id']}/buyer/escalations", headers=HEADERS)
    assert all(e["escalation_id"] != esc_id for e in r.json())
    r = client.post(
        f"/requirements/{req['id']}/buyer/escalations/{esc_id}/reply",
        json={"answer": "Again."}, headers=HEADERS)
    assert r.status_code == 409
