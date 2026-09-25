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

    def instruments(self) -> list[BinaryOption]:
        return [self._target, self._other_station, self._other_day]

    def order_book_depth10(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        self.depth_calls.append({"instrument_ids": instrument_ids, **kwargs})
        return [object()]

    def quote_ticks(self, *, instrument_ids: list[str], **kwargs: Any) -> list[object]:
        self.quote_calls.append({"instrument_ids": instrument_ids, **kwargs})
        return [object()]

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
    assert captured == {
        "climate_day": _DAY,
        "station": _STATION,
        "start": decision_window_ns(climate_day=_DAY, std_utc_offset_hours=offset)[0],
        "end": decision_window_ns(climate_day=_DAY, std_utc_offset_hours=offset)[1],
    }
