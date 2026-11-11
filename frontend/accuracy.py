"""Accuracy dashboard — pure logic, no Streamlit import (frontend/accuracy.py).

The 8 separate metrics (never blended into one score), headline cards,
alert thresholds and trend series. The Streamlit Accuracy tab
(frontend/app.py) renders what this module computes;
``tests/test_frontend.py`` covers it without Streamlit installed.

Evaluations are INTERNAL only: eval generation, eval runs, worst-answer
review and raw-event checks live in the backend / tests / CI — none of
them is rendered in this UI, and this module carries no evaluation
actions. The tab shows the observability dashboard only.

METRIC_DEFS must agree with the backend's ``app/observability.py``
METRIC_DEFS on key, formula and target — enforced by a test.
"""
import json
import os
import urllib.error
import urllib.request

from helpers import API_URL

METRIC_DEFS = [
    {"key": "groundedness", "name": "Groundedness",
     "formula": "grounded answers ÷ all answers",
     "source": "qa_log (grounded flag)",
     "target": "≥ 95%", "target_value": 0.95, "alert_below": 0.90,
     "direction": "higher", "unit": "rate"},
    {"key": "retrieval_top1", "name": "Retrieval accuracy",
     "formula": "RAG top-1 correct ÷ eval set (top-3 shown alongside)",
     "source": "eval_runs (fixed eval set)",
     "target": "top-1 ≥ 90%", "target_value": 0.90, "alert_below": 0.85,
     "direction": "higher", "unit": "rate"},
    {"key": "thumbs_up_rate", "name": "Answer accuracy",
     "formula": "👍 ÷ (👍 + 👎); “not found” rate counted separately",
     "source": "qa_log (thumbs) + qa_feedback",
     "target": "≥ 90%", "target_value": 0.90, "alert_below": 0.85,
     "direction": "higher", "unit": "rate"},
    {"key": "takeoff_mape", "name": "Takeoff estimate accuracy",
     "formula": "mean absolute % error vs user-corrected quantities",
     "source": "materials (user-corrected lines)",
     "target": "mean error ≤ 10%", "target_value": 0.10, "alert_above": 0.20,
     "direction": "lower", "unit": "rate"},
    {"key": "ranking_top1_rate", "name": "Supplier ranking accuracy",
     "formula": "chosen supplier was ranked #1 ÷ orders placed",
     "source": "orders + shortlist (best_value_rank)",
     "target": "≥ 50%", "target_value": 0.50, "alert_below": 0.40,
     "direction": "higher", "unit": "rate"},
    {"key": "buyer_agent", "name": "Buyer-agent accuracy",
     "formula": "quotes agreed ÷ quotes sent; approval-before-order = 100% (invariant)",
     "source": "outbox / quotes / approval_requests / orders",
     "target": "approval-before-order 100%", "target_value": 1.0,
     "alert_below": 1.0, "direction": "higher", "unit": "rate"},
    {"key": "guardrail_block_rate", "name": "Guardrail block rate",
     "formula": "blocked or redacted ÷ adversarial inputs (eval set); live false-positive rate shown separately",
     "source": "eval_runs + observability_events (guardrail_action)",
     "target": "100% on adversarial set; false positives < 5%",
     "target_value": 1.0, "alert_below": 0.99,
     "direction": "higher", "unit": "rate"},
    {"key": "cost_cache_speed", "name": "Cost / cache / speed",
     "formula": "cache hit rate + $ saved; latency p50/p95 per step; cost per query / per job",
     "source": "observability_events (cache_hit, cost_usd, latency_ms)",
     "target": "cache hit ≥ 50%; p95 ask latency < 10 s",
     "target_value": 0.50, "alert_below": 0.30,
     "direction": "higher", "unit": "rate"},
]

# Alert thresholds drawn as dashed lines on the trend charts.
ALERT_THRESHOLDS = {
    "groundedness": 0.90,
    "retrieval_top1": 0.85,
    "eval_pass_rate": 0.90,
    "latency_p95_s": 10.0,
}


def format_value(value, unit="rate"):
    """Display for one metric value — "no data yet", never a guess."""
    if value is None:
        return "no data yet"
    if unit == "usd":
        return f"${value:.2f}"
    if unit == "ms":
        return f"{value} ms"
    return f"{value * 100:.1f}%" if isinstance(value, float) else str(value)


def metric_status(metric_def, value):
    """ok | alert | no_data — against the metric's own alert threshold."""
    if value is None:
        return "no_data"
    if metric_def["direction"] == "higher":
        return "alert" if value < metric_def.get("alert_below", 0) else "ok"
    return "alert" if value > metric_def.get("alert_above", 1) else "ok"


def dashboard_is_empty(dashboard):
    """True when every one of the 8 metrics has no data yet."""
    return all((m.get("value") is None) for m in dashboard.get("metrics", []))


def fetch_live_accuracy(api_url=None, timeout=2):
    """GET /accuracy from the backend. Returns the dashboard dict, or
    None when the backend is unreachable — the caller then shows the
    labelled synthetic demo dashboard instead of inventing live data.
    Never raises.
    """
    url = (api_url or API_URL).rstrip("/") + "/accuracy"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


def _as_fraction(value):
    """Normalise a series value to a 0–1 fraction: fractions pass
    through, percentages (92) become 0.92, None stays None."""
    if value is None:
        return None
    return value / 100.0 if value > 1 else value


def trend_rows(days, groundedness, retrieval_top1, eval_pass):
    """One row per day for the accuracy trend chart. Series may be
    fractions (0.92) or percentages (92) — both become percentages.
    None stays None (no data yet). Kept pure so the chart data is
    testable."""
    rows = []
    for i, day in enumerate(days):
        def _pct(series):
            v = _as_fraction(series[i] if i < len(series) else None)
            return None if v is None else round(v * 100, 1)
        rows.append({
            "Day": day,
            "Groundedness %": _pct(groundedness),
            "Retrieval top-1 %": _pct(retrieval_top1),
            "Eval pass %": _pct(eval_pass),
        })
    return rows


def cost_rows(days, cost_per_job, latency_p95_s):
    """One row per day for the cost/latency trend chart."""
    return [{
        "Day": day,
        "Cost per job ($)": cost_per_job[i],
        "p95 ask latency (s)": latency_p95_s[i],
    } for i, day in enumerate(days)]
