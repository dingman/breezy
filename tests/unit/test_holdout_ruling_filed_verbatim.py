"""Pin the ARCH-owned holdout ruling filed under docs/evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SOURCE_PATH: Final[Path] = (
    _REPO_ROOT
    / "docs"
    / "plans"
    / "backlog"
    / "AUTONOMY_2026-10-03"
    / "reviews"
    / "snapshots"
    / "ARCH_rev9_2.md"
)
_EVIDENCE_FILENAME: Final[str] = "RULING_holdout_freeze_and_forward_window_2026-10-03.md"
_EVIDENCE_PATH: Final[Path] = _REPO_ROOT / "docs" / "evidence" / _EVIDENCE_FILENAME
_SOURCE_START_LINE: Final[int] = 379
_SOURCE_END_LINE: Final[int] = 392
_EXPECTED_SHA256: Final[str] = "2cfe8b335d30a077f9378c36374f69435b9cf895200c0144bcadac220afdeb80"


def _source_slice() -> bytes:
    lines = _SOURCE_PATH.read_bytes().splitlines(keepends=True)
    return b"".join(lines[_SOURCE_START_LINE - 1 : _SOURCE_END_LINE])


def test_the_arch_rev9_2_snapshot_source_exists() -> None:
    assert _SOURCE_PATH.is_file()


def test_the_holdout_ruling_evidence_file_exists() -> None:
    assert _EVIDENCE_PATH.is_file()


def test_the_evidence_file_is_the_verbatim_arch_source_slice() -> None:
    assert _EVIDENCE_PATH.read_bytes() == _source_slice()


def test_the_verbatim_slice_sha256_is_pinned() -> None:
    assert hashlib.sha256(_source_slice()).hexdigest() == _EXPECTED_SHA256


def test_the_evidence_file_sha256_matches_the_pinned_slice_sha256() -> None:
    assert hashlib.sha256(_EVIDENCE_PATH.read_bytes()).hexdigest() == _EXPECTED_SHA256
