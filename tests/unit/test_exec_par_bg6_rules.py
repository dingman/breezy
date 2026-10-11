"""EXEC-PAR BG-6: the pure intraday predicates (D-PREREG r4 5, 9, 1a; r4.1 L1) and the stamp gate.

Every rule is pinned at its exact boundaries. The predicates are PURE (no I/O, no clock) so BG-4's
``--dry-eval`` can reuse them (L1).
"""

from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from fractions import Fraction

import pytest

from breezy.runtime import exec_par_intraday_rules as rules
from breezy.runtime import exec_par_stamp_gate as gate
from breezy.runtime.exec_par_records import StageEvalStamp

NS = 1_000_000_000
HOUR = 3600 * NS


# ---------------------------------------------------------------------------
# s5 Clopper-Pearson: one-sided lower bound at alpha 0.01 above 0.18, n >= 20
# ---------------------------------------------------------------------------


def test_cp_constants_are_the_spec_values() -> None:
    assert rules.CP_ALPHA == Fraction(1, 100)
    assert rules.CP_THRESHOLD == Fraction(18, 100)
    assert rules.CP_MIN_POSTED == 20


def test_cp_bound_exactly_at_the_threshold_does_not_exceed_and_just_above_does() -> None:
    # k = n = 1: the one-sided lower bound at alpha is alpha itself.
    at = Fraction(18, 100)
    assert rules.clopper_pearson_exceeds(1, 1, alpha=at, threshold=at) is False
    assert rules.clopper_pearson_exceeds(1, 1, alpha=Fraction(181, 1000), threshold=at) is True
    assert rules.clopper_pearson_exceeds(1, 1, alpha=Fraction(179, 1000), threshold=at) is False


def test_cp_exact_boundary_at_n_20_is_nine_ambiguous() -> None:
    assert rules.clopper_pearson_exceeds(8, 20) is False  # P(X>=8 | p=.18) = 0.0177 > 0.01
    assert rules.clopper_pearson_exceeds(9, 20) is True  # 0.0049 < 0.01


def test_cp_rule_needs_twenty_posted_entries() -> None:
    # 9/19 would exceed the bound, but n = 19 is below the minimum: no trip.
    assert rules.clopper_pearson_exceeds(9, 19) is True
    assert rules.cp_rule_trips(9, 19) is False
    assert rules.cp_rule_trips(9, 20) is True
    assert rules.cp_rule_trips(8, 20) is False
    assert rules.cp_rule_trips(19, 19) is False


def test_cp_zero_ambiguous_never_trips_and_all_ambiguous_trips_at_the_minimum() -> None:
    assert rules.cp_rule_trips(0, 20) is False
    assert rules.cp_rule_trips(0, 0) is False
    assert rules.cp_rule_trips(20, 20) is True


def test_cp_large_n_is_exact_and_fast() -> None:
    assert rules.cp_rule_trips(1800, 10_000) is False  # 18% observed: bound is below 0.18
    assert rules.cp_rule_trips(1900, 10_000) is True


@pytest.mark.parametrize(
    "args",
    [(-1, 20), (21, 20), (True, 20), (3, True), (3.0, 20), ("3", 20), (3, -1)],
)
def test_cp_rejects_impossible_or_non_int_counts(args: tuple[object, object]) -> None:
    with pytest.raises(rules.IntradayInputError):
        rules.cp_rule_trips(args[0], args[1])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# s5 burst: >= 5 AMBIGUOUS whose arm times fall within any 60 minutes
# ---------------------------------------------------------------------------


def test_burst_constants_are_the_spec_values() -> None:
    assert rules.BURST_MIN_AMBIGUOUS == 5
    assert rules.BURST_WINDOW_NS == 60 * 60 * NS


def test_burst_four_within_the_hour_does_not_trip_five_does() -> None:
    t0 = 10 * HOUR
    assert rules.burst_trips([t0, t0 + 1, t0 + 2, t0 + 3]) is False
    assert rules.burst_trips([t0, t0 + 1, t0 + 2, t0 + 3, t0 + 4]) is True


def test_burst_span_of_exactly_sixty_minutes_trips_and_one_ns_more_does_not() -> None:
    t0 = 10 * HOUR
    five_at_bound = [t0, t0 + 1, t0 + 2, t0 + 3, t0 + HOUR]
    assert rules.burst_trips(five_at_bound) is True
    five_over = [t0, t0 + 1, t0 + 2, t0 + 3, t0 + HOUR + 1]
    assert rules.burst_trips(five_over) is False


def test_burst_finds_a_dense_cluster_inside_a_longer_history_in_any_order() -> None:
    t0 = 100 * HOUR
    stragglers = [t0 - 50 * HOUR, t0 - 20 * HOUR, t0 + 40 * HOUR]
    cluster = [t0 + 59 * 60 * NS, t0, t0 + 10 * 60 * NS, t0 + 20 * 60 * NS, t0 + 30 * 60 * NS]
    assert rules.burst_trips([*stragglers, *cluster]) is True  # unsorted input
    spread = [t0 + i * 20 * 60 * NS for i in range(10)]  # one per 20 min: 4 in any hour + end
    assert rules.burst_trips(spread) is False
    assert rules.burst_trips([]) is False


def test_burst_threshold_and_window_are_parameters_for_the_before_freeze_adjustment() -> None:
    t0 = 10 * HOUR
    five = [t0 + i for i in range(5)]
    assert rules.burst_trips(five, min_count=6) is False
    assert rules.burst_trips([*five, t0 + 5], min_count=6) is True


@pytest.mark.parametrize("bad", [[True], [-1], [0], [1.5], ["1"]])
def test_burst_rejects_non_positive_or_non_int_arm_times(bad: list[object]) -> None:
    with pytest.raises(rules.IntradayInputError):
        rules.burst_trips(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# s9 station-day open cost 0.25 over all open positions (value-free predicate port)
# ---------------------------------------------------------------------------


class _Port:
    """Exceeds iff cost > fraction x 100 (a budget of 100); records what it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[Decimal, Decimal]] = []

    def open_cost_exceeds_budget_fraction(
        self, *, aggregate_open_cost: Decimal, fraction: Decimal
    ) -> bool:
        self.calls.append((aggregate_open_cost, fraction))
        return aggregate_open_cost > fraction * 100


def test_station_day_fraction_is_a_quarter_of_the_budget() -> None:
    assert rules.STATION_DAY_OPEN_COST_FRACTION == Decimal("0.25")


def test_station_day_boundary_at_exactly_the_fraction_and_just_above() -> None:
    port = _Port()
    at = {"NYC@2026-12-01": Decimal(25)}
    above = {"NYC@2026-12-01": Decimal("25.01")}
    assert rules.station_days_over_open_cost(port, at) == ()
    assert rules.station_days_over_open_cost(port, above) == ("NYC@2026-12-01",)
    assert all(fraction == Decimal("0.25") for _, fraction in port.calls)


def test_station_day_reports_every_exceeding_station_day_sorted() -> None:
    port = _Port()
    costs = {
        "NYC@2026-12-01": Decimal(30),
        "CHI@2026-12-01": Decimal(1),
        "AUS@2026-12-02": Decimal(26),
    }
    assert rules.station_days_over_open_cost(port, costs) == (
        "AUS@2026-12-02",
        "NYC@2026-12-01",
    )
    assert rules.station_days_over_open_cost(port, {}) == ()


def test_station_day_port_raise_or_non_bool_is_an_integrity_trip_naming_the_predicate() -> None:
    class _Raises:
        def open_cost_exceeds_budget_fraction(
            self, *, aggregate_open_cost: Decimal, fraction: Decimal
        ) -> bool:
            raise RuntimeError("budget unset 12.34")

    class _NonBool:
        def __init__(self, value: object) -> None:
            self.value = value

        def open_cost_exceeds_budget_fraction(
            self, *, aggregate_open_cost: Decimal, fraction: Decimal
        ) -> bool:
            return self.value  # type: ignore[return-value]

    costs = {"NYC@2026-12-01": Decimal(1)}
    expected = "stage_eval_fail:predicate:s9_station_day_open_cost"
    for port in (_Raises(), _NonBool(1), _NonBool(None), _NonBool("yes")):
        with pytest.raises(rules.IntradayPredicateError) as caught:
            rules.station_days_over_open_cost(port, costs)
        assert caught.value.reason == expected
        assert "12.34" not in str(caught.value)  # no value ever leaves the port


# ---------------------------------------------------------------------------
# the combined verdict (what BG-4 --dry-eval reuses)
# ---------------------------------------------------------------------------


def _inputs(
    posted: int, ambiguous: int, arms: tuple[int, ...] = (), costs: dict[str, Decimal] | None = None
) -> rules.IntradayInputs:
    return rules.IntradayInputs(
        posted=posted,
        ambiguous=ambiguous,
        ambiguous_arm_ns=arms,
        open_cost_by_station_day=costs or {},
    )


def test_stop_reasons_are_the_stage_types_constants_in_a_fixed_order() -> None:
    from breezy.runtime import exec_par_stage_types as types

    t0 = 10 * HOUR
    arms = tuple(t0 + i for i in range(5))
    costs = {"NYC@2026-12-01": Decimal(99)}
    got = rules.intraday_stop_reasons(_inputs(20, 9, arms, costs), _Port())
    assert got == (
        types.STOP_S5_CLOPPER_PEARSON,
        types.STOP_S5_BURST,
        types.STOP_S9_STATION_DAY_INTRADAY,
    )
    assert rules.intraday_stop_reasons(_inputs(20, 8), _Port()) == ()


def test_ambiguous_above_posted_is_read_conservatively_not_rejected() -> None:
    # An AMBIGUOUS mark can exist without its anchor; n is then at least the AMBIGUOUS count.
    assert rules.intraday_stop_reasons(_inputs(5, 21), _Port()) == ("s5_clopper_pearson",)


def test_every_trip_reason_is_stop_class_and_restarts_at_s1() -> None:
    from breezy.runtime import exec_par_stage_types as types

    for reason in (
        types.STOP_S5_CLOPPER_PEARSON,
        types.STOP_S5_BURST,
        types.STOP_S9_STATION_DAY_INTRADAY,
    ):
        assert reason in types.STOP_CLASS_REASONS
        assert types.STOP_OUTCOMES[reason] is types.StopOutcome.RESTART_S1


def test_rules_module_is_pure() -> None:
    tree = ast.parse(inspect.getsource(rules))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    impure = ("nautilus_trader", "breezy.adapters", "asyncio", "time", "logging", "threading")
    offenders = sorted(m for m in imported if any(m == p or m.startswith(p + ".") for p in impure))
    assert offenders == []


# ---------------------------------------------------------------------------
# counter-increase watch (ingest_fault_count, gappy_write_failures)
# ---------------------------------------------------------------------------


def test_counter_watch_trips_on_any_increase_and_is_edge_per_value() -> None:
    watch = rules.CounterIncreaseWatch()
    assert watch.increased(0) is False
    assert watch.increased(0) is False
    assert watch.increased(1) is True  # first increase
    watch.acknowledge(1)
    assert watch.increased(1) is False  # the same value never re-trips
    assert watch.increased(3) is True
    assert watch.increased(2) is True  # not acknowledged: still ahead of the seen value
    watch.acknowledge(3)
    assert watch.increased(3) is False


# ---------------------------------------------------------------------------
# the stamp gate (r4 1a boot-pass gate; E7)
# ---------------------------------------------------------------------------

BOOT = 1_000 * HOUR


def _stamp(ts_ns: int, boot_ns: int = BOOT) -> StageEvalStamp:
    return StageEvalStamp(ts_ns, boot_ns)


def _gate(stamp: StageEvalStamp | None, now_ns: int) -> str | None:
    return gate.stamp_denial(stamp, boot_ns=BOOT, now_ns=now_ns)


def test_gate_constants() -> None:
    assert gate.STAMP_MAX_AGE_NS == 26 * HOUR
    assert gate.REASON_BOOT_PENDING == "stage_eval_boot_pending"
    assert gate.REASON_STAMP_STALE == "stage_eval_stamp_stale"
    assert gate.REASON_STAMP_UNREADABLE == "stage_eval_stamp_unreadable"


def test_no_stamp_is_boot_pending_until_26_hours_after_boot_then_stale() -> None:
    assert _gate(None, BOOT + 1) == "stage_eval_boot_pending"
    assert _gate(None, BOOT + 26 * HOUR) == "stage_eval_boot_pending"  # at the bound
    assert _gate(None, BOOT + 26 * HOUR + 1) == "stage_eval_stamp_stale"  # never written


def test_a_stamp_from_a_previous_boot_never_counts() -> None:
    old = _stamp(BOOT + 10, boot_ns=BOOT - 1)
    assert _gate(old, BOOT + 20) == "stage_eval_boot_pending"
    assert _gate(old, BOOT + 26 * HOUR + 1) == "stage_eval_stamp_stale"


def test_a_stamp_older_than_this_boot_never_counts_even_with_the_right_boot_ns() -> None:
    assert _gate(_stamp(BOOT - 1), BOOT + 20) == "stage_eval_boot_pending"
    assert _gate(_stamp(BOOT), BOOT + 20) is None  # ts == boot_ns is enough (>=)


def test_a_fresh_stamp_of_this_boot_clears_the_gate() -> None:
    assert _gate(_stamp(BOOT + 5), BOOT + 10) is None


def test_stamp_age_boundary_exactly_26_hours_is_fresh_one_ns_more_is_stale() -> None:
    stamp = _stamp(BOOT + 5)
    assert _gate(stamp, BOOT + 5 + 26 * HOUR) is None
    assert _gate(stamp, BOOT + 5 + 26 * HOUR + 1) == "stage_eval_stamp_stale"


def test_stamp_in_the_future_beyond_the_skew_is_a_clock_fault_and_counts_as_stale() -> None:
    skew = gate.STAMP_FUTURE_SKEW_NS
    assert skew == 5 * NS
    now = BOOT + 100
    assert _gate(_stamp(now + skew), now) is None  # exactly at the skew
    assert _gate(_stamp(now + skew + 1), now) == "stage_eval_stamp_stale"
