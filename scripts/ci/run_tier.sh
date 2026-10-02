#!/usr/bin/env bash
# Local tier runner. Every tier delegates to the egress sandbox.
# A CLI -m replaces pytest addopts -m, so the live-class exclusion lives in
# ONE constant and every filtering tier expands it. T4 passes no args: the
# default addopts already applies the same exclusion. Tiers never replace
# the post-merge full gate.
#
# Usage: scripts/ci/run_tier.sh T1|T2|T3|T4 [pytest args...]
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

case "$tier" in
  T1)
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
