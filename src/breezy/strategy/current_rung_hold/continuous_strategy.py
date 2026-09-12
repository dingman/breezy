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
from nautilus_trader.model.events import OrderDenied, OrderFilled
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.errors import (
    ExecutionReportMappingError,
    FeeScheduleUnknownError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known
from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug, parse_weather_slug
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
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TAKEN_FROM_FILL_WALK_REASON,
    TrialDayLatch,
    TrialDayRecord,
    TrialDayRecordCorrupt,
    startup_evidence_confirms_absent_flat,
    startup_evidence_lists_slug,
    startup_evidence_permits_arm,
    startup_evidence_position_for,
)
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
#: Resolution B (plan rev 6.1): the account-wide OPEN-intent WAIT diagnostic.
#: Not a refusal -- reported through `diagnostics`/`diagnostics_alerter`
#: (the existing WAIT vocabulary), never `refusals`/`refusal_alerter`.
_DIAG_OPEN_INTENT_WAIT: Final[str] = "open_intent_wait"
#: Slice 4 item B1 (plan rev 6.1): the family-wide duplicate-fill halt WAIT.
_DIAG_FAMILY_HALT: Final[str] = "family_halt_duplicate_fill"
#: Slice 4 item E1 (plan rev 6.1, Resolution F): a re-arm gate WAIT.
_DIAG_REARM_WAIT: Final[str] = "rearm_wait"
#: Slice 4 items A1/A2 (plan rev 6.1): log-only position/fill events, never
#: a refusal and never a WAIT diagnostic -- reported through
#: `self.position_events`/`self.position_alerter`.
_POSITION_UNJOINABLE_FILL: Final[str] = "unjoinable_fill_halt"
_POSITION_STARTUP_EVIDENCE_MISSING: Final[str] = "startup_evidence_missing"
_POSITION_FILL_WALK_UNREADABLE: Final[str] = "fill_walk_unreadable"
_POSITION_UNRECONCILED_LONG: Final[str] = "unreconciled_long_no_fill"
_POSITION_FAMILY_HALT_AT_START: Final[str] = "family_halt_at_start"
#: Three-seam Slice 4 review item 1: a corrupt/unreadable latch read or
#: write inside `on_order_filled` -- fail closed, process-local, never raise.
_POSITION_FILL_JOIN_ERROR: Final[str] = "fill_join_error"
#: Review item 2: a legacy (pre-Slice-4) record with no `venue_order_id`
#: cannot prove a SECOND fill is genuinely a duplicate vs. its own replay --
#: logged, never halted.
_LEGACY_RECORD_NO_VENUE_ORDER_ID_WARNING: Final[str] = (
    "on_order_filled: {station}/{climate_day} already consumed by a legacy "
    "record with no venue_order_id; cannot determine duplicate-vs-replay, "
    "not halting the family"
)

#: Resolution F (plan rev 6.1): a documented conservative floor, not a
#: measurement -- see `v3plan_rev6.md`'s Resolution F and L-36/PREREG, which
#: declare it UNVERIFIED until the first `PositionReportingLag` record.
_REARM_MIN_DELAY_SECS: Final[int] = 120
_REARM_MIN_DELAY_NS: Final[int] = _REARM_MIN_DELAY_SECS * 1_000_000_000
#: Resolution F: a genuine fill freezes this counter (`is_consumed` short-
#: circuits `_hunt_tick` before the re-arm gate is ever consulted again).
_MAX_STATION_DAY_ATTEMPTS: Final[int] = 3

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
        position_evidence_reader: Callable[[], dict[str, object] | None] | None = None,
        phase0_permit_guard: bool = True,
    ) -> None:
        """``phase0_permit_guard=True`` (default) keeps Phase 0's seal: a
        non-None ``order_submission_permit`` raises
        :class:`Phase0PermitForbiddenError`. ``phase0_permit_guard=False`` is
        the Phase 1, continuous-only (no-shadow) opt-in a composition root
        may pass to construct this strategy WITH a real, sealed permit --
        ``_maybe_submit`` then genuinely calls ``submit_order``. This
        strategy never flips that default itself; only a caller (a
        composition root, or a test exercising the gated Phase 1 code paths
        directly) may.
        """
        if phase0_permit_guard and order_submission_permit is not None:
            raise Phase0PermitForbiddenError(
                "ContinuousRungHoldStrategy: Phase 0 forbids a non-None "
                "order_submission_permit"
            )
        super().__init__(config)
        self._config: CurrentRungHoldConfig = config
        self._latch_factory = trial_day_latch_factory
        self._order_submission_permit = order_submission_permit
        self._latch: TrialDayLatch | None = None
        #: Slice 4 items A2/E1 (plan rev 6.1): injected override for the
        #: never-arm walk's and the re-arm gate's evidence source -- tests
        #: inject a fake here; production leaves this `None` so `on_start`
        #: binds it to the just-opened latch's own `read_startup_evidence`.
        self._position_evidence_reader_override = position_evidence_reader
        self._position_evidence_reader: Callable[[], dict[str, object] | None] | None = None
        self._unjoinable_fill_instruments: set[str] = set()
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
        #: Review item 3 (three-seam Slice 4 review): the ask a Take
        #: decision was actually made against, keyed by the station-day it
        #: will (eventually) consume -- `on_order_filled` reads (and pops)
        #: this so the durable `TrialDayRecord.ask` is the DECISION price,
        #: never the fill price, keeping the scorer's L-25 `fill_below_ask`
        #: guard load-bearing. Popped on read so this never grows unbounded.
        self._decision_ask_by_station_day: dict[tuple[str, str], Decimal] = {}

    def on_start(self) -> None:
        if self._latch_factory is None:
            raise MissingTrialDayLatchError(
                "ContinuousRungHoldStrategy was constructed with no "
                "trial_day_latch_factory; see the module docstring."
            )
        exit_stack = ExitStack()
        self._latch = exit_stack.enter_context(self._latch_factory())
        self._exit_stack = exit_stack
        self._position_evidence_reader = (
            self._position_evidence_reader_override
            if self._position_evidence_reader_override is not None
            else self._latch.read_startup_evidence
        )

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

        # Phase 0 (`order_submission_permit is None`, enforced at
        # construction -- `Phase0PermitForbiddenError`) never arms anything
        # regardless: there is no order-submission capability to gate, so
        # the never-arm walk would only halt every shadow-mode deployment
        # for no safety gain. This becomes live the moment a Phase 1
        # composition threads a real permit through.
        if self._order_submission_permit is not None and not self._run_never_arm_walk():
            self.stop()
            return

        self.subscribe_data(
            station_observation_data_type(), client_id=NWS_BACKTEST_CLIENT_ID,
        )

    def _run_never_arm_walk(self) -> bool:
        """Slice 4 item A2 (plan rev 6.1): fail-closed startup gate.

        Returns ``False`` (never arm anything -- `on_start` stops the
        strategy) unless: the family halt is clear, the exec client's
        startup evidence proves a complete non-refused positions read, the
        durable fill-primary walk is fully readable, and no venue LONG on a
        configured instrument lacks a durable fill on record.
        """
        assert self._latch is not None
        if self._latch.is_family_halted():
            self.log.error("continuous_rung_hold: family halt is set; never arming")
            self.position_events.record(_POSITION_FAMILY_HALT_AT_START)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )
            return False

        evidence = (
            self._position_evidence_reader() if self._position_evidence_reader else None
        )
        if not startup_evidence_permits_arm(evidence):
            self.log.error(
                "continuous_rung_hold: startup position evidence is absent, "
                "position_read_refused, not eof_complete, or not "
                "fill_walk_complete; halting before any subscription",
            )
            self.position_events.record(_POSITION_STARTUP_EVIDENCE_MISSING)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )
            return False

        candidate_ids = self._candidate_instrument_ids()
        try:
            fills = self._latch.iter_fill_records(candidate_ids)
        except (TrialDayRecordCorrupt, ExecutionReportMappingError) as exc:
            self.log.error(
                f"continuous_rung_hold: durable fill walk unreadable ({exc}); halting",
            )
            self.position_events.record(_POSITION_FILL_WALK_UNREADABLE)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )
            return False

        for fill_record in fills:
            self._consume_trial_from_fill_record(fill_record)

        for iid, facts in self._facts.items():
            station = facts.settlement_station
            climate_day_key = facts.climate_day.isoformat()
            if self._latch.is_consumed(station, climate_day_key):
                continue
            slug = InstrumentId.from_str(iid).symbol.value
            # R-8 (2026-09-12, docs/core/PROGRESS.md): a slug LISTED on the
            # page is decided exactly as before (present branch, byte-
            # equivalent). A slug ABSENT from an eof-complete, fresh page
            # is confirmed FLAT, not UNKNOWN -- the producer emits only
            # slugs the venue's page names, so a never-traded candidate
            # market is absent by construction (supersedes three-seam
            # Slice 4 review item 5, whose PASS state was unreachable for
            # any first trade). Applies at BOTH `_run_never_arm_walk`
            # (here) and `_rearm_permitted`.
            if startup_evidence_lists_slug(evidence, slug):
                net_position = startup_evidence_position_for(evidence, slug)
                slug_ok = net_position is not None and net_position <= 0
            else:
                slug_ok = startup_evidence_confirms_absent_flat(evidence, slug)
            if not slug_ok:
                self.log.error(
                    f"continuous_rung_hold: venue position for {iid} is a "
                    "LONG or UNKNOWN (no durable fill on record); halting",
                )
                self.position_events.record(_POSITION_UNRECONCILED_LONG)
                self._report_alerter(
                    self.position_alerter, "continuous_rung_hold position report failed",
                )
                return False
        return True

    def _candidate_instrument_ids(self) -> frozenset[str]:
        """The union `on_order_filled`'s slug-fallback join, and the never-
        arm fill walk, both search: on-start-resolved "catalog" instruments
        (`self._facts`), configured instrument ids, and whatever the cache
        currently holds -- a fill can arrive for an instrument that resolved
        into the cache AFTER `on_start` populated `self._facts`.
        """
        ids = set(self._facts) | {str(i) for i in self._config.instrument_ids}
        ids |= {str(i) for i in self.cache.instrument_ids()}
        return frozenset(ids)

    def _consume_trial_from_fill_record(self, fill_record: DurableFillRecord) -> None:
        assert self._latch is not None
        joined = self._join_fill_to_station_day(
            InstrumentId.from_str(fill_record.instrument_id),
        )
        if joined is None:
            return
        station, climate_day_key = joined
        if self._latch.is_consumed(station, climate_day_key):
            return
        avg_px = (
            fill_record.cumulative_cost / fill_record.cumulative_qty
            if fill_record.cumulative_qty
            else Decimal(0)
        )
        self._latch.consume_if_absent(
            station,
            climate_day_key,
            TrialDayRecord(
                latched_at_ns=fill_record.ts_event,
                instrument_id=fill_record.instrument_id,
                ask=avg_px,
                # Review item 3 (three-seam Slice 4 review): no decision-time
                # ask exists for a fill-walk-consumed trial -- a DISTINCT
                # reason, so the scorer's L-25 guard skips it BY REASON.
                reason=TAKEN_FROM_FILL_WALK_REASON,
                venue_order_id=fill_record.venue_order_id,
            ),
        )

    def _join_fill_to_station_day(
        self, instrument_id: InstrumentId,
    ) -> tuple[str, str] | None:
        """Slice 4 item A1 (plan rev 6.1): ``(station, climate_day)`` for a
        fill -- ``self._facts`` first, then a slug fallback.

        The fallback is needed because a fill can arrive for an instrument
        that resolved into the cache AFTER `on_start` populated
        `self._facts`. HIGH-measure and station-in-config only, same scope
        `on_start` enforces for the primary join -- this is what makes NYC
        (never one of the four supported stations,
        `strategy.py::_ICAO_BY_STATION`) and any other out-of-scope city
        unjoinable here too. Returns ``None`` on ANY failure -- never a
        partial guess (fail closed).
        """
        iid = str(instrument_id)
        facts = self._facts.get(iid)
        if facts is not None:
            return facts.settlement_station, facts.climate_day.isoformat()
        if iid not in self._candidate_instrument_ids():
            return None
        try:
            slug = instrument_id_to_slug(instrument_id)
        except VenuePayloadError:
            return None
        parsed = parse_weather_slug(slug)
        if parsed is None or parsed.measure != "high":
            return None
        station = parsed.city.upper()
        if station not in self._config.stations:
            return None
        return station, parsed.climate_date

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
        assert self._latch is not None
        if self._latch.is_family_halted():
            # Slice 4 item B1 (plan rev 6.1): checked FIRST, before any
            # other decision -- no station arms anywhere for the rest of
            # the family's life once a duplicate genuine fill has occurred.
            self.diagnostics.record(_DIAG_FAMILY_HALT)
            self._report_alerter(
                self.diagnostics_alerter,
                "continuous_rung_hold diagnostics report failed",
            )
            return
        if self._fee_halt:
            return
        iid = str(snapshot.instrument_id)
        if iid in self._unjoinable_fill_instruments:
            # Review item 1 (three-seam Slice 4 review): a process-local
            # halt for THIS instrument -- an unjoinable or corrupt-record
            # fill already fired here; never hunt it again this process.
            return
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
        # Phase 0 never arms (see `on_start`'s matching guard) -- the re-arm
        # gate and its attempt counter are Phase-1-only groundwork.
        if self._order_submission_permit is not None:
            attempts, last_attempt_ns = self._latch.attempt_state(station, climate_day_key)
            if attempts > 0 and not self._rearm_permitted(
                station,
                climate_day_key,
                iid,
                attempts=attempts,
                last_attempt_ns=last_attempt_ns,
                now_ns=snapshot.ts_event,
            ):
                self.diagnostics.record(_DIAG_REARM_WAIT)
                self._report_alerter(
                    self.diagnostics_alerter,
                    "continuous_rung_hold diagnostics report failed",
                )
                return
        # Resolution B (plan rev 6.1): the cheap, read-only pre-filter.
        # While the account-wide submit-intent singleton is OPEN -- a
        # genuine in-flight sibling order OR a stale/crash-left singleton no
        # resolver has cleared yet -- every station's tick is a WAIT here,
        # never a task hop into `submit_order` that SAFETY C1's own
        # re-check would only deny later. This is what keeps a stale OPEN
        # singleton from producing a hunt -> WAIT-deny -> clear-inflight ->
        # hunt loop: with this filter in place, `_submit_order`'s WAIT path
        # (and `on_order_denied`'s clear) is reached ONLY by the genuine
        # same-burst race it exists for.
        if self._latch.is_intent_open():
            self.diagnostics.record(_DIAG_OPEN_INTENT_WAIT)
            self._report_alerter(
                self.diagnostics_alerter,
                "continuous_rung_hold diagnostics report failed",
            )
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

        # Review item 3 (three-seam Slice 4 review): the DECISION-time ask,
        # captured here so `on_order_filled` records the durable TRIAL
        # against the ask actually evaluated, never the (later, different)
        # fill price -- otherwise the scorer's L-25 `fill_below_ask` guard
        # is inert by construction.
        self._decision_ask_by_station_day[(station, climate_day_key)] = ask
        self._latch.set_inflight(station, climate_day_key)
        if self._order_submission_permit is not None:
            self._latch.record_attempt(station, climate_day_key, ts_ns=snapshot.ts_event)
        self._maybe_submit(iid, decision)
        if self._order_submission_permit is None:
            self._latch.clear_inflight(station, climate_day_key)

    def _rearm_permitted(
        self,
        station: str,
        climate_day: str,
        instrument_id: str,
        *,
        attempts: int,
        last_attempt_ns: int | None,
        now_ns: int,
    ) -> bool:
        """Slice 4 item E1 (plan rev 6.1, Resolution F): the evidence-based
        re-arm gate for a station-day that has already been attempted at
        least once and IN_FLIGHT has since cleared.

        Requires attempts under the cap, the conservative delay floor
        elapsed, AND a FRESH (read live, right here -- never cached) eof-
        complete positions read showing no LONG on this instrument.
        """
        if attempts >= _MAX_STATION_DAY_ATTEMPTS:
            return False
        if last_attempt_ns is not None and now_ns < last_attempt_ns + _REARM_MIN_DELAY_NS:
            return False
        evidence = (
            self._position_evidence_reader() if self._position_evidence_reader else None
        )
        if not startup_evidence_permits_arm(evidence):
            return False
        slug = InstrumentId.from_str(instrument_id).symbol.value
        # R-8 (2026-09-12): the same rule as `_run_never_arm_walk` (site 1),
        # through the same helpers and the same freshness ceiling.
        if startup_evidence_lists_slug(evidence, slug):
            net_position = startup_evidence_position_for(evidence, slug)
            return net_position is not None and net_position <= 0
        return startup_evidence_confirms_absent_flat(evidence, slug)

    def on_order_denied(self, event: OrderDenied) -> None:
        """SAFETY C1 (plan rev 6.1): clear IN_FLIGHT for a WAIT-class deny.

        ``_submit_order``'s pre-arm re-check denies a synchronous-burst
        sibling with ``submit_chain.OPEN_INTENT_WAIT_REASON`` -- money and
        the durable submit-intent latch untouched, so the station-day is
        free to re-hunt on a later tick. Every OTHER denial reason is a
        standing refusal this strategy does not yet resolve automatically
        (Phase 0's own auto-clear, above, only ever ran with
        ``order_submission_permit is None``), so IN_FLIGHT is left set for
        anything but the exact WAIT sentinel -- a narrower reason match
        would risk silently clearing a real refusal too.
        """
        super().on_order_denied(event)
        if event.reason != submit_chain.OPEN_INTENT_WAIT_REASON:
            return
        facts = self._facts.get(str(event.instrument_id))
        if facts is None:
            return
        assert self._latch is not None
        self._latch.clear_inflight(facts.settlement_station, facts.climate_day.isoformat())

    def on_order_filled(self, event: OrderFilled) -> None:
        """Slice 4 item A1 (plan rev 6.1): join a genuine fill to its
        station-day and durably consume the TRIAL, exactly once,
        idempotently -- the sole writer of a TRIAL for this family (never a
        Take decision by itself, unlike v2's `on_quote_tick`).

        A second GENUINE fill on an already-consumed station-day (different
        `venue_order_id`) is item B1's duplicate-fill halt, not a raise. A
        REPLAYED fill for the SAME `venue_order_id` is idempotent: this
        method's own `consume_if_absent` call already makes that a no-op.

        Three-seam Slice 4 review item 1: every latch read/write below runs
        under ONE try/except -- `Strategy.handle_event` (installed Nautilus)
        re-raises a handler exception, which would kill the strategy right
        after a real fill. A corrupt existing record or an unreadable join
        is therefore fail-closed (ERROR + alert + a process-local halt for
        THIS instrument, via `self._unjoinable_fill_instruments`, checked by
        `_hunt_tick`), never a raise.
        """
        super().on_order_filled(event)
        if event.last_qty.as_decimal() <= 0:
            return
        assert self._latch is not None
        joined = self._join_fill_to_station_day(event.instrument_id)
        if joined is None:
            self.log.error(
                f"on_order_filled: fill for {event.instrument_id} could not "
                "be joined to a station-day (no facts, no valid slug match); "
                "no TRIAL recorded, halting this instrument",
            )
            self._unjoinable_fill_instruments.add(str(event.instrument_id))
            self.position_events.record(_POSITION_UNJOINABLE_FILL)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )
            return
        station, climate_day_key = joined
        try:
            self._consume_or_flag_duplicate(station, climate_day_key, event=event)
        except (TrialDayRecordCorrupt, ExecutionReportMappingError) as exc:
            iid = str(event.instrument_id)
            self.log.error(
                f"on_order_filled: a latch read/write for {iid} raised "
                f"{type(exc).__name__}: {exc}; halting this instrument "
                "(fail closed, no TRIAL, not re-raised)",
            )
            self._unjoinable_fill_instruments.add(iid)
            self.position_events.record(_POSITION_FILL_JOIN_ERROR)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )

    def _consume_or_flag_duplicate(
        self, station: str, climate_day_key: str, *, event: OrderFilled,
    ) -> None:
        """The latch read/write body of `on_order_filled`, isolated so its
        caller can wrap it in exactly one try/except (review item 1).

        Review item 3: the durable `ask` is the DECISION-time ask
        `_hunt_tick` captured for this station-day, never the fill price --
        falls back to the fill price only when no decision ask was tracked
        (e.g. a restart between decision and fill), which cannot happen for
        the fill-walk path (that path never goes through `_hunt_tick` and
        writes `TAKEN_FROM_FILL_WALK_REASON` instead of calling this).
        """
        assert self._latch is not None
        venue_order_id = str(event.venue_order_id)
        decision_ask = self._decision_ask_by_station_day.pop((station, climate_day_key), None)
        ask = decision_ask if decision_ask is not None else event.last_px.as_decimal()
        record = TrialDayRecord(
            latched_at_ns=event.ts_event,
            instrument_id=str(event.instrument_id),
            ask=ask,
            reason="taken",
            venue_order_id=venue_order_id,
        )
        wrote = self._latch.consume_if_absent(station, climate_day_key, record)
        if wrote:
            return
        existing = self._latch.record(station, climate_day_key)
        if existing is None:
            return
        if existing.venue_order_id is None:
            # Review item 2: a legacy (pre-Slice-4) record decodes its
            # optional `venueOrderId` as `None` -- that is NOT evidence of a
            # duplicate (it is evidence of nothing at all about identity),
            # so this must never fire the family halt.
            self.log.warning(
                _LEGACY_RECORD_NO_VENUE_ORDER_ID_WARNING.format(
                    station=station, climate_day=climate_day_key,
                ),
            )
            return
        if existing.venue_order_id == venue_order_id:
            return  # a replayed fill for the SAME order -- idempotent no-op
        fee = Decimal(0) if event.commission is None else event.commission.as_decimal()
        self._latch.record_duplicate_fill(
            station,
            climate_day_key,
            venue_order_id=venue_order_id,
            qty=event.last_qty.as_decimal(),
            fill_px=event.last_px.as_decimal(),
            fee=fee,
            ts_ns=event.ts_event,
        )
        self.diagnostics.record(_DIAG_FAMILY_HALT)
        self._report_alerter(
            self.diagnostics_alerter,
            "continuous_rung_hold diagnostics report failed",
        )

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
