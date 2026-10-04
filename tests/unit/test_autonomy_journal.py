"""ARCH-0 seam 5b: the ``journal/v1`` envelope, the write-once linked append and the chain read.

``append_journal`` writes one 0444 ``evidence/journal/<venue>/<kind>/<seq:010d>.json`` envelope per
record, linked to its predecessor by ``prev_sha256`` (the sha256 of the predecessor's file bytes).
Kinds are bare names and ``JOURNAL_KINDS`` is empty at ARCH-0, so every kind is refused until an
owner registers it. ``read_journal_chain`` returns the entries or ``JournalUnverified``.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import breezy.persistence.autonomy.rollback_journal as rj
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.rollback_journal import (
    JOURNAL_KINDS,
    JournalEntry,
    JournalHead,
    JournalRefusalReason,
    JournalRefused,
    JournalUnverified,
    JournalUnverifiedReason,
    append_journal,
    head_matches,
    read_journal_chain,
)
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused

VENUE = "polymarket_us"
KIND = "probe"
TS = 1_791_100_800 * 10**9
ENVELOPE_KEYS = frozenset({"schema", "kind", "venue", "seq", "ts_ns", "prev_sha256", "record"})
SHA_A = "a" * 64


@pytest.fixture(autouse=True)
def registered_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register one test kind; the shipped set is empty and tested separately."""
    monkeypatch.setattr(rj, "JOURNAL_KINDS", frozenset({KIND, "other"}))


def journal_dir(root: Path, kind: str = KIND, venue: str = VENUE) -> Path:
    return root / "evidence" / "journal" / venue / kind


def entry_file(root: Path, seq: int, kind: str = KIND) -> Path:
    return journal_dir(root, kind) / f"{seq:010d}.json"


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append(root: Path, n: int, *, kind: str = KIND) -> JournalHead:
    return append_journal(AutonomyPaths(root), kind, VENUE, {"n": n, "note": "x"}, ts_ns=TS + n)


def rewrite(path: Path, data: bytes) -> None:
    path.chmod(0o600)
    path.write_bytes(data)
    path.chmod(0o444)


# --- the shipped defaults -------------------------------------------------------------------


def test_journal_kinds_is_empty_at_arch0() -> None:
    assert JOURNAL_KINDS == frozenset()


def test_journal_unknown_kind_refused_when_nothing_is_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rj, "JOURNAL_KINDS", frozenset())  # the shipped value
    with pytest.raises(JournalRefused) as caught:
        append_journal(AutonomyPaths(tmp_path), KIND, VENUE, {"n": 1}, ts_ns=TS)
    assert caught.value.reason is JournalRefusalReason.UNKNOWN_KIND
    assert not (tmp_path / "evidence").exists()


# --- envelope -------------------------------------------------------------------------------


def test_journal_envelope_write_once_linked(tmp_path: Path) -> None:
    heads = [append(tmp_path, n) for n in (1, 2, 3)]
    files = [entry_file(tmp_path, n) for n in (1, 2, 3)]
    assert [h.seq for h in heads] == [1, 2, 3]
    assert [h.sha256 for h in heads] == [sha_of(f) for f in files]

    envelopes = [json.loads(f.read_bytes()) for f in files]
    for seq, (envelope, file) in enumerate(zip(envelopes, files, strict=True), start=1):
        assert set(envelope) == ENVELOPE_KEYS
        assert envelope["schema"] == "journal/v1"
        assert (envelope["kind"], envelope["venue"], envelope["seq"]) == (KIND, VENUE, seq)
        assert envelope["ts_ns"] == TS + seq
        assert envelope["record"] == {"n": seq, "note": "x"}
        assert stat.S_IMODE(file.stat().st_mode) == 0o444  # write-once, read-only
        assert file.read_bytes() == canonical_json(envelope)
    assert envelopes[0]["prev_sha256"] is None
    assert envelopes[1]["prev_sha256"] == sha_of(files[0])
    assert envelopes[2]["prev_sha256"] == sha_of(files[1])

    chain = read_journal_chain(AutonomyPaths(tmp_path), KIND, VENUE)
    assert not isinstance(chain, JournalUnverified)
    assert [e.record["n"] for e in chain] == [1, 2, 3]
    assert chain[-1].head() == heads[-1]
    assert [e.sha256 for e in chain] == [h.sha256 for h in heads]


def test_an_existing_entry_is_never_rewritten_by_a_later_append(tmp_path: Path) -> None:
    append(tmp_path, 1)
    first = entry_file(tmp_path, 1)
    snapshot = (first.read_bytes(), first.stat().st_ino, first.stat().st_mtime_ns)
    append(tmp_path, 2)
    assert (first.read_bytes(), first.stat().st_ino, first.stat().st_mtime_ns) == snapshot


def test_each_venue_and_kind_has_its_own_chain(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    append(tmp_path, 1)
    append(tmp_path, 2)
    other_kind = append_journal(paths, "other", VENUE, {"n": 9}, ts_ns=TS)
    other_venue = append_journal(paths, KIND, "kalshi", {"n": 9}, ts_ns=TS)
    assert other_kind.seq == 1 and other_venue.seq == 1
    chain = read_journal_chain(paths, KIND, VENUE)
    assert not isinstance(chain, JournalUnverified)
    assert len(chain) == 2


def test_shadow_paths_journal_under_their_own_root(tmp_path: Path) -> None:
    head = append_journal(ShadowPaths(tmp_path), KIND, VENUE, {"n": 1}, ts_ns=TS)
    assert head.seq == 1
    assert entry_file(tmp_path, 1).is_file()


def test_missing_journal_directory_reads_as_an_empty_chain(tmp_path: Path) -> None:
    assert read_journal_chain(AutonomyPaths(tmp_path), KIND, VENUE) == ()


def test_record_is_normalised_to_canonical_json_values(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    append_journal(
        paths, KIND, VENUE, {"p": Decimal("0.50"), "nested": {"b": [1, None, True]}}, ts_ns=TS
    )
    chain = read_journal_chain(paths, KIND, VENUE)
    assert not isinstance(chain, JournalUnverified)
    assert chain[0].record == {"p": "0.5", "nested": {"b": [1, None, True]}}


@pytest.mark.parametrize(
    "record",
    [{"x": 1.5}, {"x": float("nan")}, {"x": object()}, {1: "non-str key"}],
    ids=["float", "nan", "object", "int_key"],
)
def test_record_with_no_canonical_form_is_refused(tmp_path: Path, record: Any) -> None:
    with pytest.raises(WireRefused) as caught:
        append_journal(AutonomyPaths(tmp_path), KIND, VENUE, record, ts_ns=TS)
    assert caught.value.reason is WireRefusalReason.BAD_VALUE
    assert not (tmp_path / "evidence").exists()


def test_oversize_entry_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    big = {"blob": "x" * rj.MAX_JOURNAL_ENTRY_BYTES}
    with pytest.raises(JournalRefused) as caught:
        append_journal(AutonomyPaths(tmp_path), KIND, VENUE, big, ts_ns=TS)
    assert caught.value.reason is JournalRefusalReason.OVERSIZE
    assert not journal_dir(tmp_path).exists()


@pytest.mark.parametrize("kind", ["../x", "a/b", "", "Upper", "x" * 49, "has space", "a\x00b"])
def test_kinds_are_bare_names(tmp_path: Path, kind: str) -> None:
    with pytest.raises(WireRefused):
        append_journal(AutonomyPaths(tmp_path), kind, VENUE, {"n": 1}, ts_ns=TS)
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize("venue", ["../x", "", "A", "a/b"])
def test_venue_is_validated(tmp_path: Path, venue: str) -> None:
    with pytest.raises(WireRefused):
        append_journal(AutonomyPaths(tmp_path), KIND, venue, {"n": 1}, ts_ns=TS)


@pytest.mark.parametrize("ts_ns", [-1, True, 1.5, "1"])
def test_ts_ns_must_be_a_non_negative_int(tmp_path: Path, ts_ns: Any) -> None:
    with pytest.raises(WireRefused):
        append_journal(AutonomyPaths(tmp_path), KIND, VENUE, {"n": 1}, ts_ns=ts_ns)


def test_journal_unknown_kind_refused(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    with pytest.raises(JournalRefused) as caught:
        append_journal(paths, "not_registered", VENUE, {"n": 1}, ts_ns=TS)
    assert caught.value.reason is JournalRefusalReason.UNKNOWN_KIND
    assert not (tmp_path / "evidence").exists()
    assert read_journal_chain(paths, "not_registered", VENUE) == JournalUnverified(
        reason=JournalUnverifiedReason.UNKNOWN_KIND, seq=None
    )


# --- seq collision --------------------------------------------------------------------------


def test_journal_seq_collision_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append(tmp_path, 1)
    first = entry_file(tmp_path, 1)
    before = first.read_bytes()
    # A concurrent writer took seq 1 between our head read and our write: we saw an empty chain.
    monkeypatch.setattr(rj, "read_journal_chain", lambda *_a, **_k: ())
    with pytest.raises(JournalRefused) as caught:
        append_journal(AutonomyPaths(tmp_path), KIND, VENUE, {"n": 99}, ts_ns=TS + 99)
    assert caught.value.reason is JournalRefusalReason.SEQ_COLLISION
    assert first.read_bytes() == before
    assert sorted(p.name for p in journal_dir(tmp_path).iterdir()) == ["0000000001.json"]


def test_an_identical_concurrent_append_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = append(tmp_path, 1)
    monkeypatch.setattr(rj, "read_journal_chain", lambda *_a, **_k: ())
    again = append_journal(
        AutonomyPaths(tmp_path), KIND, VENUE, {"n": 1, "note": "x"}, ts_ns=TS + 1
    )
    assert again == head
    assert len(list(journal_dir(tmp_path).iterdir())) == 1


# --- chain verification ---------------------------------------------------------------------


def verify(root: Path) -> Any:
    return read_journal_chain(AutonomyPaths(root), KIND, VENUE)


def _tamper_middle_record(root: Path) -> None:
    path = entry_file(root, 2)
    envelope = json.loads(path.read_bytes())
    envelope["record"] = {"n": 666, "note": "forged"}
    rewrite(path, canonical_json(envelope))


def _delete_middle(root: Path) -> None:
    path = entry_file(root, 2)
    path.chmod(0o600)
    path.unlink()


def _stray_name(root: Path) -> None:
    (journal_dir(root) / "notes.txt").write_bytes(b"x")


def _bad_json(root: Path) -> None:
    rewrite(entry_file(root, 3), b"{nope")


def _non_canonical(root: Path) -> None:
    path = entry_file(root, 3)
    rewrite(path, json.dumps(json.loads(path.read_bytes()), indent=2).encode())


def _wrong_kind_inside(root: Path) -> None:
    path = entry_file(root, 3)
    envelope = json.loads(path.read_bytes())
    envelope["kind"] = "other"
    rewrite(path, canonical_json(envelope))


def _wrong_seq_inside(root: Path) -> None:
    path = entry_file(root, 3)
    envelope = json.loads(path.read_bytes())
    envelope["seq"] = 7
    rewrite(path, canonical_json(envelope))


def _wrong_venue_inside(root: Path) -> None:
    path = entry_file(root, 3)
    envelope = json.loads(path.read_bytes())
    envelope["venue"] = "kalshi"
    rewrite(path, canonical_json(envelope))


def _symlinked_entry(root: Path) -> None:
    path = entry_file(root, 3)
    target = root / "moved.json"
    target.write_bytes(path.read_bytes())
    path.chmod(0o600)
    path.unlink()
    os.symlink(target, path)


def _group_writable(root: Path) -> None:
    entry_file(root, 3).chmod(0o464)


def _oversize_entry(root: Path) -> None:
    rewrite(entry_file(root, 3), b"x" * (rj.MAX_JOURNAL_ENTRY_BYTES + 1))


def _first_entry_linked(root: Path) -> None:
    path = entry_file(root, 1)
    envelope = json.loads(path.read_bytes())
    envelope["prev_sha256"] = SHA_A
    rewrite(path, canonical_json(envelope))


CHAIN_FAULTS: dict[str, tuple[Callable[[Path], None], JournalUnverifiedReason, int | None]] = {
    # tampering with entry 2 breaks the link recorded in entry 3
    "tampered_middle_record": (_tamper_middle_record, JournalUnverifiedReason.LINK_BROKEN, 3),
    "deleted_middle_entry": (_delete_middle, JournalUnverifiedReason.SEQ_GAP, 3),
    "stray_name": (_stray_name, JournalUnverifiedReason.UNKNOWN_NAME, None),
    "invalid_json": (_bad_json, JournalUnverifiedReason.ENTRY_INVALID, 3),
    "non_canonical_bytes": (_non_canonical, JournalUnverifiedReason.ENTRY_INVALID, 3),
    "kind_inside_differs": (_wrong_kind_inside, JournalUnverifiedReason.ADDRESS_MISMATCH, 3),
    "seq_inside_differs": (_wrong_seq_inside, JournalUnverifiedReason.ADDRESS_MISMATCH, 3),
    "venue_inside_differs": (_wrong_venue_inside, JournalUnverifiedReason.ADDRESS_MISMATCH, 3),
    "symlinked_entry": (_symlinked_entry, JournalUnverifiedReason.ENTRY_UNREADABLE, 3),
    "group_writable_entry": (_group_writable, JournalUnverifiedReason.ENTRY_UNREADABLE, 3),
    "oversize_entry": (_oversize_entry, JournalUnverifiedReason.ENTRY_UNREADABLE, 3),
    "first_entry_has_a_predecessor": (
        _first_entry_linked,
        JournalUnverifiedReason.ENTRY_INVALID,
        1,
    ),
}


@pytest.mark.parametrize("fault", sorted(CHAIN_FAULTS))
def test_a_broken_chain_is_unverified_and_refuses_further_appends(
    tmp_path: Path, fault: str
) -> None:
    for n in (1, 2, 3):
        append(tmp_path, n)
    mutate, reason, seq = CHAIN_FAULTS[fault]
    mutate(tmp_path)
    result = verify(tmp_path)
    assert result == JournalUnverified(reason=reason, seq=seq), fault
    before = sorted(p.name for p in journal_dir(tmp_path).iterdir())
    with pytest.raises(JournalRefused) as caught:
        append(tmp_path, 4)
    assert caught.value.reason is JournalRefusalReason.CHAIN_UNVERIFIED
    assert sorted(p.name for p in journal_dir(tmp_path).iterdir()) == before


def test_the_temp_name_of_an_interrupted_write_is_ignored(tmp_path: Path) -> None:
    append(tmp_path, 1)
    (journal_dir(tmp_path) / ".tmp.0123456789abcdef").write_bytes(b"{")
    chain = verify(tmp_path)
    assert not isinstance(chain, JournalUnverified)
    assert append(tmp_path, 2).seq == 2


def test_a_journal_directory_that_is_not_a_directory_is_unverified(tmp_path: Path) -> None:
    folder = journal_dir(tmp_path)
    folder.parent.mkdir(parents=True, mode=0o700)
    folder.write_bytes(b"x")
    assert verify(tmp_path) == JournalUnverified(
        reason=JournalUnverifiedReason.DIRECTORY_UNREADABLE, seq=None
    )


# --- JournalEntry wire ----------------------------------------------------------------------


def _entry(**overrides: Any) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "schema": "journal/v1",
        "kind": KIND,
        "venue": VENUE,
        "seq": 2,
        "ts_ns": TS,
        "prev_sha256": SHA_A,
        "record": {"n": 1},
    }
    wire.update(overrides)
    return wire


def test_entry_roundtrip_and_head() -> None:
    entry = JournalEntry.from_wire(_entry())
    assert entry.to_wire() == _entry()
    assert entry.head() == JournalHead(
        seq=2, sha256=hashlib.sha256(canonical_json(_entry())).hexdigest()
    )


@pytest.mark.parametrize(
    ("wire", "reason"),
    [
        (_entry(seq=1), WireRefusalReason.BAD_VALUE),  # seq 1 must have no predecessor
        (_entry(prev_sha256=None), WireRefusalReason.BAD_VALUE),  # seq 2 needs one
        (_entry(seq=0), WireRefusalReason.BAD_VALUE),
        (_entry(seq=True), WireRefusalReason.BOOL_AS_INT),
        (_entry(seq="2"), WireRefusalReason.WRONG_TYPE),
        (_entry(prev_sha256="nothex"), WireRefusalReason.BAD_VALUE),
        (_entry(schema="journal/v2"), WireRefusalReason.BAD_VALUE),
        (_entry(kind="../x"), WireRefusalReason.BAD_VALUE),
        (_entry(venue="A"), WireRefusalReason.BAD_VALUE),
        (_entry(record=[1]), WireRefusalReason.WRONG_TYPE),
        (_entry(ts_ns=-5), WireRefusalReason.BAD_VALUE),
        ({k: v for k, v in _entry().items() if k != "record"}, WireRefusalReason.MISSING_KEY),
        (_entry(extra=1), WireRefusalReason.UNKNOWN_KEY),
    ],
)
def test_entry_refuses_inexact_wire(wire: dict[str, Any], reason: WireRefusalReason) -> None:
    with pytest.raises(WireRefused) as caught:
        JournalEntry.from_wire(wire)
    assert caught.value.reason is reason


def test_head_matches_compares_the_chain_head_and_an_empty_chain_never_matches(
    tmp_path: Path,
) -> None:
    """A5b-R5: empty-vs-external-head is a mismatch; an unverified chain never matches."""
    paths = AutonomyPaths(tmp_path)
    ghost = JournalHead(seq=1, sha256="a" * 64)
    assert head_matches(read_journal_chain(paths, KIND, VENUE), ghost) is False  # empty chain
    first = append(tmp_path, 1)
    second = append(tmp_path, 2)
    chain = read_journal_chain(paths, KIND, VENUE)
    assert head_matches(chain, second) is True
    assert head_matches(chain, first) is False  # a stale head
    assert head_matches(chain, JournalHead(seq=2, sha256="b" * 64)) is False
    broken = JournalUnverified(reason=JournalUnverifiedReason.LINK_BROKEN, seq=2)
    assert head_matches(broken, second) is False
