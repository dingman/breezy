"""NO-side shadow evaluator for ``ContinuousRungHoldStrategy`` (R3.4 move).

``NoSideShadowMixin`` carries ``_evaluate_no_side_shadow`` and its log seams
unchanged; the strategy class inherits it so ``self.`` dispatch (including
test subclass overrides of the ``_emit_*`` seams) is unaffected.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal, Protocol

from nautilus_trader.model.identifiers import InstrumentId

from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    first_live_order_payload,
    is_no_side_pending,
)
from breezy.adapters.polymarket_us.operator_controls import utc_day_for_ns
from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.strategy.current_rung_hold.continuous_helpers import (
    _NS_PER_MINUTE,
    _NS_PER_SECOND,
    _ONE,
)
from breezy.strategy.current_rung_hold.decision import Decision, Refuse, Take
from breezy.strategy.current_rung_hold.offer_tape import OfferTapeRecord
from breezy.strategy.current_rung_hold.strategy import _WINDOW_START_HOUR_LST
from breezy.strategy.current_rung_hold.trial_day_latch import (
    SIBLING_LEG_TRADED_REASON,
    STATION_DAY_ADMISSION_REASON,
    refuse_if_sibling_leg_traded,
    station_day_admission,
)
from breezy.strategy.weather_common.running_extreme import RunningMax

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.common.component import Logger

    from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
    from breezy.strategy.current_rung_hold.offer_tape import OfferTape
    from breezy.strategy.current_rung_hold.resting_decider import ShadowRestTickResult
    from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch


class _NoSideHost(Protocol):
    """The exact host surface the mixin's methods use (R3.4 follow-up).

    ``ContinuousRungHoldStrategy`` is the sole host. The mixin methods annotate
    ``self: _NoSideHost`` so mypy checks every ``self.`` access against the
    host's real types. Typing-only: nothing here exists on the host at runtime.
    Under ``from __future__ import annotations`` the annotation is never
    evaluated, so no import of the strategy module (a cycle) is needed.
    """

    log: Logger
    offer_tape: OfferTape
    no_takes: int
    last_no_take_shadow: str | None
    last_no_refuse: str | None
    _latch: TrialDayLatch | None
    _no_refuse_notice: set[tuple[str, str, str]]
    _no_shadow_notice: dict[tuple[str, str, str], int]
    _decision_ask_by_station_day: dict[tuple[str, str], Decimal]

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
    ) -> ShadowRestTickResult: ...

    def _station_day_existing_legs(
        self, station_day: tuple[str, str]
    ) -> tuple[tuple[str, ...], Mapping[str, DurableFillRecord]]: ...

    def _record_rearm_decision(self, summary: str) -> None: ...
    def _maybe_submit(self, instrument_id: str, decision: Take) -> None: ...
    def _submission_armed(self) -> bool: ...
    def _record_no_take_shadow(self, summary: str) -> None: ...
    def _emit_no_take_shadow(self, summary: str) -> None: ...
    def _record_no_refuse(self, summary: str) -> None: ...
    def _emit_no_refuse(self, summary: str) -> None: ...


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


class NoSideShadowMixin:
    """Mixin: the NO-leg shadow gate chain (see ``_evaluate_no_side_shadow``)."""

    # Declared so mypy does not infer a narrower type from the ``self.`` writes
    # below; the strategy's ``__init__`` initialises both to ``None``.
    last_no_take_shadow: str | None
    last_no_refuse: str | None

    def _evaluate_no_side_shadow(
        self: _NoSideHost,
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
            store,
            prefix,
            station,
            climate_day_key,
            no_iid,
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
                decision_label="refuse",
                admission_reason=admission_refusal.reason,
            )
            return

        utc_day = utc_day_for_ns(now_ns).isoformat()
        if self._latch.is_day_budget_exhausted(utc_day):
            _refuse_once(_NO_REFUSE_DAY_BUDGET_EXHAUSTED)
            _append_no_offer_tape(
                decision_label="refuse",
                admission_reason=_NO_REFUSE_DAY_BUDGET_EXHAUSTED,
            )
            return
        if self._latch.is_consumed(station, climate_day_key, key_instrument_id=no_iid):
            _refuse_once(_NO_REFUSE_TRIAL_DAY_CONSUMED)
            _append_no_offer_tape(
                decision_label="refuse",
                admission_reason=_NO_REFUSE_TRIAL_DAY_CONSUMED,
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
                "None" if running_max is None else f"[{running_max.lower_f},{running_max.upper_f}]"
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
            station,
            climate_day_key,
            ts_ns=now_ns,
            key_instrument_id=no_iid,
        )
        self._record_rearm_decision(
            f"rearm: {station}/{climate_day_key} NO armed instrument={no_iid}"
        )
        self._maybe_submit(no_iid, no_decision)
        if not self._submission_armed():
            self._latch.clear_inflight(station, climate_day_key, key_instrument_id=no_iid)

    def _record_no_take_shadow(self: _NoSideHost, summary: str) -> None:
        """Mirrors `_record_rearm_decision` -- stores the ONE summary line
        on `self.last_no_take_shadow` (asserted by presence, L-27) and
        emits it via the overridable seam below. Stable grep token
        `no_take_shadow:`.
        """
        self.last_no_take_shadow = summary
        self._emit_no_take_shadow(summary)

    def _emit_no_take_shadow(self: _NoSideHost, summary: str) -> None:
        self.log.info(summary)

    def _record_no_refuse(self: _NoSideHost, summary: str) -> None:
        """Mirrors `_record_no_take_shadow` above for the refusal line,
        stable grep token `no_refuse:`.
        """
        self.last_no_refuse = summary
        self._emit_no_refuse(summary)

    def _emit_no_refuse(self: _NoSideHost, summary: str) -> None:
        self.log.info(summary)
