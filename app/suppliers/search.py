"""Supplier search — rank by BOTH cost and quality, trade-off shown.

Best-value rank = 0.45 * cost score + 0.35 * quality score + 0.20 * lead-time
score. Cost alone never wins: the cheapest option and the highest-quality
option are identified separately so the user can choose, and every ranked
supplier carries a one-line why_rank plus a trade-off line naming what it
gives up (e.g. "cheapest but 0.21 below best quality — late-delivery risk").

Location filter (max distance / max lead time), MOQ filter (qty below MOQ
excludes the supplier, listed with the reason — never silently dropped).

Total landed cost = goods + transport + taxes/fees, shown as a breakdown
per supplier. Transport is optional and manual: it is computed only when
the buyer types a delivery location themselves (blank by default — never
auto-detected, no geolocation, no IP lookup); otherwise the landed cost
is labelled "excl. transport".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .directory import haversine_km, quality_score, suppliers_for_material

# Best-value weights (sum to 1.0): cost leads, quality is close behind.
# CANONICAL — the single source of truth for best-value ranking.
# app/ranking.py::rank_shortlist and the frontend import these weights;
# do not keep a second formula anywhere else.
W_COST = 0.45
W_QUALITY = 0.35
W_LEAD = 0.20

# Total landed cost = goods + transport + taxes/fees (where known).
# Transport is OPTIONAL and MANUAL: the buyer types a delivery location
# (see app/suppliers/location.py — blank by default, never auto-detected).
# transport_rate_per_km is the buyer's own rate ($/km); when None, the
# documented demo shipping estimate (twin.shipping_cost_usd) is used.
# When no buyer location is given at all, transport is EXCLUDED and the
# landed cost is labelled "excl. transport".
HANDLING_PCT = 0.02  # 2% of goods value
ADMIN_FEE_USD = 15.0


def best_value_score(
    cost_score: float, quality_score: float, lead_score: float
) -> float:
    """Canonical best-value blend. All components 0..1; returns 0..1."""
    return round(
        W_COST * cost_score + W_QUALITY * quality_score + W_LEAD * lead_score, 3
    )


def landed_cost_breakdown(
    *,
    unit_price: float,
    quantity: float,
    distance_km: float | None,
    transport_rate_per_km: float | None = None,
    include_transport: bool = True,
) -> dict:
    """Total landed cost with a per-line breakdown.

    Returns {"goods", "transport", "taxes_fees", "total",
    "transport_included", "landed_cost_label"}. When no buyer location
    is known (distance_km is None) or include_transport is False,
    transport is None, excluded from the total, and the label reads
    "excl. transport" — the user sees exactly what is (not) in the total.
    """
    from app.twin.simulator import shipping_cost_usd  # local import: no cycle at load

    goods = round(unit_price * quantity, 2)
    fees = round(goods * HANDLING_PCT + ADMIN_FEE_USD, 2)
    if distance_km is None or not include_transport:
        return {
            "goods": goods,
            "transport": None,
            "taxes_fees": fees,
            "total": round(goods + fees, 2),
            "transport_included": False,
            "landed_cost_label": "excl. transport",
        }
    if transport_rate_per_km is not None:
        transport = round(distance_km * transport_rate_per_km, 2)
    else:
        transport = shipping_cost_usd(distance_km)
    return {
        "goods": goods,
        "transport": transport,
        "taxes_fees": fees,
        "total": round(goods + transport + fees, 2),
        "transport_included": True,
        "landed_cost_label": "incl. transport",
    }


@dataclass
class RankedSupplier:
    supplier: dict
    distance_km: float | None
    unit_price: float
    landed_cost: float
    cost_score: float  # 0..1, 1 = cheapest landed cost in this search
    quality_score: float  # 0..1, from evidenced signals only
    quality_evidence: list[dict] = field(default_factory=list)
    lead_score: float = 0.0  # 0..1, 1 = shortest lead time in this search
    best_value: float = 0.0
    rank: int = 0
    why_rank: str = ""
    tradeoff: str = ""
    transport_cost: float | None = None
    transport_included: bool = False
    landed_breakdown: dict = field(default_factory=dict)
    landed_cost_label: str = "excl. transport"

    def as_dict(self) -> dict:
        return {
            "supplier_id": self.supplier["id"],
            "name": self.supplier["name"],
            "city": self.supplier["city"],
            "distance_km": self.distance_km,
            "unit_price": self.unit_price,
            "landed_cost": self.landed_cost,
            "landed_breakdown": self.landed_breakdown,
            "transport_cost": self.transport_cost,
            "transport_included": self.transport_included,
            "landed_cost_label": self.landed_cost_label,
            "cost_score": self.cost_score,
            "quality_score": self.quality_score,
            "lead_score": self.lead_score,
            "best_value": self.best_value,
            "rank": self.rank,
            "why_rank": self.why_rank,
            "tradeoff": self.tradeoff,
            "quality_evidence": self.quality_evidence,
            "lead_time_days": self.supplier["lead_time_days"],
            "moq": self.supplier.get("moq", {}),
        }


def _norm(values: list[float], higher_better: bool) -> list[float]:
    """Min-max normalise to 0..1; a single value scores 1.0."""
    if len(values) <= 1:
        return [1.0 for _ in values]
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]
    if higher_better:
        return [(v - lo) / (hi - lo) for v in values]
    return [(hi - v) / (hi - lo) for v in values]


def search_suppliers(
    suppliers: list[dict],
    material: str,
    quantity: float,
    buyer_lat: float | None = None,
    buyer_lng: float | None = None,
    max_distance_km: float | None = None,
    max_lead_days: int | None = None,
    transport_rate_per_km: float | None = None,
    include_transport: bool = True,
) -> dict:
    """Rank suppliers for one material + quantity.

    ``buyer_lat``/``buyer_lng`` are OPTIONAL and come only from a
    delivery location the user typed themselves (see
    ``app.suppliers.location.geocode_location``) — blank by default,
    never auto-detected. Without them, distance is unknown, transport
    is excluded from total landed cost, and every line is labelled
    "excl. transport". ``transport_rate_per_km`` is the buyer's own
    $/km rate; when None the documented demo shipping estimate is used.

    Returns {"ranked": [...], "cheapest": {...}|None,
    "highest_quality": {...}|None, "excluded": [...]}.
    """
    candidates = []
    excluded = []
    for sup in suppliers_for_material(suppliers, material):
        moq = (sup.get("moq") or {}).get(material)
        if moq is not None and quantity < moq:
            excluded.append({
                "supplier_id": sup["id"], "name": sup["name"],
                "reason": f"quantity {quantity} below MOQ {moq} for {material}",
            })
            continue
        if max_lead_days is not None and sup["lead_time_days"] > max_lead_days:
            excluded.append({
                "supplier_id": sup["id"], "name": sup["name"],
                "reason": f"lead time {sup['lead_time_days']} days exceeds max {max_lead_days}",
            })
            continue
        if buyer_lat is None or buyer_lng is None:
            dist = None
        else:
            dist = haversine_km(buyer_lat, buyer_lng, sup["lat"], sup["lng"])
        if max_distance_km is not None and dist is not None and dist > max_distance_km:
            excluded.append({
                "supplier_id": sup["id"], "name": sup["name"],
                "reason": f"distance {dist} km exceeds max {max_distance_km} km",
            })
            continue
        unit = float(sup["unit_prices"][material])
        breakdown = landed_cost_breakdown(
            unit_price=unit, quantity=quantity, distance_km=dist,
            transport_rate_per_km=transport_rate_per_km,
            include_transport=include_transport,
        )
        q, evidence = quality_score(sup)
        candidates.append({
            "supplier": sup, "distance_km": dist, "unit_price": unit,
            "landed_cost": breakdown["total"],
            "landed_breakdown": breakdown,
            "quality_score": q,
            "quality_evidence": evidence,
        })
    if not candidates:
        return {"ranked": [], "cheapest": None, "highest_quality": None, "excluded": excluded}

    cost_scores = _norm([c["landed_cost"] for c in candidates], higher_better=False)
    lead_scores = _norm(
        [c["supplier"]["lead_time_days"] for c in candidates], higher_better=False
    )
    ranked: list[RankedSupplier] = []
    for c, cs, ls in zip(candidates, cost_scores, lead_scores):
        bd = c["landed_breakdown"]
        ranked.append(RankedSupplier(
            supplier=c["supplier"], distance_km=c["distance_km"],
            unit_price=c["unit_price"], landed_cost=c["landed_cost"],
            cost_score=round(cs, 3), quality_score=c["quality_score"],
            quality_evidence=c["quality_evidence"], lead_score=round(ls, 3),
            best_value=best_value_score(cs, c["quality_score"], ls),
            transport_cost=bd["transport"],
            transport_included=bd["transport_included"],
            landed_breakdown=bd,
            landed_cost_label=bd["landed_cost_label"],
        ))
    ranked.sort(key=lambda r: r.best_value, reverse=True)
    cheapest = min(ranked, key=lambda r: r.landed_cost)
    best_quality = max(ranked, key=lambda r: r.quality_score)
    for i, r in enumerate(ranked, start=1):
        r.rank = i
        flags = r.supplier.get("risk_flags") or []
        flag_txt = f" Risk flags: {', '.join(flags)}." if flags else ""
        dist_txt = f"{r.distance_km} km" if r.distance_km is not None else "distance unknown"
        r.why_rank = (
            f"#{i} best value ({r.best_value:.2f}): landed ${r.landed_cost:.2f} "
            f"({r.landed_cost_label}), "
            f"quality {r.quality_score:.2f}, {dist_txt}, "
            f"{r.supplier['lead_time_days']} days lead.{flag_txt}"
        )
        if r is cheapest and r is best_quality:
            r.tradeoff = "Cheapest AND highest quality in this search — no trade-off."
        elif r is cheapest:
            gap = round(best_quality.quality_score - r.quality_score, 2)
            r.tradeoff = (
                f"Cheapest at ${r.landed_cost:.2f} landed, but quality "
                f"{r.quality_score:.2f} is {gap} below the best quality "
                f"({best_quality.supplier['name']}, {best_quality.quality_score:.2f})."
                + (f" {flag_txt.strip()}" if flags else "")
            )
        elif r is best_quality:
            extra = round(r.landed_cost - cheapest.landed_cost, 2)
            r.tradeoff = (
                f"Highest quality ({r.quality_score:.2f}) but costs ${extra:.2f} more "
                f"landed than the cheapest ({cheapest.supplier['name']}, "
                f"${cheapest.landed_cost:.2f})."
            )
        else:
            r.tradeoff = (
                f"Middle of the pack: ${round(r.landed_cost - cheapest.landed_cost, 2):.2f} "
                f"above cheapest, quality {round(best_quality.quality_score - r.quality_score, 2)} "
                f"below best quality."
            )
    return {
        "ranked": [r.as_dict() for r in ranked],
        "cheapest": cheapest.as_dict(),
        "highest_quality": best_quality.as_dict(),
        "excluded": excluded,
    }
