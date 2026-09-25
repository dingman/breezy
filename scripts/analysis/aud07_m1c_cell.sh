#!/usr/bin/env bash
# AUD-07 M1c/M2 Rev 2 execution amendment -- per-cell driver (amendment
# §3.4 "aud07_m1c_cell.sh <i[:j]>"), 2026-09-25 review fixes:
#
#   CRITICAL (item 1): NEVER eval a string. Every input -- the cell arg and
#   every env value this script reads -- is validated against a strict
#   regex before use. The production cell command is a FIXED argv array
#   built inside this script from those validated values, invoked directly
#   (`"${argv[@]}"`), never through `eval`/`sh -c`/word-splitting of an
#   untrusted string.
#
#   `AUD07_CELL_CMD` may be set ONLY as a test override, and ONLY as a
#   single executable file path (validated with the same path regex as
#   every other value, plus `-x`/`-f`) -- it is invoked directly as
#   `"$AUD07_CELL_CMD" "$cell_index" "$substream"`, never re-parsed as a
#   shell string.
#
#   HIGH (item 2): implements the §3.4 est_wall/cutoff deferral --
#   `est_wall` is the class median `wall_s` of completed rows in this
#   stage's dir, else the §2.4 f=5% table x 1.15 (by cell class); if
#   `now + est_wall > cutoff`, appends to DEFERRED and exits 0.
#
#   HIGH (item 3): the snapshot-import assertion is enforced Python-side,
#   inside `aud07_live_rule_crossing_sim.main()` -- see
#   `_SNAPSHOT_GATED_STAGES` there. Nothing to duplicate here.
#
# Env (all validated; required unless marked optional):
#   STAGE        -- ^(smoke|cal_a|cal_b|cal_c|20k|80k)$
#   RUN_DIR      -- path-safe: ^[A-Za-z0-9_./-]+$
#   CODE_SHA     -- ^[0-9a-f]{7,40}$
#   CUTOFF       -- ISO-8601 UTC: ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$
#   N_REPS       -- ^[0-9]+$
#   NPTS         -- ^[0-9]+$
#   BOUNDARY_MODE (optional, default "pure") -- ^(pure|refined)$
#   EPS_PIN      (required iff BOUNDARY_MODE=refined) -- path-safe
#   COARSE_NPTS  (required iff BOUNDARY_MODE=refined) -- ^[0-9]+$
#   AUDIT_EVERY  (optional) -- ^[0-9]+$
#   SUBSTREAM    (optional) -- ^[0-9]+$
#   AUD07_CELL_CMD (optional, TEST ONLY) -- path-safe, must be an
#                  executable regular file.
#
# Exit 0 on success or deferral. On a non-zero exit from the cell command,
# appends "<arg> rc=<rc> <utc>" to "$RUN_DIR/$STAGE/FAILED" and exits 255 --
# exit 255 makes xargs -P stop launching new cells (amendment §3.4 step 3).
set -euo pipefail

_die() {
  echo "[aud07-m1c-cell] REFUSED: $*" >&2
  exit 2
}

# `[[ =~ ]]` performs regex MATCHING only -- it never re-parses or executes
# the value; this is the safe way to validate an untrusted string in bash.
_validate() {
  local value="$1" pattern="$2" name="$3"
  [[ "$value" =~ $pattern ]] || _die "invalid ${name}: ${value@Q}"
}

_PATH_RE='^[A-Za-z0-9_./-]+$'
_INT_RE='^[0-9]+$'
_ISO_UTC_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'

cell_arg="${1:?usage: aud07_m1c_cell.sh <cell_index[:substream]>}"
_validate "$cell_arg" '^[0-9]+(:[0-9]+)?$' "cell arg"
cell_index="${cell_arg%%:*}"
arg_substream=""
[[ "$cell_arg" == *:* ]] && arg_substream="${cell_arg#*:}"

stage="${STAGE:?STAGE is required}"
_validate "$stage" '^(smoke|cal_a|cal_b|cal_c|20k|80k)$' "STAGE"

run_dir="${RUN_DIR:?RUN_DIR is required}"
_validate "$run_dir" "$_PATH_RE" "RUN_DIR"

cutoff="${CUTOFF:?CUTOFF is required}"
_validate "$cutoff" "$_ISO_UTC_RE" "CUTOFF"

stage_dir="$run_dir/$stage"
mkdir -p "$stage_dir"
failed_file="$stage_dir/FAILED"
deferred_file="$stage_dir/DEFERRED"

# --- §3.4 est_wall / cutoff deferral (item 2) -------------------------------
_cell_class() {
  # mixed = cell_index 0..15 (the 16 mixed q_max=1 cells, amendment §4 M1c
  # "Grid"); everything else (same-side, control) is "other" -- matches the
  # §2.4 cost table's two-row split for the 20k/80k stages.
  local idx="$1"
  if [ "$idx" -ge 0 ] && [ "$idx" -le 15 ]; then
    echo "mixed"
  else
    echo "other"
  fi
}

_default_est_wall_s() {
  # §2.4 f=5% wall-time table, seconds, x1.15 (already applied below).
  local stage="$1" class="$2"
  case "$stage:$class" in
    20k:mixed) echo 4928 ;;   # 1.19h * 1.15
    20k:other) echo 9108 ;;   # 2.20h * 1.15
    80k:mixed) echo 4513 ;;   # 1.09h * 1.15
    80k:other) echo 8197 ;;   # 1.98h * 1.15 (control)
    *) echo 1800 ;;           # cal_a/cal_b/cal_c/smoke: generous default
  esac
}

_median_wall_s() {
  local stage_dir="$1" class="$2"
  "${BREEZY_PYTHON:-python3}" - "$stage_dir" "$class" <<'PYEOF'
import json
import pathlib
import sys

stage_dir, want_class = sys.argv[1], sys.argv[2]


def cell_class(idx: int) -> str:
    return "mixed" if 0 <= idx <= 15 else "other"


values = []
for path in pathlib.Path(stage_dir).glob("*.jsonl"):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "wall_s" not in row or "cell_index" not in row:
            continue
        if cell_class(row["cell_index"]) == want_class:
            values.append(row["wall_s"])

if values:
    values.sort()
    n = len(values)
    median = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2
    print(median)
PYEOF
}

class="$(_cell_class "$cell_index")"
est_wall="$(_median_wall_s "$stage_dir" "$class")"
if [ -z "$est_wall" ]; then
  est_wall="$(_default_est_wall_s "$stage" "$class")"
fi
est_wall_int="${est_wall%%.*}"
[ -n "$est_wall_int" ] || est_wall_int=0

now_epoch="$(date -u +%s)"
cutoff_epoch="$(date -u -d "$cutoff" +%s)" || _die "unparseable CUTOFF: $cutoff"

if [ $((now_epoch + est_wall_int)) -gt "$cutoff_epoch" ]; then
  echo "$cell_arg" >> "$deferred_file"
  exit 0
fi

# --- Build the fixed, validated cell command (item 1) -----------------------
out_path="$stage_dir/cell_$(printf '%02d' "$cell_index")"
[ -n "$arg_substream" ] && out_path="${out_path}_s${arg_substream}"
out_path="${out_path}.jsonl"

if [ -n "${AUD07_CELL_CMD:-}" ]; then
  # Test override: a single executable path, invoked directly -- never
  # re-parsed as a shell string.
  _validate "$AUD07_CELL_CMD" "$_PATH_RE" "AUD07_CELL_CMD"
  [ -f "$AUD07_CELL_CMD" ] && [ -x "$AUD07_CELL_CMD" ] || _die "AUD07_CELL_CMD is not an executable file: $AUD07_CELL_CMD"
  argv=("$AUD07_CELL_CMD" "$cell_index" "$arg_substream")
else
  code_sha="${CODE_SHA:?CODE_SHA is required}"
  _validate "$code_sha" '^[0-9a-f]{7,40}$' "CODE_SHA"

  n_reps="${N_REPS:?N_REPS is required}"
  _validate "$n_reps" "$_INT_RE" "N_REPS"

  npts="${NPTS:?NPTS is required}"
  _validate "$npts" "$_INT_RE" "NPTS"

  boundary_mode="${BOUNDARY_MODE:-pure}"
  _validate "$boundary_mode" '^(pure|refined)$' "BOUNDARY_MODE"

  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  argv=(
    "${BREEZY_PYTHON:-python3}" "$script_dir/aud07_live_rule_crossing_sim.py"
    --stage "$stage" --code-sha "$code_sha"
    --cells "$cell_index:$((cell_index + 1))"
    --n-reps "$n_reps" --npts "$npts"
    --out "$out_path"
  )

  if [ "$boundary_mode" = "refined" ]; then
    eps_pin="${EPS_PIN:?EPS_PIN is required when BOUNDARY_MODE=refined}"
    _validate "$eps_pin" "$_PATH_RE" "EPS_PIN"
    coarse_npts="${COARSE_NPTS:?COARSE_NPTS is required when BOUNDARY_MODE=refined}"
    _validate "$coarse_npts" "$_INT_RE" "COARSE_NPTS"
    argv+=(--boundary-mode refined --eps-pin "$eps_pin" --coarse-npts "$coarse_npts")
    if [ -n "${AUDIT_EVERY:-}" ]; then
      _validate "$AUDIT_EVERY" "$_INT_RE" "AUDIT_EVERY"
      argv+=(--audit-every "$AUDIT_EVERY")
    fi
  fi

  if [ -n "$arg_substream" ]; then
    _validate "$arg_substream" "$_INT_RE" "substream"
    argv+=(--substream "$arg_substream")
  fi
fi

set +e
"${argv[@]}"
rc=$?
set -e

if [ "$rc" -ne 0 ]; then
  printf '%s rc=%s %s\n' "$cell_arg" "$rc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$failed_file"
  exit 255
fi
exit 0
