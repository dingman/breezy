"""Whole-tape paper replay tests for the 2026-09-05 build."""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_current_driver() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py"
    spec = importlib.util.spec_from_file_location("current_rung_hold_paper_replay", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_whole_driver() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "whole_tape_paper_replay.py"
    spec = importlib.util.spec_from_file_location("whole_tape_paper_replay", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def current_driver() -> ModuleType:
    return _load_current_driver()


@pytest.fixture(scope="module")
def whole_driver() -> ModuleType:
    return _load_whole_driver()


@dataclass(frozen=True, slots=True)
class _Facts:
    settlement_station: str
    climate_day: dt.date


def _quote(ts_event: int, ask: str = "0.40") -> SimpleNamespace:
    return SimpleNamespace(ts_event=ts_event, ask_price=Decimal(ask), ask_size=Decimal(5))


def _depth(ts_event: int, ask: str = "0.40") -> SimpleNamespace:
    level = SimpleNamespace(price=Decimal(ask), size=Decimal(5))
    return SimpleNamespace(ts_event=ts_event, asks=(level,))


def _ti(
    *,
    station: str,
    day: dt.date,
    quote_ts: tuple[int, ...],
    depth_ts: tuple[int, ...] = (),
    instrument_id: str = "inst",
) -> SimpleNamespace:
    return SimpleNamespace(
        instrument=SimpleNamespace(id=instrument_id),
        facts=_Facts(settlement_station=station, climate_day=day),
        quotes=[_quote(ts) for ts in quote_ts],
        depths=[_depth(ts) for ts in depth_ts],
        closes=[],
    )


def test_paper_replay_refuses_both_live_scored_trials_roots(
    current_driver: ModuleType,
    tmp_path: Path,
) -> None:
    with pytest.raises(current_driver.VenueOutsideLiveDirError):
        current_driver.assert_paper_write_path_is_not_live(
            tmp_path / "derived" / "scored_trials",
        )
    with pytest.raises(current_driver.VenueOutsideLiveDirError):
        current_driver.assert_paper_write_path_is_not_live(
            tmp_path / "derived" / "live" / "scored_trials",
        )
    current_driver.assert_paper_write_path_is_not_live(
        tmp_path / "derived" / "paper_replay" / "scored_trials",
    )


def test_classification_lists_corrupt_empty_live_and_preflight_errors(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Report:
        total_rows = 12

    monkeypatch.setattr(whole_driver, "list_instance_ids", lambda *_args: ["c", "e", "l", "x"])

    def scan(_root: Path, instance_id: str, _subdir: str) -> _Report:
        if instance_id == "x":
            raise whole_driver.PreflightError("bad instance")
        return _Report()

    verdicts = {"c": "CLEAN", "e": "EMPTY", "l": "LIVE"}
    monkeypatch.setattr(whole_driver, "scan_instance", scan)
    monkeypatch.setattr(whole_driver, "classify_instance", lambda report, now_ns: verdicts[now_ns])

    rows = whole_driver.classify_tape_instances(
        tmp_path,
        now_ns="c",
        classifier=lambda _report, *, now_ns: "CLEAN",
    )
    assert [(row.instance_id, row.verdict) for row in rows] == [
        ("c", "CLEAN"),
        ("e", "CLEAN"),
        ("l", "CLEAN"),
        ("x", "PREFLIGHT_ERROR"),
    ]


def test_corrupt_only_station_days_are_blocked_not_denominator(
    whole_driver: ModuleType,
) -> None:
    clean = {("LAX", dt.date(2026, 9, 1))}
    corrupt = {("LAX", dt.date(2026, 9, 1)), ("SFO", dt.date(2026, 9, 1))}
    blocked = whole_driver.corrupt_only_blocked_days(
        clean_station_days=clean, corrupt_station_days=corrupt
    )
    assert blocked == {("SFO", dt.date(2026, 9, 1)): "CORRUPT_ONLY"}


def test_station_coverage_filters_quote_ticks_to_that_station(
    whole_driver: ModuleType,
) -> None:
    day = dt.date(2026, 9, 1)
    # LAX has only an 08:00 LST quote; SFO has a 12:00 LST quote. SFO must
    # not launder LAX into replay eligibility.
    instruments = [
        _ti(station="LAX", day=day, quote_ts=(16 * 3_600_000_000_000,)),
        _ti(station="SFO", day=day, quote_ts=(20 * 3_600_000_000_000,)),
    ]
    with pytest.raises(whole_driver.StationDayBlockedError, match="EMPTY_WINDOW"):
        whole_driver.assert_station_window_coverage(
            instruments,
            station="LAX",
            std_utc_offset_hours=-8.0,
        )
    whole_driver.assert_station_window_coverage(
        instruments,
        station="SFO",
        std_utc_offset_hours=-8.0,
    )


def test_unique_winner_uses_first_in_window_quote_not_longest_span(
    whole_driver: ModuleType,
) -> None:
    day = dt.date(2026, 9, 1)
    early_first = 20 * 3_600_000_000_000
    late_first = early_first + 235 * 60_000_000_000
    early = whole_driver.CleanInstance(
        instance_id="20-minute",
        tape_instruments=[
            _ti(station="LAX", day=day, quote_ts=(early_first,), depth_ts=(early_first,))
        ],
    )
    late = whole_driver.CleanInstance(
        instance_id="255-minute",
        tape_instruments=[
            _ti(
                station="LAX",
                day=day,
                quote_ts=(late_first, late_first + 200 * 60_000_000_000),
                depth_ts=(late_first,),
            )
        ],
    )
    winners, blocked = whole_driver.select_unique_clean_winners(
        [late, early],
        std_utc_offset_hours_by_station={"LAX": -8.0},
    )
    assert blocked == {}
    assert winners[("LAX", day)].instance_id == "20-minute"


def test_winner_tape_instruments_exclude_other_stations_and_days_on_the_same_clean_instance(
    whole_driver: ModuleType,
) -> None:
    """A CLEAN instance carries every station-day it captured, merged into one
    `tape_instruments` list. A `Winner` for ONE `(station, climate_day)` must
    carry only ITS OWN instruments -- passing the whole instance's instrument
    set into `run_one_precision_arm` lets a fill on another day's (or
    station's) instrument masquerade as this day's trial (observed as a
    genuine `EntryAskFromLatchMissingError` crash on the real quote-tape
    catalog: a fill on `...-2026-09-01-...` while replaying `SFO/2026-08-31`).
    """
    lax_day = dt.date(2026, 9, 1)
    sfo_day_1 = dt.date(2026, 8, 31)
    sfo_day_2 = dt.date(2026, 9, 1)
    instance = whole_driver.CleanInstance(
        instance_id="mixed",
        tape_instruments=[
            _ti(station="LAX", day=lax_day, quote_ts=(20 * 3_600_000_000_000,)),
            _ti(
                station="SFO",
                day=sfo_day_1,
                quote_ts=(20 * 3_600_000_000_000,),
                instrument_id="sfo-day1",
            ),
            _ti(
                station="SFO",
                day=sfo_day_2,
                quote_ts=(20 * 3_600_000_000_000,),
                instrument_id="sfo-day2",
            ),
        ],
    )
    winners, blocked = whole_driver.select_unique_clean_winners(
        [instance],
        std_utc_offset_hours_by_station={"LAX": -8.0, "SFO": -8.0},
    )
    assert blocked == {}
    sfo_day1_winner = winners[("SFO", sfo_day_1)]
    assert {ti.instrument.id for ti in sfo_day1_winner.tape_instruments} == {"sfo-day1"}
    sfo_day2_winner = winners[("SFO", sfo_day_2)]
    assert {ti.instrument.id for ti in sfo_day2_winner.tape_instruments} == {"sfo-day2"}
    lax_winner = winners[("LAX", lax_day)]
    assert {ti.instrument.id for ti in lax_winner.tape_instruments} == {"inst"}


def test_dual_cover_of_the_first_instant_is_blocked(
    whole_driver: ModuleType,
) -> None:
    day = dt.date(2026, 9, 1)
    first = 20 * 3_600_000_000_000
    instances = [
        whole_driver.CleanInstance("a", [_ti(station="LAX", day=day, quote_ts=(first,))]),
        whole_driver.CleanInstance("b", [_ti(station="LAX", day=day, quote_ts=(first,))]),
    ]
    winners, blocked = whole_driver.select_unique_clean_winners(
        instances,
        std_utc_offset_hours_by_station={"LAX": -8.0},
    )
    assert winners == {}
    assert blocked[("LAX", day)] == "DUAL_COVER_FIRST_INSTANT"


def test_replay_calls_nws_integer_precision_arm_only_with_unique_work_catalogs(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    day = dt.date(2026, 9, 1)
    candidate = whole_driver.Winner(
        station="LAX",
        climate_day=day,
        instance_id="abc",
        first_quote_ts=20 * 3_600_000_000_000,
        tape_instruments=[_ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,))],
    )
    calls: list[tuple[int, str, Path]] = []

    def fake_arm(**kwargs: object) -> SimpleNamespace:
        calls.append(
            (
                kwargs["lag_minutes"],  # type: ignore[index]
                kwargs["precision_mode"],  # type: ignore[index]
                kwargs["latch_store_path"],  # type: ignore[index]
            )
        )
        return SimpleNamespace(trials=(), strategy_refusals={}, strategy_diagnostics={})

    monkeypatch.setattr(whole_driver, "run_one_precision_arm", fake_arm)
    result = whole_driver.replay_candidate_lags(
        candidate,
        lags=(30, 45),
        output_root=tmp_path / "paper",
        work_root=tmp_path / "work",
        observation_rows=[],
        settlement_by_key={},
        now_ns=lambda: 100,
    )

    assert [call[0] for call in calls] == [30, 45]
    assert {call[1] for call in calls} == {"nws_integer_c"}
    assert calls[0][2] != calls[1][2]
    assert all("precision_mode" not in item.argv for item in result.attempts)


def test_existing_scored_trials_parquet_skips_that_lag_only(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    day = dt.date(2026, 9, 1)
    candidate = whole_driver.Winner(
        station="LAX",
        climate_day=day,
        instance_id="abc",
        first_quote_ts=20 * 3_600_000_000_000,
        tape_instruments=[_ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,))],
    )
    # finding 2: the skip sentinel is the atomic REPLAY_COMPLETE marker this
    # wrapper itself writes -- never a `scored_trials_*.parquet` glob that
    # this wrapper never produces (it writes `mechanism_trials.*`).
    existing = tmp_path / "paper" / "scored_trials" / "LAX" / day.isoformat() / "lag_30"
    existing.mkdir(parents=True)
    (existing / "mechanism_trials.parquet").write_bytes(b"existing")
    (existing / whole_driver._REPLAY_COMPLETE_MARKER).write_text("ok\n", encoding="utf-8")
    calls: list[int] = []
    monkeypatch.setattr(
        whole_driver,
        "run_one_precision_arm",
        lambda **kwargs: (
            calls.append(kwargs["lag_minutes"])  # type: ignore[index]
            or SimpleNamespace(trials=(), strategy_refusals={}, strategy_diagnostics={})
        ),
    )

    result = whole_driver.replay_candidate_lags(
        candidate,
        lags=(30, 45),
        output_root=tmp_path / "paper",
        work_root=tmp_path / "work",
        observation_rows=[],
        settlement_by_key={},
        now_ns=lambda: 200,
    )
    assert calls == [45]
    assert [attempt.status for attempt in result.attempts] == ["SKIPPED_EXISTING", "RAN"]


def test_a_genuinely_completed_replay_skips_the_same_lag_on_rerun(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    day = dt.date(2026, 9, 1)
    candidate = whole_driver.Winner(
        station="LAX",
        climate_day=day,
        instance_id="abc",
        first_quote_ts=20 * 3_600_000_000_000,
        tape_instruments=[_ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,))],
    )
    calls: list[int] = []
    monkeypatch.setattr(
        whole_driver,
        "run_one_precision_arm",
        lambda **kwargs: (
            calls.append(kwargs["lag_minutes"])  # type: ignore[index]
            or SimpleNamespace(trials=(), strategy_refusals={}, strategy_diagnostics={})
        ),
    )
    kwargs = {
        "lags": (30,),
        "output_root": tmp_path / "paper",
        "work_root": tmp_path / "work",
        "observation_rows": [],
        "settlement_by_key": {},
    }
    first = whole_driver.replay_candidate_lags(candidate, now_ns=lambda: 1, **kwargs)
    assert first.attempts[0].status == "RAN"
    assert calls == [30]

    second = whole_driver.replay_candidate_lags(candidate, now_ns=lambda: 2, **kwargs)
    assert second.attempts[0].status == "SKIPPED_EXISTING"
    assert calls == [30]  # not called again


def test_crash_before_the_completion_marker_reruns_rather_than_skipping(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    day = dt.date(2026, 9, 1)
    candidate = whole_driver.Winner(
        station="LAX",
        climate_day=day,
        instance_id="abc",
        first_quote_ts=20 * 3_600_000_000_000,
        tape_instruments=[_ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,))],
    )
    # Simulates a crash between `_write_mechanism_trials` finishing and the
    # completion marker being written: the trial artefact is on disk, the
    # marker is not.
    output_dir = tmp_path / "paper" / "scored_trials" / "LAX" / day.isoformat() / "lag_30"
    output_dir.mkdir(parents=True)
    (output_dir / "mechanism_trials.parquet").write_bytes(b"partial")
    calls: list[int] = []
    monkeypatch.setattr(
        whole_driver,
        "run_one_precision_arm",
        lambda **kwargs: (
            calls.append(kwargs["lag_minutes"])  # type: ignore[index]
            or SimpleNamespace(trials=(), strategy_refusals={}, strategy_diagnostics={})
        ),
    )
    result = whole_driver.replay_candidate_lags(
        candidate,
        lags=(30,),
        output_root=tmp_path / "paper",
        work_root=tmp_path / "work",
        observation_rows=[],
        settlement_by_key={},
        now_ns=lambda: 3,
    )
    assert calls == [30]
    assert result.attempts[0].status == "RAN"


def test_report_header_caveat_and_no_wilson_or_roi(whole_driver: ModuleType) -> None:
    day = dt.date(2026, 9, 1)
    attempts = [
        whole_driver.ReplayAttempt(
            station="LAX",
            climate_day=day,
            lag_minutes=30,
            output_dir=Path("."),
            work_catalog=Path("."),
            status="RAN",
            n_trials=1,
        ),
    ]
    report = whole_driver.render_report(
        station_day_counts={"replayed": 1, "BLOCKED:CORRUPT_ONLY": 1, "BLOCKED:EMPTY_WINDOW": 1},
        classifications=[],
        attempts=attempts,
        take_rate_denominator=1,
    )
    assert report.startswith("MECHANISM TEST -- NO VERDICT")
    assert whole_driver.LOOK_AHEAD_CAVEAT in report
    assert "lag 30: 1/1" in report
    assert "Wilson" not in report
    assert "ROI" not in report


# ---------------------------------------------------------------------------
# Defect fix: take-rate is reported PER LAG ARM, never pooled across arms
# (grok_whole_tape_replay_plan_review_2026-09-05 finding 2).
# ---------------------------------------------------------------------------


def test_report_take_rate_is_per_lag_arm_never_pooled(whole_driver: ModuleType) -> None:
    day1 = dt.date(2026, 9, 1)
    day2 = dt.date(2026, 9, 2)

    def _attempt(station: str, day: dt.date, lag: int) -> object:
        return whole_driver.ReplayAttempt(
            station=station,
            climate_day=day,
            lag_minutes=lag,
            output_dir=Path("."),
            work_catalog=Path("."),
            status="RAN",
            n_trials=1,
        )

    # 2 eligible station-days, both took at BOTH lag arms.
    attempts = [
        _attempt("LAX", day1, 30),
        _attempt("LAX", day1, 45),
        _attempt("SFO", day2, 30),
        _attempt("SFO", day2, 45),
    ]
    report = whole_driver.render_report(
        station_day_counts={"eligible_clean_unique_winner": 2, "replayed": 2},
        classifications=[],
        attempts=attempts,
        take_rate_denominator=2,
    )
    assert "lag 30: 2/2" in report
    assert "lag 45: 2/2" in report
    # A pooled sum-of-arms-over-station-days figure must never appear.
    assert "4/2" not in report
    assert "take-rate:" not in report


# ---------------------------------------------------------------------------
# Finding 1: output-root containment
# ---------------------------------------------------------------------------


def test_output_root_containment_refuses_paths_outside_derived_root(
    whole_driver: ModuleType, tmp_path: Path
) -> None:
    derived_root = tmp_path / "derived_root"
    for bad in (
        tmp_path / "repo" / "derived" / "paper_replay",
        tmp_path / "repo" / "derived" / "scored_trials",
        tmp_path / "repo" / "derived" / "live" / "scored_trials",
        tmp_path / "elsewhere",
    ):
        with pytest.raises(whole_driver.PaperReplayOutputNotContainedError):
            whole_driver.assert_output_root_is_contained(bad, derived_root=derived_root)

    ok = derived_root / "paper_replay" / "x"
    contained = whole_driver.assert_output_root_is_contained(ok, derived_root=derived_root)
    assert contained == ok.resolve()
    # The containment root itself (no subdirectory) is also contained.
    assert whole_driver.assert_output_root_is_contained(
        derived_root / "paper_replay", derived_root=derived_root
    ) == (derived_root / "paper_replay").resolve()


def test_default_derived_root_honours_the_env_override(
    whole_driver: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom = tmp_path / "custom_derived"
    monkeypatch.setenv(whole_driver.DERIVED_ROOT_ENV_VAR, str(custom))
    assert whole_driver.default_derived_root() == custom

    monkeypatch.delenv(whole_driver.DERIVED_ROOT_ENV_VAR, raising=False)
    expected_default = Path.home() / ".local" / "share" / "breezy" / "derived"
    assert whole_driver.default_derived_root() == expected_default


def test_run_refuses_an_uncontained_output_root_before_any_write(
    whole_driver: ModuleType, tmp_path: Path
) -> None:
    output_root = tmp_path / "repo_root" / "derived" / "paper_replay"
    with pytest.raises(whole_driver.PaperReplayOutputNotContainedError):
        whole_driver.run(
            quote_catalog=tmp_path / "catalog",
            output_root=output_root,
            work_root=output_root / "work",
            asos_cache_csv=tmp_path / "asos.csv",
            weather_catalog_root=tmp_path / "weather_catalog",
            dry_run=True,
            derived_root=tmp_path / "derived",
        )
    assert not output_root.exists()


# ---------------------------------------------------------------------------
# Finding 3: CORRUPT-only station-days populated through run()
# ---------------------------------------------------------------------------


def test_run_populates_corrupt_only_station_days_via_identity_only_read(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    day = dt.date(2026, 9, 1)
    clean_instance = whole_driver.CleanInstance(
        instance_id="clean1",
        tape_instruments=[_ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,))],
    )
    monkeypatch.setattr(
        whole_driver,
        "classify_tape_instances",
        lambda *_a, **_k: [
            whole_driver.TapeClassification("clean1", "CLEAN", total_rows=1),
            whole_driver.TapeClassification("corrupt1", "CORRUPT", total_rows=1),
        ],
    )
    monkeypatch.setattr(whole_driver, "_load_clean_instance", lambda **_k: clean_instance)
    monkeypatch.setattr(whole_driver, "_station_offsets", lambda _days: {"LAX": -8.0})

    fake_corrupt_instrument = SimpleNamespace(
        info={
            "weather_facts_status": "KNOWN",
            "settlement_station": "SFO",
            "climate_date": day.isoformat(),
            "measure": "high",
            "strike_lower_f": 70,
            "strike_upper_f": None,
        }
    )
    monkeypatch.setattr(whole_driver, "_load_stream", lambda *_a, **_k: [fake_corrupt_instrument])

    report = whole_driver.run(
        quote_catalog=tmp_path / "catalog",
        output_root=tmp_path / "derived" / "paper_replay",
        work_root=tmp_path / "derived" / "paper_replay" / "work",
        asos_cache_csv=tmp_path / "asos.csv",
        weather_catalog_root=tmp_path / "weather_catalog",
        dry_run=True,
        derived_root=tmp_path / "derived",
    )
    assert "BLOCKED:CORRUPT_ONLY: 1" in report


# ---------------------------------------------------------------------------
# Finding 4: malformed instrument facts are listed, not silently dropped
# ---------------------------------------------------------------------------


def test_load_clean_instance_lists_malformed_instruments_instead_of_dropping_them(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    day = dt.date(2026, 9, 1)
    good = SimpleNamespace(
        id="good.INST",
        info={
            "weather_facts_status": "KNOWN",
            "settlement_station": "LAX",
            "climate_date": day.isoformat(),
            "measure": "high",
            "strike_lower_f": 70,
            "strike_upper_f": None,
        },
    )
    missing_fields = SimpleNamespace(id="bad1.INST", info={})
    non_mapping_info = SimpleNamespace(id="bad2.INST", info=None)
    fake_catalog = SimpleNamespace(
        instruments=lambda: [good, missing_fields, non_mapping_info],
    )
    monkeypatch.setattr(whole_driver, "_convert_live_capture", lambda **_k: fake_catalog)
    good_ti = _ti(station="LAX", day=day, quote_ts=(1,))
    monkeypatch.setattr(
        whole_driver,
        "_select_capture_instruments",
        lambda _catalog, *, climate_day: [good_ti] if climate_day == day else [],
    )

    instance = whole_driver._load_clean_instance(
        quote_catalog=tmp_path / "catalog",
        instance_id="abc",
        subdirectory="live",
        work_root=tmp_path / "work",
        now_ns=lambda: 1,
    )
    assert {ti.instrument.id for ti in instance.tape_instruments} == {"inst"}
    assert set(instance.malformed_instrument_ids) == {"bad1.INST", "bad2.INST"}


# ---------------------------------------------------------------------------
# Finding 5: the look-ahead caveat rides on station_day_counts.csv
# ---------------------------------------------------------------------------


def test_station_day_counts_csv_carries_the_lookahead_caveat(
    whole_driver: ModuleType, tmp_path: Path
) -> None:
    output_root = tmp_path / "paper"
    counts = {"replayed": 2, "BLOCKED:EMPTY_WINDOW": 1}
    whole_driver._write_report_bundle(output_root, "report body\n", counts)

    import csv as csv_module

    with (output_root / "station_day_counts.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv_module.DictReader(handle))
    assert rows, "expected at least one data row"
    for row in rows:
        assert row["lookahead_caveat"] == whole_driver.LOOK_AHEAD_CAVEAT


# ---------------------------------------------------------------------------
# Finding 6: cap labelling
# ---------------------------------------------------------------------------


def test_cap_label_partial_run_lists_the_selected_clean_instance_ids(
    whole_driver: ModuleType,
) -> None:
    report = whole_driver.render_report(
        station_day_counts={},
        classifications=[],
        attempts=[],
        take_rate_denominator=0,
        clean_instance_ids_loaded=["a"],
        clean_instances_total=3,
    )
    assert "PARTIAL RUN -- 1 of 3 CLEAN instances" in report
    assert "selected CLEAN instance ids: a" in report


def test_cap_label_whole_tape_when_uncapped(whole_driver: ModuleType) -> None:
    report = whole_driver.render_report(
        station_day_counts={},
        classifications=[],
        attempts=[],
        take_rate_denominator=0,
        clean_instance_ids_loaded=["a", "b"],
        clean_instances_total=2,
    )
    assert "WHOLE TAPE -- 2 of 2 CLEAN instances" in report
    assert "selected CLEAN instance ids" not in report


def test_run_records_loaded_and_total_clean_instance_counts(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    day = dt.date(2026, 9, 1)
    clean_instance = whole_driver.CleanInstance(
        instance_id="a",
        tape_instruments=[_ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,))],
    )
    monkeypatch.setattr(
        whole_driver,
        "classify_tape_instances",
        lambda *_a, **_k: [
            whole_driver.TapeClassification("a", "CLEAN", total_rows=1),
            whole_driver.TapeClassification("b", "CLEAN", total_rows=1),
            whole_driver.TapeClassification("c", "CLEAN", total_rows=1),
        ],
    )
    monkeypatch.setattr(whole_driver, "_load_clean_instance", lambda **_k: clean_instance)
    monkeypatch.setattr(whole_driver, "_station_offsets", lambda _days: {"LAX": -8.0})
    monkeypatch.setattr(whole_driver, "_load_stream", lambda *_a, **_k: [])

    report = whole_driver.run(
        quote_catalog=tmp_path / "catalog",
        output_root=tmp_path / "derived" / "paper_replay",
        work_root=tmp_path / "derived" / "paper_replay" / "work",
        asos_cache_csv=tmp_path / "asos.csv",
        weather_catalog_root=tmp_path / "weather_catalog",
        dry_run=True,
        derived_root=tmp_path / "derived",
        max_clean_instances=1,
    )
    assert "PARTIAL RUN -- 1 of 3 CLEAN instances" in report
    assert "selected CLEAN instance ids: a" in report

    import csv as csv_module

    with (tmp_path / "derived" / "paper_replay" / "station_day_counts.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        counts = {row["bucket"]: row["count"] for row in csv_module.DictReader(handle)}
    assert counts["clean_instances_loaded"] == "1"
    assert counts["clean_instances_total"] == "3"


def test_run_blocks_unsupported_stations_instead_of_crashing(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`CurrentRungHoldConfig` refuses NYC (hourly-only ASOS feed, A14) at
    construction. A real-catalog winner for NYC must be BLOCKED before
    `replay_candidate_lags` ever calls it -- not left to crash the whole
    run with `UnsupportedStationError`."""
    day = dt.date(2026, 9, 1)
    clean_instance = whole_driver.CleanInstance(
        instance_id="a",
        tape_instruments=[
            _ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,)),
            _ti(
                station="NYC",
                day=day,
                quote_ts=(20 * 3_600_000_000_000,),
                instrument_id="nyc-inst",
            ),
        ],
    )
    monkeypatch.setattr(
        whole_driver,
        "classify_tape_instances",
        lambda *_a, **_k: [whole_driver.TapeClassification("a", "CLEAN", total_rows=1)],
    )
    monkeypatch.setattr(whole_driver, "_load_clean_instance", lambda **_k: clean_instance)
    monkeypatch.setattr(
        whole_driver, "_station_offsets", lambda _days: {"LAX": -8.0, "NYC": -5.0}
    )
    monkeypatch.setattr(whole_driver, "_load_stream", lambda *_a, **_k: [])
    calls: list[str] = []
    monkeypatch.setattr(
        whole_driver,
        "run_one_precision_arm",
        lambda **kwargs: (
            calls.append(kwargs["station"])  # type: ignore[index]
            or SimpleNamespace(trials=(), strategy_refusals={}, strategy_diagnostics={})
        ),
    )
    monkeypatch.setattr(whole_driver, "read_asos_rows", lambda _path: [])
    monkeypatch.setattr(
        whole_driver,
        "climate_day_records_to_settlement",
        lambda *_a, **_k: {("LAX", day.isoformat()): object()},
    )

    report = whole_driver.run(
        quote_catalog=tmp_path / "catalog",
        output_root=tmp_path / "derived" / "paper_replay",
        work_root=tmp_path / "derived" / "paper_replay" / "work",
        asos_cache_csv=tmp_path / "asos.csv",
        weather_catalog_root=tmp_path / "weather_catalog",
        derived_root=tmp_path / "derived",
    )
    assert calls == ["LAX", "LAX"]  # one call per lag (30, 45); NYC never called
    assert "BLOCKED:UNSUPPORTED_STATION: 1" in report


def test_run_blocks_a_winner_with_no_final_settlement_record(
    whole_driver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`build_backtest_engine` refuses a run whose instruments have no
    `InstrumentClose` (`SettlementInvariantError`), and `_synthesize_close`
    only synthesizes one from a FINAL settlement record. A station-day with
    no FINAL record yet (e.g. today's still-open climate day) must be
    BLOCKED before `replay_candidate_lags` is ever called for it, not left
    to crash the whole run."""
    day = dt.date(2026, 9, 5)
    clean_instance = whole_driver.CleanInstance(
        instance_id="a",
        tape_instruments=[_ti(station="LAX", day=day, quote_ts=(20 * 3_600_000_000_000,))],
    )
    monkeypatch.setattr(
        whole_driver,
        "classify_tape_instances",
        lambda *_a, **_k: [whole_driver.TapeClassification("a", "CLEAN", total_rows=1)],
    )
    monkeypatch.setattr(whole_driver, "_load_clean_instance", lambda **_k: clean_instance)
    monkeypatch.setattr(whole_driver, "_station_offsets", lambda _days: {"LAX": -8.0})
    monkeypatch.setattr(whole_driver, "_load_stream", lambda *_a, **_k: [])
    calls: list[str] = []
    monkeypatch.setattr(
        whole_driver,
        "run_one_precision_arm",
        lambda **kwargs: (
            calls.append(kwargs["station"])  # type: ignore[index]
            or SimpleNamespace(trials=(), strategy_refusals={}, strategy_diagnostics={})
        ),
    )
    monkeypatch.setattr(whole_driver, "read_asos_rows", lambda _path: [])
    # No FINAL record for LAX/2026-09-05 -- the climate day has not closed.
    monkeypatch.setattr(whole_driver, "climate_day_records_to_settlement", lambda *_a, **_k: {})

    report = whole_driver.run(
        quote_catalog=tmp_path / "catalog",
        output_root=tmp_path / "derived" / "paper_replay",
        work_root=tmp_path / "derived" / "paper_replay" / "work",
        asos_cache_csv=tmp_path / "asos.csv",
        weather_catalog_root=tmp_path / "weather_catalog",
        derived_root=tmp_path / "derived",
    )
    assert calls == []
    assert "BLOCKED:NO_FINAL_SETTLEMENT: 1" in report
