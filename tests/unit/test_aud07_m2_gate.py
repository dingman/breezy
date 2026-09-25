"""AUD-07 Rev 2 M1c/M2 execution amendment, tests 30-33 (plan §6, §8).

`scripts/analysis/aud07_m2_gate.py` is a set of pure functions applying the
amendment's UNCHANGED gate literals and classification rule; the gate
module exists before any number does (amendment §6 step 1).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud06a_qty_envelope_sweep import clopper_pearson_lower, clopper_pearson_upper
from aud07_m2_gate import ALPHA, I_CONF, V_CONF, V_THRESHOLD, branch, classify_cell, final_class


def test_gate_literals_are_the_amendment_values() -> None:
    """Test 30."""
    assert ALPHA == 0.025
    assert V_THRESHOLD == 0.0283
    assert V_CONF == 0.95
    assert I_CONF == 1.0 - 0.05 / 16


def _count_for_cp_upper_at_most(n: int, threshold: float, *, confidence: float) -> int:
    """The largest `count` with `clopper_pearson_upper(count, n, confidence) <= threshold`."""
    best = 0
    for count in range(n + 1):
        if clopper_pearson_upper(count, n, confidence=confidence) <= threshold:
            best = count
        else:
            break
    return best


def test_classify_cell_at_v_and_i_boundaries_at_20k_and_80k() -> None:
    """Test 31: the V boundary count (from the gate's own CP-upper
    function, never hand-typed) classifies V one side and not-V the other,
    at both the 20k and 80k rep counts. The I side is exercised at a count
    comfortably past the V/I crossover (V is checked FIRST in
    `classify_cell`, so a count can satisfy the `I` significance bound
    while still also clearing the tight `V_THRESHOLD` -- ALPHA + delta
    margin -- at large n; that band classifies V by design, never I)."""
    for n in (20000, 80000):
        v_count = _count_for_cp_upper_at_most(n, V_THRESHOLD, confidence=V_CONF)
        assert classify_cell(v_count, n) == "V"
        assert classify_cell(v_count + 1, n) != "V"

        # Walk upward from the V boundary until BOTH the V criterion fails
        # and the I criterion fires -- the unambiguous I region.
        i_count = v_count + 1
        while not (
            clopper_pearson_upper(i_count, n, confidence=V_CONF) > V_THRESHOLD
            and clopper_pearson_lower(i_count, n, confidence=I_CONF) > ALPHA
        ):
            i_count += 1
        assert classify_cell(i_count, n) == "I"


def test_80k_replaces_never_pools_with_20k_and_indeterminate_after_rerun_is_i() -> None:
    """Test 32."""
    assert final_class("INDETERMINATE", None) == "INDETERMINATE"
    assert final_class("INDETERMINATE", "V") == "V"
    assert final_class("INDETERMINATE", "I") == "I"
    # A cell still INDETERMINATE at 80k counts as I -- never pooled with the
    # 20k result, never left as INDETERMINATE.
    assert final_class("INDETERMINATE", "INDETERMINATE") == "I"
    # r80k always replaces r20k outright when present, whatever r20k was.
    assert final_class("V", "I") == "I"


def test_branch_v_needs_all_16_any_i_fires_i() -> None:
    """Test 33."""
    all_v = tuple(["V"] * 16)
    assert branch(all_v) == "V"

    one_indeterminate = ("V",) * 15 + ("INDETERMINATE",)
    assert branch(one_indeterminate) == "INDETERMINATE"

    one_i_among_vs = ("V",) * 15 + ("I",)
    assert branch(one_i_among_vs) == "I"

    one_i_among_mixed = ("V",) * 10 + ("INDETERMINATE",) * 5 + ("I",)
    assert branch(one_i_among_mixed) == "I"
