#!/bin/bash
# TCE watchdog: keeps the TCE API (pm2 "tce") and its database container alive.
#
# Runs from cron, NOT from pm2, so it survives the failure that took TCE down on
# 2026-09-18: the whole pm2 daemon was restarted from a dump that did not contain
# "tce", and nothing noticed for a day and a half.
#
#   */5 * * * * /home/ziv/scripts/run-watched.sh tce-watchdog -- \
#       /home/ziv/team-content-engine/scripts/tce-watchdog.sh >/dev/null 2>&1
#
# Surgical: it only touches the "tce" pm2 entry and the tce-db container.
#   - tce-db not running           -> docker start tce-db
#   - pm2 "tce" missing            -> register it (kill_timeout 15000) and pm2 save
#   - pm2 "tce" not online         -> start it
#   - health fails twice in a row  -> deploy-restart.sh (clears a stuck :8200)
# Every run writes $STATE/status.json. It exits 1 when it had to repair or could
# not repair, so run-watched.sh records it and alerts; a quiet run exits 0.
#
# Deliberately stopped? Create $STATE/disabled (a rollback that stops TCE must
# create it). The watchdog then only records "disabled" and changes nothing.
set -uo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

APP_DIR="/home/ziv/team-content-engine"
STATE="/home/ziv/state/tce"
HEALTH="http://127.0.0.1:8200/api/v1/health"
LOG="/home/ziv/logs/tce-watchdog.log"
mkdir -p "$STATE" "$(dirname "$LOG")"

ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
say() { echo "$(ts) $*" >> "$LOG"; }
actions=()
problems=()

write_status() { # state
  python3 - "$STATE/status.json" "$1" "$(ts)" "${actions[*]:-}" "${problems[*]:-}" <<'PY'
import json, sys
path, state, at, actions, problems = sys.argv[1:6]
json.dump({"state": state, "checked_at": at,
           "actions": [a for a in actions.split(" ") if a],
           "problems": [p for p in problems.split(" ") if p]},
          open(path, "w"), indent=2)
PY
}

if [ -f "$STATE/disabled" ]; then
  write_status disabled
  exit 0
fi

# 1. database container
db_state=$(docker inspect -f '{{.State.Status}}' tce-db 2>/dev/null || echo missing)
if [ "$db_state" != "running" ]; then
  say "tce-db is $db_state; starting it"
  if docker start tce-db >/dev/null 2>&1; then actions+=("started_tce_db")
  else problems+=("tce_db_${db_state}_start_failed"); fi
  sleep 5
fi

# 2. pm2 entry
pm2_state=$(pm2 jlist 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print('PARSE_FAIL'); sys.exit()
p=next((x for x in d if x.get('name')=='tce'),None)
print('MISSING' if p is None else p.get('pm2_env',{}).get('status','UNKNOWN'))
")
case "$pm2_state" in
  online) ;;
  MISSING)
    say "pm2 tce missing; registering"
    if pm2 start "$APP_DIR/start.sh" --name tce --kill-timeout 15000 --cwd "$APP_DIR" >/dev/null 2>&1; then
      pm2 save >/dev/null 2>&1
      actions+=("registered_pm2_tce_and_saved")
    else
      problems+=("pm2_register_failed")
    fi
    sleep 10 ;;
  PARSE_FAIL)
    problems+=("pm2_jlist_unreadable") ;;
  *)
    say "pm2 tce is $pm2_state; starting"
    if pm2 start tce >/dev/null 2>&1; then actions+=("started_pm2_tce_from_${pm2_state}")
    else problems+=("pm2_start_failed"); fi
    sleep 10 ;;
esac

# 3. health (two consecutive failures before a restart; one blip is not an outage)
if curl -s --max-time 10 -o /dev/null -w '%{http_code}' "$HEALTH" | grep -q '^200$'; then
  rm -f "$STATE/health_fail"
else
  if [ -f "$STATE/health_fail" ]; then
    say "health failed twice; deploy-restart"
    if (cd "$APP_DIR" && bash scripts/deploy-restart.sh >> "$LOG" 2>&1); then
      actions+=("restarted_after_health_failures")
    else
      problems+=("restart_failed")
    fi
    rm -f "$STATE/health_fail"
    sleep 10
    curl -s --max-time 10 -o /dev/null -w '%{http_code}' "$HEALTH" | grep -q '^200$' \
      || problems+=("unhealthy_after_restart")
  else
    touch "$STATE/health_fail"
    problems+=("health_failed_once")
  fi
fi

if [ ${#problems[@]} -eq 0 ] && [ ${#actions[@]} -eq 0 ]; then
  write_status ok
  exit 0
fi
say "actions=[${actions[*]:-}] problems=[${problems[*]:-}]"
if [ ${#problems[@]} -eq 1 ] && [ "${problems[0]}" = "health_failed_once" ] && [ ${#actions[@]} -eq 0 ]; then
  write_status watching
  exit 0
fi
write_status repaired_or_failing
exit 1
