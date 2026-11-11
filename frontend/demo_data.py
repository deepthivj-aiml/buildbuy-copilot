"""Demo data — synthetic only (frontend/demo_data.py).

All suppliers, materials, Q&A pairs and observability series used by the
Streamlit demo mode. Names, prices, certifications, reliability figures
and feedback are invented for the demo only — NOT real businesses, real
ratings, or real prices. No module imports this except the frontend.
"""
DEMO_SUPPLIERS = [
    {
        "name": "Bay Steel Supply", "location": "Fremont, CA", "lat": 37.5485, "lng": -121.9886, "distance_mi": 4.2,
        "unit_price": 6.30, "moq": 25, "lead_days": 2,
        "quality_score": 92,
        "quality_evidence": [
            "ISO 9001 certificate on file (synthetic demo record)",
            "On-time delivery 96% — n=24 synthetic orders",
            "Defect rate 0.8% — n=24 synthetic orders",
        ],
        "contact": "sales@baysteel.example — public listing (synthetic demo)",
        "contact_source": "public (synthetic demo record)",
        "why": "Closest + fast + high quality; best balance of cost and quality.",
    },
    {
        "name": "Golden State Metals", "location": "Hayward, CA", "lat": 37.6688, "lng": -122.0808, "distance_mi": 11.8,
        "unit_price": 6.10, "moq": 50, "lead_days": 3,
        "quality_score": 88,
        "quality_evidence": [
            "On-time delivery 93% — n=31 synthetic orders",
            "Defect rate 1.1% — n=31 synthetic orders",
            "Repeat-buyer note: 6 repeat synthetic orders",
        ],
        "contact": "quotes@goldenstate.example — public listing (synthetic demo)",
        "contact_source": "public (synthetic demo record)",
        "why": "Low unit price with strong quality evidence; MOQ fits the job.",
    },
    {
        "name": "Pacific Fasteners Co", "location": "San Jose, CA", "lat": 37.3387, "lng": -121.8853, "distance_mi": 18.5,
        "unit_price": 5.45, "moq": 100, "lead_days": 5,
        "quality_score": 71,
        "quality_evidence": [
            "On-time delivery 81% — n=16 synthetic orders",
            "Defect rate 3.4% — n=16 synthetic orders",
            "No quality certificate on file (synthetic demo record)",
        ],
        "contact": "not public — request via email",
        "contact_source": "not public",
        "why": "Cheap per unit, but MOQ is 2x the job size and quality evidence is weak.",
    },
    {
        "name": "Sierra Building Supply", "location": "Union City, CA", "lat": 37.5934, "lng": -122.0438, "distance_mi": 8.3,
        "unit_price": 7.20, "moq": 10, "lead_days": 1,
        "quality_score": 95,
        "quality_evidence": [
            "ISO 9001 certificate on file (synthetic demo record)",
            "On-time delivery 98% — n=42 synthetic orders",
            "Defect rate 0.5% — n=42 synthetic orders",
        ],
        "contact": "orders@sierra.example — public listing (synthetic demo)",
        "contact_source": "public (synthetic demo record)",
        "why": "Highest quality evidence and fastest delivery; highest unit price.",
    },
    {
        "name": "East Bay Industrial", "location": "Oakland, CA", "lat": 37.8044, "lng": -122.2712, "distance_mi": 22.0,
        "unit_price": 5.90, "moq": 50, "lead_days": 4,
        "quality_score": 79,
        "quality_evidence": [
            "On-time delivery 87% — n=19 synthetic orders",
            "Defect rate 2.0% — n=19 synthetic orders",
        ],
        "contact": "sales@eastbay.example — supplier-provided (synthetic demo)",
        "contact_source": "supplier-provided (synthetic demo record)",
        "why": "Mid price, mid quality; longer lead time than the top 3.",
    },
    {
        "name": "Delta Materials Direct", "location": "Stockton, CA", "lat": 37.9577, "lng": -121.2908, "distance_mi": 58.4,
        "unit_price": 4.95, "moq": 200, "lead_days": 7,
        "quality_score": 64,
        "quality_evidence": [
            "On-time delivery 74% — n=12 synthetic orders",
            "Defect rate 4.6% — n=12 synthetic orders",
            "No quality certificate on file (synthetic demo record)",
        ],
        "contact": "not public — request via email",
        "contact_source": "not public",
        "why": "Cheapest per unit, but far away, 7-day lead, MOQ 4x the job, weakest quality.",
    },
]

ESTIMATE_LABEL = "estimate, not a surveyed quantity"

DEMO_MATERIALS = [
    {"material": "Steel brackets", "quantity": 50, "unit": "pcs",
     "method": "count x unit rate (plan count)", "confidence": 0.92, "flagged": False,
     "source": "sample plan", "estimate_label": ESTIMATE_LABEL},
    {"material": "Concrete (footings)", "quantity": 2.4, "unit": "m3",
     "method": "area x thickness (12 m2 x 0.2 m)", "confidence": 0.88, "flagged": False,
     "source": "sample plan", "estimate_label": ESTIMATE_LABEL},
    {"material": "Timber joists", "quantity": 18, "unit": "pcs",
     "method": "count x unit rate (plan count)", "confidence": 0.81, "flagged": False,
     "source": "sample plan", "estimate_label": ESTIMATE_LABEL},
    {"material": "Anchor bolts M12", "quantity": 100, "unit": "pcs",
     "method": "count x 2 per bracket", "confidence": 0.95, "flagged": False,
     "source": "sample plan", "estimate_label": ESTIMATE_LABEL},
    {"material": "Plywood sheets", "quantity": 6, "unit": "sheets",
     "method": "area / sheet area (low-res region)", "confidence": 0.58, "flagged": True,
     "source": "sample plan", "estimate_label": ESTIMATE_LABEL},
]

DEMO_QA = [
    {
        "match": ["fixture", "fixtures"],
        "answer": "Sheet A-101 shows 31 fixtures by count. The fixture schedule lists 33 — "
                  "a gap of 2. Best guess: 2 fixtures are on sheet A-102 (not in this upload). "
                  "The gap is surfaced, not averaged away.",
        "region": "Sheet A-101, grid C3–D5 (highlighted region)",
        "clause": "Spec §4.2: 'Fixture count per sheet A-101: 31; per schedule: 33.'",
    },
    {
        "match": ["beam", "load"],
        "answer": "Beam B-7 load rating: 12 kN/m. Shown in the beam schedule on sheet S-201.",
        "region": "Sheet S-201, beam schedule row B-7 (highlighted region)",
        "clause": "Spec §7.1: 'Beam B-7 — design load 12 kN/m.'",
    },
    {
        "match": ["scale"],
        "answer": "The title block reads scale 1:50. Please confirm the scale before any "
                  "measurement is used — see the scale-confirm banner above the takeoff table.",
        "region": "Title block, bottom-right (highlighted region)",
        "clause": "Spec §1.1: 'All drawings at 1:50 unless noted.'",
    },
]

# Synthetic observability history — labelled synthetic, never a live claim.
DEMO_METRICS_DAYS = ["Oct 28", "Oct 29", "Oct 30", "Oct 31", "Nov 1", "Nov 2", "Nov 3",
                     "Nov 4", "Nov 5", "Nov 6", "Nov 7", "Nov 8", "Nov 9", "Nov 10"]
DEMO_GROUNDEDNESS = [92, 93, 91, 94, 94, 95, 95, 96, 95, 96, 96, 97, 96, 96]
DEMO_RETRIEVAL_TOP1 = [86, 87, 88, 87, 89, 89, 90, 90, 91, 90, 91, 92, 91, 92]
DEMO_EVAL_PASS = [100, 100, 100, None, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
# Oct 31 is None, not 0: no eval run happened that day in the demo, so
# the trend chart shows a GAP there. A 0% would claim a run failed
# entirely — and that is what the live chart wrongly showed
# (2026-11-10: Eval pass % dropped to 0% on Oct 31).
DEMO_COST_PER_JOB = [0.61, 0.58, 0.55, 0.52, 0.51, 0.49, 0.48, 0.46, 0.45, 0.44, 0.43, 0.43, 0.42, 0.42]
DEMO_LATENCY_P95 = [9.8, 9.4, 9.1, 8.9, 8.7, 8.4, 8.2, 8.0, 7.9, 7.7, 7.6, 7.4, 7.3, 7.2]

# Full synthetic Accuracy dashboard (DEMO MODE only, labelled as such).
# Values are the same synthetic series as the trend constants above;
# takeoff accuracy has no data yet even in the demo, because no
# corrected takeoff lines exist — it shows "no data yet", honestly.
DEMO_ACCURACY = {
    "metrics": [
        {"key": "groundedness", "name": "Groundedness",
         "formula": "grounded answers ÷ all answers",
         "source": "qa_log (grounded flag)", "target": "≥ 95%",
         "direction": "higher", "unit": "rate", "value": 0.96, "n": 48,
         "status": "ok"},
        {"key": "retrieval_top1", "name": "Retrieval accuracy",
         "formula": "RAG top-1 correct ÷ eval set (top-3 shown alongside)",
         "source": "eval_runs (fixed eval set)", "target": "top-1 ≥ 90%",
         "direction": "higher", "unit": "rate", "value": 0.92, "n": 73,
         "status": "ok"},
        {"key": "thumbs_up_rate", "name": "Answer accuracy",
         "formula": "👍 ÷ (👍 + 👎); “not found” rate counted separately",
         "source": "qa_log (thumbs) + qa_feedback", "target": "≥ 90%",
         "direction": "higher", "unit": "rate", "value": 0.88, "n": 34,
         "status": "ok"},
        {"key": "takeoff_mape", "name": "Takeoff estimate accuracy",
         "formula": "mean absolute % error vs user-corrected quantities",
         "source": "materials (user-corrected lines)", "target": "mean error ≤ 10%",
         "direction": "lower", "unit": "rate", "value": None, "n": 0,
         "status": "no_data"},
        {"key": "ranking_top1_rate", "name": "Supplier ranking accuracy",
         "formula": "chosen supplier was ranked #1 ÷ orders placed",
         "source": "orders + shortlist (best_value_rank)", "target": "≥ 50%",
         "direction": "higher", "unit": "rate", "value": 0.67, "n": 12,
         "status": "ok"},
        {"key": "buyer_agent", "name": "Buyer-agent accuracy",
         "formula": "quotes agreed ÷ quotes sent; approval-before-order = 100% (invariant)",
         "source": "outbox / quotes / approval_requests / orders",
         "target": "approval-before-order 100%",
         "direction": "higher", "unit": "rate", "value": 1.0, "n": 12,
         "status": "ok", "approval_before_order": 1.0,
         "agreement_rate": 0.58},
        {"key": "guardrail_block_rate", "name": "Guardrail block rate",
         "formula": "blocked or redacted ÷ adversarial inputs (eval set); live false-positive rate shown separately",
         "source": "eval_runs + observability_events (guardrail_action)",
         "target": "100% on adversarial set; false positives < 5%",
         "direction": "higher", "unit": "rate", "value": 1.0, "n": 16,
         "status": "ok"},
        {"key": "cost_cache_speed", "name": "Cost / cache / speed",
         "formula": "cache hit rate + $ saved; latency p50/p95 per step; cost per query / per job",
         "source": "observability_events (cache_hit, cost_usd, latency_ms)",
         "target": "cache hit ≥ 50%; p95 ask latency < 10 s",
         "direction": "higher", "unit": "rate", "value": 0.61, "n": 48,
         "status": "ok"},
    ],
    "headline": [
        {"label": "Groundedness (30d)", "value": 0.96, "n": 48, "unit": "rate"},
        {"label": "👍 rate", "value": 0.88, "n": 34, "unit": "rate"},
        {"label": "Takeoff mean error", "value": None, "n": 0, "unit": "rate"},
        {"label": "Cost per completed job", "value": 0.42, "n": 12, "unit": "usd"},
    ],
    "alerts": [],
    "approval_before_order": 1.0,
    "approval_violations": 0,
    "source": "synthetic demo data (labelled)",
}

