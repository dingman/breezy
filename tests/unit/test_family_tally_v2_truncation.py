"""RED-first suite: `family_tally_v2.build_family_tally_v2` truncation dispatch.

Covers the driver-level auto-detection of `I_MAX`/`n_max`-reached/
`LOSS_STOP`, plus the explicit `--truncate` off-grid override -- distinct
from `tests/unit/test_current_rung_hold_v2_truncation.py`, which is the
PURE `terminal_look()` function's own RED-first suite (already landed).

Uses synthetic, directly-constructed `BoundaryArtefact` objects (never the
real 160/40 pin) so a real, `score()`-derived, Bernoulli-variance-bounded
`I_k <= 0.25*n` can actually cross a small `i_max` with a handful of rows
-- see `test_family_tally_v2.py::_synthetic_artefact`'s docstring for why
`I_MAX` can never fire before `n=160` under the real pin.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.persistence.gs_boundary_artefact import BoundaryArtefact, SpendingSpec
from breezy.settlement.trial_scorer import ScoredTrial

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_FEE_THETA = Decimal("0.06")
_PM_PREFIX = "current_rung_hold/trial/"
_D0 = "2026-09-10"


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "family_tally_v2.py"
    spec = importlib.util.spec_from_file_location("family_tally_v2", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tally_mod() -> ModuleType:
    return _load_module()


def _synthetic_artefact(
    *, i_max: float = 40.0, n_max: int = 160, look_step: int = 10, alpha: float = 0.025
) -> BoundaryArtefact:
    return BoundaryArtefact(
        inputs_sha256="0" * 64,
        i_max=i_max,
        alpha_one_sided=alpha,
        spending=SpendingSpec(
            spending_id="test_synthetic", alpha_one_sided=alpha, n_max=n_max, look_step=look_step
        ),
        reference_rows=(),
    )


def _manifest(tmp_path: Path, **overrides: Any) -> FamilyManifest:
    payload: dict[str, Any] = {
        "family_id": "pm_us_crh_v2_test",
        "venue": "polymarket_us",
        "trial_id_prefix": _PM_PREFIX,
        "d0_climate_day": _D0,
        "boundary_artefact_path": "deploy/families/gs_boundary_pm_us_crh_v2.json",
        "boundary_inputs_sha256": "a" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
        "status": "REGISTERED",
    }
    payload.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload))
    return load_family_manifest(path, allow_draft=True)


def _fee(ask: Decimal) -> Decimal:
    return _FEE_THETA * ask * (1 - ask)


def _row(
    n: int,
    *,
    station: str = "MIA",
    climate_day: str = "2026-09-11",
    ask: str = "0.50",
    held: bool = True,
) -> ScoredTrial:
    ask_d = Decimal(ask)
    fee = _fee(ask_d)
    fill_px = ask_d
    pnl = (Decimal(1) if held else Decimal(0)) - fill_px - fee
    return ScoredTrial(
        trial_id=f"{_PM_PREFIX}{station}/{climate_day}/{n}",
        station=station,
        climate_day=climate_day,
        instrument_id=f"instrument-{n}",
        settlement_tmax_f=80,
        held=held,
        pnl=pnl,
        revision_seq=0,
        raw_sha256="deadbeef",
        scored_at_ns=1,
        score_seq=0,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=ask_d,
        fill_px=fill_px,
        fee=fee,
    )


def test_i_max_fires_before_n_max_when_information_crosses_the_pinned_ceiling(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    # ask=0.50 -> BE close to 0.5 -> near-maximal per-row information
    # (BE*(1-BE) -> its cap of 0.25). i_max=1.0 crosses well before
    # n_max=20 at look_step=10 (10 rows * ~0.235 info/row ~= 2.35 >> 1.0).
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1.0, n_max=20, look_step=10)
    rows = tuple(_row(i, ask="0.50", held=(i % 2 == 0)) for i in range(10))
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    assert tally.looks, "expected at least one completed look"
    last = tally.looks[-1]
    assert last.terminal is True
    assert last.reason is tally_mod.TruncationReason.I_MAX
    assert last.state.information >= artefact.i_max
    assert tally.verdict in ("SURVIVE", "KILL")
    assert tally.bca_line is not None


def test_n_max_reached_with_information_below_i_max_is_also_reported_i_max(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    # Small n_max=10 (one look) reached at look_step=10 with a real i_max=40
    # never crossed by n=10 low-information rows (ask=0.10 -> tiny BE*(1-BE)).
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=40.0, n_max=10, look_step=10)
    rows = tuple(_row(i, ask="0.10", held=(i % 5 == 0)) for i in range(10))
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    last = tally.looks[-1]
    assert last.terminal is True
    assert last.state.information < artefact.i_max
    # documented decision: no dedicated enum member for "n_max reached, I<i_max"
    assert last.reason is tally_mod.TruncationReason.I_MAX
    assert last.look_n == 10


def test_loss_stop_fires_unconditionally_kill_even_with_a_survive_shaped_score(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    # All 10 rows lose (held=False): total pnl = -10 * (fill_px+fee) which
    # at ask=0.9 is well past the -60 loss-stop floor is NOT reached by 10
    # rows alone at ask=0.9 (~-9.5) -- use a bigger loss per row via a high
    # ask and enough rows to cross -60 exactly at the scheduled look.
    rows = tuple(_row(i, ask="0.90", held=False) for i in range(70))
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    assert tally.total_pnl <= tally_mod.LOSS_STOP_PNL
    last = tally.looks[-1]
    assert last.reason is tally_mod.TruncationReason.LOSS_STOP
    assert last.verdict == "KILL"
    assert tally.verdict == "KILL"


def test_an_explicit_truncate_flag_forces_an_off_grid_terminal_look(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    # off-grid: n=7 < look_step
    rows = tuple(_row(i, ask="0.10", held=(i % 3 == 0)) for i in range(7))
    tally = tally_mod.build_family_tally_v2(
        rows,
        manifest=manifest,
        artefact=artefact,
        truncation=tally_mod.TruncationReason.D0_165,
    )
    assert tally.looks, "an explicit truncate must produce a terminal look even off-grid"
    last = tally.looks[-1]
    assert last.terminal is True
    assert last.look_n == 7
    assert last.reason is tally_mod.TruncationReason.D0_165
    assert tally.verdict in ("SURVIVE", "KILL")
    assert tally.bca_line is not None


def test_d0_165_at_truncation_can_be_either_survive_or_kill_not_kill_only(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """rev b SS4: D0+165 admits BOTH KILL and SURVIVE -- never KILL-only.
    Demonstrated by constructing two fixtures that land on either side of
    the (near-single-look) terminal boundary."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)

    # A strong, consistent edge (always held at a cheap ask) should SURVIVE.
    winning_rows = tuple(_row(i, ask="0.10", held=True) for i in range(10))
    winning = tally_mod.build_family_tally_v2(
        winning_rows,
        manifest=manifest,
        artefact=artefact,
        truncation=tally_mod.TruncationReason.D0_165,
    )
    assert winning.looks[-1].verdict == "SURVIVE"
    assert winning.verdict == "SURVIVE"

    # Consistent losses should KILL.
    losing_rows = tuple(_row(i, ask="0.10", held=False) for i in range(10))
    losing = tally_mod.build_family_tally_v2(
        losing_rows,
        manifest=manifest,
        artefact=artefact,
        truncation=tally_mod.TruncationReason.D0_165,
    )
    assert losing.looks[-1].verdict == "KILL"
    assert losing.verdict == "KILL"


def test_terminal_look_never_returns_continue(tmp_path: Path, tally_mod: ModuleType) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.30", held=(i % 2 == 0)) for i in range(10))
    tally = tally_mod.build_family_tally_v2(
        rows,
        manifest=manifest,
        artefact=artefact,
        truncation=tally_mod.TruncationReason.LOSS_STOP,
    )
    assert tally.looks[-1].verdict in ("SURVIVE", "KILL")


def test_no_truncation_and_below_look_step_yields_no_looks_and_no_bca(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.30") for i in range(3))
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    assert tally.looks == ()
    assert tally.bca_line is None
    assert tally.verdict == "CONTINUE"
