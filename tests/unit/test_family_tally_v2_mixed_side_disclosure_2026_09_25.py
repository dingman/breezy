"""AUD-07 amendment Stage M1b DoD (iv) (plan §4 M1b bullet 4 / §5 test 9):
the disclosure line for the L-40-amended mixed-side validity caveat --
delivered in a LATER commit than the M1b `run_sequential_looks` extraction
(`tests/unit/test_family_tally_v2_look_loop_golden.py`, byte-unchanged).

The caveat (`docs/core/LESSONS.md` L-40 amendment, 2026-09-25): the qty=1
variance ceiling `Var_H0 <= 1/4` was derived and measured for SAME-SIDE
station-days only; a mixed YES+NO station-day's `Var_H0 = S - (q_y-q_n)^2`
can reach 1.0, and the live LD-OBF boundary's validity on mixed-side
station-days is UNCONFIRMED pending the M2 ruling
(`docs/plans/backlog/AUDIT_2026-09-21/AUD-07-AMENDMENT-2026-09-25.md`).

Ambiguity note: the amendment text does not pin an exact wording for the
disclosure line, so per the coordinating brief the MORE-disclosing reading
is taken -- the line fires whenever the admitted population contains ANY
mixed-side station-day (not only on a branch-V/M2-cleared family), and
always reports both facts test 9 names: the mixed-side station-day count
and whether the terminal look reached the information ceiling BELOW
`n_max` (the circumstance under which the same-side-sized boundary is most
exposed to the higher mixed-side variance).
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
    """Mirrors `test_family_tally_v2_look_loop_golden.py::_load_module` --
    the script carries no package `__init__`."""
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
    """One mixed-side station-day: distinct rungs, one YES one NO -- same
    shape as `test_family_tally_v2_look_loop_golden.py::_mixed_pair`."""
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


def test_disclosure_absent_and_mixed_day_count_zero_on_an_all_yes_family(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """No mixed-side station-day in the admitted population -- the caveat
    does not apply, and the disclosure line must not appear (it would be
    noise on every all-one-side family, forever, if unconditional)."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = tuple(_row(i, ask="0.30") for i in range(10))

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)

    assert tally.mixed_day_count == 0
    assert tally.i_max_terminal_below_n_max is False
    report = tally_mod.render_markdown_v2(tally, source_paths=(), as_of="2026-09-25")
    assert "mixed_day_count" not in report
    assert "mixed-side disclosure" not in report


def test_disclosure_present_when_family_admits_a_mixed_side_station_day(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """At least one mixed-side station-day is admitted -- the L-40 amended
    caveat applies and the disclosure line is live in the rendered report
    (DoD iv), independent of whether this look terminated."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = (*_mixed_pair(0, ask="0.20"), *tuple(_row(i, ask="0.30") for i in range(1, 9)))

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)

    assert tally.mixed_day_count == 1
    report = tally_mod.render_markdown_v2(tally, source_paths=(), as_of="2026-09-25")
    assert "mixed_day_count=1" in report
    assert "UNCONFIRMED pending the M2 ruling" in report


def test_the_tally_report_discloses_mixed_day_count_and_i_max_terminal_below_n_max(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """Plan §5 test 9, verbatim scenario from the golden test's
    `test_i_max_terminal_look_on_a_mixed_side_station_day` (never edited
    here): one mixed YES+NO station-day at equal asks crosses `i_max=0.5`
    on the first look while `n_max=100` is nowhere close -- the exact
    circumstance the caveat is about. Both facts the amendment names are
    disclosed together."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=0.5, n_max=100, look_step=1)
    rows = _mixed_pair(0, ask="0.50")

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)

    assert tally.mixed_day_count == 1
    assert tally.i_max_terminal_below_n_max is True
    report = tally_mod.render_markdown_v2(tally, source_paths=(), as_of="2026-09-25")
    assert "mixed_day_count=1" in report
    assert "i_max_terminal_below_n_max=True" in report
