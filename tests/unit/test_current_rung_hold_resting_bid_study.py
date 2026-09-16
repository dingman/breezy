"""RED-first tests for the offline "resting bid" counterfactual study, Arm A
(``docs/plans/RESTING_BID_HUNT_2026-09-16.md`` Sec 2).

``scripts/analysis/`` carries no ``__init__.py`` and is not on the default
import path -- this test inserts it into ``sys.path`` (the same pattern
``test_current_rung_hold_exit_window_study.py`` uses for its own sibling
script) and imports ``resting_bid_core``/``resting_bid_report`` as plain
top-level modules.

Every frame/observation below is hand-built and obviously synthetic (no
venue capture is read) -- see ``tests/support/synthetic_binary_tape.py`` for
the repo's standing rationale on why synthetic market data is used here
instead of a capture.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

import resting_bid_core as rbc
import resting_bid_report as rbr

from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

_INSTRUMENT_ID = "tc-temp-sfohigh-2026-01-15-gte70lt71f.POLYMARKET_US"
_STATION = "SFO"
_SEASON = "DJF"
_CLIMATE_DAY = dt.date(2026, 1, 15)
_STD_UTC_OFFSET_HOURS = -8.0
_TZ = dt.timezone(dt.timedelta(hours=_STD_UTC_OFFSET_HOURS))
_MARGIN = Decimal("0.02")
_STALE_BOUND_NS = 50 * 60 * 1_000_000_000


def _ns_at(hour: int, minute: int = 0) -> int:
    local_dt = dt.datetime(
        _CLIMATE_DAY.year, _CLIMATE_DAY.month, _CLIMATE_DAY.day, hour, minute, tzinfo=_TZ,
    )
    return int(local_dt.timestamp() * 1_000_000_000)


def _order(side: OrderSide, price: str, size: str) -> BookOrder:
    return BookOrder(side, Price(float(price), 2), Quantity(float(size), 2), 0)


def _depth(
    *, bids: tuple[tuple[str, str], ...], asks: tuple[tuple[str, str], ...], ts_ns: int,
    instrument_id: str = _INSTRUMENT_ID,
) -> OrderBookDepth10:
    iid = InstrumentId.from_str(instrument_id)
    bid_orders = [_order(OrderSide.BUY, p, s) for p, s in bids]
    ask_orders = [_order(OrderSide.SELL, p, s) for p, s in asks]
    n = max(len(bid_orders), len(ask_orders), 1)
    while len(bid_orders) < n:
        bid_orders.append(_order(OrderSide.BUY, "0", "0"))
    while len(ask_orders) < n:
        ask_orders.append(_order(OrderSide.SELL, "0", "0"))
    return OrderBookDepth10(
        instrument_id=iid, bids=bid_orders, asks=ask_orders,
        bid_counts=[1] * len(bid_orders), ask_counts=[1] * len(ask_orders),
        flags=0, sequence=0, ts_event=ts_ns, ts_init=ts_ns,
    )


def _event(
    *, ts_ns: int, kind: str = "depth", ask: Decimal | None, p_bound: Decimal | None,
    in_window: bool = True, rung_dead: bool = False, stale: bool = False,
) -> rbc.LegEvent:
    return rbc.LegEvent(
        ts_ns=ts_ns, kind=kind, ask=ask, p_bound=p_bound, in_window=in_window,
        rung_dead=rung_dead, stale=stale,
    )


# ---------------------------------------------------------------------------
# 1. A rest never touched: cancelled at window close, no fill.
# ---------------------------------------------------------------------------


def test_an_untouched_rest_is_cancelled_at_window_close_with_no_fill() -> None:
    p_bound = Decimal("0.70")
    p_star = rbc.compute_p_star(p_bound, _MARGIN)
    assert p_star is not None
    high_ask = p_star + Decimal("0.05")
    low_ask = p_star - Decimal("0.01")  # would cross, but only used AFTER window close

    events = [
        _event(ts_ns=_ns_at(13, 0), ask=high_ask, p_bound=p_bound),
        _event(ts_ns=_ns_at(13, 5), ask=high_ask, p_bound=p_bound),
        _event(ts_ns=_ns_at(17, 0), ask=high_ask, p_bound=p_bound, in_window=False),
        _event(ts_ns=_ns_at(17, 10), ask=low_ask, p_bound=p_bound, in_window=False),
    ]

    result = rbc.simulate_leg(events, margin=_MARGIN)

    assert result.rests == 1
    assert result.cancels_by_reason == {"window_close": 1}
    assert result.fill_events == ()


# ---------------------------------------------------------------------------
# 2. A transition fills once; a sustained cross never double-counts.
# ---------------------------------------------------------------------------


def test_a_transition_event_fills_once_and_a_sustained_cross_never_double_counts() -> None:
    p_bound = Decimal("0.70")
    p_star = rbc.compute_p_star(p_bound, _MARGIN)
    assert p_star is not None
    above = p_star + Decimal("0.05")
    at_or_below = p_star

    events = [
        _event(ts_ns=_ns_at(13, 0), ask=above, p_bound=p_bound),
        _event(ts_ns=_ns_at(13, 1), ask=above, p_bound=p_bound),
        _event(ts_ns=_ns_at(13, 2), ask=at_or_below, p_bound=p_bound),
        _event(ts_ns=_ns_at(13, 3), ask=at_or_below, p_bound=p_bound),
        _event(ts_ns=_ns_at(13, 4), ask=at_or_below, p_bound=p_bound),
    ]

    result = rbc.simulate_leg(events, margin=_MARGIN)

    assert result.rests == 1
    assert len(result.fill_events) == 1
    assert result.fill_events[0].ts_ns == _ns_at(13, 2)


# ---------------------------------------------------------------------------
# 3. A fill at/after the cancel's effective instant is not a fill; a fill
#    strictly inside the cancel-latency race window still is.
# ---------------------------------------------------------------------------


def test_a_fill_after_the_cancel_effective_instant_is_not_a_fill() -> None:
    p_bound = Decimal("0.70")
    p_star = rbc.compute_p_star(p_bound, _MARGIN)
    assert p_star is not None
    above = p_star + Decimal("0.05")
    at_or_below = p_star

    kill_ts = _ns_at(13, 30)
    inside_race_ts = kill_ts + rbc.CANCEL_LATENCY_NS // 2
    after_effective_ts = kill_ts + rbc.CANCEL_LATENCY_NS + 1

    events = [
        _event(ts_ns=_ns_at(13, 0), ask=above, p_bound=p_bound),
        _event(ts_ns=kill_ts, ask=above, p_bound=p_bound, rung_dead=True),
        _event(ts_ns=inside_race_ts, ask=at_or_below, p_bound=p_bound, rung_dead=True),
    ]
    result = rbc.simulate_leg(events, margin=_MARGIN)
    assert result.cancels_by_reason == {"rung_death": 1}
    assert len(result.fill_events) == 1
    assert result.fill_events[0].ts_ns == inside_race_ts

    events_late = [
        _event(ts_ns=_ns_at(13, 0), ask=above, p_bound=p_bound),
        _event(ts_ns=kill_ts, ask=above, p_bound=p_bound, rung_dead=True),
        _event(ts_ns=after_effective_ts, ask=at_or_below, p_bound=p_bound, rung_dead=True),
    ]
    result_late = rbc.simulate_leg(events_late, margin=_MARGIN)
    assert result_late.cancels_by_reason == {"rung_death": 1}
    assert result_late.fill_events == ()


# ---------------------------------------------------------------------------
# 4. Adverse-selection classification: I vs L.
# ---------------------------------------------------------------------------


def test_a_fill_is_classified_informed_only_on_a_large_enough_p_bound_drop() -> None:
    fill_ts = _ns_at(13, 30)
    fill = rbc.FillEligibleEvent(
        ts_ns=fill_ts, price=Decimal("0.60"), rest_start_ts_ns=_ns_at(13, 0),
        p_bound_at_fill=Decimal("0.70"),
    )

    liquidity_events = [
        _event(ts_ns=fill_ts + 60_000_000_000, kind="obs", ask=None, p_bound=Decimal("0.68")),
    ]
    assert rbc.classify_fill(fill, liquidity_events) == "L"

    informed_events_big_drop = [
        _event(ts_ns=fill_ts + 60_000_000_000, kind="obs", ask=None, p_bound=Decimal("0.55")),
    ]
    assert rbc.classify_fill(fill, informed_events_big_drop) == "I"

    no_next_observation = [
        _event(
            ts_ns=fill_ts + rbc.ADVERSE_SELECTION_WINDOW_NS + 1, kind="obs", ask=None,
            p_bound=Decimal("0.10"),
        ),
    ]
    assert rbc.classify_fill(fill, no_next_observation) == "L"


# ---------------------------------------------------------------------------
# 5. NO-leg pricing complement, and per-leg rung-death cancel wiring (L-44).
# ---------------------------------------------------------------------------


def test_no_leg_ask_price_is_the_yes_bid_complement() -> None:
    depth = _depth(bids=(("0.30", "5"),), asks=(("0.90", "5"),), ts_ns=_ns_at(13, 0))
    assert rbc.leg_ask_price(depth, "YES") == Decimal("0.90")
    assert rbc.leg_ask_price(depth, "NO") == Decimal(1) - Decimal("0.30")


def test_yes_rung_death_confirms_when_the_running_max_clears_the_rung() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    facts = rbc.bucket_facts(lower_f=70, upper_f=71, station=_STATION, climate_day=_CLIMATE_DAY)
    ts_a = _ns_at(13, 0)
    ts_b = _ns_at(13, 6)

    def _push(ts_ns: int, fahrenheit: int) -> None:
        c_tenths = round((fahrenheit - 32) * 5 / 9 * 10)
        accumulator.push(ts_ns, c_tenths, 5, True, ts_ns)

    _push(ts_a, 80)
    events = rbc.build_leg_events(
        station=_STATION, season=_SEASON, climate_day=_CLIMATE_DAY,
        instrument_id=_INSTRUMENT_ID, leg="YES", facts=facts, accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS, stale_bound_ns=_STALE_BOUND_NS,
        depth_frames=(), observation_visible_ts_ns=(ts_a,),
    )
    assert events[-1].rung_dead is False

    _push(ts_b, 81)
    events = rbc.build_leg_events(
        station=_STATION, season=_SEASON, climate_day=_CLIMATE_DAY,
        instrument_id=_INSTRUMENT_ID, leg="YES", facts=facts, accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS, stale_bound_ns=_STALE_BOUND_NS,
        depth_frames=(), observation_visible_ts_ns=(ts_a, ts_b),
    )
    assert events[0].rung_dead is False
    assert events[-1].rung_dead is True


def test_no_leg_rung_death_confirms_inside_the_rung_after_the_peak_hour() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    facts = rbc.bucket_facts(lower_f=70, upper_f=71, station=_STATION, climate_day=_CLIMATE_DAY)
    ts_a = _ns_at(18, 0)
    ts_b = _ns_at(18, 6)

    c_tenths = round((70 - 32) * 5 / 9 * 10)
    accumulator.push(ts_a, c_tenths, 5, True, ts_a)

    events = rbc.build_leg_events(
        station=_STATION, season=_SEASON, climate_day=_CLIMATE_DAY,
        instrument_id=_INSTRUMENT_ID, leg="NO", facts=facts, accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS, stale_bound_ns=_STALE_BOUND_NS,
        depth_frames=(), observation_visible_ts_ns=(ts_a, ts_b),
    )
    assert events[0].rung_dead is False
    assert events[-1].rung_dead is True


# ---------------------------------------------------------------------------
# 6. IOC baseline reproduces the first executable take.
# ---------------------------------------------------------------------------


def test_ioc_baseline_reproduces_the_first_executable_snapshot() -> None:
    p_bound = Decimal("0.90")
    not_yet_ask = Decimal("0.90")  # too expensive: edge < 0
    executable_ask = Decimal("0.70")  # edge > 0

    events = [
        _event(ts_ns=_ns_at(13, 0), ask=not_yet_ask, p_bound=p_bound),
        _event(ts_ns=_ns_at(13, 5), ask=executable_ask, p_bound=p_bound),
        _event(ts_ns=_ns_at(13, 10), ask=executable_ask, p_bound=p_bound),
    ]

    result = rbc.simulate_leg(events, margin=Decimal("0.02"))

    assert result.ioc_take is not None
    assert result.ioc_take.ts_ns == _ns_at(13, 5)
    assert result.ioc_take.price == executable_ask


# ---------------------------------------------------------------------------
# 7. Stranded vs qualifying station-day coverage.
# ---------------------------------------------------------------------------


def test_stranded_vs_qualifying_station_day_coverage() -> None:
    window_start = _ns_at(12, 0)
    window_end = _ns_at(17, 0)

    dense_ts = list(range(window_start, window_end, 30_000_000_000))
    assert rbc.is_qualifying_station_day(
        rbc.window_coverage_fraction(dense_ts, window_start, window_end),
    )

    stranded_ts = [window_start, window_start + 60_000_000_000]
    assert not rbc.is_qualifying_station_day(
        rbc.window_coverage_fraction(stranded_ts, window_start, window_end),
    )


# ---------------------------------------------------------------------------
# 8. Markdown summary renders the gates.
# ---------------------------------------------------------------------------


def test_markdown_summary_renders_the_registered_gates() -> None:
    summary = rbr.StudySummary(
        qualifying_station_days=30, stranded_station_days=2, fills_by_margin_share={
            (Decimal("0.02"), Decimal("1.0")): 160,
        }, pi_hat_i_by_margin_share={(Decimal("0.02"), Decimal("1.0")): (0.10, 0.20)},
        pnl_sum_maker_by_margin_share={(Decimal("0.02"), Decimal("1.0")): Decimal("12.34")},
        pnl_sum_ioc=Decimal("3.21"), gates=(
            rbr.GateResult(
                gate_id="G-R1", description="honest N", status="PASS", detail="160 fills",
            ),
            rbr.GateResult(
                gate_id="G-R6", description="tape honesty", status="NOT_COMPUTABLE",
                detail="n/a",
            ),
        ),
    )
    markdown = rbr.render_markdown(summary)
    assert "G-R1" in markdown
    assert "PASS" in markdown
    assert "G-R6" in markdown
    assert "NOT_COMPUTABLE" in markdown
    assert "30" in markdown
