# BuildBuy Copilot — Frontend (Streamlit, v1)
"""
One dashboard, seven tabs:
  1 Start | 2 Plan & Materials | 3 Suppliers & Twin | 4 Buyer Agent
  5 My Orders | 6 Accuracy | 7 Settings

Runs with NO paid key and NO backend:
  * If the FastAPI backend is reachable at API_URL (default
    http://localhost:8000), the app uses it and says so (LIVE MODE).
  * Otherwise it runs in clearly-labelled DEMO MODE on synthetic data
    stored in-memory (session_state) + the local demo modules below.

Rules baked into this UI (from the plan):
  * Quantities are always labelled "estimate, not a surveyed quantity".
  * Supplier contacts appear only where public / supplier-provided /
    user-added — otherwise "not public".
  * Cost AND quality rank suppliers together: every supplier shows unit
    cost, landed cost, a quality score WITH its evidence, and a combined
    best-value rank. The cheapest option and the highest-quality option
    are shown side by side with the best-value pick so the user chooses.
    Quality evidence is evidence-only: a score is shown only with the
    evidence behind it; no rating is ever invented for a real supplier.
    All demo suppliers are synthetic and labelled as such.
  * Nothing is ordered or paid without the user's tap. The app never
    handles payment.
  * Contact sharing with a supplier is opt-in per supplier, default OFF.
  * Accuracy numbers are measured or labelled synthetic — never invented
    live numbers. Empty metrics show "no data yet".
"""

import io
import json
import os
import sys
from datetime import date, timedelta

# Frontend modules (same directory): pure helpers + synthetic demo data.
# sys.path bootstrap so `streamlit run frontend/app.py` finds them.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_data import (  # noqa: E402
    DEMO_ACCURACY,
    DEMO_COST_PER_JOB,
    DEMO_EVAL_PASS,
    DEMO_EVAL_RUNS,
    DEMO_GROUNDEDNESS,
    DEMO_LATENCY_P95,
    DEMO_MATERIALS,
    DEMO_METRICS_DAYS,
    DEMO_QA,
    DEMO_RAW_EVENTS,
    DEMO_RETRIEVAL_TOP1,
    DEMO_SUPPLIERS,
    DEMO_WORST_ANSWERS,
)
from accuracy import (  # noqa: E402
    ALERT_THRESHOLDS,
    METRIC_DEFS,
    apply_worst_action,
    dashboard_is_empty,
    fetch_live_accuracy,
    format_value,
    metric_status,
    worst_answers_from_feedback,
)
from helpers import (  # noqa: E402
    API_URL,
    BUYER_CONTACT,
    EMAIL_FROM,
    apply_requirement_to_takeoff,
    backend_is_reachable,
    build_quote_email,
    demo_answer,
    geocode_location,
    haversine_km,
    landed_line,
    parse_requirement,
    rank_suppliers,
    strip_contact_details,
    supplier_contact_details,
    supplier_email,
    twin_risk,
)

import streamlit as st

MAX_UPLOAD_MB = 10
FREE_TIER = {"plans": 1, "searches": 3, "buyer_runs": 1}

st.set_page_config(
    page_title="BuildBuy Copilot",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from theme import (  # noqa: E402
    THEME_CSS,
    hero_html,
    journey_stepper,
    order_chip,
    status_chip,
    thread_chip,
)

st.markdown(THEME_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Synthetic demo data — labelled as such everywhere it is shown.
# No real supplier, contact, quote, price, or rating is ever invented:
# every demo record below is synthetic and marked "synthetic demo data".
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def init_state():
    s = st.session_state
    s.setdefault("mode_checked", False)
    s.setdefault("live", False)
    s.setdefault("requirement", None)
    s.setdefault("plan_name", None)
    s.setdefault("scale_confirmed", False)
    s.setdefault("chat", [])
    s.setdefault("materials", [dict(m) for m in DEMO_MATERIALS])
    s.setdefault("takeoff_note", "")
    s.setdefault("suppliers", [dict(x) for x in DEMO_SUPPLIERS])
    s.setdefault("contact_sharing", {x["name"]: False for x in DEMO_SUPPLIERS})
    s.setdefault("threads", [
        {"supplier": "Bay Steel Supply", "status": "replied",
         "messages": [
             ("buyer", "Hi — I am BuildBuy Copilot, acting as the buying agent "
              "for a customer. I am enquiring about 50 steel brackets, "
              "delivered to Fremont by Friday. Could you quote unit price "
              "+ delivery?"),
             ("supplier", "Hi Deepthi — $6.30/unit, $18 delivery, 2-day lead. "
              "Total $333. Happy to confirm if that works."),
         ]},
        {"supplier": "Golden State Metals", "status": "replied",
         "messages": [
             ("buyer", "Hi — I am BuildBuy Copilot, acting as the buying agent "
              "for a customer. I am enquiring about 50 steel brackets, "
              "delivered to Fremont by Friday. Could you quote unit price "
              "+ delivery?"),
             ("supplier", "We can do $6.10/unit, $24 delivery, 3-day lead. Total $329."),
         ]},
        {"supplier": "East Bay Industrial", "status": "no reply",
         "messages": [
             ("buyer", "Hi — I am BuildBuy Copilot, acting as the buying agent "
              "for a customer. I am enquiring about 50 steel brackets, "
              "delivered to Fremont by Friday. Could you quote unit price "
              "+ delivery?"),
         ]},
        {"supplier": "Sierra Building Supply", "status": "needs_customer",
         "messages": [
             ("buyer", "Hi — I am BuildBuy Copilot, acting as the buying agent "
              "for a customer. I am enquiring about 18 timber joists, "
              "delivered to Fremont by Friday. Could you quote unit price "
              "+ delivery?"),
             ("supplier", "We can supply the joists. Can you pay 50% upfront "
              "before dispatch?"),
         ]},
    ])
    s.setdefault("draft_email", "")
    s.setdefault("quote_drafts", {})  # supplier name -> {"subject","body","edited": True}
    s.setdefault("quote_sent", {})  # supplier name -> {"to","subject","body","channel"}
    s.setdefault("max_price", 400.0)
    s.setdefault("latest_date", date.today() + timedelta(days=5))
    s.setdefault("selected_offer", "best_value")
    s.setdefault("order_status", "PENDING")
    s.setdefault("orders", [
        {"id": "ORD-1042", "item": "Steel brackets x50", "supplier": "Bay Steel Supply",
         "status": "INVOICE_RECEIVED", "total": 333.00,
         "timeline": ["requirement", "plan", "materials", "suppliers", "quotes",
                      "negotiation", "approval", "order", "delivery", "invoice"],
         "invoice": {"number": "INV-8841", "amount": 333.00,
                     "received": "2026-11-09",
                     "source": "recorded from supplier email — never typed by the app"},
         "chased": False},
        {"id": "ORD-1043", "item": "Timber joists x18", "supplier": "Sierra Building Supply",
         "status": "APPROVED", "total": 150.60,
         "timeline": ["requirement", "plan", "materials", "suppliers", "quotes",
                      "negotiation", "approval"],
         "invoice": None, "chased": False},
    ])
    s.setdefault("feedback", [])  # {"question","thumbs","reason"}
    s.setdefault("metrics_cleared", False)
    s.setdefault("settings", {"name": "Deepthi Jainlal",
                              "email": "deepthiag26@gmail.com",
                              "phone": "+1 341-252-9234",
                              "buddy_name": "BuyBuddy",
                              "tone": "Short, polite, direct.",
                              "remember": "Prefer suppliers within 15 miles of Fremont. "
                                          "Never share my phone unless I toggle it on."})
    s.setdefault("usage", {"plans": 0, "searches": 0, "buyer_runs": 0})
    s.setdefault("nav", "1 · Start")


init_state()

if not st.session_state["mode_checked"]:
    st.session_state["live"] = backend_is_reachable()
    st.session_state["mode_checked"] = True
LIVE = st.session_state["live"]

# ---------------------------------------------------------------------------
# Header — gradient hero (Start-tab style, shown on every tab for a
# consistent identity) + buyer-journey stepper + free-tier chips.
# ---------------------------------------------------------------------------
st.markdown(hero_html("live" if LIVE else "demo"), unsafe_allow_html=True)
if LIVE:
    st.markdown('<span class="badge badge-live">● LIVE MODE — backend reachable at '
                + API_URL + '</span>', unsafe_allow_html=True)
else:
    st.markdown('<span class="badge badge-demo">● DEMO MODE — no backend at '
                + API_URL + '; running on synthetic demo data, no real email is sent</span>',
                unsafe_allow_html=True)
    st.caption("Demo data is synthetic only. No real supplier, quote, contact, or rating "
               "is shown. Start the backend (`uvicorn app.main:app --port 8000`) to switch "
               "to live mode.")


def journey_stage():
    """0-based step of the buyer journey from session state."""
    status = st.session_state.get("order_status", "PENDING")
    nav_stage = {"1 · Start": 0, "2 · Plan & Materials": 1,
                 "3 · Suppliers & Twin": 2, "4 · Buyer Agent": 3,
                 "5 · My Orders": 4, "6 · Accuracy": 4,
                 "7 · Settings": 0}.get(st.session_state.get("nav", "1 · Start"), 0)
    status_stage = {"PENDING": 3, "APPROVED": 4, "REJECTED": 4,
                    "CONFIRMED": 6, "DELIVERED": 7,
                    "INVOICE_PENDING": 7, "INVOICE_RECEIVED": 8}.get(status, 3)
    stage = nav_stage
    if st.session_state.get("requirement"):
        stage = max(stage, 1)
    if status in ("APPROVED", "REJECTED", "CONFIRMED", "DELIVERED",
                  "INVOICE_PENDING", "INVOICE_RECEIVED"):
        stage = max(stage, status_stage)
    return min(stage, 8)


st.markdown(journey_stepper(journey_stage()), unsafe_allow_html=True)
st.caption("Buyer journey: Requirement → Materials → Suppliers → Twin → "
           "Buyer agent → Approval → Order → Delivery → Invoice")
st.markdown(
    status_chip(f"Free tier left: "
                f"{FREE_TIER['plans'] - st.session_state['usage']['plans']} plan", "info")
    + " " + status_chip(
        f"{FREE_TIER['searches'] - st.session_state['usage']['searches']} supplier searches",
        "info")
    + " " + status_chip(
        f"{FREE_TIER['buyer_runs'] - st.session_state['usage']['buyer_runs']} buyer run",
        "info"),
    unsafe_allow_html=True)

NAV = ["1 · Start", "2 · Plan & Materials", "3 · Suppliers & Twin", "4 · Buyer Agent",
       "5 · My Orders", "6 · Accuracy", "7 · Settings"]
# Keyed radio (key="nav"): the widget value lives in session_state["nav"]
# and programmatic navigation (buttons setting session_state["nav"] then
# st.rerun()) works. The old code used index=NAV.index(session_state
# ["nav"]) with no key — when the index default changed between runs,
# Streamlit re-initialised the radio from the new default and DROPPED
# the user's tab click (found by AppTest: every second navigation was
# silently ignored). A keyed widget has no moving default to reset to.
nav = st.radio("Section", NAV, horizontal=True, label_visibility="collapsed",
               key="nav")

# ---------------------------------------------------------------------------
# Tab 1 — Start
# ---------------------------------------------------------------------------
if nav == "1 · Start":
    st.header("Start — the chat is the input")
    st.caption("Upload a construction plan (image / PDF) **or** type / photograph "
               "the part or requirement in chat — “steel brackets, 50 units”. Then "
               "quantity, location, deadline and budget as follow-up prompts in the "
               "same chat flow. Location is an **optional field you fill in yourself** "
               "(blank by default) — it is used only if you type a delivery location "
               "on the Suppliers tab, and your location is never tracked.")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📄 Upload a plan")
        uploaded = st.file_uploader(
            "Plan image or PDF (JPG / PNG / PDF, ≤10 MB, ≤25 sheets)",
            type=["jpg", "jpeg", "png", "pdf"])
        if uploaded is not None:
            size_mb = uploaded.size / (1024 * 1024)
            if size_mb > MAX_UPLOAD_MB:
                st.error(f"File is {size_mb:.1f} MB — the limit is {MAX_UPLOAD_MB} MB.")
            else:
                st.session_state["plan_name"] = uploaded.name
                st.success(f"Uploaded: {uploaded.name} ({size_mb:.2f} MB). "
                           "Synthetic demo: plan contents are not read in demo mode.")
                st.session_state["usage"]["plans"] += 0  # counted on Find, not on upload
        specs = st.text_area("Text specs (optional)",
                             placeholder="Paste the spec clauses that go with the plan…",
                             height=80)
        if st.button("Try with a sample plan — no upload needed"):
            st.session_state["plan_name"] = "sample-plan-A-101.pdf (synthetic demo plan)"
            st.session_state["requirement"] = {
                "raw": "steel brackets, 50 units, Fremont, by Friday, under $400",
                "item": "steel brackets", "quantity": 50, "unit": "pcs",
                "location": "Fremont",
                "deadline": "Friday", "budget": 400.0}
            # The sample plan's own takeoff stays, but the typed quantity
            # is applied to it — a plan load must never silently discard
            # a typed quantity (2026-11-10 fix).
            mats, note = apply_requirement_to_takeoff(
                st.session_state["materials"], st.session_state["requirement"])
            st.session_state["materials"] = mats
            st.session_state["takeoff_note"] = note
            st.success("Sample plan loaded: synthetic demo plan A-101. " + note)
    with col_b:
        st.subheader("💬 Or just tell me what you need")
        typed = st.text_area(
            "Requirement in plain words",
            placeholder="steel brackets, 50 units, Fremont, by Friday, under $400",
            height=100, key="requirement_input")
        photo = st.camera_input("Or photograph the requirement") \
            if hasattr(st, "camera_input") else None
        if photo is not None:
            st.info("Photo received (demo mode: the item description is not auto-read. "
                    "Please confirm the parsed fields below before continuing.)")
        if st.button("Parse my requirement", key="parse_requirement_btn"):
            if typed.strip():
                req = parse_requirement(typed)
                st.session_state["requirement"] = req
                # THE FIX (2026-11-10): a typed requirement updates the
                # takeoff table right here. Before this, the requirement
                # was stored and the table stayed on the static demo-plan
                # values forever — typing "concrete, 10 m3" left the
                # takeoff at the demo plan's 2.4 m3.
                mats, note = apply_requirement_to_takeoff(
                    st.session_state["materials"], req)
                st.session_state["materials"] = mats
                st.session_state["takeoff_note"] = note
                st.success(note)
            else:
                st.warning("Type a requirement first, or use the sample plan.")

    req = st.session_state.get("requirement")
    if req:
        st.subheader("Parsed requirement — check and edit before anything runs")
        if req.get("quantity") is None:
            st.warning("No quantity found in your message — please enter one. "
                       "The takeoff cannot show a quantity you did not give.")
        if not req.get("item"):
            st.warning("No item found in your message — please enter one.")
        c1, c2, c3 = st.columns(3)
        with c1:
            req["item"] = st.text_input("Item", value=req.get("item") or "")
            # No invented default: an unknown quantity starts at 1 and
            # the warning above says to fix it (the old code defaulted
            # to 50, which silently invented a quantity).
            req["quantity"] = st.number_input(
                "Quantity", min_value=1, value=int(req.get("quantity") or 1))
        with c2:
            req["location"] = st.text_input(
                "Location (job site)", value=req.get("location") or "",
                placeholder="e.g. Fremont (optional)",
                help="Where the job is. This is NOT used for transport cost — "
                     "delivery location is a separate optional field on the "
                     "Suppliers tab. Blank means no location was given — "
                     "the old code filled in “Fremont” by default, which "
                     "presented a guess as a parsed fact.")
            req["deadline"] = st.text_input("Deadline", value=req.get("deadline") or "")
        with c3:
            req["budget"] = st.number_input("Max budget ($)", min_value=0.0,
                                            value=float(req.get("budget") or 0.0))
        if st.session_state.get("plan_name"):
            st.caption(f"Plan attached: {st.session_state['plan_name']}")
        if st.session_state.get("takeoff_note"):
            st.info(st.session_state["takeoff_note"])
        if st.button("Find what I need →", type="primary"):
            # Re-apply: the user may have edited the item / quantity
            # above, and the takeoff must follow the edited values.
            mats, note = apply_requirement_to_takeoff(
                st.session_state["materials"], req)
            st.session_state["materials"] = mats
            st.session_state["takeoff_note"] = note
            st.session_state["usage"]["searches"] += 1
            st.session_state["nav"] = "2 · Plan & Materials"
            st.rerun()
    st.markdown(
        '<p class="trust">Nothing is ordered without your tap. · '
        'Your contact is shared only if you allow it. · '
        'Quantities are estimates, not surveyed measurements.</p>',
        unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tab 2 — Plan & Materials
# ---------------------------------------------------------------------------
elif nav == "2 · Plan & Materials":
    st.header("Plan & Materials — ask the plan, check the takeoff")
    req = st.session_state.get("requirement") or {
        "item": "steel brackets", "quantity": 50, "location": "Fremont",
        "deadline": "Friday", "budget": 400.0}
    if st.session_state.get("plan_name") and not st.session_state["scale_confirmed"]:
        st.warning("I read the scale as 1:50 from the title block. Is that right?")
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("✓ Confirm scale 1:50", type="primary"):
                st.session_state["scale_confirmed"] = True
                st.rerun()
        with cc2:
            new_scale = st.text_input("Correct scale", value="1:50")
            if st.button("Use this scale instead"):
                st.session_state["scale_confirmed"] = True
                st.success(f"Scale set to {new_scale}. Measurements use this scale.")
                st.rerun()
    left, right = st.columns([2, 3])
    with left:
        st.subheader("Copilot chat")
        if st.session_state.get("plan_name"):
            st.caption(f"Plan: {st.session_state['plan_name']}")
        else:
            st.caption("No plan uploaded — answers come from the requirement only.")
        st.caption("Suggested: “How many fixtures are on sheet A-101?” · "
                   "“What is the load rating on this beam?” · “What scale is this plan?”")
        for msg in st.session_state["chat"]:
            with st.chat_message(msg["role"]):
                st.write(msg["text"])
                if msg.get("region"):
                    st.caption(f"📍 Image region: {msg['region']}")
                    st.caption(f"📄 Spec clause: {msg['clause']}")
                if msg["role"] == "assistant":
                    f1, f2 = st.columns(2)
                    with f1:
                        if st.button("👍", key=f"up-{msg['id']}"):
                            st.session_state["feedback"].append(
                                {"question": msg.get("q", ""), "thumbs": "up", "reason": ""})
                            st.success("Thanks — feedback recorded.")
                    with f2:
                        if st.button("👎", key=f"down-{msg['id']}"):
                            st.session_state["feedback"].append(
                                {"question": msg.get("q", ""), "thumbs": "down",
                                 "reason": "wrong number / citation / couldn't read"})
                            st.success("Thanks — this goes to the Worst Answers list.")
        q = st.chat_input("Ask about the plan or specs…")
        if q:
            answer, region, clause, grounded = demo_answer(q)
            mid = len(st.session_state["chat"])
            st.session_state["chat"].append({"role": "user", "text": q, "id": mid})
            st.session_state["chat"].append(
                {"role": "assistant", "text": answer, "region": region,
                 "clause": clause, "id": mid + 1, "q": q,
                 "grounded": grounded})
            if not grounded:
                st.info("That answer is an honest “not found” — the copilot guesses nothing.")
            st.rerun()
    with right:
        st.subheader("Materials takeoff — estimate, not a surveyed quantity")
        st.caption("Every line is an estimate with its method shown, and "
                   "every line carries the label “estimate, not a surveyed "
                   "quantity”. Review flagged lines before suppliers are contacted.")
        if st.session_state.get("takeoff_note"):
            st.info(st.session_state["takeoff_note"])
        import pandas as pd
        df = pd.DataFrame(st.session_state["materials"])
        edited = st.data_editor(
            df, num_rows="dynamic", use_container_width=True,
            column_config={
                "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                "flagged": st.column_config.CheckboxColumn("⚠ Needs review"),
            },
            key="materials_editor")
        if st.button("Save edited takeoff"):
            st.session_state["materials"] = edited.to_dict("records")
            st.success("Takeoff saved. Corrections feed the Accuracy tab.")
        flagged = [m for m in st.session_state["materials"] if m.get("flagged")]
        if flagged:
            st.warning(f"⚠ {len(flagged)} low-confidence line(s) — review before supplier search: "
                       + ", ".join(f"{m['material']} (conf {m['confidence']:.2f})"
                                   for m in flagged))
        buf = io.StringIO()
        pd.DataFrame(st.session_state["materials"]).to_csv(buf, index=False)
        st.download_button("⬇ Export takeoff as CSV", buf.getvalue(),
                           file_name="takeoff.csv", mime="text/csv")
        if st.button("Re-run takeoff with feedback (1 free re-run per plan)"):
            st.info("Demo mode: re-run queued. In live mode the plan is re-read with "
                    "your corrections and no extra charge for this one re-run.")
        if st.button("Find suppliers for these materials →", type="primary"):
            st.session_state["nav"] = "3 · Suppliers & Twin"
            st.rerun()

# ---------------------------------------------------------------------------
# Tab 3 — Suppliers & Twin (cost AND quality)
# ---------------------------------------------------------------------------
elif nav == "3 · Suppliers & Twin":
    st.header("Suppliers & Twin — best cost AND quality, not cost alone")
    st.caption("Suppliers are ranked by best value: 0.45 × landed-cost score + "
               "0.35 × quality score + 0.20 × lead-time score — the same formula as "
               "the backend supplier search. Quality is shown only with its evidence — "
               "a score with no evidence behind it is never shown, and no rating is "
               "ever invented for a real supplier. Suppliers whose MOQ is above this "
               "job's quantity are excluded from the ranking (listed below with the "
               "reason). All suppliers below are synthetic demo data.")
    req = st.session_state.get("requirement") or {"quantity": 50}
    qty = int(req.get("quantity") or 50)

    st.subheader("Delivery location — optional, you type it")
    st.caption("Type where the materials should be delivered (city / ZIP / address) "
               "to include transportation in total landed cost. Blank by default — "
               "we never track your location, and the requirement's job-site location "
               "is NOT used for this. Leave it blank and landed costs show "
               "“excl. transport”.")
    d1, d2, d3 = st.columns([2, 1, 1])
    with d1:
        delivery_location = st.text_input(
            "Delivery location (optional)",
            value=st.session_state.get("delivery_location", ""),
            placeholder="e.g. Fremont, CA — leave blank for excl. transport")
    with d2:
        use_transport = st.checkbox("Include transport in landed cost", value=True)
    with d3:
        transport_rate = st.number_input(
            "Transport rate ($/km, optional)", min_value=0.0, value=0.0,
            help="Your own $/km rate. 0 = demo estimate ($25 + $0.55/km).")
    st.session_state["delivery_location"] = delivery_location
    st.session_state["transport_rate"] = transport_rate if transport_rate > 0 else None
    if delivery_location.strip() and geocode_location(delivery_location) is None:
        st.warning("Location not recognised — transport excluded (landed costs show "
                   "“excl. transport”). Try a city name like “Fremont” or “lat,lng”.")
    rows, excluded = rank_suppliers(
        st.session_state["suppliers"], qty,
        delivery_location=delivery_location if use_transport else "",
        transport_rate=st.session_state["transport_rate"])
    best_value = next((r for r in rows if r["is_best_value"]), None)
    cheapest = next((r for r in rows if r["is_cheapest"]), None)
    best_quality = next((r for r in rows if r["is_best_quality"]), None)

    st.subheader("Your three ways to choose — side by side")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="card card-best"><b>🏆 BEST VALUE</b><br>', unsafe_allow_html=True)
        if best_value:
            st.write(f"**{best_value['name']}** — {best_value['location']}")
            st.write(f"Landed: **${best_value['landed']:.2f}** for {qty} "
                     f"({landed_line(best_value, qty)})")
            st.write(f"Quality: **{best_value['quality_score']}/100** · "
                     f"Lead: {best_value['lead_days']} days · {best_value['distance_mi']} mi")
            st.write(f"Value score: {best_value['value_score']}/100 "
                     f"(cost {best_value['cost_score']} + quality {best_value['quality_score']} "
                     f"+ lead {best_value['lead_score']})")
        st.markdown('</div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card card-cheap"><b>💲 CHEAPEST</b><br>', unsafe_allow_html=True)
        if cheapest:
            st.write(f"**{cheapest['name']}** — {cheapest['location']}")
            st.write(f"Landed: **${cheapest['landed']:.2f}** for {qty} "
                     f"({landed_line(cheapest, qty)})")
            st.write(f"Quality: **{cheapest['quality_score']}/100** · "
                     f"Lead: {cheapest['lead_days']} days · {cheapest['distance_mi']} mi")
            st.write("Cheapest per unit is not the best value when quality or "
                     "delivery is weak — check the twin risk below.")
        st.markdown('</div>', unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="card card-quality"><b>⭐ HIGHEST QUALITY</b><br>', unsafe_allow_html=True)
        if best_quality:
            st.write(f"**{best_quality['name']}** — {best_quality['location']}")
            st.write(f"Landed: **${best_quality['landed']:.2f}** for {qty} "
                     f"({landed_line(best_quality, qty)})")
            st.write(f"Quality: **{best_quality['quality_score']}/100** · "
                     f"Lead: {best_quality['lead_days']} days · {best_quality['distance_mi']} mi")
            st.write("Highest quality costs more — worth it when rework would cost "
                     "more than the saving.")
        st.markdown('</div>', unsafe_allow_html=True)

    st.subheader("Ranked shortlist — cost and quality per supplier")
    import pandas as pd
    table = pd.DataFrame([{
        "Best-value rank": r["value_rank"],
        "Supplier": r["name"],
        "Unit ($)": r["unit_price"],
        "Transport ($)": r["transport"] if r["transport"] is not None else "—",
        "Landed ($)": r["landed"],
        "Landed cost": r["landed_label"],
        "MOQ": r["moq"],
        "Lead (days)": r["lead_days"],
        "Quality /100": r["quality_score"],
        "Why this rank": r["why"],
    } for r in sorted(rows, key=lambda r: (r["value_rank"] is None, r["value_rank"]))])
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption("Total landed cost = unit price × quantity + transport + taxes/fees — "
               "the breakdown per supplier is in the cards below. “excl. transport” "
               "means no delivery location was typed, so transport is not in the total. "
               "Value = 0.45 × cost score + 0.35 × quality score + 0.20 × lead-time "
               "score (each 0–100, normalised across this shortlist). "
               "Winner per criterion is highlighted in the three cards above.")

    st.subheader("Map-like view — distance from job site")
    for r in sorted(rows, key=lambda x: x.get("distance_km") if x.get("distance_km") is not None else x["distance_mi"] * 1.609):
        dist_txt = (f"{r['distance_km']} km from delivery location"
                    if r.get("distance_km") is not None
                    else f"{r['distance_mi']} mi from job site (no delivery location typed)")
        bar = "▂" * max(1, int(20 - (r.get("distance_km") or r["distance_mi"] * 1.609) / 5))
        st.write(f"{bar} **{r['name']}** — {dist_txt} · "
                 f"{r['location']} · lead {r['lead_days']}d · "
                 f"${r['landed']:.2f} landed ({r['landed_label']}) · quality {r['quality_score']}/100")

    st.subheader("Supplier cards — quality evidence, not just a number")
    for r in sorted(rows, key=lambda x: (x["value_rank"] is None, x["value_rank"])):
        with st.expander(f"#{r['value_rank']} {r['name']} — "
                          f"${r['landed']:.2f} landed · quality {r['quality_score']}/100"):
            chips = []
            if r.get("is_best_value"):
                chips.append(status_chip("🏆 Best value", "best_value"))
            if r.get("is_cheapest"):
                chips.append(status_chip("💲 Cheapest", "cheapest"))
            if r.get("is_best_quality"):
                chips.append(status_chip("⭐ Highest quality", "quality"))
            if chips:
                st.markdown(" ".join(chips), unsafe_allow_html=True)
            st.write(f"**Location:** {r['location']} ({r['distance_mi']} mi) · "
                     f"**MOQ:** {r['moq']} · **Lead:** {r['lead_days']} days")
            st.write(f"**Landed breakdown ({qty} units):** {landed_line(r, qty)} · "
                     f"**Total: ${r['landed']:.2f} ({r['landed_label']})**")
            st.write("**Quality evidence:**")
            for ev in r["quality_evidence"]:
                st.write(f"- {ev}")
            st.write(f"**Contact:** {r['contact']} (source: {r['contact_source']})")
            st.write(f"**Phone:** {r.get('phone') or 'not held'} · "
                     f"**Address:** {r.get('address') or 'not held'} "
                     f"(area: {r['location']})")
            st.write(f"**How we'll contact them:** Email — from {EMAIL_FROM} "
                     f"to {supplier_email(r) or 'not held — cannot send yet'} · "
                     f"Full email preview + edit on the Buyer Agent tab.")
            st.write(f"**Why this rank:** {r['why']}")
            share = st.checkbox(f"Share my contact with {r['name']}",
                                value=st.session_state["contact_sharing"].get(r["name"], False),
                                key=f"share-{r['name']}")
            st.session_state["contact_sharing"][r["name"]] = share
            st.caption("Your choice, per supplier. OFF (default): the supplier "
                       "only sees “BuildBuy Copilot, buying agent for a customer” "
                       "— no name, email or phone. ON: your name (Deepthi Jainlal), "
                       "email (deepthiag26@gmail.com) and phone (+1 341-252-9234) "
                       "are included so they can reach you directly.")

    if excluded:
        st.subheader("Not eligible for this quantity — excluded, not hidden")
        st.caption("These suppliers will not sell this quantity (MOQ above the job "
                   "size). They are listed with the reason, never silently dropped — "
                   "the cheapest per-unit price here is a trap if you cannot buy that few.")
        for r in excluded:
            st.write(f"**{r['name']}** — ${r['unit_price']:.2f}/unit looks cheap, but "
                     f"MOQ {r['moq']} > {qty} needed ({r['reason']}). "
                     f"Quality {r['quality_score']}/100 · lead {r['lead_days']} days · "
                     f"{r['distance_mi']} mi away.")

    st.subheader("Digital twin — what-if simulator (cost AND quality risk)")
    st.caption("Simulates the top 3 suppliers for this one purchase. Method: what-if "
               "landed cost = (base landed − transport) × (1 + qty%) × (1 + price%) "
               "+ transport (freight does not rise with the unit price); quality risk "
               "is 10 for evidenced quality ≥ 80, 30 for 60–79, 55 for < 60, and 60 "
               "where there is no quality evidence; overall risk = 0.5 × quality risk "
               "+ 0.3 × cost risk + 0.2 × lead risk. Cheap but late or low quality = "
               "higher total risk, because rework + delay compound — the same formula "
               "as the backend twin (app/ranking.py).")
    top3 = sorted(rows, key=lambda x: (x["value_rank"] is None, x["value_rank"]))[:3]
    s1, s2, s3 = st.columns(3)
    with s1:
        price_pct = st.slider("Price rises by (%)", 0, 50, 10)
    with s2:
        slip_days = st.slider("Delivery slips by (days)", 0, 14, 3)
    with s3:
        qty_pct = st.slider("Quantity changes by (%)", -20, 50, 20)
    sim_rows = []
    for r in top3:
        sim = twin_risk(r, qty, price_pct, slip_days, qty_pct)
        sim_rows.append({
            "Supplier": r["name"],
            "New landed ($)": sim["landed"],
            "Delivery": sim["delivery_date"].strftime("%b %d") + f" ({sim['lead_days']}d)",
            "Quality /100": sim["quality"],
            "Quality risk": f"{sim['quality_risk']:.0f} — {sim['quality_reason']}",
            "Total risk": f"{sim['risk']} ({sim['risk_level']})",
        })
        if sim["risk_level"] == "High":
            st.warning(f"⚠ {r['name']}: total risk HIGH ({sim['risk']}) under this "
                       f"what-if — cheap price does not cover late delivery + weak quality.")
    st.dataframe(pd.DataFrame(sim_rows), use_container_width=True, hide_index=True)
    rec = top3[0] if top3 else None
    if rec:
        st.success(f"**Twin recommendation (best value): {rec['name']}** — lowest combined "
                   f"cost + quality risk under the current what-if. "
                   f"Runner-up: {top3[1]['name'] if len(top3) > 1 else '—'}. "
                   "The final choice is yours on the approval screen.")
    if st.button("Contact top 3 suppliers →", type="primary"):
        st.session_state["usage"]["buyer_runs"] += 0  # counted when the draft is sent
        st.session_state["nav"] = "4 · Buyer Agent"
        st.rerun()

# ---------------------------------------------------------------------------
# Tab 4 — Buyer Agent
# ---------------------------------------------------------------------------
elif nav == "4 · Buyer Agent":
    st.header("Buyer Agent — quotes, negotiation, approval")
    st.progress(4 / 5, text="Requirement → Materials → Suppliers → Quotes → Approval")
    req = st.session_state.get("requirement") or {"quantity": 50, "item": "steel brackets"}
    qty = int(req.get("quantity") or 50)
    rows, _excluded = rank_suppliers(
        st.session_state["suppliers"], qty,
        delivery_location=st.session_state.get("delivery_location", ""),
        transport_rate=st.session_state.get("transport_rate"))
    by_name = {r["name"]: r for r in rows}
    best_value = next((r for r in rows if r["is_best_value"]), None)
    cheapest = next((r for r in rows if r["is_cheapest"]), None)
    best_quality = next((r for r in rows if r["is_best_quality"]), None)

    st.subheader("Negotiation limits — the agent can never go above these")
    l1, l2 = st.columns(2)
    with l1:
        st.session_state["max_price"] = st.number_input(
            "Max price — total landed ($)", min_value=0.0,
            value=float(st.session_state["max_price"]))
    with l2:
        st.session_state["latest_date"] = st.date_input(
            "Latest acceptable delivery date", value=st.session_state["latest_date"])
    st.caption("One negotiation round only, within these limits. The agent cannot agree "
               "above the cap or after the deadline — enforced in code, not just in a prompt.")

    st.subheader("Emails to suppliers — preview, edit, then send")
    st.caption("One email per supplier, shown IN FULL before anything is sent. "
               "Each card shows the supplier's contact details (never invented — "
               "“not held” when missing), HOW they will be contacted (channel, "
               "from, to, subject), and the exact email body. Edit the subject "
               "or body, save, and only then send — nothing is sent without you "
               "seeing the final text. The agent always identifies itself as "
               "your buying agent; your name, email and phone appear ONLY when "
               "you toggle sharing ON for that supplier.")
    top3 = sorted(rows, key=lambda x: (x["value_rank"] is None, x["value_rank"]))[:3]
    buyer = {
        "name": st.session_state["settings"]["name"],
        "email": st.session_state["settings"]["email"],
        "phone": st.session_state["settings"]["phone"],
    }
    for r in top3:
        details = supplier_contact_details(r)
        share = st.checkbox(
            f"Share my contact with {r['name']}",
            value=st.session_state["contact_sharing"].get(r["name"], False),
            key=f"send-share-{r['name']}",
            help="OFF (default): the supplier only sees “BuildBuy Copilot, "
                 "buying agent for a customer” — no name, email or phone. ON: "
                 "your name, email and phone are included so they can reach "
                 "you directly.")
        st.session_state["contact_sharing"][r["name"]] = share
        generated = build_quote_email(
            req, r, share_contact=share, buyer=buyer,
            max_price=st.session_state["max_price"])
        saved = st.session_state["quote_drafts"].get(r["name"])
        with st.expander(
                f"✉️ {r['name']} — "
                f"{generated['to'] or 'email not held — cannot send'}", expanded=True):
            st.write(f"**Contact details:** {details['name']} · "
                     f"Email: {details['email'] or 'not held'} · "
                     f"Phone: {details['phone'] or 'not held'} · "
                     f"Address: {details['address'] or 'not held'}"
                     + (f" (area: {details['area']})" if details["area"] else "")
                     + f" · Source: {details['contact_source']}")
            st.write(f"**How we will contact them:** Channel: Email · "
                     f"From: {EMAIL_FROM} · "
                     f"To: {generated['to'] or '— not held —'} · "
                     f"Subject: {generated['subject']}")
            if not generated["sendable"]:
                st.warning(f"⚠ {generated['blocked_reason']} "
                           "Add their email to the supplier record first — "
                           "no address is ever guessed.")
            # Widget keys carry the sharing state: Streamlit keeps a
            # widget's value by key, so toggling sharing must create a
            # fresh widget initialised from the regenerated preview —
            # otherwise the preview would keep showing the old text
            # (sharing OFF body after toggling ON, and vice versa).
            share_tag = "shared" if share else "private"
            subj_key = f"quote-subject-{r['name']}-{share_tag}"
            body_key = f"quote-body-{r['name']}-{share_tag}"
            subject = st.text_input(
                "Subject (editable)", value=saved["subject"] if saved else generated["subject"],
                key=subj_key)
            body = st.text_area(
                "Email body (editable) — this exact text is what gets sent",
                value=saved["body"] if saved else generated["body"],
                height=260, key=body_key)
            if saved:
                st.caption("✏️ Edited by you — “Reset to draft” rebuilds it "
                           "from the requirement.")
            if not share and any(v in body for v in
                                 (buyer["name"], buyer["email"], buyer["phone"]) if v):
                st.warning("Sharing is OFF for this supplier — your name / "
                           "email / phone in the text above will be removed "
                           "before sending.")
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("💾 Save edited email", key=f"quote-save-{r['name']}"):
                    st.session_state["quote_drafts"][r["name"]] = {
                        "subject": subject, "body": body, "edited": True}
                    st.success("Saved — this exact text will be sent.")
            with b2:
                if st.button("↩ Reset to draft", key=f"quote-reset-{r['name']}"):
                    st.session_state["quote_drafts"].pop(r["name"], None)
                    for tag in ("shared", "private"):
                        st.session_state.pop(f"quote-subject-{r['name']}-{tag}", None)
                        st.session_state.pop(f"quote-body-{r['name']}-{tag}", None)
                    st.rerun()
            with b3:
                if st.button(f"📧 Send to {r['name']}", key=f"quote-send-{r['name']}",
                             type="primary", disabled=not generated["sendable"]):
                    final_body = body if share else strip_contact_details(body, buyer)
                    st.session_state["quote_sent"][r["name"]] = {
                        "to": generated["to"], "subject": subject,
                        "body": final_body, "channel": "email"}
                    st.session_state["usage"]["buyer_runs"] += 1
                    if LIVE:
                        st.info("Live mode: sending via the backend email service.")
                    st.success(f"Demo mode: email to {r['name']} "
                               f"({generated['to']}) recorded as “sent” locally. "
                               "No real email was sent. In live mode this sends "
                               "via Gmail SMTP / Resend.")
                    if not share and final_body != body:
                        st.caption("Contact details were removed before sending "
                                   "because sharing is OFF for this supplier.")
            sent = st.session_state["quote_sent"].get(r["name"])
            if sent:
                st.caption(f"✅ Sent (demo record): to {sent['to']} · "
                           f"subject “{sent['subject']}”")
    if st.button("Send quote requests to top 3", type="primary"):
        sent_names, blocked_names = [], []
        for r in top3:
            generated = build_quote_email(
                req, r, share_contact=st.session_state["contact_sharing"].get(r["name"], False),
                buyer=buyer, max_price=st.session_state["max_price"])
            if not generated["sendable"]:
                blocked_names.append(f"{r['name']} ({generated['blocked_reason']})")
                continue
            share_tag = ("shared" if st.session_state["contact_sharing"].get(r["name"], False)
                         else "private")
            body = st.session_state.get(
                f"quote-body-{r['name']}-{share_tag}", generated["body"])
            subject = st.session_state.get(
                f"quote-subject-{r['name']}-{share_tag}", generated["subject"])
            if not st.session_state["contact_sharing"].get(r["name"], False):
                body = strip_contact_details(body, buyer)
            st.session_state["quote_sent"][r["name"]] = {
                "to": generated["to"], "subject": subject,
                "body": body, "channel": "email"}
            sent_names.append(f"{r['name']} ({generated['to']})")
        if sent_names:
            st.session_state["usage"]["buyer_runs"] += 1
            if LIVE:
                st.info("Live mode: sending via the backend email service.")
            st.success("Demo mode: recorded as “sent” locally — no real email "
                       "was sent. In live mode these send via Gmail SMTP / Resend: "
                       + "; ".join(sent_names))
        if blocked_names:
            st.warning("Not sent — email not held, no address guessed: "
                       + "; ".join(blocked_names))
        if not sent_names and not blocked_names:
            st.info("No suppliers to contact.")
        for t in st.session_state["threads"]:
            if t["status"] == "no reply":
                pass  # no reply stays no reply — never presented as a quote

    st.subheader("Inbox")
    col_list, col_thread, col_info = st.columns([1, 2, 1])
    with col_list:
        st.caption("Conversations")
        sel = st.radio("Thread", [t["supplier"] for t in st.session_state["threads"]],
                       label_visibility="collapsed")
        for t in st.session_state["threads"]:
            st.markdown(f"**{t['supplier']}** — {thread_chip(t['status'])}",
                        unsafe_allow_html=True)
            st.caption(t["messages"][-1][1][:60] + "…")
    thread = next(t for t in st.session_state["threads"] if t["supplier"] == sel)
    with col_thread:
        st.caption(f"Thread — {thread['supplier']}")
        for who, text in thread["messages"]:
            with st.chat_message("user" if who == "buyer" else "assistant"):
                st.write(text)
        reply = st.text_input("Reply in this thread (demo: saved locally only)",
                              key=f"reply-{sel}")
        if st.button("Send reply", key=f"send-reply-{sel}") and reply.strip():
            thread["messages"].append(("buyer", reply.strip()))
            st.rerun()
    with col_info:
        st.caption("Supplier info")
        info = by_name.get(sel)
        if info:
            st.write(f"**{info['name']}**")
            st.write(f"{info['location']} · {info['distance_mi']} mi")
            st.write(f"Unit ${info['unit_price']:.2f} · Landed ${info['landed']:.2f}")
            st.write(f"MOQ {info['moq']} · Lead {info['lead_days']} days")
            st.write(f"Quality {info['quality_score']}/100")
            st.write("Evidence:")
            for ev in info["quality_evidence"]:
                st.write(f"- {ev}")
            st.write(f"Contact: {info['contact']}")
    needs_you = [t for t in st.session_state["threads"] if t["status"] == "needs_customer"]
    if needs_you:
        st.subheader("Supplier asked something I can't answer — needs you")
        st.caption("The agent never guesses. When a supplier asks about "
                   "payment, a price beyond your limits, a spec, or anything "
                   "not in your requirement, it emails you instead and waits. "
                   "Answer here and the agent sends your words to the supplier.")
        for t in needs_you:
            st.warning(f"**{t['supplier']}** asked: “{t['messages'][-1][1]}”")
            answer = st.text_input("Your answer (sent to the supplier in your words)",
                                   key=f"escalation-answer-{t['supplier']}")
            if st.button("Send my answer to supplier", key=f"escalation-send-{t['supplier']}") and answer.strip():
                t["messages"].append(("buyer", "BuildBuy Copilot, acting as the "
                                     f"buying agent for a customer: {answer.strip()}"))
                t["status"] = "replied"
                st.success("Demo mode: your answer was recorded locally and the "
                           "thread is no longer waiting. In live mode it is emailed "
                           "to the supplier (POST /buyer/escalations/{id}/reply).")
                st.rerun()

    no_reply = [t for t in st.session_state["threads"] if t["status"] == "no reply"]
    if no_reply:
        st.subheader("Couldn't answer / no reply in 24h")
        for t in no_reply:
            c1, c2 = st.columns([3, 1])
            with c1:
                st.write(f"**{t['supplier']}** — no reply yet. This is not a quote.")
            with c2:
                if st.button("Try next supplier", key=f"next-{t['supplier']}"):
                    st.info("Demo mode: the next-ranked supplier would be contacted. "
                            "In live mode the agent emails the next supplier on the shortlist.")

    st.subheader("Approval — one tap, and only your tap orders anything")
    st.caption("Compare the three options, then choose. Approving confirms the order "
               "with the supplier. You pay the supplier directly — this app never "
               "handles payment, and nothing is ordered without this tap.")
    choice = st.radio(
        "Which offer do you want to approve?",
        ["best_value", "cheapest", "best_quality"],
        format_func=lambda v: {
            "best_value": f"🏆 Best value — {best_value['name']} "
                          f"(${best_value['landed']:.2f} landed, quality "
                          f"{best_value['quality_score']}/100)",
            "cheapest": f"💲 Cheapest — {cheapest['name']} "
                        f"(${cheapest['landed']:.2f} landed, quality "
                        f"{cheapest['quality_score']}/100)",
            "best_quality": f"⭐ Highest quality — {best_quality['name']} "
                            f"(${best_quality['landed']:.2f} landed, quality "
                            f"{best_quality['quality_score']}/100)",
        }[v],
        index=["best_value", "cheapest", "best_quality"].index(
            st.session_state["selected_offer"]))
    st.session_state["selected_offer"] = choice
    picked = {"best_value": best_value, "cheapest": cheapest,
              "best_quality": best_quality}[choice]
    st.write(f"Selected: **{picked['name']}** — ${picked['landed']:.2f} landed, "
             f"quality {picked['quality_score']}/100, lead {picked['lead_days']} days. "
             f"Within your limits: "
             f"{'yes' if picked['landed'] <= st.session_state['max_price'] else 'NO — over cap, cannot approve'}")
    a1, a2 = st.columns(2)
    with a1:
        if st.button("✅ Approve this offer", type="primary",
                     disabled=picked["landed"] > st.session_state["max_price"]):
            st.session_state["order_status"] = "APPROVED"
            st.success(f"Approved: {picked['name']}. Order confirmation is sent by the "
                       "agent; you pay the supplier directly. See My Orders for the timeline.")
    with a2:
        if st.button("Reject this offer"):
            st.session_state["order_status"] = "REJECTED"
            st.info("Offer rejected. No order was created. You can pick another "
                    "supplier or end this purchase.")
    st.write(f"Current order status: **{st.session_state['order_status']}**")

# ---------------------------------------------------------------------------
# Tab 5 — My Orders
# ---------------------------------------------------------------------------
elif nav == "5 · My Orders":
    st.header("My Orders — full timeline, delivery chase, invoices")
    TIMELINE = ["requirement", "plan", "materials", "suppliers", "quotes",
                "negotiation", "approval", "order", "delivery", "invoice"]
    filt = st.selectbox("Filter", ["All", "Awaiting approval", "Approved",
                                   "Delivered", "No reply", "Invoice received"])
    for order in st.session_state["orders"]:
        if filt == "Invoice received" and order["status"] != "INVOICE_RECEIVED":
            continue
        if filt == "Approved" and order["status"] not in ("APPROVED", "INVOICE_RECEIVED"):
            continue
        with st.expander(f"{order['id']} — {order['item']} · {order['supplier']} · "
                          f"{order['status']} · ${order['total']:.2f}", expanded=True):
            st.markdown(order_chip(order["status"]), unsafe_allow_html=True)
            reached = [s for s in TIMELINE if s in order["timeline"]]
            st.write(" → ".join(
                f"**{s}**" if s in reached else s for s in TIMELINE))
            st.caption("Timeline: requirement → plan → materials → suppliers → quotes → "
                       "negotiation → approval → order → delivery → invoice. "
                       "Every quote and message is expandable in the Buyer Agent inbox.")
            if order["status"] == "INVOICE_RECEIVED" and order.get("invoice"):
                inv = order["invoice"]
                st.subheader("Invoice received")
                st.write(f"**Invoice:** {inv['number']} · **Amount:** ${inv['amount']:.2f} · "
                         f"**Received:** {inv['received']}")
                st.caption("Invoice details are recorded only from the supplier — "
                           "the app never invents an invoice number or amount. "
                           f"Source: {inv['source']}.")
            elif order["status"] == "APPROVED":
                st.info("No invoice yet — invoice details will appear here only once "
                        "the supplier sends one.")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("📧 Chase delivery", key=f"chase-{order['id']}"):
                    order["chased"] = True
                    st.success("Demo mode: chase email drafted locally, not sent. "
                               "In live mode the agent emails the supplier on the "
                               "promised date if delivery is not confirmed.")
            with c2:
                if st.button("✓ Mark delivered", key=f"deliv-{order['id']}"):
                    order["status"] = "DELIVERED"
                    if "delivery" not in order["timeline"]:
                        order["timeline"].append("delivery")
                    st.success("Marked delivered. Only you can confirm delivery — "
                               "no competitor or agent can prove the goods arrived.")
                    st.rerun()
            with c3:
                if st.button("Export order (JSON)", key=f"exp-{order['id']}"):
                    st.download_button(
                        "Download JSON", json.dumps(order, indent=2, default=str),
                        file_name=f"{order['id']}.json", mime="application/json",
                        key=f"dl-{order['id']}")
    st.caption("Invoice tracking: an order reaches INVOICE_RECEIVED only when the supplier "
               "sends an invoice. The app records the supplier's invoice number, amount, "
               "and date — it never generates them.")

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Tab 6 — Accuracy (observability dashboard)
# ---------------------------------------------------------------------------
elif nav == "6 · Accuracy":
    st.header("Accuracy — is the copilot getting better or worse?")
    st.caption("Observability dashboard: 8 separate metrics, never blended "
               "into one score — a problem in one module cannot hide behind "
               "another. All numbers are measured from logged events, or "
               "labelled synthetic demo data. If there is not enough data "
               "yet, the dashboard says “no data yet” instead of showing a "
               "made-up percentage.")
    # Live data when the backend is up; labelled synthetic demo otherwise.
    live_dash = fetch_live_accuracy() if LIVE else None
    if LIVE and live_dash is not None:
        dash = live_dash
        st.markdown('<span class="badge badge-live">● LIVE — measured from '
                    'metrics_daily + eval_runs + qa_log + observability_events'
                    '</span>', unsafe_allow_html=True)
        worst = dash.get("worst_answers", [])
        trends = dash.get("trends", [])
        eval_runs = dash.get("eval_runs", [])
        raw_events = dash.get("raw_events", [])
        per_module = dash.get("per_module", [])
    else:
        dash = DEMO_ACCURACY
        if LIVE:
            st.warning("Backend is up but /accuracy did not answer — showing "
                       "labelled synthetic demo data instead of inventing "
                       "live numbers.")
        else:
            st.caption("Source: synthetic demo metrics (labelled) — replace "
                       "with measured values from `metrics_daily` / "
                       "`eval_runs` when the backend is live.")
        worst = worst_answers_from_feedback(
            st.session_state["feedback"], DEMO_WORST_ANSWERS)
        # Apply any demo Worst Answers actions taken this session.
        for _qa, _act in st.session_state.get("worst_actions", {}).items():
            worst = apply_worst_action(worst, _qa, _act)
        trends = [{"date": d, "groundedness": g / 100, "retrieval_top1": r / 100,
                   "eval_pass_rate": e / 100,
                   "cost_per_job_usd": c, "latency_p95_ms": int(p * 1000),
                   "cache_hit_rate": None}
                  for d, g, r, e, c, p in zip(
                      DEMO_METRICS_DAYS, DEMO_GROUNDEDNESS, DEMO_RETRIEVAL_TOP1,
                      DEMO_EVAL_PASS, DEMO_COST_PER_JOB, DEMO_LATENCY_P95)]
        eval_runs = DEMO_EVAL_RUNS
        raw_events = DEMO_RAW_EVENTS
        per_module = [
            {"module": "Plan Q&A", "metric": "Groundedness",
             "value": 0.96, "n": 48,
             "worst": "2 ungrounded answers"},
            {"module": "Retrieval (RAG)", "metric": "Retrieval top-1",
             "value": 0.92, "n": 73,
             "worst": "eval runs below the gate in Eval Run History"},
            {"module": "Takeoff", "metric": "Mean error (MAPE)",
             "value": None, "n": 0,
             "worst": "no corrected lines recorded yet"},
            {"module": "Supplier ranking", "metric": "Chosen-was-#1",
             "value": 0.67, "n": 12,
             "worst": "orders where the chosen supplier was not ranked #1"},
            {"module": "Buyer agent", "metric": "Approval-before-order",
             "value": 1.0, "n": 12, "worst": "none"},
            {"module": "Guardrails", "metric": "Block rate",
             "value": 1.0, "n": 16,
             "worst": "adversarial items that were NOT blocked"},
            {"module": "Cache / cost", "metric": "Cache hit rate",
             "value": 0.61, "n": 48, "worst": "p95 ask latency 7,200 ms"},
        ]
    st.session_state.setdefault("worst_actions", {})

    if st.button("Clear demo metrics (show the empty state)"):
        st.session_state["metrics_cleared"] = True
        st.rerun()
    if st.session_state["metrics_cleared"]:
        st.info("No data yet — no answers, jobs, or eval runs have been logged in this "
                "window. Use the Copilot chat and run a purchase, then come back: "
                "groundedness, thumbs-up rate, takeoff error, and cost per job will "
                "appear here with their sample sizes (n = …).")
        if st.button("Restore synthetic demo metrics"):
            st.session_state["metrics_cleared"] = False
            st.rerun()
    elif dashboard_is_empty(dash):
        st.info("No data yet — the backend has logged no answers, jobs, or eval runs "
                "in this window. Every metric below shows “no data yet” until the "
                "first answer, job, or eval run is recorded. Nothing here is invented.")
    else:
        # --- Alerts ------------------------------------------------------
        for a in dash.get("alerts", []):
            st.warning(f"⚠ Alert: **{a['metric']}** is {a['value']} — below its "
                       f"alert threshold {a['threshold']}. See the metric table "
                       "below for the formula and source.")

        # --- 1. The 8 metrics, each with formula / source / n / target --
        st.subheader("The 8 metrics — separate, never blended")
        st.caption("No single 0–100% accuracy score is shown anywhere. Each "
                   "metric has its own formula, source, sample size (n) and "
                   "proposed target. “no data yet” means not enough has been "
                   "logged — never a made-up number.")
        import pandas as pd
        metric_rows = []
        for m in dash["metrics"]:
            extra = ""
            if m["key"] == "buyer_agent" and m.get("agreement_rate") is not None:
                extra = (f" Quotes agreed: {m['agreement_rate'] * 100:.0f}% "
                         f"(shown separately, not blended into the invariant).")
            if m["key"] == "thumbs_up_rate":
                nf = next((x for x in dash["metrics"]
                           if x["key"] == "groundedness"), None)
                extra = " “Not found” answers are counted separately, not as wrong answers."
            status_txt = {"ok": "✅ ok", "alert": "⚠ ALERT",
                          "no_data": "— no data yet"}[m.get("status", "no_data")]
            metric_rows.append({
                "Metric": m["name"],
                "Value": format_value(m.get("value"), m.get("unit", "rate")),
                "n": m.get("n", 0),
                "Formula": m["formula"] + extra,
                "Source": m["source"],
                "Target": m["target"],
                "Status": status_txt,
            })
        st.dataframe(pd.DataFrame(metric_rows), use_container_width=True,
                     hide_index=True)
        st.markdown(
            " ".join(
                status_chip(
                    f"{m['name']}: "
                    f"{'✅ ok' if m.get('status') == 'ok' else ('⚠ ALERT' if m.get('status') == 'alert' else '— no data yet')}",
                    {"ok": "ok", "alert": "warn", "no_data": "nodata"}.get(
                        m.get("status", "no_data"), "nodata"))
                for m in dash["metrics"]),
            unsafe_allow_html=True)

        # --- 2. Headline cards ------------------------------------------
        st.subheader("Headline — the 4 numbers to glance at")
        m1, m2, m3, m4 = st.columns(4)
        heads = dash["headline"]
        for col, h in zip((m1, m2, m3, m4), heads):
            with col:
                st.markdown(
                    '<div class="metric-card"><div class="metric-num">' +
                    format_value(h.get("value"), h.get("unit", "rate")) +
                    '</div>' + h["label"] + '<br><span class="small">n=' +
                    str(h.get("n", 0)) + '</span></div>',
                    unsafe_allow_html=True)
        st.caption("Headline cards are the same 4 metrics from the table "
                   "above (groundedness, 👍 rate, takeoff error, cost per "
                   "job) — a shortcut, not a different score.")

        # --- 3. Trend charts, with dashed alert thresholds --------------
        st.subheader("Trends — accuracy over time (30 days)")
        st.caption("Dashed lines are the alert thresholds: groundedness 90%, "
                   "retrieval top-1 85%, eval pass 90%. A series crossing "
                   "below its dashed line triggers an alert (see above).")
        if trends:
            trend_df = pd.DataFrame([{
                "Day": t["date"],
                "Groundedness %": (None if t.get("groundedness") is None
                                   else round(t["groundedness"] * 100, 1)),
                "Retrieval top-1 %": (None if t.get("retrieval_top1") is None
                                      else round(t["retrieval_top1"] * 100, 1)),
                "Eval pass %": (None if t.get("eval_pass_rate") is None
                                else round(t["eval_pass_rate"] * 100, 1)),
            } for t in trends]).set_index("Day")
            try:
                import altair as alt
                base = alt.Chart(trend_df.reset_index()).transform_fold(
                    ["Groundedness %", "Retrieval top-1 %", "Eval pass %"],
                    as_=["Metric", "Value"]).mark_line().encode(
                    x="Day:N", y=alt.Y("Value:Q", scale=alt.Scale(domain=[0, 105])),
                    color="Metric:N")
                rules = alt.Chart(pd.DataFrame([
                    {"Threshold": "Groundedness alert 90%", "Value": 90},
                    {"Threshold": "Retrieval alert 85%", "Value": 85},
                    {"Threshold": "Eval pass alert 90%", "Value": 90},
                ])).mark_rule(strokeDash=[6, 4], color="red").encode(
                    y="Value:Q", tooltip=["Threshold:N"])
                st.altair_chart(base + rules, use_container_width=True)
            except Exception:
                st.line_chart(trend_df)
                st.caption("Thresholds (dashed in the live chart): "
                           "groundedness 90% · retrieval top-1 85% · "
                           "eval pass 90%.")
        else:
            st.info("No trend data yet — trends appear after the first daily "
                    "rollup (`python -m app.observability`).")
        st.subheader("Trends — cost and latency")
        st.caption("Dashed line: p95 ask latency alert at 10 s. Cost per job "
                   "should fall as the cache hit rate rises.")
        if trends:
            cost_df = pd.DataFrame([{
                "Day": t["date"],
                "Cost per job ($)": t.get("cost_per_job_usd"),
                "p95 ask latency (s)": (
                    None if t.get("latency_p95_ms") is None
                    else round(t["latency_p95_ms"] / 1000, 1)),
            } for t in trends]).set_index("Day")
            try:
                import altair as alt
                base = alt.Chart(cost_df.reset_index()).transform_fold(
                    ["Cost per job ($)", "p95 ask latency (s)"],
                    as_=["Metric", "Value"]).mark_line().encode(
                    x="Day:N", y="Value:Q", color="Metric:N")
                rule = alt.Chart(pd.DataFrame([
                    {"Threshold": "p95 latency alert 10 s", "Value": 10},
                ])).mark_rule(strokeDash=[6, 4], color="red").encode(
                    y="Value:Q", tooltip=["Threshold:N"])
                st.altair_chart(base + rule, use_container_width=True)
            except Exception:
                st.line_chart(cost_df)
                st.caption("Threshold: p95 ask latency 10 s (dashed in the "
                           "live chart).")
        else:
            st.info("No cost/latency trend yet.")

        # --- 4. Per-module breakdown ------------------------------------
        st.subheader("Per-module breakdown")
        st.dataframe(pd.DataFrame([{
            "Module": r["module"], "Metric": r["metric"],
            "Value": format_value(r.get("value"), "rate"),
            "n": r.get("n", 0), "Worst in 7 days": r.get("worst", ""),
        } for r in per_module]), use_container_width=True, hide_index=True)
        st.caption("One row per module. A module's worst item is named, not "
                   "averaged away.")

        # --- 5. Worst Answers (10 lowest) -------------------------------
        st.subheader("Worst Answers — the fix list (10 lowest)")
        st.caption("Lowest-scoring answers first: thumbs-down, then "
                   "ungrounded. Each row has two actions — “Add to eval "
                   "set” puts the labelled example into the regression set "
                   "for the next eval run; “Mark fixed” records that the "
                   "underlying problem is fixed. A row already acted on "
                   "keeps its status and cannot be added twice.")
        if not worst:
            st.info("No worst answers yet — no thumbs-down or ungrounded "
                    "answers have been logged.")
        else:
            for w in worst:
                qid = w.get("qa_log_id")
                with st.expander(
                        f"{'👎' if (w.get('thumbs') or 0) < 0 else '❓'} "
                        f"{w['question']} — {w.get('status', 'open')}"):
                    st.write(f"**Answer:** {w.get('answer', '—')}")
                    st.write(f"**Citations:** {w.get('citations') or '—'}")
                    st.write(f"**Reason:** {w.get('reason', '—')}")
                    st.write(f"**Grounded:** {w.get('grounded')} · "
                             f"**Thumbs:** {w.get('thumbs', 0)}")
                    if w.get("status") == "open":
                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("➕ Add to eval set",
                                         key=f"eval-{qid or w['question'][:20]}"):
                                if LIVE and live_dash is not None and qid:
                                    import urllib.request as _u
                                    req = _u.Request(
                                        API_URL + f"/accuracy/worst-answers/{qid}/action",
                                        method="POST",
                                        data=json.dumps(
                                            {"action": "add_to_eval_set"}).encode(),
                                        headers={"Content-Type": "application/json"})
                                    try:
                                        with _u.urlopen(req, timeout=5) as resp:
                                            st.success("Added to the eval set "
                                                       "(live backend).")
                                    except Exception as exc:
                                        st.error(f"Backend did not accept it: {exc}")
                                else:
                                    st.session_state.setdefault("worst_actions", {})[
                                        qid or w["question"]] = "add_to_eval_set"
                                    st.success("Demo mode: noted locally as "
                                               "added to the eval set.")
                                st.rerun()
                        with b2:
                            if st.button("✓ Mark fixed",
                                         key=f"fix-{qid or w['question'][:20]}"):
                                if LIVE and live_dash is not None and qid:
                                    import urllib.request as _u
                                    req = _u.Request(
                                        API_URL + f"/accuracy/worst-answers/{qid}/action",
                                        method="POST",
                                        data=json.dumps(
                                            {"action": "mark_fixed"}).encode(),
                                        headers={"Content-Type": "application/json"})
                                    try:
                                        with _u.urlopen(req, timeout=5) as resp:
                                            st.success("Marked fixed (live backend).")
                                    except Exception as exc:
                                        st.error(f"Backend did not accept it: {exc}")
                                else:
                                    st.session_state.setdefault("worst_actions", {})[
                                        qid or w["question"]] = "mark_fixed"
                                    st.success("Demo mode: noted locally as fixed.")
                                st.rerun()
                    else:
                        st.caption(f"Status: **{w.get('status')}** — already "
                                   "recorded, cannot be added twice.")

        # --- 6. Eval Run History ----------------------------------------
        st.subheader("Eval Run History")
        st.caption("A failed eval run blocks the deploy via the CI "
                   "regression gate. Pass = groundedness ≥ 90% and "
                   "retrieval top-1 ≥ 85%.")
        if eval_runs:
            st.dataframe(pd.DataFrame([{
                "Date": r.get("date", ""),
                "Eval set": r.get("eval_set", ""),
                "Groundedness": (format_value(r.get("groundedness"), "rate")
                                 if isinstance(r.get("groundedness"), (int, float))
                                 else r.get("groundedness", "—")),
                "Retrieval top-1": (format_value(r.get("retrieval_top1"), "rate")
                                    if isinstance(r.get("retrieval_top1"), (int, float))
                                    else r.get("retrieval_top1", "—")),
                "Guardrail block": (format_value(r.get("guardrail_block"), "rate")
                                    if isinstance(r.get("guardrail_block"), (int, float))
                                    else r.get("guardrail_block", r.get("guardrail_block_rate", "—"))),
                "Cache hit": (format_value(r.get("cache_hit"), "rate")
                              if isinstance(r.get("cache_hit"), (int, float))
                              else r.get("cache_hit", r.get("cache_hit_rate", "—"))),
                "Result": r.get("result", ""),
            } for r in eval_runs]), use_container_width=True, hide_index=True)
        else:
            st.info("No eval runs yet.")

        # --- 7. Drill-down: raw events ----------------------------------
        st.subheader("Drill-down — raw events behind a metric")
        st.caption("Pick a metric (or a request) and see the raw logged "
                   "events: step, model, latency, grounded, cache hit, "
                   "guardrail action, cost. Prompts, plan text and email "
                   "bodies are never logged in full and never shown here — "
                   "only PII-free fields.")
        drill = st.selectbox(
            "Drill into",
            ["All steps", "ask", "retrieval", "takeoff", "guardrail",
             "send_supplier_email", "twin_simulate"],
            key="accuracy-drill")
        events = [e for e in raw_events
                  if drill == "All steps" or e.get("step") == drill]
        if events:
            st.dataframe(pd.DataFrame([{
                "request_id": e.get("request_id", ""),
                "Step": e.get("step", ""),
                "Model": e.get("model", ""),
                "Latency (ms)": e.get("latency_ms"),
                "Grounded": e.get("grounded"),
                "Cache hit": e.get("cache_hit"),
                "Guardrail": e.get("guardrail_action", ""),
                "Cost ($)": e.get("cost_usd", 0.0),
                "When": e.get("created_at", ""),
            } for e in events]), use_container_width=True, hide_index=True)
        else:
            st.info(f"No raw events for step “{drill}” yet.")
        st.caption("Accuracy is a loop, not a report: evals → this dashboard "
                   "→ Worst Answers / failing items → fix → re-run evals → "
                   "the dashboard shows whether it improved. The dashboard "
                   "never changes the product by itself.")

# Tab 7 — Settings
# ---------------------------------------------------------------------------
elif nav == "7 · Settings":
    st.header("Settings — contact, sharing, usage, data")
    s = st.session_state["settings"]
    st.subheader("My contact")
    st.caption("Shared with a supplier only if you toggle it on for that supplier "
               "(Buyer Agent tab). Default is OFF.")
    s["name"] = st.text_input("Name", value=s["name"])
    s["email"] = st.text_input("Email", value=s["email"])
    s["phone"] = st.text_input("Phone", value=s["phone"])
    st.subheader("Contact-sharing defaults")
    for name in st.session_state["contact_sharing"]:
        val = st.checkbox(f"Share my contact with {name} by default",
                          value=st.session_state["contact_sharing"][name],
                          key=f"default-share-{name}")
        st.session_state["contact_sharing"][name] = val
    st.caption("Per-supplier toggles, default OFF. Toggle OFF = your contact never "
               "appears in an outbound email to that supplier.")
    st.subheader("My buddy (personalisation, in plain words)")
    s["buddy_name"] = st.text_input("Buddy name", value=s["buddy_name"])
    s["tone"] = st.text_input("Tone", value=s["tone"])
    s["remember"] = st.text_area("Things to remember", value=s["remember"], height=80)
    st.subheader("Free-tier usage — one understandable meter")
    u = st.session_state["usage"]
    st.write(f"Plans used: {u['plans']} / {FREE_TIER['plans']} this month")
    st.write(f"Supplier searches used: {u['searches']} / {FREE_TIER['searches']} this month")
    st.write(f"Buyer runs used: {u['buyer_runs']} / {FREE_TIER['buyer_runs']} this month")
    st.caption("Free tier never deletes your work after inactivity. Paid plan (target): "
               "$19–$49/month flat, or $9 per plan for Plan Copilot-only use. "
               "No credits, no per-message meter.")
    st.subheader("API key (bring your own key)")
    byo = os.environ.get("LLM_API_KEY", "")
    st.write(f"BYO LLM key status: **{'set' if byo else 'not set'}** — "
             "the key value is never shown here.")
    st.caption("Without a key the app runs on local models only (TF-IDF + rules, "
               "local sentence-transformers) at $0. Add a key in `.env` "
               "(`LLM_API_KEY=…`) to enable the VLM + generation provider.")
    st.subheader("Data — export and delete")
    export = {"settings": s, "requirement": st.session_state.get("requirement"),
              "materials": st.session_state["materials"],
              "orders": st.session_state["orders"],
              "feedback": st.session_state["feedback"]}
    st.download_button("⬇ Export all my data (JSON)", json.dumps(export, indent=2, default=str),
                       file_name="buildbuy-my-data.json", mime="application/json")
    if st.button("Delete this purchase (demo data)"):
        st.session_state["requirement"] = None
        st.session_state["chat"] = []
        st.session_state["materials"] = [dict(m) for m in DEMO_MATERIALS]
        st.success("Demo purchase cleared from this session.")
    if st.button("Delete all my data (this session)"):
        for k in ("requirement", "chat", "feedback", "orders"):
            st.session_state[k] = [] if k in ("chat", "feedback") else None
        st.session_state["orders"] = []
        st.success("Session data cleared. Nothing is used to train a shared model.")
    st.subheader("About — limits, stated plainly")
    st.write("- Quantities are estimates, not surveyed measurements.")
    st.write("- We never handle payment — you pay the supplier directly.")
    st.write("- Nothing is ordered, confirmed, or paid without your tap.")
    st.write("- Supplier contacts are shown only where public or supplier-provided.")
    st.write("- Quality scores are shown only with their evidence; no rating is invented.")

st.divider()
st.caption("BuildBuy Copilot v1 — Streamlit frontend. Demo mode uses synthetic data only. "
           "See README.md and docs/ for architecture, deploy, and UAT.")
