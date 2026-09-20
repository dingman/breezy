"""RED-first suite for the 2026-09-20 ruling
`docs/evidence/RULING_v3_admissibility_divergence_2026-09-20.md`:

R1 -- `family_tally_v2.build_family_tally_v2` admitted on the parquet
      `excluded_reason` column ALONE and never consulted the
      `excluded_fills.jsonl` residual sidecar, so a fill its own scorer had
      classified `no_side_first_order_residual` still counted toward `n` on
      a REGISTERED sequential test.
R2 -- `coverage_rows` then HID that contradiction ("dropped as
      already-scored"), discarding the one record that reveals it.
R4 -- no fix may reduce residual strictness; the admissible direction is
      always the one that SHRINKS `n`.

L-42 (BINDING): every parquet + sidecar fixture here is written by the REAL
scorer (`score_live_trials.score_live_trials` -> the real
`write_scored_trials`, and the real `_append_excluded_fills` over the real
`_admit_fill` classification), reusing
`tests/unit/test_realized_draws_loader.py`'s helpers rather than inventing a
second fixture path. Nothing here is hand-built.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.persistence.family_manifest import FamilyManifest
from breezy.persistence.gs_boundary_artefact import BoundaryArtefact, load_boundary_artefact
from breezy.persistence.realized_draws import load_realized_draws
from breezy.persistence.residual_fills import read_excluded_fills
from breezy.persistence.scored_trial_store import read_scored_trials
from tests.unit.test_family_tally_v2 import (
    _REAL_ARTEFACT_PATH,
    _REAL_ARTEFACT_SHA,
    _load_module,
    _manifest,
)
from tests.unit.test_realized_draws_loader import (
    _LIVE_STORE,
    _reseed_fill,
    _run_real_scorer,
    _seeded_store,
)
from tests.unit.test_score_live_trials_state_db_source import (
    _DAY_ISO,
    _STATION,
    _V3_FAMILY_PREFIX,
)

_CONT_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "deploy/families/pm_us_crh_cont.json"


@pytest.fixture(scope="module")
def tally_mod() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def real_artefact() -> BoundaryArtefact:
    return load_boundary_artefact(_REAL_ARTEFACT_PATH, expected_sha256=_REAL_ARTEFACT_SHA)


def _v3_manifest(tmp_path: Path, **overrides: Any) -> FamilyManifest:
    return _manifest(
        tmp_path,
        family_id="pm_us_crh_cont_test",
        trial_id_prefix=_V3_FAMILY_PREFIX,
        d0_climate_day="2026-09-01",
        stations=[_STATION],
        **overrides,
    )


def _contradiction_store(tmp_path: Path) -> Path:
    """The LIVE shape, reproduced by the real scorer: run 1 scores the fill
    (parquet row, `excluded_reason=None`); run 2 classifies the SAME fill
    residual and writes it to `excluded_fills.jsonl`. The parquet row from
    run 1 stays -- the store then asserts both things at once."""
    store_path, instrument_id = _seeded_store(tmp_path, family_prefix=_V3_FAMILY_PREFIX)
    _run_real_scorer(tmp_path, store_path, family_prefix=_V3_FAMILY_PREFIX)
    _reseed_fill(store_path, instrument_id, fee_reconciled=False)
    return _run_real_scorer(tmp_path, store_path, family_prefix=_V3_FAMILY_PREFIX)


def _clean_store(tmp_path: Path) -> Path:
    store_path, _instrument_id = _seeded_store(tmp_path, family_prefix=_V3_FAMILY_PREFIX)
    return _run_real_scorer(tmp_path, store_path, family_prefix=_V3_FAMILY_PREFIX)


def _tally(tally_mod: ModuleType, derived: Path, manifest: FamilyManifest, artefact: Any) -> Any:
    return tally_mod.build_family_tally_v2(
        read_scored_trials(derived), manifest=manifest, artefact=artefact, store_dir=derived
    )


def _admitted(tally: Any) -> int:
    return tally.n_scored - tally.n_excluded


# ---------------------------------------------------------------------------
# R1: the sidecar is consulted -- a residual trial_id is NOT admissible
# ---------------------------------------------------------------------------


def test_a_scored_row_whose_trial_id_is_residual_in_the_sidecar_is_not_admitted(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    derived = _contradiction_store(tmp_path)
    # precondition: the store really does assert both things at once.
    assert [r.excluded_reason for r in read_scored_trials(derived)] == [None]
    assert [f.reason for f in read_excluded_fills(derived)] == ["fee_unverified"]

    tally = _tally(tally_mod, derived, _v3_manifest(tmp_path), real_artefact)

    assert tally.n_scored == 1
    assert _admitted(tally) == 0
    assert tally.n_residual_excluded == 1
    assert tally.pooled is None


def test_the_tally_n_equals_the_loader_admissible_count_on_the_same_store(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    """Pinned together so the registered tally and the WP-31 §5 loader can
    never again disagree about what `n` is."""
    derived = _contradiction_store(tmp_path)

    tally = _tally(tally_mod, derived, _v3_manifest(tmp_path), real_artefact)

    assert _admitted(tally) == load_realized_draws(derived).n_admissible_fills


def test_a_clean_store_still_admits_its_fill_and_still_agrees_with_the_loader(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    derived = _clean_store(tmp_path)

    tally = _tally(tally_mod, derived, _v3_manifest(tmp_path), real_artefact)

    assert _admitted(tally) == 1
    assert tally.n_residual_excluded == 0
    assert _admitted(tally) == load_realized_draws(derived).n_admissible_fills


# ---------------------------------------------------------------------------
# R2: the contradiction is LOUD -- named, counted, reported, refusable
# ---------------------------------------------------------------------------


def test_a_residual_whose_trial_id_has_a_scored_row_is_reported_not_silently_dropped(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    derived = _contradiction_store(tmp_path)
    excluded = read_excluded_fills(derived)
    scored_ids = frozenset(t.trial_id for t in read_scored_trials(derived))

    rows = tally_mod.coverage_rows(excluded, scored_ids)

    assert [(r.reason, r.station, r.climate_day, r.count) for r in rows] == [
        ("fee_unverified", _STATION, _DAY_ISO, 1)
    ]
    assert tally_mod.residual_scored_contradictions(excluded, scored_ids) == (
        next(iter(scored_ids)),
    )


def test_the_rendered_coverage_section_names_and_counts_the_contradiction(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    derived = _contradiction_store(tmp_path)
    tally = _tally(tally_mod, derived, _v3_manifest(tmp_path), real_artefact)

    report = tally_mod.render_markdown_v2(tally, source_paths=(derived,), as_of="2026-09-20")

    assert "residual/scored contradiction" in report
    assert "dropped as already-scored: 1" not in report
    assert next(iter(t.trial_id for t in read_scored_trials(derived))) in report


def test_the_tally_carries_the_contradiction_trial_ids(
    tmp_path: Path, tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    derived = _contradiction_store(tmp_path)

    tally = _tally(tally_mod, derived, _v3_manifest(tmp_path), real_artefact)

    assert tally.residual_scored_contradictions == tuple(
        sorted(t.trial_id for t in read_scored_trials(derived))
    )


def test_a_contradiction_left_in_the_admitted_set_refuses_the_whole_tally(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """R4: the fail-closed guard. Reducing residual strictness -- readmitting
    a sidecar-residual trial_id -- must REFUSE, never silently inflate `n`."""
    with pytest.raises(tally_mod.ResidualScoredContradictionError, match="t1"):
        tally_mod.assert_residual_contradictions_excluded(
            ("t1",), admitted_trial_ids=frozenset({"t1"}), store_declared_single_family=True
        )


# ---------------------------------------------------------------------------
# no regression: the already-scored drop survives for NON-residual reasons
# ---------------------------------------------------------------------------


def test_a_residual_with_no_scored_row_behaves_exactly_as_it_does_today(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    derived = _contradiction_store(tmp_path)
    excluded = read_excluded_fills(derived)

    rows = tally_mod.coverage_rows(excluded, frozenset())

    assert [(r.reason, r.count) for r in rows] == [("fee_unverified", 1)]
    assert tally_mod.residual_scored_contradictions(excluded, frozenset()) == ()


def test_a_non_residual_exclusion_whose_trial_id_is_scored_is_still_dropped(
    tmp_path: Path, tally_mod: ModuleType
) -> None:
    """A `no_taken_latch`/`ambiguous_latch` line re-scored on a later run is
    the ORIGINAL I3c case ("append-only jsonl is evidence, not the count")
    and stays dropped -- widened, never relaxed (L-12)."""
    derived = _contradiction_store(tmp_path)
    scored_ids = frozenset(t.trial_id for t in read_scored_trials(derived))
    non_residual = tuple(
        dataclasses.replace(f, reason="ambiguous_latch") for f in read_excluded_fills(derived)
    )

    assert tally_mod.coverage_rows(non_residual, scored_ids) == ()
    assert tally_mod.residual_scored_contradictions(non_residual, scored_ids) == ()


# ---------------------------------------------------------------------------
# the REAL live store (read-only): the registered family now admits 3, not 4
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIVE_STORE.exists(), reason="no live scored-trial store on this host")
def test_the_real_live_store_tally_admits_three_not_four(
    tally_mod: ModuleType, real_artefact: BoundaryArtefact
) -> None:
    from breezy.persistence.family_manifest import load_family_manifest

    manifest = load_family_manifest(_CONT_MANIFEST_PATH, allow_draft=True)
    tally = tally_mod.build_family_tally_v2(
        read_scored_trials(_LIVE_STORE),
        manifest=manifest,
        artefact=real_artefact,
        store_dir=_LIVE_STORE,
    )

    assert tally.n_scored == 4
    assert _admitted(tally) == 3
    assert tally.n_residual_excluded == 1
    assert _admitted(tally) == load_realized_draws(_LIVE_STORE).n_admissible_fills
