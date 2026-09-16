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

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderDenied, OrderFilled, PositionOpened
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.errors import (
    ExecutionReportMappingError,
    FeeScheduleUnknownError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    first_live_order_payload,
    is_no_side_pending,
)
from breezy.adapters.polymarket_us.operator_controls import utc_day_for_ns
from breezy.adapters.polymarket_us.parsing import assert_fee_schedule_known
from breezy.adapters.polymarket_us.symbology import (
    base_slug_of,
    leg_of,
    parse_weather_slug,
    sibling_instrument_id,
)
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
from breezy.runtime.paper_replay import EXPIRATION_LEG_PREFIX
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import Decision, Refuse, Take
from breezy.strategy.current_rung_hold.offer_tape import OfferTape, OfferTapeRecord
from breezy.strategy.current_rung_hold.position_monitor import PositionMonitor
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
    BothSides,
    evaluate_both_sides,
    instrument_rung_is_current,
    width_and_m,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    SIBLING_LEG_TRADED_REASON,
    STATION_DAY_ADMISSION_REASON,
    TAKEN_FROM_FILL_WALK_REASON,
    Refusal,
    TrialDayLatch,
    TrialDayLatchError,
    TrialDayRecord,
    TrialDayRecordCorrupt,
    refuse_if_sibling_leg_traded,
    startup_evidence_confirms_absent_flat,
    startup_evidence_lists_slug,
    startup_evidence_permits_arm,
    startup_evidence_position_for,
    station_day_admission,
)
from breezy.strategy.depth10 import best_order
from breezy.strategy.weather_common.refusals import RefusalAlerter, RefusalCounter
from breezy.strategy.weather_common.running_extreme import (
    RunningExtremeAccumulator,
    RunningMax,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
    from nautilus_trader.model.instruments import Instrument

__all__ = [
    "NO_SIDE_SHADOW_ONLY",
    "NO_SIDE_SHADOW_REFUSAL_REASONS",
    "ContinuousRungHoldStrategy",
    "Phase0PermitForbiddenError",
]

_NS_PER_MINUTE: Final[int] = 60_000_000_000
#: GAP fix 2026-09-15: for the `take:` log line's `staleness_s=` field only.
_NS_PER_SECOND: Final[int] = 1_000_000_000
#: GAP fix 2026-09-15: `NO_ask = 1 - bid`, for the NO-side offer-tape row's
#: `ask` field ONLY when `no_decision` is a `Refuse` that never reached a
#: `Take.limit_price` -- mirrors `decision.py`'s own inversion exactly,
#: recomputed here purely for logging (never for a decision).
_ONE: Final[Decimal] = Decimal(1)
_CLASS_NAME: Final[str] = "ContinuousRungHoldStrategy"
#: S3b (plan NO_SIDE_EDGE_2026-09-14 S4/S5): the NO leg's Take is evaluated
#: and gated every tick. FLIPPED to `False` by this commit (S5 Track C,
#: the tail commit of `NO_SIDE_S5_EXEC_2026-09-14.md` §5) -- exit criteria
#: (a)-(d) are MET (preview+book capture, the X3 ruling sign-off at
#: 8c954ef, the S6b citation, and the first-order-protocol keys/CLI/RED
#: tests landing before this flip; PREREG amendment §8). Criterion (e),
#: the position-shape ruling, stays OPEN by design and is contained by
#: the bounded first-order protocol (`NO_SIDE_FIRST_ORDER_PENDING_REASON`)
#: until the first NO fill's venue position payload is captured and
#: ruled on.
NO_SIDE_SHADOW_ONLY: Final[bool] = False
#: Closed-set reasons for a `no_refuse:` shadow-gate log line (S3b, S4).
#: Deliberately disjoint from `decision.REFUSAL_REASONS` -- these are the
#: LATCH-layer gates run only after the NO leg's own `Take` already cleared
#: `evaluate_decision`, never a decision-layer refusal (those are silent,
#: matching the YES path's existing behaviour).
_NO_REFUSE_INTENT_OPEN: Final[str] = "intent_open"
_NO_REFUSE_DAY_BUDGET_EXHAUSTED: Final[str] = "day_budget_exhausted"
_NO_REFUSE_TRIAL_DAY_CONSUMED: Final[str] = "trial_day_consumed"
NO_SIDE_SHADOW_REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        _NO_REFUSE_INTENT_OPEN,
        SIBLING_LEG_TRADED_REASON,
        STATION_DAY_ADMISSION_REASON,
        _NO_REFUSE_DAY_BUDGET_EXHAUSTED,
        _NO_REFUSE_TRIAL_DAY_CONSUMED,
    }
)
#: Resolution B (plan rev 6.1): the account-wide OPEN-intent WAIT diagnostic.
#: Not a refusal -- reported through `diagnostics`/`diagnostics_alerter`
#: (the existing WAIT vocabulary), never `refusals`/`refusal_alerter`.
_DIAG_OPEN_INTENT_WAIT: Final[str] = "open_intent_wait"
#: Slice 4 item B1 (plan rev 6.1): the family-wide duplicate-fill halt WAIT.
_DIAG_FAMILY_HALT: Final[str] = "family_halt_duplicate_fill"
#: Slice 4 item E1 (plan rev 6.1, Resolution F): a re-arm gate WAIT.
_DIAG_REARM_WAIT: Final[str] = "rearm_wait"
#: HF-4 Decision 1 (1B): a stale IN_FLIGHT marker was released this tick.
_DIAG_INFLIGHT_RELEASED: Final[str] = "inflight_released"
#: Operator ruling 2026-09-14: today's UTC-day dollar ceiling is exhausted --
#: a WAIT, checked before IN_FLIGHT/the attempt counter, never a refusal.
_DIAG_DAY_BUDGET_EXHAUSTED: Final[str] = "day_budget_exhausted"
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
#: INC-5 (intra-day position monitor, D8): a `PositionMonitor` forwarding
#: call failed -- caught at THIS handler boundary (`_forward_to_monitor`),
#: counted, reported, never raised into `_hunt_tick`/`_maybe_submit`/latch
#: state.
_POSITION_MONITOR_ERROR: Final[str] = "monitor_error"
#: Review finding F3: `on_position_opened`'s `self.cache.position(event.
#: position_id)` lookup returns `None` -- counted, never silently skipped.
#: A later Depth10 frame still registers the position lazily via
#: `PositionMonitor._ensure_registered`'s own `positions_open` read
#: (`position_monitor.py`), so this is observability only, never a lost
#: registration.
_POSITION_OPENED_EVENT_UNRESOLVED: Final[str] = "position_opened_event_unresolved"
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
#: R-8 (2026-09-12, N-ceiling): how long an eof-complete page's absence of
#: a candidate slug may be read as FLAT before it degrades to UNKNOWN. A
#: coordinator ceiling, not a measurement -- justified against the native
#: boot path: `reconciliation_startup_delay_secs` default 10.0
#: (`live/config.py:199`) + `timeout_reconciliation` default 30.0
#: (`system/config.py:128`) => worst-case write->read gap is ~40s plus
#: engine-connect/portfolio-init awaits. 600s is ~15x worst case and far
#: below any previous-process record (hours). Build-side (PREREG v3 §7
#: pins exactly two operator controls; this is not one of them).
_STARTUP_EVIDENCE_MAX_AGE_SECS: Final[int] = 600
_STARTUP_EVIDENCE_MAX_AGE_NS: Final[int] = _STARTUP_EVIDENCE_MAX_AGE_SECS * 1_000_000_000
#: R-9a (HF-4 rev2, B4 ii): the RE-ARM ceiling, consumed ONLY at
#: `_rearm_permitted`'s absent-slug branch -- tighter than the 600s boot
#: ceiling above because attempts 2-3 can echo the resolver's own
#: misclassification (R14): a re-arm demands fresher evidence than a first
#: boot does. Coupled to the resolver's own supply side
#: (`_EVIDENCE_REFRESH_AFTER_NS = 60s`, `exec/client.py`): 120s (the
#: `_REARM_MIN_DELAY_NS` floor) < 180s (this ceiling) ⇒ a healthy resolver
#: loop always clears it; a backed-off or dead loop (backoff cap 300s,
#: `exec/client.py::_RESOLVER_BACKOFF_CAP_SECS`) is denied, fail-closed.
_REARM_EVIDENCE_MAX_AGE_SECS: Final[int] = 180
_REARM_EVIDENCE_MAX_AGE_NS: Final[int] = _REARM_EVIDENCE_MAX_AGE_SECS * 1_000_000_000

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
    #: S3b (plan NO_SIDE_EDGE_2026-09-14 S3): the YES bid side of the SAME
    #: frame, additive -- every existing construction site gains these two
    #: fields below; a caller that omits them (there are none left in this
    #: module) would get `None`, which `evaluate_both_sides` already treats
    #: as a missing bid (NO refuses `not_executable`).
    bid: Decimal | None = None
    bid_size: Decimal | None = None


def _snapshot_from_quote(tick: QuoteTick) -> _AskSnapshot:
    return _AskSnapshot(
        instrument_id=tick.instrument_id,
        ask=tick.ask_price.as_decimal(),
        size=int(tick.ask_size),
        ts_event=tick.ts_event,
        source="quote",
        bid=tick.bid_price.as_decimal(),
        bid_size=tick.bid_size.as_decimal(),
    )


def _startup_evidence_summary(
    evidence: dict[str, object] | None,
    *,
    now_ns: int,
    decisions: Mapping[str, str],
) -> str:
    """AC-13/N2 (R-8, 2026-09-12): a pure, unit-tested renderer for the
    never-arm walk's ONE INFO summary line, emitted on ALL FIVE
    `_run_never_arm_walk` return paths (L-30: observability by presence of
    a line, never by the absence of a halt error). Accepts ``evidence is
    None`` (the evidence-missing return path). ``decisions`` maps each
    candidate instrument id already evaluated (in this call) to one of
    ``"present-flat" | "absent-flat" | "LONG" | "UNKNOWN"``; it may be
    empty when the walk halted before any per-slug decision was made
    (family halt, evidence-missing, fill-walk-unreadable).
    """
    if evidence is None:
        return (
            "continuous_rung_hold startup_evidence: evidence=absent "
            f"decisions={dict(decisions)!r}"
        )
    eof_complete = evidence.get("eof_complete")
    position_read_refused = evidence.get("position_read_refused")
    fill_walk_complete = evidence.get("fill_walk_complete")
    positions = evidence.get("positions")
    page_slug_count = len(positions) if isinstance(positions, list) else None
    ts = evidence.get("ts_ns")
    age_secs: float | None = None
    if isinstance(ts, int) and not isinstance(ts, bool):
        age_secs = (now_ns - ts) / 1_000_000_000
    return (
        "continuous_rung_hold startup_evidence: "
        f"eof_complete={eof_complete!r} "
        f"position_read_refused={position_read_refused!r} "
        f"fill_walk_complete={fill_walk_complete!r} "
        f"page_slug_count={page_slug_count!r} "
        f"age_secs={age_secs!r} "
        f"decisions={dict(decisions)!r}"
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
        position_monitor: PositionMonitor | None = None,
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
        #: AC-13/N2 (R-8, L-30): the rendered `_startup_evidence_summary(...)`
        #: from the MOST RECENT `_run_never_arm_walk` call, on every one of
        #: its five return paths. Asserted by presence, never via log
        #: capture (L-27) -- first-boot verification checks this is a
        #: non-`None` string, not merely the absence of a halt error.
        self.last_startup_evidence_summary: str | None = None
        #: B3 (Decision 3, HF-4 rev2): mirrors `last_startup_evidence_
        #: summary` above -- the MOST RECENT rearm decision line (release,
        #: first-denial-per-reason, or a successful re-arm), asserted by
        #: presence, never via log capture (L-27).
        self.last_rearm_decision: str | None = None
        #: AM-3 (Rev 2.1): dedupe set for `_record_rearm_denial_once`,
        #: bounded -- see that method's own comment.
        self._rearm_decision_dedupe: set[tuple[tuple[str, str], str]] = set()
        #: Operator ruling 2026-09-14: dedupes the ``budget_stop`` WARN/alert
        #: to once per ``(station, utc_day)``, mirroring the rearm-denial
        #: dedupe above.
        self._budget_stop_notice: set[tuple[str, str]] = set()
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
        #: S3b (plan NO_SIDE_EDGE_2026-09-14): mirrors `last_rearm_decision`
        #: (L-27, asserted by presence, never via log capture) -- the MOST
        #: RECENT `no_take_shadow:`/`no_refuse:` line, respectively.
        self.last_no_take_shadow: str | None = None
        self.last_no_refuse: str | None = None
        #: Dedupe for `no_take_shadow:` -- at most once per (station,
        #: climate_day, NO instrument id) per UTC MINUTE, the same bounded
        #: shape as `_budget_stop_notice` (bounded by the finite set of
        #: station-days a process ever hunts). Maps the key to the last
        #: minute bucket (``now_ns // _NS_PER_MINUTE``) it logged in.
        self._no_shadow_notice: dict[tuple[str, str, str], int] = {}
        #: Dedupe for `no_refuse:` -- once per (station, climate_day, NO
        #: instrument id), for the life of the process, mirroring
        #: `_illegal_cell_station_days`.
        self._no_refuse_notice: set[tuple[str, str, str]] = set()
        #: GAP fix 2026-09-15 (brief item 4): dedupe for the `take:` INFO
        #: line -- once per (station, climate_day, YES instrument id), for
        #: the life of the process, mirroring `_no_refuse_notice` above.
        self._take_log_notice: set[tuple[str, str, str]] = set()
        #: INC-5 (intra-day position monitor, SHADOW-ONLY): `None` (default)
        #: means every monitor hook below is a no-op -- byte-identical
        #: behaviour to before this field existed. A composition root wires
        #: a real `PositionMonitor` in after construction (`composition.py`);
        #: this strategy never constructs one itself and never reaches into
        #: its mutating surface (there is none -- M7 D3 pin).
        self._position_monitor: PositionMonitor | None = position_monitor

    def _submission_armed(self) -> bool:
        """Whether this strategy holds a real order-submission capability.

        Base body: ``bool(self._order_submission_permit is not None)`` --
        identical to the raw predicate every one of the five call sites read
        directly before this extraction (L-2 unit line: EQUAL for every
        non-subclass instance; evaluation order preserved at every site --
        `on_start`, `_hunt_tick`'s re-arm gate, the attempt-record and
        in-flight-clear sites, and `_maybe_submit` -- never at a line
        number, which shifts as the module changes).
        Increment B's ``ContinuousRungHoldBacktestStrategy`` overrides this
        to gate on a private backtest-only flag instead, while never holding
        a real ``OrderSubmissionPermit`` (PERMIT ISOLATION).
        """
        return self._order_submission_permit is not None

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
        if self._submission_armed() and not self._run_never_arm_walk():
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
        now_ns = self.clock.timestamp_ns()
        if self._latch.is_family_halted():
            self.log.error("continuous_rung_hold: family halt is set; never arming")
            self.position_events.record(_POSITION_FAMILY_HALT_AT_START)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )
            self._record_startup_evidence_summary(None, now_ns=now_ns, decisions={})
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
            self._record_startup_evidence_summary(evidence, now_ns=now_ns, decisions={})
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
            self._record_startup_evidence_summary(evidence, now_ns=now_ns, decisions={})
            return False

        for fill_record in fills:
            self._consume_trial_from_fill_record(fill_record)

        decisions: dict[str, str] = {}
        for iid, facts in self._facts.items():
            station = facts.settlement_station
            climate_day_key = facts.climate_day.isoformat()
            # NO-SIDE S5 (§5 plan, "the never-arm walk decides both legs"):
            # the NO sibling's decision is recorded for observability ONLY --
            # it never gates the YES `slug_ok`/`return False` logic below,
            # because no venue position evidence for a NO id can ever exist
            # (E2-1(i)/(ii), `_map_position` is YES-only). A NO leg with no
            # durable fill record on this instrument-day is "flat" without
            # any position read; a NO leg with ANY fill record is "UNKNOWN"
            # for NO-arming purposes (the position-shape ruling has not
            # fired yet) -- either way YES keeps arming exactly as before.
            no_iid = str(sibling_instrument_id(InstrumentId.from_str(iid)))
            try:
                no_has_fill = self._latch.is_consumed(
                    station, climate_day_key, key_instrument_id=no_iid,
                ) or bool(self._latch.iter_fill_records(frozenset({no_iid})))
            except (TrialDayRecordCorrupt, ExecutionReportMappingError) as exc:
                # Fail closed exactly like the entry-level walk (:527) and
                # the sibling cross-check below (:603) -- an unreadable
                # NO-leg fill index must halt the walk, never raise out of
                # it (safety review finding, 2026-09-14).
                self.log.error(
                    f"continuous_rung_hold: durable fill walk unreadable ({exc}); halting",
                )
                self.position_events.record(_POSITION_FILL_WALK_UNREADABLE)
                self._report_alerter(
                    self.position_alerter, "continuous_rung_hold position report failed",
                )
                self._record_startup_evidence_summary(
                    evidence, now_ns=now_ns, decisions=decisions,
                )
                return False
            decisions[no_iid] = "UNKNOWN" if no_has_fill else "flat"
            if self._latch.is_consumed(station, climate_day_key, key_instrument_id=iid):
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
                decisions[iid] = "present-flat" if slug_ok else (
                    "UNKNOWN" if net_position is None else "LONG"
                )
            else:
                # Option B (T3, N-T3): a LATER, independent read -- Nautilus's
                # OWN reconciled portfolio -- must also agree the instrument
                # is flat. Not a second source (same venue endpoint, R9): an
                # AND on the arming side that can only ever refuse an arm the
                # evidence read alone would have granted, never grant one it
                # alone would have refused (AC-11).
                slug_ok = startup_evidence_confirms_absent_flat(
                    evidence, slug,
                    now_ns=now_ns,
                    max_age_ns=_STARTUP_EVIDENCE_MAX_AGE_NS,
                ) and self.portfolio.net_position(InstrumentId.from_str(iid)) <= 0
                decisions[iid] = "absent-flat" if slug_ok else "UNKNOWN"
            if not slug_ok:
                # E3-1 (S5 plan Rev 3/Rev 4 E4-8): a venue LONG on the YES id
                # with no YES fill on record may still be fully accounted
                # for by a fill on the sibling NO id for the SAME
                # instrument-day -- sibling exclusion forbids a YES and a NO
                # fill on one instrument-day, so a NO fill here is
                # unambiguous evidence that the position is the NO leg's,
                # not an unreconciled YES long. `sibling_instrument_id`
                # varies only the leg suffix on the same dated slug, so this
                # never crosses days. Shape-agnostic: a venue that nets the
                # NO leg as non-long on the YES slug never reaches this
                # block at all (`slug_ok` was already `True`).
                no_iid_for_slug = no_iid
                try:
                    no_fill_records = self._latch.iter_fill_records(
                        frozenset({no_iid_for_slug}),
                    )
                except (TrialDayRecordCorrupt, ExecutionReportMappingError):
                    # Fail closed: an unreadable NO-leg fill index is never
                    # treated as accounting evidence -- falls through to the
                    # halt below, exactly like an absent one.
                    no_fill_records = ()
                if no_fill_records:
                    self.log.info(
                        f"never_arm: accounted_by_no_leg instrument={iid} "
                        f"no_instrument={no_iid_for_slug}",
                    )
                    decisions[iid] = "accounted-by-no-leg"
                    continue
                self.log.error(
                    f"continuous_rung_hold: venue position for {iid} is a "
                    "LONG or UNKNOWN (no durable fill on record); halting",
                )
                self.position_events.record(_POSITION_UNRECONCILED_LONG)
                self._report_alerter(
                    self.position_alerter, "continuous_rung_hold position report failed",
                )
                self._record_startup_evidence_summary(
                    evidence, now_ns=now_ns, decisions=decisions,
                )
                return False
        self._record_startup_evidence_summary(evidence, now_ns=now_ns, decisions=decisions)
        return True

    def _record_startup_evidence_summary(
        self,
        evidence: dict[str, object] | None,
        *,
        now_ns: int,
        decisions: Mapping[str, str],
    ) -> None:
        """AC-13/N2 (R-8, C5): computes the ONE summary line for this
        return path, stores it on `self.last_startup_evidence_summary`
        (asserted by presence, L-27), and emits it via the seam below --
        exactly once per `_run_never_arm_walk` return.
        """
        summary = _startup_evidence_summary(evidence, now_ns=now_ns, decisions=decisions)
        self.last_startup_evidence_summary = summary
        self._emit_startup_evidence_summary(summary)

    def _emit_startup_evidence_summary(self, summary: str) -> None:
        """C5 (code-reviewer HIGH on 8ae97be): the ONE INFO line AC-13
        requires on every `_run_never_arm_walk` return, so a live boot's
        `journalctl`/node-log inspection has something to find. A
        Breezy-owned seam (never a Nautilus internal, never log capture,
        L-27) so a test can override this method to record calls instead
        of asserting on captured log output. Production body is exactly
        one `self.log.info` call -- page facts only (eof_complete,
        position_read_refused, fill_walk_complete, page slug count,
        evidence age, per-candidate decision); never a URL or secret.
        """
        self.log.info(summary)

    def _candidate_instrument_ids(self) -> frozenset[str]:
        """The union `on_order_filled`'s slug-fallback join, and the never-
        arm fill walk, both search: on-start-resolved "catalog" instruments
        (`self._facts`), configured instrument ids, and whatever the cache
        currently holds -- a fill can arrive for an instrument that resolved
        into the cache AFTER `on_start` populated `self._facts`.
        """
        ids = set(self._facts) | {str(i) for i in self._config.instrument_ids}
        ids |= {str(i) for i in self.cache.instrument_ids()}
        # NO-SIDE S5: both legs are candidates -- a NO fill/never-arm lookup
        # must find its instrument-day here too (E2-6: the arming loop is
        # not NO-aware yet, but the join/walk lookups must be).
        siblings: set[str] = set()
        for candidate_id in ids:
            try:
                siblings.add(str(sibling_instrument_id(InstrumentId.from_str(candidate_id))))
            except VenuePayloadError:
                continue
        ids |= siblings
        return frozenset(ids)

    def _consume_trial_from_fill_record(self, fill_record: DurableFillRecord) -> None:
        assert self._latch is not None
        joined = self._join_fill_to_station_day(
            InstrumentId.from_str(fill_record.instrument_id),
        )
        if joined is None:
            return
        station, climate_day_key = joined
        instrument_id = fill_record.instrument_id
        if self._latch.is_consumed(station, climate_day_key, key_instrument_id=instrument_id):
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
            key_instrument_id=instrument_id,
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
        # NO-SIDE S5 (§5 plan): a NO-leg fill has no entry of its own in
        # `self._facts` (which is populated from YES instruments only) --
        # its YES sibling's facts join it to the same station-day.
        if leg_of(instrument_id) == "no":
            yes_facts = self._facts.get(str(sibling_instrument_id(instrument_id)))
            if yes_facts is not None:
                return yes_facts.settlement_station, yes_facts.climate_day.isoformat()
        if iid not in self._candidate_instrument_ids():
            return None
        try:
            # `base_slug_of` (unlike `instrument_id_to_slug`) accepts either
            # leg's id, recovering the same underlying venue slug.
            slug = base_slug_of(instrument_id)
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
        if self._position_monitor is not None:
            monitor = self._position_monitor
            self._forward_to_monitor(lambda: monitor.on_stop(self.clock.timestamp_ns()))
        exit_stack, self._exit_stack = self._exit_stack, None
        self._latch = None
        if exit_stack is not None:
            exit_stack.close()

    def on_position_opened(self, event: PositionOpened) -> None:
        super().on_position_opened(event)
        if self._position_monitor is None:
            return
        monitor = self._position_monitor
        position = self.cache.position(event.position_id)
        if position is None:
            # F3: counted, never silently dropped. `_ensure_registered`
            # (`position_monitor.py`) still registers this position lazily
            # off its own `positions_open` read the next time a Depth10
            # frame arrives, so nothing is permanently lost -- only this
            # event's own hand-off.
            self.position_events.record(_POSITION_OPENED_EVENT_UNRESOLVED)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )
            return
        self._forward_to_monitor(
            lambda: monitor.on_position_opened(position, self.clock.timestamp_ns()),
        )

    def _forward_to_monitor(self, action: Callable[[], None]) -> None:
        """D8 (plan §2/§7): "monitor exceptions caught at the handler
        boundary" -- a SECOND, strategy-level containment layer on top of
        `PositionMonitor`'s own internal guard, so even a monitor object
        that fails in some way its own guard cannot catch (a broken stub,
        a raise from a mocked method) never reaches -- or blocks --
        `_hunt_tick`/`_maybe_submit`/latch state. Counted the same way
        every other position-observability event is (`position_events`),
        never as a refusal or a diagnostic WAIT.
        """
        try:
            action()
        except Exception:  # noqa: BLE001 - a monitor must never affect the strategy's own path
            self.position_events.record(_POSITION_MONITOR_ERROR)
            self._report_alerter(
                self.position_alerter, "continuous_rung_hold position report failed",
            )

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
        if self._position_monitor is not None:
            monitor = self._position_monitor
            received_at_ns = data.received_at_ns
            self._forward_to_monitor(lambda: monitor.on_observation(station, received_at_ns))
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
        bid = best_order(depth.bids)
        snapshot = _AskSnapshot(
            instrument_id=depth.instrument_id,
            ask=ask.price.as_decimal(),
            size=int(ask.size),
            ts_event=depth.ts_event,
            source="depth",
            bid=bid.price.as_decimal() if bid is not None else None,
            bid_size=bid.size.as_decimal() if bid is not None else None,
        )
        self._hunt_tick(snapshot, trigger="depth", quote_age_ns=None)
        if self._position_monitor is not None:
            monitor = self._position_monitor
            self._forward_to_monitor(lambda: monitor.on_depth(depth, depth.ts_event))

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

        utc_day = utc_day_for_ns(snapshot.ts_event).isoformat()
        if self._latch.is_day_budget_exhausted(utc_day):
            # Operator ruling 2026-09-14: checked BEFORE is_consumed/
            # attempt_state/is_inflight, so a budget-stopped day never
            # touches IN_FLIGHT or the attempt counter -- this is a WAIT for
            # the rest of the UTC day, not a refusal.
            self.diagnostics.record(_DIAG_DAY_BUDGET_EXHAUSTED)
            notice_key = (station, utc_day)
            if notice_key not in self._budget_stop_notice:
                self._budget_stop_notice.add(notice_key)
                notice = (
                    f"budget_stop: {station}/{utc_day} not arming for the rest "
                    "of the UTC day (the day's spend ceiling is reached)"
                )
                self.log.warning(notice)
                self._report_alerter(
                    self.diagnostics_alerter,
                    "continuous_rung_hold diagnostics report failed",
                )
            return

        assert self._latch is not None
        if self._latch.is_consumed(station, climate_day_key, key_instrument_id=iid):
            return
        # AM-4 (HF-4 rev2.1): hoisted once per tick, BEFORE the IN_FLIGHT
        # check below, so the stale-IN_FLIGHT release and the re-arm gate a
        # few lines down share ONE store read instead of two. Phase 0
        # (`order_submission_permit is None`) now pays this one extra read
        # on every tick too, since the release check runs unconditionally --
        # accepted cost (Decision 1, HF-4.rev2.md): Phase 0 already self-
        # clears IN_FLIGHT at the end of this method regardless.
        attempt_state = self._latch.attempt_state(station, climate_day_key, key_instrument_id=iid)
        if self._latch.is_inflight(
            station, climate_day_key, key_instrument_id=iid,
        ) and not self._release_stale_inflight(
            station,
            climate_day_key,
            iid,
            attempts=attempt_state[0],
            last_attempt_ns=attempt_state[1],
            now_ns=snapshot.ts_event,
        ):
            return
        # Phase 0 never arms (see `on_start`'s matching guard) -- the re-arm
        # gate and its attempt counter are Phase-1-only groundwork.
        # defence in depth -- attempts > 0 implies armed (guard at the
        # attempt increment); removal is behaviourally inert, pinned by
        # test_an_unarmed_strategy_never_records_an_attempt_across_many_
        # eligible_depth_frames.
        if self._submission_armed():
            attempts, last_attempt_ns = attempt_state
            if attempts > 0 and not self._rearm_permitted(
                station,
                climate_day_key,
                iid,
                attempts=attempts,
                last_attempt_ns=last_attempt_ns,
                now_ns=snapshot.ts_event,
            ):
                self.diagnostics.record(_DIAG_REARM_WAIT)
                self._record_rearm_denial_once(station_day, attempts)
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
        # GAP fix 2026-09-15 (offer-tape postmortem observability): named
        # once so the offer-tape row below and the NO-side shadow evaluation
        # log the SAME staleness the decision was actually evaluated
        # against, rather than two independent (if numerically identical)
        # calls -- pure extraction, no behaviour change.
        staleness_ns = accumulator.staleness_ns(now_ns)
        # S3b (plan NO_SIDE_EDGE_2026-09-14 S3/S4): both sides are evaluated
        # from the SAME frame every tick. `decision` (YES) continues through
        # the existing arm/submit path below, byte-identical to before this
        # slice; the NO side is evaluated and gated independently, in
        # SHADOW ONLY (`NO_SIDE_SHADOW_ONLY`) -- it never affects `decision`,
        # `self.refusals`/`self.diagnostics`, the offer tape, or IN_FLIGHT.
        both_sides: BothSides = evaluate_both_sides(
            station=station,
            climate_day=climate_day,
            now_ns=now_ns,
            ladder=self._ladders[(station, climate_day_key)],
            fee_coefficient=fee_coefficient,
            ask=ask,
            ask_size=size,
            bid=snapshot.bid,
            bid_size=snapshot.bid_size,
            running_max=running_max,
            staleness_ns=staleness_ns,
            config=self._config,
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
        )
        decision: Decision = both_sides.yes
        self._evaluate_no_side_shadow(
            station=station,
            climate_day_key=climate_day_key,
            station_day=station_day,
            yes_instrument_id=snapshot.instrument_id,
            no_decision=both_sides.no,
            now_ns=now_ns,
            bid_size=snapshot.bid_size,
            bid=snapshot.bid,
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
            fee_coefficient=fee_coefficient,
            staleness_ns=staleness_ns,
            running_max=running_max,
        )

        # ADM-1 fix (2026-09-15, docs/core/PROGRESS.md row ADM-1): the YES
        # arm path never ran the two S4 latch-level gates the NO shadow
        # path immediately above already runs -- R-10 registers this gate
        # for BOTH legs (plan MULTI_POSITION_PER_STATION_2026-09-14.md
        # SS13/SS16: "the tally gate stays as defence in depth and must
        # never fire on a day the arm-time gate admitted"). Evaluated ONLY
        # for a Take -- a Refuse never reaches `_maybe_submit`/IN_FLIGHT
        # below, so it needs no admission check and `yes_admission_refusal`
        # stays `None` for it (never surfaced on the offer-tape row either,
        # mirroring `_evaluate_no_side_shadow`'s own `not isinstance(...,
        # Take)` early branch). Mirrors the NO path's own gate ORDER
        # (sibling first, then Sigma-q) and its own `existing_instrument_
        # ids` construction verbatim (today's ladder plus any durable fill
        # joined to this station-day, each leg deduped with its sibling) --
        # see `_evaluate_no_side_shadow`'s matching block below for the
        # shared rationale (TrialDayLatch has no public accessor for its
        # store/key-prefix; these two gate functions are pure over exactly
        # those by design).
        yes_admission_refusal: Refusal | None = None
        if isinstance(decision, Take):
            store = self._latch._store
            prefix = self._latch._key_prefix
            yes_admission_refusal = refuse_if_sibling_leg_traded(
                store, prefix, station, climate_day_key, iid,
            )
            if yes_admission_refusal is None:
                existing_ids: list[str] = []
                seen_ids: set[str] = set()

                def _add_leg(instrument_id_obj: InstrumentId) -> None:
                    leg_iid = str(instrument_id_obj)
                    if leg_iid in seen_ids:
                        return
                    seen_ids.add(leg_iid)
                    existing_ids.append(leg_iid)

                for other_iid, other_facts in self._facts.items():
                    if (
                        other_facts.settlement_station,
                        other_facts.climate_day.isoformat(),
                    ) != station_day:
                        continue
                    other_iid_obj = InstrumentId.from_str(other_iid)
                    _add_leg(other_iid_obj)
                    _add_leg(sibling_instrument_id(other_iid_obj))
                for fill_record in self._latch.iter_fill_records(
                    self._candidate_instrument_ids(),
                ):
                    joined = self._join_fill_to_station_day(
                        InstrumentId.from_str(fill_record.instrument_id),
                    )
                    if joined != station_day:
                        continue
                    fill_iid_obj = InstrumentId.from_str(fill_record.instrument_id)
                    _add_leg(fill_iid_obj)
                    _add_leg(sibling_instrument_id(fill_iid_obj))
                yes_admission_refusal = station_day_admission(
                    store,
                    prefix,
                    station,
                    climate_day_key,
                    "yes",
                    decision.break_even,
                    existing_instrument_ids=tuple(existing_ids),
                )

        reason = decision.reason if isinstance(decision, Refuse) else "taken"
        prior = self._eligible_snap_counts.get(station_day, 0)
        illegal = isinstance(decision, Refuse) and decision.reason == "illegal_cell"
        # GAP fix 2026-09-15: the decision-input fields a postmortem needs
        # (p_bound/break_even/running-max interval/staleness/fee
        # coefficient) -- read off `decision` (Take) or left `None` (Refuse
        # never reached the table lookup, except `edge_below_break_even`,
        # which `Refuse` itself now carries). Pure observability: neither
        # branch below changes `decision` or anything it drives.
        offer_admission_reason: str | None
        if isinstance(decision, Take):
            offer_p_bound: Decimal | None = decision.p_hold_lower
            offer_break_even: Decimal | None = decision.break_even
            if yes_admission_refusal is None:
                offer_decision_label = "take"
                offer_admission_reason = "admitted"
            else:
                offer_decision_label = "refuse"
                offer_admission_reason = yes_admission_refusal.reason
        else:
            offer_p_bound = decision.p_bound
            offer_break_even = decision.break_even
            offer_decision_label = "refuse"
            offer_admission_reason = None
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
                side="YES",
                p_bound=offer_p_bound,
                break_even=offer_break_even,
                running_max_lower=Decimal(running_max.lower_f),
                running_max_upper=Decimal(running_max.upper_f),
                running_max_exact=running_max.exact_f is not None,
                staleness_ns=staleness_ns,
                fee_coefficient=fee_coefficient,
                observed_at_ns=running_max.source_observed_at_ns,
                admission_reason=offer_admission_reason,
                decision=offer_decision_label,
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

        # ADM-1 fix: `decision` is a genuine Take here (mypy narrows it via
        # the exhaustive `Refuse` return above), but the arm-time latch
        # gates computed earlier may still have refused it -- counted and
        # alerted exactly like every other refusal above, and returned
        # BEFORE the `take:` log line below (never log a take for a rung
        # that never armed) and BEFORE `_decision_ask_by_station_day`/
        # `set_inflight`/`_maybe_submit` (no submit, no IN_FLIGHT).
        if yes_admission_refusal is not None:
            self.refusals.record(yes_admission_refusal.reason)
            self._report_alerter(
                self.refusal_alerter,
                "continuous_rung_hold refusal report failed",
            )
            return

        # GAP fix 2026-09-15 (brief item 4): one INFO line per FINALIZED
        # take, mirroring `no_take_shadow:`'s fields -- gated by
        # `_take_log_notice` so a re-arm cycle for the same instrument-day
        # never logs twice, never once per tick (`decision` is a `Take`
        # here; mypy narrows it via the exhaustive `Refuse` return above).
        take_log_key = (station, climate_day_key, iid)
        if take_log_key not in self._take_log_notice:
            self._take_log_notice.add(take_log_key)
            staleness_s = None if staleness_ns is None else staleness_ns / _NS_PER_SECOND
            self._emit_take_log(
                f"take: station={station} instrument={iid} ask={decision.limit_price} "
                f"p_bound={decision.p_hold_lower} be={decision.break_even} "
                f"R=[{running_max.lower_f},{running_max.upper_f}] "
                f"staleness_s={staleness_s} "
                f"cell=({hour_lst},{width_code},{m_code})"
            )

        # Review item 3 (three-seam Slice 4 review): the DECISION-time ask,
        # captured here so `on_order_filled` records the durable TRIAL
        # against the ask actually evaluated, never the (later, different)
        # fill price -- otherwise the scorer's L-25 `fill_below_ask` guard
        # is inert by construction.
        self._decision_ask_by_station_day[(station, climate_day_key)] = ask
        self._latch.set_inflight(station, climate_day_key, key_instrument_id=iid)
        if self._submission_armed():
            self._latch.record_attempt(
                station, climate_day_key, ts_ns=snapshot.ts_event, key_instrument_id=iid,
            )
            if attempt_state[0] > 0:
                # B3 (Decision 3, HF-4 rev2): a genuine RE-arm (attempts
                # already > 0 before this one), never the first attempt --
                # the boot walk already has its own INFO line for that.
                self._record_rearm_decision(
                    f"rearm: {station}/{climate_day_key} re-armed "
                    f"(attempt={attempt_state[0] + 1})"
                )
        self._maybe_submit(iid, decision)
        if not self._submission_armed():
            self._latch.clear_inflight(station, climate_day_key, key_instrument_id=iid)

    def _evaluate_no_side_shadow(
        self,
        *,
        station: str,
        climate_day_key: str,
        station_day: tuple[str, str],
        yes_instrument_id: InstrumentId,
        no_decision: Decision,
        now_ns: int,
        bid_size: Decimal | None,
        bid: Decimal | None = None,
        hour_lst: int = 0,
        width_code: int = 0,
        m_code: int = 0,
        fee_coefficient: Decimal | None = None,
        staleness_ns: int | None = None,
        running_max: RunningMax | None = None,
    ) -> None:
        """S3b (plan NO_SIDE_EDGE_2026-09-14 S3/S4): the NO leg's Take,
        gated but NEVER armed, consumed, or submitted (`NO_SIDE_SHADOW_ONLY`).

        GAP fix 2026-09-15 (offer-tape postmortem observability): the eight
        keyword-only parameters from ``bid`` onward are ADDITIVE, each
        defaulted so the two direct unit-test call sites
        (``tests/unit/test_continuous_rung_hold_no_side_shadow_2026_09_14.py``)
        keep working unedited -- they carry no decision-affecting weight,
        only the offer-tape row's own postmortem fields (mirroring the YES
        side's row in ``_hunt_tick``). Pure observability (L-34/D3): nothing
        below changes because of them.

        Runs the S4 gates in the fixed order the plan names, refusing at
        the FIRST that fires (closed-set reason, `NO_SIDE_SHADOW_REFUSAL_
        REASONS`) and logging once per instrument-day:

        (a) the account-wide submit-intent latch -- this closes the
            in-flight sibling race: an OPEN intent (a genuine in-flight
            order, or a crash-left singleton no resolver has cleared yet)
            must refuse a NO shadow evaluation exactly like `_hunt_tick`'s
            own `is_intent_open()` check already refuses the YES arm path.
            (In THIS call frame that check already ran, synchronously,
            before `_hunt_tick` ever reached `evaluate_both_sides` -- this
            is defence in depth against a future reordering, not dead
            code by intent.)
        (b) `refuse_if_sibling_leg_traded` for the YES sibling of this NO
            instrument (a same-slug YES fill forbids the NO leg, S4/§3).
        (c) `station_day_admission` (R3-7), enumerating BOTH legs of every
            rung on this station-day -- the caller obligation the S4
            review named, since `station_day_admission` never scans the
            store itself.
        (d) the existing day-budget stop and the per-instrument-day
            `is_consumed` check, keyed on the NO instrument id.

        `TrialDayLatch` (S1/S4, frozen for this slice) has no public
        accessor for its store/key-prefix -- `refuse_if_sibling_leg_traded`
        and `station_day_admission` are pure functions over exactly those,
        by design (S4's own docstrings: neither needs the flock). Reading
        the two private fields here is the narrowest bridge that avoids
        touching `trial_day_latch.py`.

        Safety review finding 1 (2026-09-14, commit f2d33f4): both gate
        functions, and the shared `_key` builder underneath them, now
        accept EITHER the bare symbol or the DOTTED `str(InstrumentId)`
        form and normalise to one canonical (dotted) key -- so this method
        passes the SAME dotted `iid`/`no_iid` convention every OTHER
        `key_instrument_id` in this module already uses (`iid =
        str(snapshot.instrument_id)`), rather than a bare form that would
        have matched nothing a real fill ever writes.

        Safety review finding 2: `existing_instrument_ids` (for `station_
        day_admission`) is the union of every rung resolved in `self._facts`
        for this station-day (today's ladder) AND every instrument with a
        durable venue fill on record (`TrialDayLatch.iter_fill_records`,
        the SAME primitive `_run_never_arm_walk` already uses) that joins
        to this station-day -- a rung filled earlier and since dropped from
        `self._facts` (a mid-day relaunch) still contributes its `q`.
        """
        no_instrument_id = sibling_instrument_id(yes_instrument_id)
        no_iid = str(no_instrument_id)

        def _append_no_offer_tape(*, decision_label: str, admission_reason: str | None) -> None:
            """GAP fix 2026-09-15: ONE offer-tape row per branch this method
            can return from -- pure side effect, never read back by this
            method or anything it calls, so it cannot change which branch
            fires (L-34/D3).
            """
            ask_str: str | None
            if isinstance(no_decision, Take):
                ask_str = str(no_decision.limit_price)
                reason = "taken"
            else:
                # M1 review finding (commit 309dab6): `None`, not `""` -- a
                # NO row with no bid has no `1 - bid` ask to report at all,
                # matching `OfferTapeRecord.ask`'s `str | None` contract.
                ask_str = None if bid is None else str(_ONE - bid)
                reason = no_decision.reason
            row_p_bound = no_decision.p_bound
            row_break_even = no_decision.break_even
            row_size = 0 if bid_size is None else int(bid_size)
            self.offer_tape.append(
                OfferTapeRecord(
                    station=station,
                    climate_day=climate_day_key,
                    instrument_id=no_iid,
                    ask=ask_str,
                    size=row_size,
                    reason=reason,
                    ts_event=now_ns,
                    hour_lst=hour_lst,
                    width_code=width_code,
                    m_code=m_code,
                    trigger="no_side_shadow",
                    quote_age_ns=None,
                    minutes_since_window_open=max(0, hour_lst - _WINDOW_START_HOUR_LST) * 60,
                    prior_eligible_snaps=0,
                    illegal_cell=False,
                    source="no_side_shadow",
                    side="NO",
                    p_bound=row_p_bound,
                    break_even=row_break_even,
                    running_max_lower=(
                        None if running_max is None else Decimal(running_max.lower_f)
                    ),
                    running_max_upper=(
                        None if running_max is None else Decimal(running_max.upper_f)
                    ),
                    running_max_exact=running_max is not None and running_max.exact_f is not None,
                    staleness_ns=staleness_ns,
                    fee_coefficient=fee_coefficient,
                    observed_at_ns=(
                        None if running_max is None else running_max.source_observed_at_ns
                    ),
                    admission_reason=admission_reason,
                    decision=decision_label,
                )
            )

        if not isinstance(no_decision, Take):
            _append_no_offer_tape(decision_label="refuse", admission_reason=None)
            return
        assert self._latch is not None
        notice_key = (station_day[0], station_day[1], no_iid)

        def _refuse_once(reason: str) -> None:
            if notice_key in self._no_refuse_notice:
                return
            self._no_refuse_notice.add(notice_key)
            self._record_no_refuse(f"no_refuse: reason={reason}")

        if self._latch.is_intent_open():
            _refuse_once(_NO_REFUSE_INTENT_OPEN)
            _append_no_offer_tape(decision_label="refuse", admission_reason=_NO_REFUSE_INTENT_OPEN)
            return

        store = self._latch._store
        prefix = self._latch._key_prefix
        # NO-SIDE S5 (E3-2/E3-5): the bounded first-order containment
        # window, checked IMMEDIATELY after `is_intent_open` and BEFORE any
        # side effect below (mirroring `is_intent_open`'s own pre-filter
        # precedent). This does NOT refuse the evaluation itself -- the
        # hunt stays observable while pending (E3-5): every gate below
        # still runs, and only the terminal shadow log's `pending=` field
        # reflects the containment state. Submission (this method's
        # `NO_SIDE_SHADOW_ONLY` scope has none yet) is the thing the
        # closed-set reason `no_side_first_order_pending`
        # (`LATCH_GATE_REFUSAL_REASONS`) will gate once §5 flips the flag.
        pending = is_no_side_pending(store)

        sibling_refusal = refuse_if_sibling_leg_traded(
            store, prefix, station, climate_day_key, no_iid,
        )
        if sibling_refusal is not None:
            _refuse_once(sibling_refusal.reason)
            _append_no_offer_tape(decision_label="refuse", admission_reason=sibling_refusal.reason)
            return

        existing_ids: list[str] = []
        seen_ids: set[str] = set()

        def _add_leg(instrument_id_obj: InstrumentId) -> None:
            leg_iid = str(instrument_id_obj)
            if leg_iid in seen_ids:
                return
            seen_ids.add(leg_iid)
            existing_ids.append(leg_iid)

        for iid, facts in self._facts.items():
            if (facts.settlement_station, facts.climate_day.isoformat()) != station_day:
                continue
            yes_iid_obj = InstrumentId.from_str(iid)
            _add_leg(yes_iid_obj)
            _add_leg(sibling_instrument_id(yes_iid_obj))
        for fill_record in self._latch.iter_fill_records(self._candidate_instrument_ids()):
            joined = self._join_fill_to_station_day(
                InstrumentId.from_str(fill_record.instrument_id),
            )
            if joined != station_day:
                continue
            fill_iid_obj = InstrumentId.from_str(fill_record.instrument_id)
            _add_leg(fill_iid_obj)
            _add_leg(sibling_instrument_id(fill_iid_obj))
        admission_refusal = station_day_admission(
            store,
            prefix,
            station,
            climate_day_key,
            "no",
            no_decision.break_even,
            existing_instrument_ids=tuple(existing_ids),
        )
        if admission_refusal is not None:
            _refuse_once(admission_refusal.reason)
            _append_no_offer_tape(
                decision_label="refuse", admission_reason=admission_refusal.reason,
            )
            return

        utc_day = utc_day_for_ns(now_ns).isoformat()
        if self._latch.is_day_budget_exhausted(utc_day):
            _refuse_once(_NO_REFUSE_DAY_BUDGET_EXHAUSTED)
            _append_no_offer_tape(
                decision_label="refuse", admission_reason=_NO_REFUSE_DAY_BUDGET_EXHAUSTED,
            )
            return
        if self._latch.is_consumed(station, climate_day_key, key_instrument_id=no_iid):
            _refuse_once(_NO_REFUSE_TRIAL_DAY_CONSUMED)
            _append_no_offer_tape(
                decision_label="refuse", admission_reason=_NO_REFUSE_TRIAL_DAY_CONSUMED,
            )
            return

        # GAP fix 2026-09-15: every gate above has cleared -- this snapshot
        # is a genuinely ADMITTED NO candidate (would arm, or already has,
        # depending on `pending`/`NO_SIDE_SHADOW_ONLY` below). ONE row per
        # finalized evaluation, never per WAIT tick -- this line runs
        # exactly once per `_evaluate_no_side_shadow` call that reaches it.
        _append_no_offer_tape(decision_label="take", admission_reason="admitted")

        minute_bucket = now_ns // _NS_PER_MINUTE
        # E3-5: the hunt stays observable while pending -- log every minute,
        # even for a take that would have submitted, BEFORE the flag/pending
        # branch below decides whether it actually arms.
        if self._no_shadow_notice.get(notice_key) != minute_bucket:
            self._no_shadow_notice[notice_key] = minute_bucket
            self._record_no_take_shadow(
                f"no_take_shadow: station={station} instrument={no_iid} "
                f"no_ask={no_decision.limit_price} p_miss_lower={no_decision.p_bound} "
                f"be={no_decision.break_even} bid_size={bid_size} "
                f"pending={1 if pending else 0}"
            )

        if NO_SIDE_SHADOW_ONLY:
            # S3b (frozen behaviour): never arm, consume, or submit.
            return

        # NO-SIDE S5 tail (§5 plan): the flag is False -- arm the NO take
        # exactly like the YES arm block (:1020-1041), keyed on `no_iid`,
        # UNLESS the bounded first-order protocol (E2-1/E3-2) is pending.
        # E3-2/E3-5 (pinned by test_no_side_first_order_pending_2026_09_14.py):
        # this is a silent WAIT, never a `no_refuse:` -- `NO_SIDE_FIRST_
        # ORDER_PENDING_REASON` lives in `LATCH_GATE_REFUSAL_REASONS` for
        # the client-side denial path, not for a `Refusal`/`_refuse_once`
        # this method would raise.
        if pending:
            return
        # SAFETY (adjudicated placement, strategy-side, mirrors client.py's
        # SAFETY C1 comment at `_submit_order`): this write and the arm
        # block below run with NO `await` between the `pending` read above
        # and here -- `Strategy.on_quote_tick`/`on_data` are plain
        # synchronous methods, so two stations' ticks handled back-to-back
        # in one process cannot interleave: whichever call reaches this
        # line first WRITES the key and COMMITs (`SqliteStateStore.set`
        # commits before returning) before it ever yields control, so the
        # second call's OWN `pending = is_no_side_pending(store)` read,
        # taken at the top of its own invocation of this method, observes
        # `True` and returns above -- never reaching this line. The key is
        # NEVER cleared by this method: if `_maybe_submit` below goes on to
        # refuse (permit exhausted, budget cap, latch already armed by a
        # true concurrent submit_order path), the key stays SET -- "pending
        # with no order" fails closed exactly like `client.py`'s own C1
        # WAIT (no money moved, but no further NO arm is granted either).
        store.set(
            NO_SIDE_FIRST_LIVE_ORDER_KEY,
            first_live_order_payload(no_iid, now_ns),
        )
        self._decision_ask_by_station_day[(station, climate_day_key)] = no_decision.limit_price
        self._latch.set_inflight(station, climate_day_key, key_instrument_id=no_iid)
        self._latch.record_attempt(
            station, climate_day_key, ts_ns=now_ns, key_instrument_id=no_iid,
        )
        self._record_rearm_decision(
            f"rearm: {station}/{climate_day_key} NO armed instrument={no_iid}"
        )
        self._maybe_submit(no_iid, no_decision)
        if not self._submission_armed():
            self._latch.clear_inflight(station, climate_day_key, key_instrument_id=no_iid)

    def _record_no_take_shadow(self, summary: str) -> None:
        """Mirrors `_record_rearm_decision` -- stores the ONE summary line
        on `self.last_no_take_shadow` (asserted by presence, L-27) and
        emits it via the overridable seam below. Stable grep token
        `no_take_shadow:`.
        """
        self.last_no_take_shadow = summary
        self._emit_no_take_shadow(summary)

    def _emit_no_take_shadow(self, summary: str) -> None:
        self.log.info(summary)

    def _record_no_refuse(self, summary: str) -> None:
        """Mirrors `_record_no_take_shadow` above for the refusal line,
        stable grep token `no_refuse:`.
        """
        self.last_no_refuse = summary
        self._emit_no_refuse(summary)

    def _emit_no_refuse(self, summary: str) -> None:
        self.log.info(summary)

    def _emit_take_log(self, summary: str) -> None:
        """GAP fix 2026-09-15 (brief item 4): overridable seam for the
        `take:` INFO line, mirroring `_emit_no_take_shadow` above. Stable
        grep token `take:`.
        """
        self.log.info(summary)

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
        elapsed, AND an eof-complete positions read showing no LONG on this
        instrument (R-8: a slug ABSENT from the page is confirmed FLAT for
        a candidate instrument, when fresh and Nautilus-reconciled-flat --
        see :func:`startup_evidence_confirms_absent_flat`).

        This evidence is read FRESH FROM THE STORE -- the durable record
        the exec client wrote at `_connect` (`exec/client.py:1117`) or at a
        resolver terminal-zero resolution (`exec/client.py:1536`) -- it is
        NOT a fresh VENUE read (that is HF-4's scope). ``now_ns`` here is
        venue EVENT time (`_hunt_tick:587`), used ONLY for the delay-floor
        comparison below; freshness for the absence branch is computed
        separately, from `self.clock.timestamp_ns()` (wall time) against
        the record's own wall-clock `ts_ns` -- R2-B1/L-2, HB7-4. Within the
        freshness ceiling this record can predate an unmapped fill (R14,
        a named residual, not fail-closed by this gate alone -- bounded by
        `is_intent_open()` and the resolver's ACCEPT_FILL terminal).
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
        # through the same helpers and the same freshness ceiling. R3-B1:
        # freshness reads the WALL clock INSIDE this method -- NOT the
        # `now_ns` parameter above, which is venue EVENT time
        # (`_hunt_tick:587`, `snapshot.ts_event`) and keeps its only
        # existing use, the delay-floor comparison above. Reusing `now_ns`
        # here would understate the age under feed lag and silently extend
        # the ceiling (a fail-OPEN, HB7-4).
        if startup_evidence_lists_slug(evidence, slug):
            net_position = startup_evidence_position_for(evidence, slug)
            # B5 (Rev 2, security HIGH): symmetric with the absent branch
            # below -- HF-4 makes attempts 2-3 reachable, so the page alone
            # is no longer sufficient at site 2. Site 1
            # (`_run_never_arm_walk`) is deliberately left asymmetric: see
            # the present-row pin at `test_continuous_rung_hold_fill_
            # wiring.py:720-744` and HF-4.rev2.md Decision 2(iii)/Risk R-J.
            return (
                net_position is not None
                and net_position <= 0
                and self.portfolio.net_position(InstrumentId.from_str(instrument_id)) <= 0
            )
        # Option B (HB7-3): same later, independent Nautilus cross-check as
        # site 1 -- an AND on the arming side only (AC-11/AC-12). B4(ii)
        # (R-9a): the RE-ARM ceiling (180s) is tighter than the boot-walk's
        # 600s -- `_STARTUP_EVIDENCE_MAX_AGE_NS` keeps its only OTHER
        # consumer, site 1 `_run_never_arm_walk`.
        return startup_evidence_confirms_absent_flat(
            evidence, slug,
            now_ns=self.clock.timestamp_ns(),
            max_age_ns=_REARM_EVIDENCE_MAX_AGE_NS,
        ) and self.portfolio.net_position(InstrumentId.from_str(instrument_id)) <= 0

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
        self._latch.clear_inflight(
            facts.settlement_station,
            facts.climate_day.isoformat(),
            key_instrument_id=str(event.instrument_id),
        )

    def _release_stale_inflight(
        self,
        station: str,
        climate_day: str,
        instrument_id: str,
        *,
        attempts: int,
        last_attempt_ns: int | None,
        now_ns: int,
    ) -> bool:
        """HF-4 Decision 1 (1B): release a stale IN_FLIGHT marker once the
        account-wide submit intent has CLOSED, so a non-fill outcome
        (create-path zero-fill, a resolver terminal-zero resolution, a
        crash before ``arm()``, or a restart against an already-retired
        intent) makes PREREG v3 §5's attempts 2 and 3 reachable. A genuine
        fill never reaches here: ``is_consumed`` short-circuits
        ``_hunt_tick`` before IN_FLIGHT is ever consulted again (AC-7).

        Returns ``True`` iff this call cleared the marker. Keyword-only,
        no defaults (L-28), matching :meth:`_rearm_permitted`. Every
        return path logs (L-30).
        """
        assert self._latch is not None
        try:
            intent_open = self._latch.is_intent_open()
        except TrialDayLatchError:
            # Edge case (Decision 1, fail-closed properties): an unbound
            # intent_latch double raises rather than answers -- treated as
            # OPEN, never release. A construction defect in a test double,
            # never a live path (see ``open_trial_day_latch``).
            self.log.debug(
                f"rearm: {station}/{climate_day} inflight release skipped -- "
                "is_intent_open() raised (unbound intent_latch); treating "
                "as OPEN"
            )
            return False
        if intent_open:
            self.log.debug(
                f"rearm: {station}/{climate_day} inflight release skipped -- "
                "the account-wide submit intent is still OPEN"
            )
            return False
        if last_attempt_ns is None or now_ns < last_attempt_ns + _REARM_MIN_DELAY_NS:
            # `attempts == 0` with IN_FLIGHT set (Phase-0 residue / a
            # pre-HF-4 crash) has `last_attempt_ns is None` -- fail closed,
            # never release (`:857` already self-clears Phase 0). The
            # same-burst race (`set_inflight` precedes `arm()`) is bounded
            # by the same delay floor the re-arm gate itself uses.
            self.log.debug(
                f"rearm: {station}/{climate_day} inflight release skipped -- "
                "the same-burst delay floor has not elapsed"
            )
            return False
        self._latch.clear_inflight(station, climate_day, key_instrument_id=instrument_id)
        self.diagnostics.record(_DIAG_INFLIGHT_RELEASED)
        self._report_alerter(
            self.diagnostics_alerter,
            "continuous_rung_hold diagnostics report failed",
        )
        self._record_rearm_decision(
            f"rearm: {station}/{climate_day} released a stale IN_FLIGHT "
            f"marker (attempts={attempts})"
        )
        return True

    def _record_rearm_denial_once(self, station_day: tuple[str, str], attempts: int) -> None:
        """AC-17: one INFO per FIRST denial per ``(station_day, reason)`` --
        an unconditional per-tick INFO would flood at depth-frame rate.
        """
        reason = "attempt_cap" if attempts >= _MAX_STATION_DAY_ATTEMPTS else "not_ready"
        key = (station_day, reason)
        if key in self._rearm_decision_dedupe:
            return
        # AM-3 (Rev 2.1, architect N1): bounded -- discard rather than grow
        # unboundedly across a long-running process, citing the unbounded-
        # diagnostics OOM lesson (`unit-memory-cap-is-containment`). NOT
        # applied to the pre-existing `_resolver_stale_alerted_intent_ids`
        # (out of scope, client.py).
        if len(self._rearm_decision_dedupe) > 4096:
            self._rearm_decision_dedupe = set()
        self._rearm_decision_dedupe.add(key)
        self._record_rearm_decision(
            f"rearm: {station_day[0]}/{station_day[1]} denied reason={reason} "
            f"attempts={attempts}"
        )

    def _record_rearm_decision(self, summary: str) -> None:
        """B3 (Decision 3, HF-4 rev2): mirrors ``_record_startup_evidence_
        summary`` (:474-488) -- stores the ONE summary line for this
        transition on ``self.last_rearm_decision`` (asserted by presence,
        L-27) and emits it via the overridable seam below. Stable grep
        token ``rearm:``.
        """
        self.last_rearm_decision = summary
        self._emit_rearm_decision(summary)

    def _emit_rearm_decision(self, summary: str) -> None:
        """Mirrors ``_emit_startup_evidence_summary`` (:490-501): production
        body is exactly one ``self.log.info`` call -- overridable so a test
        can record calls instead of asserting on captured log output (L-27).
        """
        self.log.info(summary)

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
        if str(event.client_order_id).startswith(EXPIRATION_LEG_PREFIX):
            # `check_instrument_expiration`'s own synthetic settlement-close
            # order (`backtest/engine.pyx:5952`) is not a genuine hunt fill --
            # counting it here would present the end-of-tape close as a
            # SECOND fill on an already-consumed station-day, tripping the
            # duplicate-fill family halt over a harness artefact, never a
            # market fact (L-8; mirrors `resting_ladder.py`'s own exclusion
            # of the same leg from its decision log, :290-297). Never joined,
            # never consumed, never counted as a duplicate.
            self.log.debug(
                f"on_order_filled: ignoring the engine's synthetic expiration "
                f"leg {event.client_order_id}",
            )
            return
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

    def _recorded_fee_for(
        self, instrument_id: InstrumentId, venue_order_id: str,
    ) -> Decimal | None:
        """The per-contract venue fee this fill's own durable
        `DurableFillRecord` supports, when known.

        RULING (option B, domain review of a9fd0fb): a genuine create-path
        fill left `TrialDayRecord.fee` permanently `None`, which made
        `station_day_admission` refuse EVERY second YES rung on a
        station-day (unknown `q` -- R3-7 never guesses) -- de facto one
        position per station, contradicting R-10. This reads through
        `TrialDayLatch.iter_fill_records`, the SAME read-only, store-based
        accessor the never-arm walk (`_run_never_arm_walk`) already uses to
        find fill records -- never a second store, never the adapters exec
        module imported here.

        Deliberately NEVER `event.commission`: the resolver path emits a
        synthetic `Money(0)` there, indistinguishable from a genuine zero
        fee (PREREG v3 fee-unreconciled-residual ruling).

        `None` unless a record for this EXACT `venue_order_id` exists, is
        `fee_reconciled`, and carries a positive `cumulative_qty` -- an
        absent, unreconciled, or zero-qty record leaves `q` UNKNOWN, and
        `station_day_admission` must keep refusing rather than guess (never
        relaxed by this helper).
        """
        assert self._latch is not None
        for candidate in self._latch.iter_fill_records((str(instrument_id),)):
            if candidate.venue_order_id != venue_order_id:
                continue
            if not candidate.fee_reconciled or candidate.cumulative_qty <= 0:
                return None
            return candidate.cumulative_fee / candidate.cumulative_qty
        return None

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
        instrument_id = str(event.instrument_id)
        venue_order_id = str(event.venue_order_id)
        decision_ask = self._decision_ask_by_station_day.pop((station, climate_day_key), None)
        ask = decision_ask if decision_ask is not None else event.last_px.as_decimal()
        fee = self._recorded_fee_for(event.instrument_id, venue_order_id)
        record = TrialDayRecord(
            latched_at_ns=event.ts_event,
            instrument_id=instrument_id,
            ask=ask,
            reason="taken",
            venue_order_id=venue_order_id,
            fee=fee,
        )
        wrote = self._latch.consume_if_absent(
            station, climate_day_key, record, key_instrument_id=instrument_id,
        )
        if wrote:
            # Live evidence (09-13): `continuous_rung_hold/inflight/MIA/
            # 2026-09-13` stayed `open` after the fill. IN_FLIGHT is
            # cleared only AFTER the durable trial write above has already
            # COMMIT-ted (`consume_if_absent` -> `StateStore.set`), never
            # before it -- a crash between the two leaves IN_FLIGHT set on
            # an already-consumed instrument-day, which is safe (fail
            # closed: `is_consumed` short-circuits `_hunt_tick` regardless).
            self._latch.clear_inflight(station, climate_day_key, key_instrument_id=instrument_id)
            return
        existing = self._latch.record_with_legacy_fallback(
            station, climate_day_key, key_instrument_id=instrument_id,
        )
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
            self._submission_armed()
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
