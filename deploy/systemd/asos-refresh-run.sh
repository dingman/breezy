#!/usr/bin/env bash
# AUD-15 re-home (ruling A1): the ONLY surviving nightly invocation of
# `asos_recent_refresh.py --since <ASOS_FETCH_START anchor>`, moved here from
# the now-retired `mb-daily-run.sh` when `breezy-mb-daily` and
# `breezy-offer-gate-daily` were retired
# (docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md).
#
# CONTROL FLOW DIFFERS FROM THE HEAVY-STUDY WRAPPERS ON PURPOSE (r6 review
# defect, fixed here): `k1-daily-run.sh`/the retired wrappers `exit 0`
# IMMEDIATELY on lock contention, so nothing after the lock line ever runs on
# a contention night. This wrapper's freshness check must run on EVERY
# invocation -- contention or not -- so the lock result is CAPTURED, never
# acted on by an early `exit`: `if flock -n 9; then <refresh>; else
# <SKIPPED-LOCK>; fi`, and the freshness check runs unconditionally after
# that `if/else`. The `SKIPPED-INFRA`/`exit 75` paths below are unchanged
# from the shared idiom -- a lock-INFRASTRUCTURE failure is a real failure
# and must still reach `failed` so 15a's OnFailure= fires.
#
# Exit status: ALWAYS 0. Neither a lock skip nor a stale cache is a unit
# failure (module docstrings of asos_recent_refresh.py and
# asos_cache_freshness_check.py); only a lock-infrastructure failure exits
# non-zero (75).
set -uo pipefail

REPO=/home/jon/breezy
PY="$REPO/.venv/bin/python"
OUT=${BREEZY_ASOS_REFRESH_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/asos_refresh.log
# ma_prelock_winner_ask_study.ASOS_FETCH_START -- fixed anchor, update both
# together if it ever changes (mirrors the retired mb-daily-run.sh's own
# comment; the anchor is not forked, ruling §A1(iii)).
ASOS_FETCH_START_ANCHOR=2026-08-30

mkdir -p "$OUT"

say() {
  local msg
  msg="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  echo "$msg" >> "$LOG"
  echo "$msg"
}

# Host-wide mutual exclusion for the heavy nightly studies, same lock path
# and infra-failure contract as every other wrapper (see their own headers
# for the measured bash redirection-failure semantics this preamble relies
# on). Unlike the heavy wrappers, CONTENTION does not `exit 0` here -- the
# lock result is captured and the freshness check still runs below.
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

if flock -n 9; then
  # AUD-15 amendment, least privilege (A-5): the fetch talks only to the
  # public IEM ASOS endpoint and has no use for the alert webhook URL --
  # `env -u` strips it from THIS subprocess only, so a credential-shaped
  # value never reaches a process whose job is an outbound HTTP GET to a
  # third party. Only the freshness check below (never this one) needs it.
  if env -u BREEZY_ALERT_WEBHOOK_URL "$PY" "$REPO/scripts/analysis/asos_recent_refresh.py" \
       --since "$ASOS_FETCH_START_ANCHOR" >>"$LOG" 2>>"$LOG"; then
    say "asos refresh ok"
  else
    say "asos refresh reported a shortfall (see log above) -- continuing on whatever is cached"
  fi
else
  say "SKIPPED-LOCK -- another study holds the studies lock; asos refresh not attempted this invocation"
fi

# UNCONDITIONAL: runs whether the lock was acquired or not, and whether the
# refresh subprocess ran, succeeded, reported a shortfall, or was never
# invoked. Placing this before any early `exit` is the fix for the r6 defect
# above -- see asos_cache_freshness_check.py's own module docstring for why
# existence alone is not the rule and why there is no hour threshold. This
# step, and ONLY this step, needs BREEZY_ALERT_WEBHOOK_URL (from this unit's
# own EnvironmentFile=-%h/.config/breezy/alerts.env) to deliver off-box.
if "$PY" "$REPO/scripts/analysis/asos_cache_freshness_check.py" >>"$LOG" 2>>"$LOG"; then
  say "asos cache freshness check ok"
else
  say "asos cache freshness check reported an internal error (see log above)"
fi

exit 0
