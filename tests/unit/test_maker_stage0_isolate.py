"""MAKER-S2 S-5: each station-day runs in its own child process (memory bounded by construction).

Fixture world only. The golden sha256 pins in ``test_maker_stage0_driver`` and
``test_maker_stage0_perf_equivalence`` already run through the isolated default; these tests pin the
isolation contract itself: byte-identical outputs against the in-process path, the child's memory
numbers reaching the progress log and the S-5 abort, loud failure on every child failure mode, and
a repeat of the same day starting from a fresh process.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_isolate as iso
from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis import maker_stage0_runio as runio
from tests.fixtures.maker_stage0 import replay_world as rw
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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- module-level so the spawned child can import them (patched over ``_child_main``) -----------


def child_dies(conn: Connection, *_a: Any) -> None:
    os._exit(9)


def child_raises(conn: Connection, *_a: Any) -> None:
    conn.send(("err", "ValueError", "boom", "traceback text"))
    conn.close()


def child_reports_fixed_memory(
    conn: Connection, ctx: Any, key: Any, work_dir: Path, want_episodes: bool
) -> None:
    report = iso._run_in_child(ctx, key, work_dir, want_episodes)
    fixed = dataclasses.replace(
        report.measure, rss_bytes=CHILD_RSS, peak_bytes=CHILD_PEAK, peak_delta_bytes=CHILD_PEAK - 1
    )
    conn.send(("ok", dataclasses.replace(report, measure=fixed)))
    conn.close()


def _run(world: rw.World, tmp_path: Path, **over: Any) -> drv.RunConfig:
    cfg = drv_fx._fresh(world, tmp_path, **over)
    drv.run(cfg)
    return cfg


def test_isolated_outputs_are_byte_identical_to_the_in_process_path(
    world: rw.World, tmp_path: Path
) -> None:
    child = _run(world, tmp_path / "child", isolate=True)
    local = _run(world, tmp_path / "local", isolate=False)
    for name in OUTPUTS:
        assert _sha(child.out_dir / name) == _sha(local.out_dir / name), name
    assert (child.out_dir / "catalog_slice_manifest.json").read_text() == (
        local.out_dir / "catalog_slice_manifest.json"
    ).read_text()
    lines = [json.loads(x) for x in (child.out_dir / "progress.jsonl").read_text().splitlines()]
    assert [(e["index"], e["of"]) for e in lines] == [
        (i, len(lines)) for i in range(1, len(lines) + 1)
    ]
    assert all(set(e) <= runio.PROGRESS_FIELDS for e in lines)


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
