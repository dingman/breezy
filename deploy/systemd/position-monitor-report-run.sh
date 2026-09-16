#!/usr/bin/env bash
# INC-6 (docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md Sec 4 "Nightly
# report" / Sec 6 INC-6). ONE run of the position-monitor nightly report
# (scripts/analysis/position_monitor_nightly_report.py), mirroring
# score-live-trials-run.sh / family-tally-v2-run.sh: systemd's timer owns
# the cadence, this script owns only the work.
#
# Scheduled AFTER breezy-score-live-trials.timer (14:15 UTC), which is the
# thing that populates the scored-trials store this report joins against --
# never after either PREREG tally (14:30/17:15 UTC): this report reads the
# monitor's own summary store and the scorer's store directly, never a
# tally's output file.
#
# SHADOW-ONLY / read-only (position_monitor_nightly_report.py's own module
# docstring, D2/D3): this script never constructs, submits, modifies, or
# cancels an order and never touches the TrialDayLatch -- it is a pure
# reduction over two already-persisted parquet stores.
#
# Exit status: 0 on a completed report -- INCLUDING an empty one. An absent
# or empty summaries/scored-trials directory is a normal early-deployment
# state, not a defect: `read_monitor_summaries`/`read_scored_trials`
# (monitor_store.py/scored_trial_store.py) both return zero rows rather than
# raising on a missing directory, and `build_monitor_report` renders a
# report over zero positions -- verified 2026-09-15 against this exact CLI
# with both dirs pointed at nonexistent paths (exit 0). 1 if the report
# script itself fails. Reported to `systemctl --user status
# breezy-position-monitor-report.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_POSITION_MONITOR_REPORT_PYTHON:-$REPO/.venv/bin/python}"

# Same quote-tape catalog root literal as score-live-trials-run.sh:33
# (DEFAULT_QUOTE_TAPE_CATALOG). The live monitor's own summaries directory
# is never a second, hand-maintained path -- it is derived the SAME way
# `composition.py::build_continuous_rung_hold_strategies` derives it for the
# live node: `monitor_root = catalog_root.parent / "monitor"`,
# `summaries_dir = monitor_root / "summaries"`
# (composition.py:490 `_MONITOR_CATALOG_DIRNAME`, :567 `_MONITOR_SUMMARIES_DIRNAME`).
CATALOG_ROOT=${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us}
MONITOR_ROOT="$(dirname "$CATALOG_ROOT")/monitor"
SUMMARIES_DIR="$MONITOR_ROOT/summaries"

# Same scored-trials store as score-live-trials-run.sh:27 /
# family-tally-v2-run.sh:23, and the same reports-dir convention
# (BREEZY_LIVE_TALLY_OUTPUT_DIR override shared with both), so every
# derived artefact lands under the one ~/.local/share/breezy/derived/ root.
STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-$HOME/.local/share/breezy/derived/scored_trials}
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/position_monitor_report.log

# INC-8 corpus summary (scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py
# -> monitor_hypothetical_report.py's `build_corpus_report`), read ONLY when
# present -- optional, so the report's calibration flag reflects the corpus
# accumulation rather than the live monitor's own (usually much smaller)
# station-day count alone. No unit writes into this directory yet; an
# absent directory is normal, not a defect.
CORPUS_DIR="$HOME/.local/share/breezy/derived/hypothetical_hold_corpus"

mkdir -p "$OUT"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

# Host-wide mutual exclusion, same convention as k1-daily-run.sh /
# mb-daily-run.sh / offer-gate-daily-run.sh (SP-1.rev4.md). Skip-not-kill:
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
JSON_OUT="$OUT/position_monitor_report_$STAMP.json"
MD_OUT="$OUT/position_monitor_report_$STAMP.md"

ARGS=(
  --summaries-dir "$SUMMARIES_DIR"
  --scored-trials-dir "$STORE_DIR"
  --out "$JSON_OUT"
  --markdown "$MD_OUT"
)

CORPUS_SUMMARY=""
if [ -d "$CORPUS_DIR" ]; then
  CORPUS_SUMMARY=$(find "$CORPUS_DIR" -maxdepth 1 -name 'hypothetical_hold_corpus_report_*.json' -print 2>/dev/null | sort | tail -n1)
fi
if [ -n "$CORPUS_SUMMARY" ]; then
  ARGS+=(--corpus-summary "$CORPUS_SUMMARY")
fi

if "$PY" "$REPO/scripts/analysis/position_monitor_nightly_report.py" "${ARGS[@]}" >>"$LOG" 2>&1; then
  say "position monitor report ok -- $JSON_OUT"
  exit 0
fi

say "POSITION MONITOR REPORT FAILED (see stderr above in $LOG)"
exit 1
