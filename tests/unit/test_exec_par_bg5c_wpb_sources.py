"""EXEC-PAR BG-5c WP-B (R2, R3, A2, port failure contract): durable day sources."""

from __future__ import annotations

import ast
import datetime as dt
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.domain.exec_intent import (
    FILL_BY_FINGERPRINT_KEY_PREFIX,
    FILL_KEY_PREFIX,
    utc_day_for_ns,
)
from breezy.runtime import exec_par_durable_sources as mod
from breezy.runtime.exec_par_durable_sources import (
    AuditStatus,
    CacheFill,
    DurableSources,
    SpendAuditor,
    StoreIntentSource,
    counters_expected_from,
    day_bounds_from_offsets,
    terminal_fill,
)
from breezy.runtime.exec_par_governed_days import governed_days_for
from breezy.runtime.exec_par_reconcile import (
    SlotDayCounts,
    UnattributableFill,
    reconcile_day,
)
from breezy.runtime.exec_par_records import AmbiguousRow, EpochRow
from breezy.runtime.exec_par_settled_pnl import SETTLEMENT_DEADLINE_DAYS
from breezy.runtime.submit_intent import history_key

S = 1_000_000_000
H = 3_600 * S
D = Decimal
OFFSETS = {"KNYC": -5.0, "KSFO": -8.0}
GOV = governed_days_for(list(OFFSETS), OFFSETS.__getitem__)


def ns_at(day: str, hour: int = 15) -> int:
    moment = dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")
    return int(moment.timestamp()) * S


def station_of(slug: str) -> str | None:
    if "nyc" in slug:
        return "KNYC"
    if "sfo" in slug:
        return "KSFO"
    return None


@dataclass(frozen=True)
class Intent:
    intent_id: str
    fingerprint: str
    created_ns: int
    slug: str | None
    is_exit: bool = False


@dataclass(frozen=True)
class Rec:
    venue_order_id: str
    client_order_id: str
    order_side: str
    cumulative_qty: Decimal
    cumulative_cost: Decimal


def decode_rec(raw: bytes) -> Rec:
    body = json.loads(raw.decode())
    return Rec(body["v"], body["c"], body["s"], Decimal(body["q"]), Decimal(body["k"]))


class Intents:
    def __init__(self) -> None:
        self.items: list[Intent] = []
        self.error: Exception | None = None

    def all_intents(self) -> Iterable[Intent]:
        if self.error is not None:
            raise self.error
        return tuple(self.items)


class Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.error: Exception | None = None
        self.reads = 0

    def get(self, key: str) -> bytes | None:
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.data.get(key)


class Marks:
    def __init__(self) -> None:
        self.rows: dict[str, list[AmbiguousRow]] = {}
        self.error: Exception | None = None

    def read_ambiguous(self, day: str) -> tuple[AmbiguousRow, ...]:
        if self.error is not None:
            raise self.error
        return tuple(self.rows.get(day, ()))


@dataclass
class World:
    intents: Intents = field(default_factory=Intents)
    store: Store = field(default_factory=Store)
    marks: Marks = field(default_factory=Marks)
    n: int = 0

    def entry(
        self,
        slug: str,
        created_ns: int,
        *,
        fill: tuple[str, str] | None = None,
        is_exit: bool = False,
        side: str = "BUY",
    ) -> Intent:
        self.n += 1
        intent = Intent(f"i{self.n}", f"fp{self.n}", created_ns, slug, is_exit)
        self.intents.items.append(intent)
        if fill is not None:
            self.fill_for(intent, fill, side)
        return intent

    def fill_for(self, intent: Intent, fill: tuple[str, str], side: str = "BUY") -> None:
        qty, cost = fill
        vid = f"v-{intent.intent_id}"
        day = utc_day_for_ns(intent.created_ns).isoformat()
        self.store.data[f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{intent.fingerprint}"] = (
            vid.encode()
        )
        body = {"v": vid, "c": f"c-{intent.intent_id}", "s": side, "q": qty, "k": cost}
        self.store.data[f"{FILL_KEY_PREFIX}{vid}"] = json.dumps(body).encode()

    def mark(
        self, intent: Intent, *, day: str, station: str = "KNYC", arm_ns: int | None = None
    ) -> None:
        row = AmbiguousRow(
            intent_id=intent.intent_id,
            source="armed_post_boot",
            day=day,
            arm_ns=intent.created_ns if arm_ns is None else arm_ns,
            attribution="slot",
            ts_ns=1,
            station=station,
        )
        self.marks.rows.setdefault(day, []).append(row)

    def sources(self, auditor: SpendAuditor | None = None) -> DurableSources:
        return DurableSources(
            intents=self.intents,
            store=self.store,
            decode_fill=decode_rec,
            governed=GOV,
            station_of=station_of,
            ambiguous=self.marks,
            auditor=auditor,
        )


DAY1, DAY2 = "2026-10-12", "2026-10-13"


# -- entry fill count (item 1) ---------------------------------------------------


def test_entry_fills_are_counted_per_entry_day_by_the_stations_own_standard_time() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    w.entry("m-sfo", ns_at(DAY1), fill=("5", "2"))
    # 04:00Z on the 13th is still the 12th for NYC (UTC-5) and the 12th for SFO
    w.entry("m-nyc", ns_at(DAY2, 4), fill=("3", "1"))
    w.entry("m-nyc", ns_at(DAY2), fill=("2", "1"))
    src = w.sources()
    assert src.entry_fill_count(DAY1) == 3
    assert src.entry_fill_count(DAY2) == 1


def test_a_posted_entry_with_no_fill_is_not_a_filled_entry_and_zero_is_a_real_zero() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1))
    src = w.sources()
    reading = src.fills_reading(DAY1)
    assert (reading.ok, reading.value, reading.failure) == (True, 0, None)
    assert src.entry_fill_count(DAY1) == 0


def test_no_intents_at_all_is_an_ok_empty_result_not_a_failure() -> None:
    src = World().sources()
    for reading in (src.fills_reading(DAY1), src.spend_reading(DAY1)):
        assert reading.ok is True
    assert src.fills_reading(DAY1).value == 0
    assert src.spend_reading(DAY1).value == D(0)
    assert src.slot_counts(DAY1) == SlotDayCounts(0, 0)


def test_partial_fills_count_once_and_spend_is_the_terminal_record_only() -> None:
    w = World()
    intent = w.entry("m-nyc", ns_at(DAY1), fill=("3", "1.2"))
    w.fill_for(intent, ("7", "2.8"))  # the client's monotone rewrite of the SAME venue order
    src = w.sources()
    assert src.entry_fill_count(DAY1) == 1
    assert src.spend_reading(DAY1).value == D("2.8")  # never 1.2 + 2.8


def test_terminal_fill_is_the_max_cumulative_qty_never_a_sum() -> None:
    a = Rec("v", "c", "BUY", D("3"), D("1.2"))
    b = Rec("v", "c", "BUY", D("7"), D("2.8"))
    assert terminal_fill([a, b]) is b
    assert terminal_fill([b, a]) is b
    assert terminal_fill([a]) is a
    with pytest.raises(ValueError):
        terminal_fill([])
    with pytest.raises(ValueError):  # equal qty, different cost: ambiguous terminal
        terminal_fill([a, Rec("v", "c", "BUY", D("3"), D("1.3"))])


def test_an_exit_order_is_excluded_from_counts_and_spend() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "9"), is_exit=True, side="SELL")
    src = w.sources()
    assert src.entry_fill_count(DAY1) == 1
    assert src.spend_reading(DAY1).value == D("4")
    assert src.slot_counts(DAY1) == SlotDayCounts(1, 0)


def test_a_missing_station_on_a_filled_entry_is_unattributable_and_fails() -> None:
    w = World()
    w.entry("m-unknown", ns_at(DAY1), fill=("10", "4"))
    src = w.sources()
    with pytest.raises(UnattributableFill):
        src.entry_fill_count(DAY1)
    reading = src.fills_reading(DAY1)
    assert reading.ok is False and reading.value is None
    assert reading.failure is not None and reading.failure.reason == "unattributable"
    assert src.spend_reading(DAY1).ok is False
    assert src.ledger_spend(DAY1) is None


def test_a_slugless_entry_poisons_slot_counts_but_not_the_fill_count() -> None:
    w = World()
    w.intents.items.append(Intent("i9", "fp9", ns_at(DAY1), None))
    src = w.sources()
    assert src.slot_counts(DAY1) is None  # posted count cannot be trusted
    assert src.entry_fill_count(DAY1) == 0  # but no fill is involved


def test_an_unattributable_entry_only_poisons_the_days_open_at_its_arm_time() -> None:
    w = World()
    w.intents.items.append(Intent("old", "fpold", ns_at("2026-09-01"), None, False))
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    src = w.sources()
    assert src.slot_counts(DAY1) == SlotDayCounts(1, 0)
    assert src.entry_fill_count(DAY1) == 1
    assert src.slot_counts("2026-09-01") is None


def test_a_store_or_slot_read_failure_is_a_typed_failure_never_zero() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    w.store.error = OSError("disk")
    src = w.sources()
    assert src.entry_fill_count(DAY1) is None
    assert src.slot_counts(DAY1) is None
    assert src.ledger_spend(DAY1) is None
    failure = src.fills_reading(DAY1).failure
    assert failure is not None and failure.reason == "read_error"
    assert {f.source for f in src.failures} >= {"fills"}

    w2 = World()
    w2.intents.error = TimeoutError("slow")
    src2 = w2.sources()
    assert src2.entry_fill_count(DAY1) is None
    assert src2.slot_counts(DAY1) is None
    assert src2.spend_reading(DAY1).ok is False


def test_a_fingerprint_index_without_a_fill_record_is_corrupt_not_a_missing_fill() -> None:
    w = World()
    intent = w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    del w.store.data[f"{FILL_KEY_PREFIX}v-{intent.intent_id}"]
    src = w.sources()
    assert src.entry_fill_count(DAY1) is None
    failure = src.fills_reading(DAY1).failure
    assert failure is not None and failure.reason == "corrupt"


@pytest.mark.parametrize("raw", [b"not json", b'{"v":"x"}'])
def test_an_undecodable_fill_record_is_corrupt(raw: bytes) -> None:
    w = World()
    intent = w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    w.store.data[f"{FILL_KEY_PREFIX}v-{intent.intent_id}"] = raw
    failure = w.sources().fills_reading(DAY1).failure
    assert failure is not None and failure.reason == "corrupt"


def test_a_negative_or_nonfinite_cost_is_corrupt() -> None:
    for cost in ("-1", "NaN"):
        w = World()
        w.entry("m-nyc", ns_at(DAY1), fill=("10", cost))
        failure = w.sources().spend_reading(DAY1).failure
        assert failure is not None and failure.reason == "corrupt"


def test_a_zero_quantity_record_is_not_a_filled_entry() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("0", "0"))
    src = w.sources()
    assert src.entry_fill_count(DAY1) == 0
    assert src.spend_reading(DAY1).value == D(0)


def test_a_buy_side_mismatch_on_an_entry_is_unattributable() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"), side="SELL")  # not an exit per the slot
    with pytest.raises(UnattributableFill):
        w.sources().entry_fill_count(DAY1)


def test_a_repeated_intent_id_is_counted_once() -> None:
    w = World()
    intent = w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    w.intents.items.append(intent)  # open slot AND history copy of the same intent
    src = w.sources()
    assert src.entry_fill_count(DAY1) == 1
    assert src.slot_counts(DAY1) == SlotDayCounts(1, 0)
    assert src.spend_reading(DAY1).value == D(4)


def test_the_join_is_exact_on_the_fingerprint_and_the_utc_day_of_the_intent() -> None:
    w = World()
    intent = w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    day = utc_day_for_ns(intent.created_ns).isoformat()
    other = f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{intent.fingerprint}"
    # move the index to a different fingerprint: the intent no longer joins to any fill
    w.store.data[f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:zz"] = w.store.data.pop(other)
    assert w.sources().entry_fill_count(DAY1) == 0


# -- spend (item 3, R3) ----------------------------------------------------------


def test_spend_sums_terminal_costs_per_entry_day() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4.25"))
    w.entry("m-sfo", ns_at(DAY1), fill=("5", "2.5"))
    w.entry("m-nyc", ns_at(DAY2), fill=("1", "0.5"))
    src = w.sources()
    assert src.ledger_spend(DAY1) == D("6.75")
    assert src.ledger_spend(DAY2) == D("0.5")


# -- AMBIGUOUS counts (item 2, R2) -------------------------------------------------


def test_ambiguous_counts_come_from_the_mark_rows_by_their_stored_arm_ns() -> None:
    w = World()
    a = w.entry("m-nyc", ns_at(DAY1))
    b = w.entry("m-nyc", ns_at(DAY1))
    w.entry("m-nyc", ns_at(DAY1))
    w.mark(a, day=DAY1)
    w.mark(b, day=DAY1)
    counts = w.sources().slot_counts(DAY1)
    assert counts == SlotDayCounts(posted_entries=3, ambiguous=2)


def test_a_mark_whose_arm_ns_lands_on_another_day_is_unattributable() -> None:
    w = World()
    a = w.entry("m-nyc", ns_at(DAY1))
    w.mark(a, day=DAY1, arm_ns=ns_at(DAY2))  # keyed under DAY1, armed on DAY2
    src = w.sources()
    assert src.slot_counts(DAY1) is None
    failure = src.slots_reading(DAY1).failure
    assert failure is not None and failure.reason == "unattributable"


def test_an_unattributed_or_unknown_station_mark_is_unattributable() -> None:
    w = World()
    a = w.entry("m-nyc", ns_at(DAY1))
    w.mark(a, day=DAY1, station="unattributed")
    assert w.sources().slot_counts(DAY1) is None
    w2 = World()
    w2.mark(w2.entry("m-nyc", ns_at(DAY1)), day=DAY1, station="NOWHERE")
    assert w2.sources().slot_counts(DAY1) is None


def test_ambiguous_read_failure_is_a_failure_and_unattributed_marks_are_counted_apart() -> None:
    w = World()
    w.marks.error = OSError("db")
    assert w.sources().slot_counts(DAY1) is None
    w2 = World()
    ghost = Intent("ghost", "fpg", 5, None)
    w2.marks.rows["unattributed"] = [
        AmbiguousRow(
            ghost.intent_id, "unknown", "unattributed", 5, "unattributed", 5, "unattributed"
        )
    ]
    reading = w2.sources().unattributed_ambiguous_reading()
    assert (reading.ok, reading.value) == (True, 1)
    w2.marks.error = OSError("db")
    assert w2.sources().unattributed_ambiguous_reading().ok is False


# -- the spend audit (item 3, A2) ---------------------------------------------------


class Cache:
    def __init__(self, fills: list[CacheFill] | None = None) -> None:
        self.fills = fills
        self.error: Exception | None = None

    def order_fills(self) -> Iterable[CacheFill] | None:
        if self.error is not None:
            raise self.error
        return self.fills


BOOT = ns_at(DAY2, 0)
LOOKBACK = 60 * 60 * S  # 60 min


def day_start(day: str) -> int:
    return day_bounds_from_offsets(OFFSETS)(day)[0]


def auditor(cache: Cache | None, *, boot: int = BOOT, lookback: int = LOOKBACK) -> SpendAuditor:
    return SpendAuditor(
        cache=cache,
        governed=GOV,
        station_of=station_of,
        boot_ts_ns=boot,
        lookback_ns=lookback,
        day_start_ns=day_start,
    )


def cfill(slug: str, at: int, cost: str, side: str = "BUY", coid: str = "c") -> CacheFill:
    return CacheFill(client_order_id=coid, slug=slug, arm_ns=at, order_side=side, cost=D(cost))


def test_day_bounds_are_the_union_over_the_governed_stations() -> None:
    start, end = day_bounds_from_offsets(OFFSETS)(DAY1)
    assert start == ns_at(DAY1, 0) + 5 * H  # NYC rolls first, at 05:00Z
    assert end == ns_at(DAY1, 0) + 24 * H + 8 * H  # SFO rolls last, at 08:00Z next day


def test_audit_full_coverage_match() -> None:
    cache = Cache([cfill("m-nyc", ns_at(DAY1), "4.25"), cfill("m-sfo", ns_at(DAY1), "2.5")])
    # boot far after the day, so the boundary rule is the only gate: use a boot just after
    boot = day_start(DAY1) + LOOKBACK
    result = auditor(cache, boot=boot).audit(DAY1, D("6.75"))
    assert result.status is AuditStatus.FULL_MATCH
    assert result.defers_look is False


def test_audit_coverage_boundary_day_start_equal_to_boot_minus_lookback_is_full() -> None:
    cache = Cache([])
    start = day_start(DAY1)
    exact = auditor(cache, boot=start + LOOKBACK).audit(DAY1, D(0))
    assert exact.status is AuditStatus.FULL_MATCH
    one_late = auditor(cache, boot=start + LOOKBACK + 1).audit(DAY1, D(0))
    assert one_late.status is AuditStatus.UNAUDITED
    assert one_late.reason == "partial_coverage"
    assert one_late.defers_look is True


def test_a_partial_coverage_day_is_unaudited_even_when_the_cache_agrees_and_never_a_mismatch() -> (
    None
):
    cache = Cache([cfill("m-nyc", ns_at(DAY1), "999")])  # would mismatch if it were compared
    result = auditor(cache, boot=ns_at(DAY2)).audit(DAY1, D("1"))
    assert result.status is AuditStatus.UNAUDITED


def test_audit_mismatch_is_reported_and_never_green() -> None:
    boot = day_start(DAY1) + LOOKBACK
    cache = Cache([cfill("m-nyc", ns_at(DAY1), "4.25")])
    result = auditor(cache, boot=boot).audit(DAY1, D("6.75"))
    assert result.status is AuditStatus.MISMATCH
    assert result.defers_look is False


def test_a_fill_missing_from_durable_but_present_in_the_cache_is_a_mismatch() -> None:
    boot = day_start(DAY1) + LOOKBACK
    cache = Cache([cfill("m-nyc", ns_at(DAY1), "4")])
    assert auditor(cache, boot=boot).audit(DAY1, D(0)).status is AuditStatus.MISMATCH


def test_cache_exits_and_other_days_are_ignored() -> None:
    boot = day_start(DAY1) + LOOKBACK
    cache = Cache(
        [
            cfill("m-nyc", ns_at(DAY1), "4"),
            cfill("m-nyc", ns_at(DAY1), "9", side="SELL", coid="x"),
            cfill("m-nyc", ns_at(DAY2), "7", coid="y"),
        ]
    )
    assert auditor(cache, boot=boot).audit(DAY1, D("4")).status is AuditStatus.FULL_MATCH


@pytest.mark.parametrize("mode", ["none_port", "none_result", "raises", "timeout"])
def test_unavailable_cache_defers_the_look_it_does_not_fail_it(mode: str) -> None:
    boot = day_start(DAY1) + LOOKBACK
    cache: Cache | None = Cache(None if mode == "none_result" else [])
    if mode == "none_port":
        cache = None
    if mode == "raises" and cache is not None:
        cache.error = RuntimeError("cache closed")
    if mode == "timeout" and cache is not None:
        cache.error = TimeoutError("slow")
    result = auditor(cache, boot=boot).audit(DAY1, D(0))
    assert result.status is AuditStatus.UNAUDITED
    assert result.defers_look is True
    assert result.reason in {"cache_unavailable", "cache_error"}


def test_an_unattributable_cache_fill_leaves_its_candidate_days_unaudited() -> None:
    boot = day_start(DAY1) + LOOKBACK
    cache = Cache([cfill("m-nowhere", ns_at(DAY1), "4")])
    result = auditor(cache, boot=boot).audit(DAY1, D(0))
    assert result.status is AuditStatus.UNAUDITED
    assert result.reason == "cache_unattributable"


def test_unaudited_past_the_settlement_deadline_excludes_the_day() -> None:
    result = auditor(None).audit(DAY1, D(0))
    day = dt.date.fromisoformat(DAY1)
    young = (day + dt.timedelta(days=SETTLEMENT_DEADLINE_DAYS - 1)).isoformat()
    old = (day + dt.timedelta(days=SETTLEMENT_DEADLINE_DAYS)).isoformat()
    assert result.excludes_day(young) is False
    assert result.excludes_day(old) is True
    matched = auditor(Cache([]), boot=day_start(DAY1) + LOOKBACK).audit(DAY1, D(0))
    assert matched.excludes_day(old) is False


def test_the_audit_result_repr_carries_no_amounts() -> None:
    boot = day_start(DAY1) + LOOKBACK
    result = auditor(Cache([cfill("m-nyc", ns_at(DAY1), "123.456")]), boot=boot).audit(
        DAY1, D("654.321")
    )
    assert "123.456" not in repr(result) and "654.321" not in repr(result)


def test_durable_sources_audit_spend_and_ledger_spend_on_mismatch() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    boot = day_start(DAY1) + LOOKBACK
    good = w.sources(auditor(Cache([cfill("m-nyc", ns_at(DAY1), "4")]), boot=boot))
    assert good.audit_spend(DAY1).status is AuditStatus.FULL_MATCH
    assert good.ledger_spend(DAY1) == D(4)
    bad = w.sources(auditor(Cache([cfill("m-nyc", ns_at(DAY1), "5")]), boot=boot))
    assert bad.audit_spend(DAY1).status is AuditStatus.MISMATCH
    assert bad.ledger_spend(DAY1) is None  # BG-1d exclusion path, never a silent pass
    assert any(f.reason == "spend_audit_mismatch" for f in bad.failures)
    unaudited = w.sources(auditor(None))
    assert unaudited.ledger_spend(DAY1) == D(4)  # unaudited defers the look; it is not a failure
    assert unaudited.audit_spend(DAY1).status is AuditStatus.UNAUDITED


def test_audit_spend_is_durable_unreadable_when_the_durable_side_fails() -> None:
    w = World()
    w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    w.store.error = OSError("disk")
    result = w.sources(auditor(Cache([]))).audit_spend(DAY1)
    assert result.status is AuditStatus.DURABLE_UNREADABLE
    assert result.defers_look is False


# -- reconcile protocol fit ----------------------------------------------------------


def test_sources_satisfy_the_reconcile_day_contract() -> None:
    w = World()
    a = w.entry("m-nyc", ns_at(DAY1), fill=("10", "4"))
    w.mark(a, day=DAY1)
    src = w.sources()
    verdict = reconcile_day(
        DAY1,
        stored=None,
        fills=src.entry_fill_count(DAY1),
        slots=src.slot_counts(DAY1),
        spend=src.ledger_spend(DAY1),
        gappy=False,
        expected_counters=False,
        pending=None,
    )
    assert verdict.kind.value == "unchanged"
    w.store.error = OSError("x")
    broken = w.sources()
    verdict2 = reconcile_day(
        DAY1,
        stored=None,
        fills=broken.entry_fill_count(DAY1),
        slots=broken.slot_counts(DAY1),
        spend=broken.ledger_spend(DAY1),
        gappy=False,
        expected_counters=False,
        pending=None,
    )
    assert verdict2.kind.value == "day_excluded"


# -- counters_expected (item 4) --------------------------------------------------------


def epoch(boot: int, stop: int | None = None, k: int = 2) -> EpochRow:
    return EpochRow(commit_sha="c", effective_k=k, force_reason=None, boot_ts=boot, stop_ts=stop)


def expected(epochs: list[EpochRow], now: int) -> Callable[[str], bool]:
    return counters_expected_from(
        lambda: epochs, now_ns=lambda: now, day_bounds_ns=day_bounds_from_offsets(OFFSETS)
    )


def test_counters_are_expected_for_a_day_a_k_gt_1_epoch_overlaps() -> None:
    start, end = day_bounds_from_offsets(OFFSETS)(DAY1)
    check = expected([epoch(start + H, start + 2 * H)], now=end + 100 * H)
    assert check(DAY1) is True
    assert check(DAY2) is False


def test_k1_epochs_never_expect_counters() -> None:
    start, _ = day_bounds_from_offsets(OFFSETS)(DAY1)
    assert expected([epoch(start + H, start + 2 * H, k=1)], now=start + 3 * H)(DAY1) is False


def test_an_open_epoch_runs_to_now_and_an_unclean_one_to_the_next_boot() -> None:
    d1_start, _ = day_bounds_from_offsets(OFFSETS)(DAY1)
    d2_start, d2_end = day_bounds_from_offsets(OFFSETS)(DAY2)
    open_epoch = expected([epoch(d1_start + H)], now=d2_start + H)
    assert open_epoch(DAY1) is True and open_epoch(DAY2) is True
    unclean = expected([epoch(d1_start + H), epoch(d1_start + 2 * H, k=1)], now=d2_end + H)
    assert unclean(DAY1) is True
    assert unclean(DAY2) is False  # the unclean K=2 epoch ended at the next boot


def test_epoch_window_edges_do_not_overlap_the_adjacent_day() -> None:
    start, end = day_bounds_from_offsets(OFFSETS)(DAY1)
    ends_at_day_start = expected([epoch(start - H, start)], now=end)
    assert ends_at_day_start(DAY1) is False
    starts_at_day_end = expected([epoch(end, end + H)], now=end + 2 * H)
    assert starts_at_day_end(DAY1) is False


def test_an_epoch_read_failure_propagates_loudly() -> None:
    def boom() -> list[EpochRow]:
        raise OSError("db")

    check = counters_expected_from(
        boom, now_ns=lambda: 1, day_bounds_ns=day_bounds_from_offsets(OFFSETS)
    )
    with pytest.raises(OSError):
        check(DAY1)


# -- the slot source over the store ------------------------------------------------------


class KeyedStore:
    def __init__(self, data: dict[str, bytes]) -> None:
        self.data = data

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))


def _decode_intent(raw: bytes) -> Intent:
    body = json.loads(raw.decode())
    return Intent(body["id"], body["fp"], body["ns"], body.get("slug"), body.get("x", False))


def test_store_intent_source_reads_open_and_history_once_each() -> None:
    open_one = Intent("a", "fa", 1, "m-nyc")
    data = {
        history_key("a"): json.dumps({"id": "a", "fp": "fa", "ns": 1, "slug": "m-nyc"}).encode(),
        history_key("b"): json.dumps({"id": "b", "fp": "fb", "ns": 2, "slug": "m-sfo"}).encode(),
        "exec/polymarket_us/intent/breaker": b"ignored",
    }
    source = StoreIntentSource(
        open_intents=lambda: (open_one,), store=KeyedStore(data), decode=_decode_intent
    )
    assert sorted(i.intent_id for i in source.all_intents()) == ["a", "b"]


def test_restated_constants_match_their_owners() -> None:
    from breezy.runtime.exec_par_counter_ingest import UNATTRIBUTED

    assert mod.UNATTRIBUTED == UNATTRIBUTED


def test_store_intent_source_history_prefix_matches_the_latch_key() -> None:
    assert history_key("abc").startswith(mod.HISTORY_KEY_PREFIX)
    assert history_key("abc") == mod.HISTORY_KEY_PREFIX + "abc"


def test_store_intent_source_raises_on_an_undecodable_history_row() -> None:
    data = {history_key("a"): b"garbage"}
    source = StoreIntentSource(
        open_intents=lambda: (), store=KeyedStore(data), decode=_decode_intent
    )
    with pytest.raises(Exception):  # noqa: B017 - any decode failure must surface, never skip
        tuple(source.all_intents())


# -- hygiene ---------------------------------------------------------------------------------


_MODULES = ("exec_par_durable_sources.py", "exec_par_gap_marking.py")
_ROOT = Path(__file__).resolve().parents[2] / "src" / "breezy" / "runtime"


@pytest.mark.parametrize("name", _MODULES)
def test_new_modules_import_no_network_no_evidence_and_never_asdict(name: str) -> None:
    source = (_ROOT / name).read_text()
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported.isdisjoint({"urllib", "socket", "httpx", "requests", "aiohttp"})
    assert "docs/evidence" not in source and "docs.evidence" not in source
    assert "asdict" not in source
    assert "exec.client" not in source and "adapters.polymarket_us.exec" not in source
