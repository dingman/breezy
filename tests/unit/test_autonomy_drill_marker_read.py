"""ARCH-0 seam 5b ruling A5b-R5: the drill-marker read reports the raw sha256 and fstat failures."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from breezy.persistence.autonomy import drill_marker
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.drill_marker import (
    DrillMarker,
    MarkerError,
    MarkerErrorReason,
    read_marker,
)
from breezy.persistence.autonomy.paths import AutonomyPaths

SHA = "d" * 64
START = 1_791_100_800 * 10**9


def wire() -> dict[str, object]:
    return {
        "schema": "drill_marker/v1",
        "registry_root": "/home/jon/.local/share/breezy",
        "venue": "polymarket_us",
        "episode_id": "ep1",
        "child_id": "pm_us_crh_fq_v1_d0001",
        "detector": "DRILL_INJECT",
        "step": "demote",
        "window_start_ns": START,
        "window_end_ns": START + 10**9,
        "abort_record_sha256": None,
        "drill_clause_sha256": SHA,
        "ts_ns": START,
    }


def place(root: Path, raw: bytes) -> None:
    folder = root / "registry" / "drill"
    folder.mkdir(parents=True)
    folder.chmod(0o700)
    (folder / "marker.json").write_bytes(raw)
    (folder / "marker.json").chmod(0o600)


def test_marker_read_returns_the_sha256_of_the_raw_bytes(tmp_path: Path) -> None:
    raw = canonical_json(wire())
    place(tmp_path, raw)
    marker = read_marker(AutonomyPaths(tmp_path))
    assert isinstance(marker, DrillMarker)
    assert marker.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert marker.to_wire() == wire()  # the digest is not a wire key


def test_the_digest_is_of_the_bytes_read_not_of_a_re_serialisation(tmp_path: Path) -> None:
    raw = b" " + canonical_json(wire()) + b"\n"  # parses, but is not the canonical bytes
    place(tmp_path, raw)
    marker = read_marker(AutonomyPaths(tmp_path))
    assert isinstance(marker, DrillMarker)
    assert marker.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert marker.raw_sha256 != hashlib.sha256(canonical_json(wire())).hexdigest()


def test_an_fstat_failure_is_a_marker_error_not_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    place(tmp_path, canonical_json(wire()))

    def failing_fstat(_fd: int) -> os.stat_result:
        raise OSError(5, "boom")

    monkeypatch.setattr(drill_marker, "os", SimpleNamespace(close=os.close, fstat=failing_fstat))
    result = read_marker(AutonomyPaths(tmp_path))
    assert isinstance(result, MarkerError)
    assert result.reason is MarkerErrorReason.DIR_UNSAFE and result.detail == "io"


def test_an_fstat_failure_after_the_directory_walk_is_also_a_marker_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    place(tmp_path, canonical_json(wire()))
    from breezy.persistence.autonomy import single_read

    real = single_read.walk_dirs
    calls: list[int] = []

    def walk_then_break(rootfd: int, rel: object, **kw: object) -> int:
        fd = real(rootfd, rel, **kw)  # type: ignore[arg-type]
        calls.append(fd)
        return fd

    monkeypatch.setattr(drill_marker, "walk_dirs", walk_then_break)
    monkeypatch.setattr(drill_marker, "os", SimpleNamespace(close=os.close, fstat=_raise_oserror))
    assert isinstance(read_marker(AutonomyPaths(tmp_path)), MarkerError)
    assert calls  # the walk itself succeeded; the descriptor check is what failed


def _raise_oserror(_fd: int) -> os.stat_result:
    raise OSError(5, "boom")
