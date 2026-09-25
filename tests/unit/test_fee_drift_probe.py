"""AUD-12b: unattended fee-schedule drift probe.

Native, therefore used rather than rebuilt (verified in the installed
``nautilus-trader==1.231.0``, mirroring ``tests/unit/test_nbm_forecast_actor.py``'s
own citation): ``Clock.set_timer`` (``common/component.pyx:419``),
``Actor._start -> on_start`` (``common/actor.pyx:148,691``). The Actor is
driven by a NATIVE ``TestClock`` registered through ``Actor.register_base``,
timers fire ORGANICALLY through ``TestClock.advance_time`` -- the exact shape
``test_nbm_forecast_actor.py`` established for this same extension point.

Three outcomes, never two (plan §7 step 3): AGREE (silent), DISAGREE
(CRITICAL alert + ``set_family_halted()``), UNKNOWN (alert, never defaults to
"agrees", never halts on a bare transient read failure -- a documented,
deliberate design choice, see ``fee_drift_probe.py``'s module docstring).

No ``src/`` constant is touched by any test here (plan §6 item 4): every
fixture injects its own fee value; ``DOCUMENTED_TAKER_FEE_COEFFICIENT`` is
only ever READ, and one test pins it byte-identical to the schedule-pin
capture ("0.06") so a future edit there is caught here too.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.fees import DOCUMENTED_TAKER_FEE_COEFFICIENT
from breezy.adapters.polymarket_us.provider import MARKET_BY_SLUG_PATH
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_DISCOVERY
from breezy.runtime.health import AlertPayload
from breezy.strategy.current_rung_hold.fee_drift_probe import (
    DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS,
    FEE_COEFFICIENT_WIRE_KEY,
    FeeDriftProbeActor,
    WireFeeCoefficientError,
    fetch_wire_fee_coefficient,
)

_SLUG = "tc-temp-sfohigh-2026-09-21-gte70f"


class _RecordingAlertSink:
    """A stub `AlertSink` (`runtime/health.py`'s `Protocol`) -- records, never sends."""

    def __init__(self) -> None:
        self.emitted: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.emitted.append(payload)


@dataclass
class _RecordingHaltSetter:
    """Stands in for the wiring site's `TrialDayLatch.record_policy_halt` binding."""

    calls: int = field(default=0)
    last_wire_fee: Decimal | None = field(default=None)

    def __call__(self, wire_fee: Decimal) -> None:
        self.calls += 1
        self.last_wire_fee = wire_fee


def _agreeing_fetcher() -> Any:
    async def _fetch() -> Decimal:
        return DOCUMENTED_TAKER_FEE_COEFFICIENT

    return _fetch


def _disagreeing_fetcher(value: str) -> Any:
    async def _fetch() -> Decimal:
        return Decimal(value)

    return _fetch


def _raising_fetcher(exc: BaseException) -> Any:
    async def _fetch() -> Decimal:
        raise exc

    return _fetch


def _build_actor(
    *,
    wire_fee_fetcher: Any,
    alert_sink: _RecordingAlertSink | None = None,
    halt_setter: _RecordingHaltSetter | None = None,
    interval_seconds: int = DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS,
) -> tuple[FeeDriftProbeActor, _RecordingAlertSink, _RecordingHaltSetter]:
    sink = alert_sink if alert_sink is not None else _RecordingAlertSink()
    setter = halt_setter if halt_setter is not None else _RecordingHaltSetter()
    actor = FeeDriftProbeActor(
        wire_fee_fetcher=wire_fee_fetcher,
        set_family_halted=setter,
        alert_sink=sink,
        interval_seconds=interval_seconds,
    )
    return actor, sink, setter


# ---------------------------------------------------------------------------
# probe_once: the three outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_once_agrees_and_never_alerts_or_halts() -> None:
    actor, sink, setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())

    outcome = await actor.probe_once()

    assert outcome == "AGREE"
    assert sink.emitted == []
    assert setter.calls == 0
    assert actor.counters["agree"] == 1


@pytest.mark.asyncio
async def test_probe_once_disagrees_alerts_critical_and_halts() -> None:
    actor, sink, setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))

    outcome = await actor.probe_once()

    assert outcome == "DISAGREE"
    assert setter.calls == 1
    assert setter.last_wire_fee == Decimal("0.0695")
    (payload,) = sink.emitted
    assert payload.severity == "CRITICAL"
    assert "0.0695" in payload.detail
    assert str(DOCUMENTED_TAKER_FEE_COEFFICIENT) in payload.detail
    assert actor.counters["disagree"] == 1


@pytest.mark.asyncio
async def test_probe_once_fails_closed_to_unknown_and_never_defaults_to_agree() -> None:
    actor, sink, setter = _build_actor(
        wire_fee_fetcher=_raising_fetcher(WireFeeCoefficientError("no feeCoefficient field"))
    )

    outcome = await actor.probe_once()

    assert outcome == "UNKNOWN"
    assert setter.calls == 0, "an unreadable wire response must never halt the family itself"
    (payload,) = sink.emitted
    assert payload.severity == "CRITICAL"
    assert actor.counters["unknown"] == 1


# ---------------------------------------------------------------------------
# fetch_wire_fee_coefficient: the unauthenticated gateway path, and failure shapes
# ---------------------------------------------------------------------------


class _RecordingHttpClient:
    """Stands in for `PolymarketUSHttpClient` -- records which method was called."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = payload
        self.public_calls: list[tuple[str, str]] = []
        self.authenticated_calls: list[tuple[str, str]] = []

    async def get_public(
        self, path: str, *, query: Any = None, quota_key: str
    ) -> Mapping[str, Any]:
        self.public_calls.append((path, quota_key))
        return self._payload

    async def get_authenticated(
        self, path: str, *, query: Any = None, quota_key: str
    ) -> Mapping[str, Any]:
        self.authenticated_calls.append((path, quota_key))
        raise AssertionError("the fee-drift probe must never use the authenticated path")


@pytest.mark.asyncio
async def test_fetch_wire_fee_coefficient_uses_the_unauthenticated_gateway_path() -> None:
    client = _RecordingHttpClient({FEE_COEFFICIENT_WIRE_KEY: "0.06"})

    result = await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)

    assert result == Decimal("0.06")
    assert client.public_calls == [
        (MARKET_BY_SLUG_PATH.format(slug=_SLUG), QUOTA_KEY_DISCOVERY)
    ]
    assert client.authenticated_calls == []


@pytest.mark.asyncio
async def test_fetch_wire_fee_coefficient_raises_on_a_missing_field() -> None:
    client = _RecordingHttpClient({"slug": _SLUG})

    with pytest.raises(WireFeeCoefficientError):
        await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)


@pytest.mark.asyncio
async def test_fetch_wire_fee_coefficient_raises_on_a_malformed_field() -> None:
    client = _RecordingHttpClient({FEE_COEFFICIENT_WIRE_KEY: "not-a-number"})

    with pytest.raises(WireFeeCoefficientError):
        await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)


# ---------------------------------------------------------------------------
# Timer wiring: no coarser than 2 hours, native `Clock.set_timer`
# ---------------------------------------------------------------------------


def _register(actor: FeeDriftProbeActor, clock: TestClock) -> None:
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_on_start_arms_a_timer_no_coarser_than_two_hours_and_probes_once() -> None:
    assert DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS <= 2 * 60 * 60
    actor, sink, setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())
    clock = TestClock()
    _register(actor, clock)

    actor.start()
    for _ in range(5_000):
        if actor.inflight == 0:
            break
        await asyncio.sleep(0)
    assert actor.timer_armed is True
    assert actor.counters["agree"] == 1
    assert sink.emitted == []
    assert setter.calls == 0


def test_with_no_running_loop_nothing_is_armed() -> None:
    """A backtest has no loop: no timer, no network I/O by construction."""
    actor, _sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())
    clock = TestClock()
    _register(actor, clock)

    actor.start()

    assert actor.timer_armed is False


def test_documented_fee_coefficient_default_is_byte_identical_to_the_pin() -> None:
    """Pins this probe's default against the schedule-pin capture -- never edited here."""
    assert DOCUMENTED_TAKER_FEE_COEFFICIENT == Decimal("0.06")
    actor, _sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())
    assert actor._documented == DOCUMENTED_TAKER_FEE_COEFFICIENT
