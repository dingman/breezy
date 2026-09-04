"""RED-first tests wiring the v1 structural-dead stop (section 5:105-106)
into `build_live_family_tally` -- additive only, KILL-class, evaluated
alongside the existing `pooled_kill`/`cell_dead` logic without altering it.
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


def test_default_call_leaves_structural_dead_none(tally_mod: ModuleType) -> None:
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 6)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.structural_dead is None
    assert tally.outcome == "UNDERPOWERED"


def test_zero_fills_anywhere_at_15_covered_listed_days_fires_kill(
    tally_mod: ModuleType,
) -> None:
    """15 covered-listed days, filled_takes=0 sourced from a fill-time
    store (not from `rows`) -- genuinely zero fills, so it fires."""
    tally = tally_mod.build_live_family_tally(
        (), covered_listed_station_days=15, filled_takes=0
    )
    assert tally.structural_dead is not None
    assert tally.structural_dead.structural_dead is True
    assert tally.outcome == "KILL"
    assert "structural-dead" in tally.detail
    assert "15" in tally.detail


def test_one_unsettled_fill_at_15_covered_days_does_not_fire(tally_mod: ModuleType) -> None:
    """15 covered days, 0 SCORED rows, but 1 fill-time fill (not yet
    settled) -- must NOT fire; this is exactly the false-KILL the settled-
    only count would have produced."""
    tally = tally_mod.build_live_family_tally(
        (), covered_listed_station_days=15, filled_takes=1
    )
    assert tally.structural_dead is not None
    assert tally.structural_dead.structural_dead is False
    assert tally.outcome == "UNDERPOWERED"


def test_14_covered_listed_days_zero_fills_does_not_fire(tally_mod: ModuleType) -> None:
    tally = tally_mod.build_live_family_tally(
        (), covered_listed_station_days=14, filled_takes=0
    )
    assert tally.structural_dead is not None
    assert tally.structural_dead.structural_dead is False
    assert tally.outcome == "UNDERPOWERED"


def test_fill_time_source_unavailable_is_not_evaluable_and_never_kills(
    tally_mod: ModuleType,
) -> None:
    """15 covered-listed days but NO fill-time count reachable
    (`filled_takes` omitted) -- FAILS CLOSED: never fires, and the rendered
    report states it was skipped rather than silently assuming zero fills."""
    tally = tally_mod.build_live_family_tally((), covered_listed_station_days=15)
    assert tally.structural_dead is not None
    assert tally.structural_dead.evaluable is False
    assert tally.structural_dead.structural_dead is False
    assert tally.outcome == "UNDERPOWERED"
    rendered = tally_mod.render_markdown(tally, source_paths=(Path("x"),), as_of="2026-09-04")
    assert "SKIPPED" in rendered


def test_a_settled_only_fill_count_smaller_than_rows_is_refused(tally_mod: ModuleType) -> None:
    """`filled_takes` must be a superset of the scored rows -- a caller that
    accidentally wires in a settled-only count smaller than `len(rows)` is
    refused outright rather than silently trusted."""
    rows = (_trial(_live_id("LAX", "2026-08-01"), station="LAX", held=True),)
    with pytest.raises(ValueError, match="settled-only count"):
        tally_mod.build_live_family_tally(
            rows, covered_listed_station_days=15, filled_takes=0
        )


# ---------------------------------------------------------------------------
# Pre-change fixture pin: every OTHER field is byte-for-byte/value-for-value
# identical to what `build_live_family_tally` produced before this stop was
# wired in -- only `structural_dead` is new (and `None` by default).
# ---------------------------------------------------------------------------


def _assert_unchanged_from_pre_structural_dead_fixture(tally: object, expected: dict) -> None:
    for field_name, expected_value in expected.items():
        actual = getattr(tally, field_name)
        assert actual == expected_value, f"{field_name}: {actual!r} != {expected_value!r}"


def test_pre_change_kill_fixture_every_other_field_pinned(tally_mod: ModuleType) -> None:
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
    assert tally.structural_dead is None
    _assert_unchanged_from_pre_structural_dead_fixture(
        tally,
        {
            "outcome": "KILL",
            "n_scored": 60,
            "n_excluded": 0,
            "total_pnl": Decimal("-48.00"),
        },
    )
    assert tally.pooled is not None and tally.pooled.n == 60 and tally.pooled.cell_dead


def test_pre_change_underpowered_fixture_every_other_field_pinned(tally_mod: ModuleType) -> None:
    rows = tuple(
        _trial(_live_id("LAX", f"2026-08-{d:02d}"), station="LAX", held=True)
        for d in range(1, 6)
    )
    tally = tally_mod.build_live_family_tally(rows)
    assert tally.structural_dead is None
    _assert_unchanged_from_pre_structural_dead_fixture(
        tally,
        {
            "outcome": "UNDERPOWERED",
            "detail": "n=5; not dead, not (yet) a SURVIVE",
            "n_scored": 5,
            "n_excluded": 0,
            "total_pnl": Decimal("2.75"),
        },
    )
    assert tally.pooled is not None and tally.pooled.n == 5
