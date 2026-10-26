"""MAKER-S2 WP6: the run driver (plan r3 WP6 + r4 delta (b)(c)(d)(e)(g)(i)). Fixture world only.

One module-scoped verdict run on the fake capture feeds the output-shape tests; refusal and abort
tests build their own (cheap) configurations. No real catalog, NBP store, truth CSV or node log.
"""

from __future__ import annotations

import ast
import csv
import dataclasses
import datetime as dt
import hashlib
import json
import multiprocessing as mp
import re
import traceback
from collections.abc import Iterator
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, NamedTuple, cast

import pytest

from breezy.runtime import quote_tape_ingest_core as ingest_core
from scripts.analysis import maker_stage0_catalog_read as catalog_read
from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_events_build as eb
from scripts.analysis import maker_stage0_finish as fin
from scripts.analysis import maker_stage0_inputs as inputs
from scripts.analysis import maker_stage0_modes as modes_mod
from scripts.analysis import maker_stage0_preflight as pf
from scripts.analysis import maker_stage0_render as render
from scripts.analysis import maker_stage0_report as rep
from scripts.analysis import maker_stage0_scoped_convert as sc
from scripts.analysis import maker_stage0_verify_first as vf
from scripts.analysis.maker_stage0_catalog_read import CatalogSession, query_window_ns
from scripts.analysis.maker_stage0_events_build import LocalDayViolation
from scripts.analysis.maker_stage0_fill_events import DeltaBoundExceeded, EventError, LeakageError
from scripts.analysis.maker_stage0_frozen import FrozenSetRefused
from scripts.analysis.maker_stage0_inputs import InputRefused
from scripts.analysis.maker_stage0_ledger import LedgerRefused
from scripts.analysis.maker_stage0_pins import CatalogSliceManifest, DirtyTree
from scripts.analysis.maker_stage0_pno_store import PNoStoreReadError, StationRefusedError
from scripts.analysis.maker_stage0_probe_core import StopS2
from scripts.analysis.maker_stage0_rows import CsvCellError, CsvColumnError
from scripts.analysis.maker_stage0_scored import VerdictRefused
from scripts.analysis.maker_stage0_verdict import UNDERPOWERED
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.support.stage0_outputs import VOLATILE, _normalised
from tests.unit import test_maker_stage0_pins as pins_fx
from tests.unit import test_maker_stage0_pno as pno_fx
from tests.unit.test_maker_stage0_probe import _slug as pt_slug

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
#: Module-scoped runs that tests share read-only; `_shared_outputs_unchanged` guards each.
SHARED_RUN_FIXTURES = ("e2e", "s4_stop", "inprocess_spied")


Digests = tuple[tuple[str, str], ...]


@dataclasses.dataclass(frozen=True)
class Run:
    cfg: drv.RunConfig
    run_dir: Path
    repo: Path
    summary: drv.RunSummary
    world: rw.World
    atomic_writes: tuple[str, ...] = ()
    digests: Digests = ()


class SpySnapshot(NamedTuple):
    pulled: int


class InProcessSpied(NamedTuple):
    """The one in-process (`isolate=False`) run with the order spy and the consumed-iterator spy."""

    order: tuple[str, ...]
    early_pulls: tuple[int, ...]
    spies: tuple[SpySnapshot, ...]
    cfg: drv.RunConfig
    digests: Digests


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digests_of(cfg: drv.RunConfig) -> Digests:
    """Every path under the run dir, the ledger file, and the repo's HEAD and dirty state.

    `work_root` is excluded on purpose: test_driver_refuses_existing_run_dir calls
    `drv.run(e2e.cfg)` again, which may touch scratch there before it raises `RunDirExists`.
    """
    entries: list[tuple[str, str]] = []
    for path in sorted(cfg.out_dir.rglob("*")):
        rel = "run_dir/" + path.relative_to(cfg.out_dir).as_posix()
        entries.append((rel, _sha256(path) if path.is_file() else "<dir>"))
    entries.append(("ledger", _sha256(cfg.ledger) if cfg.ledger.exists() else "<absent>"))
    entries.append(("git_head", pins_fx._git(cfg.repo_root, "rev-parse", "HEAD").strip()))
    status = pins_fx._git(cfg.repo_root, "status", "--porcelain")
    entries.append(("git_status", hashlib.sha256(status.encode()).hexdigest()))
    return tuple(entries)


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
def e2e(world: rw.World, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """One verdict run on the fixture world, shared read-only by every `e2e` consumer.

    It also records which files `fin` wrote atomically (a pass-through spy). Its digest covers
    the run dir, the ledger and the repo state, but NOT `work_root`: test
    `test_driver_refuses_existing_run_dir` calls `drv.run(e2e.cfg)`, which may touch scratch
    there before it raises. `_shared_outputs_unchanged` re-checks the digest after each test.
    """
    base = tmp_path_factory.mktemp("e2e")
    repo = pins_fx._repo(base)
    written: list[str] = []
    real = inputs.write_text_atomic

    def spy(path: Path, text: str) -> Path:
        written.append(path.name)
        return real(path, text)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())
        mp.setattr(fin, "write_text_atomic", spy)
        cfg = make_cfg(world, base, repo)
        summary = drv.run(cfg)
    return Run(cfg, cfg.out_dir, repo, summary, world, tuple(written), _digests_of(cfg))


@pytest.fixture(scope="module")
def s4_stop(tmp_path_factory: pytest.TempPathFactory) -> Run:
    """One STOP-S4 run (no covered bid-bearing day): completes, never voids."""
    base = tmp_path_factory.mktemp("s4_stop")
    world = rw.build_world(base / "w", census_changes={"covered_bidlive": False})
    cfg = _fresh(world, base / "r")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())
        summary = drv.run(cfg)
    return Run(cfg, cfg.out_dir, cfg.repo_root, summary, world, (), _digests_of(cfg))


@pytest.fixture(scope="module")
def inprocess_spied(world: rw.World, tmp_path_factory: pytest.TempPathFactory) -> InProcessSpied:
    """One `isolate=False` run with both spies, for the two structure tests.

    `sim643` wraps `sim618`, which wraps the real `simulate_station_day`, so the consumed-iterator
    spy wraps the episodes the order spy let through. `verify_first_s6` is forbidden inside a
    verdict run. The guards fail the fixture if a spy never fired, so no test can pass vacuously.
    """
    base = tmp_path_factory.mktemp("inprocess_spied")
    cfg = _fresh(world, base, isolate=False)
    episodes_path = cfg.out_dir / "episodes.jsonl"
    real_sim, real_truth = eb.simulate_station_day, rep.load_truth
    order: list[str] = []
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

    def sim618(*args: Any, **kw: Any) -> Any:
        order.append("sim")
        return real_sim(*args, **kw)

    def sim643(*args: Any, **kw: Any) -> Any:
        result = sim618(*args, **kw)
        if not result.episodes:
            return result
        spy = Spy(result.episodes)
        spies.append(spy)
        return dataclasses.replace(result, episodes=cast(Any, spy))

    def truth(*args: Any, **kw: Any) -> Any:
        order.append("truth")
        return real_truth(*args, **kw)

    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("verify-first must not run inside a verdict run")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())
        mp.setattr(eb, "simulate_station_day", sim643)
        mp.setattr(rep, "load_truth", truth)
        mp.setattr(drv, "verify_first_s6", never)
        drv.run(cfg)
    if not spies or not order:
        raise AssertionError("the in-process run never reached its spies")
    return InProcessSpied(
        tuple(order),
        tuple(early_pulls),
        tuple(SpySnapshot(s.pulled) for s in spies),
        cfg,
        _digests_of(cfg),
    )


@pytest.fixture(autouse=True)
def _shared_outputs_unchanged(request: pytest.FixtureRequest) -> Iterator[None]:
    """Fail (as a teardown error) any test that altered a shared run's outputs."""
    yield
    for name in SHARED_RUN_FIXTURES:
        shared = request.node.funcargs.get(name)
        if shared is not None:
            assert _digests_of(shared.cfg) == shared.digests, f"{name} outputs changed"


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
        (r["station"], r["climate_day"], r["unit_hypothesis"]): r
        for r in _rows(e2e.run_dir / "station_days.csv")
    }
    day = sd[("SFO", "2026-09-29", "CONTRACTS")]
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
    # replayed or not: 4 frozen stations x 25 rule days, 2026-10-01 absent.
    keys = [(r["station"], r["climate_day"], r["unit_hypothesis"]) for r in rows]
    assert len(keys) == len(set(keys)) == 4 * len(rw.rule_days())
    assert "2026-10-01" not in {k[1] for k in keys}
    unreplayed = next(r for r in rows if r["climate_day"] == "2026-09-25" and r["station"] == "SFO")
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
        "index", "of", "station", "climate_day", "status", "elapsed_s", "rss_bytes", "n_events",
        "rss_peak_delta_bytes", "peak_rss_bytes", "parent_rss_bytes",
    }  # fmt: skip
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
        if r["climate_day"] == "2026-09-29" and r["station"] == "SFO"
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
    assert render.BANNER in text and "never emits a go verdict" in text
    assert "## Pins" in text and e2e.summary.code_sha in text and e2e.world.amendment_sha in text
    assert render.HOLDOUT_LINE in text
    for phrase in ("clause 3", "descriptive", "open_holdout", "2026-10-01"):
        assert phrase in render.HOLDOUT_LINE
    assert "run-time only, sha-pinned" in text  # sidecar-backed blocks are labelled
    assert "Overlay schedule (report-only)" in text and "Stress variants (report-only)" in text


def test_stats_rerun_on_scored_csv_reproduces_tables(e2e: Run) -> None:
    from scripts.analysis.maker_stage0_tables import tables_from_csvs

    tables = tables_from_csvs(
        e2e.run_dir / "scored_episodes.csv",
        e2e.run_dir / "station_days.csv",
        e2e.run_dir / "tail_reliability.csv",
        hypotheses=["CONTRACTS"],
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


def _fresh(
    world: rw.World, tmp_path: Path, *, pinned_dates: bool = False, **over: Any
) -> drv.RunConfig:
    repo = pins_fx._repo(tmp_path, pinned_dates=pinned_dates)
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
    with pytest.raises(drv.RunVoided, match="last|rule|differs") as info:
        drv.run(cfg)  # needs the truth CSV's last FINAL day: decided by score, after the claim
    assert isinstance(info.value.cause, FrozenSetRefused)


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
    with pytest.raises(drv.RunVoided, match="S-7") as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, DeltaBoundExceeded)
    assert touched == []  # neither a simulation nor the truth file was reached
    assert _void_dir(cfg).is_dir() and not cfg.out_dir.exists()
    kinds = [e["kind"] for e in _ledger(cfg)]
    assert kinds == ["verdict_run_start", "void"]
    assert not [n for n in RESULT_FILES if (_void_dir(cfg) / n).exists()]


def _dense_spike_cfg(tmp_path: Path, *spike_isos: str) -> drv.RunConfig:
    """Fixture capture plus 0.1 s samples at 45 s spacing around 01:30Z with 700 s at the spikes."""
    around = [("2026-09-29T01:29:15", 0.1), ("2026-09-29T01:31:30", 0.1)]
    spikes = tuple((iso, 700.0) for iso in spike_isos)
    world = rw.build_world(
        tmp_path / "w",
        capture=rw.build_capture(tmp_path / "w", extra_offsets=(*around, *spikes)),
    )
    return _fresh(world, tmp_path / "r")


def test_isolated_700s_spike_with_dense_neighbours_no_longer_voids_the_run(
    tmp_path: Path,
) -> None:
    cfg = _dense_spike_cfg(tmp_path, "2026-09-29T01:30:00")

    drv.run(cfg)  # S-7 estimator: an isolated stale frame is clamped, the run proceeds

    assert not _void_dir(cfg).exists() and cfg.out_dir.is_dir()


def test_two_consecutive_700s_samples_still_void_the_run(tmp_path: Path) -> None:
    cfg = _dense_spike_cfg(tmp_path, "2026-09-29T01:30:00", "2026-09-29T01:30:45")

    with pytest.raises(drv.RunVoided, match="S-7") as info:
        drv.run(cfg)

    assert isinstance(info.value.cause, DeltaBoundExceeded)
    assert _void_dir(cfg).is_dir() and not cfg.out_dir.exists()


def test_inverted_direction_voids_run_s2(tmp_path: Path) -> None:
    world = rw.build_world(tmp_path / "w", capture=rw.build_capture(tmp_path / "w", inverted=True))
    cfg = _fresh(world, tmp_path / "r")
    with pytest.raises(drv.RunVoided) as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, StopS2)
    void = _void_dir(cfg)
    agreement = json.loads((void / "wp0_agreement.json").read_text())  # written BEFORE the STOP
    assert agreement["direction"]["verdict"] == "INVERTED"
    assert not [n for n in RESULT_FILES if (void / n).exists()]
    assert [e["kind"] for e in _ledger(cfg)] == ["verdict_run_start", "void"]


def test_rss_over_four_gib_aborts_and_voids_run(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drv, "current_rss_bytes", lambda: 5 * 2**30)
    cfg = _fresh(world, tmp_path, isolate=False)
    with pytest.raises(drv.RunVoided, match="S-5") as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, drv.MemoryAbort)
    assert _void_dir(cfg).is_dir()


def test_a_void_run_may_be_rerun_only_with_a_dated_addendum(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drv, "current_rss_bytes", lambda: 5 * 2**30)
    cfg = _fresh(world, tmp_path, isolate=False)
    with pytest.raises(drv.RunVoided):
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
    cfg = _fresh(world, tmp_path, bench=4, stations=("SFO",), days=(rw.DAY, rw.DIRECTION_DAY))
    summary = drv.run(cfg)
    assert touched == []
    names = {p.name for p in cfg.out_dir.iterdir()}
    assert names == {"bench.json", "progress.jsonl", "run_manifest.json"}
    bench = json.loads((cfg.out_dir / "bench.json").read_text())
    session = CatalogSession(world.capture, tmp_path / "plan_work")
    plans = session.plan([rw.DAY, rw.DIRECTION_DAY], ["SFO"])
    rows = bench["station_days"]
    assert len(rows) == 3  # N = 4 over two replayed days: both timed, then the heaviest again
    assert [bool(r.get("repeat_of_first")) for r in rows] == [False, False, True]
    assert (rows[2]["station"], rows[2]["climate_day"]) in {
        (r["station"], r["climate_day"]) for r in rows[:2]
    }
    by_day = {r["climate_day"]: r for r in bench["station_days"]}
    for (_, day), plan in plans.items():  # weights are capture bytes only
        assert by_day[day.isoformat()]["catalog_bytes"] == plan.catalog_bytes > 0
    only = bench["station_days"][0]
    assert only["elapsed_s"] >= 0 and only["peak_rss_bytes"] > 0
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


def test_driver_scores_only_after_simulation_completes(inprocess_spied: InProcessSpied) -> None:
    order = list(inprocess_spied.order)
    assert order.count("truth") == 1 and order[-1] == "truth"
    assert order.count("sim") >= 2 and "truth" not in order[:-1]


def test_driver_writes_each_episode_to_disk_before_the_next_is_pulled(
    inprocess_spied: InProcessSpied,
) -> None:
    spies = list(inprocess_spied.spies)
    early_pulls = list(inprocess_spied.early_pulls)
    episodes_path = inprocess_spied.cfg.out_dir / "episodes.jsonl"

    def written() -> int:
        return len(episodes_path.read_text().splitlines()) if episodes_path.exists() else 0

    consumed = [s for s in spies if s.pulled]
    assert consumed and sum(s.pulled for s in consumed) == written()  # the primary pass only
    assert early_pulls == []  # never pulled ahead of the file: nothing accumulated first


def test_a_late_first_print_contradicting_the_frozen_block_voids_the_run(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    late = int(dt.datetime(2026, 9, 17, 18, 0, tzinfo=dt.UTC).timestamp()) * 10**9
    monkeypatch.setattr(drv, "first_print_instant", lambda *a, **k: late)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(drv.RunVoided, match="replayable day") as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, drv.InputRefused)
    assert _void_dir(cfg).is_dir()


def test_episodes_jsonl_has_one_line_per_primary_episode_and_valid_leakage_fields(e2e: Run) -> None:
    lines = [json.loads(x) for x in (e2e.run_dir / "episodes.jsonl").read_text().splitlines()]
    assert lines and all(l["unit_hypothesis"] == "CONTRACTS" for l in lines)
    placed = [l for l in lines if l["refused_reason"] is None]
    assert all(l["available_at_ns"] <= l["end_ns"] for l in placed)
    assert all(l["depth_ts_used_ns"] <= l["t0_ns"] for l in placed)


#: sha256 of the fixture run's result files, taken on d563e702 BEFORE the S-5 time optimisations
GOLDEN_RESULT_SHA256 = {
    "episodes.jsonl": "8a3e7f3b8922375eca95e947abcea16cfd5c13027e53f5fb2ea77282ce2835e9",
    "station_days.csv": "7cf762357f754c3aaae291d9f21a1fa492f4fbdee96514d55dcf208d97a1fc3d",
    "scored_episodes.csv": "14879a8c2efdfcfaaa1820cf22463bd8d0888a9d4920fef345e596b1965647ec",
}


@pytest.mark.parametrize("name", sorted(GOLDEN_RESULT_SHA256))
def test_fixture_result_files_are_byte_identical_to_the_pre_optimisation_golden(
    e2e: Run, name: str
) -> None:
    digest = hashlib.sha256((e2e.run_dir / name).read_bytes()).hexdigest()
    assert digest == GOLDEN_RESULT_SHA256[name]


SIM_PREFIX = "scripts.analysis.maker_stage0_"
REPO_ROOT = Path(__file__).resolve().parents[2]
TRUTH_NAMES = {"load_truth", "TruthTable", "load_tail_truth"}
SIM_ROOTS = ("station_loop", "runio", "events_build", "adapter", "modes", "catalog_read")


def test_simulation_loop_import_closure_never_reaches_truth() -> None:
    union: set[str] = set()
    for root in SIM_ROOTS:
        closure = drv.import_closure(SIM_PREFIX + root, prefix=SIM_PREFIX)
        assert SIM_PREFIX + "fill" in drv.import_closure(
            SIM_PREFIX + "events_build", prefix=SIM_PREFIX
        )
        banned = {
            SIM_PREFIX + n
            for n in ("report", "driver", "verify_first", "render", "preflight", "finish", "pins")
        }
        assert not (banned & closure), (root, sorted(banned & closure))
        union |= closure
    for name in sorted(union):  # no module the loop can reach even IMPORTS the truth loader
        path = REPO_ROOT.joinpath(*name.split(".")).with_suffix(".py")
        if not path.is_file():  # `from pkg.mod import NAME` also yields "pkg.mod.NAME"
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
        }
        assert not (imported & TRUTH_NAMES), (name, sorted(imported & TRUTH_NAMES))
    strict = drv.import_closure(SIM_PREFIX + "events_build", prefix=SIM_PREFIX)
    assert SIM_PREFIX + "adapter" in strict
    assert not ({SIM_PREFIX + "inputs", SIM_PREFIX + "tables", SIM_PREFIX + "verdict"} & strict)


def test_import_closure_walk_catches_a_helper_that_imports_truth(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("from pkg import b\n")
    (pkg / "b.py").write_text("from pkg import truthy\n")
    (pkg / "truthy.py").write_text("X = 1\n")
    found = drv.import_closure("pkg.a", prefix="pkg.", root=tmp_path)
    assert found == {"pkg.a", "pkg.b", "pkg.truthy"}


def test_import_closure_ignores_imports_that_only_exist_for_type_checking(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg import truthy\n"
        "from pkg import real\n"
    )
    (pkg / "real.py").write_text("X = 1\n")
    (pkg / "truthy.py").write_text("X = 1\n")
    assert drv.import_closure("pkg.a", prefix="pkg.", root=tmp_path) == {"pkg.a", "pkg.real"}


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
    day = {
        r["unit_hypothesis"]: r
        for r in rows
        if r["climate_day"] == "2026-09-29" and r["station"] == "SFO"
    }
    # the bid sits above the displayed NO level, so nothing is ahead; a 3-notional print is 12
    # contracts under the taker reading and still consumes our own unit.
    assert {d["filled_pairs_base"] for d in day.values()} == {"1"}
    assert all(d["bid_bearing"] == "true" for d in day.values())
    assert summary.label == UNDERPOWERED
    scored = _rows(cfg.out_dir / "scored_episodes.csv")
    assert {r["unit_hypothesis"] for r in scored} == {"USD_NOTIONAL_TAKER", "USD_NOTIONAL_YES"}
    episodes = [json.loads(x) for x in (cfg.out_dir / "episodes.jsonl").read_text().splitlines()]
    assert {e["unit_hypothesis"] for e in episodes} == {"USD_NOTIONAL_TAKER", "USD_NOTIONAL_YES"}


# --- WP5 contract (delta (r)) ------------------------------------------------------------------

STOP_S4 = "STOP-S4-NO-BID-BEARING-DAYS"


def test_s4_no_bid_bearing_days_is_a_reported_stop_not_a_void(s4_stop: Run) -> None:
    cfg, summary = s4_stop.cfg, s4_stop.summary  # the run completed: the caller (CLI) exits 0
    assert summary.label == STOP_S4 and summary.run_dir == cfg.out_dir
    assert not _void_dir(cfg).exists() and cfg.out_dir.is_dir()
    s3 = json.loads((cfg.out_dir / "s3_inputs.json").read_text())
    assert s3["verdict"] == STOP_S4
    assert {k for k, v in s3.items() if v is not None} == {"verdict"}  # every other key null
    assert f"Verdict: {STOP_S4}" in (cfg.out_dir / "report.md").read_text()
    manifest = json.loads((cfg.out_dir / "run_manifest.json").read_text())
    assert manifest["verdict"] == STOP_S4 and manifest["phases"][-1] == "report"
    assert [e["kind"] for e in _ledger(cfg)] == ["verdict_run_start"]  # the entry stays


def test_s4_stop_s3_inputs_carry_exactly_the_keys_of_a_real_verdict(e2e: Run, s4_stop: Run) -> None:
    real = json.loads((e2e.run_dir / "s3_inputs.json").read_text())
    cfg = s4_stop.cfg
    assert set(json.loads((cfg.out_dir / "s3_inputs.json").read_text())) == set(real)


def test_theta_outside_zero_to_point_two_is_refused_before_the_ledger(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pf, "theta_for_day", lambda _day: 0.25)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(drv.InputRefused, match="theta"):
        drv.run(cfg)
    _assert_untouched(cfg)


def test_replayed_station_days_carry_both_denominator_columns(e2e: Run) -> None:
    rows = _rows(e2e.run_dir / "station_days.csv")
    day = next(r for r in rows if r["climate_day"] == "2026-09-29" and r["station"] == "SFO")
    assert int(day["rung_trials_attempted"]) >= 1 and int(day["n_no_book_wants"]) >= 0
    unreplayed = next(r for r in rows if r["climate_day"] == "2026-09-25" and r["station"] == "SFO")
    assert unreplayed["n_no_book_wants"] in ("", "0")


def test_truth_token_is_one_function_and_a_missing_final_is_blank_at_any_age() -> None:
    high = pt_slug("sfo", rw.FILL_RUNG, "2026-09-29")
    band = pt_slug("sfo", "gte60lt61f", "2026-09-29")
    assert rep.truth_token(high, None) == ""  # no FINAL row: never UNRESOLVED, however old
    assert rep.truth_token(high, rw.TRUTH_TMAX_F) == "NO"
    assert rep.truth_token(band, 60) == "YES"
    assert rep.day_truth(None) == {
        "truth_final": False, "truth_tmax_f": None, "void": False, "unresolved_d14": False,
    }  # fmt: skip
    assert rep.day_truth(70)["truth_final"] is True
    assert not hasattr(rep, "UNRESOLVED_AFTER_DAYS")


# --- review fixes: listing abstention (pmr H1) -------------------------------------------------


def test_a_ladder_listed_after_d_minus_1_noon_is_a_listing_abstention_not_a_bid(
    tmp_path: Path,
) -> None:
    late = rw.build_capture(tmp_path / "w", listed_iso="2026-09-28T13:00:00")
    cfg = _fresh(rw.build_world(tmp_path / "w", capture=late), tmp_path / "r")
    summary = drv.run(cfg)
    rows = _rows(cfg.out_dir / "station_days.csv")
    day = next(r for r in rows if r["station"] == "SFO" and r["climate_day"] == "2026-09-29")
    assert day["covered"] == "true" and day["bid_bearing"] == "false"  # covered, never bid
    assert int(day["n_attempts"] or 0) == 0 and int(day["n_episodes"] or 0) == 0
    assert summary.label == "STOP-S4-NO-BID-BEARING-DAYS"  # the only bid-bearing day is gone
    assert "listing_abstained: 1" in (cfg.out_dir / "report.md").read_text()
    assert not [
        r for r in _rows(cfg.out_dir / "scored_episodes.csv") if r["climate_day"] == "2026-09-29"
    ]


def test_a_ladder_listed_in_time_reports_zero_listing_abstentions(e2e: Run) -> None:
    assert "listing_abstained: 0" in (e2e.run_dir / "report.md").read_text()


# --- review fixes: licence of the tail-only stations (pmr H3) ----------------------------------


@pytest.mark.parametrize(
    "parity", [(("NYC", 0),), (("SFO", 0), ("NYC", 1)), (("XYZ", 0),)], ids=["nyc", "mixed", "xyz"]
)
def test_tail_only_refuses_a_station_outside_the_maker_set_before_any_read(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parity: tuple[Any, ...]
) -> None:
    def read(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a read happened before the station licence was checked")

    monkeypatch.setattr(rep, "load_tail_truth", read)
    monkeypatch.setattr(drv, "_preflight", read)
    cfg = _fresh(world, tmp_path, tail_only=True, parity=parity)
    with pytest.raises(drv.InputRefused, match="NYC|XYZ|MAKER"):
        drv.run(cfg)
    assert not cfg.out_dir.exists()


# --- review fixes: typed exit codes (py H1) ----------------------------------------------------

BOOM = "boom-original-cause"
ERRORS: list[BaseException] = [
    EventError(BOOM), LeakageError(BOOM), LocalDayViolation(BOOM), PNoStoreReadError(Path(BOOM)),
    VerdictRefused(BOOM), CsvCellError(BOOM), CsvColumnError(BOOM), OSError(BOOM),
    ValueError(BOOM), RuntimeError(BOOM), StationRefusedError(BOOM), InputRefused(BOOM),
    DeltaBoundExceeded(BOOM), drv.MemoryAbort(BOOM),
]  # fmt: skip


@pytest.mark.parametrize("exc", ERRORS, ids=lambda e: type(e).__name__)
def test_every_post_claim_failure_is_a_typed_void(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    def fail(*_a: Any, **_k: Any) -> Any:
        raise exc

    monkeypatch.setattr(drv, "_wp0", fail)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(drv.RunVoided) as info:
        drv.run(cfg)
    assert info.value.cause is exc and type(exc).__name__ in str(info.value)
    assert _void_dir(cfg).is_dir() and not cfg.out_dir.exists()
    assert [e["kind"] for e in _ledger(cfg)] == ["verdict_run_start", "void"]


@pytest.mark.parametrize("exc", ERRORS, ids=lambda e: type(e).__name__)
def test_every_pre_claim_failure_propagates_raw_and_leaves_the_ledger_untouched(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    def fail(*_a: Any, **_k: Any) -> Any:
        raise exc

    monkeypatch.setattr(drv, "_preflight", fail)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(type(exc)):
        drv.run(cfg)
    _assert_untouched(cfg)


def test_a_failing_void_keeps_the_original_cause_in_the_message(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_a: Any, **_k: Any) -> Any:
        raise LeakageError(BOOM)

    def no_void(*_a: Any, **_k: Any) -> Any:
        raise LedgerRefused("cannot rename the run directory")

    monkeypatch.setattr(drv, "_wp0", fail)
    monkeypatch.setattr(drv, "void_run_dir", no_void)
    with pytest.raises(drv.RunVoided) as info:
        drv.run(_fresh(world, tmp_path))
    assert isinstance(info.value.cause, LeakageError)
    assert BOOM in str(info.value) and "cannot rename" in str(info.value)


# --- review fixes: determinism (py H2) and the capture-hashed manifest (py H3) -----------------

PROBE_KEY = "breezy-determinism-probe"
CHILD_HASH_SEED = "20260101"  # fixed and non-zero: the parent's own seed is random per process
CHILD_TIMEOUT_S = 600.0
_JOIN_S = 30.0


def _probe() -> int:
    """A string hash: equal across processes only when their PYTHONHASHSEED values are equal."""
    return hash(PROBE_KEY)


def run_once(conn: Connection, cfg: drv.RunConfig | None) -> None:
    """Spawned-child entry (top level so ``spawn`` can import it): one cold run, or the probe only.

    Sends ``("ok", probe)`` or ``("err", traceback text)``; exception objects are never pickled.
    """
    try:
        if cfg is not None:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())
                drv.run(cfg)
        conn.send(("ok", _probe()))
    except Exception:  # noqa: BLE001 - reported to the parent, which fails the test with it
        conn.send(("err", traceback.format_exc()))
    finally:
        conn.close()


def _cold_probe(cfg: drv.RunConfig | None, seed: str) -> int:
    """Run ``run_once`` in ONE spawned child under ``PYTHONHASHSEED=seed``; return its probe."""
    ctx = mp.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=run_once, args=(sender, cfg))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PYTHONHASHSEED", seed)
        proc.start()
    sender.close()
    if not receiver.poll(CHILD_TIMEOUT_S):
        proc.kill()
        proc.join(_JOIN_S)
        pytest.fail(f"the determinism child gave no result in {CHILD_TIMEOUT_S:.0f} s")
    try:
        status, payload = receiver.recv()
    except EOFError:
        status, payload = "err", "the child closed its pipe without a result"
    proc.join(_JOIN_S)
    if status != "ok":
        pytest.fail(f"the determinism child failed:\n{payload}")
    assert proc.exitcode == 0, f"the determinism child exited with {proc.exitcode}"
    return int(payload)


def test_probe_children_agree_on_one_seed_and_differ_across_seeds() -> None:
    """Positive control for the hash-seed difference the determinism test relies on."""
    same = (_cold_probe(None, "11"), _cold_probe(None, "11"))
    other = _cold_probe(None, "22")
    assert same[0] == same[1]
    assert other != same[0]


def test_full_run_is_deterministic(
    world: rw.World, tmp_path: Path, inprocess_spied: InProcessSpied
) -> None:
    """Run A: warm parent (memo + caches populated, parent hash seed). Run B: ONE cold child with
    another PYTHONHASHSEED. Every output file must match once run-specific values are blanked.

    Both runs are `isolate=False`: the isolate-equivalence tests pin isolated == in-process.
    """
    assert sc._SCANS, "run A must be warm: `inprocess_spied` fills the scan memo in this process"
    first = _fresh(world, tmp_path / "a", isolate=False, pinned_dates=True)
    second = _fresh(world, tmp_path / "b", isolate=False, pinned_dates=True)
    drv.run(first)
    child_probe = _cold_probe(second, CHILD_HASH_SEED)
    assert _probe() != child_probe, "the child shared the parent's hash seed: B would add nothing"
    a, b = first.out_dir, second.out_dir
    commits = [json.loads((d / "run_manifest.json").read_text())["git_commit"] for d in (a, b)]
    assert commits[0] == commits[1], "pinned git dates must give equal commits before masking"
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir())
    assert (a / "episodes.jsonl").stat().st_size > 0
    with (a / "scored_episodes.csv").open(newline="") as handle:
        assert list(csv.DictReader(handle)), "scored_episodes.csv has no data rows"
    with (a / "station_days.csv").open(newline="") as handle:
        assert sum(int(r["n_episodes"] or 0) for r in csv.DictReader(handle)) > 0
    for name in sorted(set(names) - VOLATILE):
        assert _normalised(first, name) == _normalised(second, name), name


def test_catalog_slice_manifest_hashes_the_capture_files_by_relative_path(e2e: Run) -> None:
    files = json.loads((e2e.run_dir / "catalog_slice_manifest.json").read_text())["files"]
    assert files
    for entry in files:
        assert set(entry) == {"path", "size", "sha256"}  # no mtime, no absolute path
        source = e2e.world.capture / entry["path"]
        assert not Path(entry["path"]).is_absolute() and source.is_file()
        assert entry["size"] == source.stat().st_size
        assert entry["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert not [e for e in files if "work" in e["path"] or "replay" in e["path"]]


def test_lru_eviction_removes_scratch_and_a_reconverted_instance_keeps_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w", second_instance=True)
    scratch = tmp_path / "scratch"
    manifest = CatalogSliceManifest()
    session = CatalogSession(capture, scratch, manifest, keep=1)
    plan = session.plan([rw.DAY], ["SFO"])[("SFO", rw.DAY)]
    assert plan.instances == ("inst-a", "inst-b")
    window = query_window_ns("SFO", rw.DAY)
    converted: list[str] = []
    real = ingest_core.default_convert

    def spy(source: Any, instance: str, data_cls: Any, *a: Any, **k: Any) -> Any:
        converted.append(instance)
        return real(source, instance, data_cls, *a, **k)

    monkeypatch.setattr(catalog_read, "default_convert", spy)
    session.read(plan, window)  # a converted, then evicted when b arrives
    assert sorted(p.name for p in (scratch / "replay").iterdir()) == ["inst-b"]
    first = manifest.to_dict()
    session.read(plan, window)  # a re-converted (new mtimes), b evicted, b re-converted
    assert sorted(p.name for p in (scratch / "replay").iterdir()) == ["inst-b"]
    assert sorted(set(converted)) == ["inst-a", "inst-b"] and converted.count("inst-a") == 2 * len(
        catalog_read.REPLAY_STREAMS
    )  # every stream of a was converted twice
    assert manifest.to_dict() == first  # same capture bytes: same manifest, no "changed" error
    session.close()
    assert not list((scratch / "replay").iterdir())


# --- review fixes: preflight completeness (pmr M2, M3) -----------------------------------------


@pytest.mark.parametrize("what", ["cross_check", "nbp_manifest", "spec", "uv_lock", "node_log_dir"])
def test_a_missing_pinned_input_is_refused_before_the_ledger_claim(
    world: rw.World, tmp_path: Path, what: str
) -> None:
    cfg = _fresh(world, tmp_path)
    missing = tmp_path / "does_not_exist"
    over: dict[str, Any] = {
        "cross_check": {"truth_cross_check": missing},
        "nbp_manifest": {"nbp_root": missing},
        "spec": {"spec": missing},
        "uv_lock": {},
        "node_log_dir": {"node_log_dir": missing},
    }[what]
    if what == "uv_lock":
        (cfg.repo_root / "uv.lock").unlink()
    cfg = dataclasses.replace(cfg, **over)
    with pytest.raises(drv.InputRefused):
        drv.run(cfg)
    _assert_untouched(cfg)


def test_a_frozen_station_day_without_a_census_row_is_refused_before_the_ledger(
    world: rw.World, tmp_path: Path
) -> None:
    from tests.fixtures.maker_stage0 import make_census_fixture as fx

    rows = [r for r in rw.census_rows() if not (r.station == "MIA" and r.climate_day == rw.DAY)]
    fx.write_census_fixture(tmp_path / "census.jsonl", rows)
    cfg = dataclasses.replace(_fresh(world, tmp_path), census_days=tmp_path / "census.jsonl")
    with pytest.raises(FrozenSetRefused, match="MIA"):
        drv.run(cfg)
    _assert_untouched(cfg)


def test_a_duplicate_census_row_for_a_frozen_station_day_is_refused(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.analysis import maker_stage0_preflight as pf
    from scripts.analysis.maker_stage0_inputs import CensusLoad

    rows = rw.census_rows()
    monkeypatch.setattr(pf, "load_census_days", lambda _p: CensusLoad((*rows, rows[0]), 0))
    cfg = _fresh(world, tmp_path)
    with pytest.raises(FrozenSetRefused, match="duplicate"):
        drv.run(cfg)
    _assert_untouched(cfg)


# --- review fixes: bench licence and projection (pmr M4) ---------------------------------------


@pytest.mark.parametrize("n", [1, 3, 5, 100])
def test_bench_refuses_a_count_other_than_four_or_eight(
    world: rw.World, tmp_path: Path, n: int
) -> None:
    cfg = _fresh(world, tmp_path, bench=n, stations=("SFO",), days=(rw.DAY,))
    with pytest.raises(drv.SubsetRefused, match="4"):
        drv.run(cfg)
    assert not cfg.out_dir.exists()


def test_bench_weighs_replayed_days_only_and_runs_every_variant(
    world: rw.World, tmp_path: Path
) -> None:
    cfg = _fresh(world, tmp_path, bench=8, stations=("SFO", "LAX"), days=(rw.DAY, rw.DIRECTION_DAY))
    drv.run(cfg)
    bench = json.loads((cfg.out_dir / "bench.json").read_text())
    assert {r["station"] for r in bench["station_days"]} == {"SFO"}  # LAX is never listed
    assert bench["n_replayable_station_days"] == 2
    assert bench["variants"] == ["primary", "overlay", "plus60", "poll_lag", "delta0"]


# --- review fixes: provenance (pmr M7), atomic writes, mutually exclusive modes ----------------


def test_the_tail_csv_source_and_episodes_jsonl_are_pinned(world: rw.World, tmp_path: Path) -> None:
    tail = tmp_path / "tail_reliability.csv"
    tail.write_text("station,climate_day,vector,p_yes,outcome\n")
    cfg = _fresh(world, tmp_path / "r", tail_csv=tail)
    drv.run(cfg)
    pins = json.loads((cfg.out_dir / "pins.json").read_text())
    assert pins["tail_csv_source"]["sha256"] == hashlib.sha256(tail.read_bytes()).hexdigest()
    episodes = (cfg.out_dir / "episodes.jsonl").read_bytes()
    assert pins["episodes_jsonl"]["sha256"] == hashlib.sha256(episodes).hexdigest()


def test_result_files_are_written_atomically(e2e: Run) -> None:
    written = e2e.atomic_writes
    assert {"s3_inputs.json", "report.md", "station_days.csv", "scored_episodes.csv",
            "tail_reliability.csv"} <= set(written)  # fmt: skip


@pytest.mark.parametrize("mode", ["bench", "tail", "verify"])
def test_report_only_modes_clean_up_on_failure(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    def fail(*_a: Any, **_k: Any) -> Any:
        raise OSError("disk full")

    options: dict[str, dict[str, Any]] = {
        "bench": {"bench": 4, "stations": ("SFO",), "days": (rw.DAY,)},
        "tail": {"tail_only": True, "parity": (("SFO", 0),)},
        "verify": {"verify_first": True},
    }
    over = options[mode]
    monkeypatch.setattr(modes_mod, "simulate", fail)
    monkeypatch.setattr(rep, "load_tail_truth", fail)
    monkeypatch.setattr(drv, "verify_first_s6", fail)
    cfg = _fresh(world, tmp_path, **over)
    with pytest.raises(OSError, match="disk full"):
        drv.run(cfg)
    assert not cfg.out_dir.exists() and not cfg.work_root.exists()


# --- review fixes: RSS watch (py MED 5) --------------------------------------------------------


def test_peak_rss_is_checked_inside_the_day_not_only_after_it(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drv, "peak_rss_bytes", lambda: 5 * 2**30)  # a mid-day spike
    cfg = _fresh(world, tmp_path, isolate=False)
    with pytest.raises(drv.RunVoided, match="S-5") as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, drv.MemoryAbort)


def test_progress_lines_carry_the_ru_maxrss_delta_per_station_day(e2e: Run) -> None:
    lines = [json.loads(x) for x in (e2e.run_dir / "progress.jsonl").read_text().splitlines()]
    assert all(e["rss_peak_delta_bytes"] >= 0 and e["peak_rss_bytes"] > 0 for e in lines)


# --- review fixes: disclosures (pmr D1-D8) -----------------------------------------------------


def test_the_report_carries_every_disclosure_obligation(e2e: Run) -> None:
    text = (e2e.run_dir / "report.md").read_text()
    assert "## Disclosures" in text
    for needle in (
        "abstain NO_VECTOR:", "abstain UNKNOWN_ERA:", "abstain NONFINITE_P_YES:",  # D2, separate
        "buyer prints floored to 0 (CONTRACTS):", "depth levels raised by ceil (CONTRACTS):",  # D4
        "CLI FINAL as a proxy for venue resolution", "no VOID or UNRESOLVED handling",  # D5
        "no-FINAL station-days excluded:", "inclusive",
        "theta is constant per climate day", "taker_fee_coefficient_as_of",  # D8
        "documented exception", "no-book rungs are not priced",  # D8, M6
        "listing_abstained:", "unknown-delta station-days:",
        "r3 L154",  # D1
    ):  # fmt: skip
        assert needle in text, needle


def test_the_s4_stop_report_discloses_the_consumed_ledger_entry(s4_stop: Run) -> None:
    cfg = s4_stop.cfg
    text = (cfg.out_dir / "report.md").read_text()
    for needle in ("ledger entry is consumed", "no label", "n_sd = 0", "new dated declaration"):
        assert needle in text, needle


def test_tail_only_csv_is_written_atomically(
    world: rw.World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[str] = []
    real = rep.write_text_atomic

    def spy(path: Path, text: str) -> Path:
        written.append(path.name)
        return real(path, text)

    monkeypatch.setattr(rep, "write_text_atomic", spy)
    monkeypatch.setattr(drv, "TAIL_RANGE", (rw.DAY, rw.DAY))
    drv.run(_fresh(world, tmp_path, tail_only=True, parity=(("SFO", 0),)))
    assert "tail_reliability.csv" in written
