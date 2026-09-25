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
    r_threat_pnl: Decimal, r_best_pnl: Decimal,
) -> ewr.PositionExitRow:
    position = _position(filled_at_ns=_ns_at(14, 5))
    position = ewc.FilledPosition(
        trial_id=trial_id, station=position.station, climate_day=position.climate_day,
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
    }
    path.write_text(json.dumps(payload, indent=2))


class TestAud04Reconciliation:
    def test_a_matching_total_reconciles(self) -> None:
        result = study_mod.reconcile_with_aud04(
            sum_hold_pnl=Decimal("0.61"), aud04_realised_pnl_after_fees_total=Decimal("0.61"),
        )
        assert result.matched is True
        assert result.divergence == Decimal(0)

    def test_a_mismatched_total_does_not_reconcile_and_names_the_divergence(self) -> None:
        result = study_mod.reconcile_with_aud04(
            sum_hold_pnl=Decimal("0.61"), aud04_realised_pnl_after_fees_total=Decimal("0.50"),
        )
        assert result.matched is False
        assert result.divergence == Decimal("0.11")

    def test_an_empty_study_against_a_nonzero_aud04_total_is_a_mismatch_never_dropped(
        self,
    ) -> None:
        result = study_mod.reconcile_with_aud04(
            sum_hold_pnl=None, aud04_realised_pnl_after_fees_total=Decimal("0.50"),
        )
        assert result.matched is False
        assert result.divergence == Decimal("0.50")

    def test_the_reconciliation_reads_aud04_through_its_schema_version_reader(
        self, tmp_path: Path,
    ) -> None:
        report_path = tmp_path / "PRIVATE_portfolio_roi_2026-01-10.json"
        _write_minimal_aud04_report(report_path, realised_pnl_after_fees_total=Decimal("0.61"))

        view = prr.read_portfolio_roi_report(report_path)
        result = study_mod.reconcile_with_aud04(
            sum_hold_pnl=Decimal("0.61"),
            aud04_realised_pnl_after_fees_total=view.realised_pnl_after_fees_total,
        )
        assert result.matched is True


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

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str, *, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(self._status_code, request=request)


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


def _study_argv(tmp_path: Path, *, cache_dir: Path) -> list[str]:
    catalog = tmp_path / "catalog"
    catalog.mkdir(exist_ok=True)
    return [
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
    )

    assert [row.position.station for row in rows] == [_CACHED_CITY]
    failed = [item for item in missing if _FAILED_CITY in item]
    assert failed
    assert all("429" in item for item in failed)
    assert study_mod.main(_study_argv(tmp_path, cache_dir=cache_dir)) == 0


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

    code = study_mod.main(_study_argv(tmp_path, cache_dir=cache_dir))

    assert code != 0
    report = tmp_path / "out" / "synthetic-fetch" / "exit_window_study.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    missing = payload["missing_inputs"]
    for city in (_FAILED_CITY, _CACHED_CITY):
        named = [item for item in missing if city in item and "429" in item]
        assert named, missing
