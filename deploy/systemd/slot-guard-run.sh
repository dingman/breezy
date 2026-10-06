#!/bin/bash
# ExecCondition wrapper for the score-live-trials catch-up guard (AUT-2 r7 WP6, V1).
#
# slot_guard exits 0 (permit) or 10 (deliberate refusal). systemd treats an ExecCondition status of
# 1-254 as a clean skip and 255 as a failure, so the mapping is: 0 -> 0, 10 -> 1 (skip, never
# `failed`), and ANY other status -> 255. That last arm is the point: an ImportError raised before
# slot_guard's own code runs makes Python exit 1, which systemd would read as a clean skip; here it
# becomes a failure and the unit's OnFailure= fires.
#
# BREEZY_PYTHON and SLOT_GUARD_MODULE are test seams only; the unit never sets them.
set -u

PYTHON="${BREEZY_PYTHON:-/home/jon/breezy/.venv/bin/python}"
MODULE="${SLOT_GUARD_MODULE:-breezy.analysis.labeling.slot_guard}"

# -I (isolated mode) ignores PYTHON* variables and the working directory, so the unit cannot be
# steered to another module path. Only the test seam (SLOT_GUARD_MODULE, never set by the unit)
# drops it, because it needs PYTHONPATH to find a planted stand-in module.
if [ -n "${SLOT_GUARD_MODULE:-}" ]; then
  "$PYTHON" -m "$MODULE" "$@"
else
  "$PYTHON" -I -m "$MODULE" "$@"
fi
status=$?
case "$status" in
  0) exit 0 ;;
  10) exit 1 ;;
  *) exit 255 ;;
esac
