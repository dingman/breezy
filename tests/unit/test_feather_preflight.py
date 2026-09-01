"""BL-23: the read-back preflight must be LOUD where Nautilus is silent.

The defect being closed is measured, not hypothetical. A feather tape whose
final Arrow message is incomplete makes
``ParquetDataCatalog._read_feather_file`` catch ``(pa.ArrowInvalid, OSError)``
and return ``None`` (``persistence/catalog/parquet.py:2795-2800``), which
``convert_stream_to_data`` turns into ``continue`` (``:2644-2646``). The
conversion completes, raises nothing, logs nothing, and delivers ZERO rows.

The interpretive danger is the whole point: a silently-truncated tape reads as
"0 rows", reads as "quiet market", reads as "no edge" -- a false NO-GO on a
strategy, produced by a file-handling bug. So the preflight's first duty is not
to recover data; it is to make "0 rows" impossible to confuse with "nothing
happened".

That forces the distinction these tests exist to pin: **empty and truncated are
different verdicts.** The discriminator is NOT the row count -- both are zero
-- it is where the byte stream stops relative to Arrow's message framing. A
file that ends exactly on a message boundary (or has no bytes at all) recorded
nothing. A file whose trailing bytes are a partial message lost data.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa
import pytest

from breezy.persistence.feather_preflight import (
    FeatherStatus,
    PreflightError,
    TruncatedTapeError,
    inspect_feather_file,
    list_instance_ids,
    salvage_feather_file,
    scan_instance,
)

INSTANCE_ID = "instance-1"

#: The Arrow IPC stream end-of-stream marker: a 0xFFFFFFFF continuation token
#: followed by a zero-length metadata block. ``StreamingFeatherWriter.close()``
#: is what appends it, so a killed writer never has one.
END_OF_STREAM = b"\xff\xff\xff\xff\x00\x00\x00\x00"

_SCHEMA = pa.schema([pa.field("value", pa.int64()), pa.field("ts_init", pa.int64())])


def _write_stream(path: Path, *, batches: int, rows_per_batch: int = 10, close: bool) -> None:
    """Write a real Arrow IPC stream, optionally without its end-of-stream marker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sink = pa.OSFile(str(path), "wb")
    writer = pa.ipc.new_stream(sink, _SCHEMA)
    for index in range(batches):
        writer.write_batch(
            pa.record_batch(
                [
                    pa.array([index] * rows_per_batch),
                    pa.array(list(range(rows_per_batch))),
                ],
                schema=_SCHEMA,
            )
        )
    if close:
        writer.close()
    sink.close()


def _truncate(path: Path, *, drop_bytes: int) -> None:
    with path.open("r+b") as handle:
        handle.truncate(path.stat().st_size - drop_bytes)


def _tape(tmp_path: Path, name: str = "quote_tick_1.feather") -> Path:
    return tmp_path / "live" / INSTANCE_ID / name


# ---------------------------------------------------------------------------
# Per-file classification
# ---------------------------------------------------------------------------


def test_a_truncated_stream_is_reported_truncated_with_its_readable_prefix(
    tmp_path: Path,
) -> None:
    """The headline case: a partial trailing message, reported loudly.

    The native path returns ``None`` here and the caller sees nothing. The
    preflight must instead name the file, the batches it could read, the rows
    it recovered, and the fact that the stream ended mid-message.
    """
    tape = _tape(tmp_path)
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    report = inspect_feather_file(tape)

    assert report.status is FeatherStatus.TRUNCATED
    assert report.ended_mid_message is True
    assert report.schema_readable is True
    assert 0 < report.rows < 200, "the readable prefix must survive and the tail must be lost"
    assert report.batches == 19
    assert report.readable_bytes < report.size_bytes
    assert report.lost_bytes > 0
    assert report.failure is not None


def test_a_zero_byte_file_is_empty_not_truncated(tmp_path: Path) -> None:
    """A file the writer opened and never flushed captured nothing.

    This is not hypothetical: the live tree carries a 0-byte
    ``instrument_close_*.feather`` for the currently-running capture. Reporting
    it as truncation would train the operator to ignore the alarm.
    """
    tape = _tape(tmp_path, "instrument_close_1.feather")
    tape.parent.mkdir(parents=True, exist_ok=True)
    tape.write_bytes(b"")

    report = inspect_feather_file(tape)

    assert report.status is FeatherStatus.EMPTY_FILE
    assert report.ended_mid_message is False
    assert report.schema_readable is False
    assert report.rows == 0
    assert report.lost_bytes == 0


def test_a_schema_only_stream_is_empty_not_truncated(tmp_path: Path) -> None:
    """A cleanly-closed stream with no record batches recorded nothing.

    Zero rows, and zero rows is the CORRECT answer for this file. It must not
    be confused with the truncated file above, which also reports zero rows in
    the native read path.
    """
    tape = _tape(tmp_path)
    _write_stream(tape, batches=0, close=True)

    report = inspect_feather_file(tape)

    assert report.status is FeatherStatus.EMPTY_STREAM
    assert report.ended_mid_message is False
    assert report.schema_readable is True
    assert report.end_of_stream_marker is True
    assert report.rows == 0
    assert report.lost_bytes == 0


def test_a_stream_truncated_inside_its_schema_is_truncated_not_empty(tmp_path: Path) -> None:
    """Zero rows AND an unreadable schema is still a LOSS, never an empty capture.

    ``pa.ipc.open_stream`` raises before any batch is reachable, so the row
    count is identical to the empty cases. Only the byte framing separates
    them, and the framing says bytes were written and then cut.
    """
    tape = _tape(tmp_path)
    _write_stream(tape, batches=20, close=True)
    intact = tape.read_bytes()
    tape.write_bytes(intact[:20])

    report = inspect_feather_file(tape)

    assert report.status is FeatherStatus.TRUNCATED
    assert report.schema_readable is False
    assert report.rows == 0
    assert report.size_bytes > 0
    assert report.lost_bytes == report.size_bytes


def test_a_kill_on_a_message_boundary_is_intact_without_an_end_of_stream_marker(
    tmp_path: Path,
) -> None:
    """An unclean death is NOT itself a fault; only a partial message is.

    ``tests/contract/test_quote_tape_unclean_shutdown.py`` proves every record
    still reads back. The preflight must agree, or it cries wolf on every
    SIGKILLed capture -- which is every unattended capture.
    """
    tape = _tape(tmp_path)
    _write_stream(tape, batches=20, close=False)

    report = inspect_feather_file(tape)

    assert report.status is FeatherStatus.INTACT
    assert report.end_of_stream_marker is False
    assert report.ended_mid_message is False
    assert report.rows == 200
    assert report.lost_bytes == 0


def test_a_cleanly_closed_stream_carries_its_end_of_stream_marker(tmp_path: Path) -> None:
    tape = _tape(tmp_path)
    _write_stream(tape, batches=3, close=True)

    report = inspect_feather_file(tape)

    assert report.status is FeatherStatus.INTACT
    assert report.end_of_stream_marker is True
    assert tape.read_bytes().endswith(END_OF_STREAM)
    assert report.rows == 30


def test_an_unreadable_file_is_reported_not_swallowed(tmp_path: Path) -> None:
    """A file that cannot be opened is an alarm, never a zero-row result."""
    tape = _tape(tmp_path)
    _write_stream(tape, batches=3, close=True)
    tape.chmod(0o000)
    try:
        report = inspect_feather_file(tape)
    finally:
        tape.chmod(0o600)

    assert report.status is FeatherStatus.UNREADABLE
    assert report.failure is not None
    assert report.rows == 0


# ---------------------------------------------------------------------------
# Instance-level scan
# ---------------------------------------------------------------------------


def test_the_scan_finds_flat_and_per_instrument_feather_files(tmp_path: Path) -> None:
    """The writer uses both layouts, so a walker that sees one is half blind."""
    root = tmp_path
    _write_stream(_tape(root, "quote_tick_1.feather"), batches=2, close=True)
    _write_stream(
        root / "live" / INSTANCE_ID / "custom_quote_tape_gap" / "SLUG.VENUE" / "part.feather",
        batches=1,
        close=True,
    )

    report = scan_instance(root, INSTANCE_ID)

    assert {file.path.name for file in report.files} == {"quote_tick_1.feather", "part.feather"}
    assert report.total_rows == 30


def test_a_truncated_file_makes_the_whole_instance_report_truncation(tmp_path: Path) -> None:
    root = tmp_path
    _write_stream(_tape(root, "quote_tick_1.feather"), batches=5, close=True)
    bad = _tape(root, "instrument_status_1.feather")
    _write_stream(bad, batches=5, close=False)
    _truncate(bad, drop_bytes=64)

    report = scan_instance(root, INSTANCE_ID)

    assert report.has_truncation is True
    assert [file.path for file in report.truncated] == [bad]
    assert report.captured_nothing is False


def test_an_instance_that_captured_nothing_is_reported_and_is_not_success(
    tmp_path: Path,
) -> None:
    """Zero rows is never success -- but it is a DIFFERENT failure from truncation."""
    root = tmp_path
    _write_stream(_tape(root, "quote_tick_1.feather"), batches=0, close=True)
    empty = _tape(root, "instrument_close_1.feather")
    empty.write_bytes(b"")

    report = scan_instance(root, INSTANCE_ID)

    assert report.captured_nothing is True
    assert report.has_truncation is False
    assert report.total_rows == 0
    assert len(report.empty) == 2


def test_scanning_an_unknown_instance_raises_rather_than_returning_an_empty_report(
    tmp_path: Path,
) -> None:
    """An empty report for a typo'd id is the original defect one level up."""
    (tmp_path / "live").mkdir()

    with pytest.raises(PreflightError) as excinfo:
        scan_instance(tmp_path, "no-such-instance")

    assert "no-such-instance" in str(excinfo.value)


def test_scanning_an_instance_with_no_feather_files_raises(tmp_path: Path) -> None:
    (tmp_path / "live" / INSTANCE_ID).mkdir(parents=True)

    with pytest.raises(PreflightError):
        scan_instance(tmp_path, INSTANCE_ID)


def test_list_instance_ids_returns_the_run_directories(tmp_path: Path) -> None:
    _write_stream(_tape(tmp_path, "quote_tick_1.feather"), batches=1, close=True)
    _write_stream(
        tmp_path / "live" / "instance-2" / "quote_tick_1.feather", batches=1, close=True
    )

    assert list_instance_ids(tmp_path) == ("instance-1", "instance-2")


def test_list_instance_ids_raises_when_the_subdirectory_is_absent(tmp_path: Path) -> None:
    with pytest.raises(PreflightError):
        list_instance_ids(tmp_path)


def test_the_scan_does_not_modify_the_catalog_it_inspects(tmp_path: Path) -> None:
    """A preflight that mutates the only copy of an irreplaceable tape is a defect."""
    root = tmp_path
    good = _tape(root, "quote_tick_1.feather")
    _write_stream(good, batches=5, close=True)
    bad = _tape(root, "instrument_status_1.feather")
    _write_stream(bad, batches=5, close=False)
    _truncate(bad, drop_bytes=64)

    def fingerprint() -> dict[str, tuple[str, int, int]]:
        return {
            str(path): (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in sorted((root / "live").rglob("*"))
            if path.is_file()
        }

    before = fingerprint()
    scan_instance(root, INSTANCE_ID)
    salvage_feather_file(bad)

    assert fingerprint() == before


# ---------------------------------------------------------------------------
# Salvage
# ---------------------------------------------------------------------------


def test_salvage_returns_the_readable_prefix_and_says_it_is_partial(tmp_path: Path) -> None:
    """A salvage that looked like a clean read would recreate the defect one level up."""
    tape = _tape(tmp_path)
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    result = salvage_feather_file(tape)

    assert result.is_partial is True
    assert result.table is not None
    assert result.table.num_rows == result.rows_recovered == 190
    assert result.bytes_lost > 0
    assert "TRUNCATED" in result.describe()
    assert str(result.bytes_lost) in result.describe()


def test_salvage_of_an_intact_file_is_not_partial(tmp_path: Path) -> None:
    tape = _tape(tmp_path)
    _write_stream(tape, batches=4, close=True)

    result = salvage_feather_file(tape)

    assert result.is_partial is False
    assert result.bytes_lost == 0
    assert result.require_complete().num_rows == 40


def test_require_complete_refuses_a_partial_salvage_and_names_the_loss(tmp_path: Path) -> None:
    """The safe unwrap must be the loud one; ``.table`` is the deliberate opt-in."""
    tape = _tape(tmp_path)
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    result = salvage_feather_file(tape)

    with pytest.raises(TruncatedTapeError) as excinfo:
        result.require_complete()

    message = str(excinfo.value)
    assert str(tape) in message
    assert "190" in message, "the caller must be told how much WAS recovered"
    assert str(result.bytes_lost) in message


def test_salvage_cannot_report_rows_lost_because_that_number_is_unknowable(
    tmp_path: Path,
) -> None:
    """Honesty bound: the incomplete message's row count is not on disk.

    Bytes lost IS knowable and is reported. Rows lost is not, and inventing it
    would be exactly the kind of confident wrong number this ticket exists to
    eliminate.
    """
    tape = _tape(tmp_path)
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    result = salvage_feather_file(tape)

    assert not hasattr(result, "rows_lost")
    assert "unknown" in result.describe().lower()


def test_salvage_of_a_stream_truncated_in_its_schema_recovers_no_table(tmp_path: Path) -> None:
    tape = _tape(tmp_path)
    _write_stream(tape, batches=20, close=True)
    tape.write_bytes(tape.read_bytes()[:20])

    result = salvage_feather_file(tape)

    assert result.is_partial is True
    assert result.table is None
    assert result.rows_recovered == 0
    with pytest.raises(TruncatedTapeError):
        result.require_complete()


def test_salvage_of_an_empty_file_is_not_partial_and_yields_no_table(tmp_path: Path) -> None:
    """Nothing was captured, so nothing was lost. The two must not blur."""
    tape = _tape(tmp_path)
    tape.parent.mkdir(parents=True, exist_ok=True)
    tape.write_bytes(b"")

    result = salvage_feather_file(tape)

    assert result.is_partial is False
    assert result.table is None
    assert result.bytes_lost == 0
    assert result.report.status is FeatherStatus.EMPTY_FILE
