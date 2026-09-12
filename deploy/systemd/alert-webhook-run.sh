#!/usr/bin/env bash
# SP-6 A9. The program `breezy-alert@.service`'s ExecStart= invokes,
# rather than a shell body directly in the unit -- the same convention
# `breezy-offer-gate-daily.service:55-65` documents (an ExecStart= with a
# shell body, `$(...)`, or `%`-date-format specifiers made
# `systemd-analyze --user verify` print "Ignoring unknown escape
# sequences", a non-empty-output FAIL by this repo's own convention; a
# wrapper script path is still a single plain command in exactly the
# sense that check cares about). `%i` (the failed unit's name) is passed
# as this script's one argument by the template unit -- resolved by
# systemd itself, never by a shell here.
#
# The webhook URL travels on curl's OWN stdin only (`--config -`), never
# argv and never echoed -- so it never appears in `ps -eo args` or in any
# line this script itself prints. stderr is discarded so a transport
# error (which could name the destination host) never reaches the
# journal (S-M1).
#
# `-f` (AM-14/SEC2-L1): the OnFailure= path is otherwise UNOBSERVABLE --
# stderr is discarded by the line above, so a destination that breaks
# after the one-time build-time test would report unit success forever,
# silently. `-f` makes curl exit non-zero on an HTTP error response (and
# a connection failure already does), which -- combined with the
# `pipefail` below -- makes THIS SCRIPT exit non-zero too, putting
# `breezy-alert@.service` into `failed`: visible to
# `systemctl --user list-units --failed` without printing the host
# anywhere. Accepted residual: nothing automatically re-checks this path;
# see the deploy README's operator step 5.
set -uo pipefail

# No destination configured: exit 0 quietly. `${1:-unknown}` also makes a
# MISSING argument (should never happen under the template unit, but
# `set -u` would otherwise raise on a bare `$1`) safe -- this line is
# reached and returns 0 before `$1` is ever referenced when the variable
# is unset, and defaults it harmlessly otherwise.
[ -n "${BREEZY_ALERT_WEBHOOK_URL:-}" ] || exit 0

DETAIL="${1:-unknown}"

printf 'url="%s"\n' "$BREEZY_ALERT_WEBHOOK_URL" \
  | curl -sf --max-time 10 --config - -d "unit_failed:$DETAIL" 2>/dev/null
