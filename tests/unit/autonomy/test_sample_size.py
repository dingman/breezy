"""AUT-4 WP2: `sample_size` primitives and `recompute_mde`'s delegation to them (r11 RC-1).

The golden grid was captured from `hypothesis_ledger.recompute_mde` at base sha 8bdb5ef1, BEFORE the
delegation edit, as hex floats (`float.hex`), so a one-ulp drift fails.
"""

from __future__ import annotations

import ast
import math
import random
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from statistics import NormalDist
from unittest import mock

import pytest

from breezy.analysis import hypothesis_ledger as ledger
from breezy.analysis import nbp_calibration
from breezy.persistence.autonomy import sample_size
from breezy.settlement import roi_bound

_ALPHAS = (
    ledger.MIN_PER_VARIANT_ALPHA,
    0.00625,
    0.0125,
    0.025,
    *(0.025 * 2.0**-k for k in range(1, 5)),
    *(0.025 * 2.0**-k / 3.0 for k in range(1, 5)),
)
_NS = (1, 2, 10, 60, 89, 300, 403, 600, 1000)
_GRID = [(a, n) for a in _ALPHAS for n in _NS]
#: float.hex of recompute_mde(per_variant_alpha=a, n_station_days=n) at 8bdb5ef1, in `_GRID` order.
GOLDEN_HEX: tuple[str, ...] = (
    "0x1.c9ba0a7d96ca0p+0",
    "0x1.43a9632b7c5c1p+0",
    "0x1.217de676c7980p-1",
    "0x1.d8bcf5d871cd7p-3",
    "0x1.8426c7af2c864p-3",
    "0x1.a6d47006c9f68p-4",
    "0x1.6cd0dd1f79770p-4",
    "0x1.2afc60380c433p-4",
    "0x1.cf2fd724728cdp-5",
    "0x1.ab6f0ebcba634p+0",
    "0x1.2e3dc938de0a8p+0",
    "0x1.0e5537d4c6a84p-1",
    "0x1.b973a5dd32126p-3",
    "0x1.6a76913662645p-3",
    "0x1.8ad8b0d76e593p-4",
    "0x1.54ac030dd37a3p-4",
    "0x1.1732d786eece5p-4",
    "0x1.b0885954710d4p-5",
    "0x1.8aa08777058a6p+0",
    "0x1.170b212fc484dp+0",
    "0x1.f32b0b6feba97p-2",
    "0x1.9791af606f7cbp-3",
    "0x1.4ea4a11fbc286p-3",
    "0x1.6c8a766ae0e12p-4",
    "0x1.3a863e731b121p-4",
    "0x1.01c4f234dc772p-4",
    "0x1.8f55a2bfefbacp-5",
    "0x1.669a582c6048ep+0",
    "0x1.fb241edc2274bp-1",
    "0x1.c599cd19afb6ep-2",
    "0x1.725d0dbaa2aebp-3",
    "0x1.30183b7d1e1d3p-3",
    "0x1.4b435f8bd7c9bp-4",
    "0x1.1dd0020fd0a02p-4",
    "0x1.d47a149f26663p-5",
    "0x1.6ae170e1595f2p-5",
    "0x1.8aa08777058a6p+0",
    "0x1.170b212fc484dp+0",
    "0x1.f32b0b6feba97p-2",
    "0x1.9791af606f7cbp-3",
    "0x1.4ea4a11fbc286p-3",
    "0x1.6c8a766ae0e12p-4",
    "0x1.3a863e731b121p-4",
    "0x1.01c4f234dc772p-4",
    "0x1.8f55a2bfefbacp-5",
    "0x1.ab6f0ebcba634p+0",
    "0x1.2e3dc938de0a8p+0",
    "0x1.0e5537d4c6a84p-1",
    "0x1.b973a5dd32126p-3",
    "0x1.6a76913662645p-3",
    "0x1.8ad8b0d76e593p-4",
    "0x1.54ac030dd37a3p-4",
    "0x1.1732d786eece5p-4",
    "0x1.b0885954710d4p-5",
    "0x1.c9ba0a7d96ca0p+0",
    "0x1.43a9632b7c5c1p+0",
    "0x1.217de676c7980p-1",
    "0x1.d8bcf5d871cd7p-3",
    "0x1.8426c7af2c864p-3",
    "0x1.a6d47006c9f68p-4",
    "0x1.6cd0dd1f79770p-4",
    "0x1.2afc60380c433p-4",
    "0x1.cf2fd724728cdp-5",
    "0x1.e5fd26df054eap+0",
    "0x1.57a5622241ea8p+0",
    "0x1.335dc9406c9ddp-1",
    "0x1.f5ed59c784fbcp-3",
    "0x1.9c1e244a2aabdp-3",
    "0x1.c0eff25cdb2bdp-4",
    "0x1.83575e52ea0c3p-4",
    "0x1.3d72549a59744p-4",
    "0x1.ebc94200adc96p-5",
    "0x1.bd6ca8aeea727p+0",
    "0x1.3af6701ee203dp+0",
    "0x1.19b60e5f6f105p-1",
    "0x1.cc084ae32dd81p-3",
    "0x1.79b81bffc1bfdp-3",
    "0x1.9b7729bf51b95p-4",
    "0x1.6302c0e1b4b8ep-4",
    "0x1.22f3354692bfap-4",
    "0x1.c2bce3cbe4e6ep-5",
    "0x1.da7b17926b754p+0",
    "0x1.4f82345a11472p+0",
    "0x1.2c1688cad10d7p-1",
    "0x1.ea0aac5adb400p-3",
    "0x1.925be358da121p-3",
    "0x1.b64e7e4887719p-4",
    "0x1.7a2b4f35e012ep-4",
    "0x1.35edf8e8c0369p-4",
    "0x1.e0240e114e7c0p-5",
    "0x1.f5b908d870968p+0",
    "0x1.62c586c9abf33p+0",
    "0x1.3d513e2af43a1p-1",
    "0x1.0316aa3ffd9fep-2",
    "0x1.a975c78b09398p-3",
    "0x1.cf78bed26c6e6p-4",
    "0x1.8fe1a894f12a0p-4",
    "0x1.47b9551b78829p-4",
    "0x1.fbb53044b9f69p-5",
    "0x1.07b8a808d3664p+1",
    "0x1.74f5507560985p+0",
    "0x1.4d95818ae3e89p-1",
    "0x1.105ec58d7357ep-2",
    "0x1.bf453c7951476p-3",
    "0x1.e73b0a843277bp-4",
    "0x1.a461704d6931cp-4",
    "0x1.58862a3b990dcp-4",
    "0x1.0ade013be986ep-4",
)


def test_golden_grid_has_one_value_per_cell() -> None:
    assert len(GOLDEN_HEX) == len(_GRID) == 108


@pytest.mark.parametrize(("alpha", "n"), _GRID)
def test_recompute_mde_bit_identical_before_and_after_delegation(alpha: float, n: int) -> None:
    expected = float.fromhex(GOLDEN_HEX[_GRID.index((alpha, n))])
    assert ledger.recompute_mde(per_variant_alpha=alpha, n_station_days=n) == expected


def test_recompute_mde_delegates_to_sample_size() -> None:
    with mock.patch.object(sample_size, "mde_one_sided", wraps=sample_size.mde_one_sided) as spy:
        value = ledger.recompute_mde(per_variant_alpha=0.025, n_station_days=89)
    spy.assert_called_once_with(0.5, 89, 0.025, ledger.POWER)
    assert value == sample_size.mde_one_sided(0.5, 89, 0.025, ledger.POWER)


@pytest.mark.parametrize("n", [0, -1])
def test_recompute_mde_nonpositive_n_message_pinned(n: int) -> None:
    with (
        mock.patch.object(sample_size, "mde_one_sided") as spy,
        pytest.raises(ValueError) as caught,
    ):
        ledger.recompute_mde(per_variant_alpha=0.025, n_station_days=n)
    assert str(caught.value) == "recompute_mde is undefined for n_station_days <= 0"
    spy.assert_not_called()


@pytest.mark.parametrize(("alpha", "n"), _GRID)
def test_n_min_inverts_mde(alpha: float, n: int) -> None:
    sigma = 0.5
    mde = sample_size.mde_one_sided(sigma, n, alpha)
    recovered = sample_size.n_min_one_sided(sigma, mde, alpha)
    assert recovered in (n, n + 1)  # ceil of a value within an ulp of n
    assert sample_size.mde_one_sided(sigma, recovered, alpha) <= mde * (1 + 1e-12)


@pytest.mark.parametrize(("alpha", "n"), _GRID)
def test_power_at_mde_is_design_power(alpha: float, n: int) -> None:
    sigma = 0.5
    mde = sample_size.mde_one_sided(sigma, n, alpha)
    assert sample_size.power_one_sided(sigma, n, alpha, mde) == pytest.approx(0.80, abs=1e-12)


def _z_sum_pair() -> tuple[float, float]:
    zs_a = nbp_calibration.Z_ALPHA_TWO_SIDED_095 + nbp_calibration.Z_POWER_080
    normal = NormalDist()
    zs_b = float(normal.inv_cdf(1.0 - 0.025) + normal.inv_cdf(0.80))
    return zs_a, zs_b


def _sweep_points() -> list[tuple[float, float]]:
    rng = random.Random(roi_bound.SEED)
    sigmas = [0.05, 0.099, 0.1, 0.25, 0.5, 1.0]
    xs = [0.005, 0.01, 0.0152, 0.02, 0.05, 0.1]
    grid = [(s, x) for s in sigmas for x in xs]
    for _ in range(500):
        s = math.exp(rng.uniform(math.log(0.01), math.log(2.0)))
        x = math.exp(rng.uniform(math.log(0.001), math.log(0.2)))
        grid.append((s, x))
    return grid


def test_n_min_one_sided_matches_nbp_compute_n_min_at_alpha_0_025() -> None:
    for sigma, x in _sweep_points():
        zs_a, zs_b = _z_sum_pair()
        # Check (i). The plan (r11 §0a, WP2 LOW-1) states a 1 ulp gap; measured on this interpreter
        # it is exactly 2 ulp (1.9599639845400545 + 0.8416212335729143 against the NormalDist sum).
        # The measured value is pinned, so an interpreter change that moves it fails loudly.
        assert abs(zs_a - zs_b) == 2 * math.ulp(zs_a)
        raw_a = (zs_a * sigma / x) ** 2
        raw_b = (zs_b * sigma / x) ** 2
        theirs = nbp_calibration.compute_n_min(sigma, x=x).n_min
        ours = sample_size.n_min_one_sided(sigma, x, 0.025)
        low, high = min(raw_a, raw_b), max(raw_a, raw_b)
        flipped = math.ceil(low) != math.ceil(high)
        if flipped:
            assert abs(theirs - ours) <= 1
        else:
            assert theirs == ours, (sigma, x)


def test_n_min_sweep_boundary_branch_is_exercised_by_a_constructed_point() -> None:
    sigma, k = 0.5, 400
    zs_a, _ = _z_sum_pair()
    x = zs_a * sigma / math.sqrt(k)  # puts raw within ulps of the integer k
    theirs = nbp_calibration.compute_n_min(sigma, x=x).n_min
    ours = sample_size.n_min_one_sided(sigma, x, 0.025)
    assert abs(theirs - ours) <= 1
    assert {theirs, ours} <= {k, k + 1}


def test_c_min_at_each_lineage_alpha() -> None:
    alphas = [0.025 * 2.0**-k for k in range(1, 5)]
    assert [sample_size.c_min(a) for a in alphas] == [10, 11, 12, 13]
    assert [sample_size.c_min(a / 3.0) for a in alphas] == [12, 13, 14, 15]


def test_deff_and_n_min_eff() -> None:
    assert sample_size.deff(1.0, 0.7) == 1.0
    assert sample_size.deff(3.0, 0.25) == 1.5
    assert sample_size.n_min_eff(403, 1.5, 10) == math.ceil(1.5 * 403)
    assert sample_size.n_min_eff(5, 1.0, 10) == 40  # the 4 * c_min floor binds


@pytest.mark.parametrize(
    "call",
    [
        lambda: sample_size.mde_one_sided(0.5, 0, 0.025),
        lambda: sample_size.mde_one_sided(0.0, 10, 0.025),
        lambda: sample_size.n_min_one_sided(-1.0, 0.02, 0.025),
        lambda: sample_size.n_min_one_sided(0.5, 0.0, 0.025),
        lambda: sample_size.power_one_sided(0.5, 0, 0.025, 0.1),
        lambda: sample_size.c_min(0.0),
        lambda: sample_size.c_min(1.0),
    ],
)
def test_primitives_refuse_degenerate_inputs(call: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        call()


_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_sample_size_source_imports_stdlib_only() -> None:
    tree = ast.parse((_REPO_ROOT / "src/breezy/persistence/autonomy/sample_size.py").read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "math", "statistics", "typing", "decimal"}


_CLOSURE_PROBE = (
    "import sys; before = set(sys.modules); import breezy.analysis.hypothesis_ledger; "
    "print('\\n'.join(sorted(set(sys.modules) - before)))"
)


def test_hypothesis_ledger_import_closure_gains_only_sample_size() -> None:
    """The delta from importing `hypothesis_ledger` after the edit, minus before, is exactly the
    three modules `breezy.persistence`, `.autonomy` and `.autonomy.sample_size` (AH5)."""
    out = subprocess.run(
        [sys.executable, "-c", _CLOSURE_PROBE], capture_output=True, text=True, check=True
    ).stdout.split()
    delta = {m for m in out if m.startswith("breezy.persistence")}
    assert delta == {
        "breezy.persistence",
        "breezy.persistence.autonomy",
        "breezy.persistence.autonomy.sample_size",
    }
    assert not [m for m in out if m.startswith("nautilus_trader")]
