#!/usr/bin/env bash
# AUD-09b nightly replay runner. Mirrors exit-window-study-run.sh's own
# shape (wrapper-owns-the-work, opt-in to breezy-studies.slice + the shared
# host-wide lock): systemd's timer owns the cadence, this script owns
# resolving environment paths and invoking the two Python entry points.
#
# base plan §6b.3 (invocation-set property, B18): this wrapper makes NO
# selection decision, parses NO JSONL artefact, and contains NO
# `record_blocked` -- every `"$PY"` invocation below is one of the two
# named scripts (`replay_sufficiency_census.py`,
# `replay_daily_runner.py`, `promotion_proposal.py`). The proposal
# invocation is the sanctioned third `"$PY"` script (AUD-09 B18 / AUD-10
# C19). It is disk-only and arms nothing.
#
# The armed family manifest is resolved via the SAME
# `systemctl --user show breezy-trade-supervisor.service --property=
# Environment` idiom `score-live-trials-run.sh` / `family-tally-v2-run.sh`
# already use for `BREEZY_SENDING_FAMILY_ID` -- no second resolution
# mechanism for the same value.
#
# Exit status: 0 on a completed run (COMPLETED/RECOVERED/BLOCKED/empty
# queue -- base plan §9: a BLOCKED day or an all-INSUFFICIENT census is a
# data verdict, never a job failure) and 0 on a BENIGN skip (lock
# contention, or no armed/REGISTERED family -- skip-not-kill; each records
# a durable skip via `replay_daily_runner.py --report-skip`, review fix 3);
# non-zero when the runner itself exits non-zero (H0/H3 corruption, or a
# FAILED replay -- base plan §9), OR when `systemctl show` itself fails
# (review fix 3: an INFRA failure resolving the armed family is never
# silently treated as "no family armed"). Reported to `systemctl --user
# status breezy-replay-daily.service`.
set -uo pipefail

REPO=/home/jon/breezy
PY="${BREEZY_REPLAY_DAILY_PYTHON:-$REPO/.venv/bin/python}"
OUT=${BREEZY_LIVE_TALLY_OUTPUT_DIR:-$HOME/.local/share/breezy/derived}
LOG=$OUT/replay_daily.log
FAMILIES_DIR="${BREEZY_REPLAY_DAILY_FAMILIES_DIR:-$REPO/deploy/families}"
QUOTE_CATALOG=${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us}
WEATHER_CATALOG_ROOT=${BREEZY_WEATHER_CATALOG_ROOT:-$HOME/.local/share/breezy/catalog}
OUT_ROOT=${BREEZY_REPLAY_DAILY_OUTPUT_ROOT:-$HOME/.local/share/breezy/derived}
REPLAY_DIR=$OUT/replay
SKIP_STATE_PATH="${BREEZY_REPLAY_DAILY_SKIP_STATE:-$REPLAY_DIR/wrapper_skip_state}"
# R3V-a item 8/9: the nightly timer passes 6 (4 accrual + slack); the
# coordinator's hand-run backfill (2026-09-29, ~10:30Z, outside AUD-07 and
# the protected window) overrides this to 40 via the same env var under
# `systemd-run`.
MAX_TARGETS="${BREEZY_REPLAY_DAILY_MAX_TARGETS:-6}"
# Must equal breezy-replay-daily.service's own TimeoutStartSec= -- the
# override exists only so a test wrapper never has to wait out 1800s.
TIMEOUT_START_SEC="${BREEZY_REPLAY_DAILY_TIMEOUT_START_SEC:-1800}"
# R3V-a item 2: the budget passed to replay_daily_runner.py is never the
# hardcoded 1500 the r1 plan drafted -- it is derived from THIS run's own
# elapsed $SECONDS (the census already ran by the time this is computed)
# and the PREVIOUS run's measured promotion_proposal.py wall time (that
# script runs AFTER the runner, so this run's own duration is unknowable
# yet; last run's is the best available estimate). 300s covers every
# measured promotion_proposal run so far if no estimate exists yet.
PROMOTION_WALL_FILE="$REPLAY_DIR/promotion_proposal_wall_s"

mkdir -p "$OUT" "$REPLAY_DIR"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

# Review fix 3: a benign skip (lock contention, no armed family) is
# recorded durably via the SAME module the real run uses -- never a second
# JSONL-writing/record_blocked mechanism here (B18 stays intact: this is
# one more invocation of the ALREADY-named `replay_daily_runner.py`, using
# a mode that never reads replay_sufficiency.jsonl or replay_results.jsonl
# at all).
#
# Coordinator follow-up (2026-09-25): NOT best-effort. `|| true` here used
# to mean a crashing recorder (e.g. an OSError writing the state file)
# left the skip unrecorded AND the wrapper still exiting 0 -- a skip that
# is silently never recorded can never reach the B19-style >=3 escalation,
# so the ONE thing this fix exists to guarantee (a persistent skip
# eventually pages someone) would quietly stop holding. The recorder's OWN
# exit code is now the caller's problem: propagated via `return`, and the
# call site exits non-zero when it is non-zero, so
# `OnFailure=breezy-study-failed@%n.service` fires on a broken recorder
# exactly like any other wrapper failure.
report_skip() {
  "$PY" "$REPO/scripts/analysis/replay_daily_runner.py" \
    --report-skip "$1" --skip-state-path "$SKIP_STATE_PATH" >>"$LOG" 2>&1
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    say "skip recorder FAILED (exit $rc)"
  fi
  return "$rc"
}

# Host-wide mutual exclusion, same convention as every sibling study
# wrapper (SP-1.rev4.md). Skip-not-kill.
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
if ! flock -n 9; then
  say "SKIPPED -- another study holds the studies lock"
  if report_skip LOCK_CONTENTION; then
    exit 0
  fi
  exit 1
fi

manifest_field() {
  grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$1" | head -n1 \
    | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
}

# Resolve the ARMED family only (base plan §6b.2) -- byte-identical idiom to
# score-live-trials-run.sh's own resolve_sending_family_manifest(), EXCEPT
# (review fix 3) the `systemctl show` call's own exit status is checked
# BEFORE `|| true` ever discarded it: a `systemctl` FAILURE (not installed,
# permission denied, unit unknown) is an INFRA problem, distinct from a
# benign "no family armed yet", and must exit non-zero so `OnFailure=`
# fires -- never silently folded into the ordinary skip path.
SYSTEMCTL="${BREEZY_SYSTEMCTL:-systemctl}"
resolve_family_manifest() {
  local show id path status kind
  if ! show=$("$SYSTEMCTL" --user show breezy-trade-supervisor.service --property=Environment 2>>"$LOG"); then
    say "REPLAY DAILY FAILED -- systemctl show failed, see $LOG"
    return 2
  fi
  id=$(printf '%s\n' "$show" | sed -n 's/^Environment=//p' | tr ' ' '\n' | sed -n 's/^BREEZY_SENDING_FAMILY_ID=//p' | head -n1)
  id=${id%\"}
  id=${id#\"}
  if [ -z "$id" ]; then
    say "REPLAY DAILY SKIPPED -- BREEZY_SENDING_FAMILY_ID absent on breezy-trade-supervisor.service"
    return 1
  fi
  case "$id" in
    *[!A-Za-z0-9_-]*)
      say "REPLAY DAILY SKIPPED -- BREEZY_SENDING_FAMILY_ID is not a family id"
      return 1
      ;;
  esac
  path="$FAMILIES_DIR/$id.json"
  if [ ! -f "$path" ]; then
    say "REPLAY DAILY SKIPPED -- no manifest for sending family $id"
    return 1
  fi
  # S7: this composition has no replay_daily_runner. Return 3 (2 is the
  # systemctl failure) before the REGISTERED gate, and do not call the
  # skip recorder -- that recorder is replay_daily_runner.py.
  kind=$(manifest_field "$path" composition_kind)
  if [ "$kind" = "forecast_quantile_ladder" ]; then
    say "REPLAY DAILY SKIPPED -- composition_kind=forecast_quantile_ladder has no replay_daily_runner"
    return 3
  fi
  status=$(manifest_field "$path" status)
  if [ "$status" != "REGISTERED" ]; then
    say "REPLAY DAILY SKIPPED -- sending family $id status=${status:-absent} is not REGISTERED"
    return 1
  fi
  FAMILY_MANIFEST=$path
}

resolve_family_manifest
resolve_rc=$?
if [ "$resolve_rc" -eq 2 ]; then
  # INFRA failure (systemctl itself) -- loud, non-zero, no skip record: a
  # skip means "we know nothing is armed"; this means we DON'T know.
  exit 1
elif [ "$resolve_rc" -eq 3 ]; then
  exit 0
elif [ "$resolve_rc" -ne 0 ]; then
  if report_skip NO_ARMED_FAMILY; then
    exit 0
  fi
  exit 1
fi

# Step 1: the census (base plan §6b.3 step 1).
if ! "$PY" "$REPO/scripts/analysis/replay_sufficiency_census.py" >>"$LOG" 2>&1; then
  say "REPLAY DAILY FAILED -- census (see $LOG)"
  exit 1
fi

# R3V-a item 2: est_promotion_s is last run's OWN measured
# promotion_proposal.py wall time (written at the tail of this script,
# below) -- a missing or non-numeric file (first run ever, or a
# hand-edited state dir) falls back to 300s, never crashes the arithmetic.
est_promotion_s=$(cat "$PROMOTION_WALL_FILE" 2>/dev/null || true)
est_promotion_s=${est_promotion_s%%.*}
case "$est_promotion_s" in
  ''|*[!0-9]*) est_promotion_s=300 ;;
esac
BUDGET_S=$(( TIMEOUT_START_SEC - SECONDS - est_promotion_s ))

# Step 2: the runner -- everything else (H0 read, target selection, ASOS
# producer + driver subprocess invocations, RECOVERED/FAILED,
# record_blocked, the row append, the summary/batch-summary line) lives in
# replay_daily_runner.py, never here.
if ! "$PY" "$REPO/scripts/analysis/replay_daily_runner.py" \
     --quote-catalog "$QUOTE_CATALOG" \
     --weather-catalog-root "$WEATHER_CATALOG_ROOT" \
     --family-manifest "$FAMILY_MANIFEST" \
     --output-root "$OUT_ROOT" \
     --python "$PY" \
     --max-targets "$MAX_TARGETS" \
     --budget-s "$BUDGET_S" >>"$LOG" 2>&1; then
  say "REPLAY DAILY FAILED (see $LOG)"
  exit 1
fi

# AUD-10b: sanctioned third invocation, still inside breezy-studies.lock,
# after the replay. Disk-only proposal. No JSONL parsing in this wrapper.
# R3V-a: timed so the NEXT run's own --budget-s estimate improves.
promotion_started=$SECONDS
if ! "$PY" "$REPO/scripts/analysis/promotion_proposal.py" \
     --family-manifest "$FAMILY_MANIFEST" \
     --output-root "$OUT/promotion" \
     --tally-output-dir "$OUT" >>"$LOG" 2>&1; then
  say "REPLAY DAILY FAILED -- promotion proposal (see $LOG)"
  exit 1
fi
promotion_wall_s=$(( SECONDS - promotion_started ))
printf '%s\n' "$promotion_wall_s" > "$PROMOTION_WALL_FILE.tmp" 2>>"$LOG" \
  && mv -f "$PROMOTION_WALL_FILE.tmp" "$PROMOTION_WALL_FILE" 2>>"$LOG" \
  || say "promotion_proposal wall-time estimate NOT updated (non-fatal, see $LOG)"
say "replay daily ok"
exit 0
