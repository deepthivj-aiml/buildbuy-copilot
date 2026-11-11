"""Supplier-question escalation — the agent never guesses.

Rule (user, 2026-11-10): when a supplier asks a question the agent
cannot answer from the customer's stated requirement / limits, the
agent must NOT guess or invent an answer. Instead it emails the
customer, waits for the customer's reply, and then replies to the
supplier with the customer's answer.

What the agent CAN answer, from the requirement alone:
- the part / item and the quantity asked for
- the delivery location the customer typed
- the deadline / latest date
- the budget / max price the customer set

What it CANNOT answer (escalates): anything that needs a new decision
or information the customer never gave — payment terms (upfront /
deposit / advance), a discount or price beyond the stated limits, a
spec / grade / material the requirement does not name, a different
delivery address, warranty / returns / tax terms, or any other topic
outside the requirement. A question that mixes a known topic with an
unknown one escalates: the agent answers nothing until the customer
has answered the unknown part.

State (persisted, not in-memory):
- supplier question arrives -> inbound ``Message`` recorded, the
  supplier's ``Outreach`` row goes to ``NEEDS_CUSTOMER``, a
  customer-escalation email is queued (MockSMTP by default), audit
  ``supplier_question_escalated``.
- customer replies -> the reply is recorded as a ``Message``, the
  supplier reply is sent with the customer's words (agent identity
  line only added), ``Outreach`` returns to ``SENT``, audit
  ``customer_reply_sent_to_supplier``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import AuditLog, Message, Outreach, OutreachStatus
from app.email.service import EmailService, record_message

# Topics the agent must never answer on its own — they need a new
# customer decision or information the requirement never gave.
_UNANSWERABLE = (
    "upfront", "advance payment", "advance", "deposit", "prepay",
    "pre-pay", "pay in advance", "50%", "half now", "payment term",
    "payment method", "bank transfer", "card payment", "cash on delivery",
    "discount", "cheaper", "lower price", "negotiat", "warranty",
    "guarantee", "return", "refund", "tax", "gst", "vat",
    "delivery address", "different address", "ship to a different",
    "custom", "customise", "customize", "grade", "specification",
    "spec ", "material grade", "certification", "certificate",
    "invoice term", "credit term", "net 30", "net 60", "net 15",
)

# Topics that are already stated in the requirement — the agent may
# confirm them (and only them) without asking the customer.
_KNOWN = (
    "quantity", "how many", "units", "qty", "item", "part",
    "delivery location", "where", "location", "address",
    "deadline", "needed by", "when do you need", "by friday",
    "budget", "max price", "maximum price", "price limit",
)


def classify_supplier_question(question: str, requirement: dict) -> dict:
    """Classify a supplier question.

    Returns ``{"answerable": bool, "reason": str, "answer": str|None}``.
    ``answer`` is built only from values already in the requirement —
    never invented. An unanswerable question has ``answer=None``.
    """
    q = (question or "").lower()
    if not q.strip():
        return {"answerable": False, "reason": "empty question", "answer": None}
    if any(topic in q for topic in _UNANSWERABLE):
        return {"answerable": False,
                "reason": "question needs a new customer decision or "
                          "information not in the requirement (payment / "
                          "price / spec / warranty / terms)",
                "answer": None}
    if any(topic in q for topic in _KNOWN):
        items = requirement.get("items") or []
        parts = [f"{i.get('quantity', '')} x {i.get('item', '')}" for i in items]
        answer = (
            "Confirming from the requirement: "
            + (", ".join(parts) if parts else "no items listed")
            + (f"; delivery location: {requirement.get('location') or 'not given'}")
            + (f"; needed by: {requirement.get('deadline') or 'not given'}")
            + (f"; budget / max price: {requirement.get('max_price') or requirement.get('budget') or 'not given'}")
            + "."
        )
        return {"answerable": True,
                "reason": "question only asks to confirm what the "
                          "requirement already states",
                "answer": answer}
    return {"answerable": False,
            "reason": "question is about something not covered by the "
                      "requirement — the customer must answer it",
            "answer": None}


def requirement_summary(requirement) -> str:
    items = requirement.items or []
    parts = ", ".join(f"{i.get('quantity', '')} x {i.get('item', '')}" for i in items)
    return (parts or requirement.raw_text or requirement.id) + (
        f", delivery {requirement.location}" if requirement.location else "")


def escalate_supplier_question(db: Session, *, requirement, supplier,
                               question: str, user, subject: str = "") -> dict:
    """Record a supplier question, mark NEEDS_CUSTOMER, email the customer.

    No reply is sent to the supplier here — that is the whole point.
    Returns the escalation record (the inbound Message row).
    """
    msg = record_message(
        db, requirement_id=requirement.id, supplier_id=supplier.id,
        direction="inbound", sender=supplier.email or supplier.name,
        subject=subject or "Supplier question — BuildBuy Copilot",
        body=question)
    db.commit()
    outreach = (
        db.query(Outreach)
        .filter(Outreach.requirement_id == requirement.id,
                Outreach.supplier_id == supplier.id)
        .first()
    )
    if outreach is None:
        outreach = Outreach(requirement_id=requirement.id,
                            supplier_id=supplier.id, channel="email",
                            draft="", contact_shared=False)
        db.add(outreach)
    outreach.status = OutreachStatus.NEEDS_CUSTOMER.value
    db.commit()
    service = EmailService(db)
    sent = service.send_customer_question(
        deal_id=requirement.id, supplier_id=supplier.id,
        supplier_name=supplier.name, question=question,
        requirement_summary=requirement_summary(requirement))
    db.add(AuditLog(requirement_id=requirement.id, actor="agent",
                    action="supplier_question_escalated",
                    detail={"supplier_id": supplier.id,
                            "escalation_id": msg.id,
                            "question": question[:500],
                            "customer_email_status": sent.get("status"),
                            "customer_email": user.email}))
    db.commit()
    return {"escalation_id": msg.id, "status": "NEEDS_CUSTOMER",
            "supplier_id": supplier.id,
            "customer_email": user.email,
            "customer_email_status": sent.get("status")}


def reply_to_supplier_with_customer_answer(
        db: Session, *, requirement, supplier, escalation_id: str,
        customer_answer: str, user, share_contact: bool = False) -> dict:
    """Send the supplier the CUSTOMER's answer, verbatim + identity line.

    Raises ``ValueError`` when there is no pending escalation with this
    id, or when the customer answer is empty. The supplier email is
    mock-recorded unless SMTP is configured.
    """
    question_msg = (
        db.query(Message)
        .filter(Message.id == escalation_id,
                Message.requirement_id == requirement.id,
                Message.supplier_id == supplier.id,
                Message.direction == "inbound")
        .first()
    )
    if question_msg is None:
        raise ValueError(f"no supplier question with id {escalation_id} "
                         "for this requirement")
    outreach = (
        db.query(Outreach)
        .filter(Outreach.requirement_id == requirement.id,
                Outreach.supplier_id == supplier.id)
        .first()
    )
    if outreach is not None and outreach.status != OutreachStatus.NEEDS_CUSTOMER.value:
        raise ValueError("this supplier question is not waiting for the "
                         "customer — it is already answered or was never "
                         "escalated")
    if not (customer_answer or "").strip():
        raise ValueError("customer answer is empty — nothing to send")
    # Record the customer's reply (inbound to the agent, from the user).
    record_message(db, requirement_id=requirement.id, supplier_id=supplier.id,
                   direction="inbound", sender=user.email,
                   subject="Customer reply to supplier question",
                   body=customer_answer.strip())
    db.commit()
    if not supplier.email:
        raise ValueError(f"supplier {supplier.name} has no public email — "
                         "the reply cannot be sent")
    service = EmailService(db)
    sent = service.send_supplier_reply(
        to=supplier.email, deal_id=requirement.id, supplier_id=supplier.id,
        supplier_name=supplier.name, customer_answer=customer_answer.strip(),
        buyer_name=user.name or "", share_contact=share_contact)
    record_message(db, requirement_id=requirement.id, supplier_id=supplier.id,
                   direction="outbound", sender=user.email,
                   subject="Re: Quote request — BuildBuy Copilot",
                   body=(f"BuildBuy Copilot, acting as the buying agent for "
                         f"{user.name or 'a customer'}: {customer_answer.strip()}"))
    if outreach is not None:
        outreach.status = OutreachStatus.SENT.value
    db.add(AuditLog(requirement_id=requirement.id, actor="user",
                    action="customer_reply_sent_to_supplier",
                    detail={"supplier_id": supplier.id,
                            "escalation_id": escalation_id,
                            "contact_shared": share_contact,
                            "supplier_email_status": sent.get("status")}))
    db.commit()
    return {"escalation_id": escalation_id, "status": "SENT",
            "supplier_id": supplier.id,
            "supplier_email_status": sent.get("status"),
            "contact_shared": share_contact}


def pending_escalations(db: Session, requirement_id: str) -> list[dict]:
    """Escalations still waiting for the customer, with their questions.

    A supplier question is the inbound Message recorded by
    :func:`escalate_supplier_question` for a supplier whose Outreach
    row is still NEEDS_CUSTOMER. The customer's own reply is recorded
    with subject "Customer reply to supplier question" and is excluded.
    """
    waiting = {
        o.supplier_id for o in
        db.query(Outreach)
        .filter(Outreach.requirement_id == requirement_id,
                Outreach.status == OutreachStatus.NEEDS_CUSTOMER.value).all()
    }
    if not waiting:
        return []
    msgs = (
        db.query(Message)
        .filter(Message.requirement_id == requirement_id,
                Message.direction == "inbound",
                Message.supplier_id.in_(waiting),
                Message.subject != "Customer reply to supplier question")
        .order_by(Message.created_at).all()
    )
    return [{
        "escalation_id": m.id,
        "supplier_id": m.supplier_id,
        "question": m.body,
        "subject": m.subject,
        "asked_at": m.created_at.isoformat() if m.created_at else None,
        "status": "NEEDS_CUSTOMER",
    } for m in msgs]
