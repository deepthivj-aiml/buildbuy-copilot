# BuildBuy Copilot — Manual UAT Checklist

Run this by hand, on a phone first (mobile-first product), then on desktop.
Every item must pass. A failure is filed as an issue — never worked around,
never skipped silently. Record the date, device, and result per item.

**Test data:** synthetic demo data only. Never a real client plan, never a
real supplier contact, never a real payment. Email sending is mocked
locally (`EMAIL_PROVIDER=mock`); no real email is sent during UAT.

## 1. First run — 5 minutes, phone

| # | Check | Pass means |
|---|---|---|
| 1.1 | Open the app on a phone | Home screen loads, no error banner, no step requires a desktop |
| 1.2 | Free-tier counter visible on Start | "1 plan · 3 supplier searches · 1 buyer run left this month" (or current counts) |
| 1.3 | "Try with a sample plan" | Sample plan loads without an upload; plan name shown on Screen 2 |
| 1.4 | Upload a JPG plan ≤10 MB | Accepted; file name + size shown |
| 1.5 | Upload a file >10 MB | Rejected with a plain-language message, nothing crashes |
| 1.6 | Type `steel brackets, 50 units, Fremont, by Friday, under $400` → Parse | Parsed fields shown (item / quantity / location / deadline / budget), each editable |
| 1.7 | Time from open to first answer | Under 5 minutes on the phone |

## 2. Plan & Materials — citations and estimates

| # | Check | Pass means |
|---|---|---|
| 2.1 | Confirm scale 1:50 | Scale-confirm banner appears once; Confirm works; measurements wait for it |
| 2.2 | Ask "How many fixtures are on sheet A-101?" | Answer names the sheet, cites the image region AND the spec clause — or says "not found" |
| 2.3 | Ask a question the plan cannot answer | Answer is "not found / I can't read that" with the sheet named — never a guess |
| 2.4 | Takeoff table | Every line shows quantity, unit, method, confidence, and the label "estimate, not a surveyed quantity" |
| 2.5 | Low-confidence line (Plywood sheets, conf 0.58) | Flagged amber with page + location; "review flagged lines" path visible |
| 2.6 | Edit a takeoff line, save | Saved value persists; correction is noted for the Accuracy tab |
| 2.7 | Export takeoff as CSV | CSV downloads and matches the table shown |
| 2.8 | Thumbs down on an answer | Recorded; answer appears in the Accuracy → Worst Answers list |

## 3. Suppliers & Twin — cost AND quality

| # | Check | Pass means |
|---|---|---|
| 3.1 | Ranked shortlist | Table shows Supplier \| Unit \| MOQ \| Lead \| Fit, plus landed cost and quality score per supplier |
| 3.2 | Quality score with evidence | Every quality score has its evidence listed (cert / on-time rate with n= / defect rate); no score without evidence |
| 3.3 | Best-value vs cheapest vs highest-quality | Three cards side by side; the three winners are named and can differ |
| 3.4 | Best-value rank | Ranked by cost AND quality (0.45 cost + 0.35 quality + 0.20 lead), not cost alone |
| 3.5 | Below-MOQ suppliers | Listed under "Not eligible for this quantity" with the reason — never silently dropped, never ranked |
| 3.6 | Map-like distance list | Suppliers ordered by distance from the job site; distance + lead + landed + quality per row |
| 3.7 | Supplier card contact | Contact shown only where public / supplier-provided / user-added; otherwise "not public — request via email" |
| 3.8 | Twin what-if sliders | Price +10%, delivery +3 days, quantity +20% re-compute landed cost, delivery date, cost risk AND quality risk |
| 3.9 | Cheap but late / low quality | That supplier's total risk is higher than a pricier, on-time, high-quality supplier's under the same what-if |
| 3.10 | Recommendation + runner-up | Twin names a recommendation AND a runner-up, with reasons and method shown |

## 4. Buyer Agent — draft, toggles, approval

| # | Check | Pass means |
|---|---|---|
| 4.1 | Draft email shown before sending | Draft visible and editable; nothing is sent before you tap Send |
| 4.2 | Contact-sharing toggles | Default OFF per supplier; with OFF, your contact never appears in the draft/email |
| 4.3 | Toggle ON for one supplier only | Contact appears for that supplier only, not for the others |
| 4.4 | Negotiation limits | Max price + latest date set by you; an offer above the cap cannot be approved (Approve disabled) |
| 4.5 | Inbox, 3 columns | Thread list (supplier / time / snippet / status) · message thread · supplier info panel |
| 4.6 | No-reply supplier | Shown honestly as "no reply in 24h" with a "Try next supplier" action; never presented as a quote |
| 4.7 | Approval pane | Best-value vs cheapest vs highest-quality side by side; you pick one, then Approve or Reject |
| 4.8 | Approve | Order created, confirmation sent (mocked in UAT), order appears in My Orders |
| 4.9 | Reject | No order created; status REJECTED; you can pick another supplier |
| 4.10 | "We never handle payment" | Stated on the approval screen; no payment field, no card input anywhere |
| 4.11 | No order without a tap | There is no path in the UI that creates an order without Approve |

## 5. My Orders — timeline, chase, invoice

| # | Check | Pass means |
|---|---|---|
| 5.1 | Timeline | requirement → plan → materials → suppliers → quotes → negotiation → approval → order → delivery → invoice, with status per step |
| 5.2 | Invoice received order | Shows invoice number, amount, received date — recorded from the supplier only |
| 5.3 | Order with no invoice yet | States plainly "No invoice yet" — no invented invoice number or amount |
| 5.4 | Chase delivery | Chase action drafts/sends a follow-up; recorded on the timeline |
| 5.5 | Mark delivered | Only a human tap marks delivery; the app never claims to prove arrival |
| 5.6 | Records export | Order exports as JSON with the full audit trail |

## 6. Accuracy — observability

| # | Check | Pass means |
|---|---|---|
| 6.1 | 4 headline cards | Groundedness / thumbs-up rate / takeoff mean error / cost per job, each with "n = …" |
| 6.2 | 2 trend charts | Accuracy over time + cost/latency over time render from the metrics |
| 6.3 | Per-module table | One row per module with its metrics and worst-in-7-days |
| 6.4 | Worst Answers list | Lowest-scoring answers with question, answer, citations, thumbs, reason |
| 6.5 | Eval Run History | Runs listed with date, eval set, groundedness, retrieval top-1, guardrail block rate, cache hit rate, pass/fail |
| 6.6 | Empty state | With metrics cleared, the tab says "No data yet" — never a made-up percentage |

## 7. Settings — privacy and data

| # | Check | Pass means |
|---|---|---|
| 7.1 | Contact + sharing defaults | Editable; defaults OFF; plain-language "who sees this" explainer |
| 7.2 | BYO key status | Shows "set / not set" only — the key value is never displayed |
| 7.3 | Export all my data | JSON downloads with requirement, materials, orders, feedback |
| 7.4 | Delete a purchase / delete my data | Clears the session data; no user data used to train a shared model |

## 8. Results log

| Date | Device | Tester | Items passed / total | Failures (issue #) |
|---|---|---|---|---|
| _yyyy-mm-dd_ | _phone model / desktop_ | | _/ 40_ | |
