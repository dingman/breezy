"""RED-first tests wiring `--fill-source` (fill_time_count.py) into the
`live_family_tally.py` CLI, alongside `--covered-listed-station-days`
(needed to make the v1 structural-dead stop evaluable at all -- see
`build_live_family_tally`'s `structural_dead is None` gate,
`live_family_tally.py:311-315`).
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_LIVE_PREFIX = "current_rung_hold/trial/"


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "live_family_tally.py"
    spec = importlib.util.spec_from_file_location("live_family_tally", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tally_mod() -> ModuleType:
    return _load_module()


def _make_state_db(path: Path, rows: dict[str, bytes]) -> None:
    """Write `rows` through the REAL `SqliteStateStore`, closed before the
    reader opens read-only -- see `test_fill_time_count.py`'s twin helper."""
    store = SqliteStateStore(path)
    try:
        for key, value in rows.items():
            store.set(key, value)
    finally:
        store.close()


def _trial_row(instrument_id: str) -> bytes:
    return TrialDayRecord(
        latched_at_ns=1, instrument_id=instrument_id, ask=Decimal("0.40"), reason="taken"
    ).to_bytes()


def _fill_row(venue_order_id: str, instrument_id: str) -> bytes:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"client-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.40"),
        cumulative_fee=Decimal("0.00"),
        fee_reconciled=True,
        ts_event=1,
    ).to_bytes()


def test_with_fill_source_the_structural_dead_line_is_evaluable_not_skipped(
    tally_mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    fill_db = tmp_path / "exec_state.sqlite"
    _make_state_db(
        fill_db,
        {
            f"{_LIVE_PREFIX}LAX/2026-08-01": _trial_row("LAX-2026-08-01-lt79f"),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-08-01-lt79f"),
        },
    )
    exit_code = tally_mod.main(
        [
            str(store_dir),
            "--covered-listed-station-days",
            "15",
            "--fill-source",
            str(fill_db),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "SKIPPED" not in out


def test_without_fill_source_the_structural_dead_line_is_skipped(
    tally_mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    exit_code = tally_mod.main([str(store_dir), "--covered-listed-station-days", "15"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "SKIPPED" in out


def test_fill_since_climate_day_excludes_an_earlier_trial_from_the_count(
    tally_mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pass-through only: an earlier taken+filled trial is scoped out by
    `--fill-since-climate-day`, so filled_takes=0 fires the KILL at 15
    covered-listed days -- proving the CLI actually threads the argument
    through to `count_filled_takes`, not just accepting it."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    fill_db = tmp_path / "exec_state.sqlite"
    _make_state_db(
        fill_db,
        {
            f"{_LIVE_PREFIX}LAX/2026-08-01": _trial_row("LAX-2026-08-01-lt79f"),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-08-01-lt79f"),
        },
    )
    exit_code = tally_mod.main(
        [
            str(store_dir),
            "--covered-listed-station-days",
            "15",
            "--fill-source",
            str(fill_db),
            "--fill-since-climate-day",
            "2026-08-05",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "SKIPPED" not in out
    assert "0 filled Take(s)" in out


def test_fill_source_pointing_at_an_absent_file_is_also_skipped_not_fatal(
    tally_mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    missing = tmp_path / "does-not-exist.sqlite"
    exit_code = tally_mod.main(
        [
            str(store_dir),
            "--covered-listed-station-days",
            "15",
            "--fill-source",
            str(missing),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "SKIPPED" in out
