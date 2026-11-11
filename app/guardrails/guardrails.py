"""Guardrails — reel skill #6.

Runs BEFORE the cache and BEFORE any email is sent (UNIFIED_PLAN_ARCHITECTURE
§2.4 S1): a violating input can never be served a cached answer or emailed
to a supplier.

Checks, in order: PII redaction (regex for email / phone / card; Presidio
used if installed), price-cap check (price > max -> block), deadline check
(past deadline -> block), policy blocklist, never-pay check (any payment
instruction -> block), contact-sharing check (toggle OFF -> contact is
stripped, never passed through).

Returns pass/fail + reason. A violation is NEVER silently passed: every
violation is listed in result.violations, and a blocked input returns
action="block" with the reason, not a cleaned-up pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")

# Policy blocklist: phrases that must never reach a supplier or an order.
BLOCKLIST = [
    "bypass approval",
    "ignore the price cap",
    "ignore the cap",
    "pay in advance",
    "gift card",
    "wire transfer",
    "crypto",
    "send payment now",
    "pay now",
    "transfer $",
    "confirm the order immediately",
    "skip approval",
]

PAYMENT_RE = re.compile(
    r"\b(pay|send payment|transfer|wire)\b.{0,30}\b(payment|money|\$|funds)\b",
    re.IGNORECASE,
)


@dataclass
class GuardrailResult:
    action: str  # "allow" | "redact" | "block"
    passed: bool
    reason: str
    text: str  # redacted text (safe to forward) or "" when blocked
    violations: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)


class Guardrails:
    """Deterministic guardrail layer. No LLM involved in the decision."""

    def __init__(self, use_presidio: bool = True):
        self._analyzer = None
        if use_presidio:
            try:
                from presidio_analyzer import AnalyzerEngine  # type: ignore

                self._analyzer = AnalyzerEngine()
            except Exception:
                self._analyzer = None  # Presidio not installed — regex only

    def redact_pii(self, text: str) -> tuple[str, list[str]]:
        """Redact email / phone / card numbers. Returns (text, redactions)."""
        redactions: list[str] = []
        if self._analyzer is not None:
            try:
                for r in self._analyzer.analyze(text=text, language="en"):
                    if r.entity_type in ("EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"):
                        redactions.append(r.entity_type)
                # Fall through to regex as well — belt and braces.
            except Exception:
                pass
        for pattern, label in ((EMAIL_RE, "EMAIL"), (PHONE_RE, "PHONE"), (CARD_RE, "CARD")):
            if pattern.search(text):
                text = pattern.sub(f"[{label}_REDACTED]", text)
                redactions.append(label)
        return text, sorted(set(redactions))

    def check(
        self,
        text: str,
        *,
        max_price: float | None = None,
        price: float | None = None,
        deadline: date | None = None,
        on_date: date | None = None,
        share_contact: bool = False,
        action: str = "email",
    ) -> GuardrailResult:
        violations: list[str] = []
        # 1. Price cap — code-enforced, not a prompt instruction.
        if max_price is not None and price is not None and price > max_price:
            violations.append(f"price_cap: ${price:.2f} exceeds max ${max_price:.2f}")
        # 2. Deadline.
        if deadline is not None:
            today = on_date or date.today()
            if today > deadline:
                violations.append(f"deadline: {today} is past deadline {deadline}")
        # 3. Blocklist.
        lowered = text.lower()
        for phrase in BLOCKLIST:
            if phrase in lowered:
                violations.append(f"blocklist: phrase '{phrase}'")
        # 4. Never-pay: any payment instruction is blocked outright.
        if PAYMENT_RE.search(text) or "pay now" in lowered:
            violations.append("never_pay: payment instruction is not allowed — buyer pays directly after approval")
        if violations:
            return GuardrailResult(
                action="block", passed=False,
                reason="; ".join(violations), text="", violations=violations,
            )
        # 5. PII redaction + contact-sharing check.
        redacted, redactions = self.redact_pii(text)
        if redactions and not share_contact:
            return GuardrailResult(
                action="redact", passed=True,
                reason=f"PII redacted ({', '.join(redactions)}); contact sharing is OFF",
                text=redacted, violations=[], redactions=redactions,
            )
        if redactions and share_contact:
            # Toggle ON: contact (email/phone) may pass, card numbers never do.
            card_only = [r for r in redactions if r == "CARD"]
            if card_only:
                return GuardrailResult(
                    action="redact", passed=True,
                    reason="Card number redacted even with contact sharing ON",
                    text=redacted, violations=[], redactions=redactions,
                )
            return GuardrailResult(
                action="allow", passed=True,
                reason="Contact sharing ON for this supplier; contact passed through",
                text=text, violations=[], redactions=[],
            )
        return GuardrailResult(
            action="allow", passed=True, reason="No violations", text=text,
        )
