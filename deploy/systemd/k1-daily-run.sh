#!/usr/bin/env bash
# G-14. ONE run of the K1 cheap-open D+1 settlement measurement.
#
# This is the loop BODY of the stopgap /tmp driver `k1_daily.sh`, with the
# `while`/`sleep 86400` removed: systemd's timer owns the cadence, so the
# script owns only the work. The `timeout 1800` is likewise removed -- the
# unit's TimeoutStartSec enforces it, and two competing timeouts is one
# policy too many.
#
# Writes OUTSIDE the repo so the committed evidence file is never churned; a
# dated snapshot is kept per run and a one-line summary appended to the log.
# Regenerate the committed doc deliberately when the verdict changes.
#
# Exit status: 0 on a completed measurement, 1 if the analysis script failed.
# The unit reports that to `systemctl --user status breezy-k1-daily.service`.
set -uo pipefail

REPO=/home/jon/breezy
OUT=${BREEZY_K1_OUTPUT_DIR:-$HOME/.local/share/breezy/k1}
LOG=$OUT/k1_daily.log

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

STAMP=$(date -u +%Y-%m-%d)
SNAP="$OUT/k1_$STAMP.md"

if "$REPO/.venv/bin/python" "$REPO/scripts/analysis/k1_cheap_open_settlement.py" \
     --output "$SNAP" >/dev/null 2>>"$LOG"; then
  POP=$(grep -m1 'MEASURED POPULATION' "$SNAP" 2>/dev/null | tr -dc '0-9')
  VERD=$(grep -A2 -m1 '^## 6. VERDICT' "$SNAP" 2>/dev/null | grep -m1 '^\*\*' | tr -d '*')
  say "n=${POP:-?} verdict=${VERD:-unparsed}"
  case "$VERD" in
    *UNDERPOWERED*|"") : ;;
    *) say "!!! K1 HAS REPORTED A DECISIVE VERDICT: $VERD -- snapshot $SNAP" ;;
  esac
  exit 0
fi

say "K1 RUN FAILED (see stderr above in $LOG)"
exit 1
