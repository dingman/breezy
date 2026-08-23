"""Tests for the product_uuid -> raw_sha256 integrity index.

Governing ruling: docs/plans/PHASE1_ACTOR_BRIEF.md SS3.4. The supersession key
``(venue, city, climate_day, issuance_class, revision_seq)`` cannot see the one
event it most needs to -- the same NWS ``product_uuid`` observed twice with a
*different* ``raw_sha256``. That is upstream mutation of an already-issued
product, not a revision, and it must surface as a CRIT integrity outcome the
caller acts on.

Every test here is about one of three properties:
  1. the three-way outcome is correct,
  2. the first-seen digest is NEVER overwritten,
  3. neither a restart nor corrupt persisted bytes can launder a mutated
     product into a clean "never seen".
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from breezy.ingest.product_index import (
    PRODUCT_INDEX_KEY_PREFIX,
    CorruptProductIndexEntryError,
    ProductIntegrityIndex,
    ProductIntegrityOutcome,
    ProductIntegrityResult,
    StateStore,
    _index_key,
)

UUID_A = "6a1b8f2e-2c3d-4e5f-9a0b-1c2d3e4f5a6b"
UUID_B = "7b2c9a3f-3d4e-5f60-ab1c-2d3e4f5a6b7c"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


DIGEST_ORIGINAL = _digest("...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21...\nMAXIMUM 84")
DIGEST_MUTATED = _digest("...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21...\nMAXIMUM 99")


class _FakeStore:
    """A five-line StateStore plus call recording, so tests can prove that a
    match performs no write and that a mismatch performs no write either.
    """

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.set_calls: list[tuple[str, bytes]] = []
        self.get_calls: list[str] = []

    def get(self, key: str) -> bytes | None:
        self.get_calls.append(key)
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.set_calls.append((key, value))
        self.data[key] = value


class _RaisingGetStore:
    """A store whose backing database is unavailable."""

    def __init__(self) -> None:
        self.set_calls: list[tuple[str, bytes]] = []

    def get(self, key: str) -> bytes | None:
        raise OSError("cache database unreachable")

    def set(self, key: str, value: bytes) -> None:
        self.set_calls.append((key, value))


class _RaisingSetStore:
    """A store that accepts reads but fails every write."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        raise OSError("cache database read-only")


class _FakeClock:
    def __init__(self, start_ns: int = 1_000) -> None:
        self._now_ns = start_ns

    def __call__(self) -> int:
        return self._now_ns

    def advance(self, delta_ns: int) -> None:
        self._now_ns += delta_ns


def _index(
    store: _FakeStore | None = None, clock: _FakeClock | None = None
) -> tuple[ProductIntegrityIndex, _FakeStore, _FakeClock]:
    store = store if store is not None else _FakeStore()
    clock = clock if clock is not None else _FakeClock()
    return ProductIntegrityIndex(store=store, clock=clock), store, clock


# ---------------------------------------------------------------------------
# Outcome vocabulary
# ---------------------------------------------------------------------------


def test_outcome_is_exactly_three_way() -> None:
    assert {member.value for member in ProductIntegrityOutcome} == {
        "first_seen",
        "match",
        "mismatch",
    }


def test_only_mismatch_is_an_integrity_alarm() -> None:
    index, _store, _clock = _index()
    first = index.observe(UUID_A, DIGEST_ORIGINAL)
    match = index.observe(UUID_A, DIGEST_ORIGINAL)
    mismatch = index.observe(UUID_A, DIGEST_MUTATED)

    assert first.is_integrity_alarm is False
    assert match.is_integrity_alarm is False
    assert mismatch.is_integrity_alarm is True


def test_index_key_is_namespaced_away_from_gate_keys() -> None:
    assert _index_key(UUID_A) == f"{PRODUCT_INDEX_KEY_PREFIX}{UUID_A}"
    assert not _index_key(UUID_A).startswith("gate:")


# ---------------------------------------------------------------------------
# First observation
# ---------------------------------------------------------------------------


def test_first_observation_of_unknown_uuid_is_first_seen() -> None:
    index, _store, _clock = _index()
    result = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert isinstance(result, ProductIntegrityResult)
    assert result.outcome is ProductIntegrityOutcome.FIRST_SEEN
    assert result.product_uuid == UUID_A
    assert result.observed_sha256 == DIGEST_ORIGINAL
    assert result.first_seen_sha256 == DIGEST_ORIGINAL


def test_first_observation_persists_the_digest_under_the_namespaced_key() -> None:
    index, store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)

    raw = store.data[_index_key(UUID_A)]
    payload = json.loads(raw.decode("utf-8"))
    assert payload["raw_sha256"] == DIGEST_ORIGINAL


def test_first_seen_timestamp_comes_from_the_injected_clock() -> None:
    clock = _FakeClock(start_ns=4_242)
    index, _store, _ = _index(clock=clock)
    result = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.first_seen_at_ns == 4_242
    assert result.observed_at_ns == 4_242


def test_distinct_uuids_are_tracked_independently() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    result = index.observe(UUID_B, DIGEST_MUTATED)

    assert result.outcome is ProductIntegrityOutcome.FIRST_SEEN


# ---------------------------------------------------------------------------
# Identical re-observation -- the ordinary re-poll case
# ---------------------------------------------------------------------------


def test_identical_re_observation_matches() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    result = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.outcome is ProductIntegrityOutcome.MATCH
    assert result.first_seen_sha256 == DIGEST_ORIGINAL
    assert result.observed_sha256 == DIGEST_ORIGINAL


def test_identical_re_observation_writes_nothing() -> None:
    index, store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    writes_after_first = len(store.set_calls)

    index.observe(UUID_A, DIGEST_ORIGINAL)
    index.observe(UUID_A, DIGEST_ORIGINAL)

    assert len(store.set_calls) == writes_after_first


def test_identical_re_observation_is_cheap_and_does_not_re_read_the_store() -> None:
    index, store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    reads_after_first = len(store.get_calls)

    index.observe(UUID_A, DIGEST_ORIGINAL)

    assert len(store.get_calls) == reads_after_first


def test_match_preserves_the_original_first_seen_timestamp() -> None:
    clock = _FakeClock(start_ns=100)
    index, _store, _ = _index(clock=clock)
    index.observe(UUID_A, DIGEST_ORIGINAL)
    clock.advance(500)
    result = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.first_seen_at_ns == 100
    assert result.observed_at_ns == 600


# ---------------------------------------------------------------------------
# Mismatch -- the integrity event
# ---------------------------------------------------------------------------


def test_differing_digest_for_a_known_uuid_is_a_mismatch() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    result = index.observe(UUID_A, DIGEST_MUTATED)

    assert result.outcome is ProductIntegrityOutcome.MISMATCH
    assert result.first_seen_sha256 == DIGEST_ORIGINAL
    assert result.observed_sha256 == DIGEST_MUTATED


def test_mismatch_logs_critical(caplog: pytest.LogCaptureFixture) -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.product_index"):
        index.observe(UUID_A, DIGEST_MUTATED)

    records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(records) == 1
    assert UUID_A in records[0].getMessage()


def test_mismatch_does_not_overwrite_the_first_seen_digest_in_the_store() -> None:
    index, store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    persisted_before = store.data[_index_key(UUID_A)]

    index.observe(UUID_A, DIGEST_MUTATED)

    assert store.data[_index_key(UUID_A)] == persisted_before


def test_mismatch_performs_no_write_at_all() -> None:
    index, store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    writes_after_first = len(store.set_calls)

    index.observe(UUID_A, DIGEST_MUTATED)

    assert len(store.set_calls) == writes_after_first


def test_first_seen_digest_survives_a_mismatch_on_re_read() -> None:
    index, store, clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    index.observe(UUID_A, DIGEST_MUTATED)

    # A brand-new index over the same store: nothing in memory to help it.
    restarted = ProductIntegrityIndex(store=store, clock=clock)
    assert restarted.known_digest(UUID_A) == DIGEST_ORIGINAL


def test_repeated_mismatch_still_reports_the_original_digest() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    index.observe(UUID_A, DIGEST_MUTATED)
    third = index.observe(UUID_A, _digest("a third, different body"))

    assert third.outcome is ProductIntegrityOutcome.MISMATCH
    assert third.first_seen_sha256 == DIGEST_ORIGINAL


def test_original_digest_still_matches_after_a_mismatch() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    index.observe(UUID_A, DIGEST_MUTATED)
    result = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.outcome is ProductIntegrityOutcome.MATCH


# ---------------------------------------------------------------------------
# Cross-restart persistence
# ---------------------------------------------------------------------------


def test_index_survives_restart_and_still_matches() -> None:
    store = _FakeStore()
    first_index, _store, clock = _index(store=store)
    first_index.observe(UUID_A, DIGEST_ORIGINAL)

    restarted = ProductIntegrityIndex(store=store, clock=clock)
    result = restarted.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.outcome is ProductIntegrityOutcome.MATCH
    assert result.first_seen_sha256 == DIGEST_ORIGINAL


def test_restart_still_detects_a_mismatch_recorded_before_the_restart() -> None:
    store = _FakeStore()
    first_index, _store, clock = _index(store=store)
    first_index.observe(UUID_A, DIGEST_ORIGINAL)

    restarted = ProductIntegrityIndex(store=store, clock=clock)
    result = restarted.observe(UUID_A, DIGEST_MUTATED)

    assert result.outcome is ProductIntegrityOutcome.MISMATCH
    assert result.first_seen_sha256 == DIGEST_ORIGINAL


def test_restart_preserves_the_original_first_seen_timestamp() -> None:
    store = _FakeStore()
    clock = _FakeClock(start_ns=777)
    first_index, _store, _ = _index(store=store, clock=clock)
    first_index.observe(UUID_A, DIGEST_ORIGINAL)

    clock.advance(1_000)
    restarted = ProductIntegrityIndex(store=store, clock=clock)
    result = restarted.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.first_seen_at_ns == 777


def test_restart_with_an_empty_store_is_a_clean_slate_only_because_state_is_gone() -> None:
    """The in-memory-only failure mode this module exists to prevent, pinned
    as the contrast case: an index over a *different* store legitimately
    reports first-seen, which is exactly why the store must be durable.
    """
    first_index, _store, clock = _index()
    first_index.observe(UUID_A, DIGEST_ORIGINAL)

    fresh = ProductIntegrityIndex(store=_FakeStore(), clock=clock)
    assert fresh.observe(UUID_A, DIGEST_MUTATED).outcome is ProductIntegrityOutcome.FIRST_SEEN


# ---------------------------------------------------------------------------
# Corrupt persisted state -- fail closed
# ---------------------------------------------------------------------------

CORRUPT_PAYLOADS: list[tuple[str, bytes]] = [
    ("not_utf8", b"\xff\xfe\x00garbage"),
    ("not_json", b"this is not json at all"),
    ("json_list", b'["6a1b", "deadbeef"]'),
    ("json_string", b'"just a string"'),
    ("json_null", b"null"),
    ("missing_digest_key", b'{"first_seen_at_ns": 1}'),
    ("missing_timestamp_key", b'{"raw_sha256": "' + DIGEST_ORIGINAL.encode() + b'"}'),
    ("digest_not_a_string", b'{"raw_sha256": 12345, "first_seen_at_ns": 1}'),
    ("digest_too_short", b'{"raw_sha256": "abc123", "first_seen_at_ns": 1}'),
    (
        "digest_uppercase",
        b'{"raw_sha256": "' + DIGEST_ORIGINAL.upper().encode() + b'", "first_seen_at_ns": 1}',
    ),
    (
        "timestamp_not_an_int",
        b'{"raw_sha256": "' + DIGEST_ORIGINAL.encode() + b'", "first_seen_at_ns": "soon"}',
    ),
    (
        "timestamp_is_a_bool",
        b'{"raw_sha256": "' + DIGEST_ORIGINAL.encode() + b'", "first_seen_at_ns": true}',
    ),
]


@pytest.mark.parametrize(
    "label,raw", CORRUPT_PAYLOADS, ids=[label for label, _ in CORRUPT_PAYLOADS]
)
def test_corrupt_persisted_entry_never_reads_as_first_seen(label: str, raw: bytes) -> None:
    store = _FakeStore()
    store.data[_index_key(UUID_A)] = raw
    index, _store, _clock = _index(store=store)

    result = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.outcome is ProductIntegrityOutcome.MISMATCH
    assert result.is_integrity_alarm is True
    assert result.first_seen_sha256 is None
    assert result.first_seen_at_ns is None


def test_corrupt_persisted_entry_logs_critical(caplog: pytest.LogCaptureFixture) -> None:
    store = _FakeStore()
    store.data[_index_key(UUID_A)] = b"not json"
    index, _store, _clock = _index(store=store)

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.product_index"):
        index.observe(UUID_A, DIGEST_ORIGINAL)

    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_corrupt_persisted_entry_is_left_untouched_as_evidence() -> None:
    store = _FakeStore()
    store.data[_index_key(UUID_A)] = b"not json"
    index, _store, _clock = _index(store=store)

    index.observe(UUID_A, DIGEST_ORIGINAL)

    assert store.data[_index_key(UUID_A)] == b"not json"
    assert store.set_calls == []


def test_corrupt_state_is_sticky_within_the_process() -> None:
    store = _FakeStore()
    store.data[_index_key(UUID_A)] = b"not json"
    index, _store, _clock = _index(store=store)

    index.observe(UUID_A, DIGEST_ORIGINAL)
    second = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert second.outcome is ProductIntegrityOutcome.MISMATCH


def test_corrupt_entry_for_one_uuid_does_not_affect_another() -> None:
    store = _FakeStore()
    store.data[_index_key(UUID_A)] = b"not json"
    index, _store, _clock = _index(store=store)

    assert index.observe(UUID_B, DIGEST_ORIGINAL).outcome is ProductIntegrityOutcome.FIRST_SEEN


# ---------------------------------------------------------------------------
# known_digest -- read-only inspection, also fail-closed
# ---------------------------------------------------------------------------


def test_known_digest_returns_none_for_a_never_seen_uuid() -> None:
    index, _store, _clock = _index()
    assert index.known_digest(UUID_A) is None


def test_known_digest_returns_the_first_seen_digest() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    assert index.known_digest(UUID_A) == DIGEST_ORIGINAL


def test_known_digest_records_no_observation() -> None:
    index, store, _clock = _index()
    index.known_digest(UUID_A)
    assert store.set_calls == []


def test_known_digest_raises_rather_than_reporting_never_seen_on_corrupt_state() -> None:
    store = _FakeStore()
    store.data[_index_key(UUID_A)] = b"not json"
    index, _store, _clock = _index(store=store)

    with pytest.raises(CorruptProductIndexEntryError) as excinfo:
        index.known_digest(UUID_A)

    assert excinfo.value.product_uuid == UUID_A
    assert excinfo.value.detail


# ---------------------------------------------------------------------------
# Store failures must never be laundered into "never seen"
# ---------------------------------------------------------------------------


def test_unreadable_store_propagates_rather_than_reporting_first_seen() -> None:
    index = ProductIntegrityIndex(store=_RaisingGetStore(), clock=_FakeClock())
    with pytest.raises(OSError):
        index.observe(UUID_A, DIGEST_ORIGINAL)


def test_unreadable_store_never_writes_a_first_seen_entry() -> None:
    store = _RaisingGetStore()
    index = ProductIntegrityIndex(store=store, clock=_FakeClock())
    with pytest.raises(OSError):
        index.observe(UUID_A, DIGEST_ORIGINAL)
    assert store.set_calls == []


def test_failed_persist_does_not_advance_the_in_memory_view() -> None:
    """Persist FIRST, cache second. If the durable write fails, a later
    observation must NOT report MATCH off a memory-only entry.
    """
    failing = _RaisingSetStore()
    index = ProductIntegrityIndex(store=failing, clock=_FakeClock())
    with pytest.raises(OSError):
        index.observe(UUID_A, DIGEST_ORIGINAL)

    working = _FakeStore()
    recovered = ProductIntegrityIndex(store=working, clock=_FakeClock())
    assert recovered.observe(UUID_A, DIGEST_MUTATED).outcome is ProductIntegrityOutcome.FIRST_SEEN


def test_failed_persist_leaves_the_same_instance_able_to_retry() -> None:
    store = _FakeStore()
    index = ProductIntegrityIndex(store=store, clock=_FakeClock())

    calls: list[str] = []
    original_set = store.set

    def flaky_set(key: str, value: bytes) -> None:
        calls.append(key)
        if len(calls) == 1:
            raise OSError("transient")
        original_set(key, value)

    store.set = flaky_set  # type: ignore[method-assign]
    with pytest.raises(OSError):
        index.observe(UUID_A, DIGEST_ORIGINAL)

    assert index.observe(UUID_A, DIGEST_ORIGINAL).outcome is ProductIntegrityOutcome.FIRST_SEEN


# ---------------------------------------------------------------------------
# Input validation -- a malformed digest must never be first-written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_empty_product_uuid_is_rejected(bad: str) -> None:
    index, _store, _clock = _index()
    with pytest.raises(ValueError):
        index.observe(bad, DIGEST_ORIGINAL)


def test_non_string_product_uuid_is_rejected() -> None:
    index, _store, _clock = _index()
    with pytest.raises(TypeError):
        index.observe(object(), DIGEST_ORIGINAL)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    ["", "abc123", DIGEST_ORIGINAL.upper(), DIGEST_ORIGINAL[:-1], DIGEST_ORIGINAL + "0"],
)
def test_malformed_digest_is_rejected(bad: str) -> None:
    index, _store, _clock = _index()
    with pytest.raises(ValueError):
        index.observe(UUID_A, bad)


def test_non_string_digest_is_rejected() -> None:
    index, _store, _clock = _index()
    with pytest.raises(ValueError):
        index.observe(UUID_A, 12345)  # type: ignore[arg-type]


def test_rejected_input_writes_nothing() -> None:
    index, store, _clock = _index()
    with pytest.raises(ValueError):
        index.observe(UUID_A, "not-a-digest")
    assert store.set_calls == []


def test_known_digest_validates_its_uuid() -> None:
    index, _store, _clock = _index()
    with pytest.raises(ValueError):
        index.known_digest("")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_fake_store_satisfies_the_state_store_protocol() -> None:
    store: StateStore = _FakeStore()
    store.set("k", b"v")
    assert store.get("k") == b"v"


def test_result_is_immutable() -> None:
    index, _store, _clock = _index()
    result = index.observe(UUID_A, DIGEST_ORIGINAL)
    with pytest.raises(FrozenInstanceError):
        result.outcome = ProductIntegrityOutcome.MATCH  # type: ignore[misc]


def test_detail_is_populated_for_every_outcome() -> None:
    index, _store, _clock = _index()
    details: list[Any] = [
        index.observe(UUID_A, DIGEST_ORIGINAL).detail,
        index.observe(UUID_A, DIGEST_ORIGINAL).detail,
        index.observe(UUID_A, DIGEST_MUTATED).detail,
    ]
    assert all(isinstance(d, str) and d for d in details)


# ---------------------------------------------------------------------------
# DEFECT 3 -- UUID casing must not split the index
# ---------------------------------------------------------------------------
#
# `_require_hex_digest` is strict (64-char LOWERCASE hex, never normalised),
# but `_require_product_uuid` only checked "non-empty str". A product uuid
# differing from a stored one ONLY in case therefore keyed a SECOND
# first-write-wins entry, so the mutated bytes read as first-seen and the
# integrity alarm never fires. The uuid is a settlement identifier, so the fix
# is to reject a non-canonical form loudly -- never to silently lower-case it
# (`nws_envelope` takes the same stance: matched, never round-tripped).


def test_upper_case_uuid_is_rejected_rather_than_creating_a_second_entry() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)

    with pytest.raises(ValueError):
        index.observe(UUID_A.upper(), DIGEST_MUTATED)


def test_a_case_variant_uuid_never_hides_a_digest_mismatch() -> None:
    """The money bug: same product, upper-cased id, MUTATED bytes. Before the
    fix this returned FIRST_SEEN under a second key; it must never do that.
    """
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)

    with pytest.raises(ValueError):
        index.observe(UUID_A.swapcase(), DIGEST_MUTATED)

    assert index.known_digest(UUID_A) == DIGEST_ORIGINAL


@pytest.mark.parametrize(
    "bad",
    [
        UUID_A.upper(),
        UUID_A.replace("-", ""),
        f"urn:uuid:{UUID_A}",
        f"{{{UUID_A}}}",
        f" {UUID_A}",
        f"{UUID_A} ",
        UUID_A[:-1],
        f"{UUID_A}0",
        "not-a-uuid",
    ],
)
def test_non_canonical_product_uuid_is_rejected(bad: str) -> None:
    index, _store, _clock = _index()
    with pytest.raises(ValueError):
        index.observe(bad, DIGEST_ORIGINAL)


def test_rejected_uuid_writes_nothing() -> None:
    index, store, _clock = _index()
    with pytest.raises(ValueError):
        index.observe(UUID_A.upper(), DIGEST_ORIGINAL)
    assert store.set_calls == []


def test_known_digest_rejects_a_case_variant_uuid() -> None:
    index, _store, _clock = _index()
    index.observe(UUID_A, DIGEST_ORIGINAL)
    with pytest.raises(ValueError):
        index.known_digest(UUID_A.upper())


# ---------------------------------------------------------------------------
# Bootstrap manifest -- a wiped entry key must never downgrade a mutated
# re-fetch of a KNOWN uuid from MISMATCH to FIRST_SEEN.
#
# Full deletion-and-recreation of the whole backing file is not solvable
# here either, for the identical reason documented in gate.py's own
# bootstrap-sentinel tests: every key in this store, including the
# manifest, is gone together in that case. What the manifest closes is the
# achievable case -- the store still answers, but one entry key vanished
# out from under it (a stray DELETE, a partial restore) while the manifest
# survived. A real SqliteStateStore is required so a second connection to
# the same file can remove exactly one row.
# ---------------------------------------------------------------------------


def test_a_wiped_entry_for_a_known_uuid_is_a_mismatch_not_first_seen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """RED-first reproduction: observe a uuid (FIRST_SEEN, manifest records
    it), delete ONLY its entry row out from under the store, then re-observe
    the SAME uuid with MUTATED bytes. Before this fix that read as
    FIRST_SEEN -- silently accepting changed bytes under a stable id. It
    must read as MISMATCH.
    """
    import sqlite3

    from breezy.runtime.sqlite_store import SqliteStateStore

    path = tmp_path / "product_index.sqlite3"
    with SqliteStateStore(path) as store:
        index = ProductIntegrityIndex(store=store, clock=_FakeClock())
        first = index.observe(UUID_A, DIGEST_ORIGINAL)
        assert first.outcome is ProductIntegrityOutcome.FIRST_SEEN

    # Out-of-band tamper on the SAME file: remove only this uuid's entry.
    with sqlite3.connect(str(path)) as raw_conn:
        deleted = raw_conn.execute(
            "DELETE FROM state WHERE key = ?", (_index_key(UUID_A),)
        ).rowcount
        raw_conn.commit()
    assert deleted == 1, "the entry row must have existed to demonstrate its deletion"

    with SqliteStateStore(path) as reopened:
        restarted = ProductIntegrityIndex(store=reopened, clock=_FakeClock())
        result = restarted.observe(UUID_A, DIGEST_MUTATED)

    assert result.outcome is ProductIntegrityOutcome.MISMATCH
    assert result.outcome is not ProductIntegrityOutcome.FIRST_SEEN
    assert result.is_integrity_alarm is True


@pytest.mark.parametrize(
    "label,raw",
    [
        ("not_json", b"not json at all"),
        ("json_object_not_a_list", b'{"foo": "bar"}'),
        ("list_with_non_string_item", b"[123]"),
    ],
)
def test_corrupt_manifest_fails_closed_for_a_uuid_with_a_missing_entry(
    label: str, raw: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    """If the manifest itself cannot be decoded (or is not a JSON array of
    strings), a uuid with no entry key must never be waved through as
    first-seen -- corruption of the record that would otherwise prove
    "genuinely new" is itself an integrity signal, not a free pass.
    """
    from breezy.ingest.product_index import _MANIFEST_KEY

    store = _FakeStore()
    store.data[_MANIFEST_KEY] = raw
    index, _store, _clock = _index(store=store)

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.product_index"):
        result = index.observe(UUID_A, DIGEST_ORIGINAL)

    assert result.outcome is ProductIntegrityOutcome.MISMATCH
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_a_genuinely_new_uuid_is_still_first_seen_over_a_real_sqlite_store(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The other half of the same fix: a uuid this store has never recorded
    (absent from both the entry key AND the manifest) must still be
    reported FIRST_SEEN -- the manifest must not turn every legitimate new
    product into a false integrity alarm.
    """
    from breezy.runtime.sqlite_store import SqliteStateStore

    path = tmp_path / "fresh_product_index.sqlite3"
    with SqliteStateStore(path) as store:
        index = ProductIntegrityIndex(store=store, clock=_FakeClock())
        index.observe(UUID_A, DIGEST_ORIGINAL)  # unrelated prior history

        result = index.observe(UUID_B, DIGEST_ORIGINAL)

    assert result.outcome is ProductIntegrityOutcome.FIRST_SEEN
