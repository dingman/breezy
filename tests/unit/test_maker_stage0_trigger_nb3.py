"""MAKER-S2 second look (C4, NB3): trigger rows are hash-pinned, so wrong types are refused."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis.maker_stage0_inputs import InputRefused
from scripts.analysis.maker_stage0_trigger_rule import read_trigger_rows

_GOOD: dict[str, Any] = {
    "station": "SFO", "climate_day": "2026-10-14", "reason": "COVERED", "first_seen_ns": 5
}  # fmt: skip


@pytest.mark.parametrize(
    "patch",
    [
        {"station": 7},
        {"reason": None},
        {"climate_day": 20261014},
        {"first_seen_ns": "5"},
        {"first_seen_ns": 5.0},
        {"first_seen_ns": True},
    ],
)
def test_read_trigger_rows_rejects_wrong_types(tmp_path: Path, patch: dict[str, Any]) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps({**_GOOD, **patch}) + "\n")
    with pytest.raises(InputRefused):
        read_trigger_rows(path)
    path.write_text(json.dumps({**_GOOD, "first_seen_ns": None}) + "\n")
    assert read_trigger_rows(path)[0].first_seen_ns is None
