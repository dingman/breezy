"""ING-3 regression pin: how the 600 s `RunDeadline` start-gate behaves when the
production 09:45Z rotated-instance run slows down.

Production units (STAGE0_findings.md): quote_tick ~381 s, order_book_depths
~101 s, custom_depth_truncation ~41 s. `QuoteTick`, `OrderBookDepth10` and
`TradeTick` stand in for them (only the durations matter here).

Pinned behaviour on HEAD:

* `RunDeadline.admit` is a START gate. At 1.15x the third unit starts at
  (381+101)*1.15 = 554.3 s < 600 s, so it is admitted and the run finishes at
  601.45 s: it overshoots the budget but stays under the unit's
  `TimeoutStartSec=780`.
* At 1.30x the third unit would start at 626.6 s, so it is deferred
  (`deferred-deadline`, never `failed`), and the next run drains it. One
  deferral run never reaches the stall alert (>= 4 consecutive runs AND
  >= 60 min); a persistent deferral does.

LATENT BOUND (stated, deliberately NOT asserted safe): because the gate only
decides whether a unit may START, the worst-case run wall time is
``budget + largest unit`` ~= 600 + 381*k seconds for slowdown k. A large unit
admitted late in a run can therefore exceed the 780 s `TimeoutStartSec`
(for k=1.15 only a ~180 s unit started just under 600 s would stay inside it).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nautilus_trader.model.data import OrderBookDepth10, QuoteTick, TradeTick

from breezy.runtime.ingest_deadline import DEFERRED_DEADLINE, RunDeadline, count_deferred
from breezy.runtime.ingest_deferral_streak import INITIAL_STATE, step
from breezy.runtime.quote_tape_ingest_core import InstanceIngestResult, run_ingest
from tests.unit.test_quote_tape_ingest_cli import INSTANCE, _never_active, _touch
from tests.unit.test_quote_tape_ingest_deadline import FakeClock

_BUDGET_S = 600
_UNIT_FILE = Path(__file__).resolve().parents[2] / "deploy/systemd/breezy-quote-tape-ingest.service"
_TYPES = (QuoteTick, OrderBookDepth10, TradeTick)
_BASE_DURATIONS_S = {QuoteTick: 381.0, OrderBookDepth10: 101.0, TradeTick: 41.0}
_FILES = ("quote_tick_0", "order_book_depths_0", "trade_tick_0")
_T0 = datetime(2026, 10, 9, 9, 45, tzinfo=UTC)


def _timeout_start_sec() -> int:
    match = re.search(r"^TimeoutStartSec=(\d+)\s*$", _UNIT_FILE.read_text(), re.MULTILINE)
    assert match is not None
    return int(match.group(1))


def _run_once(
    catalog_root: Path, slowdown: float
) -> tuple[InstanceIngestResult, list[type], float]:
    """One run with a fresh 600 s deadline; returns (result, converted, elapsed_s)."""
    clock = FakeClock()
    converted: list[type] = []

    def convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
        converted.append(data_cls)
        clock.advance(_BASE_DURATIONS_S[data_cls] * slowdown)

    deadline = RunDeadline(budget_ns=_BUDGET_S * 1_000_000_000, clock_ns=clock)
    results = run_ingest(
        catalog_root,
        data_types=_TYPES,
        service_active_probe=_never_active,
        convert_fn=convert,
        deadline=deadline,
    )
    assert len(results) == 1
    return results[0], converted, deadline.elapsed_ns / 1e9


def _seed(catalog_root: Path) -> None:
    for name in _FILES:
        _touch(catalog_root, INSTANCE, f"{name}.feather", age_minutes=60)


def _pending(result: InstanceIngestResult) -> bool:
    units, _instances = count_deferred([result])
    return units > 0


def _outcomes(result: InstanceIngestResult) -> dict[type, str]:
    return {tr.data_cls: tr.outcome for tr in result.type_results}


def test_unit_file_timeout_start_sec_is_780() -> None:
    assert _timeout_start_sec() == 780


def test_1_15x_admits_all_three_overshoots_budget_but_stays_under_timeout(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)

    result, converted, elapsed_s = _run_once(tmp_path, 1.15)

    assert converted == [QuoteTick, OrderBookDepth10, TradeTick]
    assert result.outcome == "converted"
    assert DEFERRED_DEADLINE not in _outcomes(result).values()
    assert not _pending(result)
    assert elapsed_s == 601.45 or abs(elapsed_s - 601.45) < 1e-3
    assert elapsed_s > _BUDGET_S  # overshoot is real and tolerated
    assert elapsed_s < _timeout_start_sec()
    # No pending work -> the streak resets/never starts.
    state, alert_due = step(INITIAL_STATE, pending=_pending(result), now=_T0)
    assert state == INITIAL_STATE
    assert alert_due is False


def test_1_30x_defers_last_unit_then_next_run_drains_without_stall_alert(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)

    run1, converted1, _ = _run_once(tmp_path, 1.30)
    assert converted1 == [QuoteTick, OrderBookDepth10]
    assert _outcomes(run1)[TradeTick] == DEFERRED_DEADLINE
    assert run1.outcome == DEFERRED_DEADLINE  # a deferral, not a failure
    assert "failed" not in {o.split("=")[0] for o in _outcomes(run1).values()}
    assert not (tmp_path / "live" / INSTANCE / ".converted-trade_tick").exists()
    state1, alert1 = step(INITIAL_STATE, pending=_pending(run1), now=_T0)
    assert _pending(run1) is True
    assert state1.consecutive_runs == 1
    assert alert1 is False

    run2, converted2, _ = _run_once(tmp_path, 1.30)
    assert converted2 == [TradeTick]
    assert run2.outcome == "converted"
    assert _outcomes(run2)[TradeTick] == "converted"
    assert (tmp_path / "live" / INSTANCE / ".converted-trade_tick").exists()
    state2, alert2 = step(state1, pending=_pending(run2), now=_T0 + timedelta(minutes=15))
    assert alert2 is False
    assert state2 == INITIAL_STATE


def test_persistent_deferral_over_four_runs_and_60_min_reports_alert_due() -> None:
    """Positive control: the same pending=True signal, persisting, does alert."""
    state = INITIAL_STATE
    alerts = []
    for run_index in range(4):
        state, alert_due = step(state, pending=True, now=_T0 + timedelta(minutes=20 * run_index))
        alerts.append(alert_due)
    # Runs at +0, +20, +40, +60 min: the 4th is the first to satisfy both
    # >= 4 consecutive runs and >= 60 min of age.
    assert alerts == [False, False, False, True]
