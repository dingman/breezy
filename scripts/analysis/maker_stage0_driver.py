"""MAKER-S2 WP6: the run driver (plan r3 WP6 + r4 delta (b)(c)(d)(e)(g)(i)).

Modes (mutually exclusive): the VERDICT run (default), ``--bench N`` (timing and RSS only; the only
mode that accepts ``--stations/--days``), ``--tail-only`` and ``--verify-first`` (see
``maker_stage0_modes`` and ``maker_stage0_report``). A verdict run is gated by the frozen-set
amendment, a clean tree and the one-shot ledger; every refusal (``maker_stage0_preflight``) happens
BEFORE the ledger is claimed, and after the claim ANY failure renames the run directory
``<run_id>.void`` (no resume; ``episodes.jsonl`` never reopened) and surfaces as ``RunVoided``.
The ledger and the repo root are not caller choices: the CLI derives both.

DEVIATIONS (each is a reported departure from, or a pinned reading of, plan r3/r4; WP6 review aid):
  D1 r3 L154: decision instants come from depth frames, forecast releases and schedule cuts
     (``clock_events``), not from a fixed wall-clock grid.
  D2 r4 (g): p_NO abstains NO_VECTOR / UNKNOWN_ERA / NONFINITE_P_YES map to the rule's
     ``NOT_YET_AVAILABLE`` reason (the rung is not wanted); the adapter owns the table and counts
     each reason separately (the report discloses all three).
  D3 r4 (e): a later recorder instance's START (its first in-window event of any kind: frame,
     print, gap or truncation row) ends the earlier instance.
  D4 r3 WP4 sizing: per hypothesis, depth sizes round UP and print sizes DOWN to whole contracts;
     the prints floored to zero and the levels raised by the ceil are counted and disclosed.
  D5 r4 (r)3 / spec 6.5: ``truth_final`` is "" for a day with no FINAL row at ANY age; UNRESOLVED
     and VOID are never scored (the pinned truth CSV has no resolution state; one function,
     ``report.day_truth``, feeds both truth fields).
  D6 r4 (r)1: ``n_no_book_wants`` = wanted RUNGS with no book all day (``replay_station_day``); a
     rung with no book is never priced, ranked or K1 (adapter).
  D7 r4 (a) S-4 + coordinator ruling: n_sd = 0 is a REPORTED stop ``STOP-S4-NO-BID-BEARING-DAYS``
     (exit 0, ledger entry kept), not a void; ``s3_inputs.json`` holds the verdict, rest null.
  D8 r4 (r)6: a day whose venue theta falls outside [0, 0.2] is refused before the ledger claim.
  D9 spec 3: a ladder listed after D-1 12:00Z is a listing abstention: replayed (covered), never
     bid, counted as ``listing_abstained``.

Verdict flow: preflight -> ledger claim -> WP0 probe (S-2) -> S-7 pre-pass -> simulate every
station-day (episodes streamed, one progress line each, RSS watch) -> only then ``report.score``
(truth) -> CSVs, sidecars, pins, S3 inputs and the report. Nothing here writes under the capture.
"""

from __future__ import annotations

import datetime as dt
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace

from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    LiveCalibration,
    load_live_calibration,
)
from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis import maker_stage0_report as report
from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_catalog_read import CatalogSession
from scripts.analysis.maker_stage0_fill_events import assert_delta_within_bound
from scripts.analysis.maker_stage0_finish import finish, run_verify_first
from scripts.analysis.maker_stage0_first_replayable import check_first_replayable
from scripts.analysis.maker_stage0_frozen import load_amendment
from scripts.analysis.maker_stage0_inputs import InputRefused
from scripts.analysis.maker_stage0_ledger import (
    LedgerRefused,
    claim_verdict_run,
    load_addendum,
    void_run_dir,
)
from scripts.analysis.maker_stage0_model import ModelPin
from scripts.analysis.maker_stage0_pins import CatalogSliceManifest
from scripts.analysis.maker_stage0_preflight import mode_of
from scripts.analysis.maker_stage0_preflight import preflight as _preflight
from scripts.analysis.maker_stage0_probe import first_print_instant, probe
from scripts.analysis.maker_stage0_probe_core import StationDayCoverage
from scripts.analysis.maker_stage0_run_types import (
    MIN_FREE_BYTES,
    RSS_ABORT_BYTES,
    DiskLow,
    MemoryAbort,
    Pre,
    RunConfig,
    RunDirExists,
    RunSummary,
    RunVoided,
    SubsetRefused,
)
from scripts.analysis.maker_stage0_runio import (
    EpisodeSink,
    ProgressLog,
    heaviest,
    import_closure,
    peak_rss_bytes,
    read_rss_bytes,
    theta_for_day,
    write_json,
)
from scripts.analysis.maker_stage0_schedule import write_schedule
from scripts.analysis.maker_stage0_station_loop import VARIANTS, LoopOutput
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
    "RunVoided",
    "SubsetRefused",
    "heaviest",
    "import_closure",
    "load_calibration",
    "run",
    "theta_for_day",
]

TAIL_RANGE: tuple[dt.date, dt.date] = (dt.date(2026, 7, 1), dt.date(2026, 9, 17))
Key = tuple[str, dt.date]


@dataclass(frozen=True)
class Wp0:
    """What the WP0 pass hands the loop: Delta per station-day and the listing abstentions."""

    deltas: dict[Key, int]
    abstained: frozenset[Key]
    unknown_delta: int
    first_replayable_observed: str | None = None


def current_rss_bytes() -> int:
    return read_rss_bytes()


def load_calibration(model: ModelPin) -> LiveCalibration:
    return load_live_calibration(str(model.artefact_path), expected_sha256=model.artefact_sha256)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --- dispatch -----------------------------------------------------------------------------------


def run(cfg: RunConfig, *, now: Callable[[], dt.datetime] = _utcnow) -> RunSummary:
    mode = mode_of(cfg)
    if cfg.out_dir.exists() or cfg.out_dir.with_name(cfg.out_dir.name + ".void").exists():
        raise RunDirExists(f"{cfg.out_dir} already exists: there is no resume")
    if cfg.work_root.exists() and any(cfg.work_root.iterdir()):
        raise RunDirExists(f"scratch root {cfg.work_root} is not empty")
    if mode == "verdict":
        return _run_verdict(cfg, _preflight(cfg, mode), now)
    try:
        return _report_only(cfg, mode)
    except BaseException:  # a report-only mode leaves nothing behind on failure
        shutil.rmtree(cfg.out_dir, ignore_errors=True)
        shutil.rmtree(cfg.work_root, ignore_errors=True)
        raise


def _report_only(cfg: RunConfig, mode: str) -> RunSummary:
    if mode == "verify-first":
        frozen = load_amendment(cfg.amendment, cfg.amendment_sha)  # the licence for the read
        return run_verify_first(cfg, verify_first_s6, VERIFY_FIRST_DAY, len(frozen.dates))
    pre = _preflight(cfg, mode)
    if mode == "tail-only" and pre.frozen.block == 2:
        raise InputRefused("--tail-only is not licensed for a v2 block (Doc B section 1)")
    if mode == "bench":
        calibration = load_calibration(pre.model)
        return modes.run_bench(cfg, pre, calibration, current_rss_bytes, peak_rss_bytes)
    return report.run_tail(cfg, pre, load_calibration(pre.model), TAIL_RANGE)


# --- verdict ------------------------------------------------------------------------------------


def _claim_block_day(cfg: RunConfig, pre: Pre) -> str | None:
    """The claim's block day: derived from the frozen block, never trusted from ``cfg``."""
    derived = pre.frozen.first_replayable_day.isoformat() if pre.frozen.block == 2 else None
    if cfg.block_first_day is not None and cfg.block_first_day != derived:
        raise InputRefused(
            f"block_first_day {cfg.block_first_day!r} disagrees with the frozen block ({derived!r})"
        )
    return derived


def _run_verdict(cfg: RunConfig, pre: Pre, now: Callable[[], dt.datetime]) -> RunSummary:
    addendum = None
    if cfg.addendum is not None:
        if cfg.addendum_sha is None:
            raise InputRefused("--addendum needs --addendum-sha")
        addendum = load_addendum(cfg.addendum, cfg.addendum_sha)
    block_day = _claim_block_day(cfg, pre)
    refusal = claim_verdict_run(
        cfg.ledger,
        amendment_sha=cfg.amendment_sha,
        run_id=cfg.out_dir.name,
        code_sha=pre.code_sha,
        now=now(),
        runs_root=cfg.out_dir.parent,
        addendum=addendum,
        block_first_day=block_day,
    )
    if refusal is not None:
        raise LedgerRefused(refusal)
    cfg.out_dir.mkdir(parents=True)
    try:
        return _execute(cfg, pre)
    except BaseException as exc:
        shutil.rmtree(cfg.work_root, ignore_errors=True)
        void_failure = _void(cfg, now)
        if not isinstance(exc, Exception):
            raise  # an interrupt is not wrapped
        raise RunVoided(exc, void_failure=void_failure) from exc


def _void(cfg: RunConfig, now: Callable[[], dt.datetime]) -> Exception | None:
    """Rename the run directory; a failure here is returned, never allowed to mask the cause."""
    try:
        void_run_dir(cfg.out_dir, ledger=cfg.ledger, now=now())
    except Exception as exc:  # noqa: BLE001 - reported inside RunVoided, never raised over the cause
        return exc
    return None


def _listing_abstains(coverage: StationDayCoverage, day: dt.date) -> bool:
    """Spec 3: not listed by D-1 12:00Z (the probe's flag, cross-checked with WP3's rule)."""
    return coverage.listing_abstain or not rule.listed_in_time(coverage.listing_ns, day)


def _wp0(cfg: RunConfig, pre: Pre) -> Wp0:
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
    refusal = check_first_replayable(probed, pre.frozen)
    if refusal is not None:
        raise InputRefused(refusal)
    assert_delta_within_bound(d.delta_ns for d in probed.delta_instance_days)  # S-7
    keyed = [(c, (c.station, dt.date.fromisoformat(c.climate_day))) for c in probed.coverage]
    return Wp0(
        deltas={key: c.delta_ns or 0 for c, key in keyed},
        abstained=frozenset(key for c, key in keyed if _listing_abstains(c, key[1])),
        unknown_delta=sum(c.delta_ns is None for c, _ in keyed),
        first_replayable_observed=probed.first_replayable_day,
    )


def _execute(cfg: RunConfig, pre: Pre) -> RunSummary:
    phases = ["preflight"]
    manifest = CatalogSliceManifest()
    session = CatalogSession(cfg.catalog_root, cfg.work_root, manifest)
    out = LoopOutput()
    try:
        wp0 = _wp0(cfg, pre)  # S-2 / S-7 abort here, before any episode file exists
        out.unknown_delta = wp0.unknown_delta
        observed = wp0.first_replayable_observed
        phases += ["probe", "s7"]
        _simulate_all(cfg, pre, session, wp0, out)
        phases.append("simulate")
    finally:
        session.close()
        shutil.rmtree(cfg.work_root, ignore_errors=True)
    summary = finish(cfg, pre, out, manifest, phases)
    return replace(summary, first_replayable_observed=observed)


def _simulate_all(
    cfg: RunConfig, pre: Pre, session: CatalogSession, wp0: Wp0, out: LoopOutput
) -> None:
    run_dir = cfg.out_dir
    progress = ProgressLog(run_dir / "progress.jsonl")
    sink = EpisodeSink(run_dir / "episodes.jsonl")
    try:
        ctx, overlay = modes.build_context(
            cfg,
            pre,
            session,
            wp0.deltas,
            sink=sink,
            variants=tuple(VARIANTS),
            calibration=load_calibration(pre.model),
            peak_fn=peak_rss_bytes,
            abstained=wp0.abstained,
        )
        write_schedule(run_dir / "process_schedule.json", ctx.primary)
        write_schedule(run_dir / "process_schedule_overlay.json", overlay, kind="OVERLAY")
        keys = sorted(pre.census, key=lambda k: (k[1], k[0]))
        modes.simulate(
            ctx,
            keys,
            progress,
            out,
            current_rss_bytes,
            peak_rss_bytes,
            runner=modes.day_runner(cfg),
        )
    finally:
        progress.close()
        sink.close()
