"""Pure frontend helpers — no Streamlit import (frontend/helpers.py).

Ranking, transport / total landed cost, twin what-if, requirement
parsing and demo Q&A. Same formulas as the backend (see
app/suppliers/search.py, app/ranking.py, app/twin/simulator.py).
Tested alone: .venv/bin/python -m pytest tests/test_frontend.py -v
"""
import math
import os
import re
import urllib.error
import urllib.request
from datetime import date, timedelta

from demo_data import DEMO_QA

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")

def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km (demo helper, same formula as backend)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


# Delivery location — MANUAL input only, never auto-detected. The user
# types a city / ZIP / address into an optional field (blank by default).
# No browser geolocation, no IP lookup, no auto-use of the requirement
# location. Offline lookup over demo-area cities + "lat,lng"; anything
# unrecognised returns None and transport is excluded, never guessed.
KNOWN_PLACES = {
    "fremont": (37.5485, -121.9886),
    "hayward": (37.6688, -122.0808),
    "san jose": (37.3387, -121.8853),
    "oakland": (37.8044, -122.2712),
    "redwood city": (37.4852, -122.2364),
    "union city": (37.5934, -122.0438),
    "alameda": (37.7652, -122.2416),
    "santa clara": (37.3541, -121.9552),
    "novato": (38.0874, -122.5699),
    "modesto": (37.6391, -120.9969),
    "stockton": (37.9577, -121.2908),
    "san francisco": (37.7749, -122.4194),
    "milpitas": (37.4323, -121.8996),
    "newark": (37.5297, -122.0402),
    "livermore": (37.6819, -121.7680),
    "pleasanton": (37.6624, -121.8747),
    "sacramento": (38.5816, -121.4944),
}
_LATLNG_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def geocode_location(text):
    """Resolve a user-typed location to (lat, lng, name) or None."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    m = _LATLNG_RE.match(raw)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            return lat, lng, f"{lat},{lng}"
        return None
    key = raw.lower().rstrip(",").strip()
    key = key.removesuffix(", ca").removesuffix(", california").strip()
    if key in KNOWN_PLACES:
        lat, lng = KNOWN_PLACES[key]
        return lat, lng, key.title()
    return None


def backend_is_reachable():
    """True if the FastAPI backend answers /health. Never raises."""
    try:
        req = urllib.request.Request(API_URL + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def transport_for(supplier, delivery_location, transport_rate=None):
    """Transport line for one supplier, from a user-typed delivery location.

    Returns (transport $, distance_km, label). Blank / unrecognised
    location -> (None, None, "excl. transport"): transport is excluded
    from total landed cost, never guessed. With a location, transport =
    distance x rate (buyer's own $/km rate when given, else the demo
    shipping estimate $25 + $0.55/km — same formula as the backend).
    """
    resolved = geocode_location(delivery_location)
    if resolved is None:
        return None, None, "excl. transport"
    lat, lng, _name = resolved
    dist = haversine_km(lat, lng, supplier["lat"], supplier["lng"])
    if transport_rate is not None:
        transport = round(dist * transport_rate, 2)
    else:
        transport = round(25.0 + 0.55 * dist, 2)
    return transport, dist, "incl. transport"


def landed_cost(supplier, qty, transport=None):
    """Total landed cost = unit price x qty + transport (when included).

    ``transport`` is None when no delivery location was typed: the
    landed cost then EXCLUDES transport and is labelled "excl. transport".
    """
    return round(supplier["unit_price"] * qty + (transport or 0.0), 2)


def landed_breakdown(supplier, qty, transport=None):
    """Per-line breakdown: goods + transport + fees, with the label."""
    goods = round(supplier["unit_price"] * qty, 2)
    fees = round(goods * 0.02 + 15.0, 2)
    return {
        "goods": goods,
        "transport": transport,
        "taxes_fees": fees,
        "total": round(goods + (transport or 0.0) + fees, 2),
        "transport_included": transport is not None,
        "label": "incl. transport" if transport is not None else "excl. transport",
    }


def rank_suppliers(suppliers, qty, delivery_location="", transport_rate=None):
    """Cost + quality ranking (best value), same formula as the backend
    supplier search (app/suppliers/search.py):

        best value = 0.45 * cost_score + 0.35 * quality_score
                     + 0.20 * lead_score
        (each component normalised 0-100 across the shortlist)

    Total landed cost = goods + transport + taxes/fees, shown per
    supplier as a breakdown. Transport comes ONLY from a delivery
    location the user types themselves (blank by default — never
    auto-detected, never taken from the requirement location). Blank
    means landed cost is "excl. transport" and ranking works without it.

    Cost alone never wins: the cheapest option and the highest-quality
    option are identified separately so the user can choose.
    Suppliers whose MOQ is above the job quantity are EXCLUDED from the
    ranked shortlist (same as the backend) and returned separately with
    the reason — never silently dropped, never ranked on a quantity they
    will not sell.
    Quality scores come only from the evidence attached to each supplier;
    a supplier with no quality evidence gets no quality score and is
    scored on cost + lead only, flagged "quality unknown" — a rating is
    never invented. Returns (ranked_rows, excluded_rows).
    """
    eligible, excluded = [], []
    for s in suppliers:
        if s["moq"] > qty:
            excluded.append({**s,
                             "reason": f"quantity {qty} below MOQ {s['moq']}"})
        else:
            transport, dist_km, _label = transport_for(
                s, delivery_location, transport_rate)
            bd = landed_breakdown(s, qty, transport)
            eligible.append({**s, "landed": bd["total"],
                             "transport": transport,
                             "transport_included": bd["transport_included"],
                             "landed_label": bd["label"],
                             "landed_breakdown": bd,
                             "distance_km": dist_km})
    rows = eligible
    if rows:
        landed = [r["landed"] for r in rows]
        lo, hi = min(landed), max(landed)
        leads = [r["lead_days"] for r in rows]
        lead_lo, lead_hi = min(leads), max(leads)
        for r in rows:
            r["cost_score"] = 100.0 if hi == lo else round((hi - r["landed"]) / (hi - lo) * 100, 1)
            r["lead_score"] = 100.0 if lead_hi == lead_lo else round(
                (lead_hi - r["lead_days"]) / (lead_hi - lead_lo) * 100, 1)
            q = r.get("quality_score")
            r["quality_unknown"] = q is None
            r["value_score"] = (round(0.45 * r["cost_score"] + 0.20 * r["lead_score"], 1)
                                if q is None else round(
                                    0.45 * r["cost_score"] + 0.35 * q
                                    + 0.20 * r["lead_score"], 1))
        ranked = sorted(rows, key=lambda r: r["value_score"], reverse=True)
        for i, r in enumerate(ranked, start=1):
            r["value_rank"] = i
        cheapest = min(rows, key=lambda r: r["landed"])
        best_quality = max((r for r in rows if r.get("quality_score") is not None),
                           key=lambda r: r["quality_score"], default=None)
        for r in rows:
            r["is_cheapest"] = r is cheapest
            r["is_best_quality"] = best_quality is not None and r is best_quality
            r["is_best_value"] = r.get("value_rank") == 1
    return rows, excluded


def landed_line(r, qty):
    """One-line landed-cost breakdown for the cards: goods + transport + fees."""
    bd = r.get("landed_breakdown") or {}
    goods = bd.get("goods", round(r["unit_price"] * qty, 2))
    fees = bd.get("taxes_fees", 0.0)
    transport = r.get("transport")
    if transport is None:
        return (f"${r['unit_price']:.2f}/unit x {qty} = ${goods:.2f} goods + "
                f"${fees:.2f} fees — excl. transport")
    return (f"${r['unit_price']:.2f}/unit x {qty} = ${goods:.2f} goods + "
            f"${transport:.2f} transport + ${fees:.2f} fees — incl. transport")


def twin_risk(supplier, qty, price_pct, slip_days, qty_pct):
    """Twin what-if: cost AND quality risk, same formula as the backend
    (app/ranking.py simulate_cost_and_quality).

    What-if landed cost = (base landed − transport) x (1 + qty%)
    x (1 + price%) + transport: freight does not rise with the unit
    price, so the transport line is added back unscaled. When no
    delivery location was typed, transport is None and the landed cost
    is "excl. transport". The base landed cost is the shortlist row's
    ``landed`` (goods + transport + fees) when present, so the twin
    and the shortlist never disagree on the starting total.
    Quality risk: no evidence = 60; score >= 80 = 10; 60-79 = 30;
    < 60 = 55 (plus 10 per risk flag). Cost risk = min(50,
    |price%| x 2 + |qty%| x 0.5). Lead risk = min(30, slip x 5 +
    max(0, lead - 14)). Overall risk = 0.5 x quality risk +
    0.3 x cost risk + 0.2 x lead risk.
    A cheap but late or low-quality supplier therefore scores a higher
    total risk than a pricier, on-time, high-quality one — the cost +
    quality rule, computed not asserted. All inputs and the formula are
    shown in the UI; nothing is a black box.
    """
    transport = supplier.get("transport")
    base_landed = supplier.get("landed")
    if base_landed is None:
        base_landed = landed_cost(supplier, qty, transport)
    goods_fees = base_landed - (transport or 0.0)
    new_qty = max(1, round(qty * (1 + qty_pct / 100)))
    new_landed = round(
        goods_fees * (1 + qty_pct / 100) * (1 + price_pct / 100)
        + (transport or 0.0), 2)
    new_lead = supplier["lead_days"] + slip_days
    delivery_date = date.today() + timedelta(days=new_lead)
    quality = supplier.get("quality_score")
    if quality is None:
        quality_risk, quality_reason = 60.0, (
            "No quality evidence on file — quality is unverified for this supplier.")
    elif quality >= 80:
        quality_risk, quality_reason = 10.0, "Strong evidenced quality (score >= 80)."
    elif quality >= 60:
        quality_risk, quality_reason = 30.0, "Moderate evidenced quality (score 60-79)."
    else:
        quality_risk, quality_reason = 55.0, "Low evidenced quality (score < 60)."
    cost_risk = min(50.0, abs(price_pct) * 2.0 + abs(qty_pct) * 0.5)
    lead_risk = min(30.0, slip_days * 5.0 + max(0, supplier["lead_days"] - 14) * 1.0)
    risk = round(min(100.0, 0.5 * quality_risk + 0.3 * cost_risk + 0.2 * lead_risk), 1)
    level = "Low" if risk < 30 else ("Medium" if risk < 60 else "High")
    return {
        "qty": new_qty, "unit": supplier["unit_price"], "landed": new_landed,
        "base_landed": base_landed,
        "lead_days": new_lead, "delivery_date": delivery_date,
        "quality": quality, "quality_risk": quality_risk,
        "quality_reason": quality_reason,
        "risk": risk, "risk_level": level,
    }


def parse_requirement(text):
    """Tiny local parser (no LLM, no key): quantity, budget, location, deadline."""
    req = {"raw": text, "item": text.strip(), "quantity": None,
           "location": "", "deadline": "", "budget": None}
    m = re.search(r"(\d+)\s*(units|pcs|pieces)?", text, re.I)
    if m:
        req["quantity"] = int(m.group(1))
    m = re.search(r"(?:under|below|max|budget)\s*\$?\s*([\d,]+)", text, re.I)
    if m:
        req["budget"] = float(m.group(1).replace(",", ""))
    m = re.search(r"\b(?:in|near|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
    if m:
        req["location"] = m.group(1)
    m = re.search(r"\bby\s+(Friday|Monday|Tuesday|Wednesday|Thursday|Saturday|Sunday|\w+\s+\d+)",
                  text, re.I)
    if m:
        req["deadline"] = m.group(1)
    # Item = text with numbers/budget/location stripped is overkill; keep raw as item.
    return req


def demo_answer(question):
    """Local demo Q&A: cited answer if the question matches the demo plan,
    otherwise an honest 'not found' — never a guess."""
    q = question.lower()
    for entry in DEMO_QA:
        if any(k in q for k in entry["match"]):
            return entry["answer"], entry["region"], entry["clause"], True
    return ("Not found — I can't read that from the uploaded plan or specs. "
            "The sheet/page is A-101 (synthetic demo plan). Try rephrasing, "
            "or upload a clearer scan.", "—", "—", False)
