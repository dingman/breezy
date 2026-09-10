"""``ContinuousRungHoldStrategy`` -- Phase 0 shadow hunter.

Sibling of ``CurrentRungHoldStrategy``. Shares ``decision.py`` (via
``tick_eval``) only. Hunts every eligible in-window quote; retry-set
refusals never consume a TRIAL; ``illegal_cell`` is counted once per
station-day and surfaced on ``on_stop``. IN_FLIGHT is committed in the
latch primitive before ``_maybe_submit``. Phase 0 constructs this with
``order_submission_permit=None``, so ``_maybe_submit`` logs and returns
without reaching ``submit_order``.

No ``LiveClock`` timer (L-16). ``on_data`` re-evaluates the pinned last
tick with guards, else skips.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.errors import FeeScheduleUnknownError
from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known
from breezy.domain.station_observation import StationObservation
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherBucketFacts,
    read_weather_bucket_facts,
)
from breezy.ingest.iem_observations import station_observation_data_type
from breezy.registry.sites import default_registry
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.runtime.order_enablement import OrderSubmissionPermit
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import Decision, Refuse, Take
from breezy.strategy.current_rung_hold.offer_tape import OfferTape, OfferTapeRecord
from breezy.strategy.current_rung_hold.strategy import (
    _DIAG_NO_RUNNING_MAX_YET,
    _DIAG_NOT_EXECUTABLE,
    _DIAG_RUNG_NOT_CURRENT,
    _INSTRUMENT_UNRESOLVED,
    _OUTSIDE_DECISION_WINDOW,
    _STATION_BY_ICAO,
    _VENUE,
    _WINDOW_END_HOUR_LST,
    _WINDOW_START_HOUR_LST,
    MissingTrialDayLatchError,
    _local_hour,
)
from breezy.strategy.current_rung_hold.tick_eval import (
    evaluate_eligible_snapshot,
    instrument_rung_is_current,
    width_and_m,
)
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch
from breezy.strategy.depth10 import best_order
from breezy.strategy.weather_common.refusals import RefusalAlerter, RefusalCounter
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
    from nautilus_trader.model.instruments import Instrument

__all__ = ["ContinuousRungHoldStrategy", "Phase0PermitForbiddenError"]

_NS_PER_MINUTE: Final[int] = 60_000_000_000
_CLASS_NAME: Final[str] = "ContinuousRungHoldStrategy"
Trigger = Literal["quote_tick", "on_data", "depth"]
Source = Literal["quote", "depth"]


@dataclass(frozen=True, slots=True)
class _AskSnapshot:
    """The minimal ask-side view `_hunt_tick` needs, from either a `QuoteTick`
    or a `OrderBookDepth10` ask level (Phase 0b). `tick_eval.py` stays typed
    on primitives only -- this is the one construction seam that lets
    `_hunt_tick` treat the two sources identically.
    """

    instrument_id: InstrumentId
    ask: Decimal
    size: int
    ts_event: int
    source: Source


def _snapshot_from_quote(tick: QuoteTick) -> _AskSnapshot:
    return _AskSnapshot(
        instrument_id=tick.instrument_id,
        ask=tick.ask_price.as_decimal(),
        size=int(tick.ask_size),
        ts_event=tick.ts_event,
        source="quote",
    )


class Phase0PermitForbiddenError(RuntimeError):
    """A non-None `order_submission_permit` was given in Phase 0.

    Phase 0 mints every `ContinuousRungHoldStrategy` (and its composition
    root, `build_continuous_rung_hold_strategies`) with `permit=None`; v3
    never holds the sealed order-submission capability while Phase 0 is in
    force (see `composition.py::phase0_family_permits`).
    """


class ContinuousRungHoldStrategy(Strategy):
    """Hunt every eligible in-window snapshot; Phase 0 never submits."""

    def __init__(
        self,
        config: CurrentRungHoldConfig,
        *,
        trial_day_latch_factory: Callable[[], AbstractContextManager[TrialDayLatch]]
        | None = None,
        order_submission_permit: OrderSubmissionPermit | None = None,
        offer_tape: OfferTape | None = None,
        offer_tape_path: Path | None = None,
    ) -> None:
        if order_submission_permit is not None:
            raise Phase0PermitForbiddenError(
                "ContinuousRungHoldStrategy: Phase 0 forbids a non-None "
                "order_submission_permit"
            )
        super().__init__(config)
        self._config: CurrentRungHoldConfig = config
        self._latch_factory = trial_day_latch_factory
        self._order_submission_permit = order_submission_permit
        self._latch: TrialDayLatch | None = None
        self._exit_stack: ExitStack | None = None
        self._facts: dict[str, WeatherBucketFacts] = {}
        self._ladders: dict[tuple[str, str], list[tuple[int | None, int | None]]] = {}
        self._accumulators: dict[str, RunningExtremeAccumulator] = {}
        self._std_utc_offset_hours_by_station: dict[str, float] = {}
        self.refusals = RefusalCounter()
        self.diagnostics = RefusalCounter()
        self.refusal_alerter: RefusalAlerter | None = None
        self.diagnostics_alerter: RefusalAlerter | None = None
        self.position_events = RefusalCounter()
        self.position_alerter: RefusalAlerter | None = None
        self._illegal_cell_station_days: set[tuple[str, str]] = set()
        self._eligible_snap_counts: dict[tuple[str, str], int] = {}
        self._fee_halt = False
        self.offer_tape = offer_tape if offer_tape is not None else OfferTape(offer_tape_path)
        # De-dupe key for the LAST ask evaluated per instrument, so a WS frame
        # that yields BOTH a QuoteTick and an OrderBookDepth10 (identical
        # ts_event -- same frame) is hunted once. One entry per instrument,
        # not a growing set: `on_data` retries deliberately re-evaluate the
        # SAME cached quote on a later weather update, so only the two live
        # push triggers ("quote_tick", "depth") ever consult or update this.
        self._last_ask_seen: dict[str, tuple[int, Decimal, int]] = {}

    def on_start(self) -> None:
        if self._latch_factory is None:
            raise MissingTrialDayLatchError(
                "ContinuousRungHoldStrategy was constructed with no "
                "trial_day_latch_factory; see the module docstring."
            )
        exit_stack = ExitStack()
        self._latch = exit_stack.enter_context(self._latch_factory())
        self._exit_stack = exit_stack

        registry = default_registry()
        self._std_utc_offset_hours_by_station = {
            station: registry.climate_day_window(_VENUE, station).std_utc_offset_hours
            for station in self._config.stations
        }

        resolved_any = False
        for instrument_id in self._config.instrument_ids:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.warning(
                    f"no instrument {instrument_id} in the cache; skipping "
                    "subscription (refusal: instrument_unresolved)",
                )
                self.refusals.record(_INSTRUMENT_UNRESOLVED)
                continue
            resolved_any = True
            facts = read_weather_bucket_facts(instrument.info)
            if facts.measure is not Measure.HIGH:
                self.log.warning(
                    f"{instrument_id} measures {facts.measure.value!r}; this package "
                    "trades HIGH only, skipping subscription.",
                )
                continue
            if facts.settlement_station not in self._config.stations:
                self.log.warning(
                    f"{instrument_id} settles {facts.settlement_station!r}, outside "
                    f"{self._config.stations!r}; skipping subscription.",
                )
                continue
            iid = str(instrument_id)
            self._facts[iid] = facts
            key = (facts.settlement_station, facts.climate_day.isoformat())
            self._ladders.setdefault(key, []).append((facts.lower_f, facts.upper_f))
            self.subscribe_quote_ticks(instrument_id)
            self.subscribe_order_book_depth(instrument_id)
            self.log.info(f"{_CLASS_NAME} subscribed {instrument_id}")

        if self._config.instrument_ids and not resolved_any:
            self.log.error("no configured instrument resolved from the cache; stopping")
            self.stop()
            return

        self.subscribe_data(
            station_observation_data_type(), client_id=NWS_BACKTEST_CLIENT_ID,
        )

    def on_stop(self) -> None:
        self.log.info(self._diagnostics_snapshot_message())
        self.log.info(self._illegal_cell_snapshot_message())
        for iid in self._facts:
            self.unsubscribe_order_book_depth(InstrumentId.from_str(iid))
        exit_stack, self._exit_stack = self._exit_stack, None
        self._latch = None
        if exit_stack is not None:
            exit_stack.close()

    def _diagnostics_snapshot_message(self) -> str:
        counts = dict(sorted(self.diagnostics.counts.items()))
        return f"continuous_rung_hold diagnostics snapshot: {counts}"

    def _illegal_cell_snapshot_message(self) -> str:
        n = len(self._illegal_cell_station_days)
        return f"continuous_rung_hold illegal_cell once-count: {n}"

    def on_data(self, data: Data) -> None:
        if type(data) is not StationObservation:
            return
        station = _STATION_BY_ICAO.get(data.station)
        if station is None or station not in self._config.stations:
            return
        offset = self._std_utc_offset_hours_by_station[station]
        accumulator = self._accumulators.setdefault(
            station, RunningExtremeAccumulator(std_utc_offset_hours=offset),
        )
        accumulator.push(
            data.observed_at_ns,
            data.temp_c_tenths,
            data.precision_c_tenths,
            data.is_metar,
            data.received_at_ns,
        )
        stale_bound_ns = self._config.stale_observation_minutes * _NS_PER_MINUTE
        for iid, facts in self._facts.items():
            if facts.settlement_station != station:
                continue
            last = self.cache.quote_tick(InstrumentId.from_str(iid))
            if last is None:
                continue
            if last.ts_event > data.received_at_ns:
                continue
            age = data.received_at_ns - last.ts_event
            if age > stale_bound_ns:
                continue
            self._hunt_tick(_snapshot_from_quote(last), trigger="on_data", quote_age_ns=age)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._hunt_tick(_snapshot_from_quote(tick), trigger="quote_tick", quote_age_ns=None)

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        """Hunt on the venue's own Depth10 ask when quotes go dark (L-35).

        A one-sided book (no bid) never produces a `QuoteTick`
        (`parse_quote_tick` requires both sides) but still carries a real,
        executable ask -- `best_order` skips the size-0 Arrow pad.
        """
        ask = best_order(depth.asks)
        if ask is None:
            return
        snapshot = _AskSnapshot(
            instrument_id=depth.instrument_id,
            ask=ask.price.as_decimal(),
            size=int(ask.size),
            ts_event=depth.ts_event,
            source="depth",
        )
        self._hunt_tick(snapshot, trigger="depth", quote_age_ns=None)

    def _hunt_tick(
        self,
        snapshot: _AskSnapshot,
        *,
        trigger: Trigger,
        quote_age_ns: int | None,
    ) -> None:
        if self._fee_halt:
            return
        iid = str(snapshot.instrument_id)
        facts = self._facts.get(iid)
        if facts is None:
            return

        # De-dupe the two LIVE push triggers only (`quote_tick`, `depth`): a
        # single WS frame can yield both a QuoteTick and an OrderBookDepth10
        # with an identical (ts_event, ask, size). `on_data` deliberately
        # re-evaluates the SAME cached quote on a later weather update and
        # must never be short-circuited by this.
        if trigger in ("quote_tick", "depth"):
            dedupe_key = (snapshot.ts_event, snapshot.ask, snapshot.size)
            if self._last_ask_seen.get(iid) == dedupe_key:
                return
            self._last_ask_seen[iid] = dedupe_key

        station = facts.settlement_station
        climate_day = facts.climate_day
        climate_day_key = climate_day.isoformat()
        station_day = (station, climate_day_key)

        assert self._latch is not None
        if self._latch.is_consumed(station, climate_day_key):
            return
        if self._latch.is_inflight(station, climate_day_key):
            return

        now_ns = snapshot.ts_event
        offset = self._std_utc_offset_hours_by_station[station]
        hour_lst = _local_hour(now_ns, offset)
        if not (_WINDOW_START_HOUR_LST <= hour_lst < _WINDOW_END_HOUR_LST):
            self.refusals.record(_OUTSIDE_DECISION_WINDOW)
            self._report_alerter(
                self.refusal_alerter,
                "continuous_rung_hold refusal report failed",
            )
            return

        ask = snapshot.ask
        size = snapshot.size
        raw_executable = (
            self._config.executable_ask_lower < ask < self._config.executable_ask_upper
            and size >= self._config.minimum_displayed_size
        )
        if not raw_executable:
            self.diagnostics.record(_DIAG_NOT_EXECUTABLE)
            self._report_alerter(
                self.diagnostics_alerter,
                "continuous_rung_hold diagnostics report failed",
            )
            return

        accumulator = self._accumulators.get(station)
        running_max = None if accumulator is None else accumulator.value_at(now_ns)
        if running_max is None or accumulator is None:
            self.diagnostics.record(_DIAG_NO_RUNNING_MAX_YET)
            self._report_alerter(
                self.diagnostics_alerter,
                "continuous_rung_hold diagnostics report failed",
            )
            return
        if not instrument_rung_is_current(facts, running_max):
            self.diagnostics.record(_DIAG_RUNG_NOT_CURRENT)
            self._report_alerter(
                self.diagnostics_alerter,
                "continuous_rung_hold diagnostics report failed",
            )
            return

        width_code, m_code = width_and_m(facts, running_max)
        instrument = self.cache.instrument(snapshot.instrument_id)
        fee_coefficient = self._guarded_fee_coefficient(instrument)
        decision: Decision = evaluate_eligible_snapshot(
            station=station,
            climate_day=climate_day,
            now_ns=now_ns,
            ladder=self._ladders[(station, climate_day_key)],
            fee_coefficient=fee_coefficient,
            ask=ask,
            size=size,
            running_max=running_max,
            staleness_ns=accumulator.staleness_ns(now_ns),
            config=self._config,
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
        )

        reason = decision.reason if isinstance(decision, Refuse) else "taken"
        prior = self._eligible_snap_counts.get(station_day, 0)
        illegal = isinstance(decision, Refuse) and decision.reason == "illegal_cell"
        self.offer_tape.append(
            OfferTapeRecord(
                station=station,
                climate_day=climate_day_key,
                instrument_id=iid,
                ask=str(ask),
                size=size,
                reason=reason,
                ts_event=now_ns,
                hour_lst=hour_lst,
                width_code=width_code,
                m_code=m_code,
                trigger=trigger,
                quote_age_ns=quote_age_ns,
                minutes_since_window_open=max(0, hour_lst - _WINDOW_START_HOUR_LST) * 60,
                prior_eligible_snaps=prior,
                illegal_cell=illegal,
                source=snapshot.source,
            )
        )
        self._eligible_snap_counts[station_day] = prior + 1

        if isinstance(decision, Refuse):
            if decision.reason == "fee_schedule_mismatch":
                self.refusals.record(decision.reason)
                self._fee_halt = True
                self._report_alerter(
                    self.refusal_alerter,
                    "continuous_rung_hold refusal report failed",
                )
                return
            if decision.reason == "illegal_cell":
                if station_day not in self._illegal_cell_station_days:
                    self._illegal_cell_station_days.add(station_day)
                    self.refusals.record(decision.reason)
                    self._report_alerter(
                        self.refusal_alerter,
                        "continuous_rung_hold refusal report failed",
                    )
                return
            self.refusals.record(decision.reason)
            self._report_alerter(
                self.refusal_alerter,
                "continuous_rung_hold refusal report failed",
            )
            return

        self._latch.set_inflight(station, climate_day_key)
        self._maybe_submit(iid, decision)
        if self._order_submission_permit is None:
            self._latch.clear_inflight(station, climate_day_key)

    def _report_alerter(
        self,
        alerter: RefusalAlerter | None,
        fail_message: str,
    ) -> tuple[object, ...] | None:
        if alerter is None:
            return ()
        result = self._run_observability(
            fail_message,
            lambda: alerter.report_payloads(now_ns=self.clock.timestamp_ns()),
        )
        if result is None:
            return None
        return tuple(result)  # type: ignore[arg-type]

    def _run_observability(self, message: str, action: Callable[[], object]) -> object:
        try:
            return action()
        except Exception as exc:
            self.log.exception(message, exc)  # noqa: TRY401
            return None

    def _guarded_fee_coefficient(self, instrument: Instrument | None) -> Decimal | None:
        if instrument is None:
            return None
        try:
            assert_fee_schedule_known(instrument)
        except FeeScheduleUnknownError:
            return None
        fee = instrument.maker_fee
        return fee if isinstance(fee, Decimal) else None

    def _maybe_submit(self, instrument_id: str, decision: Take) -> None:
        if not (
            self._order_submission_permit is not None
            and isinstance(self._config.stale_observation_minutes, int)
        ):
            self.log.info(
                "TAKE recorded, no submit "
                f"(order_submission_permit="
                f"{'granted' if self._order_submission_permit is not None else 'none'}): "
                f"{instrument_id} qty={decision.quantity} px={decision.limit_price} "
                f"p_hold_lower={decision.p_hold_lower} break_even={decision.break_even}",
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
