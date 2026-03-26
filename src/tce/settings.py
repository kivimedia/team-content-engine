"""Application settings loaded from environment variables."""

from decimal import Decimal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCE_", env_file=".env")

    # Database
    database_url: str = "postgresql+asyncpg://tce:tce@localhost:5432/tce"

    # Anthropic
    anthropic_api_key: SecretStr = SecretStr("")

    # Model tiers (per PRD Section 37)
    default_model: str = "claude-sonnet-4-20250514"
    opus_model: str = "claude-opus-4-20250514"
    haiku_model: str = "claude-haiku-4-5-20251001"

    # Budget controls (per PRD Section 36.5)
    daily_budget_usd: Decimal = Decimal("40.00")
    monthly_budget_usd: Decimal = Decimal("800.00")

    # fal.ai
    fal_api_key: str = ""

    # Logging
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Pipeline
    max_pipeline_concurrency: int = 5

    # Web search (GAP-01)
    search_api_key: str = ""

    # S3-compatible storage (GAP-04)
    s3_endpoint: str = ""
    s3_bucket: str = "tce-assets"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Social platform tokens (GAP-03)
    facebook_page_token: str = ""
    facebook_verify_token: str = "tce_webhook_verify"
    linkedin_access_token: str = ""

    # Notifications (GAP-09)
    resend_api_key: str = ""
    slack_webhook_url: str = ""
    notification_email: str = ""

    # Per-agent cost cap (GAP-14)
    per_agent_daily_cap_usd: Decimal = Decimal("10.00")


settings = Settings()
