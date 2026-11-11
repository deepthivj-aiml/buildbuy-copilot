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
