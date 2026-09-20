"""WP-R1 -- "all orders refused / zero orders today" must be treated as a HALT.

On 2026-09-17 the venue's taker fee coefficient moved and the live family
began refusing **100%** of candidates for the single reason
``fee_schedule_mismatch``. It ran three days before anyone noticed, because
a total refusal rate was logged at WARN and nothing escalated it.

These tests pin the discriminator that matters: a bot that declines to
trade because there is no edge is WORKING, and paging on that is worse than
paging on nothing at all. The predicate therefore keys on refusal-reason
HOMOGENEITY over a closed STRUCTURAL class -- never on take count alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from breezy.runtime.health import ALLOWED_ALERT_PAYLOAD_KEYS, AlertPayload, AlertState
from breezy.strategy.current_rung_hold.decision import REFUSAL_REASONS
from breezy.strategy.current_rung_hold.trial_day_latch import LATCH_GATE_REFUSAL_REASONS
from breezy.strategy.weather_common.halt_detector import (
    ALL_REFUSED_EVENT,
    ALLOWED_HALT_DETAILS,
    DEFAULT_HALT_WINDOW_NS,
    MIN_EVALUATED_FOR_ALL_REFUSED,
    PRE_DECISION_WAIT_DIAGNOSTICS,
    STRUCTURAL_HALT_REASONS,
    ZERO_EVALUATION_EVENT,
    DecisionWindowTally,
    HaltDetail,
    HaltDetector,
    all_refused_halt_reason,
    zero_evaluation_halt,
)
from breezy.strategy.weather_common.risk import COUNTED_REFUSAL_REASONS

SITE = "ContinuousRungHoldStrategy-MIA"
T0 = 1_789_664_400_000_000_000

#: The real 2026-09-17 offer tape, six rows, copied verbatim out of
#: ``docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md``.
INCIDENT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "incidents"
    / "offer_tape_2026-09-17_fee_drift.jsonl"
)


class RecordingSink:
    """Captures what would have gone on the wire."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _detector(sink: RecordingSink, **kwargs: object) -> HaltDetector:
    return HaltDetector(site=SITE, sink=sink, **kwargs)  # type: ignore[arg-type]


def _run_one_window(
    detector: HaltDetector, *, refusal_counts: dict[str, int], takes: int
) -> None:
    """Open a window at ``T0`` and close it one window later."""
    detector.observe(refusal_counts={}, takes=0, now_ns=T0, trading_expected=True)
    detector.observe(
        refusal_counts=refusal_counts,
        takes=takes,
        now_ns=T0 + DEFAULT_HALT_WINDOW_NS,
        trading_expected=True,
    )


# -- the predicate ------------------------------------------------------


def test_every_candidate_refused_for_one_structural_reason_is_a_halt() -> None:
    tally = DecisionWindowTally(refusals={"fee_schedule_mismatch": 40}, takes=0)
    assert all_refused_halt_reason(tally) == "fee_schedule_mismatch"


def test_a_mix_of_refusal_reasons_with_zero_takes_is_a_working_bot() -> None:
    tally = DecisionWindowTally(
        refusals={
            "edge_below_break_even": 22,
            "observation_ambiguous": 9,
            "not_executable": 5,
            "illegal_cell": 4,
        },
        takes=0,
    )
    assert all_refused_halt_reason(tally) is None
    assert zero_evaluation_halt(tally) is False


def test_one_homogeneous_judgement_reason_is_not_a_halt() -> None:
    """A whole window refused ``edge_below_break_even`` is the strategy
    working exactly as designed -- never a page."""
    tally = DecisionWindowTally(refusals={"edge_below_break_even": 40}, takes=0)
    assert all_refused_halt_reason(tally) is None


def test_a_window_with_a_take_is_never_a_halt() -> None:
    tally = DecisionWindowTally(refusals={"fee_schedule_mismatch": 40}, takes=1)
    assert all_refused_halt_reason(tally) is None
    assert zero_evaluation_halt(tally) is False


def test_zero_candidates_evaluated_is_its_own_condition() -> None:
    tally = DecisionWindowTally(refusals={}, takes=0)
    assert zero_evaluation_halt(tally) is True
    assert all_refused_halt_reason(tally) is None


def test_structural_reasons_are_a_subset_of_the_existing_refusal_vocabulary() -> None:
    known = REFUSAL_REASONS | COUNTED_REFUSAL_REASONS | LATCH_GATE_REFUSAL_REASONS
    assert STRUCTURAL_HALT_REASONS <= known


def test_an_unknown_reason_never_pages() -> None:
    tally = DecisionWindowTally(refusals={"some_future_reason": 99}, takes=0)
    assert all_refused_halt_reason(tally) is None


# -- the detector, end to end through the existing sink -----------------


def test_all_refused_window_emits_a_critical_alert_naming_the_reason() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window(detector, refusal_counts={"fee_schedule_mismatch": 40}, takes=0)

    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.severity == "CRITICAL"
    assert payload.event == ALL_REFUSED_EVENT
    assert payload.site == SITE
    assert payload.detail == "fee_schedule_mismatch"
    assert payload.detail in ALLOWED_HALT_DETAILS


def test_a_mixed_reason_window_emits_nothing() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window(
        detector,
        refusal_counts={"edge_below_break_even": 30, "observation_ambiguous": 10},
        takes=0,
    )
    assert sink.payloads == []


def test_a_window_with_a_take_emits_nothing() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window(detector, refusal_counts={"fee_schedule_mismatch": 40}, takes=2)
    assert sink.payloads == []


def test_a_window_with_no_candidate_evaluated_emits_the_zero_evaluation_alert() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window(detector, refusal_counts={}, takes=0)

    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.event == ZERO_EVALUATION_EVENT
    assert payload.severity == "CRITICAL"
    assert payload.detail == HaltDetail.NO_CANDIDATE_EVALUATED.value


def test_nothing_is_evaluated_while_trading_is_not_expected() -> None:
    """Overnight, zero candidates is the correct and expected state."""
    sink = RecordingSink()
    detector = _detector(sink)
    now = T0
    for _ in range(50):
        detector.observe(
            refusal_counts={}, takes=0, now_ns=now, trading_expected=False
        )
        now += DEFAULT_HALT_WINDOW_NS
    assert sink.payloads == []


# -- the wire contract --------------------------------------------------


@pytest.mark.parametrize(
    ("refusal_counts", "takes"),
    [({"fee_schedule_mismatch": 40}, 0), ({}, 0)],
)
def test_nothing_free_text_or_valued_reaches_the_wire(
    refusal_counts: dict[str, int], takes: int
) -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window(detector, refusal_counts=refusal_counts, takes=takes)

    assert sink.payloads
    for payload in sink.payloads:
        assert set(payload.to_dict()) == ALLOWED_ALERT_PAYLOAD_KEYS
        assert payload.detail in ALLOWED_HALT_DETAILS
        # No count, no theta, no config value, no credential: the detail is
        # a closed-enum token and nothing else.
        assert not any(char.isdigit() for char in payload.detail)
        assert " " not in payload.detail
        assert "0.0695" not in payload.detail
        assert "0.06" not in payload.detail


# -- rate limiting ------------------------------------------------------


def test_a_standing_halt_alerts_once_then_heartbeats_never_floods() -> None:
    sink = RecordingSink()
    renotify_ns = 24 * 3_600 * 1_000_000_000
    detector = _detector(sink, state=AlertState(renotify_after_ns=renotify_ns))

    now = T0
    # Two full days of ticks, 60s apart, every one of them refused.
    for tick in range(2 * 24 * 60):
        detector.observe(
            refusal_counts={"fee_schedule_mismatch": tick + 1},
            takes=0,
            now_ns=now,
            trading_expected=True,
        )
        now += 60_000_000_000

    # One transition alert, plus at most the 24h heartbeat -- never a flood.
    assert 1 <= len(sink.payloads) <= 2
    assert {payload.event for payload in sink.payloads} == {ALL_REFUSED_EVENT}


def test_a_window_still_open_emits_nothing_on_every_tick() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    detector.observe(refusal_counts={}, takes=0, now_ns=T0, trading_expected=True)
    for offset in range(1, 10):
        detector.observe(
            refusal_counts={"fee_schedule_mismatch": offset},
            takes=0,
            now_ns=T0 + offset,
            trading_expected=True,
        )
    assert sink.payloads == []


def test_recovery_then_relapse_alerts_again() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window(detector, refusal_counts={"fee_schedule_mismatch": 40}, takes=0)
    assert len(sink.payloads) == 1

    # A healthy window clears the condition...
    detector.observe(
        refusal_counts={"fee_schedule_mismatch": 40},
        takes=3,
        now_ns=T0 + 2 * DEFAULT_HALT_WINDOW_NS,
        trading_expected=True,
    )
    assert len(sink.payloads) == 1

    # ...so the next all-refused window is a fresh false->true transition.
    detector.observe(
        refusal_counts={"fee_schedule_mismatch": 80},
        takes=3,
        now_ns=T0 + 3 * DEFAULT_HALT_WINDOW_NS,
        trading_expected=True,
    )
    assert len(sink.payloads) == 2


# -- the 2026-09-17 regression -------------------------------------------


def _incident_tally() -> DecisionWindowTally:
    refusals: dict[str, int] = {}
    takes = 0
    for line in INCIDENT_FIXTURE.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["decision"] == "refuse":
            reason = row["reason"]
            refusals[reason] = refusals.get(reason, 0) + 1
        else:
            takes += 1
    return DecisionWindowTally(refusals=refusals, takes=takes)


def test_the_real_2026_09_17_tape_is_homogeneous_fee_schedule_mismatch() -> None:
    tally = _incident_tally()
    assert tally.takes == 0
    assert tally.refusals == {"fee_schedule_mismatch": 6}
    assert tally.evaluated >= MIN_EVALUATED_FOR_ALL_REFUSED


def test_this_detector_would_have_fired_on_2026_09_17() -> None:
    """The regression that matters: three silent days.

    Six rows is the WHOLE day's offer tape (2026-09-16 held 53,624), so any
    coverage threshold above a handful would have missed the very incident
    this detector exists for.
    """
    sink = RecordingSink()
    detector = _detector(sink)
    tally = _incident_tally()
    _run_one_window(detector, refusal_counts=dict(tally.refusals), takes=tally.takes)

    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.severity == "CRITICAL"
    assert payload.event == ALL_REFUSED_EVENT
    assert payload.detail == "fee_schedule_mismatch"
    assert "0.0695" not in payload.detail


# -- wiring: a detector nobody calls is a decoration ---------------------


class _FakeStrategy:
    """Duck-typed stand-in, mirroring ``test_current_rung_hold_composition``'s:
    the installer only reads ``.id`` and the counter attributes."""

    def __init__(self, strategy_id: str) -> None:
        from breezy.strategy.weather_common.refusals import RefusalCounter

        self.id = strategy_id
        self.refusals = RefusalCounter()
        self.refusal_alerter: object | None = None
        self.diagnostics = RefusalCounter()
        self.diagnostics_alerter: object | None = None
        self.position_events = RefusalCounter()
        self.position_alerter: object | None = None
        self.halt_detector: object | None = None


def test_composition_installs_a_halt_detector_on_every_strategy() -> None:
    from breezy.strategy.current_rung_hold.composition import (
        install_current_rung_hold_refusal_watch,
    )

    strategy = _FakeStrategy("ContinuousRungHoldStrategy-LAX")
    install_current_rung_hold_refusal_watch(object(), [strategy])  # type: ignore[list-item]

    assert isinstance(strategy.halt_detector, HaltDetector)


def test_the_continuous_strategy_exposes_the_detector_and_a_take_counter() -> None:
    """The two attributes the per-tick observe call needs."""
    import inspect

    from breezy.strategy.current_rung_hold import continuous_strategy

    source = inspect.getsource(continuous_strategy)
    assert "self.halt_detector" in source
    assert "self.takes" in source
    assert "_observe_halt" in source


# -- the MDW 2026-09-20 FALSE-PAGE regression ---------------------------
#
# WP-R1 shipped and misfired on its first live day: MDW raised
# ``ZERO_CANDIDATES_EVALUATED_HALT`` at 18:58Z while the SAME station
# evaluated at 18:48Z and 19:03Z, both ``IN_WINDOW_NOT_EXECUTABLE_WAIT``.
# A pre-decision WAIT is not a candidate evaluated, so an ordinary illiquid
# stretch closed a window with zero candidates and the zero-evaluation arm
# read it as a structural block. The arm must gate on OBSERVED TICKS, not on
# candidate count: ticks observed but none reaching a decision is a thin
# market; NO tick at all while trading was expected is the discovery /
# subscription collapse this condition exists for.


def _run_one_window_with_waits(
    detector: HaltDetector,
    *,
    refusal_counts: dict[str, int],
    takes: int,
    diagnostic_counts: dict[str, int],
) -> None:
    detector.observe(
        refusal_counts={},
        takes=0,
        now_ns=T0,
        trading_expected=True,
        diagnostic_counts={},
    )
    detector.observe(
        refusal_counts=refusal_counts,
        takes=takes,
        now_ns=T0 + DEFAULT_HALT_WINDOW_NS,
        trading_expected=True,
        diagnostic_counts=diagnostic_counts,
    )


def test_pre_decision_wait_keys_match_the_strategys_own_diagnostics() -> None:
    """This module invents no counter: every member is a key the strategy
    already records at a pre-decision ``return``."""
    from breezy.strategy.current_rung_hold import strategy as strategy_module

    assert PRE_DECISION_WAIT_DIAGNOSTICS == frozenset(
        {
            strategy_module._DIAG_NOT_EXECUTABLE,
            strategy_module._DIAG_NO_RUNNING_MAX_YET,
            strategy_module._DIAG_RUNG_NOT_CURRENT,
        }
    )


def test_ticks_observed_but_none_evaluated_is_a_thin_market_not_a_halt() -> None:
    tally = DecisionWindowTally(refusals={}, takes=0, wait_ticks=2)
    assert tally.evaluated == 0
    assert zero_evaluation_halt(tally) is False
    assert all_refused_halt_reason(tally) is None


def test_the_mdw_18_58z_shape_is_silent() -> None:
    """The exact defect: in-window, ``in_window_not_executable`` waits
    observed, zero candidates evaluated -- and NO page."""
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window_with_waits(
        detector,
        refusal_counts={},
        takes=0,
        diagnostic_counts={"in_window_not_executable": 2},
    )
    assert sink.payloads == []


def test_a_rung_not_current_wait_window_is_silent_too() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window_with_waits(
        detector,
        refusal_counts={},
        takes=0,
        diagnostic_counts={"in_window_rung_not_current": 7},
    )
    assert sink.payloads == []


def test_a_non_wait_diagnostic_does_not_suppress_the_zero_evaluation_alert() -> None:
    """Only PRE-DECISION waits count as an observed tick. A post-decision
    diagnostic (``family_halt``) is not evidence the feed is alive."""
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window_with_waits(
        detector,
        refusal_counts={},
        takes=0,
        diagnostic_counts={"family_halt": 3},
    )
    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == ZERO_EVALUATION_EVENT


def test_zero_ticks_of_any_kind_still_pages_the_zero_evaluation_alert() -> None:
    """The genuine case WP-R1 exists for: no eligible instrument, discovery
    collapse, subscription starvation -- nothing observed at all."""
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window_with_waits(
        detector, refusal_counts={}, takes=0, diagnostic_counts={}
    )
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.event == ZERO_EVALUATION_EVENT
    assert payload.severity == "CRITICAL"
    assert payload.detail == HaltDetail.NO_CANDIDATE_EVALUATED.value
    assert payload.detail in ALLOWED_HALT_DETAILS
    assert not any(char.isdigit() for char in payload.detail)
    assert " " not in payload.detail


def test_wait_ticks_outside_the_decision_window_never_page() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    now = T0
    for _ in range(50):
        detector.observe(
            refusal_counts={},
            takes=0,
            now_ns=now,
            trading_expected=False,
            diagnostic_counts={"in_window_not_executable": 1},
        )
        now += DEFAULT_HALT_WINDOW_NS
    assert sink.payloads == []


def test_wait_ticks_from_an_earlier_window_do_not_suppress_the_next_one() -> None:
    """The wait counter is CUMULATIVE, so the detector must diff it per
    window: yesterday's waits must not mute today's genuine starvation."""
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window_with_waits(
        detector,
        refusal_counts={},
        takes=0,
        diagnostic_counts={"in_window_not_executable": 4},
    )
    assert sink.payloads == []

    detector.observe(
        refusal_counts={},
        takes=0,
        now_ns=T0 + 2 * DEFAULT_HALT_WINDOW_NS,
        trading_expected=True,
        diagnostic_counts={"in_window_not_executable": 4},
    )
    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == ZERO_EVALUATION_EVENT


def test_the_all_refused_arm_is_untouched_by_wait_ticks() -> None:
    """A window that DID evaluate, homogeneously structural, still pages --
    with or without waits alongside it."""
    sink = RecordingSink()
    detector = _detector(sink)
    _run_one_window_with_waits(
        detector,
        refusal_counts={"fee_schedule_mismatch": 40},
        takes=0,
        diagnostic_counts={"in_window_not_executable": 11},
    )
    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == ALL_REFUSED_EVENT
    assert sink.payloads[0].detail == "fee_schedule_mismatch"


def test_the_2026_09_17_fixture_still_fires_with_waits_observed() -> None:
    sink = RecordingSink()
    detector = _detector(sink)
    tally = _incident_tally()
    _run_one_window_with_waits(
        detector,
        refusal_counts=dict(tally.refusals),
        takes=tally.takes,
        diagnostic_counts={"in_window_not_executable": 3},
    )
    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == ALL_REFUSED_EVENT
    assert sink.payloads[0].detail == "fee_schedule_mismatch"
    assert "0.0695" not in sink.payloads[0].detail


def test_the_continuous_strategy_feeds_the_detector_its_wait_diagnostics() -> None:
    """A gate nobody supplies is a gate that never opens: the per-tick
    observe call must hand the diagnostics counter across."""
    import inspect

    from breezy.strategy.current_rung_hold import continuous_strategy

    source = inspect.getsource(
        continuous_strategy.ContinuousRungHoldStrategy._observe_halt
    )
    assert "diagnostic_counts=self.diagnostics.counts" in source
