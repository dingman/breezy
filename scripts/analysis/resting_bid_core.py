"""Pure core for the offline "resting bid" counterfactual study, Arm A
(``docs/plans/RESTING_BID_HUNT_2026-09-16.md`` Sec 2).

Reuses, never re-derives: :class:`~breezy.strategy.weather_common
.running_extreme.RunningExtremeAccumulator` for the observation-driven
running max, :func:`~breezy.strategy.current_rung_hold.tick_eval.width_and_m`
for the legal-cell derivation, :func:`~breezy.strategy.current_rung_hold
.monitor_evidence.p_hold_at` for the ARCHIVE ``p_bound`` lookup (already
``None`` below the frozen table's own ``N_MIN`` -- see ``archive_table.py``'s
module docstring), and :func:`~breezy.strategy.current_rung_hold
.monitor_decision.evaluate_monitor` for the leg-aware rung-death classifier
that drives this module's CANCEL-on-rung-death rule (module docstring's
"Confirmation modes" note: ``ThesisState.DEAD_BY_OBSERVATION`` is already the
YES "running max cleared the rung" state AND the NO "inside the rung after
the peak hour" state -- the two conditions the plan's cancel rule names --
so one state comparison is leg-correct for both).

Taker fee reuse: :func:`fee_taker` calls the SAME ``decision._fee`` formula
(``theta * price * (1 - price)``, banker's-rounded to the cent) the live
strategy uses for its break-even test, at the SAME ``theta = 0.06`` pin
(``config.py``'s ``required_fee_coefficient`` default). :func:`fee_maker`
calls the IDENTICAL formula at a DIFFERENT, LOCAL, PROVISIONAL coefficient
(``MAKER_FEE_COEFFICIENT = -0.0125``) -- **DOCUMENTED-NOT-WIRE-OBSERVED**:
no maker fee schedule has ever been read from the venue (plan Sec 0.5 --
``Order`` carries a SEPARATE ``makerCommissionsBasisPoints`` that has never
been captured). A negative coefficient makes :func:`fee_maker` a REBATE
(``fee_maker(p) <= 0`` for every ``p`` in ``(0, 1)``), which is why every
maker PnL formula below reads ``payoff - price - fee_maker(price)`` (SUBTRACT
a negative number to ADD the rebate) rather than the taker convention's
``payoff - price - fee_taker(price)`` (still a subtraction, but there
``fee_taker`` is a genuine cost). A separate maker branch of ``fees.py`` is
being added concurrently by another agent -- this module does NOT import it
(brief instruction); when that lands, this local constant is the thing to
replace, not the formula shape.

Rung/closed-bounds parsing reuses ``h4_preliminary_economic_read.parse_rung``
/``.Rung``/``.parse_ladder`` (the offline instrument-id grammar parser every
sibling analysis script uses -- NOT ``adapters.polymarket_us.symbology
.parse_weather_slug``, which requires a live venue-prose cross-check this
offline study has no access to).

PURE module: no I/O, no wall-clock read, no Nautilus strategy/clock/cache
access. ``OrderBookDepth10`` (a Nautilus VALUE OBJECT, immutable data) is
accepted as a plain input, exactly as ``exit_window_core.py``/``monitor_
evidence.py`` already do.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Final, Literal

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from archive_correction_probe import wilson_interval
from nautilus_trader.model.data import OrderBookDepth10
from settlement_truth_dataset import bucket_facts

from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.strategy.current_rung_hold.decision import _fee as _fee_formula
from breezy.strategy.current_rung_hold.monitor_decision import (
    MonitorHistory,
    ThesisState,
    evaluate_monitor,
)
from breezy.strategy.current_rung_hold.monitor_evidence import (
    Leg,
    build_monitor_evidence,
    p_hold_at,
)
from breezy.strategy.current_rung_hold.strategy import _local_hour
from breezy.strategy.current_rung_hold.tick_eval import width_and_m
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

__all__ = [
    "ADVERSE_SELECTION_DROP_MARGIN",
    "ADVERSE_SELECTION_WINDOW_NS",
    "CANCEL_LATENCY_NS",
    "COVERAGE_MAX_GAP_NS",
    "COVERAGE_MIN_FRACTION",
    "DEFAULT_MARGINS",
    "DEFAULT_QUEUE_SHARES",
    "MAKER_FEE_COEFFICIENT",
    "TAKER_FEE_COEFFICIENT",
    "WINDOW_END_HOUR_LST",
    "WINDOW_START_HOUR_LST",
    "FillEligibleEvent",
    "IocTake",
    "LegEvent",
    "RestingSimResult",
    "bucket_facts",
    "build_leg_events",
    "classify_fill",
    "compute_p_star",
    "fee_maker",
    "fee_taker",
    "fill_pnl",
    "ioc_pnl",
    "is_qualifying_station_day",
    "leg_ask_price",
    "simulate_leg",
    "time_to_fill_band",
    "wilson_interval",
    "window_coverage_fraction",
]

_ONE: Final[Decimal] = Decimal(1)
_ZERO: Final[Decimal] = Decimal(0)
_CENT: Final[Decimal] = Decimal("0.01")

#: The archive break-even fee coefficient (``config.py``'s
#: ``required_fee_coefficient`` default) -- the SAME number the live IOC
#: rule's ``decision._fee`` uses.
TAKER_FEE_COEFFICIENT: Final[Decimal] = Decimal("0.06")

#: PROVISIONAL, DOCUMENTED-NOT-WIRE-OBSERVED (module docstring). Negative:
#: a maker REBATE, not a cost.
MAKER_FEE_COEFFICIENT: Final[Decimal] = Decimal("-0.0125")

#: PROVISIONAL registered margins (plan Sec 1.2/2.1), probability points.
DEFAULT_MARGINS: Final[tuple[Decimal, ...]] = (Decimal("0.02"), Decimal("0.05"))

#: PROVISIONAL queue-share fractions (brief).
DEFAULT_QUEUE_SHARES: Final[tuple[Decimal, ...]] = (
    Decimal("0.25"),
    Decimal("0.5"),
    Decimal("1.0"),
)

#: PROVISIONAL venue tick size (plan Sec 1.2 clamp; no instrument-level
#: ``price_increment`` is loaded offline -- see ``symbology.py``'s
#: per-market ``orderPriceMinTickSize``, unavailable in this study).
_TICK_CENTS: Final[int] = 1
#: Executable band (``config.py`` ``executable_ask_lower``/``upper``),
#: STRICTLY interior -- the search grid never touches 0.05 or 0.95.
_BAND_LOW_CENTS: Final[int] = 5
_BAND_HIGH_CENTS: Final[int] = 95

#: PROVISIONAL cancel latency (plan Sec 1.3/brief): 500 ms.
CANCEL_LATENCY_NS: Final[int] = 500_000_000

#: The strategy's own observation-visibility poll lag (``config.py``
#: ``nws_observation_config.py:41``) -- the REAL 300 s the live node is
#: behind an observation's own valid instant.
POLL_LAG_NS: Final[int] = 300_000_000_000

#: PROVISIONAL adverse-selection classifier window/margin (plan Sec 1.4).
ADVERSE_SELECTION_WINDOW_NS: Final[int] = 600_000_000_000
ADVERSE_SELECTION_DROP_MARGIN: Final[Decimal] = Decimal("0.05")

#: The decision window (``strategy.py:154-155``), exclusive end.
WINDOW_START_HOUR_LST: Final[int] = 12
WINDOW_END_HOUR_LST: Final[int] = 17

#: Coverage/stranded classifier (brief): qualifying iff >= 80% of the
#: window's duration is covered by consecutive-frame gaps <= 60 s.
COVERAGE_MAX_GAP_NS: Final[int] = 60_000_000_000
COVERAGE_MIN_FRACTION: Final[float] = 0.8

_TIME_TO_FILL_BANDS: Final[tuple[tuple[int, str], ...]] = (
    (5 * 60_000_000_000, "<5min"),
    (30 * 60_000_000_000, "5-30min"),
    (120 * 60_000_000_000, "30-120min"),
)


# ---------------------------------------------------------------------------
# Fees (reuse decision._fee, two coefficients)
# ---------------------------------------------------------------------------


def fee_taker(price: Decimal) -> Decimal:
    """The live IOC rule's own break-even fee, at ``TAKER_FEE_COEFFICIENT``."""
    return _fee_formula(price, TAKER_FEE_COEFFICIENT)


def fee_maker(price: Decimal) -> Decimal:
    """The PROVISIONAL maker rebate -- SAME formula, negative coefficient.

    See the module docstring's DOCUMENTED-NOT-WIRE-OBSERVED note. Always
    ``<= 0`` for ``price`` in ``(0, 1)``.
    """
    return _fee_formula(price, MAKER_FEE_COEFFICIENT)


# ---------------------------------------------------------------------------
# The resting price p*
# ---------------------------------------------------------------------------


def compute_p_star(p_bound: Decimal | None, margin: Decimal) -> Decimal | None:
    """The highest venue-tick price with ``edge_maker(p) >= margin``.

    Searches the tick grid strictly inside the executable band
    ``(0.05, 0.95)`` (plan Sec 1.2's clamp), from the top down -- ``edge_maker
    (p) = p_bound - (p + fee_maker(p))`` is monotone NON-INCREASING in ``p``
    for the PROVISIONAL ``MAKER_FEE_COEFFICIENT`` magnitude (a rebate whose
    own contribution shrinks slower than ``p`` grows), so the first
    tick-aligned price (descending) that satisfies the margin is the highest
    one. Returns ``None`` when ``p_bound`` is ``None`` (undefined cell) or no
    tick in the band satisfies ``margin`` -- never a guessed price.

    Deliberately does NOT compare against the current best ask -- see
    :func:`simulate_leg`'s docstring for the "does this rest, or is this the
    IOC case" decision, made by the caller from THIS value.
    """
    if p_bound is None:
        return None
    for cents in range(_BAND_HIGH_CENTS - _TICK_CENTS, _BAND_LOW_CENTS, -_TICK_CENTS):
        price = Decimal(cents) / 100
        edge = p_bound - (price + fee_maker(price))
        if edge >= margin:
            return price
    return None


# ---------------------------------------------------------------------------
# Leg-aware top-of-book ask (module docstring: reuse decision.py's NO_ask
# formula, never invented)
# ---------------------------------------------------------------------------


def _top_of_book(levels: Sequence[object]) -> tuple[Decimal | None, Decimal | None]:
    """The first non-zero-size level's ``(price, size)``, or ``(None, None)``."""
    for level in levels:
        size = level.size.as_decimal()  # type: ignore[attr-defined]
        if size > _ZERO:
            return level.price.as_decimal(), size  # type: ignore[attr-defined]
    return None, None


def leg_ask_price(
    depth: OrderBookDepth10 | None, leg: Leg, *, min_size: Decimal = _ONE,
) -> Decimal | None:
    """The leg's own "ask" domain value: what a TAKER would pay to BUY this leg.

    YES: the top-of-book ``depth.asks`` price directly. NO: ``1 -
    top_of_book(depth.bids)`` -- EXACTLY ``decision._evaluate_no_side``'s
    ``no_ask = 1 - inputs.bid`` formula (module docstring), never a fresh
    derivation. ``None`` when ``depth`` is ``None`` or the relevant side's
    top-of-book size is below ``min_size`` (mirrors ``evaluate_decision``'s
    ``minimum_displayed_size`` executable gate).
    """
    if depth is None:
        return None
    if leg == "YES":
        price, size = _top_of_book(depth.asks)
        if price is None or size is None or size < min_size:
            return None
        return price
    if leg == "NO":
        price, size = _top_of_book(depth.bids)
        if price is None or size is None or size < min_size:
            return None
        return _ONE - price
    raise ValueError(f"unknown leg {leg!r}; expected 'YES' or 'NO'")  # pragma: no cover


# ---------------------------------------------------------------------------
# Per-instant facts: LegEvent, and the glue that builds a sequence of them
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class LegEvent:
    """One evaluated instant for one (station-day, rung, leg): every fact
    :func:`simulate_leg` needs, already resolved from the accumulator/Depth10/
    monitor_decision (module docstring). ``kind == "depth"`` instants are the
    only ones :func:`simulate_leg` checks for a fill-eligible transition."""

    ts_ns: int
    kind: Literal["depth", "obs"]
    ask: Decimal | None
    p_bound: Decimal | None
    in_window: bool
    rung_dead: bool
    stale: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class _DepthTick:
    depth: OrderBookDepth10


@dataclass(frozen=True, slots=True, kw_only=True)
class _ObsTick:
    pass


def build_leg_events(
    *,
    station: str,
    season: str,
    climate_day: date,
    instrument_id: str,
    leg: Leg,
    facts: WeatherBucketFacts,
    accumulator: RunningExtremeAccumulator,
    std_utc_offset_hours: float,
    stale_bound_ns: int,
    depth_frames: Sequence[OrderBookDepth10],
    observation_visible_ts_ns: Sequence[int],
    window_start_hour_lst: int = WINDOW_START_HOUR_LST,
    window_end_hour_lst: int = WINDOW_END_HOUR_LST,
    fee_coefficient: Decimal = TAKER_FEE_COEFFICIENT,
) -> tuple[LegEvent, ...]:
    """Every evaluated instant for one (rung, leg), ``ts_ns``-ascending.

    Merges Depth10 frames and observation-VISIBILITY instants (the caller
    passes ``observation_visible_ts_ns`` already lagged by
    :data:`POLL_LAG_NS` -- this function has no opinion on the lag, exactly
    ``exit_window_core.build_exit_timeline``'s own depth/obs merge shape).
    ``accumulator`` must already have been fed with ``received_at_ns ==
    observed_at_ns + POLL_LAG_NS`` (never hindsight) so
    ``accumulator.value_at``/``staleness_ns`` at any ``ts_ns`` here already
    reflect only what would genuinely have been visible.

    Rung-death (module docstring) is read from ``monitor_decision
    .evaluate_monitor``'s ``ThesisState.DEAD_BY_OBSERVATION`` -- leg-correct
    for BOTH legs already (the module it lives in dispatches on ``leg``), so
    this function makes no separate YES/NO rung-death decision of its own.
    """
    events: list[tuple[int, int, object]] = [
        (frame.ts_init, 1, _DepthTick(depth=frame)) for frame in depth_frames
    ]
    events.extend((ts, 0, _ObsTick()) for ts in observation_visible_ts_ns)
    events.sort(key=lambda item: (item[0], item[1]))

    history = MonitorHistory.EMPTY
    last_depth: OrderBookDepth10 | None = None
    results: list[LegEvent] = []

    for ts_ns, _tiebreak, tick in events:
        if isinstance(tick, _DepthTick):
            last_depth = tick.depth

        running_max = accumulator.value_at(ts_ns)
        if running_max is None:
            results.append(
                LegEvent(
                    ts_ns=ts_ns, kind="depth" if isinstance(tick, _DepthTick) else "obs",
                    ask=leg_ask_price(last_depth, leg), p_bound=None, in_window=False,
                    rung_dead=False, stale=True,
                ),
            )
            continue

        staleness_ns = accumulator.staleness_ns(ts_ns)
        stale = staleness_ns is None or staleness_ns > stale_bound_ns
        hour_lst = _local_hour(ts_ns, std_utc_offset_hours)
        in_window = window_start_hour_lst <= hour_lst < window_end_hour_lst
        width_code, m_code = width_and_m(facts, running_max)
        cell_p_bound = None if stale else p_hold_at(
            station=station, season=season, hour_lst=hour_lst, width_code=width_code,
            m_code=m_code, leg=leg,
        )

        evidence = build_monitor_evidence(
            ts_ns=ts_ns,
            instrument_id=instrument_id,
            station=station,
            climate_day=climate_day.isoformat(),
            season=season,
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
            leg=leg,
            entry_context="resting_bid_study",
            fill_px=Decimal("0.50"),
            held_qty=1,
            running_max_lower=running_max.lower_f,
            running_max_upper=running_max.upper_f,
            staleness_ns=staleness_ns,
            book_staleness_ns=0,
            rung_low=facts.lower_f,
            rung_high=facts.upper_f,
            depth=last_depth,
            fee_coefficient=fee_coefficient,
            p_hold_at_entry=None,
            observed_at_ns=running_max.source_observed_at_ns,
        )
        decision, history = evaluate_monitor(
            evidence, history, stale_observation_bound_ns=stale_bound_ns,
        )
        rung_dead = decision.state is ThesisState.DEAD_BY_OBSERVATION

        results.append(
            LegEvent(
                ts_ns=ts_ns, kind="depth" if isinstance(tick, _DepthTick) else "obs",
                ask=leg_ask_price(last_depth, leg), p_bound=cell_p_bound, in_window=in_window,
                rung_dead=rung_dead, stale=stale,
            ),
        )

    return tuple(results)


# ---------------------------------------------------------------------------
# The resting/re-price/cancel/fill state machine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class FillEligibleEvent:
    """One CROSSING-EVENT (Rev 2 Sec 2.1's renamed term for what was called a
    "transition event": best-ask crossed to <= the resting price) --
    deterministic and independent of the queue-share ``s``; the caller
    scales counts/PnL by ``s`` when aggregating (brief: "report all three").
    Renamed, never re-modelled, so it cannot read as validating a crossed
    rest (Rev 2 finding 3)."""

    ts_ns: int
    price: Decimal
    rest_start_ts_ns: int
    p_bound_at_fill: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class IocTake:
    """The IOC baseline's first executable snapshot (mirrors ``decision
    .evaluate_decision``'s taker rule, at :data:`TAKER_FEE_COEFFICIENT`)."""

    ts_ns: int
    price: Decimal
    p_bound: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class RestingSimResult:
    rests: int
    reprices: int
    cancels_by_reason: Mapping[str, int]
    fill_events: tuple[FillEligibleEvent, ...]
    ioc_take: IocTake | None


def _cancels_dict() -> dict[str, int]:
    return {}


@dataclass(slots=True)
class _State:
    resting_price: Decimal | None = None
    rest_start_ts_ns: int | None = None
    side_above: bool = True
    pending_cancel_reason: str | None = None
    pending_cancel_effective_ns: int | None = None
    rests: int = 0
    reprices: int = 0
    cancels: dict[str, int] = field(default_factory=_cancels_dict)
    fills: list[FillEligibleEvent] = field(default_factory=list)
    ioc_take: IocTake | None = None


def _record_cancel_complete(state: _State) -> None:
    """Clear the resting order once its pending cancel takes effect.

    The cancel is COUNTED at the DECISION instant (:func:`_start_pending_
    cancel`), not here -- a cancel that is still in flight when a finite
    event window ends is still a real cancel decision (the brief's
    ``cancels_by_reason`` accounting), even though this replay never
    observes its completion.
    """
    state.resting_price = None
    state.rest_start_ts_ns = None
    state.pending_cancel_reason = None
    state.pending_cancel_effective_ns = None
    state.side_above = True


def _start_pending_cancel(state: _State, reason: str, ts_ns: int) -> None:
    state.cancels[reason] = state.cancels.get(reason, 0) + 1
    state.pending_cancel_reason = reason
    state.pending_cancel_effective_ns = ts_ns + CANCEL_LATENCY_NS


def simulate_leg(
    events: Sequence[LegEvent], *, margin: Decimal,
) -> RestingSimResult:
    """Replay one (rung, leg)'s events under the REST/RE-PRICE/CANCEL/FILL
    rules (plan Sec 1.3, brief).

    REST: not already resting/cancel-pending, ``in_window``, not ``stale``,
    not ``rung_dead``, ``p_bound`` defined, and the nominal :func:`compute_
    p_star` price is STRICTLY below the current ``ask`` -- otherwise this
    instant is the IOC case (never rested here; the caller's own
    :class:`IocTake` tracking, run independently below, is unaffected).

    RE-PRICE: while resting, a change in the nominal price re-prices in
    place (no transition credited -- ``side_above`` resets, since the rule
    never rests crossed, so the ask is guaranteed above the new price at the
    re-price instant).

    CANCEL: staleness, window close, rung death, or the nominal price
    ceasing to exist/satisfy the margin. A cancel is NOT instantaneous: it
    goes ``pending`` at the deciding instant and completes
    :data:`CANCEL_LATENCY_NS` later (the race window plan Sec 2.1 step 4
    describes) -- the resting order (and its fill-eligibility) stays live
    until the pending cancel's effective instant is reached by a later
    event's ``ts_ns``, so a fill strictly inside the race window still
    counts, and nothing at or after the effective instant ever does (the
    order is by then reliably gone).

    FILL (transition, not sustained-cross): only on ``kind == "depth"``
    events, only while genuinely resting (not cancel-pending... actually
    pending-cancel STILL resting until effective -- see above), the
    ask-vs-price relationship flipping from above to at-or-below is exactly
    ONE :class:`FillEligibleEvent`; it does not re-fire while the ask stays
    at-or-below, only on the NEXT above-to-at-or-below flip.
    """
    state = _State()

    for event in events:
        if (
            state.pending_cancel_effective_ns is not None
            and event.ts_ns >= state.pending_cancel_effective_ns
        ):
            _record_cancel_complete(state)

        if state.ioc_take is None and event.kind == "depth" and event.in_window and (
            not event.stale
        ) and event.ask is not None and event.p_bound is not None:
            edge = event.p_bound - (event.ask + fee_taker(event.ask))
            if edge > _ZERO:
                state.ioc_take = IocTake(
                    ts_ns=event.ts_ns, price=event.ask, p_bound=event.p_bound,
                )

        if state.pending_cancel_reason is None:
            nominal = compute_p_star(event.p_bound, margin) if not event.stale else None
            can_rest_here = (
                event.in_window and not event.stale and not event.rung_dead
                and nominal is not None and event.ask is not None and nominal < event.ask
            )

            if state.resting_price is not None:
                reason: str | None = None
                if event.stale:
                    reason = "staleness"
                elif not event.in_window:
                    reason = "window_close"
                elif event.rung_dead:
                    reason = "rung_death"
                elif not can_rest_here:
                    reason = "edge_gone"
                elif nominal != state.resting_price:
                    state.reprices += 1
                    state.resting_price = nominal
                    state.side_above = True

                if reason is not None:
                    _start_pending_cancel(state, reason, event.ts_ns)
            elif can_rest_here:
                assert nominal is not None
                state.resting_price = nominal
                state.rest_start_ts_ns = event.ts_ns
                state.rests += 1
                state.side_above = True

        if (
            event.kind == "depth" and state.resting_price is not None and event.ask is not None
        ):
            now_at_or_below = event.ask <= state.resting_price
            if state.side_above and now_at_or_below:
                assert state.rest_start_ts_ns is not None
                state.fills.append(
                    FillEligibleEvent(
                        ts_ns=event.ts_ns, price=state.resting_price,
                        rest_start_ts_ns=state.rest_start_ts_ns,
                        p_bound_at_fill=event.p_bound,
                    ),
                )
            state.side_above = not now_at_or_below

    return RestingSimResult(
        rests=state.rests, reprices=state.reprices, cancels_by_reason=dict(state.cancels),
        fill_events=tuple(state.fills), ioc_take=state.ioc_take,
    )


# ---------------------------------------------------------------------------
# Fill classification, PnL, time-to-fill
# ---------------------------------------------------------------------------


def classify_fill(
    fill: FillEligibleEvent, events: Sequence[LegEvent],
) -> Literal["I", "L"]:
    """"I" (informed) iff the NEXT visible observation within
    :data:`ADVERSE_SELECTION_WINDOW_NS` of the fill moves ``p_bound`` DOWN by
    more than :data:`ADVERSE_SELECTION_DROP_MARGIN`; else "L" (liquidity) --
    the plan's default when no disproof of liquidity exists (module
    docstring, plan Sec 1.4's estimator)."""
    if fill.p_bound_at_fill is None:
        return "L"
    horizon_ns = fill.ts_ns + ADVERSE_SELECTION_WINDOW_NS
    for event in events:
        if event.kind != "obs" or event.ts_ns <= fill.ts_ns:
            continue
        if event.ts_ns > horizon_ns:
            break
        if event.p_bound is None:
            continue
        if (fill.p_bound_at_fill - event.p_bound) > ADVERSE_SELECTION_DROP_MARGIN:
            return "I"
        return "L"
    return "L"


def fill_pnl(fill: FillEligibleEvent, *, leg_won: bool | None) -> Decimal | None:
    """``payoff - price - fee_maker(price)`` (a rebate SUBTRACTS a negative
    number, i.e. adds its magnitude -- module docstring). ``None`` when the
    settlement outcome is unknown."""
    if leg_won is None:
        return None
    payoff = _ONE if leg_won else _ZERO
    return payoff - fill.price - fee_maker(fill.price)


def ioc_pnl(take: IocTake, *, leg_won: bool | None) -> Decimal | None:
    """The IOC baseline's PnL for the SAME settlement outcome."""
    if leg_won is None:
        return None
    payoff = _ONE if leg_won else _ZERO
    return payoff - (take.price + fee_taker(take.price))


def time_to_fill_band(fill: FillEligibleEvent) -> str:
    """One of ``"<5min"``/``"5-30min"``/``"30-120min"``/``">120min"``."""
    elapsed_ns = fill.ts_ns - fill.rest_start_ts_ns
    for bound_ns, label in _TIME_TO_FILL_BANDS:
        if elapsed_ns < bound_ns:
            return label
    return ">120min"


# ---------------------------------------------------------------------------
# Station-day coverage: qualifying vs stranded (ING-1)
# ---------------------------------------------------------------------------


def window_coverage_fraction(
    frame_ts_ns: Sequence[int], window_start_ns: int, window_end_ns: int,
) -> float:
    """Fraction of ``[window_start_ns, window_end_ns)`` covered by
    consecutive-frame gaps (including the two boundary gaps) of at most
    :data:`COVERAGE_MAX_GAP_NS`. ``0.0`` on an empty/degenerate window."""
    duration = window_end_ns - window_start_ns
    if duration <= 0:
        return 0.0
    ts_in_window = sorted(t for t in frame_ts_ns if window_start_ns <= t < window_end_ns)
    if not ts_in_window:
        return 0.0
    boundaries = [window_start_ns, *ts_in_window, window_end_ns]
    covered = sum(
        (later - earlier)
        for earlier, later in pairwise(boundaries)
        if (later - earlier) <= COVERAGE_MAX_GAP_NS
    )
    return covered / duration


def is_qualifying_station_day(fraction: float) -> bool:
    return fraction >= COVERAGE_MIN_FRACTION
