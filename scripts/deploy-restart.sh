#!/bin/bash
# Fix 3 of the port-8201 zombie triad: deploy-restart that ALWAYS clears
# port 8201 before starting the new process. Use this instead of bare
# `pm2 restart tce` on the VPS to guarantee deploys are idempotent even
# when the graceful-shutdown + kill-timeout combo fails (e.g. runaway
# request, stuck DB query, OOM).
#
# Flow:
#   1. pm2 stop tce   -> sends SIGTERM, uvicorn drains (~10s)
#   2. Poll :8201 up to 15s waiting for TCP release
#   3. If still held, force fuser -k
#   4. pm2 start tce
#
# Run from the repo root on VPS:
#   bash scripts/deploy-restart.sh
set -euo pipefail

echo "[deploy-restart] Stopping tce (graceful)..."
pm2 stop tce 2>&1 | tail -1

echo "[deploy-restart] Waiting up to 15s for port 8201 to release..."
for i in $(seq 1 15); do
  if ! sudo ss -lntp 2>/dev/null | grep -q ':8201 '; then
    echo "[deploy-restart] Port 8201 free after ${i}s"
    break
  fi
  sleep 1
done

if sudo ss -lntp 2>/dev/null | grep -q ':8201 '; then
  echo "[deploy-restart] Port still held - force-killing zombies..."
  sudo fuser -k 8201/tcp 2>&1 | tail -1 || true
  sleep 1
fi

echo "[deploy-restart] Starting tce..."
pm2 start tce 2>&1 | grep -E 'online|status' | head -3
sleep 3
echo "[deploy-restart] Final status:"
pm2 show tce 2>&1 | grep -E 'status|uptime|restarts' | head -3
