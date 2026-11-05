#!/usr/bin/env bash
# AUD-18 hypothesis triage. systemd's timer owns the cadence; this wrapper
# owns the studies lock and exactly one Python entry point.
#
# Exit status: 0 on a completed run and on lock contention (skip-not-kill,
# so Persistent=true does not retrigger and OnFailure= does not fire for a
# healthy skip); the Python entry point's own status when that entry point
# fails; 75 (EX_TEMPFAIL) when the lock directory itself cannot be opened.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_HYPOTHESIS_TRIAGE_PYTHON:-$REPO/.venv/bin/python}"
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/hypothesis_triage.log

mkdir -p "$OUT"

say() {
  local msg
  msg="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  echo "$msg" >> "$LOG"
  echo "$msg"
}

# Host-wide mutual exclusion, same lock and skip-not-kill semantics as
# every sibling study wrapper. Contention exits 0. A redirection failure
# on `exec` under POSIX mode kills the shell even with `||`, so POSIX
# mode is closed before the lock is taken.
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
exec 9>>"$LOCK" || { say "SKIPPED-INFRA -- cannot open the studies lock"; exit 75; }
flock -n 9 || { say "SKIPPED -- another study holds the studies lock"; exit 0; }

"$PY" "$REPO/scripts/analysis/hypothesis_triage.py"
