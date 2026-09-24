"""A mechanism-test directory is ineligible as a PREREG, manifest, or tally input.

The marker is written beside the existing look-ahead caveat. Readers refuse the
directory before they parse rows. A directory that does not carry the marker
keeps today's empty-store contract.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pyarrow.parquet as pq
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WHOLE_TAPE = _REPO_ROOT / "scripts" / "analysis" / "whole_tape_paper_replay.py"


def _load_whole_tape() -> ModuleType:
    scripts = _WHOLE_TAPE.parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("whole_tape_paper_replay", _WHOLE_TAPE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row() -> dict[str, str]:
    return {
        "station": "LAX",
        "climate_day": "2026-09-01",
        "lag_minutes": "30",
        "precision_mode": "nws_integer_c",
        "instrument_id": "synthetic-instrument",
        "fill_px": "0.41",
        "entry_ask": "0.40",
        "best_l2_ask_at_entry": "0.40",
        "fill_minus_entry_ask": "0.01",
        "fill_minus_l2_ask": "0.01",
        "lookahead_caveat": "MECHANISM TEST -- NO VERDICT",
    }


def test_prereg_and_tally_readers_refuse_a_mechanism_test_directory(tmp_path: Path) -> None:
    whole = _load_whole_tape()
    whole._write_mechanism_trials(tmp_path, [_row()])

    table = pq.read_schema(tmp_path / "mechanism_trials.parquet")
    metadata = table.metadata or {}
    assert metadata.get(b"mechanism_test_only") == b"true"

    import csv

    with (tmp_path / "mechanism_trials.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["mechanism_test_only"] == "true"

    from breezy.persistence.family_manifest import load_family_manifest
    from breezy.persistence.mechanism_test_guard import (
        MechanismTestIneligibleError,
        assert_prereg_directory_eligible,
    )
    from breezy.persistence.scored_trial_store import read_scored_trials

    with pytest.raises(MechanismTestIneligibleError):
        assert_prereg_directory_eligible(tmp_path)
    with pytest.raises(MechanismTestIneligibleError):
        read_scored_trials(tmp_path)

    manifest = tmp_path / "family.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(MechanismTestIneligibleError):
        load_family_manifest(manifest)

    clean = tmp_path / "clean-store"
    clean.mkdir()
    assert read_scored_trials(clean) == ()
    assert_prereg_directory_eligible(clean)
