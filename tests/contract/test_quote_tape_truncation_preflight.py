"""BL-23 contract: the preflight is loud exactly where Nautilus is silent.

``tests/contract/test_quote_tape_unclean_shutdown.py`` measured the defect
against a real ``SIGKILL``: 228 KB on disk, ``convert_stream_to_data`` returns
normally, and the catalog holds ZERO rows. That file pins the *native*
behaviour and must never be weakened -- it is the evidence.

This file pins the *response*. It runs the same real writer, kills it the same
way, and asserts both halves in one place, because the pairing is the claim:

* the native read path still returns nothing, silently -- unchanged, because
  Nautilus is immutable and we did not patch it; and
* :func:`breezy.persistence.feather_preflight.scan_instance` reports the same
  bytes as ``TRUNCATED``, with the batches and rows it recovered, and the CLI
  exits non-zero.

A version bump that changes either half fails here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pyarrow as pa
import pytest
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.persistence.feather_preflight import (
    FeatherStatus,
    salvage_feather_file,
    scan_instance,
)
from breezy.runtime.quote_tape_preflight_cli import EXIT_TRUNCATED, run
from tests.contract.test_quote_tape_unclean_shutdown import (
    INSTANCE_ID,
    RECORD_COUNT,
    _sigkill_a_real_writer,
)

pytestmark = pytest.mark.contract


def _convert_and_count(catalog_root: Path) -> int:
    catalog = ParquetDataCatalog(str(catalog_root))
    catalog.convert_stream_to_data(INSTANCE_ID, QuoteTick, subdirectory="live")
    return len(catalog.query(data_cls=QuoteTick))


def test_the_preflight_reports_the_truncation_that_the_native_path_swallows(
    tmp_path: Path,
) -> None:
    tape = _sigkill_a_real_writer(tmp_path, mode="flush")
    with tape.open("r+b") as handle:
        handle.truncate(tape.stat().st_size - 64)

    report = scan_instance(tmp_path, INSTANCE_ID)

    assert report.has_truncation is True
    truncated = [file for file in report.files if file.path == tape]
    assert len(truncated) == 1
    assert truncated[0].status is FeatherStatus.TRUNCATED
    assert truncated[0].ended_mid_message is True
    assert 0 < truncated[0].rows < RECORD_COUNT
    assert truncated[0].lost_bytes > 0

    # The native path is UNCHANGED and still silent. If this ever stops being
    # true the preflight's reason for existing has changed, and that should
    # fail loudly rather than pass quietly.
    assert _convert_and_count(tmp_path) == 0


def test_the_console_entrypoint_exits_non_zero_on_a_real_killed_tape(
    tmp_path: Path,
) -> None:
    import io

    tape = _sigkill_a_real_writer(tmp_path, mode="flush")
    with tape.open("r+b") as handle:
        handle.truncate(tape.stat().st_size - 64)

    out, err = io.StringIO(), io.StringIO()
    code = run(
        argv=["--catalog", str(tmp_path), "--instance-id", INSTANCE_ID],
        env={},
        stdout=out,
        stderr=err,
    )

    assert code == EXIT_TRUNCATED
    assert "TRUNCATION DETECTED" in out.getvalue()


def test_a_kill_on_a_message_boundary_reports_intact_and_converts_in_full(
    tmp_path: Path,
) -> None:
    """No false alarm on the ordinary unattended-capture ending."""
    tape = _sigkill_a_real_writer(tmp_path, mode="flush")

    report = scan_instance(tmp_path, INSTANCE_ID)
    quote_files = [file for file in report.files if file.path == tape]

    assert quote_files[0].status is FeatherStatus.INTACT
    assert quote_files[0].end_of_stream_marker is False
    assert quote_files[0].rows == RECORD_COUNT
    assert report.has_truncation is False
    assert _convert_and_count(tmp_path) == RECORD_COUNT


def test_the_walker_sees_every_feather_file_the_native_reader_would_read(
    tmp_path: Path,
) -> None:
    """A preflight that misses a file is the silent-omission defect again.

    Pinned against Nautilus's own enumeration
    (``ParquetDataCatalog._list_feather_data_files``) so a layout change in a
    future release fails here instead of shrinking the preflight's coverage in
    silence. Ours is a superset by construction: it walks bytes on disk, so it
    also reports files whose data class is not registered with Nautilus.
    """
    _sigkill_a_real_writer(tmp_path, mode="flush")

    catalog = ParquetDataCatalog(str(tmp_path))
    native = {
        Path(file.path).resolve()
        for file in catalog._list_feather_data_files("live", INSTANCE_ID, QuoteTick)
    }
    ours = {file.path.resolve() for file in scan_instance(tmp_path, INSTANCE_ID).files}

    assert native, "the native enumeration must find something for this to mean anything"
    assert native <= ours


def test_the_salvaged_prefix_is_the_real_data_not_merely_some_rows(
    tmp_path: Path,
) -> None:
    """Salvage must reproduce the intact file's leading rows exactly.

    Recovering *a* table proves nothing; recovering the same bytes the intact
    tape holds is what makes a salvaged tape usable. The intact original is
    copied before truncation so the comparison is against real writer output.
    """
    tape = _sigkill_a_real_writer(tmp_path, mode="flush")
    intact_copy = tmp_path / "intact.feather"
    shutil.copyfile(tape, intact_copy)

    with intact_copy.open("rb") as handle:
        intact_table = pa.ipc.open_stream(handle).read_all()
    assert intact_table.num_rows == RECORD_COUNT

    with tape.open("r+b") as handle:
        handle.truncate(tape.stat().st_size - 64)

    result = salvage_feather_file(tape)

    assert result.is_partial is True
    assert result.table is not None
    recovered = result.rows_recovered
    assert 0 < recovered < RECORD_COUNT
    assert result.table.equals(intact_table.slice(0, recovered))
