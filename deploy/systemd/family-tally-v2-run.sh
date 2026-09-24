#!/usr/bin/env bash
# ONE run of the PREREG v2 family tally (scripts/analysis/family_tally_v2.py)
# for ONE family, mirroring live-tally-run.sh: systemd's timer owns the
# cadence, this script owns only the work. The family is named by argument
# ($1), NEVER inferred -- one invocation per family. $1 is validated against
# the manifests present in deploy/families/*.json (basename without .json);
# an unknown or missing id fails loudly (exit 2) naming the valid ids,
# rather than silently tallying the wrong family or none at all.
#
# Exit status: 2 on an invalid/missing family id (usage error, never reaches
# the CLI); 0 on a completed report; 1 if the analysis script failed.
# Reported to `systemctl --user status breezy-<family>-tally.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY=${BREEZY_FAMILY_TALLY_V2_PYTHON:-$REPO/.venv/bin/python}
# Overridable so tests can enumerate a worktree's own deploy/families
# instead of the deployed tree's (the deployed default never changes:
# systemd always sees $REPO/deploy/families, exactly the manifests actually
# shipped there).
FAMILIES_DIR="${BREEZY_FAMILY_TALLY_V2_FAMILIES_DIR:-$REPO/deploy/families}"
# Same base store dir the v1 live tally reads (BREEZY_SCORED_TRIALS_DIR
# override shared with live-tally-run.sh) and the same reports-dir
# convention (BREEZY_LIVE_TALLY_OUTPUT_DIR override shared with
# live-tally-run.sh), so both tallies land artefacts in the same place
# under ~/.local/share/breezy/derived/.
#
# L-38: score-live-trials-run.sh now writes each REGISTERED family's rows
# to its OWN "$STORE_DIR_BASE/<family_id>" subdirectory (never a shared
# top-level directory -- this CLI's own filter_rows_to_manifest_prefix
# refuses a store contaminated by another family's rows,
# FamilyStoreContaminationError). This wrapper reads exactly the one
# subdirectory matching $FAMILY below.
STORE_DIR_BASE=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/family_tally_v2.log

FAMILY=${1:-}

manifest_family_id() {
  # B6: a manifest is a family manifest only if it declares its OWN
  # `family_id` field (never inferred from the filename) -- extracted with
  # grep/sed, deliberately never $PY (which the id-validation tests stub to
  # a non-JSON-aware fake for the DOWNSTREAM analysis-script invocation
  # only). Prints nothing if the key is absent (e.g. a boundary-artefact
  # JSON like gs_boundary_pm_us_crh_v2.json, which is never a family
  # manifest and carries no family_id key at all).
  grep -o '"family_id"[[:space:]]*:[[:space:]]*"[^"]*"' "$1" | head -n1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
}

# SD-1/L-38 (2026-09-16): generic single-key string-field reader, same
# grep/sed idiom as manifest_family_id() above and byte-identical to
# score-live-trials-run.sh's own manifest_field() -- never a second JSON
# parser. Used below to read `status`/`venue`/`d0_climate_day` off THIS
# family's own manifest, so the structural-dead-stop inputs generalise to
# ANY REGISTERED, venue=polymarket_us family instead of the literal
# pm_us_crh_v2 alone.
manifest_field() {
  grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$1" | head -n1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
}

# INC-SP1I5: the shared counter's manifest is the deployed sending family,
# read the same way score-live-trials-run.sh reads it. No second family
# literal. BREEZY_SYSTEMCTL is a test seam; production leaves it unset.
SYSTEMCTL="${BREEZY_SYSTEMCTL:-systemctl}"
resolve_champion_manifest() {
  local show id path status
  show=$("$SYSTEMCTL" --user show breezy-trade-supervisor.service --property=Environment 2>>"$LOG") || true
  id=$(printf '%s\n' "$show" | sed -n 's/^Environment=//p' | tr ' ' '\n' | sed -n 's/^BREEZY_SENDING_FAMILY_ID=//p' | head -n1)
  id=${id%\"}
  id=${id#\"}
  if [ -z "$id" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- BREEZY_SENDING_FAMILY_ID absent on breezy-trade-supervisor.service"
    return 1
  fi
  case "$id" in
    *[!A-Za-z0-9_-]*)
      say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- BREEZY_SENDING_FAMILY_ID is not a family id"
      return 1
      ;;
  esac
  path="$FAMILIES_DIR/$id.json"
  if [ ! -f "$path" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- no manifest for sending family $id"
    return 1
  fi
  status=$(manifest_field "$path" status)
  if [ "$status" != "REGISTERED" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- sending family $id status=${status:-absent} is not REGISTERED"
    return 1
  fi
  CHAMPION_MANIFEST=$path
  return 0
}

valid_family_ids() {
  local manifest stem field
  for manifest in "$FAMILIES_DIR"/*.json; do
    [ -e "$manifest" ] || continue
    stem=$(basename "$manifest" .json)
    field=$(manifest_family_id "$manifest")
    [ -n "$field" ] && [ "$field" = "$stem" ] && echo "$stem"
  done
}

VALID_IDS=$(valid_family_ids)

is_valid_family_id() {
  local candidate="$1" known
  for known in $VALID_IDS; do
    [ "$known" = "$candidate" ] && return 0
  done
  return 1
}

if [ -z "$FAMILY" ] || ! is_valid_family_id "$FAMILY"; then
  echo "family-tally-v2-run.sh: unknown or missing family id '$FAMILY' -- valid ids: $(echo "$VALID_IDS" | tr '\n' ' ' | sed 's/ *$//')" >&2
  exit 2
fi

# L-38: this family's own scored-trial subdirectory -- see STORE_DIR_BASE's
# docstring above.
STORE_DIR="$STORE_DIR_BASE/$FAMILY"

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

STAMP=$(date -u +%Y-%m-%d)
STATUS=0
# Structural-dead pin is pm_us_crh_v2 only -- never attached to kalshi_crh_v1.
# v2 is not the KILL clock. Its retired unit files are orphans (plan D-E);
# this id only selects the v2 launch-window gate below.
PM_FAMILY="pm_us_crh_v2"

# I3 (docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md, BLOCK-2): assert the
# 14:15 score-live-trials-run.sh success marker before tallying -- never
# invoke the CLI against a partial or unscored store.
if [ ! -f "$OUT/score_live_trials_ok_$STAMP" ]; then
  say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- no score-live-trials success marker for $STAMP"
  exit 1
fi

if [ "$FAMILY" = "$PM_FAMILY" ]; then
  # The structural-PIN launch-window gate (`structural_pin_guard`) is,
  # deliberately, a pm_us_crh_v2-only artefact of that family's own launch
  # (its own docstring: "Pure structural-pin gate for the PREREG v2
  # family-tally wrapper"; `evaluate_pin_gate` returns NOT_APPLICABLE, never
  # READY, for any other family_id) -- tracked separately (R-4, SP-1 I5) and
  # OUT OF SCOPE for the SD-1/L-38 generalisation below. Never extended to
  # another family.
  CHECK_TOKEN="refused"
  # Capture stdout even on non-zero (MISMATCH/DISCOVERY_FAILED print a token
  # then exit 3). Unset-env --check prints nothing and stays 'refused'.
  CHECK_TOKEN_OUTPUT=$("$PY" -m breezy.runtime.exec_state_db_path --check 2>>"$LOG") || true
  if [ -n "$CHECK_TOKEN_OUTPUT" ]; then
    CHECK_TOKEN="$CHECK_TOKEN_OUTPUT"
  fi

  # Persistent=true boot catch-up before 16:50 exits 1 with no report --
  # accepted. AC #1 is MATCH at 17:15Z; the 14:15 marker is already required
  # above. Time gate is binding: MATCH before LAUNCH_UTC is PRE_LAUNCH.
  GUARD_OUT=$("$PY" -m breezy.runtime.structural_pin_guard --family "$FAMILY" --token "$CHECK_TOKEN" 2>&1)
  GUARD_RC=$?
  say "$GUARD_OUT"
  if [ "$GUARD_RC" -ne 0 ]; then
    MSG="FAMILY TALLY V2 ($FAMILY) STRUCTURAL PIN NOT READY -- $GUARD_OUT (token '$CHECK_TOKEN')"
    echo "$MSG"
    say "$MSG"
    exit 1
  fi
fi

# SD-1/L-38 (2026-09-16, PROGRESS): the structural-dead stop's two inputs --
# covered-listed station-days and the FILL-TIME filled-Takes count -- used
# to reach `family_tally_v2.py` ONLY when `$FAMILY` was literally
# pm_us_crh_v2, so the LIVE `pm_us_crh_cont` family tallied with
# filled_takes=None forever and its own structural-dead stop
# (structural_dead_stop.py's `StructuralDeadVerdict.evaluable`) could never
# fire. Generalised: ANY family whose OWN manifest declares
# status=REGISTERED and venue=polymarket_us gets both inputs -- never a
# second hardcoded family literal.
#
# covered-listed-station-days is FAMILY-AGNOSTIC PER STATION (a property of
# which afternoon windows were actually captured, not of who is trading
# them) and comes from the ONE shared counter JSON
# score-live-trials-run.sh writes once per day for the deployed champion
# (BREEZY_SENDING_FAMILY_ID). The freshness check below is against THAT
# manifest's d0_climate_day and sha256, for every family -- never a v2
# date literal, and never this family's own D0. A drift means the shared
# counter is not the champion's.
#
# Per family (plan §6 D-H, §7 step 11, §8 AC #2/#15; ruling R-4): v4 is
# tallied on its own d0; cont stays invocable for its one terminal run and
# keeps cont's own fill-since; v2 is not the clock (pin gate only).
#
# fill-source/fill-since-climate-day ARE per-family: filled_takes and the
# v3 residual are read under THIS family's own `trial_id_prefix`
# (`count_filled_takes`/`v3_residual_from_fill_source`, both already keyed
# by `manifest.trial_id_prefix` -- e.g. v3's `continuous_rung_hold/trial/`
# vs v2's `current_rung_hold/trial/` -- so no prefix argument needs adding
# here), scoped `--fill-since-climate-day` to THIS family's own
# `d0_climate_day` (read straight off its manifest) so a family registered
# after v2 never inherits v2's D0 or the champion's.
EXTRA_ARGS=()
FAMILY_MANIFEST_PATH="$FAMILIES_DIR/$FAMILY.json"
FAMILY_STATUS=$(manifest_field "$FAMILY_MANIFEST_PATH" status)
FAMILY_VENUE=$(manifest_field "$FAMILY_MANIFEST_PATH" venue)
FAMILY_D0=$(manifest_field "$FAMILY_MANIFEST_PATH" d0_climate_day)

if [ "$FAMILY_STATUS" = "REGISTERED" ] && [ "$FAMILY_VENUE" = "polymarket_us" ]; then
  # AUD-05 fix-2 (SPLIT THE ARTEFACT, 2026-09-24): this reads the
  # CHAMPION-scoped counter score-live-trials-run.sh writes at its OWN,
  # separate path -- never the pre-existing `covered_listed_station_days_
  # $STAMP.json` path, which is v1-scoped (pm_us_crh_v2, fetch_start
  # 2026-09-05) and is live-tally-run.sh's own artefact.
  CJSON="$OUT/covered_listed_station_days_champion_$STAMP.json"
  if [ ! -f "$CJSON" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- no covered-listed station-days JSON for $STAMP"
    exit 1
  fi

  # Shape-check copied from live-tally-run.sh:47-80 -- six-key JSON, sed-stable
  # count/fetch_start. Extra keys are not added by the 14:15 writer.
  CJSON_FIRST_LINE=$(head -n1 "$CJSON")
  CJSON_LAST_LINE=$(tail -n1 "$CJSON")
  if [ "$CJSON_FIRST_LINE" != "{" ] || [ "$CJSON_LAST_LINE" != "}" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- counter JSON is not well-shaped (missing braces)"
    exit 1
  fi
  CJSON_COUNT_LINES=$(grep -cE '^  "count": [0-9]+,?$' "$CJSON")
  CJSON_FETCH_START_LINES=$(grep -cE '^  "fetch_start": "[0-9]{4}-[0-9]{2}-[0-9]{2}",?$' "$CJSON")
  if [ "$CJSON_COUNT_LINES" -ne 1 ] || [ "$CJSON_FETCH_START_LINES" -ne 1 ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- counter JSON count/fetch_start not exactly one line each"
    exit 1
  fi

  COUNT=$(sed -nE 's/^  "count": ([0-9]+),?$/\1/p' "$CJSON")
  CJSON_FETCH_START=$(sed -nE 's/^  "fetch_start": "([0-9]{4}-[0-9]{2}-[0-9]{2})",?$/\1/p' "$CJSON")

  if [ -z "$COUNT" ] || [ -z "$CJSON_FETCH_START" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- could not extract count/fetch_start from $CJSON"
    exit 1
  fi

  # Same manifest the counter was resolved from. Fail closed if its d0
  # or sha cannot be read. Do not delete $CJSON -- the producer owns it.
  if ! resolve_champion_manifest; then
    exit 1
  fi
  if [ ! -r "$CHAMPION_MANIFEST" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- champion manifest unreadable"
    exit 1
  fi
  CHAMPION_D0=$(manifest_field "$CHAMPION_MANIFEST" d0_climate_day)
  if [ -z "$CHAMPION_D0" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- champion manifest d0_climate_day unreadable"
    exit 1
  fi
  CHAMPION_SHA=$(sha256sum "$CHAMPION_MANIFEST" 2>>"$LOG" | awk 'NR==1 { print $1 }')
  if [ -z "$CHAMPION_SHA" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- champion manifest sha256 unreadable"
    exit 1
  fi
  if [ "$CJSON_FETCH_START" != "$CHAMPION_D0" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- counter fetch_start drifted from the resolved champion manifest d0"
    exit 1
  fi
  CJSON_SHA_LINES=$(grep -cE '^  "manifest_sha256": "[0-9a-f]{64}",?$' "$CJSON" || true)
  if [ "$CJSON_SHA_LINES" -ne 1 ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- counter JSON manifest_sha256 not exactly one line"
    exit 1
  fi
  CJSON_SHA=$(sed -nE 's/^  "manifest_sha256": "([0-9a-f]{64})",?$/\1/p' "$CJSON")
  if [ -z "$CJSON_SHA" ] || [ "$CJSON_SHA" != "$CHAMPION_SHA" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- counter manifest_sha256 drifted from the resolved champion manifest"
    exit 1
  fi

  if [ -z "$FAMILY_D0" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- manifest has no d0_climate_day"
    exit 1
  fi

  STATE_DB="${POLYMARKET_US_EXEC_STATE_DB:?POLYMARKET_US_EXEC_STATE_DB is required}"

  EXTRA_ARGS=(
    --covered-listed-station-days "$COUNT"
    --fill-source "$STATE_DB"
    --fill-since-climate-day "$FAMILY_D0"
  )
  say "family tally v2 ($FAMILY) supplied covered-listed-station-days=$COUNT fill-source=$STATE_DB fill-since-climate-day=$FAMILY_D0"
else
  say "family tally v2 ($FAMILY) structural-dead-stop inputs SKIPPED -- status=$FAMILY_STATUS venue=$FAMILY_VENUE (not a REGISTERED polymarket_us family)"
fi

# This run's stderr only. The append-only family_tally_v2.log is not an
# alert input -- reading it loads every previous run. 64KiB bounds the
# traceback the alert process is allowed to hold.
TALLY_ERR_BOUND_BYTES=65536
TALLY_ERR=$(mktemp "${TMPDIR:-/tmp}/breezy-family-tally-err.XXXXXX" 2>>"$LOG") || {
  say "FAMILY TALLY V2 ($FAMILY) RUN FAILED -- could not capture stderr"
  exit 1
}
if "$PY" "$REPO/scripts/analysis/family_tally_v2.py" \
     --family "$FAMILY" \
     --store-dir "$STORE_DIR" \
     --as-of "$STAMP" \
     --output "$OUT/family_tally_v2_${FAMILY}_$STAMP.md" \
     "${EXTRA_ARGS[@]}" >/dev/null 2>"$TALLY_ERR"; then
  cat "$TALLY_ERR" >> "$LOG"
  rm -f "$TALLY_ERR"
  say "family tally v2 ($FAMILY) ok"
else
  TALLY_ERR_BOUND=$(mktemp "${TMPDIR:-/tmp}/breezy-family-tally-err.XXXXXX" 2>>"$LOG") || {
    rm -f "$TALLY_ERR"
    say "FAMILY TALLY V2 ($FAMILY) RUN FAILED -- could not bound stderr"
    exit 1
  }
  tail -c "$TALLY_ERR_BOUND_BYTES" "$TALLY_ERR" > "$TALLY_ERR_BOUND"
  cat "$TALLY_ERR_BOUND" >> "$LOG"
  rm -f "$TALLY_ERR"
  say "FAMILY TALLY V2 ($FAMILY) RUN FAILED (see stderr above in $LOG)"
  STATUS=1
  # AUD-05 D-F: one CRITICAL per (family, UTC day). A repeat the same day
  # is latched. Alert failure must not change the tally's own exit status.
  LATCH="$OUT/family_tally/.alert_latch.json"
  "$PY" -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from family_tally_v2 import emit_family_tally_failure_alert; err_path = Path(sys.argv[3]); emit_family_tally_failure_alert(family_id=sys.argv[2], log_text=err_path.read_text(encoding="utf-8", errors="replace") if err_path.is_file() else "", latch_path=Path(sys.argv[4]), today_utc=sys.argv[5])' \
    "$REPO/scripts/analysis" "$FAMILY" "$TALLY_ERR_BOUND" "$LATCH" "$STAMP" \
    || say "FAMILY TALLY V2 ($FAMILY) alert emit failed (non-fatal)"
  rm -f "$TALLY_ERR_BOUND"
fi

exit "$STATUS"
