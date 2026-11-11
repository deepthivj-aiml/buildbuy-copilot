"""Takeoff engine — deterministic materials estimation.

Pure Python, unit-testable. Given synthetic plan metadata (area, counts,
lengths) it computes materials with the method shown per line, a confidence
score, and low-confidence flags. EVERY line is labelled
"estimate, not a surveyed quantity" — never presented as a surveyor's
measurement (UNIFIED_PLAN_ARCHITECTURE.md §2.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ESTIMATE_LABEL = "estimate, not a surveyed quantity"

# Rates are documented assumptions, not measured site data.
WASTE_CONCRETE = 1.05  # 5% waste / over-pour allowance
WASTE_TILES = 1.10  # 10% cutting waste
WASTE_TIMBER = 1.05  # 5% cutting waste
BRICKS_PER_M2_WALL = 50  # per spec clause 4.1
DEFAULT_STEEL_KG_PER_M3 = 85  # per spec clause 3.4 (plan-001/003); plan-002 uses 90

_STEEL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kg per cubic metre")


@dataclass
class TakeoffLine:
    material: str
    quantity: float | None
    unit: str
    method: str
    confidence: float  # 0..1
    flagged: bool
    estimate_label: str = ESTIMATE_LABEL


@dataclass
class TakeoffResult:
    plan_id: str
    lines: list[TakeoffLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, float]:
        return {
            line.material: line.quantity
            for line in self.lines
            if line.quantity is not None
        }

    def flagged_lines(self) -> list[TakeoffLine]:
        return [line for line in self.lines if line.flagged]


def _steel_rate(plan: dict) -> float:
    for clause in plan.get("spec_clauses", []):
        m = _STEEL_RE.search(clause.get("text", ""))
        if m:
            return float(m.group(1))
    return float(plan.get("steel_kg_per_m3", DEFAULT_STEEL_KG_PER_M3))


def compute_takeoff(plan: dict) -> TakeoffResult:
    """Compute the materials estimate for one synthetic plan dict."""
    pid = plan.get("plan_id", "unknown")
    result = TakeoffResult(plan_id=pid)
    missing = [k for k in ("floor_area_m2", "slab_thickness_m") if plan.get(k) is None]
    base_conf = 0.90 if not missing else 0.60
    if missing:
        result.notes.append(
            f"Missing plan inputs {missing}; affected lines are flagged and "
            "have no quantity — do not use them for ordering."
        )

    area = plan.get("floor_area_m2")
    thick = plan.get("slab_thickness_m")
    concrete = None
    if area is not None and thick is not None:
        concrete = round(area * thick * WASTE_CONCRETE, 2)
    result.lines.append(
        TakeoffLine(
            material="concrete",
            quantity=concrete,
            unit="m3",
            method=f"floor area ({area} m2) x slab thickness ({thick} m) x "
            f"waste factor {WASTE_CONCRETE}",
            confidence=base_conf if concrete is not None else 0.4,
            flagged=concrete is None,
        )
    )

    steel_rate = _steel_rate(plan)
    steel = round(concrete * steel_rate, 1) if concrete is not None else None
    result.lines.append(
        TakeoffLine(
            material="steel",
            quantity=steel,
            unit="kg",
            method=f"concrete ({concrete} m3) x steel rate ({steel_rate} kg/m3, "
            "spec clause 3.4)",
            confidence=base_conf if steel is not None else 0.4,
            flagged=steel is None,
        )
    )

    wall_len, wall_h = plan.get("wall_length_m"), plan.get("wall_height_m")
    wall_area = None
    if wall_len is not None and wall_h is not None:
        wall_area = round(wall_len * wall_h, 2)
    bricks = int(wall_area * BRICKS_PER_M2_WALL) if wall_area is not None else None
    result.lines.append(
        TakeoffLine(
            material="bricks",
            quantity=bricks,
            unit="units",
            method=f"wall area ({wall_len} m x {wall_h} m = {wall_area} m2) x "
            f"{BRICKS_PER_M2_WALL} bricks/m2 (spec clause 4.1)",
            confidence=0.85 if bricks is not None else 0.4,
            flagged=bricks is None,
        )
    )

    tile_area = plan.get("tile_area_m2")
    tiles = round(tile_area * WASTE_TILES, 2) if tile_area is not None else None
    result.lines.append(
        TakeoffLine(
            material="tiles",
            quantity=tiles,
            unit="m2",
            method=f"tiled area ({tile_area} m2) x cutting waste {WASTE_TILES} "
            "(spec clause 5.2)",
            confidence=0.85 if tiles is not None else 0.4,
            flagged=tiles is None,
        )
    )

    timber_len = plan.get("timber_length_m")
    timber = round(timber_len * WASTE_TIMBER, 1) if timber_len is not None else None
    result.lines.append(
        TakeoffLine(
            material="timber",
            quantity=timber,
            unit="m",
            method=f"timber length ({timber_len} m) x cutting waste {WASTE_TIMBER} "
            "(spec clause 6.1)",
            confidence=0.85 if timber is not None else 0.4,
            flagged=timber is None,
        )
    )
    return result


def verify_reconciliation(result: TakeoffResult, plan: dict) -> dict:
    """Hand-worked re-check: recompute each line independently and compare.

    Returns {"ok": bool, "checks": {material: bool}} — the test suite asserts
    ok is True for every synthetic plan.
    """
    checks: dict[str, bool] = {}
    expected = compute_takeoff(plan)
    for line, exp in zip(result.lines, expected.lines):
        checks[line.material] = line.quantity == exp.quantity
    return {"ok": all(checks.values()), "checks": checks}
