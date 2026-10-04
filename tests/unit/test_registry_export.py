"""ARCH-0 seam 6f: ``registry_export`` (``RegistryReader``, ``write_export``, ``newest_export``).

The reader is read-only and maps every failure onto ``UnreadableReason``. The exports directory is
classified name by name (A5-R6, A6-R1): this venue's exports are candidates, a closed set of foreign
names is ignored, and anything else fails closed.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import re
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any, Final

import pytest

import breezy.persistence.autonomy.registry_export as rx
import breezy.persistence.autonomy.registry_store as rs
from breezy.persistence.autonomy import chain, rollback_journal
from breezy.persistence.autonomy.hwm import HwmPresent, hwm_check, next_hwm
from breezy.persistence.autonomy.paths import VENUE_RE, AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.registry_export import (
    ExportAbsent,
    ExportRead,
    ExportRefused,
    ExportUnreadable,
    RegistryReader,
    RegistryUnreadable,
    newest_export,
    unreadable_reason,
    write_export,
)
from breezy.persistence.autonomy.registry_store import RegistryStore
from breezy.persistence.autonomy.schemas import (
    ExportTrailer,
    RefusalReason,
    TransitionRow,
    UnreadableReason,
    WriterMode,
)
from breezy.persistence.autonomy.single_read import (
    SingleReadReason,
    SingleReadRefused,
    WriteOutcome,
)
from breezy.persistence.autonomy.wire import WireRefused
from tests.support.autonomy_write_scan import find_write_sites
from tests.support.entry_points import SRC_DIR
from tests.unit.test_autonomy_files_one_writer import unallowed_write_sites
from tests.unit.test_registry_store import NOW, SEC, VENUE, bootstrap, demote

MODULE_PATH: Final = SRC_DIR / "breezy" / "persistence" / "autonomy" / "registry_export.py"
DAY: Final = "2026-12-01"
OTHER_VENUE: Final = "kalshi"
BUSY_MS: Final = 0


# --- fixtures and helpers -------------------------------------------------------------------------


@pytest.fixture
def paths(tmp_path: Path) -> AutonomyPaths:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    return AutonomyPaths(root)


@pytest.fixture
def store(paths: AutonomyPaths, tmp_path: Path) -> RegistryStore:
    return RegistryStore.initialise(paths, repo_root=tmp_path / "repo")


@pytest.fixture
def stored_rows(store: RegistryStore) -> tuple[TransitionRow, ...]:
    """Two sealed rows: BOOTSTRAP then DEMOTE."""
    first = store.append([bootstrap()], expected_prior_seq=0, mode=WriterMode.BOOTSTRAP, now_ns=NOW)
    second = store.append([demote()], expected_prior_seq=1, mode=WriterMode.DAILY, now_ns=NOW + SEC)
    return (*first.rows, *second.rows)


@pytest.fixture
def export_dir(paths: AutonomyPaths) -> Path:
    directory = paths.export_dir()
    directory.mkdir(parents=True, mode=0o700)
    for parent in (directory.parent, directory):
        parent.chmod(0o700)
    return directory


def trailer_for(
    rows: tuple[TransitionRow, ...], export_seq: int, venue: str = VENUE
) -> ExportTrailer:
    last = rows[-1]
    assert last.venue_seq is not None and last.transition_hash is not None
    return ExportTrailer(
        venue=venue,
        venue_seq=last.venue_seq,
        chain_head=last.transition_hash,
        export_seq=export_seq,
    )


def put_export(
    paths: AutonomyPaths,
    rows: tuple[TransitionRow, ...],
    export_seq: int,
    *,
    day: str = DAY,
    hwm: bool = False,
) -> Path:
    write_export(
        paths,
        day=day,
        trailer=trailer_for(rows, export_seq),
        rows=rows,
        hwm_export_seq=export_seq if hwm else None,
    )
    return paths.export_file(VENUE, day, hwm_export_seq=export_seq if hwm else None)


def raw(store: RegistryStore) -> sqlite3.Connection:
    return sqlite3.connect(store._db)


def reader(paths: AutonomyPaths, busy_ms: int = BUSY_MS) -> RegistryReader:
    return RegistryReader(paths, busy_timeout_ms=busy_ms)


def reason_of(call: Any) -> UnreadableReason:
    with pytest.raises(RegistryUnreadable) as caught:
        call()
    return caught.value.reason


def plant(path: Path, data: bytes, *, mode: int = 0o444) -> Path:
    """A file written around ``write_export``, with a mode ``newest_export`` accepts."""
    path.write_bytes(data)
    path.chmod(mode)
    return path


def tree_snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


# --- the reader -----------------------------------------------------------------------------------


def test_registry_readonly_open_engine_stopped(
    paths: AutonomyPaths, store: RegistryStore, stored_rows: tuple[TransitionRow, ...]
) -> None:
    before = tree_snapshot(store._db.parent)
    mtime = store._db.stat().st_mtime_ns
    rows = reader(paths).read_venue_rows(VENUE)
    assert rows == stored_rows
    assert [r.venue_seq for r in reader(paths).read_venue_rows(VENUE, after_seq=1)] == [2]
    assert reader(paths).read_venue_rows(VENUE, after_seq=2) == ()
    assert reader(paths).read_venue_rows(OTHER_VENUE) == ()
    assert tree_snapshot(store._db.parent) == before  # no journal, no write
    assert store._db.stat().st_mtime_ns == mtime
    assert chain.verify_venue_chain(rows, VENUE).head_venue_seq == 2


def test_registry_reader_mode_ro_query_only(paths: AutonomyPaths, store: RegistryStore) -> None:
    conn = reader(paths)._connect()
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        assert conn.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE intruder (x)")
        # query_only is the second belt: with it off, the mode=ro open still refuses a write.
        conn.execute("PRAGMA query_only = OFF")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE intruder (x)")
    finally:
        conn.close()


def test_reader_never_sets_a_write_pragma() -> None:
    """``synchronous`` and ``journal_mode`` belong to the writer (A6e-R6); the reader only reads."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    pragmas = [
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.upper().startswith("PRAGMA")
    ]
    assert pragmas  # the scan sees the reader's own pragmas
    assert not [p for p in pragmas if "synchronous" in p or "journal_mode" in p]


def test_reader_refuses_a_missing_database_as_io(paths: AutonomyPaths) -> None:
    assert reason_of(lambda: reader(paths).read_venue_rows(VENUE)) is UnreadableReason.IO


def test_reader_refuses_a_database_that_is_not_a_regular_file(
    paths: AutonomyPaths, store: RegistryStore, tmp_path: Path
) -> None:
    real = tmp_path / "elsewhere.sqlite"
    store._db.rename(real)
    store._db.symlink_to(real)
    assert reason_of(lambda: reader(paths).read_venue_rows(VENUE)) is UnreadableReason.IO


_FOREIGN_DDL: Final[dict[str, str]] = {
    "extra_table": "CREATE TABLE intruder (x)",
    "extra_trigger": ("CREATE TRIGGER intruder_t BEFORE INSERT ON transitions BEGIN SELECT 1; END"),
    "missing_update_trigger": "DROP TRIGGER transitions_no_update",
    "missing_meta": "DROP TABLE meta",
    "meta_other_schema": "UPDATE meta SET schema = 'registry/v2'",
    "application_id": "PRAGMA application_id = 7",
    "user_version": "PRAGMA user_version = 2",
}


@pytest.mark.parametrize("case", sorted(_FOREIGN_DDL))
def test_reader_refuses_foreign_ddl(paths: AutonomyPaths, store: RegistryStore, case: str) -> None:
    conn = raw(store)
    conn.execute(_FOREIGN_DDL[case])
    conn.commit()
    conn.close()
    assert (
        reason_of(lambda: reader(paths).read_venue_rows(VENUE)) is UnreadableReason.SCHEMA_MISMATCH
    )


def test_reader_refuses_an_empty_foreign_database(paths: AutonomyPaths) -> None:
    (paths.root / "registry").mkdir(mode=0o700)
    sqlite3.connect(paths.registry_db()).close()
    assert (
        reason_of(lambda: reader(paths).read_venue_rows(VENUE)) is UnreadableReason.SCHEMA_MISMATCH
    )


def test_reader_maps_a_file_that_is_not_sqlite_to_sqlite_error(paths: AutonomyPaths) -> None:
    (paths.root / "registry").mkdir(mode=0o700)
    paths.registry_db().write_bytes(b"this is not a database" * 100)
    assert reason_of(lambda: reader(paths).read_venue_rows(VENUE)) is UnreadableReason.SQLITE_ERROR


def test_reader_maps_an_undecodable_stored_row_to_schema_mismatch(
    paths: AutonomyPaths, store: RegistryStore, stored_rows: tuple[TransitionRow, ...]
) -> None:
    conn = store._open()
    try:
        # A row whose columns fit the DDL but not the C5 row schema; the guard allows head + 1.
        record = conn.execute(rs._SELECT_ROWS + " WHERE venue_seq = 2").fetchone()
        forged = list(record)
        forged[rs.COLUMNS.index("seq")] = None
        forged[rs.COLUMNS.index("venue_seq")] = 3
        forged[rs.COLUMNS.index("transition_id")] = "9" * 64
        forged[rs.COLUMNS.index("kind")] = "NOT_A_KIND"
        columns = [c for c in rs.COLUMNS if c != "seq"]
        marks = ", ".join("?" for _ in columns)
        conn.execute(f"INSERT INTO transitions ({', '.join(columns)}) VALUES ({marks})", forged[1:])
    finally:
        conn.close()
    assert reason_of(lambda: reader(paths).read_venue_rows(VENUE)) is (
        UnreadableReason.SCHEMA_MISMATCH
    )


def _sqlite_error(code: int) -> sqlite3.Error:
    exc = sqlite3.OperationalError("planted")
    exc.sqlite_errorcode = code
    return exc


_ERROR_MAP: Final[dict[str, tuple[int, UnreadableReason]]] = {
    "busy": (sqlite3.SQLITE_BUSY, UnreadableReason.BUSY),
    "busy_recovery": (sqlite3.SQLITE_BUSY_RECOVERY, UnreadableReason.BUSY),
    "busy_snapshot": (sqlite3.SQLITE_BUSY_SNAPSHOT, UnreadableReason.BUSY),
    "locked": (sqlite3.SQLITE_LOCKED, UnreadableReason.BUSY),
    "locked_sharedcache": (sqlite3.SQLITE_LOCKED_SHAREDCACHE, UnreadableReason.BUSY),
    "readonly_rollback": (sqlite3.SQLITE_READONLY_ROLLBACK, UnreadableReason.HOT_JOURNAL),
    "readonly_other": (sqlite3.SQLITE_READONLY, UnreadableReason.SQLITE_ERROR),
    "readonly_dbmoved": (sqlite3.SQLITE_READONLY_DBMOVED, UnreadableReason.SQLITE_ERROR),
    "ioerr": (sqlite3.SQLITE_IOERR, UnreadableReason.IO),
    "ioerr_read": (sqlite3.SQLITE_IOERR_READ, UnreadableReason.IO),
    "cantopen": (sqlite3.SQLITE_CANTOPEN, UnreadableReason.IO),
    "cantopen_notempdir": (sqlite3.SQLITE_CANTOPEN_NOTEMPDIR, UnreadableReason.IO),
    "error": (sqlite3.SQLITE_ERROR, UnreadableReason.SQLITE_ERROR),
    "corrupt": (sqlite3.SQLITE_CORRUPT, UnreadableReason.SQLITE_ERROR),
    "notadb": (sqlite3.SQLITE_NOTADB, UnreadableReason.SQLITE_ERROR),
    "full": (sqlite3.SQLITE_FULL, UnreadableReason.SQLITE_ERROR),
    "perm": (sqlite3.SQLITE_PERM, UnreadableReason.SQLITE_ERROR),
}


@pytest.mark.parametrize("case", sorted(_ERROR_MAP))
def test_reader_maps_every_sqlite_error(case: str) -> None:
    code, expected = _ERROR_MAP[case]
    assert unreadable_reason(_sqlite_error(code)) is expected


def test_the_error_map_reaches_every_reason_a_sqlite_code_can_give() -> None:
    """``schema_mismatch`` is never a result code: the foreign-DDL tests cover it."""
    mapped = {reason for _code, reason in _ERROR_MAP.values()}
    # schema_mismatch is the reader's own check; venue_malformed is the resolver's (A8c-R3)
    assert mapped == set(UnreadableReason) - {
        UnreadableReason.SCHEMA_MISMATCH,
        UnreadableReason.VENUE_MALFORMED,
    }


def test_errors_with_no_result_code_and_os_errors_map_to_their_reasons() -> None:
    assert unreadable_reason(sqlite3.ProgrammingError("x")) is UnreadableReason.SQLITE_ERROR
    assert unreadable_reason(FileNotFoundError("x")) is UnreadableReason.IO
    assert unreadable_reason(PermissionError("x")) is UnreadableReason.IO


def test_reader_distinguishes_busy(
    paths: AutonomyPaths, store: RegistryStore, stored_rows: tuple[TransitionRow, ...]
) -> None:
    holder = store._open()
    try:
        holder.execute("BEGIN EXCLUSIVE")
        busy = reason_of(lambda: reader(paths).read_venue_rows(VENUE))
        started = time.monotonic()
        waited = reason_of(lambda: reader(paths, busy_ms=250).read_venue_rows(VENUE))
        elapsed = time.monotonic() - started
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert busy is waited is UnreadableReason.BUSY
    assert elapsed >= 0.2  # busy_timeout_ms is honoured, not ignored
    assert reader(paths).read_venue_rows(VENUE) == stored_rows  # and BUSY clears

    conn = raw(store)
    conn.execute("DROP TRIGGER transitions_no_delete")
    conn.commit()
    conn.close()
    drift = reason_of(lambda: reader(paths).read_venue_rows(VENUE))
    store._db.rename(store._db.with_name("gone.sqlite"))
    missing = reason_of(lambda: reader(paths).read_venue_rows(VENUE))
    assert {busy, drift, missing} == {
        UnreadableReason.BUSY,
        UnreadableReason.SCHEMA_MISMATCH,
        UnreadableReason.IO,
    }


def test_a_broken_chain_is_not_unreadable_it_comes_back_for_chain_verification(
    paths: AutonomyPaths, store: RegistryStore, stored_rows: tuple[TransitionRow, ...]
) -> None:
    forged = dataclasses.replace(
        stored_rows[-1],
        seq=None,
        venue_seq=3,
        transition_id="9" * 64,
        transition_hash="f" * 64,
    )
    conn = store._open()
    try:
        conn.execute(rs._INSERT_ROW, rs._to_db(forged))
    finally:
        conn.close()
    rows = reader(paths).read_venue_rows(VENUE)  # no RegistryUnreadable
    assert len(rows) == 3
    with pytest.raises(chain.ChainBroken):
        chain.verify_venue_chain(rows, VENUE)


def test_reader_validates_its_arguments(paths: AutonomyPaths, store: RegistryStore) -> None:
    with pytest.raises(TypeError):
        RegistryReader(paths.root, busy_timeout_ms=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RegistryReader(paths, busy_timeout_ms=True)
    with pytest.raises(TypeError):
        RegistryReader(paths, busy_timeout_ms=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RegistryReader(paths, busy_timeout_ms=-1)
    with pytest.raises(WireRefused):
        reader(paths).read_venue_rows("Bad Venue")
    with pytest.raises(WireRefused):
        reader(paths).read_venue_rows(VENUE, after_seq=-1)
    with pytest.raises(WireRefused):
        reader(paths).read_venue_rows(VENUE, after_seq=True)


def test_reader_reads_a_shadow_root(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    root.mkdir(mode=0o700)
    shadow = ShadowPaths(root)
    RegistryStore.initialise(shadow, repo_root=tmp_path / "repo")
    assert RegistryReader(shadow, busy_timeout_ms=0).read_venue_rows(VENUE) == ()


# --- write_export ---------------------------------------------------------------------------------


def test_write_export_publishes_write_once_read_only_and_round_trips(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    trailer = trailer_for(stored_rows, 1)
    outcome = write_export(paths, day=DAY, trailer=trailer, rows=stored_rows)
    target = paths.export_file(VENUE, DAY)
    assert outcome is WriteOutcome.WRITTEN
    assert stat.S_IMODE(target.stat().st_mode) == 0o444
    assert [p.name for p in export_dir.iterdir()] == [target.name]  # no temp name left behind
    assert write_export(paths, day=DAY, trailer=trailer, rows=stored_rows) is (
        WriteOutcome.EXISTS_EQUAL
    )
    assert newest_export(paths, VENUE) == ExportRead(trailer, stored_rows)


def test_write_export_never_overwrites_different_bytes(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    target = put_export(paths, stored_rows, 1)
    original = target.read_bytes()
    with pytest.raises(SingleReadRefused) as caught:
        write_export(paths, day=DAY, trailer=trailer_for(stored_rows[:1], 2), rows=stored_rows[:1])
    assert caught.value.reason is SingleReadReason.EXISTS_DIFFERENT
    assert target.read_bytes() == original


def test_write_export_refuses_a_missing_directory(
    paths: AutonomyPaths, stored_rows: tuple[TransitionRow, ...]
) -> None:
    with pytest.raises(SingleReadRefused) as caught:
        write_export(paths, day=DAY, trailer=trailer_for(stored_rows, 1), rows=stored_rows)
    assert caught.value.reason is SingleReadReason.NOT_FOUND


def test_write_export_carries_the_reset_variant_name(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    target = put_export(paths, stored_rows, 7, hwm=True)
    assert target.name == f"registry_{VENUE}_{DAY}_hwm7.jsonl"
    assert target.exists()


def test_write_export_refuses_an_export_with_no_rows(
    paths: AutonomyPaths, export_dir: Path
) -> None:
    trailer = ExportTrailer(venue=VENUE, venue_seq=2, chain_head="a" * 64, export_seq=3)
    with pytest.raises(ExportRefused):
        write_export(paths, day=DAY, trailer=trailer, rows=())
    assert list(export_dir.iterdir()) == []


def _swap_venue(row: TransitionRow) -> TransitionRow:
    return dataclasses.replace(row, venue=OTHER_VENUE)


_BAD_EXPORTS: Final[dict[str, Any]] = {
    "foreign_venue_row": lambda rows: (rows[:1] + (_swap_venue(rows[1]),), 1, None),
    "unsealed_row": lambda rows: (
        (dataclasses.replace(rows[0], transition_hash=None), rows[1]),
        1,
        None,
    ),
    "venue_seq_gap": lambda rows: (
        (rows[1],) + (dataclasses.replace(rows[1], venue_seq=4),),
        1,
        None,
    ),
    "trailer_is_not_last_row": lambda rows: (rows[:1], 1, None),
    "hwm_name_disagrees_with_trailer": lambda rows: (rows, 1, 2),
}


@pytest.mark.parametrize("case", sorted(_BAD_EXPORTS))
def test_write_export_refuses_inconsistent_input(
    case: str, paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    rows, export_seq, hwm = _BAD_EXPORTS[case](stored_rows)
    trailer = trailer_for(stored_rows, export_seq)
    if case == "foreign_venue_row":
        trailer = trailer_for(stored_rows[:1], export_seq)
    with pytest.raises(ExportRefused):
        write_export(paths, day=DAY, trailer=trailer, rows=rows, hwm_export_seq=hwm)
    assert list(export_dir.iterdir()) == []


def test_write_export_validates_paths_and_day(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    trailer = trailer_for(stored_rows, 1)
    with pytest.raises(TypeError):
        write_export(paths.root, day=DAY, trailer=trailer, rows=stored_rows)  # type: ignore[arg-type]
    with pytest.raises(WireRefused):
        write_export(paths, day="20261201", trailer=trailer, rows=stored_rows)


def test_write_export_refuses_an_oversize_export(
    paths: AutonomyPaths,
    export_dir: Path,
    stored_rows: tuple[TransitionRow, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rx, "MAX_EXPORT_BYTES", 100)
    with pytest.raises(ExportRefused):
        write_export(paths, day=DAY, trailer=trailer_for(stored_rows, 1), rows=stored_rows)


# --- newest_export --------------------------------------------------------------------------------


def test_export_seq_monotone_and_newest_wins(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    # File order by date is the reverse of export_seq order: the date never decides.
    put_export(paths, stored_rows[:1], 1, day="2026-12-03")
    put_export(paths, stored_rows, 2, day="2026-12-01")
    put_export(paths, stored_rows[:1], 3, day="2026-12-02", hwm=True)
    newest = newest_export(paths, VENUE)
    assert isinstance(newest, ExportRead)
    assert newest.trailer.export_seq == 3
    assert newest.rows == stored_rows[:1]


def test_equal_export_seq_in_two_files_is_ambiguous(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    put_export(paths, stored_rows, 2, day="2026-12-01")
    put_export(paths, stored_rows, 2, day="2026-12-02")
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportUnreadable)
    assert result.reason is RefusalReason.EXPORT_UNREADABLE


def test_one_bad_candidate_is_never_skipped_for_an_older_good_one(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    put_export(paths, stored_rows, 1, day="2026-12-01")
    plant(export_dir / f"registry_{VENUE}_2026-12-02.jsonl", b"{not json\n")
    assert isinstance(newest_export(paths, VENUE), ExportUnreadable)


def _seed_good(paths: AutonomyPaths, rows: tuple[TransitionRow, ...]) -> ExportRead:
    put_export(paths, rows, 1)
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportRead)
    return result


#: ``(name, outcome)``: a candidate is a real export under that name, which wins by export_seq.
_NAME_CASES: Final[dict[str, tuple[str, str]]] = {
    "daily_export": (f"registry_{VENUE}_2026-12-02.jsonl", "candidate"),
    "hwm_export": (f"registry_{VENUE}_2026-12-02_hwm5.jsonl", "candidate"),
    "hwm_reset_record_ignored": ("hwm_reset_20261202T000000Z.json", "ignored"),
    "other_venue_export_ignored": (f"registry_{OTHER_VENUE}_2026-12-02.jsonl", "ignored"),
    "unknown_name_unreadable": ("notes.txt", "unreadable"),
    "tmp_16hex_ignored": (".tmp.0123456789abcdef", "ignored"),
    "tmp_non_hex_unreadable": (".tmp.0123456789abcdeg", "unreadable"),
}


@pytest.mark.parametrize("case", list(_NAME_CASES))
def test_newest_export_name_filter(
    case: str, paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    name, outcome = _NAME_CASES[case]
    good = _seed_good(paths, stored_rows)
    if outcome == "candidate":
        hwm = 5 if "_hwm" in name else None
        write_export(
            paths,
            day="2026-12-02",
            trailer=trailer_for(stored_rows, 5),
            rows=stored_rows,
            hwm_export_seq=hwm,
        )
        assert (export_dir / name).exists()
        result = newest_export(paths, VENUE)
        assert isinstance(result, ExportRead)
        assert result.trailer.export_seq == 5
        return
    (export_dir / name).write_bytes(b"junk that must never be parsed\n")
    result = newest_export(paths, VENUE)
    if outcome == "unreadable":
        assert isinstance(result, ExportUnreadable)
        assert name in result.detail
    else:
        assert result == good  # a known foreign name is neither read nor an error


def test_newest_export_ignores_write_once_temp_name(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    good = _seed_good(paths, stored_rows)
    (export_dir / ".tmp.deadbeefdeadbeef").write_bytes(b"x")
    assert newest_export(paths, VENUE) == good
    (export_dir / ".tmp.x").write_bytes(b"x")  # control: an unmatched .tmp. name still refuses
    assert isinstance(newest_export(paths, VENUE), ExportUnreadable)


@pytest.mark.parametrize(
    "name",
    [
        ".tmp.DEADBEEFDEADBEEF",
        ".tmp.deadbeefdeadbeef0",
        ".tmp.deadbeefdeadbee",
        ".tmp.deadbeefdeadbeef\n",
        "hwm_reset_.json.bak",
        "hwm_reset_x.json\n",
        f"registry_{VENUE}_2026-12-02.jsonl.bak",
        f"registry_{VENUE}_2026-12-02.jsonl\n",
        f"registry_{VENUE}_2026-12-2.jsonl",
        f"registry_{VENUE}_2026-12-02_hwm.jsonl",
        f"registry_{VENUE}_2026-12-02_hwmx.jsonl",
        f"registry_{VENUE}_２０２６-12-02.jsonl",  # full-width digits (re.ASCII)
        f"REGISTRY_{VENUE}_2026-12-02.jsonl",
        "registry__2026-12-02.jsonl",
        f"registry_{'v' * 33}_2026-12-02.jsonl",
        "registry_Kalshi_2026-12-02.jsonl",
    ],
)
def test_near_miss_names_fail_closed(
    name: str, paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    _seed_good(paths, stored_rows)
    (export_dir / name).write_bytes(b"x")
    assert isinstance(newest_export(paths, VENUE), ExportUnreadable)


def test_a_longer_venue_sharing_this_venues_prefix_is_another_venue(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    good = _seed_good(paths, stored_rows)
    (export_dir / "registry_polymarket_us_extra_2026-12-02.jsonl").write_bytes(b"x")
    assert newest_export(paths, "polymarket") == ExportAbsent()  # its own, never VENUE's
    assert newest_export(paths, VENUE) == good


def test_no_candidate_is_absent_not_unreadable(paths: AutonomyPaths, export_dir: Path) -> None:
    assert newest_export(paths, VENUE) == ExportAbsent()
    (export_dir / "hwm_reset_1.json").write_bytes(b"{}")
    (export_dir / f"registry_{OTHER_VENUE}_2026-12-01.jsonl").write_bytes(b"x")
    assert newest_export(paths, VENUE) == ExportAbsent()


def test_a_missing_or_unreadable_directory_is_unreadable(
    paths: AutonomyPaths, export_dir: Path, tmp_path: Path
) -> None:
    export_dir.rmdir()
    assert isinstance(newest_export(paths, VENUE), ExportUnreadable)
    export_dir.symlink_to(tmp_path)
    assert isinstance(newest_export(paths, VENUE), ExportUnreadable)
    missing_root = AutonomyPaths(tmp_path / "no-such-root")
    assert isinstance(newest_export(missing_root, VENUE), ExportUnreadable)


def test_a_listing_error_is_unreadable(
    paths: AutonomyPaths, export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.listdir

    def fail(target: Any) -> list[str]:
        if isinstance(target, int):  # newest_export lists by directory fd
            raise OSError("listing failed")
        return real(target)

    monkeypatch.setattr(os, "listdir", fail)
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportUnreadable)
    assert "listing" in result.detail


def _write_raw(directory: Path, data: bytes, *, mode: int = 0o444) -> Path:
    return plant(directory / f"registry_{VENUE}_{DAY}.jsonl", data, mode=mode)


def _good_bytes(paths: AutonomyPaths, rows: tuple[TransitionRow, ...]) -> bytes:
    return put_export(paths, rows, 1).read_bytes()


def _unlink(path: Path) -> None:
    path.chmod(0o644)
    path.unlink()


_TAMPERS: Final[dict[str, Any]] = {
    "empty_file": lambda good: b"",
    "no_trailing_newline": lambda good: good.rstrip(b"\n"),
    "truncated_trailer": lambda good: good[:-20] + b"\n",
    "garbage": lambda good: b"\x00\xff not json\n",
    "blank_line": lambda good: good + b"\n",
    "pretty_printed_not_canonical": lambda good: good.replace(b'":', b'": ', 1),
    "rows_out_of_order": lambda good: b"\n".join(reversed(good.rstrip(b"\n").split(b"\n"))) + b"\n",
    "every_venue_field_replaced": lambda good: good.replace(VENUE.encode(), OTHER_VENUE.encode()),
    "trailer_with_an_extra_key": lambda good: good.replace(
        b'"export_seq":1', b'"export_seq":1,"x":1'
    ),
}


@pytest.mark.parametrize("case", sorted(_TAMPERS))
def test_a_tampered_candidate_is_unreadable(
    case: str, paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    good = _good_bytes(paths, stored_rows)
    _unlink(paths.export_file(VENUE, DAY))
    _write_raw(export_dir, _TAMPERS[case](good))
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportUnreadable), case


def test_the_untampered_bytes_read_back(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    good = _good_bytes(paths, stored_rows)
    _unlink(paths.export_file(VENUE, DAY))
    _write_raw(export_dir, good)
    assert isinstance(newest_export(paths, VENUE), ExportRead)


def test_a_trailer_that_is_not_the_last_row_is_unreadable(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    trailer = dataclasses.replace(trailer_for(stored_rows, 1), chain_head="e" * 64)
    # Render around the writer's own guard to plant the inconsistency on disk.
    _write_raw(export_dir, rx._render(trailer, stored_rows))
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportUnreadable)
    assert "trailer" in result.detail


def test_a_hwm_name_whose_trailer_disagrees_is_unreadable(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    data = rx._render(trailer_for(stored_rows, 3), stored_rows)
    plant(export_dir / f"registry_{VENUE}_{DAY}_hwm4.jsonl", data)
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportUnreadable)
    assert "export_seq" in result.detail


def test_a_trailer_naming_another_venue_is_unreadable(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    other = tuple(_swap_venue(row) for row in stored_rows)
    data = rx._render(trailer_for(other, 1, venue=OTHER_VENUE), other)
    _write_raw(export_dir, data)  # under this venue's name
    assert isinstance(newest_export(paths, VENUE), ExportUnreadable)


@pytest.mark.parametrize("kind", ["directory", "symlink", "group_writable", "oversize"])
def test_a_candidate_that_is_not_a_plain_strict_file_is_unreadable(
    kind: str,
    paths: AutonomyPaths,
    export_dir: Path,
    stored_rows: tuple[TransitionRow, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = rx._render(trailer_for(stored_rows, 1), stored_rows)
    target = export_dir / f"registry_{VENUE}_{DAY}.jsonl"
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        real = tmp_path / "real.jsonl"
        real.write_bytes(good)
        target.symlink_to(real)
    elif kind == "group_writable":
        _write_raw(export_dir, good, mode=0o664)
    else:
        _write_raw(export_dir, good)
        monkeypatch.setattr(rx, "MAX_EXPORT_BYTES", 10)
    assert isinstance(newest_export(paths, VENUE), ExportUnreadable)


def test_newest_export_validates_the_venue(paths: AutonomyPaths, export_dir: Path) -> None:
    with pytest.raises(WireRefused):
        newest_export(paths, "Bad Venue")


# --- the export, the chain, the journal and the HWM --------------------------------------------


def test_the_exported_trailer_verifies_against_the_chain_and_a_forged_head_does_not(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    put_export(paths, stored_rows[:1], 1)  # an export of the first row only: a strict prefix
    newest = newest_export(paths, VENUE)
    assert isinstance(newest, ExportRead)
    verified = chain.verify_venue_chain(stored_rows, VENUE)
    assert chain.verify_against_export(verified, newest.trailer) is None
    forged = dataclasses.replace(newest.trailer, chain_head="d" * 64)
    assert chain.verify_against_export(verified, forged) is RefusalReason.EXPORT_PREFIX_MISMATCH


def test_the_trailer_carries_journal_heads_that_match_the_journal(
    paths: AutonomyPaths,
    export_dir: Path,
    stored_rows: tuple[TransitionRow, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rollback_journal, "JOURNAL_KINDS", frozenset({"rollback"}))
    head = rollback_journal.append_journal(paths, "rollback", VENUE, {"event": "x"}, ts_ns=NOW)
    trailer = dataclasses.replace(
        trailer_for(stored_rows, 1), evidence_journal_heads=(("rollback", head),)
    )
    write_export(paths, day=DAY, trailer=trailer, rows=stored_rows)
    newest = newest_export(paths, VENUE)
    assert isinstance(newest, ExportRead)
    ((kind, exported),) = newest.trailer.evidence_journal_heads
    journal = rollback_journal.read_journal_chain(paths, kind, VENUE)
    assert rollback_journal.head_matches(journal, exported)
    moved = rollback_journal.JournalHead(seq=exported.seq, sha256="0" * 64)
    assert not rollback_journal.head_matches(journal, moved)


def test_newest_export_seq_feeds_hwm_check(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    verified = chain.verify_venue_chain(stored_rows, VENUE)

    def refusal(export_seq: int, newest_seq: int) -> RefusalReason | None:
        hwm = next_hwm(verified, export_seq=export_seq)
        return hwm_check(verified, HwmPresent(hwm=hwm), newest_export_seq=newest_seq)

    assert newest_export(paths, VENUE) == ExportAbsent()  # no export: newest_export_seq is 0
    assert refusal(0, 0) is None
    assert refusal(1, 0) is RefusalReason.HWM_REGRESSED
    put_export(paths, stored_rows, 4)
    newest = newest_export(paths, VENUE)
    assert isinstance(newest, ExportRead)
    assert refusal(4, newest.trailer.export_seq) is None
    assert refusal(5, newest.trailer.export_seq) is RefusalReason.HWM_REGRESSED


# --- A6f-R1: a repeat of any export_seq refuses --------------------------------------------------


def test_a_lower_duplicate_export_seq_after_the_maximum_is_ambiguous(
    paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    # Name order is 12-01, 12-02, 12-03: seq 3, then the maximum 5, then a repeat of 3.
    put_export(paths, stored_rows, 3, day="2026-12-01")
    put_export(paths, stored_rows, 5, day="2026-12-02")
    put_export(paths, stored_rows, 3, day="2026-12-03")
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportUnreadable)
    assert "share export_seq 3" in result.detail


# --- A6f-R2: every export is the venue's full history from venue_seq 1 -------------------------


def _suffix_only(rows: tuple[TransitionRow, ...]) -> tuple[TransitionRow, ...]:
    return rows[1:]


def _first_row_is_five(rows: tuple[TransitionRow, ...]) -> tuple[TransitionRow, ...]:
    return (dataclasses.replace(rows[0], venue_seq=5),)


def _broken_prev_hash(rows: tuple[TransitionRow, ...]) -> tuple[TransitionRow, ...]:
    return (rows[0], dataclasses.replace(rows[1], prev_transition_hash="e" * 64))


def _first_prev_is_not_genesis(rows: tuple[TransitionRow, ...]) -> tuple[TransitionRow, ...]:
    return (dataclasses.replace(rows[0], prev_transition_hash="e" * 64), rows[1])


_HISTORY_BREAKS: Final[dict[str, Any]] = {
    "suffix_only": _suffix_only,
    "first_row_other_than_1": _first_row_is_five,
    "broken_prev_hash": _broken_prev_hash,
    "first_prev_is_not_genesis": _first_prev_is_not_genesis,
}


@pytest.mark.parametrize("case", sorted(_HISTORY_BREAKS))
def test_write_export_refuses_anything_but_the_full_linked_history(
    case: str, paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    rows = _HISTORY_BREAKS[case](stored_rows)
    with pytest.raises(ExportRefused):
        write_export(paths, day=DAY, trailer=trailer_for(rows, 1), rows=rows)
    assert list(export_dir.iterdir()) == []


@pytest.mark.parametrize("case", sorted(_HISTORY_BREAKS))
def test_newest_export_refuses_anything_but_the_full_linked_history(
    case: str, paths: AutonomyPaths, export_dir: Path, stored_rows: tuple[TransitionRow, ...]
) -> None:
    rows = _HISTORY_BREAKS[case](stored_rows)
    plant(export_dir / f"registry_{VENUE}_{DAY}.jsonl", rx._render(trailer_for(rows, 1), rows))
    result = newest_export(paths, VENUE)
    assert isinstance(result, ExportUnreadable), case


# --- A6f-R5 L1: a real hot journal --------------------------------------------------------------

_HOT_WRITER: Final = """
import sqlite3, sys, time
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
conn.execute("PRAGMA journal_mode = DELETE")
conn.execute("PRAGMA cache_size = 1")
conn.execute("BEGIN IMMEDIATE")
columns = (
    "venue, venue_seq, transition_id, family_id, family_prior_seq, to_state, kind,"
    " cause_verdict_ids, drill, policy_ruling_id, policy_ruling_sha256, decided_by,"
    " invocation_id, engine_code_sha, expected_prior_seq, ts_ns, prev_transition_hash,"
    " transition_hash"
)
for n in range(1, 9):
    conn.execute(
        f"INSERT INTO transitions ({columns}) VALUES ('zz', ?, ?, 'f', 0, 'CHAMPION', 'BOOTSTRAP',"
        " ?, 0, 'r', 's', 'engine', 'i', 'e', 0, 1, 'p', 'h')",
        (n, f"{n:064x}", "ab" * 400_000),
    )
print("READY", flush=True)
time.sleep(120)
"""


def test_a_writer_killed_mid_commit_leaves_a_hot_journal_the_reader_names(
    paths: AutonomyPaths, store: RegistryStore, stored_rows: tuple[TransitionRow, ...]
) -> None:
    import signal
    import subprocess
    import sys

    child = subprocess.Popen(
        [sys.executable, "-c", _HOT_WRITER, str(store._db)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "READY"
        child.send_signal(signal.SIGKILL)  # after BEGIN and the INSERTs, before COMMIT
    finally:
        child.kill()
        child.wait(timeout=30)
    journal = store._db.with_name(store._db.name + "-journal")
    assert journal.exists() and journal.stat().st_size > 0
    before = (store._db.read_bytes(), journal.read_bytes())
    assert reason_of(lambda: reader(paths).read_venue_rows(VENUE)) is UnreadableReason.HOT_JOURNAL
    assert (store._db.read_bytes(), journal.read_bytes()) == before  # the reader repaired nothing
    # The engine's next read-write open rolls the journal back; the reader then sees the old rows.
    conn = store._open()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    assert not journal.exists()
    assert reader(paths).read_venue_rows(VENUE) == stored_rows


# --- A6f-R5 L5: the documented residual -----------------------------------------------------


def test_connect_documents_the_same_uid_parent_symlink_residual() -> None:
    doc = RegistryReader._connect.__doc__ or ""
    assert "symlink" in doc and "l.408" in doc


# --- module hygiene -------------------------------------------------------------------------------


def test_venue_class_matches_the_paths_venue_pattern() -> None:
    assert f"\\A{rx._VENUE_CLASS}\\Z" == VENUE_RE.pattern


def test_the_only_write_site_is_the_readers_connect_and_write_export_has_none() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    sites = find_write_sites("registry_export.py", source)
    assert {(site.scope, site.detail) for site in sites} == {
        ("RegistryReader._connect", "sqlite3.connect")
    }


def test_the_writer_table_row_is_narrow_to_the_readers_connect() -> None:
    module = "breezy.persistence.autonomy.registry_export"
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert unallowed_write_sites("registry_export.py", source, module=module) == []
    planted = "import os\ndef write_export(a):\n    os.unlink(a)\n"
    assert unallowed_write_sites("p.py", planted, module=module)  # control: no module-wide row
    other = "import sqlite3\ndef other(p):\n    sqlite3.connect(p)\n"
    assert unallowed_write_sites("p.py", other, module=module)


def test_the_module_is_within_the_size_cap_and_never_opens_the_database_read_write() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 800
    assert "mode=ro" in source
    assert not re.search(r"mode=r(w|wc)\b", source)
    tree = ast.parse(source)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "_INSERT_ROW"]


def test_the_module_never_derives_a_location_from_file_or_cwd() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "__file__" not in names
    assert not ({"cwd", "getcwd", "home", "environ"} & attrs)


def test_the_directory_is_never_created_by_the_reader_or_newest_export(
    paths: AutonomyPaths, store: RegistryStore
) -> None:
    newest_export(paths, VENUE)
    reader(paths).read_venue_rows(VENUE)
    assert not os.path.lexists(paths.export_dir())
