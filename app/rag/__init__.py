"""Hybrid Search RAG — reel skill #1.

TF-IDF + BM25 (implemented here, no heavy dependency) + optional
sentence-transformers / FAISS embeddings behind try/except, fused with
Reciprocal Rank Fusion (RRF). Local-first: no API key required.
"""
from .retrieval import (
    BM25,
    HybridRetrieval,
    Passage,
    RetrievalResult,
    TfIdf,
    build_plan_corpus,
    load_plan_corpus,
)

__all__ = [
    "BM25",
    "HybridRetrieval",
    "Passage",
    "RetrievalResult",
    "TfIdf",
    "build_plan_corpus",
    "load_plan_corpus",
]
