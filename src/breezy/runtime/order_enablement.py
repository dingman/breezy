"""The sealed, unforgeable capability that gates the first live order submission.

L-22's rule is that the exclusive mechanism belongs in a safety primitive's
CONSTRUCTION path, never a sibling helper that could be skipped. This module
follows it: :class:`OrderSubmissionPermit` cannot exist unvalidated. Its
``__init__`` accepts a seal only ``issue`` holds, and ``issue`` IS the
constructor -- the five preconditions below run inside it, not beside it.

The security claim is data-unforgeability, not secrecy of the seal object.
A sealed object cannot be a field on a msgspec ``Struct``-based
``NautilusConfig`` (``common/config.py``), so a permit is reachable only from
running code, never decoded out of a persisted or replayed strategy config.
The AST barrier that makes this the guarantee -- pinning ``issue`` and the
one construction site to an exact, reviewed call-set -- lives in
``tests/unit/test_polymarket_us_readonly_guard.py`` (B11): one pin on
``OrderSubmissionPermit.issue``'s callers, one permanent pin on
``OrderSubmissionPermit(``'s construction sites (only ``issue`` itself may
construct it). ``issue`` has exactly one PRODUCTION caller,
``app/trade.py::main``; the pin also covers ``tests/`` and is alias-resolved
-- a rebind like ``_ISSUE = OrderSubmissionPermit.issue`` followed by
``_ISSUE(...)`` still counts as a call site of ``issue``, not a silent
evasion of the scanner. Residual, same class as B5/B8: dynamic ``getattr``
dispatch is not resolved.

``orders_enabled`` on ``CurrentRungHoldConfig`` is not, and can never be, this
capability: any bool or string field on a frozen msgspec config is exactly
reproducible by anyone who can write a config dict through
``ImportableStrategyConfig`` + ``StrategyFactory.create``. A value that can be
copied is not a capability -- only an object minted by code, and refused by
data, qualifies.

Five preconditions, not six. A sixth -- venue-credential completeness -- was
in the survey's design, gated on a ``credentials.is_complete()`` check
(``adapters/polymarket_us/credentials.py``). Neither ``app/trade.py`` nor
``runtime/trade_cli.py`` calls that check today, and the ``issue`` signature
given for this increment (``settings``, ``live_trading_permit``, ``clock``)
carries no credentials object -- adding one would be new surface beyond this
commit's scope. Dropped here; the actual submission path still gates on
credential completeness at D3 (``safety.assert_live_order_submission_permitted``),
independently of this permit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, final, runtime_checkable

from breezy.adapters.polymarket_us import write_transport
from breezy.adapters.polymarket_us.operator_controls import (
    operator_max_daily_budget_usd,
    operator_max_position_cost_usd,
)
from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError, LiveTradingPermit

__all__ = [
    "LiveTradingPermitNotValidError",
    "OperatorCapsNotConfiguredError",
    "OrderSubmissionPermit",
    "OrderSubmissionPermitForgeryError",
    "OrderSubmissionRefused",
    "OrdersNotRequestedError",
    "RungHoldNotReadyError",
    "SettingsNotSettingsLikeError",
    "WriteCanonicalStringUnverifiedError",
]

#: Module-private, never exported, never a default value for anything.
#: Reachable by any in-process code that imports this module -- that is an
#: accepted residual, the same trust boundary as the issuer key backing
#: ``safety``'s own authenticity tag. What makes a second grant impossible to
#: SHIP is the AST barrier (B11), not secrecy of this object.
_SEAL = object()


class OrderSubmissionPermitForgeryError(PermissionError):
    """Raised when ``OrderSubmissionPermit`` is built without the internal seal.

    This is an accidental-construction guard only -- ``issue`` is the real
    exclusivity mechanism (see the module docstring); this error exists so a
    caller that tries the obvious ``OrderSubmissionPermit(...)`` shape gets an
    explicit refusal instead of a confusing ``TypeError`` about a stray
    positional argument.
    """


class OrderSubmissionRefused(PermissionError):
    """Base class for a named refusal of one of ``issue``'s preconditions.

    Every subclass names the FAILED PRECONDITION only, never a value: no
    config content, no permit field, no cap amount ever appears in a message
    raised from here.
    """


class OrdersNotRequestedError(OrderSubmissionRefused):
    """The build-side enablement flag was not requested."""


class LiveTradingPermitNotValidError(OrderSubmissionRefused):
    """The supplied live-trading permit is not genuine, or has expired."""


class WriteCanonicalStringUnverifiedError(OrderSubmissionRefused):
    """The write-path canonical-string verification predicate is not True."""


class OperatorCapsNotConfiguredError(OrderSubmissionRefused):
    """The two operator-reserved caps are not both present and positive."""


class RungHoldNotReadyError(OrderSubmissionRefused):
    """The current-rung-hold / live-observations settings are not both set."""


class SettingsNotSettingsLikeError(OrderSubmissionRefused):
    """``settings`` does not structurally satisfy ``SettingsLike``.

    ``SettingsLike`` was declared ``runtime_checkable`` but never actually
    checked -- a plain object missing one of the three required attributes
    fell through to an ``AttributeError`` deep inside the precondition
    chain instead of a named refusal at the door.
    """


@runtime_checkable
class SettingsLike(Protocol):
    """The narrow surface ``issue`` needs from ``BreezyTradeSettings``.

    A ``Protocol`` rather than an import of the concrete settings type: this
    keeps the dependency duck-typed, so a small fake settings object is
    sufficient in a test, and this module never re-parses anything the
    settings loader already owns.
    """

    orders_enabled_requested: bool
    current_rung_hold: bool
    live_observations: bool


class ClockLike(Protocol):
    """The narrow surface ``issue`` needs from an injected clock."""

    def timestamp_ns(self) -> int: ...


@final
@dataclass(frozen=True, slots=True)
class OrderSubmissionPermit:
    """Unforgeable, minted-only-by-``issue`` approval to submit a live order.

    Not a msgspec ``Struct``: it must never be decodable out of persisted or
    replayed config bytes, and a ``NautilusConfig`` field must be msgspec-
    encodable, so this type structurally cannot become one.

    Every field is ``repr=False`` -- a permit is never logged by value.
    """

    seal: object = field(repr=False)
    expires_at_ns: int = field(repr=False, kw_only=True)
    operator_id: str = field(repr=False, kw_only=True)

    def __post_init__(self) -> None:
        if self.seal is not _SEAL:
            raise OrderSubmissionPermitForgeryError(
                "OrderSubmissionPermit is obtainable only from "
                "OrderSubmissionPermit.issue()"
            )

    @classmethod
    def issue(
        cls,
        *,
        settings: SettingsLike,
        live_trading_permit: LiveTradingPermit,
        clock: ClockLike,
    ) -> OrderSubmissionPermit:
        """Run every precondition and mint the permit, or refuse.

        Absence is always refusal, never a default. Each refusal names the
        failed precondition and never a value. This is the ONLY construction
        path -- the checks live here, in the construction path, not in a
        sibling helper (L-22).
        """
        if not isinstance(settings, SettingsLike):
            raise SettingsNotSettingsLikeError(
                "settings must satisfy the SettingsLike protocol"
            )

        if settings.orders_enabled_requested is not True:
            raise OrdersNotRequestedError(
                "orders_enabled_requested must be exactly True; enablement was "
                "not requested"
            )

        if not isinstance(live_trading_permit, LiveTradingPermit):
            raise LiveTradingPermitNotValidError(
                "live_trading_permit must be a genuine LiveTradingPermit issued "
                "by issue_live_trading_permit"
            )
        if clock.timestamp_ns() > live_trading_permit.expires_at_ns:
            raise LiveTradingPermitNotValidError("live_trading_permit has expired")

        if write_transport.WRITE_CANONICAL_STRING_VERIFIED is not True:
            raise WriteCanonicalStringUnverifiedError(
                "the write-path canonical-string verification predicate is not True"
            )

        try:
            operator_max_daily_budget_usd()
            operator_max_position_cost_usd()
        except LiveTradingPermissionError as exc:
            raise OperatorCapsNotConfiguredError(
                "both operator-reserved caps must be present and positive"
            ) from exc

        if settings.current_rung_hold is not True or settings.live_observations is not True:
            raise RungHoldNotReadyError(
                "current_rung_hold and live_observations must both be enabled"
            )

        # The construction call names the class directly, not ``cls``: the
        # B11 construction-site pin (test_polymarket_us_readonly_guard.py)
        # scans for a literal ``OrderSubmissionPermit(`` call, so this is the
        # one site it must find -- and ``@final`` means there is no subclass
        # for ``cls`` to legitimately differ from it.
        return OrderSubmissionPermit(
            _SEAL,
            expires_at_ns=live_trading_permit.expires_at_ns,
            operator_id=live_trading_permit.operator_id,
        )
