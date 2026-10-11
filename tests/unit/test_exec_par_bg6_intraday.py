"""EXEC-PAR BG-6: the intraday monitor (s5 CP + burst, s9 station-day, stale stamp, M3 ordering).

Driven against the REAL ``SubmitIntentLatch`` through the BG-5b rig; a spy records the call order
of the stop-class writes and injects write failures. Every rule is pinned at its boundaries; the
stop-class write ordering (M3) reuses the BG-5b evaluator's helpers, so the same spy sees both.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.exec_par_intraday import (
    IntradayMonitor,
    IntradayPorts,
)
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    ExcludedDay,
    OrderAnchor,
    StageEvalStamp,
)
from breezy.runtime.exec_par_stage_eval import VerdictKind
from tests.unit.test_exec_par_bg5b_runner import (
    BOOT_NS,
    NS,
    Rig,
    d,
    make_rig,
    ns_of,
    verdict,
)

HOUR = 3600 * NS
SECOND_DAY = 1
FLOOR = ns_of(d(0)) + 5  # the seeded stage_reset instant (make_rig(seed=True))


class _Budget:
    """open_cost > 0.25 x 100 (a budget of 100); records every aggregate it was asked about."""

    def __init__(self) -> None:
        self.asked: list[Decimal] = []

    def open_cost_exceeds_budget_fraction(
        self, *, aggregate_open_cost: Decimal, fraction: Decimal
    ) -> bool:
        self.asked.append(aggregate_open_cost)
        return aggregate_open_cost > fraction * 100


def _ports(
    costs: Callable[[], Mapping[str, Decimal]] | None = None, port: object | None = None
) -> IntradayPorts:
    return IntradayPorts(
        open_cost_port=port if port is not None else _Budget(),  # type: ignore[arg-type]
        open_cost_by_station_day=costs if costs is not None else dict,
    )


def _monitor(rig: Rig, intraday: IntradayPorts | None | str = "default") -> IntradayMonitor:
    ports = rig.ports
    return IntradayMonitor(
        reads=ports.store,
        counters=ports.counters,
        governed=ports.governed,
        boot_ns=ports.boot_ns,
        intraday=_ports() if intraday == "default" else intraday,  # type: ignore[arg-type]
        stop=rig.ev.stop_class,
        integrity=rig.ev.integrity_halt,
    )


def _fresh_stamp(rig: Rig) -> None:
    rig.latch.write_stage_eval_stamp(StageEvalStamp(rig.clock.ns, BOOT_NS))


_SEQ = [0]


def _sub(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _post(rig: Rig, arm_ns: int, *, ambiguous: bool = False, station: str = "NYC") -> None:
    """One posted entry (an anchor) and, if ``ambiguous``, its AMBIGUOUS mark, on its entry_day."""
    _SEQ[0] += 1
    n = _SEQ[0]
    day = rig.ports.governed.entry_day(station, arm_ns)
    rig.latch.write_order_anchor(
        OrderAnchor(
            client_order_id=f"coid-{n}",
            slug=f"slug-{n}",
            day=day,
            arm_ns=arm_ns,
            decision_ask="0.40",
            qty="1",
            notional="0.40",
            window_start_ns=arm_ns - arm_ns % NS,
            attribution="event_time",
            station=station,
        )
    )
    if ambiguous:
        rig.latch.write_ambiguous(
            AmbiguousRow(
                intent_id=f"intent-{n}",
                source="armed_post_boot",
                day=day,
                arm_ns=arm_ns,
                attribution="slot",
                ts_ns=arm_ns,
                station=station,
            )
        )


def _spread(rig: Rig, count: int, ambiguous: int, *, start: int | None = None) -> None:
    """``count`` posted entries 2 h apart (never a burst); the first ``ambiguous`` are AMBIGUOUS."""
    first = ns_of(d(1)) if start is None else start
    for i in range(count):
        _post(rig, first + i * 2 * HOUR + 1, ambiguous=i < ambiguous)


def _ready(rig: Rig) -> IntradayMonitor:
    _fresh_stamp(rig)
    return _monitor(rig)


# ---------------------------------------------------------------------------
# s5 Clopper-Pearson at the monitor: n = 19 vs 20; 8 vs 9 AMBIGUOUS
# ---------------------------------------------------------------------------


def test_cp_does_not_trip_at_19_posted_even_with_9_ambiguous(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _spread(rig, 19, 9)
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == [] and rig.breaker() is None


def test_cp_trips_at_20_posted_with_9_ambiguous_and_not_with_8(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _spread(rig, 20, 8)
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == [] and rig.breaker() is None
    with make_rig(_sub(tmp_path, "b"), seed=True) as rig:
        _spread(rig, 20, 9)
        _ready(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_clopper_pearson"


def test_cp_counts_open_days_immediately(tmp_path: Path) -> None:
    """BG-5c N-C: the entries are on TODAY (an open day); the first check sees them."""
    with make_rig(tmp_path, seed=True, now=ns_of(d(4)) + 12 * HOUR) as rig:
        assert rig.ports.governed.today(rig.clock.ns) == d(4)
        for i in range(20):  # 20 min apart: never five inside an hour
            _post(rig, ns_of(d(4)) + i * 20 * 60 * NS + 1, ambiguous=i < 9)
        _ready(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_clopper_pearson"


# ---------------------------------------------------------------------------
# s5 burst: 4 vs 5 inside 60 min, 60 min vs 60 min + 1 ns, by ARM time
# ---------------------------------------------------------------------------


def _burst(rig: Rig, arms: list[int]) -> None:
    for arm in arms:
        _post(rig, arm, ambiguous=True)


def test_burst_four_within_an_hour_does_not_trip(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(4)])
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == []


def test_burst_five_within_an_hour_trips_and_names_the_rule(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        _ready(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"


def test_burst_window_boundary_is_60_minutes_inclusive(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0, t0 + 1, t0 + 2, t0 + 3, t0 + HOUR])
        _ready(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"
    with make_rig(_sub(tmp_path, "b"), seed=True) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0, t0 + 1, t0 + 2, t0 + 3, t0 + HOUR + 1])
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == [] and rig.breaker() is None


def test_burst_is_by_arm_time_not_by_the_time_the_mark_was_ingested(tmp_path: Path) -> None:
    """Five marks ingested days apart still burst if their ARM times are inside one hour."""
    with make_rig(tmp_path, seed=True) as rig:
        t0 = ns_of(d(1))
        for i in range(5):
            _post(rig, t0 + i, ambiguous=False)
            rig.latch.write_ambiguous(
                AmbiguousRow(
                    intent_id=f"late-{i}",
                    source="armed_pre_boot",
                    day=d(1),
                    arm_ns=t0 + i,
                    attribution="slot",
                    ts_ns=ns_of(d(3)) + i * HOUR,  # ingested hours apart, far from arm
                    station="NYC",
                )
            )
        _ready(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"


def test_burst_straddling_a_day_label_boundary_is_found(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        edge = ns_of(d(2))
        _burst(rig, [edge - 2, edge - 1, edge, edge + 1, edge + 2])  # two labels, one hour
        _ready(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"


# ---------------------------------------------------------------------------
# window attribution: the stage floor, excluded days
# ---------------------------------------------------------------------------


def test_floor_boundary_an_entry_armed_exactly_at_the_floor_counts_one_ns_before_does_not(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        # four at/after the floor + one a nanosecond BEFORE it: only four count
        _burst(rig, [FLOOR - 1, FLOOR, FLOOR + 1, FLOOR + 2, FLOOR + 3])
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == [], "the pre-floor entry must not complete a burst"
    with make_rig(_sub(tmp_path, "b"), seed=True) as rig:
        _burst(rig, [FLOOR, FLOOR + 1, FLOOR + 2, FLOOR + 3, FLOOR + 4])
        _ready(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"


def test_pre_floor_entries_do_not_count_toward_the_cp_posted_total(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        for i in range(5):  # armed before the floor (FLOOR = d0 + 5 ns), same label: excluded
            _post(rig, ns_of(d(0)) + i, ambiguous=False)
        _spread(rig, 19, 9)  # post-floor posted = 19 < 20
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == []


def test_excluded_days_are_skipped(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        assert rig.latch.add_excluded_day(ExcludedDay(d(2), "test", rig.clock.ns))
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == []


# ---------------------------------------------------------------------------
# s9 station-day: 0.25 of the budget over ALL open positions
# ---------------------------------------------------------------------------


def test_station_day_boundary_at_25_does_not_trip_above_does(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _fresh_stamp(rig)
        _monitor(rig, _ports(lambda: {"NYC@2026-12-05": Decimal(25)})).check(rig.clock.ns)
        assert rig.spy.calls == []
    with make_rig(_sub(tmp_path, "b"), seed=True) as rig:
        _fresh_stamp(rig)
        _monitor(rig, _ports(lambda: {"NYC@2026-12-05": Decimal("25.01")})).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s9_station_day_open_cost"


def test_station_day_counts_positions_regardless_of_arm_time_or_floor(tmp_path: Path) -> None:
    """The provider is asked with no floor/arm filter, and a pre-floor station-day still trips."""
    with make_rig(tmp_path, seed=True) as rig:
        _fresh_stamp(rig)
        asked: list[int] = []

        def costs() -> Mapping[str, Decimal]:
            asked.append(1)
            return {f"NYC@{d(0)}": Decimal(99)}  # the floor's own (pre-floor) label

        _monitor(rig, _ports(costs)).check(rig.clock.ns)
        assert asked == [1]
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s9_station_day_open_cost"


def test_predicate_raise_and_non_bool_are_integrity_trips_naming_the_predicate(
    tmp_path: Path,
) -> None:
    class _Raises:
        def open_cost_exceeds_budget_fraction(
            self, *, aggregate_open_cost: Decimal, fraction: Decimal
        ) -> bool:
            raise RuntimeError("budget unset")

    class _NonBool:
        def open_cost_exceeds_budget_fraction(
            self, *, aggregate_open_cost: Decimal, fraction: Decimal
        ) -> bool:
            return 1  # type: ignore[return-value]

    for n, port in enumerate((_Raises(), _NonBool())):
        with make_rig(_sub(tmp_path, str(n)), seed=True) as rig:
            _fresh_stamp(rig)
            _monitor(rig, _ports(lambda: {"NYC@2026-12-05": Decimal(1)}, port)).check(rig.clock.ns)
            record = rig.breaker()
            assert record is not None
            assert record.halted_reason == "stage_eval_fail:predicate:s9_station_day_open_cost"
            assert "write_force_k1_flag" not in rig.spy.calls  # integrity class: no flag
            assert "write_stop_verdict" not in rig.spy.calls  # and no stop marker


# ---------------------------------------------------------------------------
# stop-class write ordering (M3): marker, halt, flag
# ---------------------------------------------------------------------------


def _trip_burst(rig: Rig) -> IntradayMonitor:
    t0 = ns_of(d(2))
    _burst(rig, [t0 + i for i in range(5)])
    return _ready(rig)


def test_m3_ordering_marker_then_halt_then_flag_all_carry_the_reason(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _trip_burst(rig).check(rig.clock.ns)
        assert rig.spy.calls == ["write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"]
        (marker,) = rig.latch.read_stop_verdicts_since(0)
        assert marker.reason == "s5_burst" and marker.ts_ns == rig.clock.ns
        flag = rig.latch.read_force_k1_flag()
        assert flag.kind.value == "set" and flag.record is not None
        assert flag.record.reason == "s5_burst" and flag.record.set_by == "stage_eval"
        assert rig.halts == [("s5_burst", rig.clock.ns)]
        assert rig.ev.heartbeat_ok
        assert [a[1] for a in rig.alerts] == ["EXEC_PAR_STAGE_STOP"]


def test_m3_marker_write_failure_is_stop_marker_write_fail_and_stops_the_heartbeat(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        rig.spy.fail.add("write_stop_verdict")
        _trip_burst(rig).check(rig.clock.ns)
        # the marker was attempted FIRST; the halt and the flag still follow (fail closed)
        assert rig.spy.calls == ["write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"]
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stop_marker_write_fail"
        assert rig.latch.read_stop_verdicts_since(0) == ()
        assert not rig.ev.heartbeat_ok
        assert "EXEC_PAR_STAGE_INTEGRITY_HALT" in [a[1] for a in rig.alerts]


@pytest.mark.asyncio
async def test_d3_halt_write_raise_stops_the_heartbeat_but_the_flag_is_still_written(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, seed=True, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:
        rig.spy.fail.add("write_breaker_halt")
        _trip_burst(rig).check(rig.clock.ns)
        assert rig.spy.calls == ["write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"]
        assert rig.breaker() is None  # the halt did not latch
        assert not rig.ev.heartbeat_ok  # D3: heartbeat withheld
        assert rig.latch.read_force_k1_flag().kind.value == "set"
        assert len(rig.latch.read_stop_verdicts_since(0)) == 1
        # the pending halt is retried on the next service and the heartbeat resumes
        rig.spy.fail.clear()
        await rig.run_pass(rig.clock.ns + NS)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"
        assert rig.ev.heartbeat_ok


def test_flag_write_failure_marks_the_breaker_record_and_keeps_the_halt(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        rig.spy.fail.add("write_force_k1_flag")
        _trip_burst(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"
        assert record.flag_write_failed is True
        assert "EXEC_PAR_FORCE_K1_FLAG_WRITE_FAILED" in [a[1] for a in rig.alerts]


def test_a_standing_condition_is_acted_on_once_not_every_tick(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        monitor = _trip_burst(rig)
        monitor.check(rig.clock.ns)
        before = list(rig.spy.calls)
        for i in range(1, 5):
            monitor.check(rig.clock.ns + i * 5 * NS)
        assert rig.spy.calls == before
        assert len(rig.latch.read_stop_verdicts_since(0)) == 1


def test_two_rules_at_once_are_acted_on_one_per_tick_and_the_first_halt_reason_sticks(
    tmp_path: Path,
) -> None:
    """Markers are keyed by ts_ns, so one new stop reason is acted on per check (never lost)."""
    with make_rig(tmp_path, seed=True) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        _fresh_stamp(rig)
        monitor = _monitor(rig, _ports(lambda: {"NYC@2026-12-05": Decimal(99)}))
        monitor.check(rig.clock.ns)
        assert [m.reason for m in rig.latch.read_stop_verdicts_since(0)] == ["s5_burst"]
        monitor.check(rig.clock.ns + 5 * NS)
        assert [m.reason for m in rig.latch.read_stop_verdicts_since(0)] == [
            "s5_burst",
            "s9_station_day_open_cost",
        ]
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"  # sticky, fixed order
        assert rig.ev.heartbeat_ok
        before = list(rig.spy.calls)
        monitor.check(rig.clock.ns + 10 * NS)  # both acted on: nothing more is written
        assert rig.spy.calls == before


# ---------------------------------------------------------------------------
# stamp: stale or never written is an integrity trip; boot-pending is not a halt
# ---------------------------------------------------------------------------


def test_boot_pending_is_an_entry_denial_not_a_halt(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        # boot 1 h ago, no stamp yet
        monitor = IntradayMonitor(
            reads=rig.ports.store,
            counters=rig.ports.counters,
            governed=rig.ports.governed,
            boot_ns=rig.clock.ns - HOUR,
            intraday=_ports(),
            stop=rig.ev.stop_class,
            integrity=rig.ev.integrity_halt,
        )
        monitor.check(rig.clock.ns)
        assert rig.spy.calls == [] and rig.breaker() is None


def test_never_written_stamp_halts_once_the_boot_is_older_than_26_hours(tmp_path: Path) -> None:
    for n, (age, halted) in enumerate(((26 * HOUR, False), (26 * HOUR + 1, True))):
        with make_rig(_sub(tmp_path, str(n)), seed=True) as rig:
            monitor = IntradayMonitor(
                reads=rig.ports.store,
                counters=rig.ports.counters,
                governed=rig.ports.governed,
                boot_ns=rig.clock.ns - age,
                intraday=_ports(),
                stop=rig.ev.stop_class,
                integrity=rig.ev.integrity_halt,
            )
            monitor.check(rig.clock.ns)
            record = rig.breaker()
            assert (record is not None) is halted
            if record is not None:
                assert record.halted_reason == "stage_eval_stamp_stale"
                assert "write_force_k1_flag" not in rig.spy.calls  # integrity: no flag
                assert "write_stop_verdict" not in rig.spy.calls


def test_stamp_age_boundary_26_hours_is_fresh_one_ns_more_halts(tmp_path: Path) -> None:
    for n, (age, halted) in enumerate(((26 * HOUR, False), (26 * HOUR + 1, True))):
        with make_rig(_sub(tmp_path, str(n)), seed=True) as rig:
            rig.latch.write_stage_eval_stamp(StageEvalStamp(rig.clock.ns - age, BOOT_NS))
            _monitor(rig).check(rig.clock.ns)
            assert (rig.breaker() is not None) is halted
            if halted:
                assert rig.halts == [("stage_eval_stamp_stale", rig.clock.ns)]


def test_unreadable_stamp_row_halts_fail_closed(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        rig.store.data["exec/polymarket_us/exec_par/stage_eval/stamp"] = b"{garbled"
        _monitor(rig).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_stamp_unreadable"


# ---------------------------------------------------------------------------
# fail-closed wiring and reads
# ---------------------------------------------------------------------------


def test_unbound_intraday_ports_fail_closed_with_a_named_integrity_halt(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _fresh_stamp(rig)
        _monitor(rig, None).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_fail:intraday_unbound"


def test_a_failing_read_is_an_integrity_halt_naming_only_the_exception_type(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _fresh_stamp(rig)

        def boom() -> Mapping[str, Decimal]:
            raise KeyError("secret 12.34")

        _monitor(rig, _ports(boom)).check(rig.clock.ns)
        record = rig.breaker()
        assert record is not None
        assert record.halted_reason == "stage_eval_fail:intraday_read:KeyError"
        assert "12.34" not in (record.halted_reason or "")


def test_check_never_raises_even_when_every_write_and_read_fails(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        rig.spy.fail.update({"write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"})
        rig.spy.fail.add("mark_flag_write_failed")
        monitor = _trip_burst(rig)
        monitor.check(rig.clock.ns)
        assert not rig.ev.heartbeat_ok


@pytest.mark.parametrize("posted", [0, 1])
def test_empty_window_never_trips(tmp_path: Path, posted: int) -> None:
    with make_rig(_sub(tmp_path, str(posted)), seed=True) as rig:
        _spread(rig, posted, 0)
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == []
