"""EXEC-PAR BG-5c WP-C review fixes (two READY-88 reviews): ahead-tail, emptiness, stub P&L,
force-then-alert ordering and a single `through` label per pass."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import exec_par_stage_runner as runner
from breezy.runtime import exec_par_stage_snapshot as snapshot_mod
from breezy.runtime.exec_par_day_convention import enforce_day_convention_at_boot
from breezy.runtime.exec_par_reconcile import DayCounts
from breezy.runtime.exec_par_records import AmbiguousRow, DenialRow, OpenCostFlag, WindowPeak
from breezy.runtime.exec_par_stage_eval import DayPnl, VerdictKind, evaluate_stage
from breezy.runtime.exec_par_stage_snapshot import build_stage_snapshot
from tests.unit.test_exec_par_bg5b_runner import make_rig
from tests.unit.test_exec_par_bg5c_day_convention import _FakeLatch, _Sink
from tests.unit.test_exec_par_bg5c_floor_stub_open_days import (
    FLOOR_LABELS,
    GOV,
    NS,
    D,
    anchor,
    build,
    floor_day_reads,
    inputs,
    label,
    ns_utc,
    reading,
)

# -- 1: the ahead tail -----


def ambiguous_at(day: str, hour: int = 12) -> AmbiguousRow:
    arm = ns_utc(int(day[5:7]), int(day[8:10]), hour)
    return AmbiguousRow("ghost", "armed_post_boot", day, arm, "slot", arm, "EAST")


def test_an_anchorless_ambiguous_mark_within_the_allowance_is_read_as_open_data() -> None:
    reads, counter_reads = floor_day_reads()
    day = label(10, 21)  # two days after today: legal open data
    reads.ambiguous[day] = (ambiguous_at(day),)
    counter_reads.counts[day] = DayCounts(0, 1, 0, D(0))
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    row = {x.day: x for x in snap.days}[day]
    assert row.ambiguous == 1


def test_a_denial_only_day_within_the_allowance_is_read() -> None:
    reads, counter_reads = floor_day_reads()
    day = label(10, 21)
    arm = ns_utc(10, 21, 12)
    reads.denials[day] = (DenialRow("d1", "k-full", day, arm, "EAST"),)
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    assert day in {x.day for x in snap.days}


def test_an_anchorless_ambiguous_mark_beyond_the_allowance_is_counter_missing() -> None:
    reads, counter_reads = floor_day_reads()
    day = label(10, 22)  # three days after today
    reads.ambiguous[day] = (ambiguous_at(day),)
    verdict = evaluate_stage(build_stage_snapshot(reads, counter_reads, inputs()))
    assert verdict.kind is VerdictKind.FAIL
    assert verdict.reason == "stage_eval_fail:counter_missing"


def test_an_entry_ten_days_ahead_fails_closed_without_a_day_loop() -> None:
    reads, counter_reads = floor_day_reads()
    day = label(10, 29)  # ten days after today: beyond any bounded day probe
    reads.anchors[day] = (anchor("far", day, ns_utc(10, 29, 12), "EAST"),)
    verdict = evaluate_stage(build_stage_snapshot(reads, counter_reads, inputs()))
    assert verdict.kind is VerdictKind.FAIL
    assert verdict.reason == "stage_eval_fail:counter_missing"


def test_the_latch_reports_the_latest_entry_day_from_key_prefixes(tmp_path: Path) -> None:
    from breezy.runtime.exec_par_records import AmbiguousRow as Row
    from breezy.runtime.submit_intent import open_submit_intent_latch

    class Store:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def get(self, key: str) -> bytes | None:
            return self.data.get(key)

        def set(self, key: str, value: bytes) -> None:
            self.data[key] = value

        def keys_with_prefix(self, prefix: str) -> list[str]:
            return sorted(k for k in self.data if k.startswith(prefix))

        def delete(self, key: str) -> bool:
            return self.data.pop(key, None) is not None

    with open_submit_intent_latch(
        Store(), tmp_path / "s.db", max_slots=2, v2_predicate=lambda: True, clock_ns=lambda: 1
    ) as latch:
        assert latch.read_latest_entry_day() is None
        latch.write_ambiguous(Row("a", "armed_post_boot", "2026-10-21", 5, "slot", 6, "EAST"))
        latch.write_denial(DenialRow("d", "k-full", "2026-10-25", 5, "EAST"))
        latch.write_order_anchor(anchor("o", "2026-10-23", 5, "EAST"))
        assert latch.read_latest_entry_day() == "2026-10-25"


# -- 2: emptiness -----


def _floor_snapshot_without_stub(**changes: Any) -> Any:
    snap = build(stubs={}, whole_posted={FLOOR_LABELS[0]: 0, FLOOR_LABELS[1]: 0})
    days = tuple(
        dataclasses.replace(x, **changes) if x.day == FLOOR_LABELS[0] else x for x in snap.days
    )
    return dataclasses.replace(snap, days=days)


@pytest.mark.parametrize(
    "changes",
    [
        {"denied_counted": 2},
        {"open_flags": (OpenCostFlag("EAST@x", FLOOR_LABELS[0], True, 1),)},
        {"windows": (WindowPeak(FLOOR_LABELS[0], 1, 1, "9", "c"),)},
    ],
    ids=["denials", "open_flags", "windows"],
)
def test_a_floor_day_with_only_denials_flags_or_windows_is_not_empty(changes: Any) -> None:
    verdict = evaluate_stage(_floor_snapshot_without_stub(**changes))
    assert verdict.kind is VerdictKind.FAIL
    assert verdict.reason == "stage_eval_fail:pre_floor_unknown"


def test_a_truly_empty_floor_day_is_still_an_empty_stub() -> None:
    verdict = evaluate_stage(_floor_snapshot_without_stub())
    assert verdict.kind is not VerdictKind.FAIL, verdict.reason


# -- 3: stub P&L rows -----


def test_a_floor_stub_with_fills_and_no_stub_pnl_row_fails_closed() -> None:
    verdict = evaluate_stage(build(floor_stub_pnl=()))
    assert verdict.kind is VerdictKind.FAIL
    assert verdict.reason == "stage_eval_fail:settled_pnl_missing"


def test_a_floor_stub_with_an_ambiguous_mark_and_no_stub_pnl_row_fails_closed() -> None:
    snap = build(floor_stub_pnl=())
    stub = dataclasses.replace(snap.floor_stubs[0], ambiguous=1, fills=())
    stubs = (stub, *snap.floor_stubs[1:])
    only_first = dataclasses.replace(
        snap,
        floor_stubs=(
            stub,
            dataclasses.replace(snap.floor_stubs[1], fills=(), posted=0, windows=()),
        ),
    )
    assert stubs
    assert evaluate_stage(only_first).reason == "stage_eval_fail:settled_pnl_missing"


def test_a_stub_pnl_row_replaces_the_whole_day_row_for_the_day_and_stage_stops() -> None:
    # the whole-day row carries a pre-floor loss; the stub row is post-floor only
    calm = build(pnl_over={FLOOR_LABELS[0]: "-0.5", FLOOR_LABELS[1]: "-0.5"})
    assert evaluate_stage(calm).kind not in (VerdictKind.STOP, VerdictKind.FAIL)
    bad_stub = tuple(DayPnl(x.day, reading("-0.2")) for x in calm.floor_stub_pnl)
    tripped = evaluate_stage(dataclasses.replace(calm, floor_stub_pnl=bad_stub))
    assert tripped.kind is VerdictKind.STOP and "s15_day" in tripped.stops


# -- 4: force-then-alert -----


class _ForceFails(_FakeLatch):
    def force_k1(self, reason: str) -> None:
        raise RuntimeError("force failed")


def test_a_failing_force_still_alerts_and_the_original_read_error_surfaces() -> None:
    latch, sink = _ForceFails(slots=2, read_raises=True), _Sink()
    with pytest.raises(OSError, match="read"):
        enforce_day_convention_at_boot(latch, alert_sink=sink)
    assert [p.severity for p in sink.events] == ["CRITICAL"]


def test_a_failing_force_on_a_mismatch_alerts_then_raises_the_force_error() -> None:
    latch, sink = _ForceFails(slots=2, row=1), _Sink()
    with pytest.raises(RuntimeError, match="force failed"):
        enforce_day_convention_at_boot(latch, alert_sink=sink)
    assert [p.severity for p in sink.events] == ["CRITICAL"]


# -- 5: one `through` per pass -----


@pytest.mark.asyncio
async def test_reconcile_and_snapshot_share_one_through_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = ns_utc(12, 5, 0, 0)  # EAST rolls at 05:00Z; every wall read advances one hour
    ticks = {"ns": start}

    def ticking_wall() -> int:
        ticks["ns"] += 3_600 * NS
        return ticks["ns"]

    seen_through: list[str] = []
    seen_now: list[int] = []
    real_labels, real_build = snapshot_mod.stage_day_labels, snapshot_mod.build_stage_snapshot

    def spy_labels(*args: Any) -> Any:
        seen_through.append(args[4])
        return real_labels(*args)

    def spy_build(reads: Any, counters_: Any, inp: Any) -> Any:
        seen_now.append(inp.now_ns)
        return real_build(reads, counters_, inp)

    monkeypatch.setattr(runner, "stage_day_labels", spy_labels, raising=True)
    monkeypatch.setattr(runner, "build_stage_snapshot", spy_build, raising=True)
    today = GOV.today(start + 1800 * NS)
    with make_rig(tmp_path, seed=True, port_over={"governed": GOV, "wall_ns": ticking_wall}) as rig:
        await rig.run_pass(start + 1800 * NS)
    assert seen_through and seen_now
    expected = max({today, *GOV.open_days_at(seen_now[0])})
    assert seen_through[0] == expected
