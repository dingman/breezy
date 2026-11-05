"""Shadow-only intra-day position monitor orchestrator (INC-5).

L-1: GAP -- Nautilus wires no per-position thesis re-evaluation into a
live ``Strategy``'s handler loop. This is the authored glue
(``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` §2, Rev 2.1
addendum A1/A3), composing ``monitor_evidence.py``/``monitor_decision.py``/
``monitor_store.py`` into ``PositionMonitor``, which
``ContinuousRungHoldStrategy`` forwards its handler calls to.

M7 D3 pin (never violate): holds NO reference to ``TrialDayLatch``'s
mutating surface (only the read-only ``record`` accessor, as a plain
callable); NEVER calls ``_hunt_tick``/``_maybe_submit``, reads, or pops
``_decision_ask_by_station_day``. Accumulator access is limited to
``value_at``/``staleness_ns`` -- never ``push``/``coverage``/
``earliest_observed_ns``.

D8: every public method is wrapped so an internal failure is caught,
counted (``monitor_errors``), and reported -- never raised into the
strategy's own handler, never able to affect hunting/latch state.

INC-E3 (``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`` §3, PREREG v4
§3b/§5b): this object stays SHADOW-ONLY by DEFAULT -- ``exit_decider`` and
``submit_exit`` both default to ``None``, in which case every evaluation
behaves byte-identically to before this increment (D3's "never constructs,
submits, modifies, or cancels an order" holds exactly as before). A caller
that installs BOTH a decider and a ``submit_exit`` callable opts THIS ONE
instance into evaluating (never constructing or submitting itself: that
stays the injected ``submit_exit``'s job, owned by the strategy layer)
whether the current evaluation authorises a 1-contract closing order --
still never touching ``TrialDayLatch``'s mutating surface directly, and
still never able to affect entry-side hunting/latch state (the exit path
and the entry path share no state through this object).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from nautilus_trader.model.identifiers import InstrumentId

from breezy.domain.season import season_for
from breezy.strategy.current_rung_hold.exit_decider import ExitProposal, ExitRefusal
from breezy.strategy.current_rung_hold.monitor_decision import (
    MonitorDecision,
    MonitorHistory,
    ThesisState,
    evaluate_monitor,
    should_emit,
)
from breezy.strategy.current_rung_hold.monitor_evidence import (
    Leg,
    MonitorEvidence,
    build_monitor_evidence,
    p_hold_at,
)
from breezy.strategy.current_rung_hold.monitor_records import (
    PositionMarkRecord,
    PositionMonitorSummary,
)
from breezy.strategy.current_rung_hold.monitor_store import MarkBuffer, write_monitor_summaries
from breezy.strategy.current_rung_hold.offer_tape import OfferTapeRecord
from breezy.strategy.current_rung_hold.tick_eval import width_and_m
from breezy.strategy.current_rung_hold.trial_day_latch import trial_id_for

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.data import OrderBookDepth10
    from nautilus_trader.model.position import Position

    from breezy.domain.weather_bucket_facts import WeatherBucketFacts
    from breezy.persistence.family_manifest import FamilyManifest
    from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord
    from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

#: The exit decider's full keyword signature (``exit_decider.decide_exit``)
#: -- typed loosely here (``...``) rather than spelled out, mirroring this
#: module's own existing callables (``latch_record: Callable[..., ...]``):
#: the caller passes ``decide_exit`` itself or a test double with the same
#: keyword surface.
ExitDecider = Callable[..., "ExitProposal | ExitRefusal"]

__all__ = ["PositionMonitor"]

logger = logging.getLogger(__name__)


def _season_for_climate_day(climate_day: str) -> str:
    return season_for(date.fromisoformat(climate_day))


@dataclass(slots=True)
class _MonitoredPosition:
    """Mutable, INTERNAL-ONLY per-position state. Never exported: every
    externally-visible fact is a fresh :class:`MonitorEvidence`/
    :class:`PositionMonitorSummary`, built from this on demand.
    """

    instrument_id: str
    station: str
    climate_day: str
    leg: Leg
    entry_context: str
    trial_id: str
    fill_px: Decimal
    p_hold_at_entry: Decimal | None
    opened_at_ns: int
    #: INC-E3: the Nautilus ``PositionId`` string, needed by the exit
    #: decider (``position_id``) and the strategy's own ``submit_exit``.
    position_id: str = ""
    history: MonitorHistory = field(default_factory=lambda: MonitorHistory.EMPTY)
    last_depth: OrderBookDepth10 | None = None
    last_book_ts_ns: int | None = None
    last_held_qty: int = 0
    mae: Decimal = Decimal(0)
    mfe: Decimal = Decimal(0)
    total_frames: int = 0
    mark_missing_frames: int = 0
    first_signal_ts_ns: int | None = None
    first_signal_hour_lst: int | None = None
    first_signal_state: str | None = None
    verdict_at_signal: str | None = None
    recoverable_value_at_signal: Decimal | None = None
    monitor_seq: int = 0
    #: INC-E3: the MOST RECENT exit decision for this position, tracked so
    #: (a) the rate limit (``exit_decider._required_span_ns``) can be
    #: enforced across evaluations and (b) the position-day summary can
    #: report the latest decision even when it was refused.
    last_exit_decided_at_ns: int | None = None
    last_exit_rule: str | None = None
    last_exit_decision: str | None = None
    last_exit_reason_code: str | None = None
    last_exit_limit_price: Decimal | None = None
    last_exit_expected_settlement_value: Decimal | None = None
    #: Review finding B: the client_order_id of the MOST RECENT fired
    #: exit for this position, so the NEXT evaluation can check (via
    #: ``check_ambiguous_exit``) whether that prior exit's own durable
    #: intent is still stuck OPEN past the AMBIGUOUS-send deadline.
    last_exit_client_order_id: str | None = None


def _exit_offer_tape_record(
    monitored: _MonitoredPosition,
    evidence: MonitorEvidence,
    outcome: ExitProposal | ExitRefusal,
    now_ns: int,
) -> OfferTapeRecord:
    """One offer-tape row per exit decision (INC-E3, plan §3 acceptance
    item 8: "every exit decision -- fired or refused -- is persisted").

    Reuses ``OfferTapeRecord`` (never a second row type) with ``trigger=
    "exit"``/``source="position_monitor"`` as the discriminator from an
    entry-hunt row: every entry-only field this row has no value for
    (``size``, ``quote_age_ns``, ``minutes_since_window_open``,
    ``prior_eligible_snaps``, ``illegal_cell``) takes its own type's
    zero/empty default rather than a fabricated number.
    """
    fired = isinstance(outcome, ExitProposal)
    if isinstance(outcome, ExitProposal):
        rule_value: str | None = outcome.authorization.rule.value
        limit_price = outcome.authorization.limit_price
        expected_settlement_value = outcome.authorization.expected_settlement_value
        reason_code = "fired"
    else:
        rule_value = outcome.rule.value if outcome.rule is not None else None
        limit_price = None
        expected_settlement_value = None
        reason_code = outcome.reason
    return OfferTapeRecord(
        station=monitored.station,
        climate_day=monitored.climate_day,
        instrument_id=evidence.instrument_id,
        ask=None,
        size=0,
        reason=("exit_fired" if fired else f"exit_refused:{reason_code}"),
        ts_event=now_ns,
        hour_lst=evidence.hour_lst,
        width_code=evidence.cell_key[3],
        m_code=evidence.cell_key[4],
        trigger="exit",
        quote_age_ns=None,
        minutes_since_window_open=0,
        prior_eligible_snaps=0,
        illegal_cell=False,
        source="position_monitor",
        side=monitored.leg,
        decision=("exit_fired" if fired else "exit_refused"),
        exit_rule=rule_value,
        exit_decision=("fired" if fired else "refused"),
        exit_reason_code=reason_code,
        exit_limit_price=limit_price,
        expected_settlement_value=expected_settlement_value,
    )


class PositionMonitor:
    """Orchestrates the shadow monitor for every position a strategy
    instance holds. Constructor-injected callables (never a direct
    ``Strategy``/``Cache``/``TrialDayLatch`` reference) so tests exercise
    this in isolation with plain stubs (module docstring's D3 pin).
    """

    def __init__(
        self,
        *,
        clock_ns: Callable[[], int],
        positions_open: Callable[[str], Sequence[Position]],
        accumulators: Mapping[str, RunningExtremeAccumulator],
        latch_record: Callable[..., TrialDayRecord | None],
        rung_geometry: Callable[[str], WeatherBucketFacts | None],
        fee_coefficient_for: Callable[[str], Decimal],
        leg_for: Callable[[str], Leg],
        station_for: Callable[[str], str],
        climate_day_for: Callable[[str], str],
        hour_lst_for: Callable[[str, int], int],
        stale_observation_bound_ns: int,
        trial_id_prefix: str,
        buffer: MarkBuffer,
        catalog_root: Path,
        summaries_dir: Path,
        report: Callable[[str, Mapping[str, object]], None],
        exit_decider: ExitDecider | None = None,
        exit_manifest: FamilyManifest | None = None,
        exit_family_id: str | None = None,
        exit_client_order_id_factory: Callable[[], str] | None = None,
        submit_exit: Callable[[ExitProposal], None] | None = None,
        record_exit_offer: Callable[[OfferTapeRecord], None] | None = None,
        check_ambiguous_exit: Callable[..., None] | None = None,
        sibling_for: Callable[[str], str | None] | None = None,
    ) -> None:
        self._clock_ns = clock_ns
        self._positions_open = positions_open
        self._accumulators = accumulators
        self._latch_record = latch_record
        self._rung_geometry = rung_geometry
        self._fee_coefficient_for = fee_coefficient_for
        self._leg_for = leg_for
        self._station_for = station_for
        self._climate_day_for = climate_day_for
        self._hour_lst_for = hour_lst_for
        self._stale_observation_bound_ns = stale_observation_bound_ns
        self._trial_id_prefix = trial_id_prefix
        self._buffer = buffer
        self._catalog_root = catalog_root
        self._summaries_dir = summaries_dir
        self._report = report
        #: INC-E3 (module docstring): every one of these five defaults to
        #: `None` -- SHADOW-ONLY, byte-identical to before this increment,
        #: unless a caller installs both `exit_decider` and `submit_exit`
        #: (module docstring).
        self._exit_decider = exit_decider
        self._exit_manifest = exit_manifest
        self._exit_family_id = exit_family_id
        self._exit_client_order_id_factory = exit_client_order_id_factory
        self._submit_exit = submit_exit
        self._record_exit_offer = record_exit_offer
        #: Review finding B: the SAME shadow-only default posture --
        #: `None` unless a caller opts in alongside the five above.
        self._check_ambiguous_exit = check_ambiguous_exit
        #: FU-1d: routes a YES `OrderBookDepth10` frame to its registered
        #: sibling NO position too (`RULING_FU-1b_no_leg_marks_2026-09-26.md`).
        #: `None` (the default) is byte-identical shadow behaviour -- no
        #: caller of this constructor before FU-1d passes anything here, so
        #: `on_depth`'s existing YES-only behaviour is completely unchanged.
        self._sibling_for = sibling_for

        self._positions: dict[str, _MonitoredPosition] = {}
        #: A3: negative `TrialDayRecord` lookups cached per (instrument_id,
        #: climate_day) for the process lifetime -- never re-hits the store.
        self._negative_record_cache: set[tuple[str, str]] = set()
        self._monitor_errors = 0
        self._evaluations = 0
        self._emitted = 0
        #: INC-E3: exit orders fired this process, per (station, climate_day)
        #: -- the per-station-day cap `exit_decider.decide_exit` enforces.
        #: FU-1d S1 (deliberate, not an oversight): keyed by (station,
        #: climate_day) ONLY -- SHARED across a station-day's YES and NO
        #: legs. PREREG v4 section3b:48 ("a per-station-day cap bounds a
        #: flapping book") and L-40 both name the station-day, never a leg,
        #: as the trial unit; a fired YES exit for this station-day is
        #: therefore visible to the very next NO-leg evaluation of the SAME
        #: station-day. Keying by leg instead would double the possible
        #: exits per station-day -- a Class-C amendment of
        #: `MAX_STATION_DAY_EXIT_ORDERS` (PREREG v4 :112), never a bare
        #: refactor of this dict.
        self._station_day_exit_counts: dict[tuple[str, str], int] = {}

    @property
    def counters(self) -> Mapping[str, int]:
        return {
            "monitor_errors": self._monitor_errors,
            "monitor_marks_dropped": self._buffer.dropped,
            "flush_errors": self._buffer.flush_errors,
            "sidecar_errors": self._buffer.sidecar_errors,
            "evaluations": self._evaluations,
            "emitted": self._emitted,
        }

    # -- public handlers, every one guarded (D8) -------------------------

    def on_observation(self, station: str, now_ns: int) -> None:
        self._guarded("on_observation", lambda: self._on_observation(station, now_ns))

    def on_depth(self, depth: OrderBookDepth10, now_ns: int) -> None:
        self._guarded("on_depth", lambda: self._on_depth(depth, now_ns))
        self._guarded("on_depth_sibling", lambda: self._on_sibling_depth(depth, now_ns))

    def on_position_opened(self, position: Position, now_ns: int) -> None:
        self._guarded(
            "on_position_opened",
            lambda: self._on_position_opened(position, now_ns),
        )

    def on_stop(self, now_ns: int) -> None:
        self._guarded("on_stop", lambda: self._on_stop(now_ns))

    def _guarded(self, site: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - a monitor must never raise into the strategy
            self._monitor_errors += 1
            try:
                self._report(
                    "monitor_error",
                    {"site": site, "exc_type": type(exc).__name__},
                )
            except Exception:  # the report sink itself must never propagate
                logger.exception("PositionMonitor: report() failed for site=%s", site)

    # -- internal, unguarded bodies ---------------------------------------

    def _on_observation(self, station: str, now_ns: int) -> None:
        for iid, monitored in list(self._positions.items()):
            if monitored.station != station:
                continue
            self._evaluate(monitored, iid, now_ns, depth=None)

    def _on_depth(self, depth: OrderBookDepth10, now_ns: int) -> None:
        iid = str(depth.instrument_id)
        monitored = self._ensure_registered(iid, now_ns)
        if monitored is None:
            return
        self._evaluate(monitored, iid, now_ns, depth=depth)

    def _on_sibling_depth(self, depth: OrderBookDepth10, now_ns: int) -> None:
        """FU-1d (RULING_FU-1b_no_leg_marks_2026-09-26.md): re-route THIS
        SAME YES depth frame to its registered NO-leg sibling, evaluated
        independently of `_on_depth` above -- its own `_guarded` site
        (`on_depth_sibling`) means an error here can never suppress or alter
        the YES evaluation, and vice versa.

        A no-op whenever `sibling_for` is `None` (the default: byte-
        identical shadow behaviour for every caller that predates FU-1d).
        `sibling_for` itself returns `None` for a NO-leg frame (defence in
        depth against a YES<->NO ping-pong that should never happen -- the
        venue has one book per market slug, subscribed only under the YES
        id) and for a malformed/foreign-venue id, in which case this is
        also a no-op.
        """
        if self._sibling_for is None:
            return
        iid = str(depth.instrument_id)
        sibling_iid = self._sibling_for(iid)
        if sibling_iid is None:
            return
        monitored = self._ensure_registered(sibling_iid, now_ns)
        if monitored is None:
            return
        self._evaluate(monitored, sibling_iid, now_ns, depth=depth)

    def _on_position_opened(self, position: Position, now_ns: int) -> None:
        iid = str(position.instrument_id)
        if iid in self._positions:
            return
        self._register(iid, position, now_ns, entry_context="live")

    def _on_stop(self, now_ns: int) -> None:
        summaries: list[PositionMonitorSummary] = []
        for monitored in self._positions.values():
            self._buffer.flush(self._catalog_root, monitored.climate_day)
            monitored.monitor_seq += 1
            summaries.append(self._summary_for(monitored, now_ns))
        if not summaries:
            return
        try:
            write_monitor_summaries(self._summaries_dir, summaries, now_ns=now_ns)
        except Exception as exc:  # noqa: BLE001 - writer failure is counted, never raised
            self._monitor_errors += 1
            self._report(
                "monitor_error",
                {"site": "write_monitor_summaries", "exc_type": type(exc).__name__},
            )

    # -- registration (B3) -------------------------------------------------

    def _ensure_registered(self, iid: str, now_ns: int) -> _MonitoredPosition | None:
        existing = self._positions.get(iid)
        if existing is not None:
            return existing
        candidates = self._positions_open(iid)
        if not candidates:
            return None
        return self._register(iid, candidates[0], now_ns, entry_context="reconciled")

    def _register(
        self,
        iid: str,
        position: Position,
        now_ns: int,
        *,
        entry_context: str,
    ) -> _MonitoredPosition:
        station = self._station_for(iid)
        climate_day = self._climate_day_for(iid)
        leg = self._leg_for(iid)
        trial_id = trial_id_for(self._trial_id_prefix, station, climate_day, iid)
        fill_px = Decimal(str(position.avg_px_open))

        cache_key = (iid, climate_day)
        record: TrialDayRecord | None = None
        if cache_key not in self._negative_record_cache:
            record = self._latch_record(station, climate_day, key_instrument_id=iid)
            if record is None:
                self._negative_record_cache.add(cache_key)

        resolved_entry_context = entry_context
        p_hold_at_entry: Decimal | None = None
        if record is None:
            if entry_context == "reconciled":
                resolved_entry_context = "reconciled_no_record"
        else:
            p_hold_at_entry = self._recover_p_hold_at_entry(iid, station, record)

        monitored = _MonitoredPosition(
            instrument_id=iid,
            station=station,
            climate_day=climate_day,
            leg=leg,
            entry_context=resolved_entry_context,
            trial_id=trial_id,
            fill_px=fill_px,
            p_hold_at_entry=p_hold_at_entry,
            opened_at_ns=now_ns,
            position_id=str(position.id),
        )
        self._positions[iid] = monitored
        return monitored

    def _recover_p_hold_at_entry(
        self,
        iid: str,
        station: str,
        record: TrialDayRecord,
    ) -> Decimal | None:
        """Best-effort re-derivation of the estimand entry evaluated.

        Recoverable ONLY when the SAME in-memory accumulator still holds a
        row at-or-before ``record.latched_at_ns`` -- true "live" the same
        process/day, ``None`` for most reconciled-after-restart positions
        (a fresh accumulator holds no pre-restart rows). ``None`` is not a
        failure: ``evaluate_monitor`` treats it as membership-only logic.
        """
        facts = self._rung_geometry(iid)
        accumulator = self._accumulators.get(station)
        if facts is None or accumulator is None:
            return None
        running_max = accumulator.value_at(record.latched_at_ns)
        if running_max is None:
            return None
        width_code, m_code = width_and_m(facts, running_max)
        entry_hour_lst = self._hour_lst_for(station, record.latched_at_ns)
        return p_hold_at(
            station=station,
            season=_season_for_climate_day(self._climate_day_for(iid)),
            hour_lst=entry_hour_lst,
            width_code=width_code,
            m_code=m_code,
            leg=self._leg_for(iid),
        )

    # -- evaluation ----------------------------------------------------

    def _evaluate(
        self,
        monitored: _MonitoredPosition,
        iid: str,
        now_ns: int,
        *,
        depth: OrderBookDepth10 | None,
    ) -> None:
        candidates = self._positions_open(iid)
        held_qty = sum(int(p.quantity) for p in candidates)
        monitored.last_held_qty = held_qty
        if held_qty <= 0:
            return  # closed/flat: no on_position_closed exists (CUT); never evaluate flat

        if depth is not None:
            monitored.last_depth = depth
            monitored.last_book_ts_ns = now_ns

        facts = self._rung_geometry(iid)
        accumulator = self._accumulators.get(monitored.station)
        running_max = None if accumulator is None else accumulator.value_at(now_ns)
        if facts is None or running_max is None:
            return  # nothing to classify against yet; read-only (L-34), defers to next eval

        staleness_ns = accumulator.staleness_ns(now_ns) if accumulator is not None else None
        book_staleness_ns = (
            None if monitored.last_book_ts_ns is None else now_ns - monitored.last_book_ts_ns
        )
        width_code, m_code = width_and_m(facts, running_max)
        hour_lst = self._hour_lst_for(monitored.station, now_ns)
        fee_coefficient = self._fee_coefficient_for(iid)

        evidence = build_monitor_evidence(
            ts_ns=now_ns,
            instrument_id=iid,
            station=monitored.station,
            climate_day=monitored.climate_day,
            season=_season_for_climate_day(monitored.climate_day),
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
            leg=monitored.leg,
            entry_context=monitored.entry_context,
            fill_px=monitored.fill_px,
            held_qty=held_qty,
            running_max_lower=running_max.lower_f,
            running_max_upper=running_max.upper_f,
            staleness_ns=staleness_ns,
            book_staleness_ns=book_staleness_ns,
            rung_low=facts.lower_f,
            rung_high=facts.upper_f,
            depth=monitored.last_depth,
            fee_coefficient=fee_coefficient,
            p_hold_at_entry=monitored.p_hold_at_entry,
            observed_at_ns=running_max.source_observed_at_ns,
        )

        pre_history = monitored.history
        decision, new_history = evaluate_monitor(
            evidence,
            pre_history,
            stale_observation_bound_ns=self._stale_observation_bound_ns,
        )
        monitored.history = new_history
        self._evaluations += 1
        monitored.total_frames += 1
        if evidence.mark_source == "missing":
            monitored.mark_missing_frames += 1
        if evidence.unrealized_pnl is not None:
            monitored.mae = min(monitored.mae, evidence.unrealized_pnl)
            monitored.mfe = max(monitored.mfe, evidence.unrealized_pnl)
        if monitored.first_signal_ts_ns is None and decision.state is not ThesisState.ALIVE:
            monitored.first_signal_ts_ns = now_ns
            monitored.first_signal_hour_lst = hour_lst
            monitored.first_signal_state = decision.state.value
            monitored.verdict_at_signal = decision.verdict.value
            monitored.recoverable_value_at_signal = evidence.recoverable_value

        if should_emit(decision, pre_history, now_ns):
            self._emit(monitored, iid, evidence, decision, now_ns)

        self._maybe_decide_exit(monitored, evidence, decision, now_ns)

    def _maybe_decide_exit(
        self,
        monitored: _MonitoredPosition,
        evidence: MonitorEvidence,
        decision: MonitorDecision,
        now_ns: int,
    ) -> None:
        """INC-E3 (module docstring): a no-op unless BOTH ``exit_decider``
        and the family/factory context were installed. Neither rule can
        ever fire outside ``THREATENED``/``DEAD_BY_OBSERVATION`` (module
        docstring's decider does that gating itself), so this method skips
        the call entirely for every other state -- never floods the offer
        tape/summary with a decision for an ``ALIVE``/``HOLD`` position.
        """
        if self._exit_decider is None:
            return
        # Review finding B: checked on EVERY evaluation once a prior exit
        # has fired for this position -- never gated on THIS tick's state --
        # so a stuck AMBIGUOUS send is caught even if the position's thesis
        # has since drifted back toward ALIVE/HOLD.
        if self._check_ambiguous_exit is not None and monitored.last_exit_client_order_id:
            self._check_ambiguous_exit(
                client_order_id=monitored.last_exit_client_order_id,
                position_id=monitored.position_id,
                now_ns=now_ns,
            )
        if decision.state not in (ThesisState.THREATENED, ThesisState.DEAD_BY_OBSERVATION):
            return
        assert self._exit_manifest is not None
        assert self._exit_family_id is not None
        assert self._exit_client_order_id_factory is not None

        station_day_key = (monitored.station, monitored.climate_day)
        outcome = self._exit_decider(
            decision,
            evidence,
            manifest=self._exit_manifest,
            family_id=self._exit_family_id,
            position_id=monitored.position_id,
            client_order_id_factory=self._exit_client_order_id_factory,
            last_exit_decided_at_ns_for_position=monitored.last_exit_decided_at_ns,
            station_day_exit_count=self._station_day_exit_counts.get(station_day_key, 0),
            fee_coefficient=self._fee_coefficient_for(evidence.instrument_id),
            now_ns=now_ns,
        )
        fired = isinstance(outcome, ExitProposal)
        monitored.last_exit_decision = "fired" if fired else "refused"
        if isinstance(outcome, ExitProposal):
            monitored.last_exit_rule = outcome.authorization.rule.value
            monitored.last_exit_reason_code = "fired"
            monitored.last_exit_limit_price = outcome.authorization.limit_price
            monitored.last_exit_expected_settlement_value = (
                outcome.authorization.expected_settlement_value
            )
        else:
            monitored.last_exit_rule = outcome.rule.value if outcome.rule is not None else None
            monitored.last_exit_reason_code = outcome.reason
            monitored.last_exit_limit_price = None
            monitored.last_exit_expected_settlement_value = None

        # Persisted BEFORE any submit (hard invariant, plan §3 INC-E3):
        # every exit decision -- fired or refused -- reaches the offer tape
        # first.
        if self._record_exit_offer is not None:
            self._record_exit_offer(_exit_offer_tape_record(monitored, evidence, outcome, now_ns))

        if isinstance(outcome, ExitProposal):
            monitored.last_exit_decided_at_ns = now_ns
            monitored.last_exit_client_order_id = outcome.authorization.client_order_id
            self._station_day_exit_counts[station_day_key] = (
                self._station_day_exit_counts.get(station_day_key, 0) + 1
            )
            if self._submit_exit is not None:
                self._submit_exit(outcome)

    def _emit(
        self,
        monitored: _MonitoredPosition,
        iid: str,
        evidence: MonitorEvidence,
        decision: MonitorDecision,
        now_ns: int,
    ) -> None:
        record = PositionMarkRecord(
            instrument_id=InstrumentId.from_str(iid),
            station=monitored.station,
            climate_day=monitored.climate_day,
            leg=monitored.leg,
            entry_context=monitored.entry_context,
            thesis_state=decision.state.value,
            verdict=decision.verdict.value,
            mark_vwap=evidence.mark_vwap,
            mark_source=evidence.mark_source,
            unrealized_pnl=evidence.unrealized_pnl,
            recoverable_value=evidence.recoverable_value,
            running_max_lower=Decimal(evidence.running_max_lower),
            running_max_upper=Decimal(evidence.running_max_upper),
            staleness_ns=evidence.staleness_ns if evidence.staleness_ns is not None else 0,
            book_staleness_ns=(
                evidence.book_staleness_ns if evidence.book_staleness_ns is not None else 0
            ),
            held_qty=Decimal(evidence.held_qty),
            reason_codes=decision.reason_codes,
            ts_event=now_ns,
            ts_init=now_ns,
        )
        self._buffer.append(record)
        monitored.history = dataclasses.replace(monitored.history, last_emitted_ts_ns=now_ns)
        self._emitted += 1
        if self._buffer.should_flush():
            self._buffer.flush(self._catalog_root, monitored.climate_day)

    def _summary_for(self, monitored: _MonitoredPosition, now_ns: int) -> PositionMonitorSummary:
        return PositionMonitorSummary(
            trial_id=monitored.trial_id,
            instrument_id=monitored.instrument_id,
            station=monitored.station,
            climate_day=monitored.climate_day,
            leg=monitored.leg,
            entry_context=monitored.entry_context,
            monitor_seq=monitored.monitor_seq,
            fill_px=monitored.fill_px,
            held_qty=Decimal(monitored.last_held_qty),
            mae=monitored.mae,
            mfe=monitored.mfe,
            first_signal_ts_ns=monitored.first_signal_ts_ns,
            first_signal_hour_lst=monitored.first_signal_hour_lst,
            first_signal_state=monitored.first_signal_state,
            verdict_at_signal=monitored.verdict_at_signal,
            recoverable_value_at_signal=monitored.recoverable_value_at_signal,
            held_duration_ns=max(0, now_ns - monitored.opened_at_ns),
            total_frames=monitored.total_frames,
            mark_missing_frames=monitored.mark_missing_frames,
            settled_pnl=None,
            settled_held=None,
            exit_rule=monitored.last_exit_rule,
            exit_decision=monitored.last_exit_decision,
            exit_reason_code=monitored.last_exit_reason_code,
            exit_limit_price=monitored.last_exit_limit_price,
            expected_settlement_value=monitored.last_exit_expected_settlement_value,
        )
