#!/bin/bash
# Delete raw videos/ + transcriptions/ subdirs from InstaIQ output runs
# that have already produced their 6 deliverables. Keeps deliverables
# (a few MB of markdown/JSON) so the TCE import + writer prompt still
# works, discards the multi-GB raw MP4s that are re-fetchable by
# re-running InstaIQ.
#
# Run this via cron on the VPS, or manually after a scraping session:
#   bash /home/ziv/team-content-engine/scripts/cleanup-instaiq-videos.sh
#
# Safe to run repeatedly - skips any run that's missing deliverable_6
# (i.e. still in progress). Never touches the most recent run per handle
# (safety net so the most recent scrape survives for re-analysis).

set -euo pipefail

INSTAIQ_OUTPUT="${INSTAIQ_OUTPUT:-/opt/instaiq/output}"
DRY_RUN="${DRY_RUN:-0}"

if [ ! -d "$INSTAIQ_OUTPUT" ]; then
  echo "[cleanup-instaiq] $INSTAIQ_OUTPUT does not exist, nothing to do"
  exit 0
fi

freed_bytes=0
kept_count=0
cleaned_count=0
skipped_count=0

# Group runs by handle. Directory names are like: <handle>_<YYYYMMDD_HHMMSS>
# Keep the newest run per handle, clean videos/ from older runs IF they
# have deliverable_6 (proof the run finished).

declare -A newest_per_handle

for rundir in "$INSTAIQ_OUTPUT"/*/; do
  [ -d "$rundir" ] || continue
  runname=$(basename "$rundir")
  # Handle is everything before the _YYYYMMDD_HHMMSS suffix
  handle=$(echo "$runname" | sed -E 's/_[0-9]{8}_[0-9]{6}$//')
  # Timestamp for sorting (YYYYMMDD_HHMMSS)
  ts=$(echo "$runname" | grep -oE '[0-9]{8}_[0-9]{6}$' || true)
  [ -n "$ts" ] || continue

  current=${newest_per_handle[$handle]:-}
  if [ -z "$current" ] || [ "$ts" \> "${current##*|}" ]; then
    newest_per_handle[$handle]="$rundir|$ts"
  fi
done

for rundir in "$INSTAIQ_OUTPUT"/*/; do
  [ -d "$rundir" ] || continue
  runname=$(basename "$rundir")
  handle=$(echo "$runname" | sed -E 's/_[0-9]{8}_[0-9]{6}$//')
  videos="$rundir/videos"
  transcriptions="$rundir/transcriptions"
  deliv6="$rundir/deliverable_6_content_plan.md"

  # Rule 1: never touch the newest run per handle
  newest=${newest_per_handle[$handle]:-}
  newest_dir="${newest%|*}"
  if [ "$rundir" = "$newest_dir" ]; then
    kept_count=$((kept_count + 1))
    continue
  fi

  # Rule 2: only clean runs that finished (deliverable_6 exists)
  if [ ! -f "$deliv6" ]; then
    skipped_count=$((skipped_count + 1))
    continue
  fi

  # Rule 3: only clean if there's actually something to free
  if [ ! -d "$videos" ] && [ ! -d "$transcriptions" ]; then
    continue
  fi

  size=$(du -sb "$videos" "$transcriptions" 2>/dev/null | awk '{s += $1} END {print s+0}')
  echo "[cleanup-instaiq] Cleaning $runname (would free $((size / 1024 / 1024)) MB)"

  if [ "$DRY_RUN" = "1" ]; then
    echo "  (dry-run, not deleting)"
  else
    rm -rf "$videos" "$transcriptions"
  fi

  freed_bytes=$((freed_bytes + size))
  cleaned_count=$((cleaned_count + 1))
done

echo ""
echo "[cleanup-instaiq] Summary:"
echo "  Cleaned:  $cleaned_count runs ($((freed_bytes / 1024 / 1024)) MB freed)"
echo "  Kept:     $kept_count runs (newest per handle)"
echo "  Skipped:  $skipped_count runs (no deliverable_6 - still in progress)"
if [ "$DRY_RUN" = "1" ]; then
  echo "  NOTE: DRY_RUN=1 - no files were deleted. Re-run with DRY_RUN=0 to apply."
fi
