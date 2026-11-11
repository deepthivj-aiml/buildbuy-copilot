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
