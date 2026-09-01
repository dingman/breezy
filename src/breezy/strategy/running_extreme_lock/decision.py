"""The preserved trading decision: a same-day running extreme, already inside
the open-ended tail, versus the live ask.

Edge hypothesis (see ``docs/strategies/breezy_strategy_running_extreme_lock.md``):
once the official running high ``H`` for a station/climate-day is already
``>=`` the lower bound of an open-ended "X or above" contract, that contract
can only settle YES unless the observation is later revised down across the
tail floor. This module is PURE -- no I/O, no clock, no order submission --
mirroring ``breezy.strategy.forecast_mispricing.decision.evaluate_instrument``.

v1 SCOPE (binding, not a placeholder)
--------------------------------------
Only the open-ended UPPER tail on a HIGH-measure bucket is implemented
(``open_tail_only=True`` is the only path -- see
``breezy.strategy.running_extreme_lock.config.RunningExtremeLockConfig``).
The interior-bucket path from the design brief is NOT implemented: the
pre-registered symmetric-revision-rate study, re-run against the archive
(N>=1800/site, POWERED), FAILS on 3 of 5 sites for an interior bucket's exact-
equality requirement (MDW 13.96%, NYC 11.79%, SFO 4.50% -- see
``docs/evidence/observation_lock_falsification_2026-08-31.md`` section 2). The
open tail survives on the SAME data: it only loses on a DOWNWARD crossing,
measured pooled at 0.21% (20/9736). The low-measure open tail is also out of
scope -- no ``p_hold`` table exists for a running minimum. A bucket that does
not qualify for the open-upper-tail path -- including an interior bucket the
running value has already blown past -- always evaluates to ``None``, never a
short (the design brief's step 5, and this module's own
``test_running_value_above_an_interior_buckets_upper_bound_is_dead_not_a_short``).

MARGIN-CONDITIONED model_p (C5, binding)
------------------------------------------
A flat probability floor (the brief's ``min_p_hold = 0.96``) gates a
margin-conditional hazard while firing at margin ~= 0 -- the worst-conditioned
cell. ``model_probability`` here is instead looked up from a table of
MEASURED, margin-conditioned Wilson-95%-LOWER bounds (never a point estimate),
keyed by ``margin_f = running_f - tail_floor``:

    margin_f  p_hold      Wilson 95% lower
    0         99.7946%    99.6829%
    1         99.9076%    99.8244%
    2         99.9486%    99.8798%
    3         99.9692%    99.9094%
    4+        99.9897%    99.9418%

Source: N=9736 preliminary records, archive-powered, 2020-12..2026-08, 5
sites (KNYC/KMIA/KMDW/KLAX/KSFO) --
``docs/evidence/observation_lock_falsification_2026-08-31.md`` section 2.
Downward events by magnitude: -1F x11, -2F x4, -3F x2, -4F x2, -16F x1 (20
total). The table is passed IN by the caller (``model_p_table``), never
computed here -- see ``breezy.strategy.running_extreme_lock.strategy`` for
where it is built and why it is a fixed, cited constant rather than a
runtime-queried one.

Deliberately NOT ``WeatherBucketFacts.distance_f`` for margin. That method
returns the unsigned distance a reading sits OUTSIDE an interval, and 0 for
any reading INSIDE it (verified in source,
``breezy/domain/weather_bucket_facts.py``). For an open-ended tail
(``upper_f is None``), ``contains(running_f)`` is True for every
``running_f >= lower_f`` -- so ``distance_f`` returns 0 for margin 0 AND
margin 40 alike. It cannot express "how far past the floor", only "are we
past it at all". Margin is computed directly instead:
``running_f - tail_floor``.

FAT TAIL -- documented, not engineered away
----------------------------------------------
MDW 2021-12-30: preliminary ``MAXIMUM 55  7:11 AM``, final ``MAXIMUM 39``.
Neither product carried ``CCA``/``CCB`` or correction text; cached hourly
observations topped out at 39.2F. An UNFLAGGED bad preliminary --
``correction_flag`` would NOT have caught it, and no margin guard band stops
it (a 55F print at the floor of an 80F+ tail would have margin far past the
table's cap). 1 event in 9736. This module does not attempt to filter it;
it is carried here as an acknowledged, unclosed risk, per the peer review.

C6 -- gate on correction_flag / is_superseded
------------------------------------------------
The design brief names a downward revision as loss condition #1 but its
published algorithm never checks the record's own flags. A record flagged
corrected or superseded is not tradable here, full stop -- see
:func:`evaluate_instrument`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from breezy.domain.weather_bucket_facts import Measure
from breezy.strategy.weather_common.ladder import walk_ask_ladder
from breezy.strategy.weather_common.models import SideIntent, SignalDecision, ensure_aware

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.running_extreme_lock.config import RunningExtremeLockConfig
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import MarketQuote

__all__ = ["RunningExtremeObservation", "evaluate_instrument"]


@dataclass(frozen=True, slots=True)
class RunningExtremeObservation:
    """The station/climate-day running-extreme signal, translated out of the
    raw ``breezy.domain.nws_climate_day.NwsClimateDay`` wire record.

    A translated snapshot, not the wire type itself -- the same shape choice
    ``ForecastSnapshot`` makes for the forecast-driven strategies -- so this
    module's tests never need to construct a full 20-field ``NwsClimateDay``.
    ``published_at`` is the record's ISSUANCE instant (never a retrieval/ingest
    timestamp), matching ``SignalFreshness.age_hours``'s own contract.
    """

    station: str
    climate_day: dt.date
    #: The running high. ``None`` when the product carries no reading yet.
    tmax_f: int | None
    #: The running low. Carried for completeness with ``NwsClimateDay`` but
    #: UNUSED in v1 -- see the module docstring: the low-measure open tail
    #: needs its own ``p_hold`` table, which does not exist yet.
    tmin_f: int | None
    correction_flag: bool
    is_superseded: bool
    published_at: dt.datetime


def _vwap_ask_for_quantity(
    ladder: Sequence[tuple[float, float]],
    quantity: float,
) -> tuple[float, float] | None:
    """Thin adapter over :func:`weather_common.ladder.walk_ask_ladder`.

    THE WALK ITSELF NO LONGER LIVES HERE (BL-25 D2). It was private to this
    module while `cli_settlement_print_lock.decision`,
    `weather_common.risk.RiskManager.evaluate_order` and the offline gate
    classifier in `scripts/analysis/weather_strategy_backtest_lib` all needed
    the same arithmetic; four copies of a book walk is four places for the
    fill price to drift from the price the edge was computed at. See
    `weather_common.ladder` for the padding, exhaustion and unit semantics
    this function's callers rely on -- all unchanged.

    Kept as a named function, returning the same `(vwap_price,
    filled_quantity)` tuple it always returned, because the sole caller below
    and the record in `weather_strategy_backtest_lib` both read it that way.
    """
    walk = walk_ask_ladder(ladder, quantity)
    if walk is None:
        return None
    return walk.vwap_price, walk.filled_quantity


def _model_p_for_margin(margin_f: int, model_p_table: Mapping[int, float]) -> float:
    """The measured Wilson-lower-bound ``model_p`` for ``margin_f`` degrees past the floor.

    Clamps to the table's highest keyed margin -- the "5+" row collapses every
    margin from 5 upward to one measured value (see the module docstring).
    ``margin_f`` is always >= 0 here: the only caller only reaches this
    function once ``running_f >= tail_floor`` is already established.
    """
    ceiling = max(model_p_table)
    capped_margin = min(max(margin_f, 0), ceiling)
    return model_p_table[capped_margin]


def evaluate_instrument(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    observation: RunningExtremeObservation,
    now: dt.datetime,
    model_p_table: Mapping[int, float],
    cfg: RunningExtremeLockConfig,
) -> SignalDecision | None:
    """Return the desired position change, or ``None`` for "do nothing".

    Never returns a ``SHORT_YES`` intent under any input -- there is no branch
    in this function that constructs one.
    """
    facts = contract.facts
    if not facts.applies_to(observation.station, observation.climate_day):
        return None
    if ensure_aware(observation.published_at) > ensure_aware(now):
        # Look-ahead guard: a record whose own timestamp is still in the
        # future relative to the decision clock has not "happened" yet.
        return None
    if observation.correction_flag or observation.is_superseded:
        # C6: a corrected/superseded record is not tradable, regardless of
        # what it reads.
        return None

    if facts.measure is not Measure.HIGH:
        # v1: no p_hold table exists for a running-minimum open tail.
        return None
    if facts.lower_f is None or facts.upper_f is not None:
        # v1: only an open-ended UPPER tail (a finite lower bound, no upper
        # bound) is implemented. Anything else -- including an interior
        # bucket the running value has already cleared -- is dead: return
        # None, never a short (design brief step 5).
        return None

    running_f = observation.tmax_f
    if running_f is None:
        return None

    tail_floor = facts.lower_f
    if running_f < tail_floor:
        # The tail has not been entered yet -- no signal at all.
        return None

    margin_f = running_f - tail_floor
    model_p = _model_p_for_margin(margin_f, model_p_table)

    scale = (
        cfg.price_scale_override if cfg.price_scale_override is not None else contract.price_scale
    )
    ask_p = quote.implied_ask(scale)
    ask_raw = quote.ask
    if ask_p is None or ask_raw is None:
        return None
    # Degenerate-ask guard -- independent of `RiskManager.quote_tradable`'s
    # crossed-book refusal downstream: this module is documented as
    # independently reusable, so its own guard must hold on its own (MEDIUM
    # finding). `ask_p <= 0.0` flows through the edge formula below as
    # `edge ~= model_p - cost`, an apparent ~0.98 "free" edge that is really
    # a degenerate/missing price, never a real quote. `ask_p >= 1.0` is the
    # mirror boundary for a 0/1 binary contract: paying at or above the
    # maximum possible payout can never be a profitable LONG_YES trade
    # (`model_p` is always < 1.0 here -- see `MEASURED_MARGIN_MODEL_P`), so
    # `edge < cfg.min_model_edge` already rejects it algebraically today --
    # guarded explicitly anyway so the invariant does not silently depend on
    # the table staying < 1.0 or `transaction_cost_prob` staying
    # non-negative.
    if ask_p <= 0.0 or ask_p >= 1.0:
        return None

    # --- Depth-aware pricing & sizing (HIGH finding) -----------------------
    # Every fill here is a TAKER against the live ask (module docstring), so
    # pricing/sizing off the level-0 tick alone prices an execution that
    # never actually happens once the intended size exceeds level 0 -- on a
    # thin book the fill walks through price and can consume the entire
    # "profitable" edge.
    #
    # Sizing and edge are mutually dependent: a bigger size walks deeper into
    # the ask ladder, worsening the VWAP price, which shrinks the edge, which
    # would (in a full fixed-point sense) shrink the size again. Resolved
    # here as SIZE-FIRST-THEN-REPRICE, not an iterative largest-quantity
    # search: `candidate_quantity` below is the same
    # `base_quantity + edge_qty_scale * edge` formula as before, evaluated
    # against the level-0 (top-of-book) edge purely as an initial ESTIMATE.
    # That candidate is then clipped to whatever real depth the ladder
    # offers and RE-PRICED against the VWAP of that exact clipped size. If
    # the VWAP-priced edge no longer clears `min_model_edge`, the signal is
    # refused outright -- it is not shrunk further to "make it fit": a size
    # whose true cost fails the edge floor is not a trade this strategy
    # chases down to a smaller size derived from a stale top-of-book
    # estimate. A full largest-quantity-that-still-clears search would
    # converge (edge is monotonically non-increasing in quantity as deeper,
    # worse-priced levels are consumed), but is unwarranted complexity for a
    # v1 sizing formula whose inputs (`base_quantity`, `edge_qty_scale`) are
    # themselves a coarse, tunable estimate rather than an optimized target.
    level0_edge = model_p - ask_p - cfg.transaction_cost_prob
    candidate_quantity = min(
        cfg.max_quantity,
        cfg.base_quantity + cfg.edge_qty_scale * level0_edge,
    )
    if candidate_quantity <= 0:
        return None

    ladder = (
        quote.ask_ladder if quote.ask_ladder is not None else ((ask_raw, quote.ask_size or 0.0),)
    )
    filled = _vwap_ask_for_quantity(ladder, candidate_quantity)
    if filled is None:
        return None
    vwap_raw, quantity = filled
    vwap_ask_p = vwap_raw * scale
    if vwap_ask_p <= 0.0 or vwap_ask_p >= 1.0:
        # Defensive: a degenerate deeper level (bad venue data) should not
        # silently produce a degenerate VWAP once it clears the top-of-book
        # guard above.
        return None

    # Edge vs the VWAP-priced ask actually consumed, never the level-0 tick
    # or the mid -- every fill here is a taker.
    edge = model_p - vwap_ask_p - cfg.transaction_cost_prob
    if edge < cfg.min_model_edge:
        return None

    return SignalDecision(
        instrument_id=contract.instrument_id,
        intent=SideIntent.LONG_YES,
        model_probability=model_p,
        market_probability=vwap_ask_p,
        edge=edge,
        # 0.0 at the tail floor (margin 0, the worst-conditioned cell) rising
        # to 1.0 once margin reaches the table's highest keyed value.
        conviction=min(1.0, margin_f / float(max(model_p_table))),
        quantity=quantity,
        reason="running_extreme_open_tail_cleared",
        metadata={
            "margin_f": margin_f,
            "running_f": running_f,
            "tail_floor_f": tail_floor,
        },
    )
