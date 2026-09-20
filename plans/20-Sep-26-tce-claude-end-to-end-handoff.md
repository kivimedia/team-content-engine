# TCE end-to-end closure handoff for Claude Code

Date: 20 September 2026

## Ownership and authorization

Take over the remaining TCE work end to end. Continue until every technical item that does not require Ziv's physical recording or editorial verdict is complete, tested, committed, pushed and deployed. Keep this file and the implementation report current so the conversation can continue through Claude without losing state.

Use only the verified VS Code Claude Code bundle and its first-party Max subscription for TCE runtime LLM jobs. Do not use a metered API, API-key authentication, account rotation, Codex or Grok fallback. Do not launch duplicate workers. Keep publishing disabled. There is no client approval gate.

Repository: `E:\FromC\projects\Team Content Engine`

Current production revisions: `f22a05364c92794ac76aec419f8a3a14bb395c69` and follow-up `778c1d98c243ed1517d2f84f84a20efa937a81dc`

Worker state: `C:\Users\raviv\.tce-worker\state`

Manual stop: `C:\Users\raviv\.tce-worker\state\STOP` is intentional. Never remove it because a date elapsed. Verify subscription capacity and policy first, then remove it only as an explicit operational resume while you own and observe the worker.

Credentials: read `C:\Users\raviv\.claude\projects\C--Users-raviv\memory\tce-editor-creds.md`. Never copy passwords, access keys or tokenized URLs into Git, reports or terminal output.

Primary implementation report: `E:\FromC\projects\Team Content Engine\plans\20-Sep-26-tce-completion-implementation.html`

Original execution plan: `E:\FromC\projects\Team Content Engine\plans\20-Sep-26-tce-completion-execution-plan.html`

Private progress ledger: `C:\Users\raviv\.tce-worker\state\implementation-20260920\progress.json`

Production backup: `/home/ziv/backups/tce/tce-pre-f22a053-20260920T110045Z.dump`, SHA256 `678f0bfb426aca0fd1af0166bf4554a96fcf2d841def8c0134db00b2d38ff453`

## Settled product decisions

Preserve all seven settled decisions in the execution plan: offer, position, rejection gates, content mix, recording format, weekly time budget and privacy boundary. Fathom and repository work are primary evidence. Keep the six accepted topics as positive calibration. Do not ask Ziv to decide these again.

## Verified completed work

- Production is on Alembic `040`; TCE is online under PM2.
- The code-only completion implementation is deployed. Its last recorded full suite was 636 passing tests.
- Durable content runs, stage leases, reusable selection work, packet v2, durable exports, recording sessions, chunk upload recovery, local editing integration, Produce now and the narrow Claude request adapter exist.
- Packet v2 generates exactly three ranked, evidence-linked openings with an unresolved question, payoff phrase, moment IDs and rationale. A chosen hook creates an immutable packet version. Validation requires the selected hook to be the spoken opening.
- The recording studio has camera preview, Points and Full script modes, beat jumps, scroll controls, Record, Pause, Resume, Finish clip, Finish session, local chunk persistence and recovery.
- Anonymous production access returns 401 and authenticated access succeeds.
- A manual STOP still prevents subscription workers from running.

Do not rerun completed jobs merely to prove activity. Reuse successful outputs when their source and prompt versions match.

## Open issues, in execution order

### 1. Finish and verify the public route

The canonical user route is `https://bot.kivimedia.co/tce/`, with the recorder at `https://bot.kivimedia.co/tce/record`. Preserve the older sslip route only as a temporary rollback path.

Use `/etc/nginx/snippets/kmbot-extra-tce.conf`. The `bot.kivimedia.co` vhost intentionally includes `kmbot-extra-*.conf`; do not edit generated `kmbot-locations.conf`. Keep backups outside `sites-enabled`. Proxy `/tce/*` to `127.0.0.1:8200`, strip the `/tce` prefix, retain Basic Auth through `/etc/nginx/tce.htpasswd`, clear the incoming Authorization header before upstream, inject the current private editor key from `/home/ziv/team-content-engine/.env`, support large recording uploads and keep adequate proxy timeouts. Never print the key.

Verify anonymous 401 and authenticated 200 for the recorder, CSS, JavaScript, recording queue and content-run endpoints. Verify phone camera and microphone permissions on the final HTTPS hostname. Add no root favicon request that can trigger auth failures.

### 2. Complete the hook and curiosity-gap recorder experience

The generation and backend contracts are complete, but the current recorder only displays the selected opening. It does not show all three ranked alternatives or let Ziv compare and choose one. This means the hook work from the recording-studio prototype is only partially complete.

Add a compact hook chooser before recording starts. Show the recommended hook first, the viewer question and a short private rationale for each option. Choosing another option must call `POST /api/v1/editorial/packets/{packet_id}/choose-hook`, receive the new immutable packet version, update the recording queue/session binding and never mutate a packet already used by a recording. Do not overload the walking reader with editorial detail once recording begins.

Add regression coverage for selection, immutable packet versioning, active-session protection, mobile layout and the selected opening remaining the first spoken phrase.

### 3. Install durable VPS daily and weekly cron ownership

Cron on the VPS must own occurrence creation. TCE subscription generation remains on the authenticated PC worker. Cron may enqueue durable server runs while the PC is offline; it must never invoke a metered provider or pretend the worker is online.

Recommended schedule:

- Daily at 07:15 Asia/Jerusalem: collect and extract new evidence only, then leave generation queued or ready for the weekly run.
- Monday at 07:30 Asia/Jerusalem: create the full previous completed Monday-to-Monday run through the same coordinator used by Produce now.

The VPS cron implementation must handle Israel daylight saving time through an `Asia/Jerusalem` aware launcher and persistent occurrence keys. Do not hardcode UTC+3. The server's cron is UTC and does not reliably honor `CRON_TZ`. A frequent cron tick plus a timezone-aware guard is acceptable. Store last occurrence durably in PostgreSQL, not a temporary file.

Disable duplicate schedule ownership in the legacy in-process scheduler. Keep the new editorial schedule separate from old daily-generation and publishing switches. Test DST boundaries, missed execution within seven days, repeated ticks, restart and concurrent ticks. Show waiting for worker accurately.

### 4. Resume the unfinished real evidence run

Before resuming, verify the pinned VS Code Claude executable, `auth status --json`, first-party `claude.ai` authentication, Max subscription and the required Opus policy. Confirm actual capacity with a policy-compliant job, not the absence of an error message. Then explicitly remove manual STOP and start exactly one supervisor with the existing worker group.

Reconcile the 7 to 13 September repository equation: 295 groups = 121 analyzed + 15 justified exclusions + 159 pending. Resume only the 159 pending groups using existing job keys and current source versions. Preserve all 33 meeting extractions, 259 successful jobs, six earlier candidates, the saved 21-shard run, feedback and previous packets.

Monitor capacity pause, heartbeat freshness, leases and durable completion outbox. If subscription capacity remains unavailable, restore manual STOP, record the exact provider response and continue all independent work.

### 5. Finish selection, ranking, packets and Google Docs

Freeze the complete evidence snapshot after extraction. Run the final whole-week selection and global ranking without silently truncating sources. Account for every shard and finalist. Preserve previous candidates until the full new result commits.

Generate at least three strong packet-v2 outputs if the evidence supports them. Each needs 5 to 7 walking points, full phrase script, three honest openings, payoff mapping, beat map, interviewer prompt, Facebook and LinkedIn adaptations, private citations and the strategy-session CTA. Do not fill a quota with weak ideas.

Export actual Google Docs with durable identity, content and access readback. Zero Google Doc IDs is still the current open state. Owner-only is accurate until intended editors are resolved. A DOCX download is not a Google Docs success.

### 6. Exercise Produce now and the conversational request

Verify repeated Produce now clicks deduplicate and resume the same normalized run. Test one actual targeted request such as: `Yesterday's Fathom with Dovid is sick. Make a script for me in TCE.` Resolve yesterday in Asia/Jerusalem, show the exact dated meeting, refresh that date once if absent, and ask only when multiple real meetings match. Create a targeted one-idea run that does not supersede weekly candidates.

Return a real focused TCE run link. Keep transcript text as untrusted data and expose no arbitrary shell or publishing action.

### 7. Close editing integration with real media

Confirm whether the local ASR listener is running and inspect its actual timing contract. It was previously absent on port 8765. Use local ASR only. Preserve the honest coarse-timing and uncut fallback if precise word timing is unavailable.

Run the real canonical session through ffprobe, transcription, conservative edit planning, rendering and captions. Preserve all source clips and the uncut result. Listen to retained and removed spans. Automatic checks do not establish that the best performance was selected.

### 8. Ziv-only acceptance and pilot

Prepare the recorder and give Ziv one exact action. Ziv must record two short clips using both reader tabs, repeat one line three times, pause and resume, switch scripts and return, then judge eye line, outdoor readability, hand reach and preferred reader mode. He must listen to the edit and confirm its meaning.

The two-week pilot requires three publishable originals and at least two recorded clips per week within 90 minutes of Ziv's time. Publishing remains separately controlled. Report technical readiness, first real recording accepted and two-week pilot completed as three separate statuses. Do not claim Phase 4 closed before the observed pilot finishes.

## Tests and deployment discipline

For every bug, reproduce the failure before fixing it. Run focused tests, the relevant full suite, Ruff, Python compilation, JavaScript syntax and Alembic single-head checks. Use synthetic fixtures for ordinary tests and never invoke paid services from tests.

Commit the complete dependency chain, push, deploy TCE only and independently verify authenticated live behavior after restart. Do not restart unrelated VPS services. Preserve additive schema and raw media during application rollback. Never roll back to a metered client.

After every production change, update both:

- `E:\FromC\projects\Team Content Engine\plans\20-Sep-26-tce-completion-implementation.md`
- `E:\FromC\projects\Team Content Engine\plans\20-Sep-26-tce-completion-implementation.html`

The HTML must remain self-contained, truthful, readable on mobile and served at `http://localhost:47800/tce/20-Sep-26-tce-completion-implementation.html`. Keep the final live route and exact remaining Ziv action prominent.

## Definition of technical completion

Technical completion requires the canonical `bot.kivimedia.co/tce` route, hook choice UI, durable cron schedules, all 159 groups resolved or explicitly excluded, full-source ranking, final packets, verified Google Docs, deduplicated Produce now, one real targeted Claude request, one real mobile recording manifest and a verified edited output. It also requires fresh subscription-authenticated Opus receipts and one-worker ownership. Only Ziv's recording judgment and the observed two-week pilot may remain after that point.

## Resolved takeover questions

1. Do not keep one unattended closure process alive until 24 September. Complete all independent work in the visible VS Code session. Then recheck the live subscription state because the stored STOP reason may be stale. A fresh successful policy-compliant worker job is the capacity proof. If still capped, preserve STOP and leave a precise resumable checkpoint for the reset instead of idling for days.
2. Google Docs uses the existing `GwsDocsClient` contract in `src/tce/production/export.py`. It invokes the authenticated `gws` CLI on the TCE execution host. Verify which account that host actually reports before export. The intended owner is Ziv's Google Workspace identity, currently expected to be `ravivziv@gmail.com`; do not assume this without the auth check and do not introduce a service account unless the existing route cannot work.
3. Use owner-only restricted Docs for the first successful export. No team editor list is currently required, and missing editor emails must not block Phase 4 technical proof. Record owner-only truthfully. Sharing can be configured later when Ziv names recipients.
4. Resolve the targeted request from real Fathom metadata. Search yesterday first exactly as the request says. If no matching Dovid meeting exists, prove the refresh-once and no-match behavior, then run the successful one-idea acceptance against the most recent real Dovid meeting discovered by metadata. Do not assume the 16 September PRISM call without evidence. Report the exact title and date used.
5. The intended ASR is a self-hosted faster-whisper WebSocket service at `ws://127.0.0.1:8765/transcribe`, configured by `TCE_PRODUCTION_TRANSCRIBE_WS_URL`. TCE already understands segment and word timing. Discover an existing service/install contract first. If none exists, install a persistent local faster-whisper service on the VPS, document its model and startup ownership, and keep paid Whisper disabled. Preserve the coarse-timing or uncut path until the listener passes a real fixture.
6. `/etc/nginx/snippets/kmbot-extra-tce.conf` is the persistent integration surface. The `bot.kivimedia.co` vhost includes `kmbot-extra-*.conf`, while generated KM Bot locations live elsewhere. Add a deployment regression check that the include and TCE snippet remain present after a KM Bot configuration refresh. Never place backup files inside `sites-enabled` or the wildcard snippet directory.
7. Real phone camera and microphone acceptance is Ziv-only and belongs to the human acceptance phase. Technical item 1 closes with authenticated HTTPS, correct assets/API routing, responsive browser checks and permission-capable markup. Give Ziv the exact real-phone action afterward; do not leave the routing task falsely open.
