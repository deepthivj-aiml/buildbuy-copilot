"""Digital twin simulator — per-decision purchase simulation (pure Python).

Simulates BOTH cost and quality risk for one purchase with one supplier:
landed cost (goods + shipping + fees), delivery date from lead time, and a
risk score built from cost risk AND quality risk. A cheap supplier that is
late or low quality shows a higher total risk — cost alone never wins.

What-if sliders (price +%, delivery +days, quantity +%) recompute everything
and list exactly what breaks (over budget, past deadline, quality risk too
high, defect exposure). All formulas are deterministic and unit-testable.

Total landed cost = goods + transport + taxes/fees, shown as a breakdown.
Transport is OPTIONAL and MANUAL: the buyer location comes only from a
delivery location the user types themselves (blank by default — never
auto-detected, no geolocation, no IP lookup; see
app/suppliers/location.py). Without a buyer location, transport is
excluded and the landed cost is labelled "excl. transport".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

# Documented synthetic rates (demo only — not real carrier tariffs).
SHIPPING_BASE_USD = 25.0
SHIPPING_PER_KM_USD = 0.55
HANDLING_PCT = 0.02  # 2% of goods value
ADMIN_FEE_USD = 15.0
QUALITY_RISK_HIGH = 0.60  # quality_risk_score above this = "breaks"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def shipping_cost_usd(distance_km: float) -> float:
    return round(SHIPPING_BASE_USD + SHIPPING_PER_KM_USD * distance_km, 2)


def quality_risk_from_supplier(supplier: dict) -> tuple[float, list[str]]:
    """Quality risk 0..1 (higher = riskier) + evidence, from quality signals.

    Uses the supplier directory's quality score when available; falls back to
    the raw reliability fields so this module stays standalone.
    """
    try:
        from app.suppliers.directory import quality_score  # type: ignore

        q, evidence = quality_score(supplier)
        notes = [e["signal"] + ": " + str(e["value"]) for e in evidence]
        return round(1.0 - q, 3), notes
    except Exception:
        reply = float(supplier.get("reply_reliability") or 0.5)
        lead_rel = float(supplier.get("lead_time_reliability") or 0.5)
        defect = supplier.get("defect_rate_pct")
        defect_score = max(0.0, 1.0 - defect / 5.0) if defect is not None else 0.5
        q = 0.4 * reply + 0.35 * lead_rel + 0.25 * defect_score
        return round(1.0 - q, 3), ["fallback quality estimate from reliability fields"]


@dataclass
class Simulation:
    supplier_id: str
    supplier_name: str
    material: str
    quantity: float
    unit_price: float
    goods_cost: float
    shipping_cost: float
    fees: float
    landed_cost: float
    distance_km: float | None
    delivery_date: date
    lead_time_days: int
    cost_risk: float  # 0..1 — price variance / distance driven
    quality_risk: float  # 0..1 — cheap-but-late / low-quality driven
    risk_score: float  # combined: 0.5 * cost_risk + 0.5 * quality_risk
    quality_evidence: list[str] = field(default_factory=list)
    breaks: list[str] = field(default_factory=list)
    # Transport is the shipping line, made explicit: when the buyer gave
    # no delivery location it is excluded (None / 0.0) and the landed
    # cost is labelled "excl. transport".
    transport_cost: float | None = None
    transport_included: bool = False
    landed_breakdown: dict = field(default_factory=dict)
    landed_cost_label: str = "excl. transport"

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["delivery_date"] = self.delivery_date.isoformat()
        return d


class DigitalTwin:
    """Simulate one purchase decision with one supplier.

    ``buyer_lat``/``buyer_lng`` are OPTIONAL and come only from a
    delivery location the user typed themselves — blank by default,
    never auto-detected. Without them, distance is unknown, transport
    is excluded from total landed cost, and the simulation is labelled
    "excl. transport".
    """

    def __init__(
        self,
        buyer_lat: float | None = None,
        buyer_lng: float | None = None,
        order_date: date | None = None,
    ):
        self.buyer_lat = buyer_lat
        self.buyer_lng = buyer_lng
        self.order_date = order_date or date.today()

    def simulate(
        self,
        supplier: dict,
        material: str,
        quantity: float,
        max_price: float | None = None,
        deadline: date | None = None,
        transport_rate_per_km: float | None = None,
        include_transport: bool = True,
    ) -> Simulation:
        from app.suppliers.search import landed_cost_breakdown  # local import: no cycle

        unit = float(supplier["unit_prices"][material])
        if self.buyer_lat is None or self.buyer_lng is None:
            distance = None
        else:
            distance = haversine_km(
                self.buyer_lat, self.buyer_lng, supplier["lat"], supplier["lng"]
            )
        breakdown = landed_cost_breakdown(
            unit_price=unit, quantity=quantity, distance_km=distance,
            transport_rate_per_km=transport_rate_per_km,
            include_transport=include_transport,
        )
        goods = breakdown["goods"]
        ship = breakdown["transport"] if breakdown["transport"] is not None else 0.0
        fees = breakdown["taxes_fees"]
        landed = breakdown["total"]
        lead = int(supplier["lead_time_days"])
        delivery = self.order_date + timedelta(days=lead)

        quality_risk, evidence = quality_risk_from_supplier(supplier)
        # Cost risk: long distance + long lead time make the landed cost
        # fragile (shipping and delay exposure); normalised 0..1.
        # No buyer location -> distance unknown -> distance term is 0.
        cost_risk = round(
            min(1.0, 0.5 * ((distance or 0.0) / 1000.0) + 0.5 * (lead / 14.0)), 3
        )
        risk = round(0.5 * cost_risk + 0.5 * quality_risk, 3)

        breaks: list[str] = []
        if max_price is not None and landed > max_price:
            breaks.append(f"over_budget: landed ${landed:.2f} > max ${max_price:.2f}")
        if deadline is not None and delivery > deadline:
            breaks.append(f"past_deadline: delivery {delivery} > deadline {deadline}")
        if quality_risk >= QUALITY_RISK_HIGH:
            breaks.append(
                f"quality_risk_high: quality risk {quality_risk} >= {QUALITY_RISK_HIGH} "
                "(cheap but late / low quality — see quality evidence)"
            )
        defect = supplier.get("defect_rate_pct")
        if defect is not None:
            exposure = round(goods * defect / 100.0, 2)
            if exposure > 0.05 * landed:
                breaks.append(
                    f"defect_exposure: expected defect cost ${exposure:.2f} "
                    f"({defect}% of goods) exceeds 5% of landed cost"
                )
        return Simulation(
            supplier_id=supplier["id"],
            supplier_name=supplier["name"],
            material=material,
            quantity=quantity,
            unit_price=unit,
            goods_cost=goods,
            shipping_cost=ship,
            fees=fees,
            landed_cost=landed,
            distance_km=distance,
            delivery_date=delivery,
            lead_time_days=lead,
            cost_risk=cost_risk,
            quality_risk=quality_risk,
            risk_score=risk,
            quality_evidence=evidence,
            breaks=breaks,
            transport_cost=breakdown["transport"],
            transport_included=breakdown["transport_included"],
            landed_breakdown=breakdown,
            landed_cost_label=breakdown["landed_cost_label"],
        )

    def what_if(
        self,
        supplier: dict,
        material: str,
        quantity: float,
        price_pct: float = 0.0,
        delay_days: int = 0,
        qty_pct: float = 0.0,
        max_price: float | None = None,
        deadline: date | None = None,
        transport_rate_per_km: float | None = None,
        include_transport: bool = True,
    ) -> dict:
        """Recompute the simulation under a what-if change; show what breaks."""
        base = self.simulate(
            supplier, material, quantity, max_price, deadline,
            transport_rate_per_km=transport_rate_per_km,
            include_transport=include_transport,
        )
        new_qty = quantity * (1 + qty_pct / 100.0)
        # Apply the price change by simulating with an adjusted unit price.
        adjusted = dict(supplier)
        adjusted["unit_prices"] = dict(supplier["unit_prices"])
        adjusted["unit_prices"][material] = round(
            supplier["unit_prices"][material] * (1 + price_pct / 100.0), 4
        )
        adjusted["lead_time_days"] = int(supplier["lead_time_days"]) + delay_days
        new = self.simulate(
            adjusted, material, new_qty, max_price, deadline,
            transport_rate_per_km=transport_rate_per_km,
            include_transport=include_transport,
        )
        # Delay also raises quality risk: a slip is itself a reliability failure.
        if delay_days:
            new.quality_risk = round(
                min(1.0, new.quality_risk + 0.05 * delay_days), 3
            )
            new.risk_score = round(0.5 * new.cost_risk + 0.5 * new.quality_risk, 3)
            if (
                new.quality_risk >= QUALITY_RISK_HIGH
                and not any(b.startswith("quality_risk_high") for b in new.breaks)
            ):
                new.breaks.append(
                    f"quality_risk_high: delay of {delay_days} days pushes quality "
                    f"risk to {new.quality_risk}"
                )
        return {
            "base": base.as_dict(),
            "what_if": {
                "price_pct": price_pct,
                "delay_days": delay_days,
                "qty_pct": qty_pct,
            },
            "result": new.as_dict(),
            "delta_landed_usd": round(new.landed_cost - base.landed_cost, 2),
            "delta_risk": round(new.risk_score - base.risk_score, 3),
            "delta_quality_risk": round(new.quality_risk - base.quality_risk, 3),
            "breaks": new.breaks,
        }
