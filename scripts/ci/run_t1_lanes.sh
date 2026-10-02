#!/usr/bin/env bash
# T1 lane runner, invoked by run_tier.sh when `T1 --lanes N` (N > 1).
# Shards the T1 files into N concurrent lanes, then runs the always-serial
# files. It first PROVES the split: one --collect-only per lane plus the
# serial lane must equal, as a multiset of node ids, one --collect-only of
# the whole tier; it refuses to run otherwise. Exit is non-zero if ANY lane
# fails, and each lane's summary line is printed.
#
# Usage: scripts/ci/run_t1_lanes.sh <lanes> <-m expression> [pytest args...]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/ci/run_tests_no_egress.sh"
lanes="$1"
T1_MARK="$2"
shift 2
pytest_args=("$@")

T1_ROOTS=(tests/unit tests/strategy)
GATE_DIR="${BREEZY_GATE_DIR:-$HOME/.cache/breezy-gate}"

# Node ids of a --collect-only, sorted, one per line (multiset: duplicates kept).
collect_ids() {
  "$WRAPPER" --collect-only -p no:randomly -p no:cacheprovider \
    --basetemp="$GATE_DIR/t1-collect-bt" "$@" 2>/dev/null \
    | { grep -E '^tests/.+\.py::' || true; } | LC_ALL=C sort
}

run_t1_lanes() {
  local py="${BREEZY_PYTHON:-$REPO_ROOT/.venv/bin/python}"
  [[ -x "$py" ]] || py=python3
  local work="$GATE_DIR/t1-lanes"
  rm -rf "$work"
  mkdir -p "$work"
  "$py" "$REPO_ROOT/scripts/ci/tier_lanes.py" --lanes "$lanes" \
    --repo-root "$REPO_ROOT" --out-dir "$work" "${T1_ROOTS[@]}"

  local i
  collect_ids -m "$T1_MARK" "${T1_ROOTS[@]}" "${pytest_args[@]}" > "$work/whole.ids"
  if [[ ! -s "$work/whole.ids" ]]; then
    echo "error: whole-tier collection is empty; refusing to run" >&2
    return 2
  fi
  : > "$work/union.ids"
  for name in $(seq 1 "$lanes") serial; do
    local list="$work/lane$name.txt"
    [[ "$name" == serial ]] && list="$work/serial.txt"
    mapfile -t files < <(grep -v '^$' "$list" || true)
    [[ ${#files[@]} -gt 0 ]] || continue
    collect_ids -m "$T1_MARK" "${files[@]}" "${pytest_args[@]}" >> "$work/union.ids"
  done
  LC_ALL=C sort -o "$work/union.ids" "$work/union.ids"
  if ! cmp -s "$work/whole.ids" "$work/union.ids"; then
    echo "error: lanes are not an exact partition of the T1 collection; refusing to run" >&2
    diff "$work/whole.ids" "$work/union.ids" | head -20 >&2 || true
    return 2
  fi
  echo "[tier] partition proven: $(wc -l < "$work/whole.ids") node ids across $lanes lanes + serial lane" >&2

  local pids=()
  for i in $(seq 1 "$lanes"); do
    mapfile -t files < <(grep -v '^$' "$work/lane$i.txt" || true)
    [[ ${#files[@]} -gt 0 ]] || { pids+=(0); continue; }
    "$WRAPPER" -m "$T1_MARK" --basetemp="$GATE_DIR/t1-lane$i-bt" \
      "${files[@]}" "${pytest_args[@]}" > "$work/lane$i.log" 2>&1 &
    pids+=($!)
  done

  local rc=0 lane_rc
  for i in $(seq 1 "$lanes"); do
    lane_rc=0
    if [[ "${pids[$((i - 1))]}" != 0 ]]; then
      wait "${pids[$((i - 1))]}" || lane_rc=$?
    fi
    echo "[tier] lane $i exit=$lane_rc: $(grep -v '^$' "$work/lane$i.log" | tail -1)" >&2
    [[ "$lane_rc" -eq 0 ]] || { rc=1; tail -40 "$work/lane$i.log" >&2; }
  done

  mapfile -t files < <(grep -v '^$' "$work/serial.txt" || true)
  if [[ ${#files[@]} -gt 0 ]]; then
    lane_rc=0
    "$WRAPPER" -m "$T1_MARK" --basetemp="$GATE_DIR/t1-serial-bt" \
      "${files[@]}" "${pytest_args[@]}" > "$work/serial.log" 2>&1 || lane_rc=$?
    echo "[tier] serial lane exit=$lane_rc: $(grep -v '^$' "$work/serial.log" | tail -1)" >&2
    [[ "$lane_rc" -eq 0 ]] || { rc=1; tail -40 "$work/serial.log" >&2; }
  fi
  return "$rc"
}


run_t1_lanes
