"""RED-first tests: the structural-dead-stop champion counter reads only each
station-day's afternoon window, column-wise, never full Depth10 objects for the
whole catalog (breezy-score-live-trials timeout, 4.4 GB peak since 2026-10-24).

Equivalence oracle: the pre-fix pipeline, `h4_preliminary_economic_read.load_depth`
fed through `covered_listed_station_days`.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

_ANALYSIS = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
_NS = 1_000_000_000
_DAY = dt.date(2026, 9, 1)
_CITY = "LAX"
_LAX_OFFSET = -8.0
_RUNG_A = "tc-temp-laxhigh-2026-09-01-gte72lt73f.POLYMARKET_US"
_RUNG_B = "tc-temp-laxhigh-2026-09-01-gte74lt75f.POLYMARKET_US"
# 12:00 LST (UTC-8) on _DAY is 20:00Z.
_NOON_LST_NS = int(dt.datetime(2026, 9, 1, 20, tzinfo=dt.UTC).timestamp()) * _NS


def _load(name: str) -> ModuleType:
    if str(_ANALYSIS) not in sys.path:
        sys.path.insert(0, str(_ANALYSIS))
    spec = importlib.util.spec_from_file_location(name, _ANALYSIS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sds_mod() -> ModuleType:
    return _load("structural_dead_stop")


@pytest.fixture(scope="module")
def h4_mod() -> ModuleType:
    return _load("h4_preliminary_economic_read")


def _depth(instrument: str, ts_ns: int, *, has_ask: bool) -> OrderBookDepth10:
    pad_bid = BookOrder(OrderSide.BUY, Price(0, 2), Quantity(0, 0), 0)
    pad_ask = BookOrder(OrderSide.SELL, Price(0, 2), Quantity(0, 0), 0)
    asks = [pad_ask] * 10
    ask_counts = [0] * 10
    if has_ask:
        asks[0] = BookOrder(OrderSide.SELL, Price.from_str("0.51"), Quantity.from_int(5), 0)
        ask_counts[0] = 1
    return OrderBookDepth10(
        instrument_id=InstrumentId.from_str(instrument),
        bids=[pad_bid] * 10,
        asks=asks,
        bid_counts=[0] * 10,
        ask_counts=[0] * 10 if not has_ask else ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def _write_catalog(root: Path, rows: Mapping[str, Sequence[tuple[int, bool]]]) -> None:
    catalog = ParquetDataCatalog(str(root))
    for instrument, stamps in rows.items():
        catalog.write_data([_depth(instrument, ts, has_ask=ask) for ts, ask in stamps])


def _minutes(minutes: float) -> int:
    return int(minutes * 60) * _NS


def _count(sds_mod: ModuleType, root: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sds_mod, "_resolved_gaps_from_catalog", lambda _root: ())
    return int(
        sds_mod.count_covered_listed_station_days_from_catalog(
            catalog_root=root, cities=(_CITY,), fetch_start=_DAY, fetch_end=_DAY
        )
    )


def _oracle(sds_mod: ModuleType, h4_mod: ModuleType, root: Path) -> int:
    depth_root = root / "data" / "order_book_depths"
    ma = sys.modules["ma_prelock_winner_ask_study"]

    def loader(city: str, day: dt.date):  # type: ignore[no-untyped-def]
        ids = ma.instrument_ids_for(depth_root=depth_root, city=city, climate_day=day)
        return h4_mod.load_depth(catalog_root=root, instrument_ids=ids)

    return int(
        sds_mod.covered_listed_station_days(
            station_days=[(_CITY, _DAY)],
            load_depth_for_day=loader,
            std_utc_offset_by_city={_CITY: _LAX_OFFSET},
        )
    )


_SCENARIOS = {
    # span 31 min across two rungs; the earliest snapshot has NO ask (still an instant).
    "covered_with_empty_ask_edge": {
        _RUNG_A: [(_NOON_LST_NS - _minutes(5), True), (_NOON_LST_NS + _minutes(1), False)],
        _RUNG_B: [(_NOON_LST_NS + _minutes(32), True)],
    },
    # in-window span only 20 min; outside-window rows must not stretch it.
    "outside_window_rows_ignored": {
        _RUNG_A: [
            (_NOON_LST_NS - _minutes(120), True),
            (_NOON_LST_NS + _minutes(10), True),
            (_NOON_LST_NS + _minutes(30), True),
            (_NOON_LST_NS + _minutes(300), True),  # 17:00 LST exactly: excluded
        ],
    },
    # exactly 30 minutes: boundary stays inclusive of >= 30.0.
    "exactly_thirty_minutes": {
        _RUNG_A: [(_NOON_LST_NS, True), (_NOON_LST_NS + _minutes(30), True)],
    },
    "single_instant": {_RUNG_A: [(_NOON_LST_NS + _minutes(7), True)]},
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_windowed_counter_matches_full_depth_loader(
    sds_mod: ModuleType,
    h4_mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    _write_catalog(tmp_path, _SCENARIOS[scenario])
    expected = _oracle(sds_mod, h4_mod, tmp_path)
    assert _count(sds_mod, tmp_path, monkeypatch) == expected


def test_scenarios_exercise_both_verdicts(
    sds_mod: ModuleType, h4_mod: ModuleType, tmp_path: Path
) -> None:
    _write_catalog(tmp_path, _SCENARIOS["covered_with_empty_ask_edge"])
    assert _oracle(sds_mod, h4_mod, tmp_path) == 1
    other = tmp_path / "other"
    _write_catalog(other, _SCENARIOS["outside_window_rows_ignored"])
    assert _oracle(sds_mod, h4_mod, other) == 0


def test_counter_never_builds_depth10_objects(
    sds_mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_catalog(tmp_path, _SCENARIOS["covered_with_empty_ask_edge"])

    def _forbidden(self: object, *args: object, **kwargs: object) -> None:
        raise AssertionError("catalog.query materialises full Depth10 objects")

    monkeypatch.setattr(ParquetDataCatalog, "query", _forbidden)
    assert _count(sds_mod, tmp_path, monkeypatch) == 1


def test_scan_receives_the_station_days_afternoon_window(
    sds_mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_catalog(tmp_path, _SCENARIOS["covered_with_empty_ask_edge"])
    calls: list[dict[str, object]] = []
    real = sds_mod.scan_depth_window

    def _spy(files: Sequence[str], **kwargs: object):  # type: ignore[no-untyped-def]
        calls.append({"files": list(files), **kwargs})
        return real(files, **kwargs)

    monkeypatch.setattr(sds_mod, "scan_depth_window", _spy)
    _count(sds_mod, tmp_path, monkeypatch)
    assert len(calls) == 2  # one per rung
    for call in calls:
        assert call["start_ns"] == _NOON_LST_NS
        assert call["end_ns"] == _NOON_LST_NS + _minutes(300)
        assert call["ask_masked"] is False
        assert len(call["files"]) == 1  # type: ignore[arg-type]
