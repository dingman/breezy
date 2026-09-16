"""RED-first tests for `read_scored_trials_pooled` (defect fix, 2026-09-16).

Context: `cbd5fec` made the scheduled scorer (`score-live-trials-run.sh`)
write each REGISTERED family's rows to its OWN
`<store>/<family_id>/` subdirectory (L-38: `family_tally_v2.py`'s
contamination barrier forbids a shared top-level store). `read_scored_trials`
itself is non-recursive (`directory.glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}")`),
so every caller that still points it at the TOP-LEVEL store directory now
silently reads zero rows. `read_scored_trials_pooled` is the shared fix: it
reads the union of every per-family subdirectory PLUS any legacy top-level
parquet files (the pre-L-38 layout), and reports a per-source row-count
breakdown for callers that want to render one.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from breezy.persistence.scored_trial_store import (
    read_scored_trials,
    read_scored_trials_pooled,
    write_scored_trials,
)
from breezy.settlement.trial_scorer import ScoredTrial

_BASE_NS = 1_757_000_000_000_000_000


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


def _rows(n: int, *, prefix: str) -> tuple[ScoredTrial, ...]:
    return tuple(
        _trial(f"current_rung_hold/trial/{prefix}/2026-08-{i + 1:02d}") for i in range(n)
    )


def test_two_family_subdirectories_pool_to_the_union_with_a_breakdown(
    tmp_path: Path,
) -> None:
    base = tmp_path / "scored_trials"
    write_scored_trials(base / "pm_us_crh_v2", _rows(3, prefix="pm"), now_ns=1)
    write_scored_trials(base / "kalshi_crh_v1", _rows(1, prefix="kalshi"), now_ns=2)

    pooled = read_scored_trials_pooled(base)

    assert len(pooled.rows) == 4
    assert dict(pooled.family_counts) == {"pm_us_crh_v2": 3, "kalshi_crh_v1": 1}


def test_legacy_top_level_only_layout_still_works(tmp_path: Path) -> None:
    base = tmp_path / "scored_trials"
    write_scored_trials(base, _rows(2, prefix="legacy"), now_ns=1)

    pooled = read_scored_trials_pooled(base)

    assert len(pooled.rows) == 2
    assert set(pooled.rows) == set(read_scored_trials(base))
    assert len(pooled.family_counts) == 1
    _label, count = pooled.family_counts[0]
    assert count == 2


def test_legacy_and_per_family_rows_both_pool_when_both_are_present(
    tmp_path: Path,
) -> None:
    base = tmp_path / "scored_trials"
    write_scored_trials(base, _rows(2, prefix="legacy"), now_ns=1)
    write_scored_trials(base / "pm_us_crh_v2", _rows(3, prefix="pm"), now_ns=1)

    pooled = read_scored_trials_pooled(base)

    assert len(pooled.rows) == 5
    counts = dict(pooled.family_counts)
    assert counts["pm_us_crh_v2"] == 3
    assert sum(counts.values()) == 5


def test_an_absent_store_returns_no_rows_and_no_breakdown(tmp_path: Path) -> None:
    pooled = read_scored_trials_pooled(tmp_path / "does_not_exist")
    assert pooled.rows == ()
    assert pooled.family_counts == ()


def test_an_empty_store_directory_returns_no_rows_and_no_breakdown(
    tmp_path: Path,
) -> None:
    base = tmp_path / "scored_trials"
    base.mkdir()
    pooled = read_scored_trials_pooled(base)
    assert pooled.rows == ()
    assert pooled.family_counts == ()


def test_a_subdirectory_with_no_parquet_files_is_never_counted(tmp_path: Path) -> None:
    base = tmp_path / "scored_trials"
    (base / "empty_family").mkdir(parents=True)
    pooled = read_scored_trials_pooled(base)
    assert pooled.rows == ()
    assert pooled.family_counts == ()
