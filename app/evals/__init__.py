"""Eval generator + runner — reel skill #4. Grounded pairs, JSONL/CSV, measured metrics."""
from .eval_gen import (
    ADVERSARIAL,
    build_and_export,
    dedupe_pairs,
    export_eval_set,
    generate_eval_pairs,
    quality_check,
    run_eval,
)

__all__ = [
    "ADVERSARIAL",
    "build_and_export",
    "dedupe_pairs",
    "export_eval_set",
    "generate_eval_pairs",
    "quality_check",
    "run_eval",
]
