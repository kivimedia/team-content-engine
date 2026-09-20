# TCE operations runbook

How the Team Content Engine stays up, how to tell when it is not, and how to stop
it safely. No hostnames, keys or paths to private data belong in this file.

## The three moving parts

| Part | Where | Kept alive by | Status |
|---|---|---|---|
| API + dashboard (`uvicorn tce.api.app`) | server, pm2 name `tce`, bound to 127.0.0.1:8200 behind the authenticated nginx vhost | pm2 (resurrected at boot from the saved dump) + `scripts/tce-watchdog.sh` from cron every 5 minutes | `~/state/tce/status.json`, `~/logs/tce-watchdog.log`, `GET /api/v1/health` |
| Database | server, docker container `tce-db` (restart policy `unless-stopped`) | docker + the same watchdog | `docker inspect tce-db` |
| Subscription LLM worker(s) | the desktop where Claude Code is logged in to the subscription | Windows Scheduled Task "TCE Subscription Worker" running `scripts/tce_worker_supervisor.py` hidden (pythonw) | `%USERPROFILE%\.tce-worker\state\status.json`, dashboard "Live activity" worker row, `GET /api/v1/llm-jobs/worker-status` |

### Why the worker lives on a desktop, and what that means

Every model call is Claude Opus 5 through a Claude Code subscription login. There is
no metered API key and no fallback model: the queue waits instead. The login lives
on the desktop, so **the desktop must be on, awake and logged in for any LLM work to
happen** (moment extraction, weekly selection, global ranking, packets). While it
sleeps, jobs stay `queued` with nothing lost; they run when it wakes. To keep it
working overnight, set Windows power options so the machine does not sleep while
plugged in. Collection (Fathom, GitHub), the dashboard, uploads, transcription and
rendering do not need the desktop.

## What recovers on its own

- **Server reboot or pm2 daemon restart**: pm2 resurrects `tce` from the saved dump.
  If the dump ever loses it (this happened on 18-Sep-2026 after a fleet-wide pm2
  restart), the watchdog re-registers it within 5 minutes and saves the dump.
- **API hung or port 8200 stuck**: two failed health checks in a row trigger
  `scripts/deploy-restart.sh`.
- **Database container stopped**: the watchdog starts it.
- **Worker crash**: the supervisor restarts it (5 s backoff, doubling to 5 min).
- **SSH tunnel drop**: the supervisor restarts it with backoff.
- **Supervisor crash or desktop logon**: the scheduled task relaunches it (at logon
  and every 5 minutes; a lock file makes a relaunch a no-op while it runs).
- **Interrupted content runs**: `content_runs` and `content_run_stages` keep the
  exact completed stages and output references. POST
  `/api/v1/content-runs/<run-id>/resume` leases the first unfinished stage. The
  stored selection run id and subscription job idempotency keys reuse completed
  jobs instead of creating duplicates.
- **Interrupted Google Docs exports**: `export_intents` commits the document id
  before content, sharing or permission readback. A retry finds that id and
  continues. It also rechecks access on an already verified export so permission
  drift cannot remain labelled safe.
- **Interrupted phone uploads**: recording chunks are checksum-addressed and
  idempotent by clip and sequence. The browser keeps unsent chunks in IndexedDB;
  the API assembles only a complete sequence and keeps every source clip after it
  creates the canonical upload.

The watchdog exits non-zero whenever it had to repair something, so the fleet's
`run-watched.sh` wrapper records a heartbeat and raises its usual deduplicated alert.

## What fails closed (by design)

- A worker whose environment contains a metered or third-party provider variable
  refuses to start (exit 2); the supervisor leaves that slot stopped.
- A worker that cannot verify a `claude.ai` subscription login (exit 3) waits 10
  minutes and verifies again. No job is leased until verification passes.
- TCE never logs in, switches or rotates Claude accounts.
- The older publishing scheduler stays off (`TCE_SCHEDULER_ENABLED=false`). The
  content-run poller only sees durable `editorial_schedules` rows, and every new
  weekly schedule starts disabled. Enabling one is an explicit private API action.
- Google Docs export fails closed as `not_connected`, `waiting_worker` or
  `access_problem`. A private DOCX may exist, but the content run is not `ready`
  until the restricted Google Doc passes permission readback.

## Stopping things safely

- **Stop the desktop worker**: create `%USERPROFILE%\.tce-worker\state\STOP`. Workers
  and tunnel stop within 15 s and every relaunch exits at once. Delete the file to
  resume. To remove it entirely: `Unregister-ScheduledTask -TaskName "TCE Subscription Worker"`.
- **Stop the API on purpose** (for example a rollback): first
  `touch ~/state/tce/disabled` so the watchdog does not start it again, then
  `pm2 stop tce`. Remove the file after `pm2 start tce`.
- **Rollback rule**: roll back only to a commit that still runs the subscription-only
  queue. Never boot pre-subscription code; if no safe revision exists, stop TCE.

## Installing on a new desktop

1. Create the venv (`.venv`) with the project dependencies and log Claude Code in to
   the subscription.
2. Put the TCE private access key in `%USERPROFILE%\.tce-worker\private_access_key`
   and restrict the file to your user (`icacls <file> /inheritance:r /grant:r "%USERNAME%:F"`).
3. `powershell -NoProfile -File scripts\install_tce_worker_task.ps1 -SshTarget <user@server> -Workers 3`
4. The installer finds the newest VS Code Claude bundle, resolves its exact
   executable path, checks `auth status --json` for a first-party `claude.ai`
   subscription session, records the CLI version, and passes the pinned path to
   the supervisor. PATH discovery is intentionally rejected at worker runtime.
5. Check `status.json`: `api_ok: true`, `auth_ok: true`, the expected Opus policy,
   and each worker `running`. The API treats a worker receipt older than 180 seconds
   as offline.

Moment extraction runs up to `TCE_EVIDENCE_EXTRACT_CONCURRENCY` (default 3) sources
at once, which matches three workers. More workers than that only helps selection,
which enqueues all shards together.

## Content request surfaces

All three surfaces create the same durable `content_runs` record and share the
same stage contract: collecting, extracting, selecting, ranking, drafting and
exporting.

- `POST /api/v1/content-runs/produce-now`: run an explicit week or source scope.
- `POST /api/v1/content-runs/from-claude/request`: resolve a request such as
  "Yesterday's Fathom with Dovid is sick. Make a script for me in TCE." Ambiguous
  matches return choices and create no run.
- `PUT /api/v1/content-runs/schedule/weekly`: configure the disabled-by-default
  weekly schedule. Occurrence keys make catch-up and repeated ticks idempotent.
- `GET /api/v1/content-runs/<run-id>`: inspect current stage, attempts, job ids,
  outputs and the exact failure or wait reason.

Every route requires the existing private workspace access header. Produce now
does not bypass subscription capacity, create a metered call, or publish content.

## Recording and post-production

`GET /record` serves the mobile recording studio. It provides the selected hook,
Points and Full script tabs, beat and scroll controls, text sizing, Record,
Pause/Resume, Mark take, Finish clip and Finish session. Camera and microphone
checks run before recording. A session can contain several clips and switch to
another script without losing the current take.

Finalization verifies audio and video with ffprobe, joins selected clips with
ffmpeg, saves a timeline map with clip offsets and take markers, and creates one
canonical `recording_uploads` row. Source clips remain available for a later edit.

The configured transcription WebSocket remains a required local dependency. If
it is unavailable, TCE says so and does not buy a transcription fallback. Precise
word timings are labelled `word`; a legacy transcript without word timing is
labelled `coarse` and cannot support timing-sensitive auto-edit claims.

## Deployment and migration checks

Before `alembic upgrade head`:

1. Verify no duplicate `(workspace_id, candidate_id, version)` rows exist in
   `recording_packets`.
2. Take and size-check a PostgreSQL custom-format backup.
3. Restore that backup into a temporary database and run migrations 038, 039 and
   040 there.
4. Keep the desktop `STOP` file in place throughout the deployment.

After restart, verify `/api/v1/health`, Alembic head `040`, anonymous denial on
the live private routes, authenticated `/record`, and a worker status that is
honestly stopped or offline while `STOP` exists. Rollback uses the recorded prior
commit plus the pre-migration backup; never downgrade tables while new code is
still accepting writes.
