"""Unit tests for `build_monitor_callables` (review finding F1, DRY
extraction): the eight read-only closures wiring a `PositionMonitor` to a
`ContinuousRungHoldStrategy` are built in exactly ONE place now
(`breezy.strategy.current_rung_hold.monitor_wiring`), reused by
`composition.py::_build_position_monitor_for`, the paper-replay driver's
`install_position_monitor`, and the trial-id join contract test's
`_wire_monitor`.

These tests exercise the factory in isolation against a minimal, duck-typed
stand-in strategy -- never a real Nautilus `Strategy` (whose `cache`
attribute is a non-writable Cython property, unsuitable for the strict-stub
technique below). Reuses the recording-stub allowlist approach from
`tests/unit/test_current_rung_hold_position_monitor.py`'s
`_StrictAccumulator`: a stub that raises `AssertionError` on any attribute
access outside the M7 D3 pin's read-only allowlist proves the closures never
reach into the strategy's mutating cache/latch surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Venue

from breezy.adapters.polymarket_us.symbology import (
    no_leg_instrument_id,
    sibling_instrument_id,
)
from breezy.strategy.current_rung_hold.monitor_wiring import (
    MonitorCallables,
    build_monitor_callables,
)
from breezy.strategy.current_rung_hold.strategy import _local_hour

STATION = "LAX"
CLIMATE_DAY = date(2026, 9, 4)
WINDOW_OPEN_NS = 1_788_552_000_000_000_000
_IID_OBJ = InstrumentId.from_str("lax-86-87.POLYMARKET_US")
_IID = str(_IID_OBJ)
_NO_IID = str(sibling_instrument_id(_IID_OBJ))


@dataclass
class _FakeFacts:
    settlement_station: str
    climate_day: date


class _StrictCache:
    """Raises on any attribute beyond `positions_open`/`instrument` -- the
    M7 D3 pin's read-only cache surface `build_monitor_callables` may touch
    (`position_monitor.py`'s own docstring)."""

    def __init__(
        self, *, positions: Sequence[object] = (), instrument: object = None,
    ) -> None:
        self._positions = positions
        self._instrument = instrument
        self.positions_open_calls = 0
        self.instrument_calls = 0

    def positions_open(self, *, instrument_id: object) -> Sequence[object]:
        self.positions_open_calls += 1
        return self._positions

    def instrument(self, instrument_id: object) -> object:
        self.instrument_calls += 1
        return self._instrument

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"build_monitor_callables touched disallowed cache attribute: {name}")


class _StrictLatch:
    """Raises on any attribute beyond `record_with_legacy_fallback` -- the
    M7 D3 pin's only sanctioned read accessor onto `TrialDayLatch`. Never
    exposes `consume`/`is_intent_open`/any other mutating method, so a call
    to one of those here is a real violation, not a stub gap."""

    def __init__(self, record: object | None) -> None:
        self._record = record
        self.record_calls = 0

    def record_with_legacy_fallback(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> object | None:
        self.record_calls += 1
        return self._record

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"build_monitor_callables touched disallowed latch attribute: {name}")


@dataclass
class _FakeStrategy:
    """Minimal duck-typed stand-in for `ContinuousRungHoldStrategy` --
    exposes ONLY the attributes `build_monitor_callables` reads."""

    cache: object
    _latch: object
    _facts: dict[str, _FakeFacts] = field(default_factory=dict)
    _accumulators: dict[str, object] = field(default_factory=dict)
    _std_utc_offset_hours_by_station: dict[str, float] = field(default_factory=dict)
    _fee: Decimal | None = None

    def _guarded_fee_coefficient(self, instrument: object) -> Decimal | None:
        return self._fee


def _strategy(**overrides: object) -> _FakeStrategy:
    defaults: dict[str, object] = {"cache": _StrictCache(), "_latch": None}
    defaults.update(overrides)
    return _FakeStrategy(**defaults)  # type: ignore[arg-type]


def test_build_monitor_callables_returns_all_eight_named_fields() -> None:
    callables = build_monitor_callables(_strategy())  # type: ignore[arg-type]
    assert isinstance(callables, MonitorCallables)
    for name in (
        "positions_open", "latch_record", "rung_geometry", "fee_coefficient_for",
        "leg_for", "station_for", "climate_day_for", "hour_lst_for",
    ):
        assert callable(getattr(callables, name))


def test_positions_open_reads_only_the_allowed_cache_surface() -> None:
    fake_position = object()
    cache = _StrictCache(positions=(fake_position,))
    callables = build_monitor_callables(_strategy(cache=cache))  # type: ignore[arg-type]

    result = callables.positions_open(_IID)

    assert result == (fake_position,)
    assert cache.positions_open_calls == 1


def test_latch_record_reads_only_the_allowed_latch_surface_and_forwards_the_key() -> None:
    sentinel_record = object()
    latch = _StrictLatch(sentinel_record)
    callables = build_monitor_callables(_strategy(_latch=latch))  # type: ignore[arg-type]

    result = callables.latch_record(STATION, CLIMATE_DAY.isoformat(), key_instrument_id=_IID)

    assert result is sentinel_record
    assert latch.record_calls == 1


def test_latch_record_returns_none_when_the_strategy_holds_no_latch() -> None:
    callables = build_monitor_callables(_strategy(_latch=None))  # type: ignore[arg-type]

    assert callables.latch_record(STATION, CLIMATE_DAY.isoformat(), key_instrument_id=_IID) is None


def test_rung_geometry_reads_facts_and_never_mutates_the_facts_mapping() -> None:
    facts = {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}
    callables = build_monitor_callables(_strategy(_facts=facts))  # type: ignore[arg-type]

    assert callables.rung_geometry(_IID) is facts[_IID]
    assert callables.rung_geometry("unregistered-id") is None
    assert facts == {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}


def test_fee_coefficient_for_reads_the_guarded_fee_via_the_strategys_own_method() -> None:
    instrument = object()
    cache = _StrictCache(instrument=instrument)
    callables = build_monitor_callables(  # type: ignore[arg-type]
        _strategy(cache=cache, _fee=Decimal("0.06")),
    )

    assert callables.fee_coefficient_for(_IID) == Decimal("0.06")
    assert cache.instrument_calls == 1


def test_fee_coefficient_for_raises_when_the_strategy_reports_no_known_fee() -> None:
    callables = build_monitor_callables(_strategy(_fee=None))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unknown fee schedule"):
        callables.fee_coefficient_for(_IID)


def test_leg_for_reads_the_instrument_ids_own_leg_suffix() -> None:
    callables = build_monitor_callables(_strategy())  # type: ignore[arg-type]

    assert callables.leg_for(_IID) == "YES"
    assert callables.leg_for(_NO_IID) == "NO"


def test_station_and_climate_day_for_read_the_strategys_own_facts() -> None:
    facts = {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}
    callables = build_monitor_callables(_strategy(_facts=facts))  # type: ignore[arg-type]

    assert callables.station_for(_IID) == STATION
    assert callables.climate_day_for(_IID) == CLIMATE_DAY.isoformat()


# ---------------------------------------------------------------------------
# FU-1: a `^no` id falls back to its YES sibling's facts
# ---------------------------------------------------------------------------


def test_station_and_climate_day_for_fall_back_to_the_yes_sibling_for_a_no_leg_id() -> None:
    facts = {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}
    callables = build_monitor_callables(_strategy(_facts=facts))  # type: ignore[arg-type]

    assert callables.station_for(_NO_IID) == STATION
    assert callables.climate_day_for(_NO_IID) == CLIMATE_DAY.isoformat()


def test_rung_geometry_falls_back_to_the_yes_sibling_for_a_no_leg_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}
    callables = build_monitor_callables(_strategy(_facts=facts))  # type: ignore[arg-type]

    assert callables.rung_geometry(_NO_IID) is facts[_IID]

    def _raise(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "sibling_instrument_id must never be called for a YES-id miss"
        )

    # A YES-id miss (e.g. an unregistered instrument) must never even
    # attempt the sibling probe -- reviewer finding: prove it by making the
    # probe itself raise.
    monkeypatch.setattr(
        "breezy.strategy.current_rung_hold.monitor_wiring.sibling_instrument_id", _raise,
    )
    assert callables.rung_geometry("unregistered-id") is None


def test_station_and_climate_day_for_raise_keyerror_when_neither_leg_is_in_facts() -> None:
    callables = build_monitor_callables(_strategy(_facts={}))  # type: ignore[arg-type]

    assert callables.rung_geometry(_NO_IID) is None
    with pytest.raises(KeyError):
        callables.station_for(_NO_IID)
    with pytest.raises(KeyError):
        callables.climate_day_for(_NO_IID)


def test_rung_geometry_for_a_no_leg_id_never_mutates_the_facts_mapping() -> None:
    facts = {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}
    callables = build_monitor_callables(_strategy(_facts=facts))  # type: ignore[arg-type]

    callables.rung_geometry(_NO_IID)

    assert facts == {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}
    assert list(facts) == [_IID]


def test_a_foreign_venue_or_malformed_no_leg_id_resolves_to_none() -> None:
    facts = {_IID: _FakeFacts(settlement_station=STATION, climate_day=CLIMATE_DAY)}
    callables = build_monitor_callables(_strategy(_facts=facts))  # type: ignore[arg-type]

    # Malformed (unparseable by `InstrumentId.from_str`): `ValueError` -> `None`.
    assert callables.rung_geometry("not-a-valid-instrument-id") is None
    with pytest.raises(KeyError):
        callables.station_for("not-a-valid-instrument-id")

    # A NO-leg id for a foreign venue: `sibling_instrument_id`'s own venue
    # check raises `VenuePayloadError` -> `None`, never a guessed slug.
    foreign_no_id = str(no_leg_instrument_id("lax-86-87", venue=Venue("KALSHI")))
    assert callables.rung_geometry(foreign_no_id) is None
    with pytest.raises(KeyError):
        callables.station_for(foreign_no_id)


def test_hour_lst_for_matches_the_shared_local_hour_derivation() -> None:
    offsets = {STATION: -8.0}
    callables = build_monitor_callables(  # type: ignore[arg-type]
        _strategy(_std_utc_offset_hours_by_station=offsets),
    )

    assert callables.hour_lst_for(STATION, WINDOW_OPEN_NS) == _local_hour(
        WINDOW_OPEN_NS, offsets[STATION],
    )
