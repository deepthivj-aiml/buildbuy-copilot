"""Cost-AND-quality ranking + twin simulation helpers.

RECONCILED 2026-11-11 — single source of truth: ``app.suppliers.search``.
The best-value formula lives in ``app/suppliers/search.py`` as
``best_value_score`` with weights ``W_COST=0.45, W_QUALITY=0.35,
W_LEAD=0.20``. This module IMPORTS that function and those weights — it
does not keep a second formula. (The old 0.50/0.50, no-lead blend and the
``VALUE_WEIGHT_*`` env defaults were updated to match; see ``.env.example``
and ``app/config.py``.)

Rules (non-negotiable):
- Quality is used ONLY where evidenced. A supplier with no quality
  evidence gets ``quality_score=None`` and ``quality_unknown=True``.
  No rating is ever invented, averaged in from nothing, or defaulted
  to a "typical" value.
- Best-value score = 0.45 * cost_score + 0.35 * quality_score
  + 0.20 * lead_score, each component normalised 0-1 across the
  shortlist. When NO supplier in the shortlist has evidenced quality,
  best-value falls back to the cost rank and the result is flagged
  (``no_quality_evidence=True``).
- When no entry carries ``lead_time_days``, the lead term is neutral
  (0.5 for every entry) so it cannot change the order — the blend is
  still the canonical one, with a documented neutral lead.
- The twin simulates BOTH cost risk and quality risk: a supplier with
  no quality evidence, or with risk flags, carries a higher quality
  risk and a higher overall risk score.
- Total landed cost = goods + transport + taxes/fees. Transport is
  optional and manual (buyer-typed delivery location, blank by
  default — never auto-detected). ``simulate_cost_and_quality`` takes
  an optional ``transport_cost``: it is NOT scaled by the price
  what-if (freight does not rise with the unit price), it is added
  back after the goods/fees portion is scaled.
"""

from __future__ import annotations

from decimal import Decimal

from app.suppliers.search import best_value_score


def _to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def normalise_cost_score(landed_costs: list[float | None]) -> dict[int, float]:
    """Higher score = cheaper. Costs of None score 0 (unknown cost).

    Ratio-based (``100 * cheapest / cost``), NOT min-max: a $10 gap on a
    $200 order must not score as 0 vs 100 the way min-max would.
    Equal costs all score 100.
    """
    known = [c for c in landed_costs if c is not None and c > 0]
    if not known:
        return {i: 0.0 for i in range(len(landed_costs))}
    cheapest = min(known)
    out: dict[int, float] = {}
    for i, c in enumerate(landed_costs):
        if c is None or c <= 0:
            out[i] = 0.0
        else:
            out[i] = round(100.0 * cheapest / c, 2)
    return out


def _normalise_lead_score(lead_days: list[float | None]) -> dict[int, float]:
    """Lead-time score 0..1 (1 = shortest lead). Missing lead -> 0.5 neutral.

    Min-max across the entries that HAVE a lead time; when none do, every
    entry gets the neutral 0.5 so the lead term cannot change the order.
    """
    known = [v for v in lead_days if v is not None]
    if not known:
        return {i: 0.5 for i in range(len(lead_days))}
    lo, hi = min(known), max(known)
    out: dict[int, float] = {}
    for i, v in enumerate(lead_days):
        if v is None:
            out[i] = 0.5
        elif hi == lo:
            out[i] = 1.0
        else:
            out[i] = round((hi - v) / (hi - lo), 3)
    return out


def rank_shortlist(entries: list[dict]) -> list[dict]:
    """Rank a shortlist by best value (cost AND quality AND lead).

    Canonical blend (imported from ``app.suppliers.search``):
    ``best_value = 0.45 * cost_score + 0.35 * quality_score
    + 0.20 * lead_score`` (each 0..1).

    ``entries``: list of dicts with keys ``landed_cost`` (float|None),
    ``quality_score`` (float|None, 0-100, evidenced only),
    ``lead_time_days`` (int|None) and any other fields to pass through.
    Returns the same entries, enriched with: ``cost_score``,
    ``lead_score``, ``best_value_score``, ``best_value_rank``,
    ``is_cheapest``, ``is_highest_quality``, ``quality_unknown``,
    ``no_quality_evidence`` (same bool on every entry).
    """
    costs = [_to_float(e.get("landed_cost")) for e in entries]
    cost_scores = normalise_cost_score(costs)
    lead_scores = _normalise_lead_score(
        [_to_float(e.get("lead_time_days")) for e in entries]
    )
    any_quality = any(e.get("quality_score") is not None for e in entries)

    cheapest_idx = min(
        (i for i, c in enumerate(costs) if c is not None),
        key=lambda i: costs[i],  # type: ignore[index]
        default=None,
    )
    best_quality_idx = max(
        (i for i, e in enumerate(entries) if e.get("quality_score") is not None),
        key=lambda i: float(entries[i]["quality_score"]),  # type: ignore[arg-type]
        default=None,
    )

    scored: list[tuple[int, float]] = []
    for i, entry in enumerate(entries):
        quality = _to_float(entry.get("quality_score"))
        entry["quality_unknown"] = quality is None
        entry["cost_score"] = round(cost_scores[i], 2)
        entry["lead_score"] = round(lead_scores[i], 3)
        if quality is not None:
            # Canonical blend; components are 0..1 here, score kept 0..100
            # for display (x100) so existing callers/tests see the same scale.
            entry["best_value_score"] = round(
                100.0 * best_value_score(
                    cost_scores[i] / 100.0, quality / 100.0, lead_scores[i]
                ),
                2,
            )
        elif any_quality:
            # Quality unknown for this supplier but known for others:
            # score on cost + lead only, quality component 0 — honest,
            # and visible via quality_unknown.
            entry["best_value_score"] = round(
                100.0
                * best_value_score(cost_scores[i] / 100.0, 0.0, lead_scores[i]),
                2,
            )
        else:
            # No quality evidence anywhere: best value == cost + lead, flagged.
            entry["best_value_score"] = round(
                100.0
                * best_value_score(cost_scores[i] / 100.0, 0.0, lead_scores[i]),
                2,
            )
        entry["no_quality_evidence"] = not any_quality
        entry["is_cheapest"] = i == cheapest_idx
        entry["is_highest_quality"] = i == best_quality_idx
        scored.append((i, entry["best_value_score"]))

    ranked = sorted(scored, key=lambda t: (-t[1], costs[t[0]] if costs[t[0]] is not None else float("inf")))
    for rank, (i, _) in enumerate(ranked, start=1):
        entries[i]["best_value_rank"] = rank
        entries[i]["rank"] = rank  # keep legacy `rank` aligned with best value
    return entries


def simulate_cost_and_quality(
    *,
    landed_cost: float | None,
    quality_score: float | None,
    quality_evidence: list,
    risk_flags: list,
    lead_time_days: int | None,
    price_change_pct: float = 0.0,
    delivery_slip_days: int = 0,
    quantity_change_pct: float = 0.0,
    transport_cost: float | None = None,
    transport_included: bool | None = None,
) -> dict:
    """Twin simulation for one supplier: cost AND quality risk.

    Pure deterministic Python (no LLM call, $0, unit-testable).
    Returns landed cost under the what-if, delivery shift, risk scores
    and a plain-language reason for the quality risk.

    ``transport_cost`` (optional): the transport line inside
    ``landed_cost``. It is NOT scaled by the price what-if — freight
    does not rise with the unit price — it is added back after the
    goods/fees portion is scaled. ``None`` (or 0) means no transport
    line: landed cost is "excl. transport".
    """
    base_cost = landed_cost if landed_cost is not None else 0.0
    transport = float(transport_cost or 0.0)
    goods_fees = max(0.0, base_cost - transport)
    qty_factor = 1.0 + quantity_change_pct / 100.0
    what_if_cost = round(
        goods_fees * qty_factor * (1.0 + price_change_pct / 100.0) + transport, 2
    )

    # --- quality risk (0-100, higher = riskier) ---
    if quality_score is None:
        quality_risk = 60.0
        quality_reason = (
            "No quality evidence on file (no certification, verified review "
            "or past-order record) — quality is unverified for this supplier."
        )
    elif quality_score >= 80:
        quality_risk = 10.0
        quality_reason = "Strong evidenced quality (score >= 80)."
    elif quality_score >= 60:
        quality_risk = 30.0
        quality_reason = "Moderate evidenced quality (score 60-79)."
    else:
        quality_risk = 55.0
        quality_reason = "Low evidenced quality (score < 60)."
    if risk_flags:
        quality_risk = min(100.0, quality_risk + 10.0 * len(risk_flags))
        quality_reason += f" Risk flags on file: {len(risk_flags)}."
    if not quality_evidence and quality_score is not None:
        quality_reason += " (score supplied without attached evidence — treat with caution)"

    # --- overall risk: cost volatility + quality risk + lead-time risk ---
    cost_risk = min(50.0, abs(price_change_pct) * 2.0 + abs(quantity_change_pct) * 0.5)
    lead_risk = min(30.0, (delivery_slip_days or 0) * 5.0 + (max(0, (lead_time_days or 0) - 14) * 1.0))
    risk_score = round(min(100.0, 0.5 * quality_risk + 0.3 * cost_risk + 0.2 * lead_risk), 2)

    if transport_included is None:
        transport_included = transport > 0
    return {
        "landed_cost": what_if_cost,
        "base_landed_cost": round(base_cost, 2),
        "delivery_slip_days": delivery_slip_days,
        "risk_score": risk_score,
        "quality_score": quality_score,
        "quality_risk": round(quality_risk, 2),
        "quality_risk_reason": quality_reason,
        "transport_cost": round(transport, 2),
        "transport_included": bool(transport_included),
        "landed_cost_label": (
            "incl. transport" if transport_included else "excl. transport"
        ),
        "what_if": {
            "price_change_pct": price_change_pct,
            "delivery_slip_days": delivery_slip_days,
            "quantity_change_pct": quantity_change_pct,
            "landed_cost_before": round(base_cost, 2),
            "landed_cost_after": what_if_cost,
            "transport_cost": round(transport, 2),
            "transport_included": bool(transport_included),
        },
    }
