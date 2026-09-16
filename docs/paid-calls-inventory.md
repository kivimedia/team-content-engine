# Paid and metered call inventory (16-Sep-2026)

Scope: every outbound call in `src/tce` and `scripts/` that can cost money or quota,
what triggers it, and whether anything automatic can reach it. Written alongside the
subscription-only LLM change (work package 1).

## LLM text calls: no metered path remains

- Every text-generation call goes through `tce.llm.complete()` / `get_llm_client()`.
  It writes an `llm_jobs` row. A Claude Code worker logged in to a subscription
  (`scripts/tce_llm_worker.py`) runs it on `claude-opus-5` only.
- No code constructs a metered SDK client. The static scan in
  `tests/unit/test_llm_provider.py` fails the build if one returns.
- The Batch API service (`services/batch_api.py`) raises `LLMPolicyError`.
- The model fallback chain in `services/resilience.py` is empty.
- A usage limit on the subscription leaves the job `waiting_capacity` with a `retry_at`.
  Nothing retries it on another model, another account or a paid path.
- `CostTracker.record` now defaults to `billing="subscription"`. It stores real token
  counts and the model that ran, with `computed_cost_usd = 0`.
- Behaviour change: DOCX image OCR (`services/document_ingest.py`) used a metered vision
  call per embedded image. It is now disabled, because the worker is text-only. Images
  are counted in the log and are not transcribed.

## Scheduler gate

- `api/app.py` starts the scheduler at boot only when `TCE_SCHEDULER_ENABLED=true`.
  The default is off.
- `POST /api/v1/scheduler/start` and `POST /api/v1/scheduler/trigger/{job}` now return
  409 unless that setting is true. Before this change, both could start spend over HTTP
  without authentication.

Jobs the scheduler registers (`services/scheduler.py`) and what each can reach:

| Job | When | Paid calls reachable |
|---|---|---|
| `daily_content` | Mon-Fri 09:00 | web search, YouTube quota, image generation, ElevenLabs (via `video_agent`) |
| `weekly_planning` | Mon 07:00 | web search, YouTube quota |
| `weekly_learning` | Fri 17:00 | LLM jobs only |
| `quarterly_corpus_nudge` | Mon 10:00 | none (log line) |
| `linkedin_comment_poll` | Mon-Fri 11:00 | none (DB query + log) |
| `daily_backup` | 02:00 | none (local `pg_dump`) |
| `weekly_repo_spotlight` | Sun 07:00 | GitHub (free, rate-limited), web search, image generation |
| `competitor_velocity_poll_*` | every 6 h | YouTube Data API quota |

## Non-LLM paid or metered paths

| # | Provider | Code | Triggers | Gate | Automatic? |
|---|---|---|---|---|---|
| 1 | OpenAI Images (images/generations endpoint), the default image model | `services/openai_image.py` `generate_image`; routed by `services/image_generation.py` `generate_image` / `_one` | Pipeline step after `creative_director` (`orchestrator/engine.py`); `POST /content/packages/{id}/generate-images`; `POST /content/packages/{id}/regenerate-image/{idx}`; pipeline routes `/pipeline/run`, `/generate-week`, `/start-from-topic`, `/polish-copy`, `/start-from-repo`, `/run-for-workspace` | OpenAI key setting empty = skipped | Yes, through `daily_content` / `weekly_repo_spotlight`, only when the scheduler is enabled |
| 2 | fal.ai (`fal.run/{model}`) | `services/image_generation.py` | Same as 1, as fallback or for flux / cinematic prompts. `_one` tries the other provider on failure, so one image can bill both. | `fal_api_key` empty = skipped | Same as 1 |
| 3 | ElevenLabs TTS (`api.elevenlabs.io/v1`) | `services/tts.py` (`generate`, `generate_with_timestamps`, `list_voices`) | `POST /narration/tts-preview`; `POST /narration/scripts/{id}/tts-generate`; `GET /narration/tts-voices` (listing only); `video_agent._generate_voiceover` in video workflows (`/videos/generate`, `/videos/product-demo`, `/videos/batch`, pipeline routes) | `elevenlabs_api_key` plus a voice id | Yes, through `daily_content` when configured and the scheduler is enabled |
| 4 | OpenAI Whisper (audio transcriptions endpoint, `whisper-1`) | `services/audio_alignment.py` `transcribe_with_timestamps` | `POST /narration/scripts/{id}/align` | OpenAI key setting. There is no empty-key pre-check, so a request without a key fails with 401. | No |
| 5 | CutSense HTTP shim (`cutsense_api_url`, default localhost) | `agents/weekly_walking_pipeline.py` (`/transcribe`, `/split`, `/edit`, `/jobs/{id}/status`) | `POST /video-scripts/walking/weekly/{id}/run-split-edit` (403 unless `weekly_walking_pipeline`); `/pipeline/run` with `workflow=weekly_walking_split_edit` (no flag check) | optional service key | No. Transcription and vision spend happen on the CutSense host, not in this repo. |
| 6 | Brave Search (`api.search.brave.com`) | `services/web_search.py` | `trend_scout` (about 24 queries per run), `research_agent`, `proof_checker`, `POST /monthly/plan`, `POST /pipeline/brainstorm` tool calls, `POST /trends/scan`, `weekly_planner` | `search_api_key` empty = returns `[]` | Yes, through `daily_content`, `weekly_planning`, `weekly_repo_spotlight` |
| 7 | YouTube Data API v3 (quota) | `services/youtube_demand.py`, `services/competitor_velocity.py` | `trend_scout`; scheduled `competitor_velocity_poll_*` | `youtube_api_key` empty = skipped | Yes, 4 times a day when the scheduler is enabled |
| 8 | Resend (`api.resend.com/emails`) | `services/notifications.py` `_dispatch_external` | `NotificationService.notify`. Nothing in `src` calls it today. | `resend_api_key` + `notification_email` | No (dead path) |
| 9 | Slack webhook | `services/notifications.py` | same as 8 | `slack_webhook_url` | No (dead path) |
| 10 | Fathom API | settings only (`fathom_api_key`, `fathom_api_base`) in this package | evidence intake (package 2) | key | No |
| 11 | GitHub (git over HTTPS, PAT) | `services/repo_service.py` | `repo_scout` agent, `POST /repos/tracked/{id}/scan`, `GET /repos/remote-head`; `scripts/seed_tracked_repos.py` (REST, manual) | `github_pat` optional | Yes (`weekly_repo_spotlight`); free but rate-limited |
| 12 | S3-compatible storage | `services/storage.py` | image persistence, DOCX ingest | endpoint + keys, otherwise skipped | Indirectly, through image generation |
| 13 | Facebook Graph Send API | `services/cta_fulfillment.py` | `POST /dm-fulfillment/webhook/facebook` (inbound webhook, no signature check) | `facebook_page_token` | Inbound-triggered |

Not paid, listed for completeness:

- Reddit public JSON (`services/reddit_demand.py`, from `trend_scout`)
- arbitrary URL fetches (`services/url_fetcher.py`)
- local ffmpeg, Remotion and `pg_dump` subprocesses
- `gws` Gmail sends from the video-script email routes

## What this change activates

None of the paths above. This change does not add or enable any image, TTS,
transcription, search, YouTube, email, storage or publishing call. It also changes no
gate on any of them, except that the scheduler and its manual trigger now refuse to run
unless explicitly enabled.

The new LLM worker runs only the prompts already queued in `llm_jobs`. It never calls a
tool: it runs with `--tools ""`, no MCP servers and no setting sources.

## Findings outside this package (not changed here)

- `orchestrator/engine.py` gates pipeline images on `fal_api_key` while routing to
  OpenAI by default. A fal key alone enables OpenAI image spend if an OpenAI key is also
  set.
- Whisper alignment has no empty-key pre-check.
- The Facebook webhook does not verify `X-Hub-Signature`.
- `/pipeline/run` can start `weekly_walking_split_edit` without the feature flag.
