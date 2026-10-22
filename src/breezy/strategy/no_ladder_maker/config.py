"""``NoLadderMakerConfig`` -- the maker-sharp v1 StrategyConfig (ARM C2).

Operator-reserved dollar caps (maximum daily budget, maximum per position) are deliberately absent:
they are enforced by the execution client's ``DailySpendLedger`` and the permit, never by a field
here. ``allow_short`` stays False and a ``True`` is refused at construction. ``manage_gtd_expiry``
must be True: the GTD expiry is Nautilus' native managed timer, never a hand-rolled cancel.
``shadow_only`` defaults True (fail closed); its one non-literal origin is
``not live_orders.enabled`` in ``app/trade.py`` (the AST guard in
``test_shadow_only_false_is_only_the_gate_output``).
"""

from __future__ import annotations

from typing import Final

from nautilus_trader.trading.config import StrategyConfig

__all__ = [
    "CANCEL_DEADLINE_S",
    "DEFAULT_POLL_INTERVAL_S",
    "STALE_BOOK_S",
    "AllowShortNotPermittedError",
    "NoLadderMakerConfig",
]

#: The ``query_order`` poll cadence (plan section 3); the native ``open_check_interval_secs`` is
#: rejected in r3 (it would poll every open order the engine knows, not just ours).
DEFAULT_POLL_INTERVAL_S: Final[int] = 30

#: A cancel not acknowledged within this many seconds is re-queried and re-issued by the poll
#: (two poll intervals): a lost ack or a refused cancel can never leave a rest CANCELING forever.
CANCEL_DEADLINE_S: Final[int] = 60

#: Feed liveness bound: a post needs some Depth10 frame (any maker instrument) within this many
#: seconds. The order is non-post-only, so a silent feed whose ask has since dropped would TAKE.
STALE_BOOK_S: Final[int] = 5


class AllowShortNotPermittedError(ValueError):
    """Raised when ``allow_short`` is constructed ``True``; SHORT_YES is forbidden."""


class NoLadderMakerConfig(StrategyConfig, frozen=True):
    """One strategy instance serves every configured station (a single order book of rests)."""

    stations: tuple[str, ...] = ()
    shadow_only: bool = True
    allow_short: bool = False
    manage_gtd_expiry: bool = True
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S

    def __post_init__(self) -> None:
        if self.allow_short:
            raise AllowShortNotPermittedError(
                "allow_short must stay False; NO exposure only via the native NO instrument"
            )
        if not self.manage_gtd_expiry:
            raise ValueError("manage_gtd_expiry must stay True: the GTD expiry is the native timer")
        if not self.stations:
            raise ValueError("`stations` must name at least one station")
        if self.poll_interval_s < 1:
            raise ValueError(f"poll_interval_s must be >= 1, was {self.poll_interval_s!r}")
