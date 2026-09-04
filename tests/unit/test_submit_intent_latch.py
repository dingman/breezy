"""Tests for the durable submit-intent latch (src/breezy/runtime/submit_intent.py).

Zero production call sites: this library is persistence-only. The latch record
is value-free in str/repr; fingerprints stay out of every exception message.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    RetirementReason,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentInvalidFingerprint,
    SubmitIntentLatch,
    SubmitIntentLatched,
    SubmitIntentLockError,
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    SubmitIntentMismatch,
    SubmitIntentState,
    history_key,
    hold_submit_intent_process_lock,
    open_submit_intent_latch,
)

FINGERPRINT = "9f3ac0de" + "a1b2c3d4" * 7
NOW_NS = 1_700_000_000_000_000_000
_INTENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_VALID_INTENT_ID = "ab" * 16
_PLANTED_BYTES = b"\xff\xfe SECRET-SHOULD-NOT-LEAK"

_BASE_PAYLOAD: dict[str, object] = {
    "v": 1,
    "intent_id": _VALID_INTENT_ID,
    "fingerprint": FINGERPRINT,
    "created_ns": NOW_NS,
    "state": "OPEN",
    "retired_ns": None,
    "retirement_reason": None,
}


def _payload(**changes: object) -> bytes:
    data = dict(_BASE_PAYLOAD)
    data.update(changes)
    return json.dumps(data).encode("utf-8")


class _DictStore:
    """Two-method in-memory StateStore: get/set over a shared dict."""

    def __init__(self, data: dict[str, bytes] | None = None) -> None:
        self.data: dict[str, bytes] = {} if data is None else data

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


class _RecordingStore(_DictStore):
    def __init__(self, data: dict[str, bytes] | None = None) -> None:
        super().__init__(data)
        self.set_keys: list[str] = []

    def set(self, key: str, value: bytes) -> None:
        self.set_keys.append(key)
        super().set(key, value)


class _RaisingStore(_DictStore):
    def set(self, key: str, value: bytes) -> None:
        raise OSError("simulated store write failure")


class _FailCurrentOnceHistoryExists(_DictStore):
    def set(self, key: str, value: bytes) -> None:
        if key == CURRENT_INTENT_KEY and any(
            existing.startswith("exec/polymarket_us/intent/history/") for existing in self.data
        ):
            raise OSError("simulated store write failure")
        super().set(key, value)


class _FillProbe:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[str] = []

    def __call__(self, fingerprint: str) -> object:
        self.calls.append(fingerprint)
        return self.result


def _assert_value_free(*objects: object) -> None:
    for obj in objects:
        assert FINGERPRINT not in str(obj)
        assert FINGERPRINT not in repr(obj)
        if isinstance(obj, BaseException):
            assert FINGERPRINT not in repr(obj.__cause__)
            assert FINGERPRINT not in repr(obj.__context__)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


class TestArm:
    def test_arm_on_empty_store_writes_open_singleton_and_current_round_trips(
        self, store_path: Path
    ) -> None:
        store = _DictStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)

            assert armed.state is SubmitIntentState.OPEN
            assert armed.fingerprint == FINGERPRINT
            assert armed.created_ns == NOW_NS
            assert armed.retired_ns is None
            assert armed.retirement_reason is None
            assert _INTENT_ID_RE.fullmatch(armed.intent_id)
            assert CURRENT_INTENT_KEY in store.data
            assert latch.current() == armed

    def test_second_arm_while_open_raises_latched_and_does_not_write(
        self, store_path: Path
    ) -> None:
        store = _RecordingStore()
        with open_submit_intent_latch(store, store_path) as latch:
            first = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            writes_after_first = list(store.set_keys)

            with pytest.raises(SubmitIntentLatched) as exc_info:
                latch.arm(FINGERPRINT, now_ns=NOW_NS + 1)

            assert first.intent_id in str(exc_info.value)
            _assert_value_free(exc_info.value)
            assert store.set_keys == writes_after_first

    def test_fresh_latch_over_same_store_refuses_arm_while_unretired(
        self, store_path: Path
    ) -> None:
        data: dict[str, bytes] = {}
        with open_submit_intent_latch(_DictStore(data), store_path) as first:
            armed = first.arm(FINGERPRINT, now_ns=NOW_NS)

        with open_submit_intent_latch(_DictStore(data), store_path) as restarted:
            with pytest.raises(SubmitIntentLatched) as exc_info:
                restarted.arm("cafef00d" + "11" * 28, now_ns=NOW_NS + 1)
            assert armed.intent_id in str(exc_info.value)

    def test_arm_rejects_invalid_fingerprint_before_any_write(self, store_path: Path) -> None:
        store = _RecordingStore()
        with open_submit_intent_latch(store, store_path) as latch:
            with pytest.raises(SubmitIntentInvalidFingerprint) as exc_info:
                latch.arm("not-a-digest", now_ns=NOW_NS)
            _assert_value_free(exc_info.value)
            with pytest.raises(SubmitIntentInvalidFingerprint):
                latch.arm("A" * 64, now_ns=NOW_NS)
            with pytest.raises(SubmitIntentInvalidFingerprint):
                latch.arm("0" * 63, now_ns=NOW_NS)
            assert store.set_keys == []
            assert latch.current() is None


class TestRetire:
    def test_retire_writes_history_before_singleton_then_arm_succeeds(
        self, store_path: Path
    ) -> None:
        store = _RecordingStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            store.set_keys.clear()

            retired = latch.retire(
                armed.intent_id,
                RetirementReason.DEFINITIVE_REJECT,
                now_ns=NOW_NS + 1,
            )

            assert store.set_keys == [history_key(armed.intent_id), CURRENT_INTENT_KEY]
            assert retired.state is SubmitIntentState.RETIRED
            assert retired.retirement_reason is RetirementReason.DEFINITIVE_REJECT
            second = latch.arm(FINGERPRINT, now_ns=NOW_NS + 2)
            assert second.state is SubmitIntentState.OPEN
            assert second.intent_id != armed.intent_id

    def test_retire_wrong_intent_id_raises_mismatch_and_leaves_singleton_open(
        self, store_path: Path
    ) -> None:
        store = _DictStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)

            with pytest.raises(SubmitIntentMismatch) as exc_info:
                latch.retire("0" * 32, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW_NS + 1)

            _assert_value_free(exc_info.value)
            current = latch.current()
            assert current is not None
            assert current.state is SubmitIntentState.OPEN
            assert current.intent_id == armed.intent_id
            assert history_key(armed.intent_id) not in store.data

    def test_retire_when_nothing_is_open_raises_mismatch(self, store_path: Path) -> None:
        with (
            open_submit_intent_latch(_DictStore(), store_path) as latch,
            pytest.raises(SubmitIntentMismatch),
        ):
            latch.retire("0" * 32, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW_NS)

    def test_retire_rejects_invalid_intent_id_without_escaping_namespace(
        self, store_path: Path
    ) -> None:
        store = _RecordingStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            store.set_keys.clear()
            escaped = "../" + "a" * 29

            with pytest.raises(SubmitIntentCorrupt):
                latch.retire(escaped, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW_NS + 1)
            with pytest.raises(SubmitIntentCorrupt):
                latch.retire("z" * 32, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW_NS + 1)

            assert store.set_keys == []
            assert not any(".." in key for key in store.data)
            current = latch.current()
            assert current is not None
            assert current.intent_id == armed.intent_id
            assert current.state is SubmitIntentState.OPEN


class TestStoreWriteFailures:
    def test_raising_store_on_arm_propagates_and_current_stays_none(self, store_path: Path) -> None:
        store = _RaisingStore()
        with open_submit_intent_latch(store, store_path) as latch:
            with pytest.raises(OSError, match="simulated store write failure"):
                latch.arm(FINGERPRINT, now_ns=NOW_NS)
            assert latch.current() is None

    def test_raising_store_on_first_retire_write_leaves_singleton_open(
        self, store_path: Path
    ) -> None:
        data: dict[str, bytes] = {}
        with open_submit_intent_latch(_DictStore(data), store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)

        with (
            open_submit_intent_latch(_RaisingStore(data), store_path) as failing,
            pytest.raises(OSError, match="simulated store write failure"),
        ):
            failing.retire(
                armed.intent_id,
                RetirementReason.DEFINITIVE_REJECT,
                now_ns=NOW_NS + 1,
            )

        with open_submit_intent_latch(_DictStore(data), store_path) as remaining:
            current = remaining.current()
            assert current is not None
            assert current.state is SubmitIntentState.OPEN
            assert current.intent_id == armed.intent_id
            assert history_key(armed.intent_id) not in data

    def test_second_retire_write_failure_leaves_open_singleton_and_history(
        self, store_path: Path
    ) -> None:
        store = _FailCurrentOnceHistoryExists()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            with pytest.raises(OSError, match="simulated store write failure"):
                latch.retire(
                    armed.intent_id,
                    RetirementReason.DEFINITIVE_REJECT,
                    now_ns=NOW_NS + 1,
                )
            current = latch.current()
            assert current is not None
            assert current.state is SubmitIntentState.OPEN
            history_bytes = store.data[history_key(armed.intent_id)]
            assert SubmitIntent.from_bytes(history_bytes).state is SubmitIntentState.RETIRED

        probe = _FillProbe(result=True)
        with open_submit_intent_latch(_DictStore(store.data), store_path) as repaired:
            result = repaired.reconcile_at_startup(
                has_durable_fill_record=probe,
                now_ns=NOW_NS + 2,
            )
            assert result is not None
            assert result.state is SubmitIntentState.RETIRED
            assert result.retirement_reason is RetirementReason.DEFINITIVE_REJECT
            assert result.retired_ns == NOW_NS + 1
            assert store.data[CURRENT_INTENT_KEY] == history_bytes
            assert probe.calls == []


class TestCorruptSingleton:
    def test_corrupt_singleton_is_latched_arm_raises_latched_current_raises_corrupt(
        self, store_path: Path
    ) -> None:
        store = _DictStore()
        store.set(CURRENT_INTENT_KEY, b"not-a-submit-intent")
        with open_submit_intent_latch(store, store_path) as latch:
            assert latch.is_latched() is True
            with pytest.raises(SubmitIntentLatched):
                latch.arm(FINGERPRINT, now_ns=NOW_NS)
            with pytest.raises(SubmitIntentCorrupt):
                latch.current()
            assert CURRENT_INTENT_KEY in store.data
            assert store.data[CURRENT_INTENT_KEY] == b"not-a-submit-intent"

    def test_reconcile_over_corrupt_singleton_raises_corrupt(self, store_path: Path) -> None:
        store = _DictStore()
        store.set(CURRENT_INTENT_KEY, b"not-a-submit-intent")
        probe = _FillProbe(result=True)
        with open_submit_intent_latch(store, store_path) as latch:
            with pytest.raises(SubmitIntentCorrupt):
                latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS)
            assert probe.calls == []
            assert store.data[CURRENT_INTENT_KEY] == b"not-a-submit-intent"


class TestSerialization:
    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(_payload(created_ns=True), id="bool-as-created-ns"),
            pytest.param(_payload(v=True), id="bool-as-version"),
            pytest.param(_payload(created_ns="1"), id="str-created-ns"),
            pytest.param(_payload(fingerprint=1), id="int-fingerprint"),
            pytest.param(_payload(intent_id=1), id="int-intent-id"),
            pytest.param(b"[]", id="json-array"),
            pytest.param(b"null", id="json-null"),
            pytest.param(b'"str"', id="json-string"),
            pytest.param(_payload(retirement_reason=1), id="non-str-reason"),
            pytest.param(_payload(v=99), id="unknown-version"),
            pytest.param(_payload(state="AMBIGUOUS"), id="unknown-state"),
            pytest.param(b"\xff\xfe undecodable", id="undecodable"),
        ],
    )
    def test_decoder_rejects_malformed_payloads(self, raw: bytes) -> None:
        with pytest.raises(SubmitIntentCorrupt) as exc_info:
            SubmitIntent.from_bytes(raw)
        _assert_value_free(exc_info.value)

    @pytest.mark.parametrize(
        "missing",
        ["v", "intent_id", "fingerprint", "created_ns", "state", "retired_ns", "retirement_reason"],
    )
    def test_decoder_rejects_missing_key(self, missing: str) -> None:
        payload = dict(_BASE_PAYLOAD)
        del payload[missing]
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(json.dumps(payload).encode("utf-8"))

    def test_from_bytes_rejects_invalid_fingerprint(self) -> None:
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(fingerprint="not-a-digest"))
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(fingerprint="A" * 64))
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(fingerprint="0" * 63))

    def test_from_bytes_rejects_invalid_intent_id(self) -> None:
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(intent_id="A" * 32))
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(intent_id="g" * 32))
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(intent_id="ab" * 15))

    def test_corrupt_decode_does_not_leak_payload_through_cause(self) -> None:
        with pytest.raises(SubmitIntentCorrupt) as exc_info:
            SubmitIntent.from_bytes(_PLANTED_BYTES)
        exc = exc_info.value
        assert "SECRET" not in repr(exc.__cause__)
        assert "SECRET" not in repr(exc.__context__)
        assert "SECRET-SHOULD-NOT-LEAK" not in str(exc)
        assert "SECRET-SHOULD-NOT-LEAK" not in repr(exc)

    def test_round_trip_equality_for_open_and_retired_records(self) -> None:
        opened = SubmitIntent(
            intent_id="b" * 32,
            fingerprint=FINGERPRINT,
            created_ns=NOW_NS,
            state=SubmitIntentState.OPEN,
            retired_ns=None,
            retirement_reason=None,
        )
        retired = SubmitIntent(
            intent_id="c" * 32,
            fingerprint=FINGERPRINT,
            created_ns=NOW_NS,
            state=SubmitIntentState.RETIRED,
            retired_ns=NOW_NS + 1,
            retirement_reason=RetirementReason.ACCEPTED_WITH_DURABLE_FILL,
        )
        assert SubmitIntent.from_bytes(opened.to_bytes()) == opened
        assert SubmitIntent.from_bytes(retired.to_bytes()) == retired
        assert list(json.loads(opened.to_bytes()).keys()) == sorted(
            json.loads(opened.to_bytes()).keys()
        )
        _assert_value_free(opened, retired)


class TestCrossFieldInvariants:
    def test_retired_with_null_fields_does_not_unlatch(self, store_path: Path) -> None:
        store = _DictStore()
        store.set(
            CURRENT_INTENT_KEY,
            _payload(state="RETIRED", retired_ns=None, retirement_reason=None),
        )
        with open_submit_intent_latch(store, store_path) as latch:
            assert latch.is_latched() is True
            with pytest.raises(SubmitIntentLatched):
                latch.arm(FINGERPRINT, now_ns=NOW_NS)
            with pytest.raises(SubmitIntentCorrupt):
                latch.current()

    def test_open_with_reason_set_is_corrupt(self) -> None:
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(retirement_reason="DEFINITIVE_REJECT"))

    def test_open_with_retired_ns_set_is_corrupt(self) -> None:
        with pytest.raises(SubmitIntentCorrupt):
            SubmitIntent.from_bytes(_payload(retired_ns=NOW_NS))


class TestReconcileAtStartup:
    def test_open_plus_history_retired_copies_history_bytes_verbatim(
        self, store_path: Path
    ) -> None:
        store = _DictStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            history_record = SubmitIntent(
                intent_id=armed.intent_id,
                fingerprint=FINGERPRINT,
                created_ns=NOW_NS,
                state=SubmitIntentState.RETIRED,
                retired_ns=NOW_NS + 1,
                retirement_reason=RetirementReason.DEFINITIVE_REJECT,
            )
            history_bytes = history_record.to_bytes()
            store.set(history_key(armed.intent_id), history_bytes)
            probe = _FillProbe(result=True)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS + 2)

            assert result is not None
            assert result.state is SubmitIntentState.RETIRED
            assert result.retirement_reason is RetirementReason.DEFINITIVE_REJECT
            assert result.retired_ns == NOW_NS + 1
            assert store.data[CURRENT_INTENT_KEY] == history_bytes
            decoded_history = SubmitIntent.from_bytes(store.data[history_key(armed.intent_id)])
            assert decoded_history == history_record
            assert probe.calls == []
            second = latch.arm(FINGERPRINT, now_ns=NOW_NS + 3)
            assert second.state is SubmitIntentState.OPEN

    def test_open_plus_fill_record_callable_true_uses_startup_fill_record_match(
        self, store_path: Path
    ) -> None:
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            probe = _FillProbe(result=True)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS + 1)

            assert result is not None
            assert result.intent_id == armed.intent_id
            assert result.state is SubmitIntentState.RETIRED
            assert result.retirement_reason is RetirementReason.STARTUP_FILL_RECORD_MATCH
            assert probe.calls == [FINGERPRINT]

    def test_open_plus_neither_stays_open_and_invokes_callable_with_fingerprint(
        self, store_path: Path
    ) -> None:
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            probe = _FillProbe(result=False)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS + 1)

            assert result is not None
            assert result.state is SubmitIntentState.OPEN
            assert result.intent_id == armed.intent_id
            assert probe.calls == [FINGERPRINT]
            assert latch.is_latched() is True

    @pytest.mark.parametrize("probe_result", ["maybe", {"filled": True}, Mock()])
    def test_truthy_non_bool_probe_leaves_open(
        self, store_path: Path, probe_result: object
    ) -> None:
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            probe = _FillProbe(result=probe_result)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS + 1)

            assert result is not None
            assert result.state is SubmitIntentState.OPEN
            assert result.intent_id == armed.intent_id
            assert latch.is_latched() is True
            assert probe.calls == [FINGERPRINT]

    def test_empty_store_returns_none_and_never_invokes_callable(self, store_path: Path) -> None:
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            probe = _FillProbe(result=True)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS)

            assert result is None
            assert probe.calls == []

    def test_mismatched_history_id_leaves_open_and_skips_probe(self, store_path: Path) -> None:
        store = _DictStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            mismatched = SubmitIntent(
                intent_id="d" * 32,
                fingerprint=FINGERPRINT,
                created_ns=NOW_NS,
                state=SubmitIntentState.RETIRED,
                retired_ns=NOW_NS + 1,
                retirement_reason=RetirementReason.DEFINITIVE_REJECT,
            )
            store.set(history_key(armed.intent_id), mismatched.to_bytes())
            probe = _FillProbe(result=True)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS + 2)

            assert result is not None
            assert result.state is SubmitIntentState.OPEN
            assert result.intent_id == armed.intent_id
            assert probe.calls == []
            assert latch.is_latched() is True

    def test_mismatched_history_fingerprint_leaves_open_and_skips_probe(
        self, store_path: Path
    ) -> None:
        store = _DictStore()
        other_fingerprint = "cafef00d" + "11" * 28
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            mismatched = SubmitIntent(
                intent_id=armed.intent_id,
                fingerprint=other_fingerprint,
                created_ns=NOW_NS,
                state=SubmitIntentState.RETIRED,
                retired_ns=NOW_NS + 1,
                retirement_reason=RetirementReason.DEFINITIVE_REJECT,
            )
            store.set(history_key(armed.intent_id), mismatched.to_bytes())
            probe = _FillProbe(result=True)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS + 2)

            assert result is not None
            assert result.state is SubmitIntentState.OPEN
            assert probe.calls == []
            assert latch.is_latched() is True

    def test_corrupt_history_leaves_open_and_skips_probe(self, store_path: Path) -> None:
        store = _DictStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            store.set(history_key(armed.intent_id), b"not-a-history-record")
            probe = _FillProbe(result=True)

            result = latch.reconcile_at_startup(has_durable_fill_record=probe, now_ns=NOW_NS + 2)

            assert result is not None
            assert result.state is SubmitIntentState.OPEN
            assert result.intent_id == armed.intent_id
            assert probe.calls == []
            assert latch.is_latched() is True
            assert store.data[CURRENT_INTENT_KEY] != b"not-a-history-record"


class TestProcessLock:
    def test_second_acquirer_raises_then_succeeds_after_release_and_lock_file_sits_beside(
        self, store_path: Path
    ) -> None:
        lock_path = store_path.with_name(store_path.name + ".intent.lock")

        with (
            hold_submit_intent_process_lock(store_path),
            pytest.raises(SubmitIntentLockHeld) as held,
            hold_submit_intent_process_lock(store_path),
        ):
            raise AssertionError("nested acquire must not enter the body")
        _assert_value_free(held.value)
        assert lock_path.exists()
        assert lock_path.parent == store_path.parent

        with hold_submit_intent_process_lock(store_path):
            pass

    def test_second_open_latch_over_same_path_raises_lock_held(self, store_path: Path) -> None:
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            assert latch.current() is None
            with (
                pytest.raises(SubmitIntentLockHeld),
                open_submit_intent_latch(_DictStore(), store_path),
            ):
                raise AssertionError("second factory must not yield")

    def test_use_after_with_exits_raises_lock_not_held(self, store_path: Path) -> None:
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            pass
        with pytest.raises(SubmitIntentLockNotHeld):
            latch.current()
        with pytest.raises(SubmitIntentLockNotHeld):
            latch.is_latched()
        with pytest.raises(SubmitIntentLockNotHeld):
            latch.arm(FINGERPRINT, now_ns=NOW_NS)
        with pytest.raises(SubmitIntentLockNotHeld):
            latch.retire("0" * 32, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW_NS)
        with pytest.raises(SubmitIntentLockNotHeld):
            latch.reconcile_at_startup(has_durable_fill_record=lambda _: False, now_ns=NOW_NS)

    def test_missing_parent_raises_lock_error(self, tmp_path: Path) -> None:
        store_path = tmp_path / "missing" / "state.db"
        with (
            pytest.raises(SubmitIntentLockError),
            open_submit_intent_latch(_DictStore(), store_path),
        ):
            raise AssertionError("missing parent must not yield")

    def test_symlinked_lock_path_raises_lock_error(self, store_path: Path) -> None:
        lock_path = store_path.with_name(store_path.name + ".intent.lock")
        target = store_path.parent / "other.lock"
        target.write_bytes(b"")
        lock_path.symlink_to(target)
        with (
            pytest.raises(SubmitIntentLockError),
            open_submit_intent_latch(_DictStore(), store_path),
        ):
            raise AssertionError("symlinked lock path must not yield")

    def test_cross_process_acquire_while_held_exits_with_marker(self, store_path: Path) -> None:
        child = (
            "import sys\n"
            "from pathlib import Path\n"
            "from breezy.runtime.submit_intent import (\n"
            "    SubmitIntentLockHeld,\n"
            "    hold_submit_intent_process_lock,\n"
            ")\n"
            "try:\n"
            "    with hold_submit_intent_process_lock(Path(sys.argv[1])):\n"
            "        print('ACQUIRED', flush=True)\n"
            "except SubmitIntentLockHeld:\n"
            "    print('LOCK_HELD', flush=True)\n"
            "    raise SystemExit(2)\n"
        )
        with open_submit_intent_latch(_DictStore(), store_path):
            completed = subprocess.run(
                [sys.executable, "-c", child, str(store_path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        assert completed.returncode == 2
        assert "LOCK_HELD" in completed.stdout
        assert "ACQUIRED" not in completed.stdout


class TestSharedStateBinding:
    """`shared_state_binding` -- the accessor `current_rung_hold.trial_day_latch`
    uses to bind a `TrialDayLatch` to this SAME store and flock, never a
    second opener (L-22).
    """

    def test_returns_the_same_store_and_a_lock_that_reflects_this_latch(
        self, store_path: Path
    ) -> None:
        store = _DictStore()
        with open_submit_intent_latch(store, store_path) as latch:
            bound_store, bound_lock = latch.shared_state_binding()
            assert bound_store is store
            assert bound_lock.held is True

            # The bound lock is not a fresh grant: it is the exact token
            # this latch holds, so mutating one is observed through both.
            latch.arm(FINGERPRINT, now_ns=NOW_NS)
            assert bound_store.get(CURRENT_INTENT_KEY) is not None

        # Once this latch's own `with` exits, the SAME token the accessor
        # returned reflects that release -- it grants nothing durable.
        assert bound_lock.held is False

    def test_raises_lock_not_held_once_this_latch_is_released(self, store_path: Path) -> None:
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            pass
        with pytest.raises(SubmitIntentLockNotHeld):
            latch.shared_state_binding()

    def test_a_second_store_path_opener_still_raises_lock_held(self, store_path: Path) -> None:
        """The accessor is not a side door: a second constructor over the
        same store path is refused exactly as it is for `SubmitIntentLatch`
        itself -- there is no second flock to acquire through it.
        """
        with open_submit_intent_latch(_DictStore(), store_path) as latch:
            latch.shared_state_binding()
            with (
                pytest.raises(SubmitIntentLockHeld),
                open_submit_intent_latch(_DictStore(), store_path),
            ):
                raise AssertionError("second factory must not yield")


class TestSqliteRoundTrip:
    def test_arm_close_reopen_is_latched_then_retire_reopen_arm_succeeds(
        self, store_path: Path
    ) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
        store.close()

        reopened = SqliteStateStore(store_path)
        with open_submit_intent_latch(reopened, store_path) as restarted:
            assert restarted.is_latched() is True
            restarted.retire(
                armed.intent_id,
                RetirementReason.OPERATOR_CLEARED,
                now_ns=NOW_NS + 1,
            )
        reopened.close()

        after_retire = SqliteStateStore(store_path)
        with open_submit_intent_latch(after_retire, store_path) as cleared:
            second = cleared.arm(FINGERPRINT, now_ns=NOW_NS + 2)
            assert second.state is SubmitIntentState.OPEN
        after_retire.close()


class TestValueFreeGrammar:
    def test_str_and_repr_of_exceptions_and_intent_never_contain_fingerprint(
        self, store_path: Path
    ) -> None:
        store = _DictStore()
        with open_submit_intent_latch(store, store_path) as latch:
            armed = latch.arm(FINGERPRINT, now_ns=NOW_NS)
            _assert_value_free(armed)

            with pytest.raises(SubmitIntentLatched) as latched:
                latch.arm(FINGERPRINT, now_ns=NOW_NS + 1)
            _assert_value_free(latched.value)

            with pytest.raises(SubmitIntentMismatch) as mismatch:
                latch.retire("0" * 32, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW_NS + 1)
            _assert_value_free(mismatch.value)

            store.set(CURRENT_INTENT_KEY, b"not-a-submit-intent")
            with pytest.raises(SubmitIntentCorrupt) as corrupt:
                latch.current()
            _assert_value_free(corrupt.value)


class TestStaticIsolation:
    def test_module_source_imports_no_nautilus_http_or_adapter(self) -> None:
        import breezy.runtime.submit_intent as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
        forbidden = ("nautilus_trader", "breezy.adapters", "httpx", "aiohttp", "requests")
        for name in imported:
            assert not any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
        assert "breezy.ingest.gate" not in imported
        assert SubmitIntentLatch is not None
