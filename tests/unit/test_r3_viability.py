"""RED-first tests for `scripts/analysis/r3_viability.py` (R3-VIABILITY plan
r1 §3.5/§4, tests 8-9; r2 delta "R3V-b").

Drives the module's pure functions directly against synthetic
`ReplayResult`/`ReplaySufficiency` rows -- never the real
`~/.local/share/breezy/derived/replay/replay_results.jsonl` (binding brief
constraint: "Never read the live ... replay_results.jsonl in a test").
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import hypothesis_register
import r3_viability as viability

from breezy.analysis.replay_results import (
    REPLAY_RESULTS_SCHEMA_VERSION,
    REPLAY_VALIDITY,
    ReplayResult,
    append_replay_result,
)
from breezy.analysis.replay_sufficiency import (
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    ReplaySufficiency,
    write_replay_sufficiency,
)

STATION = "SFO"
STRATEGY = "continuous_rung_hold"
LAG_MINUTES = 30
FREEZE = viability.FREEZE_CLIMATE_DAY


def _sufficiency_row(
    *,
    station: str = STATION,
    climate_day: str,
    verdict: str = "SUFFICIENT",
    window_complete: bool = True,
    coverage_kind: str = "WHOLE",
) -> ReplaySufficiency:
    return ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=station,
        climate_day=climate_day,
        verdict=verdict,  # type: ignore[arg-type]
        reason="",
        winner_instance_id="5a111bca-0000-0000-0000-000000000000",
        depth_window_minutes=300.0,
        quote_window_minutes=300.0,
        distinct_instruments=4,
        computed_day="2026-09-25",
        window_start_ns=0,
        window_end_ns=18_000_000_000_000,
        winner_first_in_window_ns=1_000,
        winner_last_in_window_ns=2_000,
        window_complete=window_complete,
        live_instance_count=0,
        coverage_kind=coverage_kind,
        excluded_fragments=(),
    )


def _result_row(
    *,
    station: str = STATION,
    climate_day: str,
    outcome: str = "COMPLETED",
    fills: int = 1,
    refusal_counts: dict[str, int] | None = None,
) -> ReplayResult:
    return ReplayResult(
        schema_version=REPLAY_RESULTS_SCHEMA_VERSION,
        run_ts="2026-09-25T15:50:00+00:00",
        station=station,
        climate_day=climate_day,
        strategy=STRATEGY,
        lag_minutes=LAG_MINUTES,
        outcome=outcome,  # type: ignore[arg-type]
        validity=REPLAY_VALIDITY,
        blocked_reason=None,
        exception_type=None,
        family_id="pm_us_crh_v4",
        manifest_sha256="a" * 64,
        manifest_taker_fee_coefficient="0.0695",
        engine_required_fee_coefficient="0.0695",
        engine_params_source="FAMILY_MANIFEST",
        params_match=True,
        composition_kind="continuous_rung_hold",
        tape_instance_id="5a111bca-0000-0000-0000-000000000000",
        sufficiency_reason="",
        trials=max(fills, 1),
        fills=fills,
        fill_price_vs_decision_ask=("0.01",) if fills else (),
        refusal_counts=refusal_counts or {},
        wall_s=10.0,
        peak_rss_bytes=1_000,
        parquet_sha256=None,
        window_complete=True,
        replayed_first_ns=1_000,
        replayed_last_ns=2_000,
        census_schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    )


# ---------------------------------------------------------------------------
# Freeze date sourcing (r2 delta item 2: no new literal)
# ---------------------------------------------------------------------------


def test_freeze_climate_day_is_sourced_from_archive_recal_not_no_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CRITICAL fix (code review, 2026-09-28): the tape freeze is owned by
    `H-ARCHIVE-RECAL-2026-09` (`EDGE-4_DISPOSITION_2026-09-27.md:6,19`:
    "the freeze commit on 2026-09-25" is that hypothesis's own bar), not
    `H-NO-SIDE-2026-09` -- `NO_SIDE_RULING_DATE` equals the same date today
    only by coincidence. A bare value-equality assertion cannot catch a
    wrong-source bug when the two constants coincide, so this pins SOURCE:
    monkeypatch `NO_SIDE_RULING_DATE` to a different date and reload --
    `FREEZE_CLIMATE_DAY` must not move, because it must never have been
    wired to it in the first place."""
    assert viability.FREEZE_CLIMATE_DAY == hypothesis_register.ARCHIVE_RECAL_RULING_DATE
    assert viability.FREEZE_CLIMATE_DAY == "2026-09-25"

    monkeypatch.setattr(hypothesis_register, "NO_SIDE_RULING_DATE", "2099-01-01")
    try:
        importlib.reload(viability)
        assert viability.FREEZE_CLIMATE_DAY == hypothesis_register.ARCHIVE_RECAL_RULING_DATE
        assert viability.FREEZE_CLIMATE_DAY != "2099-01-01"
    finally:
        monkeypatch.undo()
        importlib.reload(viability)


# ---------------------------------------------------------------------------
# required_f() (r1 test 9 / r2 delta item 4)
# ---------------------------------------------------------------------------


def test_required_f_is_0_625() -> None:
    assert viability.required_f() == pytest.approx(0.625)


# ---------------------------------------------------------------------------
# Wilson interval wiring (r1 test 9 / r2 delta item 6: Wilson(2,5))
# ---------------------------------------------------------------------------


def test_wilson_2_5_matches_the_expected_interval() -> None:
    sufficiency = [_sufficiency_row(climate_day=f"2026-09-0{i}") for i in range(1, 6)]
    results = [
        _result_row(climate_day="2026-09-01", fills=1),
        _result_row(climate_day="2026-09-02", fills=1),
        _result_row(climate_day="2026-09-03", fills=0),
        _result_row(climate_day="2026-09-04", fills=0),
        _result_row(climate_day="2026-09-05", fills=0),
    ]
    result = viability.compute_viability(results=results, sufficiency=sufficiency)
    assert result.k == 2
    assert result.n == 5
    assert result.wilson_lower == pytest.approx(0.1176, abs=1e-4)
    assert result.wilson_upper == pytest.approx(0.7693, abs=1e-4)


# ---------------------------------------------------------------------------
# n=35 k=16/k=17 boundary (r2 delta item 6)
# ---------------------------------------------------------------------------


def _corpus(n: int, k: int) -> tuple[list[ReplayResult], list[ReplaySufficiency]]:
    """`n` eligible pre-freeze whole-day COMPLETED rows across `n` distinct
    stations-in-name-only climate days, `k` of them with a fill."""
    days = [f"2026-08-{(i % 25) + 1:02d}" for i in range(n)]
    sufficiency = [_sufficiency_row(climate_day=day) for day in days]
    results = [
        _result_row(climate_day=day, fills=1 if i < k else 0)
        for i, day in enumerate(days)
    ]
    return results, sufficiency


def test_n_35_k_16_is_not_viable() -> None:
    results, sufficiency = _corpus(35, 16)
    result = viability.compute_viability(results=results, sufficiency=sufficiency)
    assert result.n == 35
    assert result.k == 16
    assert result.wilson_upper == pytest.approx(0.618, abs=1e-3)
    assert result.verdict == "NOT_VIABLE"


def test_n_35_k_17_is_not_not_viable() -> None:
    results, sufficiency = _corpus(35, 17)
    result = viability.compute_viability(results=results, sufficiency=sufficiency)
    assert result.n == 35
    assert result.k == 17
    assert result.wilson_upper == pytest.approx(0.644, abs=1e-3)
    assert result.verdict != "NOT_VIABLE"
    assert result.verdict == "VIABLE"


# ---------------------------------------------------------------------------
# n < 20 -> INSUFFICIENT_N (r2 delta item 6)
# ---------------------------------------------------------------------------


def test_n_below_20_gives_insufficient_n() -> None:
    results, sufficiency = _corpus(19, 19)
    result = viability.compute_viability(results=results, sufficiency=sufficiency)
    assert result.n == 19
    assert result.verdict == "INSUFFICIENT_N"


def test_n_at_20_is_not_insufficient() -> None:
    results, sufficiency = _corpus(20, 20)
    result = viability.compute_viability(results=results, sufficiency=sufficiency)
    assert result.n == 20
    assert result.verdict != "INSUFFICIENT_N"


# ---------------------------------------------------------------------------
# eligible_rows() exclusions (r2 delta item 1 / FIREWALL)
# ---------------------------------------------------------------------------


def test_eligible_rows_excludes_a_climate_day_after_the_freeze() -> None:
    post_freeze_day = "2026-09-26"
    assert post_freeze_day > FREEZE
    sufficiency = [_sufficiency_row(climate_day=post_freeze_day)]
    results = [_result_row(climate_day=post_freeze_day, fills=1)]
    eligible = viability.eligible_rows(results=results, sufficiency=sufficiency)
    assert eligible == ()


def test_eligible_rows_includes_the_freeze_day_itself() -> None:
    """The firewall binds strictly AFTER the freeze date -- the freeze date
    itself counts as pre-freeze (r2 delta item 2)."""
    sufficiency = [_sufficiency_row(climate_day=FREEZE)]
    results = [_result_row(climate_day=FREEZE, fills=1)]
    eligible = viability.eligible_rows(results=results, sufficiency=sufficiency)
    assert len(eligible) == 1


def test_eligible_rows_excludes_a_fee_void_row() -> None:
    day = "2026-09-01"
    sufficiency = [_sufficiency_row(climate_day=day)]
    results = [
        _result_row(climate_day=day, fills=1, refusal_counts={"fee_schedule_mismatch": 1}),
    ]
    eligible = viability.eligible_rows(results=results, sufficiency=sufficiency)
    assert eligible == ()


def test_eligible_rows_excludes_a_non_whole_day() -> None:
    day = "2026-09-01"
    sufficiency = [_sufficiency_row(climate_day=day, coverage_kind="FRAGMENT")]
    results = [_result_row(climate_day=day, fills=1)]
    eligible = viability.eligible_rows(results=results, sufficiency=sufficiency)
    assert eligible == ()


def test_eligible_rows_excludes_a_non_completed_outcome() -> None:
    day = "2026-09-01"
    sufficiency = [_sufficiency_row(climate_day=day)]
    results = [_result_row(climate_day=day, outcome="FAILED", fills=0)]
    eligible = viability.eligible_rows(results=results, sufficiency=sufficiency)
    assert eligible == ()


# ---------------------------------------------------------------------------
# FIREWALL spy: `fills` is never read on a post-freeze row
# ---------------------------------------------------------------------------


class _FillsReadSpy:
    """Duck-typed `ReplayResult` stand-in whose `fills` property records
    every read. `eligible_rows`/`compute_viability` only ever consult
    `.station`/`.climate_day`/`.outcome`/`.refusal_counts` for a row's own
    pre-freeze and eligibility checks; `.fills` must not be touched until
    AFTER the row has already passed the pre-freeze test."""

    def __init__(self, *, station: str, climate_day: str, outcome: str, fills: int, log: list[str]):
        self._station = station
        self._climate_day = climate_day
        self._outcome = outcome
        self._fills = fills
        self._log = log

    @property
    def station(self) -> str:
        return self._station

    @property
    def climate_day(self) -> str:
        return self._climate_day

    @property
    def outcome(self) -> str:
        return self._outcome

    @property
    def refusal_counts(self) -> dict[str, int]:
        return {}

    @property
    def fills(self) -> int:
        self._log.append(self._climate_day)
        return self._fills


def test_fills_is_never_read_on_a_post_freeze_row() -> None:
    post_freeze_day = "2026-09-26"
    pre_freeze_day = "2026-09-01"
    log: list[str] = []
    rows = [
        _FillsReadSpy(
            station=STATION, climate_day=post_freeze_day, outcome="COMPLETED", fills=1, log=log,
        ),
        _FillsReadSpy(
            station=STATION, climate_day=pre_freeze_day, outcome="COMPLETED", fills=1, log=log,
        ),
    ]
    sufficiency = [
        _sufficiency_row(climate_day=post_freeze_day),
        _sufficiency_row(climate_day=pre_freeze_day),
    ]
    result = viability.compute_viability(results=rows, sufficiency=sufficiency)
    assert post_freeze_day not in log
    assert pre_freeze_day in log
    assert result.n == 1
    assert result.k == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_prints_k_n_wilson_bounds_f_req_and_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    results_path = tmp_path / "replay_results.jsonl"
    sufficiency_path = tmp_path / "replay_sufficiency.jsonl"
    write_replay_sufficiency(sufficiency_path, [_sufficiency_row(climate_day="2026-09-01")])
    append_replay_result(results_path, _result_row(climate_day="2026-09-01", fills=1))

    exit_code = viability.main(
        ["--replay-results", str(results_path), "--replay-sufficiency", str(sufficiency_path)]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "k=1" in out
    assert "n=1" in out
    assert "f_req=0.6250" in out
    assert "verdict=INSUFFICIENT_N" in out
