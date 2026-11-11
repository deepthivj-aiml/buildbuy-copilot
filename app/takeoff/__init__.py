"""Takeoff engine — deterministic materials estimation (pure Python).

Every line is labelled "estimate, not a surveyed quantity".
"""
from .engine import (
    ESTIMATE_LABEL,
    TakeoffLine,
    TakeoffResult,
    apply_requirement_to_result,
    compute_takeoff,
    takeoff_line_from_requirement,
    verify_reconciliation,
)

__all__ = [
    "ESTIMATE_LABEL",
    "TakeoffLine",
    "TakeoffResult",
    "apply_requirement_to_result",
    "compute_takeoff",
    "takeoff_line_from_requirement",
    "verify_reconciliation",
]
