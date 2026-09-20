#!/bin/bash
# The VPS cron heartbeat that owns TCE content-run scheduling.
#
# Cron on this box is UTC and does not reliably honour CRON_TZ, so the launcher
# does not try to fire "at 07:15 Asia/Jerusalem". It ticks every five minutes
# and the API decides, in the schedule's own timezone (ZoneInfo, DST included),
# whether an occurrence is due; occurrence keys live in PostgreSQL, so a repeat
# tick, a concurrent tick, a restart or a missed hour create nothing twice and
# catch up within the schedule's catch-up window. The same tick re-drives runs
# that are waiting for a worker once the desktop worker has checked in.
#
# Crontab line (install once as ziv):
#   */5 * * * * /home/ziv/scripts/run-watched.sh tce-schedule-tick -- \
#       /home/ziv/team-content-engine/scripts/tce-schedule-tick.sh >/dev/null 2>&1
#
# Reads the private key and workspace from the app's own .env; never prints them.
set -uo pipefail

APP_DIR="${TCE_APP_DIR:-/home/ziv/team-content-engine}"
ENV_FILE="${TCE_ENV_FILE:-$APP_DIR/.env}"
API="${TCE_API_BASE:-http://127.0.0.1:8200}"
LOG="${TCE_TICK_LOG:-/home/ziv/logs/tce-schedule-tick.log}"
mkdir -p "$(dirname "$LOG")"

env_value() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }
KEY="$(env_value TCE_PRIVATE_ACCESS_KEY)"
WS="$(env_value TCE_EDITOR_DEFAULT_WORKSPACE_ID)"
if [ -z "$KEY" ] || [ -z "$WS" ]; then
  echo "$(date -u +%FT%TZ) tick: missing TCE_PRIVATE_ACCESS_KEY or TCE_EDITOR_DEFAULT_WORKSPACE_ID in $ENV_FILE" >>"$LOG"
  exit 1
fi

# Local disable switch shared with the watchdog: a paused box ticks nothing.
if [ -f /home/ziv/state/tce/disabled ]; then
  echo "$(date -u +%FT%TZ) tick: skipped, /home/ziv/state/tce/disabled present" >>"$LOG"
  exit 0
fi

BODY="$(mktemp)"
# -w prints 000 itself when the connection fails; no fallback echo, or the code doubles.
CODE="$(curl -s -o "$BODY" -w '%{http_code}' -m 60 -X POST "$API/api/v1/content-runs/schedule/tick" \
  -H "Authorization: Bearer $KEY" -H "X-Workspace-Id: $WS" -H "Content-Type: application/json" 2>/dev/null)"
CODE="${CODE:-000}"
SUMMARY="$(python3 - "$BODY" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"unreadable response: {e}"); raise SystemExit
occ = ", ".join(f"{o.get('schedule')}:{o.get('status')}:{o.get('occurrence_key')}" for o in d.get("occurrences", []))
red = ", ".join(f"{r['run_id'][:8]}@{r['stage']}" for r in d.get("redriven", []))
w = d.get("worker", {})
print(f"status={d.get('status')} occurrences=[{occ}] redriven=[{red}] worker_online={w.get('online')} ({w.get('detail')})")
PY
)"
rm -f "$BODY"
echo "$(date -u +%FT%TZ) tick: http=$CODE $SUMMARY" >>"$LOG"
[ "$CODE" = "200" ] || exit 1
exit 0
