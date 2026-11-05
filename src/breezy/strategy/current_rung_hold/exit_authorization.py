"""``ExitAuthorization`` -- a fail-fast convenience value object for one
proposed 1-contract closing order (INC-E1,
``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`` §3).

No ``nautilus_trader`` import, no I/O, no clock read: every fact this module
needs is passed in by the caller (the intra-day position monitor /
``continuous_strategy.py``, INC-E3), mirroring every other pure decision
module in this package (see ``decision.py``'s own docstring).

**This object is a convenience, never the binding invariant (review LOW
10).** It is constructed by the STRATEGY layer, so unlike a manifest- or
frozenset-gated fact (L-22), it is NOT unforgeable: a bug in the caller could
in principle build one with wrong numbers. The construction-time checks
below exist only to fail loudly and immediately at the decision site, one
layer above the wire. The actual, binding, account-wide invariant that
prevents a naked short or an over-sized exit from ever reaching the venue is
``breezy.runtime.backtest_order_guard._refuse_naked_short`` (installed by
``install_live_order_guard`` at ``trade_cli.py:399``), which reads the
shared ``Portfolio``/``Cache`` per instrument regardless of what any
strategy-constructed object claims. Nothing in this module substitutes for
that guard.

Reuses :func:`breezy.strategy.current_rung_hold.monitor_evidence.exit_fee`
for the net-proceeds check (imported, never re-derived) -- the SAME
per-contract fee coefficient source ``recoverable_value`` is computed from,
so a strategy-authored authorisation and the archive-driven evidence it was
built from can never silently price the exit fee two different ways.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final, Literal

from breezy.strategy.current_rung_hold.monitor_evidence import exit_fee

__all__ = ["ExitAuthorization", "ExitAuthorizationRefusalError", "ExitRule"]

_ZERO: Final[Decimal] = Decimal(0)
_ONE: Final[Decimal] = Decimal(1)
_PINNED_QUANTITY: Final[int] = 1

#: A held position's side, matching
#: ``breezy.adapters.polymarket_us.symbology.leg_of``'s two values -- declared
#: locally (never imported from ``adapters/``) because the importlinter layer
#: contract (``pyproject.toml`` ``[tool.importlinter]``) lets this
#: ``strategy``-layer module reach down into ``persistence`` and ``runtime``
#: only (module docstring); ``decision.py``'s own ``side: Literal["yes",
#: "no"]`` field is the precedent for declaring the same two-value literal
#: locally rather than importing it.
Leg = Literal["yes", "no"]


class ExitRule(str, Enum):
    """The two registered exit rules (PREREG v4, plan §1).

    ``R_THREAT`` is the primary, acting rule (fires on a THREATENED thesis
    while ``recoverable_value`` still exceeds the archive's own hold
    expectation). ``R_DEAD`` is the backstop (fires once the thesis is
    confirmed dead and any recovery at all beats a certain zero).
    """

    R_THREAT = "R_THREAT"
    R_DEAD = "R_DEAD"


class ExitAuthorizationRefusalError(ValueError):
    """Refused at construction -- an ``ExitAuthorization`` that violates one
    of its own fail-fast checks was never minted (module docstring)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitAuthorization:
    """One proposed 1-contract closing order, self-validating at construction.

    Fields (plan §3 INC-E1): ``family_id``, ``position_id``,
    ``client_order_id``, ``leg``, ``attributed_net_long``,
    ``working_sell_qty``, ``quantity``, ``limit_price``, ``rule``,
    ``expected_settlement_value``, ``decided_at_ns``, ``book_staleness_ns``,
    plus ``fee_coefficient`` -- added beyond the plan's enumerated list
    because the rule's own net-proceeds threshold (below) cannot be
    evaluated without it, and this object must fail fast on its OWN terms
    without depending on the caller having already re-derived the fee.

    ``__post_init__`` refuses (raises :class:`ExitAuthorizationRefusalError`):

    * ``quantity`` exceeding the remaining attributable long
      (``attributed_net_long - working_sell_qty``).
    * ``quantity != 1`` -- every exit order is pinned to exactly one
      contract (plan §1, §0: partial fills cannot occur; qty == 1 is pinned
      at ``submit_chain.py:295-296``).
    * ``limit_price`` not strictly inside ``(0, 1)``.
    * a missing or empty ``position_id``.
    * for ``ExitRule.R_THREAT``: net proceeds (``limit_price * quantity -
      exit_fee(limit_price, quantity, fee_coefficient)``) not strictly
      greater than ``expected_settlement_value`` -- an exit that clears no
      more than the archive already expects from holding is not a
      registered improvement (plan §1 C3).
    * for ``ExitRule.R_DEAD``: net proceeds not strictly positive (plan §1:
      ``E[settlement | DEAD] ~= 0``, so any positive recovery clears the
      backstop's own bar).
    """

    family_id: str
    position_id: str
    client_order_id: str
    leg: Leg
    attributed_net_long: int
    working_sell_qty: int
    quantity: int
    limit_price: Decimal
    rule: ExitRule
    expected_settlement_value: Decimal
    fee_coefficient: Decimal
    decided_at_ns: int
    book_staleness_ns: int

    def __post_init__(self) -> None:
        if not self.position_id:
            raise ExitAuthorizationRefusalError(
                "refusing to authorise an exit with a missing/empty position_id"
            )
        if self.quantity != _PINNED_QUANTITY:
            raise ExitAuthorizationRefusalError(
                f"refusing to authorise an exit for quantity={self.quantity!r}; "
                f"every exit order is pinned to exactly {_PINNED_QUANTITY} contract"
            )
        remaining = self.attributed_net_long - self.working_sell_qty
        if self.quantity > remaining:
            raise ExitAuthorizationRefusalError(
                f"refusing to authorise an exit for {self.quantity} contract(s) against "
                f"position {self.position_id!r}: only {remaining} remains attributable "
                f"(attributed_net_long={self.attributed_net_long}, "
                f"working_sell_qty={self.working_sell_qty})"
            )
        if not (_ZERO < self.limit_price < _ONE):
            raise ExitAuthorizationRefusalError(
                f"refusing to authorise an exit at limit_price={self.limit_price!r}: "
                "must be strictly inside (0, 1)"
            )

        net_proceeds = self.limit_price * self.quantity - exit_fee(
            self.limit_price, self.quantity, self.fee_coefficient
        )
        if self.rule is ExitRule.R_THREAT:
            if not (net_proceeds > self.expected_settlement_value):
                raise ExitAuthorizationRefusalError(
                    f"refusing an R_THREAT exit for position {self.position_id!r}: "
                    f"net proceeds {net_proceeds!r} do not exceed the archive's own "
                    f"hold expectation {self.expected_settlement_value!r}"
                )
        elif self.rule is ExitRule.R_DEAD:
            if not (net_proceeds > _ZERO):
                raise ExitAuthorizationRefusalError(
                    f"refusing an R_DEAD exit for position {self.position_id!r}: "
                    f"net proceeds {net_proceeds!r} are not strictly positive"
                )
        else:  # pragma: no cover - unreachable, `ExitRule` has exactly two members.
            raise ExitAuthorizationRefusalError(f"unreachable: rule={self.rule!r}")
