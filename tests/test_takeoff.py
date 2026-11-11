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
