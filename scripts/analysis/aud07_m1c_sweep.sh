#!/usr/bin/env bash
# AUD-07 M1c/M2 Rev 2 execution amendment -- sweep driver (amendment §3.4
# "aud07_m1c_sweep.sh --code-sha --stage --queue <file> --cutoff <ISO-UTC>
# -P 8"), 2026-09-25 review fixes:
#
#   item 2: forwards CODE_SHA/STAGE/RUN_DIR/CUTOFF to `aud07_m1c_cell.sh` as
#   env, so `cell.sh` can implement the est_wall/cutoff deferral itself.
#   Every other cell input (N_REPS, NPTS, BOUNDARY_MODE, EPS_PIN,
#   COARSE_NPTS, AUDIT_EVERY) is inherited from THIS script's own
#   environment -- set by the coordinator (e.g. `systemd-run --setenv=...`)
#   before invoking this script -- and validated by `cell.sh` itself.
#
#   item 4: exports the thread-oversubscription guards itself, rather than
#   relying on the caller to have set them.
set -euo pipefail

export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

code_sha=""
stage=""
queue=""
cutoff=""
parallel=8

while [ $# -gt 0 ]; do
  case "$1" in
    --code-sha) code_sha="$2"; shift 2 ;;
    --stage) stage="$2"; shift 2 ;;
    --queue) queue="$2"; shift 2 ;;
    --cutoff) cutoff="$2"; shift 2 ;;
    -P) parallel="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

: "${code_sha:?--code-sha is required}"
: "${stage:?--stage is required}"
: "${queue:?--queue is required}"
: "${cutoff:?--cutoff is required}"
run_dir="${RUN_DIR:?RUN_DIR is required}"

# Fail-closed: refuse to start if ANY stage under this run has an existing
# FAILED file, until the coordinator resolves it (amendment §3.4 step 1).
shopt -s nullglob
existing_failed=("$run_dir"/*/FAILED)
shopt -u nullglob
if [ "${#existing_failed[@]}" -gt 0 ]; then
  echo "[aud07-m1c-sweep] refusing to start: FAILED file(s) exist:" >&2
  cat "${existing_failed[@]}" >&2
  exit 1
fi

stage_dir="$run_dir/$stage"
mkdir -p "$stage_dir"

cell_script="$(dirname "$0")/aud07_m1c_cell.sh"
export STAGE="$stage" RUN_DIR="$run_dir" CODE_SHA="$code_sha" CUTOFF="$cutoff"
set +e
xargs -a "$queue" -P "$parallel" -n 1 "$cell_script"
rc=$?
set -e

if [ "$rc" -eq 123 ] || [ "$rc" -eq 124 ] || [ "$rc" -eq 125 ]; then
  echo "[aud07-m1c-sweep] one or more cells failed:" >&2
  cat "$stage_dir/FAILED" >&2 2>/dev/null || true
  exit 1
fi
exit 0
