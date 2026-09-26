#!/usr/bin/env bash
# AUD-03: one run of scripts/analysis/decision_funnel_daily_digest.py.
# The timer owns cadence. This script owns the studies flock and nothing else.
#
# Read-only over the local offer-tape JSONL. No venue credential, no socket
# opened by this wrapper. The alert webhook URL reaches ONLY the python
# process, via the unit's EnvironmentFile (alerts.env).
#
# Lock discipline matches portfolio-roi-run.sh: contention skips (exit 0;
# Persistent=true does not retrigger); a lock-infrastructure failure exits
# 75 so OnFailure= can fire. A digest skipped on contention is not retried
# until the next 09:20Z tick — accepted, same as the other light units.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_DECISION_FUNNEL_PYTHON:-$REPO/.venv/bin/python}"
OUT=${BREEZY_DECISION_FUNNEL_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/decision_funnel_digest.log

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
flock -n 9                     || { say "SKIPPED -- another study holds the studies lock"; exit 0; }

# FU-6: supplied by the unit's own Environment= line (a non-secret path
# literal, byte-identical to the sibling analysis units -- see the unit
# file's own comment). Passed through explicitly as --store-path so the
# digest's halt_enforced read never silently falls back to "unknown" for
# want of this var.
STATE_DB="${POLYMARKET_US_EXEC_STATE_DB:?POLYMARKET_US_EXEC_STATE_DB is required}"

if "$PY" "$REPO/scripts/analysis/decision_funnel_daily_digest.py" --store-path "$STATE_DB"; then
  say "decision funnel digest ok"
else
  status=$?
  say "decision funnel digest failed status=$status"
  exit "$status"
fi
