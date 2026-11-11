"""BuildBuy Copilot — backend configuration.

All secrets come from the environment (or a local ``.env`` file, never
committed). No default here is a credential. See ``.env.example``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings. Env names only — no secret values in code."""

    app_name: str = "BuildBuy Copilot"
    app_env: str = "local"  # local | staging | production
    debug: bool = False

    # Database: SQLite file locally; Postgres via DATABASE_URL in deploy.
    # Default is a SQLite file inside the project data dir.
    # LIVE-DATA-ONLY (2026-11-10): storage is OFF by default. The
    # live flow (app/live.py + the Streamlit session) reads and writes
    # NO database at all — requirement, takeoff, shortlist, emails and
    # orders live only in the session. ``storage_enabled`` exists only
    # for the legacy stored-data API (app/api/routes.py) and the
    # internal eval/observability rollups, which tests call explicitly
    # via init_db(). Set STORAGE_ENABLED=true only when you have a
    # database to store in — the deployed app does not.
    storage_enabled: bool = False
    database_url: str = "sqlite:///./data/buildbuy.db"

    # Email: MockSMTP is the default — nothing real is ever sent unless
    # EMAIL_PROVIDER is explicitly set to "smtp" AND SMTP_* vars are set.
    email_provider: str = "mock"  # mock | smtp
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # noqa: S105 — env-provided only, never committed
    smtp_use_tls: bool = True
    email_from: str = "BuildBuy Copilot <noreply@buildbuy.local>"

    # The user's own mailbox for summaries / records exports.
    # Configurable via env; the default is the address the user named for
    # Gmail/outreach in the project plan. Never hardcode secrets here.
    user_email: str = "deepthiag26@gmail.com"

    # LLM (optional — the backend runs in local-fallback mode without one).
    llm_provider: str = ""  # openai | anthropic | ""
    llm_api_key: str = ""  # noqa: S105 — env-provided only
    llm_model: str = ""

    # Cache / tracing (optional; in-memory fallback when unset).
    redis_url: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""  # noqa: S105
    langfuse_host: str = ""

    # Cost/quality ranking weights (defaults; tunable via env).
    # Best-value score = w_cost * cost_score + w_quality * quality_score
    # + w_lead * lead_score, where each component is normalised 0-1.
    # CANONICAL weights live in app/suppliers/search.py (W_COST /
    # W_QUALITY / W_LEAD); these defaults MUST match them (0.45 / 0.35 /
    # 0.20). Quality is used ONLY when evidenced (quality_score is not
    # None); otherwise the rank falls back to cost and is flagged
    # quality_unknown=True — never invented.
    value_weight_cost: float = 0.45
    value_weight_quality: float = 0.35
    value_weight_lead: float = 0.20

    # Outbox relay / approval sweeper.
    outbox_max_attempts: int = 5
    approval_reminder_hours: int = 24

    # File storage for mock emails + exports (local only).
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_mock_email(self) -> bool:
        return self.email_provider.lower() != "smtp" or not self.smtp_host


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings


def load_env_file() -> None:
    """Load a local ``.env`` file if present (dev convenience only).

    Values already in the real environment win. Never writes anything.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
