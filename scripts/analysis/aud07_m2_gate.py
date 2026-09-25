#!/usr/bin/env python3
"""AUD-07 M2 ruling artefact gate (amendment §6.1) -- pure functions.

The gate literals and classification rule exist BEFORE any number does
(amendment §6 step 1). Reuses `clopper_pearson_upper`/`_lower`
(`aud06a_qty_envelope_sweep.py:393-404`, both one-sided); never
re-implements them.

No network. No repo writes.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud06a_qty_envelope_sweep import clopper_pearson_lower, clopper_pearson_upper

__all__ = [
    "ALPHA",
    "I_CONF",
    "V_CONF",
    "V_THRESHOLD",
    "Verdict",
    "branch",
    "classify_cell",
    "final_class",
]

Verdict = Literal["V", "I", "INDETERMINATE"]

#: Amendment §4 M1c, "Unchanged" -- cited verbatim, never re-derived.
ALPHA: Final[float] = 0.025
#: V: one-sided 95% CP-upper <= 0.0283 (amendment "Unchanged").
V_THRESHOLD: Final[float] = 0.0283
V_CONF: Final[float] = 0.95
#: I: CP-lower at confidence 1 - 0.05/16 > alpha (amendment "Unchanged",
#: Bonferroni over the 16 mixed cells).
I_CONF: Final[float] = 1.0 - 0.05 / 16


def classify_cell(count: int, n: int) -> Verdict:
    """One cell's classification (amendment §6.1 `classify_cell`):
    `V` if the one-sided `V_CONF` CP-upper bound is <= `V_THRESHOLD`;
    else `I` if the one-sided `I_CONF` CP-lower bound is > `ALPHA`;
    else `INDETERMINATE`."""
    cp_upper = clopper_pearson_upper(count, n, confidence=V_CONF)
    if cp_upper <= V_THRESHOLD:
        return "V"
    cp_lower = clopper_pearson_lower(count, n, confidence=I_CONF)
    if cp_lower > ALPHA:
        return "I"
    return "INDETERMINATE"


def final_class(r20k: Verdict, r80k: Verdict | None) -> Verdict:
    """The 80k result REPLACES the 20k result and is never pooled with it
    (amendment "Unchanged"). A cell still `INDETERMINATE` at 80k counts as
    `I` (amendment "Unchanged")."""
    if r80k is None:
        return r20k
    if r80k == "INDETERMINATE":
        return "I"
    return r80k


def branch(mixed16: Sequence[Verdict]) -> Verdict:
    """`V` only if all 16 mixed cells are `V`; `I` if any is `I`
    (amendment §6.1 `branch`); otherwise `INDETERMINATE`."""
    if any(c == "I" for c in mixed16):
        return "I"
    if all(c == "V" for c in mixed16):
        return "V"
    return "INDETERMINATE"
