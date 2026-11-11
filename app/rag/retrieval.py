"""Hybrid Search RAG — reel skill #1.

Local, no-paid-API retrieval over plan passages, spec clauses and supplier
docs: TF-IDF + BM25 (both implemented in pure Python) fused with Reciprocal
Rank Fusion (RRF, k=60). sentence-transformers / FAISS embeddings are
optional: used only if installed, otherwise the TF-IDF + BM25 hybrid runs
alone and says so in ``backend``.

Every hit carries a citation (doc_id, page/region, clause). If nothing scores
above the threshold the search returns an empty list and ``answer()`` says
"not found" instead of guessing — see UNIFIED_PLAN_ARCHITECTURE.md §2.1.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "what", "which", "who",
    "how", "many", "much", "do", "does", "did", "in", "on", "of", "for",
    "to", "and", "or", "with", "by", "at", "from", "it", "its", "this",
    "that", "there", "here", "please", "tell", "me", "show", "give",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stopwords removed."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


@dataclass
class Passage:
    """One retrievable unit with its citation."""

    doc_id: str
    text: str
    source_type: str  # "plan_passage" | "spec_clause" | "supplier_doc"
    page: str = ""  # sheet, e.g. "A-101"
    region: str = ""  # region id on the plan image, e.g. "R-slab"
    clause: str = ""  # spec clause id, e.g. "C-01"
    plan_id: str = ""

    def citation(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "page": self.page,
            "region": self.region,
            "clause": self.clause,
        }


@dataclass
class RetrievalResult:
    passage: Passage
    score: float  # fused RRF score
    tfidf_score: float = 0.0
    bm25_score: float = 0.0
    embedding_score: float = 0.0


class TfIdf:
    """Minimal TF-IDF ranker (pure Python)."""

    def __init__(self, docs: list[list[str]]):
        self.docs = docs
        self.n = len(docs)
        self.df = Counter()
        for tokens in docs:
            self.df.update(set(tokens))
        self.idf = {
            t: math.log((self.n + 1) / (df + 1)) + 1.0 for t, df in self.df.items()
        }

    def score(self, query_tokens: list[str]) -> list[float]:
        q = Counter(query_tokens)
        out = []
        for tokens in self.docs:
            tf = Counter(tokens)
            s = 0.0
            for term, qc in q.items():
                if term in tf:
                    s += (tf[term] / len(tokens)) * self.idf.get(term, 0.0) * qc
            out.append(s)
        return out


class BM25:
    """Minimal BM25 ranker (pure Python). k1=1.5, b=0.75."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.avgdl = sum(len(d) for d in docs) / max(self.n, 1)
        self.df = Counter()
        for tokens in docs:
            self.df.update(set(tokens))
        self.idf = {
            t: math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            for t, df in self.df.items()
        }

    def score(self, query_tokens: list[str]) -> list[float]:
        out = []
        for tokens in self.docs:
            tf = Counter(tokens)
            dl = len(tokens)
            s = 0.0
            for term in set(query_tokens):
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1))
                s += self.idf.get(term, 0.0) * f * (self.k1 + 1) / denom
            out.append(s)
        return out


def _rrf(ranks: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion over per-ranker rank lists (doc indices)."""
    fused: dict[int, float] = {}
    for rank_list in ranks:
        for rank, doc_idx in enumerate(rank_list, start=1):
            fused[doc_idx] = fused.get(doc_idx, 0.0) + 1.0 / (k + rank)
    return fused


class HybridRetrieval:
    """TF-IDF + BM25 (+ optional embeddings), RRF fusion, cited results."""

    def __init__(self, passages: Iterable[Passage], threshold: float = 0.15):
        self.passages = list(passages)
        self.threshold = threshold
        docs = [tokenize(p.text) for p in self.passages]
        self._tfidf = TfIdf(docs)
        self._bm25 = BM25(docs)
        self._embeddings = None  # optional (sentence-transformers + FAISS)
        self.backend = "tfidf+bm25 (local, no API key)"
        self._try_load_embeddings(docs)

    def _try_load_embeddings(self, docs: list[list[str]]) -> None:
        """Best-effort local embeddings; silent fallback to TF-IDF + BM25."""
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            model = SentenceTransformer("all-MiniLM-L6-v2")
            texts = [p.text for p in self.passages]
            vecs = model.encode(texts, normalize_embeddings=True)
            try:
                import faiss  # type: ignore

                index = faiss.IndexFlatIP(vecs.shape[1])
                index.add(vecs.astype("float32"))
                self._embeddings = (model, index)
                self.backend = "tfidf+bm25+faiss (local sentence-transformers)"
            except ImportError:
                self._embeddings = (model, None)
                self.backend = "tfidf+bm25+sentence-transformers (local, no FAISS)"
        except Exception:
            self._embeddings = None  # not installed / no model — local fallback

    def _rank(self, scores: list[float]) -> list[int]:
        return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """Return up to top_k passages above threshold, RRF-fused.

        Returns an empty list when nothing matches above threshold — the
        caller must say "not found", never invent an answer.
        """
        if not self.passages:
            return []
        qt = tokenize(query)
        if not qt:
            return []
        qt_set = set(qt)
        # A real match must share at least 2 distinct query terms with the
        # passage (1 for a single-term query). One shared word — e.g. "base"
        # in "granular base" for a question about a moon base — is not a
        # match, and must return "not found", never a guessed answer.
        min_terms = min(2, len(qt_set))
        doc_tokens = [set(t) for t in self._tfidf.docs]
        tfidf_scores = self._tfidf.score(qt)
        bm25_scores = self._bm25.score(qt)
        rank_lists = [self._rank(tfidf_scores), self._rank(bm25_scores)]
        emb_scores = [0.0] * len(self.passages)
        if self._embeddings is not None:
            model, index = self._embeddings
            qv = model.encode([query], normalize_embeddings=True)
            if index is not None:
                sims, idxs = index.search(qv.astype("float32"), top_k)
                for sim, i in zip(sims[0], idxs[0]):
                    if i >= 0:
                        emb_scores[i] = float(sim)
                rank_lists.append(self._rank(emb_scores))
            else:
                import numpy as np  # local import: numpy is optional here

                vecs = model.encode(
                    [p.text for p in self.passages], normalize_embeddings=True
                )
                sims = (vecs @ qv[0]).tolist()
                emb_scores = sims
                rank_lists.append(self._rank(emb_scores))
        fused = _rrf(rank_lists)
        results = []
        # Sort by query-term coverage first, then RRF: the passage that
        # answers the question shares the most distinct query terms. This
        # stops short passages (e.g. a plan region) outranking the passage
        # that actually contains the answer, on length normalisation alone.
        for doc_idx, rrf in sorted(
            fused.items(),
            key=lambda kv: (
                -len(qt_set & doc_tokens[kv[0]]) / len(qt_set),
                -kv[1],
            ),
        ):
            matched = qt_set & doc_tokens[doc_idx]
            if len(matched) < min_terms:
                continue
            # Gate on real lexical evidence: a passage with no TF-IDF and no
            # BM25 support is not a match, however RRF ranks it.
            if tfidf_scores[doc_idx] <= 0 and bm25_scores[doc_idx] <= 0:
                continue
            combined = tfidf_scores[doc_idx] + bm25_scores[doc_idx]
            if combined < self.threshold:
                continue
            results.append(
                RetrievalResult(
                    passage=self.passages[doc_idx],
                    score=rrf,
                    tfidf_score=tfidf_scores[doc_idx],
                    bm25_score=bm25_scores[doc_idx],
                    embedding_score=emb_scores[doc_idx],
                )
            )
        return results[:top_k]

    def answer(self, query: str, top_k: int = 3) -> dict:
        """Cited answer, or an honest 'not found' when nothing matches."""
        hits = self.search(query, top_k=top_k)
        if not hits:
            return {
                "status": "not_found",
                "answer": "Not found — I could not find this in the plan or specs. "
                "Please check the sheet or rephrase the question.",
                "citations": [],
                "hits": [],
            }
        top = hits[0]
        return {
            "status": "found",
            "answer": top.passage.text,
            "citations": [h.passage.citation() for h in hits],
            "hits": [
                {
                    "doc_id": h.passage.doc_id,
                    "score": round(h.score, 4),
                    "text": h.passage.text,
                }
                for h in hits
            ],
        }


def build_plan_corpus(
    plans: list[dict], suppliers: Optional[list[dict]] = None
) -> list[Passage]:
    """Passages from synthetic plan JSONs (+ optional supplier docs)."""
    passages: list[Passage] = []
    for plan in plans:
        pid = plan["plan_id"]
        passages.append(
            Passage(
                doc_id=f"{pid}-overview",
                text=f"{plan['title']}, sheet {plan['sheet']}, scale {plan['scale']}, "
                f"floor area {plan['floor_area_m2']} square metres, {plan['rooms']} rooms, "
                f"{plan['fixtures']} fixtures, located in {plan['location']}.",
                source_type="plan_passage",
                page=plan["sheet"],
                plan_id=pid,
            )
        )
        for clause in plan.get("spec_clauses", []):
            passages.append(
                Passage(
                    doc_id=f"{pid}-{clause['clause_id']}",
                    # Title included: a clause belongs to its plan, and the
                    # title is the context a question will name.
                    text=f"{plan['title']}. {clause['text']}",
                    source_type="spec_clause",
                    page=plan["sheet"],
                    clause=clause["clause_id"],
                    plan_id=pid,
                )
            )
        for region in plan.get("regions", []):
            passages.append(
                Passage(
                    doc_id=f"{pid}-{region['region_id']}",
                    # No plan title here: region passages are short, and the
                    # title terms would let them outrank the passages that
                    # actually answer the question.
                    text=f"Plan region {region['label']} on sheet {plan['sheet']}, "
                    f"region {region['region_id']}.",
                    source_type="plan_passage",
                    page=plan["sheet"],
                    region=region["region_id"],
                    plan_id=pid,
                )
            )
    for sup in suppliers or []:
        mats = ", ".join(sup.get("materials", []))
        passages.append(
            Passage(
                doc_id=f"supplier-{sup['id']}",
                text=f"Supplier {sup['name']} in {sup['city']}, {sup['state']} supplies "
                f"{mats}. Lead time {sup['lead_time_days']} days. "
                f"Certifications: {', '.join(sup.get('certifications') or ['none'])}. "
                f"Contact source: {sup.get('contact_source')}.",
                source_type="supplier_doc",
                page="supplier directory",
            )
        )
    return passages


def load_plan_corpus(data_dir: str | Path) -> list[Passage]:
    """Load the synthetic plan + supplier corpus from data/."""
    root = Path(data_dir)
    plans = [
        json.loads(p.read_text())
        for p in sorted((root / "plans").glob("plan-*.json"))
    ]
    sup_file = root / "suppliers.json"
    suppliers = json.loads(sup_file.read_text())["suppliers"] if sup_file.exists() else []
    return build_plan_corpus(plans, suppliers)
