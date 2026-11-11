"""Tests for RAG / hybrid retrieval — TF-IDF + BM25 + RRF, cited answers or honest not-found.

Run alone:  .venv/bin/python -m pytest tests/test_rag.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.retrieval import HybridRetrieval, load_plan_corpus  # noqa: E402

DATA = ROOT / "data"


def test_retrieval_top1_and_not_found():
    ret = HybridRetrieval(load_plan_corpus(DATA))
    hits = ret.search("What concrete grade is specified for Maple Court ADU?")
    assert hits, "expected a hit for a grounded question"
    assert hits[0].passage.doc_id == "plan-001-C-01", f"top-1 was {hits[0].passage.doc_id}"
    assert hits[0].passage.citation()["clause"] == "C-01"
    assert ret.search("What is the tensile strength of the moon base?") == []
    ans = ret.answer("What is the tensile strength of the moon base?")
    assert ans["status"] == "not_found" and "Not found" in ans["answer"]
    found = ret.answer("How many fixtures are in Maple Court ADU?")
    # Top hit may be clause C-06 or the overview — both contain the answer;
    # what matters is the answer is cited and contains the count.
    assert found["status"] == "found" and "12" in found["answer"]
    assert found["citations"] and found["citations"][0]["doc_id"].startswith("plan-001")
