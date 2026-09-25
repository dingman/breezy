#!/usr/bin/env bash
# AUD-07 M1c/M2 Rev 2 execution amendment -- per-cell driver (amendment
# §3.4 "aud07_m1c_cell.sh <i[:j]>").
#
# Env (all required except the CMD override, which is test-only):
#   STAGE       -- the stage name (matches the RUN_DIR/<stage>/ layout).
#   RUN_DIR     -- the root under which `<stage>/{FAILED,DEFERRED}` live.
#   AUD07_CELL_CMD -- the command to run for one cell (tests only: the
#                     production driver invokes
#                     aud07_live_rule_crossing_sim.py directly; this
#                     override exists ONLY so the orchestration tests can
#                     exercise the FAILED/exit-code wiring without running
#                     a real Monte-Carlo cell).
#
# Exit 0 on success. On a non-zero exit from AUD07_CELL_CMD, appends
# "<arg> rc=<rc> <utc>" to "$RUN_DIR/$STAGE/FAILED" and exits 255 -- exit
# 255 makes xargs -P stop launching new cells (amendment §3.4 step 3).
set -euo pipefail

cell_arg="${1:?usage: aud07_m1c_cell.sh <cell_index[:substream]>}"
stage="${STAGE:?STAGE is required}"
run_dir="${RUN_DIR:?RUN_DIR is required}"
cmd="${AUD07_CELL_CMD:?AUD07_CELL_CMD is required (tests: a stub; production: the real CLI invocation)}"

stage_dir="$run_dir/$stage"
mkdir -p "$stage_dir"
failed_file="$stage_dir/FAILED"

set +e
# shellcheck disable=SC2086
eval "$cmd" "$cell_arg"
rc=$?
set -e

if [ "$rc" -ne 0 ]; then
  printf '%s rc=%s %s\n' "$cell_arg" "$rc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$failed_file"
  exit 255
fi
exit 0
