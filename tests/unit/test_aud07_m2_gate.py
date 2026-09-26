"""AUD-07 Rev 2 M1c/M2 execution amendment, tests 30-33 (plan §6, §8).

`scripts/analysis/aud07_m2_gate.py` is a set of pure functions applying the
amendment's UNCHANGED gate literals and classification rule; the gate
module exists before any number does (amendment §6 step 1).
"""

from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path

from scipy.stats import beta as scipy_beta

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud07_m2_gate import ALPHA, I_CONF, V_CONF, V_THRESHOLD, branch, classify_cell, final_class


def _indep_cp_upper(count: int, n: int, confidence: float) -> float:
    """One-sided exact Clopper-Pearson upper bound, computed INDEPENDENTLY
    of `aud06a_qty_envelope_sweep.clopper_pearson_upper` -- review item 5:
    test 31 must not share its ground truth with the function it verifies.
    `beta.ppf(conf, c+1, n-c)`, 1.0 at c=n."""
    if count >= n:
        return 1.0
    return float(scipy_beta.ppf(confidence, count + 1, n - count))


def _indep_cp_lower(count: int, n: int, confidence: float) -> float:
    """One-sided exact Clopper-Pearson lower bound, independently derived.
    `beta.ppf(1-conf, c, n-c+1)`, 0.0 at c=0."""
    if count <= 0:
        return 0.0
    return float(scipy_beta.ppf(1.0 - confidence, count, n - count + 1))


def test_gate_literals_are_the_amendment_values() -> None:
    """Test 30."""
    assert ALPHA == 0.025
    assert V_THRESHOLD == 0.0283
    assert V_CONF == 0.95
    assert I_CONF == 1.0 - 0.05 / 16


def _count_for_cp_upper_at_most(n: int, threshold: float, *, confidence: float) -> int:
    """The largest `count` with `_indep_cp_upper(count, n, confidence) <= threshold`,
    computed from the INDEPENDENT `scipy.stats.beta.ppf` derivation above."""
    best = 0
    for count in range(n + 1):
        if _indep_cp_upper(count, n, confidence) <= threshold:
            best = count
        else:
            break
    return best


def test_classify_cell_at_v_and_i_boundaries_at_20k_and_80k() -> None:
    """Test 31 (review item 5: independently derived via `scipy.stats.beta.ppf`
    directly, never via the module's own `clopper_pearson_upper`/`_lower` --
    a shared implementation would make this test a tautology). Asserts
    `classify_cell` at count-1/count/count+1 around each independently
    computed boundary, at both the 20k and 80k rep counts."""
    for n in (20000, 80000):
        v_count = _count_for_cp_upper_at_most(n, V_THRESHOLD, confidence=V_CONF)
        assert classify_cell(v_count - 1, n) == "V"
        assert classify_cell(v_count, n) == "V"
        assert classify_cell(v_count + 1, n) != "V"

        # Walk upward from the V boundary until BOTH the V criterion fails
        # and the I criterion fires -- the unambiguous I region (V is
        # checked FIRST in `classify_cell`, so a count can independently
        # satisfy the I significance bound while still also clearing the
        # tight V_THRESHOLD -- ALPHA + delta margin -- at large n; that
        # band classifies V by design, never I, which is why both
        # independent conditions are required here, not just the I bound).
        i_count = v_count + 1
        while not (
            _indep_cp_upper(i_count, n, V_CONF) > V_THRESHOLD
            and _indep_cp_lower(i_count, n, I_CONF) > ALPHA
        ):
            i_count += 1
        assert classify_cell(i_count - 1, n) != "I"
        assert classify_cell(i_count, n) == "I"
        assert classify_cell(i_count + 1, n) == "I"


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


#: Captured from `aud07_m2_gate.py` at 32a764d (pre-AUD-07-M1c-eps_k), the
#: last commit before the eps_k switch. AUD-07 M1c-eps_k (RULING PR-1/PR-2)
#: only ever changes the f-producing SIM/pin layer -- f is performance-only
#: (RULING finding 1) and must never touch this V/I/INDETERMINATE gate.
_GATE_CODE_SHA256_AT_32A764D = (
    "71a0dbeea4fdf247ca007c2fc922469aa4d365b8dd4cfc1b117972486bcb9049"
)


def test_classify_final_class_and_branch_are_byte_unchanged_by_the_eps_k_switch() -> None:
    """The eps_k switch (AUD-07 M1c-eps_k) touches only the f-producing
    sim/pin layer; `classify_cell`/`final_class`/`branch` -- the actual
    V/I/INDETERMINATE gate -- must stay byte-for-byte identical."""
    source = (
        inspect.getsource(classify_cell)
        + inspect.getsource(final_class)
        + inspect.getsource(branch)
    )
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == _GATE_CODE_SHA256_AT_32A764D
