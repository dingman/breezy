#!/usr/bin/env bash
# 6d. ONE run of the nightly live-family tally over the 6c scored-trial
# store, mirroring mb-daily-run.sh: systemd's timer owns the cadence, this
# script owns only the work.
#
# Exit status: 0 on a completed report, 1 if the analysis script failed.
# Reported to `systemctl --user status breezy-live-tally.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="$REPO/.venv/bin/python"
STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/live_tally.log

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

STAMP=$(date -u +%Y-%m-%d)
STATUS=0

if "$PY" "$REPO/scripts/analysis/live_family_tally.py" \
     "$STORE_DIR" \
     --output "$OUT/live_family_tally_$STAMP.md" \
     --as-of "$STAMP" >/dev/null 2>>"$LOG"; then
  say "live tally ok"
else
  say "LIVE TALLY RUN FAILED (see stderr above in $LOG)"
  STATUS=1
fi

exit "$STATUS"
