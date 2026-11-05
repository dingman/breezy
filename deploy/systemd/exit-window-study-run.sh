#!/usr/bin/env bash
# Nightly driver for the offline "exit window" study
# (docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md,
# scripts/analysis/current_rung_hold_exit_window_study.py). Mirrors
# position-monitor-report-run.sh's own shape (wrapper-owns-the-work, opt-in
# to breezy-studies.slice + the shared host-wide lock even though this unit
# is itself modest) -- systemd's timer owns the cadence, this script owns
# only the work.
#
# READ-ONLY / offline analysis only (the study script's own module
# docstring): this wrapper never constructs, submits, modifies, or cancels
# an order and never touches the TrialDayLatch. It reads the live exec
# `SqliteStateStore` (POLYMARKET_US_EXEC_STATE_DB) but NEVER opens that live
# path from the study CLI: it first makes a READ-ONLY sqlite3 backup copy
# into a private mktemp directory (removed on exit via the trap below) and
# passes ONLY that copy's path as --state-db. The live store is opened here
# with `mode=ro` (URI, no flock) purely to read it for the backup -- this
# process performs no write against it at any point, and the backup step
# uses the stdlib `sqlite3.Connection.backup()` API (safe against a
# concurrently writing WAL-mode node) rather than a plain `cp` of a
# possibly-mid-write file.
#
# STATIONS / SINCE_CLIMATE_DAY below are the pm_us_crh_v2 family's own
# `stations` / `d0_climate_day` (deploy/families/pm_us_crh_v2.json),
# hardcoded with a citation comment. This study is v2-scoped offline
# analysis, not the KILL clock: family-tally-v2-run.sh reads the deployed
# champion manifest for that guard and does not share this date literal.
#
# Exit status: 0 on a completed run (including zero positions -- the study
# script itself reports missing inputs rather than fabricating them, never
# refusing on an empty result), and 0 on lock contention (skip-not-kill,
# never retriggering Persistent=true nor a sibling OnFailure=); 1 if the
# read-only state-store copy or the study script itself fails; 75 on
# lock-infrastructure failure (EX_TEMPFAIL). Reported to `systemctl --user
# status breezy-exit-window-study.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_EXIT_WINDOW_STUDY_PYTHON:-$REPO/.venv/bin/python}"
# Same reports-dir convention (BREEZY_LIVE_TALLY_OUTPUT_DIR override shared
# with every sibling wrapper) so this wrapper's own log lands under the one
# ~/.local/share/breezy/derived/ root -- the study's dated JSON/Markdown
# output goes to the study CLI's own default
# (~/.local/share/breezy/derived/exit_window_study/<run-stamp>/), a sibling
# of this same root, never overridden here.
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/exit_window_study.log

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

# Host-wide mutual exclusion, same lock path as asos-refresh-run.sh and
# position-monitor-report-run.sh. Skip-not-kill: CONTENTION exits 0 so
# Persistent=true does not retrigger and no sibling OnFailure= fires on a
# healthy skip; LOCK-INFRASTRUCTURE failure exits 75 (EX_TEMPFAIL) so a
# persistently broken lock dir is loud in journalctl instead of silently skipping
# forever. `Conflicts=` is deliberately NOT used -- it would SIGTERM the
# RUNNING job (the 2026-09-11 shape).
#
# MEASURED on this host (GNU bash 5.3.9, `set -uo pipefail`, non-POSIX):
# a redirection failure on `exec` returns 1 and RUNS the `||` branch -- the
# shell does NOT exit, so no separate probe command is needed. The ONE
# exception is POSIX mode, where a special builtin's redirection error kills
# the shell EVEN WITH `||`. POSIX mode is reachable two ways -- `set -o posix`
# in this file (not set here) and POSIXLY_CORRECT in the ENVIRONMENT, which
# turns it on at bash startup (measured). Both are closed: the unset below.
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

STATE_DB="${POLYMARKET_US_EXEC_STATE_DB:?POLYMARKET_US_EXEC_STATE_DB is required}"

# pm_us_crh_v2.json stations / d0_climate_day -- see module comment above.
STATIONS=(LAX MDW MIA SFO)
SINCE_CLIMATE_DAY="2026-09-05"  # pm_us_crh_v2.json d0_climate_day

# AUD-07 standing reconciliation (§6): the MOST RECENT AUD-04
# PRIVATE_portfolio_roi_<stamp>.json under the shared $OUT root, read ONLY
# when it exists -- this wrapper runs at 15:20 UTC, before AUD-04's own
# 17:40 UTC timer, so "today's" AUD-04 artefact never exists yet at this
# instant; the most recent one that DOES exist (typically yesterday's) is
# the correct "any date both artefacts exist" reading, never assumed same-day.
AUD04_REPORT=""
if [ -d "$OUT" ]; then
  AUD04_REPORT=$(find "$OUT" -maxdepth 1 -name 'PRIVATE_portfolio_roi_*.json' -print 2>/dev/null | sort | tail -n1)
fi

STAMP=$(date -u +%Y-%m-%d)
RUN_STAMP="${STAMP}_nightly"

TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/breezy-exit-window-study.XXXXXX" 2>>"$LOG") || {
  say "SKIPPED-INFRA -- cannot create a temp dir for the read-only state-store copy"
  exit 75
}
trap 'rm -rf "$TMP_DIR"' EXIT
STATE_DB_COPY="$TMP_DIR/exec_state_ro.sqlite3"

# Read-only sqlite3 backup (module comment above): opens $STATE_DB with
# `mode=ro` (no flock) and writes a full snapshot into $STATE_DB_COPY via
# the stdlib `Connection.backup()` API. The study CLI below receives ONLY
# $STATE_DB_COPY, never $STATE_DB.
BACKUP_PY='
import sqlite3, sys

src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
dst = sqlite3.connect(dst_path)
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
'
if ! "$PY" -c "$BACKUP_PY" "$STATE_DB" "$STATE_DB_COPY" >>"$LOG" 2>&1; then
  say "EXIT WINDOW STUDY SKIPPED -- could not make a read-only copy of the exec state store"
  exit 1
fi

STUDY_ARGS=(
  --state-db "$STATE_DB_COPY"
  --stations "${STATIONS[@]}"
  --since-climate-day "$SINCE_CLIMATE_DAY"
  --obs-source fetch
  --run-stamp "$RUN_STAMP"
)
if [ -n "$AUD04_REPORT" ]; then
  STUDY_ARGS+=(--aud04-report "$AUD04_REPORT")
fi

if "$PY" "$REPO/scripts/analysis/current_rung_hold_exit_window_study.py" \
     "${STUDY_ARGS[@]}" >>"$LOG" 2>&1; then
  say "exit window study ok -- run-stamp $RUN_STAMP"
  exit 0
fi

say "EXIT WINDOW STUDY FAILED (see stderr above in $LOG)"
exit 1
