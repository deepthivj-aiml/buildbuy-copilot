"""Tests for the UI theme (frontend/theme.py) — pure helpers, no Streamlit.

Run alone:  .venv/bin/python -m pytest tests/test_theme.py -v
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend"))

import theme  # noqa: E402


def test_palette_and_css_are_consistent():
    assert theme.PALETTE["primary"] == "#7C4A21"  # warm brown (2026-11-10 21:32)
    assert theme.PALETTE["ink"] == "#2E1F14"
    assert theme.PALETTE["primary"] in theme.THEME_CSS
    assert theme.PALETTE["page_bg"] == "#FBF6EF"
    assert ".hero" in theme.THEME_CSS and ".journey" in theme.THEME_CSS
    assert ".chip-best" in theme.THEME_CSS and ".chip-pending" in theme.THEME_CSS
    assert "stBaseButton-primary" in theme.THEME_CSS
    assert "linear-gradient" in theme.THEME_CSS
    # Brown theme: no indigo left in the CSS (primary, hero, buttons,
    # stepper, metric numbers all use the brown palette).
    assert "#4F46E5" not in theme.THEME_CSS
    assert "#7C3AED" not in theme.THEME_CSS
    assert "#0D9488" not in theme.THEME_CSS
    assert "linear-gradient(135deg, #5C3413" in theme.THEME_CSS


def test_status_chips_keep_their_text_label():
    """Colour is decoration only: the label text is always rendered,
    and labels are HTML-escaped."""
    chip = theme.status_chip("Best value", "best_value")
    assert "Best value" in chip and "chip-best" in chip
    chip = theme.status_chip("<b>x</b>", "ok")
    assert "<b>" not in chip and "&lt;b&gt;" in chip
    assert theme.order_chip("INVOICE_RECEIVED") and "INVOICE_RECEIVED" in theme.order_chip("INVOICE_RECEIVED")
    assert "chip-invoice" in theme.order_chip("INVOICE_RECEIVED")
    assert "chip-approved" in theme.order_chip("APPROVED")
    assert "chip-rejected" in theme.order_chip("REJECTED")
    assert "needs you" in theme.thread_chip("needs_customer")


def test_journey_stepper_shows_all_nine_steps():
    html_out = theme.journey_stepper(2)
    for step in theme.JOURNEY_STEPS:
        assert step in html_out
    assert len(theme.JOURNEY_STEPS) == 9
    assert html_out.count("jstep done") == 2
    assert html_out.count("jstep current") == 1
    assert html_out.count("jstep todo") == 6
    # Out-of-range current clamps instead of crashing.
    assert "jstep current" in theme.journey_stepper(99)
    assert "jstep current" in theme.journey_stepper(-3)


def test_hero_labels_mode_honestly():
    demo = theme.hero_html("demo")
    assert "BuildBuy Copilot" in demo
    assert "DEMO MODE" in demo and "LIVE MODE" not in demo
    live = theme.hero_html("live")
    assert "LIVE MODE" in live and "DEMO MODE" not in live
