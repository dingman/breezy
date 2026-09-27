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

import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, cast

from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderDenied, OrderFilled, OrderRejected, PositionOpened
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
from breezy.strategy.current_rung_hold import exit_wiring
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import Decision, Refuse, Take, no_leg_executable
from breezy.strategy.current_rung_hold.diagnostics_summary import (
    DiagnosticsSummarySink,
)
from breezy.strategy.current_rung_hold.diagnostics_summary import (
    delta as _diagnostics_delta,
)
from breezy.strategy.current_rung_hold.exit_decider import ExitProposal
from breezy.strategy.current_rung_hold.offer_tape import OfferTape, OfferTapeRecord
from breezy.strategy.current_rung_hold.position_monitor import PositionMonitor
from breezy.strategy.current_rung_hold.resting_decider import (
    MAX_CLIMATE_DAYS_PER_STATION_LEG,
    ShadowRestingDecider,
    ShadowRestTickResult,
)
from breezy.strategy.current_rung_hold.shadow_rest_store import (
    ShadowRestSummary,
    write_shadow_rest_summaries,
)
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
    evaluate_eligible_snapshot_no_side,
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
from breezy.strategy.weather_common.halt_detector import HaltDetector
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
#: F-4 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): the `open_intent_wait:` log
#: line's own re-log cadence while the SAME intent_id persists.
_NS_PER_HOUR: Final[int] = 60 * _NS_PER_MINUTE
#: GAP fix 2026-09-15: `NO_ask = 1 - bid`, for the NO-side offer-tape row's
#: `ask` field ONLY when `no_decision` is a `Refuse` that never reached a
#: `Take.limit_price` -- mirrors `decision.py`'s own inversion exactly,
#: recomputed here purely for logging (never for a decision).
_ONE: Final[Decimal] = Decimal(1)
#: F-1a hardening (silent-failure-hunter finding, 2026-09-25): the
#: diagnostic reason `_hunt_no_only`'s containment handler records on every
#: exception it catches -- a NEW key (not a `REFUSAL_REASONS` member; there
#: is no closed-set validation on `self.diagnostics`), so a persistent store
#: fault is counted every tick even while its ERROR log is deduped.
_DIAG_NO_ONLY_HUNT_ERROR: Final[str] = "no_only_hunt_error"
_CLASS_NAME: Final[str] = "ContinuousRungHoldStrategy"
#: Domain review of 87446c2, finding 1: `_evaluate_shadow_rest`'s
#: containment fallback when the shadow decider raises -- a synthetic
#: no-op tick, never persisted as a real REST/CANCEL, so the offer tape's
#: `shadow_rest_*` fields still record SOMETHING (`"decider_error"`)
#: rather than silently going stale mid-run.
_SHADOW_REST_DECIDER_ERROR_RESULT: Final[ShadowRestTickResult] = ShadowRestTickResult(
    state="NONE",
    price=None,
    margin=None,
    price_secondary=None,
    reason="decider_error",
    fill_event=False,
)
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
#: EDGE-1 (AM-4): the entry-only "fee unverified" staleness veto WAIT --
#: distinct from `_DIAG_FAMILY_HALT` and from `self._fee_halt`'s own
#: (unnamed, bare-`return`) `fee_schedule_mismatch` refusal. Never engages
#: on the exit path (structurally untouched -- see `exit_wiring.py`).
_DIAG_FEE_UNVERIFIED: Final[str] = "fee_unverified"
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
#: INC-E3 (plan §3, PREREG v4 §5b): the exit-side diagnostics/position-event
#: counter names (`family_halt_ambiguous_exit`, `exit_filled`,
#: `exit_order_rejected`, `exit_fill_join_error`) now live as private
#: constants in `exit_wiring.py` (extraction: brief's "keep
#: continuous_strategy.py growth small") alongside the functions that
#: record them -- kept here only as this comment so a future reader
#: searching this file for the string still finds where it moved to.
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
    #: F-1b (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md, Rev 3.1): optional --
    #: `None` when a Depth10 frame carries a real bid but no real ask (the
    #: cheapest NO population, `on_order_book_depth`). `size` is `0` in that
    #: case. `_snapshot_from_quote` always sets a real `ask` (a `QuoteTick`
    #: cannot exist without both sides), so the QuoteTick path is unaffected.
    ask: Decimal | None
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


@dataclass(frozen=True, slots=True, kw_only=True)
class _EligibleSetup:
    """The three per-tick facts the YES path and the NO-only hunt (F-1a)
    both need, derived identically from the same snapshot -- extracted (A1,
    plan ``STALL_FOLLOWUPS_F1_F4_2026-09-24.md``) so `_hunt_no_only` can
    share them with `_hunt_tick`'s YES path without duplicating the calls.
    """

    width_code: int
    m_code: int
    fee_coefficient: Decimal | None
    staleness_ns: int | None


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


def _per_contract_reconciled_fee(record: DurableFillRecord) -> Decimal | None:
    """The per-contract fee a `DurableFillRecord` supports, when known.

    ONE shared derivation for both `TrialDayRecord.fee` call sites (companion
    ruling to option B, domain review of a9fd0fb): `ContinuousRungHoldStrategy
    ._recorded_fee_for` (create-path fill, `_consume_or_flag_duplicate`) and
    `_consume_trial_from_fill_record` (the boot never-arm walk's fill-record
    join). The boot walk re-adopts open positions through this join on every
    16:50Z reboot, so a fee derivation that only ran on the create path would
    re-impose the unknown-fee refusal on any later rung of that station-day
    after every restart -- this function makes both sites agree byte-for-byte.

    `None` unless `record` is `fee_reconciled` and carries a positive
    `cumulative_qty` -- an unreconciled or zero-qty record leaves `q`
    UNKNOWN, and `station_day_admission` must keep refusing rather than
    guess (never relaxed by this helper). Deliberately NEVER
    `event.commission`: the resolver path emits a synthetic `Money(0)`
    there, indistinguishable from a genuine zero fee (PREREG v3
    fee-unreconciled-residual ruling).
    """
    if not record.fee_reconciled or record.cumulative_qty <= 0:
        return None
    return record.cumulative_fee / record.cumulative_qty


class Phase0PermitForbiddenError(RuntimeError):
    """A non-None `order_submission_permit` was given in Phase 0.

    Phase 0 mints every `ContinuousRungHoldStrategy` (and its composition
    root, `build_continuous_rung_hold_strategies`) with `permit=None`; v3
    never holds the sealed order-submission capability while Phase 0 is in
    force (see `composition.py::phase1_sending_permit`).
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
        shadow_rest_summary_dir: Path | None = None,
        diagnostics_summary: DiagnosticsSummarySink | None = None,
        build_sha: str = "unknown",
        fee_verified_check: Callable[[int], bool] | None = None,
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

        ``fee_verified_check`` (EDGE-1, AM-2): ``None`` by default -- byte-
        identical to before this parameter existed, and the shape every
        paper-replay/test call site keeps (``ContinuousRungHoldBacktestStrategy``
        never exposes this parameter at all, so it always inherits this
        default). ``app/trade.py``'s live composition root is the ONE
        caller that passes a non-None callable (a late-bound holder over
        ``FeeDriftProbeActor.is_fee_verified``). When non-None, ``_hunt_tick``
        calls it with ``self.clock.timestamp_ns()`` -- never
        ``snapshot.ts_event`` (AM-1) -- immediately after the existing
        ``is_family_halted()``/``self._fee_halt`` checks, and refuses a NEW
        entry (never an exit -- structurally unreachable from
        ``exit_wiring.py``) whenever it returns ``False``.
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
        #: WP-R1: takes FINALIZED this process (counted at the same point
        #: the trial-day latch goes IN_FLIGHT), and the detector that reads
        #: it alongside `self.refusals`. Installed by
        #: `install_current_rung_hold_refusal_watch`; `None` in a test or a
        #: harness that never wires composition, in which case
        #: `_observe_halt` is a no-op.
        self.takes = 0
        self.halt_detector: HaltDetector | None = None
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
        #: EDGE-1 (AM-2): ``None`` means no check is configured -- every
        #: entry tick is treated as fee-verified, byte-identical to before
        #: this parameter existed. See the constructor docstring.
        self._fee_verified_check = fee_verified_check
        self.offer_tape = offer_tape if offer_tape is not None else OfferTape(offer_tape_path)
        # De-dupe key for the LAST ask evaluated per instrument, so a WS frame
        # that yields BOTH a QuoteTick and an OrderBookDepth10 (identical
        # ts_event -- same frame) is hunted once. One entry per instrument,
        # not a growing set: `on_data` retries deliberately re-evaluate the
        # SAME cached quote on a later weather update, so only the two live
        # push triggers ("quote_tick", "depth") ever consult or update this.
        self._last_ask_seen: dict[
            str, tuple[int, Decimal, int] | tuple[int, None, Decimal | None, Decimal | None]
        ] = {}
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
        #: F-1a hardening (silent-failure-hunter finding, 2026-09-25):
        #: dedupes `_hunt_no_only`'s containment ERROR log to once per
        #: (station, climate_day) for the life of the process -- mirrors
        #: `_illegal_cell_station_days`'s bounded shape, so a PERSISTENT
        #: store fault logs once, never once per tick.
        self._no_only_hunt_error_notice: set[tuple[str, str]] = set()
        #: Mirrors `last_rearm_decision`/`last_no_take_shadow` (L-27:
        #: asserted by presence, never via log capture) -- the MOST RECENT
        #: `_hunt_no_only` containment message actually LOGGED (never set
        #: on a deduped repeat, so its presence proves the guard fired
        #: without needing to capture the logger).
        self.last_no_only_hunt_error: str | None = None
        #: F-1c (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md, Rev 3.1): caches
        #: a POSITIVE `refuse_if_sibling_leg_traded` result keyed by
        #: `(station_day, yes_iid)` -- a fill record is durable and never
        #: reverts, so caching "this YES instrument-day is a confirmed
        #: fill" can never go stale. A NEGATIVE result (the YES record is
        #: consumed but not filled) is deliberately never cached (R4), so a
        #: later genuine fill on this same key is observed the very next
        #: tick. Bounded by the process's instruments, exactly like
        #: `_illegal_cell_station_days` -- see
        #: `_hunt_no_only_after_yes_consumed`.
        self._yes_fill_blocks_no: set[tuple[tuple[str, str], str]] = set()
        #: INC-5 (intra-day position monitor, SHADOW-ONLY): `None` (default)
        #: means every monitor hook below is a no-op -- byte-identical
        #: behaviour to before this field existed. A composition root wires
        #: a real `PositionMonitor` in after construction (`composition.py`);
        #: this strategy never constructs one itself and never reaches into
        #: its mutating surface (there is none -- M7 D3 pin).
        self._position_monitor: PositionMonitor | None = position_monitor
        #: RESTING_BID_HUNT Rev 2 §6 (shadow stage): a PURE counterfactual
        #: decider -- constructs no order, never touches `self._latch`, and
        #: is consulted AFTER every take/refuse decision below already
        #: fired, so it can never block or alter one (L-34/D3: computed +
        #: persisted, nothing else). `_shadow_rest_summaries` is the
        #: per-`(station, climate_day, leg)` tally flushed at `on_stop`;
        #: `_shadow_rest_summary_dir` is `None` (the shadow default) unless
        #: a composition root opts into the parquet sidecar.
        self._shadow_rest_decider = ShadowRestingDecider()
        self._shadow_rest_summaries: dict[str, ShadowRestSummary] = {}
        self._shadow_rest_summary_dir = shadow_rest_summary_dir
        #: Domain review of 87446c2, finding 2: counted evictions from the
        #: hard cap `_evict_stale_shadow_rest_summaries` enforces on
        #: `_shadow_rest_summaries` -- observable, never silent, so a
        #: genuine leak (evictions climbing every day) is distinguishable
        #: from ordinary multi-day overlap.
        self._shadow_rest_summary_evictions = 0
        #: F-4 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md, A7): dedupes the store
        #: read `current_open_submit_intent()` to at most once per event-
        #: time MINUTE bucket (`snapshot.ts_event // 60e9`) -- `None` until
        #: the first `is_intent_open()` WAIT tick this process ever sees.
        self._open_intent_wait_last_minute_bucket: int | None = None
        #: F-4: `(intent_id, last_logged_ns)` for the LOG line's OWN dedupe
        #: -- once per NEW `intent_id`, then at most once per hour while the
        #: SAME id persists. `None` until a line is actually logged.
        self._open_intent_wait_log_state: tuple[str, int] | None = None
        #: Mirrors `last_rearm_decision`/`last_no_take_shadow` (L-27:
        #: asserted by presence, never via log capture) -- the MOST RECENT
        #: `open_intent_wait:` line actually logged (never set on a
        #: deduped repeat).
        self.last_open_intent_wait: str | None = None
        #: F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md, A4): mirrors `self.
        #: takes` -- the NO leg's own FINALIZED-take count, incremented at
        #: the same point the latch goes IN_FLIGHT for `no_iid`.
        #: `HaltDetector.observe(takes=self.takes)` stays YES-only: no cited
        #: rule requires it to see this.
        self.no_takes = 0
        #: F-2 (coordinator carry-forward): distinct from `diagnostics`/
        #: `refusals` (no new alerter condition, AC4) -- counts an
        #: in-window bid-only Depth10 frame (F-1b), and, of those, the ones
        #: whose NO leg is ALSO outside the executable band. Both were
        #: invisible to every counter before this pair existed.
        self._bid_only_in_window_frames = 0
        self._no_out_of_band_frames = 0
        #: F-2: the optional shared hourly-diagnostics sidecar and this
        #: process's build identity -- `None`/`"unknown"` by default so a
        #: harness/test that never wires composition is byte-identical to
        #: before this pair of kwargs existed.
        self._diagnostics_summary = diagnostics_summary
        self._build_sha = build_sha
        #: Per-process attribution (A5) for every `crh_diag_hourly_v1` row.
        #: `_diag_boot_ns` is resolved once in `on_start` (the clock is not
        #: bound until `register()` runs); `0` here is never emitted since
        #: no row exists before `on_start`.
        self._diag_pid = os.getpid()
        self._diag_boot_ns = 0
        #: The event-time hour bucket (`ts_event // _NS_PER_HOUR`) of the
        #: MOST RECENT `_maybe_roll_diagnostics` call, and the counter
        #: snapshot taken at that call -- `None` until the first tick this
        #: process ever hunts. Bounded: exactly one bucket int and one
        #: bounded dict-of-dicts, never a growing collection.
        self._diag_hourly_bucket: int | None = None
        self._diag_hourly_baseline: dict[str, object] | None = None

    def _record_shadow_rest_tick(
        self,
        *,
        station: str,
        climate_day_key: str,
        leg: Literal["YES", "NO"],
        result: ShadowRestTickResult,
    ) -> None:
        """Tally one tick's shadow-decider outcome (observability only).

        Never raises into the caller's hot path -- a summary dict miss is
        the only failure mode here, and `setdefault` makes that impossible;
        this is a plain accumulator, no I/O, no exception surface.
        """
        summary_key = f"{station}|{climate_day_key}|{leg}"
        summary = self._shadow_rest_summaries.setdefault(
            summary_key,
            ShadowRestSummary(station=station, climate_day=climate_day_key, leg=leg),
        )
        summary.ticks_evaluated += 1
        summary.record_reason(result.reason)
        if result.fill_event:
            summary.fill_eligible_events += 1

    def _evaluate_shadow_rest(
        self,
        *,
        station: str,
        climate_day_key: str,
        leg: Literal["YES", "NO"],
        best_ask: Decimal | None,
        p_bound: Decimal | None,
        staleness_ns: int | None,
        cell_legal: bool,
        sibling_leg_filled: bool,
        fee_schedule_mismatch: bool = False,
    ) -> ShadowRestTickResult:
        """Compute-and-persist one tick's shadow resting-bid outcome,
        CONTAINED (domain review of 87446c2, finding 1).

        Mirrors `_forward_to_monitor`'s containment discipline: the shadow
        decider is compute-and-persist ONLY (`resting_decider.py`'s own
        module docstring) and must never raise into the live hunt tick. A
        decider exception is caught here, logged, and reported as the
        synthetic `_SHADOW_REST_DECIDER_ERROR_RESULT` (`"decider_error"`),
        so a bug in observability code can never kill `_hunt_tick`.
        """
        try:
            result = self._shadow_rest_decider.evaluate_tick(
                station=station,
                climate_day=climate_day_key,
                leg=leg,
                best_ask=best_ask,
                p_bound=p_bound,
                staleness_ns=staleness_ns,
                stale_bound_ns=self._config.stale_observation_minutes * _NS_PER_MINUTE,
                cell_legal=cell_legal,
                sibling_leg_filled=sibling_leg_filled,
                fee_schedule_mismatch=fee_schedule_mismatch,
            )
        except Exception as exc:  # the shadow decider must never affect the live hunt tick
            message = "continuous_rung_hold: shadow-rest decider failed"
            self.log.exception(message, exc)  # noqa: TRY401
            result = _SHADOW_REST_DECIDER_ERROR_RESULT
        self._record_shadow_rest_tick(
            station=station, climate_day_key=climate_day_key, leg=leg, result=result,
        )
        self._drain_shadow_rest_evictions()
        return result

    def _drain_shadow_rest_evictions(self) -> None:
        """Fold every eviction the decider self-enforced this tick
        (`ShadowRestingDecider.evaluate_tick`'s own hard cap, domain review
        finding 2) into `_shadow_rest_summaries` -- the evicted key's
        CANCEL is recorded exactly as a real window-close would be, even
        though the decider already bounded itself independent of this
        call. Then re-checks the summary dict's own independent cap.
        """
        for (station, climate_day, leg), result in self._shadow_rest_decider.drain_evictions():
            self._record_shadow_rest_tick(
                station=station, climate_day_key=climate_day, leg=leg, result=result,
            )
        self._evict_stale_shadow_rest_summaries()

    def _evict_stale_shadow_rest_summaries(self) -> None:
        """Hard cap on `_shadow_rest_summaries` itself (domain review of
        87446c2, finding 2), INDEPENDENT of the decider's own `_states`
        bound: `_shadow_rest_summaries` grows one entry per ticked
        `(station, climate_day, leg)` regardless of whether that key ever
        rested, so a long run touching many climate_days for one
        `(station, leg)` must never grow it past `MAX_CLIMATE_DAYS_PER_
        STATION_LEG` either. Evictions are counted
        (`_shadow_rest_summary_evictions`) and logged, never silent.
        """
        by_station_leg: dict[tuple[str, str], list[str]] = {}
        for summary_key in self._shadow_rest_summaries:
            station, climate_day, leg = summary_key.split("|")
            by_station_leg.setdefault((station, leg), []).append(climate_day)
        for (station, leg), days in by_station_leg.items():
            if len(days) <= MAX_CLIMATE_DAYS_PER_STATION_LEG:
                continue
            for stale_day in sorted(days)[:-MAX_CLIMATE_DAYS_PER_STATION_LEG]:
                stale_key = f"{station}|{stale_day}|{leg}"
                if self._shadow_rest_summaries.pop(stale_key, None) is None:
                    continue
                self._shadow_rest_summary_evictions += 1
                self.log.warning(
                    "continuous_rung_hold: evicted stale shadow-rest summary "
                    f"{stale_key!r} (evictions so far: "
                    f"{self._shadow_rest_summary_evictions})",
                )

    def _flush_shadow_rest_summaries(self) -> None:
        """`on_stop`: close every still-RESTING key (CANCEL `window_close`,
        recorded on the summary, never on the offer tape -- no tick exists
        for a window-close transition to ride on), then flush the run's
        tally to the optional parquet sidecar. Best-effort, mirroring every
        other optional sidecar in this package (`OfferTape`, `MarkBuffer`):
        a failure here must never raise out of `on_stop` (finding 3, domain
        review of 87446c2 -- the whole body is contained, not just the
        write call, so `exit_stack.close()`/clearing `self._latch` always
        run regardless of what fails here). A successful write clears
        `_shadow_rest_summaries` (finding 4) so a second `on_stop` call --
        the shape every other `on_stop` idempotence test in this package
        already pins -- writes nothing rather than re-writing a stale run.
        """
        try:
            for (station, climate_day, leg), result in (
                self._shadow_rest_decider.close_all_windows()
            ):
                summary_key = f"{station}|{climate_day}|{leg}"
                summary = self._shadow_rest_summaries.get(summary_key)
                if summary is not None:
                    summary.still_resting_at_stop = True
                    summary.record_reason(result.reason)
            if self._shadow_rest_summary_dir is None or not self._shadow_rest_summaries:
                return
            write_shadow_rest_summaries(
                self._shadow_rest_summary_dir,
                tuple(self._shadow_rest_summaries.values()),
                now_ns=self.clock.timestamp_ns(),
            )
            self._shadow_rest_summaries.clear()
        except Exception as exc:  # on_stop's cleanup must always complete
            message = "continuous_rung_hold: shadow-rest summary flush failed"
            self.log.exception(message, exc)  # noqa: TRY401

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
        # F-2: the clock is only bound once `register()` has run, so this is
        # the earliest point `self.clock.timestamp_ns()` is meaningful.
        self._diag_boot_ns = self.clock.timestamp_ns()
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
                # Companion to the create-path fix (option B, domain review
                # of a9fd0fb): this record is ALREADY in hand, so the SAME
                # derivation `_recorded_fee_for` uses is applied directly --
                # without this, every 16:50Z reboot's re-adoption of an open
                # position through this walk would re-impose the
                # unknown-fee refusal on any later rung of the station-day.
                fee=_per_contract_reconciled_fee(fill_record),
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

    def _station_day_existing_legs(
        self, station_day: tuple[str, str],
    ) -> tuple[tuple[str, ...], Mapping[str, DurableFillRecord]]:
        """ADM-1 shared helper for the YES (``:2143-2161`` pre-fix) and NO
        (``:2550-2568`` pre-fix) arm-time gates: every instrument-leg
        belonging to ``station_day`` -- today's facts ladder plus any
        durable fill reachable via ``iter_fill_records``, each deduped with
        its sibling -- PLUS a ``pending_fills`` map (keyed by the fill
        record's own dotted instrument id) for
        :func:`station_day_admission`'s ADM-1 fallback: a leg whose fill is
        already committed but has no TRIAL record yet (the create-path
        window between ``record_fill`` and this strategy processing the
        queued ``OrderFilled``) is still counted, from the fill's own
        realized cost, rather than silently contributing zero to Sigma-q.
        """
        assert self._latch is not None
        existing_ids: list[str] = []
        seen_ids: set[str] = set()
        pending_fills: dict[str, DurableFillRecord] = {}

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
        for fill_record in self._latch.iter_fill_records(self._candidate_instrument_ids()):
            joined = self._join_fill_to_station_day(
                InstrumentId.from_str(fill_record.instrument_id),
            )
            if joined != station_day:
                continue
            fill_iid_obj = InstrumentId.from_str(fill_record.instrument_id)
            _add_leg(fill_iid_obj)
            _add_leg(sibling_instrument_id(fill_iid_obj))
            pending_fills[fill_record.instrument_id] = fill_record
        return tuple(existing_ids), pending_fills

    def on_stop(self) -> None:
        self.log.info(self._diagnostics_snapshot_message())
        self.log.info(self._illegal_cell_snapshot_message())
        self._flush_diagnostics_summary_final()
        for iid in self._facts:
            self.unsubscribe_order_book_depth(InstrumentId.from_str(iid))
        if self._position_monitor is not None:
            monitor = self._position_monitor
            self._forward_to_monitor(lambda: monitor.on_stop(self.clock.timestamp_ns()))
        self._flush_shadow_rest_summaries()
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

    def _diagnostics_baseline_snapshot(self) -> dict[str, object]:
        """F-2: the full set of counters the hourly row's deltas are
        computed against. A plain dict-of-copies -- `diagnostics`/
        `refusals` are copied (mutable dicts, snapshotted by value) so a
        later in-place mutation of `self.diagnostics.counts` can never
        retroactively change an ALREADY-COMPUTED baseline.
        """
        sink = self._diagnostics_summary
        return {
            "diagnostics": dict(self.diagnostics.counts),
            "refusals": dict(self.refusals.counts),
            "takes": self.takes,
            "no_takes": self.no_takes,
            "offer_tape_capped": self.offer_tape.sidecar_capped,
            "bid_only_in_window": self._bid_only_in_window_frames,
            "no_out_of_band": self._no_out_of_band_frames,
            #: Silent-failure review (2026-09-25): the sidecar's OWN health
            #: mirrored into the NEXT row it (or, if it is itself the thing
            #: failing, the log line alone) can still deliver -- `0`/`0`
            #: when there is no sink at all, exactly like every other
            #: counter here defaults to "nothing happened".
            "diagnostics_summary_errors": 0 if sink is None else sink.errors,
            "diagnostics_summary_capped": 0 if sink is None else sink.capped,
        }

    def _maybe_roll_diagnostics(self, *, now_ns: int) -> None:
        """F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): event-time hourly
        rollover. On the FIRST call this process ever makes, only the
        baseline is captured (no emission -- there is no prior hour to
        close). On every later call whose bucket has moved FORWARD, the
        just-closed hour's deltas are emitted and the baseline resets to
        NOW. A bucket that has not advanced -- including one that appears
        to move BACKWARD (an out-of-order `on_data` retry re-evaluating an
        older cached quote) -- is a no-op: the bucket and baseline are
        never rolled back.
        """
        bucket = now_ns // _NS_PER_HOUR
        if self._diag_hourly_bucket is None:
            self._diag_hourly_bucket = bucket
            self._diag_hourly_baseline = self._diagnostics_baseline_snapshot()
            return
        if bucket <= self._diag_hourly_bucket:
            return
        closed_hour_start_ns = self._diag_hourly_bucket * _NS_PER_HOUR
        emitted = self._run_observability(
            "continuous_rung_hold diagnostics-summary rollover failed",
            lambda: self._emit_diagnostics_row(
                hour_utc_start_ns=closed_hour_start_ns, final=False,
            ),
        )
        # Silent-failure review (2026-09-25): the bucket (and therefore the
        # baseline `_emit_diagnostics_row` itself updates) advances ONLY on
        # a successful emission. A failure leaves both untouched, so the
        # NEXT tick -- in the SAME new hour -- retries emitting the SAME
        # closed hour's deltas rather than silently losing that hour's data
        # the moment a transient fault clears.
        if emitted:
            self._diag_hourly_bucket = bucket

    def _emit_diagnostics_row(self, *, hour_utc_start_ns: int, final: bool) -> bool:
        """F-2 Design: one INFO log line (Output 1) plus one JSONL row
        (Output 2, schema ``crh_diag_hourly_v1``) per emission -- deltas
        since the LAST emission for `diagnostics`, `refusals`, `takes`,
        `no_takes` and `offer_tape.sidecar_capped`, plus the two F-2
        coordinator counters. Never raises: called only from inside
        `_run_observability` (the rollover path) or `_flush_diagnostics_
        summary_final` (also wrapped there). Returns `True` on completion --
        `_maybe_roll_diagnostics` only advances its bucket once this
        returns (silent-failure review 2026-09-25): `_run_observability`
        itself returns `None` on a caught exception, so the caller can tell
        "emitted" from "raised" without a second flag.
        """
        baseline = self._diag_hourly_baseline
        if baseline is None:
            baseline = self._diagnostics_baseline_snapshot()
        current = self._diagnostics_baseline_snapshot()
        diag_delta = _diagnostics_delta(
            cast("Mapping[str, int]", baseline["diagnostics"]),
            cast("Mapping[str, int]", current["diagnostics"]),
        )
        refusals_delta = _diagnostics_delta(
            cast("Mapping[str, int]", baseline["refusals"]),
            cast("Mapping[str, int]", current["refusals"]),
        )
        takes_delta = cast(int, current["takes"]) - cast(int, baseline["takes"])
        no_takes_delta = cast(int, current["no_takes"]) - cast(int, baseline["no_takes"])
        tape_capped_delta = cast(int, current["offer_tape_capped"]) - cast(
            int, baseline["offer_tape_capped"]
        )
        bid_only_delta = cast(int, current["bid_only_in_window"]) - cast(
            int, baseline["bid_only_in_window"]
        )
        no_oob_delta = cast(int, current["no_out_of_band"]) - cast(
            int, baseline["no_out_of_band"]
        )
        summary_errors_delta = cast(int, current["diagnostics_summary_errors"]) - cast(
            int, baseline["diagnostics_summary_errors"]
        )
        summary_capped_delta = cast(int, current["diagnostics_summary_capped"]) - cast(
            int, baseline["diagnostics_summary_capped"]
        )
        station = ",".join(self._config.stations)
        emitted_at_ns = self.clock.timestamp_ns()
        self.log.info(
            f"diagnostics_hourly: station={station} hour_utc={hour_utc_start_ns} "
            f"diag={diag_delta} refusals={refusals_delta} takes=+{takes_delta} "
            f"no_takes=+{no_takes_delta} tape_capped=+{tape_capped_delta} "
            f"summary_errors=+{summary_errors_delta} summary_capped=+{summary_capped_delta} "
            f"build_sha={self._build_sha}"
        )
        row: dict[str, object] = {
            "schema": "crh_diag_hourly_v1",
            "station": station,
            "pid": self._diag_pid,
            "boot_ns": self._diag_boot_ns,
            "build_sha": self._build_sha,
            "hour_utc_start_ns": hour_utc_start_ns,
            "emitted_at_ns": emitted_at_ns,
            "diagnostics": diag_delta,
            "refusals": refusals_delta,
            "takes": takes_delta,
            "no_takes": no_takes_delta,
            "offer_tape_capped": tape_capped_delta,
            "bid_only_in_window": bid_only_delta,
            "no_out_of_band": no_oob_delta,
            "diagnostics_summary_errors": summary_errors_delta,
            "diagnostics_summary_capped": summary_capped_delta,
            "final": final,
        }
        if self._diagnostics_summary is not None:
            self._diagnostics_summary.append(row)
        self._diag_hourly_baseline = current
        return True

    def _flush_diagnostics_summary_final(self) -> None:
        """F-2 Design: "Emit a `final` row in `on_stop`". No-op if this
        process never hunted a single tick (no baseline was ever taken) --
        there is no hour to close. Wrapped in `_run_observability` so a
        sidecar/log failure at shutdown can never prevent the REST of
        `on_stop`'s own cleanup (latch/exit-stack) from running.
        """
        if self._diag_hourly_bucket is None:
            return
        hour_utc_start_ns = self._diag_hourly_bucket * _NS_PER_HOUR
        self._run_observability(
            "continuous_rung_hold diagnostics-summary final flush failed",
            lambda: self._emit_diagnostics_row(hour_utc_start_ns=hour_utc_start_ns, final=True),
        )

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
        """Hunt on the venue's own Depth10 book when quotes go dark (L-35).

        A one-sided book (no bid) never produces a `QuoteTick`
        (`parse_quote_tick` requires both sides) but still carries a real,
        executable ask -- `best_order` skips the size-0 Arrow pad.

        F-1b (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md, Rev 3.1): the
        REVERSE one-sided book -- a real bid, no real ask -- is the cheapest
        NO population (amendment sec2:32 reads a bid-only Depth10 update as
        an update to the NO leg's own ask) and must reach `_hunt_tick` too,
        never return here. Only a book with NEITHER side returns early.
        """
        ask = best_order(depth.asks)
        bid = best_order(depth.bids)
        if ask is None and bid is None:
            return
        snapshot = _AskSnapshot(
            instrument_id=depth.instrument_id,
            ask=ask.price.as_decimal() if ask is not None else None,
            size=int(ask.size) if ask is not None else 0,
            ts_event=depth.ts_event,
            source="depth",
            bid=bid.price.as_decimal() if bid is not None else None,
            bid_size=bid.size.as_decimal() if bid is not None else None,
        )
        self._hunt_tick(snapshot, trigger="depth", quote_age_ns=None)
        if self._position_monitor is not None:
            monitor = self._position_monitor
            self._forward_to_monitor(lambda: monitor.on_depth(depth, depth.ts_event))

    def _eligible_setup(
        self,
        instrument_id: InstrumentId,
        facts: WeatherBucketFacts,
        running_max: RunningMax,
        accumulator: RunningExtremeAccumulator,
        now_ns: int,
    ) -> _EligibleSetup:
        """Pure extraction (A1, F-1a) of the YES path's three per-tick
        lookups -- `width_and_m`, `_guarded_fee_coefficient`,
        `accumulator.staleness_ns` -- same calls, same order, no behaviour
        change. Shared by `_hunt_tick`'s YES path and `_hunt_no_only`.
        """
        width_code, m_code = width_and_m(facts, running_max)
        instrument = self.cache.instrument(instrument_id)
        fee_coefficient = self._guarded_fee_coefficient(instrument)
        staleness_ns = accumulator.staleness_ns(now_ns)
        return _EligibleSetup(
            width_code=width_code,
            m_code=m_code,
            fee_coefficient=fee_coefficient,
            staleness_ns=staleness_ns,
        )

    def _hunt_no_only(
        self,
        snapshot: _AskSnapshot,
        facts: WeatherBucketFacts,
        *,
        station: str,
        climate_day: date,
        climate_day_key: str,
        station_day: tuple[str, str],
        now_ns: int,
        hour_lst: int,
    ) -> None:
        """F-1a (plan ``STALL_FOLLOWUPS_F1_F4_2026-09-24.md``): a quiet
        NO-only evaluation, reached ONLY from `_hunt_tick`'s
        ``not raw_executable`` branch, and only when the caller has already
        proven ``no_leg_executable`` for this snapshot. The YES path
        (`_hunt_tick`'s ``:1336`` onward) is untouched: this method always
        returns before it, and this method itself never touches
        ``self.diagnostics``/``self.refusals``/``self._eligible_snap_counts``
        or the YES offer-tape row -- restoring the registered NO population
        (PREREG v3 amendment §1:13/§2:32; the F-1 diagnosis's finding: the
        YES-ask-in-band requirement at the caller was the code's deviation,
        not this branch) must never add a second count to a tick the caller
        already counted once.

        Steps 1-2 are QUIET (no diagnostic, no tape row): an unresolved
        running max or an off-rung instrument is upstream state the YES
        path already has its own (counted) gates for on the SAME tick --
        this NO-only path must not double-count it. Step 3 shares the exact
        per-tick lookups the YES path uses (`_eligible_setup`). Step 4, when
        ``snapshot.ask`` is present, reuses `evaluate_both_sides` so the
        crossed-book check (``tick_eval.py``'s own ``bid >= ask`` guard) is
        single-sourced -- never re-implemented here. F-1b (Rev 3.1): when
        ``snapshot.ask`` is ``None`` (a bid-only Depth10 frame -- there is
        no ask to cross against), it calls
        `evaluate_eligible_snapshot_no_side` directly -- the same NO-side
        evaluate path `evaluate_both_sides` itself calls for its own
        ``.no`` -- so both branches run the identical NO-side rule order,
        never a second implementation. Step 5, `_evaluate_no_side_shadow`,
        is completely unchanged: it runs its own admission/budget/consumed
        gates independently, exactly as it already does on the YES-in-band
        path.

        CONTAINED (silent-failure-hunter finding, 2026-09-25): unlike the
        YES path's own store reads, which only happen on the rarer in-band
        Take, `_evaluate_no_side_shadow`'s store-backed gates run on every
        COMMON out-of-band-YES tick that reaches this method -- mirrors
        `_evaluate_shadow_rest`'s containment of its decider, so a raising
        store dependency here can never escape into `_hunt_tick`/
        `on_quote_tick`/`on_data`/`on_order_book_depth`. See
        `_contain_no_only_hunt_error` for the exact ordering-safety
        argument on `NO_SIDE_FIRST_LIVE_ORDER_KEY` vs. `is_inflight`.
        """
        try:
            accumulator = self._accumulators.get(station)
            running_max = None if accumulator is None else accumulator.value_at(now_ns)
            if running_max is None or accumulator is None:
                return
            if not instrument_rung_is_current(facts, running_max):
                return

            setup = self._eligible_setup(
                snapshot.instrument_id, facts, running_max, accumulator, now_ns,
            )
            no_decision: Decision
            if snapshot.ask is not None:
                both_sides = evaluate_both_sides(
                    station=station,
                    climate_day=climate_day,
                    now_ns=now_ns,
                    ladder=self._ladders[(station, climate_day_key)],
                    fee_coefficient=setup.fee_coefficient,
                    ask=snapshot.ask,
                    ask_size=snapshot.size,
                    bid=snapshot.bid,
                    bid_size=snapshot.bid_size,
                    running_max=running_max,
                    staleness_ns=setup.staleness_ns,
                    config=self._config,
                    hour_lst=hour_lst,
                    width_code=setup.width_code,
                    m_code=setup.m_code,
                )
                no_decision = both_sides.no
            else:
                # F-1b: no ask on this frame, so `evaluate_both_sides`'s own
                # crossed-book check (which needs both sides) does not
                # apply -- there is nothing to be crossed against.
                no_decision = evaluate_eligible_snapshot_no_side(
                    station=station,
                    climate_day=climate_day,
                    now_ns=now_ns,
                    ladder=self._ladders[(station, climate_day_key)],
                    fee_coefficient=setup.fee_coefficient,
                    bid=snapshot.bid,
                    bid_size=snapshot.bid_size,
                    running_max=running_max,
                    staleness_ns=setup.staleness_ns,
                    config=self._config,
                    hour_lst=hour_lst,
                    width_code=setup.width_code,
                    m_code=setup.m_code,
                )
            self._evaluate_no_side_shadow(
                station=station,
                climate_day_key=climate_day_key,
                station_day=station_day,
                yes_instrument_id=snapshot.instrument_id,
                no_decision=no_decision,
                now_ns=now_ns,
                bid_size=snapshot.bid_size,
                bid=snapshot.bid,
                hour_lst=hour_lst,
                width_code=setup.width_code,
                m_code=setup.m_code,
                fee_coefficient=setup.fee_coefficient,
                staleness_ns=setup.staleness_ns,
                running_max=running_max,
            )
        except Exception as exc:  # noqa: BLE001 - a NO-only hunt fault must never affect _hunt_tick
            self._contain_no_only_hunt_error(
                exc,
                yes_instrument_id=snapshot.instrument_id,
                station=station,
                climate_day_key=climate_day_key,
            )

    def _contain_no_only_hunt_error(
        self,
        exc: Exception,
        *,
        yes_instrument_id: InstrumentId,
        station: str,
        climate_day_key: str,
    ) -> None:
        """Containment tail for `_hunt_no_only` (silent-failure-hunter
        finding, 2026-09-25). Never raises.

        Counts every fault (uncapped -- a persistent fault is never
        silently invisible after the first tick), but logs at ERROR at
        most once per (station, climate_day) for the life of the process
        (`_no_only_hunt_error_notice`), so a persistent store fault cannot
        flood the log.

        Ordering safety: `NO_SIDE_FIRST_LIVE_ORDER_KEY` is NEVER touched
        here, matching `_evaluate_no_side_shadow`'s own documented
        fail-closed stance on that key -- if the fault struck AFTER it was
        durably written, clearing it would be the UNSAFE direction: it
        would grant a second NO arm attempt while the first's outcome is
        still unknown. `is_inflight(no_iid)` IS defensively cleared,
        itself contained -- no gate in this module ever reads NO's
        `is_inflight` (only the YES `iid`'s is, in `_hunt_tick`'s own
        re-arm gate), so clearing it can never grant an arm that would
        otherwise be denied; it only prevents a stale marker from
        outliving the tick that half-wrote it.
        """
        self.diagnostics.record(_DIAG_NO_ONLY_HUNT_ERROR)
        notice_key = (station, climate_day_key)
        if notice_key not in self._no_only_hunt_error_notice:
            self._no_only_hunt_error_notice.add(notice_key)
            message = (
                f"continuous_rung_hold: NO-only hunt failed station={station} "
                f"climate_day={climate_day_key}"
            )
            self.last_no_only_hunt_error = message
            self.log.exception(message, exc)
        if self._latch is None:
            return
        no_iid = str(sibling_instrument_id(yes_instrument_id))
        try:
            self._latch.clear_inflight(station, climate_day_key, key_instrument_id=no_iid)
        except Exception as cleanup_exc:  # cleanup must never itself raise
            cleanup_message = (
                "continuous_rung_hold: NO-only hunt error cleanup (clear_inflight) failed"
            )
            self.log.exception(cleanup_message, cleanup_exc)  # noqa: TRY401

    def _hunt_no_only_after_yes_consumed(
        self,
        snapshot: _AskSnapshot,
        facts: WeatherBucketFacts,
        *,
        station: str,
        climate_day: date,
        climate_day_key: str,
        station_day: tuple[str, str],
        iid: str,
    ) -> None:
        """F-1c (plan ``STALL_FOLLOWUPS_F1_F4_2026-09-24.md``, Rev 3.1):
        reached ONLY from `_hunt_tick`'s ``is_consumed(YES iid)`` branch,
        which today returns unconditionally. Amendment §4:114 excludes a NO
        take only when the sibling YES leg already has a *fill* on record
        (``_FILLED_REASONS``) -- a YES instrument-day that was merely
        EVALUATED and refused (never filled) must still reach NO.

        Fail-closed argument (R3). A YES order that reached ``submit_order``
        without a confirmed fill is AMBIGUOUS by default (L-36); the
        account-wide submit intent stays OPEN until the resolver retires it
        with venue evidence (R-7; PREREG v3 §4; L-48 names the clearing
        path). While that intent is OPEN, step 2 below returns silently, and
        `_evaluate_no_side_shadow` re-checks ``is_intent_open()`` again at
        its own gate -- so NO is evaluated next to a non-fill YES record
        only after the intent is retired, which means venue evidence has
        already said "not filled". That is exactly the case §4 permits.

        Step 1 reuses `refuse_if_sibling_leg_traded` on the NO id -- the
        SAME sibling-fill check the YES admission gate and
        `_evaluate_no_side_shadow`'s own admission gate already run -- so
        "is the consumed YES record actually a fill" is never a second,
        independently-drifting reason check. A POSITIVE result is cached in
        `self._yes_fill_blocks_no`, bounded by the process's instruments
        exactly like `self._illegal_cell_station_days` (R4): a fill record
        is durable and never reverts, so caching it can never go stale. A
        NEGATIVE result (a non-fill reason) is never cached, so a later
        genuine fill durably written to this SAME key is observed the very
        next tick.

        Writer-proof scope note (coordinator review of 10d46cf): the "no
        live path writes a non-fill YES record" dormancy claim (module
        docstring / commit message) covers ONLY this module, the v3
        continuous family. The v2 ``CurrentRungHoldStrategy``
        (``strategy.py``) CAN write a non-fill Refuse reason through its own
        ``consume`` call. That stays segregated from this module's writes by
        trial-key PREFIX -- ``DEFAULT_TRIAL_KEY_PREFIX`` (v2) vs
        ``CONTINUOUS_TRIAL_KEY_PREFIX`` (this module, injected into the
        latch factory this ``on_start`` enters via ``composition.py``) --
        and the two strategies are mutually exclusive ``composition_kind``
        branches (``"current_rung_hold"`` vs ``"continuous_rung_hold"``) in
        ``app/trade.py``, never composed against the same store.
        Composing both against one store, or unifying the prefix, would
        reactivate this method's non-fill branch in production; either
        change must re-run this writer proof before it ships.

        Steps 2-3 are QUIET: no diagnostic, no refusal, no `_observe_halt`
        call -- this branch runs BEFORE `_hunt_tick` reaches its own
        window/intent checks for the YES path, so the counters those checks
        own must stay byte-identical to a world where this method never ran
        (AC4).

        CONTAINED (silent-failure-hunter discipline, matching
        `_hunt_no_only`): `refuse_if_sibling_leg_traded` reads and decodes a
        durable record and can raise `TrialDayRecordCorrupt`; a fault here
        fails CLOSED (no cache write, no NO evaluation) rather than risk a
        NO take next to an unprovable YES outcome. Shares
        `_contain_no_only_hunt_error`'s counter/notice/log-once discipline
        with `_hunt_no_only` -- this is the same "quiet NO-only hunt"
        surface, reached through a second entry point.
        """
        cache_key = (station_day, iid)
        if cache_key in self._yes_fill_blocks_no:
            return
        try:
            assert self._latch is not None
            store = self._latch._store
            prefix = self._latch._key_prefix
            no_iid = str(sibling_instrument_id(InstrumentId.from_str(iid)))
            if refuse_if_sibling_leg_traded(
                store, prefix, station, climate_day_key, no_iid,
            ) is not None:
                self._yes_fill_blocks_no.add(cache_key)
                return

            now_ns = snapshot.ts_event
            offset = self._std_utc_offset_hours_by_station[station]
            hour_lst = _local_hour(now_ns, offset)
            if not (_WINDOW_START_HOUR_LST <= hour_lst < _WINDOW_END_HOUR_LST):
                return
            if self._latch.is_intent_open():
                # Silent-failure review (2026-09-25): this WAIT is silent on
                # `diagnostics`/`refusals` by design (AC4 above), but it is
                # still a genuine `open_intent_wait` -- routed through the
                # SAME F-4 observation `_hunt_tick`'s own check uses, so it
                # is not invisible to `last_open_intent_wait`/the log line.
                # Deduped by the SAME per-process state (minute bucket,
                # intent_id) either check already shares.
                self._maybe_observe_open_intent_wait(now_ns=now_ns)
                return
            if no_leg_executable(snapshot.bid, snapshot.bid_size, self._config):
                self._hunt_no_only(
                    snapshot,
                    facts,
                    station=station,
                    climate_day=climate_day,
                    climate_day_key=climate_day_key,
                    station_day=station_day,
                    now_ns=now_ns,
                    hour_lst=hour_lst,
                )
        except Exception as exc:  # noqa: BLE001 - must never affect _hunt_tick (fail closed)
            self._contain_no_only_hunt_error(
                exc,
                yes_instrument_id=snapshot.instrument_id,
                station=station,
                climate_day_key=climate_day_key,
            )

    def _hunt_tick(
        self,
        snapshot: _AskSnapshot,
        *,
        trigger: Trigger,
        quote_age_ns: int | None,
    ) -> None:
        # F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): checked FIRST, ahead of
        # every gate -- pre-decision WAIT diagnostics record BEFORE reaching
        # a Take/Refuse, so the hourly rollover must see EVERY tick, not
        # only the ones that reach a decision.
        self._maybe_roll_diagnostics(now_ns=snapshot.ts_event)
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
        # EDGE-1 (AM-4): a DIFFERENT failure class from `self._fee_halt`
        # above (which is set on a `fee_schedule_mismatch` decision refusal
        # and never clears) -- this is the fee-DRIFT-PROBE's own staleness
        # veto, entry-only. `self.clock.timestamp_ns()`, never
        # `snapshot.ts_event` (AM-1: market-data time can lag wall time
        # under feed backlog, which would understate elapsed time and
        # fail-open). An unhandled exception here aborts this tick before
        # submit -- fails closed, consistent with every other unwrapped
        # check in this method.
        if self._fee_verified_check is not None and not self._fee_verified_check(
            self.clock.timestamp_ns()
        ):
            self.diagnostics.record(_DIAG_FEE_UNVERIFIED)
            self._report_alerter(
                self.diagnostics_alerter,
                "continuous_rung_hold diagnostics report failed",
            )
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
            # F-1b: a bid-only frame (no ask) is deduped on the NO leg's own
            # inputs -- `size` is always `0` for an ask-less snapshot and
            # would collapse two DIFFERENT bids at the same `ts_event` into
            # one dedupe key.
            dedupe_key: (
                tuple[int, Decimal, int] | tuple[int, None, Decimal | None, Decimal | None]
            )
            if snapshot.ask is not None:
                dedupe_key = (snapshot.ts_event, snapshot.ask, snapshot.size)
            else:
                dedupe_key = (snapshot.ts_event, None, snapshot.bid, snapshot.bid_size)
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
            # F-1c (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md, Rev 3.1): a
            # consumed YES instrument-day no longer implies "never evaluate
            # NO" -- see `_hunt_no_only_after_yes_consumed`'s own table and
            # fail-closed argument.
            self._hunt_no_only_after_yes_consumed(
                snapshot,
                facts,
                station=station,
                climate_day=climate_day,
                climate_day_key=climate_day_key,
                station_day=station_day,
                iid=iid,
            )
            return
        # AM-4 (HF-4 rev2.1): hoisted once per tick, BEFORE the IN_FLIGHT
        # check below, so the stale-IN_FLIGHT release and the re-arm gate a
        # few lines down share ONE store read instead of two. Phase 0
        # (`order_submission_permit is None`) now pays this one extra read
        # on every tick too, since the release check runs unconditionally --
        # accepted cost (Decision 1, HF-4.rev2.md): Phase 0 already self-
        # clears IN_FLIGHT at the end of this method regardless.
        attempt_state = self._latch.attempt_state(station, climate_day_key, key_instrument_id=iid)
        # F-1c table: an unreleased IN_FLIGHT YES marker fails closed here --
        # the sibling exclusion (amendment sec4:114) cannot be proven safe
        # while this leg's fill outcome is unresolved, so NO is not
        # evaluated on this branch.
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
            # F-1c table: a YES re-arm wait fails closed for the same reason
            # as IN_FLIGHT above -- the prior YES attempt lacks venue
            # evidence of a non-fill, so the sibling exclusion cannot yet be
            # proven safe and NO is not evaluated on this branch.
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
            # F-4 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): observability ONLY
            # -- the WAIT outcome above is already decided; this can never
            # change it, add a refusal/diagnostic key, or affect the gate.
            self._maybe_observe_open_intent_wait(now_ns=snapshot.ts_event)
            return

        now_ns = snapshot.ts_event
        offset = self._std_utc_offset_hours_by_station[station]
        hour_lst = _local_hour(now_ns, offset)
        if not (_WINDOW_START_HOUR_LST <= hour_lst < _WINDOW_END_HOUR_LST):
            if snapshot.ask is None:
                # F-1b (R1): a bid-only frame outside the window returns
                # BEFORE the refusal/alerter/halt-observation below, so
                # `refusals` and the halt detector's baseline stay
                # byte-identical to a world where this frame never arrived.
                return
            self.refusals.record(_OUTSIDE_DECISION_WINDOW)
            self._report_alerter(
                self.refusal_alerter,
                "continuous_rung_hold refusal report failed",
            )
            self._observe_halt(trading_expected=False)
            return

        # WP-R1: the ONE per-tick halt observation, placed here because this
        # is the single point every in-window candidate passes through --
        # ahead of the decision rather than at each of the refusal sites
        # below, since the detector reads CUMULATIVE counters and only needs
        # to be called often enough to close its window.
        self._observe_halt(trading_expected=True)

        ask = snapshot.ask
        size = snapshot.size
        if ask is None:
            # F-1b (R1): a bid-only Depth10 frame -- no YES diagnostic is
            # recorded (today these frames record nothing at all, since
            # `on_order_book_depth` returned before `_hunt_tick` ever ran),
            # so the YES-side counters stay byte-identical. Only the NO
            # leg's own executability (never the YES ask, which does not
            # exist on this frame) gates the NO-only hunt.
            #
            # F-2 (coordinator carry-forward, STALL_FOLLOWUPS_F1_F4_2026-09-
            # 24.md): these two counts are DISTINCT from `diagnostics`/
            # `refusals` (AC4: no new keys there, no new alerter condition)
            # -- they exist ONLY in the hourly diagnostics-summary row, so
            # the halt detector's input is unaffected. Since F-1b landed,
            # both were invisible: an in-window bid-only frame recorded
            # nothing at all before this increment.
            self._bid_only_in_window_frames += 1
            if no_leg_executable(snapshot.bid, snapshot.bid_size, self._config):
                self._hunt_no_only(
                    snapshot,
                    facts,
                    station=station,
                    climate_day=climate_day,
                    climate_day_key=climate_day_key,
                    station_day=station_day,
                    now_ns=now_ns,
                    hour_lst=hour_lst,
                )
            else:
                # The NO leg (`1 - bid`) is ALSO outside the executable
                # band -- an in-window frame with neither leg executable,
                # silent and row-less exactly as F-1b AC2 pins, but now
                # counted here so it stops being invisible to the F-2
                # digest (never to `diagnostics`/`refusals`/the halt
                # detector).
                self._no_out_of_band_frames += 1
            return
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
            # F-1a (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md): the YES ask
            # being outside the executable band (or too thin) never implies
            # the NO leg (1 - bid) is -- PREREG v3 amendment §1:13/§2:32
            # registers the NO population on the NO leg's OWN executability,
            # never gated on the YES ask. This restores that population; the
            # counted diagnostic above and this `return` are unchanged, so
            # every existing YES-side count and tape row stays byte-identical.
            if no_leg_executable(snapshot.bid, snapshot.bid_size, self._config):
                self._hunt_no_only(
                    snapshot,
                    facts,
                    station=station,
                    climate_day=climate_day,
                    climate_day_key=climate_day_key,
                    station_day=station_day,
                    now_ns=now_ns,
                    hour_lst=hour_lst,
                )
            return
        assert ask is not None  # mypy narrowing for the YES path below

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

        # A1 (F-1a): extracted into `_eligible_setup` so the NO-only hunt
        # can share these exact three lookups -- same calls, same order, no
        # behaviour change on this (YES) path.
        setup = self._eligible_setup(
            snapshot.instrument_id, facts, running_max, accumulator, now_ns,
        )
        width_code, m_code = setup.width_code, setup.m_code
        fee_coefficient = setup.fee_coefficient
        # GAP fix 2026-09-15 (offer-tape postmortem observability): named
        # once so the offer-tape row below and the NO-side shadow evaluation
        # log the SAME staleness the decision was actually evaluated
        # against, rather than two independent (if numerically identical)
        # calls -- pure extraction, no behaviour change.
        staleness_ns = setup.staleness_ns
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
                existing_ids, pending_fills = self._station_day_existing_legs(station_day)
                yes_admission_refusal = station_day_admission(
                    store,
                    prefix,
                    station,
                    climate_day_key,
                    "yes",
                    decision.break_even,
                    existing_instrument_ids=existing_ids,
                    pending_fills=pending_fills,
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
        # RESTING_BID_HUNT Rev 2 §6 (shadow stage): computed AFTER `decision`
        # and `yes_admission_refusal` are both final, so the shadow decider
        # observes exactly the same sibling-fill/illegal-cell facts the YES
        # arm path itself just used -- and, being read-only over locals
        # already computed above, can never influence them (L-34/D3).
        shadow_yes_sibling_filled = (
            yes_admission_refusal is not None
            and yes_admission_refusal.reason == SIBLING_LEG_TRADED_REASON
        )
        shadow_yes_fee_schedule_mismatch = (
            isinstance(decision, Refuse) and decision.reason == "fee_schedule_mismatch"
        )
        shadow_yes_result = self._evaluate_shadow_rest(
            station=station,
            climate_day_key=climate_day_key,
            leg="YES",
            best_ask=ask,
            p_bound=offer_p_bound,
            staleness_ns=staleness_ns,
            cell_legal=not illegal,
            sibling_leg_filled=shadow_yes_sibling_filled,
            fee_schedule_mismatch=shadow_yes_fee_schedule_mismatch,
        )
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
                shadow_rest_state=shadow_yes_result.state,
                shadow_rest_price=shadow_yes_result.price,
                shadow_rest_margin=shadow_yes_result.margin,
                shadow_rest_reason=shadow_yes_result.reason,
                shadow_fill_event=shadow_yes_result.fill_event,
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
        # WP-R1: one FINALIZED take. Counted here, at the same point the
        # latch goes IN_FLIGHT -- never at `Take` construction, which the
        # arm-time admission gates above can still refuse.
        self.takes += 1
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
            # RESTING_BID_HUNT Rev 2 §6 (shadow stage): the NO leg's ask is
            # the caller's own `1 - bid` complement -- the SAME pure
            # `compute_p_star` the YES leg uses, fed the complement price,
            # never a leg-conditional branch inside the decider itself.
            no_best_ask = None if bid is None else _ONE - bid
            shadow_no_sibling_filled = admission_reason == SIBLING_LEG_TRADED_REASON
            shadow_no_cell_legal = not (
                isinstance(no_decision, Refuse) and no_decision.reason == "illegal_cell"
            )
            shadow_no_fee_schedule_mismatch = (
                isinstance(no_decision, Refuse) and no_decision.reason == "fee_schedule_mismatch"
            )
            shadow_no_result = self._evaluate_shadow_rest(
                station=station,
                climate_day_key=climate_day_key,
                leg="NO",
                best_ask=no_best_ask,
                p_bound=row_p_bound,
                staleness_ns=staleness_ns,
                cell_legal=shadow_no_cell_legal,
                sibling_leg_filled=shadow_no_sibling_filled,
                fee_schedule_mismatch=shadow_no_fee_schedule_mismatch,
            )
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
                    shadow_rest_state=shadow_no_result.state,
                    shadow_rest_price=shadow_no_result.price,
                    shadow_rest_margin=shadow_no_result.margin,
                    shadow_rest_reason=shadow_no_result.reason,
                    shadow_fill_event=shadow_no_result.fill_event,
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

        existing_ids, pending_fills = self._station_day_existing_legs(station_day)
        admission_refusal = station_day_admission(
            store,
            prefix,
            station,
            climate_day_key,
            "no",
            no_decision.break_even,
            existing_instrument_ids=existing_ids,
            pending_fills=pending_fills,
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
            # FU-2: mirrors the YES `take:` line's own `R=[...]`/staleness
            # fields (`:2298-2304`) -- rendered `None` when `running_max`/
            # `staleness_ns` are absent (the two direct-call-site unit tests
            # never supply them), never a `NoneType` crash on `.lower_f`.
            no_r_bounds = (
                "None" if running_max is None
                else f"[{running_max.lower_f},{running_max.upper_f}]"
            )
            no_obs_ts_ns = None if running_max is None else running_max.source_observed_at_ns
            no_staleness_s = None if staleness_ns is None else staleness_ns / _NS_PER_SECOND
            self._record_no_take_shadow(
                f"no_take_shadow: station={station} instrument={no_iid} "
                f"no_ask={no_decision.limit_price} p_miss_lower={no_decision.p_bound} "
                f"be={no_decision.break_even} bid_size={bid_size} "
                f"pending={1 if pending else 0} "
                f"R={no_r_bounds} obs_ts_ns={no_obs_ts_ns} staleness_s={no_staleness_s}"
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
        # F-2 (A4): mirrors `self.takes += 1` at the YES tail (:2069) --
        # counted here, at the SAME point the latch goes IN_FLIGHT for the
        # NO leg, unconditionally (even under Phase 0/gate-closed, exactly
        # like `takes`). `HaltDetector.observe(takes=self.takes)` stays
        # UNCHANGED (no cited rule makes it NO-aware) -- see the dedicated
        # test.
        self.no_takes += 1
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

        INC-E3 (plan §3, PREREG v4 §5b): a denied EXIT order (identified by
        its own tags, never by reason string -- an exit never uses the
        entry-only WAIT sentinel) is an AMBIGUOUS/rejected exit -- the
        family-wide kill fires instead of any entry-shaped IN_FLIGHT logic.
        """
        super().on_order_denied(event)
        order = self.cache.order(event.client_order_id)
        if order is not None and exit_wiring.order_is_exit(order):
            self._halt_family_for_ambiguous_exit(
                position_id=exit_wiring.exit_position_id_from_tags(order),
                reason=f"order_denied:{event.reason}",
                ts_ns=event.ts_event,
            )
            return
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

    def on_order_rejected(self, event: OrderRejected) -> None:
        """INC-E3 (plan §3, PREREG v4 §5b): a venue-rejected EXIT order sets
        the family-wide AMBIGUOUS/rejected-exit kill. Entry orders never
        reach here today (Phase 0/1's own guards refuse before submission,
        never after venue acceptance) -- this override exists FOR the exit
        path, but is written generically (tag-gated) rather than asserting
        the order must be an exit, so a future entry-side rejection is
        merely ignored rather than mis-attributed.
        """
        super().on_order_rejected(event)
        order = self.cache.order(event.client_order_id)
        if order is not None and exit_wiring.order_is_exit(order):
            self._halt_family_for_ambiguous_exit(
                position_id=exit_wiring.exit_position_id_from_tags(order),
                reason=f"order_rejected:{event.reason}",
                ts_ns=event.ts_event,
            )

    def _halt_family_for_ambiguous_exit(
        self, *, position_id: str, reason: str, ts_ns: int,
    ) -> None:
        """Thin delegator (extraction: `exit_wiring.py`, brief's "keep
        continuous_strategy.py growth small") -- kept as a bound method
        because `on_order_denied`/`on_order_rejected` are Strategy-hook
        overrides that must stay on this class.
        """
        exit_wiring.halt_family_for_ambiguous_exit(
            self, position_id=position_id, reason=reason, ts_ns=ts_ns,
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

    def _maybe_observe_open_intent_wait(self, *, now_ns: int) -> None:
        """F-4 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md, A7): reads
        ``current_open_submit_intent()`` at most once per event-time MINUTE
        bucket -- contained under :meth:`_run_observability` exactly like
        every other observability call in this class (``_observe_halt``,
        ``_report_alerter``), so a store-read failure can never affect the
        WAIT outcome ``is_intent_open()`` already decided, nor raise into
        ``_hunt_tick``.
        """
        minute_bucket = now_ns // _NS_PER_MINUTE
        if minute_bucket == self._open_intent_wait_last_minute_bucket:
            return
        self._open_intent_wait_last_minute_bucket = minute_bucket
        self._run_observability(
            "continuous_rung_hold open-intent-wait observation failed",
            lambda: self._log_open_intent_wait_if_due(now_ns=now_ns),
        )

    def _log_open_intent_wait_if_due(self, *, now_ns: int) -> None:
        """F-4: logs once per NEW ``intent_id``, then at most once per hour
        while the SAME id persists (``_open_intent_wait_log_state``). Never
        reads or logs ``SubmitIntent.fingerprint`` (``repr=False`` on that
        dataclass) -- only ``intent_id`` and the age derived from
        ``created_ns``.
        """
        assert self._latch is not None
        intent = self._latch.current_open_submit_intent()
        if intent is None:
            # The singleton cleared between `is_intent_open()`'s read and
            # this one (a genuine, if narrow, race) -- nothing to log.
            return
        state = self._open_intent_wait_log_state
        if (
            state is not None
            and state[0] == intent.intent_id
            and now_ns - state[1] < _NS_PER_HOUR
        ):
            return
        self._open_intent_wait_log_state = (intent.intent_id, now_ns)
        station = ",".join(self._config.stations)
        age_s = (now_ns - intent.created_ns) / _NS_PER_SECOND
        self._record_open_intent_wait(
            f"open_intent_wait: station={station} intent_id={intent.intent_id} "
            f"age_s={age_s}"
        )

    def _record_open_intent_wait(self, summary: str) -> None:
        """Mirrors ``_record_rearm_decision`` -- stores the ONE summary line
        on ``self.last_open_intent_wait`` (asserted by presence, L-27) and
        emits it via the overridable seam below. Stable grep token
        ``open_intent_wait:``.
        """
        self.last_open_intent_wait = summary
        self._emit_open_intent_wait(summary)

    def _emit_open_intent_wait(self, summary: str) -> None:
        """Mirrors ``_emit_rearm_decision``: production body is exactly one
        ``self.log.info`` call -- overridable so a test can record calls
        instead of asserting on captured log output (L-27).
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
        if event.order_side is OrderSide.SELL:
            # INC-E3 (plan §3): Breezy never submits any OTHER SELL --
            # every entry is a plain BUY (`_maybe_submit`) -- so a SELL
            # fill is unambiguously an EXIT fill, routed to its own,
            # entirely separate join/provenance path (never the entry
            # `consume_if_absent`/duplicate-fill machinery below).
            self._on_exit_order_filled(event)
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

    def _on_exit_order_filled(self, event: OrderFilled) -> None:
        """Thin delegator (extraction: `exit_wiring.py`, brief's "keep
        continuous_strategy.py growth small") -- kept as a bound method
        because `on_order_filled` (a Strategy-hook override that must stay
        on this class) calls it by that name.
        """
        exit_wiring.on_exit_order_filled(self, event)

    def submit_exit(self, proposal: ExitProposal) -> None:
        """Injected into `PositionMonitor` as its `submit_exit` callable
        (INC-E3, plan §3). Thin delegator (extraction: `exit_wiring.py`,
        brief's "keep continuous_strategy.py growth small") -- kept as a
        bound method so `PositionMonitor` can be handed a plain
        `Callable[[ExitProposal], None]` (`strategy.submit_exit`) without
        the composition root reaching into `exit_wiring` itself.
        """
        exit_wiring.submit_exit(self, proposal)

    def check_ambiguous_exit_intent(
        self, *, client_order_id: str, position_id: str, now_ns: int,
    ) -> None:
        """Injected into `PositionMonitor` as its `check_ambiguous_exit`
        callable (review finding B). Thin delegator (extraction:
        `exit_wiring.py`, brief's "keep continuous_strategy.py growth
        small") -- kept as a bound method so `PositionMonitor` can be handed
        a plain callable without the composition root reaching into
        `exit_wiring` itself.
        """
        exit_wiring.check_exit_intent_for_ambiguous_send(
            self, client_order_id=client_order_id, position_id=position_id, now_ns=now_ns,
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

        `None` unless a record for this EXACT `venue_order_id` exists and
        `_per_contract_reconciled_fee` (the module-level helper this method
        shares with `_consume_trial_from_fill_record`) derives a fee from
        it -- an absent record leaves `q` UNKNOWN, and `station_day_admission`
        must keep refusing rather than guess (never relaxed by this helper).
        """
        assert self._latch is not None
        for candidate in self._latch.iter_fill_records((str(instrument_id),)):
            if candidate.venue_order_id != venue_order_id:
                continue
            return _per_contract_reconciled_fee(candidate)
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

    def _observe_halt(self, *, trading_expected: bool) -> None:
        """WP-R1: hand this tick's cumulative counters to the halt detector.

        Observability ONLY, and guarded by `_run_observability` exactly like
        every alerter call above: this can never raise into the decision
        path and can never let an order through -- the detector submits
        nothing and holds no reference to any gate it reports on.

        `trading_expected` is this station's LST decision window: while it is
        `False`, zero candidates is simply correct and no window can close.

        `self.diagnostics.counts` supplies the detector's OBSERVED-TICK
        gate (MDW 18:58Z, 2026-09-20): the WAIT-state keys already recorded
        at the pre-decision returns below are what tell an illiquid stretch
        (ticks arrived, none reached a decision) apart from a starved feed
        (nothing arrived at all). Read only -- nothing here changes what the
        strategy counts or when it counts it.
        """
        detector = self.halt_detector
        if detector is None:
            return
        self._run_observability(
            "continuous_rung_hold halt detector failed",
            lambda: detector.observe(
                refusal_counts=self.refusals.counts,
                takes=self.takes,
                now_ns=self.clock.timestamp_ns(),
                trading_expected=trading_expected,
                diagnostic_counts=self.diagnostics.counts,
            ),
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
