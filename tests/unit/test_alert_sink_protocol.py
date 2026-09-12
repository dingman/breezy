"""RED/GREEN coverage for the `AlertSink` structural protocol (SP-6 A2,
architect confirmation row 10b).

`AlertSink` (`runtime/health.py`) is a plain `typing.Protocol`, not
`@runtime_checkable` -- so mypy enforces conformance at every call site,
but nothing at runtime previously exercised the actual DUCK-TYPING
contract: any object exposing `emit(payload) -> None`, with no required
base class, must be accepted by `emit_alert` and by every installer that
takes a `sink=` kwarg. These tests exercise that at runtime, not just via
mypy.
"""

from __future__ import annotations

import pytest

from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    LoggingAlertSink,
    WebhookAlertSink,
    emit_alert,
)

_PAYLOAD = AlertPayload(severity="WARN", event="test_event", site="global", detail="ok")


def test_logging_alert_sink_satisfies_the_protocol() -> None:
    sink: AlertSink = LoggingAlertSink()
    assert hasattr(sink, "emit")
    assert callable(sink.emit)
    sink.emit(_PAYLOAD)  # never raises


def test_webhook_alert_sink_satisfies_the_protocol() -> None:
    sink: AlertSink = WebhookAlertSink("https://alerts.example.invalid/webhook")
    assert hasattr(sink, "emit")
    assert callable(sink.emit)


def test_a_bare_duck_typed_object_with_no_shared_base_class_satisfies_the_protocol() -> None:
    """`AlertSink` is structural: an object needs no inheritance
    relationship to either shipped sink to be accepted everywhere a
    `sink=` kwarg is threaded."""

    class _MinimalSink:
        def __init__(self) -> None:
            self.received: list[AlertPayload] = []

        def emit(self, payload: AlertPayload) -> None:
            self.received.append(payload)

    sink: AlertSink = _MinimalSink()
    emit_alert(sink, _PAYLOAD)
    assert sink.received == [_PAYLOAD]  # type: ignore[attr-defined]


def test_emit_alert_never_requires_a_shared_base_class() -> None:
    """`emit_alert` (the ONLY sanctioned call path to any sink, per
    `health.py`'s own containment contract) dispatches purely by calling
    `.emit` -- confirmed by a sink whose class shares nothing with
    `LoggingAlertSink`/`WebhookAlertSink` beyond the one method."""

    class _OtherMinimalSink:
        def emit(self, payload: AlertPayload) -> None:
            del payload

    emit_alert(_OtherMinimalSink(), _PAYLOAD)  # never raises


def test_an_object_missing_emit_fails_at_the_direct_call_not_earlier() -> None:
    """`AlertSink` is not `@runtime_checkable`, so nothing catches a
    non-conforming object before it is actually used: calling `.emit`
    directly on one raises `AttributeError` at the call site."""

    class _NotASink:
        pass

    with pytest.raises(AttributeError):
        _NotASink().emit(_PAYLOAD)  # type: ignore[attr-defined]


def test_emit_alert_contains_even_a_non_conforming_sink() -> None:
    """`emit_alert`'s `BaseException` containment (its own docstring: "a
    failure here is logged at ERROR ... and swallowed") means a
    non-conforming sink cannot crash the caller either -- the SAME
    containment guarantee applies whether the failure is a network error
    or simply a missing `emit`."""

    class _NotASink:
        pass

    emit_alert(_NotASink(), _PAYLOAD)  # type: ignore[arg-type]  # never raises
