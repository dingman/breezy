"""Refuse a mechanism-test directory as a PREREG, manifest, or tally input.

``whole_tape_paper_replay`` writes ``mechanism_test_only=true`` into the trial
parquet schema metadata and the trial CSV. That directory is a plumbing test.
It must not be read as promotion evidence. Absence of the marker leaves the
store eligible; a present marker, or a marker file that cannot be read, refuses.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pyarrow.parquet as pq

_METADATA_KEY = b"mechanism_test_only"
_COLUMN = "mechanism_test_only"
_TRUE = frozenset({"true", "1", "yes"})
_PARQUET_NAME = "mechanism_trials.parquet"
_CSV_NAME = "mechanism_trials.csv"


class MechanismTestIneligibleError(ValueError):
    """The directory declares itself ineligible for a PREREG or tally read."""


def assert_prereg_directory_eligible(directory: Path) -> None:
    """Raise when ``directory`` carries a mechanism-test marker.

    An absent path is not a directory carrying the marker (the scored-trial
    store's own "fresh deployment" contract). A directory that exists is
    scanned for ``mechanism_trials.parquet`` / ``.csv``, including nested
    lag folders, so pointing a tally at the replay root still refuses.
    """
    if not directory.exists():
        return
    if not directory.is_dir():
        raise MechanismTestIneligibleError(
            f"{directory} is not a directory; refusing it as a PREREG or tally input"
        )
    if _declares_mechanism_test_only(directory):
        raise MechanismTestIneligibleError(
            f"{directory} carries mechanism_test_only=true and cannot be read "
            "as a PREREG, family-manifest, or tally input"
        )


def _declares_mechanism_test_only(directory: Path) -> bool:
    for path in directory.rglob(_PARQUET_NAME):
        if path.is_file() and _parquet_declares(path):
            return True
    for path in directory.rglob(_CSV_NAME):
        if path.is_file() and _csv_declares(path):
            return True
    return False


def _parquet_declares(path: Path) -> bool:
    metadata = pq.read_schema(path).metadata or {}
    raw = metadata.get(_METADATA_KEY)
    if raw is None:
        return False
    text = raw.decode("utf-8", errors="replace").strip().lower()
    if text in _TRUE:
        return True
    raise MechanismTestIneligibleError(
        f"{path} carries mechanism_test_only={raw!r}, which is not an explicit "
        "false; refusing it as a PREREG or tally input"
    )


def _csv_declares(path: Path) -> bool:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or _COLUMN not in reader.fieldnames:
            return False
        for row in reader:
            value = (row.get(_COLUMN) or "").strip().lower()
            if value not in _TRUE | {"false", "0", "no"}:
                raise MechanismTestIneligibleError(
                    f"{path} carries mechanism_test_only={value!r}, which is not "
                    "a boolean marker; refusing it as a PREREG or tally input"
                )
        # The column is present. True refuses. An explicit false, or a header
        # with no rows, still carries the field, so it refuses too.
        return True
