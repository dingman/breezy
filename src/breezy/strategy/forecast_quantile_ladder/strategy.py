"""``ForecastQuantileLadderStrategy`` -- V1 D+1 taker, shadow-first (SL-12).

Plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §7 row SL-12.
**Not wired into ``app/trade.py`` in this slice** -- that composition-root
wiring (instrument subscription, venue/instrument resolution, and actually
calling ``self.submit_order``) is SL-13's job. This class exists, is a real
``nautilus_trader.trading.strategy.Strategy``, and is fully exercised through
:meth:`evaluate_snapshot` and :meth:`try_submit`, but SL-12 never sends an
order: every snapshot this slice evaluates is recorded as a SHADOW decision.

Guard shape matches ``ContinuousRungHoldStrategy`` exactly, by construction,
so SL-13's wiring is a constructor-argument change, never a rewrite:

* ``order_submission_permit: OrderSubmissionPermit | None`` -- the SAME
  phase-0 permit guard (``None`` = shadow-only, matches the "Phase 0 ...
  never arms anything" convention in ``continuous_strategy.py``).
* ``submit_veto: Callable[[], str | None] | None`` -- the SAME shape
  ``breezy.strategy.current_rung_hold.composition.family_halt_submit_veto``
  produces.
* ``fee_verified: Callable[[], bool] | None`` -- the SAME fee-drift-probe
  shape used before a live submission.

:meth:`try_submit` runs all three guards and, if every one passes, returns
the would-be submission's Take record rather than calling
``self.submit_order`` -- SL-12 has no instrument/venue resolution in scope,
so there is no ``Order`` object to build yet, and the exec client's deny
chain (``adapters/polymarket_us/exec/client.py:5327-5510``) is therefore
untouched by this file, byte-for-byte, exactly as the plan requires.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import date
from typing import Literal, Protocol, runtime_checkable

from nautilus_trader.trading.strategy import Strategy

from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.decision import Decision, Take, evaluate
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.quantile_density import Rung

__all__ = ["ForecastQuantileLadderStrategy", "SubmissionRefused"]


class SubmissionRefused(Exception):
    """Raised by nothing here -- callers use :meth:`try_submit`'s return value.

    Kept as a named type so a future caller that DOES want to raise on a
    refused guard has one ready, without inventing a new name at that call
    site.
    """


@runtime_checkable
class SupportsExpiresAtNs(Protocol):
    """The narrow surface this strategy needs from an order-submission permit.

    A real ``breezy.runtime.order_enablement.OrderSubmissionPermit`` (minted
    only by its own ``.issue()``, which requires the live operator-gate
    environment) satisfies this Protocol structurally -- SL-13's wiring
    passes one unmodified. Declaring the DEPENDENCY as a Protocol rather than
    importing the concrete unforgeable type keeps this module, and every
    test of it, from ever needing to touch the operator-reserved enablement
    environment (plan §8: never read or assign one) merely to exercise the
    guard ORDER below.
    """

    @property
    def expires_at_ns(self) -> int: ...


class ForecastQuantileLadderStrategy(Strategy):
    """Evaluates NBP quantile-vector snapshots against a sha-pinned artefact.

    Every evaluated snapshot is appended to :attr:`shadow_decisions` --
    plan §7 row SL-12: "logs every decision (keys and inputs) as a shadow
    decision log line."
    """

    def __init__(
        self,
        config: ForecastQuantileLadderConfig,
        *,
        quantile_actor: ForecastQuantileStateActor,
        artefact: CalibrationArtefact,
        ladder_cfg: LadderEvConfig,
        latch: QuantileLadderLatch | None = None,
        order_submission_permit: SupportsExpiresAtNs | None = None,
        submit_veto: Callable[[], str | None] | None = None,
        fee_verified: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(config)
        self._quantile_actor = quantile_actor
        self._artefact = artefact
        self._ladder_cfg = ladder_cfg
        self._latch = latch if latch is not None else QuantileLadderLatch()
        self._order_submission_permit = order_submission_permit
        self._submit_veto = submit_veto
        self._fee_verified = fee_verified
        self.shadow_decisions: list[Mapping[str, object]] = []

    def on_start(self) -> None:
        """No venue subscription in this slice -- see the module docstring."""

    def _permit_covers(self, now_ns: int) -> bool:
        permit = self._order_submission_permit
        return permit is not None and now_ns < permit.expires_at_ns

    def evaluate_snapshot(
        self,
        *,
        now_ns: int,
        station: str,
        climate_day: date,
        instrument_id: str,
        ladder: Sequence[Rung],
        rung_id: str,
        side: Literal["yes", "no"] = "yes",
        ask: float,
        fee_coefficient: float,
        slippage_floor_prob: float,
        h_hours: float,
        n_cell: int,
    ) -> Decision:
        """Evaluate one (station-day, rung, side) snapshot and log it.

        Reads the visible quantile vector from ``self._quantile_actor`` at
        ``now_ns`` -- never a catalog read, mirroring
        ``ForecastState``'s own actor-push pattern (WP-12 Seam D).
        """
        vector: ForecastQuantileVector | None = self._quantile_actor.state_for(
            station,
        ).value_at(now_ns)
        decision = evaluate(
            permit_covers=self._permit_covers(now_ns),
            vector=vector,
            station=station,
            climate_day=climate_day,
            instrument_id=instrument_id,
            ladder=ladder,
            rung_id=rung_id,
            side=side,
            ask=ask,
            fee_coefficient=fee_coefficient,
            slippage_floor_prob=slippage_floor_prob,
            h_hours=h_hours,
            n_cell=n_cell,
            cfg=self._ladder_cfg,
            artefact=self._artefact,
            latch=self._latch,
        )
        self.shadow_decisions.append(self._shadow_log_line(decision, now_ns=now_ns))
        return decision

    def _shadow_log_line(self, decision: Decision, *, now_ns: int) -> Mapping[str, object]:
        """Decision keys and inputs only -- never scored, never a catalog write.

        Plan §4.4 item 1: "The shadow log carries decision keys and decision
        inputs only." No settlement/CLI/P&L module is imported by this file.
        """
        return {"now_ns": now_ns, "kind": type(decision).__name__, **asdict(decision)}

    def try_submit(self, take: Take) -> str | None:
        """Run the phase-0 permit, family-halt-veto and fee-verified guards.

        Returns ``None`` on every guard passing (nothing is actually
        submitted in this slice -- see the module docstring), or the refusal
        reason string otherwise. Never calls ``self.submit_order``.
        """
        if self._order_submission_permit is None:
            return "phase0_permit_absent"
        if self._submit_veto is not None:
            veto_reason = self._submit_veto()
            if veto_reason is not None:
                return veto_reason
        if self._fee_verified is not None and not self._fee_verified():
            return "fee_unverified"
        return None
