#!/usr/bin/env bash
# G-14-style daily driver for M_A (ma_prelock_winner_ask_study.py) and M_B
# (mb_current_rung_edge_study.py), the two remaining tape-side measurements.
#
# This is the loop BODY, mirroring k1-daily-run.sh: systemd's timer owns the
# cadence (breezy-mb-daily.timer), this script owns only the work.
#
# ORDER AND FAILURE ISOLATION: M_A runs, then M_B runs UNCONDITIONALLY -- a
# failed or cache-starved M_A must never skip M_B's own daily sample. Each
# `if` block below reports its own outcome and the overall exit status is the
# OR of both, never a short-circuit.
#
# ASOS REFRESH FIRST, PINNED TO THE STUDIES' OWN ANCHOR: `--since` is set to
# the exact literal `ma_prelock_winner_ask_study.ASOS_FETCH_START` value, so
# `asos_recent_refresh.py`'s fetch (via `lookback_days_since`) requests the
# byte-identical URL that `load_asos_series_for_day`'s cache-only,
# raise-on-miss read requires (both scripts import `ASOS_FETCH_START` /
# `ASOS_FETCH_END` from the ma module; `ASOS_FETCH_END` now defaults to
# `default_asos_fetch_end()` = today, matching the refresh's own `today`
# anchor exactly). If `ASOS_FETCH_START` ever moves in that module, this
# literal must move with it -- there is no shared import across the
# process boundary between a shell unit and the Python constant.
# Best-effort ("|| true" via the `if`): a fetch shortfall for one or more
# sites is diagnostic (logged by the refresh script itself), never fatal --
# both studies still run on whatever is cached and report PENDING for
# whatever a station-day is missing a final CLI or ASOS coverage for.
#
# Exit status: 0 if BOTH measurements completed; 1 if either failed. Reported
# to `systemctl --user status breezy-mb-daily.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="$REPO/.venv/bin/python"
OUT=${BREEZY_MB_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/mb_daily.log
# ma_prelock_winner_ask_study.py:ASOS_FETCH_START -- fixed anchor, update both
# together if it ever changes.
ASOS_FETCH_START_ANCHOR=2026-08-30

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

STAMP=$(date -u +%Y-%m-%d)
STATUS=0

if "$PY" "$REPO/scripts/analysis/asos_recent_refresh.py" \
     --since "$ASOS_FETCH_START_ANCHOR" >/dev/null 2>>"$LOG"; then
  say "asos refresh ok"
else
  say "asos refresh reported a shortfall (see log above) -- continuing on whatever is cached"
fi

if "$PY" "$REPO/scripts/analysis/ma_prelock_winner_ask_study.py" \
     --output "$OUT/ma_prelock_winner_ask_$STAMP.md" >/dev/null 2>>"$LOG"; then
  say "M_A ok"
else
  say "M_A RUN FAILED (see stderr above in $LOG)"
  STATUS=1
fi

if "$PY" "$REPO/scripts/analysis/mb_current_rung_edge_study.py" \
     --output "$OUT/mb_current_rung_edge_$STAMP.md" >/dev/null 2>>"$LOG"; then
  say "M_B ok"
else
  say "M_B RUN FAILED (see stderr above in $LOG)"
  STATUS=1
fi

exit "$STATUS"
