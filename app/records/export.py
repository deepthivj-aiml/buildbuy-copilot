"""Full records export: requirement, plan, materials, suppliers, quotes,
negotiation, approval, order, invoice, audit log — as CSV + JSON + a
plain-text summary.

The summary is a PDF when ``reportlab`` is available, otherwise a
plain-text file labelled ``.txt`` — the export NEVER fails because
reportlab is missing.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalRequest,
    AuditLog,
    Invoice,
    Material,
    Message,
    Order,
    Outreach,
    Plan,
    Quote,
    Requirement,
    Shortlist,
    Simulation,
    Supplier,
)

try:
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.pdfgen import canvas as _pdf_canvas  # type: ignore

    REPORTLAB_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional dep
    REPORTLAB_AVAILABLE = False


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def build_records(req: Requirement, db: Session) -> dict:
    """Collect every record for one requirement into a plain dict."""
    req_id = req.id
    plans = db.query(Plan).filter(Plan.requirement_id == req_id).all()
    materials = db.query(Material).filter(Material.requirement_id == req_id).all()
    shortlist = db.query(Shortlist).filter(Shortlist.requirement_id == req_id).all()
    suppliers = {s.id: s for s in db.query(Supplier).all()}
    simulations = db.query(Simulation).filter(Simulation.requirement_id == req_id).all()
    outreach = db.query(Outreach).filter(Outreach.requirement_id == req_id).all()
    quotes = db.query(Quote).filter(Quote.requirement_id == req_id).all()
    orders = db.query(Order).filter(Order.requirement_id == req_id).all()
    invoices = db.query(Invoice).filter(Invoice.requirement_id == req_id).all()
    messages = db.query(Message).filter(Message.requirement_id == req_id).all()
    approvals = db.query(ApprovalRequest).filter(ApprovalRequest.deal_id == req_id).all()
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.requirement_id == req_id)
        .order_by(AuditLog.created_at)
        .all()
    )

    def supplier_name(sid):
        s = suppliers.get(sid)
        return s.name if s else (sid or "")

    return {
        "requirement": {
            "id": req.id, "source_type": req.source_type, "raw_text": req.raw_text,
            "items": req.items, "location": req.location,
            "deadline": req.deadline, "budget": _fmt(req.budget),
            "max_price": _fmt(req.max_price), "latest_date": req.latest_date,
            "status": req.status, "created_at": _fmt(req.created_at),
        },
        "plans": [
            {"id": p.id, "file_name": p.file_name, "file_type": p.file_type,
             "sheets": p.sheets, "scale": p.scale,
             "scale_confirmed": p.scale_confirmed} for p in plans
        ],
        "materials": [
            {"material": m.material, "quantity": _fmt(m.quantity), "unit": m.unit,
             "method": m.method, "confidence": _fmt(m.confidence),
             "flagged": m.flagged, "estimate_label": m.estimate_label}
            for m in materials
        ],
        "suppliers": [
            {"supplier": supplier_name(s.supplier_id),
             "rank": s.rank, "best_value_rank": s.best_value_rank,
             "unit_price": _fmt(s.unit_price), "landed_cost": _fmt(s.landed_cost),
             "fit_score": _fmt(s.fit_score), "why_rank": s.why_rank,
             "quality_score": _fmt(s.quality_score),
             "quality_evidence": s.quality_evidence,
             "quality_unknown": s.quality_unknown,
             "best_value_score": _fmt(s.best_value_score),
             "is_cheapest": s.is_cheapest,
             "is_highest_quality": s.is_highest_quality}
            for s in shortlist
        ],
        "simulations": [
            {"supplier": supplier_name(s.supplier_id),
             "landed_cost": _fmt(s.landed_cost), "delivery_date": s.delivery_date,
             "risk_score": _fmt(s.risk_score),
             "quality_score": _fmt(s.quality_score),
             "quality_risk": _fmt(s.quality_risk),
             "quality_risk_reason": s.quality_risk_reason,
             "what_if": s.what_if, "recommendation": s.recommendation}
            for s in simulations
        ],
        "outreach": [
            {"supplier": supplier_name(o.supplier_id), "channel": o.channel,
             "status": o.status, "contact_shared": o.contact_shared,
             "sent_at": _fmt(o.sent_at)} for o in outreach
        ],
        "quotes": [
            {"supplier": supplier_name(q.supplier_id),
             "unit_price": _fmt(q.unit_price), "total": _fmt(q.total),
             "lead_time_days": q.lead_time_days, "terms": q.terms,
             "source": q.source, "received_at": _fmt(q.received_at),
             "quality_score": _fmt(q.quality_score),
             "quality_evidence": q.quality_evidence} for q in quotes
        ],
        "negotiation": [
            {"supplier": supplier_name(m.supplier_id), "direction": m.direction,
             "subject": m.subject, "body": m.body, "sent_at": _fmt(m.sent_at)}
            for m in messages
        ],
        "approvals": [
            {"id": a.id, "status": a.status, "decided_by": a.decided_by,
             "decided_at": _fmt(a.decided_at), "payload": a.payload_json}
            for a in approvals
        ],
        "orders": [
            {"id": o.id, "supplier": supplier_name(o.supplier_id or ""),
             "status": o.status, "approved_at": _fmt(o.approved_at),
             "confirmed_at": _fmt(o.confirmed_at),
             "promised_date": o.promised_date} for o in orders
        ],
        "invoices": [
            {"invoice_number": i.invoice_number, "amount": _fmt(i.amount),
             "currency": i.currency, "received_at": _fmt(i.received_at),
             "file_ref": i.file_ref, "chase_count": i.chase_count,
             "chased_at": _fmt(i.chased_at)} for i in invoices
        ],
        "audit_log": [
            {"actor": a.actor, "action": a.action, "detail": a.detail,
             "created_at": _fmt(a.created_at)} for a in audit
        ],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Quantities are estimates, not surveyed measurements. "
            "Quality scores appear only where evidenced; missing quality "
            "means no evidence, not a low rating. Invoice data comes only "
            "from supplier-supplied records."
        ),
    }


def to_csv(records: dict) -> bytes:
    """One CSV with a section per record type (section, field, value rows)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "field", "value"])
    for section, content in records.items():
        if isinstance(content, list):
            for i, row in enumerate(content):
                if isinstance(row, dict):
                    for k, v in row.items():
                        writer.writerow([section, f"[{i}].{k}", _fmt(v)])
                else:
                    writer.writerow([section, f"[{i}]", _fmt(row)])
        elif isinstance(content, dict):
            for k, v in content.items():
                writer.writerow([section, k, _fmt(v)])
        else:
            writer.writerow([section, "", _fmt(content)])
    return buf.getvalue().encode("utf-8")


def to_json(records: dict) -> bytes:
    return json.dumps(records, indent=2, default=str).encode("utf-8")


def summary_text(records: dict) -> str:
    """Plain-text human-readable summary of the full record set."""
    req = records["requirement"]
    lines = [
        "BuildBuy Copilot — Records Summary",
        "=" * 40,
        f"Requirement: {req['id']} ({req['source_type']})",
        f"Items: {json.dumps(req['items'])}",
        f"Location: {req['location']}  Deadline: {req['deadline']}  "
        f"Budget: {req['budget']}  Status: {req['status']}",
        "",
        f"Materials ({len(records['materials'])} lines, estimates — not surveyed):",
    ]
    for m in records["materials"]:
        lines.append(f"  - {m['material']}: {m['quantity']} {m['unit']} "
                     f"({m['method']}, confidence {m['confidence']})")
    lines.append("")
    lines.append("Suppliers (best value = cost AND quality):")
    for s in records["suppliers"]:
        q = s["quality_score"] if s["quality_score"] != "" else "no evidence"
        lines.append(f"  - {s['supplier']}: best-value rank {s['best_value_rank']}, "
                     f"landed cost {s['landed_cost']}, quality {q}, "
                     f"cheapest={s['is_cheapest']}, highest-quality={s['is_highest_quality']}")
    lines.append("")
    lines.append(f"Quotes: {len(records['quotes'])}  Orders: {len(records['orders'])}  "
                 f"Invoices: {len(records['invoices'])}")
    for inv in records["invoices"]:
        lines.append(f"  - Invoice {inv['invoice_number']}: "
                     f"{inv['amount']} {inv['currency']} received {inv['received_at']}")
    lines.append("")
    lines.append(f"Audit events: {len(records['audit_log'])}")
    lines.append("")
    lines.append(records["disclaimer"])
    lines.append(f"Exported at: {records['exported_at']}")
    return "\n".join(lines)


def summary_pdf_or_text(records: dict) -> tuple[bytes, str]:
    """Return (bytes, filename). PDF when reportlab is present, else .txt."""
    text = summary_text(records)
    if not REPORTLAB_AVAILABLE:
        return text.encode("utf-8"), "summary.txt"
    buf = io.BytesIO()
    pdf = _pdf_canvas.Canvas(buf, pagesize=A4)
    y = 800
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "BuildBuy Copilot — Records Summary")
    y -= 24
    pdf.setFont("Helvetica", 10)
    for line in text.splitlines():
        if y < 40:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = 800
        pdf.drawString(40, y, line[:110])
        y -= 14
    pdf.save()
    return buf.getvalue(), "summary.pdf"


def build_export(req: Requirement, db: Session) -> dict:
    """Build all three artefacts. Keys: csv, json, summary_text, summary_file."""
    records = build_records(req, db)
    summary_bytes, summary_name = summary_pdf_or_text(records)
    return {
        "records": records,
        "csv": to_csv(records),
        "json": to_json(records),
        "summary_text": summary_text(records),
        "summary_bytes": summary_bytes,
        "summary_filename": summary_name,
    }
