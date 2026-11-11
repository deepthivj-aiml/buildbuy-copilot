"""Tests for eval generator + runner — grounded pairs, measured retrieval/groundedness/guardrail metrics.

Run alone:  .venv/bin/python -m pytest tests/test_evals.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evals.eval_gen import build_and_export, dedupe_pairs, generate_eval_pairs, quality_check, run_eval  # noqa: E402
from app.rag.retrieval import HybridRetrieval, load_plan_corpus  # noqa: E402

DATA = ROOT / "data"
PLANS = [json.loads(p.read_text()) for p in sorted((DATA / "plans").glob("plan-*.json"))]
from app.suppliers.directory import load_suppliers  # noqa: E402
SUPPLIERS = load_suppliers(DATA)



def test_eval_generation_and_runner():
    pairs = generate_eval_pairs(PLANS, SUPPLIERS)
    assert len(pairs) >= 40, f"only {len(pairs)} pairs"
    assert len({p["question"].strip().lower() for p in pairs}) == len(pairs), "duplicates!"
    qc = quality_check(pairs, load_plan_corpus(DATA))
    assert qc["pass"] is True, qc["ungrounded"]
    ret = HybridRetrieval(load_plan_corpus(DATA))
    metrics = run_eval(ret, pairs)
    assert metrics["groundedness"] >= 0.9, metrics
    assert metrics["retrieval_top3"] >= 0.9, metrics
    assert metrics["guardrail_block_rate"] == 1.0, metrics
    # Top-1 is reported, not forced — but the fixed set should clear 0.85.
    assert metrics["retrieval_top1"] >= 0.85, metrics
