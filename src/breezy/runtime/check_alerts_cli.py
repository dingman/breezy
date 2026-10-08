"""``breezy-check-alerts`` -- prove the operator's alert channel works.

[WP-B0] A SEPARATE, short-lived operator process, deliberately not a flag
on the node or the supervisor: it must be runnable on a host with no venue
configuration, it holds no credential, it touches no state store, and it
sends exactly ONE alert and exits. This is what an operator runs after
setting ``BREEZY_ALERT_WEBHOOK_URL`` to find out -- before an incident,
not during one -- whether anything actually arrives.

Exit contract:

* ``0`` -- delivered. The configured sink accepted the payload and the
  endpoint answered 2xx.
* ``2`` -- NOT CONFIGURED (or configured invalidly). No egress exists;
  nothing was sent off-box. This is the state the whole system was in.
* ``3`` -- CONFIGURED but NOT DELIVERED. Transport failure, TLS failure,
  timeout, or a non-2xx response.

**Production path (G26).** When no ``sink_factory`` is injected this tool
does not call ``sink.emit``. It calls ``deliver_with_proof``
(``attempt_kind="alert"``, writer ``check``) and exits
``EXIT_DELIVERY_FAILED`` iff that proof is not delivered. An injected
``sink_factory`` keeps the direct ``sink.emit`` path so a test double is
not forced through the journal.

**Nothing but the four allowlisted payload fields reaches the wire.** The
``detail`` is a closed-enum value (:class:`CheckAlertDetail`), never free
text; ``--severity`` is a closed choice set, never an arbitrary string.
On failure the exception's *type name* is reported locally and its message
is NOT: an ``httpx``/``ssl`` message routinely embeds the full request URL,
and that URL is a bearer credential this tool must not print into a
terminal, a shell history file, or a CI log.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Final, TextIO

from breezy.runtime.health import (
    ALERT_WEBHOOK_URL_ENV_VAR,
    AlertPayload,
    AlertSink,
    alert_egress_configured,
    resolve_alert_sink,
)

EXIT_OK: Final[int] = 0
EXIT_NOT_CONFIGURED: Final[int] = 2
EXIT_DELIVERY_FAILED: Final[int] = 3

#: The one event name this tool ever emits. Static, so an operator can
#: filter it out of a real incident channel by exact match.
CHECK_ALERT_EVENT: Final[str] = "BREEZY_ALERT_EGRESS_CHECK"

#: Never a real venue/city: this alert is about the operator's channel,
#: not about any trading site.
CHECK_ALERT_SITE: Final[str] = "operator_check"

#: Closed choice set for ``--severity`` -- mirrors
#: ``LoggingAlertSink._LEVEL_FOR_SEVERITY``'s own vocabulary.
_SEVERITIES: Final[tuple[str, ...]] = ("INFO", "WARN", "CRITICAL")

_PROG: Final[str] = "breezy-check-alerts"


class CheckAlertDetail(str, Enum):
    """Closed set of ``detail`` reasons this tool ever puts on the wire.

    Mirrors ``trade_supervisor_core.AlertDetail``'s stance exactly: never
    exception text, never a config/permit value, never a credential.
    """

    OPERATOR_CHANNEL_TEST = "operator_channel_test"


SinkFactory = Callable[[Mapping[str, str]], AlertSink]


def _close_quietly(sink: AlertSink) -> None:
    """Release a sink that owns a transport; duck-typed like composition's."""
    close = getattr(sink, "close", None)
    if callable(close):
        close()


def check_alerts(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    sink_factory: SinkFactory | None = None,
) -> int:
    """Send one test alert through the configured sink. See module docstring."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    source: Mapping[str, str] = os.environ if env is None else env

    parser = argparse.ArgumentParser(
        prog=_PROG,
        description="Send one test alert through the configured alert sink.",
    )
    parser.add_argument(
        "--severity",
        choices=_SEVERITIES,
        default="INFO",
        help="severity of the test alert (default: INFO)",
    )
    args = parser.parse_args(argv)

    if not alert_egress_configured(source):
        print(
            f"{_PROG}: NOT DELIVERED -- no alert egress is configured. "
            f"{ALERT_WEBHOOK_URL_ENV_VAR} is unset, so every alert this system "
            f"emits reaches the log only and no operator.",
            file=err,
        )
        return EXIT_NOT_CONFIGURED

    build = resolve_alert_sink if sink_factory is None else sink_factory
    try:
        sink = build(source)
    except ValueError as exc:
        # `_validate_webhook_url`'s messages name the env var and the
        # offending *scheme*, never the URL itself.
        print(f"{_PROG}: NOT DELIVERED -- {exc}", file=err)
        return EXIT_NOT_CONFIGURED

    payload = AlertPayload(
        severity=args.severity,
        event=CHECK_ALERT_EVENT,
        site=CHECK_ALERT_SITE,
        detail=CheckAlertDetail.OPERATOR_CHANNEL_TEST.value,
    )
    if sink_factory is None:
        return _deliver_with_proof(sink, payload, out=out, err=err)
    try:
        try:
            sink.emit(payload)
        except BaseException as exc:  # noqa: BLE001 - the failure IS the answer.
            print(
                f"{_PROG}: NOT DELIVERED -- the sink raised "
                f"{type(exc).__name__} (message withheld: it can embed the "
                f"webhook URL). Check {ALERT_WEBHOOK_URL_ENV_VAR} and the "
                f"endpoint's response.",
                file=err,
            )
            return EXIT_DELIVERY_FAILED
    finally:
        _close_quietly(sink)

    print(
        f"{_PROG}: delivered -- event={CHECK_ALERT_EVENT} "
        f"severity={args.severity} detail={CheckAlertDetail.OPERATOR_CHANNEL_TEST.value}",
        file=out,
    )
    return EXIT_OK


def _deliver_with_proof(
    sink: AlertSink,
    payload: AlertPayload,
    *,
    out: TextIO,
    err: TextIO,
) -> int:
    """G26: the production verdict is the delivery proof, not ``sink.emit``."""
    import breezy.runtime.alert_delivery as delivery

    root = delivery.default_alerts_root()
    try:
        proof = delivery.deliver_with_proof(
            sink,
            payload,
            writer="check",
            records=delivery.DeliveryRecordWriter(root),
            attempt_kind="alert",
            outbox=delivery.AlertOutbox(root),
        )
    except Exception as exc:  # noqa: BLE001 - the failure IS the answer
        print(
            f"{_PROG}: NOT DELIVERED -- {type(exc).__name__} "
            f"(message withheld: it can embed the webhook URL).",
            file=err,
        )
        return EXIT_DELIVERY_FAILED
    finally:
        _close_quietly(sink)
    if not proof.delivered:
        print(f"{_PROG}: NOT DELIVERED -- status_class={proof.status_class}", file=err)
        return EXIT_DELIVERY_FAILED
    print(
        f"{_PROG}: delivered -- event={CHECK_ALERT_EVENT} "
        f"severity={payload.severity} detail={CheckAlertDetail.OPERATOR_CHANNEL_TEST.value}",
        file=out,
    )
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    sink_factory: SinkFactory | None = None,
) -> int:
    """Console-script entrypoint. The one caller of :func:`check_alerts`."""
    return check_alerts(argv, env=env, stdout=stdout, stderr=stderr, sink_factory=sink_factory)


if __name__ == "__main__":
    raise SystemExit(main())
