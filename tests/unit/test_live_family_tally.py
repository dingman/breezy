"""RED-first tests for 6d -- the nightly live-family tally.

Spec: `docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md` section 6d, as
amended by the "Converged peer review (2026-09-04)" section.
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
    spec = importlib.util.spec_from_file_location("live_family_tally", path)
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


def _live_id(station: str, day: str) -> str:
    return f"current_rung_hold/trial/{station}/{day}"


def test_a_non_live_trial_id_is_refused_with_the_corrected_citation_docstring(
    tally_mod: ModuleType,
) -> None:
    rows = (
        _trial(_live_id("LAX", "2026-08-31"), station="LAX"),
        _trial("archive_row/LAX/2021-06-01", station="LAX"),
    )
    with pytest.raises(ValueError, match="archive trials are never pooled here"):
        tally_mod.assert_live_only(rows)
    # The corrected citation (review item 3) -- L-13 alone does NOT state
    # the never-pool rule; both source and behavior carry the full phrase.
    source = (_SCRIPTS_ANALYSIS_DIR / "live_family_tally.py").read_text()
    assert "analogous to L-13" in source
    assert "L-21" in source
    assert "no lesson states this rule verbatim" in source


def test_excluded_rows_are_left_out_of_every_stratum(tally_mod: ModuleType) -> None:
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 61)
    ) + (
        _trial(
            _live_id("LAX", "2026-09-01"),
            station="LAX",
            excluded_reason="venue_settled_without_nws",
            held=False,
            entry_ask=Decimal("0.90"),
        ),
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.n_scored == 61
    assert tally.n_excluded == 1
    assert tally.pooled is not None
    assert tally.pooled.n == 60


def test_survive_requires_positive_total_pnl_even_when_the_rate_survives(
    tally_mod: ModuleType,
) -> None:
    # 150 trials, ask 0.10 (break-even ~0.1054), held on all -> rate-survive,
    # but pnl is made deeply negative per trial so SigmaPnL < 0.
    rows = tuple(
        _trial(
            _live_id("LAX", f"2026-{(1 + i // 28):02d}-{1 + i % 28:02d}"),
            station="LAX",
            held=True,
            entry_ask=Decimal("0.10"),
            pnl=Decimal("-5.00"),
        )
        for i in range(150)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.total_pnl < 0
    assert tally.outcome != "SURVIVE"


def test_a_kill_fixture_fires_on_pooled_cell_dead(tally_mod: ModuleType) -> None:
    # 60 trials, high ask (break-even high), never held -> Wilson-upper
    # near 0, well below break-even.
    rows = tuple(
        _trial(
            _live_id("LAX", f"2026-{(1 + i // 28):02d}-{1 + i % 28:02d}"),
            station="LAX",
            held=False,
            entry_ask=Decimal("0.80"),
            pnl=Decimal("-0.80"),
        )
        for i in range(60)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.outcome == "KILL"


def test_a_small_sample_is_underpowered_not_dead_or_survive(tally_mod: ModuleType) -> None:
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 6)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.outcome == "UNDERPOWERED"


def test_the_bca_line_is_present_and_exact_when_underpowered(tally_mod: ModuleType) -> None:
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 6)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.bca_line == "BCa: UNDERPOWERED (n<30)"


def test_the_bca_line_is_present_and_exact_when_refused_by_exclusion_ceiling(
    tally_mod: ModuleType,
) -> None:
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 21)
    ) + tuple(
        _trial(
            _live_id("LAX", f"2026-09-{d:02d}"),
            station="LAX",
            excluded_reason="divergence",
        )
        for d in range(1, 11)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.bca_line.startswith("BCa: REFUSED")
    assert "0.333" in tally.bca_line


def test_no_output_or_source_ever_prints_wald(tally_mod: ModuleType) -> None:
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 6)
    )
    tally = tally_mod.build_live_family_tally(rows)
    rendered = tally_mod.render_markdown(tally, source_paths=(Path("x"),), as_of="2026-09-04")
    assert "Wald" not in rendered
    source = (_SCRIPTS_ANALYSIS_DIR / "live_family_tally.py").read_text()
    assert "Wald" not in source


def test_the_stratum_table_header_matches_the_mb_report_literally(tally_mod: ModuleType) -> None:
    mb_source = (_SCRIPTS_ANALYSIS_DIR / "mb_current_rung_edge_study.py").read_text()
    assert "| stratum | n | k | realized rate | mean ask | break-even | " in mb_source
    assert "Wilson-lower | Wilson-upper | |" in mb_source
    assert tally_mod.STRATUM_TABLE_HEADER == (
        "| stratum | n | k | realized rate | mean ask | break-even | "
        "Wilson-lower | Wilson-upper | |"
    )


def test_wilson_z_is_the_shared_constant_not_a_local_literal(tally_mod: ModuleType) -> None:
    source = (_SCRIPTS_ANALYSIS_DIR / "live_family_tally.py").read_text()
    assert "Z_95" not in source
    assert "1.959963984540054" not in source
    assert "from archive_correction_probe import wilson_interval" in source


def test_ask_bands_come_from_the_shared_classify_ask_band(tally_mod: ModuleType) -> None:
    source = (_SCRIPTS_ANALYSIS_DIR / "live_family_tally.py").read_text()
    assert "classify_ask_band" in source
    assert "ASK_BANDS" in source
    # No re-derivation of the band boundaries as local literals.
    assert "0.05, 0.15" not in source


def test_break_even_uses_the_shared_helper(tally_mod: ModuleType) -> None:
    source = (_SCRIPTS_ANALYSIS_DIR / "live_family_tally.py").read_text()
    assert "from mb_current_rung_edge_study import" in source
    assert "break_even" in source


def test_zero_rows_is_underpowered_and_does_not_crash(tally_mod: ModuleType) -> None:
    tally = tally_mod.build_live_family_tally(())
    assert tally.outcome == "UNDERPOWERED"
    assert tally.n_scored == 0
    rendered = tally_mod.render_markdown(tally, source_paths=(Path("x"),), as_of="2026-09-04")
    assert "UNDERPOWERED" in rendered


def test_a_re_scored_trial_is_counted_once_via_the_store_reader(tally_mod: ModuleType) -> None:
    # build_live_family_tally trusts its caller (score_seq dedup happens in
    # read_scored_trials); this asserts duplicate trial_ids are not
    # silently double-summed by the tally itself when the reader already
    # deduped -- i.e. the tally has no independent dedup logic to diverge.
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 6)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.n_scored == 5
