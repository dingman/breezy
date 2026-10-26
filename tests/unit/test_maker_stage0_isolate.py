"""MAKER-S2 S-5: each station-day runs in its own child process (memory bounded by construction).

Fixture world only. The golden sha256 pins in ``test_maker_stage0_driver`` and
``test_maker_stage0_perf_equivalence`` already run through the isolated default; these tests pin the
isolation contract itself: byte-identical outputs against the in-process path, the child's memory
numbers reaching the progress log and the S-5 abort, loud failure on every child failure mode, and
a repeat of the same day starting from a fresh process.
"""

from __future__ import annotations

import dataclasses
import json
import os
import struct
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_isolate as iso
from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis import maker_stage0_runio as runio
from scripts.analysis import maker_stage0_scoped_convert as sc
from scripts.analysis.maker_stage0_events_build import LocalDayViolation
from scripts.analysis.maker_stage0_station_loop import LoopOutput
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.support.stage0_outputs import VOLATILE, _normalised
from tests.unit import test_maker_stage0_driver as drv_fx
from tests.unit import test_maker_stage0_pno as pno_fx

OUTPUTS = ("episodes.jsonl", "station_days.csv", "scored_episodes.csv")
CHILD_PEAK = 123_456_789
CHILD_RSS = 98_765_432
REPEAT_RSS_BOUND = 64 * 2**20  # each row starts from a fresh process, so the repeat is flat


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> rw.World:
    return rw.build_world(tmp_path_factory.mktemp("world"))


@pytest.fixture(autouse=True)
def _calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())


# --- module-level so the spawned child can import them (patched over ``_child_main``) -----------


def child_dies(conn: Connection, *_a: Any) -> None:
    os._exit(9)


def child_raises(conn: Connection, *_a: Any) -> None:
    conn.send(("err", None, "ValueError", "boom", "traceback text"))
    conn.close()


def child_stalls_mid_send(conn: Connection, *_a: Any) -> None:
    os.write(conn.fileno(), struct.pack("!i", 1000) + b"x" * 10)  # a header and 10 of 1000 bytes
    time.sleep(600)


def child_raises_local_day_violation(conn: Connection, *_a: Any) -> None:
    try:
        raise LocalDayViolation("episode past local midnight")
    except Exception as exc:  # noqa: BLE001 - mirrors the child's own handler
        conn.send(("err", iso._portable(exc), type(exc).__name__, str(exc), "tb"))
        conn.close()


def child_echoes_scan_memo(conn: Connection, *args: Any) -> None:
    conn.send(("err", None, "ValueError", f"memo keys {sorted(args[-1])}", ""))
    conn.close()


def child_reports_fixed_memory(
    conn: Connection, ctx: Any, key: Any, work_dir: Path, want_episodes: bool, scans: Any
) -> None:
    report = iso._run_in_child(ctx, key, work_dir, want_episodes, scans)
    fixed = dataclasses.replace(
        report.measure, rss_bytes=CHILD_RSS, peak_bytes=CHILD_PEAK, peak_delta_bytes=CHILD_PEAK - 1
    )
    conn.send(("ok", dataclasses.replace(report, measure=fixed)))
    conn.close()


def _run(world: rw.World, tmp_path: Path, **over: Any) -> drv.RunConfig:
    cfg = drv_fx._fresh(world, tmp_path, **over)
    drv.run(cfg)
    return cfg


WORLDS: dict[str, dict[str, Any]] = {
    "base": {},
    "second_instance": {"second_instance": True},  # two instances: LRU reuse vs a fresh child
    "listing_abstained": {"listed_iso": "2026-09-28T13:00:00"},  # abstained + non-replayed days
}


def _capture_out(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    seen: list[Any] = []
    real = getattr(drv, "finish")  # noqa: B009 - not exported by the driver

    def spy(cfg: Any, pre: Any, out: Any, *a: Any, **k: Any) -> Any:
        seen.append(out)
        return real(cfg, pre, out, *a, **k)

    monkeypatch.setattr(drv, "finish", spy, raising=True)
    return seen


def _comparable(out: Any) -> dict[str, Any]:
    """Every LoopOutput field, order-sensitive where the order reaches an artefact."""
    return {
        "rows": {k: list(v) for k, v in out.rows.items()},
        "seeds": list(out.seeds),
        "consumed": sorted(out.consumed),
        "abstentions": list(out.abstentions.items()),
        "parity": list(out.parity.items()),
        "listing_abstained": list(out.listing_abstained),
        "rounding": {k: list(v.items()) for k, v in out.rounding.items()},
        "unknown_delta": out.unknown_delta,
    }


def _require_unpinned_hashseed() -> None:
    """Fail in the gate (egress-block attested), skip in any other environment."""
    seed = os.environ.get("PYTHONHASHSEED")
    if seed is None:
        return
    if "BREEZY_TEST_OS_EGRESS_BLOCK" not in os.environ:
        pytest.skip(f"PYTHONHASHSEED={seed} is exported, but this is not the gate")
    pytest.fail(
        f"PYTHONHASHSEED={seed} is exported: every spawned child would share one hash seed, "
        "blinding the isolated-vs-in-process and determinism comparisons to hash-order bugs. "
        "Unset it for the gate."
    )


def test_hashseed_guard_fails_in_the_gate_and_skips_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setenv("BREEZY_TEST_OS_EGRESS_BLOCK", "1")
    with pytest.raises(pytest.fail.Exception, match="PYTHONHASHSEED=0"):
        _require_unpinned_hashseed()
    monkeypatch.delenv("BREEZY_TEST_OS_EGRESS_BLOCK")
    with pytest.raises(pytest.skip.Exception, match="not the gate"):
        _require_unpinned_hashseed()
    monkeypatch.delenv("PYTHONHASHSEED")
    _require_unpinned_hashseed()  # unset: nothing to report in either environment


def test_the_gate_environment_does_not_pin_pythonhashseed() -> None:
    """Child-side hash-order coverage needs every child to draw its own random hash seed."""
    _require_unpinned_hashseed()


@pytest.mark.parametrize("variant", list(WORLDS))
def test_isolated_run_equals_the_in_process_run_in_every_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    root = tmp_path / "world"
    built = rw.build_world(root, capture=rw.build_capture(root, **WORLDS[variant]))
    seen = _capture_out(monkeypatch)
    child = _run(built, tmp_path / "child", isolate=True)
    local = _run(built, tmp_path / "local", isolate=False)
    assert _comparable(seen[0]) == _comparable(seen[1])
    names = {p.name for p in child.out_dir.iterdir()}
    assert names == {p.name for p in local.out_dir.iterdir()}
    for name in sorted(names - VOLATILE):
        assert _normalised(child, name) == _normalised(local, name), name
    assert set(OUTPUTS) <= names
    lines = [json.loads(x) for x in (child.out_dir / "progress.jsonl").read_text().splitlines()]
    mine = [json.loads(x) for x in (local.out_dir / "progress.jsonl").read_text().splitlines()]
    identity = ("index", "of", "station", "climate_day", "status", "n_events")
    assert [{k: e[k] for k in identity} for e in lines] == [
        {k: e[k] for k in identity} for e in mine
    ]
    assert [e["index"] for e in lines] == list(range(1, len(lines) + 1))
    assert all(set(e) <= runio.PROGRESS_FIELDS and "parent_rss_bytes" in e for e in lines)


def test_the_first_day_wins_the_ladder_parity_when_children_are_absorbed() -> None:
    first, second, merged = LoopOutput(), LoopOutput(), LoopOutput()
    first.parity["SFO"], second.parity["SFO"], second.parity["LAX"] = 0, 1, 1
    first.abstentions["A"], second.abstentions["B"], second.abstentions["A"] = 2, 5, 3
    first.rounding["CONTRACTS"] = {"levels": 4}
    second.rounding["CONTRACTS"] = {"levels": 6}
    for part in (first, second):
        iso._absorb(merged, part)
    assert merged.parity == {"SFO": 0, "LAX": 1} and list(merged.parity) == ["SFO", "LAX"]
    assert list(merged.abstentions.items()) == [("A", 5), ("B", 5)]
    assert merged.rounding == {"CONTRACTS": {"levels": 10}}


def test_progress_rows_carry_the_childs_memory_and_s5_reads_it(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(iso, "_child_main", child_reports_fixed_memory)
    cfg = _run(world, tmp_path)
    lines = [json.loads(x) for x in (cfg.out_dir / "progress.jsonl").read_text().splitlines()]
    assert lines
    assert {e["peak_rss_bytes"] for e in lines} == {CHILD_PEAK}
    assert {e["rss_bytes"] for e in lines} == {CHILD_RSS}
    assert {e["rss_peak_delta_bytes"] for e in lines} == {CHILD_PEAK - 1}


def test_a_child_over_four_gib_aborts_and_voids_the_run(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def runner_over(cfg: drv.RunConfig) -> iso.DayRunner:
        real = iso.isolated_runner(cfg.work_root / "children")

        def run(ctx: Any, key: Any, out: Any) -> iso.DayMeasure:
            return dataclasses.replace(real(ctx, key, out), peak_bytes=5 * 2**30)

        return run

    monkeypatch.setattr(modes, "day_runner", runner_over)
    cfg = drv_fx._fresh(world, tmp_path)
    with pytest.raises(drv.RunVoided, match="S-5") as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, drv.MemoryAbort)


@pytest.mark.parametrize(
    ("target", "needle"),
    [(child_dies, "exit code 9"), (child_raises, "ValueError: boom")],
)
def test_a_child_failure_voids_the_run_loudly(
    world: rw.World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: Callable[..., None],
    needle: str,
) -> None:
    monkeypatch.setattr(iso, "_child_main", target)
    cfg = drv_fx._fresh(world, tmp_path)
    with pytest.raises(drv.RunVoided, match="IsolatedDayFailed") as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, iso.IsolatedDayFailed)
    assert needle in str(info.value)
    assert drv_fx._void_dir(cfg).is_dir()


def test_the_child_inherits_the_parents_preflight_scan_memo(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sc._SCANS, ("root", "live", "sentinel-instance"), (("sig",), None))
    monkeypatch.setattr(iso, "_child_main", child_echoes_scan_memo)
    with pytest.raises(drv.RunVoided, match="sentinel-instance"):
        drv.run(drv_fx._fresh(world, tmp_path))


def test_a_child_that_times_out_voids_the_run(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        modes, "day_runner", lambda cfg: iso.isolated_runner(cfg.work_root / "children", 0.001)
    )
    cfg = drv_fx._fresh(world, tmp_path)
    with pytest.raises(drv.RunVoided, match="timed out"):
        drv.run(cfg)


def test_a_repeated_station_day_starts_from_a_fresh_process(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        modes, "heaviest", lambda w, n: [runio.heaviest(w, 1)[0]] * (3 if n > 1 else 1)
    )
    cfg = drv_fx._fresh(
        world, tmp_path, bench=4, stations=("SFO",), days=(rw.DAY, rw.DIRECTION_DAY)
    )
    drv.run(cfg)
    rows = json.loads((cfg.out_dir / "bench.json").read_text())["station_days"]
    ends = [r["rss_bytes"] for r in rows]
    assert len(ends) == 4
    assert max(ends) - min(ends) <= REPEAT_RSS_BOUND, ends
    assert all(r["peak_rss_bytes"] > 0 for r in rows)


def test_a_child_that_stalls_mid_send_cannot_block_the_receive(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(iso, "_child_main", child_stalls_mid_send)
    monkeypatch.setattr(
        modes, "day_runner", lambda cfg: iso.isolated_runner(cfg.work_root / "children", 3.0)
    )
    started = time.monotonic()
    with pytest.raises(drv.RunVoided, match="timed out"):
        drv.run(drv_fx._fresh(world, tmp_path))
    assert time.monotonic() - started < 120


def test_a_typed_in_day_error_keeps_its_type_and_voids_the_run(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(iso, "_child_main", child_raises_local_day_violation)
    cfg = drv_fx._fresh(world, tmp_path)
    with pytest.raises(drv.RunVoided, match="LocalDayViolation") as info:
        drv.run(cfg)
    assert type(info.value.cause) is LocalDayViolation  # not IsolatedDayFailed: exit mapping same
    assert "past local midnight" in str(info.value.cause)
    assert drv_fx._void_dir(cfg).is_dir() and not cfg.out_dir.exists()
    assert [e["kind"] for e in drv_fx._ledger(cfg)] == ["verdict_run_start", "void"]
