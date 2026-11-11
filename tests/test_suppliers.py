"""Tests for supplier search + transport — cost+quality+lead ranking, total landed cost, manual delivery location.

Run alone:  .venv/bin/python -m pytest tests/test_suppliers.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.suppliers.directory import load_suppliers, quality_score  # noqa: E402
from app.suppliers.location import geocode_location  # noqa: E402
from app.suppliers.search import search_suppliers  # noqa: E402
from app.twin.simulator import DigitalTwin  # noqa: E402

DATA = ROOT / "data"
PLANS = [json.loads(p.read_text()) for p in sorted((DATA / "plans").glob("plan-*.json"))]
SUPPLIERS = load_suppliers(DATA)
BUYER = (37.5485, -121.9886)  # Fremont, CA



def test_quality_score_evidenced_only():
    best = next(s for s in SUPPLIERS if s["id"] == "sup03")  # 2 certs, high reliability
    worst = next(s for s in SUPPLIERS if s["id"] == "sup05")  # no certs, unverified
    q_best, ev_best = quality_score(best)
    q_worst, ev_worst = quality_score(worst)
    assert q_best > q_worst
    assert 0.0 <= q_best <= 1.0 and 0.0 <= q_worst <= 1.0
    signals = {e["signal"] for e in ev_worst}
    assert {"certifications", "vetting", "reply_reliability",
            "lead_time_reliability", "defect_history", "user_feedback"} <= signals
    # Missing defect history / feedback is "not provided — neutral", never good.
    defect_ev = next(e for e in ev_worst if e["signal"] == "defect_history")
    assert defect_ev["score"] == 0.5 and "not provided" in defect_ev["value"]
    fb_ev = next(e for e in ev_worst if e["signal"] == "user_feedback")
    assert fb_ev["score"] == 0.5 and "not provided" in fb_ev["value"]


def test_cost_quality_ranking_tradeoff():
    """Cost+quality ranking (user update 2026-11-10): cheapest must NOT
    automatically win. Concrete, 10 m3, from Fremont."""
    out = search_suppliers(SUPPLIERS, "concrete", 10, *BUYER)
    ranked = out["ranked"]
    assert len(ranked) == 5, f"expected 5 concrete suppliers, got {len(ranked)}"
    cheapest = out["cheapest"]
    best_quality = out["highest_quality"]
    best_value = ranked[0]
    # Cheapest landed cost is Central Valley (sup10, $118/m3) ...
    assert cheapest["supplier_id"] == "sup10", cheapest
    # ... but it is NOT the best value: its quality (0.596) and 8-day lead
    # lose to Alameda (sup07), which is dearer but closer, faster, better.
    assert best_value["supplier_id"] == "sup07", best_value
    assert best_value["supplier_id"] != cheapest["supplier_id"]
    # Highest quality overall is Bay Area Building Supply (sup01).
    assert best_quality["supplier_id"] == "sup01", best_quality
    assert best_quality["quality_score"] > cheapest["quality_score"]
    # Every ranked supplier shows its trade-off in plain language.
    assert "Cheapest" in cheapest["tradeoff"] and "quality" in cheapest["tradeoff"]
    assert "Highest quality" in best_quality["tradeoff"]
    assert all(r["why_rank"] and r["tradeoff"] for r in ranked)
    assert all("quality_evidence" in r and r["quality_evidence"] for r in ranked)
    # MOQ filter: 1 m3 excludes every concrete supplier with MOQ > 1.
    small = search_suppliers(SUPPLIERS, "concrete", 1, *BUYER)
    assert small["ranked"] == []
    assert len(small["excluded"]) == 5


def test_transport_optional_manual_location():
    """Total landed cost incl. transport: nearer supplier can win on total
    landed cost despite a higher unit price. Location is MANUAL and
    OPTIONAL — blank by default, never auto-detected (no geolocation,
    no IP lookup, no auto-use of the requirement location)."""
    # Manual location resolves offline; blank / unknown -> None (excluded).
    assert geocode_location("Fremont") == (37.5485, -121.9886, "Fremont")
    assert geocode_location("fremont, ca")[2] == "Fremont"
    assert geocode_location("37.5485,-121.9886")[0] == 37.5485
    assert geocode_location("") is None
    assert geocode_location(None) is None
    assert geocode_location("Nowhereville") is None

    # Blank location: ranking still works, transport excluded, labelled.
    out = search_suppliers(SUPPLIERS, "concrete", 10)
    assert len(out["ranked"]) == 5
    for r in out["ranked"]:
        assert r["transport_included"] is False
        assert r["transport_cost"] is None
        assert r["distance_km"] is None
        assert r["landed_cost_label"] == "excl. transport"
        bd = r["landed_breakdown"]
        assert bd["total"] == round(bd["goods"] + bd["taxes_fees"], 2)

    # Default rate with a typed location: breakdown reconciles.
    out = search_suppliers(SUPPLIERS, "concrete", 10, *BUYER)
    sup10 = next(r for r in out["ranked"] if r["supplier_id"] == "sup10")
    bd = sup10["landed_breakdown"]
    assert sup10["transport_included"] is True
    assert sup10["landed_cost_label"] == "incl. transport"
    assert sup10["landed_cost"] == round(
        bd["goods"] + bd["transport"] + bd["taxes_fees"], 2)
    assert bd["goods"] == 118.0 * 10  # cheapest unit price, far away (Modesto)

    # High transport rate ($5/km): the near, dearer supplier wins on TOTAL
    # landed cost despite the higher unit price — that is the point of
    # total landed cost. Winner is sup02 Hayward ($128/m3, 15.6 km):
    # $1,280 goods + $78 transport + $40.60 fees = $1,398.60, beating
    # sup10 Modesto ($118/m3, 88 km): $1,180 + $440 + $38.60 = $1,658.60.
    out = search_suppliers(SUPPLIERS, "concrete", 10, *BUYER,
                           transport_rate_per_km=5.0)
    cheapest = out["cheapest"]
    assert cheapest["supplier_id"] == "sup02", cheapest
    sup10 = next(r for r in out["ranked"] if r["supplier_id"] == "sup10")
    assert cheapest["landed_cost"] < sup10["landed_cost"]
    assert cheapest["unit_price"] > sup10["unit_price"]  # dearer per unit, cheaper total

    # Twin agrees: same rate, same winner on landed cost; and with no
    # buyer location the twin excludes transport too.
    twin = DigitalTwin(*BUYER, order_date=date(2026, 11, 10))
    near = next(s for s in SUPPLIERS if s["id"] == "sup02")
    far = next(s for s in SUPPLIERS if s["id"] == "sup10")
    assert twin.simulate(near, "concrete", 10, transport_rate_per_km=5.0).landed_cost < \
        twin.simulate(far, "concrete", 10, transport_rate_per_km=5.0).landed_cost
    no_loc = DigitalTwin(order_date=date(2026, 11, 10))
    sim = no_loc.simulate(near, "concrete", 10)
    assert sim.transport_included is False
    assert sim.landed_cost_label == "excl. transport"
    assert sim.landed_cost == round(sim.goods_cost + sim.fees, 2)
