#!/bin/bash
# Fix 1 of the port-8201 zombie triad: --timeout-graceful-shutdown tells
# uvicorn to drain in-flight requests for up to 10s on SIGTERM before
# exiting. Before this flag, uvicorn exited immediately but TCP TIME_WAIT
# on :8201 held the port ~60s, which raced with pm2 spawning the new
# process -> "address already in use" loop.
#
# Must be paired with pm2 --kill-timeout 15000 (set via scripts/pm2-register.sh)
# so pm2 waits for the drain instead of SIGKILL'ing at the default 1.6s.
cd /home/ziv/team-content-engine
export PYTHONPATH=/home/ziv/team-content-engine/src
exec python3 -m uvicorn tce.api.app:app --host 0.0.0.0 --port 8201 --timeout-graceful-shutdown 10
