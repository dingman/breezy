"""LST-midnight hours to settlement (go-live plan S3, decision D1).

Venue ``expiration_ns`` (listing ``endDate``, including 05:00Z) is not the
settlement instant. Hours are measured to LST midnight ending ``climate_day``,
the same instant the pure parity path uses independently. Every D+1 tick is
then at least 24h out, so ``forecast_margin`` is the flat ``m24`` of 0.06.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from breezy.strategy.ladder_ev.config import LadderEvConfig
from scripts.analysis.nbp_shadow_parity_pure import hours_to_settlement as pure_hours_to_settlement
from tests.strategy.forecast_quantile_ladder.test_sl13b_tick_loop import (
    _CLEAR_TAKE_YES,
    _NOW_NS,
    _build_registered,
    _depth,
    _facts_info,
)
from tests.unit.test_current_rung_hold_strategy import CLIMATE_DAY, STATION

_NS_PER_SECOND = 1_000_000_000
_NS_PER_HOUR = 3_600 * _NS_PER_SECOND
_LAX_OFFSET = -8.0
#: Listing metadata, not settlement. 2026-09-04T05:00:00Z.
_EXPIRATION_05Z_NS = int(dt.datetime(2026, 9, 4, 5, 0, tzinfo=dt.UTC).timestamp()) * _NS_PER_SECOND
#: 1 ns before LST midnight that starts CLIMATE_DAY: still D+1, and already
#: past the 05:00Z listing, so the venue clock has clamped to 0h.
_LATE_D1_NS = int(dt.datetime(2026, 9, 4, 8, 0, tzinfo=dt.UTC).timestamp()) * _NS_PER_SECOND - 1
#: One hour after LST midnight ending CLIMATE_DAY (2026-09-05T08:00Z).
_AFTER_SETTLEMENT_NS = (
    int(dt.datetime(2026, 9, 5, 9, 0, tzinfo=dt.UTC).timestamp()) * _NS_PER_SECOND
)
_LAX_ID = InstrumentId.from_str("lax-05z-80-81.POLYMARKET_US")


def _lst_midnight_ns(local_date: dt.date, std_utc_offset_hours: float) -> int:
    naive = dt.datetime.combine(local_date, dt.time(0, 0), tzinfo=dt.UTC)
    utc_instant = naive - dt.timedelta(hours=std_utc_offset_hours)
    return int(utc_instant.timestamp()) * _NS_PER_SECOND


def _instrument_expiring_at_05z() -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=_LAX_ID,
        raw_symbol=_LAX_ID.symbol,
        outcome="Yes",
        description="LAX daily high",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=_EXPIRATION_05Z_NS,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info=_facts_info(
            station=STATION,
            climate_day=CLIMATE_DAY,
            lower_f=80,
            upper_f=81,
        ),
    )


def _capture(strategy: ForecastQuantileLadderStrategy) -> list[float]:
    captured: list[float] = []
    original = strategy.evaluate_snapshot

    def _spy(**kwargs: Any) -> Any:
        captured.append(kwargs["h_hours"])
        return original(**kwargs)

    strategy.evaluate_snapshot = _spy  # type: ignore[method-assign]
    return captured


def _venue_hours(now_ns: int) -> float:
    return max(0.0, (_EXPIRATION_05Z_NS - now_ns) / _NS_PER_HOUR)


def test_a_lax_rung_with_venue_expiration_05z_uses_lst_hours() -> None:
    """A 05:00Z listing must not set h. LST midnight ending the climate day does."""
    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin

    strategy = _build_registered(
        instruments=(_instrument_expiring_at_05z(),),
        bounds_provider=_CLEAR_TAKE_YES,
        shadow_only=True,
    )
    captured = _capture(strategy)
    strategy.on_order_book_depth(_depth(_LAX_ID, asks=(("0.10", 5),), ts_event=_LATE_D1_NS))

    assert strategy.rung_expiration_ns[(STATION, CLIMATE_DAY.isoformat())] == _EXPIRATION_05Z_NS
    assert len(captured) == 1
    lst_h = pure_hours_to_settlement(
        now_ns=_LATE_D1_NS,
        climate_day=CLIMATE_DAY,
        std_utc_offset_hours=_LAX_OFFSET,
    )
    assert captured[0] == lst_h
    assert captured[0] != _venue_hours(_LATE_D1_NS)
    assert forecast_margin(captured[0], LadderEvConfig()) == 0.06
    assert forecast_margin(_venue_hours(_LATE_D1_NS), LadderEvConfig()) == 0.02


@settings(derandomize=True, max_examples=60)
@given(
    year_day=st.integers(min_value=0, max_value=364),
    offset=st.sampled_from((-8.0, -6.0, -5.0)),
    slot_ns=st.integers(min_value=0, max_value=86_400 * _NS_PER_SECOND - 1),
)
def test_every_d_plus_1_tick_has_forecast_margin_0_06(
    year_day: int,
    offset: float,
    slot_ns: int,
) -> None:
    """h >= 24 on every D+1 instant, so the horizon term saturates at m24."""
    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin, hours_to_settlement

    climate_day = dt.date(2026, 1, 1) + dt.timedelta(days=year_day)
    now_ns = _lst_midnight_ns(climate_day - dt.timedelta(days=1), offset) + slot_ns
    h_hours = hours_to_settlement(
        now_ns=now_ns,
        climate_day=climate_day,
        std_utc_offset_hours=offset,
    )
    assert h_hours >= 24.0
    assert forecast_margin(h_hours, LadderEvConfig()) == 0.06


def test_strategy_hours_agree_with_the_pure_path() -> None:
    """The live tick and the untouched pure formula return the same h."""
    strategy = _build_registered(
        instruments=(_instrument_expiring_at_05z(),),
        bounds_provider=_CLEAR_TAKE_YES,
        shadow_only=True,
    )
    captured = _capture(strategy)
    ticks = (_NOW_NS, _LATE_D1_NS, _AFTER_SETTLEMENT_NS)
    for ts_event in ticks:
        strategy.on_order_book_depth(_depth(_LAX_ID, asks=(("0.10", 5),), ts_event=ts_event))

    assert len(captured) == len(ticks)
    for ts_event, live_h in zip(ticks, captured, strict=True):
        pure_h = pure_hours_to_settlement(
            now_ns=ts_event,
            climate_day=CLIMATE_DAY,
            std_utc_offset_hours=_LAX_OFFSET,
        )
        assert live_h == pure_h
        assert live_h != _venue_hours(ts_event)
