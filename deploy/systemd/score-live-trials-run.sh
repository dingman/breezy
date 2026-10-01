#!/usr/bin/env bash
# I3 (docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md section 3.0/I3/section
# 7). ONE run of the 14:15 UTC live-fill scorer: the node-env pre-flight,
# then the covered-listed-station-days counter, then one
# `score_live_trials.py` invocation per (manifest station, REGISTERED
# family manifest) pair. The dated success marker
# `score_live_trials_ok_$STAMP` is the ONE thing both 14:30 and 17:15 tally
# wrappers assert before running (BLOCK-2): this script is its SOLE writer,
# and only after BOTH counters AND every city/family scorer invocation
# exited 0.
#
# AUD-05 fix-2 (SPLIT THE ARTEFACT, 2026-09-24): the counter now runs
# TWICE, to two distinct paths, because it has two distinct consumers with
# incompatible scopes:
#   - the PRE-EXISTING path ($CJSON, `covered_listed_station_days_$STAMP.json`)
#     is produced against the v1-registered `pm_us_crh_v2.json` manifest,
#     byte-for-byte the same semantics this wrapper had on base commit
#     161cba8 (fetch_start 2026-09-05, no sha guard) -- this is what
#     `live-tally-run.sh` (the 14:30 v1 PREREG stop, R-5: OPEN, may not be
#     retired/re-windowed) and this wrapper's own STATIONS/scorer loop
#     below still read.
#   - the NEW path ($CJSON_CHAMPION,
#     `covered_listed_station_days_champion_$STAMP.json`) is produced
#     against the DEPLOYED sending family's manifest, resolved from
#     `breezy-trade-supervisor.service`'s `BREEZY_SENDING_FAMILY_ID` (INC-
#     SP1I5) -- this is what `family-tally-v2-run.sh`'s v4 instance and the
#     14:15 KILL clock read.
# Before this split, both consumers shared ONE path: moving that path onto
# the champion's scope (fetch_start 2026-09-20) fixed the KILL clock but
# made the v1 wrapper's drift guard refuse every day (a daily false page,
# since v1's D0 is pinned to 2026-09-05 and is never re-windowed). Running
# the counter twice costs one extra `structural_dead_stop.py` invocation
# per day (measured; see the fix's evidence note) -- cheap next to a daily
# false page on a live alert path.
#
# L-38 (2026-09-16): before that fix, only `pm_us_crh_v2.json` was ever
# scored, so every fill under a DIFFERENT family's trial-id prefix (e.g. the
# live `pm_us_crh_cont` family, `continuous_rung_hold/trial/`) came back
# `no_taken_latch` -- the family's own genuine taken latch was real, just
# never looked up under the right prefix. The fix: enumerate every
# REGISTERED, `venue == polymarket_us` family manifest under
# `deploy/families/*.json` (never a second hardcoded literal for THIS loop)
# and run the scorer once per (city, manifest) pair, each family's rows
# landing in its OWN `$STORE_DIR/<family_id>` subdirectory --
# `family_tally_v2.py`'s `filter_rows_to_manifest_prefix` REFUSES a store
# that mixes another family's rows into a store declared single-family
# (`FamilyStoreContaminationError`), so a shared top-level directory would
# make one family's tally poison the other's. A manifest that is
# `DRAFT_NOT_REGISTERED` (or a non-`polymarket_us` venue, e.g.
# `kalshi_crh_v1.json`) is skipped with a logged reason, never invoked.
#
# Exit status: 0 only when the marker was written; 1 if the state-DB env
# var is unset, the node-env pre-flight refuses (MISMATCH/DISCOVERY_FAILED),
# either counter fails, either counter's JSON is malformed/unreadable, the
# v1 counter's fetch_start drifts from the registered v1 D0, the champion
# counter's fetch_start or manifest_sha256 drifts from the resolved
# champion manifest, or any city/family scorer invocation fails --
# remaining (city, family) pairs are still attempted so the journal shows
# every failure.
# Reported to `systemctl --user status breezy-score-live-trials.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_SCORE_LIVE_TRIALS_PYTHON:-$REPO/.venv/bin/python}"
# AUD-05 fix-2 (SPLIT THE ARTEFACT): byte-identical to live-tally-run.sh's
# own assignment -- the v1-scoped counter's manifest, never re-windowed.
# The CHAMPION-scoped counter's manifest is resolved separately, below,
# from BREEZY_SENDING_FAMILY_ID -- never a second hardcoded literal for
# THAT path.
FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"
# INC-SP1I5 (AUD-05; RULING_live_family_tally_scope_2026-09-21.md): the
# CHAMPION-scoped counter follows the deployed sending family, read from
# breezy-trade-supervisor.service's BREEZY_SENDING_FAMILY_ID. No second
# family-manifest literal for this path. BREEZY_SYSTEMCTL is a test seam;
# production leaves it unset. RULING_A1 stops sending only -- this counter
# does not branch on that disposition.
# L-38: every REGISTERED, venue=polymarket_us family manifest under
# deploy/families -- one scorer invocation per (city, manifest) pair below.
# Overridable so tests can point at a worktree's own deploy/families
# instead of the deployed tree's (mirrors family-tally-v2-run.sh's own
# BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR override).
FAMILIES_DIR="${BREEZY_SCORE_LIVE_TRIALS_FAMILIES_DIR:-$REPO/deploy/families}"
STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/score_live_trials.log
# DEFAULT_QUOTE_TAPE_CATALOG (ma_prelock_winner_ask_study.py) -- the same
# quote-tape catalog root breezy-quote-tape(-ingest).service already write
# under this exact env var name.
CATALOG_ROOT=${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us}
# Drift guard for the v1-scoped counter: byte-identical to
# live-tally-run.sh's own assignment.
V1_D0_LITERAL="2026-09-05"  # PREREG v1 §6:130

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

# L-38: enumerate every REGISTERED, venue=polymarket_us family manifest --
# same grep/sed extraction idiom family-tally-v2-run.sh already uses for
# `family_id` (never a second JSON parser for a shell script). Populates
# the "$manifest_path:$family_id" array the city loop below iterates.
manifest_field() {
  grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$1" | head -n1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
}

FAMILY_MANIFESTS=()
for manifest in "$FAMILIES_DIR"/*.json; do
  [ -e "$manifest" ] || continue
  status=$(manifest_field "$manifest" status)
  venue=$(manifest_field "$manifest" venue)
  family_id=$(manifest_field "$manifest" family_id)
  if [ -z "$family_id" ]; then
    continue  # not a family manifest (e.g. a boundary-artefact JSON)
  fi
  if [ "$venue" != "polymarket_us" ]; then
    say "SKIP $manifest -- venue=$venue (this wrapper scores polymarket_us only)"
    continue
  fi
  if [ "$status" != "REGISTERED" ]; then
    say "SKIP $manifest -- status=$status (not REGISTERED)"
    continue
  fi
  FAMILY_MANIFESTS+=("$manifest:$family_id")
done

STAMP=$(date -u +%Y-%m-%d)
STATUS=0

# F2: drop any stale marker from an earlier same-day run BEFORE the
# pre-flight -- so a later failing run never leaves a prior success's marker
# in place for the tally wrappers to accept by mere existence.
rm -f "$OUT/score_live_trials_ok_$STAMP"

STATE_DB="${POLYMARKET_US_EXEC_STATE_DB:?POLYMARKET_US_EXEC_STATE_DB is required}"

if ! CHECK_TOKEN=$("$PY" -m breezy.runtime.exec_state_db_path --check 2>>"$LOG"); then
  say "SCORE LIVE TRIALS SKIPPED -- node-env pre-flight refused (mismatch or discovery failed)"
  exit 1
fi
if [ "$CHECK_TOKEN" = "NO_NODE" ]; then
  say "WARN: node-env pre-flight found no anchored breezy-trade process"
fi

CJSON="$OUT/covered_listed_station_days_$STAMP.json"
CJSON_CHAMPION="$OUT/covered_listed_station_days_champion_$STAMP.json"
# INC-SP1I5: resolve the champion BEFORE either counter runs. A missing or
# unregistered id removes any stale counter JSON (both paths) and exits 1,
# so yesterday's file is not consumed and no new file is written.
SYSTEMCTL="${BREEZY_SYSTEMCTL:-systemctl}"
resolve_sending_family_manifest() {
  local show id path status kind
  show=$("$SYSTEMCTL" --user show breezy-trade-supervisor.service --property=Environment 2>>"$LOG") || true
  # `systemctl show --property=Environment` prints `Environment=K=V K=V`
  # (one or more lines). Strip the property name, then split assignments.
  id=$(printf '%s\n' "$show" | sed -n 's/^Environment=//p' | tr ' ' '\n' | sed -n 's/^BREEZY_SENDING_FAMILY_ID=//p' | head -n1)
  id=${id%\"}
  id=${id#\"}
  if [ -z "$id" ]; then
    say "SCORE LIVE TRIALS SKIPPED -- BREEZY_SENDING_FAMILY_ID absent on breezy-trade-supervisor.service"
    return 1
  fi
  case "$id" in
    *[!A-Za-z0-9_-]*)
      say "SCORE LIVE TRIALS SKIPPED -- BREEZY_SENDING_FAMILY_ID is not a family id"
      return 1
      ;;
  esac
  path="$FAMILIES_DIR/$id.json"
  if [ ! -f "$path" ]; then
    say "SCORE LIVE TRIALS SKIPPED -- no manifest for sending family $id"
    return 1
  fi
  # S7: this composition has no score_live_trials. Return 2 before the
  # REGISTERED gate so a draft manifest skips the same way a registered one
  # will. The caller exits 0; every other refusal stays exit 1.
  kind=$(manifest_field "$path" composition_kind)
  if [ "$kind" = "forecast_quantile_ladder" ]; then
    say "SCORE LIVE TRIALS SKIPPED -- composition_kind=forecast_quantile_ladder has no score_live_trials"
    return 2
  fi
  status=$(manifest_field "$path" status)
  if [ "$status" != "REGISTERED" ]; then
    say "SCORE LIVE TRIALS SKIPPED -- sending family $id status=${status:-absent} is not REGISTERED"
    return 1
  fi
  CHAMPION_MANIFEST=$path
  CHAMPION_FAMILY_ID=$id
  say "covered-listed champion counter family=$id manifest=$path"
  return 0
}
resolve_sending_family_manifest
resolve_rc=$?
if [ "$resolve_rc" -eq 2 ]; then
  rm -f "$CJSON" "$CJSON_CHAMPION"
  exit 0
fi
if [ "$resolve_rc" -ne 0 ]; then
  rm -f "$CJSON" "$CJSON_CHAMPION"
  exit 1
fi
# Trust-boundary residual (Codex re-check, MEDIUM): remove any existing
# counter JSON IMMEDIATELY before invoking either counter -- never leave a
# stale/foreign well-shaped file in place for the station loop below, the
# 14:30 v1 wrapper, or the v4/champion tally to read. If a counter then
# fails, that file stays absent and its consumer refuses (this wrapper on
# the shape check below; v1/v4 on a missing file), rather than silently
# consuming yesterday's counts.
rm -f "$CJSON" "$CJSON_CHAMPION"

# AUD-05 fix-2 (SPLIT THE ARTEFACT), counter run 1 of 2 -- the PRE-EXISTING,
# v1-scoped counter. Byte-for-byte the same invocation and drift check this
# wrapper had on base commit 161cba8: `pm_us_crh_v2.json`, fetch_start
# 2026-09-05, no sha guard. `live-tally-run.sh` (R-5: OPEN, may not be
# retired/re-windowed) and this wrapper's own STATIONS/scorer loop below
# read THIS file, never the champion-scoped one.
if ! "$PY" "$REPO/scripts/analysis/structural_dead_stop.py" \
     --catalog-root "$CATALOG_ROOT" \
     --family-manifest "$FAMILY_MANIFEST" \
     --output "$CJSON" >>"$LOG" 2>&1; then
  say "SCORE LIVE TRIALS SKIPPED -- covered-listed station-days counter FAILED"
  exit 1
fi

# F3: refuse a malformed/incomplete counter JSON before extracting with
# sed -- a truncated file or one with duplicate matching lines must not be
# silently accepted just because it contains a line the pattern matches.
CJSON_FIRST_LINE=$(head -n1 "$CJSON")
CJSON_LAST_LINE=$(tail -n1 "$CJSON")
if [ "$CJSON_FIRST_LINE" != "{" ] || [ "$CJSON_LAST_LINE" != "}" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- counter JSON is not well-shaped (missing braces)"
  exit 1
fi
CJSON_COUNT_LINES=$(grep -cE '^  "count": [0-9]+,?$' "$CJSON")
CJSON_FETCH_START_LINES=$(grep -cE '^  "fetch_start": "[0-9]{4}-[0-9]{2}-[0-9]{2}",?$' "$CJSON")
CJSON_STATION_LINES=$(grep -cE '^    "[A-Z]{3,4}",?$' "$CJSON")
if [ "$CJSON_COUNT_LINES" -ne 1 ] || [ "$CJSON_FETCH_START_LINES" -ne 1 ]; then
  say "SCORE LIVE TRIALS SKIPPED -- counter JSON count/fetch_start not exactly one line each"
  exit 1
fi
if [ "$CJSON_STATION_LINES" -lt 1 ]; then
  say "SCORE LIVE TRIALS SKIPPED -- counter JSON has no station lines"
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

# AUD-05 fix-2, counter run 2 of 2 -- the NEW, champion-scoped counter
# (INC-SP1I5 / D-H). Consumed by family-tally-v2-run.sh's v4 instance and
# the 14:15 KILL clock; never by live-tally-run.sh or the scorer loop
# below.
if ! "$PY" "$REPO/scripts/analysis/structural_dead_stop.py" \
     --catalog-root "$CATALOG_ROOT" \
     --family-manifest "$CHAMPION_MANIFEST" \
     --output "$CJSON_CHAMPION" >>"$LOG" 2>&1; then
  say "SCORE LIVE TRIALS SKIPPED -- champion covered-listed station-days counter FAILED"
  exit 1
fi

CJSON_CHAMPION_FIRST_LINE=$(head -n1 "$CJSON_CHAMPION")
CJSON_CHAMPION_LAST_LINE=$(tail -n1 "$CJSON_CHAMPION")
if [ "$CJSON_CHAMPION_FIRST_LINE" != "{" ] || [ "$CJSON_CHAMPION_LAST_LINE" != "}" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion counter JSON is not well-shaped (missing braces)"
  exit 1
fi
CJSON_CHAMPION_COUNT_LINES=$(grep -cE '^  "count": [0-9]+,?$' "$CJSON_CHAMPION")
CJSON_CHAMPION_FETCH_START_LINES=$(grep -cE '^  "fetch_start": "[0-9]{4}-[0-9]{2}-[0-9]{2}",?$' "$CJSON_CHAMPION")
if [ "$CJSON_CHAMPION_COUNT_LINES" -ne 1 ] || [ "$CJSON_CHAMPION_FETCH_START_LINES" -ne 1 ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion counter JSON count/fetch_start not exactly one line each"
  exit 1
fi

CHAMPION_FETCH_START=$(sed -nE 's/^  "fetch_start": "([0-9]{4}-[0-9]{2}-[0-9]{2})",?$/\1/p' "$CJSON_CHAMPION")
if [ -z "$CHAMPION_FETCH_START" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion counter output missing fetch_start"
  exit 1
fi
# D-H: the drift guard compares to the SAME manifest the champion counter
# was resolved from. Fail closed if that file's d0 or sha cannot be read.
if [ ! -r "$CHAMPION_MANIFEST" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion manifest unreadable"
  exit 1
fi
CHAMPION_D0=$(manifest_field "$CHAMPION_MANIFEST" d0_climate_day)
if [ -z "$CHAMPION_D0" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion manifest d0_climate_day unreadable"
  exit 1
fi
CHAMPION_SHA=$(sha256sum "$CHAMPION_MANIFEST" 2>>"$LOG" | awk 'NR==1 { print $1 }')
if [ -z "$CHAMPION_SHA" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion manifest sha256 unreadable"
  exit 1
fi
if [ "$CHAMPION_FETCH_START" != "$CHAMPION_D0" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion counter fetch_start drifted from the resolved champion manifest d0"
  exit 1
fi
CJSON_CHAMPION_SHA_LINES=$(grep -cE '^  "manifest_sha256": "[0-9a-f]{64}",?$' "$CJSON_CHAMPION" || true)
if [ "$CJSON_CHAMPION_SHA_LINES" -ne 1 ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion counter JSON manifest_sha256 not exactly one line"
  exit 1
fi
CJSON_CHAMPION_SHA=$(sed -nE 's/^  "manifest_sha256": "([0-9a-f]{64})",?$/\1/p' "$CJSON_CHAMPION")
if [ -z "$CJSON_CHAMPION_SHA" ] || [ "$CJSON_CHAMPION_SHA" != "$CHAMPION_SHA" ]; then
  say "SCORE LIVE TRIALS SKIPPED -- champion counter manifest_sha256 drifted from the resolved champion manifest"
  exit 1
fi

if [ "${#FAMILY_MANIFESTS[@]}" -eq 0 ]; then
  say "SCORE LIVE TRIALS SKIPPED -- no REGISTERED polymarket_us family manifest found in $FAMILIES_DIR"
  exit 1
fi

# L-38: one scorer invocation per (city, REGISTERED family manifest) pair,
# each family's rows written to its OWN $STORE_DIR/<family_id> subdirectory
# -- never a shared top-level directory (family_tally_v2.py's
# filter_rows_to_manifest_prefix refuses a store contaminated by another
# family's rows). A per-city failure marks STATUS=1 but every remaining
# (city, family) pair is still attempted, matching the pre-L-38 per-city
# failure behaviour.
for CITY in $STATIONS; do
  for ENTRY in "${FAMILY_MANIFESTS[@]}"; do
    MANIFEST_PATH="${ENTRY%%:*}"
    FAMILY_ID="${ENTRY##*:}"
    if "$PY" "$REPO/scripts/analysis/score_live_trials.py" \
         --city "$CITY" \
         --family-manifest "$MANIFEST_PATH" \
         --derived-dir "$STORE_DIR/$FAMILY_ID" >>"$LOG" 2>&1; then
      say "scorer ok for city $CITY family $FAMILY_ID"
    else
      say "SCORER FAILED for city $CITY family $FAMILY_ID"
      STATUS=1
    fi
  done
done

if [ "$STATUS" -eq 0 ]; then
  : > "$OUT/score_live_trials_ok_$STAMP"
  say "score-live-trials ok"
fi

exit "$STATUS"
