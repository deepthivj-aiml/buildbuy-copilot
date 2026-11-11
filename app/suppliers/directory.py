"""Supplier directory — synthetic-only supplier records + quality scoring.

Covers the quality side of the cost+quality ranking (user update 2026-11-10):
quality is scored ONLY from evidenced signals — vetting evidence,
certifications, reply reliability, lead-time reliability, defect / return
history where the supplier provides it, and user feedback. Nothing is
invented: a missing signal scores neutral (0.5) and is listed as
"not provided" in the evidence, never as a good score. All quality figures
in data/suppliers.json are synthetic_demo — they must never be presented as
verified real-world ratings.

Contacts: synthetic only, emails on the .invalid domain so no real email can
ever be sent. A real supplier's contact appears only if public or
supplier-provided — never invented.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# Quality-score weights (sum to 1.0). Feedback and reliability dominate;
# certifications alone cannot carry a supplier.
W_CERTS = 0.10
W_VETTING = 0.15
W_REPLY = 0.20
W_LEAD_RELIABILITY = 0.20
W_DEFECT = 0.15
W_FEEDBACK = 0.20
SOURCE = "synthetic_demo"


def load_suppliers(data_dir: str | Path | None = None) -> list[dict]:
    """Load the 12 synthetic suppliers from data/suppliers.json."""
    path = Path(data_dir) / "suppliers.json" if data_dir else Path(__file__).resolve().parents[2] / "data" / "suppliers.json"
    data = json.loads(Path(path).read_text())
    return data["suppliers"]


def get_supplier(suppliers: list[dict], supplier_id: str) -> dict | None:
    return next((s for s in suppliers if s["id"] == supplier_id), None)


def suppliers_for_material(suppliers: list[dict], material: str) -> list[dict]:
    return [s for s in suppliers if material in s.get("materials", [])]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def _cert_score(supplier: dict) -> tuple[float, str]:
    certs = supplier.get("certifications") or []
    if not certs:
        return 0.3, "no certifications on file"
    return min(1.0, 0.5 + 0.25 * len(certs)), f"{len(certs)} certification(s): " + ", ".join(certs)


def _vetting_score(supplier: dict) -> tuple[float, str]:
    v = supplier.get("vetting") or {}
    score = 0.0
    parts = []
    if v.get("identity_verified"):
        score += 0.5
        parts.append("identity verified")
    else:
        parts.append("identity NOT verified")
    years = v.get("years_in_business") or 0
    score += min(0.3, years / 20.0 * 0.3)
    parts.append(f"{years} years in business")
    if v.get("registry_check"):
        score += 0.2
    return round(min(1.0, score), 3), "; ".join(parts)


def _feedback_score(supplier: dict) -> tuple[float, str]:
    fb = supplier.get("user_feedback")
    if not fb:
        return 0.5, "user feedback not provided — treated as neutral, not as good"
    stars = float(fb["avg_stars"])
    return round(stars / 5.0, 3), f"{stars}/5 from {fb['reviews']} review(s)"


def quality_score(supplier: dict) -> tuple[float, list[dict]]:
    """Quality score 0..1 + an evidence list (one entry per signal).

    Missing signals score neutral (0.5) and say so. The evidence list is the
    audit trail: every point of the score can be traced to a named signal.
    """
    evidence: list[dict] = []

    cert_s, cert_note = _cert_score(supplier)
    evidence.append({"signal": "certifications", "value": cert_note, "score": cert_s, "source": SOURCE})

    vet_s, vet_note = _vetting_score(supplier)
    evidence.append({"signal": "vetting", "value": vet_note, "score": vet_s, "source": SOURCE})
    for item in (supplier.get("vetting") or {}).get("evidence") or []:
        evidence.append({"signal": "vetting_evidence", "value": item, "score": None, "source": SOURCE})

    reply = supplier.get("reply_reliability")
    reply_s = float(reply) if reply is not None else 0.5
    evidence.append({
        "signal": "reply_reliability",
        "value": f"{reply_s:.2f}" if reply is not None else "not provided — neutral",
        "score": reply_s, "source": SOURCE,
    })

    lead_rel = supplier.get("lead_time_reliability")
    lead_s = float(lead_rel) if lead_rel is not None else 0.5
    evidence.append({
        "signal": "lead_time_reliability",
        "value": f"{lead_s:.2f}" if lead_rel is not None else "not provided — neutral",
        "score": lead_s, "source": SOURCE,
    })

    defect = supplier.get("defect_rate_pct")
    if defect is None:
        defect_s, defect_note = 0.5, "defect / return history not provided — neutral"
    else:
        defect_s = round(max(0.0, 1.0 - float(defect) / 5.0), 3)
        defect_note = f"defect rate {defect}%"
    evidence.append({"signal": "defect_history", "value": defect_note, "score": defect_s, "source": SOURCE})

    fb_s, fb_note = _feedback_score(supplier)
    evidence.append({"signal": "user_feedback", "value": fb_note, "score": fb_s, "source": SOURCE})

    for flag in supplier.get("risk_flags") or []:
        evidence.append({"signal": "risk_flag", "value": flag, "score": None, "source": SOURCE})

    score = round(
        W_CERTS * cert_s
        + W_VETTING * vet_s
        + W_REPLY * reply_s
        + W_LEAD_RELIABILITY * lead_s
        + W_DEFECT * defect_s
        + W_FEEDBACK * fb_s,
        3,
    )
    return score, evidence
