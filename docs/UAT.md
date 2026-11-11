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
| 2.9 | Type `concrete, 10 m3, Fremont` → Parse → Plan & Materials | Takeoff shows Concrete (footings) **10 m3** (not the demo plan's 2.4 m3); the method keeps the old plan value ("overrides plan estimate of 2.4 m3") |
| 2.10 | Type a requirement with no quantity (`timber joists`) → Parse | Takeoff is unchanged; no quantity is invented; a plain-language note says so |
| 2.11 | Load the sample plan after typing a quantity | The typed quantity is still applied to the plan takeoff — the plan load never silently discards it |

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
| 3.11 | Supplier card contact + how we contact them | Phone / address show "not held" when missing (never invented); a line says how they will be contacted (Email, from, to) and points to the full preview on the Buyer Agent tab |

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
| 4.12 | Per-supplier email preview | Each top-3 supplier has a card showing contact details (email / phone / address, "not held" when missing), channel (Email), from, to, subject, and the FULL email body — before anything is sent |
| 4.13 | Edit the email, Save, Reset | Editing subject/body and tapping Save sends the edited text; Reset to draft rebuilds the email from the requirement |
| 4.14 | Sharing toggle changes the preview | Toggling "Share my contact" ON for one supplier puts your name/email/phone in that supplier's preview only; OFF shows "a customer" |
| 4.15 | Supplier with no email held | The card says "Email not held" and its Send button is disabled; "Send to top 3" lists it as blocked — no address is ever guessed |
| 4.16 | Send uses the edited text, sharing OFF strips contact | An edited body is what gets sent; with sharing OFF, any name/email/phone typed into the edited draft is removed before sending |

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
| 6.1 | 8-metric table | All 8 metrics shown separately — Groundedness, Retrieval accuracy, Answer accuracy, Takeoff estimate accuracy, Supplier ranking accuracy, Buyer-agent accuracy, Guardrail block rate, Cost / cache / speed — each with formula, source, n=, target, status. No single blended accuracy score anywhere |
| 6.2 | 4 headline cards | Groundedness / thumbs-up rate / takeoff mean error / cost per job, each with "n = …" — the same 4 metrics as the table, not a different score |
| 6.3 | 2 trend charts | Accuracy over time + cost/latency over time render from the metrics, with alert thresholds as **dashed lines** (groundedness 90%, retrieval top-1 85%, eval pass 90%, p95 latency 10 s) |
| 6.4 | Per-module table | One row per module with its metrics and worst-in-7-days |
| 6.5 | Worst Answers list | 10 lowest-scoring answers with question, answer, citations, thumbs, reason; thumbs-down first, then ungrounded |
| 6.6 | "Add to eval set" | Tapping it on a Worst Answer records the labelled example for the next eval run; tapping it again on the same answer is refused (never duplicated) |
| 6.7 | "Mark fixed" | Tapping it records the fix; the row keeps its status and cannot be added twice |
| 6.8 | Eval Run History | Runs listed with date, eval set, groundedness, retrieval top-1, guardrail block rate, cache hit rate, pass/fail; a failed run blocks the deploy |
| 6.9 | Drill-down | Pick a step (ask / retrieval / takeoff / guardrail / send_supplier_email / twin_simulate) and see raw events: request_id, step, model, latency, grounded, cache hit, guardrail action, cost — no prompt, plan text or email body shown |
| 6.10 | Empty state | With metrics cleared, the tab says "No data yet" — never a made-up percentage |
| 6.11 | Live vs demo | With the backend up, the tab shows a LIVE badge and measured values; with no backend, it says the data is synthetic demo data |
| 6.12 | Buyer-agent invariant | After approving and confirming an order, Buyer-agent accuracy shows 100.0% (approval-before-order); the quotes-agreed rate is shown separately, not blended in |
| 6.13 | Takeoff honesty | Takeoff estimate accuracy shows "no data yet" until a takeoff line is actually corrected — no invented error rate |

## 7. Settings — privacy and data

| # | Check | Pass means |
|---|---|---|
| 7.1 | Contact + sharing defaults | Editable; defaults OFF; plain-language "who sees this" explainer |
| 7.2 | BYO key status | Shows "set / not set" only — the key value is never displayed |
| 7.3 | Export all my data | JSON downloads with requirement, materials, orders, feedback |
| 7.4 | Delete a purchase / delete my data | Clears the session data; no user data used to train a shared model |

## 8. Visual / theme (restyle 2026-11-11)

Colour is decoration only: every chip and step keeps its text label,
demo/synthetic data keeps its amber DEMO badge, and no colour implies
a real result.

| # | Check | Pass means |
|---|---|---|
| 8.1 | Hero banner + theme | Gradient hero (indigo → violet → teal) on every tab with the app name, tagline and a DEMO/LIVE pill that matches the actual mode; light indigo theme throughout |
| 8.2 | Buyer-journey stepper | 9 steps (Requirement → Materials → Suppliers → Twin → Buyer agent → Approval → Order → Delivery → Invoice) with done / current / to-do states; the current step matches where you are |
| 8.3 | Status chips | Best value (green) / cheapest (blue) / highest quality (purple) on supplier cards; order and inbox thread statuses shown as chips WITH their text labels (never colour-only) |
| 8.4 | Buttons | Primary actions are gradient indigo; secondary actions are white with an indigo outline; hover lift on cards and buttons |
| 8.5 | Tab navigation | Tapping any of the 7 tabs switches to it on the first tap, every time (no dropped tab switch) |
| 8.6 | Honest labels survive the restyle | "estimate, not a surveyed quantity" on every takeoff line, "no data yet" on empty Accuracy metrics, DEMO MODE badge in demo mode — all still present |

## 9. Results log

| Date | Device | Tester | Items passed / total | Failures (issue #) |
|---|---|---|---|---|
| _yyyy-mm-dd_ | _phone model / desktop_ | | _/ 74_ | |
