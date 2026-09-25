"""AUD-07 amendment Stage M1b (L-33 characterisation, plan §4 M1b / tests
1-2 first bullet): golden `LookRecord`/verdict/`bca_line` OBJECTS for
`build_family_tally_v2`'s pooled sequential look loop, captured BEFORE
`run_sequential_looks` is extracted.

Six scenarios (plan §4 M1b bullet 1): I_max terminal on a mixed-side row,
LOSS_STOP, forced truncation on-grid, the off-grid truncation tail
(`family_tally_v2.py:784-819`), structural KILL
(`family_tally_v2.py:706-708`), and a plain CONTINUE run. Comparison is on
the returned dataclass OBJECTS (`LookRecord.state`, `.b_eff`, `.b_fut`,
`.verdict`, `.terminal`, `.reason`), never on rendered report bytes.

Rows are passed directly to `build_family_tally_v2` as synthetic
`ScoredTrial` tuples with no `store_dir` -- the same fixture shape every
other `family_tally_v2` driver-level test in this suite uses
(`test_family_tally_v2.py`, `test_family_tally_v2_truncation.py`,
`test_station_day_mixed_side_2026_09_14.py`). L-42 (a test of a
store-READING gate must write its fixture through the real writer) does not
apply here: none of these six scenarios passes `store_dir`, so no durable
sidecar/fill-order state is ever read.

After the extraction lands, this file is re-run unchanged (byte-identical
assertions) as the regression net; mutation evidence (removing
`reached_i_max` / removing the off-grid tail from
`run_sequential_looks`) is recorded verbatim in the refactor commit
message, not in this file.
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
    """Mirrors `test_family_tally_v2.py::_load_module` / `_load_family_tally_v2`
    elsewhere in this suite -- the script carries no package `__init__`."""
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
    *, i_max: float, n_max: int, look_step: int, alpha: float = 0.025
) -> BoundaryArtefact:
    """Byte-identical shape to every other driver-level test's synthetic
    artefact (`test_family_tally_v2.py::_synthetic_artefact`,
    `test_family_tally_v2_truncation.py::_synthetic_artefact`): never
    file-loaded, so `boundary_for` exercises the real solver without paying
    `load_boundary_artefact`'s reference-table replay."""
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
        "taker_fee_coefficient": "0.06",
        "boundary_artefact_path": "deploy/families/gs_boundary_pm_us_crh_v2.json",
        "boundary_inputs_sha256": "a" * 64,
        "composition_kind": "current_rung_hold",
        "density_artefact_path": "deploy/families/artefacts/not_applicable_density.json",
        "density_artefact_sha256": (
            "247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65"
        ),
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
    climate_day: str | None = None,
    ask: str = "0.50",
    held: bool = True,
    instrument_id: str | None = None,
    trial_suffix: str = "",
) -> ScoredTrial:
    """One row. One DISTINCT station-day by default (`n` drives
    `climate_day`), same convention as
    `test_family_tally_v2_truncation.py::_row`."""
    if climate_day is None:
        climate_day = f"2026-09-{11 + n:02d}"
    ask_d = Decimal(ask)
    fee = _fee(ask_d)
    pnl = (Decimal(1) if held else Decimal(0)) - ask_d - fee
    return ScoredTrial(
        trial_id=f"{_PM_PREFIX}{station}/{climate_day}/{n}{trial_suffix}",
        station=station,
        climate_day=climate_day,
        instrument_id=instrument_id or f"instrument-{n}",
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
        fill_px=ask_d,
        fee=fee,
    )


def _mixed_pair(
    n: int, *, station: str = "MIA", ask: str = "0.50", yes_held: bool = True, no_held: bool = False
) -> tuple[ScoredTrial, ScoredTrial]:
    """One mixed-side station-day: a YES leg on rung `rungA<n>` and a NO leg
    on the DISTINCT rung `rungB<n>^no`. Distinct base rungs are required --
    a same-rung YES/NO pair is refused by `combine_station_day` as a
    same-instrument-day hedge (`_SameRungOppositeSidesRefusal`); this is
    two mutually-exclusive rungs on one station-day instead (the
    L-40-amended mixed-side case), exactly the shape `leg_of_symbol`/
    `base_symbol_of` (`src/breezy/domain/instrument_leg.py`) derive side/
    rung from."""
    climate_day = f"2026-09-{11 + n:02d}"
    yes_row = _row(
        n,
        station=station,
        climate_day=climate_day,
        ask=ask,
        held=yes_held,
        instrument_id=f"rungA{n}",
        trial_suffix="-y",
    )
    no_row = _row(
        n,
        station=station,
        climate_day=climate_day,
        ask=ask,
        held=no_held,
        instrument_id=f"rungB{n}^no",
        trial_suffix="-n",
    )
    return (yes_row, no_row)


def test_i_max_terminal_look_on_a_mixed_side_station_day(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """A single mixed YES+NO station-day at equal asks reaches
    `Var_H0 ~= 1.0` (L-40 amendment (i): the qty-1 ceiling `S(1-S) <= 1/4`
    is same-side-only) -- `i_max=0.5` is crossed on the FIRST scheduled
    look (`look_step=1`), terminal, reason `I_MAX`."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=0.5, n_max=100, look_step=1)
    rows = _mixed_pair(0, ask="0.50")

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)

    assert tally.pooled_side_mix == " (mixed-side: Y1/N1)"
    assert len(tally.looks) == 1
    look = tally.looks[0]
    assert look.look_n == 1
    assert look.terminal is True
    assert look.reason is tally_mod.TruncationReason.I_MAX
    assert look.n_max_reached_below_i_max is False
    assert look.state.n == 1
    assert look.state.s == pytest.approx(-0.03001350911933979, rel=1e-9)
    assert look.state.information == pytest.approx(0.9991, rel=1e-9)
    assert look.b_eff == pytest.approx(1.959991010906111, rel=1e-9)
    assert look.b_fut == pytest.approx(-1.9599910109061363, rel=1e-9)
    assert look.verdict == "KILL"
    assert tally.verdict == "KILL"
    assert tally.total_pnl == Decimal("-0.030000")
    assert tally.bca_line is not None


def test_loss_stop_terminal_look(tmp_path: Path, tally_mod: ModuleType) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.90", held=False) for i in range(70))

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)

    assert len(tally.looks) == 1
    look = tally.looks[0]
    assert look.look_n == 10
    assert look.terminal is True
    assert look.reason is tally_mod.TruncationReason.LOSS_STOP
    assert look.n_max_reached_below_i_max is False
    assert look.state.n == 10
    assert look.state.s == pytest.approx(-9.783059094328774, rel=1e-9)
    assert look.state.information == pytest.approx(0.8565084000000002, rel=1e-9)
    assert look.b_eff == pytest.approx(1.9764805847255287, rel=1e-9)
    assert look.b_fut == pytest.approx(-1.9764805847255258, rel=1e-9)
    assert look.verdict == "KILL"
    assert tally.verdict == "KILL"
    assert tally.total_pnl == Decimal("-63.378000")
    assert tally.bca_line is not None


def test_forced_truncation_lands_exactly_on_a_scheduled_look(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """`forced = truncation is not None and look_n == n` (rev b SS4):
    truncation is requested but neither LOSS_STOP nor I_MAX nor n_max would
    naturally fire -- the scheduled look at `look_n == n == look_step`
    still terminates, ON-GRID (never the off-grid tail branch)."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=1000, look_step=10)
    rows = tuple(_row(i, ask="0.30", held=(i % 2 == 0)) for i in range(10))

    tally = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=artefact, truncation=tally_mod.TruncationReason.D0_165
    )

    assert len(tally.looks) == 1
    look = tally.looks[0]
    assert look.look_n == 10
    assert look.terminal is True
    assert look.reason is tally_mod.TruncationReason.D0_165
    assert look.n_max_reached_below_i_max is False
    assert look.state.n == 10
    assert look.state.s == pytest.approx(1.2784105200862668, rel=1e-9)
    assert look.state.information == pytest.approx(2.1488124, rel=1e-9)
    assert look.b_eff == pytest.approx(1.9650351247932778, rel=1e-9)
    assert look.b_fut == pytest.approx(-1.9650351247932747, rel=1e-9)
    # Interior score (b_fut < S < b_eff) at truncation is fail-closed to KILL.
    assert look.verdict == "KILL"
    assert tally.verdict == "KILL"
    assert tally.total_pnl == Decimal("1.874000")
    assert tally.bca_line is not None


def test_off_grid_truncation_tail(tmp_path: Path, tally_mod: ModuleType) -> None:
    """`family_tally_v2.py:784-819`: `n=7 < look_step=10` -- the main loop's
    `scheduled_ns` is empty (`range(10, 8, 10)`), so the ONLY look is the
    off-grid tail appended after the loop, at `look_n == n` (never
    `look_step`)."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.10", held=(i % 3 == 0)) for i in range(7))

    tally = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=artefact, truncation=tally_mod.TruncationReason.D0_165
    )

    assert len(tally.looks) == 1
    look = tally.looks[0]
    assert look.look_n == 7
    assert look.terminal is True
    assert look.reason is tally_mod.TruncationReason.D0_165
    assert look.state.n == 7
    assert look.state.s == pytest.approx(2.784500022189772, rel=1e-9)
    assert look.state.information == pytest.approx(0.66003588, rel=1e-9)
    assert look.b_eff == pytest.approx(1.9820115595059, rel=1e-9)
    assert look.b_fut == pytest.approx(-1.9820115595058987, rel=1e-9)
    assert look.verdict == "SURVIVE"
    assert tally.verdict == "SURVIVE"
    assert tally.total_pnl == Decimal("2.262200")
    assert tally.bca_line is not None


def test_structural_kill_short_circuits_the_look_loop(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """`family_tally_v2.py:706-708`: `structural_fired and registered` sets
    `verdict = "KILL"` and `scheduled_ns = range(0)` unconditionally --
    ZERO looks, no BCa line, regardless of `combined_draws`."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)

    tally = tally_mod.build_family_tally_v2(
        (),
        manifest=manifest,
        artefact=artefact,
        covered_listed_station_days=15,
        filled_takes=0,
    )

    assert tally.looks == ()
    assert tally.verdict == "KILL"
    assert tally.structural_dead is not None
    assert tally.structural_dead.structural_dead is True
    assert tally.bca_line is None


def test_plain_continue_below_look_step_produces_no_looks(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.30") for i in range(3))

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)

    assert tally.looks == ()
    assert tally.verdict == "CONTINUE"
    assert tally.bca_line is None
    assert tally.total_pnl == Decimal("2.062200")
