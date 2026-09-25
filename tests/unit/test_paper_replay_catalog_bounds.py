from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_KNOWN,
)
from breezy.analysis.replay_sufficiency import decision_window_ns
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
    read_weather_bucket_facts,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_DAY = dt.date(2026, 9, 17)
_STATION = "LAX"


class _Record:
    def __init__(self, ts_init: int) -> None:
        self.ts_init = ts_init


def _load_driver() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py"
    spec = importlib.util.spec_from_file_location("current_rung_hold_paper_replay", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def driver() -> ModuleType:
    return _load_driver()


def _instrument(symbol: str, *, station: str, day: dt.date) -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    instrument_id = InstrumentId(Symbol(symbol), Venue("POLYMARKET_US"))
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description=f"{station} daily high",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: station,
            CLIMATE_DAY_KEY: day.isoformat(),
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: 76,
            STRIKE_UPPER_F_KEY: 77,
            FEE_SCHEDULE_STATUS_KEY: FEE_SCHEDULE_STATUS_KNOWN,
            FEE_COEFFICIENT_KEY: "0.06",
        },
    )


class _SpyCatalog:
    def __init__(self) -> None:
        self._target = _instrument("tc-temp-laxhigh-2026-09-17-gte76lt77", station="LAX", day=_DAY)
        self._other_station = _instrument(
            "tc-temp-mdwhigh-2026-09-17-gte76lt77",
            station="MDW",
            day=_DAY,
        )
        self._other_day = _instrument(
            "tc-temp-laxhigh-2026-09-18-gte76lt77",
            station="LAX",
            day=dt.date(2026, 9, 18),
        )
        self.depth_calls: list[dict[str, Any]] = []
        self.quote_calls: list[dict[str, Any]] = []
        self.close_calls: list[dict[str, Any]] = []
        self.depth_records: list[object] = [object()]
        self.quote_records: list[object] = [object()]

    def instruments(self) -> list[BinaryOption]:
        return [self._target, self._other_station, self._other_day]

    def order_book_depth10(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        self.depth_calls.append({"instrument_ids": instrument_ids, **kwargs})
        return self.depth_records

    def quote_ticks(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        self.quote_calls.append({"instrument_ids": instrument_ids, **kwargs})
        return self.quote_records

    def instrument_closes(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        self.close_calls.append({"instrument_ids": instrument_ids, **kwargs})
        return []


def test_selector_filters_target_station_and_bounds_quote_depth_queries(driver: ModuleType) -> None:
    catalog = _SpyCatalog()
    start_ns, end_ns = 111, 222

    selected = driver._select_capture_instruments(
        catalog,
        climate_day=_DAY,
        station=_STATION,
        start=start_ns,
        end=end_ns,
    )

    assert [ti.facts.settlement_station for ti in selected] == [_STATION]
    assert [str(ti.instrument.id) for ti in selected] == [
        "tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US",
    ]
    assert catalog.depth_calls == [
        {
            "instrument_ids": ["tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US"],
            "start": start_ns,
            "end": end_ns,
        },
    ]
    assert catalog.quote_calls == [
        {
            "instrument_ids": ["tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US"],
            "start": start_ns,
            "end": end_ns,
        },
    ]
    assert catalog.close_calls == [
        {"instrument_ids": ["tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US"]},
    ]


def test_driver_derives_selector_bounds_from_strategy_decision_window(
    driver: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    tape_instrument = driver.TapeInstrument(
        instrument=_instrument("tc-temp-laxhigh-2026-09-17-gte76lt77", station=_STATION, day=_DAY),
        facts=read_weather_bucket_facts(
            _instrument("tc-temp-laxhigh-2026-09-17-gte76lt77", station=_STATION, day=_DAY).info,
        ),
        depths=[],
        quotes=[],
        closes=[],
    )

    def _select(catalog: object, **kwargs: Any) -> list[object]:
        captured.update(kwargs)
        return [tape_instrument]

    monkeypatch.setattr(
        driver,
        "_warmup_start_ns_for_replay",
        lambda *_args, **_kwargs: decision_window_ns(
            climate_day=_DAY,
            std_utc_offset_hours=driver.default_registry()
            .climate_day_window(driver.WEATHER_VENUE, _STATION)
            .std_utc_offset_hours,
        )[0]
        - 123,
    )
    monkeypatch.setattr(driver, "_convert_live_capture", lambda **_kwargs: object())
    monkeypatch.setattr(driver, "_select_capture_instruments", _select)
    monkeypatch.setattr(driver, "assert_requested_days_are_listed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(driver, "print_tape_instrument_header", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(driver, "assert_decision_window_has_coverage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(driver, "climate_day_records_to_settlement", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(driver, "read_asos_rows", lambda _path: [])
    monkeypatch.setattr(
        driver,
        "run_one_precision_arm",
        lambda **_kwargs: driver.PrecisionArmResult(trials=()),
    )

    argv = [
        "--climate-day", _DAY.isoformat(),
        "--station", _STATION,
        "--tape-instance-id", "x",
        "--quote-catalog", str(tmp_path / "capture"),
        "--work-catalog", str(tmp_path / "work"),
        "--asos-cache-csv", str(tmp_path / "asos.csv"),
        "--weather-catalog-root", str(tmp_path / "weather"),
        "--lag-minutes", "30",
        "--output-dir", str(tmp_path / "out"),
    ]
    assert driver.main(argv) == 0

    offset = driver.default_registry().climate_day_window(
        driver.WEATHER_VENUE,
        _STATION,
    ).std_utc_offset_hours
    window_start = decision_window_ns(climate_day=_DAY, std_utc_offset_hours=offset)[0]
    assert captured == {
        "climate_day": _DAY,
        "station": _STATION,
        "start": window_start - 123,
        "end": None,
    }


def test_replay_warmup_start_uses_latest_pre_window_quote_and_depth_records(
    driver: ModuleType,
) -> None:
    catalog = _SpyCatalog()
    window_start = 1_000
    catalog.depth_records = [_Record(200), _Record(900), _Record(1_100)]
    catalog.quote_records = [_Record(400), _Record(850), _Record(1_050)]

    start = driver._warmup_start_ns_for_replay(
        catalog,
        climate_day=_DAY,
        station=_STATION,
        window_start_ns=window_start,
    )

    assert start == 850
    assert start < window_start
    assert catalog.depth_calls == [
        {
            "instrument_ids": ["tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US"],
            "end": window_start,
        },
    ]
    assert catalog.quote_calls == [
        {
            "instrument_ids": ["tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US"],
            "end": window_start,
        },
    ]


def test_replay_warmup_falls_back_to_window_start_with_no_pre_window_record(
    driver: ModuleType,
) -> None:
    """No book/quote record exists at-or-before the window: there is no
    prior state to warm from, so the read starts exactly at the window
    open -- never earlier (which would replay history nothing needs) and
    never later (which would truncate the window itself)."""
    catalog = _SpyCatalog()
    window_start = 1_000
    catalog.depth_records = [_Record(1_100), _Record(1_200)]
    catalog.quote_records = [_Record(1_050)]

    start = driver._warmup_start_ns_for_replay(
        catalog,
        climate_day=_DAY,
        station=_STATION,
        window_start_ns=window_start,
    )

    assert start == window_start


class _MultiInstrumentSpyCatalog:
    """`_SpyCatalog` variant carrying more than one station/day-matching
    instrument -- needed to pin `_warmup_start_ns_for_replay`'s min-across-
    instruments reduction; `_SpyCatalog` above always resolves to exactly
    one match."""

    def __init__(self, targets: list[BinaryOption]) -> None:
        self._targets = targets
        self.depth_calls: list[dict[str, Any]] = []
        self.quote_calls: list[dict[str, Any]] = []
        self.depth_records_by_id: dict[str, list[object]] = {}
        self.quote_records_by_id: dict[str, list[object]] = {}

    def instruments(self) -> list[BinaryOption]:
        return list(self._targets)

    def order_book_depth10(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        self.depth_calls.append({"instrument_ids": instrument_ids, **kwargs})
        [instrument_id] = instrument_ids
        return self.depth_records_by_id.get(instrument_id, [])

    def quote_ticks(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        self.quote_calls.append({"instrument_ids": instrument_ids, **kwargs})
        [instrument_id] = instrument_ids
        return self.quote_records_by_id.get(instrument_id, [])

    def instrument_closes(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        return []


def test_replay_warmup_start_is_the_minimum_across_instruments(driver: ModuleType) -> None:
    """Two station/day instruments with DIFFERENT last pre-window records:
    the replay must start early enough to warm BOTH, i.e. at the earlier
    (minimum) of the two -- not just the first instrument discovered."""
    window_start = 1_000
    instrument_a = _instrument("tc-temp-laxhigh-2026-09-17-a", station=_STATION, day=_DAY)
    instrument_b = _instrument("tc-temp-laxhigh-2026-09-17-b", station=_STATION, day=_DAY)
    catalog = _MultiInstrumentSpyCatalog([instrument_a, instrument_b])
    id_a, id_b = str(instrument_a.id), str(instrument_b.id)
    catalog.depth_records_by_id = {id_a: [_Record(900)], id_b: [_Record(700)]}
    catalog.quote_records_by_id = {id_a: [], id_b: []}

    start = driver._warmup_start_ns_for_replay(
        catalog,
        climate_day=_DAY,
        station=_STATION,
        window_start_ns=window_start,
    )

    assert start == 700


def test_late_listed_rung_is_selected_and_kept_unbounded_at_the_end(
    driver: ModuleType,
) -> None:
    """A rung with no records before the (warmed-up) start bound but real
    records after it is a LATE LISTING, not a gap -- `_select_capture_
    instruments` must still select it as trade-eligible, and `end=None`
    must reach the catalog unbounded so nothing after it is truncated."""
    catalog = _SpyCatalog()
    start_ns = 1_000
    catalog.depth_records = [_Record(1_500), _Record(2_000)]  # both AFTER start_ns
    catalog.quote_records = [_Record(1_600)]

    selected = driver._select_capture_instruments(
        catalog,
        climate_day=_DAY,
        station=_STATION,
        start=start_ns,
        end=None,
    )

    assert [str(ti.instrument.id) for ti in selected] == [
        "tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US",
    ]
    assert catalog.depth_calls == [
        {
            "instrument_ids": ["tc-temp-laxhigh-2026-09-17-gte76lt77.POLYMARKET_US"],
            "start": start_ns,
            "end": None,
        },
    ]
