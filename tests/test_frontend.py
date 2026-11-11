"""Tests for the frontend pure helpers (frontend/helpers.py).

No Streamlit needed — helpers.py imports no Streamlit, so these tests
import it directly. The Streamlit screens themselves (frontend/app.py)
are smoke-tested with AppTest only when streamlit is installed
(see docs/BUILD_REPORT.md — not installed in this VM).

Run alone:  .venv/bin/python -m pytest tests/test_frontend.py -v
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend"))

import demo_data  # noqa: E402
import helpers  # noqa: E402

SUPPLIERS = [
    {"name": "Near Dear", "location": "Fremont, CA", "lat": 37.5485, "lng": -121.9886,
     "unit_price": 6.30, "moq": 25, "lead_days": 2, "quality_score": 92,
     "quality_evidence": ["ISO"], "contact": "x", "contact_source": "public", "why": ""},
    {"name": "Far Cheap", "location": "Stockton, CA", "lat": 37.9577, "lng": -121.2908,
     "unit_price": 4.95, "moq": 10, "lead_days": 7, "quality_score": 64,
     "quality_evidence": ["none"], "contact": "x", "contact_source": "public", "why": ""},
]


def test_demo_data_is_synthetic_and_complete():
    assert len(demo_data.DEMO_SUPPLIERS) == 6
    assert all("lat" in s and "lng" in s for s in demo_data.DEMO_SUPPLIERS)
    assert len(demo_data.DEMO_MATERIALS) == 5
    assert demo_data.DEMO_QA and demo_data.DEMO_EVAL_RUNS


def test_parse_requirement():
    req = helpers.parse_requirement(
        "steel brackets, 50 units in Fremont, by Friday, under $400")
    assert req["quantity"] == 50 and req["budget"] == 400.0
    assert req["location"] == "Fremont"
    # No preposition before the place -> location stays blank, never guessed.
    assert helpers.parse_requirement("steel brackets, 50 units")["location"] == ""


def test_parse_requirement_item_unit_location():
    """2026-11-10 live bug: the old parser returned the FULL input text
    as the item and dropped the unit entirely. "concrete, 10 m3,
    Fremont" must parse to item "concrete", quantity 10, unit "m3",
    location "Fremont" — and the quantity must reach the takeoff."""
    req = helpers.parse_requirement("concrete, 10 m3, Fremont")
    assert req["item"] == "concrete"
    assert req["quantity"] == 10 and req["unit"] == "m3"
    assert req["location"] == "Fremont"
    req = helpers.parse_requirement(
        "steel brackets, 50 units in Fremont, by Friday, under $400")
    assert req["item"] == "steel brackets"
    assert req["quantity"] == 50 and req["unit"] == "pcs"
    assert req["location"] == "Fremont" and req["deadline"] == "Friday"
    assert req["budget"] == 400.0
    # "10 x concrete" form, and a bare number with no unit.
    req = helpers.parse_requirement("10 x anchor bolts M12")
    assert req["item"] == "anchor bolts M12" and req["quantity"] == 10
    req = helpers.parse_requirement("timber joists 18")
    assert req["item"] == "timber joists" and req["quantity"] == 18
    assert req["unit"] == ""
    # An unknown trailing word is never guessed as a location.
    req = helpers.parse_requirement("concrete, 10 m3, Somewhereville")
    assert req["location"] == "" and req["item"] == "concrete, Somewhereville"


def test_parse_requirement_llm_hook_falls_back():
    """The optional LLM parser hook: a working stub is used, a
    failing / empty one falls back to the deterministic parse — an
    LLM must never break parsing, and none is configured by default."""
    def stub(text):
        return {"item": "rebar", "quantity": 12, "unit": "kg"}
    req = helpers.parse_requirement("whatever the user typed", llm_parser=stub)
    assert req["item"] == "rebar" and req["quantity"] == 12
    assert req["unit"] == "kg"

    def broken(text):
        raise RuntimeError("no model here")
    req = helpers.parse_requirement("concrete, 10 m3, Fremont", llm_parser=broken)
    assert req["item"] == "concrete" and req["quantity"] == 10
    req = helpers.parse_requirement("concrete, 10 m3, Fremont",
                                    llm_parser=lambda t: {})
    assert req["item"] == "concrete"


def test_takeoff_updates_from_typed_requirement():
    """Regression for the live bug (2026-11-10 21:08): typing
    "concrete, 10 m3, Fremont" left the takeoff at the demo plan's
    2.4 m3. The typed quantity must update the table."""
    base = [dict(m) for m in demo_data.DEMO_MATERIALS]
    req = helpers.parse_requirement("concrete, 10 m3, Fremont")
    mats, note = helpers.apply_requirement_to_takeoff(base, req)
    conc = next(m for m in mats if "Concrete" in m["material"])
    assert (conc["quantity"], conc["unit"]) == (10, "m3")
    # The old plan value is kept in the method, not silently replaced.
    assert "2.4" in conc["method"] and "overrides" in conc["method"]
    assert conc["estimate_label"] == helpers.ESTIMATE_LABEL
    assert conc["source"] == "typed requirement"
    assert "10 m3" in note

    # (b) steel brackets, 50 units -> 50 pcs (already the plan value:
    # still labelled as a typed update, quantity unchanged).
    mats, _note = helpers.apply_requirement_to_takeoff(
        base, helpers.parse_requirement("steel brackets, 50 units"))
    steel = next(m for m in mats if "Steel brackets" in m["material"])
    assert (steel["quantity"], steel["unit"]) == (50, "pcs")

    # (c) sample plan load still shows its own takeoff untouched.
    assert len(base) == 5
    assert next(m for m in base if "Concrete" in m["material"])["quantity"] == 2.4

    # (d) typed quantity AFTER a plan load updates that material's line.
    mats, _note = helpers.apply_requirement_to_takeoff(
        base, helpers.parse_requirement("timber joists, 30 pcs"))
    timber = next(m for m in mats if "Timber joists" in m["material"])
    assert (timber["quantity"], timber["unit"]) == (30, "pcs")
    assert "18" in timber["method"]

    # A new material appends a line instead of touching other lines.
    mats, _note = helpers.apply_requirement_to_takeoff(
        base, helpers.parse_requirement("cement, 20 bags, Hayward"))
    cement = next(m for m in mats if m["material"] == "Cement")
    assert (cement["quantity"], cement["unit"]) == (20, "bags")
    assert len(mats) == 6
    assert next(m for m in mats if "Concrete" in m["material"])["quantity"] == 2.4

    # A single token that is only part of a multi-word line does NOT
    # hijack it ("steel" is not "Steel brackets").
    mats, _note = helpers.apply_requirement_to_takeoff(
        base, helpers.parse_requirement("steel, 500 kg"))
    assert next(m for m in mats if "Steel brackets" in m["material"])["quantity"] == 50
    assert any(m["material"] == "Steel" and m["quantity"] == 500 for m in mats)

    # (e) no quantity given -> table unchanged, never an invented qty.
    mats, note = helpers.apply_requirement_to_takeoff(
        base, helpers.parse_requirement("timber joists"))
    assert mats == base and "No quantity" in note

    # Every line keeps the estimate label, front and back agree on it.
    assert all(m["estimate_label"] == helpers.ESTIMATE_LABEL for m in mats)
    assert helpers.ESTIMATE_LABEL == demo_data.ESTIMATE_LABEL
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from app.takeoff.engine import ESTIMATE_LABEL as BACKEND_LABEL
    assert BACKEND_LABEL == helpers.ESTIMATE_LABEL


def test_supplier_contact_details_never_invented():
    """Contact details: held fields shown, missing ones "not held".
    Demo suppliers carry no phone / street address — those are None,
    never guessed; location is a city-level area, not an address."""
    bay = demo_data.DEMO_SUPPLIERS[0]
    assert helpers.supplier_email(bay) == "sales@baysteel.example"
    details = helpers.supplier_contact_details(bay)
    assert details["email"] == "sales@baysteel.example"
    assert details["phone"] is None and details["address"] is None
    assert details["area"] == "Fremont, CA"
    pacific = next(s for s in demo_data.DEMO_SUPPLIERS
                   if s["name"] == "Pacific Fasteners Co")
    assert helpers.supplier_email(pacific) is None  # "not public — request via email"
    assert helpers.supplier_contact_details(pacific)["email"] is None


def test_quote_email_preview_off_vs_on_and_blocked():
    """Per-supplier preview: correct contact + channel + full email;
    sharing OFF anonymises, ON includes the buyer's contact; a
    supplier with no email is not sendable and no address is guessed."""
    req = helpers.parse_requirement(
        "steel brackets, 50 units, Fremont, by Friday, under $400")
    bay = demo_data.DEMO_SUPPLIERS[0]
    off = helpers.build_quote_email(req, bay, share_contact=False, max_price=400.0)
    assert off["channel"] == "email"
    assert off["from"] == helpers.EMAIL_FROM
    assert off["to"] == "sales@baysteel.example" and off["sendable"] is True
    assert off["subject"] == "Quote request — 50 x steel brackets"
    assert "I am BuildBuy Copilot, acting as the buying agent for a customer" in off["body"]
    assert "50 x steel brackets" in off["body"]
    assert "Fremont" in off["body"] and "Friday" in off["body"]
    assert "Deepthi" not in off["body"] and "deepthiag26" not in off["body"]
    assert "341-252-9234" not in off["body"]
    on = helpers.build_quote_email(req, bay, share_contact=True, max_price=400.0)
    assert "acting as the buying agent for Deepthi Jainlal" in on["body"]
    assert "deepthiag26@gmail.com" in on["body"] and "+1 341-252-9234" in on["body"]
    # The preview is the email the backend would send (same draft fn).
    from app.email.service import EmailService
    backend_off = EmailService.draft_quote(
        buyer_name="Deepthi Jainlal",
        items=[{"quantity": 50, "item": "steel brackets"}],
        location="Fremont", deadline="Friday", max_price=400.0,
        share_contact=False, buyer_email="deepthiag26@gmail.com",
        buyer_phone="+1 341-252-9234")
    assert backend_off == off["body"]
    backend_on = EmailService.draft_quote(
        buyer_name="Deepthi Jainlal",
        items=[{"quantity": 50, "item": "steel brackets"}],
        location="Fremont", deadline="Friday", max_price=400.0,
        share_contact=True, buyer_email="deepthiag26@gmail.com",
        buyer_phone="+1 341-252-9234")
    assert backend_on == on["body"]
    # Missing supplier email: blocked, not invented.
    pacific = next(s for s in demo_data.DEMO_SUPPLIERS
                   if s["name"] == "Pacific Fasteners Co")
    blocked = helpers.build_quote_email(req, pacific, share_contact=False,
                                        max_price=400.0)
    assert blocked["sendable"] is False and blocked["to"] is None
    assert "not held" in blocked["blocked_reason"]
    # Editing the draft and then sending with sharing OFF strips any
    # contact the user typed into the edited text.
    edited = ("Hello, I am Deepthi Jainlal, reach me at deepthiag26@gmail.com "
              "or +1 341-252-9234 about 50 x steel brackets.")
    stripped = helpers.strip_contact_details(edited)
    assert "Deepthi" not in stripped and "deepthiag26" not in stripped
    assert "341" not in stripped and "[contact not shared]" in stripped


def test_frontend_ranking_matches_backend_formula():
    # Same canonical blend as app/suppliers/search.py (0.45/0.35/0.20),
    # min-max cost scores across the shortlist. qty 50, no delivery
    # location -> landed excl. transport: Near 336.30, Far 267.45.
    # Cost: Far 100, Near 0. Lead: Near (2d) 100, Far (7d) 0.
    # Far:  0.45*100 + 0.35*64 + 0.20*0   = 67.4 -> best value (cost dominates)
    # Near: 0.45*0   + 0.35*92 + 0.20*100 = 52.2
    rows, _ = helpers.rank_suppliers(SUPPLIERS, 50)
    by = {r["name"]: r for r in rows}
    assert by["Far Cheap"]["value_score"] == 67.4
    assert by["Near Dear"]["value_score"] == 52.2
    assert by["Far Cheap"]["value_rank"] == 1
    assert by["Far Cheap"]["is_cheapest"] is True
    assert by["Near Dear"]["is_best_quality"] is True
    # Quality unknown for the cheap one -> scored on cost + lead only,
    # and the high-quality near one wins the blend.
    no_q = [dict(s, quality_score=None) if s["name"] == "Far Cheap" else dict(s)
            for s in SUPPLIERS]
    rows, _ = helpers.rank_suppliers(no_q, 50)
    by = {r["name"]: r for r in rows}
    assert by["Near Dear"]["value_rank"] == 1
    assert by["Far Cheap"]["quality_unknown"] is True


def test_frontend_transport_optional_manual_location():
    rows, _ = helpers.rank_suppliers(SUPPLIERS, 50)
    assert all(r["landed_label"] == "excl. transport" for r in rows)
    rows, _ = helpers.rank_suppliers(SUPPLIERS, 50, delivery_location="Fremont",
                                     transport_rate=5.0)
    by = {r["name"]: r for r in rows}
    assert by["Near Dear"]["landed"] < by["Far Cheap"]["landed"]
    assert by["Far Cheap"]["unit_price"] < by["Near Dear"]["unit_price"]
    assert "incl. transport" in helpers.landed_line(by["Near Dear"], 50)
    assert helpers.geocode_location("Nowhereville") is None
    # Twin agrees with the shortlist total and does not scale transport.
    sim = helpers.twin_risk(by["Near Dear"], 50, 10, 0, 0)
    assert sim["base_landed"] == by["Near Dear"]["landed"]
    goods_fees = by["Near Dear"]["landed"] - (by["Near Dear"]["transport"] or 0.0)
    assert sim["landed"] == round(
        goods_fees * 1.10 + (by["Near Dear"]["transport"] or 0.0), 2)


def test_demo_answer_grounded_or_not_found():
    ans, _region, _clause, grounded = helpers.demo_answer("How many fixtures?")
    assert grounded is True and "31" in ans
    ans, _region, _clause, grounded = helpers.demo_answer(
        "What is the tensile strength of the moon base?")
    assert grounded is False and "not found" in ans.lower()


# ------------------------------------------------------------- accuracy dashboard
def test_accuracy_metric_defs_agree_with_backend():
    """Frontend accuracy.py and backend app/observability.py must agree
    on the 8 metrics (key, formula, target) — one source of truth, two
    copies, checked here so they cannot drift apart silently."""
    import accuracy

    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from app.observability import METRIC_DEFS as BACKEND_DEFS

    assert len(accuracy.METRIC_DEFS) == 8 == len(BACKEND_DEFS)
    front = {d["key"]: d for d in accuracy.METRIC_DEFS}
    back = {d["key"]: d for d in BACKEND_DEFS}
    assert set(front) == set(back)
    for key in front:
        assert front[key]["formula"] == back[key]["formula"], key
        assert front[key]["target"] == back[key]["target"], key
        assert front[key]["direction"] == back[key]["direction"], key
    assert "blended" not in " ".join(front)


def test_accuracy_format_and_status_never_invents():
    import accuracy

    assert accuracy.format_value(None) == "no data yet"
    assert accuracy.format_value(0.96) == "96.0%"
    assert accuracy.format_value(0.42, "usd") == "$0.42"
    assert accuracy.metric_status(accuracy.METRIC_DEFS[0], None) == "no_data"
    assert accuracy.metric_status(accuracy.METRIC_DEFS[0], 0.96) == "ok"
    assert accuracy.metric_status(accuracy.METRIC_DEFS[0], 0.89) == "alert"
    # Takeoff is lower-is-better: 25% error alerts, 6% does not.
    assert accuracy.metric_status(accuracy.METRIC_DEFS[3], 0.25) == "alert"
    assert accuracy.metric_status(accuracy.METRIC_DEFS[3], 0.06) == "ok"
    assert accuracy.dashboard_is_empty(
        {"metrics": [{"value": None}, {"value": None}]}) is True
    assert accuracy.dashboard_is_empty(
        {"metrics": [{"value": 0.9}, {"value": None}]}) is False


def test_accuracy_worst_answers_actions_and_merge():
    import accuracy

    worst = accuracy.worst_answers_from_feedback(
        [{"question": "Why is the beam wrong?", "thumbs": "down",
          "reason": "wrong number"}],
        demo_data.DEMO_WORST_ANSWERS)
    assert len(worst) == 10  # capped at 10, live row first
    assert worst[0]["question"] == "Why is the beam wrong?"
    assert worst[0]["live"] is True
    acted = accuracy.apply_worst_action(worst, "demo-qa-01", "add_to_eval_set")
    row = next(r for r in acted if r["qa_log_id"] == "demo-qa-01")
    assert row["status"] == "in_eval_set"
    # A row already acted on is left alone (backend refuses duplicates).
    acted2 = accuracy.apply_worst_action(acted, "demo-qa-01", "mark_fixed")
    row2 = next(r for r in acted2 if r["qa_log_id"] == "demo-qa-01")
    assert row2["status"] == "in_eval_set"


def test_accuracy_demo_dashboard_is_complete_and_honest():
    import accuracy

    dash = demo_data.DEMO_ACCURACY
    assert len(dash["metrics"]) == 8
    assert all(m["value"] is None or 0 <= m["value"] <= 1
               for m in dash["metrics"])
    # Takeoff has no data even in the demo — no corrected lines exist.
    takeoff = next(m for m in dash["metrics"] if m["key"] == "takeoff_mape")
    assert takeoff["value"] is None and takeoff["status"] == "no_data"
    # Buyer-agent value is the approval-before-order invariant (1.0);
    # the 58% agreement rate is separate, never blended in.
    buyer = next(m for m in dash["metrics"] if m["key"] == "buyer_agent")
    assert buyer["value"] == 1.0 and buyer["agreement_rate"] == 0.58
    assert len(demo_data.DEMO_WORST_ANSWERS) == 10
    assert len(demo_data.DEMO_RAW_EVENTS) == 10
    # Raw events are PII-free: no prompt, plan text or email body.
    assert all(set(e) <= {"request_id", "step", "model", "latency_ms",
                          "grounded", "cache_hit", "guardrail_action",
                          "cost_usd", "created_at"}
               for e in demo_data.DEMO_RAW_EVENTS)
    rows = accuracy.trend_rows(
        demo_data.DEMO_METRICS_DAYS, demo_data.DEMO_GROUNDEDNESS,
        demo_data.DEMO_RETRIEVAL_TOP1, demo_data.DEMO_EVAL_PASS)
    assert len(rows) == 14 and rows[0]["Groundedness %"] == 92.0


def test_accuracy_fetch_live_returns_none_when_backend_down():
    import accuracy

    assert accuracy.fetch_live_accuracy(
        api_url="http://127.0.0.1:9", timeout=1) is None


def test_accuracy_tab_renders_in_streamlit():
    """Real render check: the Accuracy tab opens in demo mode, shows all
    8 metric names, and raises no exception. Skipped where Streamlit is
    not installed (the pure-helper tests above cover that case)."""
    import pytest

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "frontend" / "app.py"))
    at.run()
    assert not at.exception, at.exception
    at.radio[0].set_value("6 · Accuracy").run()
    assert not at.exception, at.exception
    text = " ".join(str(m.value) for m in at.markdown) + " ".join(
        str(m.value) for m in at.dataframe) + " ".join(
        str(s.value) for s in at.subheader) + " ".join(
        str(h.value) for h in at.header)
    for name in ("Groundedness", "Retrieval accuracy", "Answer accuracy",
                 "Takeoff estimate accuracy", "Supplier ranking accuracy",
                 "Buyer-agent accuracy", "Guardrail block rate",
                 "Cost / cache / speed", "Worst Answers",
                 "Eval Run History", "Drill-down"):
        assert name in text, f"missing from Accuracy tab: {name}"
    # Demo metrics are labelled synthetic — the tab never pretends they
    # are live measurements.
    assert "synthetic demo" in text.lower()


# ------------------------------------------------------------- live UI flows
# (AppTest — real renders of frontend/app.py in demo mode)
def _app():
    import pytest

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "frontend" / "app.py"))
    at.run()
    assert not at.exception, at.exception
    return at


def _all_text(at):
    """Every visible text fragment in the current render."""
    texts = []
    for coll in (at.markdown, at.caption, at.success, at.info, at.warning,
                 at.error, at.header, at.subheader):
        try:
            texts.extend(str(el.value) for el in coll)
        except Exception:  # noqa: BLE001 — collection may be absent
            pass
    return "\n".join(texts)


def test_takeoff_updates_in_streamlit_from_typed_input():
    """End-to-end UI regression for the live bug: type
    "concrete, 10 m3, Fremont", parse, open Plan & Materials — the
    takeoff table must show concrete 10 m3, not the demo plan's 2.4."""
    at = _app()
    at.text_area(key="requirement_input").set_value("concrete, 10 m3, Fremont").run()
    assert not at.exception, at.exception
    at.button(key="parse_requirement_btn").click().run()
    assert not at.exception, at.exception
    assert "10 m3" in _all_text(at)
    at.radio[0].set_value("2 · Plan & Materials").run()
    assert not at.exception, at.exception
    df = at.data_editor[0].value
    conc = df[df["material"].str.contains("Concrete")]
    assert len(conc) == 1
    assert float(conc.iloc[0]["quantity"]) == 10.0
    assert conc.iloc[0]["unit"] == "m3"
    assert "estimate, not a surveyed quantity" in str(
        conc.iloc[0]["estimate_label"])
    assert "2.4" in str(conc.iloc[0]["method"])  # old plan value kept


def test_buyer_agent_email_preview_edit_and_send():
    """Buyer Agent tab: per-supplier contact + channel + full email
    preview; sharing toggle changes the preview; editing the body
    changes what is sent; sharing OFF strips contact on send."""
    at = _app()
    at.session_state["requirement"] = {
        "raw": "steel brackets, 50 units, Fremont, by Friday, under $400",
        "item": "steel brackets", "quantity": 50, "unit": "pcs",
        "location": "Fremont", "deadline": "Friday", "budget": 400.0}
    at.radio[0].set_value("4 · Buyer Agent").run()
    assert not at.exception, at.exception
    text = _all_text(at)
    assert "I am BuildBuy Copilot, acting as the buying agent for a customer" in text
    assert "sales@baysteel.example" in text  # supplier contact shown
    assert "Channel: Email" in text and "From: BuildBuy Copilot" in text
    assert "Quote request — 50 x steel brackets" in text
    assert "Phone: not held" in text  # demo suppliers have no phone
    # Sharing ON for Bay Steel -> the preview now names the customer.
    # The preview body lives in the editable text area, so read it there.
    at.checkbox(key="send-share-Bay Steel Supply").set_value(True).run()
    assert not at.exception, at.exception
    on_body = at.text_area(key="quote-body-Bay Steel Supply-shared").value
    assert "Deepthi Jainlal" in on_body
    assert "deepthiag26@gmail.com" in on_body
    # Sharing back OFF, edit the body, send: the sent text is the
    # edited text, with contact stripped because sharing is OFF.
    at.checkbox(key="send-share-Bay Steel Supply").set_value(False).run()
    at.text_area(key="quote-body-Bay Steel Supply-private").set_value(
        "EDITED BODY — please quote 50 x steel brackets. "
        "I am Deepthi Jainlal, deepthiag26@gmail.com.").run()
    assert not at.exception, at.exception
    at.button(key="quote-send-Bay Steel Supply").click().run()
    assert not at.exception, at.exception
    sent = at.session_state["quote_sent"]["Bay Steel Supply"]
    assert sent["to"] == "sales@baysteel.example"
    assert "EDITED BODY" in sent["body"]
    assert "Deepthi" not in sent["body"] and "deepthiag26" not in sent["body"]


def test_buyer_agent_blocks_send_when_email_not_held():
    """A supplier with no held email shows "not held" and its Send
    button is disabled — no address is ever guessed."""
    at = _app()
    at.session_state["requirement"] = {
        "raw": "steel brackets, 50 units", "item": "steel brackets",
        "quantity": 50, "unit": "pcs", "location": "Fremont",
        "deadline": "Friday", "budget": 400.0}
    at.session_state["suppliers"] = [{
        "name": "No Email Supplier", "location": "Fremont, CA",
        "lat": 37.5485, "lng": -121.9886, "distance_mi": 4.2,
        "unit_price": 6.30, "moq": 10, "lead_days": 2, "quality_score": 92,
        "quality_evidence": ["ISO 9001 certificate on file (synthetic demo record)"],
        "contact": "not public — request via email",
        "contact_source": "not public", "why": "Only supplier in this test.",
    }]
    at.radio[0].set_value("4 · Buyer Agent").run()
    assert not at.exception, at.exception
    assert "not held" in _all_text(at)
    assert "Email not held for this supplier" in _all_text(at)
    assert at.session_state["quote_sent"] == {}
    send_btn = at.button(key="quote-send-No Email Supplier")
    assert send_btn.disabled is True


def test_all_seven_tabs_render_after_restyle():
    """Restyle regression: every tab renders with no exception, its
    heading present, and the hero + journey stepper visible. Labels,
    honest wording and demo labelling are unchanged by the restyle."""
    at = _app()
    headings = {
        "1 · Start": "Start — the chat is the input",
        "2 · Plan & Materials": "Plan & Materials — ask the plan, check the takeoff",
        "3 · Suppliers & Twin": "Suppliers & Twin — best cost AND quality, not cost alone",
        "4 · Buyer Agent": "Buyer Agent — quotes, negotiation, approval",
        "5 · My Orders": "My Orders — full timeline, delivery chase, invoices",
        "6 · Accuracy": "Accuracy — is the copilot getting better or worse?",
        "7 · Settings": "Settings — contact, sharing, usage, data",
    }
    for nav_value, heading in headings.items():
        at.radio[0].set_value(nav_value).run()
        assert not at.exception, (nav_value, at.exception)
        text = _all_text(at)
        assert heading in text, nav_value
        # Hero + journey stepper are on every tab; honest labels survive.
        assert "BuildBuy Copilot" in text, nav_value
        assert "Buyer journey" in text, nav_value
        assert "DEMO MODE" in text, nav_value  # demo labelling intact
        if nav_value == "2 · Plan & Materials":
            assert "estimate, not a surveyed quantity" in text
    # Colour-coded chips: order status on My Orders, thread status on
    # Buyer Agent, metric status on Accuracy — text labels included.
    at.radio[0].set_value("5 · My Orders").run()
    assert "INVOICE_RECEIVED" in _all_text(at)
    at.radio[0].set_value("4 · Buyer Agent").run()
    assert "replied" in _all_text(at)
    at.radio[0].set_value("6 · Accuracy").run()
    assert "no data yet" in _all_text(at)
