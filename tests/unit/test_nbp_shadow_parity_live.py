"""SL-13p A-5 shadow-parity: the LIVE (native `BacktestEngine`) path, and its
round-trip against the pure batch path.

`docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-5. Every
fixture here is a synthetic mini-tape plus synthetic NBP quantile rows --
no network, no captured venue payload.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

import scripts.analysis.nbp_shadow_parity as live_module
from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.domain.forecast_point import ForecastPoint
from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_VARIABLES
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Rung,
)
from scripts.analysis.nbp_shadow_parity import run_live_parity
from scripts.analysis.nbp_shadow_parity_pure import (
    DecisionKey,
    DepthSnapshotRow,
    NbpQuantileRow,
    diff_decision_keys,
    run_batch_parity,
)

#: The registry's `(venue, city)` key space is the city TOKEN ("MIA"), never
#: the ICAO station id ("KMIA") -- `SiteRegistry.climate_day_window` (and
#: every sibling accessor) is keyed by `sites.toml`'s `[sites.polymarket_us
#: .MIA]` section name. `ForecastQuantileLadderStrategy.on_start` resolves
#: `std_utc_offset_hours` for every station in `self.config.stations`
#: through that same registry call -- exactly mirroring
#: `forecast_quantile_ladder.composition.build_forecast_quantile_ladder_
#: strategies`, whose `stations` always come from `app.trade._today_by_
#: station`'s `SUPPORTED_STATIONS` (city tokens: LAX/MDW/MIA/SFO), never an
#: ICAO code. `STATION` is threaded through every other identifier in this
#: fixture too (`ForecastPoint.station`, the synthetic instrument symbol,
#: `ForecastQuantileStateActor`'s state keys), so it must be internally
#: consistent one way or the other -- the registry lookup is the one call
#: that fixes which way: the city token.
STATION = "MIA"
STD_UTC_OFFSET_HOURS = -5.0
CLIMATE_DAY = dt.date(2026, 9, 2)
LADDER = (
    Rung(rung_id="lt_79", lo=None, hi=79),
    Rung(rung_id="80_81", lo=80, hi=81),
    Rung(rung_id="82_gte", lo=82, hi=None),
)
LADDER_BY_KEY = {(STATION, CLIMATE_DAY): LADDER}
FEE_COEFFICIENT = 0.0695
SLIPPAGE_FLOOR_PROB = 0.0
STD_OFFSET_BY_STATION = {STATION: STD_UTC_OFFSET_HOURS}

_INSTRUMENT_SYMBOL = f"{STATION.lower()}-{CLIMATE_DAY.isoformat()}-80_81"
_INSTRUMENT_ID = InstrumentId(Symbol(_INSTRUMENT_SYMBOL), POLYMARKET_US_VENUE)
_NO_INSTRUMENT_ID = no_leg_instrument_id(_INSTRUMENT_SYMBOL.lower())


def _ns(y: int, m: int, d: int, hh: int, mm: int = 0) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.UTC).timestamp()) * 1_000_000_000


# Inside the nominal permit window opened on 2026-09-01 (LAUNCH_UTC 16:50,
# 10 h TTL); D+1 of 2026-09-01 LST (offset -5h) is 2026-09-02 (CLIMATE_DAY).
DEPTH_TS_NS = _ns(2026, 9, 1, 18, 0)
_CYCLE_NS = _ns(2026, 9, 1, 6, 0)
_AVAILABLE_AT_NS = _ns(2026, 9, 1, 7, 0)

_PERCENTILES = {
    "TXN_Q10": 68.0,
    "TXN_Q25": 71.0,
    "TXN_Q50": 75.0,
    "TXN_Q75": 79.0,
    "TXN_Q90": 82.0,
    "TXN_MEAN": 75.0,
    "TXN_SD": 3.0,
}
assert set(_PERCENTILES) == set(NBP_QUANTILE_VARIABLES)


def _facts_info() -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: STATION,
        CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 81,
    }


def _instrument(instrument_id: InstrumentId = _INSTRUMENT_ID) -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    option = BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="No" if instrument_id == _NO_INSTRUMENT_ID else "Yes",
        description="MIA daily high, synthetic SL-13p fixture",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=DEPTH_TS_NS + 200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(str(FEE_COEFFICIENT)),
        taker_fee=Decimal(str(FEE_COEFFICIENT)),
        ts_event=0,
        ts_init=0,
        info=_facts_info(),
    )
    if instrument_id == _NO_INSTRUMENT_ID:
        return BinaryOption.from_dict(
            {
                **BinaryOption.to_dict(option),
                "id": str(instrument_id),
                "raw_symbol": _INSTRUMENT_SYMBOL,
            },
        )
    return option


def _book_side(
    levels: tuple[tuple[str, int], ...], side: OrderSide, instrument: BinaryOption,
) -> tuple[list[BookOrder], list[int]]:
    orders = [
        BookOrder(side, Price(float(price), instrument.price_precision),
                  Quantity(size, instrument.size_precision), 0)
        for price, size in levels
    ]
    counts = [1] * len(orders)
    filler = BookOrder(
        side, Price(0, instrument.price_precision), Quantity(0, instrument.size_precision), 0,
    )
    while len(orders) < 10:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _depth_frame(
    instrument: BinaryOption, *, ts_ns: int, ask_price: float, sequence: int,
) -> OrderBookDepth10:
    bids, bid_counts = _book_side((("0.05", 50),), OrderSide.BUY, instrument)
    asks, ask_counts = _book_side(((f"{ask_price:.2f}", 25),), OrderSide.SELL, instrument)
    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=sequence,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def _forecast_points() -> tuple[ForecastPoint, ...]:
    points = []
    for variable, value in _PERCENTILES.items():
        points.append(
            ForecastPoint(
                station=STATION,
                model="NBM_NBP",
                model_version="v5.0",
                variable=variable,
                cycle_runtime_ns=_CYCLE_NS,
                valid_start_ns=_CYCLE_NS,
                valid_end_ns=_CYCLE_NS + 24 * 3_600_000_000_000,
                value_f=value,
                issuance_seq=0,
                measured_publication_lag_ns=_AVAILABLE_AT_NS - _CYCLE_NS,
                available_at_ns=_AVAILABLE_AT_NS,
                ingested_at_ns=_AVAILABLE_AT_NS,
            ),
        )
    return tuple(points)


def _nbp_rows() -> tuple[NbpQuantileRow, ...]:
    return tuple(
        NbpQuantileRow(
            station=STATION,
            variable=variable,
            cycle_runtime_ns=_CYCLE_NS,
            value_f=value,
            available_at_ns=_AVAILABLE_AT_NS,
            climate_day=CLIMATE_DAY,
        )
        for variable, value in _PERCENTILES.items()
    )


def _artefact() -> CalibrationArtefact:
    return CalibrationArtefact(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        emos=EmosParams(a=0.0, gamma=0.0, delta=1.0),
    )


def _bounds_provider(
    *, cdf: Callable[[float], float], ladder: Sequence[Rung], rung_id: str,
) -> RungBounds:
    del cdf, ladder, rung_id
    p_hat = 0.50
    return RungBounds(p_hat=p_hat, p_lower=0.90, p_upper=0.10)


def _run_live(depths: Sequence[OrderBookDepth10]) -> tuple[DecisionKey, ...]:
    return run_live_parity(
        instruments=[_instrument(), _instrument(_NO_INSTRUMENT_ID)],
        market_data=depths,
        forecast_points=_forecast_points(),
        ladder_by_key=LADDER_BY_KEY,
        artefact=_artefact(),
        ladder_cfg=LadderEvConfig(slippage_floor_prob=SLIPPAGE_FLOOR_PROB),
        bounds_provider=_bounds_provider,
        fee_coefficient=FEE_COEFFICIENT,
        slippage_floor_prob=SLIPPAGE_FLOOR_PROB,
        std_utc_offset_hours_by_station=STD_OFFSET_BY_STATION,
        stations=(STATION,),
    )


def _run_batch(rows: Sequence[DepthSnapshotRow]) -> tuple[DecisionKey, ...]:
    return run_batch_parity(
        depth_snapshots=rows,
        nbp_rows=_nbp_rows(),
        ladder_by_key=LADDER_BY_KEY,
        artefact=_artefact(),
        ladder_cfg=LadderEvConfig(),
        bounds_provider=_bounds_provider,
        fee_coefficient=FEE_COEFFICIENT,
        slippage_floor_prob=SLIPPAGE_FLOOR_PROB,
        std_utc_offset_hours_by_station=STD_OFFSET_BY_STATION,
    )


def test_the_live_path_produces_a_take_shadow_decision() -> None:
    instrument = _instrument()
    depth = _depth_frame(instrument, ts_ns=DEPTH_TS_NS, ask_price=0.10, sequence=0)

    keys = _run_live([depth])

    assert len(keys) == 1
    assert keys[0].kind == "Take"
    assert keys[0].station == STATION
    assert keys[0].climate_day == CLIMATE_DAY
    assert keys[0].rung_id == "80_81"
    assert keys[0].side == "yes"
    assert keys[0].ts_ns == DEPTH_TS_NS


def test_the_live_path_uses_the_strategy_depth_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not hasattr(live_module, "_SnapshotDriverActor")
    assert "_SnapshotDriverActor" not in inspect.getsource(live_module)
    calls = 0
    original = ForecastQuantileLadderStrategy.on_order_book_depth

    def counting_handler(
        self: ForecastQuantileLadderStrategy, depth: OrderBookDepth10,
    ) -> None:
        nonlocal calls
        calls += 1
        original(self, depth)

    monkeypatch.setattr(ForecastQuantileLadderStrategy, "on_order_book_depth", counting_handler)
    instrument = _instrument()
    depth = _depth_frame(instrument, ts_ns=DEPTH_TS_NS, ask_price=0.10, sequence=0)

    keys = _run_live([depth])

    assert calls == 1
    assert keys[0].kind == "Take"


def test_the_live_and_batch_paths_agree_on_identical_inputs() -> None:
    instrument = _instrument()
    depth = _depth_frame(instrument, ts_ns=DEPTH_TS_NS, ask_price=0.10, sequence=0)
    row = DepthSnapshotRow(
        instrument_id=str(instrument.id),
        ts_ns=DEPTH_TS_NS,
        best_ask_price=0.10,
        best_ask_size=25.0,
        station=STATION,
        climate_day=CLIMATE_DAY,
        rung_id="80_81",
        side="yes",
    )

    live_keys = _run_live([depth])
    batch_keys = _run_batch([row])

    report = diff_decision_keys(live_keys, batch_keys)

    assert report.n_mismatches == 0, report.to_counts_dict()
    assert report.n_live == report.n_batch == 1


def test_the_live_and_batch_paths_agree_on_a_native_no_take() -> None:
    no_instrument = _instrument(_NO_INSTRUMENT_ID)
    depth = _depth_frame(no_instrument, ts_ns=DEPTH_TS_NS, ask_price=0.10, sequence=0)
    row = DepthSnapshotRow(
        instrument_id=str(no_instrument.id),
        ts_ns=DEPTH_TS_NS,
        best_ask_price=0.10,
        best_ask_size=25.0,
        station=STATION,
        climate_day=CLIMATE_DAY,
        rung_id="80_81",
        side="no",
    )

    live_keys = _run_live([depth])
    batch_keys = _run_batch([row])

    report = diff_decision_keys(live_keys, batch_keys)

    assert report.n_mismatches == 0, report.to_counts_dict()
    assert live_keys[0].side == batch_keys[0].side == "no"
    assert live_keys[0].instrument_id == str(no_instrument.id)


def test_an_injected_divergence_between_live_and_batch_is_detected() -> None:
    """A batch-side bug -- an extra decision the live path never made. """
    instrument = _instrument()
    depth = _depth_frame(instrument, ts_ns=DEPTH_TS_NS, ask_price=0.10, sequence=0)
    genuine_row = DepthSnapshotRow(
        instrument_id=str(instrument.id),
        ts_ns=DEPTH_TS_NS,
        best_ask_price=0.10,
        best_ask_size=25.0,
        station=STATION,
        climate_day=CLIMATE_DAY,
        rung_id="80_81",
        side="yes",
    )
    spurious_row = DepthSnapshotRow(
        instrument_id=str(instrument.id),
        ts_ns=DEPTH_TS_NS + 60_000_000_000,
        best_ask_price=0.09,
        best_ask_size=25.0,
        station=STATION,
        climate_day=CLIMATE_DAY,
        rung_id="80_81",
        side="yes",
    )

    live_keys = _run_live([depth])
    batch_keys = _run_batch([genuine_row, spurious_row])

    report = diff_decision_keys(live_keys, batch_keys)

    assert report.n_mismatches > 0
    assert report.n_batch_only == 1
    assert report.batch_only[0].ts_ns == spurious_row.ts_ns


def test_an_injected_no_side_divergence_is_detected() -> None:
    no_instrument = _instrument(_NO_INSTRUMENT_ID)
    depth = _depth_frame(no_instrument, ts_ns=DEPTH_TS_NS, ask_price=0.10, sequence=0)
    divergent_row = DepthSnapshotRow(
        instrument_id=str(no_instrument.id),
        ts_ns=DEPTH_TS_NS,
        best_ask_price=0.95,
        best_ask_size=25.0,
        station=STATION,
        climate_day=CLIMATE_DAY,
        rung_id="80_81",
        side="no",
    )

    report = diff_decision_keys(_run_live([depth]), _run_batch([divergent_row]))

    assert report.n_mismatches > 0
    assert report.live_only[0].side == "no"
    assert report.batch_only[0].side == "no"


def test_main_refuses_a_date_after_the_pre_freeze_cutoff(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    code = live_module.main(
        [
            "--start-date",
            "2026-09-25",
            "--end-date",
            "2026-09-26",
            "--nbp-derived-root",
            str(tmp_path / "nbp"),
            "--calibration-artefact",
            str(tmp_path / "unused.json"),
            "--calibration-sha256",
            "a" * 64,
            "--output",
            str(output),
        ],
    )

    assert code != 0
    assert not output.exists()


def test_main_refuses_an_artefact_whose_fit_status_is_not_ok(tmp_path: Path) -> None:
    artefact = tmp_path / "artefact.json"
    payload = {
        "schema_version": 1,
        "cdf_method": "normal",
        "delta": 1.0,
        "emos": {"a": 0.0, "gamma": 0.0, "delta": 1.0},
        "emos_draws_by_version": {"v1": [[0.0, 0.0]]},
        "fit_status": "FIT_NOT_CONVERGED",
    }
    raw = json.dumps(payload).encode("utf-8")
    artefact.write_bytes(raw)

    code = live_module.main(
        [
            "--start-date",
            "2026-09-01",
            "--end-date",
            "2026-09-01",
            "--nbp-derived-root",
            str(tmp_path / "nbp"),
            "--calibration-artefact",
            str(artefact),
            "--calibration-sha256",
            __import__("hashlib").sha256(raw).hexdigest(),
            "--output",
            str(tmp_path / "report.json"),
        ],
    )

    assert code != 0
