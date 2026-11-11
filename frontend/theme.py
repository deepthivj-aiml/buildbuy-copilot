"""BuildBuy Copilot UI theme — pure helpers, no Streamlit import.

Palette, CSS, status chips, the buyer-journey stepper and the Start-tab
hero. Colour is decoration only: every chip/step keeps its TEXT label
(never colour-only meaning), demo/synthetic data keeps its amber DEMO
badge, and no colour ever implies a real result where the data is
synthetic. Tested alone: .venv/bin/python -m pytest tests/test_theme.py -v
"""
import html

# Consistent palette across all 7 tabs. Light theme, dark text on light
# backgrounds throughout (contrast-first: colour accents, never
# colour-as-the-only-signal).
PALETTE = {
    "primary": "#4F46E5",      # indigo — primary buttons, accents
    "primary_dark": "#3730A3",
    "violet": "#7C3AED",
    "teal": "#0D9488",
    "green": "#15803D",
    "green_bg": "#DCFCE7",
    "blue": "#1D4ED8",
    "blue_bg": "#DBEAFE",
    "purple": "#6B21A8",
    "purple_bg": "#F3E8FF",
    "amber": "#B45309",
    "amber_bg": "#FEF3C7",
    "red": "#B91C1C",
    "red_bg": "#FEE2E2",
    "ink": "#1F2937",
    "muted": "#6B7280",
    "page_bg": "#F8F7FF",
    "card_border": "#E5E7EB",
}

THEME_CSS = """
<style>
.block-container { padding-top: 1rem; padding-bottom: 2rem; max-width: 1120px; }
h1 { font-size: 1.7rem; }
h2 { font-size: 1.25rem; margin-top: 1.2rem; border-left: 4px solid #4F46E5;
     padding-left: 10px; }
h3 { font-size: 1.05rem; }
.stButton>button { min-height: 44px; font-size: 1rem; border-radius: 10px;
                   transition: transform .12s ease, box-shadow .12s ease; }
.stButton>button:hover { transform: translateY(-1px);
                         box-shadow: 0 4px 12px rgba(79,70,229,.25); }
[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #4F46E5, #7C3AED) !important;
    color: #ffffff !important; border: none !important;
    box-shadow: 0 4px 14px rgba(79,70,229,.35); }
[data-testid="stBaseButton-secondary"] {
    background: #ffffff !important; color: #4F46E5 !important;
    border: 1.5px solid #4F46E5 !important; }
[data-testid="stBaseButton-secondary"]:hover { background: #EEF2FF !important; }
input:focus, textarea:focus, select:focus { border-color: #4F46E5 !important; }
div[data-testid="stRadio"] label:has(input:checked) {
    background: #4F46E5; color: #ffffff; border-radius: 999px; padding: 4px 12px; }
div[data-testid="stRadio"] label { border-radius: 999px; padding: 4px 10px;
                                  font-weight: 600; }
/* Hero banner (Start tab) */
.hero { background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 55%, #0D9488 100%);
        color: #ffffff; border-radius: 18px; padding: 26px 28px;
        margin: 6px 0 14px 0; box-shadow: 0 8px 24px rgba(79,70,229,.30); }
.hero h1 { color: #ffffff; font-size: 2rem; margin: 0 0 6px 0; }
.hero p { color: #E0E7FF; font-size: 1.05rem; margin: 0 0 12px 0; }
.hero .hero-pills { display: flex; flex-wrap: wrap; gap: 8px; }
.hero .hero-pill { background: rgba(255,255,255,.18); color: #ffffff;
                   border: 1px solid rgba(255,255,255,.35); border-radius: 999px;
                   padding: 3px 12px; font-size: .85rem; font-weight: 600; }
/* Cards */
.card { border: 1px solid #e0e0e0; border-radius: 12px; padding: 14px 16px;
        margin: 8px 0; background: #ffffff;
        box-shadow: 0 2px 8px rgba(31,41,55,.06);
        transition: transform .12s ease, box-shadow .12s ease; }
.card:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(31,41,55,.12); }
.card-best { border: 2px solid #1a7f37; background: linear-gradient(180deg, #f0f9f1, #ffffff); }
.card-cheap { border: 2px solid #0969da; background: linear-gradient(180deg, #f0f6ff, #ffffff); }
.card-quality { border: 2px solid #8250df; background: linear-gradient(180deg, #f6f0ff, #ffffff); }
/* Status chips — text label always present, colour is decoration only */
.chip { display: inline-block; padding: 2px 10px; border-radius: 999px;
        font-size: 0.8rem; font-weight: 700; white-space: nowrap; }
.chip-best { background: #DCFCE7; color: #14532D; border: 1px solid #86EFAC; }
.chip-cheap { background: #DBEAFE; color: #1E3A8A; border: 1px solid #93C5FD; }
.chip-quality { background: #F3E8FF; color: #581C87; border: 1px solid #D8B4FE; }
.chip-pending { background: #FEF3C7; color: #78350F; border: 1px solid #FCD34D; }
.chip-approved { background: #DBEAFE; color: #1E3A8A; border: 1px solid #93C5FD; }
.chip-delivered { background: #CCFBF1; color: #134E4A; border: 1px solid #5EEAD4; }
.chip-invoice { background: #DCFCE7; color: #14532D; border: 1px solid #86EFAC; }
.chip-rejected { background: #FEE2E2; color: #7F1D1D; border: 1px solid #FCA5A5; }
.chip-demo { background: #FEF3C7; color: #78350F; border: 1px solid #FCD34D; }
.chip-live { background: #DCFCE7; color: #14532D; border: 1px solid #86EFAC; }
.chip-warn { background: #FEE2E2; color: #7F1D1D; border: 1px solid #FCA5A5; }
.chip-ok { background: #DCFCE7; color: #14532D; border: 1px solid #86EFAC; }
.chip-info { background: #E0E7FF; color: #3730A3; border: 1px solid #A5B4FC; }
.chip-nodata { background: #F3F4F6; color: #4B5563; border: 1px solid #D1D5DB; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px;
         font-size: 0.8rem; font-weight: 600; }
.badge-demo { background: #fff3cd; color: #664d03; }
.badge-live { background: #d1e7dd; color: #0f5132; }
.badge-warn { background: #f8d7da; color: #842029; }
.badge-ok { background: #d1e7dd; color: #0f5132; }
.trust { color: #555; font-size: 0.9rem; }
.small { font-size: 0.85rem; color: #555; }
.evidence { font-size: 0.85rem; color: #444; }
.metric-card { border: 1px solid #e0e0e0; border-radius: 12px; padding: 12px;
               text-align: center; background: #fafafa;
               border-top: 4px solid #4F46E5;
               box-shadow: 0 2px 8px rgba(31,41,55,.06);
               transition: transform .12s ease; }
.metric-card:hover { transform: translateY(-2px); }
.metric-num { font-size: 1.6rem; font-weight: 700; color: #4F46E5; }
/* Buyer-journey stepper */
.journey { display: flex; align-items: flex-start; gap: 0; margin: 10px 0 4px 0; }
.jstep { display: flex; flex-direction: column; align-items: center; gap: 4px;
         min-width: 0; flex: 0 0 auto; }
.jstep-dot { width: 30px; height: 30px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; font-weight: 700;
            font-size: .85rem; border: 2px solid #D1D5DB; background: #F3F4F6;
            color: #6B7280; }
.jstep-label { font-size: .72rem; font-weight: 600; color: #6B7280;
              text-align: center; max-width: 76px; line-height: 1.1; }
.jstep.done .jstep-dot { background: #15803D; border-color: #15803D; color: #fff; }
.jstep.done .jstep-label { color: #15803D; }
.jstep.current .jstep-dot { background: #4F46E5; border-color: #4F46E5; color: #fff;
                           box-shadow: 0 0 0 4px rgba(79,70,229,.25); }
.jstep.current .jstep-label { color: #4F46E5; }
.jstep-connector { flex: 1 1 auto; height: 2px; background: #D1D5DB;
                  margin-top: 15px; min-width: 8px; }
.jstep-connector.done { background: #15803D; }
</style>
"""

JOURNEY_STEPS = ["Requirement", "Materials", "Suppliers", "Twin",
                 "Buyer agent", "Approval", "Order", "Delivery", "Invoice"]

_CHIP_KINDS = {
    "best_value": "chip-best", "cheapest": "chip-cheap",
    "quality": "chip-quality", "pending": "chip-pending",
    "approved": "chip-approved", "delivered": "chip-delivered",
    "invoice": "chip-invoice", "rejected": "chip-rejected",
    "demo": "chip-demo", "live": "chip-live", "warn": "chip-warn",
    "ok": "chip-ok", "info": "chip-info", "nodata": "chip-nodata",
}

# Order status -> chip kind (text label is the status itself).
ORDER_CHIP_KIND = {
    "PENDING": "pending", "APPROVED": "approved", "REJECTED": "rejected",
    "CONFIRMED": "approved", "DELIVERED": "delivered",
    "INVOICE_PENDING": "pending", "INVOICE_RECEIVED": "invoice",
}

# Inbox thread status -> chip kind + display label ("needs_customer"
# is shown to the user as "needs you").
THREAD_CHIP_KIND = {
    "replied": "ok", "sent": "info", "no reply": "pending",
    "agreed": "invoice", "needs_customer": "warn",
}
THREAD_CHIP_LABEL = {
    "replied": "replied", "sent": "sent", "no reply": "no reply",
    "agreed": "agreed", "needs_customer": "needs you",
}


def status_chip(label, kind="info"):
    """A colour-coded status chip. The TEXT label is always rendered —
    colour is decoration only, never the sole carrier of meaning."""
    css = _CHIP_KINDS.get(kind, "chip-info")
    return (f'<span class="chip {css}">{html.escape(str(label))}</span>')


def order_chip(status):
    """Status chip for an order status (PENDING / APPROVED / ...)."""
    return status_chip(status, ORDER_CHIP_KIND.get(str(status), "info"))


def thread_chip(status):
    """Status chip for a Buyer Agent inbox thread status."""
    return status_chip(THREAD_CHIP_LABEL.get(str(status), str(status)),
                       THREAD_CHIP_KIND.get(str(status), "info"))


def journey_stepper(current):
    """HTML stepper for the 9-step buyer journey.

    ``current`` is the 0-based index of the step the buyer is on;
    steps before it are done, later steps are to-do. Every step shows
    its number and its text label, so the journey is readable with
    colour alone turned off.
    """
    current = max(0, min(int(current), len(JOURNEY_STEPS) - 1))
    parts = ['<div class="journey" role="list" aria-label="Buyer journey">']
    for i, name in enumerate(JOURNEY_STEPS):
        state = "done" if i < current else ("current" if i == current else "todo")
        mark = "✓" if i < current else str(i + 1)
        parts.append(
            f'<div class="jstep {state}" role="listitem" aria-label="{i + 1}. '
            f'{html.escape(name)} — {state}">'
            f'<div class="jstep-dot">{mark}</div>'
            f'<div class="jstep-label">{html.escape(name)}</div></div>')
        if i < len(JOURNEY_STEPS) - 1:
            done = "done" if i < current else ""
            parts.append(f'<div class="jstep-connector {done}"></div>')
    parts.append("</div>")
    return "".join(parts)


def hero_html(mode="demo"):
    """Gradient hero banner for the Start tab. ``mode`` is "demo" or
    "live" and is shown as a text pill — colour never claims a live
    backend when the app is in demo mode."""
    mode_pill = ("● DEMO MODE — synthetic demo data" if mode == "demo"
                 else "● LIVE MODE — backend connected")
    return (
        '<div class="hero">'
        '<h1>🛒 BuildBuy Copilot</h1>'
        '<p>Upload a plan or just say what you need — read the plan, estimate '
        'materials, find nearby suppliers, simulate the purchase, negotiate, '
        'and approve one deal.</p>'
        '<div class="hero-pills">'
        '<span class="hero-pill">7 tabs · one buyer workflow</span>'
        f'<span class="hero-pill">{mode_pill}</span>'
        '<span class="hero-pill">Nothing ordered without your tap</span>'
        '</div></div>'
    )
