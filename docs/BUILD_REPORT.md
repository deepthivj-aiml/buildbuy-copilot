# BuildBuy Copilot — Build Report (integration + test pass)

**Date:** 2026-11-11 · **Scope:** integrate the three finished streams
(backend, AI modules, frontend/docs), reconcile ranking, wire backend
integrations, add optional transport / total landed cost, make the build
modular, verify with measured tests + a live smoke test.
**Not done here:** no GitHub push, no deploy, no real emails (see §7).

> Note on milestones M0–M7: the repo has no M0–M7 definition file, so
> the mapping in §2 follows the plan's own structure
> (`docs/ARCHITECTURE.md` §§1–11 + the README's 7 tabs + the 6 reel
> skills). If the parent's plan numbers them differently, the file
> list in §1 is the ground truth.

## 1. Files tree (top 2 levels)

```
.
├── .env.example            # names only, no values
├── .github/workflows/      # CI: pytest on push/PR
├── .gitignore              # .env, *.db, *.sqlite*, .venv, __pycache__
├── Dockerfile{,.api,.frontend}
├── docker-compose.yml      # services: api, frontend, db, redis
├── LICENSE
├── README.md
├── requirements.txt        # + numpy==2.5.4 (LoRA toy + cache; added this pass)
├── app/
│   ├── main.py  config.py  schemas.py  ranking.py  integrations.py
│   ├── observability.py  logging_setup.py
│   ├── agents/  api/  cache/  db/  email/  evals/  guardrails/
│   ├── lora/  rag/  records/  suppliers/  takeoff/  twin/  vlm/   (new)
├── data/                   # suppliers.json, plans/, evals/, lora_toy_adapter.npz
│                           # (buildbuy.db, checkpoints.sqlite, mock_mail/ are
│                           #  runtime artefacts, git-ignored)
├── docs/                   # ARCHITECTURE.md, DEPLOY.md, FREE_MODELS.md,
│                           # MODULES.md (new), UAT.md, BUILD_REPORT.md (this file)
├── frontend/
│   ├── app.py              # 7 Streamlit screens (960 lines)
│   ├── helpers.py          # pure logic, no Streamlit (new)
│   └── demo_data.py        # synthetic demo data (new)
└── tests/
    ├── test_backend.py     # API integration suite (9)
    ├── test_rag.py  test_vlm.py  test_takeoff.py  test_suppliers.py
    ├── test_twin.py  test_ranking.py  test_cache.py  test_evals.py
    ├── test_lora.py  test_guardrails.py  test_email.py
    ├── test_observability.py  test_records.py  test_frontend.py
    ├── test_modularity.py    # module-boundary checks (3)
    └── self_test.py          # end-to-end demo runner (exit 0)
```

## 2. What was built, per milestone

| Milestone | What exists |
|---|---|
| M0 — Setup | `.venv` (Python 3.12, pytest 8.3.4, FastAPI, uvicorn, LangGraph), `requirements.txt`, `.env.example` (names only), `.gitignore`, `docker-compose.yml` (api/frontend/db/redis), CI workflow. numpy installed this pass (LoRA toy needs it; torch/faiss stay optional and uninstalled). |
| M1 — Backend core | FastAPI app (`app/main.py`, `/health`), Pydantic contracts (`app/schemas.py`), SQLAlchemy models + session (`app/db/`), auth-lite (header identity, demo fallback), structured JSON logging + request_id, `app/config.py` (env-only settings). |
| M2 — RAG + VLM + Takeoff | `app/rag/` (HybridRetrieval: TF-IDF + BM25 + optional embeddings, RRF; cited answer or honest "not found"), `app/vlm/` (**new this pass**: deterministic plan reader — title block/scale, labelled regions, spec clauses; a real VLM plugs in behind `VisionReader.read_plan`), `app/takeoff/` (deterministic materials estimate, every line labelled "estimate, not a surveyed quantity"). |
| M3 — Suppliers + Twin + Ranking | `app/suppliers/` (directory, evidence-only quality, MOQ/lead filters, **canonical** best-value formula, manual delivery location), `app/twin/` (DigitalTwin: landed cost, delivery date, cost + quality risk, what-if), `app/ranking.py` (rank_shortlist + twin what-if; imports the canonical formula). **Total landed cost** (this pass): goods + transport + taxes/fees with a per-supplier breakdown; transport is optional/manual (see §4). |
| M4 — Buyer Agent + Email | `app/agents/` (LangGraph Planner → Finder → Buyer → Negotiator → **human approval gate** → Order → Chaser → InvoiceTracker; deterministic local runner without LangGraph), `app/email/` (MockSMTP default — writes `data/mock_mail/`, never sends real mail; transactional outbox, deterministic idempotency keys). |
| M5 — Guardrails + Cache + Evals + LoRA | `app/guardrails/` (price cap, deadline, blocklist, never-pay, PII redaction, contact toggle), `app/cache/` (plan-aware semantic cache, Redis optional), `app/evals/` (73-pair generated eval set; runner measures retrieval top-1/top-3, groundedness, guardrail block rate), `app/lora/` (toy rank-2 intent adapter; train accuracy 1.0 on 12 synthetic examples). |
| M6 — Observability / Accuracy | `app/observability.py` (`metrics_daily` rollup — §13: now also retrieval top-1, guardrail block rate, ranking top-1, cost per job from eval runs / orders / events; takeoff MAPE stays NULL until corrected-vs-estimate pairs exist) + `GET /accuracy` + Worst Answers actions (internal-only since §20 — removed from the Accuracy tab UI) + full Accuracy tab in the UI (`frontend/accuracy.py`, `frontend/demo_data.py`). Measured only, NULL when no data. Fixed this pass: `compute_daily_metrics` returned detached ORM rows (DetachedInstanceError) — now flush → expunge → commit. |
| M7 — Frontend | Streamlit, 7 tabs, chat-first Start (plan upload OR typed/photographed requirement in chat, then quantity + optional location + deadline + budget as follow-ups). Split this pass into `app.py` (screens), `helpers.py` (pure ranking/transport/twin/parsing, tested without Streamlit), `demo_data.py` (synthetic data). Live mode when the backend is up, labelled DEMO MODE otherwise. |

## 3. Test results (measured only)

Command: `.venv/bin/python -m pytest tests/ -v` — **78 passed, 0 failed,
0 skipped** (3 warnings: LangChain deprecation, FastAPI `on_event`
deprecation — pre-existing, not failures). Updated 2026-11-11 after the
UI restyle (§16, +5 tests).

| File | Tests | Covers |
|---|---|---|
| test_backend.py | 11 | health, requirement CRUD, ask (grounded + not-found), materials, approval pane ×2, simulate, confirm-refused, full draft→send→approve→confirm→invoice→records flow, reject, **GET /accuracy (8 metrics, formula/source/n/target) + Worst Answers action round-trip (200 → 409 duplicate → 404 missing → 422 unknown action)** |
| test_rag.py | 1 | retrieval top-1, not-found, cited answer |
| test_vlm.py | 4 | scale detection, regions, title block, plan Q&A / not-found |
| test_takeoff.py | 3 | takeoff maths, estimate labels, reconciliation, flagged lines; **typed requirement applied on top of a plan takeoff (override keeps old value, new material appends, no-quantity skipped); `run_takeoff` plan+typed merge and requirement-only fallback** |
| test_suppliers.py | 3 | evidenced-only quality, cost+quality tradeoff (3 distinct winners), transport (manual location) |
| test_twin.py | 2 | twin cost+quality risk, what-if breaks, ranking-fallback sim |
| test_ranking.py | 4 | canonical blend (hand-computed scores), lead breaks ties, quality can win, no-evidence fallback |
| test_cache.py | 1 | paraphrase/synonym hits, plan isolation, savings |
| test_evals.py | 1 | 73 pairs, no duplicates, groundedness ≥ 0.9, top-1 ≥ 0.85, guardrail block 1.0 |
| test_lora.py | 1 | toy adapter train (≥ 0.9) + save/load round-trip |
| test_guardrails.py | 1 | price cap, deadline, never-pay, PII redact/allow, clean allow |
| test_email.py | 2 | mock send + idempotent duplicate, draft + outbox drain |
| test_observability.py | 8 | rate NULLs, empty-day NULLs, measured groundedness 0.5, **METRIC_DEFS 8 unique, rollup populates retrieval/guardrail/ranking/cache/cost + takeoff NULL, empty dashboard all "no data", Worst Answers + PII-free raw events, Worst Answer action add-once-then-refuse** |
| test_records.py | 2 | records CSV/JSON round-trip, invoice only when recorded |
| test_frontend.py | 20 | demo data, requirement parsing, frontend ranking formula, transport, demo Q&A, **frontend/backend METRIC_DEFS agreement, accuracy format/status never invents, no evaluation UI in the Accuracy tab (test asserts Worst Answers / Eval Run History / drill-down are not rendered), demo dashboard complete + honest (takeoff "no data", buyer-agent 1.0 with 0.58 agreement rate separate), live fetch returns None when backend down, real Streamlit AppTest render of the Accuracy tab; NEW: parser item/unit/location + LLM-hook fallback, takeoff updates from typed requirement (all 5 cases), supplier contact never invented, quote-email preview OFF/ON + blocked + backend parity, AppTest end-to-end takeoff update, AppTest email preview/edit/send, AppTest blocked send when email not held, AppTest render of all 7 tabs after the restyle** |
| test_theme.py | 4 | palette/CSS consistency, status chips keep their text label (HTML-escaped), journey stepper shows all 9 steps + clamps, hero labels demo/live honestly |
| test_modularity.py | 3 | public interfaces, import map, no auto-location / no hard torch/faiss |
| test_escalation.py | 6 | agent identity in draft (OFF/ON), send OFF hides contact end-to-end, send ON shares it, answerable question answered, unanswerable escalates → customer emailed → customer reply to supplier |
| **Total** | **78** | |

Also: `.venv/bin/python tests/self_test.py` → **exit 0** (all 9 sections
print measured results; evals 73 pairs, retrieval top-1/top-3 and
groundedness 1.0 on the fixed set, LoRA train accuracy 1.0).

Changes made to tests in this pass (all deliberate, hand-computed):
- `test_backend.py::test_ranking_best_value_is_not_cheapest_alone` —
  expectations updated to the canonical 0.45/0.35/0.20 blend
  (74.3 / 66.3 / 65.9; ranks cheap 1, mid 2, best-q 3).
- New tests: lead-tie breaker, transport (nearer wins on total landed
  despite higher unit price), grounded ask regression, VLM, frontend
  helpers, email, observability, records, modularity.
- `tests/test_ai_modules.py` deleted — its 10 tests moved verbatim into
  per-module files (`tests/test_<module>.py`).

## 4. Ranking reconciliation (decision)

**Single source of truth: `app/suppliers/search.py`.**
`best_value_score(cost, quality, lead) = 0.45·cost + 0.35·quality +
0.20·lead` (each 0..1), weights `W_COST/W_QUALITY/W_LEAD`.
`app/ranking.py::rank_shortlist` imports that function — the old
0.50/0.50, no-lead blend is deleted; no second formula remains.
`.env.example` and `app/config.py` defaults updated to 0.45/0.35/0.20
(`VALUE_WEIGHT_LEAD` added). The frontend (`frontend/helpers.py`) uses
the same blend. `docs/ARCHITECTURE.md` §5.5 records the resolution.

Verified: demo shortlist (concrete, 10 m³, Fremont) still gives three
**distinct** winners — best value Alameda Concrete Supply (sup07),
cheapest Central Valley Aggregate Co (sup10, $1,292.00 landed),
highest quality Bay Area Building Supply (sup01, 0.875).

## 5. Wiring result (`app/integrations.py`)

`GET /modules` (live) returns all True:

```json
{"rag": true, "takeoff": true, "suppliers": true, "twin": true,
 "guardrails": true, "cache": true, "evals": true, "lora": true}
```

Wired to the real entry points (names checked, not guessed):
RAG `HybridRetrieval` (+ `load_plan_corpus`), Takeoff
`compute_takeoff` (loads `data/plans/<file>.json` by file name when a
plan dict is not passed), Suppliers `search_suppliers`, Twin
`DigitalTwin` (decision shape) + `simulate_cost_and_quality` (what-if
shape used by `/simulate`), Guardrails `Guardrails().check` (with
`share_contact` passed through), Cache `SemanticCache`, Evals
`generate_eval_pairs`, LoRA `ToyLoRA` (saved `.npz` loaded when
present; keyword fallback with the same labels when numpy is missing).

**Bug found and fixed by wiring:** the ask endpoint crashed (500) on
grounded answers — `rag_retrieve` returned `region` as an empty string
while `AskResponse.citation_image_region` is `dict | None`. It now
returns a region dict or `None`. Regression test:
`test_ask_with_rag_returns_grounded_cited_answer`.

## 6. Smoke test results (live server, 2026-11-11)

Uvicorn on a temp SQLite DB, `EMAIL_PROVIDER=mock`, curl only:

- `GET /health` → 200 `{"status":"ok","email_backend":"mock","graph_available":true}`
- `GET /modules` → all 8 modules true (above)
- `POST /requirements` → 201; added 3 suppliers → 201 each
- `POST /requirements/{id}/buyer/run` → LangGraph, `approval_status: PENDING`, best-value + highest-quality ids returned, `error: null`
- `POST /simulate` → 200, quality risk + reasons present, transport fields present
- `POST /buyer/draft` → 200 (draft text returned); `POST /buyer/send` → 200, 3 queued, outbox `sent: 3`
- `GET /approval` → best-value / cheapest / highest-quality pane
- `POST /approve` → `APPROVED`; `POST /confirm` → `CONFIRMED`; `GET /orders` → order `CONFIRMED`
- `POST /ask` (grounded) → 200, `found: true`, `grounded: true`, answer cites C25/30 + clause C-01; unanswerable question → honest "not found", `found: false`
- **No real emails:** only mock `.eml` files under `data/mock_mail/` (git-ignored).

**Verified since this was written:** Streamlit 1.67.0 + pandas + altair
are installed in the project `.venv` (added for the §13 Accuracy check)
and the 7 tabs ARE covered by real Streamlit AppTest renders in
`tests/test_frontend.py` (Accuracy tab, takeoff update from a typed
requirement, Buyer Agent email preview/edit/send, blocked send). `docker
compose up` is still **not** verified (docker is not installed in this VM).

## 7. What is NOT done

- **GitHub push** — no repo exists yet (`git status`: not a git
  repository); creating the repo + pushing needs a live browser
  sign-in, which a subagent cannot do.
- **Free deploy** (Streamlit Community Cloud + Neon/Supabase + Upstash)
  — same reason: needs a live browser sign-in; see `docs/DEPLOY.md`.
- **Docker compose run** — docker is not installed in this VM.
- **Streamlit AppTest** — streamlit is not installed in this VM.
- **Real emails** — MockSMTP only; SMTP is off unless `EMAIL_PROVIDER`
  is set to `smtp` with credentials.
- **No LLM key configured** — backend runs in local-fallback mode
  (TF-IDF/BM25 + rules); `LLM_API_KEY` is empty by design.
- **VLM is a local fallback** — `app/vlm/` reads structured plan data;
  no real vision model is called. Wiring a hosted VLM is a follow-up.
- **Frontend screens still in one file** — `frontend/app.py` holds all
  7 screens; pure logic is split out (`helpers.py`, `demo_data.py`). A
  `frontend/screens/` package split is a follow-up (needs Streamlit +
  AppTest to verify).

## 8. Secret scan (2026-11-11)

- `grep -r "Induvava|AmalDeepz"` over the repo (excluding `.venv`,
  `.pytest_cache`, `__pycache__`) → **no matches**.
- `grep` for hardcoded passwords / API keys / `sk-` / `AKIA` / private
  keys → **no matches**. `.env.example` contains names/empty values only.
- No `.env` file exists in the repo. `.gitignore` covers `.env`,
  `*.env`, `secrets.toml`, `*.db`, `*.sqlite*`, `.venv`,
  `data/mock_mail/`, `data/exports/`, `data/checkpoints.sqlite`,
  `data/buildbuy.db`, `__pycache__/`.

## 9. Transport / total landed cost (user update 2026-11-10/11)

- **Total landed cost = goods + transport + taxes/fees**, shown as a
  per-supplier breakdown in search, twin, `/simulate`, approval pane,
  and the Streamlit Suppliers tab — so a nearer supplier can win on
  total landed cost despite a higher unit price (tested: Hayward
  $128/m³ beats Modesto $118/m³ at $5/km).
- **Location is manual and optional, blank by default.** The buyer types
  a delivery location (city / ZIP / address) into a separate optional
  field; only then is distance + transport computed and included. Blank
  → landed cost shows **"excl. transport"** and ranking works without
  it. The buyer can toggle transport off or enter their own $/km rate.
- **No auto-detection anywhere:** no browser geolocation API, no IP
  lookup, no device location, and the requirement's job-site location is
  NOT auto-used for transport. Location resolves offline against a
  small built-in city table + `lat,lng` (`app/suppliers/location.py`,
  mirrored in `frontend/helpers.py`); unrecognised input excludes
  transport and says so. Enforced by `tests/test_modularity.py`.
- The twin's what-if does **not** scale transport by the price change
  (freight does not rise with the unit price).
- README ties this to Deepthi's Ford Total Landed Cost work (Supply
  Chain Analytics, 2023–2025) — same discipline, single-job scale.

## 10. Chat-first input (user clarification 2026-11-10)

The chat is the input: upload a construction plan (image/PDF) **or**
type / photograph the part / requirement in chat, then quantity +
optional location + deadline + budget as follow-up prompts in the same
chat flow. Start screen, README, and `docs/ARCHITECTURE.md` §4 step 1
say this explicitly.

## 11. Modularity (user update 2026-11-10)

15 modules, each with its own folder/file, `__init__.py` public
interface (`__all__`), own tests (`tests/test_<module>.py`), and a
rebuild/test-alone command — full map in [`docs/MODULES.md`](MODULES.md)
(also in README + `docs/ARCHITECTURE.md` §12). Boundaries enforced by
`tests/test_modularity.py`. New this pass: `app/vlm/`,
`frontend/helpers.py`, `frontend/demo_data.py`; filled-in `__init__.py`
for `app/agents/`, `app/api/`, `app/email/`, `app/records/`; `numpy`
added to `requirements.txt`. Follow-up: `frontend/screens/` package
(see §7).

## 12. Agent identity / supplier-question escalation / contact sharing (user update 2026-11-10 19:51)

- **Agent identity in every supplier email:** `EmailService.draft_quote`
  now opens "I am BuildBuy Copilot, acting as the buying agent for
  [customer]" and enquires about the specific part + quantity (deadline /
  budget where given). The LangGraph Buyer node and Negotiator prompts
  carry the same identity (`app/agents/graph.py`); `buyer/message` and
  negotiation emails are prefixed via `with_agent_identity`.
- **Escalation — the agent never guesses** (`app/agents/escalation.py`):
  `classify_supplier_question` answers only questions that ask to confirm
  what the requirement already states (part, quantity, location, deadline,
  budget/max price), built from those values only. Anything else — payment
  / upfront / deposit, a price beyond the limits, a spec, delivery changes,
  warranty, tax, terms — escalates: the question is recorded as an inbound
  `Message`, the supplier's `Outreach` goes to `NEEDS_CUSTOMER`, the
  customer is emailed at deepthiag26@gmail.com
  (`send_customer_question`, idempotency key
  `escalation:{deal}:{supplier}:{question-hash}`), and NO reply is sent
  to the supplier. The customer answers via
  `POST /buyer/escalations/{id}/reply`; the agent then sends the
  supplier the customer's words verbatim plus only its identity line.
  Pending escalations: `GET /buyer/escalations`.
- **Contact sharing, verified end-to-end:** the per-supplier toggle
  (default OFF) is now enforced in three places, not just the guardrail:
  `draft_quote` anonymises to "a customer" when OFF, `buyer/send` and
  `buyer/message` strip name/email/phone via
  `EmailService.strip_customer_identity` when OFF and include
  Deepthi Jainlal / deepthiag26@gmail.com / +1 341-252-9234 only when ON
  for that supplier (payload toggle, falling back to the persisted
  `POST /settings/contact-sharing/{supplier_id}` toggle). The Buyer Agent
  screen labels it "Share my contact with this supplier" with a
  plain-words explanation of what is shared when ON and what the supplier
  sees when OFF; the Suppliers tab carries the same wording. Frontend
  demo settings email corrected to deepthiag26@gmail.com.
- **Tests:** `tests/test_escalation.py` — 6 new tests (identity in draft
  OFF/ON, send OFF hides contact end-to-end, send ON shares it,
  answerable question answered from the requirement, unanswerable
  question escalates → customer emailed → customer reply reaches the
  supplier in their words → second reply refused). Full suite:
  **50 passed, 0 failed** (was 44); `tests/self_test.py` exit 0.
- **Not done:** no GitHub push, no deploy, no real emails (MockSMTP
  only). The GitHub repo now exists
  (https://github.com/deepthivj-aiml/buildbuy-copilot) — push is the
  parent's next step (git auth is not set up in this VM).

## 13. Observability Dashboard in the UI (user update 2026-11-10 20:17)

The Accuracy tab (tab 6) was a partial placeholder — no 8-metric table,
no alert thresholds on the trend charts, 3 Worst Answers with no
per-row actions, no drill-down, no live wiring. It is now the full
Observability Dashboard (plan §9, `docs/ARCHITECTURE.md` §10):

- **Backend** (`app/observability.py`): `METRIC_DEFS` — the 8 separate
  metrics with formula/source/target/direction (single source of truth;
  the frontend mirrors it and a test fails if they drift).
  `compute_daily_metrics` now also populates retrieval top-1,
  guardrail block rate, ranking top-1, cache hit rate and cost per job
  from eval runs / orders / events. Takeoff MAPE stays **NULL** —
  material edits overwrite the quantity in place, so no
  corrected-vs-estimate pair is recorded yet; the dashboard says "no
  data yet" instead of inventing a number. `build_accuracy_dashboard(db,
  days=30)` returns metrics + headline + trends + per-module + Worst
  Answers (10 lowest) + Eval Run History + PII-free raw events +
  alerts, with every count windowed to the requested days.
  `record_worst_answer_action` appends to
  `data/evals/worst_answers_eval.jsonl` (deduped by `qa_log_id`) and
  audits; a repeat returns "already recorded".
- **API** (`app/api/routes.py`): `GET /accuracy` → `AccuracyDashboardOut`
  (new schemas in `app/schemas.py`, incl. `agreement_rate` on the
  buyer-agent metric). `POST /accuracy/worst-answers/{qa_log_id}/action`
  → 200 on success, **409** on a repeat action, 404 for a missing QA
  row, 422 from the schema for an unknown action.
- **Buyer-agent metric corrected**: its value is the
  approval-before-order invariant (1.0 when every order has an APPROVED
  `ApprovalRequest`, else < 1.0). The quotes-agreed rate is reported
  alongside as `agreement_rate` — never blended in, so the metric can
  never sit permanently in alert.
- **Frontend** (`frontend/app.py` tab 6, pure helpers in new
  `frontend/accuracy.py`, demo data in `frontend/demo_data.py`):
  8-metric table (formula/source/n/target/status), 4 headline cards,
  2 Altair trend charts with alert thresholds as dashed red rules
  (groundedness 90%, retrieval top-1 85%, eval pass 90%, p95 latency
  10 s; `st.line_chart` fallback when Altair is absent), per-module
  table, Worst Answers with per-row "Add to eval set" / "Mark fixed"
  (live mode POSTs to the backend; demo mode notes the action in
  session state only), Eval Run History, drill-down to raw events by
  step. Live mode (backend answers `/health`) fetches `GET /accuracy`
  and shows a LIVE badge; demo mode shows labelled synthetic data with
  a "Clear demo metrics" button that renders the empty state. Demo
  thumbs-down feedback merges into the Worst Answers list.
- **Verified live** (2026-11-11, temp SQLite DB, uvicorn :8001, mock
  email): `GET /accuracy` on an empty DB returns all 8 metrics
  `null` / `no_data`; the AppTest render of the tab shows the LIVE
  badge + "No data yet" with no exception. After a real
  requirement → 3 suppliers → simulate → draft → send (3 queued) →
  approve → confirm flow, `GET /accuracy` reports buyer-agent
  **1.0, n=1, status ok**, approval-before-order 1.0, no alerts; the
  AppTest render shows the 8-metric table with Buyer-agent accuracy
  **100.0% ✅ ok** and Takeoff estimate accuracy "no data yet".
  Streamlit 1.67.0 + pandas + altair were installed into the project
  `.venv` for this check (already in `requirements.txt`).
- **Tests**: +13 (63 total, all passing; `self_test.py` exit 0). See §3.
  New: `test_accuracy_tab_renders_in_streamlit` (real AppTest render,
  skipped where Streamlit is not installed), live-fetch failure test,
  frontend/backend `METRIC_DEFS` agreement test.
- **Known limit (honest)**: Takeoff estimate accuracy cannot be
  measured until material corrections are recorded as
  corrected-vs-estimate pairs (today edits overwrite in place). The
  dashboard shows "no data yet" for it — by design, not a bug.

## 14. Materials takeoff not updating from a typed requirement (user report 2026-11-10 21:08)

**Live report:** typing "concrete, 10 m3, Fremont" parsed Quantity 10
correctly and the quantity reached the Buyer Agent draft, but the Plan
& Materials takeoff table stayed at the demo plan's concrete 2.4 m3.
The user asked: is it not updating because no LLM/VLM is used — any
issue? Test and correct.

**Root cause (missing wiring, NOT an LLM/VLM issue):**
- `frontend/app.py::init_state` set `session_state["materials"]` to a
  static copy of `DEMO_MATERIALS` (sample plan A-101). Tab 1 "Parse my
  requirement" only stored `session_state["requirement"]`; "Find what I
  need →" only navigated to tab 2. Tab 2 rendered `session_state
  ["materials"]` in the editor. **No code path anywhere in the frontend
  applied a parsed requirement to the takeoff table** — the typed
  quantity was never even offered to the table.
- The backend already had the wiring (`app/integrations.py::run_takeoff`
  builds a takeoff from requirement items when there is no plan), but
  the deployed app runs in Demo Mode with no backend, so that path
  never ran — and even in live mode, when a plan WAS present,
  `run_takeoff` returned the plan takeoff and silently discarded every
  typed item.
- Two parser bugs in `frontend/helpers.py::parse_requirement` made it
  worse: (1) `item` was set to the **full raw input text** ("concrete,
  10 m3, Fremont" — the comment even said "keep raw as item"); (2) no
  unit was captured at all ("10 m3" → quantity 10, unit lost; the req
  dict had no `unit` key). Location also only matched after in/near/at,
  so "concrete, 10 m3, Fremont" parsed location "" — the "Fremont"
  shown live came from the Tab 1 text-input default (`or "Fremont"`),
  not from parsing. The quantity field likewise defaulted to 50 and
  the location to "Fremont": guessed defaults presented as parsed facts.
- **LLM/VLM verdict:** `VisionReader` (`app/vlm/plan_vision.py`) is a
  deterministic reader of structured plan data — no image pixels are
  read and no VLM is called (labelled local fallback); no LLM key is
  configured anywhere (config `llm_provider`/`llm_api_key` empty by
  default). Adding an LLM/VLM would NOT have fixed this bug — it was
  a missing code path, and a typed quantity needs no model to reach a
  table. No paid key was added and no real VLM is claimed.

**Fix:**
- `frontend/helpers.py::parse_requirement` rewritten: item is only the
  item name ("concrete", "steel brackets"); quantity + unit captured
  and normalised ("10 m3" → 10 / "m3", "50 units" → 50 / "pcs",
  "10 x concrete" form handled); location from in/near/at OR a
  trailing **known** place name (unknown trailing words are never
  guessed); optional `llm_parser` plug-in hook — a callable (e.g. a
  free local Ollama model) whose fields are used where present, with
  any error/empty result falling back to the deterministic parse. No
  LLM is configured by default.
- `frontend/helpers.py::apply_requirement_to_takeoff(materials, req)`:
  no quantity → table unchanged, never invented; matching line
  (normalised tokens; a single token that is only part of a multi-word
  line, "steel" vs "Steel brackets", does NOT match) → quantity/unit
  updated, method records the override AND the old plan value;
  new material → appended line; unit not stated → line flagged for
  review. Every line keeps the "estimate, not a surveyed quantity"
  label and a `source` ("sample plan" / "typed requirement").
- `app/takeoff/engine.py`: `takeoff_line_from_requirement` +
  `apply_requirement_to_result` (same matching rules, exported in
  `app/takeoff/__init__.py`). `app/integrations.py::run_takeoff` now
  applies requirement items ON TOP of a plan takeoff, and the
  requirement-only fallback uses the engine function (stale method
  string "no plan takeoff module yet" and `estimate_label: True`
  replaced; confidence 0.90 for a user-stated quantity).
- `frontend/app.py`: Parse, "Find what I need →" (re-applies after
  the user edits the parsed fields) and "Try with a sample plan" all
  call `apply_requirement_to_takeoff` and show the resulting note on
  tabs 1 and 2; quantity/location defaults no longer invent values
  (unknown quantity starts at 1 with a warning; location blank with a
  placeholder). Demo materials in `frontend/demo_data.py` now carry
  `source` + `estimate_label` per line.
- **Tests:** +7 in this section (73 total, all passing; `self_test.py`
  exit 0), incl. real AppTest end-to-end: type "concrete, 10 m3,
  Fremont" → Parse → Plan & Materials shows concrete **10 m3** with
  the 2.4 m3 plan value kept in the method. Before the fix the repro
  (`/tmp/repro_takeoff.py`, kept out of the repo) confirmed item =
  full text, no unit, takeoff stuck at 2.4 m3.

## 15. Per-supplier contact + editable email preview (user update 2026-11-10 21:10)

**What was already there vs what was added.** Already there: the
backend `EmailService.draft_quote` (agent-identity opening, part +
quantity + location + deadline + budget, contact only when sharing is
ON) and `strip_customer_identity` (routes apply it when sharing is
OFF); the frontend had ONE static draft email for the top 3 suppliers
with per-supplier share toggles — but the toggles never changed the
draft text, the draft showed no per-supplier recipient / from /
channel, and nothing blocked sending to a supplier with no email held.
Added in this pass:
- `frontend/helpers.py`: `supplier_email` (extracts a real address or
  `None` — "not public — request via email" is not an address),
  `supplier_contact_details` (name / email / phone / address / area /
  source; missing = `None`, never invented — demo suppliers have no
  phone or street address), `build_quote_email` (per supplier:
  channel email, From `BuildBuy Copilot <noreply@buildbuy.local>`
  (config default `EMAIL_FROM`), To, subject, full body;
  `sendable: False` + reason when the email is not held), and
  `strip_contact_details` (mirror of the backend stripper, applied at
  send time when sharing is OFF — even to contact details the user
  typed into an edited draft). The preview body is byte-for-byte the
  backend `draft_quote` output for the same inputs (OFF and ON — tested).
- `frontend/app.py` Buyer Agent tab: one expandable card per top-3
  supplier with contact details, how they will be contacted, the full
  email preview, editable subject + body, Save / Reset to draft, and a
  per-supplier Send (disabled with the reason when the email is not
  held); "Send quote requests to top 3" sends only to sendable
  suppliers and lists the blocked ones. Widget keys carry the sharing
  state (`...-shared` / `...-private`) so toggling sharing rebuilds
  the preview instead of showing stale text (a real bug found while
  testing: Streamlit keeps widget values by key). The Suppliers tab
  cards now also show phone/address ("not held") and the
  how-we-contact line. `contact_sharing` lookups use `.get(..., False)`
  so a supplier list that changes cannot KeyError the tab.
- **Tests:** +3 in this section (73 total), incl. AppTest: preview
  shows identity line + supplier email + channel/from; toggling
  sharing ON puts Deepthi Jainlal / deepthiag26@gmail.com /
  +1 341-252-9234 in the preview; editing the body changes the sent
  text and sharing OFF strips the typed contact; a supplier with no
  held email shows "not held" and its Send button is disabled.

## 16. UI restyle — stylish, visual, colourful (user update 2026-11-10 21:16)

**What changed (no functionality, label or honest-data rule changed):**
- **Theme:** `.streamlit/config.toml` at the repo root (light theme:
  primary `#4F46E5` indigo, background `#F8F7FF`, text `#1F2937`) +
  custom CSS in new pure module `frontend/theme.py` (`PALETTE`,
  `THEME_CSS`, `status_chip`, `order_chip`, `thread_chip`,
  `journey_stepper`, `hero_html` — no Streamlit import, unit-tested
  in `tests/test_theme.py`). The old inline `CSS` block in
  `frontend/app.py` is deleted; the theme module is the single source.
- **Hero:** gradient banner (indigo → violet → teal) on every tab with
  the app name, tagline and pills ("7 tabs · one buyer workflow",
  DEMO/LIVE mode as text, "Nothing ordered without your tap"). The mode
  pill is honest: it says DEMO MODE in demo mode and LIVE MODE only
  when the backend answers.
- **Journey stepper:** the old 5-step `st.progress` bar is replaced by
  a 9-step stepper (Requirement → Materials → Suppliers → Twin →
  Buyer agent → Approval → Order → Delivery → Invoice) with done
  (green ✓) / current (indigo, ring) / to-do (grey) states, driven by
  `journey_stage()` from session state (requirement, nav, order
  status). Every step shows its number and text label.
- **Chips:** colour-coded status chips with text labels always kept
  (never colour-only): best value green / cheapest blue / highest
  quality purple on supplier cards; order statuses (PENDING amber,
  APPROVED blue, DELIVERED teal, INVOICE_RECEIVED green, REJECTED red)
  on My Orders; inbox thread statuses on Buyer Agent; metric statuses
  on Accuracy; free-tier counter as info chips. Demo/live badges keep
  their amber/green.
- **Cards & buttons:** supplier cards have shadows and a hover lift;
  the three choice cards keep their green/blue/purple borders with
  gradient backgrounds; primary buttons are gradient indigo with a
  shadow, secondary buttons white with an indigo outline; tab
  navigation renders as pills (selected = indigo). Headings get an
  indigo accent bar; metric cards get a coloured top border and hover
  lift. Contrast-first: dark text on light backgrounds throughout.
- **Real bug found and fixed by the restyle tests:** the tab
  navigation used `index=NAV.index(session_state["nav"])` with no key.
  When the index default changed between runs, Streamlit
  re-initialised the radio from the new default and silently DROPPED
  the user's tab click — AppTest showed every second navigation
  ignored (2→3, 2→4, 3→4 all dropped on first try, retry worked).
  The radio is now keyed (`key="nav"`, value in `session_state["nav"]`,
  programmatic buttons set the same key then `st.rerun()`); every
  navigation now sticks on the first try, verified by the debug
  sequence and by the all-tabs AppTest.
- **Tests:** +5 in this section (78 total, all passing; `self_test.py`
  exit 0): `tests/test_theme.py` (4: palette/CSS, chip labels,
  stepper, hero) + `test_all_seven_tabs_render_after_restyle` (real
  AppTest: every tab renders with no exception, its heading present,
  hero + stepper visible, DEMO labelling and the estimate label
  intact).
- **Correction (2026-11-10 21:32, live test):** the claim above that
  "every navigation now sticks on the first try" was true only for
  the RADIO tab switches, which the AppTest exercised — it was NOT
  true for the navigation BUTTONS ("Find what I need →" etc.), which
  the AppTest never clicked and which crashed live with
  `StreamlitWidgetAlreadyInstantiatedError` (see §18). The radio fix
  and the button fix are different bugs; §18 fixes the buttons.

## 18. Live crash fix + brown theme (2026-11-10 21:32)

**Live test that found it** (21:32, commit `df622e4` on
https://tu2tztzegjayuwzxudxbnv.streamlit.app/): restyle works,
takeoff fix passed (concrete 10 m3), email preview/edit passed,
steel sample passed — but clicking "Find what I need →" after
parsing "concrete, 10 m3, Fremont" crashed the app.

- **Crash — root cause:** the button handler assigned
  `st.session_state["nav"]` AFTER the keyed radio (`key="nav"`) had
  already been created in the same run. Streamlit forbids assigning
  a widget's key after instantiation and raises
  `StreamlitWidgetAlreadyInstantiatedError` (traceback
  `frontend/app.py` line 384). The app recovered on the next
  interaction, but the primary Parse → Find flow was broken. The
  same bug existed in all three navigation buttons (Find what I
  need →, Find suppliers for these materials →, Contact top 3
  suppliers →). **Fix:** buttons now set a plain
  `session_state["pending_nav"]` (not a widget key) and call
  `st.rerun()`; the next run applies it to `session_state["nav"]`
  just BEFORE `st.radio(key="nav")` is created, then clears it
  (`frontend/app.py`: `init_state` + the block above the radio +
  the three handlers). Verified by a real AppTest that clicks each
  of the three buttons and lands on the right tab first try, with
  no exception.
- **Quirk 1 — plan value overwritten on re-apply:** after the
  takeoff update the notice said "was plan estimate 10 m3" instead
  of 2.4 m3. Root cause: `apply_requirement_to_takeoff` (frontend)
  and `apply_requirement_to_result` (backend) took the "old" value
  from the line's CURRENT quantity, so the second apply (Parse,
  then Find) treated the typed 10 as the plan value. **Fix:** the
  original plan value is captured once, on the first override, in
  `plan_quantity` / `plan_unit` on the line (frontend dict keys;
  new optional fields on backend `TakeoffLine`), and the method /
  note always quote those. Re-applying now still says "plan
  estimate of 2.4 m3" (frontend) / "13.39 m3" (backend).
- **Quirk 2 — one email card for concrete: CORRECT, wording fixed.**
  For concrete x10 only Sierra Building Supply is eligible at all:
  the other five suppliers are excluded because the quantity is
  below their MOQ (Bay Steel 25, Golden State 50, Pacific 100,
  East Bay 50, Delta 200) — no card was dropped. **Fix (wording
  only):** the Buyer Agent tab now says "Showing 1 email card —
  only 1 of the 1 ranked suppliers can be emailed…" with the five
  MOQ exclusions listed, and the bulk-send button reads "Send
  quote request (1 sendable supplier)" instead of "top 3".
- **Quirk 3 — "Reset to draft" did not restore the textboxes.**
  Root cause (two parts): (a) deleting a widget's session-state
  key alone does NOT reset it in a real browser — the browser
  re-sends the widget's old value on the next run and the `value=`
  argument is then ignored (AppTest could not reproduce this: its
  simulated frontend does not re-send stale values). **Fix:** Reset
  bumps a per-supplier `quote_draft_version`, so the subject/body
  widgets are created under brand-new keys (`…-v1`) initialised
  from the regenerated draft. (b) The "How we will contact them"
  line always showed the GENERATED subject, even after an edit +
  Save — and a saved draft only becomes visible in `saved` on the
  run after the Save click. **Fix:** the line now shows the subject
  the textbox currently holds (read from the widget's own session
  state, falling back to the saved / generated subject), and the
  Save handler calls `st.rerun()` so the "Edited by you" caption
  appears at once.
- **Brown theme (user update 2026-11-10 21:32):** UI recoloured
  from light indigo to warm brown — `.streamlit/config.toml`
  (primary `#7C4A21`, background `#FBF6EF`, secondary `#F3E8D8`,
  text `#2E1F14`) + `frontend/theme.py` palette/CSS (deep brown
  primary, caramel `#A9713F` + amber `#B45309` accents, warm cream
  page). Hero gradient is now deep brown → brown → amber; primary
  buttons gradient brown, secondary white with a brown outline,
  stepper current step brown, metric numbers brown, info chips warm
  tan. Semantic chip colours (best value green / cheapest blue /
  highest quality purple) are kept distinct — they carry a category
  meaning and always keep their text label. No indigo/violet/teal
  left in the frontend (asserted in `tests/test_theme.py`).
  Functionality, labels and honesty rules unchanged.
- **Tests:** +3 in this section (81 total, all passing;
  `self_test.py` exit 0): `test_find_button_navigates_first_try`
  (AppTest clicks all three navigation buttons, no exception,
  lands on the right tab, concrete still 10 m3 with "plan estimate
  of 2.4 m3" in the method), `test_buyer_agent_email_card_count_is_
  honest` (concrete x10 → "Showing 1 email card" + MOQ list;
  steel x50 → 3 cards), `test_reset_to_draft_restores_subject_and_
  body` (edit + Save → contact line shows the saved subject; edit
  again + Reset → v1 widgets hold the regenerated draft, saved
  draft gone); re-apply plan-value assertions in
  `test_takeoff_updates_from_typed_requirement` (frontend) and
  `test_takeoff_applies_typed_requirement_on_plan` (backend); brown
  palette assertions in `tests/test_theme.py`. UAT: +5 checks
  (2.12, 4.17, 4.18, 8.7, 8.8; 79 total).

## 19. Exact next steps for the parent

1. **Push to the GitHub repo** (repo already exists:
   https://github.com/deepthivj-aiml/buildbuy-copilot, public, empty):
   `git init`, `git add .`, `git commit`, push to that remote.
   Verify `.gitignore` is honoured (`.env`, `*.db`, `.venv` must not
   appear in `git status`).
2. **Run CI once** (`.github/workflows/ci.yml` runs pytest on push) and
   confirm green.
3. **Free deploy** (live browser sign-in): follow `docs/DEPLOY.md` §4
   smoke test — Streamlit Community Cloud (frontend), Neon/Supabase
   free Postgres, Upstash/Redis free cache; set `DATABASE_URL`,
   `REDIS_URL`, `EMAIL_PROVIDER=mock` (keep mock until SMTP is a
   deliberate decision). The live URL is already in the README
   (https://tu2tztzegjayuwzxudxbnv.streamlit.app/, verified live
   2026-11-10 21:15); re-verify it after each push, since Streamlit
   auto-redeploys from master.
4. **Verify on a machine with Streamlit + Docker:** `streamlit run
   frontend/app.py` + 7-tab AppTest smoke; `docker compose up --build`
   and repeat the §6 curl flow inside Docker.
5. **Decide the follow-ups:** `frontend/screens/` package split; real
   VLM behind `VisionReader.read_plan` (needs provider + cost decision);
   LLM key (optional — local fallback works without one).


## 20. Evaluation UI removed from the Accuracy tab (user update 2026-11-10 22:03)

The user asked what "Worst Answers — the fix list (10 lowest)" was for
and said: do all evaluations internally, give the observability
dashboard only, and keep the UI for user input only — not evaluation.

- **Removed from the UI** (`frontend/app.py` tab 6, `frontend/accuracy.py`,
  `frontend/demo_data.py`): the Worst Answers section (10 lowest +
  "Add to eval set" / "Mark fixed" buttons + statuses), Eval Run
  History, and the raw-events drill-down; the per-module table no
  longer has a "Worst in 7 days" column; the thumbs-down message no
  longer says the answer "goes to the Worst Answers list" (feedback is
  still recorded). The frontend helpers `apply_worst_action` /
  `worst_answers_from_feedback` and the demo constants
  `DEMO_WORST_ANSWERS` / `DEMO_EVAL_RUNS` / `DEMO_RAW_EVENTS` are
  deleted. The tab heading is now "Accuracy — observability dashboard"
  and states plainly that evaluations run internally, with no fix list
  and no evaluation action in the UI.
- **Kept in the UI** (observability dashboard only): 8 separate metrics
  with formula/source/n/target/status, 4 headline cards, 2 trend
  charts with alert thresholds as dashed rules (the Eval pass % line
  stays as an aggregate trend series only — no run list behind it),
  per-module breakdown (module/metric/value/n), alerts, "no data yet"
  empty states, LIVE badge in live mode.
- **Still runs internally — nothing deleted from the backend:**
  `app/evals/` (eval generation + runner), `app/observability.py`
  (`build_accuracy_dashboard` still returns `worst_answers` /
  `eval_runs` / `raw_events` in the `GET /accuracy` payload for
  internal use; `record_worst_answer_action` + `POST
  /accuracy/worst-answers/{id}/action` unchanged), and the backend
  tests for both (`test_observability.py`,
  `test_backend.py::test_accuracy_worst_answer_action_round_trip`).
- **Tests:** 81 passed, 0 failed (`pytest tests/ -v`), `self_test.py`
  exit 0. New `test_accuracy_tab_has_no_evaluation_ui` asserts the
  frontend helpers/demo constants are gone and an AppTest render of
  the Accuracy tab shows all 8 metric names and none of "Worst
  Answers" / "Eval Run History" / "Drill-down" / "Add to eval set" /
  "Mark fixed". UAT §6 is now 6.1–6.8 (evaluation checks 6.5–6.9
  removed; 2.8 updated).
