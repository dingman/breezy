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
    TeeAlertSink,
    WebhookAlertSink,
    alert_egress_configured,
    emit_alert,
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
    # [WP-B0a] Configured egress now TEES: the webhook AND the local log.
    # It is still true that a webhook sink is constructed -- it is no longer
    # true that the local log branch is discarded to make room for it.
    assert isinstance(sink, TeeAlertSink)
    assert any(isinstance(branch, WebhookAlertSink) for branch in sink.sinks)
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


# --------------------------------------------------------------------------
# WP-B0a -- the tee: delivery must not COST local diagnosability
#
# Regression measured in production on 2026-09-20. `resolve_alert_sink`
# returned EITHER `LoggingAlertSink` OR `WebhookAlertSink`, never both.
# While the webhook was unset every alert landed in the node log; the
# afternoon the webhook was configured the node log went from 10 `breezy
# alert` lines in the first ~51 minutes of uptime to ZERO, while 11 alerts
# were delivered to the webhook. The node log is the authoritative forensic
# record (it alone carries the boot-time permit line that proves order
# capability) and three incidents this week were diagnosed by reading it.
# Enabling delivery must never disable the local record.
# --------------------------------------------------------------------------


def test_configured_webhook_tees_to_the_local_log_and_the_webhook() -> None:
    """The regression itself: configured egress keeps the LOCAL record."""
    sink = resolve_alert_sink({ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL})
    try:
        assert isinstance(sink, TeeAlertSink)
        branch_types = [type(branch) for branch in sink.sinks]
        assert LoggingAlertSink in branch_types, (
            "configuring a webhook must not remove the local log branch -- "
            "that is exactly the regression this tee exists to prevent"
        )
        assert WebhookAlertSink in branch_types
    finally:
        sink.close()


def test_unset_webhook_is_exactly_todays_behaviour_bare_logging_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unconfigured stays byte-for-byte what it is today: log only."""
    import socket as socket_module

    from breezy.runtime import health as health_module

    def _no_client(*args: object, **kwargs: object) -> object:
        raise AssertionError("no webhook client may be constructed when unset")

    def _no_socket(*args: object, **kwargs: object) -> object:
        raise AssertionError("no socket may be opened when the webhook is unset")

    monkeypatch.setattr(health_module, "_build_webhook_client", _no_client)
    monkeypatch.setattr(socket_module, "socket", _no_socket)

    sink = resolve_alert_sink({})

    assert isinstance(sink, LoggingAlertSink)
    assert not isinstance(sink, TeeAlertSink)


def test_a_failing_webhook_branch_still_writes_the_local_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failure isolation A -- the webhook must not cost the log line."""
    tee = TeeAlertSink(
        LoggingAlertSink(), _FailingSink(RuntimeError("POST timed out"))
    )
    payload = AlertPayload(
        severity="CRITICAL",
        event="BREEZY_PERMIT_LAPSED",
        site="trade_node",
        detail="permit_lapsed",
    )

    with caplog.at_level(logging.INFO, logger="breezy.runtime.health"):
        emit_alert(tee, payload)  # must not raise

    rendered = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("breezy alert event=BREEZY_PERMIT_LAPSED") for message in rendered
    ), "a failing webhook branch suppressed the local forensic log line"


def test_a_failing_local_logger_branch_still_reaches_the_webhook() -> None:
    """Failure isolation B -- the log must not cost the delivery."""
    delivered = _RecordingSink()
    tee = TeeAlertSink(_FailingSink(RuntimeError("logging blew up")), delivered)
    payload = AlertPayload(
        severity="CRITICAL", event="BREEZY_FEE_SCHEDULE_HALT", site="trade_node", detail="halt"
    )

    emit_alert(tee, payload)  # must not raise

    assert delivered.payloads == [payload], (
        "a failing local branch suppressed webhook delivery"
    )


def test_a_baseexception_in_one_branch_neither_propagates_nor_suppresses() -> None:
    """`emit_alert` catches `BaseException` by design; the tee must too."""
    delivered = _RecordingSink()
    tee = TeeAlertSink(_FailingSink(KeyboardInterrupt()), delivered)
    payload = AlertPayload(severity="WARN", event="E", site="global", detail="d")

    emit_alert(tee, payload)

    assert delivered.payloads == [payload]


def test_the_tee_itself_never_propagates_even_when_every_branch_fails() -> None:
    tee = TeeAlertSink(_FailingSink(RuntimeError("a")), _FailingSink(RuntimeError("b")))

    emit_alert(tee, AlertPayload(severity="INFO", event="E", site="global", detail="d"))


def test_both_branches_receive_an_identical_allowlisted_payload() -> None:
    first, second = _RecordingSink(), _RecordingSink()
    tee = TeeAlertSink(first, second)
    payload = AlertPayload(
        severity="CRITICAL", event="BREEZY_STRUCTURAL_HALT", site="pm_us/KSFO", detail="x"
    )

    emit_alert(tee, payload)

    assert first.payloads[0] is second.payloads[0]
    assert first.payloads[0].to_dict() == second.payloads[0].to_dict()
    assert set(first.payloads[0].to_dict()) <= ALLOWED_ALERT_PAYLOAD_KEYS


def test_a_failing_webhook_branch_never_names_the_endpoint_in_its_own_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The webhook URL is a bearer credential; the tee adds no disclosure."""
    secretish = "hooks.example.test/T000/B111/zzSECRETzz"
    tee = TeeAlertSink(
        LoggingAlertSink(), _FailingSink(RuntimeError(f"POST https://{secretish} failed"))
    )

    with caplog.at_level(logging.INFO, logger="breezy.runtime.health"):
        emit_alert(tee, AlertPayload(severity="WARN", event="E", site="global", detail="d"))

    rendered = " ".join(record.getMessage() for record in caplog.records)
    assert "zzSECRETzz" not in rendered
    assert "hooks.example.test" not in rendered


def test_close_releases_every_branch_and_contains_a_failing_branch() -> None:
    class _ClosingSink:
        def __init__(self, *, fails: bool = False) -> None:
            self.closed = 0
            self._fails = fails

        def emit(self, payload: AlertPayload) -> None:  # pragma: no cover - unused
            raise AssertionError

        def close(self) -> None:
            self.closed += 1
            if self._fails:
                raise RuntimeError("close blew up")

    failing, healthy = _ClosingSink(fails=True), _ClosingSink()
    tee = TeeAlertSink(failing, LoggingAlertSink(), healthy)

    tee.close()  # must not raise, and must not stop at the failing branch

    assert failing.closed == 1
    assert healthy.closed == 1


@pytest.mark.parametrize(
    "env",
    [{}, {ALERT_WEBHOOK_URL_ENV_VAR: ""}, {ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL}],
)
def test_predicate_and_resolver_branch_on_the_same_condition(env: Mapping[str, str]) -> None:
    """The predicate and the behaviour must not be able to drift apart."""
    sink = resolve_alert_sink(env)
    try:
        assert alert_egress_configured(env) is isinstance(sink, TeeAlertSink)
    finally:
        close = getattr(sink, "close", None)
        if callable(close):
            close()
