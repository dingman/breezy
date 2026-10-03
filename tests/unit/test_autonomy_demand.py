"""ARCH-0 seam 5b: the ``demand/v1`` record, its restrictive-only writer and its venue-veto reader.

The writer is the one ``demand/v1`` writer (ARCH C5 Z11, V9, U13): engine files and files from the
producers in ``DEMAND_WRITER_PRODUCER_IDS`` only, one unarchived file per (family, reason),
idempotent on ``verdict_id``, with the reserved INTEGRITY slots kept free of producer floods. The
reader turns any bad file, an unreadable directory or too many files into ``venue_veto``. There is
no archive API here (AUT-5 WP4 owns it).
"""

from __future__ import annotations

import ast
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy import demand
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.demand import (
    DemandOutcome,
    DemandRecord,
    DemandRefusalReason,
    DemandRefused,
    DemandScan,
    DemandVetoReason,
    scan_demands,
    write_engine_demand,
    write_producer_demand,
)
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.pins import (
    DEMAND_FILE_MAX_BYTES,
    DEMAND_FILES_MAX,
    DEMAND_INTEGRITY_RESERVED,
    DEMAND_WRITER_PRODUCER_IDS,
)
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused

SHA_A, SHA_B, SHA_C = ("a" * 64, "b" * 64, "c" * 64)
TS = 1_791_100_800 * 10**9
VENUE = "polymarket_us"
FAMILY = "pm_us_crh_fq_v1"
OTHER = "pm_us_crh_v4"
FOLD = frozenset({FAMILY, OTHER})
PRODUCER = "aut6.intraday"
DEMAND_KEYS = frozenset({"schema", "venue", "family_id", "reason", "writer", "verdict_id", "ts_ns"})
PRODUCER_CAP = DEMAND_FILES_MAX - DEMAND_INTEGRITY_RESERVED


def producer_rec(**overrides: Any) -> DemandRecord:
    fields: dict[str, Any] = {
        "venue": VENUE,
        "family_id": FAMILY,
        "reason": "integrity_floor",
        "writer": PRODUCER,
        "verdict_id": SHA_A,
        "ts_ns": TS,
    }
    fields.update(overrides)
    return DemandRecord(**fields)


def engine_rec(**overrides: Any) -> DemandRecord:
    return producer_rec(**{"writer": "engine", "verdict_id": None, **overrides})


def demand_dir(root: Path, venue: str = VENUE) -> Path:
    return root / "registry" / "demand" / venue


def names(root: Path, venue: str = VENUE) -> list[str]:
    folder = demand_dir(root, venue)
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def put(root: Path, record: DemandRecord, *, mode: int = 0o444) -> Path:
    """Hand-place a demand file (test fixture; bypasses the writer on purpose)."""
    folder = demand_dir(root, record.venue)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / record.filename()
    path.write_bytes(canonical_json(record.to_wire()))
    path.chmod(mode)
    return path


# --- demand/v1 record -----------------------------------------------------------------------


def test_demand_record_exact_key_set_and_roundtrip() -> None:
    record = producer_rec()
    wire = record.to_wire()
    assert set(wire) == DEMAND_KEYS
    assert wire["schema"] == "demand/v1"
    assert DemandRecord.from_wire(json.loads(canonical_json(wire))) == record
    engine = engine_rec()
    assert engine.to_wire()["verdict_id"] is None
    assert DemandRecord.from_wire(engine.to_wire()) == engine


def test_demand_record_golden_bytes() -> None:
    raw = canonical_json(producer_rec().to_wire())
    assert raw == (
        b'{"family_id":"pm_us_crh_fq_v1","reason":"integrity_floor","schema":"demand/v1",'
        b'"ts_ns":1791100800000000000,"venue":"polymarket_us",'
        b'"verdict_id":"' + SHA_A.encode() + b'","writer":"aut6.intraday"}'
    )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda w: w.pop("reason"), WireRefusalReason.MISSING_KEY),
        (lambda w: w.update(extra=1), WireRefusalReason.UNKNOWN_KEY),
        (lambda w: w.update(ts_ns=True), WireRefusalReason.BOOL_AS_INT),
        (lambda w: w.update(ts_ns="1"), WireRefusalReason.WRONG_TYPE),
        (lambda w: w.update(ts_ns=-1), WireRefusalReason.BAD_VALUE),
        (lambda w: w.update(schema="demand/v2"), WireRefusalReason.BAD_VALUE),
        (lambda w: w.update(family_id="../x"), WireRefusalReason.BAD_VALUE),
        (lambda w: w.update(venue="Poly Market"), WireRefusalReason.BAD_VALUE),
        (lambda w: w.update(writer="Aut6"), WireRefusalReason.BAD_VALUE),
        (lambda w: w.update(reason="has space"), WireRefusalReason.BAD_VALUE),
        (lambda w: w.update(verdict_id="xyz"), WireRefusalReason.BAD_VALUE),
        (lambda w: w.update(verdict_id=None), WireRefusalReason.BAD_VALUE),  # producer needs one
    ],
)
def test_demand_record_refuses_inexact_wire(
    mutate: Callable[[dict[str, Any]], object], reason: WireRefusalReason
) -> None:
    wire = producer_rec().to_wire()
    mutate(wire)
    with pytest.raises(WireRefused) as caught:
        DemandRecord.from_wire(wire)
    assert caught.value.reason is reason


def test_demand_record_file_names_follow_arch() -> None:
    assert engine_rec().filename() == f"{FAMILY}_{TS}_engine.json"
    assert producer_rec().filename() == f"{FAMILY}_integrity_floor_{SHA_A}_{PRODUCER}.json"


# --- writer ---------------------------------------------------------------------------------


def test_producer_demand_is_written_0444_in_the_venue_directory(tmp_path: Path) -> None:
    result = write_producer_demand(AutonomyPaths(tmp_path), producer_rec(), fold_family_ids=FOLD)
    assert result.outcome is DemandOutcome.WRITTEN
    assert names(tmp_path) == [producer_rec().filename()]
    path = demand_dir(tmp_path) / result.name
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    assert path.read_bytes() == canonical_json(producer_rec().to_wire())
    assert len(path.read_bytes()) <= DEMAND_FILE_MAX_BYTES
    assert stat.S_IMODE(demand_dir(tmp_path).stat().st_mode) == 0o700


def test_engine_demand_is_written_through_the_same_writer(tmp_path: Path) -> None:
    result = write_engine_demand(AutonomyPaths(tmp_path), engine_rec(), fold_family_ids=FOLD)
    assert result.outcome is DemandOutcome.WRITTEN
    assert names(tmp_path) == [f"{FAMILY}_{TS}_engine.json"]


def test_shadow_paths_write_under_their_own_root(tmp_path: Path) -> None:
    write_engine_demand(ShadowPaths(tmp_path), engine_rec(), fold_family_ids=FOLD)
    assert names(tmp_path) == [f"{FAMILY}_{TS}_engine.json"]
    assert scan_demands(ShadowPaths(tmp_path), VENUE, fold_family_ids=FOLD).demands


@pytest.mark.parametrize("writer", ["aut6.other", "engine", "aut6.intraday.x"])
def test_demand_writer_refuses_unlisted_producer(tmp_path: Path, writer: str) -> None:
    record = producer_rec(writer=writer)
    with pytest.raises(DemandRefused) as caught:
        write_producer_demand(AutonomyPaths(tmp_path), record, fold_family_ids=FOLD)
    assert caught.value.reason is DemandRefusalReason.UNLISTED_PRODUCER
    assert not (tmp_path / "registry").exists()  # refused before any directory is made


def test_demand_writer_accepts_a_producer_once_it_is_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demand, "DEMAND_WRITER_PRODUCER_IDS", (*DEMAND_WRITER_PRODUCER_IDS, "x.y"))
    record = producer_rec(writer="x.y")
    assert (
        write_producer_demand(AutonomyPaths(tmp_path), record, fold_family_ids=FOLD).outcome
        is DemandOutcome.WRITTEN
    )


def test_engine_writer_refuses_a_producer_record(tmp_path: Path) -> None:
    with pytest.raises(DemandRefused) as caught:
        write_engine_demand(AutonomyPaths(tmp_path), producer_rec(), fold_family_ids=FOLD)
    assert caught.value.reason is DemandRefusalReason.NOT_ENGINE_WRITER
    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"reason": "slow_burn"}, DemandRefusalReason.UNKNOWN_REASON),
        ({"family_id": "pm_us_unknown"}, DemandRefusalReason.UNKNOWN_FAMILY),
    ],
)
def test_demand_writer_refuses_what_would_veto_the_whole_venue(
    tmp_path: Path, overrides: dict[str, Any], reason: DemandRefusalReason
) -> None:
    with pytest.raises(DemandRefused) as caught:
        write_producer_demand(
            AutonomyPaths(tmp_path), producer_rec(**overrides), fold_family_ids=FOLD
        )
    assert caught.value.reason is reason
    assert names(tmp_path) == []


def test_demand_writer_refuses_an_oversize_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demand, "DEMAND_FILE_MAX_BYTES", 16)
    with pytest.raises(DemandRefused) as caught:
        write_producer_demand(AutonomyPaths(tmp_path), producer_rec(), fold_family_ids=FOLD)
    assert caught.value.reason is DemandRefusalReason.OVERSIZE
    assert names(tmp_path) == []


def test_producer_demand_idempotent_on_verdict_id(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    first = write_producer_demand(paths, producer_rec(), fold_family_ids=FOLD)
    before = (demand_dir(tmp_path) / first.name).read_bytes()
    # A re-run of the same verdict later in time adds nothing and never touches the first file.
    again = write_producer_demand(paths, producer_rec(ts_ns=TS + 10**9), fold_family_ids=FOLD)
    assert again.outcome is DemandOutcome.ALREADY_PRESENT
    assert again.name == first.name
    assert names(tmp_path) == [first.name]
    assert (demand_dir(tmp_path) / first.name).read_bytes() == before


def test_one_unarchived_file_per_family_and_reason(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    write_producer_demand(paths, producer_rec(), fold_family_ids=FOLD)
    other_verdict = write_producer_demand(
        paths, producer_rec(verdict_id=SHA_B, ts_ns=TS + 1), fold_family_ids=FOLD
    )
    assert other_verdict.outcome is DemandOutcome.SLOT_OCCUPIED
    other_family = write_producer_demand(
        paths, producer_rec(family_id=OTHER, verdict_id=SHA_B), fold_family_ids=FOLD
    )
    assert other_family.outcome is DemandOutcome.WRITTEN
    assert len(names(tmp_path)) == 2


def test_engine_demand_repeats_do_not_pile_up_files(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    for offset in range(5):  # the engine retries on every pass while the append keeps failing
        write_engine_demand(paths, engine_rec(ts_ns=TS + offset), fold_family_ids=FOLD)
    assert names(tmp_path) == [f"{FAMILY}_{TS}_engine.json"]


def test_producer_demand_flood_cannot_exhaust_integrity_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demand, "DEMAND_REASONS", frozenset({"integrity_floor", "slow_burn"}))
    families = frozenset(f"fam_{i:03d}" for i in range(DEMAND_FILES_MAX + 8))
    paths = AutonomyPaths(tmp_path)
    ordered = sorted(families)

    written = 0
    for family in ordered:  # a non-integrity producer flood
        try:
            result = write_producer_demand(
                paths,
                producer_rec(family_id=family, reason="slow_burn", verdict_id=SHA_C),
                fold_family_ids=families,
            )
        except DemandRefused as refused:
            assert refused.reason is DemandRefusalReason.PRODUCER_CAP
            break
        assert result.outcome is DemandOutcome.WRITTEN
        written += 1
    assert written == PRODUCER_CAP
    assert len(names(tmp_path)) == PRODUCER_CAP

    # The reserved slots still take INTEGRITY files, up to the venue maximum and no further.
    for family in ordered[written : written + DEMAND_INTEGRITY_RESERVED]:
        result = write_producer_demand(
            paths, producer_rec(family_id=family, verdict_id=SHA_A), fold_family_ids=families
        )
        assert result.outcome is DemandOutcome.WRITTEN
    assert len(names(tmp_path)) == DEMAND_FILES_MAX
    with pytest.raises(DemandRefused) as full:
        write_engine_demand(paths, engine_rec(family_id=ordered[-1]), fold_family_ids=families)
    assert full.value.reason is DemandRefusalReason.SLOTS_FULL
    assert len(names(tmp_path)) == DEMAND_FILES_MAX  # never past the maximum

    scan = scan_demands(paths, VENUE, fold_family_ids=families)
    assert scan.venue_veto is False  # the flood never reached the venue-wide veto
    assert len(scan.demands) == DEMAND_FILES_MAX


@pytest.mark.parametrize("case", [pytest.param("writer_api", id="writer_api")])
def test_producer_demand_write_is_restrictive_only(tmp_path: Path, case: str) -> None:
    assert case == "writer_api"
    paths = AutonomyPaths(tmp_path)
    existing = [
        write_engine_demand(paths, engine_rec(), fold_family_ids=FOLD),
        write_producer_demand(paths, producer_rec(family_id=OTHER), fold_family_ids=FOLD),
    ]
    snapshot = {
        r.name: (
            (demand_dir(tmp_path) / r.name).read_bytes(),
            (demand_dir(tmp_path) / r.name).stat().st_ino,
            (demand_dir(tmp_path) / r.name).stat().st_mtime_ns,
        )
        for r in existing
    }
    attempts: list[Callable[[], object]] = [
        lambda: write_producer_demand(paths, producer_rec(family_id=OTHER), fold_family_ids=FOLD),
        lambda: write_producer_demand(
            paths, producer_rec(family_id=OTHER, verdict_id=SHA_B), fold_family_ids=FOLD
        ),
        lambda: write_engine_demand(paths, engine_rec(), fold_family_ids=FOLD),
        lambda: write_engine_demand(paths, engine_rec(reason="nope"), fold_family_ids=FOLD),
        lambda: write_producer_demand(paths, producer_rec(writer="evil"), fold_family_ids=FOLD),
    ]
    for attempt in attempts:
        try:
            attempt()
        except DemandRefused:
            pass
    for name, (data, inode, mtime) in snapshot.items():  # nothing existing was edited or replaced
        path = demand_dir(tmp_path) / name
        assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == (
            data,
            inode,
            mtime,
        )
    # The API can add a stop and cannot lift one: no archive, remove or rewrite entry point.
    assert not hasattr(demand, "archive")
    assert set(demand.__all__) == {
        "DemandOutcome", "DemandRecord", "DemandRefusalReason", "DemandRefused", "DemandScan",
        "DemandVetoReason", "DemandWrite", "scan_demands", "write_engine_demand",
        "write_producer_demand",
    }  # fmt: skip
    source = Path(demand.__file__ or "").read_text(encoding="utf-8")
    forbidden = {"unlink", "rename", "replace", "rmdir", "remove", "truncate", "replace_atomic"}
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
    }
    assert called.isdisjoint(forbidden)


def test_write_failure_surfaces_and_leaves_no_file(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    write_engine_demand(paths, engine_rec(family_id=OTHER), fold_family_ids=FOLD)
    demand_dir(tmp_path).chmod(0o500)  # the directory is not writable
    try:
        with pytest.raises(DemandRefused) as caught:
            write_producer_demand(paths, producer_rec(), fold_family_ids=FOLD)
    finally:
        demand_dir(tmp_path).chmod(0o700)
    assert caught.value.reason is DemandRefusalReason.WRITE_FAILED
    assert names(tmp_path) == [f"{OTHER}_{TS}_engine.json"]


# --- reader ---------------------------------------------------------------------------------


def test_scan_of_an_absent_directory_is_empty_and_not_a_veto(tmp_path: Path) -> None:
    scan = scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD)
    assert scan == DemandScan(demands=(), venue_veto=False, veto_reason=None)


def test_scan_returns_valid_demands_in_name_order(tmp_path: Path) -> None:
    put(tmp_path, producer_rec(family_id=OTHER))
    put(tmp_path, engine_rec())
    scan = scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD)
    assert scan.venue_veto is False
    assert [d.family_id for d in scan.demands] == sorted([OTHER, FAMILY])
    assert scan.demands == tuple(sorted(scan.demands, key=lambda d: d.filename()))


def test_scan_ignores_only_the_write_once_temp_name(tmp_path: Path) -> None:
    put(tmp_path, engine_rec())
    (demand_dir(tmp_path) / ".tmp.0123456789abcdef").write_bytes(b"{")
    assert scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD).venue_veto is False
    (demand_dir(tmp_path) / ".tmp.0123456789abcdeg").write_bytes(b"{")  # not the pinned pattern
    scan = scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD)
    assert scan.venue_veto is True


def test_scan_never_returns_demands_of_another_venue_directory(tmp_path: Path) -> None:
    put(tmp_path, engine_rec(venue="kalshi"))
    assert scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD).demands == ()


BadCase = Callable[[Path], None]


def _raw(root: Path, name: str, data: bytes, mode: int = 0o444) -> None:
    folder = demand_dir(root)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / name).write_bytes(data)
    (folder / name).chmod(mode)


def _wire_variant(**changes: Any) -> BadCase:
    def build(root: Path) -> None:
        record = engine_rec()
        wire = {**record.to_wire(), **changes}
        _raw(root, record.filename(), canonical_json(wire))

    return build


def _ghost_family(root: Path) -> None:
    record = engine_rec(family_id="pm_us_ghost")  # self-consistent file, family not in the fold
    _raw(root, record.filename(), canonical_json(record.to_wire()))


def _unparseable(root: Path) -> None:
    _raw(root, engine_rec().filename(), b"{not json")


def _oversize(root: Path) -> None:
    wire = {**engine_rec().to_wire(), "writer": "engine", "venue": "v" * (DEMAND_FILE_MAX_BYTES)}
    _raw(root, engine_rec().filename(), canonical_json(wire))


def _symlinked(root: Path) -> None:
    target = root / "elsewhere.json"
    target.write_bytes(canonical_json(engine_rec().to_wire()))
    folder = demand_dir(root)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.symlink(target, folder / engine_rec().filename())


def _wrong_name(root: Path) -> None:
    _raw(root, f"{FAMILY}_{TS + 1}_engine.json", canonical_json(engine_rec().to_wire()))


def _stray_name(root: Path) -> None:
    _raw(root, "notes.txt", b"x")


def _too_many(root: Path) -> None:
    for index in range(DEMAND_FILES_MAX + 1):
        put(root, engine_rec(ts_ns=TS + index))


def _group_writable(root: Path) -> None:
    put(root, engine_rec(), mode=0o464)


def _directory_symlink(root: Path) -> None:
    real = root / "real_demand"
    real.mkdir(mode=0o700)
    parent = root / "registry" / "demand"
    parent.mkdir(parents=True, mode=0o700)
    os.symlink(real, parent / VENUE)


def _directory_is_a_file(root: Path) -> None:
    parent = root / "registry" / "demand"
    parent.mkdir(parents=True, mode=0o700)
    (parent / VENUE).write_bytes(b"x")


BAD_CASES: dict[str, tuple[BadCase, DemandVetoReason]] = {
    "unparseable": (_unparseable, DemandVetoReason.BAD_FILE),
    "oversize": (_oversize, DemandVetoReason.BAD_FILE),
    "symlinked_file": (_symlinked, DemandVetoReason.BAD_FILE),
    "unknown_key": (_wire_variant(extra=1), DemandVetoReason.BAD_FILE),
    "unknown_schema": (_wire_variant(schema="demand/v9"), DemandVetoReason.BAD_FILE),
    "family_not_in_fold": (_ghost_family, DemandVetoReason.BAD_FILE),
    "reason_outside_closed_set": (_wire_variant(reason="slow_burn"), DemandVetoReason.BAD_FILE),
    "foreign_venue_inside": (_wire_variant(venue="kalshi"), DemandVetoReason.BAD_FILE),
    "name_does_not_match_record": (_wrong_name, DemandVetoReason.BAD_FILE),
    "stray_name": (_stray_name, DemandVetoReason.BAD_FILE),
    "group_writable": (_group_writable, DemandVetoReason.BAD_FILE),
    "too_many_files": (_too_many, DemandVetoReason.TOO_MANY_FILES),
    "directory_is_a_symlink": (_directory_symlink, DemandVetoReason.DIR_UNREADABLE),
    "directory_is_a_file": (_directory_is_a_file, DemandVetoReason.DIR_UNREADABLE),
}


@pytest.mark.parametrize("case", [pytest.param("reader", id="reader")])
def test_bad_demand_file_vetoes_venue(tmp_path: Path, case: str) -> None:
    assert case == "reader"
    for name, (build, expected) in BAD_CASES.items():
        root = tmp_path / name
        root.mkdir(mode=0o700)
        build(root)
        scan = scan_demands(AutonomyPaths(root), VENUE, fold_family_ids=FOLD)
        assert scan.venue_veto is True, name
        assert scan.veto_reason is expected, name
        assert scan.demands == (), name  # a vetoed venue carries no partial answer


def test_a_good_file_beside_a_bad_one_does_not_lift_the_veto(tmp_path: Path) -> None:
    put(tmp_path, engine_rec(family_id=OTHER))
    _unparseable(tmp_path)
    scan = scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD)
    assert scan.venue_veto is True
    assert scan.veto_reason is DemandVetoReason.BAD_FILE


def test_unreadable_demand_directory_vetoes_the_venue(tmp_path: Path) -> None:
    put(tmp_path, engine_rec())
    demand_dir(tmp_path).chmod(0)
    try:
        scan = scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD)
    finally:
        demand_dir(tmp_path).chmod(0o700)
    assert scan.venue_veto is True
    assert scan.veto_reason is DemandVetoReason.DIR_UNREADABLE


def test_exactly_the_maximum_number_of_files_is_not_a_veto(tmp_path: Path) -> None:
    for index in range(DEMAND_FILES_MAX):
        put(tmp_path, engine_rec(ts_ns=TS + index))
    scan = scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD)
    assert scan.venue_veto is False
    assert len(scan.demands) == DEMAND_FILES_MAX


def test_veto_detail_never_carries_a_path(tmp_path: Path) -> None:
    _unparseable(tmp_path)
    scan = scan_demands(AutonomyPaths(tmp_path), VENUE, fold_family_ids=FOLD)
    assert str(tmp_path) not in repr(scan)


def test_scan_rejects_an_invalid_venue_component(tmp_path: Path) -> None:
    with pytest.raises(WireRefused):
        scan_demands(AutonomyPaths(tmp_path), "../escape", fold_family_ids=FOLD)
