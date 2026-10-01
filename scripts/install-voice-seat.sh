#!/bin/bash
# Put the TCE call seat (deploy/voice-seat) where the voice service reads it.
#
# 27-Sep: the repo's seat allowed 15 tools, the live seat 13. tce_find_ideas and
# tce_new_idea were built, tested and deployed, but no step ever copied the seat,
# so on a real call TCE said "I can't run that here" when Ziv asked for new topics.
# deploy-restart.sh runs this on every deploy; it is safe to run any time.
#
# 1-Oct (talk to the editor): the seat's contexts are synced too, or the "video"
# context never reaches the box and the same drift happens again. The repo's
# tce.json owns every context kind it names (default, week, topic, video); a kind
# only the live seat has is kept and named, never deleted.
#
# A seat the voice service refuses is dropped from the file whole, and then every
# TCE call fails. So the new seat is checked first, by the same rules the service
# applies (KM BOT bin/kmbot-voice-seats.mjs validateSeat), and then by that module
# itself when it is on this box. Nothing is written unless both pass, and the live
# file is replaced in one rename, with a dated copy of the old one kept beside it.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SEATS=/etc/kmbot/voice-seats.json
BRIEF=/etc/kmbot/seats/tce-brief.md
KMBOT_SEATS_JS=/opt/kmbot/bin/kmbot-voice-seats.mjs

if [ ! -f "$SEATS" ]; then
  echo "[voice-seat] no $SEATS on this box; nothing to install"
  exit 0
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
cand="$SEATS.candidate-$stamp"

# Exit 0: a new seat file is written to the candidate path. 3: already current,
# nothing written. 2: refused, nothing written. tests/unit/test_mcp_voice_tools.py
# runs this exact block against copies of the live file.
set +e
sudo python3 - "$SEATS" "$REPO/deploy/voice-seat/tce.json" "$cand" <<'PY'
import json
import os
import re
import sys

# The voice service's rules for a seat's tools and contexts (KM BOT
# bin/kmbot-voice-seats.mjs, validateSeat).
KIND = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
TOOL = re.compile(r"^mcp__([a-z][a-z0-9_]{0,31})__([A-Za-z0-9_-]{1,64})$")
MAX_TOOLS = 64
MAX_TEXT = 2000


def problems(entry, tools, contexts):
    out = []
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        out.append(f"allowedTools must be a list of at most {MAX_TOOLS}")
        tools = []
    servers = entry.get("mcpServers") or {}
    for n, tool in enumerate(tools, 1):
        m = TOOL.match(tool) if isinstance(tool, str) else None
        if not m:
            out.append(f"allowedTools entry {n} is not an mcp__<server>__<tool> name")
        elif m.group(1) not in servers:
            out.append(f"allowedTools entry {n} names a server the live seat does not define")
    if not isinstance(contexts, dict):
        out.append("contexts must be an object of kinds")
        return out
    for kind, text in contexts.items():
        if not (kind == "default" or KIND.match(kind)):
            out.append(f"context {kind!r} has a kind that is not a short lowercase word")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            out.append(f"context {kind!r} must be text of at most {MAX_TEXT} characters")
    return out


seats_path, repo_path, out_path = sys.argv[1:4]
with open(seats_path) as f:
    seats = json.load(f)
with open(repo_path) as f:
    repo = json.load(f)
listed = seats if isinstance(seats, list) else (seats or {}).get("seats") or []
entry = next((s for s in listed if isinstance(s, dict) and s.get("id") == "tce"), None)
if entry is None:
    print("[voice-seat] REFUSED, nothing written: the seat file has no tce seat")
    sys.exit(2)
want_tools = repo.get("allowedTools")
want_ctx = repo.get("contexts") or {}
bad = problems(entry, want_tools, want_ctx)
if bad:
    for why in bad:
        print(f"[voice-seat] REFUSED, nothing written: {why}")
    sys.exit(2)

before_tools = entry.get("allowedTools") or []
before_ctx = entry.get("contexts") or {}
merged = dict(before_ctx)
merged.update(want_ctx)
if before_tools == want_tools and merged == before_ctx:
    print(f"[voice-seat] tools ({len(want_tools)}) and contexts ({', '.join(merged)}) already current")
    sys.exit(3)

entry["allowedTools"] = want_tools
entry["contexts"] = merged
with open(out_path, "w") as f:
    json.dump(seats, f, indent=2)
os.chmod(out_path, 0o644)

if before_tools == want_tools:
    print(f"[voice-seat] tools already current ({len(want_tools)})")
else:
    added = sorted(set(want_tools) - set(before_tools))
    removed = sorted(set(before_tools) - set(want_tools))
    print(f"[voice-seat] tools {len(before_tools)} -> {len(want_tools)}; added {added}; removed {removed}")
new = sorted(set(want_ctx) - set(before_ctx))
changed = sorted(k for k in want_ctx if k in before_ctx and before_ctx[k] != want_ctx[k])
kept = sorted(set(before_ctx) - set(want_ctx))
print(f"[voice-seat] contexts: added {new}; changed {changed}; kept as they are on this box {kept}")
sys.exit(0)
PY
rc=$?
set -e

# The voice service's own check, run on the candidate before it goes live. Exit 2
# means it would refuse the seat; anything else but 0 means it could not run here.
NODE_CHECK='
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const [, mod, file] = process.argv;
let seats;
try { seats = await import(pathToFileURL(mod).href); }
catch (e) { console.log(`could not load it: ${e.message}`); process.exit(4); }
const loaded = seats.loadSeats(file);
const seat = loaded.seats.get("tce");
if (!seat) { console.log(`it would leave out the tce seat: ${loaded.errors.join("; ") || "no reason given"}`); process.exit(2); }
const doc = JSON.parse(fs.readFileSync(file, "utf8"));
const raw = (Array.isArray(doc) ? doc : doc.seats).find((s) => s && s.id === "tce");
const missing = Object.keys(raw.contexts || {}).filter((k) => !Object.hasOwn(seat.contexts, k));
if (missing.length) { console.log(`it would leave out the contexts ${missing.join(", ")}`); process.exit(2); }
console.log(`it loads the tce seat with ${seat.allowedTools.length} tools and the contexts ${Object.keys(seat.contexts).join(", ")}`);
'

if [ "$rc" -eq 3 ]; then
  :
elif [ "$rc" -ne 0 ]; then
  sudo rm -f "$cand"
  echo "[voice-seat] the seat was NOT changed; the live one is untouched"
  exit 1
else
  if [ -f "$KMBOT_SEATS_JS" ] && command -v node >/dev/null 2>&1; then
    set +e
    verdict=$(node --input-type=module -e "$NODE_CHECK" "$KMBOT_SEATS_JS" "$cand" 2>&1)
    vrc=$?
    set -e
    if [ "$vrc" -eq 0 ]; then
      echo "[voice-seat] the voice service's own check passed: $verdict"
    elif [ "$vrc" -eq 2 ]; then
      sudo rm -f "$cand"
      echo "[voice-seat] REFUSED by the voice service's own check, nothing written: $verdict"
      echo "[voice-seat] the seat was NOT changed; the live one is untouched"
      exit 1
    else
      echo "[voice-seat] the voice service's own check could not run ($verdict); the repo's checks passed"
    fi
  else
    echo "[voice-seat] no $KMBOT_SEATS_JS on this box to check against; the repo's checks passed"
  fi
  sudo cp -p "$SEATS" "$SEATS.bak-$stamp"
  sudo mv -f "$cand" "$SEATS"
  echo "[voice-seat] installed; the previous seat file is $SEATS.bak-$stamp"
fi

if ! sudo cmp -s "$REPO/deploy/voice-seat/tce-brief.md" "$BRIEF"; then
  sudo cp -p "$BRIEF" "$BRIEF.bak-$stamp"
  sudo install -m 644 -o ziv -g ziv "$REPO/deploy/voice-seat/tce-brief.md" "$BRIEF"
  echo "[voice-seat] brief updated"
else
  echo "[voice-seat] brief already current"
fi
# The voice service re-reads the seats on every call: no restart needed.
