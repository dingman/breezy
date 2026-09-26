"""Pure exit-decision logic for the intra-day position monitor (INC-E3,
``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`` Rev 2 §1/§3b,
``docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md`` §3b/§5b).

PURE, mirroring every sibling decision module in this package
(``monitor_decision.py``, ``decision.py``): no ``nautilus_trader`` import, no
I/O, no clock read. Every fact this needs is passed in by the caller
(``position_monitor.py``, INC-E3) -- the already-computed
:class:`~breezy.strategy.current_rung_hold.monitor_decision.MonitorDecision`
and :class:`~breezy.strategy.current_rung_hold.monitor_evidence.MonitorEvidence`
for ONE evaluation, plus the family's manifest and a small amount of
per-position/per-station-day bookkeeping the caller owns.

Two registered rules, evaluated in this order:

* **R_DEAD** (backstop) -- fires only once ``state == DEAD_BY_OBSERVATION``
  AND ``verdict == EXIT_RECOMMENDED`` (never on ``MISSING_STOP`` -- L-38: an
  exit whose leg cannot fill is an alert, never an order). Threshold: net
  proceeds strictly positive -- ``E[settlement | DEAD] ~= 0`` is the measured
  content of DEAD, so no cell estimate is needed.
* **R_THREAT** (primary) -- fires only once ``state == THREATENED`` AND
  ``verdict`` is ``REDUCE_RECOMMENDED`` or ``EXIT_RECOMMENDED``, AND
  ``evidence.p_hold_at_t`` is defined (an exit without an estimate is a
  guess -- refused, never a guessed threshold). Threshold: net proceeds
  strictly exceed the archive's own hold expectation for THIS authorised
  quantity (``p_hold_at_t`` for a YES holding, ``1 - p_hold_at_t`` for a NO
  holding -- both per-contract, matching the pinned ``quantity=1``).

Both rules share the SAME preconditions (plan §3b "Common preconditions"):
the family must be code-registered AND declare ``exit_rule``
(:func:`breezy.persistence.exit_gate.family_declares_exit_rule` -- the
unforgeable second half of a family's exit permission, L-22); the book must
be fresh and executable (the SAME predicate
``monitor_decision._dead_verdict`` already uses:
``mark_source == "depth_walk"``, ``depth_sufficient``,
``book_staleness_ns <= _BOOK_STALE_NS`` -- imported, never re-literalled, so
the two paths can never silently disagree on "fillable"); a rate limit (one
order per confirmation span -- ``_THREATENED_MIN_SPAN_NS``/
``_DEAD_MIN_CONFIRM_SPAN_NS``, imported from ``monitor_decision.py`` rather
than re-literalled, per the plan's own instruction); and a per-station-day
cap on exit orders (PROVISIONAL, module-local -- no source line to import,
since no prior increment needed one).

Price rule (plan §3 INC-E3, "never a mark, never an interpolation, never a
public-info price"): the authorised ``limit_price`` is
``evidence.mark_vwap`` -- the price
:func:`~breezy.strategy.current_rung_hold.monitor_evidence.walk_exit_vwap`
already proved fillable for the FULL held quantity walked in
``build_monitor_evidence``. This is a safe (never optimistic) price for the
PINNED ``quantity=1`` exit this module authorises even when
``evidence.held_qty > 1``: walking a book best-price-first means the
per-contract price for the FIRST unit sold is at least as good as (never
worse than) the multi-unit VWAP, so an IOC SELL LIMIT priced at the
(weaker) VWAP still clears against the best available level. A future
increment that authorises more than one contract per decision would need
to re-walk the book at that quantity instead of reusing this evaluation's
VWAP; this module never does, because it never authorises more than one.

Every refusal carries its own, distinct reason code (plan §3 INC-E3 RED
list) -- never a shared generic string -- so a caller (and a test) can
attribute a refused exit to the exact gate that refused it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from breezy.persistence.exit_gate import family_declares_exit_rule, family_declares_no_leg_exit
from breezy.strategy.current_rung_hold.exit_authorization import (
    ExitAuthorization,
    ExitAuthorizationRefusalError,
    ExitRule,
)
from breezy.strategy.current_rung_hold.monitor_decision import (
    _BOOK_STALE_NS,
    _DEAD_MIN_CONFIRM_SPAN_NS,
    _THREATENED_MIN_SPAN_NS,
    ThesisState,
    Verdict,
)
from breezy.strategy.current_rung_hold.monitor_evidence import exit_fee as _walk_exit_fee

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from breezy.persistence.family_manifest import FamilyManifest
    from breezy.strategy.current_rung_hold.monitor_decision import MonitorDecision
    from breezy.strategy.current_rung_hold.monitor_evidence import MonitorEvidence

__all__ = ["ExitProposal", "ExitRefusal", "decide_exit"]

#: The exit path never authorises more than one contract per decision (plan
#: §1/§3b: "one contract per authorisation, never the whole position in one
#: order"). Pinned locally rather than imported from ``exit_authorization``
#: (that module's own ``_PINNED_QUANTITY`` is private and unexported for the
#: same reason this one is -- a widened qty needs its own reviewed change,
#: never a shared constant two modules could drift on independently).
_QUANTITY: Final[int] = 1

#: PROVISIONAL (plan §1/§5.7, PREREG v4 §3b "Order shape"): "a per-station-
#: day cap bounds a flapping book." No prior increment defined one, so
#: there is no existing constant to import -- this is a NEW, module-local
#: PROVISIONAL value, never tuned off a live firing without a registered
#: amendment (Class-C, PREREG v4 §7).
#: FU-1d S1: the count this bounds (`PositionMonitor._station_day_exit_
#: counts`) is SHARED across a station-day's YES and NO legs, deliberately
#: -- PREREG v4 :48 and L-40 both name the station-day, not the leg, as the
#: trial unit this cap bounds.
MAX_STATION_DAY_EXIT_ORDERS: Final[int] = 2

_REASON_FAMILY_NOT_REGISTERED: Final[str] = "family_not_exit_registered"
_REASON_NO_LEG_EXIT_NOT_DECLARED: Final[str] = "no_leg_exit_not_declared"
_REASON_MISSING_STOP: Final[str] = "missing_stop_no_order"
_REASON_NO_EXIT_CONDITION: Final[str] = "no_exit_condition"
_REASON_BOOK_NOT_EXECUTABLE: Final[str] = "book_not_executable"
_REASON_BOOK_STALE: Final[str] = "book_stale"
_REASON_SETTLEMENT_UNDEFINED: Final[str] = "expected_settlement_undefined"
_REASON_RATE_LIMITED: Final[str] = "exit_rate_limited"
_REASON_STATION_DAY_CAP: Final[str] = "station_day_exit_cap"
_REASON_R_THREAT_INSUFFICIENT: Final[str] = "r_threat_insufficient_proceeds"
_REASON_R_DEAD_NONPOSITIVE: Final[str] = "r_dead_nonpositive_proceeds"
_REASON_AUTHORIZATION_REFUSED: Final[str] = "authorization_refused"

_ZERO: Final[Decimal] = Decimal(0)
_ONE: Final[Decimal] = Decimal(1)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitProposal:
    """One authorised, not-yet-submitted 1-contract closing order."""

    instrument_id: str
    authorization: ExitAuthorization
    decided_at_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitRefusal:
    """A refused exit evaluation -- ``rule`` is ``None`` when refused before
    a rule could even be selected (e.g. the family gate, or neither rule's
    state/verdict combination matched)."""

    instrument_id: str
    rule: ExitRule | None
    reason: str
    decided_at_ns: int


def _book_is_executable(evidence: MonitorEvidence) -> bool:
    """The SAME fillability predicate
    ``monitor_decision._dead_verdict`` uses -- imported constant, never
    re-literalled, so the two can never silently disagree on "fillable"."""
    return (
        evidence.mark_source == "depth_walk"
        and evidence.depth_sufficient
        and evidence.mark_vwap is not None
    )


def _book_is_fresh(evidence: MonitorEvidence) -> bool:
    return evidence.book_staleness_ns is not None and evidence.book_staleness_ns <= _BOOK_STALE_NS


def _select_rule(decision: MonitorDecision) -> tuple[ExitRule | None, str]:
    """Select a candidate rule from ``decision.state``/``decision.verdict``,
    or a refusal reason when neither rule's condition matches.

    Returns ``(rule, "")`` on a match, or ``(None, reason)`` on a refusal --
    never both ``None`` and an empty reason.
    """
    if decision.state is ThesisState.DEAD_BY_OBSERVATION:
        if decision.verdict is Verdict.EXIT_RECOMMENDED:
            return ExitRule.R_DEAD, ""
        return None, _REASON_MISSING_STOP
    if decision.state is ThesisState.THREATENED:
        if decision.verdict in (Verdict.REDUCE_RECOMMENDED, Verdict.EXIT_RECOMMENDED):
            return ExitRule.R_THREAT, ""
        return None, _REASON_NO_EXIT_CONDITION
    return None, _REASON_NO_EXIT_CONDITION


def _required_span_ns(rule: ExitRule) -> int:
    return _THREATENED_MIN_SPAN_NS if rule is ExitRule.R_THREAT else _DEAD_MIN_CONFIRM_SPAN_NS


def _expected_settlement_value(rule: ExitRule, evidence: MonitorEvidence) -> Decimal | None:
    """``E[settlement | state]`` for THIS authorised (pinned ``quantity=1``)
    contract -- ``None`` (undefined) only ever possible for R_THREAT (R_DEAD
    never calls this: ``E[settlement | DEAD] ~= 0`` is measured, not looked
    up, plan §1 C3)."""
    if rule is ExitRule.R_DEAD:
        return _ZERO
    p_hold = evidence.p_hold_at_t
    if p_hold is None:
        return None
    if evidence.leg == "YES":
        return p_hold * _QUANTITY
    return (_ONE - p_hold) * _QUANTITY


def decide_exit(
    decision: MonitorDecision,
    evidence: MonitorEvidence,
    *,
    manifest: FamilyManifest,
    family_id: str,
    position_id: str,
    client_order_id_factory: Callable[[], str],
    last_exit_decided_at_ns_for_position: int | None,
    station_day_exit_count: int,
    fee_coefficient: Decimal,
    now_ns: int,
) -> ExitProposal | ExitRefusal:
    """Evaluate one position's exit decision for THIS evaluation.

    Called only when a decider is installed (``position_monitor.py``);
    ``client_order_id_factory`` is invoked at most once, and only once every
    other gate has already passed -- a refused evaluation never consumes an
    id.
    """
    if not family_declares_exit_rule(manifest):
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=None,
            reason=_REASON_FAMILY_NOT_REGISTERED,
            decided_at_ns=now_ns,
        )

    # FU-1d: the NO-leg declaration gate. Placed directly after the family
    # gate and before rule selection, so a NO-leg evaluation refuses
    # unconditionally (rule=None) regardless of state/verdict -- this can
    # only ADD a restriction on top of the family gate above, never grant
    # an exit on its own (`family_declares_no_leg_exit`'s own docstring).
    if evidence.leg == "NO" and not family_declares_no_leg_exit(manifest):
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=None,
            reason=_REASON_NO_LEG_EXIT_NOT_DECLARED,
            decided_at_ns=now_ns,
        )

    rule, refusal_reason = _select_rule(decision)
    if rule is None:
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=None,
            reason=refusal_reason,
            decided_at_ns=now_ns,
        )

    if not _book_is_executable(evidence):
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=rule,
            reason=_REASON_BOOK_NOT_EXECUTABLE,
            decided_at_ns=now_ns,
        )
    if not _book_is_fresh(evidence):
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=rule,
            reason=_REASON_BOOK_STALE,
            decided_at_ns=now_ns,
        )

    expected_settlement_value = _expected_settlement_value(rule, evidence)
    if expected_settlement_value is None:
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=rule,
            reason=_REASON_SETTLEMENT_UNDEFINED,
            decided_at_ns=now_ns,
        )

    if last_exit_decided_at_ns_for_position is not None:
        elapsed_ns = now_ns - last_exit_decided_at_ns_for_position
        if elapsed_ns < _required_span_ns(rule):
            return ExitRefusal(
                instrument_id=evidence.instrument_id,
                rule=rule,
                reason=_REASON_RATE_LIMITED,
                decided_at_ns=now_ns,
            )

    if station_day_exit_count >= MAX_STATION_DAY_EXIT_ORDERS:
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=rule,
            reason=_REASON_STATION_DAY_CAP,
            decided_at_ns=now_ns,
        )

    assert evidence.mark_vwap is not None  # `_book_is_executable` guarantees this
    limit_price = evidence.mark_vwap
    net_proceeds = limit_price * _QUANTITY - _walk_exit_fee(limit_price, _QUANTITY, fee_coefficient)
    if rule is ExitRule.R_THREAT and not (net_proceeds > expected_settlement_value):
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=rule,
            reason=_REASON_R_THREAT_INSUFFICIENT,
            decided_at_ns=now_ns,
        )
    if rule is ExitRule.R_DEAD and not (net_proceeds > _ZERO):
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=rule,
            reason=_REASON_R_DEAD_NONPOSITIVE,
            decided_at_ns=now_ns,
        )

    try:
        authorization = ExitAuthorization(
            family_id=family_id,
            position_id=position_id,
            client_order_id=client_order_id_factory(),
            leg="yes" if evidence.leg == "YES" else "no",
            attributed_net_long=evidence.held_qty,
            working_sell_qty=0,
            quantity=_QUANTITY,
            limit_price=limit_price,
            rule=rule,
            expected_settlement_value=expected_settlement_value,
            fee_coefficient=fee_coefficient,
            decided_at_ns=now_ns,
            book_staleness_ns=(
                evidence.book_staleness_ns if evidence.book_staleness_ns is not None else 0
            ),
        )
    except ExitAuthorizationRefusalError:
        return ExitRefusal(
            instrument_id=evidence.instrument_id,
            rule=rule,
            reason=_REASON_AUTHORIZATION_REFUSED,
            decided_at_ns=now_ns,
        )

    return ExitProposal(
        instrument_id=evidence.instrument_id,
        authorization=authorization,
        decided_at_ns=now_ns,
    )
