"""Plan vision (VLM) — local-fallback plan parsing, reel skill #2 support.

What this module IS: a deterministic reader of a construction plan's
STRUCTURED data — the title block (scale, sheet, title), the labelled
plan regions (bbox + label per region), and the spec clauses. It answers
the questions the copilot chat asks about a plan ("what scale is this
plan?", "what is in region R-slab?", "what does clause 3.2 say?") from
that structured data, with a citation (sheet + region / clause) every
time — or an honest "not found".

What it is NOT: a real vision-language model. No image pixels are read
here and no VLM is called. A real VLM plugs in behind the SAME
interface: implement ``VisionReader.read_plan`` (return a
:class:`PlanReading` with the same fields) and pass it to the functions
that take a ``reader`` — nothing else changes. Until then, every
reading is labelled ``source="structured_plan_data (local fallback —
no VLM call)"`` so a fallback reading is never presented as a
model reading.

Rebuild / test alone::

    .venv/bin/python -m pytest tests/test_vlm.py -v
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_SCALE_RE = re.compile(r"1\s*:\s*(\d+)")


@dataclass
class PlanRegion:
    region_id: str
    label: str
    sheet: str
    bbox: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "region_id": self.region_id,
            "label": self.label,
            "sheet": self.sheet,
            "bbox": self.bbox,
        }


@dataclass
class PlanReading:
    """What was read from one plan (structured data or a real VLM)."""

    plan_id: str
    title: str
    sheet: str
    scale: str | None
    scale_confirmed: bool
    location: str
    regions: list[PlanRegion] = field(default_factory=list)
    clause_ids: list[str] = field(default_factory=list)
    source: str = "structured_plan_data (local fallback — no VLM call)"

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "sheet": self.sheet,
            "scale": self.scale,
            "scale_confirmed": self.scale_confirmed,
            "location": self.location,
            "regions": [r.as_dict() for r in self.regions],
            "clause_ids": self.clause_ids,
            "source": self.source,
        }


class VisionReader:
    """Local-fallback reader: structured plan data only, no model call.

    A real VLM reader subclasses this and overrides :meth:`read_plan`
    to return a :class:`PlanReading` from image pixels; callers use
    the same fields either way.
    """

    def read_plan(self, plan: dict) -> PlanReading:
        return PlanReading(
            plan_id=str(plan.get("plan_id", "")),
            title=str(plan.get("title", "")),
            sheet=str(plan.get("sheet", "")),
            scale=detect_scale(plan),
            scale_confirmed=False,  # user must confirm before measurements
            location=str(plan.get("location", "")),
            regions=extract_regions(plan),
            clause_ids=[
                str(c.get("clause_id", ""))
                for c in plan.get("spec_clauses", [])
                if c.get("clause_id")
            ],
        )


def detect_scale(plan: dict) -> str | None:
    """Scale from the plan's title block (``plan['scale']``), e.g. "1:50".

    Falls back to a "1:N" pattern in the title text. Returns ``None``
    when no scale is stated — never guessed.
    """
    scale = plan.get("scale")
    if scale:
        return str(scale)
    m = _SCALE_RE.search(str(plan.get("title", "")))
    return f"1:{m.group(1)}" if m else None


def extract_regions(plan: dict) -> list[PlanRegion]:
    """Labelled plan regions (bbox + label + sheet), in plan order."""
    regions = []
    for r in plan.get("regions", []) or []:
        regions.append(PlanRegion(
            region_id=str(r.get("region_id", "")),
            label=str(r.get("label", "")),
            sheet=str(r.get("sheet", plan.get("sheet", ""))),
            bbox=list(r.get("bbox", []) or []),
        ))
    return regions


def find_region(plan: dict, region_id: str) -> PlanRegion | None:
    """One region by id (e.g. "R-slab"), or ``None`` when not on the plan."""
    for region in extract_regions(plan):
        if region.region_id == region_id:
            return region
    return None


def read_title_block(plan: dict) -> dict:
    """Title-block facts: title, sheet, scale, location, plan id."""
    return {
        "plan_id": plan.get("plan_id"),
        "title": plan.get("title"),
        "sheet": plan.get("sheet"),
        "scale": detect_scale(plan),
        "location": plan.get("location"),
    }


def describe_plan(plan: dict, reader: VisionReader | None = None) -> PlanReading:
    """Full structured reading of one plan (default: local fallback)."""
    return (reader or VisionReader()).read_plan(plan)


def answer_about_plan(plan: dict, question: str) -> dict:
    """Answer a plan question from structured data, or honest 'not found'.

    Returns {"found": bool, "answer": str, "citation": str}. Only the
    scale, the region list, the title block, and the spec-clause texts
    are answerable here — anything else is "not found", never guessed.
    Clause matching uses CONTENT words only (stopwords excluded): a
    question must share at least 2 content words with a clause, so
    "the"/"of"/"is" can never fake a match.
    """
    q = question.lower()
    reading = describe_plan(plan)
    if "scale" in q:
        if reading.scale:
            return {
                "found": True,
                "answer": f"The title block reads scale {reading.scale}. "
                          "Please confirm the scale before any measurement is used.",
                "citation": f"Title block, sheet {reading.sheet}",
            }
        return {"found": False, "answer": "Not found — no scale is stated on this plan.",
                "citation": ""}
    if "region" in q or "regions" in q:
        if reading.regions:
            labels = ", ".join(
                f"{r.region_id} ({r.label})" for r in reading.regions
            )
            return {"found": True,
                    "answer": f"Labelled regions on sheet {reading.sheet}: {labels}.",
                    "citation": f"Sheet {reading.sheet}"}
        return {"found": False, "answer": "Not found — no regions are labelled on this plan.",
                "citation": ""}
    if "title" in q or "sheet" in q:
        return {"found": True,
                "answer": f"{reading.title}, sheet {reading.sheet}, scale {reading.scale}.",
                "citation": f"Title block, sheet {reading.sheet}"}
    stopwords = {
        "what", "is", "the", "of", "a", "an", "and", "or", "for", "on", "in",
        "at", "to", "by", "how", "much", "many", "does", "do", "did", "this",
        "that", "it", "its", "are", "was", "were", "be", "please", "tell", "me",
    }

    def content_words(text: str) -> set[str]:
        return {
            w.strip(".,;:()").lower()
            for w in text.split()
            if w.strip(".,;:()").lower() not in stopwords
        }

    words = content_words(q)
    for clause in plan.get("spec_clauses", []) or []:
        text = str(clause.get("text", ""))
        if len(words & content_words(text)) >= 2:
            return {"found": True, "answer": text,
                    "citation": f"Spec {clause.get('clause_id', '')}, sheet {reading.sheet}"}
    return {"found": False,
            "answer": "Not found — I could not find this in the plan or specs.",
            "citation": ""}
