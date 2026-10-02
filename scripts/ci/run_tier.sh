#!/usr/bin/env bash
# Local tier runner. Every tier delegates to the egress sandbox.
# A CLI -m replaces pytest addopts -m, so the live-class exclusion lives in
# ONE constant and every filtering tier expands it. T4 passes no args: the
# default addopts already applies the same exclusion. Tiers never replace
# the post-merge full gate.
#
# Usage: scripts/ci/run_tier.sh T1|T2|T3|T4 [--lanes N] [pytest args...]
#
# T1 --lanes N (N > 1, opt-in; default 1 is the unchanged serial run) hands
# off to run_t1_lanes.sh: concurrent file lanes plus a serial lane, with an
# exact-partition proof against --collect-only before anything runs.
set -euo pipefail

EXCL='not live and not venue_live and not real_money'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/ci/run_tests_no_egress.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: scripts/ci/run_tier.sh T1|T2|T3|T4 [pytest args...]" >&2
  exit 2
fi

tier="$1"
shift

lanes=1
rest=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lanes)
      [[ $# -ge 2 ]] || { echo "error: --lanes needs a value" >&2; exit 2; }
      lanes="$2"
      shift 2
      ;;
    --lanes=*)
      lanes="${1#--lanes=}"
      shift
      ;;
    *)
      rest+=("$1")
      shift
      ;;
  esac
done
set -- ${rest[@]+"${rest[@]}"}
if ! [[ "$lanes" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: --lanes must be a positive integer (got '$lanes')" >&2
  exit 2
fi
if [[ "$lanes" -gt 1 && "$tier" != "T1" ]]; then
  echo "error: --lanes is only supported for T1" >&2
  exit 2
fi

case "$tier" in
  T1)
    if [[ "$lanes" -gt 1 ]]; then
      exec "$REPO_ROOT/scripts/ci/run_t1_lanes.sh" "$lanes" "$EXCL and not contract and not heavy" "$@"
    fi
    exec "$WRAPPER" -m "$EXCL and not contract and not heavy" tests/unit tests/strategy "$@"
    ;;
  T2)
    exec "$WRAPPER" -m "contract and $EXCL" "$@"
    ;;
  T3)
    exec "$WRAPPER" -m "$EXCL" tests/integration tests/unit/test_forecast_quantile_ladder_boot.py "$@"
    ;;
  T4)
    exec "$WRAPPER" "$@"
    ;;
  *)
    echo "error: unknown tier '$tier' (expected T1, T2, T3 or T4)" >&2
    exit 2
    ;;
esac
