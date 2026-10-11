"""EXEC-PAR BG-5c WP-D confirm-review fixes: durable revision basis, narrowed audited replace,
daemon worker threads."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from breezy.runtime import exec_par_records as records
from breezy.runtime import exec_par_settled_pnl as pnl_mod
from breezy.runtime import exec_par_settled_pnl_driver as drv
from breezy.runtime.exec_par_records import SettledPnlDay, StageReset
from breezy.runtime.submit_intent import open_submit_intent_latch
from tests.unit.test_exec_par_bg5c_wpd_driver import (
    DAY,
    DAY_S,
    YES_NY,
    D,
    PnlStore,
    World,
    ns_at,
    row_of,
    tr,
)
from tests.unit.test_exec_par_bg5c_wpd_review import _KV, running

REPO = Path(__file__).resolve().parents[2]


# -- 1. a revision promoted while the driver was down ----------------------------------------


@pytest.mark.asyncio
async def test_a_revision_promoted_while_down_is_accepted_on_the_first_pass_after_restart() -> None:
    world = World()
    world.entry(YES_NY, hour=20)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80, token="p1")  # YES loses
    store = PnlStore(StageReset(ns_at(DAY_S, 18), "k_change", None))
    async with running(world, store) as first:
        await first.run_pass()
    # the process is gone; the CLI revision was promoted meanwhile
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72, token="p2")  # YES wins now
    async with running(world, store) as second:  # a NEW driver: no in-memory revision state
        report = await second.run_pass()
        assert second.settled_pnl_seq() == 1
    assert report.revisions == 0  # it was STORED, not REVISED, in this process
    assert row_of(store).pnl_decimal == D("5.9") and store.stubs[DAY_S].pnl_decimal == D("5.9")
    assert sorted((a.scope, a.day, a.cause, a.product_sha256) for a in store.revisions) == [
        ("day", DAY_S, "cli_revision", "p2"),
        ("stub", DAY_S, "cli_revision", "p2"),
    ]
    assert world.alerts == []


@pytest.mark.asyncio
async def test_the_basis_is_written_after_the_row_and_a_new_settlement_is_not_a_revision() -> None:
    world = World()
    world.entry(YES_NY)
    store = PnlStore()
    async with running(world, store) as first:
        await first.run_pass()  # pending: nothing final to build a basis from
        assert (DAY_S, "day") not in store.bases
        world.reader.truth[("NYC", DAY)] = tr("NYC", 72, token="p1")
        await first.run_pass()
    assert (DAY_S, "day") in store.bases
    async with running(world, store) as second:
        await second.run_pass()
    assert store.revisions == []  # an unchanged basis is never a revision


def test_the_latch_round_trips_the_basis_under_its_own_keys(tmp_path: Path) -> None:
    store = _KV()
    day = records.SettledPnlBasis(day=DAY_S, scope="day", basis="NYC@2026-10-03=p1:80::0")
    stub = records.SettledPnlBasis(day=DAY_S, scope="stub", basis="NYC@2026-10-03=p1:80::0")
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        assert latch.read_settled_pnl_basis(DAY_S, "day") is None
        latch.write_settled_pnl_basis(day)
        latch.write_settled_pnl_basis(stub)
        assert latch.read_settled_pnl_basis(DAY_S, "day") == day
        assert latch.read_settled_pnl_basis(DAY_S, "stub") == stub
    assert f"{records.EXEC_PAR_PREFIX}settled_pnl_basis/{DAY_S}" in store.data
    assert f"{records.EXEC_PAR_PREFIX}settled_pnl_basis/{DAY_S}/stub" in store.data


# -- 2. the audited replace is narrow --------------------------------------------------------


def test_the_regression_kind_is_carried_on_the_exception() -> None:
    shrink = SettledPnlDay(DAY_S, "0", 1, 0, 0)
    bigger = SettledPnlDay(DAY_S, "0", 1, 1, 0)
    with pytest.raises(pnl_mod.SettledPnlRegression) as caught:
        pnl_mod.check_monotonic(bigger, shrink)
    assert caught.value.kind == "entry_shrink"
    with pytest.raises(pnl_mod.SettledPnlRegression) as rise:
        pnl_mod.check_monotonic(
            SettledPnlDay(DAY_S, "-4", 1, 0, 0), SettledPnlDay(DAY_S, "5", 1, 0, 0)
        )
    assert rise.value.kind == "pnl_rise"


@pytest.mark.asyncio
async def test_a_shrink_in_entry_count_under_a_revision_is_still_a_named_fail() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80, token="p1")
    store = PnlStore()
    async with running(world, store) as driver:
        await driver.run_pass()
        # the stored row claims one more entry than the sources now show
        store.days[DAY_S] = SettledPnlDay(DAY_S, "-4.2", 1, 1, 0)
        world.reader.truth[("NYC", DAY)] = tr("NYC", 72, token="p2")  # a promoted revision
        with pytest.raises(drv.SettledPnlFail) as caught:
            await driver.run_pass()
    assert caught.value.reasons == (f"settled_truth_shrank:{DAY_S}",)
    assert store.revisions == [] and store.days[DAY_S].total_entries == 2


def test_the_latch_refuses_an_audited_replacement_that_shrinks_the_entry_count(
    tmp_path: Path,
) -> None:
    prior = SettledPnlDay(DAY_S, "-4.2", 1, 1, 0)
    smaller = SettledPnlDay(DAY_S, "5.9", 1, 0, 0)
    with open_submit_intent_latch(_KV(), tmp_path / "s.db") as latch:
        latch.write_settled_pnl_day(prior)
        latch.write_settled_pnl_revision(
            records.SettledPnlRevision(DAY_S, 7, "day", "-4.2", "5.9", 2, 1, "cli_revision", "p2")
        )
        with pytest.raises(pnl_mod.SettledPnlRegression):
            latch.replace_settled_pnl_day_for_revision(smaller, 7)
        assert latch.read_settled_pnl_day(DAY_S) == prior


# -- 3. worker threads ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_truth_worker_threads_are_daemons() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    async with running(world, PnlStore()) as driver:
        await driver.run_pass()
        workers = [t for t in threading.enumerate() if t.name.startswith("exec_par_pnl_truth")]
        assert workers and all(t.daemon for t in workers)


def test_a_hung_truth_read_does_not_block_interpreter_exit() -> None:
    script = textwrap.dedent(
        """
        import threading
        from breezy.runtime.exec_par_settled_pnl_driver import SettledPnlDriver
        import breezy.runtime.exec_par_settled_pnl_driver as m
        executor = m._new_executor()
        executor.submit(threading.Event().wait, 600)  # a read that never returns
        print("submitted", flush=True)
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert done.returncode == 0 and "submitted" in done.stdout, done.stderr
