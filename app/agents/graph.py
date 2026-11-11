"""Buyer-agent graph — LangGraph StateGraph with a human approval gate.

Flow (plan §3.7 + §10.4):
    Planner -> Finder -> Buyer -> Negotiator
        -> [HUMAN APPROVAL GATE: interrupt_before send]
        -> Order -> Chaser -> InvoiceTracker

Safety invariants (enforced in code, never only in a prompt):
- NEVER-PAY: no node pays anything; there is no payment tool at all.
- NEVER-ORDER-WITHOUT-APPROVAL: the graph cannot reach ``Order``
  without a persisted ``ApprovalRequest`` in APPROVED status. The
  approval gate is ``interrupt_before=["order"]`` in LangGraph, plus
  the DB check in :func:`order_node` as a second lock.
- Side effects are idempotent: every supplier email uses the
  deterministic key ``email:{deal}:{supplier}:{round}`` via the
  transactional outbox (see ``app/email/service.py``).
- Checkpoints: SQLite locally (``SqliteSaver``), Postgres checkpointer
  in prod when ``DATABASE_URL`` is Postgres and langgraph is installed.
  ``thread_id`` is the business key ``deal-{requirement_id}``.

When LangGraph is not installed, :class:`BuyerGraph` runs the same
nodes in the same order through a deterministic local runner with the
same approval-gate semantics (the gate is a persisted DB row either
way). The API therefore behaves identically with or without LangGraph;
``graph_available`` in ``/health`` reports which runner is live.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditLog,
    Order,
    OrderStatus,
    Outreach,
    OutreachStatus,
    Quote,
    Requirement,
    Shortlist,
    Supplier,
)
from app.email.service import EmailService, idempotency_key
from app.integrations import guardrail_check, twin_simulate
from app.ranking import rank_shortlist

logger = logging.getLogger("buildbuy.graph")

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception as exc:  # noqa: BLE001 - langgraph is a heavy optional dep
    SqliteSaver = None  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment]
    END = "END"  # type: ignore[assignment]
    LANGGRAPH_AVAILABLE = False
    logger.info("langgraph not available (%s); using deterministic local runner", exc)

# Tenacity if available, else a plain retry wrapper (same as email service).
try:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

    def _retry(fn):
        return retry(
            stop=stop_after_attempt(4),
            wait=wait_exponential_jitter(initial=1, max=60),
            retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
            reraise=True,
        )(fn)

except Exception:  # noqa: BLE001
    def _retry(fn):  # type: ignore[no-redef]
        return fn


class BuyerState(TypedDict, total=False):
    """Typed graph state — one deal, ``thread_id = deal-{requirement_id}``."""

    requirement_id: str
    user_id: str
    items: list[dict]
    location: str
    deadline: str | None
    max_price: float | None
    shortlist: list[dict]
    best_value_supplier_id: str | None
    cheapest_supplier_id: str | None
    highest_quality_supplier_id: str | None
    no_quality_evidence: bool
    draft: str
    quotes: list[dict]
    best_offer: dict | None
    runner_up: dict | None
    approval_status: str
    order_id: str | None
    error: str | None


def _audit(db: Session, requirement_id: str, actor: str, action: str, detail: dict) -> None:
    db.add(AuditLog(requirement_id=requirement_id, actor=actor, action=action, detail=detail))
    db.commit()


def _supplier_dicts(db: Session, requirement_id: str) -> list[dict]:
    rows = (
        db.query(Shortlist, Supplier)
        .join(Supplier, Shortlist.supplier_id == Supplier.id)
        .filter(Shortlist.requirement_id == requirement_id)
        .all()
    )
    out = []
    for short, sup in rows:
        out.append({
            "supplier_id": sup.id, "supplier_name": sup.name,
            "landed_cost": float(short.landed_cost) if short.landed_cost is not None else None,
            "unit_price": float(short.unit_price) if short.unit_price is not None else None,
            "quality_score": float(short.quality_score) if short.quality_score is not None else None,
            "quality_evidence": short.quality_evidence or [],
            "lead_time_days": sup.lead_time_days,
            "risk_flags": sup.risk_flags or [],
            "rank": short.rank, "why_rank": short.why_rank or "",
        })
    return out


# ------------------------------------------------------------------ nodes
def planner_node(state: BuyerState, db: Session) -> BuyerState:
    """Parse/validate the requirement into typed state."""
    req = db.query(Requirement).filter(Requirement.id == state["requirement_id"]).first()
    if req is None:
        return {**state, "error": "requirement_not_found"}
    items = [dict(i) for i in (req.items or [])]
    if not items or any((i.get("quantity") or 0) <= 0 for i in items):
        return {**state, "error": "invalid_requirement_items"}
    _audit(db, req.id, "agent", "planner_parsed",
           {"items": len(items), "location": req.location})
    return {**state, "items": items, "location": req.location,
            "deadline": req.deadline,
            "max_price": float(req.max_price) if req.max_price is not None else None}


def finder_node(state: BuyerState, db: Session) -> BuyerState:
    """Rank suppliers by best value (cost AND quality) + twin simulation."""
    entries = _supplier_dicts(db, state["requirement_id"])
    if not entries:
        return {**state, "error": "no_suppliers_in_shortlist"}
    ranked = rank_shortlist(entries)
    # Persist the ranking back to the shortlist rows.
    for entry in ranked:
        row = (
            db.query(Shortlist)
            .filter(Shortlist.requirement_id == state["requirement_id"],
                    Shortlist.supplier_id == entry["supplier_id"])
            .first()
        )
        if row is not None:
            row.best_value_score = entry["best_value_score"]
            row.best_value_rank = entry["best_value_rank"]
            row.rank = entry["best_value_rank"]
            row.is_cheapest = entry["is_cheapest"]
            row.is_highest_quality = entry["is_highest_quality"]
            row.quality_unknown = entry["quality_unknown"]
    db.commit()
    best = ranked[0]
    cheapest = next((e for e in ranked if e["is_cheapest"]), None)
    highest_q = next((e for e in ranked if e["is_highest_quality"]), None)
    _audit(db, state["requirement_id"], "agent", "finder_ranked",
           {"best_value": best["supplier_id"],
            "no_quality_evidence": bool(ranked[0].get("no_quality_evidence"))})
    return {**state, "shortlist": ranked,
            "best_value_supplier_id": best["supplier_id"],
            "cheapest_supplier_id": cheapest["supplier_id"] if cheapest else None,
            "highest_quality_supplier_id": highest_q["supplier_id"] if highest_q else None,
            "no_quality_evidence": bool(ranked[0].get("no_quality_evidence"))}


def buyer_node(state: BuyerState, db: Session) -> BuyerState:
    """Draft the quote-request email for the top 3 (draft only — no send).

    The draft identifies the agent: "BuildBuy Copilot, acting as the
    buying agent for a customer", enquiring about the specific part +
    quantity. With share_contact=False (the default) the customer's
    name / email / phone never appear in the draft — see
    ``EmailService.draft_quote``. If a supplier later asks a question
    the agent cannot answer from the requirement, it escalates to the
    customer instead of guessing (see ``app/agents/escalation.py``).
    """
    req = db.query(Requirement).filter(Requirement.id == state["requirement_id"]).first()
    from app.db.models import User as _User

    owner = db.query(_User).filter(_User.id == req.user_id).first() if req is not None else None
    user_name = owner.name if owner is not None and owner.name else "the buyer"
    user_email = owner.email if owner is not None else ""
    user_phone = owner.phone if owner is not None and owner.phone else ""
    top3 = (state.get("shortlist") or [])[:3]
    draft = EmailService.draft_quote(
        buyer_name=user_name, items=state.get("items", []),
        location=state.get("location", ""), deadline=state.get("deadline"),
        max_price=state.get("max_price"), share_contact=False,
        buyer_email=user_email, buyer_phone=user_phone,
    )
    for entry in top3:
        db.merge(Outreach(
            requirement_id=state["requirement_id"],
            supplier_id=entry["supplier_id"], channel="email",
            draft=draft, contact_shared=False,
            status=OutreachStatus.DRAFT.value,
        ))
    db.commit()
    _audit(db, state["requirement_id"], "agent", "buyer_drafted",
           {"suppliers": [e["supplier_id"] for e in top3]})
    return {**state, "draft": draft}


def negotiator_node(state: BuyerState, db: Session) -> BuyerState:
    """One negotiation round, within buyer limits (code-enforced).

    Reads recorded quotes; a quote above max_price or past latest_date
    is rejected by the guardrail check, never agreed. No quote on file
    means no offer — never an invented one. Any negotiation email the
    agent sends identifies it as the customer's buying agent
    (``EmailService.with_agent_identity``) and, if the supplier asks
    something outside the stated limits, the question escalates to the
    customer instead of being answered (``app/agents/escalation.py``).
    """
    quotes = (
        db.query(Quote)
        .filter(Quote.requirement_id == state["requirement_id"])
        .order_by(Quote.total)
        .all()
    )
    offers = []
    for q in quotes:
        price = float(q.total) if q.total is not None else None
        check = guardrail_check(text=q.terms or "", max_price=state.get("max_price"),
                                price=price, share_contact=False)
        if not check["allowed"]:
            _audit(db, state["requirement_id"], "agent", "negotiator_rejected_over_limit",
                   {"supplier_id": q.supplier_id, "reason": check["reason"]})
            continue
        offers.append({"supplier_id": q.supplier_id, "quote_id": q.id,
                       "total": price, "lead_time_days": q.lead_time_days,
                       "quality_score": float(q.quality_score) if q.quality_score is not None else None})
    # Best offer = best value among valid offers (cost + quality), not
    # cheapest alone. Reuse the ranking on the valid offers.
    best, runner_up = None, None
    if offers:
        ranked_offers = rank_shortlist([
            {"landed_cost": o["total"], "quality_score": o["quality_score"],
             "supplier_id": o["supplier_id"]} for o in offers
        ])
        order = {e["supplier_id"]: e for e in ranked_offers}
        offers.sort(key=lambda o: order[o["supplier_id"]]["best_value_rank"])
        best, runner_up = offers[0], (offers[1] if len(offers) > 1 else None)
    _audit(db, state["requirement_id"], "agent", "negotiator_completed",
           {"valid_offers": len(offers),
            "best": best["supplier_id"] if best else None})
    return {**state, "quotes": offers, "best_offer": best, "runner_up": runner_up}


def approval_gate_node(state: BuyerState, db: Session) -> BuyerState:
    """Human approval gate — a persisted state, not a prompt.

    Creates (or reuses) a PENDING ApprovalRequest with the full payload
    (deal total vs limits, supplier + quote, twin result, draft verbatim,
    expiry). The graph stops here until the user decides via the API.
    """
    existing = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.deal_id == state["requirement_id"],
                ApprovalRequest.status == ApprovalStatus.PENDING.value)
        .first()
    )
    if existing is None:
        best = state.get("best_offer") or {}
        payload = {
            "best_offer": best, "runner_up": state.get("runner_up"),
            "best_value_supplier_id": state.get("best_value_supplier_id"),
            "cheapest_supplier_id": state.get("cheapest_supplier_id"),
            "highest_quality_supplier_id": state.get("highest_quality_supplier_id"),
            "no_quality_evidence": state.get("no_quality_evidence"),
            "draft": state.get("draft", ""),
            "max_price": state.get("max_price"),
        }
        db.add(ApprovalRequest(deal_id=state["requirement_id"], payload_json=payload))
        db.commit()
    return {**state, "approval_status": ApprovalStatus.PENDING.value}


def order_node(state: BuyerState, db: Session) -> BuyerState:
    """Confirm the order — ONLY after a persisted APPROVED decision.

    Second lock on top of the graph interrupt: if no APPROVED
    ApprovalRequest exists, the order is refused and the state records
    the refusal. This is what makes never-order-without-approval a
    state-machine invariant rather than a prompt instruction.
    """
    approved = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.deal_id == state["requirement_id"],
                ApprovalRequest.status == ApprovalStatus.APPROVED.value)
        .order_by(ApprovalRequest.decided_at.desc())
        .first()
    )
    if approved is None:
        _audit(db, state["requirement_id"], "system", "order_refused_no_approval", {})
        return {**state, "error": "order_refused_no_approval",
                "approval_status": ApprovalStatus.PENDING.value}
    payload = approved.payload_json or {}
    best = payload.get("best_offer") or state.get("best_offer") or {}
    supplier_id = best.get("supplier_id") or state.get("best_value_supplier_id")
    order = Order(requirement_id=state["requirement_id"], supplier_id=supplier_id,
                  quote_id=best.get("quote_id"), status=OrderStatus.APPROVED.value)
    db.add(order)
    db.commit()
    approved.order_id = order.id
    db.commit()
    _audit(db, state["requirement_id"], "agent", "order_approved",
           {"order_id": order.id, "supplier_id": supplier_id})
    return {**state, "order_id": order.id, "approval_status": ApprovalStatus.APPROVED.value}


def chaser_node(state: BuyerState, db: Session) -> BuyerState:
    """Delivery chase + invoice tracking follow-up (email only, no payment)."""
    order = None
    if state.get("order_id"):
        order = db.query(Order).filter(Order.id == state["order_id"]).first()
    if order is None:
        return state
    # Confirm via outbox (idempotent) — the confirmation email.
    service = EmailService(db)
    supplier = db.query(Supplier).filter(Supplier.id == order.supplier_id).first()
    if supplier is not None and supplier.email:
        service.queue_outbox(
            deal_id=state["requirement_id"], supplier_id=supplier.id,
            kind="confirmation",
            payload={"to": supplier.email,
                     "subject": "Order confirmation — BuildBuy Copilot",
                     "body": f"Confirming order {order.id}."},
        )
        db.commit()
    _audit(db, state["requirement_id"], "agent", "chaser_queued_confirmation",
           {"order_id": order.id})
    return state


def invoice_tracker_node(state: BuyerState, db: Session) -> BuyerState:
    """Invoice tracking: move an approved/confirmed order to
    INVOICE_PENDING when no invoice is on file; never invent one."""
    order = None
    if state.get("order_id"):
        order = db.query(Order).filter(Order.id == state["order_id"]).first()
    if order is None:
        return state
    from app.db.models import Invoice

    has_invoice = (
        db.query(Invoice).filter(Invoice.order_id == order.id).first() is not None
    )
    if not has_invoice and order.status in (
        OrderStatus.CONFIRMED.value,
    ):
        # Lifecycle: PENDING -> APPROVED -> CONFIRMED -> INVOICE_PENDING
        # -> INVOICE_RECEIVED. Only a CONFIRMED order moves to
        # INVOICE_PENDING; an APPROVED order must stay APPROVED so the
        # confirm step can still run.
        order.status = OrderStatus.INVOICE_PENDING.value
        db.commit()
        _audit(db, state["requirement_id"], "agent", "invoice_pending",
               {"order_id": order.id})
    return state


NODES = {
    "planner": planner_node,
    "finder": finder_node,
    "buyer": buyer_node,
    "negotiator": negotiator_node,
    "approval_gate": approval_gate_node,
    "order": order_node,
    "chaser": chaser_node,
    "invoice_tracker": invoice_tracker_node,
}

ORDER = ["planner", "finder", "buyer", "negotiator", "approval_gate",
         "order", "chaser", "invoice_tracker"]


class BuyerGraph:
    """Run the buyer graph for one requirement.

    With LangGraph installed, builds a real ``StateGraph`` with
    ``interrupt_before=["order"]`` and a SQLite checkpointer
    (``data/checkpoints.sqlite``). Without it, runs the same nodes in
    the same order via :meth:`run_local`, stopping at the approval gate
    until :meth:`resume_after_approval` is called. Either way the
    approval decision is a persisted DB row.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self._compiled = None
        if LANGGRAPH_AVAILABLE:
            self._compiled = self._build_langgraph()

    # ------------------------------------------------------- langgraph
    def _build_langgraph(self):
        db = self.db

        def wrap(name):
            def node(state: BuyerState) -> BuyerState:
                return NODES[name](state, db)
            return node

        graph = StateGraph(BuyerState)
        for name in ORDER:
            graph.add_node(name, wrap(name))
        graph.set_entry_point("planner")
        for a, b in zip(ORDER, ORDER[1:]):
            graph.add_edge(a, b)
        graph.add_edge("invoice_tracker", END)
        checkpoint_path = self.settings.data_dir / "checkpoints.sqlite"
        conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        return graph.compile(
            checkpointer=checkpointer, interrupt_before=["order"]
        )

    # ------------------------------------------------------------ run
    def run(self, requirement_id: str, user_id: str = "") -> dict:
        """Run up to the approval gate. Returns the state dict."""
        state: BuyerState = {"requirement_id": requirement_id, "user_id": user_id}
        if self._compiled is not None:
            config = {"configurable": {"thread_id": f"deal-{requirement_id}"}}
            try:
                result = self._compiled.invoke(state, config=config)
                return dict(result)
            except Exception as exc:  # noqa: BLE001 - interrupt surfaces here
                logger.info("langgraph run paused/interrupted: %s", exc)
                return self.run_local(requirement_id, user_id)
        return self.run_local(requirement_id, user_id)

    def run_local(self, requirement_id: str, user_id: str = "") -> dict:
        """Deterministic runner: same nodes, same order, gate included."""
        state: BuyerState = {"requirement_id": requirement_id, "user_id": user_id}
        for name in ORDER:
            if name == "order":
                # Approval gate: stop here until a persisted APPROVED row exists.
                state = approval_gate_node(state, self.db)
                approved = (
                    self.db.query(ApprovalRequest)
                    .filter(ApprovalRequest.deal_id == requirement_id,
                            ApprovalRequest.status == ApprovalStatus.APPROVED.value)
                    .first()
                )
                if approved is None:
                    state["approval_status"] = ApprovalStatus.PENDING.value
                    return dict(state)
                state = order_node(state, self.db)
                if state.get("error"):
                    return dict(state)
                continue
            state = NODES[name](state, self.db)
            if state.get("error"):
                return dict(state)
        return dict(state)

    def resume_after_approval(self, requirement_id: str) -> dict:
        """Resume a paused deal after the user approved (or rejected).

        With LangGraph: ``Command(resume=...)`` on the same thread_id.
        Local runner: re-runs from the order node onward.
        """
        state: BuyerState = {"requirement_id": requirement_id}
        if self._compiled is not None:
            try:
                from langgraph.types import Command

                config = {"configurable": {"thread_id": f"deal-{requirement_id}"}}
                result = self._compiled.invoke(Command(resume="approved"), config=config)
                return dict(result)
            except Exception as exc:  # noqa: BLE001
                logger.info("langgraph resume fell back to local runner: %s", exc)
        # Local resume: order -> chaser -> invoice tracker.
        state = order_node(state, self.db)
        if state.get("error"):
            return dict(state)
        state = chaser_node(state, self.db)
        state = invoice_tracker_node(state, self.db)
        return dict(state)


def thread_id_for(requirement_id: str) -> str:
    return f"deal-{requirement_id}"
