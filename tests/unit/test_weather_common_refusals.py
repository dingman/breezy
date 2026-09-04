"""Unit tests for `breezy.strategy.weather_common.refusals`.

The counter exists because of a specific failure mode, not for telemetry's
sake: `calibration_mean_reversion` was SHORT_YES-only in the tested window, so
with shorts disabled it can execute NO signal at all. A strategy producing zero
trades because it is structurally disabled and one producing zero trades
because the market is efficient are the SAME observation and completely
different facts. These tests pin the second one being distinguishable from the
first at the alert sink.
"""

from __future__ import annotations

from breezy.runtime.health import AlertPayload, AlertState
from breezy.strategy.weather_common import risk as risk_module
from breezy.strategy.weather_common.refusals import (
    OBSERVATION_AMBIGUOUS,
    OBSERVATION_UNAVAILABLE,
    SHORTS_DISABLED,
    SHORTS_DISABLED_EVENT,
    RefusalAlerter,
    RefusalCounter,
    observation_refusal,
)
from breezy.strategy.weather_common.running_extreme import RunningMax

SITE = "strategy/CalibrationMeanReversion-000"

#: One day in nanoseconds -- `AlertState`'s default re-notify cadence.
DAY_NS = 24 * 60 * 60 * 1_000_000_000


class _RecordingSink:
    """An `AlertSink` that keeps what it was handed."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


# ---------------------------------------------------------------------------
# RefusalCounter
# ---------------------------------------------------------------------------


def test_a_fresh_counter_counts_zero() -> None:
    counter = RefusalCounter()
    assert counter.count(SHORTS_DISABLED) == 0
    assert counter.total() == 0


def test_records_accumulate_per_reason() -> None:
    counter = RefusalCounter()
    counter.record(SHORTS_DISABLED)
    counter.record(SHORTS_DISABLED)
    counter.record("some_other_reason")

    assert counter.count(SHORTS_DISABLED) == 2
    assert counter.count("some_other_reason") == 1
    assert counter.total() == 3


# ---------------------------------------------------------------------------
# RefusalAlerter -- counter -> existing alert path
# ---------------------------------------------------------------------------


def test_a_shorts_disabled_refusal_reaches_the_alert_sink() -> None:
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(counter, site=SITE, sink=sink)

    counter.record(SHORTS_DISABLED)
    emitted = alerter.report(now_ns=1_000)

    assert emitted == 1
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.event == SHORTS_DISABLED_EVENT
    assert payload.site == SITE
    assert payload.severity == "WARN"
    assert "1" in payload.detail


def test_no_refusal_emits_nothing() -> None:
    """Silence here must mean "nothing was refused", never "nobody looked"."""
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(counter, site=SITE, sink=sink)

    assert alerter.report(now_ns=1_000) == 0
    assert sink.payloads == []


def test_a_standing_refusal_does_not_re_notify_on_every_cycle() -> None:
    """`AlertState`'s dedupe is the whole reason this goes through it.

    A strategy evaluates on every quote tick; an alert per refused order would
    be a firehose an operator learns to ignore, which is the same outcome as no
    alert at all.
    """
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(counter, site=SITE, sink=sink)

    counter.record(SHORTS_DISABLED)
    alerter.report(now_ns=1_000)
    for _ in range(50):
        counter.record(SHORTS_DISABLED)
        alerter.report(now_ns=2_000)

    assert len(sink.payloads) == 1


def test_a_standing_refusal_re_notifies_after_the_renotify_window() -> None:
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(
        counter, site=SITE, sink=sink, state=AlertState(renotify_after_ns=DAY_NS),
    )

    counter.record(SHORTS_DISABLED)
    alerter.report(now_ns=1_000)
    counter.record(SHORTS_DISABLED)
    alerter.report(now_ns=1_000 + DAY_NS)

    assert len(sink.payloads) == 2
    assert "2" in sink.payloads[1].detail


def test_the_detail_names_the_structural_disablement_not_just_a_number() -> None:
    """"12 refusals" is a metric; the operator needs the interpretation."""
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(counter, site=SITE, sink=sink)

    counter.record(SHORTS_DISABLED)
    alerter.report(now_ns=1_000)

    detail = sink.payloads[0].detail
    assert SHORTS_DISABLED in detail
    assert "no trades" in detail


def test_a_stale_observation_only_refusal_alerts() -> None:
    """A refusal reason other than SHORTS_DISABLED must still reach the sink."""
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(counter, site=SITE, sink=sink)

    counter.record("stale_observation")
    emitted = alerter.report(now_ns=1_000)

    assert emitted == 1
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert "stale_observation" in payload.detail
    assert payload.site == SITE
    assert payload.severity == "WARN"


def test_two_refusal_reasons_alert_naming_both() -> None:
    """A run refused for two distinct reasons alerts once per reason, each named."""
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(counter, site=SITE, sink=sink)

    counter.record("stale_observation")
    counter.record(SHORTS_DISABLED)
    emitted = alerter.report(now_ns=1_000)

    assert emitted == 2
    details = [payload.detail for payload in sink.payloads]
    assert any("stale_observation" in detail for detail in details)
    assert any(SHORTS_DISABLED in detail for detail in details)


def test_zero_refusals_of_any_kind_does_not_alert() -> None:
    counter = RefusalCounter()
    sink = _RecordingSink()
    alerter = RefusalAlerter(counter, site=SITE, sink=sink)

    assert alerter.report(now_ns=1_000) == 0
    assert sink.payloads == []


# ---------------------------------------------------------------------------
# BL-24 Seam B section 5 / amendment A4: the decision-layer observation refusal
# ---------------------------------------------------------------------------

#: Closed rung bounds exactly as `WeatherBucketFacts.lower_f`/`upper_f` expose
#: them (post Seam A-2 fix): 2 F wide, an open tail either end.
_RUNGS: tuple[tuple[int | None, int | None], ...] = (
    (None, 79),
    (80, 81),
    (82, 83),
    (84, 85),
    (86, None),
)
_BOUND_NS = 2_700 * 1_000_000_000


def _running_max(lower_f: int, upper_f: int, exact_f: int | None = None) -> RunningMax:
    return RunningMax(
        lower_f=lower_f,
        upper_f=upper_f,
        exact_f=exact_f,
        source_observed_at_ns=1_000,
        source_received_at_ns=2_000,
    )


def test_a_missing_running_max_refuses_observation_unavailable() -> None:
    assert (
        observation_refusal(
            None, staleness_ns=10, staleness_bound_ns=_BOUND_NS, rung_bounds=_RUNGS
        )
        == OBSERVATION_UNAVAILABLE
    )


def test_a_staleness_over_the_bound_refuses_observation_unavailable() -> None:
    running_max = _running_max(82, 83)
    assert (
        observation_refusal(
            running_max,
            staleness_ns=_BOUND_NS + 1,
            staleness_bound_ns=_BOUND_NS,
            rung_bounds=_RUNGS,
        )
        == OBSERVATION_UNAVAILABLE
    )
    # An unknown staleness (empty accumulator) is refused the same way.
    assert (
        observation_refusal(
            running_max, staleness_ns=None, staleness_bound_ns=_BOUND_NS, rung_bounds=_RUNGS
        )
        == OBSERVATION_UNAVAILABLE
    )
    # Exactly AT the bound is still fresh.
    assert (
        observation_refusal(
            running_max, staleness_ns=_BOUND_NS, staleness_bound_ns=_BOUND_NS, rung_bounds=_RUNGS
        )
        is None
    )


def test_an_interval_spanning_two_real_rungs_refuses_observation_ambiguous() -> None:
    # [83, 84] straddles (82, 83) and (84, 85): the rung cannot be resolved.
    assert (
        observation_refusal(
            _running_max(83, 84), staleness_ns=0, staleness_bound_ns=_BOUND_NS, rung_bounds=_RUNGS
        )
        == OBSERVATION_AMBIGUOUS
    )
    # [82, 83] sits inside one rung: no refusal.
    assert (
        observation_refusal(
            _running_max(82, 83), staleness_ns=0, staleness_bound_ns=_BOUND_NS, rung_bounds=_RUNGS
        )
        is None
    )


def test_unavailable_takes_precedence_over_ambiguous() -> None:
    assert (
        observation_refusal(
            _running_max(83, 84),
            staleness_ns=_BOUND_NS + 1,
            staleness_bound_ns=_BOUND_NS,
            rung_bounds=_RUNGS,
        )
        == OBSERVATION_UNAVAILABLE
    )


def test_observation_ambiguous_is_within_the_counted_set() -> None:
    """Converged item 3: Seam B adds NO reason literal; `refusals.py` is the one
    source of the two strings and `risk.py`'s counted set carries them."""
    assert OBSERVATION_AMBIGUOUS in risk_module.COUNTED_REFUSAL_REASONS
    assert OBSERVATION_UNAVAILABLE in risk_module.COUNTED_REFUSAL_REASONS
    assert OBSERVATION_AMBIGUOUS == "observation_ambiguous"
    assert OBSERVATION_UNAVAILABLE == "observation_unavailable"
