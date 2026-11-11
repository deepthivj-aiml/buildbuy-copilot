"""Tests for observability / accuracy (app/observability.py).

Metrics are measured only: with no data the row stores NULL, never an
invented percentage. The Accuracy dashboard reads metrics_daily only.

Run alone:  .venv/bin/python -m pytest tests/test_observability.py -v
"""
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "test_obs.db")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import ObservabilityEvent, QALog, User  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.observability import _rate, compute_daily_metrics  # noqa: E402

init_db()


def test_rate_returns_none_without_data():
    assert _rate(3, 4) == 0.75
    assert _rate(None, 0) is None
    assert _rate(0, 0) is None  # never an invented percentage


def test_compute_daily_metrics_empty_db_returns_rows_with_nulls():
    # A date with no events at all: one row, NULL metrics — never invented.
    # (A far-past date, so other tests' rows for today can never leak in:
    # all test files share one temp DB in a pytest run, via cached settings.)
    rows = compute_daily_metrics(target=date(2031, 5, 18))
    assert len(rows) == 1
    assert rows[0].groundedness is None
    assert rows[0].thumbs_up_rate is None


def test_compute_daily_metrics_measures_groundedness():
    from datetime import datetime

    from app.db.models import Requirement

    day = date(2031, 5, 17)
    stamp = datetime(2031, 5, 17, 12, 0, 0)
    db = SessionLocal()
    user = User(email="obs@example.com")
    db.add(user)
    db.commit()
    req = Requirement(user_id=user.id, source_type="typed", raw_text="test")
    db.add(req)
    db.commit()
    db.add(QALog(requirement_id=req.id, question="q1",
                 answer="a1", grounded=True, created_at=stamp))
    db.add(QALog(requirement_id=req.id, question="q2",
                 answer="a2", grounded=False, created_at=stamp))
    db.add(ObservabilityEvent(request_id="r1", user_id=user.id,
                              requirement_id=req.id, step="ask",
                              latency_ms=120, grounded=True,
                              created_at=stamp))
    db.commit()
    rows = compute_daily_metrics(target=day)
    assert len(rows) == 1
    assert rows[0].user_id is None  # global rollup, not per-user
    assert rows[0].groundedness == 0.5  # 1 of 2 grounded — measured
    db.close()


def test_metric_defs_are_eight_separate_never_blended():
    from app.observability import METRIC_DEFS

    assert len(METRIC_DEFS) == 8
    keys = [d["key"] for d in METRIC_DEFS]
    assert len(set(keys)) == 8  # unique keys
    assert "blended" not in " ".join(keys).lower()
    for d in METRIC_DEFS:
        assert d["formula"] and d["source"] and d["target"]
        assert d["direction"] in ("higher", "lower")
        assert "target_value" in d


def test_compute_daily_metrics_populates_eval_ranking_guardrail_cost():
    """Eval runs feed retrieval/guardrail; orders feed ranking; events
    feed cost/cache/latency. Takeoff stays NULL — no corrected pairs."""
    from datetime import datetime

    from app.db.models import (ApprovalRequest, EvalRun, Order, Requirement,
                               Shortlist, Supplier)

    day = date(2031, 5, 16)
    stamp = datetime(2031, 5, 16, 10, 0, 0)
    db = SessionLocal()
    user = User(email="obs2@example.com")
    db.add(user)
    db.commit()
    req = Requirement(user_id=user.id, source_type="typed", raw_text="test")
    db.add(req)
    db.commit()
    sup = Supplier(name="Top Supplier", location="Fremont")
    db.add(sup)
    db.commit()
    db.add(Shortlist(requirement_id=req.id, supplier_id=sup.id,
                     best_value_rank=1, best_value_score=90))
    db.add(EvalRun(eval_set="plan-qa v3", groundedness=0.96,
                   retrieval_top1=0.92, guardrail_block_rate=1.0,
                   cache_hit_rate=0.6, run_at=stamp))
    db.add(ObservabilityEvent(request_id="r2", user_id=user.id,
                              requirement_id=req.id, step="ask",
                              latency_ms=200, cache_hit=True, cost_usd=0.02,
                              created_at=stamp))
    db.add(ObservabilityEvent(request_id="r2", user_id=user.id,
                              requirement_id=req.id, step="ask",
                              latency_ms=100, cache_hit=False, cost_usd=0.04,
                              created_at=stamp))
    order = Order(requirement_id=req.id, supplier_id=sup.id, status="APPROVED")
    order.created_at = stamp
    db.add(order)
    db.add(ApprovalRequest(deal_id=req.id, status="APPROVED",
                           decided_at=stamp))
    db.commit()
    rows = compute_daily_metrics(target=day)
    row = rows[0]
    assert row.retrieval_top1 == 0.92
    assert row.guardrail_block_rate == 1.0
    assert row.ranking_top1_rate == 1.0  # chosen supplier was ranked #1
    assert row.cache_hit_rate == 0.5
    assert row.cost_per_job_usd == 0.06  # $0.06 total / 1 order
    assert row.takeoff_mape is None  # no corrected quantities recorded
    db.close()


def test_build_accuracy_dashboard_empty_is_all_no_data():
    # Isolated empty DB: the full suite shares one temp DB, so other
    # files' rows would leak into this check.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base
    from app.observability import build_accuracy_dashboard

    engine = create_engine("sqlite:///" + os.path.join(
        tempfile.mkdtemp(), "empty_obs.db"))
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    dash = build_accuracy_dashboard(db, days=1)
    assert len(dash["metrics"]) == 8
    # No metrics_daily rows, no orders, no events: every metric is None
    # — the UI must say "no data yet", never a number.
    assert all(m["value"] is None for m in dash["metrics"])
    assert dash["approval_before_order"] is None
    assert dash["alerts"] == []
    db.close()


def test_build_accuracy_dashboard_worst_answers_and_raw_events():
    """Thumbs-down / ungrounded QA rows become Worst Answers; raw events
    expose PII-free fields only — no prompt, plan text or email body."""
    from datetime import datetime

    from app.db.models import Requirement

    db = SessionLocal()
    user = User(email="obs3@example.com")
    db.add(user)
    db.commit()
    req = Requirement(user_id=user.id, source_type="typed", raw_text="test")
    db.add(req)
    db.commit()
    bad = QALog(requirement_id=req.id, question="How many bolts?",
                answer="100", grounded=False, thumbs=-1,
                citation_spec_clause="Spec §5.3",
                created_at=datetime(2031, 5, 15, 9, 0, 0))
    db.add(bad)
    db.add(ObservabilityEvent(
        request_id="req-x", user_id=user.id, requirement_id=req.id,
        step="ask", model="local-tfidf", latency_ms=120, grounded=False,
        cache_hit=False, guardrail_action="allow", cost_usd=0.0,
        created_at=datetime(2031, 5, 15, 9, 0, 0)))
    db.commit()
    from app.observability import build_accuracy_dashboard

    dash = build_accuracy_dashboard(db, days=3650)
    worst = [w for w in dash["worst_answers"] if w["qa_log_id"] == bad.id]
    assert len(worst) == 1
    assert worst[0]["status"] == "open"
    assert worst[0]["question"] == "How many bolts?"
    event = [e for e in dash["raw_events"] if e["request_id"] == "req-x"]
    assert len(event) == 1
    assert set(event[0]) <= {"request_id", "step", "model", "latency_ms",
                             "grounded", "cache_hit", "guardrail_action",
                             "cost_usd", "created_at"}
    assert "body" not in event[0] and "prompt" not in event[0]
    db.close()


def test_record_worst_answer_action_adds_once_then_refuses():
    from datetime import datetime

    from app.db.models import Requirement
    from app.observability import record_worst_answer_action

    db = SessionLocal()
    user = User(email="obs4@example.com")
    db.add(user)
    db.commit()
    req = Requirement(user_id=user.id, source_type="typed", raw_text="test")
    db.add(req)
    db.commit()
    qa = QALog(requirement_id=req.id, question="q?", answer="a",
               grounded=False, thumbs=-1,
               created_at=datetime(2031, 5, 14, 9, 0, 0))
    db.add(qa)
    db.commit()
    out = record_worst_answer_action(db, qa.id, "add_to_eval_set")
    assert out["status"] == "in_eval_set"
    again = record_worst_answer_action(db, qa.id, "add_to_eval_set")
    assert again["error"] == "already recorded"
    fixed = record_worst_answer_action(db, qa.id, "mark_fixed")
    # Already in the eval set: the status stays recorded, never duplicated.
    assert fixed["error"] == "already recorded"
    try:
        record_worst_answer_action(db, qa.id, "delete")
    except ValueError as exc:
        assert "unknown action" in str(exc)
    else:
        raise AssertionError("unknown action must raise ValueError")
    db.close()
