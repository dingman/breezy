"""WP-B0 -- alert egress must be REAL, and its absence must be VISIBLE.

Every alert this system has ever emitted went to a log file nobody read:
``BREEZY_ALERT_WEBHOOK_URL`` is unset, so ``resolve_alert_sink`` silently
returns ``LoggingAlertSink``. A fee-schedule halt ran three days unnoticed
and a live-trading permit lapse ran eleven hours unnoticed -- both emitted,
neither delivered.

These tests pin the two halves of the fix that need no socket: the
queryable predicate plus the unmissable boot warning, and the
``breezy-check-alerts`` one-shot's contract. Real end-to-end delivery over
a real TLS socket lives in
``tests/integration/test_alert_webhook_delivery.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pytest

from breezy.runtime.check_alerts_cli import (
    CHECK_ALERT_EVENT,
    CHECK_ALERT_SITE,
    EXIT_DELIVERY_FAILED,
    EXIT_NOT_CONFIGURED,
    EXIT_OK,
    CheckAlertDetail,
    main,
)
from breezy.runtime.health import (
    ALERT_EGRESS_UNCONFIGURED_EVENT,
    ALERT_WEBHOOK_URL_ENV_VAR,
    ALLOWED_ALERT_PAYLOAD_KEYS,
    AlertPayload,
    LoggingAlertSink,
    WebhookAlertSink,
    alert_egress_configured,
    log_alert_egress_status,
    resolve_alert_sink,
)

_WEBHOOK_URL = "https://alerts.example.test/webhook"


class _RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class _FailingSink:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def emit(self, payload: AlertPayload) -> None:
        raise self._exc


# --------------------------------------------------------------------------
# The predicate
# --------------------------------------------------------------------------


def test_unset_env_means_logging_sink_and_egress_not_configured() -> None:
    env: Mapping[str, str] = {}
    assert isinstance(resolve_alert_sink(env), LoggingAlertSink)
    assert alert_egress_configured(env) is False


def test_empty_string_env_means_egress_not_configured() -> None:
    assert alert_egress_configured({ALERT_WEBHOOK_URL_ENV_VAR: ""}) is False


def test_set_env_means_webhook_sink_and_egress_configured() -> None:
    env = {ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL}
    sink = resolve_alert_sink(env)
    assert isinstance(sink, WebhookAlertSink)
    sink.close()
    assert alert_egress_configured(env) is True


def test_predicate_reads_the_process_environment_when_env_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ALERT_WEBHOOK_URL_ENV_VAR, raising=False)
    assert alert_egress_configured() is False
    monkeypatch.setenv(ALERT_WEBHOOK_URL_ENV_VAR, _WEBHOOK_URL)
    assert alert_egress_configured() is True


# --------------------------------------------------------------------------
# Boot visibility -- loud, never fatal
# --------------------------------------------------------------------------


def test_boot_emits_one_warning_naming_the_env_var_when_unconfigured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="breezy.runtime.health"):
        configured = log_alert_egress_status({}, component="trade_node")

    assert configured is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert ALERT_WEBHOOK_URL_ENV_VAR in message
    assert ALERT_EGRESS_UNCONFIGURED_EVENT in message
    assert "trade_node" in message
    assert "\n" not in message, "the boot warning must be a single line"


def test_boot_never_logs_the_webhook_url_itself(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The webhook URL is a bearer credential: possession authorises posting."""
    with caplog.at_level(logging.INFO, logger="breezy.runtime.health"):
        configured = log_alert_egress_status(
            {ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL}, component="trade_node"
        )

    assert configured is True
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    rendered = " ".join(r.getMessage() for r in caplog.records)
    assert "alerts.example.test" not in rendered
    assert _WEBHOOK_URL not in rendered


def test_unconfigured_egress_is_never_fatal_at_boot() -> None:
    """Fail loud, not closed: telemetry must never refuse to start the bot."""
    assert log_alert_egress_status({}, component="trade_supervisor") is False
    assert isinstance(resolve_alert_sink({}), LoggingAlertSink)


def test_supervisor_default_ports_warns_when_egress_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from breezy.runtime import trade_supervisor

    monkeypatch.delenv(ALERT_WEBHOOK_URL_ENV_VAR, raising=False)
    with caplog.at_level(logging.WARNING, logger="breezy.runtime.health"):
        ports = trade_supervisor.default_ports()

    assert isinstance(ports.alert_sink, LoggingAlertSink)
    assert any(
        ALERT_EGRESS_UNCONFIGURED_EVENT in r.getMessage() for r in caplog.records
    ), "the supervisor boot path must make silent alert degradation visible"


def test_ingest_composition_checks_alert_egress_at_boot() -> None:
    """The node's composition root must run the same visibility check."""
    from pathlib import Path

    source = Path(
        "src/breezy/runtime/composition.py"
    ).read_text(encoding="utf-8")
    assert "log_alert_egress_status" in source


# --------------------------------------------------------------------------
# The one-shot: breezy-check-alerts
# --------------------------------------------------------------------------


def test_check_alerts_exits_non_zero_when_no_egress_is_configured(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([], env={})
    assert code == EXIT_NOT_CONFIGURED
    assert code != EXIT_OK
    captured = capsys.readouterr()
    assert ALERT_WEBHOOK_URL_ENV_VAR in (captured.out + captured.err)
    assert "not delivered" in (captured.out + captured.err).lower()


def test_check_alerts_refuses_a_non_https_url_without_weakening_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([], env={ALERT_WEBHOOK_URL_ENV_VAR: "http://alerts.example.test/x"})
    assert code == EXIT_NOT_CONFIGURED
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "NOT DELIVERED" in combined
    assert "https" in combined
    # The refusal names the offending scheme, never the endpoint itself.
    assert "alerts.example.test" not in combined


def test_check_alerts_refuses_a_url_carrying_userinfo() -> None:
    code = main(
        [], env={ALERT_WEBHOOK_URL_ENV_VAR: "https://user:pass@alerts.example.test/x"}
    )
    assert code == EXIT_NOT_CONFIGURED


def test_check_alerts_sends_a_closed_enum_detail_through_the_sink() -> None:
    sink = _RecordingSink()
    code = main(
        [],
        env={ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL},
        sink_factory=lambda _env: sink,
    )

    assert code == EXIT_OK
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.event == CHECK_ALERT_EVENT
    assert payload.site == CHECK_ALERT_SITE
    assert payload.detail == CheckAlertDetail.OPERATOR_CHANNEL_TEST.value
    assert payload.detail in {member.value for member in CheckAlertDetail}
    assert set(payload.to_dict()) <= ALLOWED_ALERT_PAYLOAD_KEYS


def test_check_alerts_reports_not_delivered_when_the_sink_raises(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_ish = "https://hooks.example.test/T000/B111/zzSECRETzz"
    sink = _FailingSink(RuntimeError(f"POST {secret_ish} failed: bad token"))
    code = main(
        [],
        env={ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL},
        sink_factory=lambda _env: sink,
    )

    assert code == EXIT_DELIVERY_FAILED
    combined = capsys.readouterr()
    text = combined.out + combined.err
    assert "not delivered" in text.lower()
    # The exception text can carry the endpoint and its bearer path segment.
    assert secret_ish not in text
    assert "zzSECRETzz" not in text
    assert "RuntimeError" in text


def test_check_alerts_severity_choices_are_closed() -> None:
    sink = _RecordingSink()
    code = main(
        ["--severity", "CRITICAL"],
        env={ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL},
        sink_factory=lambda _env: sink,
    )
    assert code == EXIT_OK
    assert sink.payloads[0].severity == "CRITICAL"

    with pytest.raises(SystemExit):
        main(
            ["--severity", "definitely-not-a-severity"],
            env={ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL},
            sink_factory=lambda _env: sink,
        )
