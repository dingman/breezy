#!/usr/bin/env bash
# G-14. ONE run of the K1 cheap-open D+1 settlement measurement.
#
# This is the loop BODY of the stopgap /tmp driver `k1_daily.sh`, with the
# `while`/`sleep 86400` removed: systemd's timer owns the cadence, so the
# script owns only the work. The `timeout 1800` is likewise removed -- the
# unit's TimeoutStartSec enforces it, and two competing timeouts is one
# policy too many.
#
# Writes OUTSIDE the repo so the committed evidence file is never churned; a
# dated snapshot is kept per run and a one-line summary appended to the log.
# Regenerate the committed doc deliberately when the verdict changes.
#
# Exit status: 0 on a completed measurement, 1 if the analysis script failed.
# The unit reports that to `systemctl --user status breezy-k1-daily.service`.
set -uo pipefail

REPO=/home/jon/breezy
OUT=${BREEZY_K1_OUTPUT_DIR:-$HOME/.local/share/breezy/k1}
LOG=$OUT/k1_daily.log

mkdir -p "$OUT"

say() {
  local msg
  msg="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  echo "$msg" >> "$LOG"
  echo "$msg"
}

# Host-wide mutual exclusion for the heavy nightly studies. Skip-not-kill:
# CONTENTION exits 0 so Persistent=true does not retrigger and no sibling
# OnFailure= fires on a healthy skip; LOCK-INFRASTRUCTURE failure exits 75
# (EX_TEMPFAIL) so a persistently broken lock dir is loud in journalctl
# instead of silently skipping forever. `Conflicts=` is deliberately NOT
# used -- it would SIGTERM the RUNNING job (the 2026-09-11 shape).
#
# MEASURED on this host (GNU bash 5.3.9, `set -uo pipefail`, non-POSIX):
# a redirection failure on `exec` returns 1 and RUNS the `||` branch -- the
# shell does NOT exit, so no separate probe command is needed. The ONE
# exception is POSIX mode, where a special builtin's redirection error kills
# the shell EVEN WITH `||`. POSIX mode is reachable two ways -- `set -o posix`
# in this file (no wrapper sets it) and POSIXLY_CORRECT in the ENVIRONMENT,
# which turns it on at bash startup (measured). Both are closed: the unset
# below, and test_no_study_wrapper_enables_posix_mode.
unset POSIXLY_CORRECT
LOCK_DIR="${XDG_RUNTIME_DIR:-}"
if [ -z "$LOCK_DIR" ]; then
  if [ -z "${HOME:-}" ]; then
    say "SKIPPED-INFRA -- neither XDG_RUNTIME_DIR nor HOME is set"; exit 75
  fi
  LOCK_DIR="$HOME/.local/share/breezy"
fi
LOCK="$LOCK_DIR/breezy-studies.lock"
# `2>>"$LOG"` below is safe on `mkdir`: a SIMPLE command's redirect is scoped
# to that command. It must NOT be put on the `exec` line -- an `exec` with no
# command applies its redirections to the SHELL for the rest of the run, which
# measurably swallows every later stderr line and undoes the journal intent
# above. bash's own diagnostic on a failed open therefore reaches stderr ->
# journal, and `say` carries the structured reason.
mkdir -p "$LOCK_DIR" 2>>"$LOG" || { say "SKIPPED-INFRA -- no studies lock directory"; exit 75; }
exec 9>>"$LOCK"                || { say "SKIPPED-INFRA -- cannot open the studies lock"; exit 75; }
flock -n 9                     || { say "SKIPPED -- another study holds the studies lock"; exit 0; }

STAMP=$(date -u +%Y-%m-%d)
SNAP="$OUT/k1_$STAMP.md"

if "$REPO/.venv/bin/python" "$REPO/scripts/analysis/k1_cheap_open_settlement.py" \
     --output "$SNAP" >/dev/null 2>>"$LOG"; then
  POP=$(grep -m1 'MEASURED POPULATION' "$SNAP" 2>/dev/null | tr -dc '0-9')
  VERD=$(grep -A2 -m1 '^## 6. VERDICT' "$SNAP" 2>/dev/null | grep -m1 '^\*\*' | tr -d '*')
  say "n=${POP:-?} verdict=${VERD:-unparsed}"
  case "$VERD" in
    *UNDERPOWERED*|"") : ;;
    *) say "!!! K1 HAS REPORTED A DECISIVE VERDICT: $VERD -- snapshot $SNAP" ;;
  esac
  exit 0
fi

say "K1 RUN FAILED (see stderr above in $LOG)"
exit 1
