"""MCP support — BuildBuy Copilot as a local stdio MCP server.

The server runs the same live/session-only engine as the app over
the Model Context Protocol, using the official Python MCP SDK
(``mcp`` 2.x, ``MCPServer``). No tool sends an email or places an
order.
"""
from app.mcp.server import SERVER_NAME, SERVER_VERSION, create_server, main
from app.mcp.tools import (
    TOOL_NAMES,
    SessionStore,
    call_tool,
    get_accuracy_tool,
    get_order_status_tool,
    get_quote_tool,
    get_takeoff_tool,
    list_orders_tool,
    list_tools,
    search_suppliers_tool,
)

__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "TOOL_NAMES",
    "SessionStore",
    "call_tool",
    "create_server",
    "get_accuracy_tool",
    "get_order_status_tool",
    "get_quote_tool",
    "get_takeoff_tool",
    "list_orders_tool",
    "list_tools",
    "main",
    "search_suppliers_tool",
]
