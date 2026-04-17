#!/bin/bash
# Fix 2 of the port-8200 zombie triad: re-register TCE with pm2 using a
# longer kill_timeout so pm2 actually waits for uvicorn's graceful
# shutdown (configured in start.sh) before SIGKILL.
#
# Default pm2 kill_timeout is 1600ms. Uvicorn's graceful shutdown is 10s.
# Setting kill_timeout to 15s gives uvicorn the full drain window plus
# buffer for the TCP close handshake.
#
# Run this ONCE on the VPS after the first deploy that ships start.sh's
# --timeout-graceful-shutdown flag. Re-run if pm2 config is ever reset.
#
# From the repo root on VPS:
#   bash scripts/pm2-register.sh
set -euo pipefail

cd /home/ziv/team-content-engine

echo "[pm2-register] Deleting existing tce process (if any)..."
pm2 delete tce 2>&1 | tail -1 || true

echo "[pm2-register] Registering tce with kill_timeout=15000..."
pm2 start /home/ziv/team-content-engine/start.sh \
  --name tce \
  --kill-timeout 15000 \
  --cwd /home/ziv/team-content-engine

echo "[pm2-register] Persisting pm2 config across reboots..."
pm2 save 2>&1 | tail -1

echo "[pm2-register] Done. kill_timeout:"
pm2 show tce 2>&1 | grep -iE 'kill.?timeout|name' | head -3
