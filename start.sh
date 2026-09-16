#!/bin/bash
# Fix 1 of the port-8200 zombie triad: --timeout-graceful-shutdown tells
# uvicorn to drain in-flight requests for up to 10s on SIGTERM before
# exiting. Before this flag, uvicorn exited immediately but TCP TIME_WAIT
# on :8200 held the port ~60s, which raced with pm2 spawning the new
# process -> "address already in use" loop.
#
# Must be paired with pm2 --kill-timeout 15000 (set via scripts/pm2-register.sh)
# so pm2 waits for the drain instead of SIGKILL'ing at the default 1.6s.
cd /home/ziv/team-content-engine
export PYTHONPATH=/home/ziv/team-content-engine/src
# Localhost only: km-worker calls http://localhost:8200, and the dashboard is
# reached through the authenticated nginx vhost. Private evidence must never be
# served on a public port. Override with TCE_BIND_HOST only behind a proxy.
exec python3 -m uvicorn tce.api.app:app --host "${TCE_BIND_HOST:-127.0.0.1}" --port 8200 --timeout-graceful-shutdown 10
