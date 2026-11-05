"""MAKER-S2 WP6: the verdict run's closing phase (score, tables, pins, S3 inputs, report).

Runs only after every station-day is simulated. Every result file is written atomically
(``write_text_atomic``): a crash leaves the previous file or none, never a truncated one.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis import maker_stage0_render as render
from scripts.analysis import maker_stage0_report as report
from scripts.analysis import maker_stage0_verdict as vd
from scripts.analysis.maker_stage0_block_lines import block_lines
from scripts.analysis.maker_stage0_inputs import load_trade_unit, sha256_file, write_text_atomic
from scripts.analysis.maker_stage0_pins import (
    CANONICAL_SIDECARS,
    CatalogSliceManifest,
    PinSources,
    git_commit,
    pin_inputs,
    seal_sidecars,
    write_pins,
)
from scripts.analysis.maker_stage0_run_types import Pre, RunConfig, RunSummary
from scripts.analysis.maker_stage0_runio import write_json
from scripts.analysis.maker_stage0_station_loop import LoopOutput
from scripts.analysis.maker_stage0_tables import (
    pos_rows_to_csv,
    read_tail_csv,
    sd_rows_to_csv,
    tables_from_csvs,
    tail_rows_to_csv,
)

__all__ = [
    "SIDECAR_NAMES",
    "THETA_PIN_SITE",
    "VARIANT_FILES",
    "finish",
    "pin_sources",
    "run_verify_first",
]

VARIANT_FILES: Final[dict[str, str]] = {
    "overlay": "overlay_station_days.csv",
    "plus60": "stress_plus60_station_days.csv",
    "poll_lag": "stress_poll_lag_station_days.csv",
    "delta0": "delta0_station_days.csv",
}
THETA_PIN_SITE: Final[str] = (
    "src/breezy/adapters/polymarket_us/fees.py::taker_fee_coefficient_as_of (post-drift schedule)"
)
SIDECAR_NAMES: Final[tuple[str, ...]] = tuple(
    sorted({*CANONICAL_SIDECARS, VARIANT_FILES["delta0"]})
)


def _write_tables(cfg: RunConfig, scored: report.Scored, out: LoopOutput) -> None:
    d = cfg.out_dir
    write_text_atomic(d / "station_days.csv", sd_rows_to_csv(scored.sd_rows))
    write_text_atomic(d / "scored_episodes.csv", pos_rows_to_csv(scored.pos_rows))
    tail = read_tail_csv(cfg.tail_csv.read_text(encoding="utf-8")) if cfg.tail_csv else []
    write_text_atomic(d / "tail_reliability.csv", tail_rows_to_csv(tail))
    for name, filename in VARIANT_FILES.items():
        write_text_atomic(d / filename, sd_rows_to_csv(out.rows.get(name, [])))


def _file_pin(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}


def _extra_pins(cfg: RunConfig, run_dir: Path) -> dict[str, Any]:
    """Provenance WP1's pin set lacks: the episode log and the tail table's SOURCE file."""
    tail: dict[str, Any] | None = None
    if cfg.tail_csv is not None:
        sibling = cfg.tail_csv.with_name("run_manifest.json")  # holds the tail run's code_sha
        tail = {
            **_file_pin(cfg.tail_csv),
            "run_manifest": _file_pin(sibling) if sibling.is_file() else None,
        }
    return {"episodes_jsonl": _file_pin(run_dir / "episodes.jsonl"), "tail_csv_source": tail}


def _disclosures(out: LoopOutput, scored: report.Scored) -> render.Disclosures:
    return render.Disclosures(
        abstentions=out.abstentions,
        rounding=out.rounding,
        listing_abstained=tuple(sorted(out.listing_abstained)),
        unknown_delta=out.unknown_delta,
        no_final_days=report.no_final_days(scored.sd_rows),
    )


def finish(
    cfg: RunConfig, pre: Pre, out: LoopOutput, manifest: CatalogSliceManifest, phases: list[str]
) -> RunSummary:
    d = cfg.out_dir
    scored = report.score(
        sd_rows=out.rows["primary"],
        seeds=out.seeds,
        census=pre.census.values(),
        frozen=pre.frozen,
        truth_csv=cfg.need("truth"),
        cross_check=cfg.truth_cross_check,
        run_dir=d,
    )
    phases.append("score")
    _write_tables(cfg, scored, out)
    manifest.write(d / "catalog_slice_manifest.json")
    consumed = [(str(cycle), sha) for cycle, sha in sorted(out.consumed)]
    sources = pin_sources(cfg, pre, consumed, SIDECAR_NAMES)
    pins = {**seal_sidecars(pin_inputs(sources), d), **_extra_pins(cfg, d)}
    write_pins(d, pins)
    disclosures = _disclosures(out, scored)
    holdout_line, d5_line = block_lines(pre.frozen)
    hypotheses = [u.name for u in load_trade_unit(cfg.need("trade_unit")).hypotheses()]
    try:
        tables = tables_from_csvs(
            d / "scored_episodes.csv",
            d / "station_days.csv",
            d / "tail_reliability.csv",
            hypotheses=hypotheses,
            code_sha=pre.code_sha,
        )
    except vd.NoBidBearingDays as exc:  # S-4: a reported stop, never a void
        return _stop_s4(cfg, pre, pins, phases, out, str(exc), disclosures, (holdout_line, d5_line))
    write_text_atomic(d / "s3_inputs.json", tables["s3"])
    variants = {name: out.rows.get(name, []) for name in VARIANT_FILES}
    text = render.render_report(
        tables, pins, variants, scored.sd_rows,
        run_id=d.name, hypotheses=hypotheses, disclosures=disclosures,
        holdout_line=holdout_line, d5_line=d5_line,
    )  # fmt: skip
    write_text_atomic(d / "report.md", text)
    phases.append("report")
    modes.write_manifest(cfg, pre, "verdict", phases, out.parity)
    return RunSummary(d, json.loads(tables["s3"])["verdict"], pre.code_sha, "verdict")


def _stop_s4(
    cfg: RunConfig, pre: Pre, pins: dict[str, Any], phases: list[str], out: LoopOutput,
    why: str, disclosures: render.Disclosures, lines: tuple[str, str],
) -> RunSummary:  # fmt: skip
    d = cfg.out_dir
    write_json(d / "s3_inputs.json", render.stop_s3_inputs())
    text = render.render_stop_report(
        pins, run_id=d.name, reason=why, disclosures=disclosures,
        holdout_line=lines[0], d5_line=lines[1],
    )  # fmt: skip
    write_text_atomic(d / "report.md", text)
    phases.append("report")
    modes.write_manifest(cfg, pre, "verdict", phases, out.parity, verdict=render.STOP_S4)
    return RunSummary(d, render.STOP_S4, pre.code_sha, "verdict")


def pin_sources(
    cfg: RunConfig, pre: Pre, consumed: list[tuple[str, str]], sidecar_names: tuple[str, ...]
) -> PinSources:
    d = cfg.out_dir
    return PinSources(
        repo_root=cfg.repo_root,
        census=cfg.need("census_days"),
        trade_unit=cfg.need("trade_unit"),
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
        sidecar_names=sidecar_names,
        argv=cfg.argv,
        theta_pin_site=THETA_PIN_SITE,
        spec=cfg.spec,
    )


def run_verify_first(
    cfg: RunConfig, reader: Callable[[Path, dt.date], Any], day: dt.date, n_frozen_dates: int
) -> RunSummary:
    """WP2 S-6 on ``day`` only; alignment and vintage-age lines, never a fill, bid or p_NO."""
    cfg.out_dir.mkdir(parents=True)
    write_json(cfg.out_dir / "verify_first.json", reader(cfg.nbp_root, day))
    code_sha = git_commit(cfg.repo_root)
    write_json(
        cfg.out_dir / "run_manifest.json",
        {
            "mode": "verify-first",
            "run_id": cfg.out_dir.name,
            "argv": list(cfg.argv),
            "git_commit": code_sha,
            "day": day,
            "amendment_sha": cfg.amendment_sha,
            "frozen_dates": n_frozen_dates,
        },
    )
    return RunSummary(cfg.out_dir, None, code_sha, "verify-first")
