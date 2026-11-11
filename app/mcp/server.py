"""BuildBuy Copilot MCP server — stdio transport, official MCP SDK.

Run it with::

    python -m app.mcp.server

from the repo root (``.venv`` active). It speaks MCP over stdio, so a
client such as Claude Desktop or Claude Code connects with the config
in ``docs/MCP.md``. The server is local-only: it runs the same
live/session-only engine as the app (synthetic demo supplier data
until a real directory is connected), and no tool sends an email or
places an order — ``get_quote`` returns a draft only, and sending
still needs the human approval gate in the app.

Requires the official Python MCP SDK (``mcp`` 2.x — ``MCPServer``;
FastMCP was renamed in 2.x). If the SDK is not installed, running
this module fails with a plain message saying so — it never falls
back to a fake protocol.
"""
from __future__ import annotations

import asyncio
import sys

from app.mcp.tools import (
    TOOL_NAMES,
    SessionStore,
    call_tool as _call_tool,
    list_tools as _list_tools,
)

try:
    from mcp.server.mcpserver import MCPServer
except Exception as exc:  # noqa: BLE001 — SDK missing is a plain error
    MCPServer = None  # type: ignore[assignment]
    _SDK_ERROR = exc
else:
    _SDK_ERROR = None

SERVER_NAME = "buildbuy-copilot"
SERVER_VERSION = "0.1.0"
SERVER_INSTRUCTIONS = (
    "BuildBuy Copilot — a buying copilot for materials. Tools are "
    "read-only or draft-only: search_suppliers ranks suppliers by "
    "best cost AND quality (synthetic demo data, labelled as such), "
    "get_takeoff estimates materials (every line 'estimate, not a "
    "surveyed quantity'), get_quote returns a DRAFT email (nothing "
    "is sent), list_orders / get_order_status read session-only "
    "orders (empty unless the session registered one), get_accuracy "
    "returns the 8 observability metric definitions with 'no data "
    "yet' values. No tool orders, pays, or emails a supplier — "
    "sending needs the human approval gate in the app."
)


def create_server(store: SessionStore | None = None):
    """Build the MCP server with all tools registered.

    ``store`` holds session-only orders (shared with the app when
    wired in); a fresh server has an empty store.
    """
    if MCPServer is None:
        raise RuntimeError(
            "The official MCP SDK is not installed (pip install mcp). "
            f"Import error: {_SDK_ERROR}"
        )
    store = store or SessionStore()
    server = MCPServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=SERVER_INSTRUCTIONS,
    )

    @server.tool()
    def search_suppliers(requirement: str, quantity: float = 1.0,
                         location: str | None = None,
                         budget: float | None = None) -> dict:
        """Rank suppliers for one requirement + quantity by best cost AND quality, with evidence. Synthetic demo data, labelled as such. Read-only."""
        return _call_tool("search_suppliers", {
            "requirement": requirement, "quantity": quantity,
            "location": location, "budget": budget}, store)

    @server.tool()
    def get_takeoff(requirement: str) -> dict:
        """Materials/quantities estimate for one requirement. Every line is labelled 'estimate, not a surveyed quantity'. No quantity stated means no line is invented. Read-only."""
        return _call_tool("get_takeoff", {"requirement": requirement}, store)

    @server.tool()
    def get_quote(supplier: str, requirement: str, quantity: float = 1.0,
                  location: str | None = None, deadline: str | None = None,
                  max_price: float | None = None) -> dict:
        """Draft quote-request email for one supplier. DRAFT ONLY — nothing is sent; sending needs the human approval gate in the app. Blocked when the price is above the caller's cap."""
        return _call_tool("get_quote", {
            "supplier": supplier, "requirement": requirement,
            "quantity": quantity, "location": location,
            "deadline": deadline, "max_price": max_price}, store)

    @server.tool()
    def list_orders() -> dict:
        """List orders in this session only. Empty unless the session registered an order after human approval. Read-only."""
        return _call_tool("list_orders", {}, store)

    @server.tool()
    def get_order_status(order_id: str) -> dict:
        """Status of one session order by id. 'Not found' when the id is not in this session. Read-only."""
        return _call_tool("get_order_status", {"order_id": order_id}, store)

    @server.tool()
    def get_accuracy() -> dict:
        """The 8 observability metrics (definitions + targets). Values are 'no data yet' — the live flow stores no metrics. Read-only."""
        return _call_tool("get_accuracy", {}, store)

    return server


def main() -> None:
    """Stdio entry point: ``python -m app.mcp.server``."""
    server = create_server()
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()
