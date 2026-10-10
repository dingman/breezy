"""EXEC-PAR WP1: pure slot admission model (inert, domain layer)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from breezy.domain.exec_slots import (
    Admit,
    SlotRecord,
    SlotTableView,
    Wait,
    admit,
)

NOW = 1_000_000_000_000
SLUGS = ["a", "b", "c", "d"]

slot_st = st.builds(
    SlotRecord,
    key=st.text(alphabet="xyz", min_size=1, max_size=4),
    slug=st.sampled_from(SLUGS),
    is_exit=st.booleans(),
)
table_st = st.builds(
    SlotTableView,
    open_slots=st.lists(slot_st, max_size=5).map(tuple),
    unreadable_slots=st.integers(min_value=0, max_value=2),
    cooloff=st.lists(st.tuples(st.sampled_from(SLUGS), st.integers(0, 2 * NOW)), max_size=3).map(
        tuple
    ),
)


def _table(
    slots: tuple[SlotRecord, ...] = (),
    unreadable: int = 0,
    cooloff: tuple[tuple[str, int], ...] = (),
) -> SlotTableView:
    return SlotTableView(open_slots=slots, unreadable_slots=unreadable, cooloff=cooloff)


def _entry(slug: str, key: str = "k") -> SlotRecord:
    return SlotRecord(key=key, slug=slug, is_exit=False)


@given(table_st, st.sampled_from(SLUGS), st.booleans(), st.booleans())
def test_admit_k1_equals_is_latched_for_any_table_entries_and_exits(
    table: SlotTableView, slug: str, is_exit: bool, halted: bool
) -> None:
    latched = bool(table.open_slots) or table.unreadable_slots > 0
    result = admit(table, slug, is_exit, 1, halted, NOW)
    assert isinstance(result, Wait) == latched
    assert isinstance(result, Admit) == (not latched)


def test_admit_denies_same_slug() -> None:
    table = _table((_entry("a"),))
    for is_exit in (False, True):
        assert admit(table, "a", is_exit, 3, False, NOW) == Wait("slug_open")
    assert admit(table, "b", False, 3, False, NOW) == Admit()


def test_admit_k_full_entries_only_when_k_gt_1() -> None:
    table = _table((_entry("a", "1"), _entry("b", "2")))
    assert admit(table, "c", False, 2, False, NOW) == Wait("k_full")
    assert admit(table, "c", False, 3, False, NOW) == Admit()
    assert admit(table, "c", True, 2, False, NOW) == Admit()
    # k == 1 denies everything while a slot is open.
    assert isinstance(admit(table, "c", False, 1, False, NOW), Wait)
    assert isinstance(admit(table, "c", True, 1, False, NOW), Wait)


def test_exits_k_exempt_and_cooloff_exempt_only_when_k_gt_1() -> None:
    full = _table((_entry("a", "1"), _entry("b", "2")))
    cooling = _table(cooloff=(("c", NOW + 10),))
    assert admit(full, "c", True, 2, False, NOW) == Admit()
    assert admit(cooling, "c", True, 2, False, NOW) == Admit()
    assert admit(cooling, "c", False, 2, False, NOW) == Wait("cooloff")
    # Exit-flagged open slots do not count toward K when k > 1 ...
    exit_slot = SlotRecord(key="x", slug="a", is_exit=True)
    assert admit(_table((exit_slot,)), "b", False, 2, False, NOW) == Admit()
    mixed = _table((_entry("a"), SlotRecord("x", "b", True)))
    assert admit(mixed, "c", False, 2, False, NOW) == Admit()
    # ... but at k == 1 any open slot denies, exit-flagged or not.
    assert admit(_table((exit_slot,)), "b", False, 1, False, NOW) == Wait("slot_open")
    assert admit(_table((exit_slot,)), "b", True, 1, False, NOW) == Wait("slot_open")
    # k == 1 has no cool-off or K logic beyond the latch.
    assert admit(cooling, "c", True, 1, False, NOW) == Admit()


def test_quarantine_denies_exits() -> None:
    table = _table(unreadable=1)
    for k in (1, 2, 5):
        for is_exit in (False, True):
            assert admit(table, "a", is_exit, k, False, NOW) == Wait("quarantine")


def test_entry_halt_denies_entries_not_exits() -> None:
    table = _table()
    assert admit(table, "a", False, 2, True, NOW) == Wait("entry_halt")
    assert admit(table, "a", True, 2, True, NOW) == Admit()


def test_cooloff_applies_after_fill_retire() -> None:
    table = _table(cooloff=(("a", NOW + 1),))
    assert admit(table, "a", False, 2, False, NOW) == Wait("cooloff")
    assert admit(table, "b", False, 2, False, NOW) == Admit()
    # Expired exactly at until_ns.
    assert admit(table, "a", False, 2, False, NOW + 1) == Admit()


@given(table_st, st.sampled_from(SLUGS), st.booleans(), st.integers(1, 4), st.booleans())
def test_admit_pure_deterministic(
    table: SlotTableView, slug: str, is_exit: bool, k: int, halted: bool
) -> None:
    before = (table.open_slots, table.unreadable_slots, table.cooloff)
    first = admit(table, slug, is_exit, k, halted, NOW)
    second = admit(table, slug, is_exit, k, halted, NOW)
    assert first == second
    assert before == (table.open_slots, table.unreadable_slots, table.cooloff)
