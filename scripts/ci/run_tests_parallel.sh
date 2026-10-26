#!/usr/bin/env bash
# Parallel full test gate. An ACCELERATOR: the serial gate
# (scripts/ci/run_tests_no_egress.sh with no sharding) stays the reference.
#
# Splits the whole collection into N weighted shards (gate_shards.py), runs each
# shard through the UNCHANGED run_tests_no_egress.sh, then runs the files that
# are unsafe beside other shards (real-clock budgets, shared fixed paths)
# serially, then PROVES from JUnit output that every collected test ran exactly
# once with an expected outcome. Exit: the first nonzero among shards (in
# order), the tail, then the execution proof (4). 2 = refused before any test.
#
# Usage: scripts/ci/run_tests_parallel.sh --run-dir <tree>/.pytest-tmp/<name> [--shards N]
#
# Test seams (environment): BREEZY_GATE_TOOL_PYTHON (stdlib interpreter for
# gate_shards.py), BREEZY_GATE_DURATIONS, BREEZY_GATE_REFERENCE,
# BREEZY_GATE_TAIL_MAX_WAIT_S.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CI_DIR="$REPO_ROOT/scripts/ci"
WRAPPER="$CI_DIR/run_tests_no_egress.sh"
SHARDS_PY="$CI_DIR/gate_shards.py"
TOOL_PY="${BREEZY_GATE_TOOL_PYTHON:-python3}"
DURATIONS="${BREEZY_GATE_DURATIONS:-$CI_DIR/gate_durations.json}"
REFERENCE="${BREEZY_GATE_REFERENCE:-$CI_DIR/gate_reference.json}"
TAIL_MAX_WAIT_S="${BREEZY_GATE_TAIL_MAX_WAIT_S:-120}"
TAIL_QUIET_LOAD_PER_CPU=0.25
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
install -d -m 0700 "$RUN" "$RUN/gate" "$RUN/junit" "$RUN/logs" "$RUN/plan" "$RUN/bt" "$RUN/tmp"

log() { echo "[gate] $*"; }

N="$("$TOOL_PY" "$SHARDS_PY" plan-n ${shards_requested:+--shards "$shards_requested"})" || exit 2

live_pids=()
on_signal() {
  local pid
  for pid in "${live_pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  echo "[gate] interrupted; logs kept in $RUN/logs" >&2
  exit 130
}
trap on_signal INT TERM

# Start one job in its own session and process group (so a signal reaches its
# children). Per-job isolation: gate dir, TMPDIR and basetemp are all private.
# The job writes "<rc> <wall seconds>" to logs/<name>.rc when it ends.
LAST_PID=""
start_job() {
  local name="$1" xml="$2"
  shift 2
  install -d -m 0700 "$RUN/gate/$name" "$RUN/tmp/$name"
  setsid env \
    BREEZY_GATE_DIR="$RUN/gate/$name" \
    TMPDIR="$RUN/tmp/$name" \
    JOB_RC_FILE="$RUN/logs/$name.rc" \
    bash -c 'start=$(date +%s); rc=0; "$@" || rc=$?; echo "$rc $(( $(date +%s) - start ))" > "$JOB_RC_FILE"; exit "$rc"' \
    _ "$WRAPPER" -p no:cacheprovider --basetemp "$RUN/bt/$name" --junitxml "$xml" "$@" \
    > "$RUN/logs/$name.log" 2>&1 &
  LAST_PID=$!
  live_pids+=("$LAST_PID")
}

# --- 1. whole-suite collection (also the source of collection-time skips) ---------------------
install -d -m 0700 "$RUN/gate/c0" "$RUN/tmp/c0"
collect_rc=0
env BREEZY_GATE_DIR="$RUN/gate/c0" TMPDIR="$RUN/tmp/c0" \
  "$WRAPPER" --collect-only -p no:randomly -p no:cacheprovider \
  --basetemp "$RUN/bt/c0" --junitxml "$RUN/junit/collect.xml" \
  > "$RUN/logs/collect.out" 2> "$RUN/logs/collect.err" || collect_rc=$?
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
  start_job "s$k" "$RUN/junit/s$k.xml" "${args[@]}"
  pid_of["s$k"]="$LAST_PID"
  jobs_run+=("s$k")
done
log "started ${#jobs_run[@]} shards (N=$N)"

declare -A rc_of=()
for name in "${jobs_run[@]}"; do
  rc=0
  wait "${pid_of[$name]}" || rc=$?
  rc_of["$name"]="$rc"
done

# --- 4. serial tail (after every shard has exited, once the host is quiet) --------------------
mapfile -t tail_args < "$RUN/plan/tail.args"
if [[ "${#tail_args[@]}" -eq 0 ]]; then
  log "tail: empty, skipped"
else
  limit="$(awk -v n="$(nproc)" -v f="$TAIL_QUIET_LOAD_PER_CPU" 'BEGIN { printf "%.2f", n * f }')"
  waited=0
  load="$(cut -d' ' -f1 /proc/loadavg)"
  while ((waited < TAIL_MAX_WAIT_S)) && ! awk -v l="$load" -v m="$limit" 'BEGIN { exit !(l < m) }'; do
    sleep 5
    waited=$((waited + 5))
    load="$(cut -d' ' -f1 /proc/loadavg)"
  done
  log "tail: load1=$load limit=$limit waited=${waited}s files=${#tail_args[@]}"
  start_job tail "$RUN/junit/tail.xml" "${tail_args[@]}"
  rc=0
  wait "$LAST_PID" || rc=$?
  rc_of[tail]="$rc"
  jobs_run+=(tail)
fi
wall=$(($(date +%s) - started))

# --- 5. table --------------------------------------------------------------------------------
echo "[gate] job    rc  wall(s)  args"
rcs=()
for name in "${jobs_run[@]}"; do
  read -r job_rc job_wall < "$RUN/logs/$name.rc" || { job_rc="${rc_of[$name]}"; job_wall="?"; }
  nargs="$(wc -l < "$RUN/plan/$name.args")"
  printf '[gate] %-6s %-3s %-8s %s\n' "$name" "$job_rc" "$job_wall" "$nargs"
  rcs+=("${rc_of[$name]}")
done
log "shards+tail wall: ${wall}s"

# --- 6. execution proof ------------------------------------------------------------------------
junit_shards=()
for name in "${jobs_run[@]}"; do
  if [[ "$name" != tail && -f "$RUN/junit/$name.xml" ]]; then
    junit_shards+=("$RUN/junit/$name.xml")
  fi
done
tail_junit=()
if [[ -f "$RUN/junit/tail.xml" ]]; then
  tail_junit+=("$RUN/junit/tail.xml")
fi
proof_rc=0
"$TOOL_PY" "$SHARDS_PY" verify --ids "$RUN/plan/whole.ids" \
  --collect-xml "$RUN/junit/collect.xml" \
  --junit "${junit_shards[@]}" --tail-junit "${tail_junit[@]}" \
  --reference "$REFERENCE" --run-slow "$RUN_SLOW" --repo-root "$REPO_ROOT" || proof_rc=$?
rcs+=("$proof_rc")

final="$("$TOOL_PY" "$SHARDS_PY" aggregate "${rcs[@]}")"
if [[ "$final" -eq 0 ]]; then
  log "GATE GREEN (parallel; the serial gate remains the reference)"
  rm -rf -- "$RUN/bt" "$RUN/tmp" "$RUN/gate"
  "$TOOL_PY" "$SHARDS_PY" durations --from-junit "${junit_shards[@]}" "${tail_junit[@]}" \
    --out "$RUN/durations.suggested.json" || true
  log "suggested duration refresh: $RUN/durations.suggested.json (adopt it deliberately; never auto-written)"
else
  log "GATE RED rc=$final; scratch and logs kept in $RUN"
fi
exit "$final"
