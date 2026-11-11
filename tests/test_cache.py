"""Tests for semantic cache — paraphrase hits, plan isolation, measured savings.

Run alone:  .venv/bin/python -m pytest tests/test_cache.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cache.semantic_cache import SemanticCache  # noqa: E402

DATA = ROOT / "data"


def test_cache_paraphrase_hit_and_plan_isolation():
    cache = SemanticCache()
    cache.put("plan-001", "What concrete grade is specified?", "grade C25/30")
    hit = cache.get("plan-001", "What is the concrete grade specified?")
    assert hit is not None and hit["answer"] == "grade C25/30"
    synonym_hit = cache.get("plan-001", "What cement grade is specified?")
    assert synonym_hit is not None, "synonym paraphrase should hit"
    assert cache.get("plan-001", "How many bricks are needed?") is None
    # Plan-aware: the same question about a different plan must NOT hit.
    assert cache.get("plan-002", "What concrete grade is specified?") is None
    stats = cache.stats()
    assert stats["hits"] == 2 and stats["misses"] == 2
    assert stats["savings_usd"] == round(2 * 0.02, 4)
