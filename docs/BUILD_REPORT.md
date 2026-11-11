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
| M6 — Observability / Accuracy | `app/observability.py` (`metrics_daily` rollup: groundedness, thumbs-up, cache hit rate, latency p50/p95 — measured only, NULL when no data). Fixed this pass: `compute_daily_metrics` returned detached ORM rows (DetachedInstanceError) — now flush → expunge → commit. |
| M7 — Frontend | Streamlit, 7 tabs, chat-first Start (plan upload OR typed/photographed requirement in chat, then quantity + optional location + deadline + budget as follow-ups). Split this pass into `app.py` (screens), `helpers.py` (pure ranking/transport/twin/parsing, tested without Streamlit), `demo_data.py` (synthetic data). Live mode when the backend is up, labelled DEMO MODE otherwise. |

## 3. Test results (measured only)

Command: `.venv/bin/python -m pytest tests/ -v` — **50 passed, 0 failed,
0 skipped** (3 warnings: LangChain deprecation, FastAPI `on_event`
deprecation — pre-existing, not failures). Updated 2026-11-11 after the
agent-identity / escalation / contact-sharing update (+6 tests, §12).

| File | Tests | Covers |
|---|---|---|
| test_backend.py | 9 | health, requirement CRUD, ask (grounded + not-found), materials, approval pane ×2, simulate, confirm-refused, full draft→send→approve→confirm→invoice→records flow, reject |
| test_rag.py | 1 | retrieval top-1, not-found, cited answer |
| test_vlm.py | 4 | scale detection, regions, title block, plan Q&A / not-found |
| test_takeoff.py | 1 | takeoff maths, estimate labels, reconciliation, flagged lines |
| test_suppliers.py | 3 | evidenced-only quality, cost+quality tradeoff (3 distinct winners), transport (manual location) |
| test_twin.py | 2 | twin cost+quality risk, what-if breaks, ranking-fallback sim |
| test_ranking.py | 4 | canonical blend (hand-computed scores), lead breaks ties, quality can win, no-evidence fallback |
| test_cache.py | 1 | paraphrase/synonym hits, plan isolation, savings |
| test_evals.py | 1 | 73 pairs, no duplicates, groundedness ≥ 0.9, top-1 ≥ 0.85, guardrail block 1.0 |
| test_lora.py | 1 | toy adapter train (≥ 0.9) + save/load round-trip |
| test_guardrails.py | 1 | price cap, deadline, never-pay, PII redact/allow, clean allow |
| test_email.py | 2 | mock send + idempotent duplicate, draft + outbox drain |
| test_observability.py | 3 | rate NULLs, empty-day NULLs, measured groundedness 0.5 |
| test_records.py | 2 | records CSV/JSON round-trip, invoice only when recorded |
| test_frontend.py | 5 | demo data, requirement parsing, frontend ranking formula, transport, demo Q&A |
| test_modularity.py | 3 | public interfaces, import map, no auto-location / no hard torch/faiss |
| test_escalation.py | 6 | agent identity in draft (OFF/ON), send OFF hides contact end-to-end, send ON shares it, answerable question answered, unanswerable escalates → customer emailed → customer reply to supplier |
| **Total** | **50** | |

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

**Not verified in this VM:** Streamlit AppTest smoke of the 7 tabs
(streamlit is **not installed** in this VM or the system Python;
`which streamlit` → nothing) and `docker compose up` (docker is **not
installed**). The frontend pure helpers are covered by
`tests/test_frontend.py` (5 tests, run without Streamlit). Do not claim
the Streamlit UI or Docker run was verified here.

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

## 13. Exact next steps for the parent

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
   deliberate decision). Record the live URL in the README (it currently
   says "Deploy pending").
4. **Verify on a machine with Streamlit + Docker:** `streamlit run
   frontend/app.py` + 7-tab AppTest smoke; `docker compose up --build`
   and repeat the §6 curl flow inside Docker.
5. **Decide the follow-ups:** `frontend/screens/` package split; real
   VLM behind `VisionReader.read_plan` (needs provider + cost decision);
   LLM key (optional — local fallback works without one).
