"""EXEC-PAR BG-1a: breaker-record ``flag_write_failed`` (M3) and the two ports."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from breezy.runtime import breaker_watcher
from breezy.runtime.breaker_watcher import ExecParStorePort, LedgerPredicatePort
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    SubmitIntentCorrupt,
    SubmitIntentLatch,
    open_submit_intent_latch,
)
from breezy.runtime.submit_intent_slots import (
    BreakerRecord,
    SlotTableError,
    encode_breaker,
    parse_breaker,
)

OLD_BYTES = b'{"halted": {"reason": "r", "ts_ns": 5}, "hb_ns": 1, "resolver_pass_ns": 2, "v": 1}'


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


def test_old_record_without_the_field_decodes_false() -> None:
    record = parse_breaker(OLD_BYTES)
    assert record.flag_write_failed is False
    assert record.halted_reason == "r"


def test_encoding_without_the_flag_is_byte_identical_to_the_old_format() -> None:
    assert encode_breaker(BreakerRecord("r", 5, hb_ns=1, resolver_pass_ns=2)) == OLD_BYTES


def test_flag_round_trips_and_garbled_flag_raises() -> None:
    record = BreakerRecord(None, None, hb_ns=1, resolver_pass_ns=2, flag_write_failed=True)
    assert parse_breaker(encode_breaker(record)) == record
    bad_int = b'{"v":1,"halted":null,"hb_ns":1,"resolver_pass_ns":2,"flag_write_failed":1}'
    for bad in (b'"x"', bad_int):
        with pytest.raises(SlotTableError):
            parse_breaker(bad)


def test_latch_mark_and_clear_preserve_the_other_fields(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.write_breaker_heartbeat(hb_ns=10, resolver_pass_ns=20)
        latch.write_breaker_halt("why", ts_ns=30)
        latch.mark_flag_write_failed()
        assert latch.read_breaker_record() == BreakerRecord("why", 30, 10, 20, True)
        # heartbeat and operator halt reset both preserve it (N2: only --clear-force-k1 clears).
        latch.write_breaker_heartbeat(hb_ns=11, resolver_pass_ns=21)
        assert latch.reset_breaker_halt() is True
        assert latch.read_breaker_record() == BreakerRecord(None, None, 11, 21, True)
        latch.clear_flag_write_failed()
        assert latch.read_breaker_record() == BreakerRecord(None, None, 11, 21)


def test_mark_on_absent_record_and_garbled_record(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.mark_flag_write_failed()
        assert latch.read_breaker_record() == BreakerRecord(None, None, 0, 0, True)
        store.data[BREAKER_KEY] = b"garbage"
        for op in (latch.mark_flag_write_failed, latch.clear_flag_write_failed):
            with pytest.raises(SubmitIntentCorrupt):
                op()
        assert store.data[BREAKER_KEY] == b"garbage"


def test_reset_breaker_halt_refuses_a_garbled_record_and_writes_nothing(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        store.data[BREAKER_KEY] = b"{garbled"
        with pytest.raises(SubmitIntentCorrupt):
            latch.reset_breaker_halt()
        assert store.data[BREAKER_KEY] == b"{garbled"


def test_mark_flag_write_failed_garbled_raise_is_typed_for_the_integrity_stop(
    tmp_path: Path,
) -> None:
    """F8: the caller (BG-5/BG-6) treats this typed raise as an integrity stop (D3)."""
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        store.data[BREAKER_KEY] = b"garbage"
        with pytest.raises(SubmitIntentCorrupt):
            latch.mark_flag_write_failed()
    assert "integrity stop" in (SubmitIntentLatch.mark_flag_write_failed.__doc__ or "")


def test_store_port_declares_every_record_writer_and_the_latch_satisfies_it() -> None:
    assert hasattr(breaker_watcher, "BreakerLatchPort")
    port = {n for n, _ in inspect.getmembers(ExecParStorePort) if not n.startswith("_")}
    for name in (
        "write_stage_reset",
        "add_excluded_day",
        "write_epoch_row",
        "write_epoch_stop_ts",
        "write_amendment",
        "write_stage_eval_dry",
        "write_force_k1_cleared",
        "write_stop_verdict",
        "write_cleanup_demotion",
        "write_force_k1_flag",
        "clear_force_k1_flag",
        "mark_flag_write_failed",
        "clear_flag_write_failed",
    ):
        assert name in port
    assert port <= {n for n, _ in inspect.getmembers(SubmitIntentLatch)}


def test_predicate_port_is_value_free_aggregate_bool_only() -> None:
    methods = {
        n: f
        for n, f in inspect.getmembers(LedgerPredicatePort, inspect.isfunction)
        if not n.startswith("_")
    }
    assert methods
    for name, func in methods.items():
        assert inspect.signature(func).return_annotation in ("bool", bool), name
