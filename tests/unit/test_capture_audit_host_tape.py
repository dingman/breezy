"""AUT-1 WP5 stage 2b W3: the journals, the bus snapshot and the recorder catalog as a TapeIndex.

``journalctl`` is a fake at ``subprocess.Popen`` whose stdout is a real pipe (argv is asserted).
The bus snapshot is a document in seam B's real shape read by the real
``read_bus_snapshot``. The tape is tiny REAL Parquet in the recorder's layout.
"""

import ast
import datetime as dt
import fcntl
import inspect
import json
import os
import struct
import subprocess
import termios
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit_host as host
from breezy.analysis import capture_audit_tape as tape_mod
from breezy.analysis.capture_audit_input_types import TapeIndex
from breezy.analysis.capture_audit_model import AuditInputError
from breezy.analysis.capture_audit_tape import RecorderCatalogTape, catalog_instruments
from tests.support import capture_audit_w3_fixtures as w3

NS = w3.NS
DAY = w3.DAY
SINCE, UNTIL = "2026-10-03 00:00:00 UTC", "2026-10-04 00:00:00 UTC"
TEMPLATES = [host.INGEST_JOURNAL_ARGV, host.SUPERVISOR_JOURNAL_ARGV, host.RECORDER_JOURNAL_ARGV]


class FakeProc:
    """A launched ``journalctl``: stdout is a REAL pipe, so the bounded read is the production one.

    ``hang`` keeps the write end open (a child that never finishes). ``close`` is recorded, not
    performed, so a test can still ask the pipe how much was left unread."""

    def __init__(self, data: bytes = b"x\n", returncode: int = 0, *, hang: bool = False) -> None:
        read_fd, self._write_fd = os.pipe()
        os.write(self._write_fd, data)
        if not hang:
            os.close(self._write_fd)
        self.stdout = self
        self._read_fd, self._returncode, self._hang = read_fd, returncode, hang
        self.killed = self.closed = False

    def fileno(self) -> int:
        return self._read_fd

    def close(self) -> None:
        self.closed = True

    def unread(self) -> int:
        packed = fcntl.ioctl(self._read_fd, termios.FIONREAD, b"\0\0\0\0")
        return int(struct.unpack("i", packed)[0])

    def poll(self) -> int | None:
        return None if self._hang and not self.killed else self._returncode

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode

    def release(self) -> None:
        os.close(self._read_fd)
        if self._hang:
            os.close(self._write_fd)


@pytest.fixture
def procs() -> Iterator[list[FakeProc]]:
    made: list[FakeProc] = []
    yield made
    for proc in made:
        proc.release()


def _patch_run(
    monkeypatch: pytest.MonkeyPatch, result: Any, made: list[FakeProc]
) -> list[tuple[list[str], dict[str, Any]]]:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def popen(argv: list[str], **kw: Any) -> Any:
        calls.append((argv, kw))
        if isinstance(result, Exception):
            raise result
        proc = FakeProc(*result[:2], hang=len(result) > 2 and result[2])
        made.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def _ok(text: str = "x\n") -> tuple[bytes, int]:
    return text.encode(), 0


# -- the journals ------------------------------------------------------------------------------


@pytest.mark.parametrize("template", TEMPLATES, ids=["ingest", "supervisor", "recorder"])
def test_run_journal_runs_the_template_with_only_the_two_slots_substituted(
    monkeypatch: pytest.MonkeyPatch, template: tuple[str, ...], procs: list[FakeProc]
) -> None:
    calls = _patch_run(monkeypatch, _ok("line\n"), procs)
    assert host.run_journal(template, SINCE, UNTIL) == "line\n"
    ((argv, kw),) = calls
    assert argv == [SINCE if t == "{since}" else UNTIL if t == "{until}" else t for t in template]
    assert kw == {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL}
    assert inspect.signature(host.run_journal).parameters["timeout_s"].default == 30.0
    assert procs[0].closed


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "yesterday",
        "2026-10-03",
        "2026-10-03 00:00:00",
        "2026-10-03 00:00:00 UTC; rm -rf /",
        "$(id)",
        "-1d",
        "2026-10-03 00:00:00 UTC\n--vacuum-time=1s",
        # S2-R32: non-ASCII decimal digits are not time-slot digits.
        "\u0662\u0660\u0662\u0666-10-03 00:00:00 UTC",
        "2026-10-03 \uff10\uff10:00:00 UTC",
    ],
)
def test_a_time_slot_outside_the_grammar_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, bad: str, procs: list[FakeProc]
) -> None:
    calls = _patch_run(monkeypatch, _ok(), procs)
    for since, until in ((bad, UNTIL), (SINCE, bad)):
        with pytest.raises(AuditInputError) as info:
            host.run_journal(host.INGEST_JOURNAL_ARGV, since, until)
        assert (info.value.cause, info.value.detail) == ("journal_failed", "bad_time_slot")
    assert calls == []


def test_an_unknown_template_is_refused(
    monkeypatch: pytest.MonkeyPatch, procs: list[FakeProc]
) -> None:
    calls = _patch_run(monkeypatch, _ok(), procs)
    with pytest.raises(AuditInputError) as info:
        host.run_journal(("journalctl", "--rotate"), SINCE, UNTIL)
    assert info.value.detail == "unknown_template" and calls == []


def test_journalctl_nonzero_timeout_or_empty_is_error(
    monkeypatch: pytest.MonkeyPatch, procs: list[FakeProc]
) -> None:
    cases: dict[str, Any] = {
        "exit_1": (b"out", 1),
        "timeout": (b"partial", 0, True),
        "FileNotFoundError": FileNotFoundError("journalctl"),
        host.EMPTY_OUTPUT_DETAIL: (b"  \n", 0),
    }
    for detail, result in cases.items():
        _patch_run(monkeypatch, result, procs)
        with pytest.raises(AuditInputError) as info:
            host.run_journal(host.INGEST_JOURNAL_ARGV, SINCE, UNTIL, timeout_s=0.05)
        assert (info.value.cause, info.value.detail) == ("journal_failed", detail)


def test_a_child_that_never_finishes_is_killed_on_timeout(
    monkeypatch: pytest.MonkeyPatch, procs: list[FakeProc]
) -> None:
    _patch_run(monkeypatch, (b"partial", 0, True), procs)
    with pytest.raises(AuditInputError) as info:
        host.run_journal(host.INGEST_JOURNAL_ARGV, SINCE, UNTIL, timeout_s=0.05)
    assert info.value.detail == "timeout" and procs[0].killed and procs[0].closed


def test_an_oversize_journal_stops_the_read_without_buffering_it_all(
    monkeypatch: pytest.MonkeyPatch, procs: list[FakeProc]
) -> None:
    """S2-R31: the cap is enforced WHILE reading. With a 10-byte cap and 8-byte chunks the read
    stops at the second chunk; most of the 200 bytes the child wrote are never read."""
    monkeypatch.setattr(host, "_MAX_JOURNAL_BYTES", 10)
    monkeypatch.setattr(host, "_READ_CHUNK_BYTES", 8)
    _patch_run(monkeypatch, (b"a" * 200, 0, True), procs)
    with pytest.raises(AuditInputError) as info:
        host.run_journal(host.INGEST_JOURNAL_ARGV, SINCE, UNTIL)
    assert (info.value.cause, info.value.detail) == ("journal_failed", "oversize")
    assert procs[0].unread() == 200 - 16 and procs[0].killed


def test_the_journal_cap_counts_bytes_not_characters(
    monkeypatch: pytest.MonkeyPatch, procs: list[FakeProc]
) -> None:
    monkeypatch.setattr(host, "_MAX_JOURNAL_BYTES", 10)
    text = "\u00e9" * 6  # six characters, twelve bytes
    _patch_run(monkeypatch, _ok(text), procs)
    with pytest.raises(AuditInputError) as info:
        host.run_journal(host.INGEST_JOURNAL_ARGV, SINCE, UNTIL)
    assert info.value.detail == "oversize"
    _patch_run(monkeypatch, _ok("\u00e9" * 5), procs)  # exactly ten bytes: within the cap
    assert host.run_journal(host.INGEST_JOURNAL_ARGV, SINCE, UNTIL) == "\u00e9" * 5


def test_journal_slot_is_the_one_accepted_shape() -> None:
    assert host.journal_slot(0) == "1970-01-01 00:00:00 UTC"
    assert host._SLOT_RE.fullmatch(host.journal_slot(1791046250))


def test_the_recorder_journal_keeps_unit_result_entries_in_time_order() -> None:
    def entry(ts_us: int, **f: Any) -> str:
        return json.dumps({"__REALTIME_TIMESTAMP": str(ts_us), **f})

    text = "\n".join(
        [
            entry(3_000_000, UNIT_RESULT="watchdog", INVOCATION_ID="ab" * 16, MESSAGE="killed"),
            entry(1_000_000, MESSAGE="Started"),
            entry(2_000_000, UNIT_RESULT="success", _SYSTEMD_INVOCATION_ID="cd" * 16),
            "",
        ]
    )
    got = host.parse_recorder_journal(text)
    assert [(e.ts_ns, e.unit_result, e.invocation_id) for e in got] == [
        (2_000_000_000, "success", "cd" * 16),
        (3_000_000_000, "watchdog", "ab" * 16),
    ]
    assert got[1].message == "killed"


@pytest.mark.parametrize("text", ["{torn", "[1]", '{"UNIT_RESULT": "watchdog"}'])
def test_a_malformed_recorder_journal_is_journal_failed(text: str) -> None:
    with pytest.raises(AuditInputError) as info:
        host.parse_recorder_journal(text)
    assert info.value.cause == "journal_failed"


# -- S3-R1 / S3-R33: the invocation id of a UNIT_RESULT line --------------------------------------

_HEAL_FIXTURES = Path(__file__).parents[1] / "fixtures" / "capture_heal"


def _real_line(name: str) -> str:
    return (_HEAL_FIXTURES / name).read_text(encoding="utf-8")


def test_unit_result_user_invocation_id_is_read() -> None:
    text = json.dumps(
        {"__REALTIME_TIMESTAMP": "5", "UNIT_RESULT": "watchdog", "USER_INVOCATION_ID": "ef" * 16}
    )
    (got,) = host.parse_recorder_journal(text)
    assert got.invocation_id == "ef" * 16


def test_user_invocation_id_wins_over_the_fallbacks() -> None:
    text = json.dumps(
        {
            "__REALTIME_TIMESTAMP": "5",
            "UNIT_RESULT": "watchdog",
            "USER_INVOCATION_ID": "ef" * 16,
            "INVOCATION_ID": "ab" * 16,
            "_SYSTEMD_INVOCATION_ID": "cd" * 16,
        }
    )
    assert host.parse_recorder_journal(text)[0].invocation_id == "ef" * 16


def test_empty_invocation_id_is_journal_failed() -> None:
    text = json.dumps({"__REALTIME_TIMESTAMP": "5", "UNIT_RESULT": "watchdog", "MESSAGE": "x"})
    with pytest.raises(AuditInputError) as info:
        host.parse_recorder_journal(text)
    assert info.value.cause == "journal_failed"
    blank = json.dumps({"__REALTIME_TIMESTAMP": "5", "UNIT_RESULT": "x", "USER_INVOCATION_ID": ""})
    with pytest.raises(AuditInputError):
        host.parse_recorder_journal(blank)


def test_real_timeout_kill_line_parses() -> None:
    """The recorder's real 2026-09-05 ``UNIT_RESULT=timeout`` line, copied verbatim."""
    (got,) = host.parse_recorder_journal(_real_line("unit_result_real_timeout.json"))
    assert got.unit_result == "timeout"
    assert got.invocation_id == "20f02ed53de4413e811bc884c422a395"
    assert got.ts_ns == 1788582858022946 * 1000


def test_real_watchdog_kill_line_parses() -> None:
    """A real ``UNIT_RESULT=watchdog`` line from another unit (the recorder has none yet, F7)."""
    (got,) = host.parse_recorder_journal(_real_line("unit_result_real_watchdog.json"))
    raw = json.loads(_real_line("unit_result_real_watchdog.json"))
    assert raw["USER_UNIT"] != "breezy-quote-tape.service"  # another unit's line
    assert got.unit_result == "watchdog"
    assert got.invocation_id == raw["USER_INVOCATION_ID"] != ""
    assert got.ts_ns == int(raw["__REALTIME_TIMESTAMP"]) * 1000


def test_journal_argv0_is_absolute() -> None:
    """S3-R15: a bare ``journalctl`` is resolved through ``PATH``; the templates and the launched
    argvs name the binary by its absolute path."""
    for template in TEMPLATES:
        assert template[0] == "/usr/bin/journalctl"
    source = Path(host.__file__).read_text(encoding="utf-8")
    assert '"journalctl"' not in source
    assert source.count('"/usr/bin/journalctl"') == 6


# -- the bus snapshot (S2-R8) ------------------------------------------------------------------


def _bus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **plant: Any) -> Path:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root, snapshot=False)
    w3.plant_snapshot(root, **plant)
    return root


def test_audit_bus_reads_has_exactly_two_reads() -> None:
    assert host.AUDIT_BUS_READS == (
        ("-p", "WatchdogUSec,NotifyAccess,Type", "--", "breezy-quote-tape.service"),
        ("-p", "ExecMainExitTimestamp", "--", "breezy-quote-tape-ingest.service"),
    )
    assert len(host.AUDIT_BUS_READ_NAMES) == 2 and host.AUDIT_BUS_READ_NAMES[1] == "ingest_show"


def test_the_recorder_props_and_the_ingest_exit_come_from_one_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bus(tmp_path, monkeypatch)
    props = host.read_recorder_props(root, now_ns=w3.NOW_NS)
    assert (props.watchdog_usec, props.notify_access, props.type) == (600_000_000, "all", "notify")
    exit_ns = host.read_ingest_exit_ns(root, now_ns=w3.NOW_NS)  # the file was consumed: cached
    assert exit_ns == int(dt.datetime(2026, 10, 4, 9, 7, 22, tzinfo=dt.UTC).timestamp()) * NS
    assert not list((root / w3.SNAP_BIND / ".bus_snapshot").iterdir())


def test_a_second_read_returns_the_first_outcome_not_a_second_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bus(tmp_path, monkeypatch)
    consumed: list[int] = []
    real = host._consume_snapshot
    monkeypatch.setattr(host, "_consume_snapshot", w3.wrapping(consumed, real))
    for _ in range(3):
        host.read_recorder_props(root, now_ns=w3.NOW_NS)
    assert consumed == [1]


def test_a_missing_snapshot_is_bus_snapshot_missing_and_stays_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root, snapshot=False)
    for _ in range(2):
        with pytest.raises(AuditInputError) as info:
            host.read_recorder_props(root, now_ns=w3.NOW_NS)
        assert info.value.cause == "bus_snapshot_missing"
    w3.plant_snapshot(root)  # too late: the outcome of the first read stands for the run
    with pytest.raises(AuditInputError):
        host.read_ingest_exit_ns(root, now_ns=w3.NOW_NS)


@pytest.mark.parametrize("age_s", [-6, 71, 3600])
def test_an_aged_or_future_snapshot_is_bus_snapshot_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, age_s: int
) -> None:
    """The window is ``[now - (budget + 60 s), now + 5 s]`` of seam B's own rule."""
    root = _bus(tmp_path, monkeypatch, ts_ns=w3.NOW_NS - age_s * NS)
    with pytest.raises(AuditInputError) as info:
        host.read_recorder_props(root, now_ns=w3.NOW_NS)
    assert info.value.cause == "bus_snapshot_stale"


def test_a_snapshot_just_inside_the_window_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bus(tmp_path, monkeypatch, ts_ns=w3.NOW_NS - 69 * NS)
    assert host.read_recorder_props(root, now_ns=w3.NOW_NS).type == "notify"


def test_a_failed_read_inside_the_snapshot_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bus(tmp_path, monkeypatch, rc=1)
    with pytest.raises(AuditInputError) as info:
        host.read_recorder_props(root, now_ns=w3.NOW_NS)
    assert info.value.cause == "bus_snapshot_missing"


def test_without_an_audit_row_in_the_table_there_is_no_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    monkeypatch.setattr(host, "_BUS_OUTCOMES", {})
    with pytest.raises(AuditInputError) as info:
        host.read_recorder_props(root, now_ns=w3.NOW_NS)
    assert (info.value.cause, info.value.detail) == ("bus_snapshot_missing", "no_audit_row")


@pytest.mark.parametrize(
    ("text", "usec"),
    [
        ("0", 0),
        ("", 0),
        ("infinity", 0),
        ("10min", 600_000_000),
        ("1min 30s", 90_000_000),
        ("500ms", 500_000),
        ("1h", 3_600_000_000),
        ("2s", 2_000_000),
    ],
)
def test_watchdog_timespans_parse(text: str, usec: int) -> None:
    assert host._timespan_us(text) == usec


def test_an_unparseable_property_is_stale() -> None:
    with pytest.raises(AuditInputError) as info:
        host._timespan_us("soon")
    assert info.value.cause == "bus_snapshot_stale"
    with pytest.raises(AuditInputError) as info:
        host._timestamp_ns("Fri 2026-10-02 09:07:22 CEST")
    assert info.value.cause == "bus_snapshot_stale"


def test_a_snapshot_missing_a_property_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bus(tmp_path, monkeypatch, recorder="Type=notify\n")
    with pytest.raises(AuditInputError) as info:
        host.read_recorder_props(root, now_ns=w3.NOW_NS)
    assert info.value.cause == "bus_snapshot_stale"


def test_a_never_exited_ingest_unit_has_no_exit_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bus(tmp_path, monkeypatch, ingest="ExecMainExitTimestamp=\n")
    assert host.read_ingest_exit_ns(root, now_ns=w3.NOW_NS) is None


# -- the recorder catalog as a TapeIndex -------------------------------------------------------


def _tape(tmp_path: Path, **kw: Any) -> tuple[Path, RecorderCatalogTape]:
    root = w3.make_root(tmp_path)
    w3.write_tape(root, **kw)
    base = root / "catalog" / "quote_tape" / w3.VENUE
    return base, RecorderCatalogTape(base, DAY, catalog_instruments(base, DAY))


T0 = w3.day_ns(DAY, 17, 0)


def test_lookup_returns_the_wp2_r4_frame_body_shape_for_a_quote(tmp_path: Path) -> None:
    _, tape = _tape(tmp_path, quotes=[(T0, "0.01", "0.15"), (T0 + NS, "0.02", "0.16")])
    assert tape.lookup("quote", w3.INSTRUMENT, T0) == {"ask": "0.15", "bid": "0.01", "ts_event": T0}
    assert tape.lookup("quote", w3.INSTRUMENT, T0 + 5) is None
    assert tape.lookup("quote", "other.POLYMARKET_US", T0) is None


def test_lookup_returns_the_wp2_r4_frame_body_shape_for_depth10_dropping_empty_levels(
    tmp_path: Path,
) -> None:
    _, tape = _tape(tmp_path, depths=[(T0, [("0.15", "10.00"), ("0.20", "250.50")])])
    assert tape.lookup("depth10", w3.INSTRUMENT, T0) == {
        "ts_event": T0,
        "bids": [],
        "asks": [["0.15", "10.00"], ["0.20", "250.50"]],
    }
    assert set(tape.lookup("depth10", w3.INSTRUMENT, T0) or {}) == {"ts_event", "bids", "asks"}


def test_an_unknown_frame_kind_finds_nothing(tmp_path: Path) -> None:
    _, tape = _tape(tmp_path, quotes=[(T0, "0.01", "0.15")])
    assert tape.lookup("trade", w3.INSTRUMENT, T0) is None


def test_best_ask_is_the_lowest_populated_ask_of_the_latest_row_at_or_before(
    tmp_path: Path,
) -> None:
    _, tape = _tape(
        tmp_path,
        depths=[(T0, [("0.30", "1.00")]), (T0 + 10 * NS, [("0.25", "5.00"), ("0.40", "2.00")])],
    )
    assert tape.best_ask_at(w3.INSTRUMENT, T0 - 1) is None
    assert tape.best_ask_at(w3.INSTRUMENT, T0 + 5 * NS) == 0.30
    assert tape.best_ask_at(w3.INSTRUMENT, T0 + 99 * NS) == 0.25
    assert tape.best_ask_at("other", T0) is None


def test_rows_are_returned_for_a_half_open_window_in_the_frame_shape(tmp_path: Path) -> None:
    _, tape = _tape(tmp_path, quotes=[(T0 + i * NS, "0.01", "0.15") for i in range(5)])
    rows = list(tape.quote_rows(w3.INSTRUMENT, T0 + NS, T0 + 3 * NS))
    assert [r["ts_event"] for r in rows] == [T0 + NS, T0 + 2 * NS]
    assert list(tape.depth_rows(w3.INSTRUMENT, T0, T0 + 9 * NS)) == []
    assert list(tape.quote_rows("other", T0, T0 + NS)) == []


def test_the_tape_satisfies_the_tape_index_protocol(tmp_path: Path) -> None:
    _, tape = _tape(tmp_path, quotes=[(T0, "0.01", "0.15")])
    assert isinstance(tape, TapeIndex)


def test_instruments_and_activity_are_indexed_eagerly(tmp_path: Path) -> None:
    other = "tc-temp-mdwhigh-2026-10-04-gte60lt61f.POLYMARKET_US"
    root = w3.make_root(tmp_path)
    w3.write_tape(root, quotes=[(T0, "0.01", "0.15")])
    w3.write_tape(root, other, depths=[(T0 + 600 * NS, [("0.5", "1.00")])])
    base = root / "catalog" / "quote_tape" / w3.VENUE
    found = catalog_instruments(base, DAY)
    assert found == {w3.INSTRUMENT, other}
    tape = RecorderCatalogTape(base, DAY, found)
    assert tape.instruments == found
    assert tape.active_instruments(T0, T0 + NS) == {w3.INSTRUMENT}
    assert tape.active_instruments(T0, T0 + 3600 * NS) == found
    assert tape.active_instruments(T0 + 7200 * NS, T0 + 8000 * NS) == frozenset()


def test_an_instrument_outside_the_requested_set_is_not_loaded(tmp_path: Path) -> None:
    base, _ = _tape(tmp_path, quotes=[(T0, "0.01", "0.15")])
    tape = RecorderCatalogTape(base, DAY, frozenset())
    assert tape.instruments == frozenset() and tape.lookup("quote", w3.INSTRUMENT, T0) is None


def test_rows_outside_the_day_plus_the_flush_window_are_not_indexed(tmp_path: Path) -> None:
    far = w3.day_ns(DAY + dt.timedelta(days=2), 1)
    _, tape = _tape(tmp_path, quotes=[(T0, "0.01", "0.15"), (far, "0.01", "0.15")])
    assert tape.lookup("quote", w3.INSTRUMENT, far) is None
    assert tape.lookup("quote", w3.INSTRUMENT, T0) is not None


def test_no_catalog_files_for_the_day_is_an_empty_tape_not_an_error(tmp_path: Path) -> None:
    root = w3.make_root(tmp_path)
    base = root / "catalog" / "quote_tape" / w3.VENUE
    assert catalog_instruments(base, DAY) == frozenset()
    assert RecorderCatalogTape(base, DAY, frozenset()).instruments == frozenset()


def test_an_unreadable_parquet_file_is_tape_unreadable_at_construction(tmp_path: Path) -> None:
    root = w3.make_root(tmp_path)
    w3.write_tape(root, quotes=[(T0, "0.01", "0.15")])
    base = root / "catalog" / "quote_tape" / w3.VENUE
    next(base.rglob("*.parquet")).write_bytes(b"PAR1 not parquet")
    with pytest.raises(AuditInputError) as info:
        RecorderCatalogTape(base, DAY, catalog_instruments(base, DAY))
    assert info.value.cause == "tape_unreadable"


def test_a_file_that_breaks_after_the_index_is_tape_unreadable_on_read(tmp_path: Path) -> None:
    base, tape = _tape(tmp_path, quotes=[(T0, "0.01", "0.15")])
    next(base.rglob("*.parquet")).write_bytes(b"gone bad")
    with pytest.raises(AuditInputError) as info:
        list(tape.quote_rows(w3.INSTRUMENT, T0, T0 + NS))
    assert info.value.cause == "tape_unreadable"


def test_the_tape_never_materialises_a_whole_table() -> None:
    tree = ast.parse(Path(tape_mod.__file__).read_text())
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "to_table" not in attrs and "to_batches" in attrs
    source = Path(tape_mod.__file__).read_text()
    for flag in (
        "batch_size=_BATCH_ROWS",
        "batch_readahead=1",
        "fragment_readahead=1",
        "use_threads=False",
    ):
        assert flag in source
    assert tape_mod._BATCH_ROWS == 65_536
