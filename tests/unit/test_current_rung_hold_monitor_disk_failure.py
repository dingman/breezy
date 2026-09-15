"""RED-first test for a REAL disk failure hitting the position monitor
mid-strategy (safety-review finding M2, 2026-09-15).

Companion to M1 (`monitor_store.MarkBuffer.flush` widened to catch
`OSError` -- see `tests/unit/test_current_rung_hold_monitor_store.py`): a
genuine filesystem failure inside a *working* `PositionMonitor`'s catalog
flush, driven through the normal `ContinuousRungHoldStrategy` handler flow
(never a hand-called `PositionMonitor` method), must:

* never affect `TrialDayRecord`/latch state (M7 D3 pin -- the monitor is
  read-only w.r.t. trial selection, same characterisation as
  `test_current_rung_hold_position_monitor.py`'s
  ``test_attached_monitor_produces_identical_latch_state_to_no_monitor``);
* surface ONLY as `flush_errors` on the `PositionMonitor`, never as
  `monitor_errors` -- with M1 applied, `MarkBuffer.flush` contains the
  `OSError` itself, so `PositionMonitor._guarded` and the strategy-level
  `_forward_to_monitor` boundary are never even needed as a second layer;
* never raise into the strategy's own handlers.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.position import Position
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.strategy.current_rung_hold import monitor_store
from tests.unit.test_continuous_rung_hold_fill_wiring import _fill
from tests.unit.test_continuous_rung_hold_strategy import _register, _register_and_start
from tests.unit.test_current_rung_hold_position_monitor import _wire_monitor
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
)

_MINUTE_NS = 60_000_000_000
#: Twice the monitor's own heartbeat (`monitor_decision._HEARTBEAT_NS` = 60s)
#: so every observation forces a fresh emission regardless of state change.
_STEP_NS = 2 * _MINUTE_NS
_N_OBSERVATIONS = 4


def _drive(strategy, *, interior_instrument: BinaryOption) -> None:
    """Open one REAL cache position (`cache.add_position` +
    `portfolio.initialize_positions()`, the same pattern
    `test_continuous_rung_hold_strategy.py` uses -- a bare
    `on_position_opened` event alone leaves `cache.positions_open` empty, so
    the monitor's `_evaluate` would see `held_qty == 0` and never emit),
    then feed enough heartbeat-spaced observations to force several monitor
    emissions (and, with the flush threshold patched down, several flush
    attempts)."""
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-disk-1")
    strategy.on_order_filled(fill)
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.portfolio.initialize_positions()
    strategy.on_position_opened(TestEventStubs.position_opened(position))
    for i in range(_N_OBSERVATIONS):
        strategy.on_data(
            _observation(
                temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS + i * _STEP_NS,
            ),
        )


def test_a_real_disk_failure_during_flush_never_reaches_latch_state_or_monitor_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    interior_instrument = _instrument(INTERIOR_ID, lower_f=86, upper_f=87)

    baseline = _register_and_start(
        store_path=tmp_path / "baseline.db", instruments=(interior_instrument,),
    )
    _drive(baseline, interior_instrument=interior_instrument)
    assert baseline._latch is not None
    baseline_record = baseline._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    baseline_inflight = baseline._latch.is_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )

    # A REAL disk condition, not a monkeypatch: a plain FILE where the
    # monitor's per-climate-day catalog root should be a directory. This
    # holds even when the test process runs as root, unlike a permission-bit
    # simulation -- `root.mkdir(parents=True, exist_ok=True)` inside
    # `open_station_catalog` raises `NotADirectoryError` (an `OSError`
    # subclass) regardless of ownership/permissions.
    blocked_root = tmp_path / "monitor_root_is_a_file"
    blocked_root.write_text("not a directory")

    # Force a flush attempt on every single emission rather than waiting for
    # the real 256-record threshold -- the module-global `should_flush`
    # reads this at call time, so patching it before the drive is sufficient.
    monkeypatch.setattr(monitor_store, "MARK_BUFFER_FLUSH_THRESHOLD", 1)

    attached = _register(store_path=tmp_path / "attached.db", instruments=(interior_instrument,))
    monitor = _wire_monitor(attached, tmp_path=tmp_path)
    monitor._catalog_root = blocked_root  # the only lever onto the real fault
    attached._position_monitor = monitor
    attached.start()

    _drive(attached, interior_instrument=interior_instrument)  # must not raise

    assert attached._latch is not None
    attached_record = attached._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    attached_inflight = attached._latch.is_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )

    assert attached_record == baseline_record
    assert attached_inflight == baseline_inflight

    counters = monitor.counters
    assert counters["flush_errors"] >= 1
    assert counters["monitor_errors"] == 0
    assert attached.position_events.count("monitor_error") == 0

    attached.on_stop()  # exercises on_stop's own flush against the same fault
    counters_after_stop = monitor.counters
    assert counters_after_stop["flush_errors"] >= counters["flush_errors"]
    assert counters_after_stop["monitor_errors"] == 0
    assert attached.position_events.count("monitor_error") == 0
