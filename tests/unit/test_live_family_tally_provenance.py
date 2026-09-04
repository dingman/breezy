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

from breezy.settlement.trial_scorer import ScoredTrial

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_BASE_NS = int(dt.datetime(2026, 9, 1, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "live_family_tally.py"
    spec = importlib.util.spec_from_file_location("live_family_tally_prov", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tally_mod() -> ModuleType:
    return _load_module()


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


_LIVE_ID = "current_rung_hold/trial/LAX/2026-08-31"
_PAPER_ID = "paper_replay/current_rung_hold/trial/LAX/2026-08-31"


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
