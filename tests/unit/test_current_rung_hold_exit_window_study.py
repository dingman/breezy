"""RED-first tests for the offline "exit window" study
(``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md``).

``scripts/analysis/`` carries no ``__init__.py`` and is not on the default
import path -- this test inserts it into ``sys.path`` (the same pattern
``test_current_rung_hold_monitor_hypothetical_hold.py`` uses for its own
sibling script) and then imports ``exit_window_core``/``exit_window_report``
as plain top-level modules.

Every frame/observation below is hand-built and obviously synthetic (no
venue capture is read) -- see ``tests/support/synthetic_binary_tape.py`` for
the repo's standing rationale on why synthetic market data is used here
instead of a capture.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Self

import httpx
import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.runtime import alert_ladder
from breezy.settlement.trial_scorer import FilledTrial
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator, RunningMax

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

import current_rung_hold_exit_window_study as study_mod
import exit_window_core as ewc
import exit_window_report as ewr
import ma_prelock_winner_ask_study as prelock
import portfolio_roi_report as prr
import settlement_alignment_study as settlement

_STD_UTC_OFFSET_HOURS = -8.0  # Pacific standard time, matches SFO
_STATION = "SFO"
_SEASON = "DJF"  # January
_CLIMATE_DAY = dt.date(2026, 1, 15)
_FEE_COEFFICIENT = Decimal("0.06")
_TZ = dt.timezone(dt.timedelta(hours=_STD_UTC_OFFSET_HOURS))
_RUNG = (86, 87)
_INSTRUMENT_ID = "sfo-86-87.POLYMARKET_US"
_STALE_BOUND_NS = CurrentRungHoldConfig().stale_observation_minutes * 60_000_000_000


def _ns_at(hour: int, minute: int = 0) -> int:
    local_dt = dt.datetime(
        _CLIMATE_DAY.year, _CLIMATE_DAY.month, _CLIMATE_DAY.day, hour, minute, tzinfo=_TZ,
    )
    return int(local_dt.timestamp() * 1_000_000_000)


def _push_metar(accumulator: RunningExtremeAccumulator, ts_ns: int, fahrenheit: int) -> None:
    """Push an EXACT (METAR) reading at ``fahrenheit``, ``received_at_ns ==
    observed_at_ns`` -- reproduces the archive oracle."""
    c_tenths = round((fahrenheit - 32) * 5 / 9 * 10)
    accumulator.push(ts_ns, c_tenths, 5, True, ts_ns)


def _order(side: OrderSide, price: str, size: str) -> BookOrder:
    return BookOrder(side, Price(float(price), 2), Quantity(float(size), 2), 0)


def _depth(
    *, bids: tuple[tuple[str, str], ...], asks: tuple[tuple[str, str], ...], ts_ns: int,
    instrument_id: str = _INSTRUMENT_ID,
) -> OrderBookDepth10:
    """A real ``OrderBookDepth10`` -- equal bid/ask lengths, zero-size filler
    on the shorter side (mirrors the sibling monitor test's ``_depth``)."""
    iid = InstrumentId.from_str(instrument_id)
    bid_orders = [_order(OrderSide.BUY, p, s) for p, s in bids]
    ask_orders = [_order(OrderSide.SELL, p, s) for p, s in asks]
    n = max(len(bid_orders), len(ask_orders), 1)
    while len(bid_orders) < n:
        bid_orders.append(_order(OrderSide.BUY, "0", "0"))
    while len(ask_orders) < n:
        ask_orders.append(_order(OrderSide.SELL, "0", "0"))
    return OrderBookDepth10(
        instrument_id=iid,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1] * len(bid_orders),
        ask_counts=[1] * len(ask_orders),
        flags=0,
        sequence=0,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def _position(*, leg: str = "YES", fill_px: Decimal = Decimal("0.40"),
              filled_at_ns: int) -> ewc.FilledPosition:
    return ewc.FilledPosition(
        trial_id=f"t:{_STATION}:{_CLIMATE_DAY.isoformat()}:{_INSTRUMENT_ID}",
        station=_STATION,
        climate_day=_CLIMATE_DAY.isoformat(),
        season=_SEASON,
        instrument_id=_INSTRUMENT_ID,
        leg=leg,  # type: ignore[arg-type]
        rung=_RUNG,
        fill_px=fill_px,
        fee=Decimal("0.02"),
        held_qty=1,
        filled_at_ns=filled_at_ns,
    )


def _timeline(
    *, position: ewc.FilledPosition, accumulator: RunningExtremeAccumulator,
    depth_frames: tuple[OrderBookDepth10, ...] = (), observation_ts_ns: tuple[int, ...] = (),
) -> ewc.ExitTimeline:
    return ewc.build_exit_timeline(
        position=position,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        depth_frames=depth_frames,
        observation_ts_ns=observation_ts_ns,
    )


# ---------------------------------------------------------------------------
# 1. YES DEAD, executable exit at confirmation
# ---------------------------------------------------------------------------


def test_yes_position_dead_at_expected_instant_and_r_dead_sells_at_the_frame_bid() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    _push_metar(accumulator, _ns_at(13, 30), 86)  # entry reading
    position = _position(filled_at_ns=_ns_at(14, 5))
    _push_metar(accumulator, _ns_at(14, 10), 95)
    _push_metar(accumulator, _ns_at(14, 20), 95)
    fillable_frame = _depth(bids=(("0.05", "5"),), asks=(), ts_ns=_ns_at(14, 19))

    timeline = _timeline(
        position=position, accumulator=accumulator, depth_frames=(fillable_frame,),
        observation_ts_ns=(_ns_at(14, 10), _ns_at(14, 20)),
    )

    assert timeline.first_dead_ts_ns == _ns_at(14, 20)

    hold_pnl_value = ewc.hold_pnl(position, settled_held=False)
    outcome = ewc.r_dead_outcome(timeline, hold_pnl_value=hold_pnl_value)
    assert outcome.status == "exited"
    assert outcome.exit_price == Decimal("0.05")
    assert outcome.pnl is not None
    assert outcome.pnl != hold_pnl_value


# ---------------------------------------------------------------------------
# 2. NO plateau DEAD (post-2026-09-16 correction) + R-THREAT fires earlier
# ---------------------------------------------------------------------------


def test_no_position_frozen_inside_rung_confirms_dead_via_plateau_after_threatened() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    position = _position(leg="NO", fill_px=Decimal("0.60"), filled_at_ns=_ns_at(12, 5))

    # The running-max interval NEVER moves off 87F (inside the rung the
    # whole day), but fresh METAR readings keep arriving at each evaluation
    # instant so staleness never trips ("frozen max", not "frozen tape").
    pre_peak = (_ns_at(12, 20), _ns_at(12, 35), _ns_at(12, 50))
    post_peak = (_ns_at(18, 5), _ns_at(18, 15))
    for ts_ns in (_ns_at(12, 0), *pre_peak, *post_peak):
        _push_metar(accumulator, ts_ns, 87)

    timeline = _timeline(
        position=position, accumulator=accumulator, observation_ts_ns=pre_peak + post_peak,
    )

    assert timeline.first_threatened_ts_ns == _ns_at(12, 50)
    assert timeline.first_dead_ts_ns == _ns_at(18, 15)
    assert timeline.first_threatened_ts_ns < timeline.first_dead_ts_ns


# ---------------------------------------------------------------------------
# 3. Exit side empties before DEAD confirms
# ---------------------------------------------------------------------------


def test_exit_side_emptied_before_dead_makes_r_dead_unfillable_and_r_best_picks_the_earlier_frame() -> None:  # noqa: E501
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    _push_metar(accumulator, _ns_at(13, 30), 86)
    position = _position(filled_at_ns=_ns_at(14, 5))
    early_fillable_frame = _depth(bids=(("0.35", "5"),), asks=(), ts_ns=_ns_at(14, 7))
    empties_for_good = _depth(bids=(), asks=(), ts_ns=_ns_at(14, 15))
    _push_metar(accumulator, _ns_at(14, 10), 95)
    _push_metar(accumulator, _ns_at(14, 20), 95)

    timeline = _timeline(
        position=position, accumulator=accumulator,
        depth_frames=(early_fillable_frame, empties_for_good),
        observation_ts_ns=(_ns_at(14, 10), _ns_at(14, 20)),
    )

    assert timeline.first_dead_ts_ns == _ns_at(14, 20)
    # The 14:07 frame stays the LATEST known frame through the 14:10
    # evaluation (the emptying frame does not land until 14:15) -- so 14:10
    # is the last instant a non-None walk result was reported, not 14:07.
    assert timeline.last_executable_ts_ns == _ns_at(14, 10)
    assert timeline.last_executable_ts_ns < timeline.first_dead_ts_ns

    hold_pnl_value = ewc.hold_pnl(position, settled_held=False)
    dead_outcome = ewc.r_dead_outcome(timeline, hold_pnl_value=hold_pnl_value)
    assert dead_outcome.status == "unfillable"
    assert dead_outcome.pnl == hold_pnl_value

    # R-BEST picks the EARLIER of the two equally-priced fillable
    # evaluations (14:07, 14:10) -- the first maximiser, never a later one.
    best_outcome = ewc.r_best_outcome(timeline, hold_pnl_value=hold_pnl_value)
    assert best_outcome.status == "exited"
    assert best_outcome.exit_ts_ns == _ns_at(14, 7)
    assert best_outcome.exit_price == Decimal("0.35")


# ---------------------------------------------------------------------------
# 4. A winning YES position: R-THREAT's premature exit costs money vs hold
# ---------------------------------------------------------------------------


def test_winning_position_r_threat_premature_exit_costs_money_vs_hold() -> None:
    # (SFO, DJF, hour_lst=13, width_code=0): m=0 -> p_hold=0.4929, m=1 ->
    # p_hold=0.3774 (breezy.strategy.current_rung_hold.archive_table
    # .P_HOLD_LOWER) -- a genuine >= 0.10 drop, unlike hour 14 (only 0.0959).
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    _push_metar(accumulator, _ns_at(12, 30), 86)  # entry reading, m_code=0
    position = _position(filled_at_ns=_ns_at(13, 5))
    # A p_hold drop candidate (m 0 -> 1) that never recovers, confirmed over
    # 3 evaluations spanning >= 10 min -- never DEAD, never LOCKED (hour < 18
    # throughout, running max stays inside the rung at 87).
    _push_metar(accumulator, _ns_at(13, 10), 87)
    threatened_frame = _depth(bids=(("0.30", "5"),), asks=(), ts_ns=_ns_at(13, 20))

    timeline = _timeline(
        position=position, accumulator=accumulator, depth_frames=(threatened_frame,),
        observation_ts_ns=(_ns_at(13, 10), _ns_at(13, 30)),
    )

    assert timeline.first_dead_ts_ns is None
    assert timeline.first_threatened_ts_ns == _ns_at(13, 30)

    hold_pnl_value = ewc.hold_pnl(position, settled_held=True)  # settles inside [86, 87]
    threat_outcome = ewc.r_threat_outcome(timeline, hold_pnl_value=hold_pnl_value)
    assert threat_outcome.status == "exited"
    assert hold_pnl_value is not None
    assert threat_outcome.pnl is not None
    assert threat_outcome.pnl < hold_pnl_value  # premature exit cost is negative vs hold


# ---------------------------------------------------------------------------
# 4b. AUD-07 B2: the negative-median closing check, through the REAL writer
# path (build_exit_timeline replay, never a hand-set ExitTimeline) -- a
# synthetic timeline would hide exactly the class of defect the 0-vs-5
# disagreement already demonstrated (L-42).
# ---------------------------------------------------------------------------


def test_a_threatened_confirmation_before_the_exit_side_empties_yields_a_negative_delta() -> None:
    """Mirrors the one real R-THREAT firing on record (MIA NO leg, 09-15):
    THREATENED confirms, and the exit side STILL has liquidity afterward --
    delta_i = threatened - last_executable < 0, classified BEFORE."""
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    _push_metar(accumulator, _ns_at(12, 30), 86)  # entry reading, m_code=0
    position = _position(filled_at_ns=_ns_at(13, 5))
    _push_metar(accumulator, _ns_at(13, 10), 87)  # m 0 -> 1 drop begins
    # Same THREATENED-confirming frame as
    # test_winning_position_r_threat_premature_exit_costs_money_vs_hold
    # (depth is required for the monitor to assess THREATENED at all), plus
    # a SECOND, LATER fillable frame -- the exit side still has liquidity
    # well after THREATENED confirms at 13:30.
    threatened_frame = _depth(bids=(("0.30", "5"),), asks=(), ts_ns=_ns_at(13, 20))
    later_fillable_frame = _depth(bids=(("0.20", "5"),), asks=(), ts_ns=_ns_at(13, 40))

    timeline = _timeline(
        position=position, accumulator=accumulator,
        depth_frames=(threatened_frame, later_fillable_frame),
        observation_ts_ns=(_ns_at(13, 10), _ns_at(13, 30)),
    )

    assert timeline.first_threatened_ts_ns == _ns_at(13, 30)
    assert timeline.last_executable_ts_ns == _ns_at(13, 40)
    assert timeline.first_threatened_ts_ns < timeline.last_executable_ts_ns

    row = ewr.build_position_exit_row(
        timeline=timeline, settled_held=True, settlement_preliminary=False, depth_source="catalog",
    )
    assert ewr.classify_threatened_delta(row) == ewr.THREATENED_BEFORE_EXIT_SIDE_EMPTIED


def test_a_threatened_confirmation_after_the_exit_side_empties_yields_a_positive_delta() -> None:
    """The exit side empties FIRST, and THREATENED only confirms afterward --
    delta_i = threatened - last_executable > 0, classified AFTER, and must
    NOT count toward the R-THREAT "before the exit side empties" gate."""
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    _push_metar(accumulator, _ns_at(12, 30), 86)  # entry reading, m_code=0
    position = _position(filled_at_ns=_ns_at(13, 5))
    _push_metar(accumulator, _ns_at(13, 10), 87)  # m 0 -> 1 drop begins
    # Fillable only at the FIRST evaluation instant; gone by the second.
    early_fillable_frame = _depth(bids=(("0.20", "5"),), asks=(), ts_ns=_ns_at(13, 9))
    empties_for_good = _depth(bids=(), asks=(), ts_ns=_ns_at(13, 20))

    timeline = _timeline(
        position=position, accumulator=accumulator,
        depth_frames=(early_fillable_frame, empties_for_good),
        observation_ts_ns=(_ns_at(13, 10), _ns_at(13, 30)),
    )

    assert timeline.first_threatened_ts_ns == _ns_at(13, 30)
    assert timeline.last_executable_ts_ns == _ns_at(13, 10)
    assert timeline.last_executable_ts_ns < timeline.first_threatened_ts_ns

    row = ewr.build_position_exit_row(
        timeline=timeline, settled_held=True, settlement_preliminary=False, depth_source="catalog",
    )
    assert ewr.classify_threatened_delta(row) == ewr.THREATENED_AFTER_EXIT_SIDE_EMPTIED

    summary = ewr.build_summary((row,))
    # The gate-reading consequence (§6 B2.3): an AFTER row counts toward
    # neither the R-THREAT "before" gate nor its complement pool silently --
    # it is excluded from threatened_before_emptied.
    assert summary.threatened_before_emptied == 0
    assert summary.threatened_after_emptied == 1


# ---------------------------------------------------------------------------
# 5. Summary counters and Markdown rendering over a 3-row fixture
# ---------------------------------------------------------------------------


def _synthetic_row(
    *, trial_id: str, first_threatened_ts_ns: int | None, first_dead_ts_ns: int | None,
    last_executable_ts_ns: int | None, hold_pnl_value: Decimal, r_dead_pnl: Decimal,
    r_threat_pnl: Decimal, r_best_pnl: Decimal, climate_day: str | None = None,
) -> ewr.PositionExitRow:
    position = _position(filled_at_ns=_ns_at(14, 5))
    position = ewc.FilledPosition(
        trial_id=trial_id, station=position.station,
        climate_day=climate_day if climate_day is not None else position.climate_day,
        season=position.season, instrument_id=position.instrument_id, leg=position.leg,
        rung=position.rung, fill_px=position.fill_px, fee=position.fee,
        held_qty=position.held_qty, filled_at_ns=position.filled_at_ns,
    )
    timeline = ewc.ExitTimeline(
        position=position, p_hold_at_entry=None, evaluations=(),
        first_threatened_ts_ns=first_threatened_ts_ns, first_dead_ts_ns=first_dead_ts_ns,
        last_executable_ts_ns=last_executable_ts_ns,
    )
    return ewr.PositionExitRow(
        position=position, timeline=timeline, settled_held=True, settlement_preliminary=True,
        hold_pnl=hold_pnl_value, depth_source="catalog",
        r_dead=ewc.RuleOutcome(
            rule="R-DEAD", status="exited", signal_ts_ns=first_dead_ts_ns,
            exit_ts_ns=first_dead_ts_ns, exit_price=Decimal("0.10"), pnl=r_dead_pnl,
        ),
        r_threat=ewc.RuleOutcome(
            rule="R-THREAT", status="exited", signal_ts_ns=first_threatened_ts_ns,
            exit_ts_ns=first_threatened_ts_ns, exit_price=Decimal("0.20"), pnl=r_threat_pnl,
        ),
        r_best=ewc.RuleOutcome(
            rule="R-BEST", status="exited", signal_ts_ns=last_executable_ts_ns,
            exit_ts_ns=last_executable_ts_ns, exit_price=Decimal("0.30"), pnl=r_best_pnl,
        ),
    )


def test_build_summary_counts_and_medians_over_a_three_row_fixture() -> None:
    rows = (
        # THREATENED and DEAD both fire before the exit side empties for good.
        _synthetic_row(
            trial_id="row-1", first_threatened_ts_ns=_ns_at(14, 0), first_dead_ts_ns=_ns_at(14, 10),
            last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("-0.40"),
            r_dead_pnl=Decimal("-0.10"), r_threat_pnl=Decimal("-0.05"), r_best_pnl=Decimal("0.05"),
        ),
        # THREATENED fires after the exit side empties; no DEAD ever.
        _synthetic_row(
            trial_id="row-2", first_threatened_ts_ns=_ns_at(15, 0), first_dead_ts_ns=None,
            last_executable_ts_ns=_ns_at(14, 30), hold_pnl_value=Decimal("0.60"),
            r_dead_pnl=Decimal("0.60"), r_threat_pnl=Decimal("0.30"), r_best_pnl=Decimal("0.60"),
        ),
        # Neither ever fires.
        _synthetic_row(
            trial_id="row-3", first_threatened_ts_ns=None, first_dead_ts_ns=None,
            last_executable_ts_ns=_ns_at(16, 0), hold_pnl_value=Decimal("0.60"),
            r_dead_pnl=Decimal("0.60"), r_threat_pnl=Decimal("0.60"), r_best_pnl=Decimal("0.60"),
        ),
    )

    summary = ewr.build_summary(rows)

    assert summary.n_positions == 3
    assert summary.threatened_before_emptied == 1  # only row-1
    assert summary.threatened_after_emptied == 1  # only row-2 (AUD-07 B2)
    assert summary.dead_before_emptied == 1  # only row-1
    assert summary.median_minutes_last_executable_to_dead == Decimal(-10)
    assert summary.sum_hold_pnl == Decimal("0.80")
    assert summary.sum_r_dead_pnl == Decimal("1.10")
    assert summary.sum_r_threat_pnl == Decimal("0.85")
    assert summary.sum_r_best_pnl == Decimal("1.25")
    assert summary.corpus_first_fill_date == rows[0].position.climate_day
    assert summary.corpus_last_fill_date == rows[0].position.climate_day
    assert summary.n_positions_new_since_previous_run is None  # no previous run supplied

    assert ewr.classify_threatened_delta(rows[0]) == ewr.THREATENED_BEFORE_EXIT_SIDE_EMPTIED
    assert ewr.classify_threatened_delta(rows[1]) == ewr.THREATENED_AFTER_EXIT_SIDE_EMPTIED
    assert ewr.classify_threatened_delta(rows[2]) is None  # no THREATENED confirmation at all

    markdown = ewr.render_markdown(rows, summary)
    assert "row-1" in markdown
    assert "row-2" in markdown
    assert "row-3" in markdown
    assert "n_positions=3" in markdown
    assert "threatened_before_exit_side_emptied=1/3" in markdown
    assert "threatened_after_exit_side_emptied=1/3" in markdown
    assert "dead_before_exit_side_emptied=1/3" in markdown
    assert "THREATENED_BEFORE_EXIT_SIDE_EMPTIED" in markdown
    assert "THREATENED_AFTER_EXIT_SIDE_EMPTIED" in markdown


def test_build_summary_with_a_previous_run_counts_only_new_trial_ids() -> None:
    rows = (
        _synthetic_row(
            trial_id="row-1", first_threatened_ts_ns=None, first_dead_ts_ns=None,
            last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("0.10"),
            r_dead_pnl=Decimal("0.10"), r_threat_pnl=Decimal("0.10"), r_best_pnl=Decimal("0.10"),
        ),
        _synthetic_row(
            trial_id="row-2", first_threatened_ts_ns=None, first_dead_ts_ns=None,
            last_executable_ts_ns=_ns_at(14, 30), hold_pnl_value=Decimal("0.10"),
            r_dead_pnl=Decimal("0.10"), r_threat_pnl=Decimal("0.10"), r_best_pnl=Decimal("0.10"),
        ),
    )

    frozen = ewr.build_summary(rows, previous_trial_ids=frozenset({"row-1", "row-2"}))
    assert frozen.n_positions_new_since_previous_run == 0

    grown = ewr.build_summary(rows, previous_trial_ids=frozenset({"row-1"}))
    assert grown.n_positions_new_since_previous_run == 1  # only row-2 is new

    first_ever = ewr.build_summary(rows, previous_trial_ids=frozenset())
    assert first_ever.n_positions_new_since_previous_run == 2  # both new vs an empty prior set


# ---------------------------------------------------------------------------
# 5b. AUD-07 D: EXIT_CORPUS_FROZEN, on AUD-04's shared alert_ladder --
# this control's own LOCAL wiring (event names, latch file, its
# n_positions_new_since_previous_run == 0 predicate). The shared streak /
# period-key state machine itself is asserted once, in
# tests/unit/test_alert_ladder.py -- not re-asserted here.
# ---------------------------------------------------------------------------

_NS_PER_DAY = 86_400_000_000_000
_FRESH_LATCH = alert_ladder.LatchState(
    schema_version=alert_ladder.LATCH_SCHEMA_VERSION,
    streak=0, last_alert_severity=None, last_alert_period_key=None,
)


def _day_ns(day_offset: int) -> int:
    epoch_ns = int(dt.datetime(2026, 1, 1, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
    return epoch_ns + day_offset * _NS_PER_DAY


class TestExitCorpusFrozenLadder:
    def test_a_run_that_adds_no_positions_reports_zero_new(self) -> None:
        latch, payload = study_mod.apply_corpus_frozen_ladder(
            n_positions_new_since_previous_run=0, latch=_FRESH_LATCH, now_ns=_day_ns(0),
        )
        assert latch.streak == 1
        assert payload is None  # below WARN_STREAK_THRESHOLD

    def test_three_consecutive_zero_new_runs_emit_one_frozen_corpus_warn(self) -> None:
        latch = _FRESH_LATCH
        payloads = []
        for i in range(3):
            latch, payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(i),
            )
            payloads.append(payload)
        assert [p is not None for p in payloads] == [False, False, True]
        assert payloads[-1].severity == "WARN"
        assert payloads[-1].event == study_mod.EXIT_CORPUS_FROZEN_EVENT

    def test_a_thirty_night_freeze_re_alerts_weekly_then_escalates_to_daily_critical(self) -> None:
        latch = _FRESH_LATCH
        emitted: list[tuple[int, str]] = []
        for day_offset in range(30):
            latch, payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(day_offset),
            )
            if payload is not None:
                emitted.append((day_offset + 1, payload.severity))
        warns = [day for day, severity in emitted if severity == "WARN"]
        criticals = [day for day, severity in emitted if severity == "CRITICAL"]
        assert warns[0] == 3
        assert all(severity != "CRITICAL" for day, severity in emitted if day < 14)
        assert 14 in criticals
        assert criticals == list(range(14, 31))

    def test_a_same_period_rerun_does_not_re_alert(self) -> None:
        latch = _FRESH_LATCH
        for i in range(3):
            latch, _payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(i),
            )
        latch, payload = study_mod.apply_corpus_frozen_ladder(
            n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(2),
        )
        assert payload is None

    def test_the_frozen_streak_latch_survives_a_restart_without_re_alerting(
        self, tmp_path: Path,
    ) -> None:
        latch_path = tmp_path / ".frozen_streak.json"
        latch = _FRESH_LATCH
        for i in range(3):
            latch, _payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(i),
            )
        alert_ladder.write_latch_state(latch_path, latch)

        reloaded = alert_ladder.read_latch_state(latch_path)
        _new_latch, payload = study_mod.apply_corpus_frozen_ladder(
            n_positions_new_since_previous_run=0, latch=reloaded, now_ns=_day_ns(2),
        )
        assert payload is None

    def test_a_missing_or_corrupt_frozen_streak_latch_re_alerts_rather_than_failing_silent(
        self, tmp_path: Path,
    ) -> None:
        latch_path = tmp_path / ".frozen_streak.json"
        latch_path.write_text("{ not json")
        reloaded = alert_ladder.read_latch_state(latch_path)
        assert reloaded.streak == 0

        latch = reloaded
        payloads = []
        for i in range(3):
            latch, payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(i),
            )
            payloads.append(payload)
        assert payloads[-1] is not None

    def test_a_new_position_clears_the_streak_emits_one_info_and_fully_re_arms(self) -> None:
        latch = _FRESH_LATCH
        for i in range(3):
            latch, _payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(i),
            )
        assert latch.streak == 3

        latch, clear_payload = study_mod.apply_corpus_frozen_ladder(
            n_positions_new_since_previous_run=1, latch=latch, now_ns=_day_ns(3),
        )
        assert clear_payload is not None
        assert clear_payload.severity == "INFO"
        assert clear_payload.event == study_mod.EXIT_CORPUS_FROZEN_CLEARED_EVENT
        assert latch.streak == 0

        payloads = []
        for i in range(4, 7):
            latch, payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(i),
            )
            payloads.append(payload)
        assert payloads[-1] is not None
        assert payloads[-1].severity == "WARN"

    def test_the_first_ever_run_never_alerts_frozen(self) -> None:
        """`n_positions_new_since_previous_run is None` (nothing to compare
        against) must never be treated as frozen."""
        latch, payload = study_mod.apply_corpus_frozen_ladder(
            n_positions_new_since_previous_run=None, latch=_FRESH_LATCH, now_ns=_day_ns(0),
        )
        assert payload is None
        assert latch.streak == 0

    def test_severity_never_de_escalates_within_one_streak(self) -> None:
        latch = _FRESH_LATCH
        payload = None
        for day_offset in range(14):
            latch, payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(day_offset),
            )
        assert payload.severity == "CRITICAL"
        latch, payload2 = study_mod.apply_corpus_frozen_ladder(
            n_positions_new_since_previous_run=0, latch=latch,
            now_ns=_day_ns(13) + 3_600_000_000_000,
        )
        assert payload2 is None or payload2.severity == "CRITICAL"

    def test_the_warning_carries_no_currency_denominated_field(self) -> None:
        latch = _FRESH_LATCH
        payload = None
        for i in range(3):
            latch, payload = study_mod.apply_corpus_frozen_ladder(
                n_positions_new_since_previous_run=0, latch=latch, now_ns=_day_ns(i),
            )
        assert payload is not None
        assert "$" not in payload.detail
        import re as _re

        assert not _re.search(r"\d+\.\d\d\b", payload.detail)


# ---------------------------------------------------------------------------
# 5c. AUD-07 standing reconciliation with AUD-04, read through AUD-04's own
# schema_version reader (never re-parsed Markdown). See
# Aud04ReconciliationResult's docstring for the stated residual limitation:
# AUD-04's published schema carries a REPORT-LEVEL total only, not yet a
# per-trial_id breakdown to inner-join against (AUD-04's own mirror
# obligation, AUD-04 plan §8 AC#4) -- this compares totals over the same
# period until that field exists.
# ---------------------------------------------------------------------------


def _write_minimal_aud04_report(
    path: Path, *, realised_pnl_after_fees_total: Decimal,
) -> None:
    payload = {
        "schema_version": prr.PORTFOLIO_ROI_SCHEMA_VERSION,
        "period_start": "2026-01-01",
        "period_end": "2026-01-10",
        "n_fills": 1,
        "n_scored": 1,
        "n_residual": 0,
        "n_unreconciled": 0,
        "power_caveat": "n=1; not statistically powered.",
        "realised_pnl_after_fees_total": str(realised_pnl_after_fees_total),
        "capital_deployed_total": "1.00",
        "unexplained_flow_days": 0,
        "settled_through": "2026-01-08",
        "settled_through_statistic": "max",
        "lag_sample_n": 1,
        "roi_status": prr.ROI_STATUS_OK,
        "unsettled_capital_positions": 0,
        "max_days_past_horizon": 0,
        "roi": "0.10",
        "roi_minus_b0": "0.10",
        "roi_minus_b1": "0.10",
        # AUD-04 schema_version=2 requires this key (Stage C3's per-trial
        # P&L breakdown); one row, summing exactly to
        # `realised_pnl_after_fees_total` (the sum invariant), matching this
        # fixture's own `n_scored=1`.
        "trial_rows": [
            {
                "trial_id": "aud04-minimal/trial/LAX/2026-01-05",
                "family_id": "UNKNOWN",
                "climate_day": "2026-01-05",
                "side": "yes",
                "pnl": str(realised_pnl_after_fees_total),
                "settlement_basis": "nws_final",
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2))


class TestAud04Reconciliation:
    def test_a_matching_total_reconciles(self) -> None:
        rows = (
            _synthetic_row(
                trial_id="row-1", first_threatened_ts_ns=None, first_dead_ts_ns=None,
                last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("0.61"),
                r_dead_pnl=Decimal("0.61"), r_threat_pnl=Decimal("0.61"),
                r_best_pnl=Decimal("0.61"),
                climate_day="2026-01-05",
            ),
        )
        result = study_mod.reconcile_with_aud04(
            rows=rows, cutoff="2026-01-10", aud04_realised_pnl_after_fees_total=Decimal("0.61"),
        )
        assert result.matched is True
        assert result.divergence == Decimal(0)
        assert result.cutoff == "2026-01-10"

    def test_a_mismatched_total_does_not_reconcile_and_names_the_divergence(self) -> None:
        rows = (
            _synthetic_row(
                trial_id="row-1", first_threatened_ts_ns=None, first_dead_ts_ns=None,
                last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("0.61"),
                r_dead_pnl=Decimal("0.61"), r_threat_pnl=Decimal("0.61"),
                r_best_pnl=Decimal("0.61"),
                climate_day="2026-01-05",
            ),
        )
        result = study_mod.reconcile_with_aud04(
            rows=rows, cutoff="2026-01-10", aud04_realised_pnl_after_fees_total=Decimal("0.50"),
        )
        assert result.matched is False
        assert result.divergence == Decimal("0.11")

    def test_an_empty_study_against_a_nonzero_aud04_total_is_a_mismatch_never_dropped(
        self,
    ) -> None:
        result = study_mod.reconcile_with_aud04(
            rows=(), cutoff="2026-01-10", aud04_realised_pnl_after_fees_total=Decimal("0.50"),
        )
        assert result.matched is False
        assert result.divergence == Decimal("0.50")

    def test_the_reconciliation_reads_aud04_through_its_schema_version_reader(
        self, tmp_path: Path,
    ) -> None:
        report_path = tmp_path / "PRIVATE_portfolio_roi_2026-01-10.json"
        _write_minimal_aud04_report(report_path, realised_pnl_after_fees_total=Decimal("0.61"))

        view = prr.read_portfolio_roi_report(report_path)
        rows = (
            _synthetic_row(
                trial_id="row-1", first_threatened_ts_ns=None, first_dead_ts_ns=None,
                last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("0.61"),
                r_dead_pnl=Decimal("0.61"), r_threat_pnl=Decimal("0.61"),
                r_best_pnl=Decimal("0.61"),
                climate_day="2026-01-05",
            ),
        )
        result = study_mod.reconcile_with_aud04(
            rows=rows, cutoff=view.settled_through,
            aud04_realised_pnl_after_fees_total=view.realised_pnl_after_fees_total,
        )
        assert result.matched is True

    def test_a_row_after_the_cutoff_is_excluded_from_the_exit_side_sum(self) -> None:
        """Domain review item 2: "reconcile like with like" -- a settlement
        landing AFTER AUD-04's cutoff must not itself produce a mismatch."""
        rows = (
            _synthetic_row(
                trial_id="in-window", first_threatened_ts_ns=None, first_dead_ts_ns=None,
                last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("0.61"),
                r_dead_pnl=Decimal("0.61"), r_threat_pnl=Decimal("0.61"),
                r_best_pnl=Decimal("0.61"),
                climate_day="2026-01-05",
            ),
            _synthetic_row(
                trial_id="after-cutoff", first_threatened_ts_ns=None, first_dead_ts_ns=None,
                last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("9.99"),
                r_dead_pnl=Decimal("9.99"), r_threat_pnl=Decimal("9.99"),
                r_best_pnl=Decimal("9.99"),
                climate_day="2026-01-11",
            ),
        )
        result = study_mod.reconcile_with_aud04(
            rows=rows, cutoff="2026-01-10", aud04_realised_pnl_after_fees_total=Decimal("0.61"),
        )
        assert result.matched is True
        assert result.sum_hold_pnl == Decimal("0.61")

    def test_a_genuine_divergence_within_the_same_cutoff_is_a_mismatch(self) -> None:
        rows = (
            _synthetic_row(
                trial_id="in-window", first_threatened_ts_ns=None, first_dead_ts_ns=None,
                last_executable_ts_ns=_ns_at(14, 20), hold_pnl_value=Decimal("0.61"),
                r_dead_pnl=Decimal("0.61"), r_threat_pnl=Decimal("0.61"),
                r_best_pnl=Decimal("0.61"),
                climate_day="2026-01-05",
            ),
        )
        result = study_mod.reconcile_with_aud04(
            rows=rows, cutoff="2026-01-10", aud04_realised_pnl_after_fees_total=Decimal("0.10"),
        )
        assert result.matched is False
        assert result.divergence == Decimal("0.51")


class TestAud04ReconciliationReadiness:
    """Domain review item 2: reconcile like with like -- restrict both sides
    to AUD-04's own `settled_through` cutoff; skip (never compare mismatched
    periods) on an unusable or stale cutoff."""

    def test_a_fresh_report_yields_the_settled_through_cutoff(self) -> None:
        cutoff, skip_reason = study_mod.aud04_reconciliation_readiness(
            settled_through="2026-01-08", run_date="2026-01-09",
        )
        assert cutoff == "2026-01-08"
        assert skip_reason is None

    def test_a_report_exactly_at_the_staleness_bound_is_not_skipped(self) -> None:
        cutoff, skip_reason = study_mod.aud04_reconciliation_readiness(
            settled_through="2026-01-01", run_date="2026-01-03",
        )
        assert cutoff == "2026-01-01"
        assert skip_reason is None

    def test_a_report_older_than_two_days_is_skipped_with_a_warn_line_naming_its_age(
        self,
    ) -> None:
        cutoff, skip_reason = study_mod.aud04_reconciliation_readiness(
            settled_through="2026-01-01", run_date="2026-01-05",
        )
        assert cutoff is None
        assert skip_reason is not None
        assert "WARN" in skip_reason
        assert "4 day(s)" in skip_reason

    def test_an_unparseable_settled_through_is_skipped_with_a_stated_reason(self) -> None:
        cutoff, skip_reason = study_mod.aud04_reconciliation_readiness(
            settled_through="not-a-date", run_date="2026-01-05",
        )
        assert cutoff is None
        assert skip_reason is not None
        assert "not-a-date" in skip_reason


class TestPnlReconciliationLadder:
    def test_a_persistent_mismatch_emits_on_the_same_ladder_as_corpus_frozen(self) -> None:
        latch = _FRESH_LATCH
        payloads = []
        for i in range(3):
            latch, payload = study_mod.apply_pnl_reconciliation_ladder(
                matched=False, latch=latch, now_ns=_day_ns(i),
            )
            payloads.append(payload)
        assert [p is not None for p in payloads] == [False, False, True]
        assert payloads[-1].severity == "WARN"
        assert payloads[-1].event == study_mod.EXIT_PNL_RECONCILIATION_MISMATCH_EVENT

    def test_a_matching_run_clears_the_streak_and_emits_one_info(self) -> None:
        latch = _FRESH_LATCH
        for i in range(3):
            latch, _payload = study_mod.apply_pnl_reconciliation_ladder(
                matched=False, latch=latch, now_ns=_day_ns(i),
            )
        assert latch.streak == 3
        latch, clear_payload = study_mod.apply_pnl_reconciliation_ladder(
            matched=True, latch=latch, now_ns=_day_ns(3),
        )
        assert clear_payload is not None
        assert clear_payload.severity == "INFO"
        assert clear_payload.event == study_mod.EXIT_PNL_RECONCILIATION_MISMATCH_CLEARED_EVENT
        assert latch.streak == 0

    def test_own_latch_file_is_distinct_from_the_frozen_corpus_latch(self) -> None:
        assert (
            study_mod._PNL_RECONCILIATION_LATCH_FILENAME
            != study_mod._FROZEN_STREAK_LATCH_FILENAME
        )

    def test_the_mismatch_alert_carries_the_report_level_total_caveat(self) -> None:
        """Domain review item 3: the caveat must be in the alert detail text,
        not only in a docstring."""
        latch = _FRESH_LATCH
        payload = None
        for i in range(3):
            latch, payload = study_mod.apply_pnl_reconciliation_ladder(
                matched=False, latch=latch, now_ns=_day_ns(i),
            )
        assert payload is not None
        assert study_mod._AUD04_RECONCILIATION_CAVEAT in payload.detail

    def test_the_cleared_alert_also_carries_the_caveat(self) -> None:
        latch = _FRESH_LATCH
        for i in range(3):
            latch, _payload = study_mod.apply_pnl_reconciliation_ladder(
                matched=False, latch=latch, now_ns=_day_ns(i),
            )
        latch, clear_payload = study_mod.apply_pnl_reconciliation_ladder(
            matched=True, latch=latch, now_ns=_day_ns(3),
        )
        assert clear_payload is not None
        assert study_mod._AUD04_RECONCILIATION_CAVEAT in clear_payload.detail


class TestAud04MalformedArtifactHandling:
    """Domain review item 1: a malformed AUD-04 artefact must degrade to the
    SKIPPED path -- never crash the run -- and the study must still write
    its own summary."""

    def test_corrupt_json_skips_and_still_writes_the_summary(
        self, tmp_path: Path,
    ) -> None:
        report_path = tmp_path / "PRIVATE_portfolio_roi_corrupt.json"
        report_path.write_text("{ not valid json")

        with pytest.raises(json.JSONDecodeError):
            prr.read_portfolio_roi_report(report_path)

        # The exact exception main() must catch and degrade from:
        try:
            prr.read_portfolio_roi_report(report_path)
        except (
            OSError,
            json.JSONDecodeError,
            prr.UnknownPortfolioRoiSchemaError,
            prr.PortfolioRoiReportMalformedFieldError,
        ) as exc:
            caught: Exception | None = exc
        else:
            caught = None
        assert caught is not None

    def test_a_malformed_field_skips_and_still_writes_the_summary(
        self, tmp_path: Path,
    ) -> None:
        report_path = tmp_path / "PRIVATE_portfolio_roi_malformed.json"
        _write_minimal_aud04_report(report_path, realised_pnl_after_fees_total=Decimal("0.61"))
        payload = json.loads(report_path.read_text())
        payload["realised_pnl_after_fees_total"] = 0.61  # must be a decimal-shaped STR
        report_path.write_text(json.dumps(payload))

        with pytest.raises(prr.PortfolioRoiReportMalformedFieldError):
            prr.read_portfolio_roi_report(report_path)

    # The full main()-level integration tests (a real offline run, via the
    # SAME fakes as test_one_station_429_is_missing_..., with a corrupt and
    # a malformed --aud04-report) live below, after _study_argv/
    # _install_offline_study_fakes are defined:
    # test_main_degrades_to_skipped_on_a_corrupt_aud04_artefact_and_still_writes_output
    # test_main_degrades_to_skipped_on_a_malformed_aud04_artefact_and_still_writes_output


# ---------------------------------------------------------------------------
# 6. L-44: infer_preliminary_settlement must invert for the NO leg
# ---------------------------------------------------------------------------


def _running_max_exact(fahrenheit: int) -> RunningMax:
    return RunningMax(
        lower_f=fahrenheit, upper_f=fahrenheit, exact_f=fahrenheit,
        source_observed_at_ns=0, source_received_at_ns=0,
    )


def _mia_92_93_facts() -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station="MIA", climate_day=_CLIMATE_DAY, measure=Measure.HIGH,
        lower_f=92, upper_f=93,
    )


def test_running_max_inside_the_rung_wins_yes_and_loses_no() -> None:
    # 93 is INSIDE the closed [92, 93] rung (venue/repo bounds are CLOSED,
    # THRESHOLD_SEMANTICS_2026-08-25.md "INCLUSIVE PROVEN") -- YES wins, so
    # the NO leg on the SAME rung must lose, never win.
    facts = _mia_92_93_facts()
    running_max = _running_max_exact(93)

    assert ewc.infer_preliminary_settlement(
        facts=facts, final_running_max=running_max, leg="YES",
    ) is True
    assert ewc.infer_preliminary_settlement(
        facts=facts, final_running_max=running_max, leg="NO",
    ) is False


def test_running_max_outside_the_rung_loses_yes_and_wins_no() -> None:
    # 94 is OUTSIDE [92, 93] -- YES loses, NO wins: the exact opposite pair
    # from the inside-the-rung case above.
    facts = _mia_92_93_facts()
    running_max = _running_max_exact(94)

    assert ewc.infer_preliminary_settlement(
        facts=facts, final_running_max=running_max, leg="YES",
    ) is False
    assert ewc.infer_preliminary_settlement(
        facts=facts, final_running_max=running_max, leg="NO",
    ) is True


def test_ambiguous_straddling_interval_stays_none_for_both_legs() -> None:
    # An interval straddling the rung boundary is genuinely unknown -- never
    # guessed, and "unknown" has no complement to flip for the NO leg either.
    facts = _mia_92_93_facts()
    straddling = RunningMax(
        lower_f=91, upper_f=93, exact_f=None, source_observed_at_ns=0,
        source_received_at_ns=0,
    )

    assert ewc.infer_preliminary_settlement(
        facts=facts, final_running_max=straddling, leg="YES",
    ) is None
    assert ewc.infer_preliminary_settlement(
        facts=facts, final_running_max=straddling, leg="NO",
    ) is None


def test_markdown_row_for_a_leg_correct_no_loser_shows_negative_hold_pnl() -> None:
    # A NO position whose settled_held is correctly False (the leg lost) must
    # render a negative hold_pnl in the Markdown table, never the positive
    # value a mis-inverted settlement would have produced.
    position = _position(leg="NO", fill_px=Decimal("0.09"), filled_at_ns=_ns_at(18, 12))
    timeline = ewc.ExitTimeline(
        position=position, p_hold_at_entry=None, evaluations=(),
        first_threatened_ts_ns=None, first_dead_ts_ns=None, last_executable_ts_ns=None,
    )

    row = ewr.build_position_exit_row(
        timeline=timeline, settled_held=False, settlement_preliminary=True,
        depth_source="staged",
    )

    assert row.hold_pnl is not None
    assert row.hold_pnl < 0
    markdown = ewr.render_markdown((row,), ewr.build_summary((row,)))
    assert str(row.hold_pnl) in markdown
    assert f"sum_hold_pnl={row.hold_pnl}" in markdown


def test_run_exit_window_study_reads_scored_trials_via_the_pooled_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect fix (2026-09-16): `read_scored_trials` alone only sees a
    scored-trial store's LEGACY top-level parquet files -- since L-38
    (`cbd5fec`), each REGISTERED family's rows live under their own
    `<scored_trials_dir>/<family_id>/` subdirectory. `stations=()` reaches
    the `scored_by_trial_id` build (the line under test) without ever
    opening `state_db` or a real quote-tape catalog (the `for city in
    stations` loop -- the only code that touches either -- never runs), so
    this stays a cheap wiring check rather than a full end-to-end run.
    """
    calls: list[Path] = []
    original = study_mod.read_scored_trials_pooled

    def _spy(base_dir: Path) -> object:
        calls.append(base_dir)
        return original(base_dir)

    monkeypatch.setattr(study_mod, "read_scored_trials_pooled", _spy)  # type: ignore[attr-defined]

    scored_dir = tmp_path / "scored"
    empty_catalog = tmp_path / "catalog"
    empty_catalog.mkdir()

    rows, missing = study_mod.run_exit_window_study(
        state_db=tmp_path / "state.sqlite",
        stations=(),
        since_climate_day="2026-01-01",
        catalog_root=empty_catalog,
        scored_trials_dir=scored_dir,
    )

    assert calls == [scored_dir]
    assert rows == ()
    assert missing == ()


# ---------------------------------------------------------------------------
# Fetch failures are per-station missing inputs, not a crashed run.
# A total outage (every attempted station) still exits non-zero.
# ---------------------------------------------------------------------------

_CACHED_CITY = "LAX"
_FAILED_CITY = "SFO"
_FETCH_CLIMATE_DAY = "2026-01-15"


class _StatusClient:
    """Stand-in for ``httpx.Client``. ``get`` never touches the network."""

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code
        self.calls = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str, *, timeout: float) -> httpx.Response:
        self.calls += 1
        request = httpx.Request("GET", url)
        return httpx.Response(self._status_code, request=request)


class _SequencedStatusClient:
    """Stand-in whose successive ``get`` calls replay ``responses`` in
    order: ``(status_code, retry_after)``. ``retry_after`` (or ``None``) is
    sent as the ``Retry-After`` header only for a non-2xx response. A 200
    entry returns ``body`` as the response text (mirrors a real ASOS
    success). Raises ``IndexError`` if called more times than provided --
    that is a test-setup bug, never a silently-extended fake."""

    def __init__(
        self, responses: Sequence[tuple[int, str | None]], *, body: str = "station,valid,metar\n",
    ) -> None:
        self._responses = list(responses)
        self._body = body
        self.calls = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str, *, timeout: float) -> httpx.Response:
        status_code, retry_after = self._responses[self.calls]
        self.calls += 1
        request = httpx.Request("GET", url)
        if status_code == 200:
            return httpx.Response(200, request=request, text=self._body)
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        return httpx.Response(status_code, request=request, headers=headers)


class _TransportErrorClient:
    """Stand-in whose ``get`` raises ``httpx.TransportError`` (no status)."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str, *, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("synthetic connection reset")


def _synthetic_trial(city: str) -> FilledTrial:
    instrument_id = f"{city.lower()}-86-87.POLYMARKET_US"
    return FilledTrial(
        trial_id=f"synthetic:{city}:{_FETCH_CLIMATE_DAY}:{instrument_id}",
        station=city,
        climate_day=_FETCH_CLIMATE_DAY,
        instrument_id=instrument_id,
        bucket=WeatherBucketFacts(
            settlement_station=city,
            climate_day=_CLIMATE_DAY,
            measure=Measure.HIGH,
            lower_f=86,
            upper_f=87,
        ),
        fill_px=Decimal("0.40"),
        fee=Decimal("0.02"),
        qty=Decimal(1),
        filled_at_ns=_ns_at(14, 0),
        entry_ask=Decimal("0.40"),
        scheduled_release_at_ns=_ns_at(18, 0),
    )


def _depths(
    *, catalog_root: Path, instrument_ids: Sequence[str],
) -> dict[str, tuple[OrderBookDepth10, ...]]:
    del catalog_root
    return {
        instrument_id: (
            _depth(
                bids=(("0.05", "5"),),
                asks=(),
                ts_ns=_ns_at(15, 0),
                instrument_id=instrument_id,
            ),
        )
        for instrument_id in instrument_ids
    }


def _install_offline_study_fakes(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    """No sqlite, no catalog, no network. The client is the only fetch seam."""

    def _trials(
        state_db: Path,
        *,
        family_prefix: str,
        city: str,
        cli_location: str,
        since_climate_day: str,
        stations: Sequence[str],
    ) -> tuple[tuple[FilledTrial, ...], tuple[object, ...], dict[str, object], dict[str, object]]:
        del state_db, family_prefix, cli_location, since_climate_day, stations
        return (_synthetic_trial(city),), (), {}, {}

    # httpx is imported by the study module and is not part of its public surface.
    httpx_in_study = study_mod.httpx  # type: ignore[attr-defined]
    monkeypatch.setattr(httpx_in_study, "Client", lambda **kwargs: client)
    monkeypatch.setattr(study_mod, "read_filled_trials_state_db", _trials)
    monkeypatch.setattr(
        study_mod, "_read_bucket_facts_by_instrument_id", lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        study_mod, "load_settled_tmax_for_day", lambda **kwargs: (None, 0, "synthetic"),
    )
    monkeypatch.setattr(study_mod, "_load_depth_frames", _depths)


def _seed_cached_asos(cache_dir: Path, city: str) -> None:
    spec = next(spec for spec in settlement.load_sites() if spec.city == city)
    url = settlement.asos_url(
        spec.iem_asos_id, prelock.ASOS_FETCH_START, prelock.ASOS_FETCH_END,
    )
    path = settlement.cache_path_for_url(cache_dir, url, ".txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Header only: a cache hit with no METAR rows. The row still builds from
    # the stubbed depth tape; nothing here is a live observation.
    path.write_text("station,valid,metar\n", encoding="utf-8")


def _study_argv(
    tmp_path: Path, *, cache_dir: Path, aud04_report: Path | None = None,
) -> list[str]:
    catalog = tmp_path / "catalog"
    catalog.mkdir(exist_ok=True)
    argv = [
        "--state-db", str(tmp_path / "state.sqlite"),
        "--stations", _FAILED_CITY, _CACHED_CITY,
        "--since-climate-day", _FETCH_CLIMATE_DAY,
        "--catalog-root", str(catalog),
        "--scored-trials-dir", str(tmp_path / "scored"),
        "--asos-cache-dir", str(cache_dir),
        "--obs-source", "fetch",
        "--depth-source", "catalog",
        "--live-catalog-root", str(tmp_path / "live"),
        "--run-stamp", "synthetic-fetch",
        "--out-root", str(tmp_path / "out"),
    ]
    if aud04_report is not None:
        argv += ["--aud04-report", str(aud04_report)]
    return argv


def test_one_station_429_is_missing_and_the_cached_station_still_produces_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "asos"
    _seed_cached_asos(cache_dir, _CACHED_CITY)
    _install_offline_study_fakes(monkeypatch, _StatusClient(429))
    catalog = tmp_path / "catalog"
    catalog.mkdir()

    rows, missing = study_mod.run_exit_window_study(
        state_db=tmp_path / "state.sqlite",
        stations=(_FAILED_CITY, _CACHED_CITY),
        since_climate_day=_FETCH_CLIMATE_DAY,
        catalog_root=catalog,
        scored_trials_dir=tmp_path / "scored",
        asos_cache_dir=cache_dir,
        obs_source="fetch",
        depth_source="catalog",
        live_catalog_root=tmp_path / "live",
        sleep=lambda seconds: None,
    )

    assert [row.position.station for row in rows] == [_CACHED_CITY]
    failed = [item for item in missing if _FAILED_CITY in item]
    assert failed
    assert all("429" in item for item in failed)
    assert study_mod.main(
        _study_argv(tmp_path, cache_dir=cache_dir), sleep=lambda seconds: None,
    ) == 0


def test_a_transport_error_on_one_station_is_missing_and_the_cached_station_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "asos"
    _seed_cached_asos(cache_dir, _CACHED_CITY)
    _install_offline_study_fakes(monkeypatch, _TransportErrorClient())
    catalog = tmp_path / "catalog"
    catalog.mkdir()

    rows, missing = study_mod.run_exit_window_study(
        state_db=tmp_path / "state.sqlite",
        stations=(_FAILED_CITY, _CACHED_CITY),
        since_climate_day=_FETCH_CLIMATE_DAY,
        catalog_root=catalog,
        scored_trials_dir=tmp_path / "scored",
        asos_cache_dir=cache_dir,
        obs_source="fetch",
        depth_source="catalog",
        live_catalog_root=tmp_path / "live",
    )

    assert [row.position.station for row in rows] == [_CACHED_CITY]
    failed = [item for item in missing if _FAILED_CITY in item]
    assert failed
    assert all("ConnectError" in item for item in failed)


def test_every_station_429_exits_non_zero_and_names_each_station(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "asos"
    cache_dir.mkdir()
    _install_offline_study_fakes(monkeypatch, _StatusClient(429))

    class _CapturingSink:
        def __init__(self) -> None:
            self.payloads: list[object] = []

        def emit(self, payload: object) -> None:
            self.payloads.append(payload)

    sink = _CapturingSink()
    code = study_mod.main(
        _study_argv(tmp_path, cache_dir=cache_dir), sink=sink, sleep=lambda seconds: None,
    )

    assert code != 0
    report = tmp_path / "out" / "synthetic-fetch" / "exit_window_study.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    missing = payload["missing_inputs"]
    for city in (_FAILED_CITY, _CACHED_CITY):
        named = [item for item in missing if city in item and "429" in item]
        assert named, missing
    # A TOTAL outage exits 1 and trips the unit's own OnFailure= alert
    # already -- the partial-run WARN must never ALSO fire here.
    warn_payloads = [
        p for p in sink.payloads
        if p.event == study_mod.EXIT_WINDOW_ASOS_FETCH_PARTIAL_OUTAGE_EVENT
    ]
    assert warn_payloads == []


# ---------------------------------------------------------------------------
# 429/5xx retry (this backlog item): bounded, Retry-After-aware, injectable
# sleep so no test here ever really waits.
# ---------------------------------------------------------------------------


def _status_error(status_code: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/asos.txt")
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    response = httpx.Response(status_code, request=request, headers=headers)
    return httpx.HTTPStatusError(str(status_code), request=request, response=response)


def test_retry_wait_seconds_honours_retry_after_seconds_form_capped_at_120() -> None:
    exc = _status_error(429, retry_after="500")

    assert study_mod._retry_wait_seconds(exc, attempt=0) == 120.0


def test_retry_wait_seconds_honours_a_small_retry_after_uncapped() -> None:
    exc = _status_error(429, retry_after="30")

    assert study_mod._retry_wait_seconds(exc, attempt=0) == 30.0


def test_retry_wait_seconds_falls_back_to_exponential_backoff_without_retry_after() -> None:
    exc = _status_error(503)

    assert [study_mod._retry_wait_seconds(exc, attempt=n) for n in range(3)] == [5.0, 15.0, 45.0]


def test_retry_wait_seconds_falls_back_on_an_http_date_retry_after() -> None:
    """An HTTP-date ``Retry-After`` (not the seconds form) is treated as
    absent -- this study parses ONLY the seconds form, per the backlog
    item's own scope."""
    exc = _status_error(429, retry_after="Wed, 21 Oct 2026 07:28:00 GMT")

    assert study_mod._retry_wait_seconds(exc, attempt=1) == 15.0


def test_429_then_200_recovers_the_station_honouring_retry_after_and_capping_the_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "asos"
    client = _SequencedStatusClient([(429, "500"), (200, None)])
    _install_offline_study_fakes(monkeypatch, client)
    # `fetch_text_cached`'s own success path (unmodified, per this backlog
    # item's own constraint) always calls `time.sleep(delay_s=1.0)` after a
    # successful GET -- real, not this study's injected retry `sleep`. This
    # is the ONLY test in the file that ever reaches that success path, so
    # it is the only one that needs this: patch the stdlib `time.sleep`
    # `settlement_alignment_study` calls, in THIS test only (monkeypatch
    # auto-restores), never `fetch_text_cached` itself.
    monkeypatch.setattr(settlement.time, "sleep", lambda seconds: None)
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sleeps: list[float] = []

    rows, missing = study_mod.run_exit_window_study(
        state_db=tmp_path / "state.sqlite",
        stations=(_FAILED_CITY,),
        since_climate_day=_FETCH_CLIMATE_DAY,
        catalog_root=catalog,
        scored_trials_dir=tmp_path / "scored",
        asos_cache_dir=cache_dir,
        obs_source="fetch",
        depth_source="catalog",
        live_catalog_root=tmp_path / "live",
        sleep=sleeps.append,
    )

    assert client.calls == 2
    # Retry-After=500 is capped at the 120s ceiling, never used raw.
    assert sleeps == [120.0]
    assert [row.position.station for row in rows] == [_FAILED_CITY]
    assert not any(study_mod._ASOS_FETCH_FAILURE_MARKER in item for item in missing)


def test_429_exhausts_retries_missing_and_a_deduped_warn_names_the_station(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "asos"
    _seed_cached_asos(cache_dir, _CACHED_CITY)
    client = _StatusClient(429)
    _install_offline_study_fakes(monkeypatch, client)
    sleeps: list[float] = []

    class _CapturingSink:
        def __init__(self) -> None:
            self.payloads: list[object] = []

        def emit(self, payload: object) -> None:
            self.payloads.append(payload)

    sink = _CapturingSink()
    code = study_mod.main(
        _study_argv(tmp_path, cache_dir=cache_dir), sink=sink, sleep=sleeps.append,
    )

    assert code == 0
    # 1 initial attempt + 3 retries = 4 calls; 3 waits (5, 15, 45).
    assert client.calls == 4
    assert sleeps == [5.0, 15.0, 45.0]
    report = tmp_path / "out" / "synthetic-fetch" / "exit_window_study.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    missing = payload["missing_inputs"]
    failed = [item for item in missing if _FAILED_CITY in item and "429" in item]
    assert failed
    warn_payloads = [
        p for p in sink.payloads
        if p.event == study_mod.EXIT_WINDOW_ASOS_FETCH_PARTIAL_OUTAGE_EVENT
    ]
    assert len(warn_payloads) == 1
    assert warn_payloads[0].severity == "WARN"
    assert _FAILED_CITY in warn_payloads[0].detail
    assert "429" in warn_payloads[0].detail


_THIRD_FAILED_CITY = "MDW"


def test_total_retry_wait_budget_exhaustion_stops_retrying_remaining_stations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run-wide `retry_wait_budget_s` (production default 600s; injected
    small here) is a hard ceiling on the SUM of every wait across every
    station, not just each station's own `_MAX_FETCH_RETRIES`. SFO consumes
    its full 5+15+45=65s before exhausting its own retry count; MDW then
    gets only 2 waits (5+15=20s) before the shared budget (100s total)
    cannot cover its third (45s) -- it stops retrying immediately rather
    than waiting a truncated amount, and becomes missing one attempt early.
    LAX is a cache hit throughout, so this run stays a PARTIAL (not total)
    outage.
    """
    cache_dir = tmp_path / "asos"
    _seed_cached_asos(cache_dir, _CACHED_CITY)
    client = _StatusClient(429)
    _install_offline_study_fakes(monkeypatch, client)
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sleeps: list[float] = []

    rows, missing = study_mod.run_exit_window_study(
        state_db=tmp_path / "state.sqlite",
        stations=(_FAILED_CITY, _THIRD_FAILED_CITY, _CACHED_CITY),
        since_climate_day=_FETCH_CLIMATE_DAY,
        catalog_root=catalog,
        scored_trials_dir=tmp_path / "scored",
        asos_cache_dir=cache_dir,
        obs_source="fetch",
        depth_source="catalog",
        live_catalog_root=tmp_path / "live",
        sleep=sleeps.append,
        retry_wait_budget_s=100.0,
    )

    # SFO: 4 calls (1 + 3 retries), all within budget. MDW: 3 calls (1 + 2
    # retries) -- its 3rd retry is refused by the exhausted budget before a
    # 4th call is ever made. LAX: 0 calls (cache hit).
    assert client.calls == 7
    assert sleeps == [5.0, 15.0, 45.0, 5.0, 15.0]
    assert sum(sleeps) <= 100.0
    assert [row.position.station for row in rows] == [_CACHED_CITY]
    for city in (_FAILED_CITY, _THIRD_FAILED_CITY):
        failed = [item for item in missing if city in item and "429" in item]
        assert failed, missing


def test_fetch_text_cached_other_callers_still_get_exactly_one_attempt_on_429(
    tmp_path: Path,
) -> None:
    """Pins ``settlement_alignment_study.fetch_text_cached``'s own,
    unretried behaviour: the retry added by this backlog item lives ONLY in
    the exit-window study's own wrapper, never in the shared helper every
    other caller (``asos_recent_refresh.py``,
    ``current_rung_hold_resting_bid_study.py``, and
    ``settlement_alignment_study.main`` itself) still uses."""
    client = _StatusClient(429)

    with pytest.raises(httpx.HTTPStatusError):
        settlement.fetch_text_cached(client, tmp_path, "https://example.invalid/asos.txt", 0.0)

    assert client.calls == 1


# ---------------------------------------------------------------------------
# Domain review item 1: a malformed AUD-04 artefact degrades to the SKIPPED
# path rather than crashing the run -- the study's own summary is still
# written. Full main()-level runs, via the SAME offline fakes as the
# fetch-failure tests above (real state-db/catalog/network paths never
# touched).
# ---------------------------------------------------------------------------


def test_main_degrades_to_skipped_on_a_corrupt_aud04_artefact_and_still_writes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "asos"
    _seed_cached_asos(cache_dir, _CACHED_CITY)
    _install_offline_study_fakes(monkeypatch, _StatusClient(429))

    aud04_report = tmp_path / "PRIVATE_portfolio_roi_corrupt.json"
    aud04_report.write_text("{ not valid json")

    code = study_mod.main(_study_argv(tmp_path, cache_dir=cache_dir, aud04_report=aud04_report))

    assert code == 0  # the failed station is a missing input, never a crash
    report = tmp_path / "out" / "synthetic-fetch" / "exit_window_study.json"
    assert report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["summary"]["n_positions"] == 1  # the cached station still produced its row


def test_main_degrades_to_skipped_on_a_malformed_aud04_artefact_and_still_writes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "asos"
    _seed_cached_asos(cache_dir, _CACHED_CITY)
    _install_offline_study_fakes(monkeypatch, _StatusClient(429))

    aud04_report = tmp_path / "PRIVATE_portfolio_roi_malformed.json"
    _write_minimal_aud04_report(aud04_report, realised_pnl_after_fees_total=Decimal("0.61"))
    payload = json.loads(aud04_report.read_text())
    payload["realised_pnl_after_fees_total"] = 0.61  # must be a decimal-shaped STR
    aud04_report.write_text(json.dumps(payload))

    code = study_mod.main(_study_argv(tmp_path, cache_dir=cache_dir, aud04_report=aud04_report))

    assert code == 0
    report = tmp_path / "out" / "synthetic-fetch" / "exit_window_study.json"
    assert report.exists()
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["summary"]["n_positions"] == 1
