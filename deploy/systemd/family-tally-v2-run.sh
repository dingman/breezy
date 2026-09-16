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
PM_FAMILY="pm_us_crh_v2"
V2_D0_LITERAL="2026-09-05"  # pm_us_crh_v2.json d0_climate_day

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
# score-live-trials-run.sh already writes once per day, pinned to
# pm_us_crh_v2's own d0_climate_day -- so the freshness check below is
# always against $V2_D0_LITERAL, for every family, never this family's own
# D0 (a drift here means the SHARED counter drifted, not this one family).
#
# fill-source/fill-since-climate-day ARE per-family: filled_takes and the
# v3 residual are read under THIS family's own `trial_id_prefix`
# (`count_filled_takes`/`v3_residual_from_fill_source`, both already keyed
# by `manifest.trial_id_prefix` -- e.g. v3's `continuous_rung_hold/trial/`
# vs v2's `current_rung_hold/trial/` -- so no prefix argument needs adding
# here), scoped `--fill-since-climate-day` to THIS family's own
# `d0_climate_day` (read straight off its manifest, never
# $V2_D0_LITERAL) so a family registered after v2 never inherits v2's D0.
EXTRA_ARGS=()
FAMILY_MANIFEST_PATH="$FAMILIES_DIR/$FAMILY.json"
FAMILY_STATUS=$(manifest_field "$FAMILY_MANIFEST_PATH" status)
FAMILY_VENUE=$(manifest_field "$FAMILY_MANIFEST_PATH" venue)
FAMILY_D0=$(manifest_field "$FAMILY_MANIFEST_PATH" d0_climate_day)

if [ "$FAMILY_STATUS" = "REGISTERED" ] && [ "$FAMILY_VENUE" = "polymarket_us" ]; then
  CJSON="$OUT/covered_listed_station_days_$STAMP.json"
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

  if [ "$CJSON_FETCH_START" != "$V2_D0_LITERAL" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- counter fetch_start drifted from the registered d0"
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

if "$PY" "$REPO/scripts/analysis/family_tally_v2.py" \
     --family "$FAMILY" \
     --store-dir "$STORE_DIR" \
     --as-of "$STAMP" \
     --output "$OUT/family_tally_v2_${FAMILY}_$STAMP.md" \
     "${EXTRA_ARGS[@]}" >/dev/null 2>>"$LOG"; then
  say "family tally v2 ($FAMILY) ok"
else
  say "FAMILY TALLY V2 ($FAMILY) RUN FAILED (see stderr above in $LOG)"
  STATUS=1
fi

exit "$STATUS"
