"""RED-first tests for the fill-time reader (`fill_time_count.py`).

Wires the FILL-TIME count `build_live_family_tally`'s `filled_takes`
parameter requires (`live_family_tally.py:242-267`) -- see
`fill_time_count.py`'s module docstring for the source choice and the
null-hypothesis argument against Nautilus's own `Cache`.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord, trial_id_for

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
    """Write `rows` through the REAL `SqliteStateStore`, closed before the
    reader opens read-only -- so a DDL/pragma change in `sqlite_store.py`
    is caught here rather than by a hand-rolled schema drifting from it."""
    store = SqliteStateStore(path)
    try:
        for key, value in rows.items():
            store.set(key, value)
    finally:
        store.close()


def _trial_row(
    instrument_id: str, *, reason: str = "taken", venue_order_id: str | None = None,
) -> bytes:
    return TrialDayRecord(
        latched_at_ns=1,
        instrument_id=instrument_id,
        ask=Decimal("0.40"),
        reason=reason,
        venue_order_id=venue_order_id,
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


def test_a_trial_row_carrying_the_new_venue_order_id_field_still_decodes(
    ftc_mod: ModuleType, tmp_path: Path
) -> None:
    """Slice 4 schema-compat (finding_trialrecord_compat.md): the new
    TRAILING optional ``venueOrderId`` field on ``TrialDayRecord`` does not
    break the raw-sqlite prefix-filter-then-decode reader this script uses
    -- a row written WITH the field decodes exactly like one without it."""
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            f"{_LIVE_PREFIX}LAX/2026-08-01": _trial_row(
                "LAX-2026-08-01-lt79f", venue_order_id="ord-amb-1",
            ),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-08-01-lt79f"),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=_LIVE_PREFIX)
    assert result == 1


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


def test_a_duplicate_fill_on_one_instrument_does_not_double_count_the_trial(
    ftc_mod: ModuleType, tmp_path: Path,
) -> None:
    """Slice 4 item B1/B2 (plan rev 6.1): a SECOND genuine fill on an
    already-consumed station-day (a v3 duplicate) still lands on the SAME
    `instrument_id` -- this reader counts distinct TAKEN trials, not fills,
    so a duplicate must never inflate `filled_takes`."""
    db_path = tmp_path / "exec_state.sqlite"
    _CONT_PREFIX = "continuous_rung_hold/trial/"
    _make_state_db(
        db_path,
        {
            f"{_CONT_PREFIX}LAX/2026-09-04": _trial_row(
                "LAX-2026-09-04-lt79f", venue_order_id="order-1",
            ),
            "exec/polymarket_us/fill/order-1": _fill_row("order-1", "LAX-2026-09-04-lt79f"),
            "exec/polymarket_us/fill/order-2": _fill_row("order-2", "LAX-2026-09-04-lt79f"),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=_CONT_PREFIX)
    assert result == 1


def test_two_rung_fills_on_one_station_day_count_as_two(
    ftc_mod: ModuleType, tmp_path: Path
) -> None:
    """AUD-05 D-B cause (i), measured on the live exec store: v3 latches are
    ``station/climate_day/instrument_id``. Two rung fills on MDW/2026-09-15
    are two keys. The 2-part-only counter skipped both."""
    prefix = "continuous_rung_hold/trial/"
    rung_a = "tc-temp-mdwhigh-2026-09-15-gte80lt81f.POLYMARKET_US"
    rung_b = "tc-temp-mdwhigh-2026-09-15-gte82lt83f.POLYMARKET_US"
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            trial_id_for(prefix, "MDW", "2026-09-15", rung_a): _trial_row(rung_a),
            trial_id_for(prefix, "MDW", "2026-09-15", rung_b): _trial_row(rung_b),
            "exec/polymarket_us/fill/order-a": _fill_row("order-a", rung_a),
            "exec/polymarket_us/fill/order-b": _fill_row("order-b", rung_b),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=prefix)
    assert result == 2


def test_a_no_leg_fill_is_counted_under_its_composite_instrument_id(
    ftc_mod: ModuleType, tmp_path: Path
) -> None:
    """The live NO latch and its fill share one composite id
    (``...^no.POLYMARKET_US``). Cause (ii) -- a YES-vs-NO form mismatch --
    was measured and is not operative. The NO fill is still uncounted today
    because that key is 3-part."""
    prefix = "continuous_rung_hold/trial/"
    no_id = "tc-temp-miahigh-2026-09-15-gte92lt93f^no.POLYMARKET_US"
    db_path = tmp_path / "exec_state.sqlite"
    _make_state_db(
        db_path,
        {
            trial_id_for(prefix, "MIA", "2026-09-15", no_id): _trial_row(no_id),
            "exec/polymarket_us/fill/order-no": _fill_row("order-no", no_id),
        },
    )
    result = ftc_mod.count_filled_takes(db_path, family_prefix=prefix)
    assert result == 1
