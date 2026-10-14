"""MAKER-S2 WP6: scoring (the ONLY place truth is loaded), the tail table and the Markdown report.

Plan r3 WP6 flow steps (2)-(3), r4 delta (f)(g)(i)6. Nothing here runs before every station-day is
simulated: the driver calls ``score`` once, after its simulation loop. The simulator's import
closure (``maker_stage0_events_build``) cannot reach this module. ``render_report`` consumes the
three reproducible CSVs through ``tables_from_csvs`` so the report is byte-reproducible from them.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis import maker_stage0_verdict as vd
from scripts.analysis.maker_stage0_frozen import FrozenDateSet, verify_set_matches_rule
from scripts.analysis.maker_stage0_inputs import TruthTable, load_truth
from scripts.analysis.maker_stage0_pno import AbstainReason, classify_p_no, release_instants
from scripts.analysis.maker_stage0_pno_store import PNoStore
from scripts.analysis.maker_stage0_runio import PositionSeed
from scripts.analysis.maker_stage0_stats import TAIL_EDGES, TailRow
from scripts.analysis.maker_stage0_tables import BANNER, RUNTIME_ONLY_LABEL

__all__ = [
    "BANNER",
    "HOLDOUT_LINE",
    "UNRESOLVED_AFTER_DAYS",
    "Scored",
    "load_tail_truth",
    "load_truth",
    "render_report",
    "score",
    "tail_rows_for",
    "truth_token",
    "variant_section",
]

UNRESOLVED_AFTER_DAYS: Final[int] = 14
OUTCOME_UNRESOLVED: Final[str] = "UNRESOLVED"
OUTCOME_YES: Final[str] = "YES"
TAIL_P_YES_MAX: Final[float] = TAIL_EDGES[-1]
HOLDOUT_LINE: Final[str] = (
    "Holdout touch: replay days 2026-09-18..2026-09-30 and tail days 2026-07-01..2026-09-17 lie "
    "inside the frozen NBP holdout [2026-07-01, 2026-10-02); they are read under clause 3 of the "
    "holdout ruling as descriptive evidence only. 2026-10-01 is sealed and never read; "
    "2026-10-02..2026-10-13 statistics are disclosed contamination for AUT-4 forward windows. "
    "This run fits nothing and never calls open_holdout."
)
_VARIANT_FILES: Final[tuple[tuple[str, str, str], ...]] = (
    ("overlay", "overlay_station_days.csv", "Overlay schedule (report-only)"),
    ("plus60", "stress_plus60_station_days.csv", "+60 min availability stress (report-only)"),
    ("poll_lag", "stress_poll_lag_station_days.csv", "Poll-lag stress (report-only)"),
    ("delta0", "delta0_station_days.csv", "Delta = 0 re-run (report-only)"),
)


@dataclass(frozen=True, slots=True)
class Scored:
    sd_rows: list[vd.SdRow]
    pos_rows: list[vd.PosRow]
    truth: TruthTable


def truth_token(rung_id: str, tmax_f: int | None, *, day: dt.date, as_of: dt.date) -> str:
    """ "" (no FINAL yet), YES / NO from the rung's inclusive band, or UNRESOLVED past D+14."""
    if tmax_f is None:
        late = (as_of - day).days > UNRESOLVED_AFTER_DAYS
        return OUTCOME_UNRESOLVED if late else vd.NO_FINAL
    facts = bucket_facts_from_instrument_id(rung_id)
    if facts is None:
        raise ValueError(f"{rung_id} has no rung facts; cannot settle it")
    return OUTCOME_YES if facts.contains(tmax_f) else vd.OUTCOME_NO


def _truth_row(row: vd.SdRow, truth: TruthTable, as_of: dt.date) -> vd.SdRow:
    day = dt.date.fromisoformat(row.climate_day)
    tmax = truth.finals.get((row.station, day))
    late = tmax is None and (as_of - day).days > UNRESOLVED_AFTER_DAYS
    return replace(
        row, truth_final=tmax is not None, truth_tmax_f=tmax, void=False, unresolved_d14=late
    )


def _pos_row(seed: PositionSeed, truth: TruthTable, as_of: dt.date) -> vd.PosRow:
    day = dt.date.fromisoformat(seed.climate_day)
    token = truth_token(seed.rung_id, truth.finals.get((seed.station, day)), day=day, as_of=as_of)
    return vd.PosRow(
        position_id=f"{seed.station}|{seed.climate_day}|{seed.unit_hypothesis}|{seed.rung_id}",
        rung_trial_id=seed.rung_id,
        station=seed.station,
        climate_day=seed.climate_day,
        unit_hypothesis=seed.unit_hypothesis,
        bid=seed.bid,
        filled_base=seed.filled_base,
        filled_stress=seed.filled_stress,
        p_yes_point_live=seed.p_yes_point_live,
        truth_final=token,
    )


def score(
    *,
    sd_rows: Sequence[vd.SdRow],
    seeds: Iterable[PositionSeed],
    census: Iterable[CensusedDay],
    frozen: FrozenDateSet,
    truth_csv: Path,
    cross_check: Path,
    run_dir: Path,
    as_of: dt.date,
) -> Scored:
    """Load FINAL truth for the replayed station-days; called once, post-simulation."""
    keys = {(r.station, dt.date.fromisoformat(r.climate_day)) for r in sd_rows}
    truth = load_truth(
        truth_csv, cross_check, run_dir, keys=keys, expected_csv_sha256=frozen.truth_csv_sha256
    )
    verify_set_matches_rule(frozen, census, truth)
    return Scored(
        [_truth_row(r, truth, as_of) for r in sd_rows],
        [_pos_row(s, truth, as_of) for s in seeds],
        truth,
    )


def load_tail_truth(
    truth_csv: Path,
    cross_check: Path,
    scratch: Path,
    expected_sha: str,
    keys: set[tuple[str, dt.date]],
) -> TruthTable:
    """FINAL truth for the tail days (report-only); the copy goes to ``scratch``."""
    return load_truth(truth_csv, cross_check, scratch, keys=keys, expected_csv_sha256=expected_sha)


def tail_rows_for(
    store: PNoStore,
    station: str,
    day: dt.date,
    tmax_f: int | None,
    bands: Mapping[str, tuple[int, int]],
) -> list[TailRow]:
    """Every inclusive 2 F band with p_YES < 0.06 for each day-D vector (report-only)."""
    if tmax_f is None:
        return []
    rows: list[TailRow] = []
    for release in release_instants(store, station, day, stress="none"):
        served = classify_p_no(store, station, day, release + 1, stress="none")
        if isinstance(served, AbstainReason):
            continue
        cycle = dt.datetime.fromtimestamp(served.vector.cycle_runtime_ns // 10**9, tz=dt.UTC)
        label = f"{cycle.hour:02d}Z"
        for rung_id, p_yes in sorted(served.p_yes_point_live.items()):
            lo, hi = bands[rung_id]
            if p_yes < TAIL_P_YES_MAX:
                rows.append(
                    TailRow(station, day.isoformat(), label, p_yes, int(lo <= tmax_f <= hi))
                )
    return rows


# --- Markdown -----------------------------------------------------------------------------------


def _station_day_rate(rows: Sequence[vd.SdRow], pick: str) -> float | None:
    den = [r for r in rows if vd.in_denominator(r)]
    if not den:
        return None
    return sum(vd.nz(getattr(r, pick)) >= 1 for r in den) / len(den)


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def _label(rows: Sequence[vd.SdRow]) -> str:
    try:
        return vd.decide(vd.analyse_all(rows, [])).label
    except vd.NoBidBearingDays:
        return "n/a (no bid-bearing days)"


def variant_section(
    title: str, name: str, sidecar: str, rows: Sequence[vd.SdRow], primary: Sequence[vd.SdRow]
) -> str:
    """Rates beside the primary for one report-only variant, labelled run-time only."""
    base = {(r.station, r.climate_day, r.unit_hypothesis): r for r in primary}
    out = [f"### {title}", f"{RUNTIME_ONLY_LABEL}: {sidecar} (never sets the label)", ""]
    head = "| hypothesis | n_sd | base day rate | stressed day rate | days changed vs primary |"
    out += [head, "|---|---|---|---|---|"]
    for hyp in sorted({r.unit_hypothesis for r in rows}):
        mine = [r for r in rows if r.unit_hypothesis == hyp]
        changed = sum(
            (r.filled_pairs_base, r.filled_pairs_stress)
            != (b.filled_pairs_base, b.filled_pairs_stress)
            for r in mine
            if (b := base.get((r.station, r.climate_day, r.unit_hypothesis))) is not None
        )
        n_sd = sum(vd.in_denominator(r) for r in mine)
        out.append(
            f"| {hyp} | {n_sd} | {_fmt(_station_day_rate(mine, 'filled_pairs_base'))} | "
            f"{_fmt(_station_day_rate(mine, 'filled_pairs_stress'))} | {changed} |"
        )
    primary_label = _label(primary)
    out.append(f"\nrate-rows V-row outcome: {_label(rows)} (primary: {primary_label}); {name}\n")
    return "\n".join(out)


def _pins_block(pins: Mapping[str, Any]) -> str:
    def sha(key: str) -> str:
        item = pins.get(key)
        return str(item["sha256"]) if isinstance(item, Mapping) else str(item)

    rows = [
        ("code_sha (git_commit)", str(pins["git_commit"])),
        ("amendment FINAL sha256", str(pins["amendment_final_sha256"])),
        ("truth CSV sha256 (frozen block)", str(pins["truth_csv_sha256_frozen_block"])),
        ("census", sha("census")), ("trade unit", sha("trade_unit")),
        ("artefact", sha("artefact")), ("deploy manifest", sha("deploy_manifest")),
        ("evidence doc", sha("evidence_doc")), ("spec", sha("spec")), ("uv.lock", sha("uv_lock")),
        ("NBP manifest", sha("nbp_manifest")),
        ("NBP consumed cycles", str(pins["nbp_consumed"]["sha256"])),
        ("process schedule", sha("process_schedule")),
        ("catalog slice manifest", sha("catalog_slice_manifest")),
        ("package set", str(pins["installed_package_set_sha256"])),
        ("verdict ledger", str(pins["ledger_path"])),
        ("theta pin site", str(pins["theta_pin_site"])),
    ]  # fmt: skip
    table = "\n".join(f"| {k} | `{v}` |" for k, v in rows)
    sidecars = "\n".join(
        f"| {name} | {RUNTIME_ONLY_LABEL} | `{pin['sha256']}` |"
        for name, pin in sorted(pins["sidecars"].items())
    )
    return (
        f"## Pins\n\n| input | sha256 / value |\n|---|---|\n{table}\n\n"
        f"| sidecar | label | sha256 |\n|---|---|---|\n{sidecars}\n"
    )


def render_report(
    blocks: Mapping[str, str],
    pins: Mapping[str, Any],
    variants: Mapping[str, Sequence[vd.SdRow]],
    primary: Sequence[vd.SdRow],
    *,
    run_id: str,
) -> str:
    """The evidence Markdown: verdict, tables (verbatim reproducible blocks), pins, holdout line."""
    parts = [
        f"# MAKER-S2 Stage 0 replay: {run_id}\n",
        f"{BANNER}\n",
        "## Verdict\n",
        blocks["verdict"],
    ]
    for key, title in (
        ("v0", "V0 and fitted ICC"), ("rates", "Fill rates"), ("hours", "Bid-live hours"),
        ("s69", "Section 6.9"), ("expectancy", "Net expectancy"), ("bids", "Realised bids"),
        ("tail", "Tail reliability"), ("delta", "Clock offset (Delta)"),
        ("coverage", "Coverage sensitivity"), ("non_covered", "Non-COVERED days"),
    ):  # fmt: skip
        parts += [f"## {title}\n", blocks[key]]
    parts += ["## S3 inputs\n", "```json\n" + blocks["s3"] + "```\n"]
    parts.append("## Report-only variants\n")
    parts += [
        variant_section(title, name, sidecar, variants.get(name, ()), primary)
        for name, sidecar, title in _VARIANT_FILES
        if name in variants
    ]
    parts += [
        "## Stress variants (report-only)\n",
        "See the +60 min, poll-lag and Delta = 0 blocks above.\n",
    ]
    parts += ["## Run-time only blocks\n"]
    parts += [
        blocks[k]
        for k in (
            "overlay",
            "wp0_agreement",
            "stress_plus60",
            "stress_poll_lag",
            "progress",
            "bench",
        )
    ]
    parts += [_pins_block(pins), "## Holdout\n", HOLDOUT_LINE + "\n"]
    return "\n".join(parts)
