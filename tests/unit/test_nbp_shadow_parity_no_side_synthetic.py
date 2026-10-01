"""FQ-S4b mandatory gate test (plan §3 S4b, peer review disposition 6).

"If the S4a census shows the pre-freeze window holds no NO-leg depth for any
station-day, the report states `no_side_unexercisable_in_window=true` and
the guard requires YES only. In that case, a synthetic NO-path parity case
becomes a mandatory gate test." This file is that case.

A constructed, 2-station-day tape -- real-shaped NBP percentile rows, real
``BinaryOption``/``OrderBookDepth10`` fixtures -- drives NO-leg Depth10 rows
through BOTH the live (native `BacktestEngine`) path and the pure batch path
(``scripts/analysis/nbp_shadow_parity{,_pure}.py``). Both paths must produce
IDENTICAL NO decision keys: at least one NO ``Take`` (day 2, a clean take)
and at least one NO ``Refuse(opposite_side_latched)`` (day 1, after the YES
leg on the SAME rung has already latched), with zero mismatches.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, sibling_instrument_id
from breezy.domain.forecast_point import ForecastPoint
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_VARIABLES
from breezy.strategy.ladder_ev.location_correction import CorrectionForm
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams, Percentiles, Rung
from scripts.analysis.nbp_shadow_parity import run_live_parity
from scripts.analysis.nbp_shadow_parity_pure import (
    OPPOSITE_SIDE_LATCHED,
    BatchCalibration,
    DepthSnapshotRow,
    NbpQuantileRow,
    diff_decision_keys,
    no_depth_census,
    run_batch_parity,
)

STATION = "MIA"
STD_UTC_OFFSET_HOURS = -5.0
LATITUDE_DEG = 25.8
RUNG_ID = "80_81"
LADDER = (
    Rung(rung_id="lt_79", lo=None, hi=79),
    Rung(rung_id=RUNG_ID, lo=80, hi=81),
    Rung(rung_id="82_gte", lo=82, hi=None),
)
FEE_COEFFICIENT = 0.0695
SLIPPAGE_FLOOR_PROB = 0.0
_MODEL_VERSION = "5.0"
_ERA = f"v{_MODEL_VERSION}"

#: Day 1: YES takes first (latching 80_81), then the NO leg on the SAME
#: rung/day must refuse with `opposite_side_latched`.
_DAY_1_CLIMATE_DAY = dt.date(2026, 9, 2)
#: Day 2: NO leg alone, cleanly profitable -- a genuine NO `Take`, never
#: shadowed by an own-day YES evaluation.
_DAY_2_CLIMATE_DAY = dt.date(2026, 9, 3)

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


def _ns(y: int, m: int, d: int, hh: int, mm: int = 0) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.UTC).timestamp()) * 1_000_000_000


# Day 1: boot 2026-09-01, D+1 (MIA, offset -5h) is 2026-09-02.
_DAY_1_YES_TS_NS = _ns(2026, 9, 1, 18, 0)
_DAY_1_NO_TS_NS = _DAY_1_YES_TS_NS + 60_000_000_000
_DAY_1_CYCLE_NS = _ns(2026, 9, 1, 6, 0)
_DAY_1_AVAILABLE_AT_NS = _ns(2026, 9, 1, 7, 0)

# Day 2: boot 2026-09-02, D+1 is 2026-09-03 -- a SEPARATE nominal permit
# window (opened fresh each UTC day, `permit_window_for_day`).
_DAY_2_NO_TS_NS = _ns(2026, 9, 2, 18, 0)
_DAY_2_CYCLE_NS = _ns(2026, 9, 2, 6, 0)
_DAY_2_AVAILABLE_AT_NS = _ns(2026, 9, 2, 7, 0)

STD_OFFSET_BY_STATION = {STATION: STD_UTC_OFFSET_HOURS}
LATITUDE_DEG_BY_STATION = {STATION: LATITUDE_DEG}
LADDER_BY_KEY = {
    (STATION, _DAY_1_CLIMATE_DAY): LADDER,
    (STATION, _DAY_2_CLIMATE_DAY): LADDER,
}


def _facts_info(*, climate_day: dt.date) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: STATION,
        CLIMATE_DAY_KEY: climate_day.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 81,
    }


def _yes_instrument(*, climate_day: dt.date) -> BinaryOption:
    symbol = f"{STATION.lower()}-{climate_day.isoformat()}-{RUNG_ID}"
    instrument_id = InstrumentId(Symbol(symbol), POLYMARKET_US_VENUE)
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description="MIA daily high, FQ-S4b synthetic NO-side fixture",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=_ns(2026, 9, 20, 0, 0),
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(str(FEE_COEFFICIENT)),
        taker_fee=Decimal(str(FEE_COEFFICIENT)),
        ts_event=0,
        ts_init=0,
        info=_facts_info(climate_day=climate_day),
    )


def _no_instrument(yes: BinaryOption) -> BinaryOption:
    no_id = sibling_instrument_id(yes.id)
    return BinaryOption.from_dict(
        {**BinaryOption.to_dict(yes), "id": str(no_id), "raw_symbol": yes.id.symbol.value},
    )


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


def _forecast_points(
    *,
    climate_day: dt.date,
    cycle_ns: int,
    available_at_ns: int,
) -> tuple[ForecastPoint, ...]:
    return tuple(
        ForecastPoint(
            station=STATION,
            model="NBM_NBP",
            model_version=_MODEL_VERSION,
            variable=variable,
            cycle_runtime_ns=cycle_ns,
            valid_start_ns=cycle_ns,
            valid_end_ns=cycle_ns + 24 * 3_600_000_000_000,
            value_f=value,
            issuance_seq=0,
            measured_publication_lag_ns=available_at_ns - cycle_ns,
            available_at_ns=available_at_ns,
            ingested_at_ns=available_at_ns,
        )
        for variable, value in _PERCENTILES.items()
    )


def _nbp_rows(
    *,
    climate_day: dt.date,
    cycle_ns: int,
    available_at_ns: int,
) -> tuple[NbpQuantileRow, ...]:
    return tuple(
        NbpQuantileRow(
            station=STATION,
            variable=variable,
            cycle_runtime_ns=cycle_ns,
            valid_start_ns=cycle_ns,
            valid_end_ns=cycle_ns + 24 * 3_600_000_000_000,
            value_f=value,
            available_at_ns=available_at_ns,
            climate_day=climate_day,
            header_model_version=_MODEL_VERSION,
        )
        for variable, value in _PERCENTILES.items()
    )


def _live_calibration() -> LiveCalibration:
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    return LiveCalibration(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={_ERA: identity},
        draws_by_version={_ERA: (identity,)},
    )


def _batch_calibration() -> BatchCalibration:
    live = _live_calibration()
    return BatchCalibration(
        cdf_method=live.cdf_method,
        correction_form=live.correction_form,
        linear_coefficients=live.linear_coefficients,
        month_offsets=live.month_offsets,
        point_by_version=live.point_by_version,
        draws_by_version=live.draws_by_version,
    )


def _bounds_provider(
    *, percentiles: Percentiles, draws: object, ladder: object, rung_id: str,
) -> RungBounds:
    del percentiles, draws, ladder, rung_id
    # p_lower=0.90 makes the YES take profitable; p_upper=0.10 makes
    # `(1 - p_upper) = 0.90` make the NO take equally profitable -- the
    # SAME fixed stub `test_nbp_shadow_parity_live.py` already uses.
    return RungBounds(p_hat=0.50, p_lower=0.90, p_upper=0.10)


def test_live_and_batch_paths_agree_on_a_synthetic_no_side_scenario() -> None:
    day1_yes = _yes_instrument(climate_day=_DAY_1_CLIMATE_DAY)
    day1_no = _no_instrument(day1_yes)
    day2_yes = _yes_instrument(climate_day=_DAY_2_CLIMATE_DAY)
    day2_no = _no_instrument(day2_yes)

    day1_yes_depth = _depth_frame(day1_yes, ts_ns=_DAY_1_YES_TS_NS, ask_price=0.10, sequence=0)
    day1_no_depth = _depth_frame(day1_no, ts_ns=_DAY_1_NO_TS_NS, ask_price=0.10, sequence=1)
    day2_no_depth = _depth_frame(day2_no, ts_ns=_DAY_2_NO_TS_NS, ask_price=0.10, sequence=0)

    live_keys = run_live_parity(
        instruments=[day1_yes, day1_no, day2_yes, day2_no],
        market_data=[day1_yes_depth, day1_no_depth, day2_no_depth],
        forecast_points=(
            _forecast_points(
                climate_day=_DAY_1_CLIMATE_DAY,
                cycle_ns=_DAY_1_CYCLE_NS,
                available_at_ns=_DAY_1_AVAILABLE_AT_NS,
            )
            + _forecast_points(
                climate_day=_DAY_2_CLIMATE_DAY,
                cycle_ns=_DAY_2_CYCLE_NS,
                available_at_ns=_DAY_2_AVAILABLE_AT_NS,
            )
        ),
        ladder_by_key=LADDER_BY_KEY,
        calibration=_live_calibration(),
        ladder_cfg=LadderEvConfig(slippage_floor_prob=SLIPPAGE_FLOOR_PROB),
        bounds_provider=_bounds_provider,
        fee_coefficient=FEE_COEFFICIENT,
        slippage_floor_prob=SLIPPAGE_FLOOR_PROB,
        std_utc_offset_hours_by_station=STD_OFFSET_BY_STATION,
        stations=(STATION,),
    )

    day1_rows = (
        DepthSnapshotRow(
            instrument_id=str(day1_yes.id), ts_ns=_DAY_1_YES_TS_NS, best_ask_price=0.10,
            best_ask_size=25.0, station=STATION, climate_day=_DAY_1_CLIMATE_DAY, rung_id=RUNG_ID,
            side="yes",
        ),
        DepthSnapshotRow(
            instrument_id=str(day1_no.id), ts_ns=_DAY_1_NO_TS_NS, best_ask_price=0.10,
            best_ask_size=25.0, station=STATION, climate_day=_DAY_1_CLIMATE_DAY, rung_id=RUNG_ID,
            side="no",
        ),
    )
    day2_rows = (
        DepthSnapshotRow(
            instrument_id=str(day2_no.id), ts_ns=_DAY_2_NO_TS_NS, best_ask_price=0.10,
            best_ask_size=25.0, station=STATION, climate_day=_DAY_2_CLIMATE_DAY, rung_id=RUNG_ID,
            side="no",
        ),
    )
    depth_rows = day1_rows + day2_rows

    batch_keys = run_batch_parity(
        depth_snapshots=depth_rows,
        nbp_rows=(
            _nbp_rows(
                climate_day=_DAY_1_CLIMATE_DAY,
                cycle_ns=_DAY_1_CYCLE_NS,
                available_at_ns=_DAY_1_AVAILABLE_AT_NS,
            )
            + _nbp_rows(
                climate_day=_DAY_2_CLIMATE_DAY,
                cycle_ns=_DAY_2_CYCLE_NS,
                available_at_ns=_DAY_2_AVAILABLE_AT_NS,
            )
        ),
        ladder_by_key=LADDER_BY_KEY,
        calibration=_batch_calibration(),
        ladder_cfg=LadderEvConfig(),
        bounds_provider=_bounds_provider,
        fee_coefficient=FEE_COEFFICIENT,
        slippage_floor_prob=SLIPPAGE_FLOOR_PROB,
        std_utc_offset_hours_by_station=STD_OFFSET_BY_STATION,
        latitude_deg_by_station=LATITUDE_DEG_BY_STATION,
    )

    report = diff_decision_keys(live_keys, batch_keys)
    assert report.n_mismatches == 0, report.to_counts_dict()

    no_keys = [key for key in live_keys if key.side == "no"]
    assert any(key.kind == "Take" for key in no_keys), [k.kind for k in no_keys]
    assert any(
        key.kind == "Refuse" and key.reason == OPPOSITE_SIDE_LATCHED for key in no_keys
    ), [(k.kind, k.reason) for k in no_keys]

    batch_no_keys = [key for key in batch_keys if key.side == "no"]
    assert {(k.kind, k.reason) for k in no_keys} == {(k.kind, k.reason) for k in batch_no_keys}

    # Positive control: this fixture is itself the NO-depth census that would
    # make `no_side_unexercisable_in_window` False for a window that
    # included it -- confirming the fixture genuinely exercises the NO leg,
    # never a vacuous all-NotExecutable/NotDPlus1 set.
    assert no_depth_census(depth_rows) == {STATION: 2}
