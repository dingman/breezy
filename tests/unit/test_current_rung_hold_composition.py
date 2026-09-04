"""Discovery and factory units for ``current_rung_hold`` composition."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
    WEATHER_FACTS_STATUS_UNKNOWN,
)
from breezy.strategy.current_rung_hold.composition import (
    NoTradableInstrumentsError,
    build_current_rung_hold_strategies,
    resolve_station_instrument_ids,
    strategy_component_id,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy

_POLYMARKET_VENUE = Venue("POLYMARKET_US")
_DAY = dt.date(2026, 9, 4)
_TODAY = {station: _DAY for station in SUPPORTED_STATIONS}


def _binary(
    slug: str,
    *,
    info: dict[str, object],
    ts: int = 0,
) -> BinaryOption:
    instrument_id = InstrumentId(Symbol(slug), _POLYMARKET_VENUE)
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description="test",
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
        # ``ts_event``/``ts_init`` are DISTINCT per call (default ``ts=0``
        # keeps every other test's byte-identical, single-file behavior
        # unchanged): the real recorder's re-emitted definitions carry
        # distinct discovery-cycle timestamps, which is exactly what makes
        # ``ParquetDataCatalog`` write a NEW file per cycle instead of
        # silently skipping an identical-name duplicate.
        ts_event=ts,
        ts_init=ts,
        info=info,
    )


def _known(*, station: str, day: dt.date, measure: str = "high") -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: station,
        CLIMATE_DAY_KEY: day.isoformat(),
        MEASURE_KEY: measure,
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 81,
    }


def _write(catalog_root: Path, instruments: list[BinaryOption]) -> None:
    ParquetDataCatalog(str(catalog_root)).write_data(instruments)


def test_strategy_component_id_is_unique_per_station() -> None:
    ids = [strategy_component_id(station) for station in SUPPORTED_STATIONS]
    assert len(ids) == len(set(ids))
    assert ids[0] == "CurrentRungHoldStrategy-LAX"


def test_discovery_keeps_only_high_supported_stations_on_the_station_climate_day(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-laxhigh-2026-09-04-gte80lt81f",
                info=_known(station="LAX", day=_DAY),
            ),
            _binary(
                "tc-temp-laxlow-2026-09-04-gte50lt51f",
                info=_known(station="LAX", day=_DAY, measure="low"),
            ),
            _binary(
                "tc-temp-laxhigh-2026-09-03-gte80lt81f",
                info=_known(station="LAX", day=dt.date(2026, 9, 3)),
            ),
            _binary(
                "tc-temp-nychigh-2026-09-04-lt79f",
                info=_known(station="NYC", day=_DAY),
            ),
            _binary(
                "tc-temp-mdwhigh-2026-09-04-gte90lt91f",
                info=_known(station="MDW", day=_DAY),
            ),
        ],
    )

    resolved = resolve_station_instrument_ids(tmp_path, _TODAY)

    assert [str(iid) for iid in resolved["LAX"]] == [
        "tc-temp-laxhigh-2026-09-04-gte80lt81f.POLYMARKET_US"
    ]
    assert [str(iid) for iid in resolved["MDW"]] == [
        "tc-temp-mdwhigh-2026-09-04-gte90lt91f.POLYMARKET_US"
    ]
    assert resolved["MIA"] == ()
    assert resolved["SFO"] == ()


def test_discovery_falls_back_to_the_slug_when_facts_are_unknown(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-miahigh-2026-09-04-gte91lt92f",
                info={WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_UNKNOWN},
            ),
        ],
    )

    resolved = resolve_station_instrument_ids(tmp_path, _TODAY)

    assert [str(iid) for iid in resolved["MIA"]] == [
        "tc-temp-miahigh-2026-09-04-gte91lt92f.POLYMARKET_US"
    ]


def test_discovery_dedupes_a_definition_re_emitted_across_recorder_cycles(
    tmp_path: Path,
) -> None:
    """The quote-tape recorder re-emits every instrument's definition each
    discovery cycle (docstring above), so ``catalog.instruments()`` returns
    the SAME ``InstrumentId`` many times over several ``write_data`` calls.
    ``resolve_station_instrument_ids`` must collapse those to one id per
    station, first-seen, not one entry per recorded row.
    """
    for cycle in range(4):
        _write(
            tmp_path,
            [
                _binary(
                    "tc-temp-laxhigh-2026-09-04-gte80lt81f",
                    info=_known(station="LAX", day=_DAY),
                    ts=cycle,
                )
            ],
        )

    resolved = resolve_station_instrument_ids(tmp_path, _TODAY)

    assert [str(iid) for iid in resolved["LAX"]] == [
        "tc-temp-laxhigh-2026-09-04-gte80lt81f.POLYMARKET_US"
    ]


@contextmanager
def _unused_latch_factory() -> Iterator[object]:
    yield object()


def test_all_stations_zero_raises_no_tradable_instruments_error(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(NoTradableInstrumentsError) as excinfo:
        build_current_rung_hold_strategies(
            catalog_root=tmp_path,
            today_by_station=_TODAY,
            trial_day_latch_factory=_unused_latch_factory,
        )

    message = str(excinfo.value)
    assert "LAX=0" in message
    assert "MDW=0" in message
    assert "MIA=0" in message
    assert "SFO=0" in message
    assert "2026-09-04" in message


def test_per_station_degradation_skips_zero_and_builds_the_rest(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                info=_known(station="SFO", day=_DAY),
            ),
        ],
    )

    strategies = build_current_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
    )

    assert len(strategies) == 1
    strategy = strategies[0]
    assert isinstance(strategy, CurrentRungHoldStrategy)
    assert strategy._config.stations == ("SFO",)
    assert strategy._config.orders_enabled is False
    assert str(strategy.id) == "CurrentRungHoldStrategy-SFO"
    assert strategy.order_id_tag == "SFO"


def test_on_start_subscribes_each_instrument_exactly_once_despite_re_emitted_definitions(
    tmp_path: Path,
) -> None:
    """End-to-end through ``build_current_rung_hold_strategies`` + a real
    ``on_start``: a catalog holding the SAME instrument recorded 3 times
    (re-emitted definitions, as ``resolve_station_instrument_ids`` documents)
    must still yield exactly ONE ``subscribe_quote_ticks`` call per
    instrument -- never one per recorded row.
    """
    instrument = _binary(
        "tc-temp-sfohigh-2026-09-04-gte70lt71f",
        info=_known(station="SFO", day=_DAY),
    )
    for cycle in range(3):
        _write(
            tmp_path,
            [
                _binary(
                    "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                    info=_known(station="SFO", day=_DAY),
                    ts=cycle,
                )
            ],
        )

    strategies = build_current_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
    )
    assert len(strategies) == 1
    strategy = strategies[0]
    assert strategy._config.instrument_ids == (instrument.id,)

    clock = TestClock()
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    subscribed: list[InstrumentId] = []
    strategy.subscribe_quote_ticks = subscribed.append  # type: ignore[method-assign]
    strategy.start()

    assert subscribed == [instrument.id]


class _FakeRefusals:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}


class _FakeStrategy:
    """Duck-typed stand-in: `install_current_rung_hold_refusal_watch` only
    reads `.refusals`/`.id` and sets `.refusal_alerter` -- it never
    constructs a real `CurrentRungHoldStrategy`.
    """

    def __init__(self, strategy_id: str) -> None:
        self.id = strategy_id
        self.refusals = _FakeRefusals()
        self.refusal_alerter: object | None = None


class TestInstallRefusalWatch:
    def test_a_strategy_is_wired_for_per_tick_reporting_with_no_msgbus_at_all(
        self,
    ) -> None:
        """The primary (per-tick) path needs no `msgbus`, so a `node` with
        none still gets `strategy.refusal_alerter` populated.
        """
        from breezy.strategy.current_rung_hold.composition import (
            install_current_rung_hold_refusal_watch,
        )

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        install_current_rung_hold_refusal_watch(object(), [strategy])  # type: ignore[list-item]

        assert strategy.refusal_alerter is not None

    def test_a_missing_msgbus_logs_a_warning_instead_of_failing_silently(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from breezy.strategy.current_rung_hold.composition import (
            install_current_rung_hold_refusal_watch,
        )

        class _KernellessNode:
            kernel = None

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        with caplog.at_level("WARNING"):
            install_current_rung_hold_refusal_watch(
                _KernellessNode(), [strategy]  # type: ignore[list-item]
            )

        assert any(
            record.levelname == "WARNING" and "msgbus" in record.getMessage()
            for record in caplog.records
        )
        # The primary path still wires despite the missing msgbus.
        assert strategy.refusal_alerter is not None
