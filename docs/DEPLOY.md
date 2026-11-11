# BuildBuy Copilot — Deploy (free, $0)

**Status: LIVE on Streamlit Community Cloud:**
https://tu2tztzegjayuwzxudxbnv.streamlit.app/ — deployed from
`deepthivj-aiml/buildbuy-copilot`, branch `master`, main file
`frontend/app.py`, Python 3.12; verified live with sample inputs
2026-11-10. Run the smoke test in §4 after any redeploy before
sharing the link.

## 1. Free deploy plan — $0/month

| Piece | Primary (free) | Fallback (free) | Limits to state honestly |
|---|---|---|---|
| App hosting | **Streamlit Community Cloud** (free) | Render free tier (web service) | Streamlit: 1 GB RAM, sleeps after inactivity, public repo required. Render free: 750 hrs/mo, spins down after 15 min idle, 512 MB RAM |
| API (if split from Streamlit) | Render free tier (FastAPI) | Railway trial / Fly.io free allowance | Same spin-down limits; **v1 decision: single Streamlit app + FastAPI mounted inside it, one deploy** |
| Database | **None — live data only (2026-11-10).** No working database; `app/db/` is unused legacy code, future storage only. The user's records are the Excel shortlist download and the emails to deepthiag26@gmail.com. | — | Nothing is stored; close the tab and the session is gone — download the Excel / `.eml` files first. (A Neon/Supabase free tier was the *planned* store before the live-data-only change; it is not used.) |
| Cache | **Upstash free tier (Redis, 10k cmds/day) or Redis Cloud 30 MB free** | In-memory dict (single-instance only) | Free tiers are small — cache is for repeat questions, not a data store |
| Email (v1) | **Gmail SMTP via the saved Google login (deepthiag26@gmail.com)** | Resend free tier (100 emails/day) | Gmail: daily sending limits (~500/day) and spam-filter risk on a new sender; Resend: 100/day free, needs domain verification for production |
| Static site / landing | GitHub Pages (free) | Vercel free tier | Static only; no server |
| CI | GitHub Actions (free for public repos) | — | Public repos unlimited; private repos 2,000 min/mo free |
| **Total** | **$0/month** | — | With the caps above, stated in the README. No paid tier is required for the demo or the first pilots |

**Cost-stays-$0 rules:** local embeddings (no paid embedding API) by
default; semantic cache so repeat questions cost no LLM call; evals run
locally; no per-user server (one shared demo + per-user data rows, not
per-user instances). If LLM usage grows, the user adds their own key (BYO).

## 2. Deploy the frontend — Streamlit Community Cloud (primary)

Prerequisites: the repo is pushed to GitHub under `deepthivj-aiml`
(the user creates the repo / signs in herself — Muse does not hold her
GitHub password), and `pytest` is green locally.

1. Go to Streamlit Community Cloud and sign in with GitHub.
2. **New app** → pick the repo, branch `master`, main file path
   `frontend/app.py`.
3. **Advanced settings → Secrets**: add only what you have, as TOML:
   ```toml
   # LLM_API_KEY = "…"   # optional — without it the app runs local-only ($0)
   # API_URL = "https://<your-render-api>.onrender.com"  # only if the API is split out
   ```
   Never put secrets in the repo. Without `API_URL` the app runs in
   DEMO MODE on synthetic data; without `LLM_API_KEY` it runs local-only.
4. **Deploy.** First deploy takes a few minutes (Streamlit + pandas install).
5. Run the smoke test (§4) on the live URL before sharing the link.

## 3. Deploy the API separately — Render free tier (fallback / split deploy)

Use only if the API is split from the Streamlit app.

1. Render → **New → Web Service** → connect the repo.
2. Build command: `pip install -r requirements.txt`
   Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Environment variables (Render dashboard, never in the repo):
   `EMAIL_PROVIDER=mock` (until real email is deliberately enabled),
   `LLM_API_KEY` (optional). **Do not set `DATABASE_URL` or
   `STORAGE_ENABLED=true`** — the app is live-data-only by design;
   the stored-data API is legacy and unused.
4. Set the Streamlit app's `API_URL` secret to the Render URL.
5. Note the free-tier spin-down: the first request after 15 min idle is
   slow. That is expected and stated in the README.

## 4. Smoke test after deploy (do this before sharing the link)

1. Open the live app — the home screen loads with no error banner.
2. Note the mode badge: DEMO MODE (no API) or LIVE MODE (API reachable).
3. **Sample plan:** "Try with a sample plan" → confirm scale 1:50 →
   ask "How many fixtures are on sheet A-101?" → the answer must carry
   **both** citations (image region + spec clause) or an honest "not found".
4. **Sample requirement:** type `steel brackets, 50 units, Fremont, by
   Friday, under $400` → parsed fields editable → ranked shortlist shows
   cost AND quality with evidence, best-value vs cheapest vs
   highest-quality side by side → twin simulation loads for the top 3.
5. **Approval gate:** start a buyer run (mocked email by default — no real
   email is sent) → draft shown before sending → **no order is created
   until you tap Approve**.
6. **Live contact flow:** on the Buyer Agent tab click
   **"📧 Contact Bay Steel Supply — review & approve"** → the approval
   panel opens and **nothing is sent** → click **"Cancel — send
   nothing"** and confirm nothing was sent → click Contact again,
   **"✅ Approve & send"** → the supplier email is recorded and the
   user email (quotation + supplier details) appears under "Emails to
   you this session". On Suppliers & Twin, click **"⬇ Download
   shortlist as Excel (.xlsx)"** and open the file — it has 22 columns
   and one row per shortlisted supplier.
7. **Health:** `GET /health` on the API returns `{"status": "ok"}` and
   `"storage": "none — live, session-only"`.

If any step fails, do not share the link — file it as an issue and fix it
(see `docs/UAT.md`).

## 5. What is NOT deployed in v1

- No Prometheus/Grafana (Phase 2, `docker-compose --profile observability`).
- No WhatsApp supplier contact (Phase 2 — needs a Business API number).
- No React frontend (Phase 2, only after the Streamlit MVP proves the flow).
- No per-user servers. One shared demo + per-user data rows.
