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

# AUD-07 DEFERRED gate (RULING_backlog_resolution_2026-09-28.md): the chain
# never advances to 80k while 20k/DEFERRED is non-empty or 20k coverage of
# cells 0-48 is incomplete. 80k-only -- a 20k (or any other stage) sweep
# never consults its own state here.
if [ "$stage" = "80k" ]; then
  twentyk_dir="$run_dir/20k"
  twentyk_deferred="$twentyk_dir/DEFERRED"
  if [ -s "$twentyk_deferred" ]; then
    echo "[aud07-m1c-sweep] refusing --stage 80k: $twentyk_deferred is non-empty -- drain every deferred 20k cell before advancing to 80k" >&2
    exit 1
  fi

  script_dir="$(cd "$(dirname "$0")" && pwd -P)"
  py="${BREEZY_PYTHON:-$(cd "$script_dir/../.." && pwd -P)/.venv/bin/python}"
  if ! coverage_error="$("$py" - "$script_dir" "$twentyk_dir" <<'PYEOF'
import sys
from pathlib import Path

script_dir, twentyk_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, script_dir)
from aud07_m1c_merge import MergeCoverageError, MergeStageError, check_coverage_20k, dedupe_rows, load_stage_rows

try:
    rows = dedupe_rows(load_stage_rows(sorted(Path(twentyk_dir).glob("*.jsonl")), stage="20k"))
    check_coverage_20k(rows)
except (MergeCoverageError, MergeStageError) as exc:
    # stdout, not stderr: `$(... )` command substitution only captures
    # stdout, and the caller (sweep.sh) folds this text into its own
    # refusal line -- printing it to stderr instead leaves that line empty
    # after the colon while the detail leaks out as a separate, unprefixed
    # line (review fix, 2026-09-28).
    print(str(exc))
    sys.exit(1)
PYEOF
  )"; then
    echo "[aud07-m1c-sweep] refusing --stage 80k: 20k coverage of cells 0-48 is incomplete: $coverage_error" >&2
    exit 1
  fi
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
