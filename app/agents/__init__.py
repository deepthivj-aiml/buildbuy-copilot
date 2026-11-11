"""Buyer agent / LangGraph orchestrator — reel skill #2.

Planner -> Finder -> Buyer -> Negotiator -> [human approval gate] ->
Order -> Chaser -> InvoiceTracker. LangGraph when installed, otherwise
the same nodes run in the same order via BuyerGraph.run_local.
The approval decision is always a persisted DB row, never a prompt.
"""
from .graph import (
    BuyerGraph,
    BuyerState,
    approval_gate_node,
    buyer_node,
    chaser_node,
    finder_node,
    invoice_tracker_node,
    negotiator_node,
    order_node,
    planner_node,
    thread_id_for,
)

__all__ = [
    "BuyerGraph",
    "BuyerState",
    "approval_gate_node",
    "buyer_node",
    "chaser_node",
    "finder_node",
    "invoice_tracker_node",
    "negotiator_node",
    "order_node",
    "planner_node",
    "thread_id_for",
]
