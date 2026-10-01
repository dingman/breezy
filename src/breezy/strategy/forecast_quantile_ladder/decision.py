"""Pure decision module for `forecast_quantile_ladder` (SL-12). No I/O.

Plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §3.3: "The trial
is the first executable snapshot per (station-day, rung, side, variant) that
satisfies ``ev_net > margin`` under the latest available cycle. One latch;
qty 1... A decision outside [a live permit] is recorded as NOT_EXECUTABLE,
never latched and never counted as a trial... A new cycle never re-opens a
latched rung. Sizing never reads ``kelly_stake_fraction``, and no
operator-reserved value is read or assigned."

Ruling A-6 (docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md §12,
SL-12 domain review) is binding here:

* The margin comes from :func:`breezy.strategy.forecast_quantile_ladder.
  margin.forecast_margin`, never ``ladder_ev.scoring.margin`` (no
  ``n_cell``/archive-cell gate for this family).
* The take rule is side-specific: YES needs ``p_lower - ask - fee(ask) >
  margin``; NO needs ``(1 - p_upper) - no_ask - fee(no_ask) > margin``, and
  ``no_ask`` MUST be quoted from the native NO instrument -- see
  :class:`SidedAsk` and :func:`evaluate`'s first check.
* ``p_lower``/``p_upper`` are bootstrap draws (A-4), never an inline
  haircut -- see :mod:`bounds`.

Deliberately does NOT import
:func:`breezy.strategy.ladder_ev.decision.exclusion_filter` /
:class:`breezy.strategy.ladder_ev.decision.ExclusionInputs` (the DEGRADED-mode
X-rule gate; this is a distinct forecast-mode decision path) nor
``breezy.strategy.current_rung_hold.archive_table``'s ``P_HOLD_LOWER`` /
``P_HOLD_UPPER`` (the closed model's collider cells -- plan §1.2 item 2:
"No dependence on the P_HOLD_* collider cells"). Pinned by
``tests/strategy/forecast_quantile_ladder/test_forbidden_imports.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Literal

from breezy.ingest.gaps import local_standard_date
from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import Percentiles, Rung, apply_emos, build_cdf
from breezy.strategy.ladder_ev.scoring import ev_net, ev_net_no
from breezy.strategy.weather_common.costs import DepthAwareTradeCost, venue_fee_prob

__all__ = [
    "OPPOSITE_SIDE_LATCHED",
    "QTY",
    "VECTOR_DAY_MISMATCH",
    "AskSideMismatchError",
    "Decision",
    "NotDPlus1",
    "NotExecutable",
    "Refuse",
    "SidedAsk",
    "Take",
    "decision_log_fields",
    "evaluate",
]

#: Sizing is always exactly 1 contract (plan §3.3: "qty 1"). Never a config
#: field, never derived from `kelly_stake_fraction` -- there is no such input.
QTY: Literal[1] = 1

#: SL-13e defence-in-depth: a `ForecastQuantileVector` carries its own
#: target `climate_day` (the D+1 calendar day its MAX-column window was
#: computed against, at push time). A vector whose `climate_day` disagrees
#: with the instrument's own `climate_day` (this evaluation's caller-supplied
#: value) must never be scored against that instrument -- the numbers would
#: describe a DIFFERENT day's high than the one this rung settles on. Refused
#: with this named reason rather than silently scored, exactly like every
#: other non-trial verdict in this module.
VECTOR_DAY_MISMATCH: Final[str] = "vector_day_mismatch"

#: D10 / S10. Once either side of a (station, climate_day, rung) has Taken,
#: the other side refuses with this reason. Checked immediately after the
#: own-side latch and before ``forecast_unavailable`` / ``vector_day_mismatch``
#: — see :func:`evaluate`'s check-order comment. Do not reorder.
OPPOSITE_SIDE_LATCHED: Final[str] = "opposite_side_latched"

_OPPOSITE: Final[dict[Literal["yes", "no"], Literal["yes", "no"]]] = {
    "yes": "no",
    "no": "yes",
}


class AskSideMismatchError(ValueError):
    """Raised when the supplied :class:`SidedAsk` was quoted from the WRONG
    side's instrument -- e.g. a YES ask passed for a NO evaluation.

    Review HIGH (SL-12): the NO leg must be priced from its own native NO
    instrument, never derived or substituted from the YES ask.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class SidedAsk:
    """One venue ask, tagged with the side and instrument it was quoted from.

    The single source of truth for "which instrument did this price come
    from" -- :func:`evaluate` asserts ``ask.side == side`` before pricing
    anything with it, so a caller cannot accidentally price a NO take off a
    YES quote (or vice versa).
    """

    side: Literal["yes", "no"]
    instrument_id: str
    price: float


@dataclass(frozen=True, slots=True, kw_only=True)
class NotExecutable:
    """Outside a live order-permit window: never latched, never counted as a
    trial (plan §3.3)."""

    reason: str = "outside_permit_window"


@dataclass(frozen=True, slots=True, kw_only=True)
class NotDPlus1:
    """``climate_day`` is not D+1 of ``now_ns`` in the station's LST (plan
    §2.3: V1 is D+1 only). Never latched, never counted as a trial -- the
    same non-trial treatment as :class:`NotExecutable`, for a distinct
    reason."""

    reason: str = "not_d_plus_1"


@dataclass(frozen=True, slots=True, kw_only=True)
class Refuse:
    """Evaluated, but not taken; the latch is untouched."""

    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Take:
    """The first qualifying snapshot for this (station-day, rung, side).

    ``qty`` is always :data:`QTY` -- present on the record for observability,
    never accepted as a caller input. ``instrument_id`` is read off the
    winning :class:`SidedAsk`, never a separate caller-supplied value.
    """

    instrument_id: str
    station: str
    climate_day: date
    side: Literal["yes", "no"]
    rung_id: str
    qty: Literal[1]
    ev_net: float
    p_hat: float
    p_lower: float
    p_upper: float


Decision = NotExecutable | NotDPlus1 | Refuse | Take


def decision_log_fields(decision: Decision) -> dict[str, object]:
    """Explicit, field-by-field serialisation of one ``Decision`` -- the
    shadow log's ONLY encoder (plan §7 row SL-12: "logs every decision
    (keys and inputs) as a shadow decision log line").

    ``dataclasses.asdict`` is banned repo-wide outside the closed allowlist
    in ``tests/unit/test_polymarket_us_credential_serialization.py`` (item 2,
    the partial-secret-leak guard), and this package is never on it -- see
    ``tests/strategy/forecast_quantile_ladder/test_forbidden_imports.py``.
    Each branch below lists its dataclass's fields BY NAME, so a future field
    added to a ``Decision`` variant without a matching line here is a diff a
    reviewer sees, never a silent drop from the log.

    Fails CLOSED: an unrecognised ``Decision`` type raises rather than
    silently emitting nothing.
    """
    if isinstance(decision, NotExecutable):
        return {"reason": decision.reason}
    if isinstance(decision, NotDPlus1):
        return {"reason": decision.reason}
    if isinstance(decision, Refuse):
        return {"reason": decision.reason}
    if isinstance(decision, Take):
        return {
            "instrument_id": decision.instrument_id,
            "station": decision.station,
            "climate_day": decision.climate_day,
            "side": decision.side,
            "rung_id": decision.rung_id,
            "qty": decision.qty,
            "ev_net": decision.ev_net,
            "p_hat": decision.p_hat,
            "p_lower": decision.p_lower,
            "p_upper": decision.p_upper,
        }
    raise TypeError(f"decision_log_fields: unrecognised Decision type {type(decision)!r}")


def _is_d_plus_1(*, now_ns: int, climate_day: date, std_utc_offset_hours: float) -> bool:
    today_lst = local_standard_date(now_ns, std_utc_offset_hours)
    return climate_day == today_lst + timedelta(days=1)


def evaluate(
    *,
    now_ns: int,
    std_utc_offset_hours: float,
    permit_covers: bool,
    vector: ForecastQuantileVector | None,
    station: str,
    climate_day: date,
    ladder: Sequence[Rung],
    rung_id: str,
    side: Literal["yes", "no"] = "yes",
    ask: SidedAsk,
    fee_coefficient: float,
    slippage_floor_prob: float,
    h_hours: float,
    cfg: LadderEvConfig,
    artefact: CalibrationArtefact,
    bounds_provider: BoundsProvider,
    latch: QuantileLadderLatch,
) -> Decision:
    """Evaluate ONE rung at ONE snapshot. Pure; mutates only ``latch`` on a Take.

    Check order — do not reorder. Pinned by
    ``test_evaluate_check_order_pins_opposite_side_between_own_side_and_later_refusals``.
    Earliest true condition wins:

    (1) ask/side binding and (2) ``rung_id`` membership raise unconditionally.
    A mismatch here is a wiring bug, never a business decision, so it is
    checked before anything else and regardless of permit or latch state.
    (3) D+1 scope → :class:`NotDPlus1`.
    (4) the permit → :class:`NotExecutable`.
    (5) the own-side latch → ``Refuse("already_latched")``.
    (6) the opposite-side latch → ``Refuse(OPPOSITE_SIDE_LATCHED)``.
    (7) ``forecast_unavailable``.
    (8) ``vector_day_mismatch``, then the later scoring refusals.

    (3) and (4) stay ahead of both latch checks: they are non-trials (plan
    §3.3, "never latched and never counted as a trial") and must not report
    a latch reason. (6) is immediately after (5) and ahead of (7) and (8),
    so a missing or day-mismatched forecast cannot mask the self-hedge
    (D10). A later slice that adds a scoring refusal must insert it after
    (8), never above (6).
    """
    if ask.side != side:
        raise AskSideMismatchError(
            f"ask was quoted from the {ask.side!r} instrument {ask.instrument_id!r}, "
            f"but this evaluation is for side {side!r}; the {side!r} leg must be "
            f"priced from its own native instrument (ruling A-6)",
        )

    rung_ids = {rung.rung_id for rung in ladder}
    if rung_id not in rung_ids:
        raise ValueError(f"rung_id {rung_id!r} is not a member of `ladder`")

    is_d_plus_1 = _is_d_plus_1(
        now_ns=now_ns, climate_day=climate_day, std_utc_offset_hours=std_utc_offset_hours,
    )
    if not is_d_plus_1:
        return NotDPlus1()

    if not permit_covers:
        return NotExecutable()

    if latch.is_latched(station=station, climate_day=climate_day, rung_id=rung_id, side=side):
        return Refuse(reason="already_latched")

    # Precedence, pinned: own-side latch (above) then this opposite-side
    # check, then forecast_unavailable and vector_day_mismatch. D+1 and the
    # permit stay above both latch checks. Do not reorder.
    if latch.is_latched(
        station=station,
        climate_day=climate_day,
        rung_id=rung_id,
        side=_OPPOSITE[side],
    ):
        return Refuse(reason=OPPOSITE_SIDE_LATCHED)

    if vector is None:
        return Refuse(reason="forecast_unavailable")

    if vector.climate_day != climate_day:
        return Refuse(reason=VECTOR_DAY_MISMATCH)

    percentiles = Percentiles(
        q10=vector.q10,
        q25=vector.q25,
        q50=vector.q50,
        q75=vector.q75,
        q90=vector.q90,
        mean=vector.mean,
        sd=vector.sd,
    )
    base_cdf = build_cdf(artefact.cdf_method, percentiles)
    cdf = apply_emos(base_cdf, percentiles, artefact.emos)
    bounds = bounds_provider(cdf=cdf, ladder=ladder, rung_id=rung_id)
    p_hat, p_lower, p_upper = bounds.p_hat, bounds.p_lower, bounds.p_upper

    # V1 is qty 1 at a single quoted price -- no ladder walk, so the
    # executable/top-of-book/worst prices coincide and the fill is never
    # depth-exhausted. Depth-aware sizing beyond 1 contract is out of scope
    # for this slice (plan §3.3: "qty 1").
    fee_prob = venue_fee_prob(executable_price=ask.price, fee_coefficient=fee_coefficient)
    cost = DepthAwareTradeCost(
        executable_price=ask.price,
        top_of_book_price=ask.price,
        worst_price=ask.price,
        fee_prob=fee_prob,
        slippage_prob=slippage_floor_prob,
        total_prob=fee_prob + slippage_floor_prob,
        fillable_quantity=float(QTY),
        requested_quantity=float(QTY),
        depth_exhausted=False,
    )
    net = ev_net(p_lower, cost) if side == "yes" else ev_net_no(p_upper, cost)
    if net is None:
        return Refuse(reason="not_executable")

    buffer = forecast_margin(h_hours, cfg)
    if not (net > buffer):
        return Refuse(reason="below_margin")

    latch.latch(station=station, climate_day=climate_day, rung_id=rung_id, side=side)
    return Take(
        instrument_id=ask.instrument_id,
        station=station,
        climate_day=climate_day,
        side=side,
        rung_id=rung_id,
        qty=QTY,
        ev_net=net,
        p_hat=p_hat,
        p_lower=p_lower,
        p_upper=p_upper,
    )
