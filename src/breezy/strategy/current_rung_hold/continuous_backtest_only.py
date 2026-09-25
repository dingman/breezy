"""``ContinuousRungHoldBacktestStrategy`` -- a BACKTEST-ONLY subclass of
``ContinuousRungHoldStrategy`` that can actually submit orders, for the v3
continuous-rung-hold paper-replay harness (SP-4).

Why a subclass, not a config toggle (mirrors ``backtest_only.py``'s v2
precedent)
-------------------------------------------------------------------------
``ContinuousRungHoldStrategy`` is Phase 0 by construction: a non-None
``order_submission_permit`` raises :class:`Phase0PermitForbiddenError`
unless the caller also passes ``phase0_permit_guard=False`` -- and even
THAT opt-in requires a genuine, sealed ``OrderSubmissionPermit`` from
``runtime.order_enablement`` (the single ``@final``/``_SEAL``-guarded
``issue()`` site). A backtest replay must never mint or hold one of those
(PERMIT ISOLATION) -- it needs its own, narrower, unforgeable escape hatch
instead.

This subclass never exposes an ``order_submission_permit`` parameter at
all: it always constructs the parent with ``order_submission_permit=None``
and ``phase0_permit_guard=True`` -- the parent's Phase 0 seal is left
byte-unmodified and stays reachable. Instead it carries its OWN private
flag (``_backtest_submit_enabled``, always ``True`` here, set once at
construction) and overrides :meth:`_submission_armed` to read that flag
rather than the (always-``None``) permit. Every one of the five call sites
``_submission_armed`` now gates -- the never-arm walk, the re-arm gate,
the attempt counter, the shadow-only IN_FLIGHT clear, and
``_maybe_submit``'s compound guard -- therefore takes the SAME armed
branch the live v3 node takes, with the ``SimulatedExchange`` as the only
different sink (L-1 verdict 3; the method-set pin below, plus the
one-importer and literal-name scans, are the barriers that keep this out
of a live node).

Two independent unforgeable barriers keep this out of a live node
-------------------------------------------------------------------
1. ``on_start`` asserts ``isinstance(self.clock, nautilus_trader.common.
   component.TestClock)``, logging an ERROR before raising
   :class:`ContinuousNotABacktestClockError` -- a mis-wiring into a live
   node (whose clock is a ``LiveClock``) fails LOUDLY at startup, not
   silently (one line more visible than the v2 precedent, defence in
   depth; the wrapper-propagation question v2's own precedent already
   settles is not re-opened here).
2. **One-importer pin.** This module has exactly ONE non-test importer:
   ``scripts/analysis/current_rung_hold_paper_replay.py``. Widening that
   set is exactly the kind of silent scope-creep L-22 exists to catch;
   see ``tests/unit/test_continuous_rung_hold_backtest_only.py``'s
   AST-based importer scan and exact-method-set pin.

Byte-inherited (never re-implemented; the falsifier the method-set pin
enforces): ``on_order_book_depth``, ``on_quote_tick``, ``on_data``,
``_hunt_tick``, ``_maybe_submit``, ``_rearm_permitted``,
``on_order_denied``, ``on_order_filled``, ``_consume_or_flag_duplicate``,
``_run_never_arm_walk``, ``_join_fill_to_station_day``, ``on_stop``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nautilus_trader.common.component import TestClock

from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

    from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
    from breezy.strategy.current_rung_hold.diagnostics_summary import DiagnosticsSummarySink
    from breezy.strategy.current_rung_hold.offer_tape import OfferTape
    from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch

__all__ = ["ContinuousNotABacktestClockError", "ContinuousRungHoldBacktestStrategy"]

_MODULE_NAME: Final[str] = "breezy.strategy.current_rung_hold.continuous_backtest_only"
_CLASS_NAME: Final[str] = "ContinuousRungHoldBacktestStrategy"


class ContinuousNotABacktestClockError(RuntimeError):
    """Raised at ``on_start`` when this strategy's clock is not a ``TestClock``.

    Defence in depth over the one-importer pin: even if this class were
    somehow wired into a live node, it refuses to run rather than
    submitting a real order through a code path never intended to reach
    ``PolymarketUSExecutionClient``.
    """


class ContinuousRungHoldBacktestStrategy(ContinuousRungHoldStrategy):
    """The v3 paper-replay driver's ONLY continuous-hunt strategy class.

    Every decision path is inherited VERBATIM from
    :class:`~breezy.strategy.current_rung_hold.continuous_strategy.ContinuousRungHoldStrategy`
    -- see the module docstring's byte-inherited list. Exactly three
    methods are overridden here: ``__init__``, ``on_start`` and
    ``_submission_armed`` (enforced by
    ``test_the_subclass_defines_exactly_three_methods``, an AST exact-set
    pin over this class's own ``ClassDef`` body).

    R-10 note (HF-4 integration): this harness's ``submit_order`` stub
    never opens a real account-wide submit intent, so
    ``TrialDayLatch.is_intent_open()`` is trivially ``False`` here --
    HF-4's stale-``IN_FLIGHT`` release (``_release_stale_inflight``) is
    therefore floor-only (the 120s ``_REARM_MIN_DELAY_NS`` gate), never
    intent-gated the way a live/resolver-slow node is. An accepted
    divergence from live, inert for IOC-only submissions (F-32).
    """

    def __init__(
        self,
        config: CurrentRungHoldConfig,
        *,
        trial_day_latch_factory: Callable[[], AbstractContextManager[TrialDayLatch]]
        | None = None,
        offer_tape: OfferTape | None = None,
        offer_tape_path: Path | None = None,
        position_evidence_reader: Callable[[], dict[str, object] | None] | None = None,
        diagnostics_summary: DiagnosticsSummarySink | None = None,
        build_sha: str = "unknown",
    ) -> None:
        # No `order_submission_permit` parameter exists on this
        # constructor -- PERMIT ISOLATION: this subclass can never be
        # handed one, forgeable or otherwise. The parent is always
        # constructed with `order_submission_permit=None` and
        # `phase0_permit_guard=True`, so `Phase0PermitForbiddenError`
        # stays reachable and untouched (L-2: no new capability at
        # construction -- `_submission_armed`, below, is where this
        # subclass's one deliberate behaviour change lives).
        super().__init__(
            config,
            trial_day_latch_factory=trial_day_latch_factory,
            order_submission_permit=None,
            offer_tape=offer_tape,
            offer_tape_path=offer_tape_path,
            position_evidence_reader=position_evidence_reader,
            phase0_permit_guard=True,
            diagnostics_summary=diagnostics_summary,
            build_sha=build_sha,
        )
        #: Internal, backtest-only submit gate. NEVER derived from a real
        #: `OrderSubmissionPermit` -- this subclass never holds one.
        self._backtest_submit_enabled: bool = True

    def on_start(self) -> None:
        if not isinstance(self.clock, TestClock):
            self.log.error(
                f"{_CLASS_NAME} may only be registered against a "
                "nautilus_trader.common.component.TestClock -- this "
                "subclass exists to exercise the continuous hunt path "
                "inside a BacktestEngine ONLY, got clock type "
                f"{type(self.clock).__name__!r}.",
            )
            raise ContinuousNotABacktestClockError(
                f"{_CLASS_NAME} may only be registered against a "
                "nautilus_trader.common.component.TestClock, got clock "
                f"type {type(self.clock).__name__!r}.",
            )
        super().on_start()

    def _submission_armed(self) -> bool:
        return self._backtest_submit_enabled
