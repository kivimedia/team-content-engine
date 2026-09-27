#!/bin/bash
# Put the TCE call seat (deploy/voice-seat) where the voice service reads it.
#
# 27-Sep: the repo's seat allowed 15 tools, the live seat 13. tce_find_ideas and
# tce_new_idea were built, tested and deployed, but no step ever copied the seat,
# so on a real call TCE said "I can't run that here" when Ziv asked for new topics.
# deploy-restart.sh runs this on every deploy; it is safe to run any time.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SEATS=/etc/kmbot/voice-seats.json
BRIEF=/etc/kmbot/seats/tce-brief.md

if [ ! -f "$SEATS" ]; then
  echo "[voice-seat] no $SEATS on this box; nothing to install"
  exit 0
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo cp -p "$SEATS" "$SEATS.bak-$stamp"
sudo python3 - "$SEATS" "$REPO/deploy/voice-seat/tce.json" <<'PY'
import json, sys
seats_path, repo_path = sys.argv[1], sys.argv[2]
seats = json.load(open(seats_path))
want = json.load(open(repo_path))["allowedTools"]
entry = next(s for s in seats["seats"] if s.get("id") == "tce")
before = entry.get("allowedTools") or []
if before == want:
    print(f"[voice-seat] tools already current ({len(want)})")
else:
    entry["allowedTools"] = want
    tmp = seats_path + ".tmp"
    json.dump(seats, open(tmp, "w"), indent=2)
    import os
    os.chmod(tmp, 0o644)
    os.replace(tmp, seats_path)
    added = sorted(set(want) - set(before))
    removed = sorted(set(before) - set(want))
    print(f"[voice-seat] tools {len(before)} -> {len(want)}; added {added}; removed {removed}")
PY

if ! sudo cmp -s "$REPO/deploy/voice-seat/tce-brief.md" "$BRIEF"; then
  sudo cp -p "$BRIEF" "$BRIEF.bak-$stamp"
  sudo install -m 644 -o ziv -g ziv "$REPO/deploy/voice-seat/tce-brief.md" "$BRIEF"
  echo "[voice-seat] brief updated"
else
  echo "[voice-seat] brief already current"
fi
# The voice service re-reads the seats on every call: no restart needed.
