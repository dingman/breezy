"""Pure SHADOW resting-bid decider (``RESTING_BID_HUNT_2026-09-16.md`` Rev 2,
§1 model + cancel triggers, §2.1 crossing-event proxy, §6 shadow stage).

This module computes the resting-bid counterfactual for one leg
(``station``, ``climate_day``, ``leg``) per hunt tick and returns a result
the caller PERSISTS -- it never constructs an order, never touches
``SubmitIntent``/``TrialDayLatch``, and never blocks a take. Zero call
sites to order construction is a hard invariant, pinned by
``tests/unit/test_resting_decider_shadow.py``'s zero-call-sites RED test:
this module must never import ``breezy.adapters.polymarket_us.exec.
submit_chain``/``order_factory``, never construct a Nautilus ``Order``, and
never call ``submit_order``.

§1.2 -- the resting price
--------------------------
``p*`` is the **highest venue tick price** (1-cent ticks, matching
``decision.py``'s own ``_CENT`` fee-rounding grid) strictly BELOW the best
ask, with ``edge_rest_conservative(p) = p_bound - (p + fee_rest_
conservative(p)) >= m``, clamped to ``[0.05, 0.95]``. PREREG v5 §3b and
plan Rev 2 §1.2 pin the TAKER coefficient (``+theta``, a cost) for this
arithmetic, not the maker rebate: no wire-observed maker fill exists yet
to justify pricing a REST at the rebate, so every number this module
produces (``p*``, the two margins, ``price_secondary``) is deliberately
the CONSERVATIVE (taker-priced) bound until that observation retires the
pin. ``fee_rest_conservative`` is
:func:`breezy.adapters.polymarket_us.fees.expected_fee_for` at
``LiquiditySide.TAKER`` -- a COST (positive), so this module's edge is
never larger than what a genuine maker fill would realize; it only ever
understates the true edge, never overstates it. A price that would not be
strictly below the best ask is never a rest -- it is ``WOULD_CROSS``, the
taker family's job, never this one's.

Two margins are evaluated every tick, both PROVISIONAL and both recorded on
:class:`ShadowRestTickResult` (:data:`MARGIN_PRIMARY` drives the state
machine; :data:`MARGIN_SECONDARY` is observability-only, per the plan's "m
in {0.02 primary, 0.05 secondary}, both recorded").

§1.3 -- REST / RE-PRICE / CANCEL
----------------------------------
Per ``(station, climate_day, leg)`` key: ``NONE -> RESTING(p*)`` on the
first eligible tick; ``RE-PRICE`` (cancel-then-rest, in-place here since
there is no real order to cancel) when ``p*`` changes; ``CANCEL`` with a
reason code from :data:`REASON_CODES` when a live rest becomes ineligible.
The priority order below mirrors the plan's own ordering intent (a fail-
closed condition always outranks the price computation).

§2.1 -- the crossing-event proxy
-----------------------------------
A **fill-eligible event** is the transition ``ask > p*`` -> ``ask <= p*``
between consecutive ticks while RESTING at ``p*``, at most once per
persistent crossing (a book that merely stays crossed yields no further
events -- see the plan's own caveat on this being a proxy, never a fill).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Final, Literal

from nautilus_trader.model.enums import LiquiditySide

from breezy.adapters.polymarket_us.fees import expected_fee_for

__all__ = [
    "MARGIN_PRIMARY",
    "MARGIN_SECONDARY",
    "MAX_CLIMATE_DAYS_PER_STATION_LEG",
    "PRICE_CEILING",
    "PRICE_FLOOR",
    "REASON_CODES",
    "TICK",
    "Leg",
    "RestKey",
    "ShadowRestTickResult",
    "ShadowRestingDecider",
    "compute_p_star",
    "edge_rest_conservative",
    "fee_rest_conservative",
]

#: 1-cent venue tick, matching ``decision.py``'s own fee-rounding grid
#: (``_CENT``) and the executable-ask band's own scale.
TICK: Final[Decimal] = Decimal("0.01")

#: The executable-ask band this package pins (``config.py``'s
#: ``executable_ask_lower``/``executable_ask_upper`` defaults) -- the
#: decider clamps ``p*`` to the same band rather than importing
#: ``CurrentRungHoldConfig`` (this module stays pure/independent; a caller
#: may override via ``evaluate_tick``'s keyword arguments).
PRICE_FLOOR: Final[Decimal] = Decimal("0.05")
PRICE_CEILING: Final[Decimal] = Decimal("0.95")

#: PROVISIONAL (plan §1.2): the primary margin drives the shadow state
#: machine; the secondary is recorded for observability only and never
#: drives a REST/RE-PRICE/CANCEL transition.
MARGIN_PRIMARY: Final[Decimal] = Decimal("0.02")
MARGIN_SECONDARY: Final[Decimal] = Decimal("0.05")

#: The closed set of reason codes this module can emit -- either as a CANCEL
#: (a live rest became ineligible) or as a WAIT (no rest was ever possible
#: this tick). Widening this set is a change to every consumer that reads
#: it (mirrors ``decision.REFUSAL_REASONS``'s own closed-set discipline).
REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "edge_below_margin",
        "staleness",
        "window_close",
        "rung_dead",
        "sibling_leg_filled",
        "halt",
        "p_hold_undefined",
        "would_cross",
        "fee_schedule_mismatch",
        "decider_error",
    }
)

#: Domain review of 87446c2, finding 2: the hard cap on distinct
#: ``climate_day`` values tracked per ``(station, leg)`` pair, in BOTH
#: :class:`ShadowRestingDecider`'s own ``_states`` and the strategy's
#: ``_shadow_rest_summaries`` (``continuous_strategy.py``). A missed
#: window-close signal (no more ticks ever arrive for a station-day) must
#: never let either dict grow past this many climate_days per leg times
#: the finite station set -- self-enforced by :meth:`ShadowRestingDecider.
#: evaluate_tick` on every new key, never dependent on a caller
#: remembering to call :meth:`ShadowRestingDecider.close_window`.
MAX_CLIMATE_DAYS_PER_STATION_LEG: Final[int] = 3

#: One contract per order -- the live-small spec's own pin
#: (``config.py``'s ``order_quantity``), used only as the ``qty`` argument
#: to :func:`expected_fee_for` (a pure per-contract estimate, no
#: ``Instrument``, no rounding -- see that function's own docstring).
_ONE_CONTRACT: Final[Decimal] = Decimal(1)

Leg = Literal["YES", "NO"]
RestState = Literal["NONE", "RESTING"]

#: ``(station, climate_day, leg)`` -- the shadow state machine's own key,
#: mirroring ``trial_day_latch.py``'s ``station_day_admission`` key shape
#: plus the leg this state belongs to (finding 1/2 in the plan: two legs of
#: one station-day never share one record).
RestKey = tuple[str, str, Leg]


def fee_rest_conservative(price: Decimal) -> Decimal:
    """``expected_fee_for(price, 1, TAKER)`` -- a COST (positive Decimal).

    PREREG v5 §3b / plan Rev 2 §1.2: priced at the TAKER coefficient
    (``+theta``, documented at ``fees.py``'s ``_DOCUMENTED_TAKER_FEE_
    COEFFICIENT``), never the maker rebate -- no wire-observed maker fill
    exists yet to retire that pin. This makes every downstream number
    (``p*``, both margins, ``price_secondary``) the CONSERVATIVE bound: it
    only ever understates a true maker fill's edge, never overstates it.
    """
    return expected_fee_for(price, _ONE_CONTRACT, LiquiditySide.TAKER)


def edge_rest_conservative(p_bound: Decimal, price: Decimal) -> Decimal:
    """``p_bound - (price + fee_rest_conservative(price))`` -- the
    conservative (taker-priced) edge a rest at ``price`` would realize;
    never larger than the true edge a maker fill would realize, because
    ``fee_rest_conservative`` prices a cost where a real maker fill would
    earn a rebate."""
    return p_bound - (price + fee_rest_conservative(price))


def _quantize_down_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    """Floor ``value`` to the nearest ``tick`` multiple."""
    steps = (value / tick).to_integral_value(rounding=ROUND_FLOOR)
    return steps * tick


def compute_p_star(
    p_bound: Decimal,
    best_ask: Decimal,
    margin: Decimal,
    *,
    floor: Decimal = PRICE_FLOOR,
    ceiling: Decimal = PRICE_CEILING,
    tick: Decimal = TICK,
) -> tuple[Decimal | None, str | None]:
    """The highest tick price strictly below ``best_ask`` with
    ``edge_rest_conservative(p) >= margin``, clamped to ``[floor, ceiling]``.

    Returns ``(price, None)`` on success, or ``(None, reason)`` where
    ``reason`` is ``"would_cross"`` (no price strictly below ``best_ask``
    survives the band at all) or ``"edge_below_margin"`` (every candidate
    price in the band fails the margin).

    ``edge_rest_conservative`` is (for any economically sane ``theta``)
    non-increasing in ``p`` -- the linear ``-p`` term dominates the small,
    concave taker fee -- so the highest price in the admissible band is
    the FIRST candidate to check, and the search only ever walks downward.
    """
    ceiling_effective = min(ceiling, best_ask - tick)
    if ceiling_effective < floor:
        return None, "would_cross"

    price = max(_quantize_down_to_tick(ceiling_effective, tick), floor)
    while price >= floor:
        if edge_rest_conservative(p_bound, price) >= margin:
            return price, None
        price -= tick
    return None, "edge_below_margin"


@dataclass(frozen=True, slots=True, kw_only=True)
class ShadowRestTickResult:
    """One tick's shadow-decider outcome for one ``(station, climate_day, leg)``.

    ``reason`` is overloaded, by design: it carries a CANCEL reason code
    when a live rest just became ineligible, ``"rest"``/``"reprice"`` when
    a rest was just armed/re-priced, or a WAIT-style ineligibility code
    (``"would_cross"``/``"edge_below_margin"``/``"p_hold_undefined"``) when
    no rest was ever live. ``None`` only when RESTING and unchanged this
    tick. Every value is a member of :data:`REASON_CODES` except the two
    transition markers ``"rest"``/``"reprice"`` and the sentinel ``None``.

    ``fill_event`` is the §2.1 crossing-event PROXY only -- a bare boolean
    marking that the ask crossed the resting price this tick. It is never
    a fill, never a queue position, and applies no queue-share factor
    ``s``: that adjustment (turning a raw crossing count into an estimated
    fill count/rate) is applied DOWNSTREAM, offline, by the Arm A study
    (``scripts/analysis/current_rung_hold_resting_bid_study.py`` and
    ``resting_bid_core.py``) -- this module and its summary persistence
    never compute or store ``s``.
    """

    state: RestState
    price: Decimal | None
    margin: Decimal | None
    price_secondary: Decimal | None
    reason: str | None
    fill_event: bool


@dataclass(frozen=True, slots=True)
class _LegState:
    price: Decimal
    last_ask: Decimal
    crossed_active: bool


class ShadowRestingDecider:
    """Per-key shadow state machine.

    Domain review of 87446c2, finding 2 (CORRECTED): ``_states`` is NOT
    bounded merely by "the finite set of live keys a process ever hunts"
    -- a missed window-close signal (no caller ever calls
    :meth:`close_window` for a station-day whose ticks simply stop
    arriving) would let it grow one entry per climate_day forever. It is
    instead SELF-bounded: :meth:`evaluate_tick` evicts the oldest
    climate_days for a ``(station, leg)`` pair past
    :data:`MAX_CLIMATE_DAYS_PER_STATION_LEG` on every new-key insertion
    (see :meth:`evict_stale_climate_days`), independent of whether any
    caller ever calls :meth:`close_window` at all. Evicted CANCEL events
    are buffered (:meth:`drain_evictions`) so a caller can still fold them
    into its own summary tally exactly as it would a real window-close.
    """

    def __init__(self) -> None:
        self._states: dict[RestKey, _LegState] = {}
        #: Populated by :meth:`evaluate_tick`'s self-bounding eviction;
        #: drained (and cleared) by :meth:`drain_evictions`. A caller that
        #: never drains simply never sees these -- `_states` itself stays
        #: bounded regardless (the eviction already happened).
        self._eviction_buffer: list[tuple[RestKey, ShadowRestTickResult]] = []

    def __len__(self) -> int:
        return len(self._states)

    def is_resting(self, station: str, climate_day: str, leg: Leg) -> bool:
        return (station, climate_day, leg) in self._states

    def evaluate_tick(
        self,
        *,
        station: str,
        climate_day: str,
        leg: Leg,
        best_ask: Decimal | None,
        p_bound: Decimal | None,
        staleness_ns: int | None,
        stale_bound_ns: int,
        cell_legal: bool = True,
        in_window: bool = True,
        sibling_leg_filled: bool = False,
        family_halted: bool = False,
        fee_schedule_mismatch: bool = False,
        margin_primary: Decimal = MARGIN_PRIMARY,
        margin_secondary: Decimal = MARGIN_SECONDARY,
        floor: Decimal = PRICE_FLOOR,
        ceiling: Decimal = PRICE_CEILING,
        tick: Decimal = TICK,
    ) -> ShadowRestTickResult:
        """Advance the state machine for one key by one tick.

        Fail-closed conditions are checked in a fixed priority order before
        the price computation ever runs, mirroring the plan's own CANCEL
        registration (§1.3): ``halt`` > ``fee_schedule_mismatch`` >
        ``sibling_leg_filled`` > ``rung_dead`` > ``window_close`` >
        ``staleness`` > ``p_hold_undefined`` > the price computation
        itself. ``fee_schedule_mismatch`` (domain review of 87446c2,
        finding 6) mirrors the live decision's own ``fee_schedule_
        mismatch`` refusal (``decision.py``'s ``REFUSAL_REASONS``) -- a
        REST eligibility condition per PREREG v5 §3b / plan Rev 2 §1.3,
        checked right after ``halt`` because the live strategy latches
        ``_fee_halt`` permanently the same tick this fires.
        """
        key: RestKey = (station, climate_day, leg)

        price_secondary: Decimal | None = None
        if p_bound is not None and best_ask is not None:
            price_secondary, _ = compute_p_star(
                p_bound, best_ask, margin_secondary, floor=floor, ceiling=ceiling, tick=tick,
            )

        if family_halted:
            return self._exit(key, "halt", price_secondary)
        if fee_schedule_mismatch:
            return self._exit(key, "fee_schedule_mismatch", price_secondary)
        if sibling_leg_filled:
            return self._exit(key, "sibling_leg_filled", price_secondary)
        if not cell_legal:
            return self._exit(key, "rung_dead", price_secondary)
        if not in_window:
            return self._exit(key, "window_close", price_secondary)
        if staleness_ns is not None and staleness_ns > stale_bound_ns:
            return self._exit(key, "staleness", price_secondary)
        if p_bound is None:
            return self._exit(key, "p_hold_undefined", price_secondary)
        if best_ask is None:
            return self._exit(key, "p_hold_undefined", price_secondary)

        price, reason = compute_p_star(
            p_bound, best_ask, margin_primary, floor=floor, ceiling=ceiling, tick=tick,
        )
        if price is None:
            assert reason is not None
            return self._exit(key, reason, price_secondary)

        current = self._states.get(key)
        if current is None:
            self._states[key] = _LegState(price=price, last_ask=best_ask, crossed_active=False)
            self._eviction_buffer.extend(self.evict_stale_climate_days(station, leg))
            return ShadowRestTickResult(
                state="RESTING",
                price=price,
                margin=margin_primary,
                price_secondary=price_secondary,
                reason="rest",
                fill_event=False,
            )

        fill_event, crossed_active = self._crossing_event(current, best_ask)
        if price != current.price:
            self._states[key] = _LegState(
                price=price, last_ask=best_ask, crossed_active=False,
            )
            return ShadowRestTickResult(
                state="RESTING",
                price=price,
                margin=margin_primary,
                price_secondary=price_secondary,
                reason="reprice",
                fill_event=fill_event,
            )

        self._states[key] = _LegState(
            price=price, last_ask=best_ask, crossed_active=crossed_active,
        )
        return ShadowRestTickResult(
            state="RESTING",
            price=price,
            margin=margin_primary,
            price_secondary=price_secondary,
            reason=None,
            fill_event=fill_event,
        )

    @staticmethod
    def _crossing_event(current: _LegState, best_ask: Decimal) -> tuple[bool, bool]:
        """§2.1 -- one fill-eligible event per persistent crossing.

        Returns ``(fill_event, crossed_active)``: ``fill_event`` is `True`
        only on the tick the ask TRANSITIONS from above ``current.price`` to
        at-or-below it; ``crossed_active`` is the carried-forward state
        (never re-fires while the book stays crossed, resets once the ask
        moves back above the resting price).
        """
        was_crossed = current.crossed_active
        is_crossed = best_ask <= current.price
        fill_event = is_crossed and not was_crossed and current.last_ask > current.price
        return fill_event, is_crossed

    def _exit(
        self, key: RestKey, reason: str, price_secondary: Decimal | None,
    ) -> ShadowRestTickResult:
        """A CANCEL (if a rest was live) or a plain WAIT (if it was not),
        both reported the same way -- see :class:`ShadowRestTickResult`'s
        own docstring on ``reason``'s overload."""
        self._states.pop(key, None)
        return ShadowRestTickResult(
            state="NONE",
            price=None,
            margin=None,
            price_secondary=price_secondary,
            reason=reason,
            fill_event=False,
        )

    def close_window(self, station: str, climate_day: str, leg: Leg) -> ShadowRestTickResult | None:
        """Clear one key at window close, per §1.3's ``window_close`` CANCEL.

        Returns the CANCEL result only when a rest was actually live;
        `None` (no event to persist) when the key was already ``NONE``.
        """
        key: RestKey = (station, climate_day, leg)
        if key not in self._states:
            return None
        return self._exit(key, "window_close", None)

    def close_all_windows(self) -> tuple[tuple[RestKey, ShadowRestTickResult], ...]:
        """Clear every currently-RESTING key -- the ``on_stop``/day-rollover
        sweep. Iterates a snapshot of the keys since :meth:`close_window`
        mutates ``self._states``."""
        events = []
        for station, climate_day, leg in tuple(self._states):
            result = self.close_window(station, climate_day, leg)
            if result is not None:
                events.append(((station, climate_day, leg), result))
        return tuple(events)

    def evict_stale_climate_days(
        self, station: str, leg: Leg, *, keep_newest: int = MAX_CLIMATE_DAYS_PER_STATION_LEG,
    ) -> tuple[tuple[RestKey, ShadowRestTickResult], ...]:
        """Hard cap (domain review of 87446c2, finding 2): keep only the
        ``keep_newest`` climate_days (by string/date order) tracked in
        ``_states`` for ``(station, leg)``, evicting older ones as a
        ``"window_close"`` CANCEL (:meth:`close_window`'s own shape).

        Called automatically by :meth:`evaluate_tick` on every new-key
        insertion, so a missed rollover signal can never grow ``_states``
        past ``keep_newest`` climate_days per ``(station, leg)`` -- this is
        the SELF-enforced bound; a caller invoking it directly (e.g. from a
        day-rollover hook) is redundant but harmless (``close_window`` on
        an absent key is a no-op).
        """
        days = sorted(
            {cd for (st, cd, lg) in self._states if st == station and lg == leg},
        )
        if len(days) <= keep_newest:
            return ()
        events = []
        for stale_day in days[:-keep_newest]:
            result = self.close_window(station, stale_day, leg)
            if result is not None:
                events.append(((station, stale_day, leg), result))
        return tuple(events)

    def drain_evictions(self) -> tuple[tuple[RestKey, ShadowRestTickResult], ...]:
        """Return and clear every eviction :meth:`evaluate_tick` has
        self-enforced since the last drain -- the buffer a caller folds
        into its OWN summary tally so an evicted key's CANCEL is never
        silently lost, even though ``_states`` itself was already bounded
        without the caller's help."""
        events = tuple(self._eviction_buffer)
        self._eviction_buffer.clear()
        return events
