"""WP-B0 -- PROOF that a CRITICAL alert leaves this process over a socket.

Not a mock, not ``respx``, not a test double: a real ``http.server``
wrapped in a real ``ssl`` server context, bound to ``127.0.0.1`` on an
ephemeral port, receiving real TLS-encrypted HTTP from the real
``WebhookAlertSink`` -> ``httpx`` stack. The assertion is made on the bytes
the RECEIVER took off the wire -- an out-of-process artefact, not a log
line.

**What this does and does not prove.** ``WebhookAlertSink`` requires
``https`` and that validation is NOT relaxed here: the sink is constructed
from a genuine ``https://127.0.0.1:<port>/alerts`` URL and runs the same
scheme/userinfo/hostname validation production runs. The ONE difference
from production is the trust anchor -- the injected ``httpx.Client`` is
given the throwaway CA minted for the test instead of the system store,
because no public CA will issue for a loopback listener. So this proves:
URL validation, TLS 1.2+ negotiation with hostname verification and
``CERT_REQUIRED``, JSON serialisation, the POST, the receiver's parse, the
non-2xx and timeout containment, and the payload allowlist. It does NOT
prove that a *public* endpoint's certificate chains to a system root, nor
anything about a specific vendor's webhook API shape.

The suite runs inside a bubblewrap network namespace whose only interface
is loopback (``scripts/ci/run_tests_no_egress.sh``), so this test cannot
reach off-box even if it tried.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from breezy.runtime.check_alerts_cli import EXIT_DELIVERY_FAILED, EXIT_OK
from breezy.runtime.check_alerts_cli import main as check_alerts_main
from breezy.runtime.health import (
    ALERT_WEBHOOK_URL_ENV_VAR,
    ALLOWED_ALERT_PAYLOAD_KEYS,
    AlertPayload,
    WebhookAlertSink,
    emit_alert,
)
from tests.support.loopback_https import (
    TlsMaterial,
    client_ssl_context,
    generate_loopback_tls_material,
    loopback_https_receiver,
)

pytestmark = pytest.mark.allow_socket


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> TlsMaterial:
    directory: Path = tmp_path_factory.mktemp("alert-egress-tls")
    return generate_loopback_tls_material(directory)


def _sink_for(url: str, material: TlsMaterial, *, timeout_s: float = 5.0) -> WebhookAlertSink:
    client = httpx.Client(
        verify=client_ssl_context(material),
        follow_redirects=False,
        trust_env=False,
        timeout=timeout_s,
    )
    return WebhookAlertSink(url, client=client)


@pytest.fixture()
def critical_payload() -> AlertPayload:
    return AlertPayload(
        severity="CRITICAL",
        event="BREEZY_FEE_SCHEDULE_HALT",
        site="trade_node",
        detail="self_check_fail_not_ready",
    )


def test_a_critical_alert_reaches_a_real_loopback_https_receiver(
    tls_material: TlsMaterial, critical_payload: AlertPayload
) -> None:
    with loopback_https_receiver(tls_material) as receiver:
        sink = _sink_for(receiver.url, tls_material)
        try:
            emit_alert(sink, critical_payload)
        finally:
            sink.close()

        assert len(receiver.received) == 1, "the alert never left the process"
        request = receiver.received[0]

    assert request.method == "POST"
    assert request.path == "/alerts"
    assert request.headers["content-type"].startswith("application/json")
    assert request.json_body() == {
        "severity": "CRITICAL",
        "event": "BREEZY_FEE_SCHEDULE_HALT",
        "site": "trade_node",
        "detail": "self_check_fail_not_ready",
    }


def test_the_delivered_payload_carries_exactly_the_allowlisted_keys(
    tls_material: TlsMaterial, critical_payload: AlertPayload
) -> None:
    with loopback_https_receiver(tls_material) as receiver:
        sink = _sink_for(receiver.url, tls_material)
        try:
            emit_alert(sink, critical_payload)
        finally:
            sink.close()
        body = receiver.received[0].json_body()

    assert set(body) == set(ALLOWED_ALERT_PAYLOAD_KEYS)


def test_no_credential_config_or_permit_value_can_reach_the_wire(
    tls_material: TlsMaterial, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The payload leaves the machine. Nothing but the four fields may ride."""
    poison = "zzPOISONzz-api-key-value"
    monkeypatch.setenv("BREEZY_POLYMARKET_US_API_KEY", poison)
    monkeypatch.setenv("BREEZY_USER_AGENT_CONTACT", poison)

    payload = AlertPayload(
        severity="WARN",
        event="BREEZY_PERMIT_LAPSED",
        site="trade_node",
        detail="self_check_fail_shadow_mode_no_permit",
    )
    with loopback_https_receiver(tls_material) as receiver:
        sink = _sink_for(receiver.url, tls_material)
        try:
            emit_alert(sink, payload)
        finally:
            sink.close()
        raw = receiver.received[0].body

    assert poison.encode() not in raw
    decoded = json.loads(raw.decode("utf-8"))
    assert set(decoded) == set(ALLOWED_ALERT_PAYLOAD_KEYS)
    assert all(isinstance(value, str) for value in decoded.values())


def test_a_receiver_that_500s_does_not_propagate_past_emit_alert(
    tls_material: TlsMaterial,
    critical_payload: AlertPayload,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with loopback_https_receiver(tls_material, status_code=500) as receiver:
        sink = _sink_for(receiver.url, tls_material)
        try:
            with caplog.at_level(logging.ERROR, logger="breezy.runtime.health"):
                emit_alert(sink, critical_payload)  # must not raise
        finally:
            sink.close()
        assert len(receiver.received) == 1

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "alert sink failed to emit" in errors[0].getMessage()


def test_a_receiver_that_times_out_does_not_propagate_past_emit_alert(
    tls_material: TlsMaterial,
    critical_payload: AlertPayload,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with loopback_https_receiver(tls_material, response_delay_s=2.0) as receiver:
        sink = _sink_for(receiver.url, tls_material, timeout_s=0.25)
        try:
            with caplog.at_level(logging.ERROR, logger="breezy.runtime.health"):
                emit_alert(sink, critical_payload)  # must not raise
        finally:
            sink.close()

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1


def test_the_https_validation_still_rejects_a_plain_http_receiver() -> None:
    with pytest.raises(ValueError, match="https"):
        WebhookAlertSink("http://127.0.0.1:9/alerts")


def test_check_alerts_one_shot_reports_delivered_against_a_real_receiver(
    tls_material: TlsMaterial, capsys: pytest.CaptureFixture[str]
) -> None:
    with loopback_https_receiver(tls_material) as receiver:
        code = check_alerts_main(
            [],
            env={ALERT_WEBHOOK_URL_ENV_VAR: receiver.url},
            sink_factory=lambda _env: _sink_for(receiver.url, tls_material),
        )
        assert len(receiver.received) == 1
        body = receiver.received[0].json_body()

    assert code == EXIT_OK
    assert "delivered" in capsys.readouterr().out.lower()
    assert body["event"] == "BREEZY_ALERT_EGRESS_CHECK"
    assert set(body) == set(ALLOWED_ALERT_PAYLOAD_KEYS)


def test_check_alerts_one_shot_exits_non_zero_when_the_receiver_500s(
    tls_material: TlsMaterial, capsys: pytest.CaptureFixture[str]
) -> None:
    with loopback_https_receiver(tls_material, status_code=500) as receiver:
        code = check_alerts_main(
            [],
            env={ALERT_WEBHOOK_URL_ENV_VAR: receiver.url},
            sink_factory=lambda _env: _sink_for(receiver.url, tls_material),
        )
        assert len(receiver.received) == 1

    assert code == EXIT_DELIVERY_FAILED
    assert code != EXIT_OK
    assert "not delivered" in (capsys.readouterr().err).lower()
