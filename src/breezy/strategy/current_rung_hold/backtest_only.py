"""``CurrentRungHoldBacktestStrategy`` -- a BACKTEST-ONLY subclass that can
actually submit orders, for the 6b paper-replay harness.

Why a subclass, not a config toggle (converged peer review, 2026-09-04)
-------------------------------------------------------------------------
``CurrentRungHoldConfig.orders_enabled`` is refused ``True`` unconditionally
at construction (``config.py:237-241``, :class:`OrdersEnabledNotPermittedError`)
-- that pin, and the error class, stay BYTE-UNMODIFIED (L-22: a safety
primitive's exclusion must be unforgeable, not offered). A backtest replay
that needs the fill path therefore cannot flip that flag; it needs its OWN,
narrower, unforgeable escape hatch instead. This subclass carries its own
internal submit flag (``_backtest_submit_enabled``, always ``True`` here, set
once at construction, never read from ``config``) and overrides
:meth:`_maybe_submit` to check that flag rather than
``self._config.orders_enabled`` -- the parent's field, and the parent's
refusal, are never touched.

The backtest fills through ``SimulatedExchange``, never through
``PolymarketUSExecutionClient._submit_order`` (the R-4 live-submit refusal),
so this is not blocked on R-7's standing operator-enablement gate -- see
``docs/plans/PAPER_REPLAY_6B_BRIEF_2026-09-04.md``, "Converged peer review",
item 1.

Two independent unforgeable barriers keep this out of a live node
-------------------------------------------------------------------
1. ``on_start`` asserts ``isinstance(self.clock, nautilus_trader.common.
   component.TestClock)`` and raises :class:`NotABacktestClockError`
   otherwise -- a mis-wiring into a live node (whose clock is a
   ``LiveClock``) fails LOUDLY at startup, not silently.
2. **One-importer pin.** This module has exactly ONE non-test importer:
   ``scripts/analysis/current_rung_hold_paper_replay.py``. Widening that set
   is exactly the kind of silent scope-creep L-22 exists to catch; see
   ``tests/unit/test_current_rung_hold_backtest_only.py``'s AST-based
   importer scan (RED test 12).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nautilus_trader.common.component import TestClock
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId

from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
    from breezy.strategy.current_rung_hold.decision import Take
    from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch

__all__ = ["CurrentRungHoldBacktestStrategy", "NotABacktestClockError"]

_MODULE_NAME: Final[str] = "breezy.strategy.current_rung_hold.backtest_only"
_CLASS_NAME: Final[str] = "CurrentRungHoldBacktestStrategy"


class NotABacktestClockError(RuntimeError):
    """Raised at ``on_start`` when this strategy's clock is not a ``TestClock``.

    Defence in depth over the one-importer pin: even if this class were
    somehow wired into a live node, it refuses to run rather than
    submitting a real order through a code path never intended to reach
    ``PolymarketUSExecutionClient``.
    """


class CurrentRungHoldBacktestStrategy(CurrentRungHoldStrategy):
    """The paper-replay driver's ONLY strategy class. See the module docstring.

    Every decision path (``on_data``, ``on_quote_tick``, ``evaluate_decision``,
    the trial-day latch) is inherited VERBATIM from
    :class:`~breezy.strategy.current_rung_hold.strategy.CurrentRungHoldStrategy`
    -- the shipped decision logic is never re-implemented here (module
    docstring RED test 10: "the strategy object is the shipped one"). The
    only override is :meth:`_maybe_submit`, which is unreachable in the
    parent for a different reason (``orders_enabled`` refused ``True``) and
    is reachable here through this class's OWN flag instead.
    """

    def __init__(
        self,
        config: CurrentRungHoldConfig,
        *,
        trial_day_latch_factory: Callable[[], AbstractContextManager[TrialDayLatch]]
        | None = None,
    ) -> None:
        super().__init__(config, trial_day_latch_factory=trial_day_latch_factory)
        #: Internal, backtest-only submit gate. NEVER read from
        #: `self._config.orders_enabled` (which stays False, unforgeably,
        #: per L-22) -- this is a wholly separate escape hatch scoped to
        #: this one subclass.
        self._backtest_submit_enabled: bool = True

    def on_start(self) -> None:
        if not isinstance(self.clock, TestClock):
            raise NotABacktestClockError(
                f"{_CLASS_NAME} may only be registered against a "
                "nautilus_trader.common.component.TestClock -- this subclass "
                "exists to exercise the fill path inside a BacktestEngine "
                f"ONLY, got clock type {type(self.clock).__name__!r}.",
            )
        super().on_start()

    def _maybe_submit(self, instrument_id: str, decision: Take) -> None:
        if not self._backtest_submit_enabled:
            self.log.info(
                "TAKE recorded, no submit (backtest submit disabled): "
                f"{instrument_id} qty={decision.quantity} px={decision.limit_price}",
            )
            return
        nt_id = InstrumentId.from_str(instrument_id)
        instrument = self.cache.instrument(nt_id)
        if instrument is None:
            self.log.error(f"instrument vanished from cache: {instrument_id}")
            return
        order = self.order_factory.limit(
            instrument_id=nt_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(decision.quantity),
            price=instrument.make_price(decision.limit_price),
            time_in_force=TimeInForce.IOC,
            post_only=False,
        )
        self.submit_order(order)
