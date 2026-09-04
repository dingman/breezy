"""RED-first tests for the fill-time reader (`fill_time_count.py`).

Wires the FILL-TIME count `build_live_family_tally`'s `filled_takes`
parameter requires (`live_family_tally.py:242-267`) -- see
`fill_time_count.py`'s module docstring for the source choice and the
null-hypothesis argument against Nautilus's own `Cache`.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_LIVE_PREFIX = "current_rung_hold/trial/"
_PAPER_PREFIX = "paper_replay/current_rung_hold/trial/"


def _load_module() -> ModuleType:
    path = _SCRIPTS_ANALYSIS_DIR / "fill_time_count.py"
    spec = importlib.util.spec_from_file_location("fill_time_count", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ftc_mod() -> ModuleType:
    return _load_module()


def _make_state_db(path: Path, rows: dict[str, bytes]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        conn.executemany("INSERT INTO state (key, value) VALUES (?, ?)", rows.items())
        conn.commit()
    finally:
        conn.close()


def _trial_row(instrument_id: str, *, reason: str = "taken") -> bytes:
    return TrialDayRecord(
        latched_at_ns=1,
        instrument_id=instrument_id,
        ask=Decimal("0.40"),
        reason=reason,
    ).to_bytes()


def _fill_row(venue_order_id: str, instrument_id: str) -> bytes:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"client-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.40"),
        ts_event=1,
    ).to_bytes()


def test_absent_source_path_returns_none(ftc_mod: ModuleType, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.sqlite"
    result = ftc_mod.count_filled_takes(missing, family_prefix=_LIVE_PREFIX)
    assert result is None


def test_unreadable_source_returns_none(ftc_mod: ModuleType, tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.sqlite"
    garbage.write_bytes(b"not a sqlite file at all")
    result = ftc_mod.count_filled_takes(garbage, family_prefix=_LIVE_PREFIX)
    assert result is None


def test_two_fills_one_settled_one_not_counts_two(ftc_mod: ModuleType, tmp_path: Path) -> None:
    """The reader never distinguishes settled from unsettled -- both are
    fill-time fills the instant `DurableFillRecord` was committed."""
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            f"{_LIVE_PREFIX}LAX/2026-08-01": _trial_row("LAX-2026-08-01-lt79f"),
            f"{_LIVE_PREFIX}MDW/2026-08-02": _trial_row("MDW-2026-08-02-gte78f"),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-08-01-lt79f"),
            "exec/polymarket_us/fill/order-2": _fill_row("order-2", "MDW-2026-08-02-gte78f"),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=_LIVE_PREFIX)
    assert result == 2


def test_a_taken_trial_with_no_matching_fill_is_not_counted(
    ftc_mod: ModuleType, tmp_path: Path
) -> None:
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            f"{_LIVE_PREFIX}LAX/2026-08-01": _trial_row("LAX-2026-08-01-lt79f"),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=_LIVE_PREFIX)
    assert result == 0


def test_a_refused_not_taken_trial_is_never_counted_even_with_a_fill(
    ftc_mod: ModuleType, tmp_path: Path
) -> None:
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            f"{_LIVE_PREFIX}LAX/2026-08-01": _trial_row(
                "LAX-2026-08-01-lt79f", reason="fee_schedule_mismatch"
            ),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-08-01-lt79f"),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=_LIVE_PREFIX)
    assert result == 0


def test_a_foreign_family_prefix_row_is_never_counted(
    ftc_mod: ModuleType, tmp_path: Path
) -> None:
    """A `paper_replay/...` row is never pooled into the live family's count,
    even though it shares the `current_rung_hold/trial/` substring."""
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            f"{_PAPER_PREFIX}LAX/2026-08-01": _trial_row("LAX-2026-08-01-lt79f"),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-08-01-lt79f"),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=_LIVE_PREFIX)
    assert result == 0


def test_since_climate_day_excludes_earlier_trials(ftc_mod: ModuleType, tmp_path: Path) -> None:
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            f"{_LIVE_PREFIX}LAX/2026-08-01": _trial_row("LAX-2026-08-01-lt79f"),
            f"{_LIVE_PREFIX}LAX/2026-08-10": _trial_row("LAX-2026-08-10-lt79f"),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-08-01-lt79f"),
            "exec/polymarket_us/fill/order-2": _fill_row("order-2", "LAX-2026-08-10-lt79f"),
        },
    )
    result = ftc_mod.count_filled_takes(
        db_path, family_prefix=_LIVE_PREFIX, since_climate_day="2026-08-05"
    )
    assert result == 1
