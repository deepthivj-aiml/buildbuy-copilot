# BuildBuy Copilot — Module Map

Every module is a separate section with a clear boundary, its own public
interface (`__init__.py` + `__all__`), its own tests
(`tests/test_<module>.py`), and can be rebuilt / tested / replaced alone
without touching the others. Modules talk to each other only through the
interfaces below — never through private internals.

- **Contracts:** `app/schemas.py` (Pydantic API/agent contracts),
  `app/config.py` (env-only settings), `app/db/` (SQLAlchemy models —
  **unused legacy, future storage only**; the live flow never imports
  it), `app/live.py` (stdlib-only live contact + user-email flow, no
  DB imports), `app/records/excel.py` (openpyxl shortlist export).
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
| 3 | Takeoff engine | `app/takeoff/engine.py` | Deterministic materials estimation from plan data; every line labelled "estimate, not a surveyed quantity", flagged when inputs are missing. Typed requirement items apply on top of a plan takeoff (`apply_requirement_to_result`, `takeoff_line_from_requirement`): matching line updated with the old plan value kept in the method, new material appended, no-quantity item skipped — never an invented quantity | `.venv/bin/python -m pytest tests/test_takeoff.py -v` |
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
| 13 | Observability / Accuracy | `app/observability.py` (+ `app/api/routes.py` `GET /accuracy`, `POST /accuracy/worst-answers/{id}/action`; `app/schemas.py` `AccuracyMetricOut` / `AccuracyDashboardOut`) | `METRIC_DEFS` (8 separate metrics, never blended) · `compute_daily_metrics` (nightly rollup of `metrics_daily` — now also retrieval top-1, guardrail block rate, ranking top-1, cache hit, cost per job from eval runs / orders / events; takeoff MAPE stays NULL until corrected-vs-estimate pairs are recorded) · `build_accuracy_dashboard(db, days=30)` (metrics + headline + trends + per-module + alerts; the payload also carries Worst Answers + Eval Run History + PII-free raw events for internal use only — the UI does not render them; every count windowed to the requested days) · `record_worst_answer_action` (internal-only: add to eval set, deduped by `qa_log_id`, audited; repeat → 409). Measured only — NULL when there is not enough data, never invented | `.venv/bin/python -m pytest tests/test_observability.py tests/test_backend.py -k accuracy -v` |
| 14 | Records / summaries | `app/records/export.py` | Requirement → invoice audit trail as CSV / JSON / summary (PDF when reportlab is installed, else .txt). Invoices only from supplier-supplied data | `.venv/bin/python -m pytest tests/test_records.py -v` |
| 14b | Live-data-only contact + Excel | `app/live.py` (stdlib only, no DB imports), `app/records/excel.py` | **Live flow (2026-11-10):** `contact_supplier` / `contact_suppliers_bulk` — approval-gated supplier contact, user summary email (quotation + contacted supplier details) to deepthiag26@gmail.com, idempotent in-session; `supplier_official_email` (None when not held — never invented); `shortlist_to_excel` — the ranked shortlist as a real `.xlsx` (22 columns). No storage anywhere in this module | `.venv/bin/python -m pytest tests/test_live.py -v` |
| 15 | Frontend | `frontend/app.py` (7 screens), `frontend/helpers.py` (pure logic), `frontend/demo_data.py` (synthetic data), `frontend/accuracy.py` (pure Accuracy helpers), `frontend/theme.py` (pure theme: palette, CSS, status chips, journey stepper, hero) | Streamlit dashboard: Start (chat-first input) → Plan & Materials → Suppliers & Twin → Buyer Agent → My Orders → Accuracy → Settings. Typed requirements are parsed deterministically (`parse_requirement`: item, quantity, unit, location, deadline, budget; optional `llm_parser` hook with fallback) and applied to the takeoff (`apply_requirement_to_takeoff`). Buyer Agent shows a per-supplier email preview (contact details, channel/from/to/subject, full editable body, Save/Reset/Send, blocked when the email is not held; `build_quote_email` is byte-for-byte the backend `draft_quote`). Theme: warm brown (`.streamlit/config.toml` + `theme.py` CSS; primary `#7C4A21`, background `#FBF6EF`), documented design system (one typography scale, one card, one primary per section, `$`-formatted currency columns, WCAG AA contrast), compact gradient hero, 9-step journey stepper rendered after the nav radio so its current step matches the selected tab, colour-coded status chips (text labels always kept). Accuracy tab (tab 6) is the Observability Dashboard only: 8-metric table (formula/source/n/target/status), 4 headline cards, 2 Altair trend charts with alert thresholds as dashed rules (temporal date axis, chronological, missing day = gap, never 0%; line_chart fallback), per-module table (metric/value/n, no worst column). Evaluations are internal only — no Worst Answers, Eval Run History or drill-down in the UI, no evaluation actions; live mode fetches `GET /accuracy` (LIVE badge), demo mode shows labelled synthetic data, empty state says "no data yet". Pure helpers (ranking, transport, twin, parsing, accuracy, theme) are tested without Streamlit; all 7 tabs are render-checked with Streamlit AppTest when Streamlit is installed | `.venv/bin/python -m pytest tests/test_frontend.py tests/test_theme.py -v` (helpers + AppTest); `streamlit run frontend/app.py` for the UI |

Shared (not business modules): `app/main.py` (FastAPI app —
**storage OFF by default; `/health` reports `"storage": "none —
live, session-only"`**), `app/api/` (HTTP routes only — the stored
endpoints are legacy; the live endpoint is `POST /live/contact`),
`app/config.py`, `app/schemas.py`, `app/db/` (**unused legacy**),
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
  still live in `frontend/app.py` (~1,400 lines) behind one `if/elif` chain.
  The pure logic is already split out (`helpers.py`, `demo_data.py`,
  `accuracy.py`, `theme.py`) and tested; moving each screen into
  `frontend/screens/tab_<n>_<name>.py` is the remaining step.
- **VLM is a local fallback, not a real model:** `app/vlm/` reads
  structured plan data deterministically. Wiring a real hosted VLM
  behind `VisionReader.read_plan` is a follow-up (needs a provider key
  and a decision on cost per call).
