# BuildBuy Copilot — Free Models (no paid key required)

**Rule: the app runs at $0 with no key.** Everything in the "used by
default" column works locally with no account, no key, and no per-call
charge. Anything that needs a key is opt-in (BYO key) and is labelled as
such in Settings — the key value is never shown.

> Prices and free tiers change frequently. Do not quote a price from this
> file without checking the provider's live pricing page first — where this
> file says "check live pricing", that is deliberate, not a gap.

## 1. What is used by default (local only, no key)

| Model / method | Used for | Cost | Used by default? |
|---|---|---|---|
| **TF-IDF + BM25 (scikit-learn, local)** | Hybrid retrieval over plan passages, spec clauses, supplier docs; paraphrase matching for the semantic cache | $0 | ✅ Yes |
| **Local sentence-transformers embeddings** (e.g. `all-MiniLM-L6-v2`, run on device) | Retrieval embeddings for RAG + semantic cache similarity | $0 | ✅ Yes |
| **FAISS (local index)** | Vector search over the local embeddings | $0 | ✅ Yes |
| **Rule-based requirement parser + deterministic Python** (takeoff maths, landed-cost maths, twin simulation, ranking) | Parsing, takeoff, ranking, twin — all deterministic, unit-testable, no model call | $0 | ✅ Yes |
| **VLM fallback: known plan metadata** (synthetic demo) | Plan reading when no VLM key is set — labelled honestly as metadata, never presented as vision accuracy | $0 | ✅ Yes (demo) |

## 2. Free / no-key options NOT used by default (available, opt-in)

| Option | What it is | Used by default? | Notes |
|---|---|---|---|
| **Ollama (local)** | Run open models locally (e.g. small instruction models) via a local server; no key, no per-call charge | ❌ No — opt-in | Needs a local Ollama install and a model pull; useful when the machine has the RAM/disk for it. No model is bundled in the repo. Check live model sizes before choosing one. |
| **Hugging Face free Inference API** | Hosted inference for open models | ❌ No — opt-in | Free tier exists but is rate-limited and changes often — check live pricing/limits. Needs a Hugging Face token (BYO, stored in `.env`, never committed). |
| **Hugging Face Transformers (local)** | Run open models on device with `transformers` + PyTorch | ❌ No — opt-in | Same local-cost profile as Ollama; heavier dependencies (torch) — deliberately not in `requirements.txt` by default. |

## 3. Paid providers — BYO key only, never required

| Provider | Used for | Used by default? | Notes |
|---|---|---|---|
| OpenAI API (LLM + VLM) | Plan-image reading (vision), answer generation, negotiation drafting | ❌ No | One key, `LLM_API_KEY` + `LLM_PROVIDER=openai` in `.env` / Streamlit secrets. Pay-as-you-go — check live pricing; do not assume $0 forever. |
| Anthropic Claude API (LLM + VLM) | Same as OpenAI (alternative — pick one, not both) | ❌ No | `LLM_PROVIDER=anthropic`. Check live pricing. |
| OpenAI embeddings (optional) | Drop-in replacement for local sentence-transformers | ❌ No | Local embeddings are the default; paid embeddings are a plug-in point only. Check live pricing. |

## 4. What is NOT in the free tier

- No paid APM / tracing backend in v1 (OpenTelemetry SDK writes spans to
  the same JSONL logs; Langfuse Cloud Hobby is the tracing option if
  tracing is ever wanted — BYO keys, opt-in).
- No paid embedding API, no paid maps API (distance uses OpenStreetMap
  Nominatim, free, no key, rate-limited; Google Maps API is a Phase 2
  decision only).
- No fine-tuning service: the LoRA adapter (skill 5) is PyTorch + PEFT,
  rank-2, on the user's own past purchases, toy scale first — local, $0.

## 5. If the app says a key is needed

It should not, in v1. If a screen ever blocks on a missing key, that is a
bug: the local fallback (TF-IDF + rules + known metadata) must take over
and say so. File it as an issue with the screen name and the exact message.
