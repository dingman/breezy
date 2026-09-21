#!/usr/bin/env bash
# AUD-15 amendment (2026-09-22) -- ONE idempotent migration: move
# BREEZY_ALERT_WEBHOOK_URL out of ~/.config/breezy/breezy-trade.env (loaded
# only by the supervisor) into a DEDICATED, single-key
# ~/.config/breezy/alerts.env (mode 0600), so `breezy-study-failed@.service`
# and `breezy-asos-refresh.service` can load the SAME file without ever
# gaining POLYMARKET_US_ACCOUNT_NUMBER / POLYMARKET_US_EXEC_STATE_DB --
# the two venue-identifying keys `breezy-trade.env` also carries.
#
# NEVER PRINTS, LOGS, OR ECHOES THE VALUE of BREEZY_ALERT_WEBHOOK_URL (or
# any other line of either file). Names, counts, and modes only. The key's
# LINE is moved by `grep ... > file`, never captured into a shell variable
# or interpolated into an echo/say line.
#
# TWO MODES, never combined in one invocation:
#
#   (default) Base migration. Preconditions, checked before any write:
#     - alerts.env already holds exactly one matching line (idempotent
#       no-op), OR breezy-trade.env holds EXACTLY one -- zero or more than
#       one in breezy-trade.env is a loud abort, never a guess.
#     Creates alerts.env mode 0600 (via `install -m 0600 /dev/null`, then
#     the one line copied in) if it does not already hold the key.
#     breezy-trade.env is NEVER modified in this mode -- the two files may
#     transiently hold the SAME value (last-loaded-wins, deliberate and
#     harmless, see README.md's "AUD-15 alert env file" note) until
#     --finalize runs.
#
#   --finalize --delivery-confirmed
#     Removes the key from breezy-trade.env (if present) -- ONLY once BOTH:
#     (1) the INSTALLED breezy-trade-supervisor.service (queried via
#         `systemctl --user cat`, never this repo's copy) already declares
#         an `EnvironmentFile=-...alerts.env` line, proving the unit commit
#         landed AND `daemon-reload` ran; and
#     (2) the operator/coordinator passes `--delivery-confirmed`, attesting
#         the §4d delivery check (`systemd-run ... breezy-check-alerts`)
#         already exited 0. This script does not re-run that check itself --
#         doing so would require a second faked binary in its own test
#         suite (`systemd-run` on top of `systemctl`) for no safety gain
#         over an explicit, auditable flag.
#     Missing either precondition REFUSES loudly and changes nothing.
#
# NEVER restarts, stops, starts, enables, or disables ANY unit, and never
# touches the trade node or supervisor process directly -- both invariants
# this script's own tests assert against a FAKE `systemctl` on PATH.
#
# Idempotent and safe to re-run in either mode.
set -euo pipefail
umask 077

CONFIG_DIR="$HOME/.config/breezy"
TRADE_ENV="$CONFIG_DIR/breezy-trade.env"
ALERTS_ENV="$CONFIG_DIR/alerts.env"
KEY_RE='^BREEZY_ALERT_WEBHOOK_URL='
SUPERVISOR_UNIT="breezy-trade-supervisor.service"

mode="migrate"
delivery_confirmed=0
for arg in "$@"; do
  case "$arg" in
    --finalize) mode="finalize" ;;
    --delivery-confirmed) delivery_confirmed=1 ;;
    *)
      echo "migrate-alerts-env.sh: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

count_key() {
  # $1 = file path. Prints the count of matching lines; 0 if the file is
  # absent. Never prints the matched TEXT, only a count.
  local path="$1"
  if [ -f "$path" ]; then
    grep -c "$KEY_RE" "$path" || true
  else
    echo 0
  fi
}

assert_mode_600() {
  local path="$1"
  local actual
  actual=$(stat -c '%a' "$path")
  if [ "$actual" != "600" ]; then
    echo "migrate-alerts-env.sh: refusing -- $path has mode $actual, expected 600" >&2
    exit 1
  fi
}

if [ "$mode" = "finalize" ]; then
  if [ "$delivery_confirmed" -ne 1 ]; then
    echo "migrate-alerts-env.sh: refusing --finalize -- pass --delivery-confirmed only" \
         "after the README §4d delivery check has exited 0" >&2
    exit 1
  fi
  installed_unit_text="$(systemctl --user cat "$SUPERVISOR_UNIT" 2>/dev/null || true)"
  if ! printf '%s\n' "$installed_unit_text" | grep -qE '^EnvironmentFile=-.*alerts\.env$'; then
    echo "migrate-alerts-env.sh: refusing --finalize -- the INSTALLED $SUPERVISOR_UNIT" \
         "does not yet load alerts.env; land the commit and run 'systemctl --user" \
         "daemon-reload' first" >&2
    exit 1
  fi
  if [ ! -f "$ALERTS_ENV" ]; then
    echo "migrate-alerts-env.sh: refusing --finalize -- $ALERTS_ENV does not exist;" \
         "run the base migration first" >&2
    exit 1
  fi
  assert_mode_600 "$ALERTS_ENV"
  if [ -f "$TRADE_ENV" ]; then
    sed -i "\\%$KEY_RE%d" "$TRADE_ENV"
    chmod 600 "$TRADE_ENV"
  fi
  echo "migrate-alerts-env.sh: finalize ok -- BREEZY_ALERT_WEBHOOK_URL removed from" \
       "$TRADE_ENV (if it was present); $ALERTS_ENV unchanged"
  exit 0
fi

# Base migration (default mode).
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

alerts_count=$(count_key "$ALERTS_ENV")
if [ "$alerts_count" -gt 1 ]; then
  echo "migrate-alerts-env.sh: refusing -- $ALERTS_ENV already carries more than one" \
       "BREEZY_ALERT_WEBHOOK_URL= line; resolve by hand" >&2
  exit 1
fi

if [ "$alerts_count" -eq 1 ]; then
  echo "migrate-alerts-env.sh: already migrated -- $ALERTS_ENV already holds the key" \
       "(idempotent no-op)"
else
  trade_count=$(count_key "$TRADE_ENV")
  if [ "$trade_count" -eq 0 ]; then
    echo "migrate-alerts-env.sh: refusing -- no BREEZY_ALERT_WEBHOOK_URL= line found in" \
         "$TRADE_ENV or $ALERTS_ENV" >&2
    exit 1
  fi
  if [ "$trade_count" -gt 1 ]; then
    echo "migrate-alerts-env.sh: refusing -- $TRADE_ENV carries more than one" \
         "BREEZY_ALERT_WEBHOOK_URL= line; ambiguous, resolve by hand" >&2
    exit 1
  fi
  # Atomic write: build the new content in a temp file in the SAME
  # directory (so `mv` is a same-filesystem rename, never a partial copy),
  # under this script's own `umask 077`, then move it into place in one
  # step. A crash or interruption between these two lines therefore never
  # leaves `alerts.env` truncated or half-written -- readers only ever see
  # the old file or the fully-written new one, never something in between.
  tmp_file="$(mktemp "$CONFIG_DIR/.alerts.env.XXXXXX")"
  trap 'rm -f "$tmp_file"' EXIT
  chmod 600 "$tmp_file"
  grep "$KEY_RE" "$TRADE_ENV" > "$tmp_file"
  mv -f "$tmp_file" "$ALERTS_ENV"
  trap - EXIT
  chmod 600 "$ALERTS_ENV"
  echo "migrate-alerts-env.sh: migrated -- $ALERTS_ENV now holds" \
       "BREEZY_ALERT_WEBHOOK_URL (mode 600); $TRADE_ENV is UNCHANGED (run --finalize" \
       "--delivery-confirmed only after the commit lands and delivery is confirmed)"
fi

assert_mode_600 "$ALERTS_ENV"
if [ -f "$TRADE_ENV" ]; then
  assert_mode_600 "$TRADE_ENV"
fi
