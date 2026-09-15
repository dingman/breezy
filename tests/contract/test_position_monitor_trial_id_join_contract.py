"""Contract test (A1, Rev 2.1 addendum): the intra-day position monitor's
``trial_id`` derivation must be BYTE-IDENTICAL to the real key a live fill
writes into the durable store -- the exact join key any scorer read of that
fill needs.

Drives a REAL fill through ``ContinuousRungHoldStrategy.on_order_filled``
(the actual production write path, `continuous_strategy.py`'s
``_consume_or_flag_duplicate``) against a real ``SqliteStateStore``-backed
``TrialDayLatch``, never a hand-written JSON blob. Proves two things in one
chain: (1) ``trial_id_for(prefix, station, climate_day, instrument_id)`` --
the SAME function ``position_monitor.py`` calls at registration -- names the
EXACT key the fill was durably recorded under; (2) a ``PositionMonitor``
registering the resulting position produces a
:class:`PositionMonitorSummary` whose own ``trial_id`` is that identical
string.

FINDING (out of this task's scope -- reported, not silently worked around):
``scripts/analysis/score_live_trials.py``'s ``read_filled_trials_state_db``
parses ONLY 2-part (``station/climate_day``) latch keys
(``len(parts) != 2: continue``, score_live_trials.py:725,1060) -- it does
not yet join a v3 MP-A instrument-keyed (3-part) latch AT ALL, so a literal
"scorer produces a ScoredTrial" contract cannot be exercised against the
real, current v3 key shape without first fixing that reader (a different,
pre-existing backlog item; ``score_live_trials.py`` is not in this
increment's touchable-files list). This test instead proves the identity
A1 actually protects -- the join key itself never silently drifts between
the monitor and the durable write path a future MP-A-aware scorer fix would
read.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.position import Position
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.strategy.current_rung_hold.monitor_store import (
    MarkBuffer,
    read_monitor_summaries,
)
from breezy.strategy.current_rung_hold.position_monitor import PositionMonitor
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    trial_id_for,
)
from tests.unit.test_continuous_rung_hold_fill_wiring import _fill
from tests.unit.test_continuous_rung_hold_strategy import _register_and_start
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    STATION,
    _instrument,
)

_MINUTE_NS = 60_000_000_000


def _wire_monitor(strategy, *, tmp_path: Path) -> PositionMonitor:
    from nautilus_trader.model.identifiers import InstrumentId

    from breezy.adapters.polymarket_us.symbology import leg_of
    from breezy.strategy.current_rung_hold.strategy import _local_hour

    def _positions_open(iid: str):
        return strategy.cache.positions_open(instrument_id=InstrumentId.from_str(iid))

    def _latch_record(station: str, climate_day: str, *, key_instrument_id: str | None = None):
        if strategy._latch is None:
            return None
        return strategy._latch.record_with_legacy_fallback(
            station, climate_day, key_instrument_id=key_instrument_id,
        )

    def _rung_geometry(iid: str):
        return strategy._facts.get(iid)

    def _fee_coefficient_for(iid: str) -> Decimal:
        instrument = strategy.cache.instrument(InstrumentId.from_str(iid))
        fee = strategy._guarded_fee_coefficient(instrument)
        if fee is None:
            raise ValueError(f"unknown fee schedule for {iid}")
        return fee

    def _leg_for(iid: str) -> str:
        return "NO" if leg_of(InstrumentId.from_str(iid)) == "no" else "YES"

    def _station_for(iid: str) -> str:
        return strategy._facts[iid].settlement_station

    def _climate_day_for(iid: str) -> str:
        return strategy._facts[iid].climate_day.isoformat()

    def _hour_lst_for(station: str, now_ns: int) -> int:
        offset = strategy._std_utc_offset_hours_by_station[station]
        return _local_hour(now_ns, offset)

    return PositionMonitor(
        clock_ns=strategy.clock.timestamp_ns,
        positions_open=_positions_open,  # type: ignore[arg-type]
        accumulators=strategy._accumulators,
        latch_record=_latch_record,  # type: ignore[arg-type]
        rung_geometry=_rung_geometry,  # type: ignore[arg-type]
        fee_coefficient_for=_fee_coefficient_for,
        leg_for=_leg_for,  # type: ignore[arg-type]
        station_for=_station_for,
        climate_day_for=_climate_day_for,
        hour_lst_for=_hour_lst_for,
        stale_observation_bound_ns=strategy._config.stale_observation_minutes * _MINUTE_NS,
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        buffer=MarkBuffer(),
        catalog_root=tmp_path / "monitor",
        summaries_dir=tmp_path / "monitor" / "summaries",
        report=lambda event, detail: None,
    )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def test_monitor_trial_id_matches_the_real_fill_write_key(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy._position_monitor = _wire_monitor(strategy, tmp_path=tmp_path)

    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-contract-1")
    strategy.on_order_filled(fill)  # REAL write path: durably records the trial
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    opened = TestEventStubs.position_opened(position)
    strategy.on_position_opened(opened)

    expected_trial_id = trial_id_for(
        CONTINUOUS_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
    )

    # (1) The real write path recorded the trial under EXACTLY this key.
    assert strategy._latch is not None
    raw = strategy._latch._store.get(expected_trial_id)
    assert raw is not None, "trial_id_for() must name the real durable write key"

    # (2) The monitor's own summary reports the identical trial_id.
    strategy.on_stop()
    summaries = read_monitor_summaries(tmp_path / "monitor" / "summaries")
    assert len(summaries) == 1
    assert summaries[0].trial_id == expected_trial_id
