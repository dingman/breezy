"""LiveClock callbacks of ``NoLadderMakerStrategy`` must run on the kernel loop.

A ``LiveClock`` timer fires on a foreign thread
(``tests/contract/test_live_timer_thread_affinity.py``). ``SqliteStateStore`` is confined to the
thread that constructed it — the kernel loop, the same thread the app opens the halt latch on.
These tests build that latch and the composed halt veto the app hands the strategy, register the
real clock callbacks, and invoke them from a second ``threading.Thread``. The store read, and the
other three callback bodies, must run on the owner thread: no ``fq_halt_veto_unreadable`` and no
cancel-all, unless the maker's own family halt key is set.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.trial_day_latch import (
    LEGACY_FAMILY_HALT_KEY,
    classify_legacy,
    family_halt_key,
    open_trial_day_latch,
)
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import FqComposedVeto
from breezy.strategy.no_ladder_maker.composition import TRIAL_KEY_PREFIX
from breezy.strategy.no_ladder_maker.ladder_state import Rest, RestState
from breezy.strategy.no_ladder_maker.strategy import NoLadderMakerStrategy
from tests.strategy.no_ladder_maker.maker_strategy_support import NS, Harness

_MAKER_FAMILY = "pm_us_no_maker_sharp_v1"
_FQ_FAMILY = "pm_us_crh_fq_v1"
_MAKER_HALT_KEY = "continuous_rung_hold/family_halt/pm_us_no_maker_sharp_v1"
_FQ_HALT_KEY = "continuous_rung_hold/family_halt/pm_us_crh_fq_v1"
_PINNED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "family_halt"
    / "legacy_v4_halt_2026-09-24.bin"
)
_HALT_PAYLOAD = b'{"v":1,"reason":"test"}'


def _loss_stop_pass() -> str | None:
    """A probed PASS: the loss-stop branch is not the read under test."""
    return None


@dataclass
class _Maker:
    store: SqliteStateStore
    harness: Harness
    reads: list[tuple[int, str]]
    owner: int
    strategy: NoLadderMakerStrategy


@contextmanager
def _composed(tmp_path: Path) -> Iterator[_Maker]:
    """The app's halt veto over a real thread-confined store, strategy not started."""
    owner = threading.get_ident()
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    try:
        pinned = _PINNED.read_bytes()
        assert classify_legacy(pinned) == "attributable_to_v4"
        assert family_halt_key(_FQ_FAMILY) == _FQ_HALT_KEY
        assert family_halt_key(_MAKER_FAMILY) == _MAKER_HALT_KEY
        store.set(LEGACY_FAMILY_HALT_KEY, pinned)
        store.set(_FQ_HALT_KEY, _HALT_PAYLOAD)
        reads: list[tuple[int, str]] = []
        original = store.get

        def _get(key: str) -> bytes | None:
            reads.append((threading.get_ident(), key))
            return original(key)

        store.get = _get  # type: ignore[method-assign]
        with open_submit_intent_latch(store, store_path) as intent:
            latch = open_trial_day_latch(
                intent, key_prefix=TRIAL_KEY_PREFIX, family_id=_MAKER_FAMILY
            )
            veto = FqComposedVeto(
                halt_veto=family_halt_submit_veto(latch),
                loss_stop_veto=_loss_stop_pass,
            )
            harness = Harness(
                stations=("SFO",),
                shadow_only=True,
                permit_expires_at_ns=None,
                veto=veto,
                start=False,
            )
            yield _Maker(store, harness, reads, owner, harness.strategy)
    finally:
        store.close()


def _spy_body(strategy: NoLadderMakerStrategy, name: str) -> list[int]:
    """Record the thread that enters ``name`` — installed before the clock binds it."""
    idents: list[int] = []
    original = getattr(strategy, name)

    def _wrapped(*args: Any, **kwargs: Any) -> None:
        idents.append(threading.get_ident())
        original(*args, **kwargs)

    setattr(strategy, name, _wrapped)
    return idents


def _only(clock: Any, ts_ns: int, name: str) -> Any:
    handlers = list(clock.advance_time(ts_ns, set_time=False))
    names = [str(handler.event.name) for handler in handlers]
    assert names == [name], names
    return handlers[0]


async def _fire(handler: Any, *, owner: int) -> None:
    """Invoke a clock handler on a plain second thread, then drain the kernel loop."""
    done = threading.Event()
    box: list[BaseException] = []
    foreign: list[int] = []

    def _run() -> None:
        foreign.append(threading.get_ident())
        try:
            handler.handle()
        except BaseException as exc:  # noqa: BLE001 - surfaced on the loop thread below
            box.append(exc)
        finally:
            done.set()

    threading.Thread(target=_run, name="maker-clock-foreign").start()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while not done.is_set():
        if loop.time() >= deadline:
            raise AssertionError("clock callback did not return within 5s")
        await asyncio.sleep(0.01)
    await asyncio.sleep(0)
    assert foreign and foreign[0] != owner
    if box:
        raise box[0]


def _owner_reads(maker: _Maker, *, keys: set[str]) -> None:
    assert maker.reads, "the halt veto did not read the store"
    assert {ident for ident, _key in maker.reads} == {maker.owner}
    assert {key for _ident, key in maker.reads} == keys


@pytest.mark.asyncio
async def test_poll_from_a_foreign_thread_reads_the_halt_store_on_the_owner_thread(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Other-family + pinned legacy stays clear; the maker's own halt key vetoes entries.

    The poll callback is the one the live node fires every 30 s. On the wrong thread the
    store raises, the composed veto fails closed as ``fq_halt_veto_unreadable``, and the
    strategy cancels every rest.
    """
    caplog.set_level("ERROR")
    with _composed(tmp_path) as maker:
        strategy = maker.strategy
        strategy.start()
        assert strategy._submit_veto is not None
        assert strategy._submit_veto() is None  # fq key + pinned legacy do not halt this family
        maker.reads.clear()

        now = maker.harness.clock.timestamp_ns()
        interval = strategy.config.poll_interval_s * NS
        first = _only(maker.harness.clock, now + interval, "MAKER-POLL")
        await _fire(first, owner=maker.owner)

        assert strategy._veto_latched is None, caplog.text
        assert "fq_halt_veto_unreadable" not in caplog.text
        assert "different thread" not in caplog.text
        assert maker.harness.cancel_all_calls == []
        assert strategy.counters["cancel_everything_veto"] == 0
        _owner_reads(maker, keys={LEGACY_FAMILY_HALT_KEY, _MAKER_HALT_KEY})

        maker.store.set(_MAKER_HALT_KEY, _HALT_PAYLOAD)
        assert strategy._submit_veto() == "family_halt"
        maker.reads.clear()
        second = _only(maker.harness.clock, now + 2 * interval, "MAKER-POLL")
        await _fire(second, owner=maker.owner)

        assert strategy._veto_latched == "family_halt", caplog.text
        assert strategy.counters["cancel_everything_veto"] == 1
        assert "fq_halt_veto_unreadable" not in caplog.text
        _owner_reads(maker, keys={LEGACY_FAMILY_HALT_KEY, _MAKER_HALT_KEY})


@pytest.mark.asyncio
async def test_nbp_alert_from_a_foreign_thread_runs_on_the_owner_thread(tmp_path: Path) -> None:
    with _composed(tmp_path) as maker:
        strategy = maker.strategy
        idents = _spy_body(strategy, "_on_nbp_alert")
        strategy.start()
        icao = next(i for i, station in strategy._station_by_icao.items() if station == "SFO")
        strategy._schedule_nbp_release(icao)
        assert "SFO" in strategy._nbp_pending
        due = maker.harness.clock.timestamp_ns() + 1
        handler = _only(maker.harness.clock, due, "MAKER-NBP:SFO:1")
        await _fire(handler, owner=maker.owner)
        assert idents == [maker.owner]
        assert "SFO" not in strategy._nbp_pending
        assert strategy._veto_latched is None


@pytest.mark.asyncio
async def test_hard_alert_from_a_foreign_thread_runs_on_the_owner_thread(tmp_path: Path) -> None:
    with _composed(tmp_path) as maker:
        strategy = maker.strategy
        idents = _spy_body(strategy, "_on_hard_alert")
        strategy.start()
        maker.harness.clock.cancel_timer("MAKER-POLL")
        (station, day), ladder = next(iter(strategy.ladders.items()))
        name = f"MAKER-HARD:{station}:{day.isoformat()}"
        handler = _only(maker.harness.clock, ladder.hard_cancel_ns, name)
        await _fire(handler, owner=maker.owner)
        assert idents == [maker.owner]
        assert ladder.hard_cancelled is True
        assert strategy._veto_latched is None


@pytest.mark.asyncio
async def test_shadow_expiry_from_a_foreign_thread_runs_on_the_owner_thread(
    tmp_path: Path,
) -> None:
    with _composed(tmp_path) as maker:
        strategy = maker.strategy
        idents = _spy_body(strategy, "_on_shadow_expiry")
        strategy.start()
        ladder = maker.harness.ladder
        rung_id = next(iter(ladder.rungs))
        expire_ns = maker.harness.clock.timestamp_ns() + 5 * NS
        ladder.rests[rung_id] = Rest(rung_id, 5, expire_ns, RestState.SHADOW)
        strategy._schedule_shadow_expiry(ladder, rung_id, expire_ns)
        handler = _only(maker.harness.clock, expire_ns, "MAKER-SHADOW:1")
        await _fire(handler, owner=maker.owner)
        assert idents == [maker.owner]
        assert rung_id not in ladder.rests
        assert strategy.counters["shadow_expired"] == 1
        assert strategy._veto_latched is None
