"""Plan vision (VLM) — local-fallback plan parsing.

Deterministic reader of a plan's structured data (title block, labelled
regions, spec clauses). A real VLM plugs in behind the same interface
(see plan_vision.VisionReader). No model call is made here.
"""
from .plan_vision import (
    PlanReading,
    PlanRegion,
    VisionReader,
    answer_about_plan,
    describe_plan,
    detect_scale,
    extract_regions,
    find_region,
    read_title_block,
)

__all__ = [
    "PlanReading",
    "PlanRegion",
    "VisionReader",
    "answer_about_plan",
    "describe_plan",
    "detect_scale",
    "extract_regions",
    "find_region",
    "read_title_block",
]
