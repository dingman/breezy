"""RED-first: `breezy.settlement.current_rung_hold_v2.StratumV2`/`build_stratum_v2`.

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b Sec 5/6,
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` Sec "Tests" (non-vacuous
BE golden, `cell_dead` at n=59/60, inlined-Wilson equivalence).
"""

from __future__ import annotations

import importlib.util
import random
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.settlement.current_rung_hold_v2 import (
    StratumRow,
    StratumV2,
    build_stratum_v2,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

FEE_THETA = 0.06


def _break_even(ask: float) -> float:
    """Local re-derivation of `mb_current_rung_edge_study.break_even` (v1's
    registered analysis BE, `ask + theta*ask*(1-ask)`) -- documented formula
    only, never imported (rev b Sec 5 non-vacuity: `mean(BE_i)` must be
    strictly less than this on a concave-fee golden)."""
    return ask + FEE_THETA * ask * (1.0 - ask)


def _row(entry_ask: float, held: bool, *, station: str = "MIA") -> StratumRow:
    ask = Decimal(str(entry_ask))
    fee = Decimal(str(FEE_THETA)) * ask * (1 - ask)
    return StratumRow(entry_ask=ask, fee=fee, held=held, station=station)


def _load_archive_correction_probe() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "archive_correction_probe.py"
    spec = importlib.util.spec_from_file_location("archive_correction_probe", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def archive_correction_probe() -> ModuleType:
    return _load_archive_correction_probe()


def test_build_stratum_v2_is_none_for_an_empty_stratum() -> None:
    assert build_stratum_v2("pooled", ()) is None


def test_build_stratum_v2_computes_n_k_mean_ask_and_pi() -> None:
    rows = (_row(0.10, held=True), _row(0.50, held=False), _row(0.90, held=True))
    stratum = build_stratum_v2("pooled", rows)
    assert stratum is not None
    assert stratum.n == 3
    assert stratum.k == 2
    assert stratum.mean_ask == pytest.approx(Decimal("0.5"), abs=Decimal("1e-9"))
    expected_pi = sum(_break_even(a) for a in (0.10, 0.50, 0.90)) / 3
    assert float(stratum.pi) == pytest.approx(expected_pi, abs=1e-9)


def test_non_vacuous_be_golden_mean_of_be_i_is_strictly_below_break_even_of_mean_ask() -> None:
    """asks 0.10/0.50/0.90 at theta=0.06: mean(BE_i) < break_even(mean_ask),
    gap pinned numerically (Jensen's inequality on the concave fee term)."""
    asks = (0.10, 0.50, 0.90)
    rows = tuple(_row(ask, held=False) for ask in asks)
    stratum = build_stratum_v2("pooled", rows)
    assert stratum is not None

    mean_ask = sum(asks) / len(asks)
    break_even_of_mean_ask = _break_even(mean_ask)
    mean_be_i = float(stratum.pi)

    assert mean_be_i < break_even_of_mean_ask
    gap = break_even_of_mean_ask - mean_be_i
    assert gap == pytest.approx(0.0064, abs=1e-4)


def test_cell_dead_is_false_at_n_59() -> None:
    # All held (k=n), asks near 0.5 so pi (mean BE) sits comfortably below
    # the Wilson upper bound at low n.
    rows = tuple(_row(0.30, held=True, station="MIA") for _ in range(59))
    stratum = build_stratum_v2("station:MIA", rows)
    assert stratum is not None
    assert stratum.n == 59
    assert stratum.cell_dead is False


def test_cell_dead_is_true_at_n_60_when_wilson_upper_is_below_pi() -> None:
    # All NOT held (k=0): wilson_upper is small (few observed successes),
    # while pi = mean(BE_i) at ask=0.30 is well above it.
    rows = tuple(_row(0.30, held=False, station="MIA") for _ in range(60))
    stratum = build_stratum_v2("station:MIA", rows)
    assert stratum is not None
    assert stratum.n == 60
    assert stratum.wilson_upper < float(stratum.pi)
    assert stratum.cell_dead is True


def test_cell_dead_false_below_60_even_with_the_same_all_dead_shape() -> None:
    rows = tuple(_row(0.30, held=False, station="MIA") for _ in range(59))
    stratum = build_stratum_v2("station:MIA", rows)
    assert stratum is not None
    assert stratum.n == 59
    assert stratum.cell_dead is False


def test_inlined_wilson_matches_archive_correction_probe_on_200_random_pairs(
    archive_correction_probe: ModuleType,
) -> None:
    rng = random.Random(20260904)
    for _ in range(200):
        n = rng.randint(1, 500)
        k = rng.randint(0, n)
        rows = tuple(_row(0.30, held=(i < k), station="MIA") for i in range(n))
        stratum = build_stratum_v2("station:MIA", rows)
        assert stratum is not None
        expected_lower, expected_upper = archive_correction_probe.wilson_interval(k, n)
        assert stratum.wilson_lower == pytest.approx(expected_lower, abs=1e-12)
        assert stratum.wilson_upper == pytest.approx(expected_upper, abs=1e-12)


def test_stratum_v2_is_a_frozen_kw_only_dataclass() -> None:
    stratum = StratumV2(
        label="pooled",
        n=1,
        k=1,
        mean_ask=Decimal("0.3"),
        pi=Decimal("0.31"),
        wilson_lower=0.1,
        wilson_upper=0.9,
    )
    with pytest.raises(Exception):  # noqa: B017 -- frozen dataclass raises FrozenInstanceError
        stratum.n = 2  # type: ignore[misc]
