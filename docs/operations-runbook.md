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
- **Interrupted runs**: on API start, runs and media tasks that were running are
  marked interrupted/partial with a message. Re-POST `/evidence/extract` or
  `/editorial/select`: finished jobs are reused by idempotency key, never re-run.

The watchdog exits non-zero whenever it had to repair something, so the fleet's
`run-watched.sh` wrapper records a heartbeat and raises its usual deduplicated alert.

## What fails closed (by design)

- A worker whose environment contains a metered or third-party provider variable
  refuses to start (exit 2); the supervisor leaves that slot stopped.
- A worker that cannot verify a `claude.ai` subscription login (exit 3) waits 10
  minutes and verifies again. No job is leased until verification passes.
- TCE never logs in, switches or rotates Claude accounts.
- Schedules stay off (`TCE_SCHEDULER_ENABLED=false`); the scheduler routes answer 409.

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
4. Check `status.json`: `api_ok: true`, each worker `running`.

Moment extraction runs up to `TCE_EVIDENCE_EXTRACT_CONCURRENCY` (default 3) sources
at once, which matches three workers. More workers than that only helps selection,
which enqueues all shards together.
