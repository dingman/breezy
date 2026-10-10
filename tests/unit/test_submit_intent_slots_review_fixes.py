"""EXEC-PAR WP2 review follow-ups: fail-closed boot, cool-off continuity, breaker clocks."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    CURRENT_INTENT_KEY,
    RetirementReason,
    SubmitIntentBootOrderError,
    SubmitIntentCorrupt,
    SubmitIntentLatched,
    history_key,
)
from tests.unit.test_submit_intent_slots import (
    COOLOFF_NS,
    FP,
    FP2,
    NOW,
    SEC,
    Clock,
    Store,
    _b64,
    _canon,
    _id,
    _latch,
    _rec,
    _sub,
    _table,
    _v2,
)


def _retired_record(n: int, slug: str, retired_ns: int, reason: str) -> dict[str, object]:
    out = _rec(n, slug)
    out.update({"state": "RETIRED", "retired_ns": retired_ns, "retirement_reason": reason})
    return out


def test_reconcile_over_only_unreadable_slots_raises_not_none(tmp_path: Path) -> None:
    store = Store({CURRENT_INTENT_KEY: _v2({}, raw={"u1": _b64({"y": 2})})})
    with _latch(store, tmp_path) as latch, pytest.raises(SubmitIntentCorrupt):
        latch.reconcile_at_startup(has_durable_fill_record=lambda _f, _c: False, now_ns=NOW)


def test_reconcile_repairs_then_raises_when_only_unreadable_remain(tmp_path: Path) -> None:
    store = Store({CURRENT_INTENT_KEY: _v2({_id(1): _rec(1, "S-A")}, raw={"u1": _b64({"y": 2})})})
    store.data[history_key(_id(1))] = _canon(
        _retired_record(1, "S-A", NOW + 1, "DEFINITIVE_REJECT")
    ).encode("utf-8")
    with _latch(store, tmp_path) as latch, pytest.raises(SubmitIntentCorrupt):
        latch.reconcile_at_startup(has_durable_fill_record=lambda _f, _c: False, now_ns=NOW + 2)
    assert _table(store)["slots"] == {}
    assert set(_sub(store, "raw_slots")) == {"u1"}


def test_reconcile_with_healthy_slot_and_unreadable_returns_the_open_slot(tmp_path: Path) -> None:
    store = Store({CURRENT_INTENT_KEY: _v2({_id(1): _rec(1, "S-A")}, raw={"u1": _b64({"y": 2})})})
    with _latch(store, tmp_path) as latch:
        got = latch.reconcile_at_startup(has_durable_fill_record=lambda _f, _c: False, now_ns=NOW)
        assert got is not None and got.intent_id == _id(1)


def test_history_repair_at_k_gt_1_preserves_cooloff_and_earns_its_own(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        x = latch.arm_slot(FP, slug="S-X", is_exit=False, now_ns=NOW)
        latch.retire(x.intent_id, RetirementReason.ACCEPTED_WITH_DURABLE_FILL, now_ns=NOW + 1)
        a = latch.arm_slot(FP2, slug="S-A", is_exit=False, now_ns=NOW + 2)
        store.fail_set_after_history = True
        with pytest.raises(OSError):
            latch.retire(
                a.intent_id, RetirementReason.STATUS_REPORT_ZERO_FILL_TERMINAL, now_ns=NOW + 3
            )
    store.fail_set_after_history = False
    assert _table(store)["state"] == "OPEN"
    with _latch(store, tmp_path) as restarted:
        repaired = restarted.reconcile_at_startup(
            has_durable_fill_record=lambda _f, _c: False, now_ns=NOW + 4
        )
        assert repaired is not None and repaired.intent_id == a.intent_id
    final = _table(store)
    assert final["state"] == "RETIRED" and final["retired_ns"] == NOW + 3
    assert final["cooloff"] == {"S-X": NOW + 1 + COOLOFF_NS, "S-A": NOW + 3 + COOLOFF_NS}


def test_arm_over_v1_retired_preserves_unexpired_cooloff(tmp_path: Path) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        a = latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        latch.retire(a.intent_id, RetirementReason.ACCEPTED_WITH_DURABLE_FILL, now_ns=NOW + 1)
        latch.arm(FP2, now_ns=NOW + 2)
        assert _table(store)["state"] == "OPEN"
        assert _table(store)["cooloff"] == {"S-A": NOW + 1 + COOLOFF_NS}
    k1 = Store()
    with _latch(k1, tmp_path, k=1) as one:
        armed = one.arm(FP, now_ns=NOW)
        assert k1.data[CURRENT_INTENT_KEY] == armed.to_bytes()


def test_seed_boot_cooloff_requires_adoption_to_have_run(tmp_path: Path) -> None:
    raw = _v2({_id(1): _rec(1, "S-A"), _id(2): _rec(2, "S-B")})
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        with pytest.raises(SubmitIntentBootOrderError):
            latch.seed_boot_cooloff(now_ns=NOW)
        assert store.sets == []
        latch.adopt_legacy_open_slugs(lambda _i: None)
        assert latch.seed_boot_cooloff(now_ns=NOW) == 2


def test_seed_boot_cooloff_skips_exit_slots(tmp_path: Path) -> None:
    raw = _v2({_id(1): _rec(1, "S-A", is_exit=True), _id(2): _rec(2, "S-B")})
    store = Store({CURRENT_INTENT_KEY: raw})
    with _latch(store, tmp_path) as latch:
        latch.adopt_legacy_open_slugs(lambda _i: None)
        assert latch.seed_boot_cooloff(now_ns=NOW) == 1
    assert _sub(store, "cooloff") == {"S-B": NOW + COOLOFF_NS}


@pytest.mark.parametrize("bad", [123, b"S-A", ["S-A"], "", "x" * 300])
def test_find_slug_non_str_or_invalid_return_quarantines_not_raises(
    tmp_path: Path, bad: object
) -> None:
    store = Store({CURRENT_INTENT_KEY: _canon(_rec(1)).encode("utf-8")})
    with _latch(store, tmp_path) as latch:
        assert latch.adopt_legacy_open_slugs(Mock(return_value=bad)) == 0
        assert latch.unreadable_slot_keys() == (f"?:{_id(1)}",)


def test_fail_closed_denials_log_warning_with_exception_class(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = Store()
    with _latch(store, tmp_path) as latch:
        store.fail_get_keys.add(BREAKER_KEY)
        with caplog.at_level(logging.WARNING):
            assert latch.admission_refusal("S-A", False) == "breaker_unreadable"
        assert any(
            r.levelno == logging.WARNING and "OSError" in r.getMessage() for r in caplog.records
        )
        store.fail_get_keys.clear()
        store.data[CURRENT_INTENT_KEY] = b"junk"
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert latch.admission_refusal("S-A", False) == "corrupt"
            with pytest.raises(SubmitIntentLatched):
                latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2
        assert all("junk" not in r.getMessage() for r in warnings)


def test_future_dated_heartbeat_or_resolver_pass_is_stale(tmp_path: Path) -> None:
    clock = Clock()
    store = Store()
    with _latch(store, tmp_path, clock=clock) as latch:
        latch.write_breaker_heartbeat(hb_ns=NOW + 5 * SEC, resolver_pass_ns=NOW)
        assert latch.admission_refusal("S-A", False) is None  # exactly 5 s ahead is tolerated
        latch.write_breaker_heartbeat(hb_ns=NOW + 5 * SEC + 1, resolver_pass_ns=NOW)
        assert latch.admission_refusal("S-A", False) == "breaker_heartbeat_stale"
        latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW + 5 * SEC + 1)
        assert latch.admission_refusal("S-A", False) == "breaker_resolver_stale"
        assert latch.admission_refusal("S-A", True) is None  # exits unaffected


def test_arm_slot_judges_breaker_by_the_callers_now_ns(tmp_path: Path) -> None:
    clock = Clock()  # the latch clock stays at NOW
    with _latch(Store(), tmp_path, clock=clock) as latch:
        with pytest.raises(SubmitIntentLatched) as exc_info:
            latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW + 61 * SEC)
        assert getattr(exc_info.value, "reason", None) == "breaker_heartbeat_stale"
        latch.arm_slot(FP, slug="S-A", is_exit=False, now_ns=NOW + 60 * SEC)


def test_force_k1_is_thread_safe_first_reason_wins_logged_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with _latch(Store(), tmp_path, k=3) as latch:
        barrier = threading.Barrier(8)
        reasons = [f"r{i}" for i in range(8)]

        def worker(reason: str) -> None:
            barrier.wait()
            latch.force_k1(reason)

        with caplog.at_level(logging.ERROR):
            threads = [threading.Thread(target=worker, args=(r,)) for r in reasons]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert latch.k_forced_reason in reasons
        assert sum("forced to K=1" in r.getMessage() for r in caplog.records) == 1
