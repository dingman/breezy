"""AUD-05 D-A: side-aware strata against the registered NO-side amendment.

`combine_station_day` is NOT what D-A changes. The unequal-qty variance
tests below characterise that already-registered formula (amendment §3)
and must stay green on an empty diff of `combine_station_day`. D-A's RED
tests exercise `build_stratum_v2` and the tally report.

BLOCKER-3 is ruled option (a): NO rows enter station and ask-band strata
unpartitioned at pi = mean(BE_i). The interim PENDING_STRATA_RULING
sentinel is not part of the landed behaviour
(`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`).
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
from breezy.settlement.current_rung_hold_v2 import (
    StationDayAdmissionRefusal,
    StratumRow,
    StratumV2,
    build_stratum_v2,
    combine_station_day,
    score,
)
from breezy.settlement.trial_scorer import ScoredTrial

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_ALL_YES_GOLDEN = (
    _REPO_ROOT / "tests" / "fixtures" / "aud05_all_yes_tally_report.txt"
).read_text(encoding="utf-8")
_PREFIX = "continuous_rung_hold/trial/"
_FEE_THETA = Decimal("0.06")
_HEADER = "| stratum | n | k | mean ask | mean BE (pi) | Wilson-lower | Wilson-upper | |"
_DIVIDER = "|---|---:|---:|---:|---:|---:|---:|---|"
_FOOTNOTE_MARK = "mean ask is a per-leg average in each leg's OWN price domain"


def _load_tally() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "family_tally_v2.py"
    spec = importlib.util.spec_from_file_location("family_tally_v2_aud05", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tally_mod() -> ModuleType:
    return _load_tally()


def _artefact() -> BoundaryArtefact:
    return BoundaryArtefact(
        inputs_sha256="0" * 64,
        i_max=40.0,
        alpha_one_sided=0.025,
        spending=SpendingSpec(
            spending_id="test_synthetic",
            alpha_one_sided=0.025,
            n_max=160,
            look_step=100,
        ),
        reference_rows=(),
    )


def _manifest(tmp_path: Path) -> FamilyManifest:
    payload = {
        "family_id": "pm_us_crh_v2_test",
        "venue": "polymarket_us",
        "trial_id_prefix": _PREFIX,
        "d0_climate_day": "2026-09-10",
        "taker_fee_coefficient": "0.06",
        "boundary_artefact_path": "deploy/families/gs_boundary_pm_us_crh_v2.json",
        "boundary_inputs_sha256": (
            "471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c"
        ),
        "composition_kind": "current_rung_hold",
        "density_artefact_path": "deploy/families/artefacts/not_applicable_density.json",
        "density_artefact_sha256": (
            "247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65"
        ),
        "stations": ["LAX", "MDW", "MIA", "SFO"],
        "status": "REGISTERED",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload))
    return load_family_manifest(path, allow_draft=True)


def _row(
    n: int,
    *,
    station: str,
    climate_day: str,
    ask: str,
    held: bool,
    no_leg: bool,
    fee: str | None = None,
) -> ScoredTrial:
    ask_d = Decimal(ask)
    fee_d = Decimal(fee) if fee is not None else _FEE_THETA * ask_d * (1 - ask_d)
    pnl = (Decimal(1) if held else Decimal(0)) - ask_d - fee_d
    instrument = f"bucket-{n}^no.POLYMARKET_US" if no_leg else f"bucket-{n}.POLYMARKET_US"
    return ScoredTrial(
        trial_id=f"{_PREFIX}{station}/{climate_day}/{n}",
        station=station,
        climate_day=climate_day,
        instrument_id=instrument,
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
        fee=fee_d,
    )


def _render(tally_mod: ModuleType, tally: Any) -> str:
    return tally_mod.render_markdown_v2(
        tally, source_paths=(Path("/tmp/scored.parquet"),), as_of="2026-09-24"
    )


def test_a_no_leg_row_is_scored_not_refused() -> None:
    row = StratumRow(
        entry_ask=Decimal("0.40"),
        fee=Decimal(0),
        held=True,
        station="MIA",
        side="no",
        rung="rung-no",
    )
    stratum = build_stratum_v2("pooled", (row,))
    assert stratum is not None
    assert stratum.n == 1
    assert stratum.k == 1
    assert stratum.pi == Decimal("0.40")


def test_a_no_only_stratum_uses_the_legs_own_break_even_not_its_reflection() -> None:
    rows = tuple(
        StratumRow(
            entry_ask=Decimal("0.40"),
            fee=Decimal(0),
            held=False,
            station="MIA",
            side="no",
            rung=f"rung-{i}",
        )
        for i in range(3)
    )
    stratum = build_stratum_v2("pooled", rows)
    assert stratum is not None
    assert stratum.pi == Decimal("0.40")
    assert stratum.pi != Decimal("0.60")
    assert stratum.cell_dead == (
        stratum.n >= 60 and stratum.wilson_upper < float(stratum.pi)
    )


def test_a_mixed_side_pooled_stratum_scores_each_leg_against_its_own_break_even() -> None:
    rows = (
        StratumRow(
            entry_ask=Decimal("0.30"),
            fee=Decimal(0),
            held=True,
            station="MIA",
            side="yes",
            rung="yes-rung",
        ),
        StratumRow(
            entry_ask=Decimal("0.70"),
            fee=Decimal(0),
            held=False,
            station="MIA",
            side="no",
            rung="no-rung",
        ),
    )
    stratum = build_stratum_v2("pooled", rows)
    assert stratum is not None
    assert stratum.n == 2
    assert stratum.k == 1
    assert stratum.pi == Decimal("0.50")


def test_a_row_with_an_unknown_side_still_raises() -> None:
    with pytest.raises(ValueError, match="side must be 'yes' or 'no'"):
        StratumRow(
            entry_ask=Decimal("0.30"),
            fee=Decimal(0),
            held=True,
            station="MIA",
            side="maybe",  # type: ignore[arg-type]
        )


def test_score_stays_side_blind() -> None:
    row = StratumRow(
        entry_ask=Decimal("0.30"),
        fee=Decimal(0),
        held=True,
        station="MIA",
        side="no",
        rung="rung-no",
    )
    with pytest.raises(ValueError, match=r"score\(\) is side-blind"):
        score((row,))


def test_no_stratum_label_carries_a_side_suffix(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    rows = (
        _row(0, station="MIA", climate_day="2026-09-11", ask="0.10", held=True, no_leg=False),
        _row(1, station="MIA", climate_day="2026-09-12", ask="0.10", held=False, no_leg=True),
    )
    manifest = _manifest(tmp_path)
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=_artefact())
    labels = [tally.pooled.label] if tally.pooled is not None else []
    labels.extend(s.label for s in (*tally.station_strata, *tally.ask_band_strata))
    for label in labels:
        assert "|no" not in label
        assert "|yes" not in label


def test_a_mixed_station_stratum_scores_no_rows_unpartitioned_against_mean_be(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    rows = (
        _row(
            0, station="MIA", climate_day="2026-09-11", ask="0.30", held=True,
            no_leg=False, fee="0",
        ),
        _row(
            1, station="MIA", climate_day="2026-09-12", ask="0.70", held=True,
            no_leg=True, fee="0",
        ),
    )
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=_manifest(tmp_path), artefact=_artefact()
    )
    station = next(s for s in tally.station_strata if s.label == "station:MIA")
    assert station.n == 2
    assert station.k == 2
    assert station.pi == Decimal("0.50")
    assert "|no" not in station.label


def test_a_no_bearing_corpus_produces_a_registered_verdict_not_the_pending_sentinel(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    rows = (
        _row(0, station="MIA", climate_day="2026-09-11", ask="0.10", held=False, no_leg=True),
    )
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=_manifest(tmp_path), artefact=_artefact()
    )
    assert tally.station_strata
    assert tally.ask_band_strata
    assert tally.verdict in {"SURVIVE", "KILL", "CONTINUE"}
    assert tally.verdict != "PENDING_STRATA_RULING"
    assert "PENDING_STRATA_RULING" not in _render(tally_mod, tally)
    assert tally.n_scored == 1
    assert tally.pooled is not None


def test_a_mixed_side_pooled_row_renders_the_side_mix_label_on_mean_ask(
    tally_mod: ModuleType,
) -> None:
    stratum = StratumV2(
        label="pooled",
        n=12,
        k=7,
        mean_ask=Decimal("0.3125"),
        pi=Decimal("0.3400"),
        wilson_lower=0.1,
        wilson_upper=0.9,
    )
    line = tally_mod._fmt_stratum_row(stratum, side_mix=" (mixed-side: Y9/N3)")
    assert "0.3125 (mixed-side: Y9/N3)" in line
    assert tally_mod.STRATUM_TABLE_HEADER == _HEADER
    assert tally_mod.STRATUM_TABLE_DIVIDER == _DIVIDER


def test_a_no_only_stratum_renders_the_no_only_label_on_mean_ask(
    tally_mod: ModuleType,
) -> None:
    stratum = StratumV2(
        label="pooled",
        n=1,
        k=0,
        mean_ask=Decimal("0.4000"),
        pi=Decimal("0.4000"),
        wilson_lower=0.0,
        wilson_upper=0.8,
    )
    line = tally_mod._fmt_stratum_row(stratum, side_mix=" (NO-only)")
    assert "0.4000 (NO-only)" in line


def test_the_side_mix_label_reaches_the_rendered_report_end_to_end(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    stations = ("LAX", "MDW", "MIA", "SFO")
    rows = tuple(
        _row(
            i,
            station=stations[i % 4],
            climate_day=f"2026-09-{11 + i:02d}",
            ask="0.10",
            held=True,
            no_leg=i >= 9,
        )
        for i in range(12)
    )
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=_manifest(tmp_path), artefact=_artefact()
    )
    report = _render(tally_mod, tally)
    assert tally.pooled_side_mix == " (mixed-side: Y9/N3)"
    assert " (mixed-side: Y9/N3)" in report
    assert report.count(_FOOTNOTE_MARK) == 1


def test_an_all_yes_corpus_renders_no_side_mix_label_and_no_footnote(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    stations = ("LAX", "MDW", "MIA", "SFO")
    rows = tuple(
        _row(
            i,
            station=stations[i % 4],
            climate_day=f"2026-09-{11 + i:02d}",
            ask="0.10",
            held=True,
            no_leg=False,
        )
        for i in range(4)
    )
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=_manifest(tmp_path), artefact=_artefact()
    )
    report = _render(tally_mod, tally)
    assert "mixed-side" not in report
    assert "NO-only" not in report
    assert _FOOTNOTE_MARK not in report
    assert tally_mod.STRATUM_TABLE_HEADER == _HEADER
    assert tally_mod.STRATUM_TABLE_DIVIDER == _DIVIDER


def test_an_all_yes_corpus_renders_a_byte_identical_report(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    stations = ("LAX", "MDW", "MIA", "SFO")
    rows = tuple(
        _row(
            i,
            station=stations[i % 4],
            climate_day=f"2026-09-{11 + i:02d}",
            ask="0.10",
            held=True,
            no_leg=False,
        )
        for i in range(4)
    )
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=_manifest(tmp_path), artefact=_artefact()
    )
    assert _render(tally_mod, tally) == _ALL_YES_GOLDEN


def test_a_mixed_station_stratum_renders_the_side_mix_label(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    rows = (
        _row(0, station="MIA", climate_day="2026-09-11", ask="0.10", held=True, no_leg=False),
        _row(1, station="MIA", climate_day="2026-09-12", ask="0.10", held=False, no_leg=True),
    )
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=_manifest(tmp_path), artefact=_artefact()
    )
    report = _render(tally_mod, tally)
    station_lines = [line for line in report.splitlines() if line.startswith("| station:")]
    ask_lines = [line for line in report.splitlines() if line.startswith("| ask:")]
    assert any(" (mixed-side: Y1/N1)" in line for line in station_lines)
    assert any(" (mixed-side: Y1/N1)" in line for line in ask_lines)
    assert tally.strata_side_mix
    assert " (mixed-side: Y1/N1)" in tally.strata_side_mix


def test_a_settled_only_count_still_raises(tmp_path: Path, tally_mod: ModuleType) -> None:
    rows = tuple(
        _row(
            i,
            station=("LAX", "MDW")[i],
            climate_day=f"2026-09-{11 + i:02d}",
            ask="0.10",
            held=True,
            no_leg=False,
        )
        for i in range(2)
    )
    with pytest.raises(ValueError, match=r"filled_takes=1 is less than len\(rows\)=2"):
        tally_mod.build_family_tally_v2(
            rows, manifest=_manifest(tmp_path), artefact=_artefact(), filled_takes=1
        )


def test_combine_station_day_matches_the_registered_variance_formula_at_unequal_qty() -> None:
    """Characterisation of the registered formula. Not a D-A RED test."""
    yes = StratumRow(
        entry_ask=Decimal("0.30"),
        fee=Decimal(0),
        held=True,
        station="MIA",
        qty=Decimal(1),
        side="yes",
        rung="yes-rung",
    )
    no = StratumRow(
        entry_ask=Decimal("0.40"),
        fee=Decimal(0),
        held=False,
        station="MIA",
        qty=Decimal(3),
        side="no",
        rung="no-rung",
    )
    draw = combine_station_day((yes, no))
    q_yes, q_no = 0.30, 0.60
    diagonal = (1.0 ** 2) * q_yes * (1.0 - q_yes) + (3.0 ** 2) * q_no * (1.0 - q_no)
    # Amendment §3: YES/NO cross term is +2 q_i q_j, qty-weighted.
    cross = -2.0 * 1.0 * 3.0 * (1.0) * (-1.0) * q_yes * q_no
    assert diagonal == pytest.approx(2.37)
    assert cross == pytest.approx(1.08)
    assert cross > 0
    assert draw.variance == pytest.approx(diagonal + cross)


def test_a_station_day_breaching_the_sum_q_gate_is_refused() -> None:
    rows = (
        StratumRow(
            entry_ask=Decimal("0.60"), fee=Decimal(0), held=True, station="MIA", side="yes"
        ),
        StratumRow(
            entry_ask=Decimal("0.60"), fee=Decimal(0), held=False, station="MIA", side="yes"
        ),
    )
    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day(rows)
