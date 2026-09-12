"""The `breezy-liveness-watchdog` oneshot probe (SP-6 A12).

Scheduled by ``breezy-liveness-watchdog.timer`` (`*:0/5`) as a
`Type=oneshot` unit: `A12 alone covers BOTH the supervisor and the trade
node with no day-state coupling` (N12) -- A11 (`trade_supervisor.py`'s
own fast path) exists beside this for LATENCY (~120 s vs up to 5 min) and
independence from this timer's own health, not because A12 leaves a gap.

Imports ONLY :mod:`breezy.runtime.process_probe` and the schedule anchors
from :mod:`breezy.runtime.trade_supervisor_core` (N7) -- never
:mod:`breezy.runtime.trade_supervisor`, so this oneshot never pulls in
the supervisor's whole I/O shell (flock reading, log parsing,
``subprocess.Popen`` for spawning) just to look a pid up.

Shaped on ``quote_tape_preflight_cli.py``'s ``run(argv, *, env, stdout) ->
int`` idiom: injectable ``probe``/``sleep``/``now``/``sink`` for tests,
never raises.

**Fork-rate accounting (SEC2-M1).** Each of the two processes costs
exactly ONE fork (`pgrep`) when healthy (`probe_pid_by_argv`'s FOUND
outcome ends that process's check immediately) -- 2 forks per 5-minute
tick in the steady state. A second probe, ~2 s later, fires ONLY on
suspicion (a first result that was not FOUND), which is exactly the case
this two-probe design exists to disambiguate: a genuine absence from a
transient probe hiccup.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TextIO

from breezy.runtime.alert_detail import assert_payload_detail_is_safe
from breezy.runtime.composition import _close_alert_sink
from breezy.runtime.health import (
    HEALTH_LOGGER_NAME,
    AlertPayload,
    AlertSink,
    emit_alert,
    resolve_alert_sink,
)
from breezy.runtime.logging_bridge import ensure_stderr_visible
from breezy.runtime.process_probe import PidProbe, ProbeOutcome, probe_pid_by_argv
from breezy.runtime.trade_supervisor_core import (
    NODE_ARGV_ANCHOR,
    SUPERVISOR_ARGV_ANCHOR,
    AlertDetail,
    node_expected_alive,
)

__all__ = ["assert_payload_detail_is_safe", "main", "run"]

PROGRAM = "breezy-liveness-watchdog"

EXIT_OK = 0
EXIT_ABSENCE_REPORTED = 1
EXIT_INTERNAL_ERROR = 2

#: How long to wait before the SECOND probe of a suspicious (non-FOUND)
#: first result. Build-side judgement; see the module docstring.
_SECOND_PROBE_DELAY_S = 2.0

logger = logging.getLogger(__name__)

Probe = Callable[[str], PidProbe]
Sleep = Callable[[float], None]


def _classify(
    anchor: str,
    *,
    probe: Probe,
    sleep: Sleep,
) -> ProbeOutcome:
    """FOUND on either probe wins immediately. A suspicious first result
    (ABSENT or FAILED) triggers ONE second probe; FAILED on EITHER probe
    wins over ABSENT (a probe hiccup is never promoted to a confirmed
    absence). Only ABSENT on BOTH probes is a confirmed absence.
    """
    first = probe(anchor)
    if first.outcome is ProbeOutcome.FOUND:
        return ProbeOutcome.FOUND
    sleep(_SECOND_PROBE_DELAY_S)
    second = probe(anchor)
    if second.outcome is ProbeOutcome.FOUND:
        return ProbeOutcome.FOUND
    if first.outcome is ProbeOutcome.FAILED or second.outcome is ProbeOutcome.FAILED:
        return ProbeOutcome.FAILED
    return ProbeOutcome.ABSENT


def run(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    sink: AlertSink | None = None,
    stdout: TextIO | None = None,
    now: dt.datetime | None = None,
    probe: Probe | None = None,
    sleep: Sleep | None = None,
) -> int:
    """Probe the supervisor and the trade node once each; alert on a
    confirmed absence. Never raises."""
    out = sys.stdout if stdout is None else stdout
    active_env: Mapping[str, str] = env if env is not None else os.environ
    active_probe: Probe = probe if probe is not None else probe_pid_by_argv
    active_sleep: Sleep = sleep if sleep is not None else time.sleep
    active_now = now if now is not None else dt.datetime.now(dt.UTC)

    # argparse-free: this CLI takes no arguments today. `argv` is accepted
    # (and ignored beyond existing) purely to match the repo's console-CLI
    # shape, so a future flag never breaks the console-script signature.
    if argv:
        argparse.ArgumentParser(prog=PROGRAM).parse_args(list(argv))

    active_sink: AlertSink | None = None
    try:
        active_sink = sink if sink is not None else resolve_alert_sink(active_env)
        ensure_stderr_visible(HEALTH_LOGGER_NAME)
        absence_reported = False
        probe_failed = False

        supervisor_outcome = _classify(
            SUPERVISOR_ARGV_ANCHOR, probe=active_probe, sleep=active_sleep
        )
        if supervisor_outcome is ProbeOutcome.FAILED:
            probe_failed = True
        elif supervisor_outcome is ProbeOutcome.ABSENT:
            # Any hour: the supervisor is a `Restart=always` reboot-durable
            # unit with no legitimate scheduled downtime (unlike the node,
            # which stops nightly).
            detail = AlertDetail.SUPERVISOR_ABSENT.value
            assert_payload_detail_is_safe(detail)
            emit_alert(
                active_sink,
                AlertPayload(
                    severity="CRITICAL", event="SUPERVISOR_ABSENT", site="global", detail=detail
                ),
            )
            absence_reported = True

        node_outcome = _classify(NODE_ARGV_ANCHOR, probe=active_probe, sleep=active_sleep)
        if node_outcome is ProbeOutcome.FAILED:
            probe_failed = True
        elif node_outcome is ProbeOutcome.ABSENT and node_expected_alive(active_now):
            detail = AlertDetail.TRADE_NODE_ABSENT.value
            assert_payload_detail_is_safe(detail)
            emit_alert(
                active_sink,
                AlertPayload(
                    severity="CRITICAL", event="TRADE_NODE_ABSENT", site="global", detail=detail
                ),
            )
            absence_reported = True
        # else: node ABSENT but not node_expected_alive -- the stop/relaunch
        # window; silent by design (B1/AM-14).

        if probe_failed:
            # WARN, never promoted to a CRITICAL absence (B4): a probe
            # failure is evidence of nothing about the process itself.
            detail = AlertDetail.LIVENESS_PROBE_FAILED.value
            assert_payload_detail_is_safe(detail)
            emit_alert(
                active_sink,
                AlertPayload(
                    severity="WARN", event="LIVENESS_PROBE_FAILED", site="global", detail=detail
                ),
            )

        print(
            f"{PROGRAM}: supervisor={supervisor_outcome.value} node={node_outcome.value}",
            file=out,
        )
        return EXIT_ABSENCE_REPORTED if absence_reported else EXIT_OK
    except Exception:  # a watchdog must never crash its own unit
        logger.exception("%s: internal error", PROGRAM)
        return EXIT_INTERNAL_ERROR
    finally:
        if active_sink is not None:
            _close_alert_sink(active_sink)


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run(sys.argv[1:], env=os.environ)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    raise SystemExit(main())
