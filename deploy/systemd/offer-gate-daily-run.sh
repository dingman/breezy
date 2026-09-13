#!/usr/bin/env bash
# SP-1 (2026-09-12): ONE run of the CLI-basis offer-gate scan, shaped on
# k1-daily-run.sh / mb-daily-run.sh.
#
# Until this wrapper existed, breezy-offer-gate-daily.service invoked the
# scan directly via ExecStart=, with a separate ExecStartPre= refreshing
# recent ASOS first (see that unit's own header, :51-64, and its former
# ExecStartPre= comment). This wrapper folds BOTH steps in here so the
# whole run -- refresh AND scan -- sits behind the shared studies flock
# (T3): a separate ExecStartPre= would run OUTSIDE the lock, defeating the
# whole point of serializing the heavy studies.
#
# systemd still resolves `%h` (the invoking user's home directory) and
# passes it as our one required argument -- `%h`-expansion is a systemd,
# not a shell, mechanism, so ExecStart= stays a single plain command with
# no `$(...)`/`%`-date risk (breezy-offer-gate-daily.service:55-65).
#
# Exit status: 0 on a completed scan, 1 if the scan itself failed. The ASOS
# refresh is fail-soft (mirrors the former `-`-prefixed ExecStartPre=): an
# UNEXPECTED refresh crash never blocks the scan from running on whatever
# is already cached.
set -uo pipefail

REPO=/home/jon/breezy
PY="$REPO/.venv/bin/python"
OUT="${1:?offer-gate output directory is required (systemd passes %h/.local/share/breezy/offer_gate)}"
LOG=$OUT/offer_gate_daily.log

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

# Item 4 (2026-09-02) / BL-24, relocated inside the lock (SP-1/T3): refresh
# recent ASOS before the scan runs -- the settlement-alignment cache
# otherwise never advances past whatever incidental fetch last populated
# it, and the scan starves. Fail-soft: an UNEXPECTED crash in the refresh
# script (as opposed to the per-site shortfalls it already reports and
# swallows internally) never blocks the scan from running on whatever is
# already cached -- belt-and-suspenders on top of the script's own
# fail-soft design, never a substitute for it.
if "$PY" "$REPO/scripts/analysis/asos_recent_refresh.py" >/dev/null 2>>"$LOG"; then
  say "asos refresh ok"
else
  say "asos refresh reported a shortfall (see log above) -- continuing on whatever is cached"
fi

if "$PY" "$REPO/scripts/analysis/cli_basis_offer_gate_scan.py" \
     --output "$OUT/offer_gate_latest.md" >/dev/null 2>>"$LOG"; then
  say "offer-gate scan ok"
  exit 0
fi

say "OFFER-GATE SCAN FAILED (see stderr above in $LOG)"
exit 1
