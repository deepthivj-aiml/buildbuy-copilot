# BuildBuy Copilot — Module Map

Every module is a separate section with a clear boundary, its own public
interface (`__init__.py` + `__all__`), its own tests
(`tests/test_<module>.py`), and can be rebuilt / tested / replaced alone
without touching the others. Modules talk to each other only through the
interfaces below — never through private internals.

- **Contracts:** `app/schemas.py` (Pydantic API/agent contracts),
  `app/config.py` (env-only settings), `app/db/` (SQLAlchemy models).
- **Wiring:** `app/integrations.py` is the ONE module allowed to import
  every AI module; it exposes `MODULE_AVAILABILITY` and honest
  try/except fallbacks. The API layer (`app/api/`) imports it — AI
  modules never import the API.
- **Boundary test:** `tests/test_modularity.py` reads the source and
  fails the build if a module imports outside its allowed map, if a
  module's `__init__` stops exporting its interface, if any auto-location
  code appears, or if torch/faiss becomes a hard import.

## Map

| # | Module | Files | What it does | Rebuild / test it alone |
|---|---|---|---|---|
| 1 | RAG / retrieval | `app/rag/retrieval.py` | Hybrid search (TF-IDF + BM25 + optional embeddings, RRF-fused) over plan passages; cited answer or honest "not found" | `.venv/bin/python -m pytest tests/test_rag.py -v` |
| 2 | VLM / plan parsing | `app/vlm/plan_vision.py` | Reads a plan's structured data: title block (scale/sheet), labelled regions, spec clauses. Local fallback — no model call; a real VLM plugs in behind `VisionReader.read_plan` | `.venv/bin/python -m pytest tests/test_vlm.py -v` |
| 3 | Takeoff engine | `app/takeoff/engine.py` | Deterministic materials estimation from plan data; every line labelled "estimate, not a surveyed quantity", flagged when inputs are missing | `.venv/bin/python -m pytest tests/test_takeoff.py -v` |
| 4 | Supplier search | `app/suppliers/search.py`, `directory.py`, `location.py` | Supplier directory, quality evidence, MOQ/lead filters, and the **canonical** best-value ranking. `location.py` resolves a user-typed delivery location offline (blank by default — never auto-detected) | `.venv/bin/python -m pytest tests/test_suppliers.py -v` |
| 5 | Digital Twin | `app/twin/simulator.py` | Per-decision simulation: total landed cost breakdown, delivery date, cost + quality risk, what-if (price/date/qty) with what breaks | `.venv/bin/python -m pytest tests/test_twin.py -v` |
| 6 | Ranking (cost + quality + landed cost) | `app/ranking.py` | `rank_shortlist` + `simulate_cost_and_quality`. Imports the canonical formula from module 4 — no second formula. Total landed cost = goods + transport + taxes/fees; transport line is not scaled by the price what-if | `.venv/bin/python -m pytest tests/test_ranking.py -v` |
| 7 | Buyer Agent / orchestrator | `app/agents/graph.py` | LangGraph Planner → Finder → Buyer → Negotiator → **human approval gate** → Order → Chaser → InvoiceTracker; deterministic local runner when LangGraph is absent. Buyer draft identifies the agent as the customer's buying agent and enquires about part + quantity; contact sharing OFF anonymises the customer | `.venv/bin/python -m pytest tests/test_backend.py -v` (full-flow test) |
| 7b | Supplier-question escalation | `app/agents/escalation.py` | Classifies supplier questions: answerable from the requirement → answered from stated values; unanswerable → NEEDS_CUSTOMER, customer emailed, no supplier reply until the customer answers in their words | `.venv/bin/python -m pytest tests/test_escalation.py -v` |
| 8 | Email service | `app/email/service.py` | MockSMTP by default (writes `data/mock_mail/`, never sends real mail); SMTP only when configured. Transactional outbox, deterministic idempotency keys. `draft_quote` / `with_agent_identity` / `strip_customer_identity` enforce the agent-identity + contact-sharing rules | `.venv/bin/python -m pytest tests/test_email.py -v` |
| 9 | Guardrails | `app/guardrails/guardrails.py` | Deterministic checks before cache/email: price cap, deadline, blocklist, never-pay, PII redaction, contact-sharing toggle | `.venv/bin/python -m pytest tests/test_guardrails.py -v` |
| 10 | Semantic cache | `app/cache/semantic_cache.py` | Plan-aware repeat-question cache (TF-IDF cosine + synonyms); Redis optional, in-memory default | `.venv/bin/python -m pytest tests/test_cache.py -v` |
| 11 | Evals | `app/evals/eval_gen.py` | Generates grounded Q&A eval pairs, dedupes, quality-checks, exports JSONL/CSV; runner measures retrieval top-1/top-3, groundedness, guardrail block rate | `.venv/bin/python -m pytest tests/test_evals.py -v` |
| 12 | LoRA | `app/lora/adapter.py` | Toy rank-2 LoRA intent adapter (numpy-only): plan_qa / takeoff / supplier_search / buyer. Real PEFT path documented in the file, not run | `.venv/bin/python -m pytest tests/test_lora.py -v` |
| 13 | Observability / Accuracy | `app/observability.py` | Nightly rollup of `metrics_daily` from raw events (groundedness, thumbs-up, cache hit rate, latency). Measured only — NULL when there is not enough data, never invented | `.venv/bin/python -m pytest tests/test_observability.py -v` |
| 14 | Records / summaries | `app/records/export.py` | Requirement → invoice audit trail as CSV / JSON / summary (PDF when reportlab is installed, else .txt). Invoices only from supplier-supplied data | `.venv/bin/python -m pytest tests/test_records.py -v` |
| 15 | Frontend | `frontend/app.py` (7 screens), `frontend/helpers.py` (pure logic), `frontend/demo_data.py` (synthetic data) | Streamlit dashboard: Start (chat-first input) → Plan & Materials → Suppliers & Twin → Buyer Agent → My Orders → Accuracy → Settings. Pure helpers (ranking, transport, twin, parsing) are tested without Streamlit | `.venv/bin/python -m pytest tests/test_frontend.py -v` (helpers); `streamlit run frontend/app.py` for the UI |

Shared (not business modules): `app/main.py` (FastAPI app), `app/api/`
(HTTP routes only), `app/config.py`, `app/schemas.py`, `app/db/`,
`app/integrations.py` (wiring), `app/logging_setup.py`.

## How to rebuild one module alone

1. Edit only that module's file(s) and its `__init__.py` exports.
2. Run its test file from the table above — it must pass on its own
   (each file is self-contained: `pytest tests/test_<module>.py -v`).
3. Run the boundary test: `pytest tests/test_modularity.py -v`.
4. Run the full suite once before committing: `pytest tests/ -v`.
5. Docker: rebuild one service only —
   `docker compose up --build api` (backend + all API modules) or
   `docker compose up --build frontend` (Streamlit). There is one
   container per deployable (api / frontend / db / redis), not one per
   Python module — module separation is at code level, services at
   deploy level.

## What is NOT split yet (follow-up)

- **Frontend screens as a `screens/` package:** the 7 Streamlit screens
  still live in `frontend/app.py` (960 lines) behind one `if/elif` chain.
  The pure logic is already split out (`helpers.py`, `demo_data.py`) and
  tested; moving each screen into `frontend/screens/tab_<n>_<name>.py`
  is the remaining step. It was not done in this pass because Streamlit
  is not installed in this VM, so a screen split could not be
  smoke-tested here — it needs a machine with Streamlit + AppTest.
- **VLM is a local fallback, not a real model:** `app/vlm/` reads
  structured plan data deterministically. Wiring a real hosted VLM
  behind `VisionReader.read_plan` is a follow-up (needs a provider key
  and a decision on cost per call).
