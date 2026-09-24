"""AUD-05 D-G: the scorer skips a fill past a family's terminal climate day.

Oracle: `assert_family_only`'s inclusive upper bound
(`family_barrier.py`). No new CLI flag. Ruled by
`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` (BLOCKER-1).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import score_live_trials as slt_module
from score_live_trials import main, read_filled_trials_state_db

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

_PREFIX = "continuous_rung_hold/trial/"
_CONT_MANIFEST = REPO_ROOT / "deploy" / "families" / "pm_us_crh_cont.json"
_V4_MANIFEST = REPO_ROOT / "deploy" / "families" / "pm_us_crh_v4.json"


def _seed(path: Path, *, station: str, climate_day: str, instrument_id: str, order_id: str) -> None:
    store = SqliteStateStore(path)
    try:
        store.set(
            f"{_PREFIX}{station}/{climate_day}",
            TrialDayRecord(
                latched_at_ns=1,
                instrument_id=instrument_id,
                ask=Decimal("0.40"),
                reason="taken",
            ).to_bytes(),
        )
        store.set(
            f"{FILL_KEY_PREFIX}{order_id}",
            DurableFillRecord(
                venue_order_id=order_id,
                client_order_id=f"c-{order_id}",
                instrument_id=instrument_id,
                order_side="BUY",
                cumulative_qty=Decimal(1),
                cumulative_cost=Decimal("0.42"),
                cumulative_fee=Decimal("0.01"),
                fee_reconciled=True,
                ts_event=1,
            ).to_bytes(),
        )
    finally:
        store.close()


def _read(path: Path, *, city: str, since: str, until: str | None) -> tuple[Any, ...]:
    trials, _exclusions, _fees, _no_side = read_filled_trials_state_db(
        path,
        family_prefix=_PREFIX,
        city=city,
        cli_location=city,
        since_climate_day=since,
        until_climate_day=until,
        stations=("LAX", "MDW", "MIA", "SFO"),
    )
    return trials


def test_a_fill_after_a_familys_terminal_day_is_refused_for_that_family(tmp_path: Path) -> None:
    store = tmp_path / "state.sqlite"
    _seed(
        store,
        station="MIA",
        climate_day="2026-09-21",
        instrument_id="mia-2026-09-21.POLYMARKET_US",
        order_id="ord-after",
    )
    trials = _read(store, city="MIA", since="2026-09-12", until="2026-09-19")
    assert [t.climate_day for t in trials] == []


def test_a_fill_inside_a_familys_bounds_is_still_scored(tmp_path: Path) -> None:
    cont = tmp_path / "cont.sqlite"
    _seed(
        cont,
        station="MIA",
        climate_day="2026-09-15",
        instrument_id="mia-2026-09-15.POLYMARKET_US",
        order_id="ord-cont",
    )
    cont_trials = _read(cont, city="MIA", since="2026-09-12", until="2026-09-19")
    assert [t.climate_day for t in cont_trials] == ["2026-09-15"]

    v4 = tmp_path / "v4.sqlite"
    _seed(
        v4,
        station="SFO",
        climate_day="2026-09-21",
        instrument_id="sfo-2026-09-21.POLYMARKET_US",
        order_id="ord-v4",
    )
    v4_trials = _read(v4, city="SFO", since="2026-09-20", until=None)
    assert [t.climate_day for t in v4_trials] == ["2026-09-21"]


def test_the_terminal_day_bound_is_inclusive_on_both_edges(tmp_path: Path) -> None:
    store = tmp_path / "state.sqlite"
    store_obj = SqliteStateStore(store)
    try:
        for day, order_id in (("2026-09-12", "ord-d0"), ("2026-09-19", "ord-term")):
            instrument = f"mia-{day}.POLYMARKET_US"
            store_obj.set(
                f"{_PREFIX}MIA/{day}",
                TrialDayRecord(
                    latched_at_ns=1,
                    instrument_id=instrument,
                    ask=Decimal("0.40"),
                    reason="taken",
                ).to_bytes(),
            )
            store_obj.set(
                f"{FILL_KEY_PREFIX}{order_id}",
                DurableFillRecord(
                    venue_order_id=order_id,
                    client_order_id=f"c-{order_id}",
                    instrument_id=instrument,
                    order_side="BUY",
                    cumulative_qty=Decimal(1),
                    cumulative_cost=Decimal("0.42"),
                    cumulative_fee=Decimal("0.01"),
                    fee_reconciled=True,
                    ts_event=1,
                ).to_bytes(),
            )
    finally:
        store_obj.close()
    trials = _read(store, city="MIA", since="2026-09-12", until="2026-09-19")
    assert sorted(t.climate_day for t in trials) == ["2026-09-12", "2026-09-19"]


def test_an_open_family_with_no_terminal_day_is_unbounded_above(tmp_path: Path) -> None:
    store = tmp_path / "state.sqlite"
    _seed(
        store,
        station="MDW",
        climate_day="2026-09-22",
        instrument_id="mdw-2026-09-22.POLYMARKET_US",
        order_id="ord-open",
    )
    trials = _read(store, city="MDW", since="2026-09-20", until=None)
    assert [t.climate_day for t in trials] == ["2026-09-22"]


def test_main_threads_the_manifest_terminal_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def _fake(**kwargs: Any) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
        captured.update(kwargs)
        return (), (), ()

    monkeypatch.setattr(slt_module, "score_live_trials", _fake)
    rc = main(
        [
            "--family-manifest",
            str(_CONT_MANIFEST),
            "--city",
            "MIA",
            "--fill-source",
            str(tmp_path / "state.sqlite"),
            "--catalog-base",
            str(tmp_path / "catalog"),
            "--derived-dir",
            str(tmp_path / "derived"),
        ]
    )
    assert rc == 0
    assert captured["since_climate_day"] == "2026-09-12"
    assert captured["until_climate_day"] == "2026-09-19"

    captured.clear()
    rc_v4 = main(
        [
            "--family-manifest",
            str(_V4_MANIFEST),
            "--city",
            "MIA",
            "--fill-source",
            str(tmp_path / "state.sqlite"),
            "--catalog-base",
            str(tmp_path / "catalog"),
            "--derived-dir",
            str(tmp_path / "derived"),
        ]
    )
    assert rc_v4 == 0
    assert captured["since_climate_day"] == "2026-09-20"
    assert captured["until_climate_day"] is None
