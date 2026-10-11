"""EXEC-PAR BG-6 review fixes: unattributed marks, count integrity, duplicate-stop safety,
closed-day scan cache, marker timestamp collisions, check wrapping, edge re-fire after a reset."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from breezy.runtime.exec_par_counter_ingest import UNATTRIBUTED
from breezy.runtime.exec_par_intraday import IntradayMonitor
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    DayCountsDelta,
    StageReset,
    StopVerdict,
)
from tests.unit.test_exec_par_bg5b_runner import NS, Rig, d, make_rig, ns_of
from tests.unit.test_exec_par_bg6_intraday import (
    FLOOR,
    HOUR,
    _burst,
    _fresh_stamp,
    _ports,
    _post,
    _ready,
    _spread,
    _sub,
    _trip_burst,
)


def _unattributed(rig: Rig, arm_ns: int, n: int) -> None:
    rig.latch.write_ambiguous(
        AmbiguousRow(
            intent_id=f"unk-{n}",
            source="unknown",
            day=UNATTRIBUTED,
            arm_ns=arm_ns,
            attribution=UNATTRIBUTED,
            ts_ns=arm_ns,
            station=UNATTRIBUTED,
        )
    )


def _halt_reason(rig: Rig) -> str | None:
    record = rig.breaker()
    return None if record is None else record.halted_reason


# -- 1. unattributed AMBIGUOUS marks ------------------------------------------------------


def test_unattributed_marks_after_the_floor_count_in_the_burst(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        for i in range(5):
            _unattributed(rig, FLOOR + 10 + i, i)
        _ready(rig).check(rig.clock.ns)
        assert _halt_reason(rig) == "s5_burst"


def test_unattributed_mark_before_the_floor_does_not_count(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        for i in range(4):
            _unattributed(rig, FLOOR + 10 + i, i)
        _unattributed(rig, FLOOR - 1, 9)  # pre-floor: the fifth does not exist
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == []


def test_unattributed_marks_count_in_the_cp_numerator(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _spread(rig, 20, 0)
        for i in range(9):  # 2 h apart: never a burst
            _unattributed(rig, ns_of(d(1)) + 100 + i * 2 * HOUR, i)
        _ready(rig).check(rig.clock.ns)
        assert _halt_reason(rig) == "s5_clopper_pearson"


def test_unattributed_mark_with_no_usable_arm_time_is_an_integrity_halt(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _fresh_stamp(rig)
        store = rig.ports.store

        class _Reads:
            def __getattr__(self, name: str) -> Any:
                return getattr(store, name)

            def read_ambiguous(self, day: str) -> tuple[object, ...]:
                if day == UNATTRIBUTED:
                    return (AmbiguousRow("u", "unknown", UNATTRIBUTED, 0, UNATTRIBUTED, 0, "x"),)
                return store.read_ambiguous(day)

        monitor = IntradayMonitor(
            reads=cast("Any", _Reads()),
            counters=rig.ports.counters,
            governed=rig.ports.governed,
            boot_ns=rig.ports.boot_ns,
            intraday=_ports(),
            stop=rig.ev.stop_class,
            integrity=rig.ev.integrity_halt,
        )
        monitor.check(rig.clock.ns)
        assert _halt_reason(rig) == "ambiguous_unattributable"
        assert "write_force_k1_flag" not in rig.spy.calls


# -- 2. AMBIGUOUS above posted ----------------------------------------------------------


def test_ambiguous_above_posted_keeps_the_conservative_trip_and_names_the_day(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        t0 = ns_of(d(2))
        for i in range(5):  # five AMBIGUOUS rows, no anchors at all
            rig.latch.write_ambiguous(
                AmbiguousRow(f"i{i}", "armed_post_boot", d(2), t0 + i, "slot", t0 + i, "NYC")
            )
        _ready(rig).check(rig.clock.ns)
        assert _halt_reason(rig) == "s5_burst"  # the trip is kept
        details = [a[2] for a in rig.alerts if a[1] == "EXEC_PAR_STAGE_INTEGRITY_HALT"]
        assert any(f"ambiguous_exceeds_posted:{d(2)}" in x for x in details)


# -- 3. a still-true stop does not re-fire after an evaluator error ----------------------


def test_a_failed_tick_does_not_make_a_standing_stop_fire_twice(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _trip_burst(rig)
        store = rig.ports.store
        broken = {"on": False}

        class _Reads:
            def __getattr__(self, name: str) -> Any:
                return getattr(store, name)

            def read_stage_reset(self) -> object:
                if broken["on"]:
                    raise RuntimeError("boom")
                return store.read_stage_reset()

        monitor = IntradayMonitor(
            reads=cast("Any", _Reads()),
            counters=rig.ports.counters,
            governed=rig.ports.governed,
            boot_ns=rig.ports.boot_ns,
            intraday=_ports(),
            stop=rig.ev.stop_class,
            integrity=rig.ev.integrity_halt,
        )
        monitor.check(rig.clock.ns)
        broken["on"] = True
        monitor.check(rig.clock.ns + 5 * NS)  # the evaluation raises
        broken["on"] = False
        monitor.check(rig.clock.ns + 10 * NS)
        assert len(rig.latch.read_stop_verdicts_since(0)) == 1
        assert rig.spy.calls.count("write_force_k1_flag") == 1
        assert [a[1] for a in rig.alerts].count("EXEC_PAR_STAGE_STOP") == 1


# -- 4. the closed-day scan cache ----------------------------------------------------------


class _Counting:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: dict[str, int] = {}

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.calls[name] = self.calls.get(name, 0) + 1
            return attr(*args, **kwargs)

        return wrapper


def _second_check_scans(tmp_path: Path, today_index: int) -> tuple[int, int, int]:
    with make_rig(tmp_path, seed=True, now=ns_of(d(today_index)) + 100) as rig:
        _fresh_stamp(rig)
        reads, counters = _Counting(rig.ports.store), _Counting(rig.ports.counters)
        monitor = IntradayMonitor(
            reads=reads,
            counters=counters,
            governed=rig.ports.governed,
            boot_ns=rig.ports.boot_ns,
            intraday=_ports(),
            stop=rig.ev.stop_class,
            integrity=rig.ev.integrity_halt,
        )
        monitor.check(rig.clock.ns)
        reads.calls.clear()
        counters.calls.clear()
        monitor.check(rig.clock.ns + 5 * NS)
        return (
            counters.calls.get("read_day_counts", 0),
            reads.calls.get("read_ambiguous", 0),
            reads.calls.get("read_order_anchors", 0),
        )


def test_the_per_tick_scan_does_not_grow_with_the_stage(tmp_path: Path) -> None:
    short = _second_check_scans(_sub(tmp_path, "a"), 4)
    long = _second_check_scans(_sub(tmp_path, "b"), 12)
    assert short == long
    assert short[0] <= 1 and short[1] <= 2  # the open day (+ the unattributed marks)


def test_closed_days_are_rescanned_only_after_an_invalidation(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        monitor = _ready(rig)
        monitor.check(rig.clock.ns)  # populate the closed-day cache
        _burst(rig, [ns_of(d(2)) + i for i in range(5)])  # a late write on a closed day
        monitor.check(rig.clock.ns + 5 * NS)
        assert rig.spy.calls == []  # still the cached scan
        monitor.invalidate([d(2)])
        monitor.check(rig.clock.ns + 10 * NS)
        assert _halt_reason(rig) == "s5_burst"


# -- 5. counts versus rows (a BG-1d rebuild restores counts, not rows) -----------------------


def _rebuilt_day(rig: Rig, rows: int, delta: int, *, spacing: int = 2 * HOUR) -> None:
    """Five posted entries on d1, ``rows`` of them AMBIGUOUS (spread out), plus a rebuild delta."""
    for i in range(5):
        _post(rig, ns_of(d(1)) + 5 + i * spacing, ambiguous=i < rows)
    rig.latch.write_counts_delta(DayCountsDelta(d(1), 0, delta, 0, "0"))


def test_rows_plus_the_rebuild_delta_matching_the_counts_is_no_halt(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _rebuilt_day(rig, rows=3, delta=1)  # effective 4 < 5: the burst cannot trip
        _ready(rig).check(rig.clock.ns)
        assert rig.spy.calls == [] and rig.breaker() is None


def test_a_rebuilt_day_with_five_effective_and_missing_arm_times_is_burst_incomplete(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _rebuilt_day(rig, rows=4, delta=1)  # effective 5, the 4 rows are 2 h apart
        _ready(rig).check(rig.clock.ns)
        assert _halt_reason(rig) == f"burst_incomplete_rebuilt_day:{d(1)}"
        assert "write_force_k1_flag" not in rig.spy.calls  # integrity class: no flag


def test_burst_incomplete_is_silent_when_the_available_rows_already_trip(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        _rebuilt_day(rig, rows=5, delta=1, spacing=1)  # five rows inside one hour + delta
        _ready(rig).check(rig.clock.ns)
        assert _halt_reason(rig) == "s5_burst"
        details = [a[2] for a in rig.alerts if a[1] == "EXEC_PAR_STAGE_INTEGRITY_HALT"]
        assert not any("burst_incomplete" in x or "rows_mismatch" in x for x in details)


def test_the_rebuilt_days_effective_count_feeds_the_cp_numerator(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        for i in range(20):  # 20 posted, 2 h apart; 8 AMBIGUOUS rows + a delta of 1 = 9
            _post(rig, ns_of(d(1)) + 5 + i * 2 * HOUR, ambiguous=i < 8)
        rig.latch.write_counts_delta(DayCountsDelta(d(1), 0, 1, 0, "0"))
        _ready(rig).check(rig.clock.ns)
        assert _halt_reason(rig) == "s5_clopper_pearson"


def test_a_mismatch_the_delta_does_not_explain_still_halts(tmp_path: Path) -> None:
    from dataclasses import replace

    with make_rig(tmp_path, seed=True) as rig:
        for i in range(3):
            _post(rig, ns_of(d(1)) + 5 + i * 2 * HOUR, ambiguous=i < 1)
        _fresh_stamp(rig)
        inner = rig.ports.counters

        class _Counters:
            def __getattr__(self, name: str) -> Any:
                return getattr(inner, name)

            def read_day_counts(self, day: str) -> Any:
                counts = inner.read_day_counts(day)
                assert counts is not None
                return replace(counts, ambiguous=counts.ambiguous + 1)  # no delta behind it

        monitor = IntradayMonitor(
            reads=rig.ports.store,
            counters=cast("Any", _Counters()),
            governed=rig.ports.governed,
            boot_ns=rig.ports.boot_ns,
            intraday=_ports(),
            stop=rig.ev.stop_class,
            integrity=rig.ev.integrity_halt,
        )
        monitor.check(rig.clock.ns)
        assert _halt_reason(rig) == f"ambiguous_rows_mismatch:{d(1)}"


# -- 6. marker timestamp collision ---------------------------------------------------------


def test_a_marker_timestamp_collision_bumps_by_one_nanosecond(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        now = rig.clock.ns
        rig.latch.write_stop_verdict(StopVerdict("other", now))
        assert rig.ev.stop_class("s5_burst", now) is True
        rows = rig.latch.read_stop_verdicts_since(0)
        assert [(r.reason, r.ts_ns) for r in rows] == [("other", now), ("s5_burst", now + 1)]


def test_three_collisions_in_a_row_are_a_marker_failure(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        now = rig.clock.ns
        for i in range(3):
            rig.latch.write_stop_verdict(StopVerdict("other", now + i))
        assert rig.ev.stop_class("s5_burst", now) is False
        assert _halt_reason(rig) == "stop_marker_write_fail"
        assert not rig.ev.heartbeat_ok


# -- 7. the acting calls are wrapped -----------------------------------------------------


def test_a_raising_stop_or_integrity_call_becomes_intraday_check_raised(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        seen: list[str] = []

        def bad_stop(reason: str, ts: int) -> bool:
            raise RuntimeError("stop broke")

        def integrity(reason: str) -> None:
            seen.append(reason)

        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        _fresh_stamp(rig)
        monitor = IntradayMonitor(
            reads=rig.ports.store,
            counters=rig.ports.counters,
            governed=rig.ports.governed,
            boot_ns=rig.ports.boot_ns,
            intraday=_ports(),
            stop=bad_stop,
            integrity=integrity,
        )
        monitor.check(rig.clock.ns)  # must not raise
        assert seen == ["intraday_check_raised"]


# -- 8. a stage reset re-arms the edge -----------------------------------------------------


def test_a_still_true_stop_fires_again_after_a_stage_reset(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        monitor = _trip_burst(rig)
        monitor.check(rig.clock.ns)
        assert len(rig.latch.read_stop_verdicts_since(0)) == 1
        rig.latch.write_stage_reset(StageReset(ns_of(d(1)), "stop_clear", None))
        monitor.check(rig.clock.ns + 5 * NS)  # the burst (d2) is after the new floor: still true
        assert len(rig.latch.read_stop_verdicts_since(0)) == 2
