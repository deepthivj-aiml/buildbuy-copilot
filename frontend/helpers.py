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


def parse_requirement(text, llm_parser=None):
    """Parse a typed requirement (no LLM, no key, by default).

    Returns {"raw", "item", "quantity", "unit", "location", "deadline",
    "budget"}. ``item`` is ONLY the item name ("concrete", "steel
    brackets") — never the full input text (bug fixed 2026-11-10:
    the old version returned the raw text as the item). ``unit`` is
    captured too ("10 m3" -> quantity 10, unit "m3") — the old version
    dropped the unit entirely. ``location`` is a place name the user
    typed after in/near/at, or a trailing place name that is a KNOWN
    place — an unknown trailing word is never guessed as a location.

    ``llm_parser`` is an OPTIONAL plug-in, not a requirement: a
    callable(text) -> dict with the same keys, e.g. a free local model
    (Ollama) supplied by the caller. When given, its item/quantity/
    unit/location/deadline/budget are used where present and the
    deterministic parse fills the rest; any error or empty result
    falls back to the deterministic parse. No LLM is configured by
    default and no key is needed — the deterministic parse handles
    the stated inputs, and an LLM would NOT have fixed the takeoff
    bug (that was missing wiring, not parsing).
    """
    deterministic = _parse_requirement_deterministic(text)
    if llm_parser is None:
        return deterministic
    try:
        llm_result = llm_parser(text)
    except Exception:  # noqa: BLE001 — an LLM must never break parsing
        return deterministic
    if not isinstance(llm_result, dict) or not llm_result.get("item"):
        return deterministic
    merged = dict(deterministic)
    for key in ("item", "quantity", "unit", "location", "deadline", "budget"):
        if llm_result.get(key) not in (None, ""):
            merged[key] = llm_result[key]
    if isinstance(merged.get("item"), str):
        merged["item"] = merged["item"].strip().strip(",").strip()
    return merged


# Units, longest-first so "m3" wins over "m" and "units" over "unit".
_UNIT_RE = (r"(m³|m3|cubic metres|cubic meters|m²|m2|square metres|square meters"
            r"|units?|pcs|pieces?|sheets?|bags?|rolls?|litres?|liters?"
            r"|tonnes?|tons?|kg|metres|meters|feet|ft|m|l)\b")
_UNIT_ALIASES = {
    "m³": "m3", "m3": "m3", "cubic metres": "m3", "cubic meters": "m3",
    "m²": "m2", "m2": "m2", "square metres": "m2", "square meters": "m2",
    "unit": "pcs", "units": "pcs", "pcs": "pcs", "piece": "pcs", "pieces": "pcs",
    "sheet": "sheets", "sheets": "sheets", "bag": "bags", "bags": "bags",
    "roll": "rolls", "rolls": "rolls", "litre": "L", "litres": "L",
    "liter": "L", "liters": "L", "l": "L",
    "tonne": "t", "tonnes": "t", "ton": "t", "tons": "t",
    "kg": "kg", "metre": "m", "metres": "m", "meter": "m", "meters": "m",
    "m": "m", "foot": "ft", "feet": "ft", "ft": "ft",
}
_QTY_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*" + _UNIT_RE, re.I)
_QTY_BARE_RE = re.compile(r"(\d+(?:\.\d+)?)")
_LEADING_QTY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*x\s+", re.I)
_BUDGET_RE = re.compile(r"(?:under|below|max|budget)\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)
_DEADLINE_RE = re.compile(
    r"\bby\s+(Friday|Monday|Tuesday|Wednesday|Thursday|Saturday|Sunday"
    r"|\w+\s+\d+)", re.I)
_LOCATION_PREP_RE = re.compile(r"\b(?:in|near|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")


def _parse_requirement_deterministic(text):
    req = {"raw": text, "item": "", "quantity": None, "unit": "",
           "location": "", "deadline": "", "budget": None}
    work = (text or "").strip()
    if not work:
        return req
    m = _BUDGET_RE.search(work)
    if m:
        req["budget"] = float(m.group(1).replace(",", ""))
        work = work[:m.start()] + work[m.end():]
    m = _DEADLINE_RE.search(work)
    if m:
        req["deadline"] = m.group(1)
        work = work[:m.start()] + work[m.end():]
    # Leading "10 x concrete" form: the number before "x" is the quantity.
    m = _LEADING_QTY_RE.match(work)
    if m:
        req["quantity"] = float(m.group(1))
        if req["quantity"] == int(req["quantity"]):
            req["quantity"] = int(req["quantity"])
        work = work[m.end():]
    m = _QTY_UNIT_RE.search(work)
    if m:
        if req["quantity"] is None:
            qty = float(m.group(1))
            req["quantity"] = int(qty) if qty == int(qty) else qty
        req["unit"] = _UNIT_ALIASES.get(m.group(2).lower(), m.group(2).lower())
        work = work[:m.start()] + work[m.end():]
    elif req["quantity"] is None:
        # A bare number with no unit: quantity known, unit unknown
        # (never guessed — the takeoff flags the line for review).
        m = _QTY_BARE_RE.search(work)
        if m:
            qty = float(m.group(1))
            req["quantity"] = int(qty) if qty == int(qty) else qty
            work = work[:m.start()] + work[m.end():]
    m = _LOCATION_PREP_RE.search(work)
    if m:
        req["location"] = m.group(1)
        work = work[:m.start()] + work[m.end():]
    else:
        # Trailing ", Fremont": a KNOWN place only — an unknown trailing
        # word is left alone, never guessed as a location. Empty
        # segments (left by removing budget / deadline chunks) are
        # ignored when looking for the trailing place.
        parts = [p.strip() for p in work.split(",")]
        parts = [p for p in parts if p]
        if len(parts) > 1:
            tail = parts[-1].lower().removesuffix(", ca").removesuffix(
                ", california").strip()
            if tail in KNOWN_PLACES:
                req["location"] = tail.title()
                parts = parts[:-1]
                work = ", ".join(parts)
    item = ", ".join(p.strip() for p in work.split(",") if p.strip())
    item = re.sub(r"\s+", " ", item).strip(" ,")
    item = re.sub(r"\b(for|of|the)\s*$", "", item, flags=re.I).strip(" ,")
    req["item"] = item
    return req


ESTIMATE_LABEL = "estimate, not a surveyed quantity"

# ------------------------------------------------------------- supplier contact
# + quote-email preview (Buyer Agent tab, 2026-11-10 fix).
#
# What the UI must show BEFORE anything is sent, per supplier:
#   * their contact details (never invented — "not held" when missing),
#   * HOW they will be contacted (channel, from, to, subject),
#   * the FULL email body, editable, with the contact-sharing toggle
#     reflected in the text (OFF = "a customer", ON = name/email/phone).
# The body below mirrors app/email/service.py EmailService.draft_quote
# line-for-line (tested in test_frontend.py), so the preview is the
# email that would actually be sent — not a second, drifting draft.
BUYER_CONTACT = {
    "name": "Deepthi Jainlal",
    "email": "deepthiag26@gmail.com",
    "phone": "+1 341-252-9234",
}
EMAIL_FROM = "BuildBuy Copilot <noreply@buildbuy.local>"  # config default (EMAIL_FROM)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?1?[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{4}")


def supplier_email(supplier):
    """The supplier's email address, or None when it is not held.

    Extracted from the supplier's ``email`` / ``contact`` field. A
    value like "not public — request via email" contains no address
    and returns None — it is never treated as an address, and the UI
    must show "not held" and block sending instead of inventing one.
    """
    for key in ("email", "contact"):
        value = (supplier or {}).get(key) or ""
        m = _EMAIL_RE.search(str(value))
        if m:
            return m.group(0)
    return None


def supplier_contact_details(supplier):
    """Contact details for one supplier — every field is either held
    or explicitly None ("not held" in the UI). Nothing is invented:
    demo suppliers carry no phone or street address, so those are
    None; ``location`` is a city-level area, never an address."""
    supplier = supplier or {}
    return {
        "name": supplier.get("name", "Unknown supplier"),
        "email": supplier_email(supplier),
        "phone": supplier.get("phone") or None,
        "address": supplier.get("address") or None,
        "area": supplier.get("location") or None,
        "contact_source": supplier.get("contact_source") or "not stated",
    }


def strip_contact_details(body, buyer=None):
    """Remove the buyer's name / email / phone (and any other email /
    phone) from an email body — mirror of
    app/email/service.py EmailService.strip_customer_identity.

    Applied at send time whenever contact sharing is OFF for that
    supplier, even if the user typed contact details into the edited
    draft themselves.
    """
    buyer = buyer or BUYER_CONTACT
    out = str(body or "")
    for value in (buyer.get("email", ""), buyer.get("phone", ""),
                  buyer.get("name", "")):
        if value and value.strip():
            out = out.replace(value, "[contact not shared]")
    out = _EMAIL_RE.sub("[contact not shared]", out)
    out = _PHONE_RE.sub("[contact not shared]", out)
    return out


def build_quote_email(req, supplier, *, share_contact=False, buyer=None,
                      max_price=None):
    """The full quote-request email for ONE supplier, as it would be sent.

    Returns {"channel", "from", "to", "to_name", "subject", "body",
    "sendable", "blocked_reason"}. Channel is always "email" in v1.
    ``sendable`` is False (with a reason) when the supplier's email
    is not held — the UI blocks sending instead of guessing an address.
    """
    buyer = buyer or BUYER_CONTACT
    req = req or {}
    details = supplier_contact_details(supplier)
    qty = req.get("quantity") or 0
    item = req.get("item") or "item"
    who = buyer.get("name", "").strip() if share_contact else "a customer"
    lines = [
        "Hello,",
        "",
        f"I am BuildBuy Copilot, acting as the buying agent for {who}.",
        "",
        "I am enquiring on their behalf about the following part, "
        "and would like a quote:",
        f"- {qty} x {item}",
    ]
    if req.get("location"):
        lines.append(f"\nDelivery location: {req['location']}")
    if req.get("deadline"):
        lines.append(f"Needed by: {req['deadline']}")
    if max_price is not None:
        lines.append(f"Budget (max): ${max_price}")
    lines.append("\nCould you please send your best price, lead time, and delivery cost?")
    if share_contact:
        contact_parts = [p for p in [buyer.get("name", ""), buyer.get("email", ""),
                                     buyer.get("phone", "")] if p]
        if contact_parts:
            lines.append("\nYou can reach the customer directly at: "
                         + ", ".join(contact_parts))
    lines.append(f"\nThank you,\nBuildBuy Copilot (buying agent for {who})")
    email = details["email"]
    return {
        "channel": "email",
        "from": EMAIL_FROM,
        "to": email,
        "to_name": details["name"],
        "subject": f"Quote request — {qty} x {item}",
        "body": "\n".join(lines),
        "sendable": email is not None,
        "blocked_reason": (None if email is not None else
                           "Email not held for this supplier — add their email "
                           "before sending; no address is ever guessed."),
    }


def _material_tokens(name):
    """Normalised tokens of a material name: lowercased, parenthetical
    removed ("Concrete (footings)" -> "concrete"), plurals singularised."""
    core = re.sub(r"\(.*?\)", "", str(name or "")).lower()
    core = re.sub(r"[^a-z0-9 ]", " ", core)
    tokens = set()
    for tok in core.split():
        tokens.add(tok[:-1] if tok.endswith("s") and len(tok) > 2 else tok)
    return tokens


def _materials_match(req_item, line_material):
    """True when a typed item names the same material as a takeoff line.

    Exact after normalisation, or the typed item's tokens are a
    multi-token subset of the line's core tokens ("steel brackets"
    matches "Steel brackets"; "concrete" matches "Concrete
    (footings)"). A single token that is only part of a multi-word
    line ("steel" vs "Steel brackets") does NOT match — it is a
    different material and gets its own line instead.
    """
    req_tokens = _material_tokens(req_item)
    line_tokens = _material_tokens(line_material)
    if not req_tokens or not line_tokens:
        return False
    if req_tokens == line_tokens:
        return True
    return len(req_tokens) >= 2 and req_tokens <= line_tokens


def apply_requirement_to_takeoff(materials, req):
    """Apply a parsed typed requirement to a takeoff table.

    Returns (new_materials, note). ``materials`` is the frontend list
    of dicts (material / quantity / unit / method / confidence /
    flagged). This is the wiring the live bug was missing: before
    2026-11-10 the frontend never called anything like this, so a
    typed quantity never reached the table.

    - No quantity in the requirement -> table unchanged, note says so;
      a quantity is NEVER invented.
    - The item matches an existing line -> that line's quantity (and
      unit, when the user stated one) is updated; the method records
      the override AND the old plan value, so the plan estimate is
      never silently overwritten. The original plan value is stored
      in ``plan_quantity`` / ``plan_unit`` on the FIRST override, so
      re-applying the same requirement keeps saying 2.4 m3, not the
      typed 10 m3 (live bug 2026-11-10 21:32).
    - No match -> a new line is appended for the typed item.
    - Every line keeps the "estimate, not a surveyed quantity" label;
      a line whose unit was not stated is flagged for review.
    """
    lines = [dict(m) for m in (materials or [])]
    item = (req or {}).get("item") or ""
    quantity = (req or {}).get("quantity")
    if quantity is None or not item.strip():
        return lines, ("No quantity in the typed requirement — the takeoff "
                       "is unchanged (no quantity invented).")
    unit = (req or {}).get("unit") or ""
    display_item = item.strip()
    display_item = display_item[:1].upper() + display_item[1:]
    for line in lines:
        if _materials_match(item, line.get("material", "")):
            # The ORIGINAL plan estimate is captured once, on the first
            # override, and kept in plan_quantity / plan_unit. Re-applying
            # the same requirement (Parse, then "Find what I need ->",
            # then a re-render) must NOT overwrite it with the typed
            # value — the live bug was that the second apply said the
            # plan estimate was 10 m3 when the plan said 2.4 m3.
            plan_qty = line.get("plan_quantity", line.get("quantity"))
            plan_unit = line.get("plan_unit", line.get("unit", ""))
            old_qty, old_unit = line.get("quantity"), line.get("unit", "")
            line["quantity"] = quantity
            if unit:
                line["unit"] = unit
            line["confidence"] = 0.90
            line["flagged"] = False
            line["source"] = "typed requirement"
            line["plan_quantity"] = plan_qty
            line["plan_unit"] = plan_unit
            line["estimate_label"] = ESTIMATE_LABEL
            line["method"] = (
                f"user-typed quantity ({quantity} {line['unit']}) — overrides "
                f"plan estimate of {plan_qty} {plan_unit}; plan value kept here, "
                f"not silently replaced")
            if not unit:
                line["method"] += " (unit not stated — kept plan unit; confirm)"
                line["flagged"] = True
            return lines, (f"Takeoff updated from your typed requirement: "
                           f"{line['material']} → {quantity} {line['unit']} "
                           f"(was plan estimate {plan_qty} {plan_unit}).")
    new_unit = unit or "units"
    lines.append({
        "material": display_item,
        "quantity": quantity,
        "unit": new_unit,
        "method": (f"user-typed quantity ({quantity} {new_unit})"
                   + ("" if unit else " — unit not stated, assumed units; confirm")),
        "confidence": 0.90,
        "flagged": not bool(unit),
        "source": "typed requirement",
        "estimate_label": ESTIMATE_LABEL,
    })
    return lines, (f"Takeoff updated from your typed requirement: "
                   f"{display_item} → {quantity} {new_unit} (new line).")


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
