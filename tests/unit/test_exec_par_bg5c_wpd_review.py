"""EXEC-PAR BG-5c WP-D review fixes (spec READY 80, failure-mode NOT-READY 72; rulings binding).

New names are reached through their modules so that each test fails on its own behaviour before
the fix, not on one shared import error.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.runtime import exec_par_records as records
from breezy.runtime import exec_par_settled_pnl_driver as drv
from breezy.runtime.exec_par_records import SettledPnlDay, StageReset
from breezy.runtime.exec_par_stage_eval import evaluate_stage
from breezy.runtime.exec_par_stage_snapshot import build_stage_snapshot
from breezy.runtime.submit_intent import open_submit_intent_latch
from tests.unit.test_exec_par_bg5c_floor_stub_open_days import (
    FLOOR_LABELS,
    floor_day_reads,
    inputs,
)
from tests.unit.test_exec_par_bg5c_wpd_driver import (
    DAY,
    DAY_S,
    FACTS,
    TODAY_OVERDUE,
    YES_NY,
    YES_SF,
    D,
    PnlStore,
    S,
    World,
    ns_at,
    row_of,
    tr,
)

ALERT_REGRESSION = f"settled_pnl_regression:{DAY_S}"
ALERT_SHRANK = f"settled_truth_shrank:{DAY_S}"


@contextlib.asynccontextmanager
async def running(world: World, store: Any, **over: Any) -> AsyncIterator[drv.SettledPnlDriver]:
    driver = world.driver(store, **over)
    try:
        yield driver
    finally:
        driver.dispose()


# -- 1. persist isolation and the revision-accept path --------------------------------------


@pytest.mark.asyncio
async def test_a_failing_day_does_not_block_the_other_days_or_the_stubs() -> None:
    days = ["2026-10-03", "2026-10-04", "2026-10-05"]
    world = World(days=days)
    for day in days:
        world.entry(YES_NY, day=day, hour=20)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore(StageReset(ns_at("2026-10-03", 18), "k_change", None))
    store.fail_days = {"2026-10-04"}
    async with running(world, store) as driver:
        with pytest.raises(drv.SettledPnlPersistError) as caught:
            await driver.run_pass()
        assert sorted(store.days) == ["2026-10-03", "2026-10-05"]
        assert sorted(store.stubs) == ["2026-10-03"]
        assert driver.settled_pnl_seq() == 1  # something landed: the trigger must fire
    assert caught.value.reasons == ("settled_pnl_persist_failed:2026-10-04",)
    assert isinstance(caught.value.__cause__, OSError)


@pytest.mark.asyncio
async def test_a_failed_pass_is_retried_for_the_failed_day_only() -> None:
    world = World(days=["2026-10-03", "2026-10-04"])
    for day in world.days:
        world.entry(YES_NY, day=day, hour=20)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore()
    store.fail_days = {"2026-10-04"}
    async with running(world, store) as driver:
        with pytest.raises(drv.SettledPnlPersistError):
            await driver.run_pass()
        store.fail_days = set()
        await driver.run_pass()
        assert sorted(store.days) == ["2026-10-03", "2026-10-04"]
        assert driver.settled_pnl_seq() == 2


@pytest.mark.asyncio
async def test_a_promoted_revision_that_raises_pnl_is_accepted_with_an_audit_row() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80, token="p1")  # YES loses
    store = PnlStore()
    async with running(world, store) as driver:
        await driver.run_pass()
        world.reader.truth[("NYC", DAY)] = tr("NYC", 72, token="p2")  # the CLI revision: YES wins
        report = await driver.run_pass()
        assert driver.settled_pnl_seq() == 2
    assert report.revisions == 1
    assert row_of(store).pnl_decimal == D("5.9")
    (audit,) = store.revisions
    assert (audit.day, audit.scope, audit.ts_ns) == (DAY_S, "day", 1_700_000_000 * S)
    assert (audit.old_pnl, audit.new_pnl) == ("-4.1", "5.9")
    assert (audit.old_entries, audit.new_entries) == (1, 1)
    assert (audit.cause, audit.product_sha256) == ("cli_revision", "p2")


@pytest.mark.asyncio
async def test_a_promoted_revision_of_a_floor_stub_is_audited_as_a_stub() -> None:
    world = World()
    world.entry(YES_NY, hour=20)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80, token="p1")
    store = PnlStore(StageReset(ns_at(DAY_S, 18), "k_change", None))
    async with running(world, store) as driver:
        await driver.run_pass()
        world.reader.truth[("NYC", DAY)] = tr("NYC", 72, token="p2")
        await driver.run_pass()
    assert sorted((a.scope, a.day) for a in store.revisions) == [("day", DAY_S), ("stub", DAY_S)]
    assert store.stubs[DAY_S].pnl_decimal == D("5.9")


@pytest.mark.asyncio
async def test_a_regression_that_is_not_a_revision_is_a_named_fail_with_one_alert() -> None:
    world = World(days=["2026-10-03", "2026-10-04"])
    world.entry(YES_NY)
    world.entry(YES_NY, day="2026-10-04", hour=20)
    store = PnlStore()
    store.days[DAY_S] = SettledPnlDay(DAY_S, "-4.1", 0, 1, 0)  # ambiguous loss; now merely pending
    async with running(world, store) as driver:
        with pytest.raises(drv.SettledPnlFail) as caught:
            await driver.run_pass()
        assert "2026-10-04" in store.days  # the healthy day still landed
        assert driver.settled_pnl_seq() == 1
        with pytest.raises(drv.SettledPnlFail):
            await driver.run_pass()  # never silent, never wedged-quiet: it fails again ...
    assert caught.value.reasons == (ALERT_REGRESSION,)
    assert world.alerts == [ALERT_REGRESSION]  # ... but the alert is de-duplicated
    assert store.revisions == []


# -- 2. shrinking truth ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_invalidated_final_that_is_not_a_revision_is_a_named_shrink_fail() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80)
    store = PnlStore()
    async with running(world, store) as driver:
        await driver.run_pass()
        seq = driver.settled_pnl_seq()
        world.reader.truth[("NYC", DAY)] = None  # successfully read, no longer a final
        with pytest.raises(drv.SettledPnlFail) as caught:
            await driver.run_pass()
        assert driver.settled_pnl_seq() == seq
    assert caught.value.reasons == (ALERT_SHRANK,)
    assert world.alerts == [ALERT_SHRANK]
    assert row_of(store).settled_entries == 1 and row_of(store).pnl_decimal == D("-4.1")


@pytest.mark.asyncio
async def test_a_drop_in_settled_entries_is_a_named_shrink_fail() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore()
    store.days[DAY_S] = SettledPnlDay(DAY_S, "11.8", 2, 0, 0)
    async with running(world, store) as driver:
        with pytest.raises(drv.SettledPnlFail) as caught:
            await driver.run_pass()
    assert caught.value.reasons == (ALERT_SHRANK,)
    assert row_of(store).settled_entries == 2


# -- 3. cached-final staleness --------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_consecutive_failed_revalidations_alert_once_and_report_the_streak() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore()
    streaks: list[int] = []
    async with running(world, store) as driver:
        await driver.run_pass()
        world.reader.error = RuntimeError("transient")
        for _ in range(4):
            streaks.append((await driver.run_pass()).truth_error_streak)
        assert world.alerts == ["truth_revalidation_failing:NYC:2026-10-03"]
        world.reader.error = None
        assert (await driver.run_pass()).truth_error_streak == 0
    assert streaks == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_a_cached_final_unrevalidated_for_over_a_day_drops_back_to_pending() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore()
    async with running(world, store) as driver:
        await driver.run_pass()
        world.reader.error = RuntimeError("down")
        world.mono = 23 * 3600.0
        kept = await driver.run_pass()
        assert kept.stale_dropped == 0 and row_of(store).settled_entries == 1
        world.mono = 25 * 3600.0
        dropped = await driver.run_pass()
    assert dropped.stale_dropped == 1
    assert (row_of(store).settled_entries, row_of(store).unsettled_entries) == (0, 1)


# -- 4. facts_of failures -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_facts_failure_is_counted_and_logs_only_the_exception_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(instrument_id: str) -> WeatherBucketFacts | None:
        raise RuntimeError("secret-detail")

    world = World()
    world.entry(YES_NY)
    store = PnlStore()
    caplog.set_level(logging.INFO)
    async with running(world, store, facts_of=boom) as driver:
        report = await driver.run_pass()
    assert report.facts_missing == 1
    assert row_of(store).unsettled_entries == 1
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in text and "secret-detail" not in text


@pytest.mark.asyncio
async def test_facts_missing_on_an_entry_past_the_deadline_is_a_named_fail() -> None:
    world = World(today=TODAY_OVERDUE)
    world.entry(YES_NY)
    store = PnlStore()
    async with running(world, store, facts_of=lambda instrument_id: None) as driver:
        with pytest.raises(drv.SettledPnlFail) as caught:
            await driver.run_pass()
    assert caught.value.reasons == ("facts_missing",)
    assert world.alerts == ["facts_missing"]
    assert row_of(store).overdue_entries == 1  # scored and persisted before the FAIL


# -- 5. executor ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_executor_submit_leaves_the_day_pending_and_does_not_stick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore()
    loop = asyncio.get_running_loop()
    real = loop.run_in_executor

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("cannot schedule new futures after shutdown")

    async with running(world, store) as driver:
        monkeypatch.setattr(loop, "run_in_executor", broken)
        report = await driver.run_pass()
        assert report.truth_errors == 1 and row_of(store).unsettled_entries == 1
        monkeypatch.setattr(loop, "run_in_executor", real)
        await driver.run_pass()  # no stale single-flight entry blocks the retry
    assert row_of(store).settled_entries == 1


@pytest.mark.asyncio
async def test_a_dispose_mid_pass_ends_the_pass_without_writes_or_a_post_back() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    world.reader.gate = threading.Event()
    store = PnlStore()
    driver = world.driver(store)
    task = asyncio.create_task(driver.run_pass())
    try:
        await asyncio.sleep(0.2)  # the read is running on its executor thread
        driver.dispose()
        with pytest.raises(drv.DriverDisposed):
            await asyncio.wait_for(task, 1.0)  # released at once, not after the read timeout
    finally:
        world.reader.gate.set()
    await asyncio.sleep(0.2)  # the finished read must not post into a disposed driver
    assert store.writes == 0 and driver.settled_pnl_seq() == 0


# -- 6. corrections -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_correction_the_store_does_not_serve_does_not_change_pnl() -> None:
    """The driver scores on the first FINAL until a revision is promoted to the dataset."""
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72, token="p1")  # a correction exists upstream
    store = PnlStore()  # but the promoted dataset still serves p1
    async with running(world, store) as driver:
        await driver.run_pass()
        report = await driver.run_pass()
        assert driver.settled_pnl_seq() == 1
    assert report.revisions == 0 and store.revisions == []
    assert row_of(store).pnl_decimal == D("5.9")


# -- 7. an unwired stub reader --------------------------------------------------------------


def test_an_unwired_stub_reader_with_post_floor_fills_fails_settled_pnl_missing() -> None:
    reads, counter_reads = floor_day_reads()
    unwired = evaluate_stage(build_stage_snapshot(reads, counter_reads, inputs()))
    assert unwired.reason == "stage_eval_fail:settled_pnl_missing"
    wired = build_stage_snapshot(
        reads,
        counter_reads,
        inputs(
            read_stub_pnl={
                label: SettledPnlDay(label, "0.5", 1, 0, 0) for label in FLOOR_LABELS
            }.get
        ),
    )
    assert evaluate_stage(wired).reason != "stage_eval_fail:settled_pnl_missing"


# -- 8. LOW measure -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_low_measure_entry_is_pending_and_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    low_id = "kxhighny-26oct03-b60.PMUS"  # slug maps to KNYC; the FACTS say LOW
    monkeypatch.setitem(
        FACTS,
        low_id,
        WeatherBucketFacts(
            settlement_station="NYC", climate_day=DAY, measure=Measure.LOW, lower_f=60, upper_f=64
        ),
    )
    world = World()
    world.entry(low_id)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 62)
    store = PnlStore()
    async with running(world, store) as driver:
        report = await driver.run_pass()
    assert report.measure_unsupported == 1
    assert row_of(store).unsettled_entries == 1 and row_of(store).pnl_decimal == 0


# -- 9. two stations: A's floor day is D, B's D is a whole post-floor day --------------------


@pytest.mark.asyncio
async def test_stub_rows_hold_exactly_the_post_floor_entries_across_two_stations() -> None:
    prev = "2026-10-02"
    floor_ts = ns_at(DAY_S, 6)  # KNYC (UTC-5) is on 10-03; KSFO (UTC-8) is still on 10-02
    world = World(days=[prev, DAY_S])
    world.entry(YES_NY, hour=5)  # A pre-floor, label D
    world.entry(YES_NY, hour=7)  # A post-floor, label D
    world.entry(YES_SF, hour=5)  # B pre-floor, label D-1
    world.entry(YES_SF, hour=7)  # B post-floor, still label D-1
    world.entry(YES_SF, hour=9)  # B post-floor, label D: B's WHOLE post-floor day
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    world.reader.truth[("SFO", DAY)] = tr("SFO", 72)
    store = PnlStore(StageReset(floor_ts, "k_change", None))
    async with running(world, store) as driver:
        report = await driver.run_pass()
    win = D("5.9")
    assert {d: r.settled_entries for d, r in store.days.items()} == {prev: 2, DAY_S: 3}
    assert {d: r.settled_entries for d, r in store.stubs.items()} == {prev: 1, DAY_S: 2}
    assert store.stubs[DAY_S].pnl_decimal == 2 * win
    assert store.stubs[prev].pnl_decimal == win
    assert report.stub_days == 2


# -- the latch: audited replacement ----------------------------------------------------------


class _KV:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))


def _audit(ts_ns: int = 7, scope: str = "day") -> Any:
    return records.SettledPnlRevision(
        day=DAY_S,
        ts_ns=ts_ns,
        scope=scope,
        old_pnl="-4.1",
        new_pnl="5.9",
        old_entries=1,
        new_entries=1,
        cause="cli_revision",
        product_sha256="p2",
    )


def test_the_latch_replaces_a_non_monotonic_row_only_with_an_audit_row(tmp_path: Any) -> None:
    low = SettledPnlDay(DAY_S, "-4.1", 1, 0, 0)
    high = SettledPnlDay(DAY_S, "5.9", 1, 0, 0)
    store = _KV()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.write_settled_pnl_day(low)
        with pytest.raises(Exception, match="audit"):
            latch.replace_settled_pnl_day_for_revision(high, 7)
        assert latch.read_settled_pnl_day(DAY_S) == low
        latch.write_settled_pnl_revision(_audit())
        latch.replace_settled_pnl_day_for_revision(high, 7)
        assert latch.read_settled_pnl_day(DAY_S) == high
        with pytest.raises(Exception, match="audit"):
            latch.replace_settled_pnl_day_for_revision(low, 8)  # another ts has no audit
    assert f"{records.EXEC_PAR_PREFIX}settled_pnl_revision/{DAY_S}/7" in store.data


def test_the_latch_stub_replacement_needs_its_own_stub_audit(tmp_path: Any) -> None:
    low = SettledPnlDay(DAY_S, "-4.1", 1, 0, 0)
    high = SettledPnlDay(DAY_S, "5.9", 1, 0, 0)
    with open_submit_intent_latch(_KV(), tmp_path / "s.db") as latch:
        latch.write_floor_stub_pnl_day(low)
        latch.write_settled_pnl_revision(_audit(scope="day"))
        with pytest.raises(Exception, match="audit"):
            latch.replace_floor_stub_pnl_for_revision(high, 7)  # the day audit is not a stub audit
        latch.write_settled_pnl_revision(_audit(scope="stub"))
        latch.replace_floor_stub_pnl_for_revision(high, 7)
        assert latch.read_floor_stub_pnl_day(DAY_S) == high


def test_the_audit_row_round_trips_and_refuses_garbage() -> None:
    audit = _audit()
    assert records.decode_record(records.SettledPnlRevision, records.encode_record(audit)) == audit
    with pytest.raises(records.ExecParRecordError):
        records.encode_record(_audit(scope="elsewhere"))
