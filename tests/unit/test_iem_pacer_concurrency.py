"""IemPacer slot reservation under concurrency (A0-R1 spacing guarantee)."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from breezy.ingest.probe_transport import RequestBudget
from tests.support.mock_http import install_mock_http

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/venue/iem_mos_probe_transport.py"
FROZEN_NS = 1_758_153_600_000_000_000
SECOND_NS = 1_000_000_000


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"breezy_probe_pacer_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


iem = _load(_MODULE_PATH)


class _FakeTime:
    """A clock that only a sleeper advances, recording every requested sleep."""

    def __init__(self) -> None:
        self.now_ns = FROZEN_NS
        self.sleeps: list[float] = []

    def clock(self) -> int:
        return self.now_ns

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("callers", [2, 3])
async def test_concurrent_waits_reserve_distinct_slots_spaced_by_the_interval(
    callers: int,
) -> None:
    fake = _FakeTime()
    pacer = iem.IemPacer(clock=fake.clock, sleeper=fake.sleep)
    await asyncio.gather(*(pacer.wait() for _ in range(callers)))
    # First use fires at once (no sleep); each later caller waits a further interval.
    assert sorted(fake.sleeps) == [float(i) for i in range(1, callers)]


@pytest.mark.asyncio
async def test_concurrent_waits_honour_the_larger_per_method_interval() -> None:
    fake = _FakeTime()
    pacer = iem.IemPacer(clock=fake.clock, sleeper=fake.sleep)
    await asyncio.gather(*(pacer.wait(iem.IEM_AFOS_LAV_MIN_INTERVAL_NS) for _ in range(3)))
    step = iem.IEM_AFOS_LAV_MIN_INTERVAL_NS / 1e9
    assert sorted(fake.sleeps) == [step, 2 * step]


@pytest.mark.asyncio
async def test_sequential_behaviour_is_unchanged() -> None:
    fake = _FakeTime()
    pacer = iem.IemPacer(clock=fake.clock, sleeper=fake.sleep)
    await pacer.wait()
    await pacer.wait()
    assert fake.sleeps == [1.0]
    fake.now_ns += 5 * SECOND_NS
    await pacer.wait()
    assert fake.sleeps == [1.0]


@pytest.mark.asyncio
async def test_the_pacer_is_usable_from_a_second_event_loop() -> None:
    fake = _FakeTime()
    pacer = iem.IemPacer(clock=fake.clock, sleeper=fake.sleep)
    await asyncio.gather(pacer.wait(), pacer.wait())

    async def again() -> None:
        await asyncio.gather(pacer.wait(), pacer.wait())

    await asyncio.to_thread(asyncio.run, again())


@pytest.mark.asyncio
async def test_concurrent_afos_and_lav_fetches_are_spaced_from_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTime()
    install_mock_http(monkeypatch, lambda _r: httpx.Response(200, content=b"ok\n"))
    transport: Any = iem.PacedIemTransport(
        budget=RequestBudget(limit=8),
        pacer=iem.IemPacer(clock=fake.clock, sleeper=fake.sleep),
        user_agent="breezy-pacer-test",
        clock=fake.clock,
        max_body_bytes=1024 * 1024,
        accept="text/plain",
        check_proxy_env=False,
    )
    await asyncio.gather(
        transport.fetch_afos_pfm("LOT"),
        transport.fetch_afos_list("PFMLOT", dt.date(2026, 10, 5)),
        transport.fetch_lav("KNYC", "2026-10-05T00:00Z", "2026-10-06T00:00Z"),
    )
    step = iem.IEM_AFOS_LAV_MIN_INTERVAL_NS / 1e9
    assert sorted(fake.sleeps) == [step, 2 * step]


def test_slot_reservation_is_thread_safe_across_event_loops() -> None:
    import threading

    fake = _FakeTime()  # a clock that never advances: every slot must be distinct
    pacer = iem.IemPacer(clock=fake.clock, sleeper=fake.sleep)
    per_thread = 40
    barrier = threading.Barrier(2)

    def worker() -> None:
        async def run() -> None:
            barrier.wait()
            for _ in range(per_thread):
                await pacer.wait()

        asyncio.run(run())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # 2 * 40 reservations: the first fires at once, the rest are one interval apart.
    assert sorted(fake.sleeps) == [float(i) for i in range(1, 2 * per_thread)]
