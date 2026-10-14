"""MAKER-S2 WP6: the run driver (plan r3 WP6 + r4 delta (b)(c)(d)(e)(g)(i)).

Modes (mutually exclusive): the VERDICT run (default), ``--bench N`` (timing and RSS only; the only
mode that accepts ``--stations/--days``), ``--tail-only`` and ``--verify-first`` (see
``maker_stage0_modes``). A verdict run is gated by the frozen-set amendment, a clean tree and the
one-shot ledger; every refusal happens BEFORE the ledger is claimed, and after the claim ANY
failure renames the run directory ``<run_id>.void`` (no resume; ``episodes.jsonl`` never reopened).

Verdict flow: preflight -> ledger claim -> WP0 probe (S-2) -> S-7 pre-pass -> simulate every
station-day (episodes streamed, one progress line each, RSS watch) -> only then ``report.score``
(truth) -> CSVs, sidecars, pins, S3 inputs and the report. Nothing here writes under the capture.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Final

from breezy.analysis.maker_tape_census import CensusedDay
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    LiveCalibration,
    load_live_calibration,
)
from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis import maker_stage0_report as report
from scripts.analysis.maker_stage0_catalog_read import CatalogSession
from scripts.analysis.maker_stage0_fill_events import assert_delta_within_bound
from scripts.analysis.maker_stage0_frozen import (
    FrozenDateSet,
    assert_in_frozen_set,
    load_amendment,
)
from scripts.analysis.maker_stage0_inputs import (
    InputRefused,
    load_census_days,
    load_trade_unit,
    sha256_file,
)
from scripts.analysis.maker_stage0_ledger import (
    LedgerRefused,
    claim_verdict_run,
    load_addendum,
    void_run_dir,
)
from scripts.analysis.maker_stage0_model import ModelPin, load_model
from scripts.analysis.maker_stage0_nodelog import NodeLogScan, scan_node_log
from scripts.analysis.maker_stage0_pins import (
    CANONICAL_SIDECARS,
    CatalogSliceManifest,
    PinSources,
    assert_clean_tree,
    git_commit,
    pin_inputs,
    seal_sidecars,
    write_pins,
)
from scripts.analysis.maker_stage0_probe import first_print_instant, probe
from scripts.analysis.maker_stage0_run_types import (
    MIN_FREE_BYTES,
    RSS_ABORT_BYTES,
    DiskLow,
    MemoryAbort,
    Pre,
    RunConfig,
    RunDirExists,
    RunSummary,
    SubsetRefused,
)
from scripts.analysis.maker_stage0_runio import (
    EpisodeSink,
    ProgressLog,
    heaviest,
    import_closure,
    read_rss_bytes,
    theta_for_day,
    write_json,
)
from scripts.analysis.maker_stage0_schedule import write_schedule
from scripts.analysis.maker_stage0_station_loop import VARIANTS, LoopOutput
from scripts.analysis.maker_stage0_tables import (
    pos_rows_to_csv,
    read_tail_csv,
    sd_rows_to_csv,
    tables_from_csvs,
    tail_rows_to_csv,
)
from scripts.analysis.maker_stage0_verify_first import VERIFY_FIRST_DAY, verify_first_s6

__all__ = [
    "MIN_FREE_BYTES",
    "RSS_ABORT_BYTES",
    "TAIL_RANGE",
    "DiskLow",
    "InputRefused",
    "MemoryAbort",
    "RunConfig",
    "RunDirExists",
    "RunSummary",
    "SubsetRefused",
    "heaviest",
    "import_closure",
    "load_calibration",
    "run",
    "theta_for_day",
]

TAIL_RANGE: tuple[dt.date, dt.date] = (dt.date(2026, 7, 1), dt.date(2026, 9, 17))
THETA_PIN_SITE: Final[str] = (
    "src/breezy/adapters/polymarket_us/fees.py::taker_fee_coefficient_as_of (post-drift schedule)"
)
VARIANT_FILES: Final[dict[str, str]] = {
    "overlay": "overlay_station_days.csv",
    "plus60": "stress_plus60_station_days.csv",
    "poll_lag": "stress_poll_lag_station_days.csv",
    "delta0": "delta0_station_days.csv",
}
SIDECAR_NAMES: Final[tuple[str, ...]] = tuple(
    sorted({*CANONICAL_SIDECARS, VARIANT_FILES["delta0"]})
)
Key = tuple[str, dt.date]


def current_rss_bytes() -> int:
    return read_rss_bytes()


def load_calibration(model: ModelPin) -> LiveCalibration:
    return load_live_calibration(str(model.artefact_path), expected_sha256=model.artefact_sha256)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --- dispatch and preflight ---------------------------------------------------------------------


def _mode(cfg: RunConfig) -> str:
    flags = (
        ("bench", cfg.bench is not None),
        ("tail-only", cfg.tail_only),
        ("verify-first", cfg.verify_first),
    )
    chosen = [name for name, on in flags if on]
    if len(chosen) > 1:
        raise SubsetRefused(f"modes {chosen} are mutually exclusive")
    mode = chosen[0] if chosen else "verdict"
    if mode != "bench" and (cfg.stations is not None or cfg.days is not None):
        raise SubsetRefused(f"{mode} run refuses --stations/--days (only --bench accepts them)")
    if mode == "tail-only" and not cfg.parity:
        raise InputRefused("--tail-only needs --parity STATION:0|1 for every station")
    return mode


def run(cfg: RunConfig, *, now: Callable[[], dt.datetime] = _utcnow) -> RunSummary:
    mode = _mode(cfg)
    if cfg.out_dir.exists() or cfg.out_dir.with_name(cfg.out_dir.name + ".void").exists():
        raise RunDirExists(f"{cfg.out_dir} already exists: there is no resume")
    if cfg.work_root.exists() and any(cfg.work_root.iterdir()):
        raise RunDirExists(f"scratch root {cfg.work_root} is not empty")
    if mode == "verify-first":
        frozen = load_amendment(cfg.amendment, cfg.amendment_sha)  # the licence for the read
        return modes.run_verify_first(cfg, verify_first_s6, VERIFY_FIRST_DAY, len(frozen.dates))
    pre = _preflight(cfg, strict=mode != "bench")
    if mode == "bench":
        return modes.run_bench(cfg, pre, load_calibration(pre.model), current_rss_bytes)
    if mode == "tail-only":
        return modes.run_tail(cfg, pre, load_calibration(pre.model), TAIL_RANGE)
    return _run_verdict(cfg, pre, now)


def _requested(cfg: RunConfig, fs: FrozenDateSet) -> dict[Key, CensusedDay]:
    stations, days = cfg.stations or fs.stations, cfg.days or fs.dates
    for station in stations:
        for day in days:
            assert_in_frozen_set(fs, station, day)
    census: dict[Key, CensusedDay] = {}
    for row in load_census_days(cfg.census_days).rows:
        wanted = row.station in stations and row.climate_day in days
        if wanted and row.station in fs.stations and row.climate_day in fs.dates:
            assert_in_frozen_set(fs, row.station, row.climate_day)
            census[(row.station, row.climate_day)] = row
    return census


def _scan_logs(directory: Path) -> tuple[list[NodeLogScan], list[Path]]:
    paths = sorted(directory.glob("*.log")) if directory.is_dir() else []
    return [scan_node_log(p) for p in paths], paths


def _preflight(cfg: RunConfig, *, strict: bool) -> Pre:
    fs = load_amendment(cfg.amendment, cfg.amendment_sha)
    census = _requested(cfg, fs)
    free = modes.free_bytes(cfg.out_dir.parent)
    if free < cfg.min_free_bytes:
        raise DiskLow(f"E4: {free} bytes free < {cfg.min_free_bytes}")
    if sha256_file(cfg.truth) != fs.truth_csv_sha256:
        raise InputRefused("truth CSV sha256 differs from the frozen block's pinned sha")
    load_trade_unit(cfg.trade_unit)
    model = load_model(cfg.repo_root)
    if strict:
        assert_clean_tree(cfg.repo_root)
    scans, paths = _scan_logs(cfg.node_log_dir)
    return Pre(fs, census, scans, paths, model, git_commit(cfg.repo_root), free)


# --- verdict ------------------------------------------------------------------------------------


def _run_verdict(cfg: RunConfig, pre: Pre, now: Callable[[], dt.datetime]) -> RunSummary:
    addendum = None
    if cfg.addendum is not None:
        if cfg.addendum_sha is None:
            raise InputRefused("--addendum needs --addendum-sha")
        addendum = load_addendum(cfg.addendum, cfg.addendum_sha)
    refusal = claim_verdict_run(
        cfg.ledger,
        amendment_sha=cfg.amendment_sha,
        run_id=cfg.out_dir.name,
        code_sha=pre.code_sha,
        now=now(),
        runs_root=cfg.out_dir.parent,
        addendum=addendum,
    )
    if refusal is not None:
        raise LedgerRefused(refusal)
    cfg.out_dir.mkdir(parents=True)
    try:
        return _execute(cfg, pre)
    except BaseException:
        shutil.rmtree(cfg.work_root, ignore_errors=True)
        void_run_dir(cfg.out_dir, ledger=cfg.ledger, now=now())
        raise


def _wp0(cfg: RunConfig, pre: Pre) -> dict[Key, int]:
    """WP0: first print, direction (S-2; sidecar written BEFORE the STOP) and the S-7 pre-pass."""
    days = sorted({d for _, d in pre.census})
    stations = sorted({s for s, _ in pre.census})
    first = first_print_instant(
        cfg.catalog_root, days, work_root=cfg.work_root / "first_print", stations=stations
    )
    probed = probe(
        cfg.catalog_root, days, stations, work_root=cfg.work_root / "probe", first_print_ns=first
    )
    write_json(cfg.out_dir / "wp0_agreement.json", probed.to_dict())
    probed.require_clean()
    if probed.first_replayable_day != pre.frozen.first_replayable_day.isoformat():
        raise InputRefused(
            f"first print implies replayable day {probed.first_replayable_day}, the frozen "
            f"block says {pre.frozen.first_replayable_day}"
        )
    assert_delta_within_bound(d.delta_ns for d in probed.delta_instance_days)  # S-7
    return {
        (c.station, dt.date.fromisoformat(c.climate_day)): c.delta_ns or 0 for c in probed.coverage
    }


def _execute(cfg: RunConfig, pre: Pre) -> RunSummary:
    phases = ["preflight"]
    manifest = CatalogSliceManifest()
    session = CatalogSession(cfg.catalog_root, cfg.work_root, manifest)
    out = LoopOutput()
    try:
        deltas = _wp0(cfg, pre)  # S-2 / S-7 abort here, before any episode file exists
        phases += ["probe", "s7"]
        _simulate_all(cfg, pre, session, deltas, out)
        phases.append("simulate")
    finally:
        session.close()
        shutil.rmtree(cfg.work_root, ignore_errors=True)
    return _finish(cfg, pre, out, manifest, phases)


def _simulate_all(
    cfg: RunConfig, pre: Pre, session: CatalogSession, deltas: dict[Key, int], out: LoopOutput
) -> None:
    run_dir = cfg.out_dir
    progress = ProgressLog(run_dir / "progress.jsonl")
    sink = EpisodeSink(run_dir / "episodes.jsonl")
    try:
        ctx, overlay = modes.build_context(
            cfg,
            pre,
            session,
            deltas,
            sink=sink,
            variants=tuple(VARIANTS),
            calibration=load_calibration(pre.model),
        )
        write_schedule(run_dir / "process_schedule.json", ctx.primary)
        write_schedule(run_dir / "process_schedule_overlay.json", overlay, kind="OVERLAY")
        keys = sorted(pre.census, key=lambda k: (k[1], k[0]))
        modes.simulate(ctx, keys, progress, out, current_rss_bytes)
    finally:
        progress.close()
        sink.close()


def _write_tables(cfg: RunConfig, scored: report.Scored, out: LoopOutput) -> None:
    d = cfg.out_dir
    (d / "station_days.csv").write_text(sd_rows_to_csv(scored.sd_rows), encoding="utf-8")
    (d / "scored_episodes.csv").write_text(pos_rows_to_csv(scored.pos_rows), encoding="utf-8")
    tail = read_tail_csv(cfg.tail_csv.read_text(encoding="utf-8")) if cfg.tail_csv else []
    (d / "tail_reliability.csv").write_text(tail_rows_to_csv(tail), encoding="utf-8")
    for name, filename in VARIANT_FILES.items():
        (d / filename).write_text(sd_rows_to_csv(out.rows.get(name, [])), encoding="utf-8")


def _pin_sources(cfg: RunConfig, pre: Pre, consumed: list[tuple[str, str]]) -> PinSources:
    d = cfg.out_dir
    return PinSources(
        repo_root=cfg.repo_root,
        census=cfg.census_days,
        trade_unit=cfg.trade_unit,
        truth_copy=d / "truth_cli_finals.csv",
        truth_cross_check=cfg.truth_cross_check,
        truth_csv_sha256=pre.frozen.truth_csv_sha256,
        nbp_manifest=cfg.nbp_root / "_manifest.json",
        nbp_consumed=consumed,
        process_schedule=d / "process_schedule.json",
        catalog_slice_manifest=d / "catalog_slice_manifest.json",
        amendment_final=cfg.amendment,
        ledger_path=cfg.ledger,
        node_logs=pre.scan_paths,
        sidecar_names=SIDECAR_NAMES,
        argv=cfg.argv,
        theta_pin_site=THETA_PIN_SITE,
        spec=cfg.spec,
    )


def _finish(
    cfg: RunConfig, pre: Pre, out: LoopOutput, manifest: CatalogSliceManifest, phases: list[str]
) -> RunSummary:
    d = cfg.out_dir
    scored = report.score(
        sd_rows=out.rows["primary"],
        seeds=out.seeds,
        census=pre.census.values(),
        frozen=pre.frozen,
        truth_csv=cfg.truth,
        cross_check=cfg.truth_cross_check,
        run_dir=d,
        as_of=cfg.as_of or _utcnow().date(),
    )
    phases.append("score")
    _write_tables(cfg, scored, out)
    manifest.write(d / "catalog_slice_manifest.json")
    consumed = [(str(cycle), sha) for cycle, sha in sorted(out.consumed)]
    pins = seal_sidecars(pin_inputs(_pin_sources(cfg, pre, consumed)), d)
    write_pins(d, pins)
    tables = tables_from_csvs(
        d / "scored_episodes.csv",
        d / "station_days.csv",
        d / "tail_reliability.csv",
        code_sha=pre.code_sha,
    )
    (d / "s3_inputs.json").write_text(tables["s3"], encoding="utf-8")
    variants = {name: out.rows.get(name, []) for name in VARIANT_FILES}
    text = report.render_report(tables, pins, variants, scored.sd_rows, run_id=d.name)
    (d / "report.md").write_text(text, encoding="utf-8")
    phases.append("report")
    modes.write_manifest(cfg, pre, "verdict", phases, out.parity)
    return RunSummary(d, json.loads(tables["s3"])["verdict"], pre.code_sha, "verdict")
