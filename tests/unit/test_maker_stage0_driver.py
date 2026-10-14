"""MAKER-S2 WP6: the run driver (plan r3 WP6 + r4 delta (b)(c)(d)(e)(g)(i)). Fixture world only.

One module-scoped verdict run on the fake capture feeds the output-shape tests; refusal and abort
tests build their own (cheap) configurations. No real catalog, NBP store, truth CSV or node log.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_events_build as eb
from scripts.analysis import maker_stage0_report as rep
from scripts.analysis import maker_stage0_verify_first as vf
from scripts.analysis.maker_stage0_catalog_read import CatalogSession
from scripts.analysis.maker_stage0_fill_events import DeltaBoundExceeded
from scripts.analysis.maker_stage0_frozen import FrozenSetRefused
from scripts.analysis.maker_stage0_ledger import LedgerRefused
from scripts.analysis.maker_stage0_pins import DirtyTree
from scripts.analysis.maker_stage0_probe_core import StopS2
from scripts.analysis.maker_stage0_verdict import UNDERPOWERED
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.unit import test_maker_stage0_pins as pins_fx
from tests.unit import test_maker_stage0_pno as pno_fx

TRUTH_TOKENS = {"", "YES", "NO", "VOID", "UNRESOLVED"}
STATION_DAY_COLUMNS = {
    "station", "climate_day", "cluster_id", "unit_hypothesis", "census_reason", "covered_bidlive",
    "covered", "outage_excluded", "node_log_absent", "bid_bearing", "guard_refused_only",
    "n_depth_frames", "has_depth_frame", "n_attempts", "n_episodes", "n_refused",
    "n_process_cuts", "n_gtd_cuts", "rung_trials_posted", "rung_trials_filled_base",
    "rung_trials_filled_stress", "process_live_h", "forecast_valid_h", "gap_h", "covered_live_h",
    "gap_share", "filled_pairs_base", "filled_pairs_stress", "k1_rung_id", "k1_filled_base",
    "k1_filled_stress", "bid_median_fills_stress", "nogo_driving", "positions_filled_k2_base",
    "positions_filled_k2_stress", "positions_filled_k1_base", "positions_filled_k1_stress",
    "delta_ns", "truth_final", "truth_tmax_f", "void", "unresolved_d14", "theta",
    "rung_trials_attempted", "n_no_book_wants",
}  # fmt: skip
SCORED_COLUMNS = {
    "position_id", "rung_trial_id", "station", "climate_day", "unit_hypothesis", "bid",
    "filled_base", "filled_stress", "p_yes_point_live", "truth_final",
}  # fmt: skip
SIDECARS = {
    "overlay_station_days.csv", "process_schedule_overlay.json", "progress.jsonl",
    "stress_plus60_station_days.csv", "stress_poll_lag_station_days.csv", "wp0_agreement.json",
    "delta0_station_days.csv",
}  # fmt: skip
FORBIDDEN_PROGRESS = ("fill", "rate", "label", "verdict", "episode", "loss", "win")
RESULT_FILES = ("scored_episodes.csv", "s3_inputs.json", "station_days.csv", "episodes.jsonl")


@dataclasses.dataclass(frozen=True)
class Run:
    cfg: drv.RunConfig
    run_dir: Path
    repo: Path
    summary: drv.RunSummary
    world: rw.World


def make_cfg(
    world: rw.World, base: Path, repo: Path, *, name: str = "run1", **over: Any
) -> drv.RunConfig:
    cfg = drv.RunConfig(
        census_days=world.census,
        trade_unit=world.unit,
        catalog_root=world.capture,
        nbp_root=world.nbp_root,
        truth=world.truth,
        truth_cross_check=world.cross_check,
        node_log_dir=world.node_log_dir,
        out_dir=base / "runs" / name,
        repo_root=repo,
        amendment=world.amendment,
        amendment_sha=world.amendment_sha,
        spec=repo / "docs/strategies/SPEC.md",
        ledger=base / "derived" / "verdict_ledger.jsonl",
        work_root=base / "work" / name,
        as_of=dt.date(2026, 10, 14),
        argv=("maker_stage0_replay", "--fixture"),
    )
    return dataclasses.replace(cfg, **over)


@pytest.fixture(autouse=True)
def _calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> rw.World:
    return rw.build_world(tmp_path_factory.mktemp("world"))


@pytest.fixture(scope="module")
def e2e(world: rw.World, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Run]:
    base = tmp_path_factory.mktemp("e2e")
    repo = pins_fx._repo(base)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())
        cfg = make_cfg(world, base, repo)
        summary = drv.run(cfg)
    yield Run(cfg, cfg.out_dir, repo, summary, world)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _ledger(cfg: drv.RunConfig) -> list[dict[str, Any]]:
    if not cfg.ledger.exists():
        return []
    return [json.loads(line) for line in cfg.ledger.read_text().splitlines() if line.strip()]


# --- end to end ---------------------------------------------------------------------------------


def test_end_to_end_on_the_fixture_produces_a_verdict_and_every_artifact(e2e: Run) -> None:
    assert e2e.summary.label == UNDERPOWERED  # n_sd = 1 covered bid-bearing day: V0 fires
    for name in (
        "episodes.jsonl", "progress.jsonl", "station_days.csv", "scored_episodes.csv",
        "tail_reliability.csv", "s3_inputs.json", "report.md", "pins.json", "run_manifest.json",
        "process_schedule.json", "catalog_slice_manifest.json", "truth_cli_finals.csv",
        *SIDECARS,
    ):  # fmt: skip
        assert (e2e.run_dir / name).is_file(), name
    s3 = json.loads((e2e.run_dir / "s3_inputs.json").read_text())
    assert (
        s3["verdict"] == UNDERPOWERED
        and s3["code_sha"] == pins_fx._git(e2e.repo, "rev-parse", "HEAD").strip()
    )
    manifest = json.loads((e2e.run_dir / "run_manifest.json").read_text())
    assert manifest["seed"] == 20260919 and manifest["iterations"] == 2000
    assert manifest["mode"] == "verdict" and manifest["run_id"] == "run1"
    assert {"argv", "git_commit", "python", "nautilus_version", "wall_time_s"} <= set(manifest)
    assert {"free_disk_start_bytes", "free_disk_end_bytes", "peak_rss_bytes"} <= set(manifest)
    assert manifest["ladder_lower_parity"]["SFO"] == 0


def test_the_fixture_resting_bid_is_filled_under_base_and_stress(e2e: Run) -> None:
    sd = {
        (r["climate_day"], r["unit_hypothesis"]): r for r in _rows(e2e.run_dir / "station_days.csv")
    }
    day = sd[("2026-09-29", "CONTRACTS")]
    assert day["covered"] == "true" and day["bid_bearing"] == "true"
    assert int(day["filled_pairs_base"]) >= 1 and int(day["filled_pairs_stress"]) >= 1
    assert day["positions_filled_k2_base"] == day["filled_pairs_base"]
    assert day["theta"] and float(day["theta"]) == pytest.approx(0.0695)
    assert day["truth_final"] == "true" and day["truth_tmax_f"] == str(rw.TRUTH_TMAX_F)
    assert day["delta_ns"] == str(5 * 10**9)  # max |offset| over the process-live window


def test_station_days_csv_has_every_contract_column_plus_wp5_obligations(e2e: Run) -> None:
    rows = _rows(e2e.run_dir / "station_days.csv")
    assert set(rows[0]) == STATION_DAY_COLUMNS
    # one row per (station, climate_day, hypothesis) for every census day in the frozen set,
    # replayed or not: 25 rule days, 2026-10-01 absent.
    keys = [(r["station"], r["climate_day"], r["unit_hypothesis"]) for r in rows]
    assert len(keys) == len(set(keys)) == len(rw.rule_days())
    assert "2026-10-01" not in {k[1] for k in keys}
    unreplayed = next(r for r in rows if r["climate_day"] == "2026-09-25")
    assert unreplayed["n_attempts"] == "" or unreplayed["bid_bearing"] in {"false", ""}
    assert unreplayed["census_reason"] == "COVERED"


def test_scored_episodes_truth_tokens(e2e: Run) -> None:
    rows = _rows(e2e.run_dir / "scored_episodes.csv")
    assert rows and set(rows[0]) == SCORED_COLUMNS
    assert {r["truth_final"] for r in rows} <= TRUTH_TOKENS
    assert {r["truth_final"] for r in rows} == {"NO"}  # tmax 70 settles every fixture rung NO
    assert {r["filled_base"] for r in rows} <= {"true", "false"}
    assert any(r["filled_base"] == "true" for r in rows)
    assert all(re.fullmatch(r"0\.\d+", r["bid"]) for r in rows)


def test_progress_events_carry_no_fill_or_rate_fields(e2e: Run) -> None:
    lines = [json.loads(x) for x in (e2e.run_dir / "progress.jsonl").read_text().splitlines()]
    assert lines
    allowed = {
        "index",
        "of",
        "station",
        "climate_day",
        "status",
        "elapsed_s",
        "rss_bytes",
        "n_events",
    }
    for event in lines:
        assert set(event) <= allowed
        assert not [k for k in event if any(bad in k for bad in FORBIDDEN_PROGRESS)]
    assert {e["status"] for e in lines} == {"done"}
    assert all(e["rss_bytes"] > 0 for e in lines)


def test_sidecars_are_sealed_and_pinned_incl_delta0_and_stress(e2e: Run) -> None:
    pins = json.loads((e2e.run_dir / "pins.json").read_text())
    assert set(pins["sidecars"]) == SIDECARS
    for name, pin in pins["sidecars"].items():
        digest = hashlib.sha256((e2e.run_dir / name).read_bytes()).hexdigest()
        assert pin == {"run_time_only": True, "sha256": digest}, name
    for sidecar in ("stress_plus60_station_days.csv", "stress_poll_lag_station_days.csv",
                    "delta0_station_days.csv", "overlay_station_days.csv"):  # fmt: skip
        assert set(_rows(e2e.run_dir / sidecar)[0]) == STATION_DAY_COLUMNS
    delta0 = [
        r
        for r in _rows(e2e.run_dir / "delta0_station_days.csv")
        if r["climate_day"] == "2026-09-29"
    ]
    assert delta0[0]["delta_ns"] == "0"


def test_pins_include_clean_tree_package_set_argv_node_logs_ledger_and_sidecars(e2e: Run) -> None:
    pins = json.loads((e2e.run_dir / "pins.json").read_text())
    head = pins_fx._git(e2e.repo, "rev-parse", "HEAD").strip()
    assert pins["git_commit"] == head and pins["clean_tree"]["clean"] is True
    assert pins["argv"] == ["maker_stage0_replay", "--fixture"]
    assert pins["ledger_path"] == str(e2e.cfg.ledger)
    assert pins["amendment_final_sha256"] == e2e.world.amendment_sha
    assert pins["truth_csv_sha256_frozen_block"] == e2e.world.truth_sha
    assert pins["truth_csv"]["sha256"] == e2e.world.truth_sha
    assert pins["node_logs"] == []
    assert re.fullmatch(r"[0-9a-f]{64}", pins["installed_package_set_sha256"])
    assert "fees.py" in pins["theta_pin_site"] and "0.0695" not in pins["theta_pin_site"]
    assert pins["nbp_consumed"]["cycles"], "the consumed (cycle, raw_sha) set must be pinned"
    manifest = json.loads((e2e.run_dir / "catalog_slice_manifest.json").read_text())
    assert manifest["files"] and all(f["sha256"] for f in manifest["files"])
    assert (
        pins["catalog_slice_manifest"]["sha256"]
        == hashlib.sha256((e2e.run_dir / "catalog_slice_manifest.json").read_bytes()).hexdigest()
    )


def test_report_has_verdict_pins_banner_and_holdout_line(e2e: Run) -> None:
    text = (e2e.run_dir / "report.md").read_text()
    assert f"Verdict: {UNDERPOWERED}" in text
    assert rep.BANNER in text and "never emits a go verdict" in text
    assert "## Pins" in text and e2e.summary.code_sha in text and e2e.world.amendment_sha in text
    assert rep.HOLDOUT_LINE in text
    for phrase in ("clause 3", "descriptive", "open_holdout", "2026-10-01"):
        assert phrase in rep.HOLDOUT_LINE
    assert "run-time only, sha-pinned" in text  # sidecar-backed blocks are labelled
    assert "Overlay schedule (report-only)" in text and "Stress variants (report-only)" in text


def test_stats_rerun_on_scored_csv_reproduces_tables(e2e: Run) -> None:
    from scripts.analysis.maker_stage0_tables import tables_from_csvs

    tables = tables_from_csvs(
        e2e.run_dir / "scored_episodes.csv",
        e2e.run_dir / "station_days.csv",
        e2e.run_dir / "tail_reliability.csv",
        code_sha=e2e.summary.code_sha,
    )
    report = (e2e.run_dir / "report.md").read_text()
    for name in ("v0", "verdict", "rates", "s69", "expectancy", "delta", "coverage"):
        assert tables[name] in report, name


def test_the_scoring_phase_wrote_the_frozen_block_check_and_truth_after_simulation(
    e2e: Run,
) -> None:
    manifest = json.loads((e2e.run_dir / "run_manifest.json").read_text())
    assert manifest["phases"] == ["preflight", "probe", "s7", "simulate", "score", "report"]


def test_verdict_ledger_refuses_second_run_without_void_addendum(e2e: Run, tmp_path: Path) -> None:
    entries = _ledger(e2e.cfg)
    assert [e["kind"] for e in entries] == ["verdict_run_start"]
    assert entries[0]["run_id"] == "run1" and entries[0]["amendment_sha"] == e2e.world.amendment_sha
    second = dataclasses.replace(
        e2e.cfg, out_dir=e2e.cfg.out_dir.with_name("run2"), work_root=tmp_path / "w"
    )
    with pytest.raises(LedgerRefused):
        drv.run(second)
    assert not second.out_dir.exists()
    assert len(_ledger(e2e.cfg)) == 1


def test_driver_refuses_existing_run_dir(e2e: Run) -> None:
    with pytest.raises(drv.RunDirExists):
        drv.run(e2e.cfg)
    assert len(_ledger(e2e.cfg)) == 1  # refused before the ledger was touched again


# --- refusals before the ledger ---------------------------------------------------------------


def _fresh(world: rw.World, tmp_path: Path, **over: Any) -> drv.RunConfig:
    repo = pins_fx._repo(tmp_path)
    return make_cfg(world, tmp_path, repo, **over)


def _assert_untouched(cfg: drv.RunConfig) -> None:
    assert not cfg.out_dir.exists()
    assert not cfg.ledger.exists() or _ledger(cfg) == []


def test_replay_refuses_day_outside_frozen_set_or_amendment_sha_mismatch(
    world: rw.World, tmp_path: Path
) -> None:
    bad_sha = _fresh(world, tmp_path / "a", amendment_sha="0" * 64)
    with pytest.raises(FrozenSetRefused, match="sha"):
        drv.run(bad_sha)
    _assert_untouched(bad_sha)

    draft = tmp_path / "draft.md"
    draft.write_text(rw.amendment_text(world.truth_sha, status="DRAFT rev 2"))
    cfg = _fresh(
        world, tmp_path / "b", amendment=draft,
        amendment_sha=hashlib.sha256(draft.read_bytes()).hexdigest(),
    )  # fmt: skip
    with pytest.raises(FrozenSetRefused, match="DRAFT"):
        drv.run(cfg)
    _assert_untouched(cfg)

    unfilled = tmp_path / "unfilled.md"
    unfilled.write_text(rw.amendment_text(world.truth_sha).replace(world.truth_sha, "<FILL>"))
    cfg = _fresh(
        world, tmp_path / "c", amendment=unfilled,
        amendment_sha=hashlib.sha256(unfilled.read_bytes()).hexdigest(),
    )  # fmt: skip
    with pytest.raises(FrozenSetRefused, match="FILL"):
        drv.run(cfg)
    _assert_untouched(cfg)


@pytest.mark.parametrize(
    ("stations", "days"),
    [
        (("SFO",), (rw.SEALED,)),  # the sealed holdout day
        (("NYC",), (rw.DAY,)),  # NYC is never read
        (("SFO",), (dt.date(2026, 9, 10),)),  # before the first replayable day
        (("SFO",), (dt.date(2026, 10, 14),)),  # after the last allowed day
    ],
)
def test_bench_refuses_a_request_outside_the_frozen_set(
    world: rw.World, tmp_path: Path, stations: tuple[str, ...], days: tuple[dt.date, ...]
) -> None:
    cfg = _fresh(world, tmp_path, bench=4, stations=stations, days=days)
    with pytest.raises(FrozenSetRefused):
        drv.run(cfg)
    _assert_untouched(cfg)


def test_frozen_set_missing_a_rule_day_is_refused(world: rw.World, tmp_path: Path) -> None:
    short = tmp_path / "short.md"
    short.write_text(rw.amendment_text(world.truth_sha, dates=rw.rule_days()[:-1]))
    sha = hashlib.sha256(short.read_bytes()).hexdigest()
    cfg = _fresh(world, tmp_path, amendment=short, amendment_sha=sha)
    with pytest.raises(FrozenSetRefused, match="last|rule|differs"):
        drv.run(cfg)


@pytest.mark.parametrize(
    "over",
    [
        {"stations": ("SFO",)},
        {"days": (rw.DAY,)},
        {"tail_only": True, "bench": 4},
        {"verify_first": True, "bench": 4},
        {"tail_only": True, "stations": ("SFO",)},
        {"verify_first": True, "days": (rw.DAY,)},
    ],
)
def test_verdict_run_refuses_subset_flags(
    world: rw.World, tmp_path: Path, over: dict[str, Any]
) -> None:
    cfg = _fresh(world, tmp_path, **over)
    with pytest.raises(drv.SubsetRefused):
        drv.run(cfg)
    _assert_untouched(cfg)


@pytest.mark.parametrize(
    "rel",
    [
        "pyproject.toml",
        "uv.lock",
        "tests/fixtures/f.txt",
        "scripts/analysis/a.py",
        "src/breezy/b.py",
    ],
)
def test_verdict_run_refuses_dirty_tree_incl_pyproject_lock_and_fixtures(
    world: rw.World, tmp_path: Path, rel: str
) -> None:
    cfg = _fresh(world, tmp_path)
    target = cfg.repo_root / rel
    target.write_text(target.read_text() + "# edit\n")
    with pytest.raises(DirtyTree, match=re.escape(rel)):
        drv.run(cfg)
    _assert_untouched(cfg)


def test_low_disk_refuses_before_the_ledger(world: rw.World, tmp_path: Path) -> None:
    cfg = _fresh(world, tmp_path, min_free_bytes=10**18)
    with pytest.raises(drv.DiskLow):
        drv.run(cfg)
    _assert_untouched(cfg)


# --- aborts: void runs -------------------------------------------------------------------------


def _void_dir(cfg: drv.RunConfig) -> Path:
    return cfg.out_dir.with_name(cfg.out_dir.name + ".void")


def test_delta_over_10min_aborts_before_scoring_and_voids_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = rw.build_world(
        tmp_path / "w", capture=rw.build_capture(tmp_path / "w", big_offset_s=660)
    )
    touched: list[str] = []
    monkeypatch.setattr(rep, "load_truth", lambda *a, **k: touched.append("truth"))
    monkeypatch.setattr(eb, "simulate_station_day", lambda *a, **k: touched.append("sim"))
    cfg = _fresh(world, tmp_path / "r")
    with pytest.raises(DeltaBoundExceeded, match="S-7"):
        drv.run(cfg)
    assert touched == []  # neither a simulation nor the truth file was reached
    assert _void_dir(cfg).is_dir() and not cfg.out_dir.exists()
    kinds = [e["kind"] for e in _ledger(cfg)]
    assert kinds == ["verdict_run_start", "void"]
    assert not [n for n in RESULT_FILES if (_void_dir(cfg) / n).exists()]


def test_inverted_direction_voids_run_s2(tmp_path: Path) -> None:
    world = rw.build_world(tmp_path / "w", capture=rw.build_capture(tmp_path / "w", inverted=True))
    cfg = _fresh(world, tmp_path / "r")
    with pytest.raises(StopS2):
        drv.run(cfg)
    void = _void_dir(cfg)
    agreement = json.loads((void / "wp0_agreement.json").read_text())  # written BEFORE the STOP
    assert agreement["direction"]["verdict"] == "INVERTED"
    assert not [n for n in RESULT_FILES if (void / n).exists()]
    assert [e["kind"] for e in _ledger(cfg)] == ["verdict_run_start", "void"]


def test_rss_over_four_gib_aborts_and_voids_run(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drv, "current_rss_bytes", lambda: 5 * 2**30)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(drv.MemoryAbort, match="S-5"):
        drv.run(cfg)
    assert _void_dir(cfg).is_dir()


def test_a_void_run_may_be_rerun_only_with_a_dated_addendum(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drv, "current_rss_bytes", lambda: 5 * 2**30)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(drv.MemoryAbort):
        drv.run(cfg)
    monkeypatch.undo()
    monkeypatch.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())
    again = dataclasses.replace(cfg, out_dir=cfg.out_dir.with_name("run2"))
    with pytest.raises(LedgerRefused):
        drv.run(again)
    addendum = tmp_path / "addendum.md"
    addendum.write_text("# addendum\nvoided_run_id: run1\ncause: S-5 memory abort\n")
    sha = hashlib.sha256(addendum.read_bytes()).hexdigest()
    done = drv.run(dataclasses.replace(again, addendum=addendum, addendum_sha=sha))
    assert done.label == UNDERPOWERED


# --- modes ------------------------------------------------------------------------------------


def test_bench_mode_skips_scoring_and_writes_no_episode_or_rate_output(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touched: list[str] = []
    real = rep.load_truth

    def spy(*a: Any, **k: Any) -> Any:
        touched.append("truth")
        return real(*a, **k)

    monkeypatch.setattr(rep, "load_truth", spy)
    cfg = _fresh(world, tmp_path, bench=1, stations=("SFO",), days=(rw.DAY, rw.DIRECTION_DAY))
    summary = drv.run(cfg)
    assert touched == []
    names = {p.name for p in cfg.out_dir.iterdir()}
    assert names == {"bench.json", "progress.jsonl", "run_manifest.json"}
    bench = json.loads((cfg.out_dir / "bench.json").read_text())
    assert len(bench["station_days"]) == 1
    only = bench["station_days"][0]
    session = CatalogSession(world.capture, tmp_path / "plan_work")
    plans = session.plan([rw.DAY, rw.DIRECTION_DAY], ["SFO"])
    heavier = max(plans, key=lambda k: plans[k].catalog_bytes)
    assert only["climate_day"] == heavier[1].isoformat()  # chosen by capture bytes only
    assert only["catalog_bytes"] == plans[heavier].catalog_bytes
    assert only["catalog_bytes"] > 0 and only["elapsed_s"] >= 0 and only["peak_rss_bytes"] > 0
    assert {"projected_total_s", "projected_peak_rss_bytes", "s5_exceeded"} <= set(bench)
    assert summary.label is None
    assert _ledger(cfg) == []  # bench never claims the verdict ledger
    text = " ".join(p.read_text() for p in cfg.out_dir.iterdir()).lower()
    assert "filled" not in text and "fill_rate" not in text


def test_bench_picks_the_heaviest_station_days_by_catalog_bytes(world: rw.World) -> None:
    sizes = {("SFO", rw.DAY): 900, ("SFO", rw.DIRECTION_DAY): 100, ("LAX", rw.DAY): 500}
    chosen = drv.heaviest(sizes, 2)
    assert chosen == [("SFO", rw.DAY), ("LAX", rw.DAY)]
    assert drv.heaviest(sizes, 1) == [("SFO", rw.DAY)]


def test_tail_only_is_report_only_and_records_code_sha(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drv, "TAIL_RANGE", (rw.DAY, rw.DAY))
    cfg = _fresh(world, tmp_path, tail_only=True, parity=(("SFO", 0),))
    summary = drv.run(cfg)
    names = {p.name for p in cfg.out_dir.iterdir()}
    assert names == {"tail_reliability.csv", "run_manifest.json"}
    manifest = json.loads((cfg.out_dir / "run_manifest.json").read_text())
    assert manifest["mode"] == "tail-only"
    assert manifest["code_sha"] == pins_fx._git(cfg.repo_root, "rev-parse", "HEAD").strip()
    assert summary.code_sha == manifest["code_sha"] and summary.label is None
    rows = _rows(cfg.out_dir / "tail_reliability.csv")
    assert rows and set(rows[0]) == {"station", "climate_day", "vector", "p_yes", "outcome"}
    assert {r["vector"] for r in rows} <= {"13Z", "19Z", "01Z"}
    assert all(float(r["p_yes"]) < 0.06 and r["outcome"] in {"0", "1"} for r in rows)
    assert _ledger(cfg) == []


def test_tail_only_needs_a_clean_tree(world: rw.World, tmp_path: Path) -> None:
    cfg = _fresh(world, tmp_path, tail_only=True, parity=(("SFO", 0),))
    (cfg.repo_root / "scripts/analysis/a.py").write_text("A = 2\n")
    with pytest.raises(DirtyTree):
        drv.run(cfg)


def test_verify_first_runs_only_in_its_mode_and_only_on_2026_06_30(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dt.date] = []

    def spy(root: Path, day: dt.date) -> Any:
        seen.append(day)
        return vf.VerifyFirstReport(day, (), ())

    monkeypatch.setattr(drv, "verify_first_s6", spy)
    cfg = _fresh(world, tmp_path, verify_first=True)
    drv.run(cfg)
    assert seen == [dt.date(2026, 6, 30)]
    assert (cfg.out_dir / "verify_first.json").is_file()
    assert _ledger(cfg) == []


# --- structure: scoring after simulation; streaming; import closure ---------------------------


def test_driver_scores_only_after_simulation_completes(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_sim, real_truth = eb.simulate_station_day, rep.load_truth

    def sim(*args: Any, **kw: Any) -> Any:
        order.append("sim")
        return real_sim(*args, **kw)

    def truth(*args: Any, **kw: Any) -> Any:
        order.append("truth")
        return real_truth(*args, **kw)

    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("verify-first must not run inside a verdict run")

    monkeypatch.setattr(eb, "simulate_station_day", sim)
    monkeypatch.setattr(rep, "load_truth", truth)
    monkeypatch.setattr(drv, "verify_first_s6", never)
    drv.run(_fresh(world, tmp_path))
    assert order.count("truth") == 1 and order[-1] == "truth"
    assert order.count("sim") >= 2 and "truth" not in order[:-1]


def test_driver_streams_episodes_without_accumulating(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_sim = eb.simulate_station_day
    cfg = _fresh(world, tmp_path)
    episodes_path = cfg.out_dir / "episodes.jsonl"
    early_pulls: list[int] = []
    spies: list[Spy] = []

    def written() -> int:
        return len(episodes_path.read_text().splitlines()) if episodes_path.exists() else 0

    class Spy:
        """A consumed-iterator spy: each episode must be on disk before the next is pulled."""

        def __init__(self, items: tuple[Any, ...]) -> None:
            self.items, self.base, self.pulled = iter(items), written(), 0

        def __iter__(self) -> Spy:
            return self

        def __next__(self) -> Any:
            if written() - self.base != self.pulled:
                early_pulls.append(self.pulled)
            item = next(self.items)
            self.pulled += 1
            return item

    def sim(*args: Any, **kw: Any) -> Any:
        result = real_sim(*args, **kw)
        if not result.episodes:
            return result
        spy = Spy(result.episodes)
        spies.append(spy)
        return dataclasses.replace(result, episodes=cast(Any, spy))

    monkeypatch.setattr(eb, "simulate_station_day", sim)
    drv.run(cfg)
    consumed = [s for s in spies if s.pulled]
    assert consumed and sum(s.pulled for s in consumed) == written()  # the primary pass only
    assert early_pulls == []  # never pulled ahead of the file: nothing accumulated first


def test_a_late_first_print_contradicting_the_frozen_block_voids_the_run(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    late = int(dt.datetime(2026, 9, 17, 18, 0, tzinfo=dt.UTC).timestamp()) * 10**9
    monkeypatch.setattr(drv, "first_print_instant", lambda *a, **k: late)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(drv.InputRefused, match="replayable day"):
        drv.run(cfg)
    assert _void_dir(cfg).is_dir()


def test_episodes_jsonl_has_one_line_per_primary_episode_and_valid_leakage_fields(e2e: Run) -> None:
    lines = [json.loads(x) for x in (e2e.run_dir / "episodes.jsonl").read_text().splitlines()]
    assert lines and all(l["unit_hypothesis"] == "CONTRACTS" for l in lines)
    placed = [l for l in lines if l["refused_reason"] is None]
    assert all(l["available_at_ns"] <= l["end_ns"] for l in placed)
    assert all(l["depth_ts_used_ns"] <= l["t0_ns"] for l in placed)


def test_simulator_transitive_import_closure_excludes_truth() -> None:
    closure = drv.import_closure(
        "scripts.analysis.maker_stage0_events_build", prefix="scripts.analysis.maker_stage0_"
    )
    assert "scripts.analysis.maker_stage0_fill" in closure  # the walk reaches the simulator
    assert "scripts.analysis.maker_stage0_adapter" in closure
    forbidden = {
        "scripts.analysis.maker_stage0_inputs",
        "scripts.analysis.maker_stage0_verify_first",
        "scripts.analysis.maker_stage0_report",
        "scripts.analysis.maker_stage0_driver",
        "scripts.analysis.maker_stage0_verdict",
        "scripts.analysis.maker_stage0_tables",
    }
    assert not (forbidden & closure), sorted(forbidden & closure)


def test_import_closure_walk_catches_a_helper_that_imports_truth(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("from pkg import b\n")
    (pkg / "b.py").write_text("from pkg import truthy\n")
    (pkg / "truthy.py").write_text("X = 1\n")
    found = drv.import_closure("pkg.a", prefix="pkg.", root=tmp_path)
    assert found == {"pkg.a", "pkg.b", "pkg.truthy"}


def test_theta_comes_from_the_venue_schedule_not_a_literal() -> None:
    src = Path(drv.__file__).read_text()
    assert "0.0695" not in src and "0.06" not in src
    assert drv.theta_for_day(dt.date(2026, 9, 29)) == pytest.approx(0.0695)


def test_bracketed_unit_runs_both_hypotheses_and_converts_sizes_per_hypothesis(
    world: rw.World, tmp_path: Path
) -> None:
    bracketed = rw.build_world(tmp_path / "w", capture=world.capture, unit="BRACKETED_USD")
    cfg = _fresh(bracketed, tmp_path / "r")
    summary = drv.run(cfg)
    rows = _rows(cfg.out_dir / "station_days.csv")
    assert {r["unit_hypothesis"] for r in rows} == {"USD_NOTIONAL_TAKER", "USD_NOTIONAL_YES"}
    day = {r["unit_hypothesis"]: r for r in rows if r["climate_day"] == "2026-09-29"}
    # the bid sits above the displayed NO level, so nothing is ahead; a 3-notional print is 12
    # contracts under the taker reading and still consumes our own unit.
    assert {d["filled_pairs_base"] for d in day.values()} == {"1"}
    assert all(d["bid_bearing"] == "true" for d in day.values())
    assert summary.label == UNDERPOWERED
    scored = _rows(cfg.out_dir / "scored_episodes.csv")
    assert {r["unit_hypothesis"] for r in scored} == {"USD_NOTIONAL_TAKER", "USD_NOTIONAL_YES"}
    episodes = [json.loads(x) for x in (cfg.out_dir / "episodes.jsonl").read_text().splitlines()]
    assert {e["unit_hypothesis"] for e in episodes} == {"USD_NOTIONAL_TAKER", "USD_NOTIONAL_YES"}
