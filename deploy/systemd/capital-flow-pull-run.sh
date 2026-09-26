#!/usr/bin/env bash
# FU-13b round-2 review binding amendment 1 (security REQUEST_CHANGES,
# resolved by design -- no r3 needed). NO on-disk temp file for the puller's
# own stdout/stderr: a crash or an OOM-kill must never leave a residual file
# that could carry activity amounts, ids or cursors (portfolio-roi-run.sh's
# own `mktemp`-plus-scan pattern is deliberately NOT reused here for that
# reason). Instead: `set -o pipefail` plus a pipe straight into
# `grep '^CAPITAL_FLOW_PULL '` keeps ONLY the puller's one dimensionless
# summary line in memory -- nothing else the puller might emit ever touches
# disk or this wrapper's own stdout.
#
# The puller itself already withholds amounts/ids/cursors from that one
# summary line (AC9/AC10, including its ERROR branch, which carries the
# exception CLASS only). The currency-shaped-token withhold below is
# defence in depth, mirroring portfolio-roi-run.sh's own guard, in case a
# future edit to the puller's summary format regresses that.
#
# Mirrors every other study wrapper's discipline: systemd's timer owns the
# cadence, this script owns only the work. No studies flock here (unlike
# portfolio-roi-run.sh): a single bounded JSON pull is a LIGHT read, not a
# heavy quote-tape/parquet study, and it does not contend with them for the
# same reason breezy-fee-evidence-pull.service does not take the lock
# either (see deploy/systemd/README.md's entry for that unit).
#
# Exit status: 0 on a completed pull whose summary line was emitted
# (including WITHHELD -- a detected condition, not a crash); 1 if the
# puller exits non-zero, or emits no `CAPITAL_FLOW_PULL `-prefixed line at
# all. Reported to `systemctl --user status breezy-capital-flow-pull.service`.
set -o pipefail

REPO=/home/jon/breezy
PY="${BREEZY_CAPITAL_FLOW_PULL_PYTHON:-$REPO/.venv/bin/python}"
SCRIPT="$REPO/scripts/venue/polymarket_us_capital_flow_pull.py"

SUMMARY=$("$PY" "$SCRIPT" | grep '^CAPITAL_FLOW_PULL ')
STATUS=$?

if [ -z "$SUMMARY" ]; then
  echo "CAPITAL_FLOW_PULL_RUN FAILED -- no summary line (exit $STATUS)"
  exit 1
fi

if printf '%s' "$SUMMARY" | grep -Eq '\$|[0-9]+\.[0-9]{2}|USD'; then
  echo "CAPITAL_FLOW_PULL SUMMARY WITHHELD -- currency-like token"
else
  echo "$SUMMARY"
fi

exit "$STATUS"
