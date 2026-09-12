"""RED/GREEN coverage for ``breezy.runtime.alert_test_cli`` (SP-6 A4, row 8)."""

from __future__ import annotations

import io

import pytest

from breezy.runtime import alert_test_cli
from breezy.runtime.health import AlertPayload, LoggingAlertSink


class _FakeSink:
    def __init__(self) -> None:
        self.received: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.received.append(payload)


def test_emits_one_info_alert_through_the_resolved_sink() -> None:
    sink = _FakeSink()
    out = io.StringIO()

    exit_code = alert_test_cli.run([], sink=sink, stdout=out)

    assert exit_code == alert_test_cli.EXIT_OK
    assert len(sink.received) == 1
    payload = sink.received[0]
    assert payload.severity == "INFO"
    assert payload.event == alert_test_cli.TEST_ALERT_EVENT
    assert payload.site == alert_test_cli.TEST_ALERT_SITE


def test_exit_2_when_require_webhook_and_sink_is_logging() -> None:
    out = io.StringIO()

    exit_code = alert_test_cli.run(["--require-webhook"], sink=LoggingAlertSink(), stdout=out)

    assert exit_code == alert_test_cli.EXIT_NOT_CONFIGURED


def test_never_prints_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://example.invalid/some-secret-token"
    monkeypatch.setenv("BREEZY_ALERT_WEBHOOK_URL", url)
    sink = _FakeSink()  # inject a fake so resolve_alert_sink's own branch is bypassed
    out = io.StringIO()

    alert_test_cli.run([], sink=sink, stdout=out)

    assert url not in out.getvalue()


def test_exit_zero_is_documented_as_not_delivery_proof() -> None:
    assert "NOT delivery proof" in (alert_test_cli.run.__doc__ or "") or "NOT delivery proof" in (
        alert_test_cli.__doc__ or ""
    )
