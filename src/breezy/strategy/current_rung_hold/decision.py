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
   ``config.stale_observation_hours`` -> ``observation_unavailable``.
4. ``RunningMax.spans(ladder)`` -- the observation interval cannot be
   resolved to one rung -> ``observation_ambiguous`` (never rounded, never
   midpointed -- L-17).
5. the CURRENT rung is whichever ladder rung contains the whole
   ``[lower_f, upper_f]`` interval (well-defined once step 4 has passed).
   This step never refuses on its own; it only names the rung a ``Take``
   reports.
6. the quote is not executable (``executable_ask_lower < ask <
   executable_ask_upper`` and ``size >= minimum_displayed_size``, both
   strict on price) -> ``not_executable``.
7. the frozen table has no defined cell at
   ``(station, season, hour_lst, width_code, m_code)`` -> ``p_hold_undefined``
   (an under-powered cell is undefined, never the worst cell -- see
   ``archive_table.py``'s header).
8. ``p_hold_lower`` does not clear the break-even price (``ask`` plus the
   venue fee on that ask) -> ``edge_below_break_even``; otherwise ``Take``.

Receipt gating (blueprint amendment, "Receipt gating is Seam A-2's
contract") is NOT re-derived here: ``RunningMax.value_at(now_ns)`` already
excludes any row with ``received_at_ns > now_ns``
(``breezy.strategy.weather_common.running_extreme``), so as long as the
caller builds ``running_max`` and ``now_ns`` from the SAME instant a quote
is priced against, a quote can never be priced ahead of the observation that
sets ``running_max``.

Legal-cell derivation (``season``/``hour_lst``/``width_code``/``m_code``) is
the CALLER's responsibility (step 6, gated on Seam B) -- this module only
looks the key up; it does not re-derive or second-guess it. See the
blueprint's "taken test... legal cell" note for what the caller must never
pass (``m_code == 1`` or ``open_lower`` outside their measured, intended
use).

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
from typing import Final

from breezy.strategy.current_rung_hold.archive_table import P_HOLD_LOWER
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.weather_common.running_extreme import RunningMax

__all__ = [
    "REFUSAL_REASONS",
    "Decision",
    "DecisionInputs",
    "Refuse",
    "Take",
    "evaluate_decision",
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
        "not_executable",
        "p_hold_undefined",
        "edge_below_break_even",
    }
)

_NS_PER_HOUR: Final[int] = 3_600_000_000_000
_CENT: Final[Decimal] = Decimal("0.01")
_ONE: Final[Decimal] = Decimal(1)

#: Closed-closed rung bounds, exactly `WeatherBucketFacts.lower_f`/`upper_f`'s
#: shape -- either side `None` marks an open (unbounded) tail rung.
RungBounds = tuple[int | None, int | None]


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


@dataclass(frozen=True, slots=True)
class Refuse:
    """A refused decision. ``reason`` is always a member of :data:`REFUSAL_REASONS`."""

    reason: str

    def __post_init__(self) -> None:
        if self.reason not in REFUSAL_REASONS:
            raise ValueError(
                f"reason must be one of {sorted(REFUSAL_REASONS)!r}, was {self.reason!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class Take:
    """A taken decision: buy ``quantity`` at ``limit_price`` (LONG_YES only)."""

    quantity: int
    limit_price: Decimal
    p_hold_lower: Decimal
    break_even: Decimal
    rung: RungBounds


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


def _fee(ask: Decimal, fee_coefficient: Decimal) -> Decimal:
    """``theta * ask * (1 - ask)`` for ONE contract, banker's-rounded to the cent.

    See the module docstring's "The fee formula" section for the two adapter
    tests this must never silently drift from.
    """
    exact = fee_coefficient * ask * (_ONE - ask)
    return exact.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def evaluate_decision(inputs: DecisionInputs) -> Decision:
    """Evaluate one snapshot against the frozen rule order (module docstring)."""
    if inputs.latch_consumed:
        return Refuse("trial_day_consumed")

    if inputs.fee_coefficient != inputs.config.required_fee_coefficient:
        return Refuse("fee_schedule_mismatch")

    running_max = inputs.running_max
    stale_bound_ns = int(inputs.config.stale_observation_hours * _NS_PER_HOUR)
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

    executable = (
        inputs.config.executable_ask_lower < inputs.ask < inputs.config.executable_ask_upper
        and inputs.size >= inputs.config.minimum_displayed_size
    )
    if not executable:
        return Refuse("not_executable")

    key = (inputs.station, inputs.season, inputs.hour_lst, inputs.width_code, inputs.m_code)
    p_hold_lower = P_HOLD_LOWER.get(key)
    if p_hold_lower is None:
        return Refuse("p_hold_undefined")

    break_even = inputs.ask + _fee(inputs.ask, inputs.fee_coefficient)
    if not (p_hold_lower > break_even):
        return Refuse("edge_below_break_even")

    return Take(
        quantity=inputs.config.order_quantity,
        limit_price=inputs.ask,
        p_hold_lower=p_hold_lower,
        break_even=break_even,
        rung=rung,
    )
