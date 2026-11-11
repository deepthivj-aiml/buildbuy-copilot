"""BuildBuy Copilot — FastAPI routes (plan §3.6 + new endpoints).

New endpoints (2026-11-10 brief):
- POST /requirements/{id}/buyer/message — chat message to a supplier via email
- GET  /requirements/{id}/buyer/inbox — full threads (also §3.6)
- POST /requirements/{id}/invoice — record invoice received (supplier
  data only; invoice_number/amount are required — never invented)
- POST /requirements/{id}/invoice/chase — chase an overdue invoice
- POST /requirements/{id}/summary — summary + full records export to user email
- GET  /requirements/{id}/records — CSV/JSON export download
- GET  /requirements/{id}/approval — approval pane: best-value, cheapest
  and highest-quality side by side, each with cost + quality + evidence

All endpoints use Pydantic validation and return honest errors
(no invented data, no silent failures). Auth-lite: ``X-User-Id`` /
``X-User-Email`` headers identify the user; a demo user is created
when no header is supplied.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.agents.escalation import (
    classify_supplier_question,
    escalate_supplier_question,
    pending_escalations,
    reply_to_supplier_with_customer_answer,
)
from app.agents.graph import BuyerGraph, LANGGRAPH_AVAILABLE
from app.config import get_settings
from app.db.models import (
    ApprovalRequest,
    ApprovalStatus,
    AuditLog,
    Invoice,
    Material,
    Message,
    ObservabilityEvent,
    Order,
    OrderStatus,
    Outreach,
    OutreachStatus,
    Plan,
    QAFeedback,
    QALog,
    Quote,
    Requirement,
    Shortlist,
    Simulation,
    Supplier,
    User,
    UserSummary,
)
from app.db.session import get_db
from app.email.service import (
    CUSTOMER_EMAIL,
    CUSTOMER_PHONE,
    EmailService,
    drain_outbox,
    record_message,
)
from app.integrations import (
    MODULE_AVAILABILITY,
    guardrail_check,
    rag_retrieve,
    redact_contact,
    run_takeoff,
    twin_simulate,
)
from app.observability import build_accuracy_dashboard, record_worst_answer_action
from app.ranking import rank_shortlist
from app.records.export import build_export
from app.schemas import (
    ApprovalOptionOut,
    ApprovalPaneOut,
    ApproveRequest,
    AskRequest,
    AskResponse,
    BuyerDraftRequest,
    BuyerMessageRequest,
    BuyerSendRequest,
    ChaseRequest,
    ContactSharingToggle,
    CustomerReplyRequest,
    EscalationOut,
    HealthOut,
    InboxThreadOut,
    InvoiceCreate,
    InvoiceOut,
    MaterialOut,
    MaterialPatch,
    MaterialsRerun,
    MessageOut,
    NegotiateRequest,
    OrderOut,
    AccuracyDashboardOut,
    SupplierQuestionRequest,
    WorstAnswerActionOut,
    WorstAnswerActionRequest,
    PlanUpload,
    RequirementCreate,
    RequirementOut,
    ScaleConfirm,
    SettingsPatch,
    ShortlistEntryOut,
    SimulateRequest,
    SimulationOut,
    SupplierCreate,
    SupplierOut,
    UserOut,
)

logger = logging.getLogger("buildbuy.api")
router = APIRouter()
settings = get_settings()

# ------------------------------------------------------------- helpers
_SHARING_FILE = settings.data_dir / "contact_sharing.json"


def _load_sharing() -> dict:
    if _SHARING_FILE.exists():
        try:
            return json.loads(_SHARING_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_sharing(data: dict) -> None:
    _SHARING_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SHARING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
) -> User:
    """Auth-lite: header identity, demo user fallback (created on demand)."""
    if x_user_id:
        user = db.query(User).filter(User.id == x_user_id).first()
        if user is not None:
            return user
    email = x_user_email or "demo@buildbuy.local"
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(name="Demo Buyer", email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _audit(db: Session, req_id: str | None, actor: str, action: str, detail: dict) -> None:
    db.add(AuditLog(requirement_id=req_id, actor=actor, action=action, detail=detail))
    db.commit()


def _observe(db: Session, *, request_id: str, user_id: str | None,
             requirement_id: str | None, step: str, latency_ms: int = 0,
             grounded: bool | None = None, cache_hit: bool = False,
             guardrail_action: str = "allow", guardrail_reason: str | None = None,
             cost_usd: float = 0.0) -> None:
    db.add(ObservabilityEvent(
        request_id=request_id, user_id=user_id, requirement_id=requirement_id,
        step=step, latency_ms=latency_ms, grounded=grounded,
        cache_hit=cache_hit, guardrail_action=guardrail_action,
        guardrail_reason=guardrail_reason, cost_usd=cost_usd))
    db.commit()


def _get_requirement(db: Session, req_id: str, user: User) -> Requirement:
    req = db.query(Requirement).filter(Requirement.id == req_id).first()
    if req is None:
        raise HTTPException(status_code=404, detail=f"requirement {req_id} not found")
    return req


def _get_supplier(db: Session, supplier_id: str) -> Supplier:
    sup = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if sup is None:
        raise HTTPException(status_code=404, detail=f"supplier {supplier_id} not found")
    return sup


def _shortlist_rows(db: Session, req_id: str) -> list[ShortlistEntryOut]:
    rows = (
        db.query(Shortlist, Supplier)
        .join(Supplier, Shortlist.supplier_id == Supplier.id)
        .filter(Shortlist.requirement_id == req_id)
        .order_by(Shortlist.best_value_rank, Shortlist.rank)
        .all()
    )
    return [
        ShortlistEntryOut(
            requirement_id=s.requirement_id, supplier_id=s.supplier_id,
            supplier_name=sup.name, rank=s.rank or 0,
            unit_price=s.unit_price, landed_cost=s.landed_cost,
            fit_score=s.fit_score, why_rank=s.why_rank or "",
            quality_score=s.quality_score,
            quality_evidence=s.quality_evidence or [],
            quality_unknown=s.quality_unknown,
            best_value_score=s.best_value_score,
            best_value_rank=s.best_value_rank,
            is_cheapest=s.is_cheapest, is_highest_quality=s.is_highest_quality,
        )
        for s, sup in rows
    ]


def _approval_pane(db: Session, req: Requirement) -> ApprovalPaneOut:
    """Best-value / cheapest / highest-quality side by side."""
    entries = _shortlist_rows(db, req.id)
    sims = {s.supplier_id: s for s in
            db.query(Simulation).filter(Simulation.requirement_id == req.id).all()}

    def option(kind: str, entry: ShortlistEntryOut | None) -> ApprovalOptionOut | None:
        if entry is None:
            return None
        sim = sims.get(entry.supplier_id)
        transport = (sim.what_if or {}).get("transport") or {} if sim else {}
        return ApprovalOptionOut(
            kind=kind, supplier_id=entry.supplier_id,
            supplier_name=entry.supplier_name,
            unit_price=entry.unit_price, landed_cost=entry.landed_cost,
            quality_score=entry.quality_score,
            quality_evidence=entry.quality_evidence,
            quality_unknown=entry.quality_unknown,
            best_value_score=entry.best_value_score,
            best_value_rank=entry.best_value_rank,
            is_cheapest=entry.is_cheapest,
            is_highest_quality=entry.is_highest_quality,
            risk_score=sim.risk_score if sim else None,
            quality_risk=sim.quality_risk if sim else None,
            quality_risk_reason=sim.quality_risk_reason if sim else "",
            why=entry.why_rank,
            transport_cost=transport.get("transport_cost"),
            transport_included=transport.get("transport_included"),
            landed_cost_label=transport.get("landed_cost_label"),
        )

    best_value = next((e for e in entries if e.best_value_rank == 1), entries[0] if entries else None)
    cheapest = next((e for e in entries if e.is_cheapest), None)
    highest_q = next((e for e in entries if e.is_highest_quality), None)
    no_quality = all(e.quality_unknown for e in entries) if entries else True
    note = (
        "No supplier in this shortlist has evidenced quality data — "
        "the ranking is on cost alone. Ask suppliers for certifications "
        "or references before choosing on quality."
        if no_quality else
        "Best value balances cost and evidenced quality. Quality scores "
        "appear only where evidenced; 'quality unknown' means no evidence, "
        "not a low rating."
    )
    # Transport honesty: landed costs that exclude transport say so.
    any_excl = any(
        ((sims.get(e.supplier_id).what_if or {}).get("transport") or {}).get(
            "transport_included") is False
        for e in entries if sims.get(e.supplier_id) is not None
    )
    if any_excl:
        note += (" Landed costs marked 'excl. transport' do not include "
                 "delivery — add a delivery location to compare total "
                 "landed cost including transport.")
    return ApprovalPaneOut(
        requirement_id=req.id,
        best_value=option("best_value", best_value),
        cheapest=option("cheapest", cheapest),
        highest_quality=option("highest_quality", highest_q),
        no_quality_evidence=no_quality, note=note,
    )


def _send_user_summary(db: Session, req: Requirement, trigger: str, subject: str,
                       body: str) -> None:
    """Summary email to the user (best-effort; failures are logged, never fatal)."""
    try:
        service = EmailService(db)
        service.send_user_summary(to=None, subject=subject, body=body, deal_id=req.id)
        db.add(UserSummary(requirement_id=req.id, trigger=trigger,
                           sent_to=settings.user_email, subject=subject))
        db.commit()
    except Exception as exc:  # noqa: BLE001 - summary must never break the flow
        logger.warning("user summary failed (%s): %s", trigger, exc)


def _summary_body(db: Session, req: Requirement, headline: str) -> str:
    pane = _approval_pane(db, req)
    lines = [f"BuildBuy Copilot — {headline}", "",
             f"Requirement: {req.raw_text or req.id}",
             f"Location: {req.location}  Deadline: {req.deadline}  Budget: {req.budget}", ""]
    for label, opt in (("Best value", pane.best_value), ("Cheapest", pane.cheapest),
                       ("Highest quality", pane.highest_quality)):
        if opt:
            q = opt.quality_score if opt.quality_score is not None else "no evidence"
            lines.append(f"{label}: {opt.supplier_name} — landed cost "
                         f"{opt.landed_cost}, quality {q}")
    lines.append("")
    lines.append("Full records: use GET /requirements/{id}/records on the API, "
                 "or reply to this email to request an export.")
    return "\n".join(lines)


# ---------------------------------------------------------- requirements
@router.post("/requirements", response_model=RequirementOut, status_code=201)
def create_requirement(payload: RequirementCreate, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    req = Requirement(
        user_id=user.id, source_type=payload.source_type,
        raw_text=payload.raw_text,
        items=[i.model_dump(mode="json") for i in payload.items],
        location=payload.location, deadline=payload.deadline,
        budget=payload.budget, max_price=payload.max_price,
        latest_date=payload.latest_date, status="created",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    _audit(db, req.id, "user", "requirement_created",
           {"source_type": req.source_type, "items": len(req.items or [])})
    return req


@router.get("/requirements/{req_id}", response_model=RequirementOut)
def get_requirement(req_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return _get_requirement(db, req_id, user)


# ---------------------------------------------------------------- plans
@router.post("/requirements/{req_id}/plans", status_code=201)
def upload_plan(req_id: str, payload: PlanUpload, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    plan = Plan(requirement_id=req.id, file_name=payload.file_name,
                file_type=payload.file_type, sheets=payload.sheets,
                spec_text=payload.spec_text)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    _audit(db, req.id, "user", "plan_uploaded",
           {"plan_id": plan.id, "file_name": plan.file_name, "sheets": plan.sheets})
    return {"plan_id": plan.id, "file_name": plan.file_name,
            "sheets": plan.sheets, "scale_confirmed": False,
            "note": "Confirm the scale before any measurement is taken."}


@router.post("/requirements/{req_id}/plans/{plan_id}/scale-confirm")
def scale_confirm(req_id: str, plan_id: str, payload: ScaleConfirm,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    plan = db.query(Plan).filter(Plan.id == plan_id,
                                 Plan.requirement_id == req.id).first()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan {plan_id} not found")
    plan.scale = payload.scale
    plan.scale_confirmed = payload.confirmed
    db.commit()
    _audit(db, req.id, "user", "scale_confirmed",
           {"plan_id": plan.id, "scale": plan.scale})
    return {"plan_id": plan.id, "scale": plan.scale,
            "scale_confirmed": plan.scale_confirmed}


# ------------------------------------------------------------------ ask
@router.post("/requirements/{req_id}/ask", response_model=AskResponse)
def ask(req_id: str, payload: AskRequest, db: Session = Depends(get_db),
        user: User = Depends(get_current_user)):
    from app.logging_setup import request_id_var

    started = time.monotonic()
    req = _get_requirement(db, req_id, user)
    passages = rag_retrieve(payload.question, plan_id=None, top_k=3)
    if not passages:
        answer = ("Not found — I can't read that from the uploaded plan or specs. "
                  "No passage supports an answer, so I won't guess.")
        qa = QALog(requirement_id=req.id, question=payload.question,
                   answer=answer, grounded=False)
        db.add(qa)
        db.commit()
        _observe(db, request_id=request_id_var.get(), user_id=user.id,
                 requirement_id=req.id, step="ask",
                 latency_ms=int((time.monotonic() - started) * 1000),
                 grounded=False)
        return AskResponse(answer=answer, grounded=False, found=False)
    top = passages[0]
    text = top.get("text") or top.get("passage") or ""
    answer = text if text else "Not found — the retrieved passage was empty."
    qa = QALog(requirement_id=req.id, question=payload.question, answer=answer,
               citation_image_region=top.get("region"),
               citation_spec_clause=top.get("clause") or text[:500],
               grounded=bool(text))
    db.add(qa)
    db.commit()
    db.refresh(qa)
    _observe(db, request_id=request_id_var.get(), user_id=user.id,
             requirement_id=req.id, step="ask",
             latency_ms=int((time.monotonic() - started) * 1000),
             grounded=bool(text))
    return AskResponse(answer=answer,
                       citation_image_region=top.get("region"),
                       citation_spec_clause=top.get("clause") or text[:500],
                       grounded=bool(text), found=True)


@router.post("/requirements/{req_id}/ask/{qa_id}/feedback")
def qa_feedback(req_id: str, qa_id: str, thumbs: int = Query(..., ge=-1, le=1),
                reason: str | None = Query(default=None),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    qa = db.query(QALog).filter(QALog.id == qa_id,
                                QALog.requirement_id == req_id).first()
    if qa is None:
        raise HTTPException(status_code=404, detail=f"qa entry {qa_id} not found")
    qa.thumbs = thumbs
    db.add(QAFeedback(qa_log_id=qa.id, user_id=user.id, thumbs=thumbs, reason=reason))
    db.commit()
    return {"qa_log_id": qa.id, "thumbs": thumbs}


# ------------------------------------------------------------- materials
@router.get("/requirements/{req_id}/materials", response_model=list[MaterialOut])
def get_materials(req_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    rows = db.query(Material).filter(Material.requirement_id == req.id).all()
    if not rows:
        # First read builds the takeoff (fallback: requirement items).
        plan = db.query(Plan).filter(Plan.requirement_id == req.id).first()
        lines = run_takeoff(
            {"items": req.items or []},
            {"file_name": plan.file_name} if plan else None,
        )
        for line in lines:
            db.add(Material(
                requirement_id=req.id, plan_id=plan.id if plan else None,
                material=str(line.get("material", "item")),
                quantity=float(line.get("quantity") or 0),
                unit=str(line.get("unit", "")),
                method=str(line.get("method", "")),
                confidence=line.get("confidence"),
                flagged=bool(line.get("flagged", False)),
                estimate_label=True))
        db.commit()
        rows = db.query(Material).filter(Material.requirement_id == req.id).all()
    return rows


@router.patch("/requirements/{req_id}/materials/{material_id}", response_model=MaterialOut)
def patch_material(req_id: str, material_id: str, payload: MaterialPatch,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    row = db.query(Material).filter(Material.id == material_id,
                                    Material.requirement_id == req.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"material {material_id} not found")
    if payload.material is not None:
        row.material = payload.material
    if payload.quantity is not None:
        row.quantity = payload.quantity
    if payload.unit is not None:
        row.unit = payload.unit
    db.commit()
    db.refresh(row)
    _audit(db, req.id, "user", "material_edited", {"material_id": row.id})
    return row


@router.post("/requirements/{req_id}/materials/rerun")
def rerun_materials(req_id: str, payload: MaterialsRerun,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    already = db.query(AuditLog).filter(
        AuditLog.requirement_id == req.id,
        AuditLog.action == "materials_rerun").first()
    if already is not None:
        raise HTTPException(status_code=409, detail=(
            "The one free re-run for this plan has already been used. "
            "Edit lines individually instead."))
    db.query(Material).filter(Material.requirement_id == req.id).delete()
    plan = db.query(Plan).filter(Plan.requirement_id == req.id).first()
    lines = run_takeoff({"items": req.items or []},
                        {"file_name": plan.file_name} if plan else None)
    for line in lines:
        db.add(Material(requirement_id=req.id, plan_id=plan.id if plan else None,
                        material=str(line.get("material", "item")),
                        quantity=float(line.get("quantity") or 0),
                        unit=str(line.get("unit", "")),
                        method=str(line.get("method", "")),
                        confidence=line.get("confidence"),
                        flagged=bool(line.get("flagged", False)),
                        estimate_label=True))
    db.commit()
    _audit(db, req.id, "user", "materials_rerun", {"feedback": payload.feedback[:500]})
    rows = db.query(Material).filter(Material.requirement_id == req.id).all()
    return rows


# ------------------------------------------------------------- suppliers
@router.get("/requirements/{req_id}/suppliers", response_model=list[ShortlistEntryOut])
def get_suppliers(req_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    return _shortlist_rows(db, req.id)


@router.post("/requirements/{req_id}/suppliers", response_model=SupplierOut, status_code=201)
def add_supplier(req_id: str, payload: SupplierCreate,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    sup = Supplier(
        name=payload.name, location=payload.location, email=payload.email,
        phone=payload.phone, address=payload.address,
        contact_source=payload.contact_source,
        contact_source_url=payload.contact_source_url,
        moq=payload.moq, lead_time_days=payload.lead_time_days,
        certifications=payload.certifications,
        quality_score=payload.quality_score,
        quality_evidence=payload.quality_evidence,
    )
    db.add(sup)
    db.flush()
    # Add to the shortlist with a placeholder landed cost (unknown until
    # a quote arrives — never invented). Ranking will score cost as 0
    # until a real price exists.
    db.add(Shortlist(requirement_id=req.id, supplier_id=sup.id, rank=0,
                     quality_score=payload.quality_score,
                     quality_evidence=payload.quality_evidence,
                     quality_unknown=payload.quality_score is None,
                     why_rank="User-added supplier — no quote yet."))
    db.commit()
    db.refresh(sup)
    _audit(db, req.id, "user", "supplier_added",
           {"supplier_id": sup.id, "contact_source": sup.contact_source})
    return sup


@router.get("/requirements/{req_id}/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(req_id: str, supplier_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    _get_requirement(db, req_id, user)
    sup = _get_supplier(db, supplier_id)
    # Contact shown only where public / supplier-provided / user-added —
    # which is exactly what contact_source records. Nothing is invented.
    return sup


@router.post("/requirements/{req_id}/simulate", response_model=list[SimulationOut])
def simulate(req_id: str, payload: SimulateRequest,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    entries = _shortlist_rows(db, req.id)
    if not entries:
        raise HTTPException(status_code=404, detail="no suppliers in shortlist to simulate")
    top3 = sorted(entries, key=lambda e: (e.best_value_rank or 99))[:3]
    results = []
    for entry in top3:
        sup = _get_supplier(db, entry.supplier_id)
        sim = twin_simulate(
            landed_cost=float(entry.landed_cost) if entry.landed_cost is not None else None,
            quality_score=float(entry.quality_score) if entry.quality_score is not None else None,
            quality_evidence=entry.quality_evidence or [],
            risk_flags=sup.risk_flags or [],
            lead_time_days=sup.lead_time_days,
            price_change_pct=payload.price_change_pct,
            delivery_slip_days=payload.delivery_slip_days,
            quantity_change_pct=payload.quantity_change_pct,
            transport_cost=payload.transport_cost,
            transport_included=payload.transport_included,
        )
        what_if = dict(sim["what_if"])
        what_if["transport"] = {
            "transport_cost": sim.get("transport_cost"),
            "transport_included": sim.get("transport_included"),
            "landed_cost_label": sim.get("landed_cost_label"),
        }
        row = Simulation(
            requirement_id=req.id, supplier_id=entry.supplier_id,
            landed_cost=sim["landed_cost"],
            delivery_date=None, risk_score=sim["risk_score"],
            quality_score=sim["quality_score"],
            quality_risk=sim["quality_risk"],
            quality_risk_reason=sim["quality_risk_reason"],
            what_if=what_if, recommendation=False)
        db.add(row)
        db.flush()
        results.append(SimulationOut(
            supplier_id=entry.supplier_id, supplier_name=entry.supplier_name,
            landed_cost=sim["landed_cost"], delivery_date=None,
            risk_score=sim["risk_score"], quality_score=sim["quality_score"],
            quality_risk=sim["quality_risk"],
            quality_risk_reason=sim["quality_risk_reason"],
            what_if=what_if, recommendation=False,
            transport_cost=sim.get("transport_cost"),
            transport_included=sim.get("transport_included"),
            landed_cost_label=sim.get("landed_cost_label")))
    if results:
        # Recommendation = lowest overall risk among the top 3.
        best = min(results, key=lambda r: float(r.risk_score or 100))
        for row in db.query(Simulation).filter(
                Simulation.requirement_id == req.id).all():
            row.recommendation = row.supplier_id == best.supplier_id
        for r in results:
            r.recommendation = r.supplier_id == best.supplier_id
    db.commit()
    _audit(db, req.id, "agent", "twin_simulated",
           {"suppliers": [r.supplier_id for r in results]})
    return results


# ----------------------------------------------------------- buyer agent
@router.post("/requirements/{req_id}/buyer/draft")
def buyer_draft(req_id: str, payload: BuyerDraftRequest,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    entries = _shortlist_rows(db, req.id)
    targets = [e for e in entries if not payload.supplier_ids or e.supplier_id in payload.supplier_ids][:3]
    if not targets:
        raise HTTPException(status_code=404, detail="no suppliers in shortlist to draft for")
    # draft_quote() identifies the agent ("BuildBuy Copilot, acting as
    # the buying agent for a customer") and, with share_contact=False,
    # never puts the customer's name / email / phone in the draft.
    draft = payload.message or EmailService.draft_quote(
        buyer_name=user.name or "the buyer",
        items=req.items or [], location=req.location,
        deadline=req.deadline,
        max_price=float(req.max_price) if req.max_price is not None else None,
        share_contact=False, buyer_email=user.email, buyer_phone=user.phone or "")
    for entry in targets:
        db.merge(Outreach(requirement_id=req.id, supplier_id=entry.supplier_id,
                          channel="email", draft=draft, contact_shared=False,
                          status=OutreachStatus.DRAFT.value))
    db.commit()
    _audit(db, req.id, "agent", "buyer_draft_created",
           {"suppliers": [e.supplier_id for e in targets]})
    return {"draft": draft, "suppliers": [e.supplier_id for e in targets],
            "note": "Draft shown before sending. Nothing is sent until you call /buyer/send."}


@router.post("/requirements/{req_id}/buyer/send")
def buyer_send(req_id: str, payload: BuyerSendRequest,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    entries = _shortlist_rows(db, req.id)
    targets = [e for e in entries if not payload.supplier_ids or e.supplier_id in payload.supplier_ids][:3]
    if not targets:
        raise HTTPException(status_code=404, detail="no suppliers in shortlist to contact")
    service = EmailService(db)
    results = []
    for entry in targets:
        sup = _get_supplier(db, entry.supplier_id)
        if not sup.email:
            results.append({"supplier_id": sup.id, "status": "skipped",
                            "reason": "supplier email is not public — request via email first"})
            continue
        draft_row = db.query(Outreach).filter(
            Outreach.requirement_id == req.id,
            Outreach.supplier_id == sup.id,
            Outreach.status == OutreachStatus.DRAFT.value).first()
        if draft_row is None:
            raise HTTPException(
                status_code=409,
                detail=f"draft must be generated first for supplier {sup.id} "
                       "(call /buyer/draft before /buyer/send)")
        # Per-supplier toggle: payload wins, else the persisted toggle
        # from POST /settings/contact-sharing/{supplier_id}. Default OFF.
        persisted = _load_sharing().get(f"{user.id}:{sup.id}", False)
        share = bool(payload.share_contact.get(sup.id, persisted))
        body = payload.draft or draft_row.draft
        if share:
            # Agent identity WITH the customer's name; contact only
            # because this supplier was explicitly toggled ON.
            from app.email.service import with_agent_identity

            body = with_agent_identity(body, user.name or "", True)
            if user.name:
                body = body.replace("acting as the buying agent for a customer",
                                    f"acting as the buying agent for {user.name}")
                body = body.replace("buying agent for a customer)",
                                    f"buying agent for {user.name})")
            if user.email not in body:
                body += f"\n\nYou can reach the customer directly at: {user.name or ''}, {user.email}" + (
                    f", {user.phone}" if user.phone else "")
        else:
            # Sharing OFF: strip name / email / phone entirely — the
            # supplier sees only "BuildBuy Copilot, buying agent for
            # a customer". redact_contact alone would miss the name.
            body = EmailService.strip_customer_identity(
                body, user.name or "", user.email, user.phone or "")
            from app.email.service import with_agent_identity

            body = with_agent_identity(body, "", False)
        check = guardrail_check(text=body, max_price=float(req.max_price) if req.max_price else None,
                                price=float(entry.landed_cost) if entry.landed_cost else None,
                                share_contact=share)
        if not check["allowed"]:
            results.append({"supplier_id": sup.id, "status": "blocked",
                            "reason": check["reason"]})
            _audit(db, req.id, "system", "buyer_send_blocked",
                   {"supplier_id": sup.id, "reason": check["reason"]})
            continue
        # Transactional outbox: same TX as the outreach status change.
        service.queue_outbox(deal_id=req.id, supplier_id=sup.id,
                             kind="quote_request",
                             payload={"to": sup.email,
                                      "subject": "Quote request — BuildBuy Copilot",
                                      "body": body})
        draft_row.status = OutreachStatus.SENT.value
        draft_row.sent_at = datetime.now(timezone.utc)
        draft_row.contact_shared = share
        db.commit()
        record_message(db, requirement_id=req.id, supplier_id=sup.id,
                       direction="outbound", sender=user.email,
                       subject="Quote request — BuildBuy Copilot", body=body)
        db.commit()
        _audit(db, req.id, "agent", "buyer_email_queued",
               {"supplier_id": sup.id, "contact_shared": share,
                "idempotency_key": f"email:{req.id}:{sup.id}:1"})
        results.append({"supplier_id": sup.id, "status": "queued",
                        "contact_shared": share})
    drained = drain_outbox(db)
    return {"results": results, "outbox": drained,
            "note": "Emails are mock-recorded unless SMTP is configured. See data/mock_mail/."}


@router.post("/requirements/{req_id}/buyer/message")
def buyer_message(req_id: str, payload: BuyerMessageRequest,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Send a chat message to a supplier via email (new endpoint)."""
    req = _get_requirement(db, req_id, user)
    sup = _get_supplier(db, payload.supplier_id)
    if not sup.email:
        raise HTTPException(status_code=422, detail=(
            f"supplier {sup.name} has no public email — contact is 'not public'. "
            "Ask for it in a quote email first; the address is never invented."))
    # Agent identity on every supplier message; contact stripped
    # entirely when sharing is OFF for this supplier.
    from app.email.service import with_agent_identity

    if payload.share_contact:
        body = with_agent_identity(payload.body, user.name or "", True)
        if user.name:
            body = body.replace("acting as the buying agent for a customer",
                                f"acting as the buying agent for {user.name}")
    else:
        body = EmailService.strip_customer_identity(
            payload.body, user.name or "", user.email, user.phone or "")
        body = with_agent_identity(body, "", False)
    check = guardrail_check(text=body, max_price=None, price=None,
                            share_contact=payload.share_contact)
    if not check["allowed"]:
        raise HTTPException(status_code=422, detail=f"guardrail blocked message: {check['reason']}")
    service = EmailService(db)
    service.queue_outbox(deal_id=req.id, supplier_id=sup.id, kind="buyer_message",
                         payload={"to": sup.email,
                                  "subject": payload.subject or "Message — BuildBuy Copilot",
                                  "body": body})
    db.commit()
    msg = record_message(db, requirement_id=req.id, supplier_id=sup.id,
                         direction="outbound", sender=user.email,
                         subject=payload.subject or "Message — BuildBuy Copilot",
                         body=body)
    db.commit()
    drain_outbox(db)
    _audit(db, req.id, "user", "buyer_message_sent",
           {"supplier_id": sup.id, "message_id": msg.id})
    return {"message_id": msg.id, "thread_id": msg.thread_id,
            "supplier_id": sup.id, "status": "sent (mock unless SMTP configured)"}


@router.post("/requirements/{req_id}/buyer/supplier-question")
def supplier_question(req_id: str, payload: SupplierQuestionRequest,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """A supplier asked a question — answer it only if the requirement
    already states the answer; otherwise ESCALATE to the customer.

    The agent never guesses: an unanswerable question emails the
    customer (deepthiag26@gmail.com) and sends NOTHING to the supplier.
    The supplier reply comes only after the customer answers, via
    POST /buyer/escalations/{escalation_id}/reply.
    """
    req = _get_requirement(db, req_id, user)
    sup = _get_supplier(db, payload.supplier_id)
    req_dict = {"items": req.items or [], "location": req.location,
                "deadline": req.deadline, "budget": req.budget,
                "max_price": req.max_price}
    decision = classify_supplier_question(payload.question, req_dict)
    if decision["answerable"]:
        _audit(db, req.id, "agent", "supplier_question_answered_from_requirement",
               {"supplier_id": sup.id, "question": payload.question[:500]})
        return {"status": "answered_from_requirement",
                "supplier_id": sup.id, "answer": decision["answer"],
                "reason": decision["reason"],
                "note": "Answered only from what the requirement already states."}
    result = escalate_supplier_question(
        db, requirement=req, supplier=sup, question=payload.question,
        user=user, subject=payload.subject)
    return {"status": "needs_customer", "supplier_id": sup.id,
            "escalation_id": result["escalation_id"],
            "customer_email": result["customer_email"],
            "customer_email_status": result["customer_email_status"],
            "reason": decision["reason"],
            "note": "No reply was sent to the supplier. The customer was "
                    "emailed and the deal waits for their answer."}


@router.get("/requirements/{req_id}/buyer/escalations",
            response_model=list[EscalationOut])
def list_escalations(req_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Supplier questions still waiting for the customer to answer."""
    req = _get_requirement(db, req_id, user)
    return pending_escalations(db, req.id)


@router.post("/requirements/{req_id}/buyer/escalations/{escalation_id}/reply")
def customer_reply(req_id: str, escalation_id: str,
                   payload: CustomerReplyRequest,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """The customer answers a supplier question; the agent passes it on.

    The supplier reply uses the customer's words verbatim (agent
    identity line only added). Customer contact is included only when
    ``share_contact`` is true for this supplier.
    """
    req = _get_requirement(db, req_id, user)
    # The escalation id is a Message id; find its supplier from it.
    from app.db.models import Message as _Message

    msg = db.query(_Message).filter(_Message.id == escalation_id,
                                    _Message.requirement_id == req.id).first()
    if msg is None or not msg.supplier_id:
        raise HTTPException(status_code=404,
                            detail=f"escalation {escalation_id} not found")
    sup = _get_supplier(db, msg.supplier_id)
    try:
        return reply_to_supplier_with_customer_answer(
            db, requirement=req, supplier=sup, escalation_id=escalation_id,
            customer_answer=payload.answer, user=user,
            share_contact=payload.share_contact)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/requirements/{req_id}/buyer/inbox", response_model=list[InboxThreadOut])
def buyer_inbox(req_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    messages = (db.query(Message).filter(Message.requirement_id == req.id)
                .order_by(Message.sent_at).all())
    outreach = {o.supplier_id: o for o in
                db.query(Outreach).filter(Outreach.requirement_id == req.id).all()}
    threads: dict[str, InboxThreadOut] = {}
    for m in messages:
        thread = threads.get(m.thread_id)
        sup = db.query(Supplier).filter(Supplier.id == m.supplier_id).first() if m.supplier_id else None
        if thread is None:
            status = outreach[m.supplier_id].status if m.supplier_id in outreach else "sent"
            thread = InboxThreadOut(
                thread_id=m.thread_id, supplier_id=m.supplier_id,
                supplier_name=sup.name if sup else None, status=status,
                last_message_at=m.sent_at, last_snippet=m.body[:120], messages=[])
            threads[m.thread_id] = thread
        thread.messages.append(MessageOut(
            id=m.id, thread_id=m.thread_id, supplier_id=m.supplier_id,
            direction=m.direction, sender=m.sender, subject=m.subject,
            body=m.body, sent_at=m.sent_at))
        thread.last_message_at = m.sent_at
        thread.last_snippet = m.body[:120]
    # Suppliers contacted but with no message rows yet (draft/queued only).
    for supplier_id, o in outreach.items():
        thread_id = f"thread:{req.id}:{supplier_id}"
        if thread_id not in threads:
            sup = db.query(Supplier).filter(Supplier.id == supplier_id).first()
            threads[thread_id] = InboxThreadOut(
                thread_id=thread_id, supplier_id=supplier_id,
                supplier_name=sup.name if sup else None, status=o.status,
                last_message_at=o.sent_at, last_snippet=o.draft[:120] if o.draft else "",
                messages=[])
    # No-reply list is derivable: outreach SENT with no inbound message.
    return list(threads.values())


@router.post("/requirements/{req_id}/buyer/negotiate")
def negotiate(req_id: str, payload: NegotiateRequest,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    sup = _get_supplier(db, payload.supplier_id)
    max_price = float(req.max_price) if req.max_price is not None else None
    if payload.counter_price is not None and max_price is not None \
            and float(payload.counter_price) > max_price:
        raise HTTPException(status_code=422, detail=(
            f"counter price {payload.counter_price} exceeds the buyer max price "
            f"{max_price} — negotiation within limits only."))
    quote = db.query(Quote).filter(Quote.requirement_id == req.id,
                                   Quote.supplier_id == sup.id).first()
    if quote is None:
        raise HTTPException(status_code=404, detail=(
            f"no quote on file from supplier {sup.name} — nothing to negotiate. "
            "A quote is never invented."))
    if payload.counter_price is not None:
        quote.unit_price = payload.counter_price
        quote.total = payload.counter_price
        quote.terms = (quote.terms or "") + f"\nCounter-offer: {payload.counter_price}."
        db.commit()
    _audit(db, req.id, "agent", "negotiation_round",
           {"supplier_id": sup.id, "counter_price": str(payload.counter_price or "")})
    _send_user_summary(db, req, "quotes_received",
                       "BuildBuy Copilot — quotes received",
                       _summary_body(db, req, "quotes received"))
    return {"supplier_id": sup.id, "status": "negotiated within limits",
            "counter_price": payload.counter_price}


# ------------------------------------------------------- approval pane
@router.get("/requirements/{req_id}/approval", response_model=ApprovalPaneOut)
def approval_pane(req_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    return _approval_pane(db, req)


@router.post("/requirements/{req_id}/approve")
def approve(req_id: str, payload: ApproveRequest,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Human approval — the ONLY path to an order (never-pay invariant)."""
    req = _get_requirement(db, req_id, user)
    pane = _approval_pane(db, req)
    if payload.decision == "reject":
        pending = (db.query(ApprovalRequest)
                   .filter(ApprovalRequest.deal_id == req.id,
                           ApprovalRequest.status == ApprovalStatus.PENDING.value)
                   .first())
        if pending is not None:
            pending.status = ApprovalStatus.REJECTED.value
            pending.decided_by = user.email
            pending.decided_at = datetime.now(timezone.utc)
            pending.resume_value = "rejected"
        existing_order = (db.query(Order).filter(Order.requirement_id == req.id)
                          .order_by(Order.created_at.desc()).first())
        if existing_order is not None and existing_order.status == OrderStatus.PENDING.value:
            existing_order.status = OrderStatus.REJECTED.value
        db.commit()
        _audit(db, req.id, "user", "deal_rejected", {"reason": payload.reason})
        return {"status": "rejected", "requirement_id": req.id,
                "detail": "deal rejected — no order placed"}
    # Approve: pick the supplier (explicit, else best-value, else cheapest).
    supplier_id = payload.supplier_id
    if not supplier_id and pane.best_value is not None:
        supplier_id = pane.best_value.supplier_id
    if not supplier_id and pane.cheapest is not None:
        supplier_id = pane.cheapest.supplier_id
    if not supplier_id:
        raise HTTPException(status_code=422, detail=(
            "nothing to approve — no supplier in the shortlist"))
    pending = (db.query(ApprovalRequest)
               .filter(ApprovalRequest.deal_id == req.id,
                       ApprovalRequest.status == ApprovalStatus.PENDING.value)
               .first())
    if pending is None:
        pending = ApprovalRequest(deal_id=req.id, payload_json={
            "best_offer": {"supplier_id": supplier_id, "quote_id": payload.quote_id},
            "best_value_supplier_id": pane.best_value.supplier_id if pane.best_value else None,
            "cheapest_supplier_id": pane.cheapest.supplier_id if pane.cheapest else None,
            "highest_quality_supplier_id": pane.highest_quality.supplier_id if pane.highest_quality else None,
            "no_quality_evidence": pane.no_quality_evidence})
        db.add(pending)
    pending.status = ApprovalStatus.APPROVED.value
    pending.decided_by = user.email
    pending.decided_at = datetime.now(timezone.utc)
    pending.resume_value = "approved"
    db.commit()
    _audit(db, req.id, "user", "deal_approved",
           {"supplier_id": supplier_id, "approval_id": pending.id})
    graph = BuyerGraph(db)
    state = graph.resume_after_approval(req.id)
    if state.get("error"):
        raise HTTPException(status_code=409, detail=state["error"])
    order = (db.query(Order).filter(Order.requirement_id == req.id)
             .order_by(Order.created_at.desc()).first())
    if order is None:
        order = Order(requirement_id=req.id, supplier_id=supplier_id,
                      quote_id=payload.quote_id, status=OrderStatus.APPROVED.value,
                      approved_at=datetime.now(timezone.utc))
        db.add(order)
        db.commit()
        db.refresh(order)
    _send_user_summary(db, req, "deal_approved",
                       "BuildBuy Copilot — deal approved",
                       _summary_body(db, req, "deal approved"))
    return OrderOut.model_validate(order).model_dump(mode="json")


@router.post("/requirements/{req_id}/confirm", response_model=OrderOut)
def confirm_order(req_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    order = (db.query(Order).filter(Order.requirement_id == req.id)
             .order_by(Order.created_at.desc()).first())
    if order is None:
        raise HTTPException(status_code=409, detail="no order exists — human approval required; approve a deal first")
    if order.status not in (OrderStatus.APPROVED.value, OrderStatus.PENDING.value):
        raise HTTPException(status_code=409, detail=(
            f"order cannot be confirmed from status {order.status}"))
    approved = (db.query(ApprovalRequest)
                .filter(ApprovalRequest.deal_id == req.id,
                        ApprovalRequest.status == ApprovalStatus.APPROVED.value)
                .first())
    if approved is None:
        raise HTTPException(status_code=409, detail=(
            "order cannot be confirmed without a persisted approval"))
    order.status = OrderStatus.CONFIRMED.value
    order.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    sup = db.query(Supplier).filter(Supplier.id == order.supplier_id).first() if order.supplier_id else None
    if sup is not None and sup.email:
        service = EmailService(db)
        service.queue_outbox(deal_id=req.id, supplier_id=sup.id, kind="confirmation",
                             payload={"to": sup.email,
                                      "subject": "Order confirmation — BuildBuy Copilot",
                                      "body": f"Confirming order {order.id} for requirement {req.id}."})
        db.commit()
        drain_outbox(db)
    _audit(db, req.id, "agent", "order_confirmed", {"order_id": order.id})
    _send_user_summary(db, req, "order_confirmed",
                       "BuildBuy Copilot — order confirmed",
                       _summary_body(db, req, "order confirmed"))
    return order


@router.post("/requirements/{req_id}/chase", response_model=OrderOut)
def chase_delivery(req_id: str, payload: ChaseRequest,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    order = (db.query(Order).filter(Order.requirement_id == req.id)
             .order_by(Order.created_at.desc()).first())
    if order is None or order.status != OrderStatus.CONFIRMED.value:
        raise HTTPException(status_code=409, detail=(
            "delivery chase requires a CONFIRMED order"))
    sup = db.query(Supplier).filter(Supplier.id == order.supplier_id).first() if order.supplier_id else None
    if sup is None or not sup.email:
        raise HTTPException(status_code=422, detail=(
            "supplier has no public email — delivery chase cannot be sent"))
    service = EmailService(db)
    service.send_chase(
        to=sup.email, deal_id=req.id, supplier_id=sup.id,
        body=(f"Hello,\n\nFollowing up on order {order.id} "
              f"(promised {order.promised_date or 'date not recorded'}). "
              f"Could you confirm the delivery status?\n\nThank you."))
    order.status = OrderStatus.CHASED.value
    db.commit()
    _audit(db, req.id, "agent", "delivery_chased",
           {"order_id": order.id, "reason": payload.reason})
    return order


# ------------------------------------------------------------- invoices
@router.post("/requirements/{req_id}/invoice", response_model=InvoiceOut, status_code=201)
def record_invoice(req_id: str, payload: InvoiceCreate,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Record an invoice received — supplier-supplied data ONLY.

    ``invoice_number`` and ``amount`` are required inputs. The API
    never generates, guesses, or defaults them.
    """
    req = _get_requirement(db, req_id, user)
    existing = (db.query(Invoice)
                .filter(Invoice.requirement_id == req.id,
                        Invoice.invoice_number == payload.invoice_number)
                .first())
    if existing is not None:
        raise HTTPException(status_code=409, detail=(
            f"invoice {payload.invoice_number} is already recorded for this requirement"))
    order = None
    if payload.order_id:
        order = db.query(Order).filter(Order.id == payload.order_id).first()
        if order is None:
            raise HTTPException(status_code=404, detail=f"order {payload.order_id} not found")
    inv = Invoice(
        requirement_id=req.id, order_id=order.id if order else None,
        supplier_id=payload.supplier_id, invoice_number=payload.invoice_number,
        amount=payload.amount, currency=payload.currency,
        received_at=payload.received_at or datetime.now(timezone.utc),
        file_ref=payload.file_ref)
    db.add(inv)
    if order is not None:
        order.status = OrderStatus.INVOICE_RECEIVED.value
    db.commit()
    db.refresh(inv)
    _audit(db, req.id, "user", "invoice_received",
           {"invoice_number": inv.invoice_number, "amount": str(inv.amount),
            "currency": inv.currency})
    _send_user_summary(db, req, "invoice_received",
                       "BuildBuy Copilot — invoice received",
                       _summary_body(db, req, "invoice received")
                       + f"\n\nInvoice {inv.invoice_number}: {inv.amount} {inv.currency}.")
    return inv


@router.post("/requirements/{req_id}/invoice/chase")
def chase_invoice(req_id: str, payload: ChaseRequest,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Chase an overdue invoice (or an invoice that was never sent)."""
    req = _get_requirement(db, req_id, user)
    order = (db.query(Order).filter(Order.requirement_id == req.id)
             .order_by(Order.created_at.desc()).first())
    if order is None:
        raise HTTPException(status_code=409, detail="no order exists for this requirement")
    inv = (db.query(Invoice).filter(Invoice.requirement_id == req.id)
           .order_by(Invoice.created_at.desc()).first())
    sup = db.query(Supplier).filter(
        Supplier.id == (inv.supplier_id if inv else order.supplier_id)).first()
    if sup is None or not sup.email:
        raise HTTPException(status_code=422, detail=(
            "supplier has no public email — invoice chase cannot be sent"))
    invoice_number = inv.invoice_number if inv else None
    service = EmailService(db)
    body = (
        f"Hello,\n\nFollowing up on order {order.id}.\n"
        + (f"Invoice {invoice_number} was received on {inv.received_at} "
           f"and is still outstanding. " if inv else
           "We have not yet received the invoice for this order. ")
        + "Could you please confirm the invoice status and payment details?\n\nThank you."
    )
    service.send_invoice_chase(to=sup.email, deal_id=req.id, supplier_id=sup.id,
                               invoice_number=invoice_number, body=body)
    if inv is not None:
        inv.chased_at = datetime.now(timezone.utc)
        inv.chase_count = (inv.chase_count or 0) + 1
    if order.status == OrderStatus.INVOICE_PENDING.value:
        order.status = OrderStatus.CHASED.value
    db.commit()
    _audit(db, req.id, "agent", "invoice_chased",
           {"invoice_number": invoice_number, "reason": payload.reason})
    return {"status": "invoice chase sent (mock unless SMTP configured)",
            "invoice_number": invoice_number,
            "chase_count": inv.chase_count if inv else 0}


# ------------------------------------------------------------- summary
@router.post("/requirements/{req_id}/summary")
def send_summary(req_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Send the summary + full records export to the user's email."""
    req = _get_requirement(db, req_id, user)
    export = build_export(req, db)
    service = EmailService(db)
    result = service.send_records_export(
        to=None, deal_id=req.id, csv_bytes=export["csv"],
        json_bytes=export["json"], summary_text=export["summary_text"])
    db.add(UserSummary(requirement_id=req.id, trigger="manual",
                       sent_to=settings.user_email,
                       subject="Your BuildBuy records export"))
    db.commit()
    _audit(db, req.id, "user", "summary_sent",
           {"sent_to": settings.user_email, "summary_file": export["summary_filename"]})
    return {"status": result["status"], "sent_to": settings.user_email,
            "summary_file": export["summary_filename"],
            "note": "Mock-recorded unless SMTP is configured. Files also saved under data/exports/."}


@router.get("/requirements/{req_id}/records")
def download_records(req_id: str, format: str = Query(default="csv", pattern="^(csv|json|summary)$"),
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    export = build_export(req, db)
    if format == "csv":
        return Response(content=export["csv"], media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="records-{req.id}.csv"'})
    if format == "json":
        return Response(content=export["json"], media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="records-{req.id}.json"'})
    media = "application/pdf" if export["summary_filename"].endswith(".pdf") else "text/plain"
    return Response(content=export["summary_bytes"], media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{export["summary_filename"]}"'})


# -------------------------------------------------------- graph / deals
@router.post("/requirements/{req_id}/buyer/run")
def run_buyer_graph(req_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Run the buyer graph up to the approval gate (no order without approval)."""
    req = _get_requirement(db, req_id, user)
    graph = BuyerGraph(db)
    state = graph.run(req.id, user.id)
    return {"requirement_id": req.id, "thread_id": f"deal-{req.id}",
            "approval_status": state.get("approval_status", "PENDING"),
            "best_value_supplier_id": state.get("best_value_supplier_id"),
            "cheapest_supplier_id": state.get("cheapest_supplier_id"),
            "highest_quality_supplier_id": state.get("highest_quality_supplier_id"),
            "no_quality_evidence": state.get("no_quality_evidence"),
            "error": state.get("error"),
            "graph": "langgraph" if LANGGRAPH_AVAILABLE else "local-runner (langgraph not installed)"}


@router.post("/deals/{req_id}/resume")
def resume_deal(req_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    req = _get_requirement(db, req_id, user)
    graph = BuyerGraph(db)
    state = graph.resume_after_approval(req.id)
    if state.get("error"):
        raise HTTPException(status_code=409, detail=state["error"])
    return {"requirement_id": req.id, "order_id": state.get("order_id"),
            "approval_status": state.get("approval_status")}


@router.get("/deals/{req_id}/approvals")
def deal_approvals(req_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _get_requirement(db, req_id, user)
    rows = (db.query(ApprovalRequest).filter(ApprovalRequest.deal_id == req_id)
            .order_by(ApprovalRequest.created_at).all())
    return [{"id": r.id, "status": r.status, "decided_by": r.decided_by,
             "decided_at": r.decided_at, "order_id": r.order_id,
             "payload": r.payload_json} for r in rows]


# --------------------------------------------------------------- orders
@router.get("/orders", response_model=list[OrderOut])
def list_orders(status: str | None = Query(default=None),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = (db.query(Order).join(Requirement, Order.requirement_id == Requirement.id)
         .filter(Requirement.user_id == user.id))
    if status:
        q = q.filter(Order.status == status.upper())
    return q.order_by(Order.created_at.desc()).all()


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")
    audit = (db.query(AuditLog).filter(AuditLog.requirement_id == order.requirement_id)
             .order_by(AuditLog.created_at).all())
    invoices = db.query(Invoice).filter(Invoice.order_id == order.id).all()
    return {
        "order": OrderOut.model_validate(order),
        "approval_pane": _approval_pane(db, _get_requirement(db, order.requirement_id, user)),
        "invoices": [InvoiceOut.model_validate(i) for i in invoices],
        "audit_trail": [{"actor": a.actor, "action": a.action,
                         "detail": a.detail, "created_at": a.created_at} for a in audit],
    }


# ------------------------------------------------------------- settings
@router.get("/settings", response_model=UserOut)
def get_settings_route(user: User = Depends(get_current_user)):
    return user


@router.patch("/settings", response_model=UserOut)
def patch_settings(payload: SettingsPatch, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    if payload.name is not None:
        user.name = payload.name
    if payload.phone is not None:
        user.phone = payload.phone
    db.commit()
    db.refresh(user)
    return user


@router.post("/settings/contact-sharing/{supplier_id}")
def toggle_contact_sharing(supplier_id: str, payload: ContactSharingToggle,
                           db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    _get_supplier(db, supplier_id)
    sharing = _load_sharing()
    sharing[f"{user.id}:{supplier_id}"] = payload.share
    _save_sharing(sharing)
    _audit(db, None, "user", "contact_sharing_toggled",
           {"supplier_id": supplier_id, "share": payload.share})
    return {"supplier_id": supplier_id, "share_contact": payload.share,
            "note": "Default is OFF. Sharing applies only to emails sent "
                    "after this toggle is set."}


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    return HealthOut(
        status="ok",
        email_backend="mock" if settings.is_mock_email else "smtp",
        database="postgres" if settings.database_url.startswith("postgres") else "sqlite",
        graph_available=LANGGRAPH_AVAILABLE,
    )


@router.get("/modules")
def module_status():
    """Which sibling modules are available (other workers' scope)."""
    return {"modules": MODULE_AVAILABILITY,
            "note": "Missing modules fall back to honest local behaviour; nothing is invented."}


# ------------------------------------------------------------- accuracy (observability)
@router.get("/accuracy", response_model=AccuracyDashboardOut)
def accuracy_dashboard(days: int = Query(default=30, ge=1, le=90),
                       db: Session = Depends(get_db)):
    """Whole Accuracy tab payload — the 8 separate metrics, trends,
    Worst Answers, Eval Run History and raw-event drill-down.

    Every value is measured or None ("no data yet" in the UI). There is
    no blended single accuracy score anywhere in this payload.
    """
    return build_accuracy_dashboard(db, days=days)


@router.post("/accuracy/worst-answers/{qa_id}/action",
             response_model=WorstAnswerActionOut)
def worst_answer_action(qa_id: str, payload: WorstAnswerActionRequest,
                        db: Session = Depends(get_db)):
    """Add one Worst Answer to the eval set, or mark it fixed.

    ``add_to_eval_set`` appends the QA pair to
    ``data/evals/worst_answers_eval.jsonl`` (deduped) and audits it;
    ``mark_fixed`` audits only. A repeat action is refused with 409
    (``error: "already recorded"``) instead of duplicating the entry.
    Unknown action → 400; missing QA row → 404.
    """
    try:
        result = record_worst_answer_action(db, qa_id, payload.action)
    except ValueError as exc:
        if str(exc).startswith("unknown action"):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.get("error"):
        return JSONResponse(status_code=409, content=result)
    return result
