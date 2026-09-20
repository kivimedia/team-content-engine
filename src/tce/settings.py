"""Application settings loaded from environment variables."""

import tempfile
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_TMPDIR = Path(tempfile.gettempdir())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCE_", env_file=".env")

    # Database
    database_url: str = "postgresql+asyncpg://tce:tce@localhost:5432/tce"

    # Anthropic
    anthropic_api_key: SecretStr = SecretStr("")

    # Model tiers (per PRD Section 37)
    default_model: str = "claude-sonnet-5"
    opus_model: str = "claude-opus-4-7"
    haiku_model: str = "claude-haiku-4-5-20251001"
    script_model: str = "claude-sonnet-5"  # Model for ScriptAgent narration

    # Budget controls (per PRD Section 36.5)
    daily_budget_usd: Decimal = Decimal("40.00")
    monthly_budget_usd: Decimal = Decimal("800.00")

    # fal.ai
    fal_api_key: str = ""

    # Image generation provider/model
    # Default routes to OpenAI's gpt-image-2; fal.ai is the fallback for
    # photoreal/cinematic prompts the creative_director flags as fal_ai.
    default_image_model: str = "gpt-image-2.5-sunburst"

    # Local disk fallback when S3 isn't configured. OpenAI returns b64 by
    # default; we write it here and serve via /api/v1/images/<file> so the
    # database stays clean and the dashboard doesn't ship megabytes of
    # base64 inline.
    image_storage_dir: str = str(_TMPDIR / "tce-images")
    image_public_base: str = (
        ""  # If set (e.g. "https://tce.example.com"), prefixed; otherwise relative URL.
    )

    # Logging
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Pipeline
    max_pipeline_concurrency: int = 5

    # Web search (GAP-01)
    search_api_key: str = ""

    # YouTube Data API v3 â€” viral video demand signals for trend_scout.
    # Quota: 10000 units/day default, search costs 100 units, videos.list 1 unit.
    # A typical trend_scout run uses ~600 units (6 queries Ã— 100), so daily budget
    # caps to roughly 16 runs/day. trend_scout fetches gracefully degrade when
    # this is unset or quota-exceeded.
    youtube_api_key: str = ""

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

    # Video rendering (Remotion)
    remotion_project_path: str = ""  # Auto-detected from repo root if empty
    video_output_dir: str = str(_TMPDIR / "tce-video")
    video_default_codec: str = "h264"
    video_max_render_seconds: int = 120

    # Audio / Narration (Whisper alignment)
    openai_api_key: str = ""
    audio_upload_dir: str = str(_TMPDIR / "tce-audio")

    # ElevenLabs TTS (voiceover generation)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""  # Default voice ID for narrations
    elevenlabs_model: str = "eleven_multilingual_v2"

    # Multi-tenancy / service auth
    service_key: str = ""  # Shared secret for km-worker -> TCE calls

    # Repo-based content (Start From Repo feature)
    github_pat: str = ""  # Personal access token for private repos + higher rate limits
    repo_cache_dir: str = str(_TMPDIR / "tce-repo-cache")
    repo_brief_ttl_hours: int = 6  # How long a cached RepoBrief survives before re-fetch
    repo_commit_window_days: int = 30  # How far back repo_scout looks for commits

    # CutSense VPS HTTP shim (weekly walking-video pipeline)
    cutsense_api_url: str = "http://localhost:8300"
    cutsense_service_key: str = ""  # Matches CUTSENSE_SERVICE_KEY on VPS; empty = no auth

    # Feature flags
    weekly_walking_pipeline: bool = False  # TCE_WEEKLY_WALKING_PIPELINE=1 to enable

    # Recurring generation schedules. Off by default so a restart can never spend.
    scheduler_enabled: bool = False

    # Content-run schedule ownership. The VPS cron calls
    # POST /api/v1/content-runs/schedule/tick (scripts/tce-schedule-tick.sh) and
    # is the only owner of occurrence creation. The in-process poller exists for
    # a box with no cron and is OFF by default: two owners are one too many.
    content_run_poller: bool = False  # TCE_CONTENT_RUN_POLLER=1 to enable

    # Read by start.sh (uvicorn --host). Declared so .env validation accepts it.
    bind_host: str = "127.0.0.1"

    # Subscription-only LLM policy. "subscription" is the only accepted value;
    # anything else fails closed. Jobs run on a Claude Code worker, never a metered API.
    llm_provider: str = "subscription"
    llm_job_wait_timeout_s: float = 900.0
    llm_job_lease_seconds: int = 600

    # Private evidence / editorial / production routes (see api/private_access.py)
    private_access_key: SecretStr = SecretStr("")
    editor_default_workspace_id: str = ""

    # Evidence intake
    fathom_api_key: SecretStr = SecretStr("")
    fathom_api_base: str = "https://api.fathom.ai/external/v1"
    evidence_repo_cache_dir: str = str(_TMPDIR / "tce-evidence-repos")
    evidence_upload_dir: str = str(_TMPDIR / "tce-recordings")
    # Sources extracted at once. Each waits on one queued subscription job, so this
    # only helps when that many workers are leasing; extra jobs simply stay queued.
    evidence_extract_concurrency: int = 3

    # Recording and production (package 4). Every step here is local or free.
    production_max_upload_bytes: int = 4_000_000_000
    production_allowed_media_types: str = (
        "video/mp4,video/quicktime,video/webm,video/x-m4v,audio/mpeg,audio/mp4,"
        "audio/x-m4a,audio/m4a,audio/wav,audio/x-wav,audio/webm,audio/ogg"
    )
    # Self-hosted faster-whisper worker (ws://127.0.0.1:8765/transcribe on the VPS).
    # Empty = transcription shows as unavailable. No paid transcription fallback.
    production_transcribe_ws_url: str = ""
    production_transcribe_language: str = ""  # empty = auto-detect
    production_pause_threshold_s: float = 1.2
    # "gws" = create Google Docs with the gws CLI on this host; "off" = private .docx only
    production_google_export: str = "off"
    production_gws_binary: str = "gws"
    production_doc_team_emails: str = ""  # comma list shared as writers; never link sharing


settings = Settings()
