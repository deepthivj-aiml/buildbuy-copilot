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
