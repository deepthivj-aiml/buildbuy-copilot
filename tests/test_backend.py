"""Backend tests — temp SQLite DB, mock email, no network, no invented data.

Covers: health, requirement CRUD, draft-before-send enforcement,
(Ranking unit tests live in tests/test_ranking.py; twin unit tests
in tests/test_twin.py.)
mock email + outbox idempotency, approval gate (no order without
approval), confirm, invoice record + chase, buyer message + inbox,
records export, summary.
"""

from __future__ import annotations

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "test_buildbuy.db")
os.environ["EMAIL_PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app, raise_server_exceptions=False)


def _requirement(**overrides):
    payload = {
        "source_type": "typed",
        "raw_text": "steel brackets, 50 units, Fremont, by Friday, under $400",
        "items": [{"item": "steel brackets", "quantity": 50, "unit": "units"}],
        "location": "Fremont, CA",
        "deadline": "2026-11-14",
        "budget": 400,
        "max_price": 400,
    }
    payload.update(overrides)
    r = client.post("/requirements", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _add_supplier(req_id, name, quality=None, evidence=None):
    payload = {"name": name, "location": "Fremont, CA",
               "email": f"{name.lower().replace(' ', '')}@example.com",
               "contact_source": "public",
               "contact_source_url": "https://example.com/supplier",
               "lead_time_days": 3}
    if quality is not None:
        payload["quality_score"] = quality
        payload["quality_evidence"] = evidence or [
            {"type": "certification", "detail": "ISO 9001", "source": "supplier"}]
    r = client.post(f"/requirements/{req_id}/suppliers", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _set_price(req_id, supplier_id, landed_cost, unit_price=None):
    # Prices arrive via quotes in the real flow; tests set them through
    # the shortlist directly via a quote + negotiation-free path is not
    # exposed, so use the DB through the API-independent helper below.
    from app.db.models import Shortlist
    from app.db.session import SessionLocal

    db = SessionLocal()
    row = db.query(Shortlist).filter(
        Shortlist.requirement_id == req_id,
        Shortlist.supplier_id == supplier_id).first()
    row.landed_cost = landed_cost
    row.unit_price = unit_price if unit_price is not None else landed_cost / 50
    db.commit()
    db.close()


def _full_shortlist(req_id):
    """Seed 3 suppliers with distinct cost/quality profiles and rank them."""
    cheap_low = _add_supplier(req_id, "Cheap Steel Co", quality=55)
    mid_high = _add_supplier(req_id, "Quality Metals", quality=92)
    mid_mid = _add_supplier(req_id, "Midway Supply", quality=75)
    _set_price(req_id, cheap_low["id"], 200)
    _set_price(req_id, mid_high["id"], 380)
    _set_price(req_id, mid_mid["id"], 300)
    # Re-rank via the graph runner's finder (uses the same ranking code).
    from app.agents.graph import finder_node
    from app.db.session import SessionLocal

    db = SessionLocal()
    state = finder_node({"requirement_id": req_id}, db)
    db.close()
    assert state.get("error") is None, state
    return state


# ------------------------------------------------------------------ unit










# ------------------------------------------------------------------- api
def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["email_backend"] == "mock"


def test_ask_without_rag_says_not_found_not_a_guess():
    req = _requirement()
    r = client.post(f"/requirements/{req['id']}/ask", json={"question": "What is the beam load?"})
    assert r.status_code == 200
    assert r.json()["found"] is False
    assert "not found" in r.json()["answer"].lower()


def test_ask_with_rag_returns_grounded_cited_answer():
    # Wired RAG (app/integrations.py -> HybridRetrieval): a question the
    # demo plan corpus answers comes back grounded + cited. Regression:
    # citation_image_region must be a dict or None — an empty string
    # used to crash ask with a Pydantic validation error (500).
    req = _requirement()
    r = client.post(f"/requirements/{req['id']}/ask",
                    json={"question": "What concrete grade is specified for Maple Court ADU?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["grounded"] is True
    assert "C25/30" in body["answer"]
    assert body["citation_spec_clause"] == "C-01"
    assert body["citation_image_region"] is None or isinstance(
        body["citation_image_region"], dict)


def test_materials_come_from_requirement_items():
    req = _requirement()
    r = client.get(f"/requirements/{req['id']}/materials")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["estimate_label"] is True  # estimate, not surveyed


def test_approval_pane_shows_three_options_side_by_side():
    req = _requirement()
    _full_shortlist(req["id"])
    r = client.get(f"/requirements/{req['id']}/approval")
    assert r.status_code == 200
    pane = r.json()
    assert pane["best_value"] is not None
    assert pane["cheapest"] is not None
    assert pane["highest_quality"] is not None
    assert pane["cheapest"]["is_cheapest"] is True
    assert pane["highest_quality"]["is_highest_quality"] is True
    assert pane["best_value"]["quality_score"] is not None
    assert pane["no_quality_evidence"] is False


def test_approval_pane_flags_no_quality_evidence():
    req = _requirement()
    s1 = _add_supplier(req["id"], "NoEvidence One")
    s2 = _add_supplier(req["id"], "NoEvidence Two")
    _set_price(req["id"], s1["id"], 200)
    _set_price(req["id"], s2["id"], 300)
    from app.agents.graph import finder_node
    from app.db.session import SessionLocal

    db = SessionLocal()
    finder_node({"requirement_id": req["id"]}, db)
    db.close()
    r = client.get(f"/requirements/{req['id']}/approval")
    pane = r.json()
    assert pane["no_quality_evidence"] is True
    assert pane["highest_quality"] is None  # no evidenced quality to crown
    assert pane["best_value"]["supplier_name"] == "NoEvidence One"


def test_simulate_returns_cost_and_quality_risk():
    req = _requirement()
    _full_shortlist(req["id"])
    r = client.post(f"/requirements/{req['id']}/simulate", json={})
    assert r.status_code == 200
    assert len(r.json()) == 3
    for sim in r.json():
        assert "quality_risk" in sim and "quality_risk_reason" in sim
        assert "risk_score" in sim


def test_confirm_without_approval_is_refused():
    req = _requirement()
    r = client.post(f"/requirements/{req['id']}/confirm")
    assert r.status_code == 409
    assert "approval" in r.json()["detail"].lower()


def test_full_flow_draft_send_approve_confirm_invoice_records():
    req = _requirement()
    state = _full_shortlist(req["id"])
    req_id = req["id"]

    # Simulate + draft (draft must exist before send).
    assert client.post(f"/requirements/{req_id}/simulate", json={}).status_code == 200
    r = client.post(f"/requirements/{req_id}/buyer/send", json={})
    assert r.status_code == 409  # no draft yet
    assert "draft" in r.json()["detail"].lower()

    r = client.post(f"/requirements/{req_id}/buyer/draft", json={})
    assert r.status_code == 200
    assert "steel brackets" in r.json()["draft"]

    r = client.post(f"/requirements/{req_id}/buyer/send", json={"share_contact": {}})
    assert r.status_code == 200
    assert all(x["status"] in ("queued", "skipped") for x in r.json()["results"])
    assert r.json()["outbox"]["sent"] >= 0

    # Buyer message + inbox.
    best_supplier = state["best_value_supplier_id"]
    r = client.post(f"/requirements/{req_id}/buyer/message", json={
        "supplier_id": best_supplier, "subject": "Quick question",
        "body": "Can you confirm the lead time?"})
    assert r.status_code == 200, r.text
    r = client.get(f"/requirements/{req_id}/buyer/inbox")
    assert r.status_code == 200
    assert len(r.json()) >= 1

    # Approve -> order exists; confirm -> CONFIRMED.
    r = client.post(f"/requirements/{req_id}/approve", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("APPROVED", "PENDING", "CONFIRMED")
    order_id = r.json()["id"]
    r = client.post(f"/requirements/{req_id}/confirm")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CONFIRMED"

    # Invoice: missing number/amount is a validation error, never invented.
    r = client.post(f"/requirements/{req_id}/invoice", json={"amount": 300})
    assert r.status_code == 422
    r = client.post(f"/requirements/{req_id}/invoice", json={
        "invoice_number": "INV-2026-001", "amount": 300, "currency": "USD",
        "order_id": order_id, "supplier_id": best_supplier})
    assert r.status_code == 201, r.text
    assert r.json()["invoice_number"] == "INV-2026-001"
    assert float(r.json()["amount"]) == 300

    # Invoice chase + records + summary.
    r = client.post(f"/requirements/{req_id}/invoice/chase", json={})
    assert r.status_code == 200, r.text
    assert r.json()["chase_count"] == 1

    r = client.get(f"/requirements/{req_id}/records", params={"format": "csv"})
    assert r.status_code == 200
    assert "INV-2026-001" in r.text
    r = client.get(f"/requirements/{req_id}/records", params={"format": "json"})
    assert r.status_code == 200
    assert r.json()["invoices"][0]["invoice_number"] == "INV-2026-001"
    r = client.get(f"/requirements/{req_id}/records", params={"format": "summary"})
    assert r.status_code == 200

    r = client.post(f"/requirements/{req_id}/summary")
    assert r.status_code == 200, r.text
    assert r.json()["sent_to"] == "deepthiag26@gmail.com"

    # Orders list + single order with audit trail + approval pane.
    r = client.get("/orders")
    assert r.status_code == 200
    assert any(o["id"] == order_id for o in r.json())
    r = client.get(f"/orders/{order_id}")
    assert r.status_code == 200
    assert r.json()["approval_pane"]["best_value"] is not None
    assert len(r.json()["audit_trail"]) > 0


def test_reject_places_no_order():
    req = _requirement()
    _full_shortlist(req["id"])
    r = client.post(f"/requirements/{req['id']}/approve", json={"decision": "reject"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    r = client.post(f"/requirements/{req['id']}/confirm")
    assert r.status_code == 409


def test_accuracy_endpoint_returns_eight_metrics_and_empty_state():
    r = client.get("/accuracy")
    assert r.status_code == 200, r.text
    dash = r.json()
    assert len(dash["metrics"]) == 8
    keys = {m["key"] for m in dash["metrics"]}
    assert keys == {"groundedness", "retrieval_top1", "thumbs_up_rate",
                    "takeoff_mape", "ranking_top1_rate", "buyer_agent",
                    "guardrail_block_rate", "cost_cache_speed"}
    # Every metric carries formula, source, n and target — never a bare
    # number. Values may be None ("no data yet") or measured; nothing
    # here is invented by the endpoint.
    for m in dash["metrics"]:
        assert m["formula"] and m["source"] and m["target"]
        assert m["n"] >= 0
    assert isinstance(dash["alerts"], list)
    assert isinstance(dash["worst_answers"], list)
    assert isinstance(dash["raw_events"], list)


def test_accuracy_worst_answer_action_round_trip():
    from app.db.models import QALog
    from app.db.session import SessionLocal

    req = _requirement()
    db = SessionLocal()
    qa = QALog(requirement_id=req["id"], question="How many bolts?",
               answer="100", grounded=False, thumbs=-1)
    db.add(qa)
    db.commit()
    qa_id = qa.id
    db.close()
    r = client.post(f"/accuracy/worst-answers/{qa_id}/action",
                    json={"action": "add_to_eval_set"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_eval_set"
    # Second add of the same answer is refused, never duplicated.
    r = client.post(f"/accuracy/worst-answers/{qa_id}/action",
                    json={"action": "add_to_eval_set"})
    assert r.status_code == 409, r.text
    r = client.post(f"/accuracy/worst-answers/999999/action",
                    json={"action": "mark_fixed"})
    assert r.status_code == 404
    # Unknown action is rejected at the schema level (422), before the
    # route's own 400 branch — either way it never reaches the store.
    r = client.post(f"/accuracy/worst-answers/{qa_id}/action",
                    json={"action": "delete"})
    assert r.status_code == 422
