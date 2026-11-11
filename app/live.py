"""Live-data-only buyer flow — no storage, no database.

This module is the whole "live data only" rule in code:

* Everything it works on — the requirement, the takeoff, the ranked
  shortlist, the quote email, the user summary — is passed in as plain
  data and returned as plain data. NOTHING is read from or written to
  a database, a file, or any other store. The caller (the Streamlit
  session, or the ``POST /live/contact`` endpoint) holds the data for
  as long as the session lasts and drops it when the session ends.
* Sending is done through a ``send_email`` callable the caller
  supplies — in the app that is ``EmailService(db=None).send``
  (MockSMTP records a ``.eml`` file locally unless SMTP is
  configured, in which case it really sends). This module never
  invents a send: a call that is not approved, or has no official
  supplier email, sends nothing and says so.
* Idempotency is in-memory only: the caller passes a ``sent_keys``
  set that lives in the session. A second approval of the exact same
  email returns ``duplicate`` instead of sending twice. Closing the
  session clears the set — that is the honest consequence of having
  no storage: a new session cannot know what a previous session sent.

Imports: standard library only, so the Streamlit frontend can import
this module directly without pulling in SQLAlchemy or FastAPI.
"""

from __future__ import annotations

import hashlib
import re

USER_EMAIL = "deepthiag26@gmail.com"
AGENT_NAME = "BuildBuy Copilot"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?1?[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{4}")


def supplier_official_email(supplier: dict | None) -> str | None:
    """The supplier's OFFICIAL email on file, or None when none is held.

    Extracted from the supplier's ``email`` / ``contact`` field. A
    value like "not public — request via email" contains no address
    and returns None. No address is ever guessed, and a synthetic
    demo address (``*.example``) is returned as-is and labelled
    synthetic by the caller — it is the address on file, not a real
    supplier's inbox.
    """
    for key in ("email", "contact"):
        value = (supplier or {}).get(key) or ""
        m = _EMAIL_RE.search(str(value))
        if m:
            return m.group(0)
    return None


def strip_contact_details(body: str, buyer: dict | None = None) -> str:
    """Remove the buyer's name / email / phone (and any other email /
    phone) from an email body. Mirror of the frontend helper and of
    ``EmailService.strip_customer_identity`` — applied whenever
    contact sharing is OFF for that supplier, even if the user typed
    contact details into the edited draft themselves.
    """
    buyer = buyer or {}
    out = str(body or "")
    for value in (buyer.get("email", ""), buyer.get("phone", ""),
                  buyer.get("name", "")):
        if value and value.strip():
            out = out.replace(value, "[contact not shared]")
    out = _EMAIL_RE.sub("[contact not shared]", out)
    out = _PHONE_RE.sub("[contact not shared]", out)
    return out


def _fmt_money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def build_user_summary_email(*, requirement: dict | None,
                             materials: list[dict] | None,
                             contacted: list[dict],
                             user_name: str = "") -> dict:
    """The email sent to the USER (deepthiag26@gmail.com) after a
    contact: the quotation + the contacted supplier details.

    ``contacted`` is a list of dicts, one per supplier actually
    contacted: {"supplier": row, "to": email, "subject": subject,
    "body": body, "landed": float, "quality": int|None, "lead_days":
    int, "sent_status": "sent"|"mock_sent"|"duplicate"}.

    Returns {"to", "subject", "body"}. Nothing is sent by this
    function — it only builds the text; the caller sends it (or
    records it in Demo Mode) through ``contact_supplier``.
    """
    req = requirement or {}
    item = req.get("item") or "item"
    qty = req.get("quantity") or ""
    lines = [
        f"Hello{(' ' + user_name) if user_name else ''},",
        "",
        f"Your buying agent, {AGENT_NAME}, contacted the supplier(s) "
        f"below about your requirement: {qty} x {item}"
        + (f", delivery to {req['location']}" if req.get("location") else "")
        + (f", needed by {req['deadline']}" if req.get("deadline") else "")
        + (f", max budget ${_fmt_money(req['budget'])[1:]}"
           if req.get("budget") else "")
        + ".",
        "",
        "QUOTATION — what was asked for:",
    ]
    for m in (materials or []):
        lines.append(
            f"- {m.get('material', '')}: {m.get('quantity', '')} "
            f"{m.get('unit', '')} — {m.get('method', '')} "
            f"(estimate, not a surveyed quantity)")
    if not materials:
        lines.append("- (no materials takeoff in this session)")
    lines.append("")
    lines.append("SUPPLIERS CONTACTED:")
    for c in contacted:
        row = c.get("supplier") or {}
        details = c.get("details") or {}
        lines.append(
            f"- {row.get('name', 'Unknown supplier')} — "
            f"official email: {c.get('to') or 'not held'} · "
            f"phone: {details.get('phone') or 'not held'} · "
            f"address: {details.get('address') or 'not held'}"
            + (f" (area: {details['area']})" if details.get("area") else ""))
        lines.append(
            f"  Quotation: {_fmt_money(c.get('landed'))} landed for "
            f"{qty} · quality {c.get('quality') if c.get('quality') is not None else 'not scored'}/100"
            f" · lead {c.get('lead_days', '—')} days · MOQ {row.get('moq', '—')}")
        lines.append(f"  Asked: subject \"{c.get('subject', '')}\" — "
                     f"status: {c.get('sent_status', '')}")
        lines.append("  The full email text is in the app (Buyer Agent tab) "
                     "and in the shortlist Excel export.")
    lines.append("")
    lines.append(
        "Nothing has been ordered or paid — an order needs your tap "
        "on the approval screen in the app. You pay the supplier "
        "directly; this app never handles payment.")
    lines.append(f"\nThank you,\n{AGENT_NAME}")
    return {
        "to": USER_EMAIL,
        "subject": (f"BuildBuy Copilot — quotation + supplier contacted: "
                    f"{qty} x {item}"),
        "body": "\n".join(lines),
    }


def build_eml(to: str, subject: str, body: str) -> str:
    """Plain-text .eml content for one email (downloadable record)."""
    return (f"To: {to}\nSubject: {subject}\n"
            f"X-Mailer: {AGENT_NAME} (live, session-only)\n\n{body}")


def _contact_key(supplier_email: str, subject: str, body: str) -> str:
    digest = hashlib.sha256(
        f"{supplier_email}\n{subject}\n{body}".encode()).hexdigest()[:16]
    return f"contact:{supplier_email}:{digest}"


def contact_supplier(*, requirement: dict | None, materials: list[dict] | None,
                     supplier: dict, subject: str, body: str,
                     approved: bool, share_contact: bool,
                     buyer: dict | None, send_email,
                     sent_keys: set | None = None,
                     user_email: str = USER_EMAIL) -> dict:
    """Contact ONE supplier — approval-gated, edit already applied.

    ``subject`` / ``body`` are the FINAL edited texts (the caller
    shows them in the approval panel first). ``send_email`` is a
    callable ``(to, subject, body) -> dict`` — the caller supplies
    the real sender (``EmailService(db=None).send``) or a
    session-recording sender in Demo Mode.

    Returns {"status": "sent"|"mock_sent"|"duplicate"|"blocked",
    "supplier": {...}, "user_email": {...}|None, "reason": ...}.
    Raises ValueError when ``approved`` is False — nothing is ever
    sent without approval, and the caller must show the approval
    panel first. Returns "blocked" (sends NOTHING) when the supplier
    has no official email on file.
    """
    if not approved:
        raise ValueError(
            "Approval required: the supplier email must be approved "
            "before it is sent. Nothing was sent.")
    email = supplier_official_email(supplier)
    if not email:
        return {"status": "blocked", "reason": (
            "No official email held for this supplier — add their "
            "email before sending; no address is ever guessed."),
            "supplier": None, "user_email": None}
    final_body = body if share_contact else strip_contact_details(body, buyer)
    key = _contact_key(email, subject, final_body)
    sent_keys = sent_keys if sent_keys is not None else set()
    if key in sent_keys:
        return {"status": "duplicate", "reason": (
            "This exact email was already sent in this session."),
            "supplier": None, "user_email": None,
            "idempotency_key": key}
    result = send_email(to=email, subject=subject, body=final_body)
    sent_keys.add(key)
    sent_status = result.get("status", "sent") if isinstance(result, dict) else "sent"
    row = dict(supplier)
    contacted = [{
        "supplier": row,
        "details": {
            "phone": row.get("phone"),
            "address": row.get("address"),
            "area": row.get("location"),
        },
        "to": email,
        "subject": subject,
        "body": final_body,
        "landed": row.get("landed"),
        "quality": row.get("quality_score"),
        "lead_days": row.get("lead_days"),
        "sent_status": sent_status,
    }]
    summary = build_user_summary_email(
        requirement=requirement, materials=materials, contacted=contacted,
        user_name=(buyer or {}).get("name", ""))
    summary["to"] = user_email
    user_result = send_email(to=user_email, subject=summary["subject"],
                             body=summary["body"])
    return {
        "status": sent_status,
        "idempotency_key": key,
        "supplier": {"name": row.get("name"), "to": email,
                     "subject": subject, "body": final_body,
                     "send_result": result},
        "user_email": {"to": user_email, "subject": summary["subject"],
                       "body": summary["body"],
                       "send_result": user_result},
    }


def contact_suppliers_bulk(*, requirement: dict | None,
                           materials: list[dict] | None,
                           contacts: list[dict], approved: bool,
                           share_contact_by_name: dict | None,
                           buyer: dict | None, send_email,
                           sent_keys: set | None = None,
                           user_email: str = USER_EMAIL) -> dict:
    """Contact several suppliers at once, under ONE approval.

    ``contacts`` is a list of {"supplier", "subject", "body"} — the
    final edited texts per supplier. Suppliers with no official
    email are listed under "blocked" and never sent. ONE user summary
    email covers all suppliers actually contacted. Returns
    {"sent": [...], "blocked": [...], "duplicate": [...],
    "user_email": {...}|None}.
    """
    if not approved:
        raise ValueError(
            "Approval required: the supplier emails must be approved "
            "before they are sent. Nothing was sent.")
    share_by_name = share_contact_by_name or {}
    sent_keys = sent_keys if sent_keys is not None else set()
    sent, blocked, duplicate = [], [], []
    contacted_for_summary = []
    for c in contacts:
        supplier = c["supplier"]
        email = supplier_official_email(supplier)
        if not email:
            blocked.append({"name": supplier.get("name"),
                            "reason": "No official email held — no address guessed."})
            continue
        share = bool(share_by_name.get(supplier.get("name"), False))
        final_body = (c["body"] if share
                      else strip_contact_details(c["body"], buyer))
        key = _contact_key(email, c["subject"], final_body)
        if key in sent_keys:
            duplicate.append({"name": supplier.get("name"),
                              "reason": "This exact email was already sent in this session."})
            continue
        result = send_email(to=email, subject=c["subject"], body=final_body)
        sent_keys.add(key)
        sent_status = result.get("status", "sent") if isinstance(result, dict) else "sent"
        sent.append({"name": supplier.get("name"), "to": email,
                     "subject": c["subject"], "body": final_body,
                     "send_result": result})
        contacted_for_summary.append({
            "supplier": dict(supplier),
            "details": {"phone": supplier.get("phone"),
                        "address": supplier.get("address"),
                        "area": supplier.get("location")},
            "to": email, "subject": c["subject"], "body": final_body,
            "landed": supplier.get("landed"),
            "quality": supplier.get("quality_score"),
            "lead_days": supplier.get("lead_days"),
            "sent_status": sent_status,
        })
    user_email_record = None
    if contacted_for_summary:
        summary = build_user_summary_email(
            requirement=requirement, materials=materials,
            contacted=contacted_for_summary,
            user_name=(buyer or {}).get("name", ""))
        summary["to"] = user_email
        user_result = send_email(to=user_email, subject=summary["subject"],
                                 body=summary["body"])
        user_email_record = {"to": user_email, "subject": summary["subject"],
                             "body": summary["body"],
                             "send_result": user_result}
    return {"sent": sent, "blocked": blocked, "duplicate": duplicate,
            "user_email": user_email_record}
