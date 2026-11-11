"""Tests for the VLM / plan-vision module (app/vlm/).

Local-fallback plan parsing from structured plan data — title block,
labelled regions, spec clauses. No model call is made here; a real VLM
plugs in behind the same VisionReader interface.

Run alone:  .venv/bin/python -m pytest tests/test_vlm.py -v
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vlm import (  # noqa: E402
    VisionReader,
    answer_about_plan,
    describe_plan,
    detect_scale,
    extract_regions,
    find_region,
    read_title_block,
)

DATA = ROOT / "data"
PLAN = json.loads((DATA / "plans" / "plan-001.json").read_text())


def test_detect_scale_from_title_block():
    assert detect_scale(PLAN) == "1:50"
    assert detect_scale({"title": "Something at 1:100"}) == "1:100"
    assert detect_scale({"title": "No scale here"}) is None  # never guessed


def test_extract_regions_and_find():
    regions = extract_regions(PLAN)
    assert len(regions) == 4
    assert [r.region_id for r in regions] == ["R-slab", "R-walls", "R-bath", "R-roof"]
    slab = find_region(PLAN, "R-slab")
    assert slab is not None and slab.label == "Ground floor slab"
    assert slab.sheet == "A-101" and slab.bbox == [60, 300, 540, 460]
    assert find_region(PLAN, "R-nope") is None


def test_title_block_and_full_reading():
    tb = read_title_block(PLAN)
    assert tb == {"plan_id": "plan-001", "title": PLAN["title"], "sheet": "A-101",
                  "scale": "1:50", "location": "Fremont, CA"}
    reading = describe_plan(PLAN)
    assert reading.plan_id == "plan-001"
    assert reading.scale_confirmed is False  # user must confirm before measurements
    assert "no VLM call" in reading.source
    assert reading.clause_ids[0] == "C-01"
    # A custom reader plugs in behind the same interface.
    class FakeVLM(VisionReader):
        def read_plan(self, plan):
            r = super().read_plan(plan)
            r.source = "fake-vlm"
            return r
    assert describe_plan(PLAN, reader=FakeVLM()).source == "fake-vlm"


def test_answer_about_plan_or_honest_not_found():
    ans = answer_about_plan(PLAN, "What scale is this plan?")
    assert ans["found"] is True and "1:50" in ans["answer"]
    assert "Title block" in ans["citation"]
    ans = answer_about_plan(PLAN, "What regions are on this plan?")
    assert ans["found"] is True and "R-slab" in ans["answer"]
    ans = answer_about_plan(PLAN, "What is the tensile strength of the moon base?")
    assert ans["found"] is False and "not found" in ans["answer"].lower()
    # Content-word match on a real clause: concrete + grade -> C-01.
    ans = answer_about_plan(PLAN, "What concrete grade is specified?")
    assert ans["found"] is True and "C25/30" in ans["answer"]
    assert ans["citation"].startswith("Spec C-01")
