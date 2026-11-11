"""Tests for digital twin — landed cost + cost/quality risk, what-if breaks.

Run alone:  .venv/bin/python -m pytest tests/test_twin.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ranking import simulate_cost_and_quality  # noqa: E402
from app.suppliers.directory import load_suppliers  # noqa: E402
from app.twin.simulator import DigitalTwin  # noqa: E402

DATA = ROOT / "data"
PLANS = [json.loads(p.read_text()) for p in sorted((DATA / "plans").glob("plan-*.json"))]
SUPPLIERS = load_suppliers(DATA)
BUYER = (37.5485, -121.9886)  # Fremont, CA



def test_twin_cost_and_quality_risk():
    twin = DigitalTwin(*BUYER, order_date=date(2026, 11, 10))
    cheap_lowq = next(s for s in SUPPLIERS if s["id"] == "sup10")  # cheapest concrete, low quality
    near_highq = next(s for s in SUPPLIERS if s["id"] == "sup07")  # Alameda, high quality
    sim_cheap = twin.simulate(cheap_lowq, "concrete", 10)
    sim_good = twin.simulate(near_highq, "concrete", 10)
    # Landed cost reconciles: goods + shipping + fees.
    assert sim_good.landed_cost == round(
        sim_good.goods_cost + sim_good.shipping_cost + sim_good.fees, 2
    )
    assert sim_good.delivery_date == date(2026, 11, 10) + timedelta(days=2)
    # Cheap but low quality carries MORE total risk than the dearer good one.
    assert sim_cheap.quality_risk > sim_good.quality_risk
    assert sim_cheap.risk_score > sim_good.risk_score
    assert sim_cheap.landed_cost < sim_good.landed_cost  # it really is cheaper
    # What-if: a 5-day delay against a tight deadline breaks the deal.
    tight = date(2026, 11, 10) + timedelta(days=3)
    w = twin.what_if(near_highq, "concrete", 10, delay_days=5, deadline=tight)
    assert any(b.startswith("past_deadline") for b in w["breaks"])
    # What-if: +20% price against a $1,400 cap breaks on budget.
    w2 = twin.what_if(near_highq, "concrete", 10, price_pct=20, max_price=1400.0)
    assert any(b.startswith("over_budget") for b in w2["breaks"])


def test_twin_simulates_cost_and_quality_risk():
    sim = simulate_cost_and_quality(
        landed_cost=300.0, quality_score=None, quality_evidence=[],
        risk_flags=[], lead_time_days=5,
        price_change_pct=10, delivery_slip_days=3, quantity_change_pct=20)
    assert sim["landed_cost"] == 396.0  # 300 * 1.2 * 1.1
    assert sim["quality_score"] is None
    assert sim["quality_risk"] >= 60.0  # no evidence -> high quality risk
    assert "No quality evidence" in sim["quality_risk_reason"]
    sim2 = simulate_cost_and_quality(
        landed_cost=300.0, quality_score=92.0,
        quality_evidence=[{"type": "certification", "detail": "ISO 9001"}],
        risk_flags=[], lead_time_days=5)
    assert sim2["quality_risk"] < sim["quality_risk"]
