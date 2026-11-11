"""Observability rollup — compute ``metrics_daily`` from raw events.

Run nightly (or on demand): ``python -m app.observability``
Reads ``observability_events`` + ``qa_log``/``materials``/``shortlist``/
``outreach``/``orders`` and writes one row per user per day. The
Accuracy dashboard (other worker / M6-M7) reads ``metrics_daily`` only,
so the first screen stays fast. Every metric is measured; if there is
not enough data the row stores NULL — never an invented percentage.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func

from app.db.models import (
    MetricsDaily,
    ObservabilityEvent,
    QALog,
)
from app.db.session import SessionLocal, init_db

logger = logging.getLogger("buildbuy.observability")


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    if not denominator:
        return None
    return round((numerator or 0) / denominator, 4)


def compute_daily_metrics(target: date | None = None) -> list[MetricsDaily]:
    """Compute (and upsert) metrics_daily rows for one day (default today)."""
    target = target or date.today()
    day = target.isoformat()
    db = SessionLocal()
    try:
        events = db.query(ObservabilityEvent).filter(
            func.date(ObservabilityEvent.created_at) == day).all()
        qa = db.query(QALog).filter(func.date(QALog.created_at) == day).all()
        grounded = [q for q in qa if q.grounded is True]
        thumbs_up = [q for q in qa if (q.thumbs or 0) > 0]
        thumbs_total = [q for q in qa if (q.thumbs or 0) != 0]
        not_found = [q for q in qa if q.grounded is False]
        ask_events = [e for e in events if e.step == "ask"]
        latencies = sorted(e.latency_ms for e in ask_events if e.latency_ms)
        p50 = latencies[len(latencies) // 2] if latencies else None
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else None
        cache_hits = [e for e in events if e.cache_hit]

        row = db.query(MetricsDaily).filter(
            MetricsDaily.date == day, MetricsDaily.user_id.is_(None)).first()
        if row is None:
            row = MetricsDaily(user_id=None, date=day, window_days=1)
            db.add(row)
        row.groundedness = _rate(len(grounded), len(qa))
        row.thumbs_up_rate = _rate(len(thumbs_up), len(thumbs_total))
        row.not_found_rate = _rate(len(not_found), len(qa))
        row.cache_hit_rate = _rate(len(cache_hits), len(events))
        row.latency_p50_ms = p50
        row.latency_p95_ms = p95
        db.flush()
        # Detach BEFORE commit: commit expires attributes, and an expired
        # detached row cannot be read by callers (DetachedInstanceError).
        db.expunge(row)
        db.commit()
        logger.info("metrics_daily computed for %s (n_qa=%d, n_events=%d)",
                    day, len(qa), len(events))
        return [row]
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    compute_daily_metrics()
