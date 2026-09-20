"""A bot that CANNOT trade, told apart from a bot that DECLINES to trade.

WHY THIS MODULE EXISTS
----------------------
On 2026-09-17 the venue's taker fee coefficient drifted. ``decision.py``'s
fail-closed ``fee_schedule_mismatch`` gate then refused **every** candidate,
correctly, and the live family stopped trading. It ran three days before
anyone noticed, because a 100% refusal rate reached the operator as three
WARN lines that each said ``1 order(s) refused`` and nothing escalated
them (``docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md``).

    A 100% refusal rate IS a halt. A decision window with nothing evaluated
    at all IS a halt. Neither was treated as one.

THE HARD PART: NOT CRYING WOLF
------------------------------
"No take today" is a LEGITIMATE and expected outcome here. The family
refuses when there is no edge, and that is the strategy working. A detector
that pages on every quiet day is worse than no detector, because it teaches
the operator to mute the channel -- and a muted channel is exactly the
state WP-B0 just spent an increment escaping.

So the predicate never keys on take count alone. It keys on two axes:

1. **Homogeneity.** Forty candidates refused for forty different reasons is
   a working bot reading a market. Forty refused for ONE reason is a single
   gate standing in front of everything.
2. **Reason CLASS.** Homogeneity alone is not enough: a genuinely quiet hour
   can be 100% ``edge_below_break_even``, which is the rule doing its job.
   Only a reason from :data:`STRUCTURAL_HALT_REASONS` -- a closed set whose
   members depend on CONFIGURATION or ACCOUNT STATE rather than on this
   candidate's price -- can raise the all-refused halt. Every other reason,
   including any reason this module has never heard of, is silent by
   construction: an unrecognised reason is a false page waiting to happen,
   and the cost of missing one structural block is bounded by the
   zero-evaluation condition and the node-side heartbeat, while the cost of
   a false page is an operator who stops reading alerts.

COVERAGE IS DELIBERATELY LOW (:data:`MIN_EVALUATED_FOR_ALL_REFUSED` = 1).
The 2026-09-17 offer tape holds **six rows for the entire day** against
2026-09-16's 53,624. Any "you need 20 candidates before I believe you"
threshold would have missed the very incident this module exists for. The
discrimination is carried by the reason CLASS, not by sample size, so
coverage only has to be non-zero -- and a window with zero candidates is
not silently ignored, it raises the *other* condition.

NOT A SECOND ALERT CHANNEL. Conditions are dispatched through the existing
:class:`~breezy.runtime.health.AlertState` /
:func:`~breezy.runtime.health.emit_alert` path, exactly as
:mod:`breezy.strategy.weather_common.refusals` does. ``AlertState`` supplies
the false->true dedupe and the periodic re-notify, so a standing halt costs
one alert plus a heartbeat rather than one per tick.

NOTHING VALUED REACHES THE WIRE. ``AlertPayload.detail`` is always a token
from :data:`ALLOWED_HALT_DETAILS` -- the structural refusal reason itself,
or a :class:`HaltDetail` member. Never a count, never the fee coefficient
that drifted, never a config value, never a credential. The operator learns
WHICH gate is standing in front of the family; the value that tripped it is
read from the offer tape, which is the channel that can carry it safely.

**This module DETECTS a halt. It never clears one.** It holds no reference
to the fee pin, submits nothing, and cannot let an order through.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from breezy.runtime.health import (
    AlertCondition,
    AlertConditionKey,
    AlertPayload,
    AlertSink,
    AlertState,
    emit_alert,
    resolve_alert_sink,
)

__all__ = [
    "ALLOWED_HALT_DETAILS",
    "ALL_REFUSED_EVENT",
    "DEFAULT_HALT_WINDOW_NS",
    "MIN_EVALUATED_FOR_ALL_REFUSED",
    "PRE_DECISION_WAIT_DIAGNOSTICS",
    "STRUCTURAL_HALT_REASONS",
    "ZERO_EVALUATION_EVENT",
    "DecisionWindowTally",
    "HaltDetail",
    "HaltDetector",
    "all_refused_halt_reason",
    "zero_evaluation_halt",
]

#: `AlertPayload.event` for condition 1. An event names a CONDITION an
#: operator acts on; the individual refusal that raised it is the `detail`.
ALL_REFUSED_EVENT: Final[str] = "ALL_ORDERS_REFUSED_HALT"

#: `AlertPayload.event` for condition 2. Deliberately a SEPARATE event from
#: the one above: "every candidate was blocked by one gate" and "no
#: candidate ever reached a gate" have different causes (a config/state
#: block vs. discovery or subscription collapse) and different first moves.
ZERO_EVALUATION_EVENT: Final[str] = "ZERO_CANDIDATES_EVALUATED_HALT"

#: One hour. Matches the cadence at which the 2026-09-17 refusals actually
#: surfaced (17:00Z / 18:00Z / 20:00Z) and keeps at most one evaluation per
#: hour per site even if the caller `observe`s on every tick.
DEFAULT_HALT_WINDOW_NS: Final[int] = 3_600 * 1_000_000_000

#: See the module docstring: the 2026-09-17 tape held SIX rows for the whole
#: day. The reason CLASS carries the discrimination, so coverage only has to
#: be non-zero -- raising this is how the next incident goes unnoticed.
MIN_EVALUATED_FOR_ALL_REFUSED: Final[int] = 1

#: The closed set of refusal reasons that, when they are the ONLY reason a
#: window produced, mean the family is structurally unable to trade.
#:
#: Membership test: does this reason depend on CONFIGURATION or ACCOUNT
#: STATE rather than on the candidate's own price/observation? Every member
#: already exists in the shared refusal vocabulary (`decision.REFUSAL_REASONS`,
#: `risk.COUNTED_REFUSAL_REASONS`, `trial_day_latch.LATCH_GATE_REFUSAL_REASONS`)
#: -- this module invents no reason of its own.
#:
#: Deliberately EXCLUDED, with the reasoning, because each is a false page:
#:
#: * ``edge_below_break_even``, ``not_executable``, ``observation_ambiguous``,
#:   ``observation_unavailable``, ``stale_observation``, ``stale_forecast``,
#:   ``illegal_cell``, ``p_hold_undefined``, ``wide_spread`` -- per-candidate
#:   judgements. 100% of them is a quiet market, which is the expected case.
#: * ``outside_decision_window`` -- 100% of it is simply a quote arriving
#:   outside `[12:00,17:00)` LST, i.e. most of the day.
#: * ``trial_day_consumed``, ``station_day_admission``, ``sibling_leg_traded``
#:   -- the family ALREADY traded this station-day. That is success, not a
#:   halt.
#: * ``too_close_to_settlement`` -- the correct end-of-day posture.
STRUCTURAL_HALT_REASONS: Final[frozenset[str]] = frozenset(
    {
        # The 2026-09-17 incident itself: the pinned coefficient disagrees
        # with the venue's, so the break-even the archive was computed
        # against is no longer the one we would pay.
        "fee_schedule_mismatch",
        # A whole trading direction disabled by `allow_short=False`.
        "shorts_disabled",
        # Every configured instrument missing from the cache at start-up:
        # discovery or the instrument provider, not the market.
        "instrument_unresolved",
        # The settlement gate holding the family flat.
        "settlement_halt",
        # The NO-side first-order containment window standing open.
        "no_side_first_order_pending",
    }
)


#: The closed set of WAIT-state diagnostic keys that prove a tick was
#: OBSERVED in the decision window without ever reaching a decision.
#:
#: Named here as literals rather than imported from
#: ``current_rung_hold.strategy`` because ``weather_common`` sits BELOW the
#: family packages in the import graph (``lint-imports``); a test pins these
#: against that module's own ``_DIAG_*`` constants, so a rename there cannot
#: silently drift this set. This module still invents no counter of its own:
#: every member is a key the strategy ALREADY records at a pre-decision
#: ``return``, and nothing about what it counts changes here.
#:
#: Why the zero-evaluation arm needs them (MDW, 2026-09-20): a pre-decision
#: WAIT is not a candidate evaluated. When every tick in a window fails
#: executability -- an ordinary illiquid stretch on a thin venue -- the
#: window closes with ZERO candidates, and reading that as a structural
#: block pages the operator for a thin market. Ticks observed but undecided
#: is a market; NO tick at all is discovery or subscription collapse, which
#: is the condition this arm exists for.
PRE_DECISION_WAIT_DIAGNOSTICS: Final[frozenset[str]] = frozenset(
    {
        "in_window_not_executable",
        "in_window_no_running_max_yet",
        "in_window_rung_not_current",
    }
)


class HaltDetail(str, Enum):
    """Closed set of ``detail`` tokens this module emits that are NOT
    themselves a refusal reason.

    Never exception text, never a count, never a config/fee value -- the
    same stance as ``trade_supervisor_core.AlertDetail`` and
    ``check_alerts_cli.CheckAlertDetail``.
    """

    NO_CANDIDATE_EVALUATED = "no_candidate_evaluated"


#: Everything this module may ever put in ``AlertPayload.detail``. A test
#: asserts every emitted payload's detail is a member, so free text cannot
#: leak in through a future edit.
ALLOWED_HALT_DETAILS: Final[frozenset[str]] = STRUCTURAL_HALT_REASONS | frozenset(
    detail.value for detail in HaltDetail
)


@dataclass(frozen=True, slots=True)
class DecisionWindowTally:
    """What ONE decision window produced: refusals by reason, plus takes.

    ``refusals`` holds only reasons that actually occurred (a zero entry and
    an absent entry are the same fact). Deliberately NOT cumulative: this is
    a window delta, which :class:`HaltDetector` computes from the
    process-cumulative counters it is handed.
    """

    refusals: Mapping[str, int]
    takes: int
    #: Ticks OBSERVED in this window that returned before any decision --
    #: the sum of this window's :data:`PRE_DECISION_WAIT_DIAGNOSTICS`
    #: deltas. Evidence the feed is alive even when ``evaluated`` is zero.
    wait_ticks: int = 0

    @property
    def evaluated(self) -> int:
        """Candidates this window reached a decision on -- refused or taken."""
        return self.takes + sum(self.refusals.values())


def all_refused_halt_reason(tally: DecisionWindowTally) -> str | None:
    """The single structural reason that blocked EVERY candidate, or ``None``.

    See the module docstring for the two axes and why neither alone is
    enough. Returns the reason string (always a member of
    :data:`STRUCTURAL_HALT_REASONS`) so the caller can name the gate.
    """
    if tally.takes > 0:
        return None
    if tally.evaluated < MIN_EVALUATED_FOR_ALL_REFUSED:
        return None
    reasons = {reason for reason, count in tally.refusals.items() if count > 0}
    if len(reasons) != 1:
        return None
    reason = next(iter(reasons))
    return reason if reason in STRUCTURAL_HALT_REASONS else None


def zero_evaluation_halt(tally: DecisionWindowTally) -> bool:
    """A decision window in which nothing was ever OBSERVED.

    Distinct from every refusal: no gate refused, because no candidate
    reached one. The caller decides WHEN this is meaningful by passing
    ``trading_expected`` to :meth:`HaltDetector.observe` -- overnight, zero
    candidates is simply correct.

    Gated on the OBSERVED TICK count, not the candidate count (MDW
    18:58Z, 2026-09-20 -- the first live day of this module, and a false
    page). ``evaluated == 0`` alone is also what an ordinary illiquid
    stretch looks like: every tick arrived, every tick was a pre-decision
    wait, nothing reached a gate. Only a window in which NOTHING arrived at
    all -- no candidate AND no wait tick -- is the discovery / subscription
    collapse this condition names.
    """
    return tally.evaluated == 0 and tally.wait_ticks == 0


class HaltDetector:
    """Closes a decision window periodically and alerts when it was a halt.

    Fed the SAME process-cumulative counters the strategy already keeps
    (:class:`~breezy.strategy.weather_common.refusals.RefusalCounter.counts`
    plus a take count), so no second set of ``record`` calls has to be
    threaded through the decision path. Window deltas are derived here by
    diffing against the last window's baseline.

    Single-threaded for the same reason :class:`AlertState` is: ``observe``
    is a read-modify-write over this object's baselines and that state, so
    it must run on the loop that owns it (for a ``Strategy``, its event
    handlers). Nothing here is persisted: a restart starts a fresh window,
    and a still-standing halt is a fresh false->true transition that alerts
    again -- which is the behaviour you want after a restart.
    """

    def __init__(
        self,
        *,
        site: str,
        sink: AlertSink | None = None,
        state: AlertState | None = None,
        window_ns: int = DEFAULT_HALT_WINDOW_NS,
    ) -> None:
        if window_ns <= 0:
            raise ValueError(f"window_ns must be positive, was {window_ns!r}")
        self._site = site
        self._sink = resolve_alert_sink() if sink is None else sink
        self._state = AlertState() if state is None else state
        self._window_ns = window_ns
        self._window_open_ns: int | None = None
        self._baseline_refusals: dict[str, int] = {}
        self._baseline_diagnostics: dict[str, int] = {}
        self._baseline_takes = 0

    def observe(
        self,
        *,
        refusal_counts: Mapping[str, int],
        takes: int,
        now_ns: int,
        trading_expected: bool,
        diagnostic_counts: Mapping[str, int] | None = None,
    ) -> tuple[AlertPayload, ...]:
        """Record this tick's cumulative counters; close the window if due.

        Returns the payloads DECIDED this call -- empty on every tick that
        does not close a window, and on every window that was not a halt.
        Never what the sink managed to deliver (``emit_alert`` contains and
        never reports delivery failure, by design).

        ``trading_expected`` is the caller's answer to "should this family
        be able to trade right now?" -- for ``current_rung_hold``, whether
        the LST decision window is open. While it is ``False`` the baseline
        simply slides and no window can close, so a quiet night can never
        page.

        ``diagnostic_counts`` is the strategy's cumulative WAIT-state
        diagnostics counter (``strategy.diagnostics.counts``); only the
        :data:`PRE_DECISION_WAIT_DIAGNOSTICS` members are read, and only to
        answer "was anything observed at all this window?". Omitting it is
        the same fact as "no wait tick was observed".
        """
        counts = {reason: count for reason, count in refusal_counts.items() if count > 0}
        diagnostics = {
            key: count
            for key, count in (diagnostic_counts or {}).items()
            if key in PRE_DECISION_WAIT_DIAGNOSTICS and count > 0
        }
        if not trading_expected or self._window_open_ns is None:
            self._reset(counts, diagnostics, takes, now_ns)
            return ()
        if now_ns - self._window_open_ns < self._window_ns:
            return ()

        tally = self._tally(counts, diagnostics, takes)
        self._reset(counts, diagnostics, takes, now_ns)
        payloads = self._state.evaluate(self._conditions(tally), now_ns=now_ns)
        for payload in payloads:
            emit_alert(self._sink, payload)
        return payloads

    # -- internals ------------------------------------------------------

    def _reset(
        self,
        counts: Mapping[str, int],
        diagnostics: Mapping[str, int],
        takes: int,
        now_ns: int,
    ) -> None:
        self._baseline_refusals = dict(counts)
        self._baseline_diagnostics = dict(diagnostics)
        self._baseline_takes = takes
        self._window_open_ns = now_ns

    def _tally(
        self,
        counts: Mapping[str, int],
        diagnostics: Mapping[str, int],
        takes: int,
    ) -> DecisionWindowTally:
        """This window's delta against the baseline.

        A counter that went BACKWARDS (a restart of whatever owns it) is
        clamped at zero rather than producing a negative "evaluated": an
        arithmetic artefact must never be able to manufacture a halt.
        """
        refusals = {
            reason: count - self._baseline_refusals.get(reason, 0)
            for reason, count in counts.items()
            if count - self._baseline_refusals.get(reason, 0) > 0
        }
        wait_ticks = sum(
            max(0, count - self._baseline_diagnostics.get(key, 0))
            for key, count in diagnostics.items()
        )
        return DecisionWindowTally(
            refusals=refusals,
            takes=max(0, takes - self._baseline_takes),
            wait_ticks=wait_ticks,
        )

    def _conditions(self, tally: DecisionWindowTally) -> tuple[AlertCondition, ...]:
        """Every condition this detector tracks, EVERY window.

        Inactive ones are passed too, so ``AlertState`` sees the true->false
        edge and a halt that recovers and relapses alerts again rather than
        being muted as a repeat. The all-refused conditions are one per
        member of the closed :data:`STRUCTURAL_HALT_REASONS`, keyed by
        ``extra``, so switching from one structural block to another is a
        fresh transition rather than a silently-continued one.
        """
        halted_reason = all_refused_halt_reason(tally)
        conditions = [
            AlertCondition(
                key=AlertConditionKey(kind=ZERO_EVALUATION_EVENT, site=self._site),
                active=zero_evaluation_halt(tally),
                severity="CRITICAL",
                event=ZERO_EVALUATION_EVENT,
                detail=HaltDetail.NO_CANDIDATE_EVALUATED.value,
            )
        ]
        conditions.extend(
            AlertCondition(
                key=AlertConditionKey(
                    kind=ALL_REFUSED_EVENT, site=self._site, extra=reason
                ),
                active=reason == halted_reason,
                severity="CRITICAL",
                event=ALL_REFUSED_EVENT,
                detail=reason,
            )
            for reason in sorted(STRUCTURAL_HALT_REASONS)
        )
        return tuple(conditions)
