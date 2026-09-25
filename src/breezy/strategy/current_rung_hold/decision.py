"""The `current_rung_hold` PURE decision function (build order step 5).

No ``nautilus_trader`` import, no I/O, no clock read: every fact this module
needs -- the observation, the ladder, the quote, the config, the frozen
table's lookup key, and the trial-day latch's verdict -- is passed in by the
caller (``strategy.py``, step 6, gated on Seam B). This mirrors every other
strategy's ``decision.py`` in this repo
(``breezy.strategy.running_extreme_lock.decision``,
``breezy.strategy.cli_settlement_print_lock.decision``).

Rule order (binding, ``docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md``
build order step 5, refined by this increment's dispatch brief):

1. the trial-day latch already reports this station-day consumed ->
   ``trial_day_consumed``.
2. the traded instrument's fee coefficient does not equal
   ``config.required_fee_coefficient`` -> ``fee_schedule_mismatch`` (BE and
   the paid fee must never diverge silently from the archive selector, which
   was computed at ``FEE_THETA_FOR_BE``).
3. no ``RunningMax`` yet, or its staleness exceeds
   ``config.stale_observation_minutes`` -> ``observation_unavailable``.
4. ``RunningMax.spans(ladder)`` -- the observation interval cannot be
   resolved to one rung -> ``observation_ambiguous`` (never rounded, never
   midpointed -- A13 (spec rev2 §1b)).
5. the CURRENT rung is whichever ladder rung contains the whole
   ``[lower_f, upper_f]`` interval (well-defined once step 4 has passed).
   This step never refuses on its own; it only names the rung a ``Take``
   reports.
6. the ``(width_code, m_code)`` pair the caller passed is not a LEGAL CELL
   -> ``illegal_cell``. Legal iff ``(width_code == 0 AND m_code == 0)`` OR
   ``width_code == 1`` -- ``width_code == 2`` (``open_lower``) is NEVER
   legal, and ``m_code == 1`` is legal ONLY paired with ``width_code == 0``
   (blueprint step 6; see ``archive_table.py``'s header for the encoding).
   This check is ENFORCED here, not merely documented as the caller's
   responsibility (L-22: a safety exclusion must be unforgeable, not
   offered) -- it runs BEFORE the table lookup (step 8) precisely because a
   cell existing in the frozen table is never sufficient on its own: several
   out-of-policy keys (e.g. ``width_code=0, m_code=1``) ARE populated in the
   table (measured, but never intended for live use) and would otherwise
   silently reach ``Take``.
7. the quote is not executable (``executable_ask_lower < ask <
   executable_ask_upper`` and ``size >= minimum_displayed_size``, both
   strict on price) -> ``not_executable``.
8. the frozen table has no defined cell at
   ``(station, season, hour_lst, width_code, m_code)`` -> ``p_hold_undefined``
   (an under-powered cell is undefined, never the worst cell -- see
   ``archive_table.py``'s header).
9. ``p_hold_lower`` does not clear the break-even price (``ask`` plus the
   venue fee on that ask) -> ``edge_below_break_even``; otherwise ``Take``.

NO side only: after the shared gates above and the NO book's own
executability check, and before ``P_HOLD_UPPER`` is read, a closed
``config.no_side_calibration_gate_cleared`` (the default) refuses
``no_side_calibration_unsafe``. The YES side does not read that flag.
A thin NO book still refuses ``not_executable`` first.

Receipt gating (blueprint amendment, "Receipt gating is Seam A-2's
contract") is NOT re-derived here: ``RunningMax.value_at(now_ns)`` already
excludes any row with ``received_at_ns > now_ns``
(``breezy.strategy.weather_common.running_extreme``), so as long as the
caller builds ``running_max`` and ``now_ns`` from the SAME instant a quote
is priced against, a quote can never be priced ahead of the observation that
sets ``running_max``.

Legal-cell derivation (``season``/``hour_lst``) is the CALLER's
responsibility (step 6 of the caller's own wiring, gated on Seam B) -- this
module does not re-derive ``season``/``hour_lst`` from the clock or
``climate_day``. But WHICH ``(width_code, m_code)`` pairs are legal to trade
is enforced here, in step 6 of the rule order above, not merely documented
as a caller obligation -- see that step for the binding rule and why (L-22).

One trial per station-day is the CALLER's latch (``trial_day_latch.py``):
this module is pure and stateless, so ``Take`` is not itself a commit -- the
caller must durably ``consume`` the trial day before treating a ``Take`` as
final, and must never re-invoke this function for the same station-day once
consumed (which ``latch_consumed=True`` on the NEXT call would refuse
anyway, defence in depth, not the primary mechanism).

The fee formula -- and why it is NOT imported from ``adapters``
-----------------------------------------------------------------
The venue fee is ``theta * ask * (1 - ask)``, banker's-rounded
(``ROUND_HALF_EVEN``) to the cent -- pinned by
``tests/unit/test_polymarket_us_fee_model.py::
test_fee_model_pins_theta_times_contracts_times_price_times_one_minus_price``
(the formula) and ``::test_rounding_is_the_venue_documented_bankers_rounding_
to_the_cent`` (the rounding mode), both against
``breezy.adapters.polymarket_us.fees.polymarket_us_fee``/
``PolymarketUSFeeModel``. This module does not import that function: it
takes ``nautilus_trader`` ``Instrument``/``Quantity``/``Price``/``Money``
objects, and this module's contract is "no Nautilus import" (a stricter bar
than the layers-contract's `strategy` -> `adapters` direction, which would
otherwise permit it). ``_fee`` below reimplements the one-contract
(``quantity=1``, pinned by ``config.order_quantity``) special case of that
same formula and rounding rule against a bare ``Decimal`` ask, so a change
to the venue formula or rounding mode must be caught by re-deriving this
module's worked-example test against the cited adapter tests, not by a
silent drift between two copies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from breezy.strategy.current_rung_hold.archive_table import P_HOLD_LOWER, P_HOLD_UPPER
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.weather_common.running_extreme import RunningMax

__all__ = [
    "REFUSAL_REASONS",
    "Decision",
    "DecisionInputs",
    "Refuse",
    "Take",
    "evaluate_decision",
    "is_legal_cell",
    "no_leg_executable",
]

#: The closed set of refusal reasons this module can emit. Widening this set
#: is a change to every counter/latch that reads it -- see
#: ``breezy.strategy.weather_common.risk.COUNTED_REFUSAL_REASONS`` and
#: ``trial_day_latch.py``'s own closed reason set.
REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "observation_unavailable",
        "observation_ambiguous",
        "fee_schedule_mismatch",
        "trial_day_consumed",
        "illegal_cell",
        "not_executable",
        "p_hold_undefined",
        "edge_below_break_even",
        # Strategy-layer reason (``strategy.py``, build order step 6): a
        # quote arriving outside the pinned ``[12:00,17:00)`` LST decision
        # window. NOT emitted by ``evaluate_decision`` itself (the window
        # check runs in the caller, before this function is ever invoked for
        # that quote) -- widened here, not emitted here, so the trial-day
        # latch's closed reason set and the shared refusal vocabulary stay
        # ONE set across both layers, exactly as ``observation_ambiguous``
        # already does for ``RiskManager``.
        "outside_decision_window",
        # Strategy-layer reason (``strategy.py``'s ``on_start``): a
        # configured instrument id absent from ``self.cache`` at start-up
        # (L-23: ~9% of station-days never listed, and the live instrument
        # provider may lag the catalog). NOT emitted by ``evaluate_decision``
        # -- widened here, same shape as ``outside_decision_window``, so the
        # trial-day latch's closed reason set stays ONE set with the shared
        # refusal vocabulary.
        "instrument_unresolved",
        # AUD-01a: emitted by ``_evaluate_no_side`` while
        # ``no_side_calibration_gate_cleared`` is false, before
        # ``P_HOLD_UPPER`` is read. Not a structural halt -- a closed gate
        # is the intended state, not a page.
        "no_side_calibration_unsafe",
    }
)

#: Rev 3 delta (2026-09-04): the stale bound is computed from integer
#: MINUTES, never a repeating float hours value (``50/60`` is not dyadic;
#: unlike the retired ``0.75`` it cannot be safely multiplied into a
#: nanosecond bound with ``int(hours * 3.6e12)``).
_NS_PER_MINUTE: Final[int] = 60_000_000_000
_CENT: Final[Decimal] = Decimal("0.01")
_ONE: Final[Decimal] = Decimal(1)

#: Closed-closed rung bounds, exactly `WeatherBucketFacts.lower_f`/`upper_f`'s
#: shape -- either side `None` marks an open (unbounded) tail rung.
RungBounds = tuple[int | None, int | None]

#: The only two legal `side` values on `DecisionInputs`/`Take` (S3 fix-first
#: review finding 1). `Literal["yes", "no"]` is a static hint only -- it does
#: not stop `side="Yes"`/`None`/a typo reaching either dataclass at runtime,
#: so both validate against this set in `__post_init__`, raising BEFORE any
#: gate in `evaluate_decision` runs.
_VALID_SIDES: Final[frozenset[str]] = frozenset({"yes", "no"})


def _assert_valid_side(side: object) -> None:
    if side not in _VALID_SIDES:
        raise ValueError(f"side must be one of {sorted(_VALID_SIDES)!r}, was {side!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionInputs:
    """Every fact :func:`evaluate_decision` needs, passed in by the caller.

    ``ladder`` is the FULL venue ladder for this market (every rung, closed
    bounds, `WeatherBucketFacts.lower_f`/`upper_f` order-independent) -- it
    is what :meth:`RunningMax.spans` checks ambiguity against and what the
    CURRENT rung (the ``Take.rung`` a taken decision reports) is resolved
    from. ``season``/``hour_lst``/``width_code``/``m_code`` are the frozen
    table's lookup key parts for THIS station/day/hour/rung, computed by the
    caller -- see the module docstring's "Legal-cell derivation" note.

    ``side``/``bid``/``bid_size`` are additive (S3, plan
    ``NO_SIDE_EDGE_2026-09-14.md``): every existing keyword-argument
    construction defaults ``side="yes"`` and is unaffected. ``ask``/``size``
    stay the YES-ask executable inputs, used only when ``side == "yes"``.
    For ``side == "no"``, ``bid`` is the best YES bid price and ``bid_size``
    is the size displayed at it (both in the SAME contracts unit as
    ``config.minimum_displayed_size`` and ``config.order_quantity`` --
    N2-11: never dollar notional). The NO price ``NO_ask = 1 - bid`` and its
    fee/break-even are computed inside :func:`evaluate_decision`, never by
    the caller, so the ``Decimal``-only inversion stays in one place.
    """

    station: str
    climate_day: date
    now_ns: int
    ladder: Sequence[RungBounds]
    fee_coefficient: Decimal
    ask: Decimal
    size: int
    running_max: RunningMax | None
    staleness_ns: int | None
    config: CurrentRungHoldConfig
    season: str
    hour_lst: int
    width_code: int
    m_code: int
    latch_consumed: bool
    side: Literal["yes", "no"] = "yes"
    bid: Decimal | None = None
    bid_size: Decimal | None = None

    def __post_init__(self) -> None:
        _assert_valid_side(self.side)


@dataclass(frozen=True, slots=True)
class Refuse:
    """A refused decision. ``reason`` is always a member of :data:`REFUSAL_REASONS`.

    ``p_bound``/``break_even`` are additive (GAP fix 2026-09-15, offer-tape
    postmortem observability): unset (``None``) for every reason except
    ``edge_below_break_even``, where :func:`_finalize_take` now populates
    the SAME two numbers it already computed to make that refusal --
    exposed here purely so a caller (the offer tape) can log WHY the edge
    failed, never changing this class's truthiness or `evaluate_decision`'s
    branching (L-34/D3: observability only).
    """

    reason: str
    p_bound: Decimal | None = None
    break_even: Decimal | None = None

    def __post_init__(self) -> None:
        if self.reason not in REFUSAL_REASONS:
            raise ValueError(
                f"reason must be one of {sorted(REFUSAL_REASONS)!r}, was {self.reason!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class Take:
    """A taken decision: buy ``quantity`` at ``limit_price`` (always a BUY --
    a NO take buys the NO leg instrument, never a short of the YES one).

    ``side``/``p_bound`` are additive (S3): every existing keyword-argument
    construction defaults ``side="yes"`` and leaves ``p_bound`` unset, so a
    YES ``Take`` is byte-identical to before this slice. ``p_hold_lower``
    keeps its exact YES meaning and is NEVER repurposed for a NO take; the
    side-generic edge bound (``p_hold_lower`` for YES, ``p_miss_lower`` for
    NO) is carried separately as ``p_bound`` -- read that field, not
    ``p_hold_lower``, when the side is not known statically.
    """

    quantity: int
    limit_price: Decimal
    p_hold_lower: Decimal
    break_even: Decimal
    rung: RungBounds
    side: Literal["yes", "no"] = "yes"
    p_bound: Decimal | None = None

    def __post_init__(self) -> None:
        _assert_valid_side(self.side)


Decision = Refuse | Take


def _rung_index(value: int, ladder: Sequence[RungBounds]) -> int | None:
    """The index of the (single) rung in ``ladder`` containing ``value``, closed both ends.

    Mirrors ``RunningMax.spans``'s own private ``_rung_index`` exactly, so
    the rung this module names on a ``Take`` is the SAME rung ``spans``
    already proved is the unique containing one.
    """
    for index, (rung_lower, rung_upper) in enumerate(ladder):
        if rung_lower is not None and value < rung_lower:
            continue
        if rung_upper is not None and value > rung_upper:
            continue
        return index
    return None


def _is_legal_cell(width_code: int, m_code: int) -> bool:
    """The binding LEGAL CELL rule (module docstring step 6).

    ``width_code == 2`` (``open_lower``) is NEVER legal. ``m_code == 1`` is
    legal ONLY paired with ``width_code == 0`` (interior_2F) -- never with
    ``width_code == 1`` alone deciding it, since the open tails fix
    ``m_code`` at 0 and have no margin axis (``archive_table.py``'s header).
    Enforced here so a caller cannot pass an out-of-policy key and reach a
    ``Take`` merely because the frozen table happens to have that cell
    populated (L-22: unforgeable, not offered).
    """
    return (width_code == 0 and m_code == 0) or width_code == 1


is_legal_cell = _is_legal_cell


def _fee(ask: Decimal, fee_coefficient: Decimal) -> Decimal:
    """``theta * ask * (1 - ask)`` for ONE contract, banker's-rounded to the cent.

    See the module docstring's "The fee formula" section for the two adapter
    tests this must never silently drift from.
    """
    exact = fee_coefficient * ask * (_ONE - ask)
    return exact.quantize(_CENT, rounding=ROUND_HALF_EVEN)


#: Public alias for the LIVE take rule's fee, same pattern as ``is_legal_cell``
#: above. Offline studies that must price the identical quantity the live rule
#: prices (WP-7's cheap screen) import THIS rather than restating
#: ``theta * p * (1 - p)``: a second copy of the formula is how a study's hurdle
#: and the live hurdle drift apart. No behaviour change -- it is ``_fee``.
fee_on_ask = _fee


def evaluate_decision(inputs: DecisionInputs) -> Decision:
    """Evaluate one snapshot against the frozen rule order (module docstring)."""
    if inputs.latch_consumed:
        return Refuse("trial_day_consumed")

    if inputs.fee_coefficient != inputs.config.required_fee_coefficient:
        return Refuse("fee_schedule_mismatch")

    running_max = inputs.running_max
    stale_bound_ns = inputs.config.stale_observation_minutes * _NS_PER_MINUTE
    if (
        running_max is None
        or inputs.staleness_ns is None
        or inputs.staleness_ns > stale_bound_ns
    ):
        return Refuse("observation_unavailable")

    if running_max.spans(inputs.ladder):
        return Refuse("observation_ambiguous")

    rung_index = _rung_index(running_max.lower_f, inputs.ladder)
    assert rung_index is not None  # `spans` already proved containment.
    rung: RungBounds = inputs.ladder[rung_index]

    if not _is_legal_cell(inputs.width_code, inputs.m_code):
        return Refuse("illegal_cell")

    key = (inputs.station, inputs.season, inputs.hour_lst, inputs.width_code, inputs.m_code)

    # Exhaustive dispatch on the two validated `side` values (S3 fix-first
    # review finding 1) -- `DecisionInputs.__post_init__` already refused any
    # other value at construction, so this `else` is defence in depth, never
    # reachable in practice.
    if inputs.side == "yes":
        p_hold_lower = P_HOLD_LOWER.get(key)
        return _finalize_take(
            inputs,
            price=inputs.ask,
            size=inputs.size,
            p_bound=p_hold_lower,
            rung=rung,
            side="yes",
        )
    elif inputs.side == "no":
        return _evaluate_no_side(inputs, key=key, rung=rung)
    else:  # pragma: no cover - unreachable, `__post_init__` already validated `side`.
        raise ValueError(f"unreachable: side={inputs.side!r}")


def _is_executable(price: Decimal, size: Decimal | int, config: CurrentRungHoldConfig) -> bool:
    """The shared executable-band+size predicate, used by BOTH sides.

    Strictly between ``executable_ask_lower``/``executable_ask_upper``
    (exclusive) and at least ``minimum_displayed_size`` (inclusive).
    """
    return (
        config.executable_ask_lower < price < config.executable_ask_upper
        and size >= config.minimum_displayed_size
    )


def _finalize_take(
    inputs: DecisionInputs,
    *,
    price: Decimal,
    size: Decimal | int,
    p_bound: Decimal | None,
    rung: RungBounds,
    side: Literal["yes", "no"],
) -> Decision:
    """Shared executable+lookup+break-even test for BOTH sides.

    ``price``/``size`` are already side-resolved by the caller (YES:
    ``ask``/``size``; NO: ``1 - bid``/``bid_size``) and ``p_bound`` is
    already the side's own estimand (``P_HOLD_LOWER`` for YES,
    ``1 - P_HOLD_UPPER`` for NO) -- this function only runs the shared rule
    order (executable, then defined, then break-even), never any inversion.
    """
    if not _is_executable(price, size, inputs.config):
        return Refuse("not_executable")

    if p_bound is None:
        return Refuse("p_hold_undefined")

    break_even = price + _fee(price, inputs.fee_coefficient)
    if not (p_bound > break_even):
        return Refuse("edge_below_break_even", p_bound=p_bound, break_even=break_even)

    if side == "yes":
        return Take(
            quantity=inputs.config.order_quantity,
            limit_price=price,
            p_hold_lower=p_bound,
            break_even=break_even,
            rung=rung,
        )
    return Take(
        quantity=inputs.config.order_quantity,
        limit_price=price,
        p_hold_lower=p_bound,
        break_even=break_even,
        rung=rung,
        side="no",
        p_bound=p_bound,
    )


def no_leg_executable(
    bid: Decimal | None, bid_size: Decimal | int | None, config: CurrentRungHoldConfig
) -> bool:
    """Whether the NO leg (``1 - bid``) is independently executable.

    F-1a (plan ``STALL_FOLLOWUPS_F1_F4_2026-09-24.md``): single-sources the
    SAME predicate ``_evaluate_no_side`` below runs, so the caller's
    NO-only hunt gate and the armed NO evaluation can never diverge --
    exactly the executable-band-plus-size test ``_is_executable`` already
    runs, on the NO leg's own complement price, with no independent copy.
    """
    return (
        bid is not None
        and bid_size is not None
        and _is_executable(_ONE - bid, bid_size, config)
    )


def _evaluate_no_side(
    inputs: DecisionInputs, *, key: tuple[str, str, int, int, int], rung: RungBounds
) -> Decision:
    """The NO-side mirror of the take test (plan §2, S3, N2-11).

    ``NO_ask = 1 - bid`` is the ONLY inversion, computed here in ``Decimal``
    and nowhere else. The executable gate reads the BID ladder's top-of-book
    size in the SAME contracts unit as ``config.minimum_displayed_size`` --
    never dollar notional (N2-11): a 0.1-contract bid against a 1-contract
    ``order_quantity`` correctly refuses.

    After that executability check, a closed
    ``config.no_side_calibration_gate_cleared`` refuses
    ``no_side_calibration_unsafe`` and returns before ``P_HOLD_UPPER`` is
    read. The YES path never reaches this function.
    """
    if inputs.bid is None or inputs.bid_size is None:
        return Refuse("not_executable")

    no_ask = _ONE - inputs.bid
    # Same executable predicate as ``_finalize_take`` (``_is_executable``),
    # run HERE so a thin book keeps ``not_executable`` and the unsafe table
    # is never read while the calibration gate is closed. ``_finalize_take``
    # calls the same helper again on the armed path. Routed through the
    # public ``no_leg_executable`` (F-1a) so this stays the ONE predicate a
    # caller's NO-only hunt gate also uses -- no behaviour change.
    if not no_leg_executable(inputs.bid, inputs.bid_size, inputs.config):
        return Refuse("not_executable")

    if not inputs.config.no_side_calibration_gate_cleared:
        return Refuse("no_side_calibration_unsafe")

    p_hold_upper = P_HOLD_UPPER.get(key)
    p_miss_lower = None if p_hold_upper is None else _ONE - p_hold_upper
    return _finalize_take(
        inputs,
        price=no_ask,
        size=inputs.bid_size,
        p_bound=p_miss_lower,
        rung=rung,
        side="no",
    )
