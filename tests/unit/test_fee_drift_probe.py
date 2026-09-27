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
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.fees import DOCUMENTED_TAKER_FEE_COEFFICIENT
from breezy.adapters.polymarket_us.provider import MARKET_BY_SLUG_PATH
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_DISCOVERY
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.fee_drift_probe import (
    DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS,
    FEE_COEFFICIENT_WIRE_KEY,
    FeeDriftProbeActor,
    WireFeeCoefficientError,
    fetch_wire_fee_coefficient,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    open_trial_day_latch,
)

_SLUG = "tc-temp-sfohigh-2026-09-21-gte70f"

#: EDGE-1 AC1: the real, captured venue envelope shape -- not a flattened
#: stand-in. `GET /v1/market/slug/{slug}` always wraps the market object
#: under a `"market"` key (root cause of the wire-read defect this item
#: fixes).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_MARKET_ENVELOPE_PATH = (
    _REPO_ROOT
    / "docs"
    / "evidence"
    / "venue"
    / "polymarket_us"
    / "raw"
    / "market_open_510636_by_slug.json"
)


def _envelope(fee_coefficient: Any) -> dict[str, Any]:
    """A minimal, correctly-nested `{"market": {...}}` envelope -- the
    ONLY shape `fetch_wire_fee_coefficient` accepts post-fix. `fee_coefficient
    ` is placed exactly where the real venue places it (nested, never flat).
    """
    return {"market": {FEE_COEFFICIENT_WIRE_KEY: fee_coefficient, "slug": _SLUG}}


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


def _register(actor: FeeDriftProbeActor, clock: TestClock) -> None:
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )


# ---------------------------------------------------------------------------
# probe_once: the three outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_once_agrees_and_never_alerts_or_halts() -> None:
    actor, sink, setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())
    _register(actor, TestClock())

    outcome = await actor.probe_once()

    assert outcome == "AGREE"
    assert sink.emitted == []
    assert setter.calls == 0
    assert actor.counters["agree"] == 1


@pytest.mark.asyncio
async def test_probe_once_disagrees_alerts_critical_and_halts() -> None:
    actor, sink, setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))
    _register(actor, TestClock())

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
async def test_probe_once_never_raises_when_the_halt_set_write_itself_fails() -> None:
    """The DISAGREE finding must survive a failing durable write: still
    alerted (via the mismatch alert), still returned as "DISAGREE", still
    counted -- plus a SEPARATE, distinctly-named alert for the failed write
    itself, so an operator can tell "halted" apart from "found drift but the
    halt did not take"."""
    sink = _RecordingAlertSink()

    def _raising_setter(wire_fee: Decimal) -> None:
        del wire_fee
        raise RuntimeError("submit intent process lock is not held")

    actor = FeeDriftProbeActor(
        wire_fee_fetcher=_disagreeing_fetcher("0.0695"),
        set_family_halted=_raising_setter,
        alert_sink=sink,
    )
    _register(actor, TestClock())

    outcome = await actor.probe_once()

    assert outcome == "DISAGREE"
    assert actor.counters["disagree"] == 1
    assert actor.counters["halt_set_failed"] == 1
    events = {payload.event for payload in sink.emitted}
    assert events == {"fee_drift_probe_mismatch", "fee_drift_probe_halt_set_failed"}
    assert all(payload.severity == "CRITICAL" for payload in sink.emitted)


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
# Mismatch alert dedupe (fee-drift-probe-target ruling, 2026-09-25): CRITICAL
# once per distinct wire value, suppressed for 24h on the Actor's OWN clock,
# then one "persisting" reminder that re-arms its own window. The halt-set
# stays unconditional on every DISAGREE throughout -- dedupe shapes only the
# alert stream, never the halt.
# ---------------------------------------------------------------------------

_TWENTY_FOUR_HOURS_NS = 24 * 60 * 60 * 1_000_000_000


def _events_named(sink: _RecordingAlertSink, event: str) -> list[AlertPayload]:
    return [payload for payload in sink.emitted if payload.event == event]


@pytest.mark.asyncio
async def test_two_disagrees_with_the_same_wire_value_within_24h_alert_once() -> None:
    actor, sink, setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))
    clock = TestClock()
    _register(actor, clock)

    first = await actor.probe_once()
    clock.set_time(_TWENTY_FOUR_HOURS_NS - 1)
    second = await actor.probe_once()

    assert first == "DISAGREE"
    assert second == "DISAGREE"
    assert setter.calls == 2, "the halt-set stays unconditional on every DISAGREE"
    mismatches = _events_named(sink, "fee_drift_probe_mismatch")
    assert len(mismatches) == 1, "the second DISAGREE for the SAME wire value must be suppressed"
    assert all(payload.severity == "CRITICAL" for payload in mismatches)


@pytest.mark.asyncio
async def test_a_new_distinct_wire_value_alerts_immediately_inside_the_suppression_window() -> None:
    actor, sink, setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))
    clock = TestClock()
    _register(actor, clock)

    await actor.probe_once()
    actor._wire_fee_fetcher = _disagreeing_fetcher("0.07")
    outcome = await actor.probe_once()

    assert outcome == "DISAGREE"
    assert setter.calls == 2, "the halt-set stays unconditional on every DISAGREE"
    mismatches = _events_named(sink, "fee_drift_probe_mismatch")
    assert len(mismatches) == 2, "a distinct wire value is never suppressed by a prior window"


@pytest.mark.asyncio
async def test_the_same_wire_value_after_24h_emits_one_persisting_reminder_then_rearms() -> None:
    actor, sink, setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))
    clock = TestClock()
    _register(actor, clock)

    await actor.probe_once()
    clock.set_time(_TWENTY_FOUR_HOURS_NS)
    second = await actor.probe_once()
    clock.set_time(_TWENTY_FOUR_HOURS_NS + 1)  # inside the reminder's own freshly re-armed window
    third = await actor.probe_once()

    assert second == "DISAGREE"
    assert third == "DISAGREE"
    assert setter.calls == 3, "the halt-set stays unconditional on every DISAGREE"
    persisting = _events_named(sink, "fee_drift_probe_mismatch_persisting")
    assert len(persisting) == 1, "the reminder fires once at >=24h, then re-arms its own window"
    assert persisting[0].severity == "CRITICAL"
    mismatches = _events_named(sink, "fee_drift_probe_mismatch")
    assert len(mismatches) == 1, "only the first sighting of this wire value is a mismatch event"


@pytest.mark.asyncio
async def test_an_agree_resets_the_mismatch_dedupe_so_a_flap_realerts() -> None:
    """A flap is news (coordinator ruling on the 1907e68 review): an AGREE
    between two DISAGREEs for the SAME wire value means the drift ended and
    came back -- a new event, not a continuation -- so it must re-alert
    immediately, never stay suppressed by the pre-flap window."""
    actor, sink, setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))
    clock = TestClock()
    _register(actor, clock)

    first = await actor.probe_once()
    actor._wire_fee_fetcher = _agreeing_fetcher()
    middle = await actor.probe_once()
    actor._wire_fee_fetcher = _disagreeing_fetcher("0.0695")
    last = await actor.probe_once()

    assert (first, middle, last) == ("DISAGREE", "AGREE", "DISAGREE")
    assert setter.calls == 2, "the halt-set stays unconditional on every DISAGREE"
    mismatches = _events_named(sink, "fee_drift_probe_mismatch")
    assert len(mismatches) == 2, "the AGREE must reset the dedupe so the flap re-alerts"


@pytest.mark.asyncio
async def test_an_unknown_never_resets_the_mismatch_dedupe() -> None:
    """UNKNOWN is a read failure, not a resolution -- it must leave the
    dedupe state untouched, so a DISAGREE either side of it for the SAME
    wire value stays suppressed."""
    actor, sink, setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))
    clock = TestClock()
    _register(actor, clock)

    first = await actor.probe_once()
    actor._wire_fee_fetcher = _raising_fetcher(WireFeeCoefficientError("no feeCoefficient field"))
    middle = await actor.probe_once()
    actor._wire_fee_fetcher = _disagreeing_fetcher("0.0695")
    last = await actor.probe_once()

    assert (first, middle, last) == ("DISAGREE", "UNKNOWN", "DISAGREE")
    assert setter.calls == 2, "the halt-set stays unconditional on every DISAGREE"
    mismatches = _events_named(sink, "fee_drift_probe_mismatch")
    assert len(mismatches) == 1, "an UNKNOWN must never reset the mismatch dedupe"


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
    client = _RecordingHttpClient(_envelope("0.06"))

    result = await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)

    assert result == Decimal("0.06")
    assert client.public_calls == [
        (MARKET_BY_SLUG_PATH.format(slug=_SLUG), QUOTA_KEY_DISCOVERY)
    ]
    assert client.authenticated_calls == []


@pytest.mark.asyncio
async def test_fetch_wire_fee_coefficient_unwraps_the_market_envelope() -> None:
    """AC1: the REAL captured venue envelope (`{"market": {...}}`), not a
    flattened stand-in, parses to the expected `Decimal`."""
    payload = json.loads(_REAL_MARKET_ENVELOPE_PATH.read_text())
    client = _RecordingHttpClient(payload)

    result = await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)

    assert result == Decimal("0.06")


@pytest.mark.asyncio
async def test_fetch_wire_fee_coefficient_raises_on_a_missing_field() -> None:
    client = _RecordingHttpClient({"market": {"slug": _SLUG}})

    with pytest.raises(WireFeeCoefficientError):
        await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)


@pytest.mark.asyncio
async def test_fetch_wire_fee_coefficient_raises_on_a_malformed_field() -> None:
    client = _RecordingHttpClient(_envelope("not-a-number"))

    with pytest.raises(WireFeeCoefficientError):
        await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)


@pytest.mark.asyncio
async def test_fetch_wire_fee_coefficient_raises_when_the_market_envelope_is_absent() -> None:
    """Ruling (r2): a flat payload with no `"market"` key at all is
    UNKNOWN, full stop -- there is no fallback read of a top-level field."""
    client = _RecordingHttpClient({FEE_COEFFICIENT_WIRE_KEY: "0.06", "slug": _SLUG})

    with pytest.raises(WireFeeCoefficientError):
        await fetch_wire_fee_coefficient(client, _SLUG, quota_key=QUOTA_KEY_DISCOVERY)


# ---------------------------------------------------------------------------
# Timer wiring: no coarser than 2 hours, native `Clock.set_timer`
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# EDGE-1 (r2/AM-1..4): in-memory, time-based "fee unverified" staleness veto.
# `is_fee_verified(now_ns)` takes an EXTERNALLY supplied `now_ns` -- AM-1
# requires the STRATEGY's own clock (`self.clock.timestamp_ns()`), never
# `snapshot.ts_event`; this module never reads its own clock for that
# comparison either, so the caller fully controls it (proven here via
# TestClock and an explicit `now_ns` argument, and by the strategy-side test
# in test_continuous_rung_hold_strategy.py).
# ---------------------------------------------------------------------------

_FOUR_HOURS_NS = 4 * 60 * 60 * 1_000_000_000


def test_a_fresh_boot_is_unverified_until_the_first_agree() -> None:
    actor, _sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())

    assert actor.is_fee_verified(0) is False


@pytest.mark.asyncio
async def test_an_agree_clears_the_stale_state_and_refreshes_the_clock() -> None:
    actor, _sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())
    clock = TestClock()
    _register(actor, clock)
    clock.set_time(1_000)

    await actor.probe_once()

    assert actor.is_fee_verified(1_000) is True
    assert actor.is_fee_verified(1_000 + _FOUR_HOURS_NS) is True
    assert actor.is_fee_verified(1_000 + _FOUR_HOURS_NS + 1) is False


@pytest.mark.asyncio
async def test_the_veto_reengages_once_the_staleness_bound_elapses_with_no_further_agree() -> None:
    actor, sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())
    clock = TestClock()
    _register(actor, clock)
    clock.set_time(0)
    await actor.probe_once()
    assert actor.is_fee_verified(0) is True

    stale_at = _FOUR_HOURS_NS + 1
    assert actor.is_fee_verified(stale_at) is False
    stale_events = [p for p in sink.emitted if p.event == "fee_drift_probe_fee_unverified_stale"]
    assert len(stale_events) == 1
    assert stale_events[0].severity == "CRITICAL"


@pytest.mark.asyncio
async def test_a_disagree_does_not_clear_the_stale_state() -> None:
    actor, _sink, _setter = _build_actor(wire_fee_fetcher=_disagreeing_fetcher("0.0695"))
    clock = TestClock()
    _register(actor, clock)
    clock.set_time(0)

    outcome = await actor.probe_once()

    assert outcome == "DISAGREE"
    assert actor.is_fee_verified(0) is False, "only AGREE may ever clear the staleness veto"


def test_crossing_the_staleness_bound_alerts_exactly_once() -> None:
    actor, sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())

    first = actor.is_fee_verified(0)
    second = actor.is_fee_verified(1)
    third = actor.is_fee_verified(2)

    assert (first, second, third) == (False, False, False)
    stale_events = [p for p in sink.emitted if p.event == "fee_drift_probe_fee_unverified_stale"]
    assert len(stale_events) == 1, "the first-crossing alert must not repeat on every check"


def test_the_stale_state_persisting_past_the_escalation_window_fires_exactly_one_reminder() -> None:
    actor, sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())
    twenty_four_hours_ns = 24 * 60 * 60 * 1_000_000_000

    actor.is_fee_verified(0)  # first crossing (boot, never verified)
    actor.is_fee_verified(twenty_four_hours_ns - 1)  # still inside the reminder window
    actor.is_fee_verified(twenty_four_hours_ns)  # >=24h since the first alert: one reminder
    actor.is_fee_verified(twenty_four_hours_ns + 1)  # freshly re-armed window: no second reminder

    stale_events = [p for p in sink.emitted if p.event == "fee_drift_probe_fee_unverified_stale"]
    persisting_events = [
        p for p in sink.emitted if p.event == "fee_drift_probe_fee_unverified_stale_persisting"
    ]
    assert len(stale_events) == 1
    assert len(persisting_events) == 1
    assert persisting_events[0].severity == "CRITICAL"


def test_stale_alert_detail_is_never_the_raw_exception_string() -> None:
    """Security fix: `detail=` is a number or a fixed literal, never
    exception text (which could embed the slug)."""
    actor, sink, _setter = _build_actor(wire_fee_fetcher=_agreeing_fetcher())

    actor.is_fee_verified(0)

    (payload,) = sink.emitted
    assert payload.detail == "never"


# ---------------------------------------------------------------------------
# Integration: a REAL TrialDayLatch, acquired through its existing public API
# (silent-failure-hunter review, 2026-09-25) -- proves DISAGREE persists the
# family halt through the SAME mechanism the submit path itself uses, rather
# than only through a fake/stub in the unit tests above. The lock is
# acquired the same way `breezy.app.trade.run` acquires it: open the store,
# open the submit-intent latch (holds an exclusive flock for as long as this
# `with` block is entered -- exactly as long as a live process holds it for
# its whole life), then bind a `TrialDayLatch` to it via `open_trial_day_latch`
# -- never bypassing `_require_held()`.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disagree_persists_the_halt_through_a_real_trial_day_latch_and_the_veto_then_refuses(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "exec_state.sqlite"
    sink = _RecordingAlertSink()

    with (
        SqliteStateStore(store_path) as store,
        open_submit_intent_latch(store, store_path) as latch,
    ):
        family_halt_latch = open_trial_day_latch(
            latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
        )
        submit_veto = family_halt_submit_veto(family_halt_latch)
        assert submit_veto() is None, "must start un-halted"

        actor = FeeDriftProbeActor(
            wire_fee_fetcher=_disagreeing_fetcher("0.0695"),
            set_family_halted=lambda wire_fee: family_halt_latch.record_policy_halt(
                reason="fee_schedule_drift",
                evidence_sha256="0" * 64,
                ts_ns=1,
            ),
            alert_sink=sink,
        )
        _register(actor, TestClock())

        outcome = await actor.probe_once()

        assert outcome == "DISAGREE"
        assert actor.counters["halt_set_failed"] == 0, "the real write must succeed here"
        assert submit_veto() == "family_halt", (
            "a DISAGREE must durably set the SAME halt the submit veto reads, "
            "through the latch's real, held lock -- never bypassing _require_held()"
        )
