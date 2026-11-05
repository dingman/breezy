#!/usr/bin/env bash
# F-3 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): one run of
# scripts/ops/decisions_retention.py. The timer owns cadence. This script
# owns the studies flock and nothing else.
#
# Gzip only, read-mostly over the local decisions/ JSONL sidecars. No venue
# credential, no socket opened by this wrapper. R6: pruning ships disabled
# -- see decisions_retention.py's own module docstring; this invocation
# passes no deletion flag, and enabling one is a separate, future, reviewed
# change.
#
# Lock discipline matches decision-funnel-digest-run.sh: contention skips
# (exit 0; Persistent=true does not retrigger); a lock-infrastructure
# failure exits 75 so OnFailure= can fire.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_DECISIONS_RETENTION_PYTHON:-$REPO/.venv/bin/python}"
DECISIONS_DIR="${BREEZY_DECISIONS_RETENTION_DECISIONS_DIR:-$HOME/.local/share/breezy/catalog/quote_tape/decisions}"
OUT="${BREEZY_DECISIONS_RETENTION_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}"
LOG="$OUT/decisions_retention.log"

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

if "$PY" "$REPO/scripts/ops/decisions_retention.py" --decisions-dir "$DECISIONS_DIR"; then
  say "decisions retention ok"
else
  status=$?
  say "decisions retention failed status=$status"
  exit "$status"
fi
