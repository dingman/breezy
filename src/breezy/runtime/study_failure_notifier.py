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

**Cause lookup (alertcause 2026-09-27).** The one property this module's own
docstring above still calls "cause-agnostic" made every study failure read
identically -- in particular, quote-tape-ingest exit 4
(`EXIT_DEFERRAL_STALLED`) was indistinguishable from exits 2/3. The notifier
now reads the failed unit's ``ExecMainStatus``/``Result`` with a read-only
``systemctl --user show`` (:func:`_default_cause_reader`, mirroring
`quote_tape_ingest_cli.default_service_active_probe`'s own query-only,
never-signal convention) through an injectable seam
(:data:`CauseReader`/``cause_reader``), so tests never touch systemd. The
result lands on the plain log line as ``cause=<Result> exit=<code>`` -- for
``breezy-quote-tape-ingest.service`` the code is also named from the
constants `quote_tape_ingest_cli` already defines, never duplicated as a
literal. This is additive only: `AlertPayload.detail` stays the fixed enum
above, and the lookup fails OPEN (``cause=unknown``) on any read or parse
failure -- it must never suppress or delay the alert itself (L-52: a
detector without delivery is not a control).

**Never a heavy import (alertcause 2026-09-27 review fix).** The exit-code
constants above are imported from `breezy.runtime.quote_tape_exit_codes`, a
stdlib-only leaf module -- NOT from `quote_tape_ingest_cli` itself, which
pulls in `nautilus_trader` and `pyarrow` at import time. This module is the
LAST line of alert delivery; a broken Nautilus install or a syntax error
anywhere in the ingest module's import chain (exactly the kind of fault
that can make a study fail) must never crash the notifier before it can
send its alert.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
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
from breezy.runtime.quote_tape_exit_codes import (
    EXIT_CONVERSION_FAILED,
    EXIT_DEFERRAL_STALLED,
    EXIT_USAGE,
)
from breezy.runtime.quote_tape_exit_codes import PROGRAM as _QUOTE_TAPE_INGEST_PROGRAM

__all__ = [
    "STUDY_FAILED_ALERT_EVENT",
    "STUDY_FAILED_ALERT_SEVERITY",
    "STUDY_FAILED_ALERT_SITE",
    "CauseReader",
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

#: Injectable seam for the cause-of-failure read (alertcause 2026-09-27):
#: takes the failing unit's name, returns raw `systemctl --user show`
#: output. Tests inject a fake here rather than touching systemd; the real
#: default is :func:`_default_cause_reader`.
CauseReader = Callable[[str], str]

#: The one unit this module can currently name an exit code for. Built from
#: `quote_tape_ingest_cli.PROGRAM` rather than a literal, so it can never
#: silently drift from that module's own console-script name.
_QUOTE_TAPE_INGEST_UNIT: Final[str] = f"{_QUOTE_TAPE_INGEST_PROGRAM}.service"

#: Named exit codes for `breezy-quote-tape-ingest.service`, imported from
#: `quote_tape_ingest_cli` and never duplicated as literals here -- see the
#: module docstring's "Cause lookup" note.
_QUOTE_TAPE_INGEST_EXIT_NAMES: Final[Mapping[int, str]] = {
    EXIT_USAGE: "USAGE",
    EXIT_CONVERSION_FAILED: "CONVERSION_FAILED",
    EXIT_DEFERRAL_STALLED: "DEFERRAL_STALLED",
}


def _default_cause_reader(unit: str) -> str:
    """Read-only ``systemctl --user show`` for ``unit``'s last exit.

    Mirrors `quote_tape_ingest_cli.default_service_active_probe`'s own
    convention: this QUERIES state, sends no signal, and never restarts
    anything. Any failure to ask (missing systemctl, no user session,
    timeout, non-zero exit) propagates to the caller -- :func:`_cause_text`
    is the one place that catches it and falls open to ``cause=unknown``.
    """
    result = subprocess.run(
        ["systemctl", "--user", "show", unit, "-p", "ExecMainStatus", "-p", "Result"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return result.stdout


def _parse_cause(raw: str) -> tuple[str, int]:
    """``(Result, ExecMainStatus)`` parsed from ``systemctl --user show``'s
    ``Key=Value`` output. Raises on anything that doesn't look like that --
    the caller (:func:`_cause_text`) is the one place that catches it."""
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        key, sep, value = stripped.partition("=")
        if not sep:
            raise ValueError(f"unparseable systemctl show line: {stripped!r}")
        fields[key] = value
    return fields["Result"], int(fields["ExecMainStatus"])


def _cause_text(unit: str, *, cause_reader: CauseReader) -> str:
    """``cause=<Result> exit=<code>`` for the alert log line -- with a named
    exit code for `breezy-quote-tape-ingest.service` -- or ``cause=unknown``
    if the read fails or its output can't be parsed.

    Never raises: whatever :func:`_parse_cause` or ``cause_reader`` throws is
    caught here, broadly and intentionally (matching this module's own
    `except BaseException:` convention around `emit_alert` below), because
    the cause lookup must never suppress or delay the alert itself (L-52).
    The failure is still logged at ``debug`` -- diagnosable, but never at a
    level that competes with the WARN alert line itself.
    """
    try:
        result, exit_code = _parse_cause(cause_reader(unit))
    except BaseException:
        logger.debug("%s: cause lookup failed for unit=%s", _PROG, unit, exc_info=True)
        return "cause=unknown"
    name = _QUOTE_TAPE_INGEST_EXIT_NAMES.get(exit_code) if unit == _QUOTE_TAPE_INGEST_UNIT else None
    exit_part = f"exit={exit_code}" if name is None else f"exit={exit_code} ({name})"
    return f"cause={result} {exit_part}"


def notify_study_failed(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    sink_factory: SinkFactory | None = None,
    cause_reader: CauseReader = _default_cause_reader,
) -> int:
    """Emit exactly one WARN alert for the unit named by ``--unit``.

    ``sink_factory``, if given, replaces :func:`resolve_alert_sink` --
    tests inject a recording sink here rather than monkeypatching module
    state. ``cause_reader``, if given, replaces :func:`_default_cause_reader`
    -- see :data:`CauseReader`. Always returns ``0``: this process has no
    poll cycle and no caller that could do anything useful with a non-zero
    exit -- systemd would only log it, and `OnFailure=` chains are exactly
    the loop this design refuses to build (module docstring).
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
        "breezy study unit failed unit=%s event=%s %s",
        args.unit,
        STUDY_FAILED_ALERT_EVENT,
        _cause_text(args.unit, cause_reader=cause_reader),
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
