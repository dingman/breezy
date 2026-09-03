"""Pure helper logic for ``run_weather_strategy_backtests.py``.

Everything here is deliberately free of Nautilus engine construction, catalog
I/O, and strategy wiring, so it can be unit tested without a `BacktestEngine`
or a live `ParquetDataCatalog`. Three areas only, matching what the runner
actually needs to get right before it ever touches the harness:

* **Instrument selection** -- which tape instruments carry enough data to back
  a run at all (:func:`select_tradable_instrument_ids`).
* **Settlement-price mapping** -- bucket containment turned into the
  ``settlement_prices`` mapping ``BreezyBacktestConfig`` requires
  (:func:`settlement_prices_for_scenario`).
* **Scenario construction** -- the REAL-vs-ASSUMED settlement sweep
  (:func:`build_settlement_scenarios`).

:func:`hours_from_now_until` is the one small piece of arithmetic the runner's
synthetic ``ForecastSource`` needs to make ``horizon_hours`` a LIVE quantity
(computed from the current backtest clock, not frozen at forecast-issuance
time) -- see ``breezy.strategy.weather_common.forecast_source`` for why that
field is load-bearing.

ANTI-LOOKAHEAD BY CONSTRUCTION
-------------------------------
:func:`build_settlement_scenarios` never reads a forecast value and
:func:`settlement_prices_for_scenario` never reads one either -- the forecast
this runner injects is a constant, independent of every station's real or
swept reading, is never a parameter of either function below, and is wired in
only by the runner script itself.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from breezy.domain.weather_bucket_facts import WeatherBucketFacts

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.cli_settlement_print_lock.config import (
        CliSettlementPrintLockConfig,
    )
    from breezy.strategy.cli_settlement_print_lock.decision import CliPrintObservation
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import MarketQuote

__all__ = [
    "PRINT_LOCK_GATES",
    "PROVENANCE_ASSUMED",
    "PROVENANCE_REAL",
    "STATUS_COMPLETED",
    "STATUS_COMPLETED_ALL_REFUSED",
    "UNCOUNTED_GATES",
    "GateLadderDriftError",
    "PrintLockGateRecord",
    "Scenario",
    "build_settlement_scenarios",
    "derive_completion_status",
    "first_blocking_gate",
    "hours_from_now_until",
    "latest_publication_at_or_before",
    "select_book_backed_instrument_ids",
    "select_tradable_instrument_ids",
    "settlement_prices_for_scenario",
]

#: A station's reading in a `Scenario` was read from the live weather catalog.
PROVENANCE_REAL = "REAL"
#: A station's reading in a `Scenario` is a sensitivity value chosen by this
#: script -- never derived from any settlement truth or from the forecast.
PROVENANCE_ASSUMED = "ASSUMED"

#: A run submitted zero orders and recorded zero risk/decision refusals: it
#: saw no tradable opportunity. Indistinguishable, without more, from a run
#: whose entire signal set was gagged -- see :func:`derive_completion_status`.
STATUS_COMPLETED = "COMPLETED"
#: A run submitted zero orders BUT its strategy recorded at least one
#: refusal (e.g. `SHORTS_DISABLED`, see
#: `breezy.strategy.weather_common.refusals`): its entire signal set was
#: refused, not merely absent. Distinct from :data:`STATUS_COMPLETED` so a
#: gagged strategy never reports as an unqualified clean completion.
STATUS_COMPLETED_ALL_REFUSED = "COMPLETED_ALL_REFUSED"


@dataclass(frozen=True, slots=True)
class Scenario:
    """One settlement-outcome hypothesis to run every strategy against.

    Parameters
    ----------
    name : str
        Unique, stable across a run -- used as the JSON/report key.
    observed_by_station : Mapping[str, int]
        Station code (e.g. ``"NYC"``) -> whole-degree Fahrenheit high used to
        derive this scenario's ``settlement_prices``.
    provenance_by_station : Mapping[str, str]
        Same keys as ``observed_by_station``; each value is
        :data:`PROVENANCE_REAL` or :data:`PROVENANCE_ASSUMED`, so a report can
        never present a swept number as measured fact.

    """

    name: str
    observed_by_station: Mapping[str, int]
    provenance_by_station: Mapping[str, str]


def select_tradable_instrument_ids(
    depth_counts: Mapping[str, int],
    quote_counts: Mapping[str, int],
) -> list[str]:
    """Instrument ids carrying at least one depth row AND one quote row.

    An instrument with only one of the two record types cannot back a run
    under ``book_type=BookType.L2_MBP`` (``breezy.runtime.backtest_harness``):
    Nautilus's own ``InvalidConfiguration: No order book data found`` guard
    fires per instrument for a quote-only leg. Sorted so the result is
    deterministic regardless of the input mappings' iteration order.
    """
    ids = {
        instrument_id
        for instrument_id, count in depth_counts.items()
        if count > 0 and quote_counts.get(instrument_id, 0) > 0
    }
    return sorted(ids)


def settlement_prices_for_scenario[InstrumentIdT](
    facts_by_instrument_id: Mapping[InstrumentIdT, WeatherBucketFacts],
    observed_by_station: Mapping[str, int],
) -> dict[InstrumentIdT, float]:
    """Map every instrument to the settlement endpoint its bucket resolves to.

    ``1.0`` if ``facts.contains(observed_by_station[facts.settlement_station])``,
    else ``0.0`` -- the only two values
    ``breezy.runtime.backtest_harness.assert_settlement_invariants`` accepts.

    Raises
    ------
    KeyError
        If any instrument's ``settlement_station`` has no reading in
        ``observed_by_station``. Fail-closed rather than skipping that
        instrument: a partial mapping would silently trip the harness's
        COVERAGE invariant instead of failing here, with a much less specific
        message.

    """
    prices: dict[InstrumentIdT, float] = {}
    for instrument_id, facts in facts_by_instrument_id.items():
        if facts.settlement_station not in observed_by_station:
            raise KeyError(
                f"no observed reading for station {facts.settlement_station!r} "
                f"(instrument {instrument_id!r}); every instrument's station must "
                f"appear in `observed_by_station`",
            )
        reading = observed_by_station[facts.settlement_station]
        prices[instrument_id] = 1.0 if facts.contains(reading) else 0.0
    return prices


def build_settlement_scenarios(
    *,
    real_observed_by_station: Mapping[str, int],
    sweep_by_station: Mapping[str, Sequence[int]],
) -> list[Scenario]:
    """The full settlement-outcome sweep: one REAL scenario, then per-station sweeps.

    The first scenario, ``"primary_real_preliminary"``, uses
    ``real_observed_by_station`` for every station -- the one scenario that is
    not fabricated. Every other scenario varies exactly ONE station's reading
    to an :data:`PROVENANCE_ASSUMED` candidate from ``sweep_by_station`` while
    holding every other station at its REAL reading, so a PnL difference
    between two scenarios is attributable to the one station that changed.

    Parameters
    ----------
    real_observed_by_station : Mapping[str, int]
        Every station this run touches, at its REAL (measured) reading.
    sweep_by_station : Mapping[str, Sequence[int]]
        Station -> candidate readings to sweep. A station with an empty
        sequence contributes no extra scenarios.

    Raises
    ------
    ValueError
        If ``sweep_by_station`` names a station absent from
        ``real_observed_by_station`` -- there is nothing to hold fixed for the
        other scenarios in that case.

    """
    unknown = sorted(set(sweep_by_station) - set(real_observed_by_station))
    if unknown:
        raise ValueError(
            f"sweep_by_station names station(s) with no real reading to hold "
            f"fixed: {unknown}",
        )

    scenarios = [
        Scenario(
            name="primary_real_preliminary",
            observed_by_station=dict(real_observed_by_station),
            provenance_by_station=dict.fromkeys(real_observed_by_station, PROVENANCE_REAL),
        ),
    ]
    for station in sorted(sweep_by_station):
        for candidate in sweep_by_station[station]:
            observed = dict(real_observed_by_station)
            observed[station] = candidate
            provenance = dict.fromkeys(real_observed_by_station, PROVENANCE_REAL)
            provenance[station] = PROVENANCE_ASSUMED
            scenarios.append(
                Scenario(
                    name=f"sweep_{station.lower()}_{candidate}f",
                    observed_by_station=observed,
                    provenance_by_station=provenance,
                ),
            )
    return scenarios


def derive_completion_status(
    *,
    orders_submitted: int,
    refusal_counts: Mapping[str, int],
) -> str:
    """:data:`STATUS_COMPLETED_ALL_REFUSED` iff the run traded nothing AND was refused.

    A run that submits zero orders is ambiguous on its own: it may simply
    have seen no opportunity (an efficient market), or every signal it formed
    may have been refused by a risk/decision gate (e.g. `SHORTS_DISABLED`
    under `allow_short=False`) -- see
    `breezy.strategy.weather_common.refusals.RefusalCounter`. Those are
    different facts and must not report identically.

    ``refusal_counts`` is summed across every reason rather than checked for
    a specific key, so any reason the counter records (not only
    `SHORTS_DISABLED`) counts as evidence the run was gagged, not merely
    unopportune. A run with `orders_submitted > 0` is always
    :data:`STATUS_COMPLETED`, even if some of its signals were separately
    refused -- only a wholly-gagged run (zero orders) gets the distinct
    status.
    """
    if orders_submitted == 0 and sum(refusal_counts.values()) > 0:
        return STATUS_COMPLETED_ALL_REFUSED
    return STATUS_COMPLETED


def hours_from_now_until(now: dt.datetime, deadline: dt.datetime) -> float:
    """Hours from ``now`` to ``deadline``; negative once ``now`` is past it.

    Both arguments must be timezone-aware. This is the one place the synthetic
    ``ForecastSource`` computes ``ForecastSnapshot.horizon_hours`` LIVE (as of
    the backtest clock's current instant), rather than freezing it at forecast
    issuance -- see ``breezy.strategy.weather_common.forecast_source`` for why
    a frozen value would be wrong.

    T-10: named with the argument order spelled out (``now`` first, then
    ``deadline``) so it can never be confused with
    ``breezy.strategy.weather_common.models.hours_until(later, now)``, which
    takes the SAME two kinds of value in the OPPOSITE order. The two are not
    interchangeable: swapping them silently flips the sign of the horizon.

    Raises
    ------
    ValueError
        If either argument is a naive `datetime`.

    """
    if now.tzinfo is None or deadline.tzinfo is None:
        raise ValueError("both `now` and `deadline` must be timezone-aware")
    return (deadline - now).total_seconds() / 3600.0


def latest_publication_at_or_before(
    publications: Sequence[tuple[dt.datetime, float]],
    now: dt.datetime,
) -> tuple[dt.datetime, float] | None:
    """The `(published_at, expected_high_f)` with the greatest `published_at` <= `now`.

    Models a forecast source that can only ever report the latest publication
    that has actually happened as of `now` -- never a future one, and never
    interpolated between two. `publications` need not be pre-sorted.

    Returns
    -------
    tuple[dt.datetime, float] | None
        `None` if `now` precedes every publication (nothing has been issued
        yet) or `publications` is empty.

    """
    applicable = [p for p in publications if p[0] <= now]
    if not applicable:
        return None
    return max(applicable, key=lambda p: p[0])


# ---------------------------------------------------------------------------
# BL-19 s8.5 -- the per-station-day decision-input record
# ---------------------------------------------------------------------------
#
# `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s8.5 enumerates
# four distinguishable nulls for `cli_settlement_print_lock`, and says that TWO
# of them are INVISIBLE at the `RefusalCounter`:
#
#   N0  no CLI final reached the strategy before the halt window   -> uncounted
#   N1  trigger fired; a PURE gate returned `None`                 -> uncounted
#   N2  signal formed; refused at the edge floor                   -> counted
#   N3  signal formed; no book / no ask / insufficient liquidity   -> counted
#
# A pre-signal `None` never reaches `RiskManager.evaluate_order` and so is
# never counted (`risk.py`; the same class as BL-10). At the counter, N1 is
# indistinguishable from N0, and "the market had no edge" is indistinguishable
# from "the mapping was wrong". **A null therefore proves nothing unless the
# decision INPUTS and the FIRST gate are recorded per station-day.**
#
# WHAT THIS IS NOT
# ----------------
# It computes NO trading result. There is no fill, no PnL and no ROI anywhere
# below -- those come only from the `BacktestEngine`. What it records is the
# set of INPUTS a decision was taken on, plus the identity of the first shipped
# predicate that said no.
#
# WHY IT IS EVIDENCE AND NOT A SECOND OPINION
# --------------------------------------------
# Every predicate consulted below is the SHIPPED one, imported from
# `breezy.strategy.cli_settlement_print_lock` -- `facts.applies_to`,
# `facts.contains`, `MEASURED_STATIONS`, `quote.implied_ask`, `venue_fee_prob`,
# `trade_cost_prob`, `worst_admissible_ask`, `cost_basis_anchor`. None is
# re-implemented. And `first_blocking_gate` CROSS-CHECKS its own verdict
# against the shipped `evaluate_instrument`: if the classifier and the strategy
# ever disagree about whether a decision forms, it RAISES
# (`GateLadderDriftError`) instead of reporting. A record that could silently
# describe a gate ladder the running strategy does not have would be worse
# than no record at all.

#: No gate stopped it: the shipped decision layer formed a `SignalDecision`.
#: Everything downstream of that (`_maybe_submit`, `RiskManager.evaluate_order`)
#: IS counted by the `RefusalCounter`, which is authoritative from here on.
GATE_NONE = "none"
#: Strategy-level, `_evaluate_and_act`: `hours_to_settlement <=
#: halt_hours_before_settlement`. Returns with NO refusal recorded. N0.
GATE_HALT_WINDOW = "halt_window"
#: Strategy-level: no depth cached for this instrument yet.
GATE_NO_QUOTE = "no_quote"
#: Strategy-level: no CLI print received for this instrument yet. N0.
GATE_NO_OBSERVATION = "no_observation"
GATE_APPLIES_TO = "applies_to"
GATE_LOOKAHEAD = "lookahead"
GATE_NOT_FINAL = "not_final"
GATE_SUPERSEDED = "superseded"
GATE_CORRECTION = "correction"
GATE_UNMEASURED_STATION = "unmeasured_station"
GATE_MEASURE_DISABLED = "measure_disabled"
GATE_NO_PRINTED_VALUE = "no_printed_value"
GATE_BUCKET_NOT_CONTAINING = "bucket_not_containing"
GATE_MIN_STABLE_PROB = "min_stable_prob"
GATE_NO_ASK = "no_ask"
GATE_DEGENERATE_ASK = "degenerate_ask"
GATE_NO_FEE_COEFFICIENT = "no_fee_coefficient"
GATE_EDGE_BELOW_MINIMUM = "edge_below_minimum"
GATE_QUANTITY_BELOW_ONE = "quantity_below_one"

#: Every gate identity, in the SHIPPED evaluation order. The order is part of
#: the contract: "the FIRST gate that stopped it" is only meaningful against a
#: ladder whose order matches the running strategy's.
PRINT_LOCK_GATES: tuple[str, ...] = (
    GATE_NO_QUOTE,
    GATE_NO_OBSERVATION,
    GATE_HALT_WINDOW,
    GATE_APPLIES_TO,
    GATE_LOOKAHEAD,
    GATE_NOT_FINAL,
    GATE_SUPERSEDED,
    GATE_CORRECTION,
    GATE_UNMEASURED_STATION,
    GATE_MEASURE_DISABLED,
    GATE_NO_PRINTED_VALUE,
    GATE_BUCKET_NOT_CONTAINING,
    GATE_MIN_STABLE_PROB,
    GATE_NO_ASK,
    GATE_DEGENERATE_ASK,
    GATE_NO_FEE_COEFFICIENT,
    GATE_EDGE_BELOW_MINIMUM,
    GATE_QUANTITY_BELOW_ONE,
    GATE_NONE,
)

#: The gates that are NOT visible at the `RefusalCounter` -- s8.5's N0/N1.
#: Reported alongside every record so a reader never has to remember which is
#: which.
UNCOUNTED_GATES: frozenset[str] = frozenset(PRINT_LOCK_GATES) - {GATE_NONE}


class GateLadderDriftError(RuntimeError):
    """The classifier and the SHIPPED decision function disagreed.

    Raised rather than logged. The record exists to make a null decodable; a
    record built from a gate ladder that no longer matches
    `cli_settlement_print_lock.decision.evaluate_instrument` would make a null
    decodable into the WRONG answer, which is strictly worse than refusing to
    answer.
    """


@dataclass(frozen=True, slots=True)
class PrintLockGateRecord:
    """One station-day/instrument decision-input record, per BL-19 s8.5.

    Persisted regardless of whether an order formed. Carries no fill, no PnL
    and no ROI: those are the engine's to report.
    """

    instrument_id: str
    station: str
    climate_day: dt.date
    #: The instrument's own `endDate` (`expiration_ns`), which is the deadline
    #: `cli_settlement_print_lock` measures `hours_to_settlement` against.
    deadline: dt.datetime
    #: The decision instant -- for a print-driven evaluation, the moment the
    #: CLI record reached the strategy.
    decided_at: dt.datetime
    cli_issued_at: dt.datetime
    hours_to_settlement: float
    printed_f: int | None
    is_final: bool
    correction_flag: bool
    is_superseded: bool
    bucket_lower_f: int | None
    bucket_upper_f: int | None
    bucket_contains_print: bool | None
    level0_ask: float | None
    level0_ask_size: float | None
    #: VWAP ask for the quantity the decision layer would have requested, walked
    #: over `MarketQuote.ask_ladder` with the SHIPPED
    #: `running_extreme_lock.decision._vwap_ask_for_quantity`. Equal to
    #: `level0_ask` when the quote carries no ladder.
    vwap_ask: float | None
    vwap_ask_filled_qty: float | None
    fee_coefficient: float | None
    fee_prob: float | None
    slippage_prob: float
    model_probability: float | None
    #: `model_p - ask - fee(ask) - slippage_prob`, from the SHIPPED cost
    #: functions.
    edge: float | None
    #: The same edge with `slippage_prob = 0`, so s8.5's "computed edge at
    #: slippage_prob in {0.000, 0.010}" is on the record and the threshold
    #: re-derives offline from a measured slippage figure.
    edge_at_zero_slippage: float | None
    quote_age_minutes: float | None
    #: The FIRST gate that stopped it, or `GATE_NONE`.
    gate: str
    decision_formed: bool
    #: `False` for every gate at or before the decision layer -- s8.5's N0/N1.
    counted_by_refusal_counter: bool

    def to_json(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "station": self.station,
            "climate_day": self.climate_day.isoformat(),
            "deadline": self.deadline.isoformat(),
            "decided_at": self.decided_at.isoformat(),
            "cli_issued_at": self.cli_issued_at.isoformat(),
            "hours_to_settlement": self.hours_to_settlement,
            "printed_f": self.printed_f,
            "is_final": self.is_final,
            "correction_flag": self.correction_flag,
            "is_superseded": self.is_superseded,
            "bucket_lower_f": self.bucket_lower_f,
            "bucket_upper_f": self.bucket_upper_f,
            "bucket_contains_print": self.bucket_contains_print,
            "level0_ask": self.level0_ask,
            "level0_ask_size": self.level0_ask_size,
            "vwap_ask": self.vwap_ask,
            "vwap_ask_filled_qty": self.vwap_ask_filled_qty,
            "fee_coefficient": self.fee_coefficient,
            "fee_prob": self.fee_prob,
            "slippage_prob": self.slippage_prob,
            "model_probability": self.model_probability,
            "edge": self.edge,
            "edge_at_zero_slippage": self.edge_at_zero_slippage,
            "quote_age_minutes": self.quote_age_minutes,
            "first_gate": self.gate,
            "decision_formed": self.decision_formed,
            "counted_by_refusal_counter": self.counted_by_refusal_counter,
        }


def select_book_backed_instrument_ids(depth_counts: Mapping[str, int]) -> list[str]:
    """Instrument ids carrying at least one ORDER-BOOK DEPTH row.

    The sibling of :func:`select_tradable_instrument_ids`, NOT a relaxation of
    it -- that rule stays exactly as it is, and is still the right one for the
    forecast strategies, which quote from `QuoteTick`.

    Why a depth-only rule is sound for `cli_settlement_print_lock`: its own
    module docstring states "A long-only taker needs an ASK and nothing else.
    An asks-only book ... is TRADED". Its only market-data handler is
    `on_order_book_depth`; it never reads a `QuoteTick`. And under
    `BookType.L2_MBP` the harness's `InvalidConfiguration: No order book data
    found` guard fires for a QUOTE-ONLY leg, which is the opposite shape.

    Why the distinction is load-bearing on the live capture rather than
    hypothetical: `parse_book_top` requires a best level on BOTH sides, so a
    market whose bid side has emptied records depth and **zero** `QuoteTick`s.
    That is the state of every terminal weather ladder, and applying the
    quote-AND-depth rule to it discards exactly the instruments the print-lock
    strategy exists to trade.
    """
    return sorted(iid for iid, count in depth_counts.items() if count > 0)


def first_blocking_gate(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    observation: CliPrintObservation,
    now: dt.datetime,
    deadline: dt.datetime,
    cfg: CliSettlementPrintLockConfig,
) -> PrintLockGateRecord:
    """Classify the FIRST shipped gate that stops this decision, and record its inputs.

    Replays the SHIPPED predicates in the SHIPPED order and then CROSS-CHECKS
    the verdict against the shipped
    :func:`~breezy.strategy.cli_settlement_print_lock.decision.evaluate_instrument`.

    Raises
    ------
    GateLadderDriftError
        If the classifier's verdict disagrees with the shipped decision
        function about whether a decision forms.

    """
    # Imported here, not at module scope: this module is loaded by the runner
    # AND by unit tests that do not otherwise need the strategy package.
    from breezy.strategy.cli_settlement_print_lock.decision import (
        MEASURED_STATIONS,
        cost_basis_anchor,
        evaluate_instrument,
        worst_admissible_ask,
    )
    from breezy.strategy.cli_settlement_print_lock.strategy import (
        MEASURED_P_STABLE_WILSON_LOWER,
    )
    from breezy.strategy.weather_common.costs import (
        NoExecutableDepthError,
        depth_aware_trade_cost_prob,
        venue_fee_prob,
    )
    from breezy.strategy.weather_common.ladder import ask_levels, levels_within_price

    # The SHIPPED `hours_until`, deliberately not this module's
    # `hours_from_now_until` (T-10: renamed off the collision-prone name they
    # used to share): the two take their arguments in OPPOSITE order
    # (`models.hours_until(later, now)` vs `hours_from_now_until(now, deadline)`
    # above), and `cli_settlement_print_lock.strategy` calls the shipped one.
    # Using anything else here would flip the sign of every halt-window
    # verdict.
    from breezy.strategy.weather_common.models import (
        ensure_aware,
    )
    from breezy.strategy.weather_common.models import (
        hours_until as shipped_hours_until,
    )

    facts = contract.facts
    scale = (
        cfg.price_scale_override if cfg.price_scale_override is not None else contract.price_scale
    )
    hours_to_settlement = shipped_hours_until(deadline, now)

    printed_f = observation.tmax_f if facts.measure.value == "high" else observation.tmin_f
    contains = facts.contains(printed_f) if printed_f is not None else None
    ask_p = quote.implied_ask(scale)
    theta = contract.fee_coefficient

    # MIRRORS `cli_settlement_print_lock.decision.evaluate_instrument`
    # step for step -- level-0 fee for the anchor premium, the rungs the
    # shipped marketable IOC limit can lift, then the VWAP-priced edge over
    # the INTENDED size (s8.5, and BL-25 D1). Any divergence here decodes a
    # null into the wrong answer, which is the failure `GateLadderDriftError`
    # below exists to make impossible; the two are pinned by
    # `test_the_recorded_vwap_is_the_price_the_shipped_decision_actually_used`.
    fee_prob: float | None = None
    edge: float | None = None
    edge_zero_slip: float | None = None
    vwap_ask: float | None = None
    vwap_filled: float | None = None
    if ask_p is not None and 0.0 < ask_p < 1.0 and theta is not None:
        level0_fee_prob = venue_fee_prob(executable_price=ask_p, fee_coefficient=theta)
        # The level-0 PRE-SCREEN the shipped decision runs first, recorded as
        # the fallback so a book too thin to fill one contract is still
        # attributed to the SIZE gate (`GATE_QUANTITY_BELOW_ONE`) rather than
        # collapsing into `GATE_EDGE_BELOW_MINIMUM` for want of an edge.
        fee_prob = level0_fee_prob
        edge = (
            MEASURED_P_STABLE_WILSON_LOWER
            - ask_p
            - (level0_fee_prob + cfg.slippage_prob)
        )
        edge_zero_slip = edge + cfg.slippage_prob
        anchor = cost_basis_anchor(
            base_quantity=cfg.base_quantity,
            worst_ask=worst_admissible_ask(
                model_p=MEASURED_P_STABLE_WILSON_LOWER,
                fee_coefficient=theta,
                slippage_prob=cfg.slippage_prob,
                min_edge_after_costs=cfg.min_edge_after_costs,
                tick_size=contract.tick_size,
            ),
            fee_coefficient=theta,
        )
        reachable = levels_within_price(
            ask_levels(quote),
            (quote.ask or 0.0) + cfg.slippage_prob / scale,
        )
        reachable_depth = sum(size for price, size in reachable if size > 0.0 and price > 0.0)
        candidate = math.floor(
            min(cfg.max_quantity, anchor / (ask_p + level0_fee_prob), reachable_depth),
        )
        if candidate >= 1:
            try:
                cost_detail = depth_aware_trade_cost_prob(
                    ask_levels=reachable,
                    quantity=float(candidate),
                    price_scale=scale,
                    fee_coefficient=theta,
                    slippage_floor_prob=cfg.slippage_prob,
                )
            except NoExecutableDepthError:
                cost_detail = None
            if cost_detail is not None and 0.0 < cost_detail.executable_price < 1.0:
                vwap_ask = cost_detail.executable_price
                vwap_filled = float(math.floor(cost_detail.fillable_quantity))
                fee_prob = cost_detail.fee_prob
                edge = MEASURED_P_STABLE_WILSON_LOWER - vwap_ask - cost_detail.total_prob
                edge_zero_slip = edge + cost_detail.slippage_prob

    if hours_to_settlement <= cfg.halt_hours_before_settlement:
        gate = GATE_HALT_WINDOW
    elif not facts.applies_to(observation.station, observation.climate_day):
        gate = GATE_APPLIES_TO
    elif ensure_aware(observation.published_at) > ensure_aware(now):
        gate = GATE_LOOKAHEAD
    elif not observation.is_final:
        gate = GATE_NOT_FINAL
    elif observation.is_superseded:
        gate = GATE_SUPERSEDED
    elif observation.correction_flag:
        gate = GATE_CORRECTION
    elif facts.settlement_station not in MEASURED_STATIONS:
        gate = GATE_UNMEASURED_STATION
    elif not (cfg.use_tmax if facts.measure.value == "high" else cfg.use_tmin):
        gate = GATE_MEASURE_DISABLED
    elif printed_f is None:
        gate = GATE_NO_PRINTED_VALUE
    elif not contains:
        gate = GATE_BUCKET_NOT_CONTAINING
    elif MEASURED_P_STABLE_WILSON_LOWER < cfg.min_stable_prob:
        gate = GATE_MIN_STABLE_PROB
    elif ask_p is None:
        gate = GATE_NO_ASK
    elif ask_p <= 0.0 or ask_p >= 1.0:
        gate = GATE_DEGENERATE_ASK
    elif theta is None:
        gate = GATE_NO_FEE_COEFFICIENT
    elif edge is None or edge < cfg.min_edge_after_costs:
        gate = GATE_EDGE_BELOW_MINIMUM
    else:
        gate = GATE_NONE

    # CROSS-CHECK against the shipped decision function. `evaluate_instrument`
    # knows nothing about the halt window (that gate lives one level up in
    # `_evaluate_and_act`), so it is only consulted once the halt window is
    # cleared.
    if gate != GATE_HALT_WINDOW:
        decision = evaluate_instrument(
            contract=contract,
            quote=quote,
            observation=observation,
            now=now,
            p_stable=MEASURED_P_STABLE_WILSON_LOWER,
            cfg=cfg,
        )
        if decision is None and gate == GATE_NONE:
            # The one gate below the edge floor that this classifier cannot
            # reach without duplicating the shipped sizing arithmetic: the
            # floor-to-whole-contracts clip. Attribute it, then re-check.
            gate = GATE_QUANTITY_BELOW_ONE
        if (decision is not None) != (gate == GATE_NONE):
            raise GateLadderDriftError(
                f"first_blocking_gate classified {contract.instrument_id!r} as "
                f"{gate!r} (decision_formed={gate == GATE_NONE}) but the SHIPPED "
                f"cli_settlement_print_lock.decision.evaluate_instrument returned "
                f"{'a SignalDecision' if decision is not None else 'None'}. The gate "
                f"ladder in this classifier no longer matches the running strategy's; "
                f"refusing to emit a decision record that would decode a null into the "
                f"wrong answer.",
            )
        if decision is not None:
            # Prefer the SHIPPED edge over the locally recomputed one wherever
            # both exist, so the record can never disagree with the strategy.
            edge = decision.edge
            edge_zero_slip = decision.edge + cfg.slippage_prob

    decision_formed = gate == GATE_NONE
    return PrintLockGateRecord(
        instrument_id=contract.instrument_id,
        station=facts.settlement_station,
        climate_day=facts.climate_day,
        deadline=deadline,
        decided_at=now,
        cli_issued_at=observation.published_at,
        hours_to_settlement=hours_to_settlement,
        printed_f=printed_f,
        is_final=observation.is_final,
        correction_flag=observation.correction_flag,
        is_superseded=observation.is_superseded,
        bucket_lower_f=facts.lower_f,
        bucket_upper_f=facts.upper_f,
        bucket_contains_print=contains,
        level0_ask=ask_p,
        level0_ask_size=quote.ask_size,
        vwap_ask=vwap_ask,
        vwap_ask_filled_qty=vwap_filled,
        fee_coefficient=theta,
        fee_prob=fee_prob,
        slippage_prob=cfg.slippage_prob,
        model_probability=MEASURED_P_STABLE_WILSON_LOWER,
        edge=edge,
        edge_at_zero_slippage=edge_zero_slip,
        quote_age_minutes=(now - quote.ts_event).total_seconds() / 60.0,
        gate=gate,
        decision_formed=decision_formed,
        counted_by_refusal_counter=decision_formed,
    )
