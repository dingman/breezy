"""MAKER-S2 S-5 leak: a station-day's freed heap must go back to the OS, every station-day.

Bench 4 on the real catalog kept ~170 MB of resident memory per station-day: live allocations were
flat (``mallinfo2().uordblks`` ~98 MB) while the freed chunks glibc kept inside the process grew
(``fordblks`` 587 -> 775 -> 930 MB). The driver now calls ``release_free_heap`` after every
station-day. The fixture world is too small to move RSS, so the effect is pinned on the helper
with a synthetic fragmented heap and the wiring is pinned on the fixture replay.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis import maker_stage0_release as release
from scripts.analysis import maker_stage0_runio as runio
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.unit import test_maker_stage0_driver as drv_fx
from tests.unit import test_maker_stage0_pno as pno_fx

PAGE = 4096
PASSES = 4  # the same station-day replayed four times in one process
CHUNK = 2048  # above pymalloc's 512 B ceiling, so every block comes from glibc malloc
N_CHUNKS = 120_000  # ~245 MB
MIN_RETURNED_BYTES = 100 * 2**20


def _resident_bytes() -> int:
    with open("/proc/self/statm", encoding="ascii") as handle:
        return int(handle.read().split()[1]) * PAGE


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> rw.World:
    return rw.build_world(tmp_path_factory.mktemp("world"))


@pytest.mark.skipif(release._LIBC is None, reason="needs glibc malloc_trim")
def test_release_free_heap_returns_freed_chunks_that_sit_below_live_ones() -> None:
    blocks = [bytearray(CHUNK) for _ in range(N_CHUNKS)]
    survivors = blocks[::10]  # one live block in ten pins the heap top, as a day's results do
    blocks.clear()
    before = _resident_bytes()
    assert release.release_free_heap() is True
    assert before - _resident_bytes() >= MIN_RETURNED_BYTES
    assert len(survivors) == N_CHUNKS // 10


def test_the_driver_releases_the_heap_after_every_station_day(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())
    cfg = drv_fx._fresh(  # the in-process runner: the isolated child trims in its own process
        world,
        tmp_path,
        bench=4,
        stations=("SFO",),
        days=(rw.DAY, rw.DIRECTION_DAY),
        isolate=False,
    )
    monkeypatch.setattr(
        modes, "heaviest", lambda w, n: [runio.heaviest(w, 1)[0]] * (PASSES - 1 if n > 1 else 1)
    )
    calls: list[int] = []
    seen_by_rss: list[int] = []

    def trimmed() -> bool:
        calls.append(1)
        return True

    monkeypatch.setattr(modes, "release_free_heap", trimmed)

    def rss() -> int:
        seen_by_rss.append(len(calls))
        return 1

    monkeypatch.setattr(drv, "current_rss_bytes", rss)
    drv.run(cfg)
    assert len(calls) == PASSES
    # the runner reads the day's RSS and `simulate` then reads the driver's: two reads a row, and
    # the release has happened before the first of them
    assert seen_by_rss[::2] == list(range(1, PASSES + 1))


def test_release_free_heap_reports_whether_the_allocator_could_be_trimmed() -> None:
    assert release.release_free_heap() is (release._LIBC is not None)
