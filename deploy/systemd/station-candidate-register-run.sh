#!/usr/bin/env bash
# AUD-08b: one run of scripts/analysis/station_candidate_register.py, as
# breezy-station-candidate-register.service (started by the rotate unit's
# OnSuccess=). The rotate timer owns cadence. This script owns the studies flock and
# the catalog-root resolution, nothing else.
#
# ADVISORY ONLY: the register it maintains never makes a city tradeable.
# Disk-only: no venue credential, no venue socket. The alert webhook URL
# reaches ONLY the python process, via the unit's EnvironmentFile (alerts.env).
#
# Lock discipline matches decision-funnel-digest-run.sh: contention skips
# (exit 0 -- the last_folded_day watermark re-folds every missed day on the
# next run) but first runs the cheap --check-staleness mode, which alerts if
# the watermark is more than 2 days old, so a lock held every night cannot
# starve the register silently; a lock-infrastructure failure exits 75 so
# OnFailure= can fire.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_STATION_CANDIDATES_PYTHON:-$REPO/.venv/bin/python}"
OUT=${BREEZY_STATION_CANDIDATES_OUTPUT_DIR:-$HOME/.local/share/breezy/derived/station_candidates}
LOG=$OUT/station_candidate_register.log
# Byte-identical to score-live-trials-run.sh: the root breezy-quote-tape(-ingest)
# writes, so this register and the KILL clock can never read different catalogs.
CATALOG_ROOT=${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us}

mkdir -p "$OUT"

say() {
  local msg
  msg="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  echo "$msg" >> "$LOG"
  echo "$msg"
}

unset POSIXLY_CORRECT
LOCK_DIR="${XDG_RUNTIME_DIR:-}"
if [ -z "$LOCK_DIR" ]; then
  if [ -z "${HOME:-}" ]; then
    say "SKIPPED-INFRA -- neither XDG_RUNTIME_DIR nor HOME is set"; exit 75
  fi
  LOCK_DIR="$HOME/.local/share/breezy"
fi
LOCK="$LOCK_DIR/breezy-studies.lock"
mkdir -p "$LOCK_DIR" 2>>"$LOG" || { say "SKIPPED-INFRA -- no studies lock directory"; exit 75; }
exec 9>>"$LOCK"                || { say "SKIPPED-INFRA -- cannot open the studies lock"; exit 75; }
flock -n 9                     || { say "SKIPPED -- another study holds the studies lock"; "$PY" "$REPO/scripts/analysis/station_candidate_register.py" --check-staleness --state-dir "$OUT"; exit 0; }

if "$PY" "$REPO/scripts/analysis/station_candidate_register.py" \
     --catalog-root "$CATALOG_ROOT" \
     --state-dir "$OUT"; then
  say "station candidate register ok"
else
  status=$?
  say "station candidate register failed status=$status"
  exit "$status"
fi
