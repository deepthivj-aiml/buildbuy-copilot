"""HTTP API — FastAPI router (all §3.6 endpoints + buyer/inbox,
invoice, summary, records, approval pane, deals).

The router is the only module that talks to HTTP; it calls the domain
modules through app/integrations.py and the Pydantic contracts in
app/schemas.py — never the other way round.
"""
from .routes import router

__all__ = ["router"]
