#!/usr/bin/env bash
# 6d. ONE run of the nightly live-family tally over the 6c scored-trial
# store, mirroring mb-daily-run.sh: systemd's timer owns the cadence, this
# script owns only the work.
#
# I3 (docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md section 7): this
# wrapper no longer runs the covered-listed-station-days counter itself --
# score-live-trials-run.sh (14:15 UTC) writes the dated success marker and
# the counter's --output JSON; this wrapper only asserts the marker and
# READS that JSON for the v1 stop's two flags.
#
# AUD-05 fix-2 (SPLIT THE ARTEFACT, 2026-09-24): score-live-trials-run.sh
# now runs the counter TWICE, to two distinct paths -- this wrapper's own
# pre-existing path (`covered_listed_station_days_$STAMP.json`, v1-scoped:
# `pm_us_crh_v2.json`, fetch_start 2026-09-05, byte-for-byte unchanged from
# base commit 161cba8) and a NEW, separate champion-scoped path
# (`covered_listed_station_days_champion_$STAMP.json`) that
# family-tally-v2-run.sh's v4 instance and the 14:15 KILL clock read
# instead. This wrapper reads ONLY its own pre-existing path, below --
# never the champion-scoped one, regardless of which family is deployed.
#
# Exit status: 0 on a completed report; 1 if the analysis script failed, the
# 14:15 success marker is missing, the counter JSON is missing/unreadable,
# the JSON's fetch_start drifts from the registered v1 D0, the state-DB env
# var is unset, or the node-env pre-flight refuses (MISMATCH/
# DISCOVERY_FAILED). Reported to `systemctl --user status
# breezy-live-tally.service`.
#
# L-38 (`cbd5fec`, defect fix 2026-09-16): `score-live-trials-run.sh` now
# writes each REGISTERED family's rows to its OWN `$STORE_DIR/<family_id>/`
# subdirectory (family_tally_v2.py's contamination barrier forbids a shared
# top-level store) -- but `live_family_tally.py` (this wrapper's own
# analysis script) is v1-BINDING and PREREG-v1-frozen
# (`tests/unit/test_family_tally_v2.py::test_the_v1_tally_is_untouched`
# pins its bytes; "update only with a ruling"), and its reader is
# non-recursive, so pointing it straight at `$STORE_DIR` now silently reads
# zero rows whenever every family has migrated to its own subdirectory. This
# wrapper fixes that WITHOUT touching the frozen script: when `$STORE_DIR`
# has at least one subdirectory, it pools every subdirectory's (plus any
# legacy top-level) `scored_trials_*.parquet` files into a throwaway
# symlink directory and passes THAT to the unmodified CLI, then appends an
# additive "by family: ..." breakdown line to the report the CLI already
# wrote. When `$STORE_DIR` has no subdirectories (the pre-L-38 legacy
# layout), `$STORE_DIR` is passed straight through, unchanged from before
# this fix.
#
# Defect fix (measured 2026-09-16, live_tally.log): pooling EVERY
# subdirectory unconditionally means a non-v1 family (e.g. pm_us_crh_cont's
# v3 `continuous_rung_hold/trial/` trial_id prefix -- or kalshi_crh_v1's
# `kalshi:current_rung_hold/trial/`) lands rows the frozen
# `assert_live_only` refuses outright, failing the WHOLE run. Only a
# subdirectory whose manifest `trial_id_prefix` is accepted by the v1 tally
# (`current_rung_hold/trial/`) is now pooled; every other family
# subdirectory is skipped (and logged, and still listed with its FILE
# count -- explicitly labeled "files", never rows, since a skipped
# family's own row count is never computed here -- on the additive
# "by family:" line) rather than fatally refused or silently dropped.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_LIVE_TALLY_PYTHON:-$REPO/.venv/bin/python}"
# BLOCK-1: byte-identical to score-live-trials-run.sh's own assignment --
# one manifest literal, two wrappers, one test.
FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"
# Overridable so tests can enumerate a throwaway manifest directory instead
# of the deployed tree's -- mirrors family-tally-v2-run.sh's own
# BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR. The deployed default never changes:
# systemd always sees $REPO/deploy/families, exactly the manifests shipped
# there.
FAMILIES_DIR="${BREEZY_LIVE_TALLY_FAMILIES_DIR:-$REPO/deploy/families}"
STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/live_tally.log
# Drift guard: v1's own D0 (PREREG v1 section 6:130) is prose, never read
# from the manifest by the v1 python. If this wrapper's own (v1-scoped)
# counter JSON's fetch_start is not this date, refuse rather than silently
# re-window the v1 stop. The 14:15 KILL clock does not share this literal
# or this file: score-live-trials-run.sh writes it a SEPARATE,
# champion-scoped counter JSON (AUD-05 fix-2) and checks THAT file against
# the deployed champion manifest's own d0_climate_day and sha -- this
# wrapper never reads that second file.
V1_D0_LITERAL="2026-09-05"  # PREREG v1 §6:130

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

manifest_trial_id_prefix() {
  # Same grep/sed extraction shape as family-tally-v2-run.sh's own
  # manifest_family_id -- never $PY, so this never depends on the stubbed
  # analysis-script invocation. Prints nothing if the key or the file is
  # absent.
  grep -o '"trial_id_prefix"[[:space:]]*:[[:space:]]*"[^"]*"' "$1" 2>/dev/null | head -n1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
}

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

# L-38: pool every per-family subdirectory (plus any legacy top-level
# files) into a throwaway symlink directory, ONLY when $STORE_DIR actually
# has subdirectories -- see the module docstring above. A store with no
# subdirectories at all (legacy layout, or a fresh deployment) passes
# straight through unchanged, exactly as before this fix.
STORE_ARG="$STORE_DIR"
FAMILY_BREAKDOWN=""
SKIP_BREAKDOWN=""
POOL_DIR=""
if [ -d "$STORE_DIR" ] && find "$STORE_DIR" -mindepth 1 -maxdepth 1 -type d -print -quit 2>/dev/null | grep -q .; then
  POOL_DIR=$(mktemp -d)
  trap 'rm -rf "$POOL_DIR"' EXIT

  # Accepted prefix: the frozen module's own `_LIVE_TRIAL_ID_PREFIX` when
  # importable, else the v1 family manifest's own `trial_id_prefix`
  # (pm_us_crh_v2.json IS the v1 family, by construction -- byte-identical
  # to the constant in production). The import path is what a real `$PY`
  # exercises; every test here stubs `$PY` to a fake that knows nothing of
  # this call, so tests always exercise the manifest fallback.
  ACCEPTED_PREFIX=$("$PY" -c "
import sys
sys.path.insert(0, '$REPO')
from scripts.analysis.live_family_tally import _LIVE_TRIAL_ID_PREFIX
print(_LIVE_TRIAL_ID_PREFIX)
" 2>>"$LOG")
  if [ -z "$ACCEPTED_PREFIX" ]; then
    ACCEPTED_PREFIX=$(manifest_trial_id_prefix "$FAMILIES_DIR/pm_us_crh_v2.json")
  fi
  if [ -z "$ACCEPTED_PREFIX" ]; then
    say "LIVE TALLY FAILED -- could not determine the v1-accepted trial_id_prefix"
    exit 1
  fi

  pool_source() {
    # $1: directory to scan (non-recursive); $2: breakdown label.
    local src="$1" label="$2" n=0 f
    while IFS= read -r -d '' f; do
      if ! ln -s "$f" "$POOL_DIR/$(basename "$f")" 2>>"$LOG"; then
        say "LIVE TALLY FAILED -- duplicate scored-trial filename pooling $label: $(basename "$f")"
        exit 1
      fi
      n=$((n + 1))
    done < <(find "$src" -maxdepth 1 -type f -name 'scored_trials_*.parquet' -print0 2>/dev/null)
    if [ "$n" -gt 0 ]; then
      if [ -n "$FAMILY_BREAKDOWN" ]; then
        FAMILY_BREAKDOWN="$FAMILY_BREAKDOWN, $label=$n"
      else
        FAMILY_BREAKDOWN="$label=$n"
      fi
    fi
  }

  skip_source() {
    # $1: directory to scan (non-recursive, count only); $2: family id.
    # Never pooled -- the frozen v1 tally's assert_live_only would refuse
    # the WHOLE run on the first row whose trial_id carries a non-v1
    # prefix, so a mismatched family is counted and logged here instead.
    #
    # Defect fix (measured 2026-09-16, live_tally.log): this count is a
    # PARQUET FILE count (one `find`, non-recursive), never a row count --
    # a real tally's `row count:` line dedupes by trial_id via
    # `read_scored_trials`, so a skipped family with N files can report a
    # different row count in its own `family_tally_v2_<family>` output.
    # Labeling this "N (skipped)" reads as N rows and is misleading; label
    # it "N files (skipped; ...)" and point at the family's own row-count
    # report instead of silently implying this number is rows.
    local src="$1" fam="$2" n
    n=$(find "$src" -maxdepth 1 -type f -name 'scored_trials_*.parquet' 2>/dev/null | wc -l)
    if [ "$n" -gt 0 ]; then
      say "SKIP $fam: prefix not v1-live; see family_tally_v2_$fam"
      if [ -n "$SKIP_BREAKDOWN" ]; then
        SKIP_BREAKDOWN="$SKIP_BREAKDOWN, $fam=$n files (skipped; rows in family_tally_v2_$fam)"
      else
        SKIP_BREAKDOWN="$fam=$n files (skipped; rows in family_tally_v2_$fam)"
      fi
    fi
  }

  pool_source "$STORE_DIR" "(top-level)"
  while IFS= read -r -d '' fam_dir; do
    fam_id=$(basename "$fam_dir")
    fam_prefix=$(manifest_trial_id_prefix "$FAMILIES_DIR/$fam_id.json")
    case "$fam_prefix" in
      "$ACCEPTED_PREFIX"*)
        pool_source "$fam_dir" "$fam_id"
        ;;
      *)
        skip_source "$fam_dir" "$fam_id"
        ;;
    esac
  done < <(find "$STORE_DIR" -mindepth 1 -maxdepth 1 -type d -print0)

  STORE_ARG="$POOL_DIR"

  if [ -n "$SKIP_BREAKDOWN" ]; then
    if [ -n "$FAMILY_BREAKDOWN" ]; then
      FAMILY_BREAKDOWN="$FAMILY_BREAKDOWN, $SKIP_BREAKDOWN"
    else
      FAMILY_BREAKDOWN="$SKIP_BREAKDOWN"
    fi
  fi
fi

REPORT="$OUT/live_family_tally_$STAMP.md"
if "$PY" "$REPO/scripts/analysis/live_family_tally.py" \
     "$STORE_ARG" \
     --output "$REPORT" \
     --as-of "$STAMP" \
     --fill-source "$STATE_DB" \
     --fill-since-climate-day "$D0" \
     --covered-listed-station-days "$COUNT" >/dev/null 2>>"$LOG"; then
  say "live tally ok"
  # Additive only -- never touches the v1-frozen script's own report body,
  # just appends a breakdown line this wrapper computed independently.
  if [ -n "$FAMILY_BREAKDOWN" ] && [ -f "$REPORT" ]; then
    sed -i "/^row count:/a by family: $FAMILY_BREAKDOWN" "$REPORT"
  fi
else
  say "LIVE TALLY RUN FAILED (see stderr above in $LOG)"
  STATUS=1
fi

exit "$STATUS"
