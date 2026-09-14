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

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.persistence.gs_boundary_artefact import (
    BoundaryArtefact,
    SpendingSpec,
    load_boundary_artefact,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.settlement.current_rung_hold_v2 import score
from breezy.settlement.trial_scorer import ScoredTrial
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_REAL_ARTEFACT_PATH = _REPO_ROOT / "deploy" / "families" / "gs_boundary_pm_us_crh_v2.json"
_REAL_ARTEFACT_SHA = "471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c"
# pm_us_crh_cont (registered 2026-09-11) REUSES the v2 boundary artefact
# verbatim -- same file, same sha -- so the cont manifest is covered by the
# identical consistency check below, never a second artefact.
_CONT_MANIFEST_PATH = _REPO_ROOT / "deploy" / "families" / "pm_us_crh_cont.json"
_CONT_ARTEFACT_SHA = _REAL_ARTEFACT_SHA

_FEE_THETA = Decimal("0.06")
_PM_PREFIX = "current_rung_hold/trial/"
_D0 = "2026-09-10"
_PM_STRUCTURAL_D0 = "2026-09-05"


def _pm_structural_cli_args(tmp_path: Path) -> list[str]:
    """Controlled structural args so pm_us_crh_v2 CLI tests reach provenance.

    ``fill_source`` is a missing sqlite so ``count_filled_takes`` returns
    None (fail-closed, never zero) and the stop is not evaluated. Covered
    listed is 0 -- below the fire threshold even if a count were present.
    """
    fill_source = tmp_path / "controlled_fill_source.sqlite"
    return [
        "--covered-listed-station-days",
        "0",
        "--fill-source",
        str(fill_source),
        "--fill-since-climate-day",
        _PM_STRUCTURAL_D0,
    ]


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
    """`n` rows, one per DISTINCT station-day by default (operator ruling
    2026-09-14 / plan S4a R3-3): `build_family_tally_v2` now combines every
    row sharing `(station, climate_day)` into one station-day draw, so a
    caller that wants `n` genuinely independent draws (the overwhelming
    majority of this file's fixtures, pre-dating S4a) must not collide them
    all onto the SAME day the way the old single-climate_day default did.
    A caller that explicitly passes `climate_day=` (deliberately testing a
    same-day collision) is left byte-identical to before this re-pin.
    """
    if "climate_day" in kwargs:
        return tuple(_row(i, **kwargs) for i in range(n))
    return tuple(_row(i, climate_day=f"2026-09-{11 + i:02d}", **kwargs) for i in range(n))


# --- obligation (a): held/pnl-sign assertion --------------------------------


def test_v3_row_does_not_refuse_v2_tally_batch(
    tmp_path: Path,
    tally_mod: ModuleType,
    real_artefact: BoundaryArtefact,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Prefix-filter before assert_family_only: v2 rows tally; drops are loud."""
    v2_rows = _rows(2, prefix=_PM_PREFIX)
    v3_row = _row(99, prefix="continuous_rung_hold/trial/")
    mixed = (*v2_rows, v3_row)
    manifest = _manifest(tmp_path)
    with caplog.at_level("WARNING"):
        kept = tally_mod.filter_rows_to_manifest_prefix(
            mixed, manifest, store_declared_single_family=False,
        )
    assert kept == v2_rows
    assert "dropped 1 non-manifest row" in caplog.text
    assert "continuous_rung_hold/trial/" in caplog.text
    tally = tally_mod.build_family_tally_v2(
        kept, manifest=manifest, artefact=real_artefact,
    )
    assert tally.n_scored == 2
    with pytest.raises(tally_mod.FamilyStoreContaminationError) as excinfo:
        tally_mod.build_family_tally_v2(
            mixed, manifest=manifest, artefact=real_artefact,
        )
    assert "1 non-manifest" in str(excinfo.value)


def test_malformed_v3_row_never_reaches_the_integrity_guards_still_raises_contamination(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    """Order fix: the prefix filter must run BEFORE
    `_assert_held_matches_pnl_sign`. A v3 row that violates the held/pnl-sign
    guard must never be scored -- it must be dropped by the filter first, so
    the whole tally still refuses with `FamilyStoreContaminationError` (the
    correct diagnosis: contamination, not a v2 data-integrity failure) rather
    than a bare `ScoredTrialDataIntegrityError` from the guard tripping on a
    foreign row it should never have seen."""
    v2_rows = _rows(2, prefix=_PM_PREFIX)
    malformed_v3_row = dataclasses.replace(
        _row(99, prefix="continuous_rung_hold/trial/"), pnl=Decimal("-0.50")
    )
    mixed = (*v2_rows, malformed_v3_row)
    manifest = _manifest(tmp_path)
    with pytest.raises(tally_mod.FamilyStoreContaminationError) as excinfo:
        tally_mod.build_family_tally_v2(mixed, manifest=manifest, artefact=real_artefact)
    assert "1 non-manifest" in str(excinfo.value)


def test_a_well_formed_v3_parquet_sharing_the_store_dir_does_not_alter_the_v2_tally(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    """Obligation (c)'s raw-store collision scan must be prefix-aware: a
    `(trial_id, score_seq)` collision entirely within a foreign (v3)
    parquet file, sharing the same `--store-dir` as v2 (the reviewer-noted
    default: score_live_trials.py:131's single scorer dir), must not abort
    v2's tally, and v2's `n_scored`/verdict must be identical to a store
    holding only the v2 rows."""
    from breezy.persistence.scored_trial_store import read_scored_trials, write_scored_trials

    manifest = _manifest(tmp_path)
    v2_rows = _rows(5, prefix=_PM_PREFIX)

    def _fill_order_lines(rows: tuple[ScoredTrial, ...]) -> str:
        return "\n".join(
            json.dumps({"trial_id": r.trial_id, "score_seq": r.score_seq, "filled_at_ns": i})
            for i, r in enumerate(rows)
        )

    clean_store = tmp_path / "clean_store"
    write_scored_trials(clean_store, v2_rows, now_ns=1)
    (clean_store / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    (clean_store / "fill_order.jsonl").write_text(_fill_order_lines(v2_rows))
    baseline = tally_mod.build_family_tally_v2(
        tally_mod.filter_rows_to_manifest_prefix(
            read_scored_trials(clean_store), manifest, store_declared_single_family=False
        ),
        manifest=manifest,
        artefact=real_artefact,
        store_dir=clean_store,
    )

    mixed_store = tmp_path / "mixed_store"
    write_scored_trials(mixed_store, v2_rows, now_ns=1)
    (mixed_store / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    (mixed_store / "fill_order.jsonl").write_text(_fill_order_lines(v2_rows))
    same_v3_trial_id = "continuous_rung_hold/trial/MIA/2026-09-11/collide"
    v3_row_a = dataclasses.replace(
        _row(0, prefix="continuous_rung_hold/trial/"), trial_id=same_v3_trial_id, score_seq=0
    )
    v3_row_b = dataclasses.replace(
        _row(1, prefix="continuous_rung_hold/trial/"), trial_id=same_v3_trial_id, score_seq=0
    )
    write_scored_trials(mixed_store, (v3_row_a,), now_ns=2)
    write_scored_trials(mixed_store, (v3_row_b,), now_ns=3)

    kept_v2_rows = tally_mod.filter_rows_to_manifest_prefix(
        read_scored_trials(mixed_store), manifest, store_declared_single_family=False
    )
    assert kept_v2_rows == v2_rows
    tally = tally_mod.build_family_tally_v2(
        kept_v2_rows, manifest=manifest, artefact=real_artefact, store_dir=mixed_store,
    )
    assert tally.n_scored == baseline.n_scored
    assert tally.verdict == baseline.verdict
    assert tally.looks == baseline.looks


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


def test_the_real_committed_cont_manifest_is_registered_and_correctly_pinned() -> None:
    """PREREG v3 registration (2026-09-11): `pm_us_crh_cont` flips to
    REGISTERED with D0 = 2026-09-12 (first UTC day strictly after the
    registration commit). It REUSES v2's boundary artefact verbatim --
    same identical sequential design (LD-OBF, alpha=0.025, n_max=160,
    i_max=40, look_step=10) -- so `boundary_inputs_sha256` matches the
    SAME committed artefact `pm_us_crh_v2` pins, by the same consistency
    check."""
    manifest = load_family_manifest(_CONT_MANIFEST_PATH)  # no allow_draft
    assert manifest.status == "REGISTERED"
    assert manifest.d0_climate_day == "2026-09-12"
    assert manifest.boundary_artefact_path == _REAL_ARTEFACT_PATH.relative_to(_REPO_ROOT)
    assert manifest.boundary_inputs_sha256 == _CONT_ARTEFACT_SHA


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
    rc = tally_mod.main(
        [
            "--family",
            "pm_us_crh_v2",
            "--store-dir",
            str(store_dir),
            *_pm_structural_cli_args(tmp_path),
        ]
    )
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
    # Distinct climate_day per row (operator ruling 2026-09-14 / plan S4a
    # R3-3): build_family_tally_v2 now combines same-station-day rows into
    # one draw, so 6 independent draws need 6 distinct station-days.
    rows = tuple(
        _row(
            i,
            station=("LAX" if i % 2 == 0 else "MIA"),
            ask=("0.10" if i % 2 else "0.50"),
            climate_day=f"2026-09-{11 + i:02d}",
        )
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


# --- CLI: pm_us_crh_v2 three-arg / D0 fence (L-28) --------------------------


def test_pm_us_crh_v2_cli_refuses_omitted_structural_args(
    tmp_path: Path, tally_mod: ModuleType, capsys: Any
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    output = tmp_path / "report.md"
    rc = tally_mod.main(
        [
            "--family",
            "pm_us_crh_v2",
            "--store-dir",
            str(store_dir),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "CONTINUE" not in captured.out
    assert not output.exists()
    assert "covered-listed-station-days" in captured.err or "fill-source" in captured.err


def test_pm_us_crh_v2_cli_refuses_when_fill_since_climate_day_omitted(
    tmp_path: Path, tally_mod: ModuleType, capsys: Any
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    output = tmp_path / "report.md"
    fill_source = tmp_path / "controlled_fill_source.sqlite"
    rc = tally_mod.main(
        [
            "--family",
            "pm_us_crh_v2",
            "--store-dir",
            str(store_dir),
            "--output",
            str(output),
            "--covered-listed-station-days",
            "0",
            "--fill-source",
            str(fill_source),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "CONTINUE" not in captured.out
    assert not output.exists()
    assert "fill-since-climate-day" in captured.err


def test_pm_us_crh_v2_cli_refuses_drifted_fill_since_climate_day(
    tmp_path: Path, tally_mod: ModuleType, capsys: Any
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    output = tmp_path / "report.md"
    fill_source = tmp_path / "controlled_fill_source.sqlite"
    rc = tally_mod.main(
        [
            "--family",
            "pm_us_crh_v2",
            "--store-dir",
            str(store_dir),
            "--output",
            str(output),
            "--covered-listed-station-days",
            "0",
            "--fill-source",
            str(fill_source),
            "--fill-since-climate-day",
            "2026-08-30",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "CONTINUE" not in captured.out
    assert not output.exists()
    assert "2026-08-30" in captured.err
    assert "2026-09-05" in captured.err


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
    rc = tally_mod.main(
        [
            "--family",
            "pm_us_crh_v2",
            "--store-dir",
            str(store_dir),
            *_pm_structural_cli_args(tmp_path),
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "provenance" in err


def test_cli_refuses_a_paper_replay_sidecar_with_a_labelled_reason(
    tmp_path: Path, tally_mod: ModuleType, capsys: Any
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "paper_replay"}))
    rc = tally_mod.main(
        [
            "--family",
            "pm_us_crh_v2",
            "--store-dir",
            str(store_dir),
            *_pm_structural_cli_args(tmp_path),
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "paper_replay" in err


def test_cli_admits_a_live_provenance_sidecar(tmp_path: Path, tally_mod: ModuleType) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    rc = tally_mod.main(
        [
            "--family",
            "pm_us_crh_v2",
            "--store-dir",
            str(store_dir),
            *_pm_structural_cli_args(tmp_path),
        ]
    )
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


# --- I3c: v2 coverage table reads the excluded-fills artefact --------------
# `docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` 3.0(c)/(g)/(h), section
# "I3c -- v2 coverage table reads the excluded-fills artefact"; ruling
# `docs/evidence/grok_admission_exclusions_ack_2026-09-05.md` Q2/Q3.


def _excluded_fill_line(
    *,
    trial_id: str = "",
    station: str = "",
    climate_day: str = "",
    venue_order_id: str,
    qty: str = "1",
    reason: str,
    filled_at_ns: int = 1,
    scored_run_utc: str = "2026-09-05T14:15:00Z",
) -> str:
    return json.dumps(
        {
            "trial_id": trial_id,
            "station": station,
            "climate_day": climate_day,
            "venue_order_id": venue_order_id,
            "qty": qty,
            "reason": reason,
            "filled_at_ns": filled_at_ns,
            "scored_run_utc": scored_run_utc,
        }
    )


def test_read_excluded_fills_absent_artefact_is_empty_tuple(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    assert tally_mod.read_excluded_fills(store_dir) == ()


def test_render_reports_absent_artefact_line_when_no_excluded_fills_file(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    manifest = _manifest(tmp_path)
    rows = _rows(5)
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)
    report = tally_mod.render_markdown_v2(tally, source_paths=(store_dir,), as_of="2026-09-11")
    assert "no exclusions recorded (artefact absent)" in report


def test_a_seeded_artefact_renders_counts_by_reason_station_climate_day(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        "\n".join(
            (
                _excluded_fill_line(
                    trial_id=f"{_PM_PREFIX}MIA/2026-09-11/x",
                    station="MIA",
                    climate_day="2026-09-11",
                    venue_order_id="vo-1",
                    reason="fill_below_ask",
                ),
                _excluded_fill_line(
                    trial_id=f"{_PM_PREFIX}LAX/2026-09-12/y",
                    station="LAX",
                    climate_day="2026-09-12",
                    venue_order_id="vo-2",
                    reason="fee_unverified",
                ),
            )
        )
        + "\n"
    )
    manifest = _manifest(tmp_path)
    rows = _rows(5)
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=real_artefact)
    report = tally_mod.render_markdown_v2(tally, source_paths=(store_dir,), as_of="2026-09-11")
    assert "| fill_below_ask | MIA | 2026-09-11 | 1 |" in report
    assert "| fee_unverified | LAX | 2026-09-12 | 1 |" in report


def test_two_lines_for_one_venue_order_id_count_once_with_the_latest_reason(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        "\n".join(
            (
                _excluded_fill_line(
                    trial_id="t1",
                    station="MIA",
                    climate_day="2026-09-11",
                    venue_order_id="vo-1",
                    reason="fee_unverified",
                    scored_run_utc="2026-09-05T14:15:00Z",
                ),
                _excluded_fill_line(
                    trial_id="t1",
                    station="MIA",
                    climate_day="2026-09-11",
                    venue_order_id="vo-1",
                    reason="fill_below_ask",
                    scored_run_utc="2026-09-06T14:15:00Z",
                ),
            )
        )
        + "\n"
    )
    excluded = tally_mod.read_excluded_fills(store_dir)
    assert len(excluded) == 2
    rows = tally_mod.coverage_rows(excluded, frozenset())
    assert rows == (
        tally_mod.CoverageRow(
            reason="fill_below_ask", station="MIA", climate_day="2026-09-11", count=1
        ),
    )


def test_an_exclusion_whose_trial_id_has_a_scored_row_is_dropped(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    from breezy.persistence.scored_trial_store import read_scored_trials, write_scored_trials

    store_dir = tmp_path / "store"
    scored_row = _row(0, climate_day="2026-09-11")
    write_scored_trials(store_dir, (scored_row,), now_ns=1)
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id=scored_row.trial_id,
            station=scored_row.station,
            climate_day=scored_row.climate_day,
            venue_order_id="vo-1",
            reason="fee_unverified",
        )
        + "\n"
    )
    scored_ids = frozenset(t.trial_id for t in read_scored_trials(store_dir))
    excluded = tally_mod.read_excluded_fills(store_dir)
    rows = tally_mod.coverage_rows(excluded, scored_ids)
    assert rows == ()


def test_an_exclusion_whose_trial_id_is_not_scored_still_counts(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    from breezy.persistence.scored_trial_store import read_scored_trials, write_scored_trials

    store_dir = tmp_path / "store"
    scored_row = _row(0, climate_day="2026-09-11")
    write_scored_trials(store_dir, (scored_row,), now_ns=1)
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id="current_rung_hold/trial/MIA/2026-09-11/unscored",
            station="MIA",
            climate_day="2026-09-11",
            venue_order_id="vo-2",
            reason="fee_unverified",
        )
        + "\n"
    )
    scored_ids = frozenset(t.trial_id for t in read_scored_trials(store_dir))
    excluded = tally_mod.read_excluded_fills(store_dir)
    rows = tally_mod.coverage_rows(excluded, scored_ids)
    assert rows == (
        tally_mod.CoverageRow(
            reason="fee_unverified", station="MIA", climate_day="2026-09-11", count=1
        ),
    )


def test_a_malformed_excluded_fills_line_missing_keys_refuses_loudly(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text('{"trial_id": "t1"}\n')
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError):
        tally_mod.read_excluded_fills(store_dir)


def test_invalid_json_line_refuses_loudly(tmp_path: Path, tally_mod: ModuleType) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text("not-json\n")
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError):
        tally_mod.read_excluded_fills(store_dir)


def test_a_bad_scored_run_utc_format_refuses_loudly(tmp_path: Path, tally_mod: ModuleType) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            venue_order_id="vo-1", reason="fill_below_ask", scored_run_utc="2026-09-05"
        )
        + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError):
        tally_mod.read_excluded_fills(store_dir)


def test_a_non_decimal_qty_refuses_loudly(tmp_path: Path, tally_mod: ModuleType) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(venue_order_id="vo-1", reason="fill_below_ask", qty="not-a-number")
        + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError):
        tally_mod.read_excluded_fills(store_dir)


# --- BLOCK-3: identity-field validation (LIVE_FILL_SCORING_CHAIN 3.0(c), I2) -
# `venue_order_id` must be non-empty for every reason; `trial_id`/`station`/
# `climate_day` must be non-empty for every reason EXCEPT `no_taken_latch`,
# where all three may be `""` (no taken latch means no trial identity yet).


def test_a_blank_venue_order_id_refuses_loudly_for_an_ordinary_reason(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id="t1",
            station="MIA",
            climate_day="2026-09-11",
            venue_order_id="",
            reason="fee_unverified",
        )
        + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match="venue_order_id"):
        tally_mod.read_excluded_fills(store_dir)


def test_a_blank_venue_order_id_refuses_loudly_even_for_no_taken_latch(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(venue_order_id="", reason="no_taken_latch") + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match="venue_order_id"):
        tally_mod.read_excluded_fills(store_dir)


def test_a_blank_station_with_reason_fee_unverified_refuses_loudly(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id="t1",
            station="",
            climate_day="2026-09-11",
            venue_order_id="vo-1",
            reason="fee_unverified",
        )
        + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match="station"):
        tally_mod.read_excluded_fills(store_dir)


def test_a_blank_trial_id_with_reason_fill_below_ask_refuses_loudly(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id="",
            station="MIA",
            climate_day="2026-09-11",
            venue_order_id="vo-1",
            reason="fill_below_ask",
        )
        + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match="trial_id"):
        tally_mod.read_excluded_fills(store_dir)


def test_a_blank_climate_day_with_reason_duplicate_fill_for_latch_refuses_loudly(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id="t1",
            station="MIA",
            climate_day="",
            venue_order_id="vo-1",
            reason="duplicate_fill_for_latch",
        )
        + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match="climate_day"):
        tally_mod.read_excluded_fills(store_dir)


def test_no_taken_latch_accepts_blank_identity_fields_and_renders_them_blank(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(venue_order_id="vo-1", reason="no_taken_latch") + "\n"
    )
    excluded = tally_mod.read_excluded_fills(store_dir)
    assert len(excluded) == 1
    fill = excluded[0]
    assert fill.trial_id == ""
    assert fill.station == ""
    assert fill.climate_day == ""
    rows = tally_mod.coverage_rows(excluded, frozenset())
    assert rows == (
        tally_mod.CoverageRow(reason="no_taken_latch", station="", climate_day="", count=1),
    )


def test_a_non_iso_climate_day_refuses_loudly(tmp_path: Path, tally_mod: ModuleType) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id="t1",
            station="MIA",
            climate_day="09/11/2026",
            venue_order_id="vo-1",
            reason="fee_unverified",
        )
        + "\n"
    )
    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match="climate_day"):
        tally_mod.read_excluded_fills(store_dir)


def test_v2_statistics_are_byte_identical_with_and_without_excluded_fills_artefact(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    """dn = dk = dI = dS = 0 (strategy-lead ruling): the coverage table is
    reporting only -- every existing statistic in the report is unchanged
    whether or not the artefact exists."""
    manifest = _manifest(tmp_path)
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    rows = _rows(20)
    (store_dir / "fill_order.jsonl").write_text(
        "\n".join(
            json.dumps({"trial_id": row.trial_id, "score_seq": row.score_seq, "filled_at_ns": i})
            for i, row in enumerate(rows)
        )
        + "\n"
    )
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=real_artefact, store_dir=store_dir
    )
    marker = "Coverage -- admission exclusions"
    report_without = tally_mod.render_markdown_v2(
        tally, source_paths=(store_dir,), as_of="2026-09-11"
    )
    assert marker in report_without

    (store_dir / "excluded_fills.jsonl").write_text(
        _excluded_fill_line(
            trial_id="unrelated/trial",
            station="LAX",
            climate_day="2026-09-20",
            venue_order_id="vo-9",
            reason="fill_below_ask",
        )
        + "\n"
    )
    report_with = tally_mod.render_markdown_v2(tally, source_paths=(store_dir,), as_of="2026-09-11")

    stats_without = report_without.split(marker, 1)[0]
    stats_with = report_with.split(marker, 1)[0]
    assert stats_without == stats_with
    assert report_without != report_with


def test_all_widened_closed_set_reasons_render_verbatim(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """The closed set is owned by the scorer; the tally renders every
    reason string verbatim without validating membership."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    reasons = (
        "partial_fill",
        "multi_fill",
        "fill_below_ask",
        "fee_unverified",
        "duplicate_fill_for_latch",
        "no_taken_latch",
        "ambiguous_latch",
    )
    lines = []
    for i, reason in enumerate(reasons):
        if reason == "no_taken_latch":
            # empty trial_id/station/climate_day allowed for this reason
            # ONLY (spec 3.0); groups under a blank station, never dropped.
            lines.append(_excluded_fill_line(venue_order_id=f"vo-{i}", reason=reason))
        else:
            lines.append(
                _excluded_fill_line(
                    trial_id=f"t-{i}",
                    station="MIA",
                    climate_day="2026-09-11",
                    venue_order_id=f"vo-{i}",
                    reason=reason,
                )
            )
    (store_dir / "excluded_fills.jsonl").write_text("\n".join(lines) + "\n")

    excluded = tally_mod.read_excluded_fills(store_dir)
    rows = tally_mod.coverage_rows(excluded, frozenset())
    rendered_reasons = {row.reason for row in rows}
    assert rendered_reasons == set(reasons)


def test_coverage_section_footer_states_artefact_path_and_counts(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    from breezy.persistence.scored_trial_store import write_scored_trials

    store_dir = tmp_path / "store"
    scored_row = _row(0, climate_day="2026-09-11")
    write_scored_trials(store_dir, (scored_row,), now_ns=1)
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    (store_dir / "fill_order.jsonl").write_text(
        json.dumps(
            {
                "trial_id": scored_row.trial_id,
                "score_seq": scored_row.score_seq,
                "filled_at_ns": 1,
            }
        )
        + "\n"
    )
    (store_dir / "excluded_fills.jsonl").write_text(
        "\n".join(
            (
                _excluded_fill_line(
                    trial_id="unscored-1",
                    station="MIA",
                    climate_day="2026-09-11",
                    venue_order_id="vo-1",
                    reason="fill_below_ask",
                ),
                _excluded_fill_line(
                    trial_id=scored_row.trial_id,
                    station=scored_row.station,
                    climate_day=scored_row.climate_day,
                    venue_order_id="vo-2",
                    reason="fee_unverified",
                ),
            )
        )
        + "\n"
    )
    manifest = _manifest(tmp_path)
    tally = tally_mod.build_family_tally_v2(
        (scored_row,), manifest=manifest, artefact=real_artefact, store_dir=store_dir
    )
    report = tally_mod.render_markdown_v2(tally, source_paths=(store_dir,), as_of="2026-09-11")
    assert str(store_dir / "excluded_fills.jsonl") in report
    assert "lines read: 2" in report
    assert "distinct venue_order_ids: 2" in report
    assert "dropped as already-scored: 1" in report


# --- Slice 4 item B2 (plan rev 6.1): `residual` additive to the LOSS_STOP gate


def test_residual_defaults_to_zero_and_preserves_existing_behaviour(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    rows = (_row(0, held=False, ask="0.10"),)
    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    assert tally.verdict == "CONTINUE"


def test_a_residual_that_pushes_total_below_loss_stop_kills(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """The stop-rule fires on `scored_pnl + residual`, not `scored_pnl`
    alone -- a family with real, unscored dollar losses (duplicate_fill/
    q != 1/fee-unreconciled fills, Slice 4 item B2) cannot look SURVIVE
    just because those fills never entered `rows`."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    rows = (_row(0, held=False, ask="0.10"),)
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=artefact, residual=Decimal(-60),
    )
    assert tally.verdict == "KILL"


def test_v3_residual_from_fill_source_derives_a_real_duplicate_fill_dollar_sum(
    tmp_path: Path, tally_mod: ModuleType,
) -> None:
    """Three-seam Slice 4 review item 4 [HIGH]: `compute_residual` had zero
    production callers -- `v3_residual_from_fill_source` wires it to the
    SAME `--fill-source` store `count_filled_takes` already reads."""
    cont_prefix = "continuous_rung_hold/trial/"
    day = "2026-09-05"
    fill_source = tmp_path / "exec_state.sqlite"
    store = SqliteStateStore(fill_source)
    latch = TrialDayRecord(
        latched_at_ns=1,
        instrument_id="lax-instr",
        ask=Decimal("0.40"),
        reason="taken",
        venue_order_id="v1",
    )
    store.set(f"{cont_prefix}LAX/{day}", latch.to_bytes())
    primary = DurableFillRecord(
        venue_order_id="v1", client_order_id="c-v1", instrument_id="lax-instr",
        order_side="BUY", cumulative_qty=Decimal(1), cumulative_cost=Decimal("0.40"),
        cumulative_fee=Decimal("0.01"), fee_reconciled=True, ts_event=1,
    )
    duplicate = DurableFillRecord(
        venue_order_id="v2", client_order_id="c-v2", instrument_id="lax-instr",
        order_side="BUY", cumulative_qty=Decimal(1), cumulative_cost=Decimal("0.45"),
        cumulative_fee=Decimal("0.02"), fee_reconciled=True, ts_event=2,
    )
    store.set(f"{FILL_KEY_PREFIX}v1", primary.to_bytes())
    store.set(f"{FILL_KEY_PREFIX}v2", duplicate.to_bytes())
    store.close()

    manifest = _manifest(tmp_path, trial_id_prefix=cont_prefix, stations=["LAX"])

    residual = tally_mod.v3_residual_from_fill_source(
        manifest, fill_source, since_climate_day=day,
    )

    # Negated: a SIGNED contribution to `total_pnl`, always <= 0.
    assert residual == -(Decimal("0.45") + Decimal("0.02"))


def test_v2_manifest_never_derives_a_residual(tmp_path: Path, tally_mod: ModuleType) -> None:
    """Three-seam Slice 4 review item 4: v2 path unchanged -- `main()`'s
    prefix guard means `residual` stays `Decimal(0)` for a v2 manifest,
    regardless of what a `--fill-source` store might contain."""
    manifest = _manifest(tmp_path)  # default v2 trial_id_prefix
    assert not manifest.trial_id_prefix.startswith("continuous_rung_hold/")


def test_v3_duplicate_fill_residual_pushes_the_family_tally_to_kill(
    tmp_path: Path, tally_mod: ModuleType,
) -> None:
    """Three-seam Slice 4 review item 4: the residual `v3_residual_from_
    fill_source` derives from a real duplicate-fill exclusion actually
    changes the reported tally's LOSS_STOP arithmetic (assert on the
    verdict, the reported total)."""
    cont_prefix = "continuous_rung_hold/trial/"
    day = "2026-09-05"
    fill_source = tmp_path / "exec_state.sqlite"
    store = SqliteStateStore(fill_source)
    latch = TrialDayRecord(
        latched_at_ns=1, instrument_id="lax-instr", ask=Decimal("0.40"),
        reason="taken", venue_order_id="v1",
    )
    store.set(f"{cont_prefix}LAX/{day}", latch.to_bytes())
    primary = DurableFillRecord(
        venue_order_id="v1", client_order_id="c-v1", instrument_id="lax-instr",
        order_side="BUY", cumulative_qty=Decimal(1), cumulative_cost=Decimal("0.40"),
        cumulative_fee=Decimal("0.01"), fee_reconciled=True, ts_event=1,
    )
    duplicate = DurableFillRecord(
        venue_order_id="v2", client_order_id="c-v2", instrument_id="lax-instr",
        order_side="BUY", cumulative_qty=Decimal(200), cumulative_cost=Decimal(100),
        cumulative_fee=Decimal(10), fee_reconciled=True, ts_event=2,
    )
    store.set(f"{FILL_KEY_PREFIX}v1", primary.to_bytes())
    store.set(f"{FILL_KEY_PREFIX}v2", duplicate.to_bytes())
    store.close()

    manifest = _manifest(tmp_path, trial_id_prefix=cont_prefix, stations=["LAX"])
    residual = tally_mod.v3_residual_from_fill_source(
        manifest, fill_source, since_climate_day=day,
    )
    # -(qty=200 * (fill_px=0.5 + fee=0.05)) = -110 -- crosses LOSS_STOP alone.
    assert residual == -(Decimal(200) * (Decimal("0.5") + Decimal("0.05")))
    assert residual < Decimal(-60)

    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    rows = (_row(0, held=True, station="LAX", prefix=cont_prefix),)  # a single WINNING trial
    tally = tally_mod.build_family_tally_v2(
        rows, manifest=manifest, artefact=artefact, residual=residual,
    )
    assert tally.verdict == "KILL"


# --- structural-dead pin (pm_us_crh_v2, additive KILL at n < look_step) ------


def test_15_covered_0_fill_time_kills_at_n_lt_look_step(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    tally = tally_mod.build_family_tally_v2(
        (),
        manifest=manifest,
        artefact=artefact,
        covered_listed_station_days=15,
        filled_takes=0,
    )
    assert tally.verdict == "KILL"
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-05")
    assert "**KILL**" in report
    assert "structural-dead" in report


def test_14_covered_0_fills_continues(tmp_path: Path, tally_mod: ModuleType) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    tally = tally_mod.build_family_tally_v2(
        (),
        manifest=manifest,
        artefact=artefact,
        covered_listed_station_days=14,
        filled_takes=0,
    )
    assert tally.verdict == "CONTINUE"
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-05")
    assert "**CONTINUE**" in report
    assert "**KILL**" not in report


def test_15_covered_one_fill_time_fill_continues(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    tally = tally_mod.build_family_tally_v2(
        (),
        manifest=manifest,
        artefact=artefact,
        covered_listed_station_days=15,
        filled_takes=1,
    )
    assert tally.verdict == "CONTINUE"
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-05")
    assert "**CONTINUE**" in report
    assert "**KILL**" not in report


def test_empty_looks_structural_kill_is_not_continue_n_lt_look_step(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """Structural KILL at n < look_step must not collapse to CONTINUE just
    because `looks` is empty -- headline keys off tally.verdict."""
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
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-05")
    assert "**KILL**" in report
    assert "**CONTINUE**" not in report
    assert "structural-dead" in report
    assert "evaluable and fired" in report
    # The headline must attribute the KILL to the structural-dead stop
    # firing, never to insufficient data -- that phrasing is reserved for a
    # genuine n < look_step CONTINUE/KILL with no structural pin involved.
    assert (
        "**KILL** -- structural-dead stop fired "
        "(15 covered listed station-days, 0 filled Takes)"
    ) in report
    assert "fewer than one completed look" not in report


def test_paper_provenance_store_is_refused_before_structural_eval(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """A paper_replay sidecar is refused before structural_dead(); R2 (empty
    unmarked store) is a missing-sidecar exception, not a paper admit."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "paper_replay"}))
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    with pytest.raises(tally_mod.ProvenanceRefusal, match="paper_replay"):
        tally_mod.build_family_tally_v2(
            (),
            manifest=manifest,
            artefact=artefact,
            store_dir=store_dir,
            covered_listed_station_days=15,
            filled_takes=0,
        )


def test_filled_takes_less_than_n_scored_is_refused(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """v1 live_family_tally.py:281-286: filled_takes must be a superset of
    scored rows. A settled-only count smaller than len(rows) is a wiring
    defect, never a silent KILL."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    rows = _rows(3)
    with pytest.raises(ValueError, match="settled-only count"):
        tally_mod.build_family_tally_v2(
            rows,
            manifest=manifest,
            artefact=artefact,
            covered_listed_station_days=15,
            filled_takes=0,
        )


def test_draft_manifest_never_prints_kill(tmp_path: Path, tally_mod: ModuleType) -> None:
    manifest = _manifest(tmp_path, status="DRAFT_NOT_REGISTERED", boundary_inputs_sha256="0" * 64)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=10)
    tally = tally_mod.build_family_tally_v2(
        (),
        manifest=manifest,
        artefact=artefact,
        covered_listed_station_days=15,
        filled_takes=0,
    )
    report = tally_mod.render_markdown_v2(tally, source_paths=(tmp_path,), as_of="2026-09-05")
    assert "SHADOW" in report
    assert "KILL" not in report
    assert "SURVIVE" not in report
    assert "CONTINUE" not in report


# ---------------------------------------------------------------------------
# S4a (plan MULTI_POSITION_PER_STATION_2026-09-14, R3-2/R3-3): the
# station-day combined draw, wired into build_family_tally_v2.
# ---------------------------------------------------------------------------
def test_a_single_fill_station_day_is_byte_identical_to_today(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """Regression floor (R3-2 merge gate): one fill per station-day (the
    real invariant post-S1) drives `n` combined draws == `n` fills, exactly
    as `pooled_rows` did before this slice."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=5)
    rows = _rows(5)  # 5 distinct station-days (see _rows' docstring)

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)

    assert len(tally.looks) == 1
    assert tally.looks[0].state.n == 5
    expected_information = sum(
        float(r.entry_ask + r.fee) * (1.0 - float(r.entry_ask + r.fee)) for r in rows
    )
    assert tally.looks[0].state.information == pytest.approx(expected_information)


def test_two_rung_fills_on_one_station_day_are_one_draw(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """Two DIFFERENT rungs (distinct instrument_id) filled on the SAME
    station-day count as ONE draw at the look, never two."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    row_a = _row(0, ask="0.30", held=True, climate_day="2026-09-11")
    row_b = _row(1, ask="0.20", held=False, climate_day="2026-09-11")

    tally = tally_mod.build_family_tally_v2(
        (row_a, row_b), manifest=manifest, artefact=artefact
    )

    assert tally.n_scored == 2
    assert len(tally.looks) == 1
    assert tally.looks[0].state.n == 1


def test_a_station_day_whose_break_evens_sum_above_one_is_refused_as_malformed_input_before_scoring(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    row_a = _row(0, ask="0.60", held=True, climate_day="2026-09-11")
    row_b = _row(1, ask="0.55", held=False, climate_day="2026-09-11")

    with pytest.raises(tally_mod.ScoredTrialDataIntegrityError, match="malformed_input"):
        tally_mod.build_family_tally_v2((row_a, row_b), manifest=manifest, artefact=artefact)


def test_looks_are_ordered_by_the_earliest_fill_of_each_station_day(
    tally_mod: ModuleType,
) -> None:
    """`_combined_draws_for_looks` groups by first-seen `(station,
    climate_day)` in the ALREADY fill-ordered sequence, so the combined
    draw for a station-day whose FIRST constituent filled earliest sorts
    first, regardless of row order in the input list."""
    row_lax_second_rung = _row(0, station="LAX", climate_day="2026-09-11", ask="0.10")
    row_mia_first_rung = _row(1, station="MIA", climate_day="2026-09-12", ask="0.20")
    row_lax_first_rung = _row(2, station="LAX", climate_day="2026-09-11", ask="0.15")
    # Pre-ordered as `_ordered_for_looks` would deliver it: MIA's single
    # fill is EARLIEST overall, then LAX's two rungs.
    ordered = (row_mia_first_rung, row_lax_first_rung, row_lax_second_rung)

    draws = tally_mod._combined_draws_for_looks(ordered)

    assert len(draws) == 2
    assert draws[0].n_constituents == 1  # MIA's single-rung draw, first
    assert draws[1].n_constituents == 2  # LAX's two-rung combined draw, second


def test_total_pnl_still_sums_constituent_rows(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    row_a = _row(0, ask="0.30", held=True, climate_day="2026-09-11")
    row_b = _row(1, ask="0.20", held=False, climate_day="2026-09-11")

    tally = tally_mod.build_family_tally_v2(
        (row_a, row_b), manifest=manifest, artefact=artefact
    )

    assert tally.total_pnl == row_a.pnl + row_b.pnl


# ---------------------------------------------------------------------------
# S4a math-review addendum (2026-09-14): the combine_station_day/
# score_combined path (HEAD) must be identical to a reference built from the
# byte-frozen `score()` over pooled `StratumRow`s at one fill per
# station-day -- S, I, n, verdict, and the rendered markdown, all identical.
# ---------------------------------------------------------------------------
def _reference_tally_via_uncombined_score(
    rows: tuple[ScoredTrial, ...],
    *,
    manifest: FamilyManifest,
    artefact: BoundaryArtefact,
    tally_mod: ModuleType,
) -> Any:
    """Pre-S4a reference: `score()` over pooled `StratumRow`s, never
    `combine_station_day`/`score_combined` -- reimplements
    `build_family_tally_v2`'s look loop against the byte-frozen `score()`
    path so it can be compared to the real S4a path independently."""
    non_excluded = tuple(r for r in rows if r.excluded_reason is None)
    ordered = tally_mod._ordered_for_looks(non_excluded, store_dir=None)
    pooled_rows = tuple(tally_mod._stratum_row(t) for t in ordered)
    pooled = tally_mod.build_stratum_v2("pooled", pooled_rows) if pooled_rows else None
    station_strata = tally_mod._station_strata(non_excluded)
    ask_band_strata = tally_mod._ask_band_strata(non_excluded)
    any_cell_dead = any(s.cell_dead for s in (*station_strata, *ask_band_strata))
    total_pnl = sum((row.pnl for row in non_excluded), start=Decimal(0))

    n = len(pooled_rows)
    look_step = artefact.spending.look_step
    n_max = artefact.spending.n_max

    looks: list[Any] = []
    t_history: list[float] = []
    verdict = "CONTINUE"
    bca_line: str | None = None
    scheduled_ns = range(look_step, min(n, n_max) + 1, look_step)
    for look_n in scheduled_ns:
        state = score(pooled_rows[:look_n])
        t = tally_mod.information_fraction(state.information, i_max=artefact.i_max)
        t_history.append(t)
        reached_i_max = state.information >= artefact.i_max
        reached_n_max = look_n >= n_max
        is_terminal = reached_i_max or reached_n_max
        if is_terminal:
            reason = tally_mod.TruncationReason.I_MAX
            b_eff, b_fut = artefact.boundary_for(tuple(t_history), is_terminal=True)
            verdict = tally_mod.terminal_look(
                state,
                reason=reason,
                b_eff=b_eff,
                b_fut=b_fut,
                total_pnl=total_pnl,
                cell_dead=any_cell_dead,
                structural_fired=False,
            )
            looks.append(
                tally_mod.LookRecord(
                    look_n=look_n,
                    t=t,
                    state=state,
                    b_eff=b_eff,
                    b_fut=b_fut,
                    verdict=verdict,
                    terminal=True,
                    reason=reason,
                )
            )
            bca_line = tally_mod._roi_bound_line_v2(rows)
            break
        b_eff, b_fut = artefact.boundary_for(tuple(t_history), is_terminal=False)
        verdict = tally_mod.look_verdict(
            state,
            b_eff=b_eff,
            b_fut=b_fut,
            total_pnl=total_pnl,
            cell_dead=any_cell_dead,
            structural_fired=False,
        )
        looks.append(
            tally_mod.LookRecord(
                look_n=look_n,
                t=t,
                state=state,
                b_eff=b_eff,
                b_fut=b_fut,
                verdict=verdict,
                terminal=False,
                reason=None,
            )
        )
        if verdict != "CONTINUE":
            bca_line = tally_mod._roi_bound_line_v2(rows)
            break

    return tally_mod.FamilyTallyV2(
        family_id=manifest.family_id,
        manifest_sha256=manifest.manifest_sha256,
        boundary_inputs_sha256=artefact.inputs_sha256,
        status=manifest.status,
        n_scored=len(rows),
        n_excluded=len(rows) - len(non_excluded),
        pooled=pooled,
        station_strata=station_strata,
        ask_band_strata=ask_band_strata,
        looks=tuple(looks),
        verdict=verdict,
        total_pnl=total_pnl,
        bca_line=bca_line,
        structural_dead=None,
        store_empty_no_sidecar=False,
    )


def _assert_tally_matches_reference(
    tally: Any, reference: Any, *, tally_mod: ModuleType, tmp_path: Path
) -> None:
    assert len(tally.looks) == len(reference.looks)
    for head_look, ref_look in zip(tally.looks, reference.looks, strict=True):
        assert head_look.state.s == ref_look.state.s
        assert head_look.state.information == ref_look.state.information
        assert head_look.state.n == ref_look.state.n
        assert head_look.verdict == ref_look.verdict
    assert tally.verdict == reference.verdict

    source_paths = (tmp_path / "scored.parquet",)
    head_text = tally_mod.render_markdown_v2(
        tally, source_paths=source_paths, as_of="2026-09-14T00:00:00Z"
    )
    ref_text = tally_mod.render_markdown_v2(
        reference, source_paths=source_paths, as_of="2026-09-14T00:00:00Z"
    )
    assert head_text == ref_text


def test_the_multi_station_tally_matches_the_uncombined_score_reference(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """A REALISTIC multi-station fixture (3 stations, 8 station-days, one
    fill per station-day, mixed held/not-held, qty=1): the tally built at
    HEAD (combine_station_day/score_combined) must equal the reference
    built from the byte-frozen `score()` path, in S/I/n/verdict and the
    rendered markdown."""
    manifest = _manifest(tmp_path)
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    rows = (
        _row(0, station="MIA", climate_day="2026-09-11", ask="0.10", held=True),
        _row(1, station="MIA", climate_day="2026-09-12", ask="0.20", held=False),
        _row(2, station="MIA", climate_day="2026-09-13", ask="0.35", held=True),
        _row(3, station="LAX", climate_day="2026-09-11", ask="0.15", held=False),
        _row(4, station="LAX", climate_day="2026-09-12", ask="0.45", held=True),
        _row(5, station="LAX", climate_day="2026-09-13", ask="0.60", held=False),
        _row(6, station="SFO", climate_day="2026-09-11", ask="0.25", held=True),
        _row(7, station="SFO", climate_day="2026-09-12", ask="0.50", held=False),
    )

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    reference = _reference_tally_via_uncombined_score(
        rows, manifest=manifest, artefact=artefact, tally_mod=tally_mod
    )

    assert len(tally.looks) == 8
    _assert_tally_matches_reference(tally, reference, tally_mod=tally_mod, tmp_path=tmp_path)


def test_the_v2_family_tally_is_unchanged_by_the_combined_draw(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """Using the REGISTERED v2 manifest (`deploy/families/pm_us_crh_v2.json`
    semantics: at most one fill per station-day by its latch), the
    combined-draw path yields S/I/n/verdict/text identical to the
    score()-only reference -- pinning that S4a leaves the REGISTERED v2
    family's stopping statistic unaffected by construction."""
    manifest = load_family_manifest(
        _REPO_ROOT / "deploy" / "families" / "pm_us_crh_v2.json", allow_draft=True
    )
    artefact = _synthetic_artefact(i_max=1000.0, n_max=100, look_step=1)
    rows = (
        _row(0, station="MIA", climate_day="2026-09-11", ask="0.10", held=True),
        _row(1, station="LAX", climate_day="2026-09-11", ask="0.30", held=False),
        _row(2, station="MDW", climate_day="2026-09-12", ask="0.55", held=True),
        _row(3, station="SFO", climate_day="2026-09-13", ask="0.40", held=False),
    )

    tally = tally_mod.build_family_tally_v2(rows, manifest=manifest, artefact=artefact)
    reference = _reference_tally_via_uncombined_score(
        rows, manifest=manifest, artefact=artefact, tally_mod=tally_mod
    )

    assert len(tally.looks) == 4
    _assert_tally_matches_reference(tally, reference, tally_mod=tally_mod, tmp_path=tmp_path)


def test_the_v1_tally_is_untouched() -> None:
    """S4a touches only v2 (`current_rung_hold_v2.py`/`family_tally_v2.py`)
    -- v1's `live_family_tally.py` is byte-unmodified. Pinned against a
    hardcoded sha256 of the file's current bytes (computed once at S4a
    HEAD, cac3f63), not a `git show` of a commit that a future history
    squash could make unresolvable. v1 tally byte-frozen; PREREG v1 closed;
    update only with a ruling."""
    import hashlib

    path = _SCRIPTS_ANALYSIS_DIR / "live_family_tally.py"
    current = hashlib.sha256(path.read_bytes()).hexdigest()
    assert current == "801f3106e3a32f6032942b85feaf23b30cb2a0159705d471ab956f9cb86610e0"
