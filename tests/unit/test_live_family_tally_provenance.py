"""RED tests 5-6 (`docs/plans/PAPER_REPLAY_6B_BRIEF_2026-09-04.md`): paper
rows never pool into the live tally, and vice versa.

Loader pattern lifted verbatim from `test_live_family_tally.py` (dynamic
module load off `scripts/analysis/live_family_tally.py` -- `scripts/` is
unimportable as a package from `src/breezy`, and this repo's convention is
`importlib.util.spec_from_file_location`, not a `sys.path` package import).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.persistence.family_manifest import FamilyManifest
from breezy.runtime.paper_replay import PAPER_TRIAL_ID_NAMESPACE, UNSCOPED_FAMILY_ID
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.settlement.trial_scorer import ScoredTrial

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_BASE_NS = int(dt.datetime(2026, 9, 1, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


def _load_module(filename: str, register_as: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / filename
    spec = importlib.util.spec_from_file_location(register_as, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tally_mod() -> ModuleType:
    return _load_module("live_family_tally.py", "live_family_tally_prov")


@pytest.fixture(scope="module")
def family_tally_v2_mod() -> ModuleType:
    """AUD-19a step 2: the live-side `filter_rows_to_manifest_prefix`
    selector AUD-05 owns, loaded to prove it is provably unaffected by the
    paper-replay id shape change."""
    return _load_module("family_tally_v2.py", "family_tally_v2_prov")


@pytest.fixture(scope="module")
def fill_time_count_mod() -> ModuleType:
    """AUD-19a step 2: the live-side `count_filled_takes` selector AUD-05
    owns, loaded for the same reason."""
    return _load_module("fill_time_count.py", "fill_time_count_prov")


def _trial(trial_id: str, **overrides: object) -> ScoredTrial:
    kwargs: dict[str, object] = {
        "trial_id": trial_id,
        "station": "LAX",
        "climate_day": "2026-08-31",
        "instrument_id": "LAX-2026-08-31-gte78lt80f",
        "settlement_tmax_f": 79,
        "held": True,
        "pnl": Decimal("0.55"),
        "revision_seq": 1,
        "raw_sha256": "a" * 64,
        "scored_at_ns": _BASE_NS,
        "score_seq": 0,
        "settlement_basis": "nws_final",
        "excluded_reason": None,
        "slippage": Decimal("0.02"),
        "entry_ask": Decimal("0.40"),
        "fill_px": Decimal("0.42"),
        "fee": Decimal("0.01"),
    }
    kwargs.update(overrides)
    return ScoredTrial(**kwargs)  # type: ignore[arg-type]


def _manifest(*, family_id: str, trial_id_prefix: str) -> FamilyManifest:
    """A minimal, directly-constructed `FamilyManifest` -- bypasses
    `load_family_manifest`'s on-disk validation entirely, since AUD-19a's
    step 2 only needs `family_id`/`trial_id_prefix` to reach
    `filter_rows_to_manifest_prefix` (`family_tally_v2.py`, AUD-05-owned,
    untouched by this item)."""
    return FamilyManifest(
        family_id=family_id,
        venue="polymarket_us",
        trial_id_prefix=trial_id_prefix,
        d0_climate_day="2026-08-31",
        boundary_artefact_path=Path("deploy/families/artefacts/not_applicable.json"),
        boundary_inputs_sha256="a" * 64,
        stations=("LAX",),
        status="REGISTERED",
        manifest_sha256="b" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path(
            "deploy/families/artefacts/not_applicable_density.json",
        ),
        density_artefact_sha256="c" * 64,
        taker_fee_coefficient=Decimal("0.0695"),
    )


_LIVE_ID = "current_rung_hold/trial/LAX/2026-08-31"
#: AUD-19a: the CURRENT shape a 19a-era caller (no `--family-manifest` yet)
#: produces -- `PAPER_TRIAL_ID_NAMESPACE/UNSCOPED_FAMILY_ID/...`.
_PAPER_ID = (
    f"{PAPER_TRIAL_ID_NAMESPACE}/{UNSCOPED_FAMILY_ID}/current_rung_hold/trial/LAX/2026-08-31"
)
#: D3: a row already stored under the PRE-19a shape. Never rewritten; still
#: classified as paper by the outer-literal check; refused by any
#: family-scoped read (segment 1 is `current_rung_hold`, which equals no
#: registered `family_id`).
_OLD_SHAPE_PAPER_ID = "paper_replay/current_rung_hold/trial/LAX/2026-08-31"
_CONT_PREFIX = "continuous_rung_hold/trial/"
_COLLIDING_IDS = (
    f"{PAPER_TRIAL_ID_NAMESPACE}/pm_us_crh_cont/{_CONT_PREFIX}LAX/2026-08-31",
    f"{PAPER_TRIAL_ID_NAMESPACE}/pm_us_crh_v4/{_CONT_PREFIX}LAX/2026-08-31",
)


def test_paper_rows_never_pool_into_the_live_tally(tally_mod: ModuleType) -> None:
    paper_row = _trial(_PAPER_ID)
    with pytest.raises(ValueError, match="non-live"):
        tally_mod.assert_live_only([paper_row])


def test_the_paper_tally_refuses_a_live_row(tally_mod: ModuleType) -> None:
    live_row = _trial(_LIVE_ID)
    with pytest.raises(ValueError, match="non-paper"):
        tally_mod.assert_paper_only([live_row])


def test_build_live_family_tally_paper_provenance_accepts_paper_rows(
    tally_mod: ModuleType,
) -> None:
    tally = tally_mod.build_live_family_tally([_trial(_PAPER_ID)], provenance="paper_replay")
    assert tally.n_scored == 1


def test_build_live_family_tally_paper_provenance_refuses_a_live_row(
    tally_mod: ModuleType,
) -> None:
    with pytest.raises(ValueError, match="non-paper"):
        tally_mod.build_live_family_tally([_trial(_LIVE_ID)], provenance="paper_replay")


def test_build_live_family_tally_default_provenance_is_unmodified_live_behaviour(
    tally_mod: ModuleType,
) -> None:
    """`assert_live_only` itself stays byte-unmodified -- the default
    provenance dispatches to it exactly as before this brief landed."""
    with pytest.raises(ValueError, match="non-live"):
        tally_mod.build_live_family_tally([_trial(_PAPER_ID)])


def test_render_markdown_carries_the_provenance_line(tally_mod: ModuleType) -> None:
    tally = tally_mod.build_live_family_tally([_trial(_LIVE_ID)])
    report = tally_mod.render_markdown(
        tally, source_paths=(Path("/tmp/x"),), as_of="2026-09-04", provenance="live",
    )
    assert "provenance: live" in report


# ---------------------------------------------------------------------------
# AUD-19a step 2/A1b: no paper-replay id -- new-shape or old-shape -- ever
# satisfies a live selector, including the three AUD-05-owned live-side
# selectors this item must NEVER alter the behaviour of.
# ---------------------------------------------------------------------------
def test_no_paper_replay_id_satisfies_any_live_selector(
    tally_mod: ModuleType,
    family_tally_v2_mod: ModuleType,
    fill_time_count_mod: ModuleType,
    tmp_path: Path,
) -> None:
    for trial_id in (*_COLLIDING_IDS, _OLD_SHAPE_PAPER_ID):
        row = _trial(trial_id)
        with pytest.raises(ValueError, match="non-live"):
            tally_mod.assert_live_only([row])
        tally_mod.assert_paper_only([row])  # accepts -- unscoped read

    for family_id in ("pm_us_crh_cont", "pm_us_crh_v4"):
        manifest = _manifest(family_id=family_id, trial_id_prefix=_CONT_PREFIX)
        kept = family_tally_v2_mod.filter_rows_to_manifest_prefix(
            [_trial(trial_id) for trial_id in _COLLIDING_IDS],
            manifest,
            store_declared_single_family=False,
        )
        assert kept == ()

    empty_state_db = tmp_path / "exec_state.sqlite"
    SqliteStateStore(empty_state_db).close()
    assert (
        fill_time_count_mod.count_filled_takes(
            empty_state_db, family_prefix="current_rung_hold/trial/",
        )
        == 0
    )


def test_the_paper_namespace_literal_is_pinned_equal_across_both_call_sites(
    tally_mod: ModuleType,
) -> None:
    """Ruling item 6's 'must move together' discipline (AUD-19a A1c) -- the
    outer literal `paper_replay.PAPER_TRIAL_ID_NAMESPACE` and
    `live_family_tally`'s own restated, not-imported copy must never
    drift apart."""
    assert PAPER_TRIAL_ID_NAMESPACE + "/" == tally_mod._PAPER_TRIAL_ID_NAMESPACE


def test_assert_paper_only_refuses_a_row_from_a_different_family_when_scoped(
    tally_mod: ModuleType,
) -> None:
    row = _trial(_COLLIDING_IDS[1])  # family segment "pm_us_crh_v4"
    tally_mod.assert_paper_only([row], family_id="pm_us_crh_v4")
    with pytest.raises(ValueError, match="not scoped to family 'pm_us_crh_cont'"):
        tally_mod.assert_paper_only([row], family_id="pm_us_crh_cont")


def test_an_old_shape_row_is_still_classified_as_paper_but_never_attributed_to_a_family(
    tally_mod: ModuleType,
) -> None:
    """D3: an already-stored pre-19a row is never rewritten; it stays
    paper-classified under the unscoped read, and is refused -- never
    silently attributed -- by any family-scoped read, because its segment-1
    value (`current_rung_hold`) equals no registered `family_id`."""
    row = _trial(_OLD_SHAPE_PAPER_ID)
    tally_mod.assert_paper_only([row])  # still paper, unscoped
    with pytest.raises(ValueError, match="not scoped to family 'pm_us_crh_v4'"):
        tally_mod.assert_paper_only([row], family_id="pm_us_crh_v4")
