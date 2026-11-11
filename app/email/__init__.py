"""Email service — MockSMTP by default, SMTP only when configured.

Every "sent" email is recorded in the outbox table (deterministic
idempotency keys ``email:{deal}:{supplier}:{round}``) and, in mock
mode, written to data/mock_mail/. Nothing real is ever sent unless
EMAIL_PROVIDER=smtp AND SMTP_* vars are set.
"""
from .service import EmailService, drain_outbox, idempotency_key, record_message

__all__ = ["EmailService", "drain_outbox", "idempotency_key", "record_message"]
