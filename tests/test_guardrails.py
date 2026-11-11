"""Tests for guardrails — price cap, deadline, never-pay, PII redaction, contact toggle.

Run alone:  .venv/bin/python -m pytest tests/test_guardrails.py -v
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.guardrails.guardrails import Guardrails  # noqa: E402

DATA = ROOT / "data"


def test_guardrails():
    g = Guardrails()
    # Price above cap -> block, never silently passed.
    r = g.check("Quote is $500", max_price=400.0, price=500.0)
    assert r.action == "block" and not r.passed and "price_cap" in r.reason
    # Past deadline -> block.
    r = g.check("Confirm order", deadline=date(2026, 11, 1), on_date=date(2026, 11, 10))
    assert r.action == "block" and "deadline" in r.reason
    # Never-pay -> block (blocklist and/or payment-instruction rule).
    r = g.check("Please send payment now by wire transfer")
    assert r.action == "block" and not r.passed
    # PII with contact sharing OFF -> redacted, email never passes through.
    r = g.check("Contact me at buyer@example.com or 415-555-0132", share_contact=False)
    assert r.action == "redact" and "buyer@example.com" not in r.text
    assert "415-555-0132" not in r.text
    # Same text with sharing ON -> contact passes, card still never does.
    r = g.check("Contact me at buyer@example.com", share_contact=True)
    assert r.action == "allow" and "buyer@example.com" in r.text
    r = g.check("Card 4111 1111 1111 1111", share_contact=True)
    assert "4111" not in r.text
    # Clean text -> allow.
    r = g.check("Please send a quote for 10 m3 of concrete by Friday.")
    assert r.action == "allow" and r.passed
