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
    opus_model: str = "claude-opus-5-5"
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

    # The third lane ("News that excites Ziv"). Off by default and shipped off:
    # with this false nothing fetches a feed, nothing builds an anchor index and
    # the selector sees no news moments, so turning it off is the whole rollback.
    # The daily-news schedule ships disabled separately.
    news_lane: bool = False  # TCE_NEWS_LANE=1 to enable

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
    # A client's own login (comma list of <editor key>:<workspace uuid>). The proxy
    # injects that key for that client's Basic Auth user; the key is bound to its
    # one workspace and fenced off every other route (api/private_access.py).
    # Empty = no client logins, every request behaves exactly as before.
    editor_workspace_keys: SecretStr = SecretStr("")
    # Owner workspaces (comma list). A profile pick with no workspace context reads
    # only these and NULL-workspace rows, never a client workspace. Empty = the
    # editor default workspace plus the original owner workspace.
    owner_workspace_ids: str = ""
    # Per-workspace content language (comma list of <workspace uuid>:<code>), e.g.
    # TCE_WORKSPACE_LANGUAGES=40c0f179-7d5e-4397-b4de-b0b2f3e96fc2:he. A workspace not
    # listed is "en" and behaves exactly as before. Only "he" changes anything today.
    workspace_languages: str = ""
    # Per-workspace idea lanes (comma list of <workspace uuid>:<profile>), e.g.
    # TCE_WORKSPACE_LANE_PROFILES=40c0f179-7d5e-4397-b4de-b0b2f3e96fc2:performer.
    # A workspace not listed keeps the owner selector exactly as before.
    workspace_lane_profiles: str = ""
    # Read by scripts/tce-schedule-tick.sh (comma list); declared so the API accepts the .env line.
    schedule_workspaces: str = ""
    # Per-workspace aside names (comma list of <workspace uuid>:Name|Name), the people or
    # pets a client talks to off camera, e.g. his dog. Owner workspaces keep
    # production_aside_names. A client workspace not listed has none.
    workspace_aside_names: str = ""

    # Web push. Absent keys simply mean no notifications are sent; nothing else
    # in the app depends on them, and the reconciler stays asleep.
    vapid_public_key: str = ""
    vapid_private_key: SecretStr = SecretStr("")
    vapid_subject: str = "mailto:ziv@kivimedia.co"

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
    # 25-Sep: a finished session edits itself and editing requests run themselves,
    # on the subscription worker. Off = the old click-each-step flow.
    production_auto_edit: bool = True
    # 28-Sep: his dogs. A short line with their name in it is talk to them, not to the
    # viewer, and is cut ("If I call my dogs maple, rain ... that needs to be edited out").
    production_aside_names: str = "Maple,Rain"
    # How long a late editor review is still waited for after the edit rendered without it.
    production_review_wait_h: float = 12.0
    # 3-Oct: Jennifer checks every edit after it renders (pauses, leftover asides, every
    # word heard, captions, loudness). "fix" = she fixes what a cut can fix with one
    # re-render and holds what she cannot; "report" = she only measures and says;
    # "off" = no check. A pause longer than production_pause_threshold_s is a gap.
    production_qc: str = "fix"
    # How long her check waits for the subscription worker to read the words for
    # leftover asides before it goes on without that reading (and says so on the card).
    production_qc_asides_wait_s: float = 600.0
    # Transcribe the finished video again on the local recogniser, to find words that
    # cannot be heard. Off = she relies on the level reading at each cut.
    production_qc_listen: bool = True
    # A note of his that was applied becomes a rule for every next video (or is
    # recorded as only about that video), decided by one subscription job.
    production_learn_rules: bool = True
    # 26-Sep: TCE publishes the edited video through the schedule-* skills on this box.
    production_skills_dir: str = "/home/ziv/skills"
    production_linkedin_env_file: str = "/home/ziv/.kmboards-li.env"
    # His own 15-minute booking page (memory: ziv-booking-link).
    tce_booking_url: str = "https://kivimedia.co/15"
    # Where this server answers itself; LinkedIn fetches the video from a URL.
    production_self_url: str = "http://127.0.0.1:8200"
    # "gws" = create Google Docs with the gws CLI on this host; "off" = private .docx only
    production_google_export: str = "off"
    production_gws_binary: str = "gws"
    production_doc_team_emails: str = ""  # comma list shared as writers; never link sharing


settings = Settings()
