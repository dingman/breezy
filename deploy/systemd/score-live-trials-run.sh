#!/usr/bin/env bash
# I3 (docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md section 3.0/I3/section
# 7). ONE run of the 14:15 UTC live-fill scorer: the node-env pre-flight,
# then the covered-listed-station-days counter (run ONCE, here, per section
# 7's build-time disposition -- NOT by live-tally-run.sh), then one
# `score_live_trials.py` invocation per manifest station. The dated success
# marker `score_live_trials_ok_$STAMP` is the ONE thing both 14:30 and 15:30
# tally wrappers assert before running (BLOCK-2): this script is its SOLE
# writer, and only after the counter AND every city's scorer invocation
# exited 0.
#
# Exit status: 0 only when the marker was written; 1 if the state-DB env
# var is unset, the node-env pre-flight refuses (MISMATCH/DISCOVERY_FAILED),
# the counter fails, its JSON is malformed/unreadable, its fetch_start
# drifts from the registered v1 D0, or any city's scorer invocation fails --
# remaining cities are still attempted so the journal shows every failure.
# Reported to `systemctl --user status breezy-score-live-trials.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_SCORE_LIVE_TRIALS_PYTHON:-$REPO/.venv/bin/python}"
# BLOCK-1: byte-identical to live-tally-run.sh's own assignment -- one
# manifest literal, two wrappers, one test. Reaches three consumers: this
# loop's cities, every scorer invocation's --family-manifest, and the
# counter's --family-manifest.
FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"
STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/score_live_trials.log
# DEFAULT_QUOTE_TAPE_CATALOG (ma_prelock_winner_ask_study.py) -- the same
# quote-tape catalog root breezy-quote-tape(-ingest).service already write
# under this exact env var name.
CATALOG_ROOT=${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us}
# Drift guard: byte-identical to live-tally-run.sh's own assignment.
V1_D0_LITERAL="2026-09-05"  # PREREG v1 §6:130

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

STAMP=$(date -u +%Y-%m-%d)
STATUS=0

STATE_DB="${POLYMARKET_US_EXEC_STATE_DB:?POLYMARKET_US_EXEC_STATE_DB is required}"

if ! CHECK_TOKEN=$("$PY" -m breezy.runtime.exec_state_db_path --check 2>>"$LOG"); then
  say "SCORE LIVE TRIALS SKIPPED -- node-env pre-flight refused (mismatch or discovery failed)"
  exit 1
fi
if [ "$CHECK_TOKEN" = "NO_NODE" ]; then
  say "WARN: node-env pre-flight found no anchored breezy-trade process"
fi

CJSON="$OUT/covered_listed_station_days_$STAMP.json"
if ! "$PY" "$REPO/scripts/analysis/structural_dead_stop.py" \
     --catalog-root "$CATALOG_ROOT" \
     --family-manifest "$FAMILY_MANIFEST" \
     --output "$CJSON" >>"$LOG" 2>&1; then
  say "SCORE LIVE TRIALS SKIPPED -- covered-listed station-days counter FAILED"
  exit 1
fi

FETCH_START=$(sed -nE 's/^  "fetch_start": "([0-9]{4}-[0-9]{2}-[0-9]{2})",?$/\1/p' "$CJSON")
if [ -z "$FETCH_START" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- counter output missing fetch_start"
  exit 1
fi
if [ "$FETCH_START" != "$V1_D0_LITERAL" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- counter fetch_start drifted from the registered v1 D0"
  exit 1
fi

STATIONS=$(sed -nE 's/^    "([A-Z]{3,4})",?$/\1/p' "$CJSON")
if [ -z "$STATIONS" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- counter output has no stations"
  exit 1
fi

for CITY in $STATIONS; do
  if "$PY" "$REPO/scripts/analysis/score_live_trials.py" \
       --city "$CITY" \
       --family-manifest "$FAMILY_MANIFEST" \
       --derived-dir "$STORE_DIR" >>"$LOG" 2>&1; then
    say "scorer ok for city $CITY"
  else
    say "SCORER FAILED for city $CITY"
    STATUS=1
  fi
done

if [ "$STATUS" -eq 0 ]; then
  : > "$OUT/score_live_trials_ok_$STAMP"
  say "score-live-trials ok"
fi

exit "$STATUS"
