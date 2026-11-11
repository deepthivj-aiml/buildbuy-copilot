"""Wiring to the sibling AI modules — real entry points, honest fallbacks.

Wired 2026-11-11 (integration pass). Each module is imported behind
``try/except`` and ``MODULE_AVAILABILITY`` reports the real state, but the
imports below name the REAL entry points (checked against each module's
actual function/class names — never guessed):

- RAG:        ``app.rag.retrieval.HybridRetrieval`` (+ ``load_plan_corpus``)
- Takeoff:    ``app.takeoff.engine.compute_takeoff``
- Suppliers:  ``app.suppliers.search.search_suppliers``
- Twin:       ``app.twin.simulator.DigitalTwin`` (decision sim) +
              ``app.ranking.simulate_cost_and_quality`` (what-if fallback)
- Guardrails: ``app.guardrails.guardrails.Guardrails``
- Cache:      ``app.cache.semantic_cache.SemanticCache``
- Evals:      ``app.evals.eval_gen.generate_eval_pairs``
- LoRA:       ``app.lora.adapter.ToyLoRA``

Fallback policy (plan §2.2 / §2.4): a fallback NEVER invents data.
- RAG missing -> answer "not found" with ``grounded=False``.
- Takeoff missing -> materials come from the requirement items only.
- Twin missing -> :func:`app.ranking.simulate_cost_and_quality`.
- Guardrails missing -> deterministic checks in this module
  (price cap, qty > 0, PII redaction for logs) still run.
- Cache missing -> in-memory dict.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("buildbuy.integrations")

# ------------------------------------------------------------------ RAG
try:  # HybridRetrieval over the plan corpus in data/plans/
    from app.rag.retrieval import HybridRetrieval, load_plan_corpus  # type: ignore

    _RAG_IMPORT_OK = True
except Exception as exc:  # noqa: BLE001
    HybridRetrieval = None  # type: ignore
    load_plan_corpus = None  # type: ignore
    _RAG_IMPORT_OK = False
    logger.info("rag module not available yet (%s); using fallback", exc)

_rag_retriever = None
_rag_corpus_error: str | None = None


def _get_rag_retriever():
    """Lazily build the HybridRetrieval over the plan corpus (once)."""
    global _rag_retriever, _rag_corpus_error
    if _rag_retriever is not None or _rag_corpus_error is not None:
        return _rag_retriever
    if not _RAG_IMPORT_OK:
        return None
    try:
        from app.config import get_settings

        passages = load_plan_corpus(get_settings().data_dir)
        _rag_retriever = HybridRetrieval(passages)
    except Exception as exc:  # noqa: BLE001
        _rag_corpus_error = str(exc)
        logger.warning("rag corpus failed to load: %s", exc)
    return _rag_retriever


RAG_AVAILABLE = _RAG_IMPORT_OK and _get_rag_retriever() is not None


def rag_retrieve(question: str, plan_id: str | None = None, top_k: int = 3) -> list[dict]:
    """Hybrid retrieval; empty list when nothing matches (never a guess).

    Returns dicts with ``text`` / ``doc_id`` / ``clause`` / ``region`` /
    ``score`` — the shape ``app/api/routes.py`` reads for the ask endpoint.
    ``plan_id`` filters hits to that plan when given.
    """
    retriever = _get_rag_retriever()
    if retriever is None:
        return []
    try:
        hits = retriever.search(question, top_k=top_k * 2 if plan_id else top_k)
        out = []
        for hit in hits:
            passage = hit.passage
            if plan_id is not None and getattr(passage, "plan_id", None) != plan_id:
                continue
            citation = passage.citation()
            # Region is a dict (or None) — AskResponse.citation_image_region
            # and QALog.citation_image_region are dict-typed; an empty
            # string here used to crash ask with a validation error.
            region = None
            if passage.region:
                region = {"region_id": passage.region,
                          "sheet": passage.page,
                          "doc_id": passage.doc_id}
            out.append({
                "text": passage.text,
                "passage": passage.text,
                "doc_id": passage.doc_id,
                "clause": citation.get("clause", ""),
                "region": region,
                "score": round(hit.score, 4),
            })
            if len(out) >= top_k:
                break
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag retrieval failed: %s", exc)
        return []


# -------------------------------------------------------------- takeoff
try:  # compute_takeoff(plan_dict) -> TakeoffResult
    from app.takeoff.engine import compute_takeoff as _compute_takeoff  # type: ignore

    TAKEOFF_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    _compute_takeoff = None
    TAKEOFF_AVAILABLE = False
    logger.info("takeoff module not available yet (%s); using fallback", exc)


def _takeoff_lines_from_result(result) -> list[dict]:
    return [
        {
            "material": line.material,
            "quantity": line.quantity,
            "unit": line.unit,
            "method": line.method,
            "confidence": line.confidence,
            "flagged": line.flagged,
            "estimate_label": line.estimate_label,
        }
        for line in result.lines
    ]


def _load_plan_json(file_name: str | None) -> dict | None:
    """Load a plan JSON from data/plans/ by file name (demo plans only)."""
    if not file_name:
        return None
    try:
        import json
        from pathlib import Path

        from app.config import get_settings

        candidate = Path(file_name)
        path = (
            candidate
            if candidate.is_absolute() and candidate.exists()
            else get_settings().data_dir / "plans" / Path(file_name).name
        )
        if not path.exists() or path.suffix.lower() != ".json":
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not load plan json %s: %s", file_name, exc)
        return None


def run_takeoff(requirement: dict, plan: dict | None = None) -> list[dict]:
    """Materials estimate. Real takeoff when plan data is available.

    ``plan`` may be a full plan dict (floor_area_m2, spec_clauses, ...)
    or ``{"file_name": ...}`` pointing at a plan JSON in data/plans/.
    Fallback: requirement items, labelled estimate.
    """
    if _compute_takeoff is not None and plan:
        plan_data = None
        if "floor_area_m2" in plan or "spec_clauses" in plan:
            plan_data = plan
        else:
            plan_data = _load_plan_json(plan.get("file_name"))
        if plan_data is not None:
            try:
                return _takeoff_lines_from_result(_compute_takeoff(plan_data))
            except Exception as exc:  # noqa: BLE001
                logger.warning("takeoff failed: %s", exc)
    return [
        {
            "material": item.get("item", "item"),
            "quantity": item.get("quantity", 0),
            "unit": item.get("unit", ""),
            "method": "requirement list (no plan takeoff module yet)",
            "confidence": None,
            "flagged": False,
            "estimate_label": True,
        }
        for item in requirement.get("items", [])
    ]


# ------------------------------------------------------------- suppliers
try:  # search_suppliers(suppliers, material, qty, buyer_lat, buyer_lng, ...)
    from app.suppliers.search import search_suppliers as _search_suppliers  # type: ignore

    SUPPLIERS_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    _search_suppliers = None
    SUPPLIERS_AVAILABLE = False
    logger.info("suppliers module not available yet (%s); using DB fallback", exc)


def search_suppliers(
    suppliers: list[dict],
    material: str,
    quantity: float,
    buyer_lat: float | None = None,
    buyer_lng: float | None = None,
    **kwargs: Any,
) -> dict:
    """Supplier search (real module). Buyer location is optional/manual.

    ``buyer_lat``/``buyer_lng`` come only from a delivery location the
    user typed themselves — blank by default, never auto-detected.
    Without them, transport is excluded ("excl. transport").
    Falls back to the raw supplier list when the module is unavailable.
    """
    if _search_suppliers is not None:
        try:
            return _search_suppliers(
                suppliers, material, quantity, buyer_lat, buyer_lng, **kwargs
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("supplier search failed: %s", exc)
    return {"ranked": [], "cheapest": None, "highest_quality": None,
            "excluded": [], "fallback_suppliers": suppliers}


# ----------------------------------------------------------------- twin
try:  # DigitalTwin(buyer_lat, buyer_lng).simulate(supplier, material, qty)
    from app.twin.simulator import DigitalTwin as _DigitalTwin  # type: ignore

    TWIN_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    _DigitalTwin = None
    TWIN_AVAILABLE = False
    logger.info("twin module not available yet (%s); using ranking fallback", exc)


def twin_simulate(**kwargs: Any) -> dict:
    """Twin simulation, two call shapes (both honest, no invented data).

    Decision shape — ``supplier=``, ``material=``, ``quantity=`` (plus
    optional ``buyer_lat``/``buyer_lng`` from a user-typed delivery
    location, ``transport_rate_per_km``): runs the real
    :class:`app.twin.simulator.DigitalTwin` and returns its dict.
    What-if shape — ``landed_cost=``, ``quality_score=``, ... (the
    shape ``app/api/routes.py`` /simulate uses): runs
    :func:`app.ranking.simulate_cost_and_quality`.
    """
    if "supplier" in kwargs and "material" in kwargs and _DigitalTwin is not None:
        try:
            twin = _DigitalTwin(
                kwargs.pop("buyer_lat", None), kwargs.pop("buyer_lng", None)
            )
            sim = twin.simulate(**kwargs)
            return sim.as_dict()
        except Exception as exc:  # noqa: BLE001
            logger.warning("twin simulate failed: %s", exc)
            if "landed_cost" not in kwargs:
                raise
    from app.ranking import simulate_cost_and_quality

    return simulate_cost_and_quality(**kwargs)


# ------------------------------------------------------------- guardrails
try:  # Guardrails().check(text, max_price=, price=, share_contact=, ...)
    from app.guardrails.guardrails import Guardrails as _Guardrails  # type: ignore

    GUARDRAILS_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    _Guardrails = None
    GUARDRAILS_AVAILABLE = False
    logger.info("guardrails module not available yet (%s); using local checks", exc)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?1?[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{4}")


def guardrail_check(
    *,
    text: str,
    max_price: float | None,
    price: float | None,
    share_contact: bool,
) -> dict:
    """Guardrails via the real module when available (always deterministic).

    Returns ``{"allowed": bool, "reason": str}``. A "redact" outcome from
    the module is allowed (text was cleaned); a "block" is not.
    Local checks run when the module is missing.
    """
    if _Guardrails is not None:
        try:
            result = _Guardrails().check(
                text, max_price=max_price, price=price,
                share_contact=share_contact,
            )
            return {"allowed": bool(result.passed), "reason": result.reason}
        except Exception as exc:  # noqa: BLE001
            logger.warning("guardrails module failed: %s", exc)
    if price is not None and price <= 0:
        return {"allowed": False, "reason": "price must be positive"}
    if max_price is not None and price is not None and price > max_price:
        return {"allowed": False, "reason": f"price {price} exceeds max price {max_price}"}
    if not share_contact and (_EMAIL_RE.search(text) or _PHONE_RE.search(text)):
        return {"allowed": False, "reason": "contact details in outbound text but contact sharing is OFF"}
    return {"allowed": True, "reason": ""}


def redact_contact(text: str) -> str:
    """Strip emails/phones from outbound text when sharing is OFF."""
    if _Guardrails is not None:
        try:
            redacted, _ = _Guardrails().redact_pii(text)
            return redacted
        except Exception as exc:  # noqa: BLE001
            logger.warning("guardrails redact failed: %s", exc)
    text = _EMAIL_RE.sub("[contact not shared]", text)
    return _PHONE_RE.sub("[contact not shared]", text)


# ----------------------------------------------------------------- cache
try:  # SemanticCache().get(plan_id, question) / .put(plan_id, q, answer)
    from app.cache.semantic_cache import SemanticCache as _SemanticCache  # type: ignore

    _CACHE_IMPORT_OK = True
except Exception as exc:  # noqa: BLE001
    _SemanticCache = None
    _CACHE_IMPORT_OK = False
    logger.info("cache module not available yet (%s); using in-memory fallback", exc)

_memory_cache: dict[str, Any] = {}
_semantic_cache = None
if _CACHE_IMPORT_OK:
    try:
        _semantic_cache = _SemanticCache()
    except Exception as exc:  # noqa: BLE001
        _semantic_cache = None
        logger.warning("semantic cache init failed: %s", exc)

CACHE_AVAILABLE = _semantic_cache is not None


def cache_get(key: str) -> Any | None:
    """Cached answer for a question key (semantic cache, plan 'default')."""
    if _semantic_cache is not None:
        try:
            hit = _semantic_cache.get("default", key)
            if hit is not None:
                return hit.get("answer")
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache get failed: %s", exc)
    return _memory_cache.get(key)


def cache_set(key: str, value: Any) -> None:
    if _semantic_cache is not None:
        try:
            _semantic_cache.put("default", key, str(value))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache put failed: %s", exc)
    _memory_cache[key] = value


# ----------------------------------------------------------------- evals
try:  # generate_eval_pairs(plans, suppliers) -> list[dict]
    from app.evals.eval_gen import generate_eval_pairs as _gen_eval_pairs  # type: ignore

    EVALS_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    _gen_eval_pairs = None
    EVALS_AVAILABLE = False
    logger.info("evals module not available yet (%s)", exc)


def generate_eval_pairs(plans: list[dict], suppliers: list[dict]) -> list[dict]:
    """Eval-set generation via the real module (empty list if missing)."""
    if _gen_eval_pairs is None:
        return []
    try:
        return list(_gen_eval_pairs(plans, suppliers))
    except Exception as exc:  # noqa: BLE001
        logger.warning("eval generation failed: %s", exc)
        return []


# ------------------------------------------------------------------ lora
try:  # ToyLoRA().predict(text) -> (intent, probs); intents in INTENTS
    from app.lora.adapter import ToyLoRA as _ToyLoRA  # type: ignore

    LORA_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    _ToyLoRA = None
    LORA_AVAILABLE = False
    logger.info("lora module not available yet (%s)", exc)

_lora_adapter = None


def _get_lora_adapter():
    """Lazily load the saved toy adapter (or train a fresh one)."""
    global _lora_adapter
    if _lora_adapter is not None:
        return _lora_adapter
    if _ToyLoRA is None:
        return None
    try:
        from pathlib import Path

        from app.config import get_settings

        saved = get_settings().data_dir / "lora_toy_adapter.npz"
        _lora_adapter = (
            _ToyLoRA.load(saved) if saved.exists() else _ToyLoRA()
        )
        if not saved.exists():
            _lora_adapter.train()
    except Exception as exc:  # noqa: BLE001 — numpy missing, or load failed
        logger.warning("lora adapter unavailable: %s", exc)
        _lora_adapter = None
    return _lora_adapter


def classify_intent(text: str) -> str:
    """Intent classification; deterministic keyword fallback (toy).

    Real path: ToyLoRA intents — plan_qa | takeoff | supplier_search |
    buyer. Fallback uses the same labels so callers never see a
    different vocabulary.
    """
    adapter = _get_lora_adapter()
    if adapter is not None:
        try:
            intent, _probs = adapter.predict(text)
            return str(intent)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lora classify failed: %s", exc)
    lowered = text.lower()
    if any(w in lowered for w in ("plan", "drawing", "sheet", "beam", "fixture", "grade", "clause")):
        return "plan_qa"
    if any(w in lowered for w in ("how much", "how many", "estimate", "quantities", "need")):
        return "takeoff"
    if any(w in lowered for w in ("supplier", "quote", "buy", "order", "price", "cheapest", "near")):
        return "supplier_search"
    if any(w in lowered for w in ("email", "negotiate", "approve", "confirm")):
        return "buyer"
    return "plan_qa"


MODULE_AVAILABILITY = {
    "rag": RAG_AVAILABLE,
    "takeoff": TAKEOFF_AVAILABLE,
    "suppliers": SUPPLIERS_AVAILABLE,
    "twin": TWIN_AVAILABLE,
    "guardrails": GUARDRAILS_AVAILABLE,
    "cache": CACHE_AVAILABLE,
    "evals": EVALS_AVAILABLE,
    "lora": LORA_AVAILABLE,
}

__all__ = [
    "MODULE_AVAILABILITY",
    "RAG_AVAILABLE",
    "TAKEOFF_AVAILABLE",
    "SUPPLIERS_AVAILABLE",
    "TWIN_AVAILABLE",
    "GUARDRAILS_AVAILABLE",
    "CACHE_AVAILABLE",
    "EVALS_AVAILABLE",
    "LORA_AVAILABLE",
    "rag_retrieve",
    "run_takeoff",
    "search_suppliers",
    "twin_simulate",
    "guardrail_check",
    "redact_contact",
    "cache_get",
    "cache_set",
    "generate_eval_pairs",
    "classify_intent",
]
