"""``ForecastQuantileLadderStrategy`` -- V1 D+1 taker, shadow-first (SL-12/13).

Plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §7 rows SL-12
and SL-13. SL-13 wires this class into ``app/trade.py`` (a new
``forecast_quantile_ladder`` composition_kind branch, shadow-only: every
manifest naming it stays ``DRAFT_NOT_REGISTERED``, so it never becomes the
sending family) and adds :meth:`on_start` (instrument subscription and
YES/NO-per-rung resolution) and :meth:`_maybe_submit` (the native
order-submission path, gated by :meth:`try_submit`) below. Every SL-12
guard/decision surface (:meth:`evaluate_snapshot`, :meth:`try_submit`,
``decision.py``) is unmodified -- SL-13 adds a constructor-optional
``instrument_ids`` argument and two new methods, never a rewrite.

Guard shape matches ``ContinuousRungHoldStrategy`` exactly, by construction:

* ``order_submission_permit: OrderSubmissionPermit | None`` -- the SAME
  phase-0 permit guard (``None`` = shadow-only, matches the "Phase 0 ...
  never arms anything" convention in ``continuous_strategy.py``).
* ``submit_veto: Callable[[], str | None] | None`` -- the SAME shape
  ``breezy.strategy.current_rung_hold.composition.family_halt_submit_veto``
  produces.
* ``fee_verified: Callable[[], bool] | None`` -- the SAME fee-drift-probe
  shape used before a live submission.

:meth:`try_submit` runs all three guards and returns ``None`` iff every one
passes, else the refusal reason string -- never itself submitting anything.
SL-13's :meth:`_maybe_submit` is the ONE caller that acts on that result: on
a clear ``try_submit``, it resolves the take's instrument from ``self.cache``
and calls ``self.submit_order`` through the SAME ``order_factory.limit(...)``
shape ``ContinuousRungHoldStrategy._maybe_submit`` uses -- the exec client's
deny chain (``adapters/polymarket_us/exec/client.py:5327-5510``) is
therefore reached the SAME way v3 reaches it, never a second code path, and
stays untouched, byte-for-byte, by this file either way.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol, cast, runtime_checkable

from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.symbology import leg_of, sibling_instrument_id
from breezy.domain.weather_bucket_facts import Measure, read_weather_bucket_facts
from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.decision import (
    Decision,
    SidedAsk,
    Take,
    decision_log_fields,
    evaluate,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.forecast_quantile_ladder.persistent_latch import SupportsQuantileLatch
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.quantile_density import Rung

__all__ = ["ForecastQuantileLadderStrategy", "SupportsExpiresAtNs"]

_CLASS_NAME: str = "ForecastQuantileLadderStrategy"


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
        bounds_provider: BoundsProvider,
        latch: SupportsQuantileLatch | None = None,
        order_submission_permit: SupportsExpiresAtNs | None = None,
        submit_veto: Callable[[], str | None] | None = None,
        fee_verified: Callable[[], bool] | None = None,
        instrument_ids: Sequence[str | InstrumentId] = (),
    ) -> None:
        super().__init__(config)
        self._quantile_actor = quantile_actor
        self._artefact = artefact
        self._ladder_cfg = ladder_cfg
        self._bounds_provider = bounds_provider
        self._latch = latch if latch is not None else QuantileLadderLatch()
        self._order_submission_permit = order_submission_permit
        self._submit_veto = submit_veto
        self._fee_verified = fee_verified
        #: SL-13: candidate YES-leg instrument ids to resolve from
        #: ``self.cache`` at :meth:`on_start`. Never a msgspec ``StrategyConfig``
        #: field (mirrors ``order_submission_permit``/``submit_veto``/
        #: ``fee_verified`` immediately above) -- plain constructor state, not
        #: serialised, not operator-reserved.
        self._instrument_ids: tuple[str | InstrumentId, ...] = tuple(instrument_ids)
        #: ``(station, climate_day.isoformat(), rung_id) -> (yes_id, no_id)``,
        #: populated at :meth:`on_start`. Read-only outside this class; a
        #: driver evaluating a snapshot resolves the sided instrument id here
        #: before building the :class:`~breezy.strategy.forecast_quantile_ladder.decision.SidedAsk`
        #: ``evaluate_snapshot`` needs.
        self.rung_instruments: dict[tuple[str, str, str], tuple[str, str]] = {}
        #: ``(station, climate_day.isoformat()) -> [Rung, ...]``, populated at
        #: :meth:`on_start` from the resolved YES-leg instruments' own weather
        #: bucket facts.
        self.rung_ladders: dict[tuple[str, str], list[Rung]] = {}
        self.shadow_decisions: list[Mapping[str, object]] = []

    def on_start(self) -> None:
        """Resolve YES/NO instrument ids per rung and subscribe (SL-13).

        For each configured id already present in ``self.cache`` (the node's
        instrument provider populates the cache before any strategy starts,
        exactly as ``ContinuousRungHoldStrategy.on_start`` relies on): skip a
        non-HIGH measure, skip a station outside ``self.config.stations``,
        skip a bare NO id (its YES sibling resolves it below, via
        :func:`~breezy.adapters.polymarket_us.symbology.sibling_instrument_id`
        -- never registering the same rung twice). Every accepted YES id is
        subscribed for quotes and depth and recorded into
        :attr:`rung_instruments`/:attr:`rung_ladders`.

        Never calls :meth:`_maybe_submit` or ``self.submit_order`` itself --
        this method only subscribes and resolves; a decision-evaluating
        driver (an ``on_quote_tick``/``on_data`` handler, or a test/backtest
        caller) is what turns a :class:`~breezy.strategy.forecast_quantile_ladder.decision.Take`
        into a submission, via :meth:`_maybe_submit`.
        """
        for raw_id in self._instrument_ids:
            instrument_id = (
                InstrumentId.from_str(raw_id) if isinstance(raw_id, str) else raw_id
            )
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.warning(
                    f"no instrument {instrument_id} in the cache; skipping subscription",
                )
                continue
            facts = read_weather_bucket_facts(instrument.info)
            if facts.measure is not Measure.HIGH:
                self.log.warning(
                    f"{instrument_id} measures {facts.measure.value!r}; this "
                    "strategy trades HIGH only, skipping subscription.",
                )
                continue
            if facts.settlement_station not in self.config.stations:
                self.log.warning(
                    f"{instrument_id} settles {facts.settlement_station!r}, outside "
                    f"{self.config.stations!r}; skipping subscription.",
                )
                continue
            if leg_of(instrument_id) != "yes":
                # The NO leg is resolved from its YES sibling below -- a bare
                # NO id in `instrument_ids` would otherwise register the
                # SAME rung twice.
                continue
            no_instrument_id = sibling_instrument_id(instrument_id)
            climate_day_key = facts.climate_day.isoformat()
            rung_id = f"{facts.lower_f if facts.lower_f is not None else 'lt'}_" \
                f"{facts.upper_f if facts.upper_f is not None else 'gte'}"
            self.rung_instruments[(facts.settlement_station, climate_day_key, rung_id)] = (
                str(instrument_id),
                str(no_instrument_id),
            )
            self.rung_ladders.setdefault((facts.settlement_station, climate_day_key), []).append(
                Rung(rung_id=rung_id, lo=facts.lower_f, hi=facts.upper_f),
            )
            self.subscribe_quote_ticks(instrument_id)
            self.subscribe_order_book_depth(instrument_id)
            self.log.info(f"{_CLASS_NAME} subscribed {instrument_id}")
        self.log.info(f"{_CLASS_NAME} subscribed")

    def _permit_covers(self, now_ns: int) -> bool:
        permit = self._order_submission_permit
        return permit is not None and now_ns < permit.expires_at_ns

    def evaluate_snapshot(
        self,
        *,
        now_ns: int,
        std_utc_offset_hours: float,
        station: str,
        climate_day: date,
        ladder: Sequence[Rung],
        rung_id: str,
        side: Literal["yes", "no"] = "yes",
        ask: SidedAsk,
        fee_coefficient: float,
        slippage_floor_prob: float,
        h_hours: float,
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
            now_ns=now_ns,
            std_utc_offset_hours=std_utc_offset_hours,
            permit_covers=self._permit_covers(now_ns),
            vector=vector,
            station=station,
            climate_day=climate_day,
            ladder=ladder,
            rung_id=rung_id,
            side=side,
            ask=ask,
            fee_coefficient=fee_coefficient,
            slippage_floor_prob=slippage_floor_prob,
            h_hours=h_hours,
            cfg=self._ladder_cfg,
            artefact=self._artefact,
            bounds_provider=self._bounds_provider,
            # `decision.evaluate` (SL-12, unmodified) types `latch` nominally
            # as `QuantileLadderLatch`; SL-13 widens THIS class's own
            # constructor to accept any `SupportsQuantileLatch` (so a
            # `PersistentQuantileLadderLatch` type-checks too) -- `evaluate`
            # only ever calls `is_latched`/`latch` on it (both members of
            # that Protocol), so this cast is type-only, never a runtime
            # behaviour change.
            latch=cast("QuantileLadderLatch", self._latch),
        )
        self.shadow_decisions.append(self._shadow_log_line(decision, now_ns=now_ns))
        return decision

    def _shadow_log_line(self, decision: Decision, *, now_ns: int) -> Mapping[str, object]:
        """Decision keys and inputs only -- never scored, never a catalog write.

        Plan §4.4 item 1: "The shadow log carries decision keys and decision
        inputs only." No settlement/CLI/P&L module is imported by this file.
        Serialised via :func:`decision_log_fields`, never ``dataclasses.
        asdict`` -- that is banned repo-wide outside the closed allowlist in
        ``tests/unit/test_polymarket_us_credential_serialization.py``.
        """
        return {
            "now_ns": now_ns,
            "kind": type(decision).__name__,
            **decision_log_fields(decision),
        }

    def try_submit(self, take: Take) -> str | None:
        """Run the phase-0 permit, family-halt-veto and fee-verified guards.

        Returns ``None`` on every guard passing, or the refusal reason
        string otherwise. Never itself calls ``self.submit_order`` -- see
        :meth:`_maybe_submit`, SL-13's one caller that acts on this result.
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

    def _maybe_submit(self, take: Take, *, limit_price: Decimal) -> None:
        """SL-13: the native order-submission path. Runs :meth:`try_submit`
        first and returns without reaching ``self.submit_order`` on any
        refusal (including ``order_submission_permit is None`` -- the guard
        this class was built to enforce, plan §8).

        ``limit_price`` is the caller's own already-evaluated ask price
        (the SAME :class:`~breezy.strategy.forecast_quantile_ladder.decision.SidedAsk.price`
        that produced ``take`` -- ``Take`` itself carries no price field, by
        SL-12 design). Mirrors ``ContinuousRungHoldStrategy._maybe_submit``'s
        ``order_factory.limit(...)`` shape exactly: IOC, not post-only, qty
        from ``take.qty`` (always 1, plan §3.3).
        """
        refusal = self.try_submit(take)
        if refusal is not None:
            self.log.info(
                "TAKE recorded, no submit "
                f"(refusal={refusal}): {take.instrument_id} qty={take.qty} "
                f"px={limit_price} p_hat={take.p_hat} ev_net={take.ev_net}",
            )
            return
        nt_id = InstrumentId.from_str(take.instrument_id)
        instrument = self.cache.instrument(nt_id)
        if instrument is None:
            self.log.error(f"instrument vanished from cache: {take.instrument_id}")
            return
        order = self.order_factory.limit(
            instrument_id=nt_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(Decimal(take.qty)),
            price=instrument.make_price(limit_price),
            time_in_force=TimeInForce.IOC,
            post_only=False,
        )
        self.submit_order(order)
