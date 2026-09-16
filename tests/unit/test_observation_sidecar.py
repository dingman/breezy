"""Unit tests for `breezy.ingest.observation_sidecar` (2026-09-16 GAP fix).

A MIA `observation_ambiguous` refusal on the first live day could not be
diagnosed after the fact -- no raw NWS payload was ever persisted. This
module's `ObservationSidecar` is the bounded, best-effort JSONL sidecar that
fixes that, mirroring `OfferTape`'s own sidecar pattern (mkdir best-effort,
append best-effort, a per-file byte cap that stops disk writes without ever
raising).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from breezy.ingest.observation_sidecar import (
    DEFAULT_OBSERVATION_SIDECAR_MAX_BYTES,
    ObservationSidecar,
    ObservationSidecarRow,
)

_METAR_ROW = ObservationSidecarRow(
    station="KMDW",
    observed_at="2026-09-16T18:20:00+00:00",
    temp_c_raw=32.8,
    raw_message="KMDW 161820Z 09008KT 10SM CLR 33/13 A3020 RMK AO2 SLP224 T03280133",
    is_metar=True,
    precision_c_tenths=5,
    temp_c_tenths=328,
    source_url_path="/stations/KMDW/observations",
    fetched_at_ns=1_800_000_000_000_000_000,
)

_INTERVAL_ROW = ObservationSidecarRow(
    station="KMIA",
    observed_at="2026-09-16T18:20:00+00:00",
    temp_c_raw=33.0,
    raw_message="",
    is_metar=False,
    precision_c_tenths=10,
    temp_c_tenths=330,
    source_url_path="/stations/KMIA/observations",
    fetched_at_ns=1_800_000_000_000_000_000,
)


def _line_bytes(row: ObservationSidecarRow) -> int:
    return len(json.dumps(row.to_dict(), sort_keys=True).encode("utf-8")) + 1


def test_default_max_bytes_is_pinned_at_64_mib() -> None:
    assert DEFAULT_OBSERVATION_SIDECAR_MAX_BYTES == 64 * 1024 * 1024


def test_a_metar_row_round_trips_through_to_dict_and_json(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    sidecar = ObservationSidecar(path)

    sidecar.append(_METAR_ROW)

    line = path.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(line)
    assert parsed == _METAR_ROW.to_dict()
    assert parsed["is_metar"] is True
    assert parsed["precision_c_tenths"] == 5
    assert parsed["raw_message"].startswith("KMDW")


def test_a_whole_degree_row_round_trips_with_no_metar_text(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    sidecar = ObservationSidecar(path)

    sidecar.append(_INTERVAL_ROW)

    line = path.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(line)
    assert parsed["is_metar"] is False
    assert parsed["precision_c_tenths"] == 10
    assert parsed["raw_message"] == ""


def test_append_with_no_path_is_a_noop(tmp_path: Path) -> None:
    sidecar = ObservationSidecar(None)
    sidecar.append(_METAR_ROW)  # must not raise
    assert sidecar.errors == 0
    assert sidecar.capped == 0


def test_an_unwritable_sidecar_directory_never_raises_and_counts_an_error(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    path = blocker / "sub" / "observations.jsonl"

    sidecar = ObservationSidecar(path)  # must not raise

    assert sidecar.errors == 1
    sidecar.append(_METAR_ROW)  # still must not raise
    assert not path.exists()


def test_below_the_cap_every_row_is_written_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    sidecar = ObservationSidecar(path, max_bytes=DEFAULT_OBSERVATION_SIDECAR_MAX_BYTES)

    for _ in range(5):
        sidecar.append(_METAR_ROW)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert sidecar.capped == 0


def test_at_the_cap_further_rows_stop_appending_and_the_counter_increments(
    tmp_path: Path,
) -> None:
    path = tmp_path / "observations.jsonl"
    one_line = _line_bytes(_METAR_ROW)
    cap = one_line * 3
    sidecar = ObservationSidecar(path, max_bytes=cap)

    for _ in range(3):
        sidecar.append(_METAR_ROW)
    size_at_cap = path.stat().st_size
    assert size_at_cap == cap

    for _ in range(4):
        sidecar.append(_METAR_ROW)

    assert path.stat().st_size == size_at_cap
    assert sidecar.capped == 4
    assert sidecar.errors == 0

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        assert json.loads(line) == _METAR_ROW.to_dict()


def test_the_cap_warning_is_logged_exactly_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "observations.jsonl"
    one_line = _line_bytes(_METAR_ROW)
    sidecar = ObservationSidecar(path, max_bytes=one_line)

    caplog.set_level(logging.WARNING, logger="breezy.ingest.observation_sidecar")
    sidecar.append(_METAR_ROW)  # exactly fills the cap
    for _ in range(3):
        sidecar.append(_METAR_ROW)  # every one of these is refused

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert sidecar.capped == 3


def test_a_process_restart_resumes_the_cap_from_the_real_on_disk_size(
    tmp_path: Path,
) -> None:
    path = tmp_path / "observations.jsonl"
    one_line = _line_bytes(_METAR_ROW)
    cap = one_line * 3

    first = ObservationSidecar(path, max_bytes=cap)
    for _ in range(3):
        first.append(_METAR_ROW)
    assert path.stat().st_size == cap

    second = ObservationSidecar(path, max_bytes=cap)
    second.append(_METAR_ROW)

    assert path.stat().st_size == cap
    assert second.capped == 1


def test_max_bytes_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        ObservationSidecar(Path("/tmp/unused.jsonl"), max_bytes=0)
