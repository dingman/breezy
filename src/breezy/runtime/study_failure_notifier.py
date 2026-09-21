"""``breezy-study-failed`` -- ``OnFailure=`` alert path for study units (AUD-15a).

**The gap this closes.** No unit in `deploy/systemd/` declared `OnFailure=`,
so a study that timed out, was OOM-killed, or exited non-zero landed in
`failed` and alerted nobody -- `breezy-mb-daily.service` and
`breezy-offer-gate-daily.service` both did this for days before anyone
noticed (`docs/plans/backlog/AUDIT_2026-09-21/AUD-15-...md` §2).

**Null hypothesis, checked.** The alerting mechanism already exists
(`AlertPayload`/`emit_alert`/`resolve_alert_sink`, this package's own
`health.py`) and is reused verbatim -- this module is only the console
entry point `deploy/systemd/breezy-study-failed@.service` execs, mirroring
`breezy.runtime.check_alerts_cli`'s shape (a short-lived, single-purpose
process that never touches state, never holds a credential, and returns 0
unconditionally).

**Cause-agnostic by design.** `OnFailure=` fires identically whether the
failing unit hit `TimeoutStartSec`, was OOM-killed by its own `MemoryMax`,
or exited non-zero for any other reason -- this notifier does not need to
know which.

**WARN, not CRITICAL.** A study is not the trading path; CRITICAL is
reserved for conditions that mean the node is not trading
(`component_health_watch.py`'s own `DEGRADED_ALERT_SEVERITY` docstring).

**No alert loop.** The template unit `breezy-study-failed@.service` itself
declares no `OnFailure=` and no `Restart=` -- if the notifier instance
itself fails, that is a silent residual (it lands in `failed` and is
visible in `systemctl --user list-units --all`, but nothing pages on it),
accepted rather than closed with a second-order watchdog that would
reintroduce the very loop this design refuses.

**The failed unit's name never reaches the alert payload's `detail`.**
`AlertPayload.detail` is a fixed enum string, matching every other
alert-detail contract in this repo (`trade_supervisor_core.AlertDetail`,
`check_alerts_cli.CheckAlertDetail`) -- never exception text, never journal
text, never a value-bearing string. The unit name travels on the plain log
line instead, as its own structured field, which is where an operator or a
log-aggregation pipeline actually wants it.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Final

from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    emit_alert,
    log_alert_egress_status,
    resolve_alert_sink,
)

__all__ = [
    "STUDY_FAILED_ALERT_EVENT",
    "STUDY_FAILED_ALERT_SEVERITY",
    "STUDY_FAILED_ALERT_SITE",
    "StudyFailedDetail",
    "main",
    "notify_study_failed",
]

logger = logging.getLogger(__name__)

_PROG: Final[str] = "breezy-study-failed"

#: The one `AlertPayload.event` this module ever emits -- an operator
#: filtering on it gets every failed study unit and nothing else.
STUDY_FAILED_ALERT_EVENT: Final[str] = "study_unit_failed"

#: WARN, not CRITICAL -- see module docstring.
STUDY_FAILED_ALERT_SEVERITY: Final[str] = "WARN"

#: A study unit is host-wide, not tied to a venue/city, matching
#: `component_health_watch.DEGRADED_ALERT_SITE`'s own convention.
STUDY_FAILED_ALERT_SITE: Final[str] = "global"


class StudyFailedDetail(str, Enum):
    """Closed set of ``detail`` values this notifier ever puts on the wire.

    Exactly one member today: every study unit failure is reported
    identically, regardless of cause (timeout, OOM-kill, non-zero exit) --
    see the module docstring's "cause-agnostic" note.
    """

    STUDY_UNIT_REACHED_FAILED_STATE = "study_unit_reached_failed_state"


#: AUD-15 amendment (2026-09-22): was `Mapping[str, str]` -- unused and
#: wrong-shaped; a sink factory takes the environment mapping and RETURNS a
#: sink, matching `check_alerts_cli.SinkFactory`'s own (correct) shape.
SinkFactory = Callable[[Mapping[str, str]], AlertSink]


def notify_study_failed(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    sink_factory: SinkFactory | None = None,
) -> int:
    """Emit exactly one WARN alert for the unit named by ``--unit``.

    ``sink_factory``, if given, replaces :func:`resolve_alert_sink` --
    tests inject a recording sink here rather than monkeypatching module
    state. Always returns ``0``: this process has no poll cycle and no
    caller that could do anything useful with a non-zero exit -- systemd
    would only log it, and `OnFailure=` chains are exactly the loop this
    design refuses to build (module docstring).
    """
    source: Mapping[str, str] = os.environ if env is None else env
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description="Emit one alert for a study unit that reached `failed`.",
    )
    parser.add_argument(
        "--unit",
        required=True,
        help="the failing unit's name, from systemd's own %%n expansion",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # A malformed invocation must never propagate a non-zero exit into
        # systemd (module docstring) -- log it and stop, rather than let
        # argparse's own SystemExit escape.
        logger.error("%s: invalid arguments: %r", _PROG, argv)
        return 0

    logger.warning(
        "breezy study unit failed unit=%s event=%s",
        args.unit,
        STUDY_FAILED_ALERT_EVENT,
    )

    # AUD-15 amendment (2026-09-22): runtime visibility BEFORE resolving the
    # sink -- a missing/empty alerts.env (the study units' declared
    # `EnvironmentFile=-%h/.config/breezy/alerts.env`) must leave a distinct
    # journal line on every invocation, not just a silently-downgraded
    # LoggingAlertSink. This is what closes the gap the hermetic
    # `resolve_alert_sink` unit test cannot: that test proves the function
    # is correct for a given env; this proves the DECLARED env is checked at
    # runtime, every time.
    log_alert_egress_status(source, component=_PROG)

    try:
        build = resolve_alert_sink if sink_factory is None else sink_factory
        sink: AlertSink = build(source)
        payload = AlertPayload(
            severity=STUDY_FAILED_ALERT_SEVERITY,
            event=STUDY_FAILED_ALERT_EVENT,
            site=STUDY_FAILED_ALERT_SITE,
            detail=StudyFailedDetail.STUDY_UNIT_REACHED_FAILED_STATE.value,
        )
        emit_alert(sink, payload)
    except BaseException:
        logger.exception("%s: failed to emit the study-failure alert", _PROG)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console-script entrypoint. The one caller of :func:`notify_study_failed`."""
    try:
        return notify_study_failed(argv)
    except BaseException:
        logger.exception("%s: unexpected failure", _PROG)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
