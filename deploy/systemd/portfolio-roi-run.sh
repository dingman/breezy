#!/usr/bin/env bash
# AUD-04 (docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
# section 6 D1/D2, section 7 step 5). ONE run of the portfolio ROI report
# (scripts/analysis/portfolio_roi_report.py), mirroring
# position-monitor-report-run.sh / family-tally-v2-run.sh: systemd's timer
# owns the cadence, this script owns only the work.
#
# D2: gated on the SAME 14:15 UTC score-live-trials success marker
# family-tally-v2-run.sh requires -- never on AUD-05's family tally (AUD-05
# is open and this item must still produce a number while it is failing).
#
# ASSUMPTION, stated here because the plan leaves it open: section 7 steps
# 2-3 name portfolio_roi_report.py's loader FUNCTION signatures and its
# output artefact paths, but no argparse/CLI contract for the script itself
# (unlike family_tally_v2.py's --family/--store-dir/--as-of/--output, which
# the plan names explicitly). This wrapper therefore invokes the script
# with NO ARGUMENTS. If the script's implementer lands a required flag,
# this invocation line -- and tests/unit/test_portfolio_roi_deploy.py's
# pin of it -- both need updating in lockstep.
#
# Lock discipline: the SAME breezy-studies.lock host-wide flock every study
# wrapper takes (position-monitor-report-run.sh:87-96) -- CONTENTION skips
# (exit 0; Persistent=true does not retrigger, and no OnFailure= fires on a
# healthy skip); a lock-INFRASTRUCTURE failure exits 75 (EX_TEMPFAIL) so a
# persistently broken lock dir is loud in journalctl instead of silently
# skipping forever.
#
# D6 FIX (2026-09-21): the unit ships with StandardOutput=journal, but every
# say() line and the report script's own stdout used to land in $LOG ONLY
# -- never on this process's stdout -- so `journalctl --user -u
# breezy-portfolio-roi` showed nothing. say() now writes to BOTH places.
# The report script's own output is captured to a private (0600) per-run
# temp file, appended to $LOG in full, and ONLY the LAST `PORTFOLIO_ROI
# `-prefixed line it wrote (the D6 dimensionless summary from
# journal_line()) is echoed to stdout -- no other line the script wrote
# ever reaches stdout, so a stray line that could carry a currency figure
# stays LOG-only. Defence in depth: that one surfaced line is itself
# scanned for a currency-shaped token ($, N.NN, USD) before being echoed;
# a match withholds it in favour of a fixed marker line instead.
#
# Exit status: 0 on a completed report (including one whose roi_status is
# gated -- a detected, reported condition is a success of the detector, per
# section 6 D9, not a crash); 1 if the score-live-trials marker is absent
# or the report script itself fails (a score-live-trials skip marker with a
# closed reason is NO_INPUT, exit 0); 75 on lock-infrastructure failure; 0
# on lock contention (SKIPPED, not a failure). Reported to `systemctl
# --user status breezy-portfolio-roi.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_PORTFOLIO_ROI_PYTHON:-$REPO/.venv/bin/python}"

# Same reports-dir convention shared by every sibling wrapper
# (BREEZY_LIVE_TALLY_OUTPUT_DIR override shared with family-tally-v2-run.sh
# / position-monitor-report-run.sh / score-live-trials-run.sh), so the
# marker this unit gates on and every derived artefact land under the one
# ~/.local/share/breezy/derived/ root.
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/portfolio_roi.log

mkdir -p "$OUT"

# D6 FIX: echoes to stdout too, so StandardOutput=journal actually carries
# every line this wrapper itself decides to say.
say() {
  local msg
  msg="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  echo "$msg" >> "$LOG"
  echo "$msg"
}

# Host-wide mutual exclusion, same convention as every other study wrapper
# (position-monitor-report-run.sh's own comment documents the measured
# bash redirection-failure semantics this preamble relies on: a redirection
# failure on `exec` returns 1 and runs the `||` branch under this file's
# own `set -uo pipefail` -- non-POSIX -- so no separate probe command is
# needed; `unset POSIXLY_CORRECT` closes both ways POSIX mode could change
# that).
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

STAMP=$(date -u +%Y-%m-%d)

# D2: the SAME 14:15 UTC score-live-trials success marker
# family-tally-v2-run.sh requires -- never AUD-05's family tally (open;
# this item must still produce a number while it is failing).
# AUT-6 WP3 S1: a by-design upstream skip (score-live-trials writes the
# sibling `.skipped` marker, one closed `reason=` line) is NO_INPUT, exit 0,
# not a failure. Only a marker whose whole content is a closed-set reason is
# trusted; anything else is treated as an absent marker (exit 1). The success
# marker, when present, always wins.
SKIP_MARKER="$OUT/score_live_trials_ok_$STAMP.skipped"
if [ ! -f "$OUT/score_live_trials_ok_$STAMP" ] && [ -f "$SKIP_MARKER" ]; then
  SKIP_REASON=$(head -c 256 "$SKIP_MARKER" 2>/dev/null || true)
  case "$SKIP_REASON" in
    "reason=composition_kind_has_no_scorer")
      say "PORTFOLIO ROI NO_INPUT -- upstream skipped: composition_kind_has_no_scorer"
      exit 0
      ;;
  esac
fi
if [ ! -f "$OUT/score_live_trials_ok_$STAMP" ]; then
  say "PORTFOLIO ROI SKIPPED -- no score-live-trials success marker for $STAMP"
  exit 1
fi

# D6 FIX: the script's own output goes to a private per-run temp file
# first (never straight to $LOG or stdout) so it can be scanned for the
# one line worth surfacing before anything reaches either place.
OLD_UMASK=$(umask)
umask 077
SCRIPT_OUT=$(mktemp "$OUT/.portfolio_roi_run.XXXXXX")
umask "$OLD_UMASK"
trap 'rm -f "$SCRIPT_OUT"' EXIT

if "$PY" "$REPO/scripts/analysis/portfolio_roi_report.py" >>"$SCRIPT_OUT" 2>&1; then
  cat "$SCRIPT_OUT" >> "$LOG"
  SUMMARY_LINE=$(grep '^PORTFOLIO_ROI ' "$SCRIPT_OUT" | tail -n 1 || true)
  if [ -n "$SUMMARY_LINE" ]; then
    if printf '%s' "$SUMMARY_LINE" | grep -Eq '\$|[0-9]+\.[0-9]{2}|USD'; then
      say "PORTFOLIO ROI SUMMARY WITHHELD -- currency-like token"
    else
      echo "$SUMMARY_LINE"
    fi
  fi
  say "portfolio roi report ok"
  exit 0
fi

cat "$SCRIPT_OUT" >> "$LOG"
say "PORTFOLIO ROI REPORT FAILED (see stderr above in $LOG)"
exit 1
