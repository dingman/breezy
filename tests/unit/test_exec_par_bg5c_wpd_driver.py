"""EXEC-PAR BG-5c WP-D: the settled-P&L driver (R8, A3, A6, A7, N-A, cent quantization).

The world is built from the real BG-5c WP-B ``DurableSources`` over fake stores, so ``EntryInput``
rows come from ``entry_inputs_from`` (``ever_ambiguous`` from the mark rows), and from the real
BG-1c ``persist_settled_pnl`` with the real monotonic guard.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from breezy.analysis.labeling.fq_scorer import ForecastQuantileLadderScorer
from breezy.domain.exec_intent import (
    FILL_BY_DAY_KEY_PREFIX,
    FILL_BY_FINGERPRINT_KEY_PREFIX,
    FILL_KEY_PREFIX,
    utc_day_for_ns,
)
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.runtime.exec_par_durable_sources import (
    DurableSources,
    SourceReadError,
    SpendAuditMonitor,
)
from breezy.runtime.exec_par_governed_days import governed_days_for
from breezy.runtime.exec_par_records import AmbiguousRow, OrderAnchor, SettledPnlDay, StageReset
from breezy.runtime.exec_par_settled_pnl import (
    CENT,
    check_monotonic,
)
from breezy.runtime.exec_par_settled_pnl_driver import (
    DriverDisposed,
    SettledPnlDriver,
    SettledPnlPersistError,
    cent_cost,
)
from breezy.runtime.exec_par_settled_truth import TruthReadError, TruthRecord
from breezy.runtime.submit_intent import open_submit_intent_latch

S = 1_000_000_000
H = 3_600 * S
D = Decimal
OFFSETS = {"KNYC": -5.0, "KSFO": -8.0}
GOV = governed_days_for(list(OFFSETS), OFFSETS.__getitem__)
DAY = dt.date(2026, 10, 3)
DAY_S = DAY.isoformat()
TODAY_PENDING = "2026-10-05"  # age 2: pending
TODAY_OVERDUE = "2026-10-06"  # age 3 == SETTLEMENT_DEADLINE_DAYS: overdue
SLUG_NY = "kxhighny-26oct03-b72"
YES_NY = f"{SLUG_NY}.PMUS"
NO_NY = f"{SLUG_NY}^no.PMUS"
SLUG_SF = "kxhighsf-26oct03-b72"
YES_SF = f"{SLUG_SF}.PMUS"
FACTS = {
    YES_NY: WeatherBucketFacts(
        settlement_station="NYC", climate_day=DAY, measure=Measure.HIGH, lower_f=70, upper_f=74
    ),
    YES_SF: WeatherBucketFacts(
        settlement_station="SFO", climate_day=DAY, measure=Measure.HIGH, lower_f=70, upper_f=74
    ),
}
FACTS[NO_NY] = FACTS[YES_NY]


def ns_at(day: str, hour: int = 15) -> int:
    moment = dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")
    return int(moment.timestamp()) * S


def station_of(slug: str) -> str | None:
    return {"ny": "KNYC", "sf": "KSFO"}.get(slug[6:8])


def facts_of(instrument_id: str) -> WeatherBucketFacts | None:
    return FACTS.get(instrument_id)


def tr(station: str, tmax: int | None, *, token: str = "p1", flag: str = "") -> TruthRecord:
    return TruthRecord(
        station=station,
        climate_day=DAY,
        tmax_f=tmax,
        tmax_flag=flag,
        correction=False,
        token=f"{token}:{tmax}",
        product_sha256=token,
    )


# -- fakes -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rec:
    venue_order_id: str
    client_order_id: str
    order_side: str
    cumulative_qty: Decimal
    cumulative_cost: Decimal
    instrument_id: str
    cumulative_fee: Decimal
    fee_reconciled: bool = True
    fee_coefficient_at_fill: Decimal | None = None


def decode_rec(raw: bytes) -> Rec:
    b = json.loads(raw.decode())
    return Rec(b["v"], b["c"], b["s"], Decimal(b["q"]), Decimal(b["k"]), b["i"], Decimal(b["f"]))


@dataclass(frozen=True)
class Intent:
    intent_id: str
    fingerprint: str
    created_ns: int
    slug: str | None
    is_exit: bool = False


class Reader:
    """Blocking truth reader double. ``release`` (when set up) gates every read."""

    def __init__(self) -> None:
        self.truth: dict[tuple[str, dt.date], TruthRecord | None] = {}
        self.calls: list[tuple[str, dt.date]] = []
        self.error: Exception | None = None
        self.gate: threading.Event | None = None
        self.threads: set[str] = set()
        self._lock = threading.Lock()

    def read(self, station: str, climate_day: dt.date) -> TruthRecord | None:
        with self._lock:
            self.calls.append((station, climate_day))
            self.threads.add(threading.current_thread().name)
        if self.gate is not None:
            self.gate.wait(5.0)
        if self.error is not None:
            raise self.error
        return self.truth.get((station, climate_day))


class PnlStore:
    """The latch's surface with the REAL monotonic guard and the revision-audit rule."""

    def __init__(self, floor: StageReset | None = None) -> None:
        self.floor = floor
        self.days: dict[str, SettledPnlDay] = {}
        self.stubs: dict[str, SettledPnlDay] = {}
        self.revisions: list[Any] = []
        self.error: Exception | None = None
        self.fail_days: set[str] = set()
        self.writes = 0

    def read_stage_reset(self) -> StageReset | None:
        return self.floor

    def read_settled_pnl_day(self, day: str) -> SettledPnlDay | None:
        return self.days.get(day)

    def read_floor_stub_pnl_day(self, day: str) -> SettledPnlDay | None:
        return self.stubs.get(day)

    def _check(self, record: SettledPnlDay) -> None:
        if self.error is not None:
            raise self.error
        if record.day in self.fail_days:
            raise OSError("disk")

    def write_settled_pnl_day(self, record: SettledPnlDay) -> None:
        self._check(record)
        check_monotonic(self.days.get(record.day), record)
        self.days[record.day] = record
        self.writes += 1

    def write_floor_stub_pnl_day(self, record: SettledPnlDay) -> None:
        if self.error is not None:
            raise self.error
        check_monotonic(self.stubs.get(record.day), record)
        self.stubs[record.day] = record
        self.writes += 1

    def write_settled_pnl_revision(self, audit: Any) -> None:
        self.revisions.append(audit)

    def _audited(self, record: SettledPnlDay, ts_ns: int, scope: str) -> None:
        if not any(
            r.day == record.day and r.ts_ns == ts_ns and r.scope == scope for r in self.revisions
        ):
            raise RuntimeError("no revision audit row")

    def replace_settled_pnl_day_for_revision(self, record: SettledPnlDay, ts_ns: int) -> None:
        self._audited(record, ts_ns, "day")
        self.days[record.day] = record
        self.writes += 1

    def replace_floor_stub_pnl_for_revision(self, record: SettledPnlDay, ts_ns: int) -> None:
        self._audited(record, ts_ns, "stub")
        self.stubs[record.day] = record
        self.writes += 1


@dataclass
class World:
    reader: Reader = field(default_factory=Reader)
    intents: list[Intent] = field(default_factory=list)
    data: dict[str, bytes] = field(default_factory=dict)
    marks: dict[str, list[AmbiguousRow]] = field(default_factory=dict)
    anchors: dict[str, list[OrderAnchor]] = field(default_factory=dict)
    sources_error: Exception | None = None
    today: str = TODAY_PENDING
    days: list[str] = field(default_factory=lambda: [DAY_S])
    alerts: list[str] = field(default_factory=list)
    mono: float = 0.0
    n: int = 0

    def entry(
        self,
        instrument_id: str,
        *,
        qty: str = "10",
        cost: str = "4",
        fee: str = "0.1",
        hour: int = 15,
        day: str = DAY_S,
        ambiguous_mark: bool = False,
    ) -> Intent:
        self.n += 1
        slug = instrument_id.split(".")[0].removesuffix("^no")
        created = ns_at(day, hour)
        intent = Intent(f"i{self.n}", f"fp{self.n}", created, slug)
        self.intents.append(intent)
        station = station_of(slug)
        assert station is not None
        label = GOV.entry_day(station, created)
        self.anchors.setdefault(label, []).append(
            OrderAnchor(
                f"c{self.n}", slug, label, created, "0.4", qty, cost, created, "event_time", station
            )
        )
        vid = f"v{self.n}"
        utc_day = utc_day_for_ns(created).isoformat()
        self.data[f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{utc_day}:{intent.fingerprint}"] = vid.encode()
        body = {
            "v": vid,
            "c": f"c{self.n}",
            "s": "BUY",
            "q": qty,
            "k": cost,
            "i": instrument_id,
            "f": fee,
        }
        self.data[f"{FILL_KEY_PREFIX}{vid}"] = json.dumps(body).encode()
        index = f"{FILL_BY_DAY_KEY_PREFIX}{utc_day}"
        listed = json.loads(self.data.get(index, b"[]").decode())
        self.data[index] = json.dumps([*listed, vid]).encode()
        if ambiguous_mark:
            self.marks.setdefault(label, []).append(
                AmbiguousRow(
                    intent.intent_id, "armed_post_boot", label, created, "slot", 1, station
                )
            )
        return intent

    def sources(self) -> DurableSources:
        world = self

        class _Intents:
            def all_intents(self) -> tuple[Intent, ...]:
                if world.sources_error is not None:
                    raise world.sources_error
                return tuple(world.intents)

        class _Store:
            def get(self, key: str) -> bytes | None:
                return world.data.get(key)

        class _Marks:
            def read_ambiguous(self, day: str) -> tuple[AmbiguousRow, ...]:
                return tuple(world.marks.get(day, ()))

        class _Anchors:
            def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]:
                return tuple(world.anchors.get(day, ()))

        return DurableSources(
            intents=_Intents(),
            store=_Store(),
            decode_fill=decode_rec,
            governed=GOV,
            station_of=station_of,
            ambiguous=_Marks(),
            anchors=_Anchors(),
            monitor=SpendAuditMonitor(alert_sink=lambda audit: True),
        )

    def driver(self, store: Any, **over: Any) -> SettledPnlDriver:
        kwargs: dict[str, Any] = {
            "reader": self.reader,
            "facts_of": facts_of,
            "sources_factory": self.sources,
            "days": lambda: list(self.days),
            "unresolved_intent_ids": lambda: frozenset(),
            "armed_cost_of": lambda intent_id: None,
            "governed": GOV,
            "store": store,
            "today": lambda: self.today,
            "read_timeout_s": 2.0,
            "alert": self.alerts.append,
            "clock_ns": lambda: 1_700_000_000 * S,
            "monotonic": lambda: self.mono,
        }
        kwargs.update(over)
        return SettledPnlDriver(**kwargs)


def row_of(store: PnlStore, day: str = DAY_S) -> SettledPnlDay:
    return store.days[day]


# -- A6: held side, sign, payoff -------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("instrument_id", "cost", "tmax", "held"),
    [
        (YES_NY, "4", 72, True),  # YES entry, settles YES
        (YES_NY, "4", 80, False),  # YES entry, settles NO
        (NO_NY, "0.9", 72, False),  # NO entry (BUY of the ^no leg at 0.09 each), YES wins
        (NO_NY, "0.9", 80, True),  # NO entry, NO wins
    ],
)
async def test_payoff_is_qty_times_held_outcome_minus_held_cost_minus_fee(
    instrument_id: str, cost: str, tmax: int, held: bool
) -> None:
    world = World()
    world.entry(instrument_id, qty="10", cost=cost, fee="0.1")
    world.reader.truth[("NYC", DAY)] = tr("NYC", tmax)
    store = PnlStore()
    driver = world.driver(store)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    # The BG-1c-independent pin: fq_scorer's own payoff formula (qty * payoff - cost - fee).
    fill = SimpleNamespace(cumulative_cost=D(cost), cumulative_fee=D("0.1"))
    realize: Any = ForecastQuantileLadderScorer._realized
    expected = realize(SimpleNamespace(held=held, pnl=D(0)), fill, D(10), True)
    assert row_of(store).pnl_decimal == expected
    assert row_of(store).settled_entries == 1
    # exactly one flip: a NO win pays the full 10 against the held cost, never 10 - (10 - cost)
    assert expected == (D(10) if held else D(0)) - D(cost) - D("0.1")


@pytest.mark.asyncio
async def test_a_recorded_live_no_fill_scores_at_its_held_cost_with_no_second_flip() -> None:
    """The contract fixture's NO record: a ``^no`` BUY with cost 0.09 (``test_reconciliation_
    durable_reports_contract``). NO wins: payoff 1 - 0.09 - fee."""
    world = World()
    world.entry(NO_NY, qty="1", cost="0.09", fee="0.01")
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80)
    store = PnlStore()
    driver = world.driver(store)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    assert row_of(store).pnl_decimal == D("0.90")


@pytest.mark.asyncio
async def test_a_non_buy_record_is_refused_not_flipped() -> None:
    world = World()
    intent = world.entry(YES_NY)
    key = next(k for k in world.data if k.startswith(FILL_KEY_PREFIX))
    world.data[key] = world.data[key].replace(b'"BUY"', b'"SELL"')
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    driver = world.driver(PnlStore())
    try:
        with pytest.raises(Exception):  # noqa: B017 - any typed refusal, never a score
            await driver.run_pass()
    finally:
        driver.dispose()
    _ = intent


# -- inputs from entry_inputs_from; pending / overdue ----------------------------------------


@pytest.mark.asyncio
async def test_ever_ambiguous_comes_from_the_marks_via_entry_inputs_from() -> None:
    world = World()
    world.entry(YES_NY, ambiguous_mark=True)  # marked, fill confirmed, no outcome yet
    world.entry(YES_NY, hour=16)  # unmarked, no outcome yet
    store = PnlStore()
    driver = world.driver(store)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    row = row_of(store)
    assert (row.ambiguous_entries, row.unsettled_entries) == (1, 1)
    assert row.pnl_decimal == D("-4.1")  # the marked entry at cost + fee; the other is pending


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "truth",
    [
        None,  # missing
        tr("NYC", None, flag="M"),  # void / sentinel: not final-grade
        tr("NYC", 72, flag="T"),
    ],
)
async def test_missing_or_void_truth_is_pending_then_overdue_never_zero(
    truth: TruthRecord | None,
) -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = truth
    store = PnlStore()
    driver = world.driver(store)
    try:
        await driver.run_pass()
        pending = row_of(store)
        assert (pending.unsettled_entries, pending.overdue_entries, pending.settled_entries) == (
            1,
            0,
            0,
        )
        assert pending.pnl_decimal == 0  # not summed while pending ...
        world.today = TODAY_OVERDUE
        await driver.run_pass()
    finally:
        driver.dispose()
    overdue = row_of(store)
    assert (overdue.unsettled_entries, overdue.overdue_entries) == (0, 1)
    assert overdue.pnl_decimal == D("-4.1")  # ... then a full-cost loss, never a zero


@pytest.mark.asyncio
async def test_an_instrument_with_no_resolvable_rung_is_pending() -> None:
    world = World()
    world.entry(YES_NY)
    store = PnlStore()
    driver = world.driver(store, facts_of=lambda instrument_id: None)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    assert row_of(store).unsettled_entries == 1
    assert world.reader.calls == []


# -- revision, cache -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_revised_cli_value_invalidates_the_cached_outcome() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72, token="p1")
    store = PnlStore()
    driver = world.driver(store)
    try:
        first = await driver.run_pass()
        assert row_of(store).pnl_decimal == D("5.9")  # 10 - 4 - 0.1
        world.reader.truth[("NYC", DAY)] = tr("NYC", 80, token="p2")  # the CLI was corrected
        second = await driver.run_pass()
    finally:
        driver.dispose()
    assert first.revisions == 0 and second.revisions == 1
    assert row_of(store).pnl_decimal == D("-4.1")  # re-scored on the revised value
    assert len(world.reader.calls) == 2  # the cached final was re-validated, not trusted


# (the revision-raises-pnl and truth-shrank cases live in test_exec_par_bg5c_wpd_review.py)


# -- A7: executor mechanics ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reads_are_single_flight_per_station_day() -> None:
    world = World()
    world.entry(YES_NY)
    world.entry(NO_NY, cost="0.9", hour=16)  # same station-day, other instrument
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    world.reader.gate = threading.Event()
    store = PnlStore()
    driver = world.driver(store)
    try:
        first = asyncio.create_task(driver.run_pass())
        second = asyncio.create_task(driver.run_pass())
        await asyncio.sleep(0.2)  # both passes are now waiting on the one in-flight read
        world.reader.gate.set()
        await asyncio.gather(first, second)
    finally:
        world.reader.gate.set()
        driver.dispose()
    assert world.reader.calls == [("NYC", DAY)]
    assert row_of(store).settled_entries == 2


@pytest.mark.asyncio
async def test_reads_run_on_executor_threads_not_the_loop_thread() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    driver = world.driver(PnlStore())
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    assert world.reader.threads
    assert threading.current_thread().name not in world.reader.threads
    assert all(name.startswith("exec_par_pnl_truth") for name in world.reader.threads)


@pytest.mark.asyncio
async def test_results_are_posted_back_with_call_soon_threadsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    loop = asyncio.get_running_loop()
    posted: list[Any] = []
    real = loop.call_soon_threadsafe

    def spy(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        posted.append(callback)
        return real(callback, *args, **kwargs)

    monkeypatch.setattr(loop, "call_soon_threadsafe", spy)
    driver = world.driver(PnlStore())
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    assert posted


@pytest.mark.asyncio
async def test_a_read_timeout_is_pending_and_the_late_final_lands_for_the_next_pass() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    world.reader.gate = threading.Event()
    store = PnlStore()
    driver = world.driver(store, read_timeout_s=0.05)
    try:
        slow = await driver.run_pass()
        assert slow.truth_timeouts == 1
        assert row_of(store).unsettled_entries == 1 and row_of(store).pnl_decimal == 0
        world.reader.gate.set()  # the stuck read finishes; its final is cached on the loop
        await asyncio.sleep(0.2)
        fast = await driver.run_pass()
    finally:
        world.reader.gate.set()
        driver.dispose()
    assert fast.truth_timeouts == 0
    assert row_of(store).settled_entries == 1 and row_of(store).pnl_decimal == D("5.9")


@pytest.mark.asyncio
async def test_a_read_error_makes_the_first_read_pending_never_zero() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.error = TruthReadError("boom")
    store = PnlStore()
    driver = world.driver(store)
    try:
        report = await driver.run_pass()
    finally:
        driver.dispose()
    assert report.truth_errors == 1
    assert (row_of(store).unsettled_entries, row_of(store).settled_entries) == (1, 0)


@pytest.mark.asyncio
async def test_a_failed_revalidation_keeps_the_cached_final_outcome() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore()
    driver = world.driver(store)
    try:
        await driver.run_pass()
        world.reader.error = TruthReadError("transient")
        report = await driver.run_pass()
    finally:
        driver.dispose()
    assert report.truth_errors == 1
    assert row_of(store).settled_entries == 1 and row_of(store).pnl_decimal == D("5.9")


@pytest.mark.asyncio
async def test_dispose_shuts_the_executor_down_and_refuses_further_passes() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    driver = world.driver(PnlStore())
    await driver.run_pass()
    assert any(t.name.startswith("exec_par_pnl_truth") for t in threading.enumerate())
    driver.dispose()
    driver.dispose()  # idempotent
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and any(
        t.name.startswith("exec_par_pnl_truth") for t in threading.enumerate()
    ):
        await asyncio.sleep(0.02)
    assert not any(t.name.startswith("exec_par_pnl_truth") for t in threading.enumerate())
    with pytest.raises(DriverDisposed):
        await driver.run_pass()


# -- persistence, trigger seq, failures ------------------------------------------------------


@pytest.mark.asyncio
async def test_settled_pnl_seq_is_monotonic_and_moves_only_when_a_row_changes() -> None:
    world = World()
    world.entry(YES_NY)
    store = PnlStore()
    driver = world.driver(store)
    try:
        assert driver.settled_pnl_seq() == 0
        await driver.run_pass()
        after_first = driver.settled_pnl_seq()
        await driver.run_pass()  # nothing changed
        assert driver.settled_pnl_seq() == after_first
        world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
        await driver.run_pass()  # a settlement arrived
    finally:
        driver.dispose()
    assert after_first == 1 and driver.settled_pnl_seq() == 2


@pytest.mark.asyncio
async def test_a_persist_failure_raises_the_typed_error_and_does_not_advance_the_seq() -> None:
    world = World()
    world.entry(YES_NY)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore()
    store.error = OSError("disk")
    driver = world.driver(store)
    try:
        with pytest.raises(SettledPnlPersistError) as caught:
            await driver.run_pass()
    finally:
        driver.dispose()
    assert isinstance(caught.value.__cause__, OSError)
    assert driver.settled_pnl_seq() == 0
    assert "4" not in str(caught.value)  # no amounts in the message


@pytest.mark.asyncio
async def test_a_source_read_failure_propagates_and_nothing_is_written() -> None:
    world = World()
    world.entry(YES_NY)
    world.sources_error = OSError("slot table")
    store = PnlStore()
    driver = world.driver(store)
    try:
        with pytest.raises(SourceReadError):
            await driver.run_pass()
    finally:
        driver.dispose()
    assert store.writes == 0 and driver.settled_pnl_seq() == 0


# -- cent quantization -----------------------------------------------------------------------


def test_cent_cost_is_bankers_rounding_to_the_cent_the_same_rule_as_the_spend_audit() -> None:
    assert cent_cost(D("0.005")) == D("0.00")
    assert cent_cost(D("0.015")) == D("0.02")
    assert cent_cost(D("4.1049")) == D("4.10")
    for value in (D("0.005"), D("0.015"), D("0.0149"), D("7.2251")):
        assert cent_cost(value) == value.quantize(CENT, ROUND_HALF_EVEN)


@pytest.mark.asyncio
async def test_each_fill_cost_is_quantized_before_summing() -> None:
    world = World()
    for hour in (15, 16):
        world.entry(YES_NY, qty="1", cost="0.005", fee="0", hour=hour)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80)  # both lose: pnl = -sum(cost)
    store = PnlStore()
    driver = world.driver(store)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    # per-fill: 0.005 -> 0.00 twice = 0; sum-then-quantize would give 0.01
    assert row_of(store).pnl_decimal == 0


# -- N-A: the floor stub rows ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_row_covers_only_post_floor_entries_and_the_whole_day_row_covers_both() -> None:
    floor_ts = ns_at(DAY_S, 18)
    world = World()
    world.entry(YES_NY, hour=12)  # pre-floor: loses
    world.entry(YES_NY, hour=20, cost="3")  # post-floor: wins
    world.entry(YES_NY, hour=18, cost="2")  # armed exactly at the floor: post-floor
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    store = PnlStore(StageReset(floor_ts, "k_change", None))
    driver = world.driver(store)
    try:
        report = await driver.run_pass()
    finally:
        driver.dispose()
    whole, stub = store.days[DAY_S], store.stubs[DAY_S]
    assert whole.settled_entries == 3 and stub.settled_entries == 2
    assert stub.pnl_decimal == (D(10) - D(3) - D("0.1")) + (D(10) - D(2) - D("0.1"))
    assert whole.pnl_decimal == stub.pnl_decimal + (D(10) - D(4) - D("0.1"))
    assert report.stub_days == 1


@pytest.mark.asyncio
async def test_a_pre_floor_loss_stays_out_of_the_stub_even_when_it_is_the_only_entry_that_day() -> (
    None
):
    world = World()
    world.entry(YES_NY, hour=12)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 80)
    store = PnlStore(StageReset(ns_at(DAY_S, 18), "k_change", None))
    driver = world.driver(store)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    assert store.days[DAY_S].pnl_decimal == D("-4.1")
    assert DAY_S not in store.stubs  # no post-floor entry, no stub row


@pytest.mark.asyncio
async def test_no_stage_floor_means_no_stub_rows() -> None:
    world = World()
    world.entry(YES_NY)
    store = PnlStore(None)
    driver = world.driver(store)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    assert store.stubs == {}


@pytest.mark.asyncio
async def test_stub_pending_and_ambiguous_counts_follow_the_same_rules() -> None:
    world = World()
    world.entry(YES_NY, hour=20, ambiguous_mark=True)
    store = PnlStore(StageReset(ns_at(DAY_S, 18), "k_change", None))
    driver = world.driver(store)
    try:
        await driver.run_pass()
    finally:
        driver.dispose()
    assert store.stubs[DAY_S].ambiguous_entries == 1
    assert store.stubs[DAY_S].pnl_decimal == D("-4.1")


@pytest.mark.asyncio
async def test_rows_land_in_the_real_latch_under_the_day_and_stub_keys(
    tmp_path: Path,
) -> None:
    class _KV:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def get(self, key: str) -> bytes | None:
            return self.data.get(key)

        def set(self, key: str, value: bytes) -> None:
            self.data[key] = value

        def keys_with_prefix(self, prefix: str) -> list[str]:
            return sorted(k for k in self.data if k.startswith(prefix))

    world = World()
    world.entry(YES_NY, hour=20)
    world.reader.truth[("NYC", DAY)] = tr("NYC", 72)
    with open_submit_intent_latch(_KV(), tmp_path / "s.db") as latch:
        latch.write_stage_reset(StageReset(ns_at(DAY_S, 18), "k_change", None))
        driver = world.driver(latch)
        try:
            await driver.run_pass()
        finally:
            driver.dispose()
        assert latch.read_settled_pnl_day(DAY_S) is not None
        stub = latch.read_floor_stub_pnl_day(DAY_S)
        assert stub is not None and stub.pnl_decimal == D("5.9")
