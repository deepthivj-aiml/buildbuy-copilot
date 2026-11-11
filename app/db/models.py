"""BuildBuy Copilot — SQLAlchemy models.

Data model per plan §3.5 + §9.3 + §10.7 (outbox, approval_requests,
observability_events, qa_feedback, metrics_daily), plus the new
cost-AND-quality fields (2026-11-10 update):

- ``Supplier.quality_score`` / ``quality_evidence`` — a quality score
  (0-100) exists ONLY where evidenced (certifications, verified reviews,
  past performance, supplier-provided data). ``None`` means "no evidence",
  never a guessed rating.
- ``Shortlist`` carries ``quality_score``, ``quality_evidence``,
  ``best_value_rank``, ``is_cheapest`` and ``is_highest_quality`` so the
  approval pane can show best-value / cheapest / highest-quality side
  by side (see ``app/api/routes.py`` ``GET /requirements/{id}/approval``).

Order status (required set, plan §3.5):
PENDING, APPROVED, REJECTED, CONFIRMED, DELIVERED, INVOICE_PENDING,
INVOICE_RECEIVED, CHASED.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex[:16]


class Base(DeclarativeBase):
    pass


class OrderStatus(str, enum.Enum):
    """Order lifecycle. INVOICE_* and CHASED added for invoice tracking."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    INVOICE_PENDING = "INVOICE_PENDING"
    INVOICE_RECEIVED = "INVOICE_RECEIVED"
    CHASED = "CHASED"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class OutreachStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    REPLIED = "REPLIED"
    NO_REPLY = "NO_REPLY"
    AGREED = "AGREED"
    # Supplier asked a question the agent cannot answer: no supplier
    # reply is sent until the customer answers (see
    # app/agents/escalation.py). Status is NEEDS_CUSTOMER while waiting.
    NEEDS_CUSTOMER = "NEEDS_CUSTOMER"


class ContactSource(str, enum.Enum):
    PUBLIC = "public"
    SUPPLIER_PROVIDED = "supplier_provided"
    USER_ADDED = "user_added"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    free_tier_quota: Mapped[int] = mapped_column(Integer, default=1)
    byo_key_set: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirements: Mapped[list["Requirement"]] = relationship(back_populates="user")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="typed")  # plan|typed|photo
    raw_text: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{item, quantity, unit}]
    location: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(40), nullable=True)
    budget: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    latest_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="requirements")
    plans: Mapped[list["Plan"]] = relationship(back_populates="requirement")
    materials: Mapped[list["Material"]] = relationship(back_populates="requirement")
    shortlist: Mapped[list["Shortlist"]] = relationship(back_populates="requirement")
    simulations: Mapped[list["Simulation"]] = relationship(back_populates="requirement")
    outreach: Mapped[list["Outreach"]] = relationship(back_populates="requirement")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="requirement")
    orders: Mapped[list["Order"]] = relationship(back_populates="requirement")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="requirement")
    messages: Mapped[list["Message"]] = relationship(back_populates="requirement")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(300), default="")
    file_type: Mapped[str] = mapped_column(String(20), default="")
    sheets: Mapped[int] = mapped_column(Integer, default=1)
    scale: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scale_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    spec_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="plans")


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("plans.id"), nullable=True)
    material: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), default=0)
    unit: Mapped[str] = mapped_column(String(40), default="")
    method: Mapped[str] = mapped_column(Text, default="")  # e.g. "area x thickness"
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    estimate_label: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="materials")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(200), index=True)
    location: Mapped[str] = mapped_column(String(200), default="")
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    contact_source: Mapped[str] = mapped_column(String(30), default=ContactSource.PUBLIC.value)
    contact_source_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    moq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    # --- Quality (evidenced only; None = no evidence, never invented) ---
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)  # 0-100
    quality_evidence: Mapped[list] = mapped_column(JSON, default=list)
    #   e.g. [{"type": "certification", "detail": "ISO 9001", "source": "..."},
    #         {"type": "past_order", "detail": "delivered on time 4/4", ...}]
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    shortlist_entries: Mapped[list["Shortlist"]] = relationship(back_populates="supplier")


class Shortlist(Base):
    __tablename__ = "shortlist"
    __table_args__ = (UniqueConstraint("requirement_id", "supplier_id", name="uq_shortlist_req_sup"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)  # cost rank (legacy field)
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    landed_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    fit_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    why_rank: Mapped[str] = mapped_column(Text, default="")
    # --- Cost AND quality (2026-11-10 update) ---
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)  # 0-100, None = no evidence
    quality_evidence: Mapped[list] = mapped_column(JSON, default=list)
    quality_unknown: Mapped[bool] = mapped_column(Boolean, default=True)
    best_value_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)  # 0-100
    best_value_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_cheapest: Mapped[bool] = mapped_column(Boolean, default=False)
    is_highest_quality: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="shortlist")
    supplier: Mapped[Supplier] = relationship(back_populates="shortlist_entries")


class Simulation(Base):
    __tablename__ = "simulations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    landed_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)  # 0-100, higher = riskier
    # Quality risk is part of risk_score; quality detail lives here so the
    # twin simulates cost AND quality (2026-11-10 update).
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_risk: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_risk_reason: Mapped[str] = mapped_column(Text, default="")
    what_if: Mapped[dict] = mapped_column(JSON, default=dict)
    recommendation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="simulations")


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    draft: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    contact_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=OutreachStatus.DRAFT.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="outreach")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terms: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="email_reply")  # email_reply|manual
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_evidence: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="quotes")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    quote_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("quotes.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), default=OrderStatus.PENDING.value, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    promised_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="orders")


class Invoice(Base):
    """Invoice record — ONLY from supplier-supplied data.

    ``invoice_number`` and ``amount`` are never invented: this row is
    created only from a supplier email/file the user records, or from a
    parsed supplier reply. If the supplier has not supplied an invoice,
    no row exists and the order stays INVOICE_PENDING.
    """

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("orders.id"), nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    file_ref: Mapped[str | None] = mapped_column(String(600), nullable=True)
    chased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    chase_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="invoices")


class Message(Base):
    """One email in a buyer <-> supplier thread (inbox)."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # outbound | inbound
    sender: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(String(400), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="messages")


class QALog(Base):
    __tablename__ = "qa_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    citation_image_region: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    citation_spec_clause: Mapped[str | None] = mapped_column(Text, nullable=True)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    thumbs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("requirements.id"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(20))  # user | agent | supplier | system
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    eval_set: Mapped[str] = mapped_column(String(200), default="")
    groundedness: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    retrieval_top1: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    guardrail_block_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    cache_hit_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Outbox(Base):
    """Transactional outbox (plan §10.3.5). One row per email to send.

    The row is written in the SAME transaction as the business change
    (approval/order), so an approved deal can never lose its email and a
    rolled-back order can never send one. The relay drains PENDING rows
    using the deterministic idempotency key — one approved deal sends
    exactly one supplier email even if the process crashes mid-send.
    """

    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_outbox_idem_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    deal_id: Mapped[str | None] = mapped_column(String(32), index=True)  # requirement id
    supplier_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default="quote_request")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(20), default=OutboxStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ApprovalRequest(Base):
    """Persisted human-approval gate (plan §10.3.1).

    The decision lives here as a DB row, not only in the graph checkpoint,
    so a crashed/paused deal can be resumed and audited. The graph cannot
    transition to Order without a row in APPROVED status.
    """

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    deal_id: Mapped[str] = mapped_column(String(32), index=True)  # requirement id
    order_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=ApprovalStatus.PENDING.value, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resume_value: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ObservabilityEvent(Base):
    __tablename__ = "observability_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    request_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requirement_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    step: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    citations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    guardrail_action: Mapped[str] = mapped_column(String(20), default="allow")
    guardrail_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class QAFeedback(Base):
    __tablename__ = "qa_feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    qa_log_id: Mapped[str] = mapped_column(String(32), ForeignKey("qa_log.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thumbs: Mapped[int] = mapped_column(Integer, default=0)  # +1 | -1
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    corrected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_citations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MetricsDaily(Base):
    __tablename__ = "metrics_daily"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_metrics_user_date"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    window_days: Mapped[int] = mapped_column(Integer, default=30)
    groundedness: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    retrieval_top1: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    retrieval_top3: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    thumbs_up_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    not_found_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    takeoff_mape: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    takeoff_unchanged_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    ranking_top1_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    reply_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    negotiation_success_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    approval_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    guardrail_block_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    guardrail_false_positive_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    cache_hit_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    cost_saved_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    cost_per_query_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    cost_per_job_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    latency_p50_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_p95_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_pass_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class UserSummary(Base):
    """A summary email sent to the user (quotes / approval / order / invoice).

    Records what was sent and when, so summaries are never silently
    re-sent or claimed without a record.
    """

    __tablename__ = "user_summaries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    requirement_id: Mapped[str] = mapped_column(String(32), ForeignKey("requirements.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(40))  # quotes_received|deal_approved|order_confirmed|invoice_received|manual
    sent_to: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(400), default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


Index("ix_outbox_pending", Outbox.status, Outbox.next_retry_at)
