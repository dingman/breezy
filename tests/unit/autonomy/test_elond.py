"""ARCH-0-E25: the per-lineage e-LOND alpha schedule (`persistence/autonomy/elond.py`).

E-25 rule 4: `halving_v1` is alpha_total * 2**-k; `elond_heavy_tailed_v1` is
alpha_total * gamma_k * (R + 1) with gamma_t = g(t) / sum_{s<=T} g(s), g(t) = 1/(t ln^2(t+1)),
T = `pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME`, and R the lineage's effective CHALLENGER->CHAMPION
PROMOTE count before the nomination row's `ts_ns`.
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal, localcontext
from itertools import pairwise
from pathlib import Path
from typing import Final

import pytest

from breezy.persistence.autonomy import elond, pins
from tests.unit.test_registry_fold import DAY, INCUMBENT, LAUNCH, run
from tests.unit.test_registry_fold_effects import NEXT_DAY, NEXT_LATE, activated_pair, full_episode
from tests.unit.test_registry_fold_tallies import lineage_of

REPO: Final = Path(__file__).resolve().parents[3]
DESIGN_JSON: Final = (
    REPO / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json"
)
SRC: Final = REPO / "src" / "breezy"
ALPHA_TOTAL: Final = Decimal("0.025")
REL: Final = 1e-12

# Literal reference vectors. Provenance: ONE scratch run of scripts/analysis/fq_mc_eprocess.py
# (git blob sha 2f5b5b2e036c3d07a520206f76b639cbacf8a50b, `git hash-object`), ALPHA_TOTAL=0.025,
# T_NOMINATIONS=4:
#   PYTHONPATH=src python -c "import fq_mc_eprocess as m; print(repr(m.gamma_schedule(4)));
#       [print(R, repr(tuple(m.alpha_k(k, promotions=R) for k in range(1, 5)))) for R in (0, 1, 3)]"
# (with scripts/analysis on sys.path). This test never imports scripts/.
MC_GAMMA: Final = (
    0.7525926338021945, 0.14979316064842677, 0.06271605281684955, 0.034898152732529185,
)  # fmt: skip
MC_ALPHA: Final = {
    0: (0.018814815845054865, 0.0037448290162106694, 0.001567901320421239,
        0.0008724538183132297),
    1: (0.03762963169010973, 0.007489658032421339, 0.003135802640842478,
        0.0017449076366264594),
    3: (0.07525926338021946, 0.014979316064842678, 0.006271605281684956,
        0.003489815273252919),
}  # fmt: skip


def _gamma_floats() -> list[float]:
    return [float(elond.gamma(t)) for t in range(1, pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME + 1)]


def test_elond_alpha_matches_pinned_gamma_schedule() -> None:
    """FQ-R26: T and the schedule name come from the F5 design JSON and equal the pins."""
    design = json.loads(DESIGN_JSON.read_text())
    assert design["gamma_schedule"] == "elond_heavy_tailed_v1"
    assert design["gamma_schedule"] in elond.SCHEDULES
    assert design["T"] == pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME == 4
    assert Decimal(str(design["alpha_total"])) == ALPHA_TOTAL
    for k in range(1, design["T"] + 1):
        alpha = elond.alpha_k(k, 0, "elond_heavy_tailed_v1", ALPHA_TOTAL)
        assert float(alpha) == pytest.approx(MC_ALPHA[0][k - 1], rel=REL)


def test_gamma_heavy_tailed_normalised() -> None:
    values: list[Decimal] = [elond.gamma(t) for t in range(1, 5)]
    assert all(isinstance(v, Decimal) for v in values)
    with localcontext() as ctx:
        ctx.prec = 60  # the ambient 28 digits would round the very sum under test
        assert abs(sum(values, Decimal(0)) - 1) < Decimal("1e-30")
    assert values[-1] > 0
    assert all(left > right for left, right in pairwise(values))


def test_elond_sum_alpha_le_alpha_total_at_zero_discoveries() -> None:
    total = sum(
        elond.alpha_k(k, 0, "elond_heavy_tailed_v1", ALPHA_TOTAL)
        for k in range(1, pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME + 1)
    )
    assert isinstance(total, Decimal)
    assert total <= ALPHA_TOTAL  # exact Decimal comparison; floor quantisation never overshoots
    assert ALPHA_TOTAL - total < Decimal("1e-17")  # ... and is not far below it


def test_elond_alpha_is_canonical_decimal_representable() -> None:
    from breezy.persistence.autonomy.canonical import decimal_str

    for r in (0, 1, 3, 50):
        for k in range(1, 5):
            decimal_str(elond.alpha_k(k, r, "elond_heavy_tailed_v1", ALPHA_TOTAL))
            decimal_str(elond.alpha_k(k, r, "halving_v1", ALPHA_TOTAL))


def test_elond_matches_f5_mc_reference_vectors() -> None:
    for got, want in zip(_gamma_floats(), MC_GAMMA, strict=True):
        assert got == pytest.approx(want, rel=REL)
    for promotions, vector in MC_ALPHA.items():
        for k, want in enumerate(vector, start=1):
            level = elond.alpha_k(k, promotions, "elond_heavy_tailed_v1", ALPHA_TOTAL)
            assert float(level) == pytest.approx(want, rel=REL)


def test_halving_v1_matches_arch_geometric() -> None:
    for k in range(1, pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME + 1):
        got = elond.alpha_k(k, 0, "halving_v1", ALPHA_TOTAL)
        assert got == ALPHA_TOTAL * Decimal(2) ** -k  # exact: 0.025 * 2**-k has <= 18 places
        assert float(got) == pytest.approx(0.025 * 2.0**-k, rel=REL)
    # R is not used by halving_v1 (it is the FWER schedule).
    assert elond.alpha_k(2, 5, "halving_v1", ALPHA_TOTAL) == elond.alpha_k(
        2, 0, "halving_v1", ALPHA_TOTAL
    )


@pytest.mark.parametrize("bad_t", [0, -1, 5, True, 1.0, "1", None])
def test_gamma_refuses_out_of_range_and_non_int_t(bad_t: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        elond.gamma(bad_t)  # type: ignore[arg-type]


def test_gamma_refuses_horizon_above_the_pins_ceiling() -> None:
    with pytest.raises(ValueError):
        elond.gamma(1, pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME + 1)
    with pytest.raises((ValueError, TypeError)):
        elond.gamma(1, True)
    assert elond.gamma(1, 1) == 1  # a shorter horizon renormalises


@pytest.mark.parametrize(
    ("k", "r", "schedule", "total"),
    [
        (0, 0, "elond_heavy_tailed_v1", ALPHA_TOTAL),
        (5, 0, "elond_heavy_tailed_v1", ALPHA_TOTAL),
        (True, 0, "elond_heavy_tailed_v1", ALPHA_TOTAL),
        (1, -1, "elond_heavy_tailed_v1", ALPHA_TOTAL),
        (1, True, "elond_heavy_tailed_v1", ALPHA_TOTAL),
        (1, 1.0, "elond_heavy_tailed_v1", ALPHA_TOTAL),
        (1, 0, "unknown_v1", ALPHA_TOTAL),
        (1, 0, "elond_heavy_tailed_v1", 0.025),
        (1, 0, "elond_heavy_tailed_v1", Decimal(0)),
        (1, 0, "elond_heavy_tailed_v1", Decimal(1)),
        (1, 0, "elond_heavy_tailed_v1", Decimal("NaN")),
        (1, 0, "halving_v1", Decimal("-0.1")),
        (0, 0, "halving_v1", ALPHA_TOTAL),
    ],
)
def test_elond_refuses_out_of_range_and_bool_inputs(
    k: object, r: object, schedule: object, total: object
) -> None:
    with pytest.raises((ValueError, TypeError)):
        elond.alpha_k(k, r, schedule, total)  # type: ignore[arg-type]


def test_elond_ignores_the_ambient_decimal_context() -> None:
    import decimal

    baseline = elond.alpha_k(2, 1, "elond_heavy_tailed_v1", ALPHA_TOTAL)
    with decimal.localcontext() as ctx:
        ctx.prec = 5
        ctx.rounding = decimal.ROUND_UP
        assert elond.alpha_k(2, 1, "elond_heavy_tailed_v1", ALPHA_TOTAL) == baseline
        assert elond.gamma(3) == elond.gamma(3)
    with decimal.localcontext() as ctx:
        ctx.prec = 60
        assert elond.alpha_k(2, 1, "elond_heavy_tailed_v1", ALPHA_TOTAL) == baseline


def test_elond_schedule_refused_for_fixed_n_lineage() -> None:
    """E-25 rule 4 pairing rule, as a pure function (the AUT-5 r8 loader will call it)."""
    elond.require_schedule_pairing("elond_heavy_tailed_v1", "e_process")
    elond.require_schedule_pairing("halving_v1", "fixed_n")
    with pytest.raises(ValueError):
        elond.require_schedule_pairing("elond_heavy_tailed_v1", "fixed_n")
    with pytest.raises(ValueError):
        elond.require_schedule_pairing("halving_v1", "e_process")
    with pytest.raises(ValueError):
        elond.require_schedule_pairing("nope", "e_process")
    with pytest.raises(ValueError):
        elond.require_schedule_pairing("halving_v1", "sequential")


def test_promotions_before_is_strictly_before_ts_ns() -> None:
    promotions = (10, 20, 20, 30)
    assert elond.promotions_before(promotions, 10) == 0
    assert elond.promotions_before(promotions, 11) == 1
    assert elond.promotions_before(promotions, 20) == 1
    assert elond.promotions_before(promotions, 21) == 3
    assert elond.promotions_before(promotions, 31) == 4
    assert elond.promotions_before((), 5) == 0
    for bad in (True, -1, 1.5):
        with pytest.raises((ValueError, TypeError)):
            elond.promotions_before(promotions, bad)  # type: ignore[arg-type]


def test_elond_r_counts_only_effective_champion_promotes() -> None:
    """R is fed from the fold's `promotions`: PROMOTE counts; DRILL_PROMOTE and ROLLBACK do not."""
    chain, _head, _tail = activated_pair()
    effective = lineage_of(run(chain, LAUNCH))["promotions"]
    assert effective == (LAUNCH,)
    assert elond.promotions_before(effective, LAUNCH) == 0  # at the instant: not yet
    assert elond.promotions_before(effective, LAUNCH + 1) == 1
    pending = lineage_of(run(chain, LAUNCH - 1))["promotions"]
    assert elond.promotions_before(pending, LAUNCH + 1) == 0  # a still-pending pair is no R

    drill, _head, _closing = full_episode()
    drilled = lineage_of(run(drill, NEXT_LATE), INCUMBENT)["promotions"]
    assert drilled == ()  # DRILL_PROMOTE pair and its close never charge `promotions`
    assert elond.promotions_before(drilled, NEXT_LATE) == 0
    assert DAY < NEXT_DAY  # the drill episode spans two days


def _python_files(*roots: str) -> list[Path]:
    return sorted(p for root in roots for p in (SRC / root).rglob("*.py"))


def test_elond_single_definition_in_persistence() -> None:
    """No second `gamma` / `alpha_k` definition under persistence/ or analysis/.

    The `is`-identity half (a re-export is the same object) is deferred to the first slice that
    re-exports `elond` (F7B-R4).
    """
    hits: list[tuple[str, str]] = []
    for path in _python_files("persistence", "analysis"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in {
                "gamma",
                "alpha_k",
            }:
                hits.append((path.name, node.name))
    assert sorted(hits) == [("elond.py", "alpha_k"), ("elond.py", "gamma")]


def test_elond_imports_stdlib_decimal_and_pins_only() -> None:
    tree = ast.parse((SRC / "persistence/autonomy/elond.py").read_text())
    allowed_stdlib = {"__future__", "decimal", "collections", "typing", "enum", "math"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed_stdlib, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            module = node.module or ""
            if module.split(".")[0] == "breezy":
                assert (
                    module == "breezy.persistence.autonomy"
                    and [a.name for a in node.names] == ["pins"]
                    or module == "breezy.persistence.autonomy.pins"
                ), module
            else:
                assert module.split(".")[0] in allowed_stdlib, module


def test_alpha_k_refuses_level_at_or_above_one() -> None:
    with pytest.raises(ValueError, match=r"k=1.*R=30"):
        elond.alpha_k(1, 30, "elond_heavy_tailed_v1", Decimal("0.05"))
    # A huge R must be refused as a ValueError, never a decimal.InvalidOperation from quantize.
    with pytest.raises(ValueError, match="level"):
        elond.alpha_k(1, 10**17, "elond_heavy_tailed_v1", Decimal("0.05"))


def test_alpha_k_allows_level_above_alpha_total_below_one() -> None:
    alpha_total = Decimal("0.05")
    level = elond.alpha_k(1, 1, "elond_heavy_tailed_v1", alpha_total)
    assert alpha_total < level < Decimal(1)
