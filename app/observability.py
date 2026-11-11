"""Observability rollup + Accuracy dashboard payload.

* ``compute_daily_metrics`` — nightly (or on-demand) rollup into
  ``metrics_daily`` from raw events. Every metric is measured; if there
  is not enough data the row stores NULL — never an invented percentage.
* ``METRIC_DEFS`` — the 8 separate Accuracy metrics (never blended into
  one score). Each has a formula, a source table, a proposed target and
  an alert threshold. The frontend mirrors these definitions in
  ``frontend/accuracy.py`` — ``tests/test_frontend.py`` checks the two
  lists agree on key, formula and target.
* ``build_accuracy_dashboard`` — the whole Accuracy tab payload as plain
  dicts: 8 metrics, 4 headline cards, 30-day trends, per-module
  breakdown, Worst Answers (10 lowest), Eval Run History, raw-event
  drill-down, and triggered alerts. Served by ``GET /accuracy``.

Run the rollup: ``python -m app.observability``
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func

from app.db.models import (
    ApprovalRequest,
    AuditLog,
    EvalRun,
    MetricsDaily,
    ObservabilityEvent,
    Order,
    QALog,
    Shortlist,
)
from app.db.session import SessionLocal, init_db

logger = logging.getLogger("buildbuy.observability")

# ---------------------------------------------------------------------------
# The 8 metrics — one definition each, never blended into a single score.
# Targets are PROPOSED (plan §9), to confirm at build time; they are not
# claimed results. "direction" says which way is good.
# ---------------------------------------------------------------------------
METRIC_DEFS = [
    {
        "key": "groundedness",
        "name": "Groundedness",
        "formula": "grounded answers ÷ all answers",
        "source": "qa_log (grounded flag)",
        "target": "≥ 95%",
        "target_value": 0.95,
        "alert_below": 0.90,
        "direction": "higher",
        "unit": "rate",
    },
    {
        "key": "retrieval_top1",
        "name": "Retrieval accuracy",
        "formula": "RAG top-1 correct ÷ eval set (top-3 shown alongside)",
        "source": "eval_runs (fixed eval set)",
        "target": "top-1 ≥ 90%",
        "target_value": 0.90,
        "alert_below": 0.85,
        "direction": "higher",
        "unit": "rate",
    },
    {
        "key": "thumbs_up_rate",
        "name": "Answer accuracy",
        "formula": "👍 ÷ (👍 + 👎); “not found” rate counted separately",
        "source": "qa_log (thumbs) + qa_feedback",
        "target": "≥ 90%",
        "target_value": 0.90,
        "alert_below": 0.85,
        "direction": "higher",
        "unit": "rate",
    },
    {
        "key": "takeoff_mape",
        "name": "Takeoff estimate accuracy",
        "formula": "mean absolute % error vs user-corrected quantities",
        "source": "materials (user-corrected lines)",
        "target": "mean error ≤ 10%",
        "target_value": 0.10,
        "alert_above": 0.20,
        "direction": "lower",
        "unit": "rate",
    },
    {
        "key": "ranking_top1_rate",
        "name": "Supplier ranking accuracy",
        "formula": "chosen supplier was ranked #1 ÷ orders placed",
        "source": "orders + shortlist (best_value_rank)",
        "target": "≥ 50%",
        "target_value": 0.50,
        "alert_below": 0.40,
        "direction": "higher",
        "unit": "rate",
    },
    {
        "key": "buyer_agent",
        "name": "Buyer-agent accuracy",
        "formula": "quotes agreed ÷ quotes sent; approval-before-order = 100% (invariant)",
        "source": "outbox / quotes / approval_requests / orders",
        "target": "approval-before-order 100%",
        "target_value": 1.0,
        "alert_below": 1.0,
        "direction": "higher",
        "unit": "rate",
    },
    {
        "key": "guardrail_block_rate",
        "name": "Guardrail block rate",
        "formula": "blocked or redacted ÷ adversarial inputs (eval set); live false-positive rate shown separately",
        "source": "eval_runs + observability_events (guardrail_action)",
        "target": "100% on adversarial set; false positives < 5%",
        "target_value": 1.0,
        "alert_below": 0.99,
        "direction": "higher",
        "unit": "rate",
    },
    {
        "key": "cost_cache_speed",
        "name": "Cost / cache / speed",
        "formula": "cache hit rate + $ saved; latency p50/p95 per step; cost per query / per job",
        "source": "observability_events (cache_hit, cost_usd, latency_ms)",
        "target": "cache hit ≥ 50%; p95 ask latency < 10 s",
        "target_value": 0.50,
        "alert_below": 0.30,
        "direction": "higher",
        "unit": "rate",
    },
]

# Eval-run pass gate (used for eval_pass_rate and Eval Run History).
EVAL_PASS_GROUNDEDNESS = 0.90
EVAL_PASS_RETRIEVAL_TOP1 = 0.85


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    if not denominator:
        return None
    return round((numerator or 0) / denominator, 4)


def _mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(float(v) for v in vals) / len(vals), 4)


def _eval_pass(run: EvalRun) -> bool:
    return (
        (run.groundedness or 0) >= EVAL_PASS_GROUNDEDNESS
        and (run.retrieval_top1 or 0) >= EVAL_PASS_RETRIEVAL_TOP1
    )


def compute_daily_metrics(target: date | None = None) -> list[MetricsDaily]:
    """Compute (and upsert) metrics_daily rows for one day (default today).

    Every field is measured from that day's rows only. Fields with no
    source data stay NULL — including takeoff_mape: material edits
    overwrite the quantity in place (``PATCH /materials`` keeps no
    original quantity), so there is no corrected-vs-estimate pair to
    measure yet. That gap is recorded in docs, not papered over.
    """
    target = target or date.today()
    day = target.isoformat()
    db = SessionLocal()
    try:
        events = db.query(ObservabilityEvent).filter(
            func.date(ObservabilityEvent.created_at) == day).all()
        qa = db.query(QALog).filter(func.date(QALog.created_at) == day).all()
        eval_runs = db.query(EvalRun).filter(
            func.date(EvalRun.run_at) == day).all()
        orders = db.query(Order).filter(
            func.date(Order.created_at) == day).all()
        approvals = db.query(ApprovalRequest).filter(
            func.date(ApprovalRequest.decided_at) == day).all()
        decided = [a for a in approvals if a.status in ("APPROVED", "REJECTED")]

        grounded = [q for q in qa if q.grounded is True]
        thumbs_up = [q for q in qa if (q.thumbs or 0) > 0]
        thumbs_total = [q for q in qa if (q.thumbs or 0) != 0]
        not_found = [q for q in qa if q.grounded is False]
        ask_events = [e for e in events if e.step == "ask"]
        latencies = sorted(e.latency_ms for e in ask_events if e.latency_ms)
        p50 = latencies[len(latencies) // 2] if latencies else None
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else None
        cache_hits = [e for e in events if e.cache_hit]
        blocked = [e for e in events
                   if (e.guardrail_action or "") in ("block", "redact", "blocked", "redacted")]
        guardrailed = [e for e in events if (e.guardrail_action or "allow") != "allow"]

        # Ranking: orders whose supplier was the #1 best-value pick.
        ranked_orders = 0
        top1_orders = 0
        for o in orders:
            if not o.supplier_id:
                continue
            row = db.query(Shortlist).filter(
                Shortlist.requirement_id == o.requirement_id,
                Shortlist.supplier_id == o.supplier_id).first()
            if row is not None and row.best_value_rank is not None:
                ranked_orders += 1
                if row.best_value_rank == 1:
                    top1_orders += 1

        # Buyer agent: reply rate = inbound supplier messages ÷ outbound
        # buyer messages is tracked in the dashboard from Message rows;
        # here the daily rollup uses quotes-received vs outreach sent via
        # orders/approvals only — negotiation success = approved ÷ decided.
        # Approval-before-order is an invariant, checked in the dashboard.
        total_cost = sum(float(e.cost_usd or 0) for e in events)
        non_hit_costs = [float(e.cost_usd or 0) for e in ask_events if not e.cache_hit]
        avg_cost = (sum(non_hit_costs) / len(non_hit_costs)) if non_hit_costs else 0.0
        cost_saved = round(len(cache_hits) * avg_cost, 2)

        row = db.query(MetricsDaily).filter(
            MetricsDaily.date == day, MetricsDaily.user_id.is_(None)).first()
        if row is None:
            row = MetricsDaily(user_id=None, date=day, window_days=1)
            db.add(row)
        row.groundedness = _rate(len(grounded), len(qa))
        row.retrieval_top1 = _mean([r.retrieval_top1 for r in eval_runs])
        row.retrieval_top3 = _mean([getattr(r, "retrieval_top3", None) for r in eval_runs])
        row.thumbs_up_rate = _rate(len(thumbs_up), len(thumbs_total))
        row.not_found_rate = _rate(len(not_found), len(qa))
        row.takeoff_mape = None  # no corrected-vs-estimate pairs recorded yet
        row.takeoff_unchanged_rate = None
        row.ranking_top1_rate = _rate(top1_orders, ranked_orders)
        row.reply_rate = _rate(len([o for o in orders if o.status != "PENDING"]),
                               len(orders)) if orders else None
        row.negotiation_success_rate = _rate(
            len([a for a in decided if a.status == "APPROVED"]), len(decided))
        row.approval_rate = row.negotiation_success_rate
        row.guardrail_block_rate = (
            _mean([r.guardrail_block_rate for r in eval_runs]) if eval_runs
            else _rate(len(blocked), len(guardrailed)))
        row.guardrail_false_positive_rate = None  # needs labelled live FP review
        row.cache_hit_rate = _rate(len(cache_hits), len(events))
        row.cost_saved_usd = cost_saved
        row.cost_per_query_usd = (
            round(total_cost / len(ask_events), 4) if ask_events else None)
        row.cost_per_job_usd = (
            round(total_cost / len(orders), 4) if orders else None)
        row.latency_p50_ms = p50
        row.latency_p95_ms = p95
        row.eval_pass_rate = (
            _rate(len([r for r in eval_runs if _eval_pass(r)]), len(eval_runs))
            if eval_runs else None)
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


def _worst_answer_status(db, qa_id: str) -> str:
    """open | in_eval_set | fixed — from AuditLog actions on the QA row."""
    # JSON-detail filtering is backend-specific; filter in Python instead.
    actions = []
    for a in db.query(AuditLog).filter(
            AuditLog.action.in_(("worst_answer_added_to_eval",
                                 "worst_answer_marked_fixed"))).all():
        if (a.detail or {}).get("qa_log_id") == qa_id:
            actions.append(a.action)
    if "worst_answer_marked_fixed" in actions:
        return "fixed"
    if "worst_answer_added_to_eval" in actions:
        return "in_eval_set"
    return "open"


def build_accuracy_dashboard(db, days: int = 30) -> dict:
    """Whole Accuracy tab payload as plain dicts (no Streamlit, no HTTP).

    ``db`` is a SQLAlchemy session. All values are measured or None;
    nothing is invented. ``metrics`` carries the 8 separate metrics with
    their value + n; ``alerts`` lists every metric currently below its
    alert threshold.
    """
    from app.db.models import Message, QAFeedback  # local import: models only

    today = date.today()
    start = (today - timedelta(days=days - 1)).isoformat()
    daily = db.query(MetricsDaily).filter(
        MetricsDaily.user_id.is_(None),
        MetricsDaily.date >= start).order_by(MetricsDaily.date).all()
    latest = daily[-1] if daily else None

    def _val(row, field):
        v = getattr(row, field, None) if row is not None else None
        return float(v) if v is not None else None

    def _in_window(ts):
        # Rows are windowed by calendar date so a 30-day dashboard never
        # counts last year's jobs. Rows without a timestamp count as in.
        if ts is None:
            return True
        try:
            return ts.date().isoformat() >= start
        except AttributeError:
            return True

    # --- sample sizes per metric (same day window as the rollup) -------
    qa_all = [q for q in db.query(QALog).all() if _in_window(q.created_at)]
    events_all = [e for e in db.query(ObservabilityEvent).all()
                  if _in_window(e.created_at)]
    eval_all = [r for r in db.query(EvalRun).all() if _in_window(r.run_at)]
    orders_all = [o for o in db.query(Order).all() if _in_window(o.created_at)]
    n = {
        "groundedness": len(qa_all),
        "retrieval_top1": len(eval_all),
        "thumbs_up_rate": len([q for q in qa_all if (q.thumbs or 0) != 0]),
        "takeoff_mape": 0,
        "ranking_top1_rate": len([o for o in orders_all if o.supplier_id]),
        "buyer_agent": len(orders_all),
        "guardrail_block_rate": len(eval_all) or len(
            [e for e in events_all if (e.guardrail_action or "allow") != "allow"]),
        "cost_cache_speed": len(events_all),
    }
    # Approval-before-order invariant: every order must have an APPROVED
    # ApprovalRequest for its requirement. Any violation is an alert.
    # The Buyer-agent metric's VALUE is this invariant (it must be 100%);
    # the quotes-agreed rate is reported alongside it, not blended in.
    violations = 0
    for o in orders_all:
        approved = db.query(ApprovalRequest).filter(
            ApprovalRequest.deal_id == o.requirement_id,
            ApprovalRequest.status == "APPROVED").first()
        if approved is None:
            violations += 1
    approval_before_order = (
        1.0 if orders_all and violations == 0 else
        (round(1 - violations / len(orders_all), 4) if orders_all else None))

    values = {
        "groundedness": _val(latest, "groundedness"),
        "retrieval_top1": _val(latest, "retrieval_top1"),
        "thumbs_up_rate": _val(latest, "thumbs_up_rate"),
        "takeoff_mape": _val(latest, "takeoff_mape"),
        "ranking_top1_rate": _val(latest, "ranking_top1_rate"),
        "buyer_agent": approval_before_order,
        "guardrail_block_rate": _val(latest, "guardrail_block_rate"),
        "cost_cache_speed": _val(latest, "cache_hit_rate"),
    }

    metrics = []
    alerts = []
    for d in METRIC_DEFS:
        key = d["key"]
        value = approval_before_order if key == "buyer_agent" else values[key]
        status = "no_data"
        if value is not None:
            if d["direction"] == "higher":
                status = ("alert" if value < d.get("alert_below", 0)
                          else "ok")
            else:
                status = ("alert" if value > d.get("alert_above", 1)
                          else "ok")
            if status == "alert":
                alerts.append({
                    "metric": d["name"],
                    "value": value, "threshold": d.get("alert_below", d.get("alert_above")),
                    "direction": d["direction"],
                })
        metrics.append({**d, "value": value, "n": n[key], "status": status,
                        "approval_before_order": approval_before_order
                        if key == "buyer_agent" else None,
                        "agreement_rate": _val(latest, "approval_rate")
                        if key == "buyer_agent" else None})

    headline = [
        {"label": "Groundedness (30d)", "value": values["groundedness"],
         "n": n["groundedness"], "unit": "rate"},
        {"label": "👍 rate", "value": values["thumbs_up_rate"],
         "n": n["thumbs_up_rate"], "unit": "rate"},
        {"label": "Takeoff mean error", "value": values["takeoff_mape"],
         "n": n["takeoff_mape"], "unit": "rate"},
        {"label": "Cost per completed job", "value": _val(latest, "cost_per_job_usd"),
         "n": len(orders_all), "unit": "usd"},
    ]
    trends = [{
        "date": r.date,
        "groundedness": float(r.groundedness) if r.groundedness is not None else None,
        "retrieval_top1": float(r.retrieval_top1) if r.retrieval_top1 is not None else None,
        "eval_pass_rate": float(r.eval_pass_rate) if r.eval_pass_rate is not None else None,
        "cost_per_job_usd": float(r.cost_per_job_usd) if r.cost_per_job_usd is not None else None,
        "latency_p95_ms": r.latency_p95_ms,
        "cache_hit_rate": float(r.cache_hit_rate) if r.cache_hit_rate is not None else None,
    } for r in daily]

    per_module = [
        {"module": "Plan Q&A", "metric": "Groundedness",
         "value": values["groundedness"], "n": n["groundedness"],
         "worst": "ungrounded answers in Worst Answers below"},
        {"module": "Retrieval (RAG)", "metric": "Retrieval top-1",
         "value": values["retrieval_top1"], "n": n["retrieval_top1"],
         "worst": "eval runs below the gate in Eval Run History"},
        {"module": "Takeoff", "metric": "Mean error (MAPE)",
         "value": values["takeoff_mape"], "n": n["takeoff_mape"],
         "worst": "no corrected lines recorded yet"},
        {"module": "Supplier ranking", "metric": "Chosen-was-#1",
         "value": values["ranking_top1_rate"], "n": n["ranking_top1_rate"],
         "worst": "orders where the chosen supplier was not ranked #1"},
        {"module": "Buyer agent", "metric": "Approval-before-order",
         "value": approval_before_order, "n": len(orders_all),
         "worst": f"{violations} order(s) without a prior approval" if violations else "none"},
        {"module": "Guardrails", "metric": "Block rate",
         "value": values["guardrail_block_rate"], "n": n["guardrail_block_rate"],
         "worst": "adversarial items that were NOT blocked (see eval runs)"},
        {"module": "Cache / cost", "metric": "Cache hit rate",
         "value": values["cost_cache_speed"], "n": n["cost_cache_speed"],
         "worst": f"p95 ask latency {_val(latest, 'latency_p95_ms')} ms"},
    ]

    # --- Worst Answers: thumbs-down or ungrounded, lowest first --------
    feedback_reason = {}
    for fb in db.query(QAFeedback).all():
        if fb.qa_log_id and fb.reason:
            feedback_reason[fb.qa_log_id] = fb.reason
    candidates = [q for q in qa_all if (q.thumbs or 0) < 0 or q.grounded is False]
    candidates.sort(key=lambda q: (0 if (q.thumbs or 0) < 0 else 1,
                                   q.created_at or date.min))
    worst = []
    for q in candidates[:10]:
        worst.append({
            "qa_log_id": q.id,
            "question": q.question,
            "answer": q.answer,
            "citations": (q.citation_spec_clause or "")
                         + (f" [{q.citation_image_region}]" if q.citation_image_region else ""),
            "thumbs": q.thumbs or 0,
            "grounded": q.grounded,
            "reason": feedback_reason.get(q.id, "thumbs down / ungrounded — no reason given"),
            "status": _worst_answer_status(db, q.id),
        })

    eval_runs = [{
        "date": (r.run_at.date().isoformat() if r.run_at else ""),
        "eval_set": r.eval_set,
        "groundedness": float(r.groundedness) if r.groundedness is not None else None,
        "retrieval_top1": float(r.retrieval_top1) if r.retrieval_top1 is not None else None,
        "guardrail_block_rate": float(r.guardrail_block_rate) if r.guardrail_block_rate is not None else None,
        "cache_hit_rate": float(r.cache_hit_rate) if r.cache_hit_rate is not None else None,
        "result": "PASS" if _eval_pass(r) else "FAIL",
    } for r in sorted(eval_all, key=lambda r: r.run_at or date.min, reverse=True)[:20]]

    # --- Raw-event drill-down: PII-free fields only --------------------
    # Prompts, plan text and email bodies are NEVER logged in full and
    # never returned here — only step/model/latency/citations/grounded/
    # cache_hit/guardrail_action/cost per request_id.
    raw_events = [{
        "request_id": e.request_id,
        "step": e.step,
        "model": e.model,
        "latency_ms": e.latency_ms,
        "grounded": e.grounded,
        "cache_hit": e.cache_hit,
        "guardrail_action": e.guardrail_action,
        "cost_usd": float(e.cost_usd or 0),
        "created_at": e.created_at.isoformat() if e.created_at else "",
    } for e in sorted(events_all, key=lambda e: e.created_at or date.min,
                      reverse=True)[:50]]

    return {
        "metrics": metrics,
        "headline": headline,
        "trends": trends,
        "per_module": per_module,
        "worst_answers": worst,
        "eval_runs": eval_runs,
        "raw_events": raw_events,
        "alerts": alerts,
        "approval_before_order": approval_before_order,
        "approval_violations": violations,
        "source": "metrics_daily + eval_runs + qa_log + observability_events (measured only)",
    }


def record_worst_answer_action(db, qa_id: str, action: str) -> dict:
    """Handle one Worst Answers action; returns the new status.

    ``add_to_eval_set`` appends the QA pair to
    ``data/evals/worst_answers_eval.jsonl`` (deduped by qa_log_id) and
    audits it; ``mark_fixed`` audits only. A second identical action is
    refused (409-style ``{"error": ...}``) so the eval set never gets
    the same pair twice. Raises ValueError for an unknown action or
    a missing QA row.
    """
    from app.db.models import QALog  # local import: models only

    if action not in ("add_to_eval_set", "mark_fixed"):
        raise ValueError(f"unknown action: {action}")
    qa = db.query(QALog).filter(QALog.id == qa_id).first()
    if qa is None:
        raise ValueError(f"qa_log {qa_id} not found")
    status = _worst_answer_status(db, qa_id)
    audit_action = ("worst_answer_added_to_eval" if action == "add_to_eval_set"
                    else "worst_answer_marked_fixed")
    if status in ("in_eval_set", "fixed"):
        return {"qa_log_id": qa_id, "status": status, "error": "already recorded"}
    if action == "add_to_eval_set":
        path = Path(__file__).resolve().parents[1] / "data" / "evals" / "worst_answers_eval.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = set()
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    existing.add(json.loads(line).get("qa_log_id"))
                except Exception:
                    continue
        if qa_id not in existing:
            with path.open("a") as f:
                f.write(json.dumps({
                    "qa_log_id": qa_id,
                    "question": qa.question,
                    "answer": qa.answer,
                    "citation_spec_clause": qa.citation_spec_clause,
                    "grounded": qa.grounded,
                    "source": "worst_answer",
                }) + "\n")
    db.add(AuditLog(requirement_id=qa.requirement_id, actor="user",
                    action=audit_action, detail={"qa_log_id": qa_id}))
    db.commit()
    return {"qa_log_id": qa_id,
            "status": "in_eval_set" if action == "add_to_eval_set" else "fixed"}


if __name__ == "__main__":
    init_db()
    compute_daily_metrics()
