"""Email service — MockSMTP by default, real SMTP only when configured.

Default behaviour (``EMAIL_PROVIDER=mock`` or no SMTP configured):
every "sent" email is recorded in the ``outbox`` table AND written to a
local file under ``data/mock_mail/``. NOTHING is ever sent for real in
mock mode. Real SMTP is used only when ``EMAIL_PROVIDER=smtp`` and
``SMTP_HOST``/``SMTP_USER``/``SMTP_PASSWORD`` are all set via env.

Every send goes through the transactional outbox pattern: the caller
writes an outbox row (same transaction as the business change) with a
deterministic idempotency key ``email:{deal}:{supplier}:{round}``; the
relay (:func:`drain_outbox`) sends each PENDING row once and marks it
SENT, so a crash mid-send can never double-send or lose an email.
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Message, Outbox, OutboxStatus

logger = logging.getLogger("buildbuy.email")

AGENT_NAME = "BuildBuy Copilot"
# The customer's contact, used ONLY when they have toggled sharing ON
# for that supplier. These are the user's own details from their file;
# they are never guessed and never included when sharing is OFF.
CUSTOMER_NAME = "Deepthi Jainlal"
CUSTOMER_EMAIL = "deepthiag26@gmail.com"
CUSTOMER_PHONE = "+1 341-252-9234"


def agent_identity_line(buyer_name: str = "", share_contact: bool = False) -> str:
    """Opening identity line for every supplier email.

    The agent always says it is the agent of the customer. When contact
    sharing is OFF, the customer is named only as "a customer" — no name,
    email or phone. When ON, the customer's name is given.
    """
    who = buyer_name.strip() if (share_contact and buyer_name.strip()) else "a customer"
    return f"Hello,\n\nI am {AGENT_NAME}, acting as the buying agent for {who}."


def with_agent_identity(body: str, buyer_name: str = "",
                        share_contact: bool = False) -> str:
    """Prepend the agent-identity line to a supplier email if absent."""
    if AGENT_NAME in body and "acting as the buying agent for" in body:
        return body
    return agent_identity_line(buyer_name, share_contact) + "\n\n" + body.lstrip()

# Tenacity if available, else a small local retry (task requirement).
try:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

    def _retry_decorator(fn):
        return retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=30),
            retry=retry_if_exception_type((smtplib.SMTPException, OSError)),
            reraise=True,
        )(fn)

    RETRY_AVAILABLE = True
except Exception:  # noqa: BLE001 - tenacity optional
    RETRY_AVAILABLE = False

    def _retry_decorator(fn):  # type: ignore[no-redef]
        import time

        def wrapper(*args, **kwargs):
            last: Exception | None = None
            for attempt in range(3):
                try:
                    return fn(*args, **kwargs)
                except (smtplib.SMTPException, OSError) as exc:
                    last = exc
                    time.sleep(min(2 ** attempt, 8))
            raise last  # type: ignore[misc]

        return wrapper


def idempotency_key(deal_id: str, supplier_id: str, round_no: int = 1) -> str:
    """Deterministic key: ``email:{deal}:{supplier}:{round}`` (plan §10.3.3)."""
    return f"email:{deal_id}:{supplier_id}:{round_no}"


def mock_mail_dir() -> Path:
    settings = get_settings()
    d = settings.data_dir / "mock_mail"
    d.mkdir(parents=True, exist_ok=True)
    return d


class EmailService:
    """Send (or mock-send) buyer-agent emails."""

    def __init__(self, db: Session | None = None) -> None:
        self.settings = get_settings()
        self.db = db

    # ------------------------------------------------------------ core
    def _write_mock_file(self, to: str, subject: str, body: str, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        path = mock_mail_dir() / f"{safe_key}.eml"
        path.write_text(
            f"To: {to}\nSubject: {subject}\nX-Idempotency-Key: {key}\n"
            f"X-Mock: true — NOT sent for real\n\n{body}",
            encoding="utf-8",
        )
        return path

    @_retry_decorator
    def _smtp_send(self, to: str, subject: str, body: str) -> None:
        settings = self.settings
        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            if settings.smtp_use_tls:
                server.starttls(context=context)
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        deal_id: str,
        supplier_id: str,
        round_no: int = 1,
        kind: str = "quote_request",
        attachments: list[tuple[str, bytes, str]] | None = None,
        key_override: str | None = None,
    ) -> dict:
        """Send one email, idempotently.

        Returns ``{"status": "sent"|"mock_sent"|"duplicate", ...}``.
        A replay with the same idempotency key returns ``duplicate``
        without re-sending. ``attachments`` are (filename, bytes, mime)
        — honoured by SMTP, recorded by name only in mock mode.
        ``key_override`` overrides the default
        ``email:{deal}:{supplier}:{round}`` key (used for one-off
        emails such as customer escalations, where the round key would
        collide with the quote request for the same deal/supplier).
        """
        key = key_override or idempotency_key(deal_id, supplier_id, round_no)
        if self.db is not None:
            existing = (
                self.db.query(Outbox).filter(Outbox.idempotency_key == key).first()
            )
            if existing is not None and existing.status == OutboxStatus.SENT.value:
                logger.info("duplicate email suppressed key=%s", key)
                return {"status": "duplicate", "idempotency_key": key}

        if self.settings.is_mock_email:
            path = self._write_mock_file(to, subject, body, key)
            logger.info("mock email recorded to=%s key=%s file=%s", to, key, path.name)
            self._mark_sent(key, deal_id, supplier_id, kind, to, subject, body)
            return {"status": "mock_sent", "idempotency_key": key, "file": str(path)}

        self._smtp_send(to, subject, body)
        logger.info("smtp email sent to=%s key=%s", to, key)
        self._mark_sent(key, deal_id, supplier_id, kind, to, subject, body)
        return {"status": "sent", "idempotency_key": key}

    def _mark_sent(self, key, deal_id, supplier_id, kind, to, subject, body) -> None:
        if self.db is None:
            return
        row = self.db.query(Outbox).filter(Outbox.idempotency_key == key).first()
        now = datetime.now(timezone.utc)
        if row is None:
            row = Outbox(
                deal_id=deal_id,
                supplier_id=supplier_id,
                kind=kind,
                payload_json={"to": to, "subject": subject, "body": body},
                idempotency_key=key,
            )
            self.db.add(row)
        row.status = OutboxStatus.SENT.value
        row.sent_at = now
        row.attempts = (row.attempts or 0) + 1
        self.db.commit()

    def queue_outbox(
        self, *, deal_id: str, supplier_id: str, kind: str, payload: dict, round_no: int = 1
    ) -> Outbox | None:
        """Write an outbox row (same TX as the caller's business change).

        Call this BEFORE committing the approval/order, then
        :func:`drain_outbox` sends it. Returns None when no DB is bound.
        """
        if self.db is None:
            return None
        key = idempotency_key(deal_id, supplier_id, round_no)
        existing = self.db.query(Outbox).filter(Outbox.idempotency_key == key).first()
        if existing is not None:
            return existing
        row = Outbox(
            deal_id=deal_id,
            supplier_id=supplier_id,
            kind=kind,
            payload_json=payload,
            idempotency_key=key,
        )
        self.db.add(row)
        self.db.flush()
        return row

    # ------------------------------------------------- message builders
    @staticmethod
    def strip_customer_identity(body: str, buyer_name: str = "",
                                buyer_email: str = "", buyer_phone: str = "") -> str:
        """Remove the customer's name / email / phone from a supplier email.

        Used whenever contact sharing is OFF for that supplier: the
        supplier must see only "BuildBuy Copilot, buying agent for a
        customer" — no name, email or phone, even if the draft text
        typed by the user contained them.
        """
        out = body
        for value in (buyer_email, buyer_phone, buyer_name):
            if value and value.strip():
                out = out.replace(value, "[contact not shared]")
        # Also redact any other email / phone the text may contain.
        import re as _re

        out = _re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                      "[contact not shared]", out)
        out = _re.sub(r"\+?1?[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{4}",
                      "[contact not shared]", out)
        return out

    @staticmethod
    def draft_quote(*, buyer_name: str, items: list[dict], location: str,
                    deadline: str | None, max_price: float | None,
                    share_contact: bool, buyer_email: str = "",
                    buyer_phone: str = "") -> str:
        """Quote-request draft.

        The agent ALWAYS identifies itself as the buying agent of the
        customer, and enquires about the specific part + quantity (plus
        deadline / budget where the customer gave them). When contact
        sharing is OFF, the customer is only "a customer" — their name,
        email and phone never appear. When ON, their contact is included
        so the supplier can reach them directly.
        """
        who = buyer_name.strip() if share_contact else "a customer"
        lines = [
            f"Hello,",
            "",
            f"I am {AGENT_NAME}, acting as the buying agent for {who}.",
            "",
            "I am enquiring on their behalf about the following part, "
            "and would like a quote:",
        ]
        for item in items:
            lines.append(f"- {item.get('quantity', '')} x {item.get('item', '')}")
        if location:
            lines.append(f"\nDelivery location: {location}")
        if deadline:
            lines.append(f"Needed by: {deadline}")
        if max_price is not None:
            lines.append(f"Budget (max): ${max_price}")
        lines.append("\nCould you please send your best price, lead time, and delivery cost?")
        if share_contact:
            contact_parts = [p for p in [buyer_name, buyer_email, buyer_phone] if p]
            if contact_parts:
                lines.append("\nYou can reach the customer directly at: "
                             + ", ".join(contact_parts))
        lines.append(f"\nThank you,\n{AGENT_NAME} (buying agent for {who})")
        return "\n".join(lines)

    def send_customer_question(self, *, deal_id: str, supplier_id: str,
                               supplier_name: str, question: str,
                               requirement_summary: str) -> dict:
        """Escalation email to the CUSTOMER (never a guess to the supplier).

        Sent when a supplier asks a question the agent cannot answer
        from the customer's stated requirement / limits. The customer
        replies; only then does the agent reply to the supplier, using
        the customer's words. Mock-recorded unless SMTP is configured.
        """
        import hashlib

        key = ("escalation:" + deal_id + ":" + supplier_id + ":"
               + hashlib.sha256(question.encode()).hexdigest()[:12])
        body = (
            f"Hello,\n\n"
            f"Your buying agent, {AGENT_NAME}, needs your help.\n\n"
            f"Supplier {supplier_name} asked a question about your "
            f"requirement ({requirement_summary}) that I cannot answer "
            f"from what you told me, so I have not guessed or replied "
            f"to them:\n\n"
            f"\"{question}\"\n\n"
            f"Please reply to this email (or answer in the app) with "
            f"your answer, and I will pass it on to the supplier in "
            f"your words.\n\n"
            f"Thank you,\n{AGENT_NAME}"
        )
        return self.send(
            to=self.settings.user_email,
            subject=f"BuildBuy Copilot — supplier question needs your answer ({supplier_name})",
            body=body, deal_id=deal_id, supplier_id=supplier_id,
            round_no=1, kind="customer_escalation", key_override=key)

    def send_supplier_reply(self, *, to: str, deal_id: str, supplier_id: str,
                            supplier_name: str, customer_answer: str,
                            buyer_name: str = "", share_contact: bool = False) -> dict:
        """Reply to a supplier with the CUSTOMER's answer (post-escalation).

        The customer's words are passed on verbatim; the agent adds only
        its identity line. Contact is included only when sharing is ON
        for this supplier.
        """
        body = with_agent_identity(
            f"Thank you for your question. On behalf of the customer:\n\n"
            f"{customer_answer}",
            buyer_name, share_contact)
        if not share_contact:
            body = self.strip_customer_identity(
                body, buyer_name, CUSTOMER_EMAIL, CUSTOMER_PHONE)
        return self.send(
            to=to, subject="Re: Quote request — BuildBuy Copilot",
            body=body, deal_id=deal_id, supplier_id=supplier_id,
            round_no=3, kind="supplier_reply")

    def send_quote(self, *, to: str, deal_id: str, supplier_id: str, draft: str,
                   round_no: int = 1) -> dict:
        return self.send(to=to, subject="Quote request — BuildBuy Copilot",
                         body=draft, deal_id=deal_id, supplier_id=supplier_id,
                         round_no=round_no, kind="quote_request")

    def send_negotiation(self, *, to: str, deal_id: str, supplier_id: str,
                         body: str, round_no: int = 2) -> dict:
        return self.send(to=to, subject="Re: Quote request — BuildBuy Copilot",
                         body=body, deal_id=deal_id, supplier_id=supplier_id,
                         round_no=round_no, kind="negotiation")

    def send_confirmation(self, *, to: str, deal_id: str, supplier_id: str,
                          body: str) -> dict:
        return self.send(to=to, subject="Order confirmation — BuildBuy Copilot",
                         body=body, deal_id=deal_id, supplier_id=supplier_id,
                         round_no=1, kind="confirmation")

    def send_chase(self, *, to: str, deal_id: str, supplier_id: str, body: str) -> dict:
        return self.send(to=to, subject="Delivery follow-up — BuildBuy Copilot",
                         body=body, deal_id=deal_id, supplier_id=supplier_id,
                         round_no=1, kind="delivery_chase")

    def send_invoice_chase(self, *, to: str, deal_id: str, supplier_id: str,
                           invoice_number: str | None, body: str) -> dict:
        subject = "Invoice follow-up — BuildBuy Copilot"
        if invoice_number:
            subject = f"Invoice {invoice_number} follow-up — BuildBuy Copilot"
        return self.send(to=to, subject=subject, body=body,
                         deal_id=deal_id, supplier_id=supplier_id,
                         round_no=1, kind="invoice_chase")

    def send_buyer_message(self, *, to: str, deal_id: str, supplier_id: str,
                           subject: str, body: str,
                           buyer_name: str = "", share_contact: bool = False) -> dict:
        body = with_agent_identity(body, buyer_name, share_contact)
        if not share_contact:
            body = self.strip_customer_identity(
                body, buyer_name, CUSTOMER_EMAIL, CUSTOMER_PHONE)
        return self.send(to=to, subject=subject or "Message — BuildBuy Copilot",
                         body=body, deal_id=deal_id, supplier_id=supplier_id,
                         round_no=1, kind="buyer_message")

    def send_user_summary(self, *, to: str | None, subject: str, body: str,
                          deal_id: str) -> dict:
        """Summary email to the user (quotes / approval / order / invoice).

        ``to`` defaults to the configured USER_EMAIL env value.
        """
        recipient = to or self.settings.user_email
        return self.send(to=recipient, subject=subject, body=body,
                         deal_id=deal_id, supplier_id="user",
                         round_no=1, kind="user_summary")

    def send_records_export(self, *, to: str | None, deal_id: str,
                            csv_bytes: bytes, json_bytes: bytes,
                            summary_text: str) -> dict:
        """Records export to the user: CSV + JSON + plain-text summary.

        Attachments are sent for real only under SMTP; in mock mode the
        files are written next to the mock email and named in the record.
        """
        recipient = to or self.settings.user_email
        data_dir = get_settings().data_dir / "exports" / deal_id
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "records.csv").write_bytes(csv_bytes)
        (data_dir / "records.json").write_bytes(json_bytes)
        (data_dir / "summary.txt").write_text(summary_text, encoding="utf-8")
        body = (
            "Your full BuildBuy Copilot records export is attached.\n\n"
            "Files: records.csv, records.json, summary.txt\n\n"
            "This export contains your requirement, plan, materials, "
            "suppliers, quotes, negotiation, approval, order, invoice "
            "and audit-log records."
        )
        attachments = [
            ("records.csv", csv_bytes, "text/csv"),
            ("records.json", json_bytes, "application/json"),
            ("summary.txt", summary_text.encode(), "text/plain"),
        ]
        return self.send(to=recipient, subject="Your BuildBuy records export",
                         body=body, deal_id=deal_id, supplier_id="user",
                         round_no=1, kind="records_export",
                         attachments=attachments)


def drain_outbox(db: Session, limit: int = 20) -> dict:
    """Relay: send PENDING outbox rows (oldest first), idempotently.

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` on Postgres; SQLite takes
    the plain ordered query (no SKIP LOCKED support). Failed rows are
    retried up to ``outbox_max_attempts``, then DEAD_LETTER for human
    review — never silently dropped.
    """
    settings = get_settings()
    service = EmailService(db)
    rows = (
        db.query(Outbox)
        .filter(Outbox.status == OutboxStatus.PENDING.value)
        .order_by(Outbox.created_at)
        .limit(limit)
        .all()
    )
    sent, failed, dead = 0, 0, 0
    for row in rows:
        payload = row.payload_json or {}
        try:
            service.send(
                to=payload.get("to", ""),
                subject=payload.get("subject", ""),
                body=payload.get("body", ""),
                deal_id=row.deal_id or "",
                supplier_id=row.supplier_id or "",
                round_no=1,
                kind=row.kind,
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001 - relay must not die on one row
            row.attempts = (row.attempts or 0) + 1
            row.error = str(exc)[:500]
            if row.attempts >= settings.outbox_max_attempts:
                row.status = OutboxStatus.DEAD_LETTER.value
                dead += 1
            else:
                failed += 1
            db.commit()
            logger.warning("outbox send failed key=%s: %s", row.idempotency_key, exc)
    return {"sent": sent, "failed": failed, "dead_letter": dead, "checked": len(rows)}


def record_message(db: Session, *, requirement_id: str, supplier_id: str | None,
                   direction: str, sender: str, subject: str, body: str,
                   thread_id: str | None = None) -> Message:
    """Persist one inbox message (outbound or inbound)."""
    thread = thread_id or f"thread:{requirement_id}:{supplier_id or 'user'}"
    msg = Message(
        requirement_id=requirement_id,
        supplier_id=supplier_id,
        thread_id=thread,
        direction=direction,
        sender=sender,
        subject=subject,
        body=body,
    )
    db.add(msg)
    db.flush()
    return msg
