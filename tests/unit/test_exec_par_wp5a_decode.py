"""EXEC-PAR WP5a: marker capability, supervisor probes and analysis readers decode v2.

The supervisor, the operator CLI and the analysis readers must learn the v2
slot table BEFORE any v2 write exists. At K=1 (a v1 record) every one of them
behaves exactly as before; the K=1 regressions are kept in the existing suites.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path

import pytest

import breezy.runtime.trade_supervisor as ts
from breezy.analysis.labeling.prelaunch_intents import (
    IntentObservation,
    observe_open_slots_post_stop,
    observe_post_stop_from_store,
)
from breezy.domain.exec_intent import RESOLVER_CONTEXT_KEY_PREFIX
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.stop_intent_marker import process_start_ticks
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    RetirementReason,
    SlotTable,
    SubmitIntent,
    SubmitIntentState,
    decode_slot_table,
    open_submit_intent_latch,
)
from breezy.runtime.submit_intent_slots import canonical_text, encode_v2
from breezy.runtime.supervisor_decode_marker import (
    read_supervisor_decode_marker,
    supervisor_admits_slot_schema,
    supervisor_decode_marker_path,
    write_supervisor_decode_marker,
)
from breezy.runtime.trade_supervisor_core import OpenIntentShape

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts" / "analysis").as_posix())
sys.path.insert(0, (REPO_ROOT / "scripts" / "ops").as_posix())

chk = importlib.import_module("ambig_latch_phase_a_check")
slt = importlib.import_module("score_live_trials")

T = 1_790_000_000_000_000_000
REVISION = "0123456789ab"


def _id(n: int) -> str:
    return f"{n:032x}"


def _open(n: int, *, slug: str | None = "slug-a") -> SubmitIntent:
    return SubmitIntent(
        intent_id=_id(n),
        fingerprint=f"{n:064x}",
        created_ns=T + n,
        state=SubmitIntentState.OPEN,
        retired_ns=None,
        retirement_reason=None,
        slug=slug,
    )


def _v2_bytes(slots: list[SubmitIntent], raw: dict[str, bytes] | None = None) -> bytes:
    return encode_v2({s.intent_id: s.to_payload() for s in slots}, raw or {}, {})


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "state" / "store.sqlite3"
    path.parent.mkdir(parents=True)
    return path


def _put(store_path: Path, raw: bytes) -> None:
    with SqliteStateStore(store_path) as store:
        store.set(CURRENT_INTENT_KEY, raw)


def _context(store_path: Path, intent_id: str, venue_order_id: str | None) -> None:
    payload: dict[str, object] = {}
    if venue_order_id is not None:
        payload["venueOrderId"] = venue_order_id
    with SqliteStateStore(store_path) as store:
        store.set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}", json.dumps(payload).encode())


# ---------------------------------------------------------------------------
# Marker capability
# ---------------------------------------------------------------------------


def test_marker_slot_schema_field_and_old_marker_decodes_empty(tmp_path: Path) -> None:
    store_path = _store(tmp_path)
    write_supervisor_decode_marker(store_path, revision=REVISION)
    payload = json.loads(supervisor_decode_marker_path(store_path).read_text())
    assert payload["v"] == 1  # the marker schema version is unchanged
    assert payload["slot_schema_versions"] == [2]
    marker = read_supervisor_decode_marker(store_path)
    assert marker is not None
    assert marker.slot_schema_versions == frozenset({2})

    del payload["slot_schema_versions"]  # a marker written by pre-WP5a code
    supervisor_decode_marker_path(store_path).write_text(json.dumps(payload))
    old = read_supervisor_decode_marker(store_path)
    assert old is not None
    assert old.slot_schema_versions == frozenset()
    assert old.retirement_reasons == marker.retirement_reasons

    payload["slot_schema_versions"] = ["2"]  # a present-but-malformed field fails closed
    supervisor_decode_marker_path(store_path).write_text(json.dumps(payload))
    assert read_supervisor_decode_marker(store_path) is None


def test_admits_slot_schema_requires_live_matching_pid(tmp_path: Path) -> None:
    store_path = _store(tmp_path)
    assert supervisor_admits_slot_schema(store_path) is False  # no marker
    write_supervisor_decode_marker(store_path, revision=REVISION)
    assert supervisor_admits_slot_schema(store_path) is True
    assert supervisor_admits_slot_schema(store_path, 2) is True
    assert supervisor_admits_slot_schema(store_path, 3) is False  # not advertised

    own = process_start_ticks(os.getpid())
    assert own is not None
    assert (
        supervisor_admits_slot_schema(store_path, process_start_ticks=lambda _p: own + 1) is False
    )
    assert supervisor_admits_slot_schema(store_path, process_start_ticks=lambda _p: None) is False

    payload = json.loads(supervisor_decode_marker_path(store_path).read_text())
    del payload["slot_schema_versions"]
    supervisor_decode_marker_path(store_path).write_text(json.dumps(payload))
    assert supervisor_admits_slot_schema(store_path) is False  # an old marker admits nothing


# ---------------------------------------------------------------------------
# Supervisor probes
# ---------------------------------------------------------------------------


def test_probe_open_true_for_v2_with_open_slot(tmp_path: Path) -> None:
    store_path = _store(tmp_path)
    _put(store_path, _v2_bytes([_open(1), _open(2, slug="slug-b")]))
    assert ts.probe_open_intent(store_path, node_pid=None) is True

    only_unreadable = _store(tmp_path / "u")
    _put(only_unreadable, encode_v2({}, {"weird": b'{"not":"a record"}'}, {}))
    assert ts.probe_open_intent(only_unreadable, node_pid=None) is True

    bad_value = _store(tmp_path / "b")
    _put(
        bad_value,
        canonical_text({"v": 2, "slots": {_id(1): {"junk": 1}}, "raw_slots": {}, "cooloff": {}}),
    )
    assert ts.probe_open_intent(bad_value, node_pid=None) is True

    whole_table_corrupt = _store(tmp_path / "c")
    _put(whole_table_corrupt, b'{"v":2,"slots":"x","raw_slots":{}}')
    assert ts.probe_open_intent(whole_table_corrupt, node_pid=None) is True


def test_probe_resolvable_false_for_unreadable_or_contextless_slot(tmp_path: Path) -> None:
    both = _store(tmp_path / "both")
    _put(both, _v2_bytes([_open(1), _open(2, slug="slug-b")]))
    _context(both, _id(1), "ord-1")
    assert ts.probe_open_intent_resolvable(both, node_pid=None) is False  # slot 2: no context
    _context(both, _id(2), "")
    assert ts.probe_open_intent_resolvable(both, node_pid=None) is True

    unreadable = _store(tmp_path / "unreadable")
    _put(unreadable, _v2_bytes([_open(1), _open(2, slug="slug-b")], {"odd": b"{}"}))
    _context(unreadable, _id(1), "ord-1")
    _context(unreadable, _id(2), "ord-2")
    assert ts.probe_open_intent_resolvable(unreadable, node_pid=None) is False

    corrupt = _store(tmp_path / "corrupt")
    _put(corrupt, b'{"v":2}')
    assert ts.probe_open_intent_resolvable(corrupt, node_pid=None) is False

    # K=1 / v1: no context read, resolvable exactly as before.
    v1 = _store(tmp_path / "v1")
    _put(v1, _open(3, slug=None).to_bytes())
    assert ts.probe_open_intent_resolvable(v1, node_pid=None) is True


def test_probe_shape_v2_reports_the_worst_slot(tmp_path: Path) -> None:
    store_path = _store(tmp_path)
    _put(store_path, _v2_bytes([_open(1), _open(2, slug="slug-b")]))
    _context(store_path, _id(1), "ord-1")
    _context(store_path, _id(2), "ord-2")
    assert ts.probe_open_intent_shape(store_path, node_pid=None) is OpenIntentShape.WITH_ID
    _context(store_path, _id(2), "")
    assert ts.probe_open_intent_shape(store_path, node_pid=None) is OpenIntentShape.NO_ID
    with SqliteStateStore(store_path) as store:
        store.set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{_id(1)}", b"null")
    assert ts.probe_open_intent_shape(store_path, node_pid=None) is OpenIntentShape.UNKNOWN

    unreadable = _store(tmp_path / "u")
    _put(unreadable, _v2_bytes([_open(1)], {"odd": b"{}"}))
    _context(unreadable, _id(1), "ord-1")
    assert ts.probe_open_intent_shape(unreadable, node_pid=None) is OpenIntentShape.UNKNOWN


# ---------------------------------------------------------------------------
# Analysis readers
# ---------------------------------------------------------------------------


def test_score_live_trials_v2_open_not_absent() -> None:
    assert slt._decode_intent_state(_v2_bytes([_open(1), _open(2, slug="b")])) == "OPEN"
    assert slt._decode_intent_state(encode_v2({}, {"odd": b"{}"}, {})) == "OPEN"
    # K=1 shapes are untouched.
    assert slt._decode_intent_state(_open(1, slug=None).to_bytes()) == "OPEN"
    assert slt._decode_intent_state(b"not json") == "absent"


def test_prelaunch_observation_v2_open_is_ambiguous() -> None:
    def observe(raw: bytes | None, *, ambiguous: bool = False) -> IntentObservation:
        return observe_open_slots_post_stop(
            stop_signal_present=True,
            node_pid=lambda: None,
            read_table=lambda: None if raw is None else decode_slot_table(raw),
            is_ambiguous=lambda _i: ambiguous,
        )

    two = _v2_bytes([_open(1), _open(2, slug="b")])
    assert observe(two, ambiguous=True) is IntentObservation.AMBIGUOUS
    assert observe(two) is IntentObservation.OPEN
    assert observe(encode_v2({}, {"odd": b"{}"}, {})) is IntentObservation.AMBIGUOUS
    assert observe(None) is IntentObservation.NONE

    def corrupt() -> SlotTable:
        return decode_slot_table(b'{"v":2,"slots":"x"}')

    assert (
        observe_open_slots_post_stop(
            stop_signal_present=True,
            node_pid=lambda: None,
            read_table=corrupt,
            is_ambiguous=lambda _i: False,
        )
        is IntentObservation.UNKNOWN
    )
    assert (
        observe_open_slots_post_stop(
            stop_signal_present=False,
            node_pid=lambda: None,
            read_table=lambda: decode_slot_table(two),
            is_ambiguous=lambda _i: False,
        )
        is IntentObservation.UNKNOWN
    )
    assert (
        observe_open_slots_post_stop(
            stop_signal_present=True,
            node_pid=lambda: 4242,
            read_table=lambda: decode_slot_table(two),
            is_ambiguous=lambda _i: False,
        )
        is IntentObservation.UNKNOWN
    )


def test_phase_a_check_two_requires_the_slot_schema_capability(tmp_path: Path) -> None:
    store_path = _store(tmp_path)
    write_supervisor_decode_marker(store_path, revision=REVISION)
    probes = chk.Probes(
        main_pid=lambda: os.getpid(),
        main_environ_names_revision_override=lambda _p: False,
        process_start_ticks=process_start_ticks,
        supervisor_log_text=lambda: "",
        is_ancestor=lambda _a, _b: True,
        lock_holder_pid=lambda: None,
    )
    assert chk.check_decode_marker(store_path, probes) == (True, "")
    payload = json.loads(supervisor_decode_marker_path(store_path).read_text())
    del payload["slot_schema_versions"]
    supervisor_decode_marker_path(store_path).write_text(json.dumps(payload))
    assert chk.check_decode_marker(store_path, probes) == (
        False,
        "marker_does_not_admit_slot_schema_2",
    )


# ---------------------------------------------------------------------------
# Rollback drill
# ---------------------------------------------------------------------------


def test_rollback_drill_after_drain_and_reset_old_reader_sees_valid_v1_retired(
    tmp_path: Path,
) -> None:
    """Drain a v2 table, reset the entry halt: a pre-WP2 reader decodes a v1 RETIRED record."""
    store_path = _store(tmp_path)
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(
        store, store_path, max_slots=2, v2_predicate=lambda: True, clock_ns=lambda: T
    ) as latch:
        first = latch.arm_slot("a" * 64, slug="slug-a", is_exit=True, now_ns=T)
        second = latch.arm_slot("b" * 64, slug="slug-b", is_exit=True, now_ns=T + 1)
        latch.write_breaker_halt("stuck_slots", ts_ns=T + 2)
        assert json.loads(store.get(CURRENT_INTENT_KEY) or b"{}")["v"] == 2
        for intent in (first, second):
            latch.retire(intent.intent_id, RetirementReason.OPERATOR_CLEARED, now_ns=T + 10)
        assert latch.reset_breaker_halt() is True
    raw = store.get(CURRENT_INTENT_KEY)
    assert raw is not None
    old_reader = SubmitIntent.from_bytes(raw)  # the pre-WP2 decoder
    assert old_reader.state is SubmitIntentState.RETIRED
    breaker = store.get("exec/polymarket_us/intent/breaker")
    assert breaker is not None
    assert json.loads(breaker)["halted"] is None
    store.close()


def test_probe_resolvable_v2_garbled_context_is_not_resolvable(tmp_path: Path) -> None:
    store_path = _store(tmp_path)
    _put(store_path, _v2_bytes([_open(1), _open(2, slug="slug-b")]))
    _context(store_path, _id(1), "ord-1")
    _context(store_path, _id(2), "ord-2")
    assert ts.probe_open_intent_resolvable(store_path, node_pid=None) is True
    for garbage in (b"null", b"{not json", b'{"venueOrderId": 7}'):
        with SqliteStateStore(store_path) as store:
            store.set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{_id(2)}", garbage)
        assert ts.probe_open_intent_resolvable(store_path, node_pid=None) is False, garbage
        assert ts.probe_open_intent_shape(store_path, node_pid=None) is OpenIntentShape.UNKNOWN


def test_probe_shape_logs_the_swallowed_exception(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store_path = _store(tmp_path)
    _put(store_path, _v2_bytes([_open(1), _open(2, slug="slug-b")]))
    with SqliteStateStore(store_path) as store:
        store.set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{_id(1)}", b"{not json")
    with caplog.at_level(logging.WARNING, logger="breezy.runtime.trade_supervisor"):
        shape = ts.probe_open_intent_shape(store_path, node_pid=None)
    assert shape is OpenIntentShape.UNKNOWN
    assert any("JSONDecodeError" in r.getMessage() for r in caplog.records)


def test_post_stop_observation_caller_classifies_v2_and_keeps_v1(tmp_path: Path) -> None:
    """The store-backed caller reads the table: v2 is classified, v1 results are unchanged."""
    store_path = _store(tmp_path)

    def observe() -> IntentObservation:
        return observe_post_stop_from_store(
            store_path,
            stop_signal_present=True,
            node_pid=lambda: None,
            is_ambiguous=lambda _i: False,
        )

    assert observe() is IntentObservation.NONE  # absent
    _put(store_path, _open(1, slug=None).to_bytes())
    assert observe() is IntentObservation.OPEN  # v1, as before
    _put(store_path, _v2_bytes([_open(1), _open(2, slug="slug-b")]))
    assert observe() is IntentObservation.OPEN  # v2 classified, not UNKNOWN
    _put(store_path, _v2_bytes([_open(1)], {"odd": b"{}"}))
    assert observe() is IntentObservation.AMBIGUOUS
    _put(store_path, b'{"v":2,"slots":"x"}')
    assert observe() is IntentObservation.UNKNOWN  # corrupt
