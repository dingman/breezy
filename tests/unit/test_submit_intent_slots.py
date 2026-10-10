"""EXEC-PAR WP2: the durable slot table behind ``CURRENT_INTENT_KEY`` (inert).

K=1 must stay byte-identical to the pre-WP2 latch (golden below, captured from
the code before any WP2 change). v2 tables, cool-off, unreadable slots and the
breaker record are exercised through an in-memory store and injected clocks.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from breezy.domain import exec_slots
from breezy.runtime import submit_intent as si
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    CURRENT_INTENT_KEY,
    RetirementReason,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentLatch,
    SubmitIntentLatched,
    SubmitIntentState,
    history_key,
    open_submit_intent_latch,
)
from tests.unit.golden_submit_intent_k1 import run_k1_scenario

FP = "9f3ac0de" + "a1b2c3d4" * 7
FP2 = "cafef00d" + "11" * 28
NOW = 1_700_000_000_000_000_000
SEC = 1_000_000_000
COOLOFF_NS = 120 * SEC
GOLDEN_PATH = Path(__file__).with_name("golden_submit_intent_k1.json")


def _id(n: int) -> str:
    return f"{n:032x}"


class Store:
    def __init__(self, data: dict[str, bytes] | None = None) -> None:
        self.data: dict[str, bytes] = {} if data is None else data
        self.sets: list[str] = []
        self.gets: list[str] = []
        self.fail_get_keys: set[str] = set()
        self.fail_set_after_history = False

    def get(self, key: str) -> bytes | None:
        self.gets.append(key)
        if key in self.fail_get_keys:
            raise OSError("simulated get failure")
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        if (
            self.fail_set_after_history
            and key == CURRENT_INTENT_KEY
            and any(k.startswith("exec/polymarket_us/intent/history/") for k in self.sets)
        ):
            raise OSError("simulated crash before table set")
        self.sets.append(key)
        self.data[key] = value


class Clock:
    def __init__(self, now_ns: int = NOW) -> None:
        self.now_ns = now_ns

    def __call__(self) -> int:
        return self.now_ns


@contextmanager
def _fixed_ids() -> Iterator[None]:
    """Deterministic ``uuid4`` for the latch module (ids 1, 2, 3, ...)."""
    ids = iter(range(1, 50))
    with patch("breezy.runtime.submit_intent.uuid.uuid4", lambda: uuid.UUID(int=next(ids))):
        yield


def _canon(obj: object) -> str:
    return json.dumps(obj, sort_keys=True)


def _rec(
    n: int,
    slug: str | None = None,
    *,
    is_exit: bool = False,
    created: int = NOW,
    fingerprint: str = FP,
) -> dict[str, object]:
    out: dict[str, object] = {
        "v": 1,
        "intent_id": _id(n),
        "fingerprint": fingerprint,
        "created_ns": created,
        "state": "OPEN",
        "retired_ns": None,
        "retirement_reason": None,
    }
    if slug is not None:
        out["slug"] = slug
    if is_exit:
        out["is_exit"] = True
    return out


def _b64(obj: object) -> str:
    return base64.b64encode(_canon(obj).encode("utf-8")).decode("ascii")


def _v2(
    slots: dict[str, object],
    raw: dict[str, str] | None = None,
    cooloff: dict[str, int] | None = None,
) -> bytes:
    return _canon(
        {"v": 2, "slots": slots, "raw_slots": raw or {}, "cooloff": cooloff or {}}
    ).encode("utf-8")


def _table(store: Store) -> dict[str, object]:
    decoded: object = json.loads(store.data[CURRENT_INTENT_KEY])
    assert isinstance(decoded, dict)
    return decoded


def _sub(store: Store, name: str) -> dict[str, object]:
    """One nested object of the stored table (``cooloff``, ``slots``...)."""
    value = _table(store).get(name, {})
    assert isinstance(value, dict)
    return value


@contextmanager
def _latch(
    store: Store,
    tmp_path: Path,
    *,
    k: int = 2,
    predicate: object = True,
    clock: Clock | None = None,
    breaker: bool = True,
) -> Iterator[SubmitIntentLatch]:
    clk = Clock() if clock is None else clock

    def v2_predicate() -> bool:
        if callable(predicate):
            return bool(predicate())
        return bool(predicate)

    with open_submit_intent_latch(
        store,
        tmp_path / "state.db",
        max_slots=k,
        cooloff_ns=COOLOFF_NS,
        v2_predicate=v2_predicate,
        clock_ns=clk,
    ) as latch:
        if breaker and k > 1:
            latch.write_breaker_heartbeat(hb_ns=clk(), resolver_pass_ns=clk())
        store.sets.clear()
        store.gets.clear()
        yield latch


# --------------------------------------------------------------------------
# K=1 byte identity
# --------------------------------------------------------------------------


def test_k1_store_write_sequence_matches_golden_v1() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(golden) == 13
    assert [list(pair) for pair in run_k1_scenario()] == golden


def test_k1_arm_slot_bytes_identical_to_arm(tmp_path: Path) -> None:
    plain, slotted = Store(), Store()
    with _fixed_ids(), open_submit_intent_latch(plain, tmp_path / "a.db") as a:
        first = a.arm(FP, now_ns=NOW)
        a.retire(first.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 1)
    with _fixed_ids(), open_submit_intent_latch(slotted, tmp_path / "b.db") as b:
        second = b.arm_slot(FP, slug="SLUG-A", is_exit=True, now_ns=NOW)
        b.retire(second.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 1)
    assert second.slug is None and second.is_exit is False
    assert slotted.data == plain.data
    assert slotted.sets == plain.sets


def test_slug_key_only_when_set(tmp_path: Path) -> None:
    bare = SubmitIntent(_id(1), FP, NOW, SubmitIntentState.OPEN, None, None)
    assert "slug" not in json.loads(bare.to_bytes())
    assert "is_exit" not in json.loads(bare.to_bytes())
    tagged = SubmitIntent(_id(1), FP, NOW, SubmitIntentState.OPEN, None, None, slug="S-A")
    assert json.loads(tagged.to_bytes())["slug"] == "S-A"
    assert SubmitIntent.from_bytes(tagged.to_bytes()) == tagged
    with _latch(Store(), tmp_path, k=1) as one:
        assert "slug" not in json.loads(one.arm(FP, now_ns=NOW).to_bytes())
    store = Store()
    with _latch(store, tmp_path, k=2) as two:
        armed = two.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
    assert armed.slug == "S-A"
    assert _table(store)["slug"] == "S-A"


def test_v1_reader_ignores_slug_and_cooloff_keys() -> None:
    record = _rec(1, "S-A", is_exit=True)
    record["cooloff"] = {"S-B": NOW + 5}
    parsed = SubmitIntent.from_bytes(_canon(record).encode("utf-8"))
    assert parsed.intent_id == _id(1)
    assert parsed.slug == "S-A"
    plain = {k: v for k, v in record.items() if k not in {"slug", "cooloff", "is_exit"}}
    assert SubmitIntent.from_bytes(_canon(plain).encode("utf-8")).slug is None


def test_v2_table_is_corrupt_in_v1_code(tmp_path: Path) -> None:
    raw = _v2({_id(1): _rec(1, "S-A"), _id(2): _rec(2, "S-B")})
    with pytest.raises(SubmitIntentCorrupt):
        SubmitIntent.from_bytes(raw)
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        assert latch.is_latched() is True
        with pytest.raises(SubmitIntentCorrupt):
            latch.current()


# --------------------------------------------------------------------------
# Atomic arm / retire, crash recovery, downgrade, cool-off
# --------------------------------------------------------------------------


def test_arm_and_retire_are_one_atomic_set(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        a = latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        assert store.sets == [CURRENT_INTENT_KEY]
        assert _table(store)["v"] == 1
        store.sets.clear()
        b = latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW + 1)
        assert store.sets == [CURRENT_INTENT_KEY]
        assert _table(store)["v"] == 2
        store.sets.clear()
        latch.retire(a.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 2)
        assert store.sets == [history_key(a.intent_id), CURRENT_INTENT_KEY]
        assert b.intent_id in store.data[CURRENT_INTENT_KEY].decode()


def test_crash_between_history_and_table_set_recoverable(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        a = latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        b = latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW + 1)
        store.sets.clear()
        store.fail_set_after_history = True
        with pytest.raises(OSError):
            latch.retire(a.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 2)
    assert history_key(a.intent_id) in store.data
    store.fail_set_after_history = False
    store.sets.clear()
    with _latch(store, tmp_path) as restarted:
        repaired = restarted.reconcile_at_startup(
            has_durable_fill_record=lambda _f, _c: False, now_ns=NOW + 3
        )
        assert repaired is not None
        assert [i.intent_id for i in restarted.open_submit_intents()] == [b.intent_id]
        assert restarted.is_open_intent(a.intent_id) is False
    assert _table(store)["v"] == 1


def test_last_retire_writes_valid_v1_retired_with_cooloff(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        a = latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        b = latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW + 1)
        latch.retire(b.intent_id, RetirementReason.STATUS_REPORT_ZERO_FILL_TERMINAL, now_ns=NOW + 2)
        mid = _table(store)
        assert mid["v"] == 1 and mid["state"] == "OPEN" and mid["intent_id"] == a.intent_id
        assert mid["cooloff"] == {"S-B": NOW + 2 + COOLOFF_NS}
        latch.retire(a.intent_id, RetirementReason.ACCEPTED_WITH_DURABLE_FILL, now_ns=NOW + 3)
    final = _table(store)
    assert final["v"] == 1 and final["state"] == "RETIRED"
    assert final["cooloff"] == {"S-A": NOW + 3 + COOLOFF_NS, "S-B": NOW + 2 + COOLOFF_NS}
    parsed = SubmitIntent.from_bytes(store.data[CURRENT_INTENT_KEY])
    assert parsed.state is SubmitIntentState.RETIRED and parsed.intent_id == a.intent_id


def test_exit_and_reject_retires_write_no_cooloff(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        a = latch.arm_slot(FP, slug="S-A", is_exit=True, now_ns=NOW)
        latch.retire(a.intent_id, RetirementReason.ACCEPTED_WITH_DURABLE_FILL, now_ns=NOW + 1)
        assert "cooloff" not in _table(store)
        b = latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW + 2)
        latch.retire(b.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 3)
        assert "cooloff" not in _table(store)


def test_arm_from_empty_preserves_unexpired_cooloff(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        a = latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        latch.retire(a.intent_id, RetirementReason.ACCEPTED_WITH_DURABLE_FILL, now_ns=NOW + 1)
        assert latch.admission_refusal("S-A", False) == "cooloff"
        assert latch.admission_refusal("S-A", True) is None
        with pytest.raises(SubmitIntentLatched):
            latch.arm_slot(FP2, slug="S-A", is_exit=False, now_ns=NOW + 2)
        latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW + 2)
        assert _table(store)["cooloff"] == {"S-A": NOW + 1 + COOLOFF_NS}
        # past expiry the entry is pruned on the next write
        late = NOW + 1 + COOLOFF_NS + 1
        latch.write_breaker_heartbeat(hb_ns=late, resolver_pass_ns=late)
        latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=late)
    assert "S-A" not in _sub(store, "cooloff")


def test_every_slug_open_at_boot_gets_synthetic_cooloff(tmp_path: Path) -> None:
    raw = _v2({_id(1): _rec(1, "S-A"), _id(2): _rec(2, "S-B")})
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        latch.adopt_legacy_open_slugs(lambda _i: None)
        latch.seed_boot_cooloff(now_ns=NOW)
        table = _table(store)
        assert table["v"] == 2
        assert table["cooloff"] == {"S-A": NOW + COOLOFF_NS, "S-B": NOW + COOLOFF_NS}
        latch.retire(_id(1), RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 1)
        latch.retire(_id(2), RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 2)
        assert latch.admission_refusal("S-A", False) == "cooloff"
        assert latch.admission_refusal("S-B", False) == "cooloff"
    one = Store({CURRENT_INTENT_KEY: _canon(_rec(3, "S-C")).encode("utf-8")})
    with _latch(one, tmp_path) as latch:
        latch.adopt_legacy_open_slugs(lambda _i: None)
        latch.seed_boot_cooloff(now_ns=NOW)
    assert _table(one)["v"] == 1 and _table(one)["cooloff"] == {"S-C": NOW + COOLOFF_NS}
    k1 = Store({CURRENT_INTENT_KEY: _canon(_rec(4, "S-D")).encode("utf-8")})
    with _latch(k1, tmp_path, k=1) as latch:
        latch.seed_boot_cooloff(now_ns=NOW)
        assert k1.sets == []


# --------------------------------------------------------------------------
# Unreadable slots, base64, quarantine
# --------------------------------------------------------------------------


def test_retire_of_healthy_slot_preserves_unreadable_slot_bytes_base64(tmp_path: Path) -> None:
    unread = {"weird": "record", "n": 1}
    pre_encoded = _b64({"already": "raw"})
    raw = _v2(
        {_id(1): _rec(1, "S-A"), _id(2): _rec(2, "S-B"), "bad.slot": unread},
        raw={"u-raw": pre_encoded},
    )
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        latch.retire(_id(1), RetirementReason.DEFINITIVE_REJECT, now_ns=NOW)
    table = _table(store)
    assert table["v"] == 2
    assert set(_sub(store, "slots")) == {_id(2)}
    assert table["raw_slots"] == {"u-raw": pre_encoded, "bad.slot": _b64(unread)}


@pytest.mark.parametrize(
    "bad",
    ["!!!not-base64!!!", "abc", "YQ=", "Y Q==", "é"],
)
def test_bad_base64_in_raw_slots_is_whole_table_corruption(tmp_path: Path, bad: str) -> None:
    raw = _v2({_id(1): _rec(1, "S-A")}, raw={"u1": bad})
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        assert latch.is_latched() is True
        assert latch.admission_refusal("S-X", False) == "corrupt"
        assert latch.admission_refusal("S-X", True) == "corrupt"
        with pytest.raises(SubmitIntentCorrupt):
            latch.open_submit_intents()
        with pytest.raises(SubmitIntentLatched):
            latch.arm_slot(FP, slug="S-X", is_exit=False, now_ns=NOW)
    assert store.data[CURRENT_INTENT_KEY] == raw


def test_non_utf8_or_non_json_table_is_whole_table_corruption(tmp_path: Path) -> None:
    for junk in (b"\xff\xfe\x00", b"[1,2]", b"not json"):
        store = Store({CURRENT_INTENT_KEY: junk})
        with _latch(store, tmp_path) as latch:
            assert latch.admission_refusal("S-X", False) == "corrupt"


def test_lone_unreadable_slot_stays_v2(tmp_path: Path) -> None:
    raw = _v2({_id(1): _rec(1, "S-A"), "bad": {"x": 1}})
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        latch.retire(_id(1), RetirementReason.DEFINITIVE_REJECT, now_ns=NOW)
        table = _table(store)
        assert table["v"] == 2 and table["slots"] == {}
        assert table["raw_slots"] == {"bad": _b64({"x": 1})}
        assert latch.open_slot_count() == 1
        assert latch.is_latched() is True


def test_last_healthy_retire_does_not_downgrade_over_unreadable_slot(tmp_path: Path) -> None:
    raw = _v2(
        {_id(1): _rec(1, "S-A"), _id(2): _rec(2, "S-B")},
        raw={"u1": _b64({"y": 2})},
    )
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        latch.retire(_id(1), RetirementReason.DEFINITIVE_REJECT, now_ns=NOW)
        assert _table(store)["v"] == 2
        latch.retire(_id(2), RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 1)
    table = _table(store)
    assert table["v"] == 2 and table["slots"] == {}
    assert set(_sub(store, "raw_slots")) == {"u1"}


def test_unreadable_slot_quarantines_but_healthy_slot_resolvable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    raw = _v2({_id(1): _rec(1, "S-A")}, raw={"u1": _b64({"y": 2})})
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        assert latch.admission_refusal("S-X", False) == "quarantine"
        assert latch.admission_refusal("S-X", True) == "quarantine"
        with pytest.raises(SubmitIntentLatched):
            latch.arm_slot(FP, slug="S-X", is_exit=True, now_ns=NOW)
        assert latch.unreadable_slot_keys() == ("u1",)
        with caplog.at_level(logging.ERROR):
            first = latch.next_open_for_resolution({}, {})
            second = latch.next_open_for_resolution({}, {})
        assert first is not None and first.intent_id == _id(1)
        assert second is not None
        assert sum("u1" in r.getMessage() for r in caplog.records) == 1
        assert latch.is_open_intent(_id(1)) is True
        assert latch.open_slot_count() == 2


def test_legacy_open_adopted_by_context_slug(tmp_path: Path) -> None:
    store = Store({CURRENT_INTENT_KEY: _canon(_rec(1)).encode("utf-8")})
    with _latch(store, tmp_path) as latch:
        assert latch.admission_refusal("S-A", False) == "quarantine"
        assert latch.adopt_legacy_open_slugs(lambda i: "S-A" if i == _id(1) else None) == 1
        assert _table(store)["v"] == 1 and _table(store)["slug"] == "S-A"
        assert latch.admission_refusal("S-A", False) == "slug_open"
        assert latch.admission_refusal("S-B", False) is None
        latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW)
        assert _table(store)["v"] == 2
        assert {i.slug for i in latch.open_submit_intents()} == {"S-A", "S-B"}
    k1 = Store({CURRENT_INTENT_KEY: _canon(_rec(2)).encode("utf-8")})
    with _latch(k1, tmp_path, k=1) as latch:
        assert latch.adopt_legacy_open_slugs(lambda _i: "S-A") == 0
        assert k1.sets == []


def test_legacy_open_without_context_quarantines(tmp_path: Path) -> None:
    raw = _canon(_rec(1)).encode("utf-8")

    def boom(_i: str) -> str | None:
        raise RuntimeError("no context")

    for slug_of in (lambda _i: None, boom):
        store = Store({CURRENT_INTENT_KEY: raw})
        with _latch(store, tmp_path) as latch:
            assert latch.adopt_legacy_open_slugs(slug_of) == 0
            assert latch.unreadable_slot_keys() == (f"?:{_id(1)}",)
            assert latch.admission_refusal("S-X", False) == "quarantine"
            nxt = latch.next_open_for_resolution({}, {})
            assert nxt is not None and nxt.intent_id == _id(1)
            assert store.sets == []


# --------------------------------------------------------------------------
# Admission, arbiter, predicate
# --------------------------------------------------------------------------


def test_arm_slot_uses_domain_admit_as_arbiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, bool, int]] = []
    real = exec_slots.admit

    def spy(
        table: exec_slots.SlotTableView,
        slug: str,
        is_exit: bool,
        k: int,
        entry_halted: bool,
        now_ns: int,
    ) -> exec_slots.Admit | exec_slots.Wait:
        calls.append((slug, is_exit, k))
        return real(table, slug, is_exit, k, entry_halted, now_ns)

    monkeypatch.setattr(si, "admit", spy)
    with _latch(Store(), tmp_path, k=3) as latch:
        latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
    assert calls == [("S-A", False, 3)]


def test_admission_reasons_same_slug_k_full_exit_exempt(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path, k=2) as latch:
        latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        assert latch.admission_refusal("S-A", False) == "slug_open"
        assert latch.admission_refusal("S-A", True) == "slug_open"
        latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW)
        assert latch.admission_refusal("S-C", False) == "k_full"
        assert latch.admission_refusal("S-C", True) is None
        before = dict(store.data)
        assert latch.admission_refusal("S-C", False) == "k_full"
        assert store.data == before  # read-only
        latch.arm_slot(FP, slug="S-C", is_exit=True, now_ns=NOW)
        rec = next(i for i in latch.open_submit_intents() if i.slug == "S-C")
        assert rec.is_exit is True


def test_v2_predicate_false_or_raising_refuses_one_to_two(tmp_path: Path) -> None:
    calls: list[int] = []

    def counting_false() -> bool:
        calls.append(1)
        return False

    def raising() -> bool:
        raise RuntimeError("marker unreadable")

    for predicate in (counting_false, raising):
        calls.clear()
        store = Store()
        with _latch(store, tmp_path, k=2, predicate=predicate) as latch:
            latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
            assert calls == []  # 0 -> 1 never consults the predicate
            before = dict(store.data)
            assert latch.admission_refusal("S-B", False) == "v2_predicate"
            assert latch.admission_refusal("S-B", True) == "v2_predicate"
            with pytest.raises(SubmitIntentLatched) as exc_info:
                latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW)
            assert getattr(exc_info.value, "reason", None) == "v2_predicate"
            assert store.data == before
    store = Store()
    with _latch(store, tmp_path, k=2, predicate=True) as latch:
        latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW)
        assert _table(store)["v"] == 2


def test_concurrent_arm_slot_one_winner_per_slug(tmp_path: Path) -> None:
    store = Store()
    results: list[str] = []
    errors: list[BaseException] = []
    with _latch(store, tmp_path, k=4) as latch:
        barrier = threading.Barrier(8)

        def worker(slug: str) -> None:
            barrier.wait()
            try:
                latch.arm_slot(FP, slug=slug, is_exit=False, now_ns=NOW)
                results.append(slug)
            except SubmitIntentLatched:
                pass
            except Exception as exc:  # noqa: BLE001 - collected and asserted empty below
                errors.append(exc)

        slugs = ["S-A", "S-A", "S-A", "S-A", "S-B", "S-B", "S-B", "S-B"]
        threads = [threading.Thread(target=worker, args=(s,)) for s in slugs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert sorted(results) == ["S-A", "S-B"]
        assert sorted(i.slug or "" for i in latch.open_submit_intents()) == ["S-A", "S-B"]


# --------------------------------------------------------------------------
# Queries, forced K, resolution order
# --------------------------------------------------------------------------


def test_is_open_intent_open_slot_count_max_slots(tmp_path: Path) -> None:
    with _latch(Store(), tmp_path, k=3) as latch:
        assert latch.max_slots() == 3
        assert latch.open_slot_count() == 0
        assert latch.is_open_intent(_id(9)) is False
        a = latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        b = latch.arm_slot(FP2, slug="S-B", is_exit=False, now_ns=NOW + 1)
        assert latch.open_slot_count() == 2
        assert latch.is_open_intent(a.intent_id) and latch.is_open_intent(b.intent_id)
        latch.retire(a.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 2)
        assert latch.is_open_intent(a.intent_id) is False
        assert latch.open_slot_count() == 1
    with (
        pytest.raises(ValueError),
        open_submit_intent_latch(Store(), tmp_path / "x.db", max_slots=0),
    ):
        pass


def test_force_k1_makes_max_slots_one(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with _latch(Store(), tmp_path, k=3) as latch:
        assert latch.k_forced_reason is None
        with caplog.at_level(logging.ERROR):
            latch.force_k1("bucket_outside_frozen_label")
            latch.force_k1("second reason is ignored")
        assert latch.max_slots() == 1
        assert latch.k_forced_reason == "bucket_outside_frozen_label"
        assert sum("forced to K=1" in r.getMessage() for r in caplog.records) == 1
        latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        assert latch.admission_refusal("S-B", False) == "slot_open"


def test_restart_with_k_forced_1_over_open_v2_table_resolves_all_slots_and_downgrades(
    tmp_path: Path,
) -> None:
    raw = _v2(
        {_id(1): _rec(1, "S-A", created=NOW), _id(2): _rec(2, "S-B", created=NOW + 1)},
    )
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path, k=2) as latch:
        latch.force_k1("bucket")
        assert latch.max_slots() == 1
        assert latch.admission_refusal("S-C", False) == "slot_open"
        assert latch.admission_refusal("S-C", True) == "slot_open"
        first = latch.next_open_for_resolution({}, {})
        assert first is not None and first.intent_id == _id(1)
        latch.retire(first.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 5)
        assert _table(store)["v"] == 1  # one slot left: downgraded
        assert latch.admission_refusal("S-C", False) == "slot_open"
        second = latch.next_open_for_resolution({}, {})
        assert second is not None and second.intent_id == _id(2)
        latch.retire(second.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 6)
        assert latch.next_open_for_resolution({}, {}) is None
        assert latch.admission_refusal("S-C", False) is None
        assert latch.is_latched() is False
    assert _table(store)["state"] == "RETIRED"


def test_next_open_for_resolution_orders_by_failures_served_created(tmp_path: Path) -> None:
    raw = _v2(
        {
            _id(1): _rec(1, "S-A", created=NOW),
            _id(2): _rec(2, "S-B", created=NOW + 1),
            _id(3): _rec(3, "S-C", created=NOW + 2),
        }
    )
    with _latch(Store({CURRENT_INTENT_KEY: raw}), tmp_path, k=3) as latch:

        def pick(failures: dict[str, int], served: dict[str, int]) -> str:
            chosen = latch.next_open_for_resolution(failures, served)
            assert chosen is not None
            return chosen.intent_id

        assert pick({}, {}) == _id(1)
        assert pick({_id(1): 2}, {}) == _id(2)
        assert pick({_id(1): 2, _id(2): 2}, {}) == _id(3)
        assert pick({}, {_id(1): 50}) == _id(2)
        assert pick({}, {_id(1): 50, _id(2): 40}) == _id(3)
        assert pick({_id(3): 1}, {_id(1): 9, _id(2): 3}) == _id(2)


def test_next_open_for_resolution_none_on_v1_retired_and_empty(tmp_path: Path) -> None:
    with _latch(Store(), tmp_path, k=1) as latch:
        assert latch.next_open_for_resolution({}, {}) is None
        a = latch.arm(FP, now_ns=NOW)
        got = latch.next_open_for_resolution({}, {})
        assert got is not None and got.intent_id == a.intent_id
        latch.retire(a.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 1)
        assert latch.next_open_for_resolution({}, {}) is None


# --------------------------------------------------------------------------
# Breaker record (latch side only)
# --------------------------------------------------------------------------


def test_breaker_record_single_get_fail_closed_read_and_halted_preserved_across_heartbeat(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = Store()
    with _latch(store, tmp_path, k=2, clock=clock) as latch:
        # healthy: exactly one breaker get per admission call
        assert latch.admission_refusal("S-A", False) is None
        assert store.gets.count(BREAKER_KEY) == 1
        # halted is preserved across heartbeat writes
        latch.write_breaker_halt("duplicate_suspect", ts_ns=NOW + 1)
        latch.write_breaker_heartbeat(hb_ns=NOW + 2, resolver_pass_ns=NOW + 3)
        record = latch.read_breaker_record()
        assert record is not None
        assert record.halted_reason == "duplicate_suspect" and record.halted_ts_ns == NOW + 1
        assert (record.hb_ns, record.resolver_pass_ns) == (NOW + 2, NOW + 3)
        latch.write_breaker_halt("second", ts_ns=NOW + 9)  # sticky: first reason kept
        again = latch.read_breaker_record()
        assert again is not None and again.halted_reason == "duplicate_suspect"
        store.gets.clear()
        assert latch.admission_refusal("S-A", False) == "breaker_halted"
        assert store.gets.count(BREAKER_KEY) == 1
        assert latch.admission_refusal("S-A", True) is None  # exits never halted
        # fail closed: garbled / get raises -> deny entries, never raise
        store.data[BREAKER_KEY] = b"{garbled"
        assert latch.admission_refusal("S-A", False) == "breaker_unreadable"
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_breaker_record()
        with pytest.raises(SubmitIntentCorrupt):  # never overwrite an unreadable record
            latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW)
        assert store.data[BREAKER_KEY] == b"{garbled"
        store.data.pop(BREAKER_KEY)
        store.fail_get_keys.add(BREAKER_KEY)
        assert latch.admission_refusal("S-A", False) == "breaker_unreadable"


def test_breaker_absent_stale_heartbeat_and_stale_resolver_deny_entries_k_gt_1_only(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = Store()
    with _latch(store, tmp_path, k=2, clock=clock, breaker=False) as latch:
        assert latch.admission_refusal("S-A", False) is None  # grace after boot
        clock.now_ns = NOW + 61 * SEC
        assert latch.admission_refusal("S-A", False) == "breaker_absent"
        assert latch.admission_refusal("S-A", True) is None
        latch.write_breaker_heartbeat(hb_ns=clock.now_ns, resolver_pass_ns=clock.now_ns)
        assert latch.admission_refusal("S-A", False) is None
        clock.now_ns += 60 * SEC
        assert latch.admission_refusal("S-A", False) is None  # exactly at the bound
        clock.now_ns += 1
        assert latch.admission_refusal("S-A", False) == "breaker_heartbeat_stale"
        latch.write_breaker_heartbeat(hb_ns=clock.now_ns, resolver_pass_ns=clock.now_ns - 601 * SEC)
        assert latch.admission_refusal("S-A", False) == "breaker_resolver_stale"
        latch.write_breaker_heartbeat(hb_ns=clock.now_ns, resolver_pass_ns=clock.now_ns - 600 * SEC)
        assert latch.admission_refusal("S-A", False) is None
    k1 = Store()
    with _latch(k1, tmp_path, k=1, clock=Clock(NOW + 10_000 * SEC)) as latch:
        assert latch.admission_refusal("S-A", False) is None
        assert BREAKER_KEY not in k1.gets and k1.sets == []
