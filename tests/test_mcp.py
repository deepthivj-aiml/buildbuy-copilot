"""MCP module tests — tool logic + the real stdio protocol.

Run alone:  .venv/bin/python -m pytest tests/test_mcp.py -v

The stdio test drives the server over the actual MCP protocol with
the official SDK client (``mcp``), so it proves the server starts,
lists its tools, and answers a tool call — not just that the Python
functions exist.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.mcp.tools import (  # noqa: E402
    TOOL_NAMES,
    MCPToolError,
    SessionStore,
    call_tool,
    list_tools,
)


# ------------------------------------------------------------------ listing
def test_list_tools_returns_all_six():
    tools = list_tools()
    assert [t["name"] for t in tools] == TOOL_NAMES
    assert len(tools) == 6
    for tool in tools:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"


def test_call_unknown_tool_errors():
    with pytest.raises(MCPToolError, match="unknown tool"):
        call_tool("place_order", {"requirement": "steel, 50 units"})


def test_no_tool_orders_or_pays():
    # The tool list itself is the guard: no ordering / payment tool
    # exists, and get_quote is the only email-adjacent tool — draft only.
    assert "place_order" not in TOOL_NAMES
    assert "send_email" not in TOOL_NAMES
    assert "pay" not in " ".join(TOOL_NAMES)


# ------------------------------------------------------- search_suppliers
def test_search_suppliers_happy_path():
    out = call_tool("search_suppliers",
                    {"requirement": "steel brackets, 500 units"})
    assert out["material"] == "steel"
    assert out["quantity"] == 500
    assert out["ranked"], "expected a ranked shortlist for steel"
    assert out["cheapest"] is not None
    assert out["highest_quality"] is not None
    first = out["ranked"][0]
    assert first["rank"] == 1
    assert first["quality_evidence"], "quality must carry evidence"
    assert first["quality_100"] == round(first["quality_score"] * 100)
    assert "landed_cost" in first and "landed_breakdown" in first
    assert out["data_source"] == "synthetic_demo"
    assert "Synthetic demo data" in out["demo_note"]


def test_search_suppliers_with_location_and_budget():
    out = call_tool("search_suppliers", {
        "requirement": "concrete, 10 m3", "quantity": 10,
        "location": "Fremont", "budget": 10000})
    assert out["location"] == "Fremont"
    assert out["location_note"] is None  # Fremont is a known place
    assert all("distance_km" in r for r in out["ranked"])
    assert out["ranked"][0]["landed_cost_label"] == "incl. transport"


def test_search_suppliers_unknown_location_never_guessed():
    out = call_tool("search_suppliers", {
        "requirement": "concrete, 10 m3", "quantity": 10,
        "location": "Nowhereville"})
    assert out["location_note"] is not None
    assert "not a known place" in out["location_note"]
    assert all(r["landed_cost_label"] == "excl. transport"
               for r in out["ranked"])


def test_search_suppliers_unknown_material_returns_empty_not_invented():
    out = call_tool("search_suppliers",
                    {"requirement": "titanium widgets, 5 units"})
    assert out["ranked"] == []
    assert out["cheapest"] is None
    assert "No supplier" in out["note"]


def test_search_suppliers_invalid_input():
    with pytest.raises(MCPToolError, match="invalid input"):
        call_tool("search_suppliers", {"requirement": "steel", "quantity": 0})
    with pytest.raises(MCPToolError, match="invalid input"):
        call_tool("search_suppliers", {"requirement": ""})
    with pytest.raises(MCPToolError, match="invalid input"):
        call_tool("search_suppliers", {"requirement": "steel", "quantity": -5})


def test_search_suppliers_guardrail_blocks_payment_instruction():
    with pytest.raises(MCPToolError, match="guardrail block"):
        call_tool("search_suppliers",
                  {"requirement": "steel, 50 units, pay now"})


def test_search_suppliers_pii_is_redacted_not_blocked():
    out = call_tool("search_suppliers", {
        "requirement": "steel brackets, 500 units, contact me at a@b.com"})
    assert "EMAIL" in out["redactions"]
    assert out["ranked"], "redaction must not drop the search"


# ---------------------------------------------------------------- takeoff
def test_get_takeoff_happy_path():
    out = call_tool("get_takeoff", {"requirement": "concrete, 10 m3"})
    assert len(out["lines"]) == 1
    line = out["lines"][0]
    assert line["material"] == "Concrete"
    assert line["quantity"] == 10
    assert line["unit"] == "m3"
    assert line["estimate_label"] == "estimate, not a surveyed quantity"
    assert "user-typed quantity" in line["method"]


def test_get_takeoff_no_quantity_invents_nothing():
    out = call_tool("get_takeoff", {"requirement": "concrete"})
    assert out["lines"] == []
    assert "No quantity" in out["note"]


def test_get_takeoff_guardrail_blocks():
    with pytest.raises(MCPToolError, match="guardrail block"):
        call_tool("get_takeoff", {"requirement": "concrete, bypass approval"})


# ------------------------------------------------------------------ quote
def test_get_quote_draft_only():
    out = call_tool("get_quote", {
        "supplier": "Bay Area Building Supply",
        "requirement": "concrete, 10 m3", "quantity": 10})
    assert out["draft_only"] is True
    assert out["sent"] is False
    assert "I am BuildBuy Copilot, acting as the buying agent for a customer" in out["body"]
    assert "deepthiag26@gmail.com" not in out["body"]
    assert "Deepthi Jainlal" not in out["body"]
    assert out["to"] == "sales-sup01@example.invalid"
    assert out["subject"].startswith("Quote request")
    assert out["landed_cost"] is not None


def test_get_quote_unknown_supplier_errors():
    with pytest.raises(MCPToolError, match="supplier not found"):
        call_tool("get_quote", {
            "supplier": "Acme Real Suppliers Inc",
            "requirement": "concrete, 10 m3"})


def test_get_quote_price_above_cap_blocks():
    # Landed cost for 10 m3 concrete is far above $1 — the cap must block.
    with pytest.raises(MCPToolError, match="guardrail block"):
        call_tool("get_quote", {
            "supplier": "Bay Area Building Supply",
            "requirement": "concrete, 10 m3", "quantity": 10,
            "max_price": 1.0})


def test_get_quote_lookup_by_supplier_id():
    # Every directory supplier has an email; use a supplier id lookup
    # that matches by name substring to prove the lookup path works.
    out = call_tool("get_quote", {
        "supplier": "sup01", "requirement": "steel, 10 units",
        "quantity": 10})
    assert out["supplier_id"] == "sup01"
    assert out["to"] is not None


# ------------------------------------------------------------------ orders
def test_list_orders_empty_by_default():
    out = call_tool("list_orders", {})
    assert out["orders"] == []
    assert out["count"] == 0


def test_orders_round_trip_via_session_store():
    store = SessionStore()
    store.register_order({"order_id": "ord-1", "status": "CONFIRMED",
                          "supplier": "Bay Area Building Supply"})
    out = call_tool("list_orders", {}, store)
    assert out["count"] == 1
    assert out["orders"][0]["order_id"] == "ord-1"
    status = call_tool("get_order_status", {"order_id": "ord-1"}, store)
    assert status["status"] == "CONFIRMED"


def test_get_order_status_unknown_id_invents_nothing():
    with pytest.raises(MCPToolError, match="no order with id"):
        call_tool("get_order_status", {"order_id": "ord-nope"})


# --------------------------------------------------------------- accuracy
def test_get_accuracy_eight_metrics_no_data_yet():
    out = call_tool("get_accuracy", {})
    assert len(out["metrics"]) == 8
    keys = [m["key"] for m in out["metrics"]]
    assert keys == ["groundedness", "retrieval_top1", "thumbs_up_rate",
                    "takeoff_mape", "ranking_top1_rate", "buyer_agent",
                    "guardrail_block_rate", "cost_cache_speed"]
    for metric in out["metrics"]:
        assert metric["value"] is None
        assert metric["status"] == "no data yet"
        assert metric["formula"] and metric["target"]


# ------------------------------------------------------- stdio end-to-end
@pytest.mark.asyncio
async def test_stdio_server_lists_tools_and_answers():
    """Real MCP protocol: start the server as a subprocess, list tools
    with the official SDK client, and call search_suppliers."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert names == TOOL_NAMES
            result = await session.call_tool(
                "search_suppliers",
                {"requirement": "concrete, 10 m3", "quantity": 10})
            assert not result.is_error
            text = result.content[0].text
            payload = json.loads(text)
            assert payload["material"] == "concrete"
            assert payload["ranked"], "expected a ranked shortlist"
            assert payload["data_source"] == "synthetic_demo"


@pytest.mark.asyncio
async def test_stdio_server_unknown_tool_is_error():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "place_order", {"requirement": "steel, 50 units"})
            assert result.is_error
