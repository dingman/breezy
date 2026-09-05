"""RED-first suite for `scripts/analysis/family_tally_v2.py` (blueprint commit 7).

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b,
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` "Tests" -- covers the
independent-reviewer obligations (a)-(e), the draft/shadow gate, and the
"no venue: stratum" regression -- everything EXCEPT the truncation-only
tests, which live in `test_family_tally_v2_truncation.py`.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.persistence.gs_boundary_artefact import (
    BoundaryArtefact,
    SpendingSpec,
    load_boundary_artefact,
)
from breezy.settlement.trial_scorer import ScoredTrial

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_REAL_ARTEFACT_PATH = _REPO_ROOT / "deploy" / "families" / "gs_boundary_pm_us_crh_v2.json"
_REAL_ARTEFACT_SHA = "471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c"

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


@pytest.fixture(scope="module")
def real_artefact() -> BoundaryArtefact:
    return load_boundary_artefact(_REAL_ARTEFACT_PATH, expected_sha256=_REAL_ARTEFACT_SHA)


def _synthetic_artefact(
    *, i_max: float = 40.0, n_max: int = 160, look_step: int = 10, alpha: float = 0.025
) -> BoundaryArtefact:
    """A directly-constructed (never file-loaded) artefact for driver-level
    unit tests: `boundary_for`/`alpha_spent`/`remaining_alpha` never touch
    `reference_rows`, so this skips the expensive load-time replay while
    exercising the SAME solver `real_artefact` uses. Lets tests choose a
    small `i_max`/`n_max` so the (real, `score()`-derived, Bernoulli-
    variance-bounded) `I_k <= 0.25*n` ceiling can actually be crossed with
    a handful of rows -- with the real `i_max=40, n_max=160` pin, `I_MAX`
    can mathematically never fire before `n=160` (0.25*n < 40 for all
    n<160), so a driver-level `I_MAX`-before-`n_max` test needs a smaller
    `i_max` to be reachable at all.
    """
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
        "boundary_inputs_sha256": _REAL_ARTEFACT_SHA,
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
    ask: str = "0.10",
    held: bool = True,
    score_seq: int = 0,
    excluded_reason: str | None = None,
    prefix: str = _PM_PREFIX,
) -> ScoredTrial:
    ask_d = Decimal(ask)
    fee = _fee(ask_d)
    fill_px = ask_d
    pnl = (Decimal(1) if held else Decimal(0)) - fill_px - fee
    return ScoredTrial(
        trial_id=f"{prefix}{station}/{climate_day}/{n}",
        station=station,
        climate_day=climate_day,
        instrument_id=f"instrument-{n}",
        settlement_tmax_f=80,
        held=held,
        pnl=pnl,
        revision_seq=0,
        raw_sha256="deadbeef",
        scored_at_ns=1,
        score_seq=score_seq,
        settlement_basis="nws_final",
        excluded_reason=excluded_reason,
        slippage=Decimal(0),
        entry_ask=ask_d,
        fill_px=fill_px,
        fee=fee,
    )


def _rows(n: int, **kwargs: Any) -> tuple[ScoredTrial, ...]:
    return tuple(_row(i, **kwargs) for i in range(n))


# --- obligation (a): held/pnl-sign assertion --------------------------------


def test_held_pnl_sign_mismatch_is_refused(tmp_path: Path, tally_mod: ModuleType) -> None:
    good = _rows(9)
    bad = _row(9, held=True)
    # Corrupt pnl so it disagrees with held=True without going through
    # score_trial (simulating a scorer-level relabelling bug).
    bad = dataclasses.replace(bad, pnl=Decimal("-0.50"))
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError):
        tally_mod._assert_held_matches_pnl_sign((*good, bad))


def test_held_pnl_sign_consistent_rows_pass_non_vacuity(tally_mod: ModuleType) -> None:
    tally_mod._assert_held_matches_pnl_sign(_rows(9))  # no raise


# --- obligation (b): partial_or_multi_fill (dormant on real ScoredTrial) ---


def test_a_synthetic_qty_ne_1_row_is_refused(tally_mod: ModuleType) -> None:
    class _RowWithQty:
        trial_id = "x"
        qty = Decimal(2)

    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError):
        tally_mod._assert_no_partial_or_multi_fill([_RowWithQty()])


def test_a_synthetic_qty_eq_1_row_passes(tally_mod: ModuleType) -> None:
    class _RowWithQty:
        trial_id = "x"
        qty = Decimal(1)

    tally_mod._assert_no_partial_or_multi_fill([_RowWithQty()])  # no raise


def test_real_scored_trial_rows_have_no_qty_attribute_and_pass_dormant(
    tally_mod: ModuleType,
) -> None:
    rows = _rows(5)
    assert not hasattr(rows[0], "qty")
    tally_mod._assert_no_partial_or_multi_fill(rows)  # dormant, never refuses


# --- obligation (c): raw (trial_id, score_seq) collision scan --------------


def test_a_raw_score_seq_collision_across_two_files_is_refused(
    tmp_path: Path, tally_mod: ModuleType
) -> None:

    from breezy.persistence.scored_trial_store import write_scored_trials

    store_dir = tmp_path / "store"
    same_trial_id = f"{_PM_PREFIX}MIA/2026-09-11/collide"
    row_a = _row(0, climate_day="2026-09-11")
    row_a = dataclasses.replace(row_a, trial_id=same_trial_id, score_seq=0)
    row_b = _row(1, climate_day="2026-09-11")
    row_b = dataclasses.replace(row_b, trial_id=same_trial_id, score_seq=0)

    write_scored_trials(store_dir, (row_a,), now_ns=1)
    write_scored_trials(store_dir, (row_b,), now_ns=2)

    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError):
        tally_mod._assert_no_raw_score_seq_collisions(store_dir)


def test_distinct_score_seqs_for_the_same_trial_id_pass_non_vacuity(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    from breezy.persistence.scored_trial_store import write_scored_trials

    store_dir = tmp_path / "store"
    same_trial_id = f"{_PM_PREFIX}MIA/2026-09-11/rescored"
    row_a = _row(0, climate_day="2026-09-11")
    row_a = dataclasses.replace(row_a, trial_id=same_trial_id, score_seq=0)
    row_b = _row(1, climate_day="2026-09-11")
    row_b = dataclasses.replace(row_b, trial_id=same_trial_id, score_seq=1)

    write_scored_trials(store_dir, (row_a,), now_ns=1)
    write_scored_trials(store_dir, (row_b,), now_ns=2)

    tally_mod._assert_no_raw_score_seq_collisions(store_dir)  # no raise


def test_a_missing_store_dir_is_a_no_op_not_an_error(tmp_path: Path, tally_mod: ModuleType) -> None:
    tally_mod._assert_no_raw_score_seq_collisions(tmp_path / "does-not-exist")  # no raise


# --- obligation (d): BCa theta_hat printed ----------------------------------


def test_roi_bound_line_v2_includes_theta_hat_when_a_bound_is_computed(
    tally_mod: ModuleType,
) -> None:
    rows = tuple(_row(i, ask="0.10", held=(i % 3 != 0)) for i in range(40))
    line = tally_mod._roi_bound_line_v2(rows)
    assert "theta_hat" in line
    assert "BCa 95% lower bound on ROI" in line


def test_roi_bound_line_v2_omits_theta_hat_when_underpowered(tally_mod: ModuleType) -> None:
    rows = _rows(5)  # n < MIN_NON_EXCLUDED_N=30
    line = tally_mod._roi_bound_line_v2(rows)
    assert "theta_hat" not in line
    assert "UNDERPOWERED" in line


# --- family barrier integration, draft gate, no-venue-stratum --------------


def test_a_non_family_row_refuses_the_whole_tally(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    rows = (*_rows(5), _row(5, climate_day="2026-01-01"))  # before D0
    with pytest.raises(tally_mod.FamilyBarrierRefusal):
        tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)


def test_the_real_committed_pm_us_manifest_is_registered_and_correctly_pinned() -> None:
    """PREREG v2 registration (2026-09-05): `status` flipped to REGISTERED
    and `d0_climate_day` set to the registration day -- the manifest loads
    with NO `allow_draft` at all now (a caller that forgot the flag no
    longer matters for this family). `boundary_inputs_sha256` is unchanged
    and still matches the committed boundary artefact exactly."""
    real_manifest_path = _REPO_ROOT / "deploy" / "families" / "pm_us_crh_v2.json"
    manifest = load_family_manifest(real_manifest_path)  # no allow_draft
    assert manifest.status == "REGISTERED"
    assert manifest.d0_climate_day == "2026-09-05"
    assert manifest.boundary_inputs_sha256 == _REAL_ARTEFACT_SHA


def test_cli_renders_continue_verdict_vocabulary_for_the_real_registered_family_at_n_zero(
    tmp_path: Path, tally_mod: ModuleType, capsys: Any
) -> None:
    """R2/R3: the real, now-REGISTERED `pm_us_crh_v2` manifest against an
    empty store with no provenance sidecar yet renders n=0 CONTINUE verdict
    vocabulary -- never SHADOW (that gate is DRAFT-only) and never a
    ProvenanceRefusal (that refusal is reserved for a store WITH rows and
    no/mismatched sidecar, R2(b))."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    rc = tally_mod.main(["--family", "pm_us_crh_v2", "--store-dir", str(store_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "store empty; provenance sidecar not yet written" in out
    assert "**CONTINUE**" in out
    assert "SHADOW" not in out


def test_a_draft_manifest_renders_shadow_only_never_verdict_vocabulary(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path, status="DRAFT_NOT_REGISTERED", boundary_inputs_sha256="0" * 64)
    rows = _rows(5)
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-11")
    assert "SHADOW" in report
    assert "SURVIVE" not in report
    assert "KILL" not in report


def test_a_registered_manifest_with_zero_completed_looks_reports_continue(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    rows = _rows(5)  # fewer than look_step=10 -> zero completed looks
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)
    assert tally.verdict == "CONTINUE"
    assert tally.looks == ()
    assert tally.bca_line is None
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-11")
    assert "**CONTINUE**" in report


def test_no_stratum_label_starts_with_venue(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    rows = tuple(
        _row(i, station=("LAX" if i % 2 == 0 else "MIA"), ask=("0.10" if i % 2 else "0.50"))
        for i in range(6)
    )
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)
    labels = [
        s.label
        for s in (
            *((tally.pooled,) if tally.pooled else ()),
            *tally.station_strata,
            *tally.ask_band_strata,
        )
    ]
    assert labels, "expected at least one stratum to be built"
    assert all(not label.startswith("venue:") for label in labels)
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-11")
    assert "venue:" not in report


# --- BCa terminal-only (a CONTINUE look invokes no compute_roi_bound) ------


def test_bca_is_never_computed_while_the_look_stays_continue(
    tmp_path: Path,
    tally_mod: ModuleType,
    real_artefact: BoundaryArtefact,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    original = tally_mod.compute_roi_bound

    def _counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(tally_mod, "compute_roi_bound", _counting)

    manifest = _manifest(tmp_path)
    # n=10 -> exactly one completed look at t_k=0.0625, boundary b_eff~7.8 --
    # unreachable by any real S, so the look is CONTINUE (non-terminal).
    rows = _rows(10, ask="0.10")
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)
    assert tally.verdict == "CONTINUE"
    assert tally.looks[-1].terminal is False
    assert calls == []
    assert tally.bca_line is None


# --- CLI: --family is required (argparse exits 2) ---------------------------


def test_family_flag_is_required_argparse_exits_2(tally_mod: ModuleType) -> None:
    with pytest.raises(SystemExit) as exc_info:
        tally_mod.main(["--store-dir", "/tmp/does-not-matter"])
    assert exc_info.value.code == 2


def test_unknown_family_id_exits_2_loudly(tmp_path: Path, tally_mod: ModuleType) -> None:
    rc = tally_mod.main(["--family", "not_a_real_family_xyz", "--store-dir", str(tmp_path)])
    assert rc == 2


# --- B1: v2-only live-provenance barrier (ruling Q4) -------------------------


def test_assert_live_provenance_refuses_a_missing_sidecar(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    with pytest.raises(tally_mod.ProvenanceRefusal):
        tally_mod._assert_live_provenance(store_dir)


def test_assert_live_provenance_refuses_paper_replay(tmp_path: Path, tally_mod: ModuleType) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "paper_replay"}))
    with pytest.raises(tally_mod.ProvenanceRefusal):
        tally_mod._assert_live_provenance(store_dir)


def test_assert_live_provenance_admits_live_non_vacuity(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    tally_mod._assert_live_provenance(store_dir)  # no raise


def test_cli_refuses_a_populated_store_with_a_missing_provenance_sidecar(
    tmp_path: Path, tally_mod: ModuleType, capsys: Any
) -> None:
    """R2(b): the "no sidecar" exception applies ONLY to an empty store
    (n=0, see `test_cli_renders_continue_verdict_vocabulary_for_the_real_
    registered_family_at_n_zero` above) -- a store that already has scored
    rows but no sidecar still refuses fail-closed."""
    from breezy.persistence.scored_trial_store import write_scored_trials

    store_dir = tmp_path / "store"
    write_scored_trials(store_dir, _rows(1, prefix=_PM_PREFIX, climate_day="2026-09-10"), now_ns=1)
    rc = tally_mod.main(["--family", "pm_us_crh_v2", "--store-dir", str(store_dir)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "provenance" in err


def test_cli_refuses_a_paper_replay_sidecar_with_a_labelled_reason(
    tmp_path: Path, tally_mod: ModuleType, capsys: Any
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "paper_replay"}))
    rc = tally_mod.main(["--family", "pm_us_crh_v2", "--store-dir", str(store_dir)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "paper_replay" in err


def test_cli_admits_a_live_provenance_sidecar(tmp_path: Path, tally_mod: ModuleType) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    rc = tally_mod.main(["--family", "pm_us_crh_v2", "--store-dir", str(store_dir)])
    assert rc == 0


# --- R2(b): four store-empty x sidecar-present combinations ----------------
#
# (rows=0, sidecar missing)  -> n=0, NOT refused, report notes the empty store
# (rows=0, sidecar valid)    -> normal pass, no empty-store note
# (rows>0, sidecar missing)  -> still refuses (ProvenanceRefusal)
# (rows>0, sidecar mismatched) -> still refuses (ProvenanceRefusal)


def test_r2_empty_rows_and_missing_sidecar_is_n_zero_not_refused(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    tally = tally_mod.build_family_tally_v2(
        (), manifest=manifest, artefact=real_artefact, store_dir=store_dir
    )
    assert tally.n_scored == 0
    assert tally.store_empty_no_sidecar is True
    report = tally_mod.render_markdown_v2(tally, source_paths=(store_dir,), as_of="2026-09-11")
    assert "store empty; provenance sidecar not yet written" in report
    assert "**CONTINUE**" in report


def test_r2_empty_rows_and_a_valid_live_sidecar_is_the_normal_pass(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    tally = tally_mod.build_family_tally_v2(
        (), manifest=manifest, artefact=real_artefact, store_dir=store_dir
    )
    assert tally.n_scored == 0
    assert tally.store_empty_no_sidecar is False
    report = tally_mod.render_markdown_v2(tally, source_paths=(store_dir,), as_of="2026-09-11")
    assert "store empty; provenance sidecar not yet written" not in report


def test_r2_rows_present_and_missing_sidecar_still_refuses(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    rows = _rows(5)
    with pytest.raises(tally_mod.ProvenanceRefusal):
        tally_mod.build_family_tally_v2(
            rows, manifest=manifest, artefact=real_artefact, store_dir=store_dir
        )


def test_r2_rows_present_and_a_mismatched_sidecar_still_refuses(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "paper_replay"}))
    rows = _rows(5)
    with pytest.raises(tally_mod.ProvenanceRefusal):
        tally_mod.build_family_tally_v2(
            rows, manifest=manifest, artefact=real_artefact, store_dir=store_dir
        )


# --- R1: obligation (e) states all three barriers, provenance sidecar, and
# the fill-order sidecar -------------------------------------------------


def test_obligation_e_report_line_states_all_three_barriers_and_sidecars(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    manifest = _manifest(tmp_path)
    rows = _rows(5)
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-11")
    assert "trial_id prefix" in report
    assert "d0_climate_day" in report
    assert "station census" in report
    assert "provenance.json" in report
    assert "score_live_trials.py" in report
    assert "fill_order.jsonl" in report


# --- B3: fill-time look ordering (v2-only, active when store_dir is given) --


def test_ordered_for_looks_without_store_dir_uses_the_climate_day_proxy(
    tally_mod: ModuleType,
) -> None:
    row_later = _row(0, station="MIA", climate_day="2026-09-12")
    row_earlier = _row(1, station="LAX", climate_day="2026-09-11")
    ordered = tally_mod._ordered_for_looks((row_later, row_earlier))
    assert [r.trial_id for r in ordered] == [row_earlier.trial_id, row_later.trial_id]


def test_ordered_for_looks_with_store_dir_orders_by_fill_time_not_station(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    # row_a sorts FIRST by the (climate_day, trial_id) proxy (station LAX <
    # SFO) but fills LATER -- proves fill-time, not station text, drives it.
    row_a = _row(0, station="LAX", climate_day="2026-09-11")
    row_b = _row(1, station="SFO", climate_day="2026-09-11")

    proxy_ordered = tally_mod._ordered_for_looks((row_a, row_b))
    assert [r.trial_id for r in proxy_ordered] == [row_a.trial_id, row_b.trial_id]

    fill_order = store_dir / "fill_order.jsonl"
    fill_order.write_text(
        "\n".join(
            json.dumps(entry)
            for entry in (
                {"trial_id": row_a.trial_id, "score_seq": row_a.score_seq, "filled_at_ns": 200},
                {"trial_id": row_b.trial_id, "score_seq": row_b.score_seq, "filled_at_ns": 100},
            )
        )
        + "\n"
    )
    ordered = tally_mod._ordered_for_looks((row_a, row_b), store_dir=store_dir)
    assert [r.trial_id for r in ordered] == [row_b.trial_id, row_a.trial_id]


def test_ordered_for_looks_with_store_dir_refuses_a_missing_sidecar_entry(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    row = _row(0, station="LAX")
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match=row.trial_id):
        tally_mod._ordered_for_looks((row,), store_dir=store_dir)
