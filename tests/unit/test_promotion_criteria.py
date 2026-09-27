"""AUD-10b step 10: one test per promotion predicate (pass, fail, absent)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.analysis.promotion_criteria import (
    ADAPTED_R5_IDS,
    KILL_CLOCK_MAX_AGE_SECONDS,
    PROVISIONAL_TAG,
    AdmissionReport,
    CriterionRow,
    RunRefusal,
    admit_station_day,
    assemble_outcome,
    block_bootstrap_ci_lower,
    champion_kill_clock_path,
    evaluate_c_estimator,
    evaluate_c_kill,
    evaluate_c_n,
    evaluate_c_paired,
    evaluate_c_pin,
    evaluate_c_revision,
    evaluate_c_stations,
    evaluate_c_validity,
    paired_ci_comparison,
    render_rationale,
)
from breezy.analysis.replay_results import (
    REPLAY_RESULTS_SCHEMA_VERSION,
    REPLAY_VALIDITY,
    ReplayResult,
)
from breezy.analysis.replay_sufficiency import REPLAY_SUFFICIENCY_SCHEMA_VERSION, ReplaySufficiency
from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    StationDayAdmissionRefusal,
    StratumRow,
)
from breezy.settlement.roi_bound import B_RESAMPLES, SEED

_REPO = Path(__file__).resolve().parents[2]
_V4 = _REPO / "deploy" / "families" / "pm_us_crh_v4.json"
_V2 = _REPO / "deploy" / "families" / "pm_us_crh_v2.json"


def _champion() -> FamilyManifest:
    return load_family_manifest(_V4)


def _row(**overrides: object) -> ReplayResult:
    base: dict[str, object] = {
        "schema_version": REPLAY_RESULTS_SCHEMA_VERSION,
        "run_ts": "2026-09-25T00:00:00+00:00",
        "station": "LAX",
        "climate_day": "2026-09-21",
        "strategy": "continuous_rung_hold",
        "lag_minutes": 30,
        "outcome": "COMPLETED",
        "validity": REPLAY_VALIDITY,
        "blocked_reason": None,
        "exception_type": None,
        "family_id": "pm_us_crh_v4",
        "manifest_sha256": "a" * 64,
        "manifest_taker_fee_coefficient": "0.0695",
        "engine_required_fee_coefficient": "0.0695",
        "engine_params_source": "FAMILY_MANIFEST",
        "params_match": True,
        "composition_kind": "continuous_rung_hold",
        "tape_instance_id": "inst",
        "sufficiency_reason": "",
        "trials": 0,
        "fills": 0,
        "fill_price_vs_decision_ask": (),
        "refusal_counts": {},
        "wall_s": 1.0,
        "peak_rss_bytes": 1,
        "parquet_sha256": None,
        "window_complete": True,
        "replayed_first_ns": 1,
        "replayed_last_ns": 2,
        "census_schema_version": REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    }
    base.update(overrides)
    return ReplayResult(**base)  # type: ignore[arg-type]


def _census(**overrides: object) -> ReplaySufficiency:
    base: dict[str, object] = {
        "schema_version": REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        "station": "LAX",
        "climate_day": "2026-09-21",
        "verdict": "SUFFICIENT",
        "reason": "",
        "winner_instance_id": "inst",
        "depth_window_minutes": 300.0,
        "quote_window_minutes": 300.0,
        "distinct_instruments": 1,
        "computed_day": "2026-09-25",
        "window_start_ns": 1,
        "window_end_ns": 2,
        "winner_first_in_window_ns": 1,
        "winner_last_in_window_ns": 2,
        "window_complete": True,
        "live_instance_count": 0,
        "coverage_kind": "WHOLE",
        "excluded_fragments": (),
    }
    base.update(overrides)
    return ReplaySufficiency(**base)  # type: ignore[arg-type]


def _generate_counter(tmp_path: Path, manifest: Path, name: str) -> Path:
    catalog = tmp_path / name / "catalog"
    (catalog / "data" / "order_book_depths").mkdir(parents=True)
    out = tmp_path / name / "counter.json"
    subprocess.run(
        [
            sys.executable,
            str(_REPO / "scripts" / "analysis" / "structural_dead_stop.py"),
            "--catalog-root",
            str(catalog),
            "--family-manifest",
            str(manifest),
            "--output",
            str(out),
        ],
        check=True,
        cwd=_REPO,
    )
    return out


def _exec_db(tmp_path: Path) -> Path:
    path = tmp_path / "exec.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB)")
    conn.commit()
    conn.close()
    return path


def _count_filled(db: Path, manifest: FamilyManifest) -> int | None:
    # Imported lazily so a criteria-module import failure is the RED, and the
    # script module is loaded the same way the proposal script loads it.
    sys.path.insert(0, str(_REPO / "scripts" / "analysis"))
    from fill_time_count import count_filled_takes

    return count_filled_takes(
        db,
        family_prefix=manifest.trial_id_prefix,
        since_climate_day=manifest.d0_climate_day,
    )


def _structural(count: int, filled: int | None):
    sys.path.insert(0, str(_REPO / "scripts" / "analysis"))
    from structural_dead_stop import structural_dead

    return structural_dead(covered_listed_station_days=count, filled_takes=filled)


# ---------------------------------------------------------------------------
# C-KILL
# ---------------------------------------------------------------------------


def test_c_kill_champion_scoped_verdict_equals_structural_dead(tmp_path: Path) -> None:
    manifest = _champion()
    clock = _generate_counter(tmp_path, _V4, "v4")
    db = _exec_db(tmp_path)
    payload = json.loads(clock.read_text())
    assert payload["manifest_sha256"] == manifest.manifest_sha256
    filled = _count_filled(db, manifest)
    expected = _structural(payload["count"], filled)
    os.utime(clock, (clock.stat().st_atime, clock.stat().st_mtime))
    row = evaluate_c_kill(
        clock_path=clock,
        champion=manifest,
        now_unix=clock.stat().st_mtime + 10,
        fill_count=lambda: _count_filled(db, manifest),
        exec_state_db=db,
    )
    assert isinstance(row, CriterionRow)
    assert row.verdict == "true"
    assert row.value["structural_dead"] == expected.structural_dead
    assert row.value["evaluable"] == expected.evaluable
    assert row.value["covered_listed_station_days"] == expected.covered_listed_station_days
    assert row.value["filled_takes"] == expected.filled_takes
    assert expected.evaluable is True
    assert str(clock) in row.input_artefact


def test_c_kill_absent_clock_refuses(tmp_path: Path) -> None:
    with pytest.raises(RunRefusal, match="KILL_CLOCK_ABSENT") as exc:
        evaluate_c_kill(
            clock_path=tmp_path / "missing.json",
            champion=_champion(),
            now_unix=0.0,
            fill_count=lambda: 0,
            exec_state_db=tmp_path / "no.sqlite",
        )
    assert exc.value.reason == "KILL_CLOCK_ABSENT"


def test_c_kill_stale_not_tripped_clock_is_not_permissive(tmp_path: Path) -> None:
    clock = _generate_counter(tmp_path, _V4, "stale")
    payload = json.loads(clock.read_text())
    assert payload["count"] == 0  # would read "not tripped"
    old = clock.stat().st_mtime - (KILL_CLOCK_MAX_AGE_SECONDS + 1)
    os.utime(clock, (old, old))
    with pytest.raises(RunRefusal) as exc:
        evaluate_c_kill(
            clock_path=clock,
            champion=_champion(),
            now_unix=clock.stat().st_mtime + KILL_CLOCK_MAX_AGE_SECONDS + 5,
            fill_count=lambda: 0,
            exec_state_db=tmp_path / "db.sqlite",
        )
    assert exc.value.reason == "KILL_CLOCK_STALE"


def test_c_kill_provenance_mismatch_refuses(tmp_path: Path) -> None:
    clock = _generate_counter(tmp_path, _V4, "prov")
    payload = json.loads(clock.read_text())
    payload["fetch_start"] = "2026-01-01"
    clock.write_text(json.dumps(payload))
    with pytest.raises(RunRefusal) as exc:
        evaluate_c_kill(
            clock_path=clock,
            champion=_champion(),
            now_unix=clock.stat().st_mtime + 1,
            fill_count=lambda: 0,
            exec_state_db=tmp_path / "db.sqlite",
        )
    assert exc.value.reason == "KILL_CLOCK_PROVENANCE_MISMATCH"


def test_c_kill_depth_root_absent_refuses(tmp_path: Path) -> None:
    clock = _generate_counter(tmp_path, _V4, "depth")
    payload = json.loads(clock.read_text())
    payload["depth_root_present"] = False
    clock.write_text(json.dumps(payload))
    with pytest.raises(RunRefusal) as exc:
        evaluate_c_kill(
            clock_path=clock,
            champion=_champion(),
            now_unix=clock.stat().st_mtime + 1,
            fill_count=lambda: 0,
            exec_state_db=tmp_path / "db.sqlite",
        )
    assert exc.value.reason == "KILL_CLOCK_NOT_EVALUABLE"
    assert "depth_root_present" in exc.value.detail


def test_c_kill_unevaluable_fill_count_refuses(tmp_path: Path) -> None:
    clock = _generate_counter(tmp_path, _V4, "fills")
    with pytest.raises(RunRefusal) as exc:
        evaluate_c_kill(
            clock_path=clock,
            champion=_champion(),
            now_unix=clock.stat().st_mtime + 1,
            fill_count=lambda: None,
            exec_state_db=tmp_path / "missing.sqlite",
        )
    assert exc.value.reason == "KILL_CLOCK_NOT_EVALUABLE"


def test_c_kill_non_champion_clock_is_inert_ahead_of_staleness_and_depth(tmp_path: Path) -> None:
    clock = _generate_counter(tmp_path, _V2, "v2")
    payload = json.loads(clock.read_text())
    champion = _champion()
    assert payload["manifest_sha256"] != champion.manifest_sha256
    payload["depth_root_present"] = False
    clock.write_text(json.dumps(payload))
    old = 1_000.0
    os.utime(clock, (old, old))
    called = {"n": 0}

    def _fill() -> int:
        called["n"] += 1
        return 0

    row = evaluate_c_kill(
        clock_path=clock,
        champion=champion,
        now_unix=old + KILL_CLOCK_MAX_AGE_SECONDS + 10_000,
        fill_count=_fill,
        exec_state_db=tmp_path / "db.sqlite",
    )
    assert row.verdict == "INERT"
    assert row.inert_reason == "NO_CHAMPION_SCOPED_KILL_CLOCK"
    assert row.verdict not in {"true", "false"}
    assert called["n"] == 0
    assert "structural_dead" not in json.dumps(row.value)


def test_c_kill_tripped_clock_is_a_failed_predicate_not_a_refusal(tmp_path: Path) -> None:
    clock = _generate_counter(tmp_path, _V4, "tripped")
    payload = json.loads(clock.read_text())
    payload["count"] = 10_000
    clock.write_text(json.dumps(payload))
    row = evaluate_c_kill(
        clock_path=clock,
        champion=_champion(),
        now_unix=clock.stat().st_mtime + 1,
        fill_count=lambda: 0,
        exec_state_db=tmp_path / "db.sqlite",
    )
    assert row.verdict == "false"
    assert row.value["structural_dead"] is True


def test_champion_kill_clock_path_is_the_aud05_champion_file() -> None:
    import datetime as dt

    path = champion_kill_clock_path(Path("/tmp/derived"), on_date=dt.date(2026, 9, 25))
    assert path.name == "covered_listed_station_days_champion_2026-09-25.json"


# ---------------------------------------------------------------------------
# C-PAIRED (synthetic arithmetic is labelled as such)
# ---------------------------------------------------------------------------


def test_c_paired_absent_challenger_is_inert_never_false() -> None:
    row = evaluate_c_paired(
        challenger_draws=None,
        champion_draws=(),
        d0_climate_day="2026-09-20",
        replay_results_path="/tmp/replay_results.jsonl",
    )
    assert row.verdict == "INERT"
    assert row.inert_reason == "NO_CHALLENGER_REPLAY_PATH"
    assert row.verdict != "false"


def test_c_paired_synthetic_compares_ci_lower_not_challenger_ci_vs_champion_point() -> None:
    """SYNTHETIC fixture (C7): asserts the arithmetic only, nothing about production."""
    d0 = "2026-09-20"
    day = ("LAX", "2026-09-21")
    before = ("LAX", "2026-09-19")
    champion = [
        (day, CombinedDraw(x=5.0, variance=9.0, n_constituents=1)),
        (before, CombinedDraw(x=100.0, variance=0.01, n_constituents=1)),
    ]
    challenger = [
        (day, CombinedDraw(x=0.5, variance=0.01, n_constituents=1)),
        (before, CombinedDraw(x=-100.0, variance=0.01, n_constituents=1)),
    ]
    compared = paired_ci_comparison(
        champion_draws=champion,
        challenger_draws=challenger,
        d0_climate_day=d0,
    )
    assert compared.paired_keys == (day,)
    assert compared.decision_rule == "ci_lower_vs_ci_lower"
    assert compared.challenger_ci_lower > compared.champion_ci_lower
    assert compared.beats_on_ci_lower is True
    assert compared.challenger_ci_lower <= compared.champion_point
    assert compared.beats_on_point is False
    import inspect

    assert "fit_date" not in inspect.signature(evaluate_c_paired).parameters
    with pytest.raises(TypeError):
        evaluate_c_paired(  # type: ignore[call-arg]
            challenger_draws=challenger,
            champion_draws=champion,
            d0_climate_day=d0,
            replay_results_path="x",
            fit_date="2026-09-01",
        )


# ---------------------------------------------------------------------------
# C-STATIONS
# ---------------------------------------------------------------------------


def test_c_stations_refuses_an_outside_station_and_reads_no_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[object] = []
    real_open = open

    def _spy(*args: object, **kwargs: object):
        opened.append(args[0] if args else kwargs.get("file"))
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("builtins.open", _spy)
    refused = evaluate_c_stations(("LAX", "NYC"))
    assert refused.verdict == "false"
    assert refused.detail is not None and "EXPANSION_REQUIRES_RULING" in refused.detail
    assert opened == []
    assert evaluate_c_stations(("SFO", "LAX")).verdict == "true"


# ---------------------------------------------------------------------------
# C-VALIDITY (B27: whole day + drift, plus MECHANISM_ONLY / params_match)
# ---------------------------------------------------------------------------


def _validity(results: tuple[ReplayResult, ...], census: dict, drift, **kw: object) -> CriterionRow:
    return evaluate_c_validity(
        results=results,
        census_by_station_day=census,
        drift_station_days=drift,
        results_path="replay_results.jsonl",
        census_path="replay_sufficiency.jsonl",
        drift_path="replay_drift.jsonl",
        **kw,  # type: ignore[arg-type]
    )


def test_c_validity_refuses_params_match_false_and_cites_no_edge() -> None:
    row = _validity(
        (_row(params_match=False, validity="NOT_MECHANISM"),),
        {("LAX", "2026-09-21"): _census()},
        frozenset(),
    )
    assert row.verdict == "false"
    assert row.detail is not None and "params_match" in row.detail
    assert "edge_hat" not in json.dumps(row.value)


def test_c_validity_refuses_mechanism_only() -> None:
    row = _validity(
        (_row(validity=REPLAY_VALIDITY),),
        {("LAX", "2026-09-21"): _census()},
        frozenset(),
    )
    assert row.verdict == "false"
    assert row.detail is not None and "MECHANISM_ONLY" in row.detail


def test_c_validity_passes_a_params_verified_row() -> None:
    """RA-3 finding: `evaluate_c_validity` (promotion_criteria.py:427) gates on
    `row.validity == REPLAY_VALIDITY` ("MECHANISM_ONLY") alone -- it has no
    special case for "PARAMS_VERIFIED" specifically, it simply passes any
    validity value that is not MECHANISM_ONLY. This pins that a
    PARAMS_VERIFIED row clears the validity predicate with no reason cited,
    same as any other non-MECHANISM_ONLY string."""
    row = _validity(
        (_row(validity="PARAMS_VERIFIED", params_match=True),),
        {("LAX", "2026-09-21"): _census()},
        frozenset(),
    )
    assert row.verdict == "true"
    assert row.detail is None


def test_c_validity_refuses_partial_window_fragment_and_drift() -> None:
    whole = {("LAX", "2026-09-21"): _census()}
    partial = _validity(
        (_row(validity="CHECKED", window_complete=False),),
        whole,
        frozenset(),
    )
    assert partial.verdict == "false"
    assert partial.detail is not None and "window_complete" in partial.detail
    fragment = _validity(
        (_row(validity="CHECKED"),),
        {("LAX", "2026-09-21"): _census(coverage_kind="FRAGMENT")},
        frozenset(),
    )
    assert fragment.verdict == "false"
    assert fragment.detail is not None and "WHOLE" in fragment.detail
    drifted = _validity(
        (_row(validity="CHECKED"),),
        whole,
        frozenset({("LAX", "2026-09-21")}),
    )
    assert drifted.verdict == "false"
    assert drifted.detail is not None and "drift" in drifted.detail


def test_c_validity_is_vacuous_over_zero_rows_even_without_a_drift_file() -> None:
    row = _validity((), None, None)
    assert row.verdict == "true"


def test_c_validity_passes_a_whole_day_non_mechanism_row() -> None:
    row = _validity(
        (_row(validity="CHECKED", params_match=True),),
        {("LAX", "2026-09-21"): _census()},
        frozenset(),
    )
    assert row.verdict == "true"


def test_c_validity_missing_drift_file_with_rows_fails_closed() -> None:
    row = _validity(
        (_row(validity="CHECKED"),),
        {("LAX", "2026-09-21"): _census()},
        None,
    )
    assert row.verdict == "false"
    assert row.detail is not None and "replay_drift" in row.detail


# ---------------------------------------------------------------------------
# C-N / C-ESTIMATOR
# ---------------------------------------------------------------------------


def test_c_n_absent_store_is_no_proposal_with_n_zero(tmp_path: Path) -> None:
    row = evaluate_c_n(store_dir=tmp_path / "missing-family")
    assert row.verdict == "false"
    assert row.value["n"] == 0
    assert row.detail is not None and "C-N" in row.detail


def test_c_n_non_live_provenance_is_n_zero(tmp_path: Path) -> None:
    store = tmp_path / "fam"
    store.mkdir()
    (store / "provenance.json").write_text(json.dumps({"provenance": "paper_replay"}))
    row = evaluate_c_n(store_dir=store)
    assert row.verdict == "false"
    assert row.value["n"] == 0


def test_c_n_live_empty_store_is_underpowered(tmp_path: Path) -> None:
    store = tmp_path / "fam"
    store.mkdir()
    (store / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    row = evaluate_c_n(store_dir=store)
    assert row.verdict == "false"
    assert row.value["n"] == 0


def test_edge_ci_lower_uses_the_shared_one_sided_confidence_level() -> None:
    """`_edge`'s analytic CI-lower and `block_bootstrap_ci_lower`'s BCa bound
    must be reported at the SAME one-sided level -- both derived from
    `roi_bound._CONFIDENCE_LEVEL` (0.95), not a locally hardcoded 0.975."""
    from scipy.stats import norm

    from breezy.analysis.promotion_criteria import _CONFIDENCE_LEVEL, _edge

    draws = (
        CombinedDraw(x=10.0, variance=4.0, n_constituents=5),
        CombinedDraw(x=5.0, variance=1.0, n_constituents=5),
    )
    edge_hat, se, lower = _edge(draws)
    z = norm.ppf(_CONFIDENCE_LEVEL)
    assert lower == pytest.approx(edge_hat - z * se)
    # The bug this pins: 0.975 (two-sided companion of a 95% CI) is a
    # DIFFERENT level than roi_bound's one-sided 0.95.
    assert norm.ppf(_CONFIDENCE_LEVEL) != pytest.approx(norm.ppf(0.975))


def test_c_estimator_absent_cites_c_n_and_emits_no_edge(tmp_path: Path) -> None:
    row = evaluate_c_estimator(
        store_dir=tmp_path / "missing",
        validity_allows_edge=False,
    )
    assert row.verdict == "false"
    assert row.detail is not None and "C-N" in row.detail
    assert "edge_hat" not in json.dumps({"value": row.value, "detail": row.detail})


def test_c_estimator_calls_the_shipped_bootstrap_and_defines_no_local_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_bootstrap(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)

        class _CI:
            low = -0.25

        class _Result:
            confidence_interval = _CI()

        return _Result()

    import breezy.analysis.promotion_criteria as criteria

    monkeypatch.setattr(criteria, "bootstrap", _fake_bootstrap)
    draws = tuple(
        CombinedDraw(x=float(i) - 10.0, variance=0.2, n_constituents=1) for i in range(30)
    )
    lower = block_bootstrap_ci_lower(draws)
    assert captured["n_resamples"] == B_RESAMPLES
    assert captured["method"] == "BCa"
    assert lower == pytest.approx(-0.25)
    source = Path(criteria.__file__).read_text()
    assert "n_resamples=B_RESAMPLES" in source
    assert "default_rng(SEED)" in source
    assert "10_000" not in source
    assert "20260904" not in source
    assert SEED == 20260904
    assert B_RESAMPLES == 10_000


# ---------------------------------------------------------------------------
# Seven admission refusals (C15)
# ---------------------------------------------------------------------------


def _stratum(**kwargs: object) -> StratumRow:
    base: dict[str, object] = {
        "entry_ask": Decimal("0.40"),
        "fee": Decimal("0.02"),
        "held": True,
        "station": "LAX",
        "qty": Decimal(1),
        "side": "yes",
        "rung": "r1",
    }
    base.update(kwargs)
    return StratumRow(**base)  # type: ignore[arg-type]


def test_seven_combine_refusals_are_named_no_proposals_via_the_base_catch() -> None:
    assert ValueError in StationDayAdmissionRefusal.__bases__
    cases: list[tuple[str, tuple[StratumRow, ...]]] = [
        ("ValueError", ()),
        ("_MixedDayMissingRungKeyRefusal", (_stratum(side="no", rung=None),)),
        (
            "_SameRungOppositeSidesRefusal",
            (_stratum(side="yes", rung="r1"), _stratum(side="no", rung="r1")),
        ),
        (
            "StationDayAdmissionRefusal",
            (
                _stratum(rung="r1", entry_ask=Decimal("0.40")),
                _stratum(rung="r1", entry_ask=Decimal("0.55")),
            ),
        ),
        (
            "StationDayAdmissionRefusal",
            (
                _stratum(rung="r1", fee=Decimal("0.02")),
                _stratum(rung="r1", fee=Decimal("0.04")),
            ),
        ),
        (
            "StationDayAdmissionRefusal",
            (_stratum(rung="r1", held=True), _stratum(rung="r1", held=False)),
        ),
        (
            "StationDayAdmissionRefusal",
            (
                _stratum(rung="r1", entry_ask=Decimal("0.70"), fee=Decimal("0.05")),
                _stratum(rung="r2", entry_ask=Decimal("0.70"), fee=Decimal("0.05")),
            ),
        ),
    ]
    assert len(cases) == 7
    for expected_type, rows in cases:
        report = admit_station_day(rows)
        assert isinstance(report, AdmissionReport)
        assert report.outcome == "NO_PROPOSAL"
        assert report.refusal_type is not None and expected_type in report.refusal_type
        assert report.message


# ---------------------------------------------------------------------------
# C-REVISION / C-PIN / assembly / lifting
# ---------------------------------------------------------------------------


def _draft_from(champion: FamilyManifest, **changes: object) -> FamilyManifest:
    return replace(champion, manifest_sha256="0" * 64, **changes)  # type: ignore[arg-type]


def test_c_revision_refuses_the_run_without_a_champion() -> None:
    draft = _draft_from(
        _champion(),
        family_id="pm_us_crh_v4_d20260926",
        trial_id_prefix="continuous_rung_hold/pm_us_crh_v4_d20260926/trial/",
        d0_climate_day="2026-09-26",
        status="DRAFT_NOT_REGISTERED",
    )
    with pytest.raises(RunRefusal) as exc:
        evaluate_c_revision(champion=None, proposal=draft)
    assert exc.value.reason == "NO_CHAMPION_MANIFEST"


def test_c_revision_requires_a_new_revision() -> None:
    champion = _champion()
    same = evaluate_c_revision(champion=champion, proposal=champion)
    assert same.verdict == "false"
    fresh = _draft_from(
        champion,
        family_id="pm_us_crh_v4_d20260926",
        trial_id_prefix="continuous_rung_hold/pm_us_crh_v4_d20260926/trial/",
        d0_climate_day="2026-09-26",
        status="DRAFT_NOT_REGISTERED",
    )
    row = evaluate_c_revision(champion=champion, proposal=fresh)
    assert row.verdict == "true"
    assert row.value["n"] == 0


def test_c_pin_unpinned_sha_is_proposal_incomplete() -> None:
    champion = _champion()
    draft = _draft_from(
        champion,
        family_id="other",
        trial_id_prefix="other/trial/",
        d0_climate_day="2026-09-26",
        status="DRAFT_NOT_REGISTERED",
        boundary_inputs_sha256="0" * 64,
        density_artefact_sha256="0" * 64,
    )
    row = evaluate_c_pin(draft)
    assert row.verdict == "PROPOSAL_INCOMPLETE"


def test_c_pin_real_pinned_shas_pass() -> None:
    champion = _champion()
    row = evaluate_c_pin(champion)
    assert row.verdict == "true"
    assert row.value["boundary_inputs_sha256"] == champion.boundary_inputs_sha256
    assert row.value["density_artefact_sha256"] == champion.density_artefact_sha256
    assert row.detail is None


def test_c_pin_absent_density_sha_is_proposal_incomplete() -> None:
    """Only ONE of the two shas C-PIN reads is the unpinned placeholder --
    the other is a real, champion-pinned value. The `or` in `evaluate_c_pin`
    must still fail closed: any absent input is PROPOSAL_INCOMPLETE, not
    just both-absent."""
    champion = _champion()
    draft = _draft_from(
        champion,
        family_id="other",
        trial_id_prefix="other/trial/",
        d0_climate_day="2026-09-26",
        status="DRAFT_NOT_REGISTERED",
        density_artefact_sha256="0" * 64,
    )
    assert draft.boundary_inputs_sha256 == champion.boundary_inputs_sha256
    row = evaluate_c_pin(draft)
    assert row.verdict == "PROPOSAL_INCOMPLETE"


def test_adapted_r5_rows_carry_the_provisional_tag_and_name_an_artefact() -> None:
    champion = _champion()
    rows = (
        evaluate_c_paired(
            challenger_draws=None,
            champion_draws=(),
            d0_climate_day=champion.d0_climate_day,
            replay_results_path="replay_results.jsonl",
        ),
        evaluate_c_revision(
            champion=champion,
            proposal=_draft_from(
                champion,
                family_id="new_family",
                trial_id_prefix="new/trial/",
                d0_climate_day="2026-09-26",
                status="DRAFT_NOT_REGISTERED",
            ),
        ),
        evaluate_c_pin(
            _draft_from(
                champion,
                boundary_inputs_sha256="0" * 64,
                density_artefact_sha256="0" * 64,
            )
        ),
        evaluate_c_stations(("LAX",)),
        evaluate_c_n(store_dir=Path("/no/such/store")),
    )
    for row in rows:
        assert row.input_artefact
        if row.id in ADAPTED_R5_IDS:
            assert row.tag == PROVISIONAL_TAG


def test_inert_bars_proposal_even_when_every_other_predicate_passes() -> None:
    inert = CriterionRow(
        id="C-PAIRED",
        verdict="INERT",
        value=None,
        threshold=None,
        input_artefact="replay_results.jsonl",
        source="R5-7",
        tag=PROVISIONAL_TAG,
        inert_reason="NO_CHALLENGER_REPLAY_PATH",
        detail=None,
    )
    others = tuple(
        CriterionRow(
            id=name,
            verdict="true",
            value=None,
            threshold=None,
            input_artefact=f"{name}.path",
            source="test",
            tag=PROVISIONAL_TAG if name in ADAPTED_R5_IDS else None,
            inert_reason=None,
            detail=None,
        )
        for name in ("C-KILL", "C-ESTIMATOR", "C-N", "C-REVISION", "C-STATIONS", "C-VALIDITY")
    )
    pin = CriterionRow(
        id="C-PIN",
        verdict="true",
        value=None,
        threshold=None,
        input_artefact="proposal.json",
        source="R5-8",
        tag=PROVISIONAL_TAG,
        inert_reason=None,
        detail=None,
    )
    assembled = assemble_outcome(
        (inert, *others, pin),
        criteria_status="LIFTED",
    )
    assert assembled.outcome != "PROPOSAL"
    assert assembled.criteria_status == "PROVISIONAL"
    assert "C-PAIRED" in assembled.inert


def test_a_fully_evaluable_run_with_provisional_status_still_tags_the_output() -> None:
    """The PROVISIONAL/LIFTED decision is made by the caller (the lifting-ruling
    path + sha256 check lives in ``scripts/analysis/promotion_proposal.py``,
    never here -- see ``test_probe_containment.py::
    test_no_module_under_src_reads_docs_evidence``); this module only ever
    receives an already-resolved ``criteria_status`` string and must render it
    faithfully even when every predicate is evaluable.
    """
    rows = tuple(
        CriterionRow(
            id=name,
            verdict="true",
            value=None,
            threshold=None,
            input_artefact=f"{name}.path",
            source="test",
            tag=PROVISIONAL_TAG if name in ADAPTED_R5_IDS else None,
            inert_reason=None,
            detail=None,
        )
        for name in (
            "C-KILL",
            "C-PAIRED",
            "C-ESTIMATOR",
            "C-N",
            "C-REVISION",
            "C-PIN",
            "C-VALIDITY",
            "C-STATIONS",
        )
    )
    assembled = assemble_outcome(rows, criteria_status="PROVISIONAL")
    assert assembled.outcome == "PROPOSAL"
    assert assembled.criteria_status == "PROVISIONAL"
    for outcome in ("PROPOSAL", "NO_PROPOSAL"):
        text = render_rationale(replace(assembled, outcome=outcome))
        assert "PROVISIONAL" in text
        assert "never arms" in text.lower()


def test_failed_criteria_assemble_as_no_proposal() -> None:
    failed = CriterionRow(
        id="C-N",
        verdict="false",
        value={"n": 0},
        threshold=30,
        input_artefact="/store",
        source="V3",
        tag=None,
        inert_reason=None,
        detail="NO_PROPOSAL citing C-N",
    )
    inert = CriterionRow(
        id="C-KILL",
        verdict="INERT",
        value=None,
        threshold=None,
        input_artefact="/clock.json",
        source="R5-8",
        tag=PROVISIONAL_TAG,
        inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK",
        detail=None,
    )
    assembled = assemble_outcome((failed, inert), criteria_status="PROVISIONAL")
    assert assembled.outcome == "NO_PROPOSAL"
    assert assembled.failed == ("C-N",)
    assert assembled.inert == ("C-KILL",)
