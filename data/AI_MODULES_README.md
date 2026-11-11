# BuildBuy Copilot — AI Modules (README)

Owner paths: `app/rag/`, `app/takeoff/`, `app/twin/`, `app/suppliers/`,
`app/cache/`, `app/evals/`, `app/lora/`, `app/guardrails/`, `data/`.
Python 3.12, no paid API key. Local TF-IDF + BM25 + rules; numpy installed
for the LoRA toy (installed 2026-11-11 during the integration pass);
PIL only for generating synthetic plan PNGs. sentence-transformers,
FAISS, Redis and Presidio are all optional behind try/except with graceful
fallback (none of them installed — backend reports
`tfidf+bm25 (local, no API key)`).

## Modules (reel skill in brackets)

| Module | Skill | What it does |
|---|---|---|
| `app/rag/retrieval.py` | 1 Hybrid RAG | TF-IDF + BM25 (pure Python) + optional embeddings, RRF fusion, coverage-first ranking. Cited passages (doc_id, page/region, clause). Returns "not found" when <2 distinct query terms match anything. |
| `app/takeoff/engine.py` | — (takeoff) | Deterministic materials estimate from plan metadata. Every line labelled "estimate, not a surveyed quantity", method shown, confidence 0–1, low-confidence flagged. Totals reconcile (verified in tests). |
| `app/twin/simulator.py` | — (digital twin) | Landed cost = goods + shipping + fees; delivery date from lead time; risk = ½ cost risk + ½ quality risk. `what_if(price_pct, delay_days, qty_pct)` recomputes and lists what breaks (over budget, past deadline, quality risk high, defect exposure). |
| `app/suppliers/directory.py` + `search.py` | — (supplier search) | 12 synthetic suppliers. **Cost + quality ranking** (user update 2026-11-10): best value = 0.45·cost + 0.35·quality + 0.20·lead. Quality from evidenced signals only (certifications, vetting, reply reliability, lead-time reliability, defect history, user feedback); missing signals score neutral 0.5 and are listed as "not provided", never as good. Returns ranked list + cheapest + highest-quality separately, each with why_rank and a trade-off line. |
| `app/cache/semantic_cache.py` | 3 Semantic Caching | TF-IDF cosine + synonym map, plan-aware keys (no cross-plan hits), hit/miss + savings counter ($0.02 per avoided LLM call, planning figure). Redis optional via `REDIS_URL`, in-memory default. |
| `app/evals/eval_gen.py` | 4 Eval Generator | Generates grounded Q&A pairs from plan metadata + supplier records, dedupes, quality-checks (grounded, no duplicates), exports JSONL + CSV to `data/evals/`. Runner measures retrieval top-1/top-3 (answer containment), groundedness, guardrail block rate. |
| `app/lora/adapter.py` | 5 LoRA | TOY SCALE, numpy-only rank-2 adapter for intent classification (plan_qa / takeoff / supplier_search / buyer), 12 synthetic examples, saves `.npz`. Real PEFT path documented in the module docstring (not run). |
| `app/guardrails/guardrails.py` | 6 Guardrails | PII redaction (regex; Presidio if installed), price-cap, deadline, blocklist, never-pay, contact-sharing toggle (OFF → contact stripped). Returns pass/fail + reason; violations are never silently passed. |

## Data (synthetic only)

- `data/suppliers.json` — 12 synthetic suppliers (Bay Area + Portland + Phoenix).
  All contacts are `sales-supNN@example.invalid` (`.invalid` domain — no real
  email can ever be sent). Quality fields are labelled `synthetic_demo`.
- `data/plans/plan-001..003.json` + `-specs.txt` + `.png` (PIL-generated
  floor plans; regenerate with `python3 data/plans/generate_pngs.py`).
- `data/evals/eval_set.jsonl` / `.csv` — generated eval set (73 pairs).
- `data/lora_toy_adapter.npz` — trained toy LoRA weights.

## Run

```bash
.venv/bin/python -m pytest tests/ -v          # full suite (44 tests)
.venv/bin/python -m pytest tests/test_rag.py tests/test_takeoff.py tests/test_twin.py tests/test_suppliers.py tests/test_cache.py tests/test_evals.py tests/test_lora.py tests/test_guardrails.py -v   # AI modules only
.venv/bin/python tests/self_test.py            # end-to-end demo with measured results
```

## Measured results (2026-11-11, integration pass, .venv python3.12, local run)

- Tests: **44 passed, 0 failed, 0 skipped** (`pytest tests/ -v`;
  per-module files under `tests/test_<module>.py`; boundary test
  `tests/test_modularity.py` included).
- Retrieval: top-1 **1.0**, top-3 **1.0**, groundedness **1.0** on the 73-pair
  generated fixed set; unanswerable question ("tensile strength of the moon
  base") correctly returns "not found". (Fixed-set numbers, not a general
  accuracy claim.)
- Takeoff plan-001: concrete 13.39 m³, steel 1138.2 kg, bricks 8370,
  tiles 30.8 m², timber 126.0 m; all lines labelled estimate; reconciliation OK.
- Cost+quality ranking, concrete 10 m³ from Fremont: cheapest is Central
  Valley ($1292.00 landed, quality 0.60) but best value is Alameda
  ($1435.04, quality 0.86, 2-day lead, best value 0.750); highest quality is
  Bay Area Building Supply (0.875). Cheapest ≠ best value — as required.
- Twin: cheapest supplier's total risk 0.367 vs 0.115 for the dearer
  high-quality one (quality risk 0.404 vs 0.142). What-if (+10% price,
  +3 days, +20% qty on Alameda) breaks on over-budget ($1875.68 > $1600 cap).
- Cache: paraphrase hit ✓, synonym hit ✓, unrelated miss ✓, cross-plan
  miss ✓; demo hit rate 0.50, $0.04 saved.
- LoRA toy: train accuracy **1.0** (12/12 synthetic examples); all 4 demo
  intents predicted correctly; weights round-trip through `.npz`.
- Guardrails: 5/5 adversarial eval items blocked/redacted (block rate 1.0);
  self-test: 3/6 blocked (price cap, deadline, never-pay), PII redacted when
  sharing OFF, passed when sharing ON, card number always redacted.

## Blockers / notes

- No pytest, sklearn, sentence-transformers, FAISS, Redis or Presidio in this
  environment — all are optional by design; nothing is blocked.
- The project `.venv` is bare (pip only); tests were run with system python3
  (numpy 1.26.4 + PIL available). If the project venv is used, install
  `numpy` + `Pillow` for the LoRA toy and PNG generation, or those two steps
  degrade gracefully (keyword fallback / JSON-only plans).
- A sibling agent has built `app/ranking.py` alongside these modules; the
  parent may want to reconcile it with the cost+quality ranking in
  `app/suppliers/search.py` so there is one ranking implementation.
