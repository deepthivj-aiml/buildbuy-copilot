"""Takeoff engine — deterministic materials estimation (pure Python).

Every line is labelled "estimate, not a surveyed quantity".
"""
from .engine import (
    ESTIMATE_LABEL,
    TakeoffLine,
    TakeoffResult,
    compute_takeoff,
    verify_reconciliation,
)

__all__ = [
    "ESTIMATE_LABEL",
    "TakeoffLine",
    "TakeoffResult",
    "compute_takeoff",
    "verify_reconciliation",
]
