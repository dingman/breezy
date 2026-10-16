"""MAKER-S2 WP6: the Markdown report and the S-4 stop report (pure text; no truth, no I/O).

Plan r3 WP6 flow step (3), r4 delta (f)(g)(i)6. ``render_report`` consumes the three reproducible
CSVs through ``tables_from_csvs`` so the report is byte-reproducible from them. The disclosure
obligations of the WP6 review (pmr D1-D8, M6) are rendered here from counts the loop collected.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from scripts.analysis import maker_stage0_verdict as vd
from scripts.analysis.maker_stage0_tables import BANNER, RUNTIME_ONLY_LABEL

__all__ = [
    "BANNER",
    "HOLDOUT_LINE",
    "S3_KEYS",
    "STOP_S4",
    "Disclosures",
    "disclosures_block",
    "render_report",
    "render_stop_report",
    "stop_s3_inputs",
    "variant_section",
]

STOP_S4: Final[str] = "STOP-S4-NO-BID-BEARING-DAYS"  # r4 (a) S-4: a REPORTED stop, not a void
#: the ``s3_inputs.json`` keys (``build_s3_inputs``); a stop writes the verdict, null elsewhere
S3_KEYS: Final[tuple[str, ...]] = (
    "b", "base_k1", "base_station_day_rate", "base_station_day_rate_ci_cluster_boot",
    "bid_bearing_share_of_covered_listed", "code_sha", "fill_icc_rung_trial",
    "fill_icc_rung_trial_k1", "fill_icc_station_day", "max_rungs_hypothesis", "n0_climate_dates",
    "n_eff_gov", "n_stressed_fills", "r_lo", "r_lo_by_hypothesis", "r_lo_k1",
    "r_lo_k1_lcb_cluster_boot", "r_lo_lcb_by_hypothesis", "r_lo_lcb_cluster_boot", "r_lo_position",
    "r_lo_se_cluster_boot", "r_lo_station_day", "realised_bid_iqr", "realised_bid_median_base",
    "two_fill_share", "unit_hypothesis", "verdict",
)  # fmt: skip
HOLDOUT_LINE: Final[str] = (
    "Holdout touch: replay days 2026-09-18..2026-09-30 and tail days 2026-07-01..2026-09-17 lie "
    "inside the frozen NBP holdout [2026-07-01, 2026-10-02); they are read under clause 3 of the "
    "holdout ruling as descriptive evidence only. 2026-10-01 is sealed and never read; "
    "2026-10-02..2026-10-13 statistics are disclosed contamination for AUT-4 forward windows. "
    "This run fits nothing and never calls open_holdout."
)
ABSTAIN_REASONS: Final[tuple[str, ...]] = ("NO_VECTOR", "UNKNOWN_ERA", "NONFINITE_P_YES")
_VARIANT_FILES: Final[tuple[tuple[str, str, str], ...]] = (
    ("overlay", "overlay_station_days.csv", "Overlay schedule (report-only)"),
    ("plus60", "stress_plus60_station_days.csv", "+60 min availability stress (report-only)"),
    ("poll_lag", "stress_poll_lag_station_days.csv", "Poll-lag stress (report-only)"),
    ("delta0", "delta0_station_days.csv", "Delta = 0 re-run (report-only)"),
)


@dataclass(frozen=True)
class Disclosures:
    """Counts the report must state (pmr D1-D8, M6); all collected by the loop, none by scoring."""

    abstentions: Mapping[str, int] = field(default_factory=dict)  # primary decisions, by reason
    rounding: Mapping[str, Mapping[str, int]] = field(default_factory=dict)  # by hypothesis
    listing_abstained: Sequence[str] = ()
    unknown_delta: int = 0
    no_final_days: int = 0


_D1 = (
    "- D1 decision instants are depth frames, forecast releases and schedule cuts (r3 L154), not a "
    "wall-clock grid; a print never changes the displayed book, only the next frame does."
)
_D2 = (
    "- D2 forecast abstentions at primary decision instants, by reason, each counted separately "
    "(`episodes.jsonl` merges them):"
)
_D3 = (
    "- D3 a later recorder instance takes over at its start, its first in-window event of any "
    "kind (frame, print, gap or truncation row)."
)
_D4 = (
    "- D4 depth sizes round UP and print sizes DOWN to whole contracts (conservative: fewer fills, "
    "i.e. toward NO-GO, so anti-strategy rather than neutral):"
)
_D5 = (
    "- D5 the truth is the CLI FINAL as a proxy for venue resolution; there is no VOID or "
    "UNRESOLVED handling (days 2026-09-18..2026-09-30 are already past D+14 at run time); band "
    "edges are inclusive (`bucket_facts_from_instrument_id`)."
)
_D6 = (
    "- D6/M6 no-book rungs are not priced, ranked or K1 and get no attempt; they are counted in "
    "`n_no_book_wants` only."
)
_LISTING_NOTE = "(listed after D-1 12:00Z: covered, never bid-bearing)"
_D8 = (
    "- D8 theta is constant per climate day (read at D 00:00Z via `taker_fee_coefficient_as_of`); "
    "`fees.py` names that function for eligibility, so its use here is a documented exception; no "
    "intra-day drift is detectable."
)


def disclosures_block(d: Disclosures, d5_line: str = _D5) -> str:
    """The ``## Disclosures`` section: every WP6 ruling that the verdict is read against."""
    counts = {**dict.fromkeys(ABSTAIN_REASONS, 0), **d.abstentions}
    lines = [_D1, _D2, *(f"  - abstain {reason}: {n}" for reason, n in sorted(counts.items()))]
    lines += [_D3, _D4]
    for unit, c in sorted(d.rounding.items()):
        lines += [
            f"  - buyer prints floored to 0 ({unit}): {c['prints_floored_zero']} of {c['prints']}",
            f"  - depth levels raised by ceil ({unit}): {c['levels_ceil_raised']} of {c['levels']}",
        ]
    listed = f" ({', '.join(d.listing_abstained)})" if d.listing_abstained else ""
    lines += [
        d5_line,
        f"  - no-FINAL station-days excluded: {d.no_final_days}",
        _D6,
        _D8,
        f"- listing_abstained: {len(d.listing_abstained)}{listed} {_LISTING_NOTE}",
        f"- unknown-delta station-days: {d.unknown_delta} (Delta taken as 0)",
    ]
    return "## Disclosures\n\n" + "\n".join(lines) + "\n"


def _station_day_rate(rows: Sequence[vd.SdRow], pick: str) -> float | None:
    den = [r for r in rows if vd.in_denominator(r)]
    if not den:
        return None
    return sum(vd.nz(getattr(r, pick)) >= 1 for r in den) / len(den)


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def _label(rows: Sequence[vd.SdRow], hypotheses: Sequence[str]) -> str:
    try:
        return vd.decide(vd.analyse_all(rows, [], hypotheses), hypotheses).label
    except vd.NoBidBearingDays:
        return "n/a (no bid-bearing days)"


def variant_section(
    title: str,
    name: str,
    sidecar: str,
    rows: Sequence[vd.SdRow],
    primary: Sequence[vd.SdRow],
    hypotheses: Sequence[str],
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
    primary_label = _label(primary, hypotheses)
    out.append(
        f"\nrate-rows V-row outcome: {_label(rows, hypotheses)} "
        f"(primary: {primary_label}); {name}\n"
    )
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
        ("episodes.jsonl", sha("episodes_jsonl")),
        ("tail csv source", sha("tail_csv_source") if pins.get("tail_csv_source") else "none"),
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
    hypotheses: Sequence[str],
    disclosures: Disclosures,
    holdout_line: str = HOLDOUT_LINE,
    d5_line: str = _D5,
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
        variant_section(title, name, sidecar, variants.get(name, ()), primary, hypotheses)
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
    parts += [disclosures_block(disclosures, d5_line), _pins_block(pins)]
    parts += ["## Holdout\n", holdout_line + "\n"]
    return "\n".join(parts)


def stop_s3_inputs() -> dict[str, object]:
    """S-4: the verdict alone; every other key is null so S3 cannot read a number into a stop."""
    return {k: STOP_S4 if k == "verdict" else None for k in S3_KEYS}


def render_stop_report(
    pins: Mapping[str, Any],
    *,
    run_id: str,
    reason: str,
    disclosures: Disclosures,
    holdout_line: str = HOLDOUT_LINE,
    d5_line: str = _D5,
) -> str:
    """The S-4 report: the verdict, why, the pins and the holdout line (no tables to render)."""
    return "\n".join(
        [
            f"# MAKER-S2 Stage 0 replay: {run_id}\n",
            f"{BANNER}\n",
            "## Verdict\n",
            f"Verdict: {STOP_S4}\n",
            f"{reason}\n",
            (
                "This is a REPORTED stop (r4 (a) S-4), not a void. The ledger entry is consumed, "
                "there is no label, n_sd = 0 and every other S3 key is null; a re-run needs a new "
                "dated declaration (a STOP run holds `scored_episodes.csv`, so an addendum "
                "re-run is refused).\n"
            ),
            disclosures_block(disclosures, d5_line),
            _pins_block(pins),
            "## Holdout\n",
            holdout_line + "\n",
        ]
    )
