"""MCP tool logic for BuildBuy Copilot — pure functions, no MCP SDK here.

The MCP *server* (``app/mcp/server.py``) registers these functions as
tools on the official Python MCP SDK server (``mcp`` 2.x, ``MCPServer``).
This module holds the business logic so it can be tested without the
SDK and without a stdio transport.

Rules every tool follows (same as the rest of the app):

* Live data only, session only — nothing is read from or written to a
  database. Suppliers come from the synthetic demo directory
  (``data/suppliers.json``) until a real supplier directory is
  connected; every result says so.
* Nothing is invented: no supplier, quote, rating or invoice that is
  not in the data. A material no supplier carries returns an empty
  shortlist with a note, never a guessed supplier.
* Guardrails run before any result is returned: blocklist / never-pay
  inputs are blocked, PII is redacted (contact sharing is OFF for
  MCP — a tool never includes the buyer's name, email or phone), and
  a price above the caller's cap blocks ``get_quote``.
* No tool sends an email or places an order. ``get_quote`` returns a
  DRAFT only (``sent: False``). Orders exist only in the caller's
  session store — ``list_orders`` / ``get_order_status`` return an
  empty list / "not found" unless the session registered one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from app.email.service import EmailService
from app.guardrails.guardrails import Guardrails
from app.live import supplier_official_email
from app.observability import METRIC_DEFS
from app.suppliers.directory import load_suppliers
from app.suppliers.location import geocode_location
from app.suppliers.search import search_suppliers as _search_suppliers
from app.takeoff.engine import ESTIMATE_LABEL, takeoff_line_from_requirement

DEMO_NOTE = (
    "Synthetic demo data: suppliers, prices, quality evidence and "
    "contacts are invented for the demo only — NOT real businesses, "
    "real ratings, or real prices."
)

TOOL_NAMES = [
    "search_suppliers",
    "get_takeoff",
    "get_quote",
    "list_orders",
    "get_order_status",
    "get_accuracy",
]


class MCPToolError(ValueError):
    """A tool call that must fail (invalid input, guardrail block,
    unknown supplier/order). The MCP layer surfaces this as an error
    result — never as invented data."""


# ------------------------------------------------------------------ inputs
class SearchSuppliersInput(BaseModel):
    requirement: str = Field(min_length=1, max_length=500)
    quantity: float = Field(default=1.0, gt=0, le=1_000_000)
    location: str | None = Field(default=None, max_length=200)
    budget: float | None = Field(default=None, ge=0)


class TakeoffInput(BaseModel):
    requirement: str = Field(min_length=1, max_length=500)


class QuoteInput(BaseModel):
    supplier: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=500)
    quantity: float = Field(default=1.0, gt=0, le=1_000_000)
    location: str | None = Field(default=None, max_length=200)
    deadline: str | None = Field(default=None, max_length=100)
    max_price: float | None = Field(default=None, ge=0)


class OrderStatusInput(BaseModel):
    order_id: str = Field(min_length=1, max_length=200)


# ------------------------------------------------------------ session state
@dataclass
class SessionStore:
    """Session-only order state. The MCP server never creates an order
    itself — the app (or a test) registers one after the human
    approval gate. A fresh server has no orders, and ``list_orders``
    says so instead of inventing one."""

    orders: list[dict] = field(default_factory=list)

    def register_order(self, order: dict) -> dict:
        if not isinstance(order, dict) or not order.get("order_id"):
            raise MCPToolError("order must be a dict with an 'order_id'")
        self.orders.append(dict(order))
        return dict(order)

    def get_order(self, order_id: str) -> dict | None:
        return next(
            (o for o in self.orders if o.get("order_id") == order_id), None
        )


# ------------------------------------------------------------------ helpers
_QTY_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(m3|m²|m2|units?|pcs|pieces?|sheets?|bags?|kg|t|tonnes?|tons?|m|l)\b",
    re.I,
)
_BUDGET_RE = re.compile(r"(?:under|below|max|budget)\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I)


def _parse_item(requirement: str) -> dict:
    """Split a typed requirement into {item, quantity, unit}.

    Handles "concrete, 10 m3", "steel brackets, 50 units" and
    "50 x steel brackets". A quantity is never invented: when none is
    stated, quantity is None and the caller must not invent a line.
    """
    text = (requirement or "").strip()
    quantity: float | None = None
    unit = ""
    m = _QTY_UNIT_RE.search(text)
    if m:
        quantity = float(m.group(1))
        unit = m.group(2).lower()
        if unit in ("unit", "units"):
            unit = "pcs"
        text = (text[: m.start()] + text[m.end():]).strip(" ,")
    else:
        m2 = re.match(r"^\s*(\d+(?:\.\d+)?)\s*x\s+", text, re.I)
        if m2:
            quantity = float(m2.group(1))
            text = text[m2.end():].strip(" ,")
    m = _BUDGET_RE.search(text)
    if m:
        text = (text[: m.start()] + text[m.end():]).strip(" ,")
    item = re.sub(r"\b(?:in|near|at)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?$", "", text).strip(" ,")
    return {"item": item, "quantity": quantity, "unit": unit}


def _guard(text: str, *, max_price: float | None = None,
           price: float | None = None) -> tuple[str, list[str]]:
    """Run the deterministic guardrails on tool input.

    Blocked (blocklist / never-pay / price above cap) raises
    MCPToolError. PII is redacted and the redacted text is returned
    with the redaction list — the tool proceeds on the redacted text,
    never on raw contact details (contact sharing is OFF for MCP).
    """
    result = Guardrails().check(text, max_price=max_price, price=price)
    if not result.passed:
        raise MCPToolError(f"guardrail block: {result.reason}")
    return result.text, list(result.redactions)


def _known_materials(suppliers: list[dict]) -> list[str]:
    seen: list[str] = []
    for sup in suppliers:
        for mat in sup.get("materials", []):
            if mat not in seen:
                seen.append(mat)
    return seen


def _match_material(item: str, materials: list[str]) -> str | None:
    """Match a typed item ("steel brackets") to a directory material
    ("steel") by token overlap. Returns None when nothing matches —
    the caller returns an empty shortlist, never a guessed material."""
    tokens = {t[:-1] if t.endswith("s") and len(t) > 2 else t
              for t in re.sub(r"[^a-z0-9 ]", " ", item.lower()).split()}
    best: str | None = None
    best_score = 0
    for mat in materials:
        mat_tokens = set(mat.lower().split())
        score = len(tokens & mat_tokens)
        if score > best_score:
            best, best_score = mat, score
    return best


def _validate(model_cls, arguments: dict):
    try:
        return model_cls(**(arguments or {}))
    except ValidationError as exc:
        raise MCPToolError(f"invalid input: {exc}") from exc


# --------------------------------------------------------------------- tools
def search_suppliers_tool(arguments: dict) -> dict:
    """Ranked shortlist for one requirement + quantity, cost AND
    quality, with evidence. Demo data only, labelled as such."""
    args = _validate(SearchSuppliersInput, arguments)
    text, redactions = _guard(args.requirement)
    parsed = _parse_item(text)
    # The quantity typed in the requirement wins over the default;
    # the explicit quantity argument is the fallback.
    quantity = parsed["quantity"] if parsed["quantity"] is not None else args.quantity
    suppliers = load_suppliers()
    material = _match_material(parsed["item"], _known_materials(suppliers))
    if material is None:
        return {
            "requirement": args.requirement,
            "item": parsed["item"],
            "quantity": quantity,
            "ranked": [], "cheapest": None, "highest_quality": None,
            "excluded": [],
            "note": (f"No supplier in the directory carries a material "
                     f"matching '{parsed['item']}'. No supplier was "
                     f"invented."),
            "data_source": "synthetic_demo",
            "demo_note": DEMO_NOTE,
            "redactions": redactions,
        }
    buyer_lat = buyer_lng = None
    location_note = None
    if args.location:
        resolved = geocode_location(args.location)
        if resolved is None:
            location_note = (
                f"Location '{args.location}' is not a known place — "
                "distance unknown, transport excluded from landed cost "
                "(labelled 'excl. transport'); no location was guessed."
            )
        else:
            buyer_lat, buyer_lng, _name = resolved
    result = _search_suppliers(
        suppliers, material, quantity,
        buyer_lat=buyer_lat, buyer_lng=buyer_lng,
    )
    ranked = []
    for row in result["ranked"]:
        row = dict(row)
        row["quality_100"] = round(row["quality_score"] * 100)
        row["over_budget"] = (
            args.budget is not None and row["landed_cost"] > args.budget
        )
        ranked.append(row)
    for key in ("cheapest", "highest_quality"):
        if result[key] is not None:
            row = dict(result[key])
            row["quality_100"] = round(row["quality_score"] * 100)
            result[key] = row
    return {
        "requirement": args.requirement,
        "item": parsed["item"],
        "material": material,
        "quantity": quantity,
        "location": args.location,
        "location_note": location_note,
        "budget": args.budget,
        "ranked": ranked,
        "cheapest": result["cheapest"],
        "highest_quality": result["highest_quality"],
        "excluded": result["excluded"],
        "data_source": "synthetic_demo",
        "demo_note": DEMO_NOTE,
        "redactions": redactions,
    }


def get_takeoff_tool(arguments: dict) -> dict:
    """Materials/quantities estimate for one requirement. Every line
    carries "estimate, not a surveyed quantity". No quantity stated
    means no line is invented."""
    args = _validate(TakeoffInput, arguments)
    text, redactions = _guard(args.requirement)
    parsed = _parse_item(text)
    line = takeoff_line_from_requirement(parsed)
    if line is None:
        return {
            "requirement": args.requirement,
            "item": parsed["item"],
            "lines": [],
            "note": ("No quantity was stated, so no takeoff line was "
                     "invented. State a quantity (e.g. 'concrete, 10 m3')."),
            "estimate_label": ESTIMATE_LABEL,
            "redactions": redactions,
        }
    return {
        "requirement": args.requirement,
        "item": parsed["item"],
        "lines": [{
            "material": line.material,
            "quantity": line.quantity,
            "unit": line.unit,
            "method": line.method,
            "confidence": line.confidence,
            "flagged": line.flagged,
            "estimate_label": line.estimate_label,
        }],
        "estimate_label": ESTIMATE_LABEL,
        "redactions": redactions,
    }


def get_quote_tool(arguments: dict) -> dict:
    """Draft quote-request email for one supplier — DRAFT ONLY.

    Nothing is sent. The draft opens with the agent identity line
    ("I am BuildBuy Copilot, acting as the buying agent for a
    customer") and contact sharing is OFF, so no buyer name, email
    or phone appears. A price above the caller's cap blocks the
    draft; a supplier with no official email held is reported, never
    guessed.
    """
    args = _validate(QuoteInput, arguments)
    text, redactions = _guard(args.requirement)
    parsed = _parse_item(text)
    quantity = parsed["quantity"] if parsed["quantity"] is not None else args.quantity
    suppliers = load_suppliers()
    wanted = args.supplier.strip().lower()
    supplier = next(
        (s for s in suppliers
         if s.get("id", "").lower() == wanted
         or s.get("name", "").lower() == wanted
         or wanted in s.get("name", "").lower()),
        None,
    )
    if supplier is None:
        raise MCPToolError(
            f"supplier not found: '{args.supplier}' is not in the "
            "directory — no supplier was invented.")
    material = _match_material(parsed["item"], _known_materials(suppliers))
    landed: float | None = None
    moq_warning = None
    if material is not None:
        result = _search_suppliers(suppliers, material, quantity)
        row = next(
            (r for r in result["ranked"]
             if r["supplier_id"] == supplier["id"]), None)
        if row is not None:
            landed = row["landed_cost"]
        else:
            excl = next(
                (e for e in result["excluded"]
                 if e["supplier_id"] == supplier["id"]), None)
            if excl is not None:
                moq_warning = excl["reason"]
    if (args.max_price is not None and landed is not None
            and landed > args.max_price):
        _guard(args.requirement, max_price=args.max_price, price=landed)
    unit_price = float((supplier.get("unit_prices") or {}).get(material, 0.0)) \
        if material else 0.0
    body = EmailService.draft_quote(
        buyer_name="", items=[{"item": parsed["item"] or args.requirement,
                               "quantity": quantity}],
        location=args.location or "", deadline=args.deadline,
        max_price=args.max_price, share_contact=False,
    )
    return {
        "supplier": supplier["name"],
        "supplier_id": supplier["id"],
        "to": supplier_official_email(supplier),
        "subject": f"Quote request — {quantity:g} x {parsed['item'] or args.requirement}",
        "body": body,
        "draft_only": True,
        "sent": False,
        "unit_price": unit_price,
        "landed_cost": landed,
        "moq_warning": moq_warning,
        "note": ("Draft only — sending needs the human approval gate "
                 "in the app (Buyer Agent tab). Nothing was sent."),
        "data_source": "synthetic_demo",
        "demo_note": DEMO_NOTE,
        "redactions": redactions,
    }


def list_orders_tool(arguments: dict, store: SessionStore | None = None) -> dict:
    """Session-only orders. Empty unless the session registered one —
    an order is never invented."""
    store = store or SessionStore()
    return {
        "orders": [dict(o) for o in store.orders],
        "count": len(store.orders),
        "note": ("Session-only: orders exist only in this session. "
                 "No order has been placed unless one is listed here."),
    }


def get_order_status_tool(arguments: dict, store: SessionStore | None = None) -> dict:
    """Status of one session order by id. "Not found" when the id is
    not in this session — never an invented status."""
    args = _validate(OrderStatusInput, arguments)
    store = store or SessionStore()
    order = store.get_order(args.order_id)
    if order is None:
        raise MCPToolError(
            f"no order with id '{args.order_id}' in this session — "
            "no status was invented.")
    return {"order_id": args.order_id, "status": order.get("status"),
            "order": dict(order)}


def get_accuracy_tool(arguments: dict) -> dict:
    """The 8 observability metrics (definitions + targets). Values
    are "no data yet" — the live flow has no storage, so no metric
    has a measured value in this session. The Accuracy tab shows
    labelled demo data in Demo Mode; MCP reports the honest empty
    state instead of repeating demo numbers as real results."""
    return {
        "metrics": [
            {
                "key": d["key"], "name": d["name"],
                "formula": d["formula"], "source": d["source"],
                "target": d["target"], "value": None,
                "status": "no data yet",
            }
            for d in METRIC_DEFS
        ],
        "note": ("Live-data-only: no metrics are stored, so no value "
                 "is measured in this session. See the Accuracy tab "
                 "for the observability dashboard."),
    }


_TOOL_FUNCS = {
    "search_suppliers": search_suppliers_tool,
    "get_takeoff": get_takeoff_tool,
    "get_quote": get_quote_tool,
    "list_orders": list_orders_tool,
    "get_order_status": get_order_status_tool,
    "get_accuracy": get_accuracy_tool,
}

_TOOL_DESCRIPTIONS = {
    "search_suppliers": (
        "Rank suppliers for one requirement + quantity by best cost AND "
        "quality, with evidence. Synthetic demo data, labelled as such. "
        "Read-only."),
    "get_takeoff": (
        "Materials/quantities estimate for one requirement. Every line "
        "is labelled 'estimate, not a surveyed quantity'. No quantity "
        "stated means no line is invented. Read-only."),
    "get_quote": (
        "Draft quote-request email for one supplier. DRAFT ONLY — "
        "nothing is sent; sending needs the human approval gate in "
        "the app. Blocked when the price is above the caller's cap."),
    "list_orders": (
        "List orders in this session only. Empty unless the session "
        "registered an order after human approval. Read-only."),
    "get_order_status": (
        "Status of one session order by id. 'Not found' when the id "
        "is not in this session. Read-only."),
    "get_accuracy": (
        "The 8 observability metrics (definitions + targets). Values "
        "are 'no data yet' — the live flow stores no metrics. "
        "Read-only."),
}


def list_tools() -> list[dict]:
    """Tool descriptors: name, description, and the JSON input schema
    derived from each tool's Pydantic input model."""
    schemas = {
        "search_suppliers": SearchSuppliersInput,
        "get_takeoff": TakeoffInput,
        "get_quote": QuoteInput,
        "list_orders": None,
        "get_order_status": OrderStatusInput,
        "get_accuracy": None,
    }
    out = []
    for name in TOOL_NAMES:
        schema = schemas[name]
        out.append({
            "name": name,
            "description": _TOOL_DESCRIPTIONS[name],
            "input_schema": (
                schema.model_json_schema() if schema is not None
                else {"type": "object", "properties": {}}),
        })
    return out


def call_tool(name: str, arguments: dict | None = None,
              store: SessionStore | None = None) -> dict:
    """Dispatch one tool call by name. Raises MCPToolError for an
    unknown tool, invalid input, a guardrail block, or a missing
    supplier/order."""
    func = _TOOL_FUNCS.get(name)
    if func is None:
        raise MCPToolError(
            f"unknown tool '{name}' — known tools: {', '.join(TOOL_NAMES)}")
    if name in ("list_orders", "get_order_status"):
        return func(arguments or {}, store)
    return func(arguments or {})
