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

valid_family_ids() {
  local manifest
  for manifest in "$FAMILIES_DIR"/*.json; do
    [ -e "$manifest" ] || continue
    basename "$manifest" .json
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

if "$PY" "$REPO/scripts/analysis/family_tally_v2.py" \
     --family "$FAMILY" \
     --store-dir "$STORE_DIR" \
     --output "$OUT/family_tally_v2_${FAMILY}_$STAMP.md" >/dev/null 2>>"$LOG"; then
  say "family tally v2 ($FAMILY) ok"
else
  say "FAMILY TALLY V2 ($FAMILY) RUN FAILED (see stderr above in $LOG)"
  STATUS=1
fi

exit "$STATUS"
