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
# Exit status (AUD-18, 2026-09-25): 1 if ANY of the four steps below exits
# non-zero, 75 on a lock-INFRASTRUCTURE failure, 0 otherwise. Neither a lock
# SKIP nor a stale-cache WARN is a step failure (module docstrings of
# asos_recent_refresh.py, asos_cache_freshness_check.py and
# iem_mos_freshness_check.py all return 0 on staleness) -- only a step that
# itself exits non-zero counts. Each step runs regardless of the others'
# outcome (AC #9): a MOS-step failure never skips the ASOS steps and vice
# versa.
set -uo pipefail

REPO=/home/jon/breezy
PY="$REPO/.venv/bin/python"
OUT=${BREEZY_ASOS_REFRESH_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/asos_refresh.log
# ma_prelock_winner_ask_study.ASOS_FETCH_START -- fixed anchor, update both
# together if it ever changes (mirrors the retired mb-daily-run.sh's own
# comment; the anchor is not forked, ruling §A1(iii)).
ASOS_FETCH_START_ANCHOR=2026-08-30
# AUD-18: the wrapper hard-codes 7 (the deploy first run uses 14 by hand,
# outside the unit -- see the plan's Deploy step 4).
MOS_CLOSED_DAYS_LOOKBACK=7
MOS_STEP_TIMEOUT_S=900

FAILED=0

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

# Captured ONCE: both fetch steps below (ASOS and MOS) gate on the SAME
# lock outcome from this ONE flock(2) call, never a second call on fd 9 --
# both freshness checks stay unconditional regardless of LOCKED.
if flock -n 9; then
  LOCKED=1
else
  LOCKED=0
  say "SKIPPED-LOCK -- another study holds the studies lock; asos refresh not attempted this invocation"
fi

if [ "$LOCKED" -eq 1 ]; then
  # AUD-15 amendment, least privilege (A-5): the fetch talks only to the
  # public IEM ASOS endpoint and has no use for the alert webhook URL --
  # `env -u` strips it from THIS subprocess only, so a credential-shaped
  # value never reaches a process whose job is an outbound HTTP GET to a
  # third party. Only the freshness checks (never a fetch step) need it.
  if env -u BREEZY_ALERT_WEBHOOK_URL "$PY" "$REPO/scripts/analysis/asos_recent_refresh.py" \
       --since "$ASOS_FETCH_START_ANCHOR" >>"$LOG" 2>>"$LOG"; then
    say "asos refresh ok"
  else
    say "asos refresh reported a shortfall (see log above) -- continuing on whatever is cached"
    FAILED=1
  fi
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
  FAILED=1
fi

# AUD-18: the nightly IEM MOS closed-day refresh, added to this unit rather
# than a new timer (coordinator decision). Gates on the SAME captured
# LOCKED result as the ASOS refresh above -- one flock(2) call, two fetch
# steps under it -- and is otherwise independent: a MOS-step failure never
# skips the ASOS steps, and vice versa (AC #9).
if [ "$LOCKED" -eq 1 ]; then
  if BREEZY_LIVE=1 timeout --kill-after=30 "$MOS_STEP_TIMEOUT_S" \
       env -u BREEZY_ALERT_WEBHOOK_URL "$PY" "$REPO/scripts/archive/iem_mos_backfill.py" \
       --closed-days-lookback "$MOS_CLOSED_DAYS_LOOKBACK" --model NBS --apply \
       --report-json "$OUT/mos_refresh.json" >>"$LOG" 2>>"$LOG"; then
    say "iem-mos refresh ok"
  else
    say "iem-mos refresh reported a failure (see log above)"
    FAILED=1
  fi
fi
# No second SKIPPED-LOCK line here on purpose: LOCKED is captured from ONE
# flock(2) call above, and that capture already logged the single
# SKIPPED-LOCK line for this invocation.

# UNCONDITIONAL, same reasoning as the ASOS freshness check above: runs
# whether the MOS refresh step ran, succeeded, failed, or was skipped on
# lock contention. Keeps BREEZY_ALERT_WEBHOOK_URL (from this unit's
# EnvironmentFile) to deliver off-box.
if "$PY" "$REPO/scripts/archive/iem_mos_freshness_check.py" >>"$LOG" 2>>"$LOG"; then
  say "iem-mos freshness check ok"
else
  say "iem-mos freshness check reported an internal error (see log above)"
  FAILED=1
fi

exit $(( FAILED ? 1 : 0 ))
