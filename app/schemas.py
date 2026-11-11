"""Pydantic v2 schemas — the single contract shared by API, agents, evals.

Every request/response model validates here. A takeoff line, a supplier
quote, or a deal proposal that does not validate never reaches a supplier
or a user (plan §10.2).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- users
class UserCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(max_length=320)
    phone: str | None = Field(default=None, max_length=40)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None
    free_tier_quota: int
    byo_key_set: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------- requirements
class RequirementItem(BaseModel):
    item: str = Field(min_length=1, max_length=300)
    quantity: float = Field(gt=0)
    unit: str = Field(default="", max_length=40)


class RequirementCreate(BaseModel):
    source_type: Literal["plan", "typed", "photo"] = "typed"
    raw_text: str = Field(default="", max_length=5000)
    items: list[RequirementItem] = Field(default_factory=list)
    location: str = Field(default="", max_length=200)
    deadline: str | None = Field(default=None, max_length=40)
    budget: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    latest_date: str | None = Field(default=None, max_length=40)

    @field_validator("max_price")
    @classmethod
    def _max_price_within_budget(cls, v, info):
        budget = (info.data or {}).get("budget")
        if v is not None and budget is not None and v > budget:
            raise ValueError("max_price must not exceed budget")
        return v


class RequirementOut(BaseModel):
    id: str
    user_id: str
    source_type: str
    raw_text: str
    items: list[dict]
    location: str
    deadline: str | None
    budget: Decimal | None
    max_price: Decimal | None
    latest_date: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --------------------------------------------------------------- plans
class PlanUpload(BaseModel):
    file_name: str = Field(min_length=1, max_length=300)
    file_type: str = Field(default="", max_length=20)
    sheets: int = Field(default=1, ge=1, le=25)
    spec_text: str = Field(default="", max_length=100_000)


class ScaleConfirm(BaseModel):
    scale: str = Field(min_length=1, max_length=40)
    confirmed: bool = True


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    answer: str
    citation_image_region: dict | None = None
    citation_spec_clause: str | None = None
    grounded: bool | None = None
    found: bool = True


# ------------------------------------------------------------ materials
class MaterialOut(BaseModel):
    id: str
    material: str
    quantity: Decimal
    unit: str
    method: str
    confidence: Decimal | None
    flagged: bool
    estimate_label: bool = True

    model_config = {"from_attributes": True}


class MaterialPatch(BaseModel):
    material: str | None = Field(default=None, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=40)


class MaterialsRerun(BaseModel):
    feedback: str = Field(default="", max_length=2000)


# ------------------------------------------------------------ suppliers
class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=400)
    contact_source: Literal["public", "supplier_provided", "user_added"] = "user_added"
    contact_source_url: str | None = Field(default=None, max_length=600)
    moq: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    certifications: list[str] = Field(default_factory=list)
    # Quality: only ever supplied with evidence. Omit = no evidence (None),
    # never a guessed score.
    quality_score: Decimal | None = Field(default=None, ge=0, le=100)
    quality_evidence: list[dict] = Field(default_factory=list)


class SupplierOut(BaseModel):
    id: str
    name: str
    location: str
    email: str | None
    phone: str | None
    address: str | None
    contact_source: str
    contact_source_url: str | None
    moq: int | None
    lead_time_days: int | None
    certifications: list
    risk_flags: list
    quality_score: Decimal | None
    quality_evidence: list
    verified: bool

    model_config = {"from_attributes": True}


class ShortlistEntryOut(BaseModel):
    requirement_id: str
    supplier_id: str
    supplier_name: str
    rank: int
    unit_price: Decimal | None
    landed_cost: Decimal | None
    fit_score: Decimal | None
    why_rank: str
    quality_score: Decimal | None
    quality_evidence: list
    quality_unknown: bool
    best_value_score: Decimal | None
    best_value_rank: int | None
    is_cheapest: bool
    is_highest_quality: bool

    model_config = {"from_attributes": True}


class SimulateRequest(BaseModel):
    price_change_pct: float = Field(default=0.0, ge=-90, le=200)
    delivery_slip_days: int = Field(default=0, ge=0, le=90)
    quantity_change_pct: float = Field(default=0.0, ge=-90, le=500)
    # Optional transport line inside landed_cost (from a user-typed
    # delivery location). Not scaled by the price what-if. 0 / absent
    # means the landed cost is "excl. transport".
    transport_cost: float = Field(default=0.0, ge=0)
    transport_included: bool = False


class SimulationOut(BaseModel):
    supplier_id: str
    supplier_name: str
    landed_cost: Decimal | None
    delivery_date: str | None
    risk_score: Decimal | None
    quality_score: Decimal | None
    quality_risk: Decimal | None
    quality_risk_reason: str
    what_if: dict
    recommendation: bool
    transport_cost: Decimal | None = None
    transport_included: bool | None = None
    landed_cost_label: str | None = None

    model_config = {"from_attributes": True}


class ApprovalOptionOut(BaseModel):
    """One side of the approval comparison: cost + quality + evidence."""

    kind: Literal["best_value", "cheapest", "highest_quality"]
    supplier_id: str
    supplier_name: str
    unit_price: Decimal | None
    landed_cost: Decimal | None
    quality_score: Decimal | None
    quality_evidence: list
    quality_unknown: bool
    best_value_score: Decimal | None
    best_value_rank: int | None
    is_cheapest: bool
    is_highest_quality: bool
    risk_score: Decimal | None
    quality_risk: Decimal | None
    quality_risk_reason: str
    why: str
    # Total landed cost breakdown (transport is optional/manual — see
    # app/suppliers/search.py). None when the simulation did not carry it.
    transport_cost: Decimal | None = None
    transport_included: bool | None = None
    landed_cost_label: str | None = None


class ApprovalPaneOut(BaseModel):
    requirement_id: str
    best_value: ApprovalOptionOut | None
    cheapest: ApprovalOptionOut | None
    highest_quality: ApprovalOptionOut | None
    # When True, no supplier in the shortlist has evidenced quality — the
    # user is choosing on cost alone and is told so, not shown a fake rating.
    no_quality_evidence: bool
    note: str


# ----------------------------------------------------------- buyer agent
class BuyerDraftRequest(BaseModel):
    supplier_ids: list[str] = Field(default_factory=list, max_length=5)
    message: str | None = Field(default=None, max_length=5000)


class BuyerSendRequest(BaseModel):
    supplier_ids: list[str] = Field(default_factory=list, max_length=5)
    draft: str | None = Field(default=None, max_length=5000)
    # Per-supplier contact-sharing toggles. Default OFF — a missing entry
    # means do NOT share the user's contact with that supplier.
    share_contact: dict[str, bool] = Field(default_factory=dict)


class NegotiateRequest(BaseModel):
    supplier_id: str = Field(min_length=1)
    counter_price: Decimal | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=2000)


class BuyerMessageRequest(BaseModel):
    """Send a chat message to a supplier via email (new endpoint)."""

    supplier_id: str = Field(min_length=1)
    subject: str = Field(default="", max_length=400)
    body: str = Field(min_length=1, max_length=10000)
    share_contact: bool = False


class SupplierQuestionRequest(BaseModel):
    """A question a supplier asked (by email / chat).

    The agent classifies it: if it only asks to confirm what the
    requirement already states, it is answered from the requirement.
    Otherwise it escalates — the agent emails the customer and sends
    NOTHING to the supplier until the customer replies.
    """

    supplier_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=10000)
    subject: str = Field(default="", max_length=400)


class CustomerReplyRequest(BaseModel):
    """The customer's answer to a supplier question, in their words."""

    answer: str = Field(min_length=1, max_length=10000)
    # Share the customer's contact in the supplier reply? Default OFF.
    share_contact: bool = False


class EscalationOut(BaseModel):
    escalation_id: str
    supplier_id: str
    question: str
    subject: str
    asked_at: str | None = None
    status: str = "NEEDS_CUSTOMER"


class MessageOut(BaseModel):
    id: str
    thread_id: str
    supplier_id: str | None
    direction: str
    sender: str
    subject: str
    body: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class InboxThreadOut(BaseModel):
    thread_id: str
    supplier_id: str | None
    supplier_name: str | None
    status: str
    last_message_at: datetime | None
    last_snippet: str
    messages: list[MessageOut]


# ------------------------------------------------------------- approval
class ApproveRequest(BaseModel):
    decision: Literal["approve", "reject"]
    supplier_id: str | None = None  # supplier being approved (best-value default)
    quote_id: str | None = None
    reason: str = Field(default="", max_length=2000)


class OrderOut(BaseModel):
    id: str
    requirement_id: str
    supplier_id: str | None
    quote_id: str | None
    status: str
    approved_at: datetime | None
    confirmed_at: datetime | None
    promised_date: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------- invoices
class InvoiceCreate(BaseModel):
    """Record an invoice received — supplier-supplied data ONLY.

    ``invoice_number`` and ``amount`` must come from the supplier
    (email / file). They are required here precisely so the API can
    never invent them: no defaults, no auto-generation.
    """

    invoice_number: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="USD", min_length=1, max_length=10)
    received_at: datetime | None = None
    file_ref: str | None = Field(default=None, max_length=600)
    order_id: str | None = None
    supplier_id: str | None = None


class InvoiceOut(BaseModel):
    id: str
    requirement_id: str
    order_id: str | None
    supplier_id: str | None
    invoice_number: str
    amount: Decimal
    currency: str
    received_at: datetime | None
    file_ref: str | None
    chased_at: datetime | None
    chase_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ChaseRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


# ------------------------------------------------------------- settings
class SettingsPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    contact_sharing_default: bool | None = None
    buddy_personalisation: str | None = Field(default=None, max_length=5000)


class ContactSharingToggle(BaseModel):
    share: bool


# ------------------------------------------------------------- accuracy (observability)
class AccuracyMetricOut(BaseModel):
    key: str
    name: str
    formula: str
    source: str
    target: str
    direction: str
    unit: str
    value: float | None = None
    n: int = 0
    status: str = "no_data"  # ok | alert | no_data
    approval_before_order: float | None = None
    agreement_rate: float | None = None  # buyer-agent only: quotes agreed ÷ sent


class AccuracyHeadlineOut(BaseModel):
    label: str
    value: float | None = None
    n: int = 0
    unit: str = "rate"


class AccuracyTrendOut(BaseModel):
    date: str
    groundedness: float | None = None
    retrieval_top1: float | None = None
    eval_pass_rate: float | None = None
    cost_per_job_usd: float | None = None
    latency_p95_ms: int | None = None
    cache_hit_rate: float | None = None


class AccuracyModuleOut(BaseModel):
    module: str
    metric: str
    value: float | None = None
    n: int = 0
    worst: str = ""


class AccuracyWorstAnswerOut(BaseModel):
    qa_log_id: str
    question: str
    answer: str
    citations: str = ""
    thumbs: int = 0
    grounded: bool | None = None
    reason: str = ""
    status: str = "open"  # open | in_eval_set | fixed


class AccuracyEvalRunOut(BaseModel):
    date: str
    eval_set: str
    groundedness: float | None = None
    retrieval_top1: float | None = None
    guardrail_block_rate: float | None = None
    cache_hit_rate: float | None = None
    result: str


class AccuracyEventOut(BaseModel):
    request_id: str
    step: str
    model: str | None = None
    latency_ms: int | None = None
    grounded: bool | None = None
    cache_hit: bool = False
    guardrail_action: str = "allow"
    cost_usd: float = 0.0
    created_at: str = ""


class AccuracyAlertOut(BaseModel):
    metric: str
    value: float | None = None
    threshold: float | None = None
    direction: str = "higher"


class AccuracyDashboardOut(BaseModel):
    metrics: list[AccuracyMetricOut]
    headline: list[AccuracyHeadlineOut]
    trends: list[AccuracyTrendOut]
    per_module: list[AccuracyModuleOut]
    worst_answers: list[AccuracyWorstAnswerOut]
    eval_runs: list[AccuracyEvalRunOut]
    raw_events: list[AccuracyEventOut]
    alerts: list[AccuracyAlertOut]
    approval_before_order: float | None = None
    approval_violations: int = 0
    source: str = ""


class WorstAnswerActionRequest(BaseModel):
    action: Literal["add_to_eval_set", "mark_fixed"]


class WorstAnswerActionOut(BaseModel):
    qa_log_id: str
    status: str
    error: str | None = None


# ------------------------------------------------------------- misc
class ErrorOut(BaseModel):
    detail: str
    error_type: str = "error"
    request_id: str | None = None


class HealthOut(BaseModel):
    status: str = "ok"
    service: str = "buildbuy-copilot"
    email_backend: str = "mock"
    database: str = "sqlite"
    graph_available: bool = False
