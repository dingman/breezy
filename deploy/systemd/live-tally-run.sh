#!/usr/bin/env bash
# 6d. ONE run of the nightly live-family tally over the 6c scored-trial
# store, mirroring mb-daily-run.sh: systemd's timer owns the cadence, this
# script owns only the work.
#
# I3 (docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md section 7): this
# wrapper no longer runs the covered-listed-station-days counter itself --
# score-live-trials-run.sh (14:15 UTC) runs it exactly once and writes BOTH
# the dated success marker and the counter's --output JSON; this wrapper
# only asserts the marker and READS that JSON for the v1 stop's two flags.
#
# Exit status: 0 on a completed report; 1 if the analysis script failed, the
# 14:15 success marker is missing, the counter JSON is missing/unreadable,
# the JSON's fetch_start drifts from the registered v1 D0, the state-DB env
# var is unset, or the node-env pre-flight refuses (MISMATCH/
# DISCOVERY_FAILED). Reported to `systemctl --user status
# breezy-live-tally.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_LIVE_TALLY_PYTHON:-$REPO/.venv/bin/python}"
# BLOCK-1: byte-identical to score-live-trials-run.sh's own assignment --
# one manifest literal, two wrappers, one test.
FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"
STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/live_tally.log
# Drift guard: v1's own D0 (PREREG v1 section 6:130) is prose, never read
# from the manifest by the v1 python -- if a later v2 amendment ever moves
# the manifest's d0_climate_day, this wrapper must refuse rather than
# silently re-window the v1 stop. Byte-identical to
# score-live-trials-run.sh's own assignment.
V1_D0_LITERAL="2026-09-05"  # PREREG v1 §6:130

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

STAMP=$(date -u +%Y-%m-%d)
STATUS=0

if [ ! -f "$OUT/score_live_trials_ok_$STAMP" ]; then
  say "LIVE TALLY SKIPPED -- no score-live-trials success marker for $STAMP"
  exit 1
fi

CJSON="$OUT/covered_listed_station_days_$STAMP.json"
if [ ! -f "$CJSON" ]; then
  say "LIVE TALLY SKIPPED -- no covered-listed station-days JSON for $STAMP"
  exit 1
fi

# F3: refuse a malformed/incomplete counter JSON before extracting with
# sed -- a truncated file or one with duplicate matching lines must not be
# silently accepted just because it contains a line the pattern matches.
CJSON_FIRST_LINE=$(head -n1 "$CJSON")
CJSON_LAST_LINE=$(tail -n1 "$CJSON")
if [ "$CJSON_FIRST_LINE" != "{" ] || [ "$CJSON_LAST_LINE" != "}" ]; then
  say "LIVE TALLY SKIPPED -- counter JSON is not well-shaped (missing braces)"
  exit 1
fi
CJSON_COUNT_LINES=$(grep -cE '^  "count": [0-9]+,?$' "$CJSON")
CJSON_FETCH_START_LINES=$(grep -cE '^  "fetch_start": "[0-9]{4}-[0-9]{2}-[0-9]{2}",?$' "$CJSON")
if [ "$CJSON_COUNT_LINES" -ne 1 ] || [ "$CJSON_FETCH_START_LINES" -ne 1 ]; then
  say "LIVE TALLY SKIPPED -- counter JSON count/fetch_start not exactly one line each"
  exit 1
fi

COUNT=$(sed -nE 's/^  "count": ([0-9]+),?$/\1/p' "$CJSON")
D0=$(sed -nE 's/^  "fetch_start": "([0-9]{4}-[0-9]{2}-[0-9]{2})",?$/\1/p' "$CJSON")

if [ -z "$COUNT" ] || [ -z "$D0" ]; then
  say "LIVE TALLY SKIPPED -- could not extract count/fetch_start from $CJSON"
  exit 1
fi

if [ "$D0" != "$V1_D0_LITERAL" ]; then
  say "LIVE TALLY SKIPPED -- counter fetch_start drifted from the registered v1 D0"
  exit 1
fi

STATE_DB="${POLYMARKET_US_EXEC_STATE_DB:?POLYMARKET_US_EXEC_STATE_DB is required}"

if ! CHECK_TOKEN=$("$PY" -m breezy.runtime.exec_state_db_path --check 2>>"$LOG"); then
  say "LIVE TALLY SKIPPED -- node-env pre-flight refused (mismatch or discovery failed)"
  exit 1
fi
if [ "$CHECK_TOKEN" = "NO_NODE" ]; then
  say "WARN: node-env pre-flight found no anchored breezy-trade process"
fi

if "$PY" "$REPO/scripts/analysis/live_family_tally.py" \
     "$STORE_DIR" \
     --output "$OUT/live_family_tally_$STAMP.md" \
     --as-of "$STAMP" \
     --fill-source "$STATE_DB" \
     --fill-since-climate-day "$D0" \
     --covered-listed-station-days "$COUNT" >/dev/null 2>>"$LOG"; then
  say "live tally ok"
else
  say "LIVE TALLY RUN FAILED (see stderr above in $LOG)"
  STATUS=1
fi

exit "$STATUS"
