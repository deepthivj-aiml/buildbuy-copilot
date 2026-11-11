# BuildBuy Copilot — MCP support

I added MCP (Model Context Protocol) support so I can use BuildBuy
Copilot from an AI assistant like Claude Desktop or Claude Code —
the same buying engine, over a standard protocol, on my own machine.

## What it is

A **local stdio MCP server** that runs the same live/session-only
engine as the app. It uses the official Python MCP SDK (`mcp` 2.x,
`MCPServer` — FastMCP was renamed in 2.x). No tool sends an email
or places an order.

## The tools (6)

| Tool | What it does |
|---|---|
| `search_suppliers(requirement, quantity, location?, budget?)` | Ranked shortlist for one requirement + quantity, by best cost AND quality, with evidence. Cheapest and highest-quality identified separately. Suppliers whose MOQ is above the quantity are excluded, with the reason. Synthetic demo data, labelled as such. |
| `get_takeoff(requirement)` | Materials/quantities estimate. Every line carries "estimate, not a surveyed quantity". No quantity stated means no line is invented. |
| `get_quote(supplier, requirement, quantity, location?, deadline?, max_price?)` | Draft quote-request email for one supplier. **DRAFT ONLY — nothing is sent.** Opens with "I am BuildBuy Copilot, acting as the buying agent for a customer"; contact sharing is OFF, so no buyer name, email or phone appears. Blocked when the price is above the caller's cap. |
| `list_orders()` | Orders in this session only. Empty unless the session registered an order after human approval. |
| `get_order_status(order_id)` | Status of one session order. "Not found" when the id is not in this session — never an invented status. |
| `get_accuracy()` | The 8 observability metrics (definitions + targets). Values are "no data yet" — the live flow stores no metrics, so nothing is measured in the session. |

Every tool validates its inputs with Pydantic and runs the
deterministic guardrails first: blocklist / never-pay inputs are
blocked, PII is redacted (contact sharing is OFF for MCP), and a
price above the cap blocks `get_quote`. A material no supplier
carries returns an empty shortlist with a note, never a guessed
supplier. An unknown supplier or order id is an error, never an
invented record.

## How to run it

From the repo root, with the venv active:

```bash
pip install -r requirements.txt   # includes mcp==2.3.0
python -m app.mcp.server          # stdio transport, runs until stopped
```

Test it alone: `.venv/bin/python -m pytest tests/test_mcp.py -v`
(23 tests, including two that drive the server over the real MCP
protocol with the official SDK client).

## Connect Claude Desktop / Claude Code (config only)

Add this to your Claude Desktop config (`claude_desktop_config.json`)
or Claude Code MCP settings — replace the path with your own checkout:

```json
{
  "mcpServers": {
    "buildbuy-copilot": {
      "command": "/path/to/buildbuy-copilot/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/buildbuy-copilot"
    }
  }
}
```

Then restart the client. Ask it, for example: *"Find suppliers for
concrete, 10 m3 in Fremont"* or *"Draft a quote email for Bay Area
Building Supply for concrete, 10 m3"*.

**Not tested in Claude Desktop / Claude Code** — I verified the
server over the real MCP protocol with the official SDK client
(`tests/test_mcp.py`, stdio end-to-end), but I did not run it inside
Claude Desktop or Claude Code, so I do not claim that part works.

## Honest limits

- **Local stdio only.** No HTTP/SSE transport, no hosted endpoint,
  no auth — the server runs on your machine, for your client.
- **Demo data.** Suppliers, prices, quality evidence and contacts
  are synthetic (`data/suppliers.json`) until a real supplier
  directory is connected. Every result says so.
- **Session only.** Orders exist only in the server process's
  session. Restart the server and the order list is empty again —
  that is the consequence of having no storage, same as the app.
- **No sending, no ordering.** `get_quote` is a draft. Sending an
  email or placing an order still needs the human approval gate in
  the app (Buyer Agent tab). There is no tool that orders or pays,
  by design.
- **Accuracy is empty.** `get_accuracy` returns the 8 metric
  definitions with "no data yet" values, because the live flow
  stores no metrics. The Accuracy tab in the app shows labelled
  demo data in Demo Mode; MCP does not repeat demo numbers as real
  results.
- **Location is typed, never tracked.** A location is resolved
  only from a place name you type (or `lat,lng`); an unknown place
  means transport is excluded and labelled "excl. transport".
