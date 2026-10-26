#!/usr/bin/env bash
# Parallel full test gate. An ACCELERATOR: the serial gate
# (scripts/ci/run_tests_no_egress.sh with no sharding) stays the reference.
#
# Splits the whole collection into N weighted shards (gate_shards.py), runs each
# shard through the UNCHANGED run_tests_no_egress.sh, then runs the files that
# are unsafe beside other shards (real-clock budgets, shared fixed paths)
# serially, then PROVES from JUnit output that every collected test ran exactly
# once with an expected outcome. Exit: the first nonzero among shards (in
# order), the tail, the execution proof (4), the phase-2 proof (4). 2 = refused before any test.
# After the tail, failures that are ONLY committed load flakes (gate_reviewed.json
# "load_flakes", at most 3 keys) are rerun once, serially, on a quiet host.
#
# Per-job gate dirs live OUTSIDE the tree, at $HOME/.cache/breezy-gate/par/<run-name>/<job>
# (0700; the serial wrapper's own default gate-dir root). Phase 2 puts its basetemp under the
# gate dir and the sandbox binds the repo read-only, so a gate dir inside the tree breaks
# every bwrap_host test. The root is refused if it resolves inside the tree or already
# exists, and is removed when the run ends (green, red, refused or signalled) -- only ever
# a direct child of the par root (gate_shards.py rm-gate-root).
#
# Phase 2 (the fixed bwrap_host registry) runs exactly ONCE per run, in the serial tail. Every
# shard and the load-flake rerun set BREEZY_GATE_PHASE2=defer and carry the wrapper's
# .parallel-shard token in their gate dir; the tail never defers. `gate_shards.py
# phase2-proof` reads the job logs and fails the run (4) unless that holds. Concurrent
# phase-2 copies disturb the host-wide /proc/locks count one of its tests compares.
#
# Usage: scripts/ci/run_tests_parallel.sh --run-dir <tree>/.pytest-tmp/<name> [--shards N]
#
# Test seams (environment): BREEZY_GATE_TOOL_PYTHON (stdlib interpreter for
# gate_shards.py), BREEZY_GATE_DURATIONS, BREEZY_GATE_REFERENCE,
# BREEZY_GATE_TAIL_MAX_WAIT_S. Any of them being set is printed and forces the
# outcome check to ADVISORY; an explicit BREEZY_GATE_REFERENCE that is missing or
# unreadable is an error (4), not an empty reference.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CI_DIR="$REPO_ROOT/scripts/ci"
WRAPPER="$CI_DIR/run_tests_no_egress.sh"
SHARDS_PY="$CI_DIR/gate_shards.py"
TOOL_PY="${BREEZY_GATE_TOOL_PYTHON:-python3}"
DURATIONS="${BREEZY_GATE_DURATIONS:-$CI_DIR/gate_durations.json}"
REFERENCE="${BREEZY_GATE_REFERENCE:-$CI_DIR/gate_reference.json}"
TAIL_MAX_WAIT_S="${BREEZY_GATE_TAIL_MAX_WAIT_S:-120}"
# The tail starts once the host is quiet: whole-host CPU idle sampled from
# /proc/stat over a short window (the 1-minute loadavg lags too far behind).
TAIL_QUIET_IDLE_PCT=90
TAIL_IDLE_WINDOW_S=3
KILL_GRACE_S=10
REFERENCE_EXPLICIT=0
if [[ -n "${BREEZY_GATE_REFERENCE+x}" ]]; then
  REFERENCE_EXPLICIT=1
fi
seams=()
for seam_name in BREEZY_GATE_TOOL_PYTHON BREEZY_GATE_DURATIONS BREEZY_GATE_REFERENCE BREEZY_GATE_TAIL_MAX_WAIT_S; do
  if [[ -n "${!seam_name+x}" ]]; then
    seams+=("$seam_name=${!seam_name}")
  fi
done
RUN_SLOW=0
if [[ "${BREEZY_RUN_SLOW:-}" == 1 ]]; then
  RUN_SLOW=1
fi

usage() {
  echo "usage: $0 --run-dir <repo>/.pytest-tmp/<name> [--shards N]" >&2
  exit 2
}

run_dir=""
shards_requested=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir) [[ $# -ge 2 ]] || usage; run_dir="$2"; shift 2 ;;
    --shards) [[ $# -ge 2 ]] || usage; shards_requested="$2"; shift 2 ;;
    *) echo "error: unknown argument: $1" >&2; usage ;;
  esac
done
[[ -n "$run_dir" ]] || usage
[[ -z "$shards_requested" || "$shards_requested" =~ ^[0-9]+$ ]] || usage

RUN="$("$TOOL_PY" "$SHARDS_PY" check-run-dir --repo-root "$REPO_ROOT" "$run_dir")" || exit 2
if [[ -e "$RUN" ]]; then
  echo "error: run dir already exists: $RUN" >&2
  exit 2
fi
GATE_ROOT="$("$TOOL_PY" "$SHARDS_PY" gate-root --repo-root "$REPO_ROOT" --home "$HOME" "$(basename "$RUN")")" || exit 2
install -d -m 0700 "$RUN" "$RUN/junit" "$RUN/logs" "$RUN/plan" "$RUN/bt" "$RUN/tmp"
install -d -m 0700 "$HOME/.cache" "$HOME/.cache/breezy-gate" "$(dirname "$GATE_ROOT")" "$GATE_ROOT"

# Remove this run's gate dirs on every way out (EXIT also fires after on_signal's exit 130).
cleanup_gate_root() {
  "$TOOL_PY" "$SHARDS_PY" rm-gate-root --home "$HOME" "$GATE_ROOT" ||
    echo "[gate] warning: gate dirs left in place: $GATE_ROOT" >&2
}
trap cleanup_gate_root EXIT

log() { echo "[gate] $*"; }

# Only start_job decides whether a job defers phase 2; never inherit it.
unset BREEZY_GATE_PHASE2

N="$("$TOOL_PY" "$SHARDS_PY" plan-n ${shards_requested:+--shards "$shards_requested"})" || exit 2

live_pids=()
forget_pid() {
  local pid="$1" keep=() other
  for other in "${live_pids[@]}"; do
    if [[ "$other" != "$pid" ]]; then
      keep+=("$other")
    fi
  done
  live_pids=("${keep[@]}")
}
# TERM every live job's process group, give them KILL_GRACE_S to leave, KILL the
# survivors, and reap everything before exiting.
on_signal() {
  trap '' INT TERM
  local pid
  for pid in "${live_pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  sleep "$KILL_GRACE_S"
  for pid in "${live_pids[@]}"; do
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  live_pids=()
  echo "[gate] interrupted; logs kept in $RUN/logs" >&2
  exit 130
}
trap on_signal INT TERM

# Start one job in its own session and process group (so a signal reaches its
# children). Per-job isolation: gate dir, TMPDIR and basetemp are all private.
# The job writes "<rc> <wall seconds>" to logs/<name>.rc when it ends.
# `mode` is `defer` (shards, load-flake rerun: skip phase 2, write the wrapper's token) or
# `run` (the tail: runs phase 2).
LAST_PID=""
start_job() {
  local name="$1" xml="$2" mode="$3" defer_env=()
  shift 3
  install -d -m 0700 "$GATE_ROOT/$name" "$RUN/tmp/$name"
  if [[ "$mode" == defer ]]; then
    install -m 0600 /dev/null "$GATE_ROOT/$name/.parallel-shard"
    defer_env=(BREEZY_GATE_PHASE2=defer)
  fi
  setsid env \
    "${defer_env[@]}" \
    BREEZY_GATE_DIR="$GATE_ROOT/$name" \
    TMPDIR="$RUN/tmp/$name" \
    JOB_RC_FILE="$RUN/logs/$name.rc" \
    bash -c 'start=$(date +%s); rc=0; "$@" || rc=$?; echo "$rc $(( $(date +%s) - start ))" > "$JOB_RC_FILE"; exit "$rc"' \
    _ "$WRAPPER" -p no:cacheprovider --basetemp "$RUN/bt/$name" --junitxml "$xml" "$@" \
    > "$RUN/logs/$name.log" 2>&1 &
  LAST_PID=$!
  live_pids+=("$LAST_PID")
}

# Wait for a tracked job, set JOB_RC to its status and stop tracking it.
JOB_RC=0
wait_job() {
  local pid="$1"
  JOB_RC=0
  wait "$pid" || JOB_RC=$?
  forget_pid "$pid"
}

# Block until the host is quiet (CPU idle >= TAIL_QUIET_IDLE_PCT over a short
# window) or TAIL_MAX_WAIT_S has passed; print the measured value.
quiet_wait() {
  local label="$1" idle="n/a" waited=0
  if ((TAIL_MAX_WAIT_S <= 0)); then
    log "$label: quiet wait disabled (BREEZY_GATE_TAIL_MAX_WAIT_S=$TAIL_MAX_WAIT_S)"
    return 0
  fi
  while true; do
    idle="$("$TOOL_PY" "$SHARDS_PY" cpu-idle --window "$TAIL_IDLE_WINDOW_S")" || {
      log "$label: cpu idle could not be measured; not waiting"
      return 0
    }
    if awk -v i="$idle" -v t="$TAIL_QUIET_IDLE_PCT" 'BEGIN { exit !(i >= t) }'; then
      break
    fi
    waited=$((waited + TAIL_IDLE_WINDOW_S))
    if ((waited >= TAIL_MAX_WAIT_S)); then
      break
    fi
  done
  log "$label: cpu_idle=${idle}% threshold=${TAIL_QUIET_IDLE_PCT}% waited=${waited}s"
}

# --- 1. whole-suite collection (also the source of collection-time skips) ---------------------
install -d -m 0700 "$GATE_ROOT/c0" "$RUN/tmp/c0"
setsid env BREEZY_GATE_DIR="$GATE_ROOT/c0" TMPDIR="$RUN/tmp/c0" \
  "$WRAPPER" --collect-only -p no:randomly -p no:cacheprovider \
  --basetemp "$RUN/bt/c0" --junitxml "$RUN/junit/collect.xml" \
  > "$RUN/logs/collect.out" 2> "$RUN/logs/collect.err" &
collect_pid=$!
live_pids+=("$collect_pid")
wait_job "$collect_pid"
collect_rc="$JOB_RC"
if [[ "$collect_rc" -ne 0 ]]; then
  echo "error: whole-suite collection failed (rc=$collect_rc); refusing to run" >&2
  tail -20 "$RUN/logs/collect.err" >&2 || true
  exit 2
fi
{ grep -E '^tests/.+\.py::' "$RUN/logs/collect.out" || true; } | LC_ALL=C sort > "$RUN/plan/whole.ids"
if [[ ! -s "$RUN/plan/whole.ids" ]]; then
  echo "error: whole-suite collection is empty; refusing to run" >&2
  exit 2
fi

# --- 2. partition ----------------------------------------------------------------------------
"$TOOL_PY" "$SHARDS_PY" partition --ids "$RUN/plan/whole.ids" --shards "$N" \
  --durations "$DURATIONS" --out-dir "$RUN/plan" || exit 2

# --- 3. shards ----------------------------------------------------------------------------------
started=$(date +%s)
declare -A pid_of=()
jobs_run=()
for ((k = 0; k < N; k++)); do
  mapfile -t args < "$RUN/plan/s$k.args"
  if [[ "${#args[@]}" -eq 0 ]]; then
    log "shard s$k: empty, skipped"
    continue
  fi
  start_job "s$k" "$RUN/junit/s$k.xml" defer "${args[@]}"
  pid_of["s$k"]="$LAST_PID"
  jobs_run+=("s$k")
done
log "started ${#jobs_run[@]} shards (N=$N)"

declare -A rc_of=()
for name in "${jobs_run[@]}"; do
  wait_job "${pid_of[$name]}"
  rc_of["$name"]="$JOB_RC"
done

# --- 4. serial tail (after every shard has exited, once the host is quiet) --------------------
mapfile -t tail_args < "$RUN/plan/tail.args"
tail_empty_rc=0
if [[ "${#tail_args[@]}" -eq 0 ]]; then
  # Phase 2 only runs in the tail, so an empty tail means it never ran: red. (Giving the tail
  # a stand-in selection would run a test twice and break the execution proof.)
  log "tail: empty; phase 2 never ran"
  tail_empty_rc=4
else
  quiet_wait "tail files=${#tail_args[@]}"
  start_job tail "$RUN/junit/tail.xml" run "${tail_args[@]}"
  wait_job "$LAST_PID"
  rc_of[tail]="$JOB_RC"
  jobs_run+=(tail)
fi

# Prove phase 2 ran exactly once, in the tail: every non-tail job log deferred it, the tail log
# ran it green. Prints the verdict; the caller silences it for the pre-rerun check.
phase2_proof_run() {
  local name p2_args=()
  for name in "${jobs_run[@]}"; do
    if [[ "$name" != tail ]]; then
      p2_args+=(--shard-log "$RUN/logs/$name.log")
    fi
  done
  if [[ -f "$RUN/logs/tail.log" ]]; then
    p2_args+=(--tail-log "$RUN/logs/tail.log")
  fi
  "$TOOL_PY" "$SHARDS_PY" phase2-proof "${p2_args[@]}"
}

# --- 4b. load-flake rerun (committed flakes only, at most 3 keys, serial, quiet host) ---------
flake_labels=""
flake_applied=0
any_failed=0
for name in "${jobs_run[@]}"; do
  if [[ "${rc_of[$name]}" -ne 0 ]]; then
    any_failed=1
  fi
done
if [[ "$any_failed" -eq 1 ]] && ! phase2_proof_run > /dev/null; then
  # A phase-2 fault is not a load flake: a passing rerun must never supersede it.
  log "phase 2 not proven (see the proof below); no load-flake rerun"
elif [[ "$any_failed" -eq 1 ]]; then
  plan_args=(--ids "$RUN/plan/whole.ids" --out "$RUN/plan/flake.args")
  for name in "${jobs_run[@]}"; do
    plan_args+=(--job "$name" "${rc_of[$name]}" "$RUN/junit/$name.xml")
  done
  if flake_labels="$("$TOOL_PY" "$SHARDS_PY" flake-plan "${plan_args[@]}")"; then
    mapfile -t flake_args < "$RUN/plan/flake.args"
    quiet_wait "flake rerun"
    log "load-flake rerun (once): $flake_labels"
    start_job flake "$RUN/junit/flake-rerun.xml" defer "${flake_args[@]}"
    wait_job "$LAST_PID"
    rc_of[flake]="$JOB_RC"
    jobs_run+=(flake)
    if [[ "$JOB_RC" -eq 0 ]]; then
      flake_applied=1
      for name in "${jobs_run[@]}"; do
        if [[ "$name" != flake && "${rc_of[$name]}" -ne 0 ]]; then
          log "job $name: rc=${rc_of[$name]} explained by load flake(s); superseded by the passing rerun"
          rc_of["$name"]=0
        fi
      done
    fi
  else
    flake_labels=""
  fi
fi
wall=$(($(date +%s) - started))

# --- 5. table --------------------------------------------------------------------------------
echo "[gate] job    rc  wall(s)  args"
rcs=()
for name in "${jobs_run[@]}"; do
  read -r job_rc job_wall < "$RUN/logs/$name.rc" || { job_rc="${rc_of[$name]}"; job_wall="?"; }
  if [[ "$name" == flake ]]; then
    nargs="$(wc -l < "$RUN/plan/flake.args")"
  else
    nargs="$(wc -l < "$RUN/plan/$name.args")"
  fi
  printf '[gate] %-6s %-3s %-8s %s\n' "$name" "$job_rc" "$job_wall" "$nargs"
  rcs+=("${rc_of[$name]}")
done
log "shards+tail wall: ${wall}s"

# --- 6. execution proof ------------------------------------------------------------------------
junit_shards=()
for name in "${jobs_run[@]}"; do
  if [[ "$name" != tail && "$name" != flake && -f "$RUN/junit/$name.xml" ]]; then
    junit_shards+=("$RUN/junit/$name.xml")
  fi
done
tail_junit=()
if [[ -f "$RUN/junit/tail.xml" ]]; then
  tail_junit+=("$RUN/junit/tail.xml")
fi
verify_args=(--ids "$RUN/plan/whole.ids" --collect-xml "$RUN/junit/collect.xml"
  --reference "$REFERENCE" --run-slow "$RUN_SLOW" --repo-root "$REPO_ROOT"
  --status-out "$RUN/logs/proof.status")
if [[ "$REFERENCE_EXPLICIT" -eq 1 ]]; then
  verify_args+=(--reference-explicit)
fi
for seam in "${seams[@]}"; do
  verify_args+=(--seam "$seam")
done
if [[ "$flake_applied" -eq 1 && -f "$RUN/junit/flake-rerun.xml" ]]; then
  verify_args+=(--flake-junit "$RUN/junit/flake-rerun.xml")
fi
if [[ "${#seams[@]}" -gt 0 ]]; then
  log "test seams active (outcome check forced ADVISORY): ${seams[*]}"
fi
proof_rc=0
"$TOOL_PY" "$SHARDS_PY" verify "${verify_args[@]}" \
  --junit "${junit_shards[@]}" --tail-junit "${tail_junit[@]}" || proof_rc=$?
rcs+=("$proof_rc")

# --- 6b. phase 2 ran once, in the tail ----------------------------------------------------------
p2_rc=0
phase2_proof_run || p2_rc=$?
rcs+=("$p2_rc")
if [[ "$tail_empty_rc" -ne 0 ]]; then
  rcs+=("$tail_empty_rc")
fi

final="$("$TOOL_PY" "$SHARDS_PY" aggregate "${rcs[@]}")" || {
  log "aggregate of the job return codes failed (${rcs[*]}); refusing to pass"
  exit 2
}
if [[ "$final" -eq 0 ]]; then
  proof_status="advisory"
  if [[ -f "$RUN/logs/proof.status" ]]; then
    proof_status="$(< "$RUN/logs/proof.status")"
  fi
  parts=()
  if [[ "$proof_status" != authoritative ]]; then
    parts+=("OUTCOME CHECK ADVISORY")
  fi
  if [[ "$flake_applied" -eq 1 ]]; then
    n_flakes="$(awk -F', ' '{ print NF }' <<< "$flake_labels")"
    parts+=("$n_flakes load-flake rerun(s): $flake_labels")
  fi
  if [[ "${#parts[@]}" -eq 0 ]]; then
    log "GATE GREEN (parallel; the serial gate remains the reference)"
  else
    joined="${parts[0]}"
    for part in "${parts[@]:1}"; do
      joined+="; $part"
    done
    log "GATE GREEN ($joined)"
    log "(the serial gate remains the reference)"
  fi
  rm -rf -- "$RUN/bt" "$RUN/tmp"
  "$TOOL_PY" "$SHARDS_PY" durations --from-junit "${junit_shards[@]}" "${tail_junit[@]}" \
    --out "$RUN/durations.suggested.json" || true
  log "suggested duration refresh: $RUN/durations.suggested.json (adopt it deliberately; never auto-written)"
else
  log "GATE RED rc=$final; scratch and logs kept in $RUN (gate dirs removed)"
fi
exit "$final"
