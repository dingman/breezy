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
FAMILIES_DIR="$REPO/deploy/families"
# Same store the v1 live tally reads (BREEZY_SCORED_TRIALS_DIR override
# shared with live-tally-run.sh) and the same reports-dir convention
# (BREEZY_LIVE_TALLY_OUTPUT_DIR override shared with live-tally-run.sh),
# so both tallies land artefacts in the same place under
# ~/.local/share/breezy/derived/.
STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
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

EXTRA_ARGS=()
if [ "$FAMILY" = "$PM_FAMILY" ]; then
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
  D0=$(sed -nE 's/^  "fetch_start": "([0-9]{4}-[0-9]{2}-[0-9]{2})",?$/\1/p' "$CJSON")

  if [ -z "$COUNT" ] || [ -z "$D0" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- could not extract count/fetch_start from $CJSON"
    exit 1
  fi

  if [ "$D0" != "$V2_D0_LITERAL" ]; then
    say "FAMILY TALLY V2 ($FAMILY) SKIPPED -- counter fetch_start drifted from the registered d0"
    exit 1
  fi

  STATE_DB="${POLYMARKET_US_EXEC_STATE_DB:?POLYMARKET_US_EXEC_STATE_DB is required}"

  EXTRA_ARGS=(
    --covered-listed-station-days "$COUNT"
    --fill-source "$STATE_DB"
    --fill-since-climate-day "$D0"
  )
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
