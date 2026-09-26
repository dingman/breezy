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
from breezy.strategy.current_rung_hold.monitor_wiring import build_monitor_callables
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
    # F1 DRY extraction: the eight read-only closures come from
    # `build_monitor_callables` (`monitor_wiring.py`) -- the SAME factory
    # `composition.py::_build_position_monitor_for` and the paper-replay
    # driver's `install_position_monitor` also call. This helper still owns
    # everything test-specific: a no-op `report`, a bare `MarkBuffer()`, and
    # a `tmp_path`-scoped catalog/summaries pair.
    callables = build_monitor_callables(strategy)
    return PositionMonitor(
        clock_ns=strategy.clock.timestamp_ns,
        positions_open=callables.positions_open,
        accumulators=strategy._accumulators,
        latch_record=callables.latch_record,
        rung_geometry=callables.rung_geometry,
        fee_coefficient_for=callables.fee_coefficient_for,
        leg_for=callables.leg_for,
        station_for=callables.station_for,
        climate_day_for=callables.climate_day_for,
        hour_lst_for=callables.hour_lst_for,
        sibling_for=callables.sibling_for,
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
