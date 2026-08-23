"""Tests for the health snapshot + alert sink (src/breezy/runtime/health.py).

WI-12. See docs/plans/PHASE_CD_COLLECTION_DURABILITY_DESIGN.md §4 for the
authoritative design this file pins.

Zero network I/O anywhere in this file: `WebhookAlertSink` tests use
`respx`, which intercepts at the `httpx` transport layer -- before any
socket opens -- exactly like `tests/unit/test_http_transport.py` already
does for `HttpTransport`. No test constructs a real URL a client could
actually connect to.

No hard-coded absolute dates: every timestamp is an integer nanosecond
offset from an arbitrary local `_START_NS`, never a wall-clock read.
"""

from __future__ import annotations

import json
import os
import ssl
import stat
from pathlib import Path

import httpx
import pytest
import respx

from breezy.runtime.health import (
    ALERT_WEBHOOK_URL_ENV_VAR,
    ALLOWED_ALERT_PAYLOAD_KEYS,
    DEFAULT_RENOTIFY_AFTER_NS,
    SCHEMA_VERSION,
    AlertCondition,
    AlertConditionKey,
    AlertPayload,
    AlertState,
    GapSummary,
    HealthSnapshot,
    LoggingAlertSink,
    SiteHealth,
    WebhookAlertSink,
    emit_alert,
    resolve_alert_sink,
    write_snapshot_atomic,
)

_START_NS = 1_700_000_000_000_000_000
_SECOND_NS = 1_000_000_000
_WEBHOOK_URL = "https://alerts.example.test/webhook"

# A sentinel standing in for "the operator's configured user_agent_contact
# value", e.g. `breezy.ingest.http.DEFAULT_CONTACT` or a
# `BREEZY_USER_AGENT` override. health.py never accepts or imports a
# settings object at all, so this sentinel is never threaded into any
# constructor below -- the tests prove it therefore cannot appear in the
# serialized output.
_USER_AGENT_CONTACT_SENTINEL = "breezy-data@gmail.com"


class _FakeSink:
    """Records every payload handed to `emit`; optionally raises."""

    def __init__(self, *, raises: BaseException | None = None) -> None:
        self.received: list[AlertPayload] = []
        self._raises = raises

    def emit(self, payload: AlertPayload) -> None:
        self.received.append(payload)
        if self._raises is not None:
            raise self._raises


def _gap(day: str = "2026-08-01", *, state: str = "OPEN", severity: str = "WARN") -> GapSummary:
    return GapSummary(climate_day=day, state=state, severity=severity, days_until_retention_loss=3)


def _site(
    *,
    venue: str = "polymarket_us",
    city: str = "NYC",
    gate_state: str = "OPEN",
    gate_reason: str = "successful_poll",
    blocking_causes: tuple[str, ...] = (),
    last_successful_poll_ns: int | None = _START_NS,
    cursor: str | None = "cursor-abc",
    open_gaps: tuple[GapSummary, ...] = (),
    acknowledged_lost_count: int = 0,
) -> SiteHealth:
    return SiteHealth(
        venue=venue,
        city=city,
        gate_state=gate_state,
        gate_reason=gate_reason,
        blocking_causes=blocking_causes,
        last_successful_poll_ns=last_successful_poll_ns,
        cursor=cursor,
        open_gaps=open_gaps,
        acknowledged_lost_count=acknowledged_lost_count,
    )


def _snapshot(
    *,
    sites: tuple[SiteHealth, ...] = (),
    ua_trap_latched: bool = False,
    alerts_emitted_this_cycle: int = 0,
    trader_id: str = "BREEZY-001",
) -> HealthSnapshot:
    return HealthSnapshot(
        schema_version=SCHEMA_VERSION,
        process_started_at_ns=_START_NS,
        snapshot_at_ns=_START_NS + _SECOND_NS,
        trader_id=trader_id,
        sites=sites,
        ua_trap_latched=ua_trap_latched,
        alerts_emitted_this_cycle=alerts_emitted_this_cycle,
    )


# --------------------------------------------------------------------------
# Snapshot fields
# --------------------------------------------------------------------------


def test_snapshot_to_dict_carries_every_declared_field() -> None:
    site = _site(open_gaps=(_gap(),))
    snapshot = _snapshot(sites=(site,), ua_trap_latched=True, alerts_emitted_this_cycle=2)

    payload = snapshot.to_dict()

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["process_started_at_ns"] == _START_NS
    assert payload["snapshot_at_ns"] == _START_NS + _SECOND_NS
    assert payload["trader_id"] == "BREEZY-001"
    assert payload["ua_trap_latched"] is True
    assert payload["alerts_emitted_this_cycle"] == 2

    (site_payload,) = payload["sites"]  # type: ignore[index]
    assert site_payload["venue"] == "polymarket_us"
    assert site_payload["city"] == "NYC"
    assert site_payload["gate_state"] == "OPEN"
    assert site_payload["gate_reason"] == "successful_poll"
    assert site_payload["blocking_causes"] == []
    assert site_payload["last_successful_poll_ns"] == _START_NS
    assert site_payload["cursor"] == "cursor-abc"
    assert site_payload["acknowledged_lost_count"] == 0

    (gap_payload,) = site_payload["open_gaps"]
    assert gap_payload == {
        "climate_day": "2026-08-01",
        "state": "OPEN",
        "severity": "WARN",
        "days_until_retention_loss": 3,
    }


def test_snapshot_json_round_trips_through_json_dumps() -> None:
    snapshot = _snapshot(sites=(_site(open_gaps=(_gap(),)),))

    text = json.dumps(snapshot.to_dict())
    decoded = json.loads(text)

    assert decoded["schema_version"] == SCHEMA_VERSION
    assert decoded["sites"][0]["cursor"] == "cursor-abc"


def test_health_snapshot_slots_reject_arbitrary_attribute_injection() -> None:
    """`slots=True` forecloses attaching a settings-shaped attribute at all.

    This is the strongest available proof that `user_agent_contact` (or an
    absolute filesystem path, or any other field this module was never
    told about) cannot reach a `HealthSnapshot` instance, let alone its
    serialized JSON: there is no `__dict__` and no declared slot to hold
    it.
    """
    snapshot = _snapshot()

    with pytest.raises(AttributeError):
        object.__setattr__(snapshot, "user_agent_contact", _USER_AGENT_CONTACT_SENTINEL)


def test_snapshot_json_excludes_user_agent_contact() -> None:
    """`health.py` never accepts a settings object or a `user_agent_contact`
    value anywhere in its public API, so a realistic, fully-populated
    snapshot's JSON can never contain the sentinel below -- proven here by
    construction rather than by mocking anything out.
    """
    snapshot = _snapshot(
        sites=(
            _site(
                gate_reason="cross_check_unavailable",
                blocking_causes=("acis_disagreement", "cross_check_unavailable"),
                open_gaps=(_gap(),),
            ),
        ),
        ua_trap_latched=True,
    )

    text = json.dumps(snapshot.to_dict())

    assert _USER_AGENT_CONTACT_SENTINEL not in text


# --------------------------------------------------------------------------
# Atomic write
# --------------------------------------------------------------------------


def test_write_snapshot_atomic_writes_readable_json(tmp_path: Path) -> None:
    target = tmp_path / "health.json"
    snapshot = _snapshot(sites=(_site(),))

    write_snapshot_atomic(target, snapshot)

    assert json.loads(target.read_text())["trader_id"] == "BREEZY-001"


def test_write_snapshot_atomic_file_mode_is_0600(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "health.json"
    write_snapshot_atomic(target, _snapshot())

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_write_snapshot_atomic_no_temp_file_left_after_success(tmp_path: Path) -> None:
    target = tmp_path / "health.json"
    write_snapshot_atomic(target, _snapshot())

    leftovers = list(tmp_path.glob(".health-snapshot-*"))
    assert leftovers == []


def test_write_snapshot_atomic_partial_write_never_observable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure inside `os.replace` must leave the old file untouched and
    must not leave a temp file behind.
    """
    target = tmp_path / "health.json"
    write_snapshot_atomic(target, _snapshot(trader_id="ORIGINAL"))
    original_bytes = target.read_bytes()

    def _boom(_src: object, _dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_snapshot_atomic(target, _snapshot(trader_id="SHOULD-NOT-LAND"))

    assert target.read_bytes() == original_bytes
    leftovers = list(tmp_path.glob(".health-snapshot-*"))
    assert leftovers == []


def test_write_snapshot_atomic_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "dir" / "health.json"
    write_snapshot_atomic(target, _snapshot())

    assert target.exists()


# --------------------------------------------------------------------------
# AlertPayload
# --------------------------------------------------------------------------


def test_alert_payload_keys_are_within_the_allowlist() -> None:
    payload = AlertPayload(
        severity="WARN", event="site_blocked", site="polymarket_us/NYC", detail="x"
    )

    assert set(payload.to_dict()) <= ALLOWED_ALERT_PAYLOAD_KEYS
    assert set(payload.to_dict()) == ALLOWED_ALERT_PAYLOAD_KEYS


def test_alert_payload_detail_is_truncated() -> None:
    payload = AlertPayload(severity="INFO", event="e", site="global", detail="x" * 500)

    assert len(payload.detail) == 200


# --------------------------------------------------------------------------
# emit_alert containment -- the single most important test in the module
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("boom"),
        ssl.SSLError("certificate verify failed"),
        httpx.TimeoutException("timed out"),
        httpx.TransportError("connection reset"),
        KeyboardInterrupt(),
    ],
)
def test_emit_alert_never_propagates_sink_failures(exc: BaseException) -> None:
    sink = _FakeSink(raises=exc)
    payload = AlertPayload(severity="CRITICAL", event="e", site="global", detail="d")

    emit_alert(sink, payload)  # must not raise

    assert sink.received == [payload]


def test_emit_alert_calls_a_healthy_sink_normally() -> None:
    sink = _FakeSink()
    payload = AlertPayload(severity="INFO", event="e", site="global", detail="d")

    emit_alert(sink, payload)

    assert sink.received == [payload]


# --------------------------------------------------------------------------
# LoggingAlertSink
# --------------------------------------------------------------------------


def test_logging_alert_sink_logs_at_expected_level(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="breezy.runtime.health")
    sink = LoggingAlertSink()
    payload = AlertPayload(severity="CRITICAL", event="ua_trap", site="global", detail="latched")

    sink.emit(payload)

    assert any("ua_trap" in record.message for record in caplog.records)


def test_logging_alert_sink_falls_back_to_warning_for_unknown_severity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="breezy.runtime.health")
    sink = LoggingAlertSink()
    payload = AlertPayload(severity="WEIRD", event="e", site="global", detail="d")

    sink.emit(payload)

    assert any(record.levelname == "WARNING" for record in caplog.records)


# --------------------------------------------------------------------------
# WebhookAlertSink construction gating
# --------------------------------------------------------------------------


def test_resolve_alert_sink_returns_logging_sink_when_env_var_unset() -> None:
    sink = resolve_alert_sink({})

    assert isinstance(sink, LoggingAlertSink)


def test_resolve_alert_sink_returns_logging_sink_when_env_var_empty_string() -> None:
    sink = resolve_alert_sink({ALERT_WEBHOOK_URL_ENV_VAR: ""})

    assert isinstance(sink, LoggingAlertSink)


def test_resolve_alert_sink_returns_webhook_sink_when_env_var_set() -> None:
    sink = resolve_alert_sink({ALERT_WEBHOOK_URL_ENV_VAR: _WEBHOOK_URL})

    assert isinstance(sink, WebhookAlertSink)


def test_webhook_alert_sink_rejects_non_https_scheme() -> None:
    with pytest.raises(ValueError, match="https"):
        WebhookAlertSink("http://alerts.example.test/webhook")


def test_webhook_alert_sink_rejects_userinfo_in_url() -> None:
    with pytest.raises(ValueError, match="userinfo"):
        WebhookAlertSink("https://user:pass@alerts.example.test/webhook")


def test_webhook_alert_sink_rejects_url_with_no_hostname() -> None:
    with pytest.raises(ValueError, match="hostname"):
        WebhookAlertSink("https:///webhook")


# --------------------------------------------------------------------------
# WebhookAlertSink transport behaviour -- respx only, zero real sockets
# --------------------------------------------------------------------------


@respx.mock
def test_webhook_alert_sink_posts_allowlisted_payload() -> None:
    route = respx.post(_WEBHOOK_URL).mock(return_value=httpx.Response(200))
    sink = WebhookAlertSink(_WEBHOOK_URL)
    payload = AlertPayload(
        severity="WARN", event="site_blocked", site="polymarket_us/NYC", detail="d"
    )

    sink.emit(payload)

    assert route.called
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == payload.to_dict()


@respx.mock
def test_webhook_alert_sink_raises_on_non_2xx_response() -> None:
    respx.post(_WEBHOOK_URL).mock(return_value=httpx.Response(500))
    sink = WebhookAlertSink(_WEBHOOK_URL)
    payload = AlertPayload(severity="WARN", event="e", site="global", detail="d")

    with pytest.raises(httpx.HTTPStatusError):
        sink.emit(payload)


@respx.mock
def test_webhook_alert_sink_tls_failure_does_not_propagate_through_emit_alert() -> None:
    respx.post(_WEBHOOK_URL).mock(side_effect=ssl.SSLError("certificate verify failed"))
    sink = WebhookAlertSink(_WEBHOOK_URL)
    payload = AlertPayload(severity="CRITICAL", event="e", site="global", detail="d")

    emit_alert(sink, payload)  # must not raise


@respx.mock
def test_webhook_alert_sink_timeout_does_not_propagate_through_emit_alert() -> None:
    respx.post(_WEBHOOK_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    sink = WebhookAlertSink(_WEBHOOK_URL)
    payload = AlertPayload(severity="CRITICAL", event="e", site="global", detail="d")

    emit_alert(sink, payload)  # must not raise


@respx.mock
def test_webhook_alert_sink_raises_directly_when_not_wrapped() -> None:
    """Positive control for the two tests above: proves `WebhookAlertSink`
    itself does not swallow the failure -- `emit_alert` is what contains
    it, not the sink.
    """
    respx.post(_WEBHOOK_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    sink = WebhookAlertSink(_WEBHOOK_URL)
    payload = AlertPayload(severity="CRITICAL", event="e", site="global", detail="d")

    with pytest.raises(httpx.TimeoutException):
        sink.emit(payload)


# --------------------------------------------------------------------------
# AlertState -- cold start, transitions, dedupe/re-notify
# --------------------------------------------------------------------------


def _condition(
    *,
    kind: str = "site_blocked",
    site: str = "polymarket_us/NYC",
    extra: str = "",
    active: bool,
    severity: str = "WARN",
    event: str = "site_blocked",
    detail: str = "blocked",
    renotify_muted: bool = False,
) -> AlertCondition:
    return AlertCondition(
        key=AlertConditionKey(kind=kind, site=site, extra=extra),
        active=active,
        severity=severity,
        event=event,
        detail=detail,
        renotify_muted=renotify_muted,
    )


def test_alert_fires_on_first_cycle_when_condition_already_true_at_startup() -> None:
    """BLOCKING cold-start rule: a condition already true when `AlertState`
    is constructed (e.g. a UA-trap latch or a BLOCKED gate that survived a
    restart) must fire on the very first `evaluate`/`dispatch` call, not
    be treated as "no change from an assumed-clear prior state".
    """
    state = AlertState()

    fired = state.evaluate([_condition(active=True)], now_ns=_START_NS)

    assert len(fired) == 1
    assert fired[0].event == "site_blocked"


def test_condition_does_not_fire_on_first_cycle_when_not_active() -> None:
    state = AlertState()

    fired = state.evaluate([_condition(active=False)], now_ns=_START_NS)

    assert fired == ()


def test_condition_fires_once_on_transition_and_not_again_within_renotify_window() -> None:
    state = AlertState(renotify_after_ns=10 * _SECOND_NS)

    first = state.evaluate([_condition(active=True)], now_ns=_START_NS)
    second = state.evaluate([_condition(active=True)], now_ns=_START_NS + 1 * _SECOND_NS)
    third = state.evaluate([_condition(active=True)], now_ns=_START_NS + 5 * _SECOND_NS)

    assert len(first) == 1
    assert second == ()
    assert third == ()


def test_condition_re_notifies_after_the_renotify_window_elapses() -> None:
    state = AlertState(renotify_after_ns=10 * _SECOND_NS)

    first = state.evaluate([_condition(active=True)], now_ns=_START_NS)
    still_within = state.evaluate([_condition(active=True)], now_ns=_START_NS + 9 * _SECOND_NS)
    after_window = state.evaluate([_condition(active=True)], now_ns=_START_NS + 11 * _SECOND_NS)

    assert len(first) == 1
    assert still_within == ()
    assert len(after_window) == 1


def test_clearing_then_re_firing_produces_a_second_alert() -> None:
    state = AlertState(renotify_after_ns=DEFAULT_RENOTIFY_AFTER_NS)

    first = state.evaluate([_condition(active=True)], now_ns=_START_NS)
    cleared = state.evaluate([_condition(active=False)], now_ns=_START_NS + 1 * _SECOND_NS)
    second = state.evaluate([_condition(active=True)], now_ns=_START_NS + 2 * _SECOND_NS)

    assert len(first) == 1
    assert cleared == ()
    assert len(second) == 1
    assert first[0].detail == second[0].detail


def test_renotify_muted_condition_fires_on_transition_but_never_again() -> None:
    # near-zero window: would re-fire immediately if not muted
    state = AlertState(renotify_after_ns=1)

    first = state.evaluate([_condition(active=True, renotify_muted=True)], now_ns=_START_NS)
    still_active_later = state.evaluate(
        [_condition(active=True, renotify_muted=True)], now_ns=_START_NS + 100 * _SECOND_NS
    )

    assert len(first) == 1
    assert still_active_later == ()


def test_independent_condition_keys_are_tracked_independently() -> None:
    state = AlertState()

    fired = state.evaluate(
        [
            _condition(kind="site_blocked", site="polymarket_us/NYC", active=True),
            _condition(kind="site_blocked", site="polymarket_us/SFO", active=True),
        ],
        now_ns=_START_NS,
    )

    assert len(fired) == 2
    assert {payload.site for payload in fired} == {"polymarket_us/NYC", "polymarket_us/SFO"}


def test_dispatch_returns_count_and_calls_the_sink() -> None:
    state = AlertState()
    sink = _FakeSink()

    count = state.dispatch(sink, [_condition(active=True)], now_ns=_START_NS)

    assert count == 1
    assert len(sink.received) == 1


def test_dispatch_count_is_unaffected_by_a_failing_sink() -> None:
    state = AlertState()
    sink = _FakeSink(raises=RuntimeError("delivery failed"))

    count = state.dispatch(sink, [_condition(active=True)], now_ns=_START_NS)  # must not raise

    assert count == 1
    assert len(sink.received) == 1


def test_dispatch_zero_when_nothing_active() -> None:
    state = AlertState()
    sink = _FakeSink()

    count = state.dispatch(sink, [_condition(active=False)], now_ns=_START_NS)

    assert count == 0
    assert sink.received == []
