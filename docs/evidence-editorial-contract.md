# Evidence-first editorial system: shared contract (v1, 16-Sep-2026)

Public repository. Nothing here, in tests or in fixtures may contain real transcripts,
client names, commit contents from private repos, credentials, local paths or money
figures. Synthetic fixtures only.

## Records

`SourceRecord (evidence_sources) -> EvidenceMoment -> TopicCandidate -> RecordingPacket ->
RecordingUpload -> PublicationReceipt`, plus `evidence_collection_runs` (coverage ledger),
`editorial_feedback` and `llm_jobs`. Models: `src/tce/models/editorial.py`,
`src/tce/models/llm_job.py`. Migration `037` is additive only.

Every row has a non-null `workspace_id`. Routers filter `Model.workspace_id == ws`
explicitly. Raw content lives only in `*_private` columns. Claim types:
quoted, paraphrased, inferred, demonstrated, measured. A draft may not state a
measured outcome unless a cited moment has `claim_type == "measured"`.

## Access

All routes below use `Depends(require_private_workspace)` from
`tce.api.private_access` (returns the workspace UUID). No key configured means 503.

## LLM policy (package 1)

`from tce.llm import LLMRequest, complete, get_llm_client, LLMUnavailable, LLMPolicyError`.
Only `claude-opus-5` through a Claude Code subscription worker. No metered client, no
batch API, no lower-model fallback. Capacity exhaustion leaves the job
`waiting_capacity` with `retry_at`; callers surface that state, they never retry
elsewhere.

`/api/v1/llm-jobs`
- `POST /lease` `{worker_id, lease_seconds}` -> `{job|null}` (job includes `id, attempt_id,
  request_json, policy_model, job_type`)
- `POST /{id}/heartbeat` `{attempt_id}` -> `{leased_until}` (409 if attempt is stale)
- `POST /{id}/complete` `{attempt_id, result_text, result_json, receipt}` -> job
  (idempotent for the same attempt; 409 for a stale attempt)
- `POST /{id}/fail` `{attempt_id, error_code, error_detail, retry_at?}` -> job
  (`capacity` -> waiting_capacity; `policy_violation`/`model_mismatch`/`auth` -> failed;
  other -> queued again until max_attempts)
- `GET /` `?status=&limit=` -> `{jobs:[...], counts:{status:n}}`; `GET /{id}`
- `GET /worker-status` -> latest worker preflight receipt(s)

## Evidence intake (package 2)

`/api/v1/evidence`
- `POST /collect` `{kinds:["fathom","github"], window_start, window_end}` -> `{run_ids}`
  (background, returns immediately)
- `GET /runs?limit=` and `GET /runs/{id}` -> run with `status, counts, items, errors,
  complete, current_activity`
- `GET /coverage?window_start=&window_end=` -> per source kind latest run summary
- `GET /sources?kind=&window_start=&window_end=` -> list without payload;
  `GET /sources/{id}` -> with payload (editor only)
- `POST /extract` `{window_start, window_end}` -> starts moment extraction for sources
  lacking active moments for their current version_hash -> `{started, job_ids}`
- `GET /moments?window_start=&window_end=&status=` -> moments

## Editorial selection (package 3)

`/api/v1/editorial`
- `POST /select` `{week_start, max_candidates<=6}` -> `{selection_run_id, candidates:[...],
  rejected:[{moment_ids, gate, reason}], status}` (zero candidates is valid)
- `GET /candidates?week_start=&status=` -> `{candidates:[Candidate]}` ordered by rank
- `PATCH /candidates/{id}` `{status?, editor_notes?}`
- `POST /candidates/{id}/feedback` `{kind, rating?, gate?, note?}` -> feedback row
- `GET /candidates/{id}/feedback`
- `POST /candidates/{id}/packet` -> packet (runs one subscription job)
- `GET /candidates/{id}/packets` / `GET /packets/{id}`
- `GET /strategy` -> effective strategy text + where each part came from (file, DB override,
  prompt version)

Week: `week_start` is a Monday calendar label and stays stored as that naive date. Evidence
belongs to the week by Asia/Jerusalem time (Monday 00:00 to Monday 00:00, DST-aware), e.g.
week 2026-09-07 = `2026-09-06T21:00Z <= occurred_at < 2026-09-13T21:00Z`.

Coverage (`editorial_selection.v2`): every eligible week moment is sent to the model, in
shards of at most 40 (one job per shard, sources kept whole). The evergreen reserve is at
most 30 moments, round robin across sources. The selection result carries `coverage{window,
week_moments, reserve{eligible, included, omitted, policy}, shards[{shard, moments, job_id,
status, accounted, unaccounted}], considered, unaccounted_moment_ids, complete}`. If any
shard does not finish, nothing is saved or superseded. Moments the model skipped are listed,
never turned into rejections.

Durable status: `GET /select-status` and `GET /candidates/{id}/packet-status` return `job`
(the live in-process entry while running, otherwise the durable view rebuilt from llm_jobs
and saved rows) and `durable{state: done|waiting|failed|interrupted, resumable,
current_activity, job_ids, shards?}`. `GET /jobs` adds `in_flight` (queued, leased or
waiting editorial jobs on record). `POST /select` and `POST /candidates/{id}/packet` resume
a resumable run under its own job keys (`resumed: true`), so no job is enqueued twice and
a run is saved once.

Candidate JSON: `id, rank, rank_score, title, lesson, audience, reasons_to_care[],
public_angle, public_safety_notes, gates{gate:{pass,reason}}, freshness_role, status,
editor_notes, citations_private[{moment_id, source_kind, source_title, occurred_at,
span_start_s, span_end_s, code_refs, url_private, claim_type, speaker,
speaker_confidence, translation_label, excerpt_private}], origin, feedback[]`.

Packet JSON: `id, candidate_id, version, bullets[5..7], script_phrases[], facebook_post,
linkedin_post, interviewer_prompt, citations_private[], public_safety{status, issues[]},
google_doc_url, google_doc_access, status`.

## Recording and production (package 4)

`/api/v1/production`
- `POST /packets/{id}/export` -> Google Doc when a connection exists, otherwise an explicit
  `{status:"not_connected", docx_url}`; records intended and verified access
- `POST /candidates/{id}/recording` (multipart, one file per idea) -> upload row
- `GET /uploads/{id}`; `POST /uploads/{id}/plan-edit` -> edit plan (pauses, retakes,
  meaning check); `POST /uploads/{id}/render` -> edited file + captions
- `POST /candidates/{id}/publications` `{platform, external_post_id, url, published_at,
  final_text}` (dedup on platform+external_post_id); `PATCH /publications/{id}` `{outcome}`
- `GET /activity` -> `{now, llm_jobs:[...], collection_runs:[...], uploads:[...]}` with
  human-readable `current_activity` strings for the dashboard live panel

TCE records publications. It does not publish in this workflow.
