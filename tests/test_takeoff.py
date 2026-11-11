"""Tests for takeoff engine — deterministic materials estimation, labelled estimates.

Run alone:  .venv/bin/python -m pytest tests/test_takeoff.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.takeoff.engine import ESTIMATE_LABEL, compute_takeoff, verify_reconciliation  # noqa: E402

DATA = ROOT / "data"
PLANS = [json.loads(p.read_text()) for p in sorted((DATA / "plans").glob("plan-*.json"))]



def test_takeoff_maths_and_labels():
    plan = PLANS[0]  # Maple Court ADU: 85 m2, 0.15 m slab, 62 m x 2.7 m walls
    result = compute_takeoff(plan)
    totals = result.totals
    assert totals["concrete"] == round(85 * 0.15 * 1.05, 2) == 13.39
    assert totals["bricks"] == int(62 * 2.7 * 50) == 8370
    assert totals["tiles"] == round(28 * 1.10, 2) == 30.8
    assert totals["timber"] == round(120 * 1.05, 1) == 126.0
    assert totals["steel"] == round(13.39 * 85, 1)  # spec clause 3.4 rate
    assert all(line.estimate_label == ESTIMATE_LABEL for line in result.lines)
    assert all("x" in line.method for line in result.lines)
    assert verify_reconciliation(result, plan)["ok"] is True
    assert result.flagged_lines() == []
    # Missing inputs -> flagged line, no quantity, never a silent number.
    incomplete = dict(plan, floor_area_m2=None)
    bad = compute_takeoff(incomplete)
    assert bad.totals.get("concrete") is None
    assert any(line.material == "concrete" and line.flagged for line in bad.lines)


def test_takeoff_applies_typed_requirement_on_plan():
    """Backend half of the 2026-11-10 fix: a typed quantity updates
    its material's plan line (old value kept in the method), a new
    material appends a line, an item with no quantity is skipped."""
    from app.takeoff.engine import apply_requirement_to_result

    plan = PLANS[0]  # concrete 13.39 m3 from the plan
    result = compute_takeoff(plan)
    apply_requirement_to_result(
        result, [{"item": "concrete", "quantity": 10, "unit": "m3"}])
    conc = next(line for line in result.lines if line.material == "concrete")
    assert conc.quantity == 10 and conc.unit == "m3"
    assert "13.39" in conc.method and "overrides" in conc.method
    assert conc.estimate_label == ESTIMATE_LABEL
    # Steel is derived from concrete in the plan takeoff — it is NOT
    # silently recomputed from the typed concrete (that would invent a
    # steel quantity the user never stated).
    steel = next(line for line in result.lines if line.material == "steel")
    assert steel.quantity == round(13.39 * 85, 1)
    # New material appends; no-quantity item is skipped.
    apply_requirement_to_result(
        result, [{"item": "cement", "quantity": 20, "unit": "bags"},
                 {"item": "rebar", "quantity": None, "unit": "kg"}])
    assert any(line.material == "Cement" and line.quantity == 20
               for line in result.lines)
    assert not any(line.material == "Rebar" for line in result.lines)


def test_run_takeoff_merges_plan_and_typed_items():
    """run_takeoff: plan takeoff + typed items merged (typed wins on
    its material), and requirement-only fallback when there is no plan.
    Before the fix the plan path returned the plan takeoff and
    silently discarded every typed quantity."""
    from app.integrations import run_takeoff

    plan = PLANS[0]
    lines = run_takeoff(
        {"items": [{"item": "concrete", "quantity": 10, "unit": "m3"}]},
        plan)
    conc = next(line for line in lines if line["material"] == "concrete")
    assert conc["quantity"] == 10 and conc["unit"] == "m3"
    assert "13.39" in conc["method"]
    assert conc["estimate_label"] == ESTIMATE_LABEL
    # No plan at all: takeoff is just the typed items, labelled estimate.
    lines = run_takeoff(
        {"items": [{"item": "steel brackets", "quantity": 50, "unit": "pcs"}]},
        None)
    assert len(lines) == 1
    assert lines[0]["material"] == "Steel brackets"
    assert lines[0]["quantity"] == 50 and lines[0]["unit"] == "pcs"
    assert lines[0]["estimate_label"] == ESTIMATE_LABEL
    # No items and no plan: no lines, never an invented quantity.
    assert run_takeoff({"items": []}, None) == []
