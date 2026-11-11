"""Tests for ranking (cost + quality + landed cost) — canonical best-value blend, evidence-only quality, lead term.

Run alone:  .venv/bin/python -m pytest tests/test_ranking.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ranking import rank_shortlist  # noqa: E402

DATA = ROOT / "data"


def test_ranking_best_value_is_not_cheapest_alone():
    entries = rank_shortlist([
        {"landed_cost": 200.0, "quality_score": 55.0, "supplier_id": "cheap"},
        {"landed_cost": 380.0, "quality_score": 92.0, "supplier_id": "best-q"},
        {"landed_cost": 300.0, "quality_score": 75.0, "supplier_id": "mid"},
    ])
    by_id = {e["supplier_id"]: e for e in entries}
    assert by_id["cheap"]["is_cheapest"] is True
    assert by_id["best-q"]["is_highest_quality"] is True
    # Canonical blend (app/suppliers/search.py): 0.45 cost + 0.35 quality
    # + 0.20 lead; no lead_time_days here, so lead is neutral 0.5 for all.
    # Ratio-based cost scores: cheap=100, mid=66.67, best-q=52.63.
    # cheap: 0.45*1.00 + 0.35*0.55 + 0.20*0.50 = 0.7425 -> 0.743 (float
    # rounding at 3 decimals in best_value_score) -> 74.3
    # mid:   0.45*0.6667 + 0.35*0.75 + 0.20*0.50 = 0.6625 -> 0.663 -> 66.3
    # best-q: 0.45*0.5263 + 0.35*0.92 + 0.20*0.50 = 0.6588 -> 0.659 -> 65.9
    # So best value here IS the cheapest, but only because its quality
    # penalty is small; the rank is a blend, not the cost rank alone
    # (see the next test, where quality wins outright).
    assert by_id["cheap"]["best_value_score"] == 74.3
    assert by_id["mid"]["best_value_score"] == 66.3
    assert by_id["best-q"]["best_value_score"] == 65.9
    assert by_id["cheap"]["best_value_rank"] == 1
    assert by_id["mid"]["best_value_rank"] == 2
    assert by_id["best-q"]["best_value_rank"] == 3


def test_ranking_lead_time_breaks_a_tie():
    """Same cost, same quality — the shorter lead time wins (0.20 lead term)."""
    entries = rank_shortlist([
        {"landed_cost": 300.0, "quality_score": 80.0, "supplier_id": "slow",
         "lead_time_days": 10},
        {"landed_cost": 300.0, "quality_score": 80.0, "supplier_id": "fast",
         "lead_time_days": 2},
    ])
    by_id = {e["supplier_id"]: e for e in entries}
    assert by_id["fast"]["lead_score"] == 1.0
    assert by_id["slow"]["lead_score"] == 0.0
    assert by_id["fast"]["best_value_rank"] == 1
    assert by_id["slow"]["best_value_rank"] == 2


def test_ranking_quality_can_win_over_cost():
    entries = rank_shortlist([
        {"landed_cost": 200.0, "quality_score": 20.0, "supplier_id": "cheap-bad"},
        {"landed_cost": 210.0, "quality_score": 95.0, "supplier_id": "good"},
    ])
    by_id = {e["supplier_id"]: e for e in entries}
    assert by_id["cheap-bad"]["is_cheapest"] is True
    assert by_id["good"]["is_highest_quality"] is True
    assert by_id["good"]["best_value_rank"] == 1  # quality wins the blend
    assert by_id["cheap-bad"]["best_value_rank"] == 2


def test_ranking_no_quality_evidence_falls_back_to_cost_and_flags_it():
    entries = rank_shortlist([
        {"landed_cost": 200.0, "quality_score": None, "supplier_id": "a"},
        {"landed_cost": 300.0, "quality_score": None, "supplier_id": "b"},
    ])
    assert all(e["quality_unknown"] for e in entries)
    assert all(e["no_quality_evidence"] for e in entries)
    assert entries[0]["best_value_rank"] == 1  # cheapest first, honestly flagged
    assert all(e["is_highest_quality"] is False for e in entries)
