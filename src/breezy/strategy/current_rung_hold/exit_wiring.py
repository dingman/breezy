"""Exit-order construction, fill provenance, and the AMBIGUOUS/rejected-exit
kill for :class:`~breezy.strategy.current_rung_hold.continuous_strategy.
ContinuousRungHoldStrategy` (INC-E3, ``docs/plans/
POSITION_EXIT_EXECUTION_2026-09-16.md`` §3, PREREG v4 §5b/§10).

Extracted from ``continuous_strategy.py`` (brief: "keep continuous_strategy
.py growth small -- extract to exit_wiring.py if > ~120 new lines") as free
functions taking the strategy instance as an explicit first argument --
mirrors ``monitor_wiring.py::build_monitor_callables``'s own DI shape for
the SAME module. ``ContinuousRungHoldStrategy`` is imported only under
``TYPE_CHECKING``: this module is imported BY ``continuous_strategy.py``,
so a runtime import the other way would be circular. ``continuous_strategy
.py`` keeps only thin wrapper methods (``submit_exit``,
``_on_exit_order_filled``, ``_halt_family_for_ambiguous_exit``) plus the
``on_order_filled``/``on_order_denied``/``on_order_rejected`` dispatch
points, which must stay on the class (they override ``Strategy`` methods).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId, PositionId
from nautilus_trader.model.orders import Order

from breezy.persistence.exit_tags import (
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatchError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.events import OrderFilled

    from breezy.strategy.current_rung_hold.continuous_strategy import (
        ContinuousRungHoldStrategy,
    )
    from breezy.strategy.current_rung_hold.exit_decider import ExitProposal

__all__ = [
    "EXIT_CLIENT_ORDER_ID_TAG_PREFIX",
    "EXIT_FAMILY_TAG_PREFIX",
    "EXIT_POSITION_TAG_PREFIX",
    "EXIT_RULE_TAG_PREFIX",
    "exit_position_id_from_tags",
    "exit_rule_from_tags",
    "halt_family_for_ambiguous_exit",
    "on_exit_order_filled",
    "order_is_exit",
    "submit_exit",
]

#: INC-E3 (plan §3): the Nautilus-native ``Order.tags`` carrier for an exit
#: order's ``ExitAuthorization`` fields -- never a global registry (the
#: brief's own instruction). ``EXIT_RULE_TAG_PREFIX``'s presence on ANY tag
#: is this module's sole "is this order an exit" test: Breezy never submits
#: any OTHER SELL-shaped or tagged order (every entry is a plain BUY,
#: ``continuous_strategy.py::_maybe_submit``), so a bare ``OrderSide.SELL``
#: check would be an equally correct but less self-documenting alternative
#: -- tags are used instead because ``OrderDenied``/``OrderRejected`` carry
#: no ``order_side`` field at all, only a ``client_order_id`` to look the
#: order back up by.
#:
#: INC-E2c: moved to ``persistence/exit_tags.py`` (the one definition site
#: both this module and the ``adapters``-layer exec client can import, per
#: the importlinter layer contract) and re-exported here UNCHANGED, so every
#: existing importer of ``exit_wiring.EXIT_RULE_TAG_PREFIX`` (etc.) keeps
#: working with no call-site change.

#: MUST match ``continuous_strategy._DIAG_FAMILY_HALT``'s value exactly (a
#: free-form diagnostics-counter string, not a shared enum) -- both name the
#: SAME "the family-wide halt gate blocked this tick" WAIT condition,
#: regardless of which of the two independent causes (a duplicate entry
#: fill, or an AMBIGUOUS/rejected exit) originally set it.
_DIAG_FAMILY_HALT: Final[str] = "family_halt_duplicate_fill"
_DIAG_FAMILY_HALT_AMBIGUOUS_EXIT: Final[str] = "family_halt_ambiguous_exit"
_POSITION_EXIT_FILLED: Final[str] = "exit_filled"
_POSITION_EXIT_ORDER_REJECTED: Final[str] = "exit_order_rejected"
_POSITION_EXIT_FILL_JOIN_ERROR: Final[str] = "exit_fill_join_error"


def order_is_exit(order: Order) -> bool:
    tags = order.tags
    if not tags:
        return False
    return any(tag.startswith(EXIT_RULE_TAG_PREFIX) for tag in tags)


def exit_position_id_from_tags(order: Order) -> str:
    tags: list[str] = order.tags or []
    for tag in tags:
        if tag.startswith(EXIT_POSITION_TAG_PREFIX):
            return str(tag[len(EXIT_POSITION_TAG_PREFIX) :])
    return ""


def exit_rule_from_tags(order: Order) -> str | None:
    tags: list[str] = order.tags or []
    for tag in tags:
        if tag.startswith(EXIT_RULE_TAG_PREFIX):
            return str(tag[len(EXIT_RULE_TAG_PREFIX) :])
    return None


def halt_family_for_ambiguous_exit(
    strategy: ContinuousRungHoldStrategy, *, position_id: str, reason: str, ts_ns: int,
) -> None:
    """Plan §5.4: the durable family-wide kill for an AMBIGUOUS or rejected
    exit order -- writes the SAME durable state
    ``TrialDayLatch.record_duplicate_fill`` writes, via
    ``TrialDayLatch.record_ambiguous_exit``."""
    assert strategy._latch is not None
    strategy._latch.record_ambiguous_exit(position_id=position_id, reason=reason, ts_ns=ts_ns)
    strategy.diagnostics.record(_DIAG_FAMILY_HALT_AMBIGUOUS_EXIT)
    strategy.position_events.record(_POSITION_EXIT_ORDER_REJECTED)
    strategy._report_alerter(
        strategy.diagnostics_alerter, "continuous_rung_hold diagnostics report failed",
    )


def on_exit_order_filled(strategy: ContinuousRungHoldStrategy, event: OrderFilled) -> None:
    """INC-E3 (plan §3, PREREG v4 §5b/§10): join a genuine EXIT fill to its
    station-day's ALREADY-CONSUMED trial and durably attach exit provenance
    via ``TrialDayLatch.record_exit`` -- a DIFFERENT durable write from the
    entry path's ``consume_if_absent``/duplicate-fill machinery, never
    re-consuming and never able to trip the duplicate-fill family halt.
    """
    assert strategy._latch is not None
    joined = strategy._join_fill_to_station_day(event.instrument_id)
    order = strategy.cache.order(event.client_order_id)
    exit_rule = None if order is None else exit_rule_from_tags(order)
    if joined is None or exit_rule is None:
        strategy.log.error(
            f"on_order_filled: exit fill for {event.instrument_id} could "
            "not be joined to a station-day or carries no exit_rule tag; "
            "exit provenance not recorded",
        )
        strategy.position_events.record(_POSITION_EXIT_FILL_JOIN_ERROR)
        strategy._report_alerter(
            strategy.position_alerter, "continuous_rung_hold position report failed",
        )
        return
    station, climate_day_key = joined
    fee = Decimal(0) if event.commission is None else event.commission.as_decimal()
    try:
        strategy._latch.record_exit(
            station,
            climate_day_key,
            key_instrument_id=str(event.instrument_id),
            exit_reason=exit_rule,
            exit_px=event.last_px.as_decimal(),
            exit_fee=fee,
            exit_at_ns=event.ts_event,
        )
    except TrialDayLatchError as exc:
        strategy.log.error(
            f"on_order_filled: record_exit failed for {event.instrument_id}: "
            f"{type(exc).__name__}: {exc}",
        )
        strategy.position_events.record(_POSITION_EXIT_FILL_JOIN_ERROR)
        strategy._report_alerter(
            strategy.position_alerter, "continuous_rung_hold position report failed",
        )
        return
    strategy.position_events.record(_POSITION_EXIT_FILLED)
    strategy._report_alerter(
        strategy.position_alerter, "continuous_rung_hold position report failed",
    )


def submit_exit(strategy: ContinuousRungHoldStrategy, proposal: ExitProposal) -> None:
    """Injected into ``PositionMonitor`` as its ``submit_exit`` callable
    (INC-E3, plan §3): construct and submit exactly the ONE 1-contract IOC
    LIMIT closing order ``proposal.authorization`` authorises.

    Family-halt veto FIRST (mirrors ``_hunt_tick``'s own ordering, plan
    §5.4): an exit competes for the SAME durable halt an entry does, so a
    family halted for ANY reason (a duplicate fill, or a prior
    AMBIGUOUS/rejected exit) never submits another order of either kind.
    The account-wide ``SubmitIntentLatch`` singleton (plan §5.2) is NOT
    re-checked here: every order this strategy ever builds -- entry or
    exit -- reaches the venue through the SAME ``submit_order``/execution-
    client path (``_maybe_submit`` makes no such check either), so the
    singleton is already binding for an exit with no extra code.

    ``Order.closing_side(position.side)`` (never a hardcoded ``SELL``) and
    ``reduce_only=False`` (no such venue request field, Appendix A) are the
    native shape L-1 verified (plan §0); ``client_order_id`` is pinned to
    the authorisation's own id so the two are ALWAYS the same string, and
    every authorisation field the exec seam or a rejection handler needs is
    ALSO carried in ``tags`` (the Nautilus-native carrier -- never a global
    registry).
    """
    assert strategy._latch is not None
    if strategy._latch.is_family_halted():
        strategy.diagnostics.record(_DIAG_FAMILY_HALT)
        strategy._report_alerter(
            strategy.diagnostics_alerter, "continuous_rung_hold diagnostics report failed",
        )
        return
    auth = proposal.authorization
    nt_id = InstrumentId.from_str(proposal.instrument_id)
    instrument = strategy.cache.instrument(nt_id)
    if instrument is None:
        strategy.log.error(f"exit: instrument vanished from cache: {proposal.instrument_id}")
        return
    position = strategy.cache.position(PositionId(auth.position_id))
    if position is None:
        strategy.log.error(f"exit: position vanished from cache: {auth.position_id}")
        return
    order = strategy.order_factory.limit(
        instrument_id=nt_id,
        order_side=Order.closing_side(position.side),
        quantity=instrument.make_qty(auth.quantity),
        price=instrument.make_price(auth.limit_price),
        time_in_force=TimeInForce.IOC,
        post_only=False,
        reduce_only=False,
        tags=[
            f"{EXIT_RULE_TAG_PREFIX}{auth.rule.value}",
            f"{EXIT_POSITION_TAG_PREFIX}{auth.position_id}",
            f"{EXIT_FAMILY_TAG_PREFIX}{auth.family_id}",
            f"{EXIT_CLIENT_ORDER_ID_TAG_PREFIX}{auth.client_order_id}",
        ],
        client_order_id=ClientOrderId(auth.client_order_id),
    )
    strategy.submit_order(order, position_id=position.id)
