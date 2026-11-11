"""Semantic cache — reel skill #3.

In-memory semantic cache with an optional Redis backend (import behind
try/except; REDIS_URL env). Matching is TF-IDF cosine over normalised
question text plus a synonym map — repeat plan questions and repeat supplier
questions are served with no LLM call, and the dollars saved are counted.

Plan-aware keys: the cache key includes plan_id, so a question about
plan-001 can never return an answer cached for plan-002 (no cross-plan
false hits). A question with no plan context uses plan_id "general".
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

# Cost avoided per cache hit — the local TF-IDF + rules fallback costs $0 in
# API spend, so the saving is the LLM call that did NOT happen (documented
# planning figure, not a measured bill).
COST_PER_LLM_CALL_USD = 0.02
SIMILARITY_THRESHOLD = 0.75

SYNONYMS = {
    "concrete": {"cement", "slab"},
    "steel": {"rebar", "reinforcement"},
    "bricks": {"brick", "masonry"},
    "tiles": {"tile", "tiling"},
    "timber": {"wood", "lumber", "joist"},
    "fixtures": {"fixture", "fittings"},
    "grade": {"rating", "spec"},
    "thickness": {"thick", "depth"},
}

# Explicit canonical map (synonym -> canonical term). Built by hand, not
# derived from SYNONYMS, so no term can map to two different canonicals.
CANON = {
    "cement": "concrete",
    "slab": "concrete",
    "rebar": "steel",
    "reinforcement": "steel",
    "brick": "bricks",
    "masonry": "bricks",
    "tile": "tiles",
    "tiling": "tiles",
    "wood": "timber",
    "lumber": "timber",
    "joist": "timber",
    "fixture": "fixtures",
    "fittings": "fixtures",
    "rating": "grade",
    "spec": "grade",
    "thick": "thickness",
    "depth": "thickness",
}

_STOP = {
    "a", "an", "the", "is", "are", "what", "which", "how", "many", "much",
    "do", "does", "in", "on", "of", "for", "to", "and", "or", "with", "by",
    "at", "from", "it", "this", "that", "please", "tell", "me", "show",
}


def normalize(text: str) -> str:
    """Lowercase, expand synonyms to a canonical token, drop stopwords."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for tok in tokens:
        if tok in _STOP:
            continue
        out.append(CANON.get(tok, tok))
    return " ".join(out)


def _tfidf_cosine(a: Counter, b: Counter, idf: dict[str, float]) -> float:
    def vec(c: Counter) -> dict[str, float]:
        return {t: (n / sum(c.values())) * idf.get(t, 1.0) for t, n in c.items()}

    va, vb = vec(a), vec(b)
    dot = sum(va[t] * vb.get(t, 0.0) for t in va)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    """Plan-aware semantic cache. Redis optional; in-memory is the default."""

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD):
        self.threshold = threshold
        self.hits = 0
        self.misses = 0
        self.savings_usd = 0.0
        self._store: dict[str, list[dict]] = {}  # plan_id -> entries
        self._redis = None
        self.backend = "in-memory"
        self._try_redis()

    def _try_redis(self) -> None:
        url = os.environ.get("REDIS_URL")
        if not url:
            return
        try:
            import redis  # type: ignore

            client = redis.Redis.from_url(url, socket_connect_timeout=2)
            client.ping()
            self._redis = client
            self.backend = f"redis ({url.split('@')[-1]})"
        except Exception:
            self._redis = None  # Redis unavailable — in-memory fallback

    def _idf(self, plan_id: str) -> dict[str, float]:
        entries = self._store.get(plan_id, [])
        n = len(entries)
        df: Counter = Counter()
        for e in entries:
            df.update(set(e["tokens"]))
        return {t: math.log((n + 1) / (d + 1)) + 1.0 for t, d in df.items()}

    def put(self, plan_id: str, question: str, answer: str) -> None:
        entry = {
            "question": question,
            "normalized": normalize(question),
            "tokens": Counter(normalize(question).split()),
            "answer": answer,
        }
        self._store.setdefault(plan_id, []).append(entry)

    def get(self, plan_id: str, question: str) -> dict | None:
        """Return {"answer": ..., "similarity": ...} on a hit, else None.

        Only entries stored under the SAME plan_id are ever considered —
        plan-aware keys prevent cross-plan false hits.
        """
        entries = self._store.get(plan_id, [])
        if not entries:
            self.misses += 1
            return None
        q_tokens = Counter(normalize(question).split())
        idf = self._idf(plan_id)
        best, best_sim = None, 0.0
        for e in entries:
            sim = _tfidf_cosine(q_tokens, e["tokens"], idf)
            if sim > best_sim:
                best, best_sim = e, sim
        if best is not None and best_sim >= self.threshold:
            self.hits += 1
            self.savings_usd = round(self.savings_usd + COST_PER_LLM_CALL_USD, 4)
            return {"answer": best["answer"], "similarity": round(best_sim, 3),
                    "matched_question": best["question"]}
        self.misses += 1
        return None

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 3) if total else 0.0

    def stats(self) -> dict:
        return {
            "backend": self.backend,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hit_rate,
            "savings_usd": round(self.savings_usd, 4),
            "entries": sum(len(v) for v in self._store.values()),
        }
