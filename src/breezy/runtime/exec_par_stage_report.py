"""EXEC-PAR BG-5b: the stage report as canonical JSON (counts, ratios and flags only).

``StageReport`` (BG-5a) carries no currency amounts, so the document can sit in the local
store for BG-10(f) and BG-7 to read (r4.5 O5: the per-day AMBIGUOUS counts are in
``day_stats``). Decimals are written as strings, never floats.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from enum import Enum

from breezy.runtime.exec_par_stage_types import StageReport

__all__ = ["report_json"]


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def report_json(report: StageReport) -> str:
    """Deterministic compact JSON of the report."""
    return json.dumps(_plain(asdict(report)), sort_keys=True, separators=(",", ":"))
