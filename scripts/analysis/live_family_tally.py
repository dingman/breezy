"""6d -- nightly live-family tally over 6c's scored trials.

Spec: `docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md`, section 6d, as
amended by the "Converged peer review (2026-09-04)" section (BINDING over
the draft body). Reads the 6c scored-trial parquet store
(`breezy.persistence.scored_trial_store`), builds realized-hold-rate strata
(pooled / per-station / per-ask-band) over LIVE trials only, renders a
Markdown report whose stratum table is byte-comparable to the M_B live
section (`mb_current_rung_edge_study.py`), and appends the 6e BCa bootstrap
line via `breezy.settlement.roi_bound`.

Never-pool provenance (review item 3, corrected citation): the rule that
archive trials are never pooled into this tally is analogous to L-13
(cadence mismatch) and L-21 (archive vs realized) -- no lesson states this
rule verbatim; it is a plan decision of this brief, enforced here by
refusing any row whose `trial_id` is not a
`current_rung_hold/trial/{station}/{climate_day}` key (the live latch's own
key format, review item 8), since the 6c store carries no separate
provenance column.

Verdict (review item 5, verbatim): "6d SURVIVE = `RealizedStratum.survives`
(n>=150 AND Wilson lower > BE) plus a new SigmaPnL > 0 guard; KILL is
unchanged." KILL fires when the pooled stratum is `cell_dead` or any
n>=60 stratum (station or ask-band) is `cell_dead`, exactly
`RealizedStratum.cell_dead`'s own rule -- restated nowhere else.

This module never prints the naive normal-approximation interval EXEC_SPINE
R-9 refuses by name ("anticonservative exactly where the decision is
made") -- only `roi_bound.format_roi_bound`'s four pinned strings.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_correction_probe import wilson_interval
from mb_current_rung_edge_study import (
    ASK_BANDS,
    CurrentRungTrial,
    RealizedStratum,
    break_even,
    build_realized_stratum,
    classify_ask_band,
)

from structural_dead_stop import StructuralDeadVerdict, structural_dead

from breezy.persistence.scored_trial_store import read_scored_trials
from breezy.settlement.roi_bound import (
    ROIInputRow,
    compute_roi_bound,
    format_roi_bound,
)
from breezy.settlement.trial_scorer import ScoredTrial

__all__ = [
    "STRATUM_TABLE_DIVIDER",
    "STRATUM_TABLE_HEADER",
    "LiveFamilyTally",
    "StructuralDeadVerdict",
    "SlippageSummary",
    "assert_live_only",
    "assert_paper_only",
    "break_even",
    "build_live_family_tally",
    "render_markdown",
    "wilson_interval",
]

#: The live latch's own key prefix (`current_rung_hold/trial/{station}/
#: {climate_day}`) -- the ONLY provenance signal the 6c store carries.
_LIVE_TRIAL_ID_PREFIX = "current_rung_hold/trial/"

#: The paper-replay latch's own key prefix (6b, `paper_replay.
#: PAPER_TRIAL_ID_PREFIX`) -- restated verbatim here, not imported, because
#: `breezy.runtime.paper_replay` sits above this script in the layer graph
#: the same way `breezy.persistence.scored_trial_store` does; the two
#: prefixes are pinned never to collide by
#: `tests/unit/test_live_family_tally_provenance.py`.
_PAPER_TRIAL_ID_PREFIX = "paper_replay/current_rung_hold/trial/"

#: Pinned column-for-column identical to the M_B live section's stratum
#: table (`mb_current_rung_edge_study.py`'s `render_markdown`), per the
#: brief's "table columns byte-comparable to the M_B live section".
STRATUM_TABLE_HEADER = (
    "| stratum | n | k | realized rate | mean ask | break-even | "
    "Wilson-lower | Wilson-upper | |"
)
STRATUM_TABLE_DIVIDER = "|---|---:|---:|---:|---:|---:|---:|---:|---|"


@dataclass(frozen=True, slots=True, kw_only=True)
class _PricedRow:
    """Adapter shape `build_realized_stratum` needs: `.entry_ask`, `.held`.

    `build_realized_stratum` is annotated `Sequence[CurrentRungTrial]`, but
    its body (verified at `mb_current_rung_edge_study.py:726-741`) reads
    only `.entry_ask` and `.held` -- a genuine structural-typing reuse, so
    the `cast` at each call site below is honest, not a type-system
    workaround for an actual mismatch.
    """

    entry_ask: float
    held: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class SlippageSummary:
    """Mean/max of `fill_px - entry_ask` over the priced (non-excluded) rows."""

    n: int
    mean: Decimal | None
    max: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveFamilyTally:
    """The full 6d result: strata, verdict, slippage, and the 6e BCa line."""

    pooled: RealizedStratum | None
    station_strata: tuple[RealizedStratum, ...]
    ask_band_strata: tuple[RealizedStratum, ...]
    outcome: str
    detail: str
    total_pnl: Decimal
    n_scored: int
    n_excluded: int
    slippage: SlippageSummary
    bca_line: str
    #: The v1 section 5:105-106 structural-dead stop (KILL-class, additive
    #: to -- never a replacement of -- `pooled_kill`/`cell_dead` below).
    #: `None` when the caller supplies no `covered_listed_station_days`
    #: (the reader has its own I/O path; the tally never runs it itself).
    structural_dead: StructuralDeadVerdict | None


def assert_live_only(rows: Sequence[ScoredTrial]) -> None:
    """Refuse the whole tally if any row is not a live-latch trial.

    Analogous to L-13 (cadence mismatch) and L-21 (archive vs realized) --
    no lesson states this rule verbatim; it is a plan decision of this
    brief. The 6c store carries no separate archive/live provenance column,
    so the live latch's own key format is the only signal available; a row
    whose `trial_id` does not match it is refused outright rather than
    silently pooled.
    """
    offenders = tuple(
        row.trial_id for row in rows if not row.trial_id.startswith(_LIVE_TRIAL_ID_PREFIX)
    )
    if offenders:
        raise ValueError(
            "refusing to tally: non-live trial_id(s) found "
            f"(archive trials are never pooled here): {offenders!r}"
        )


def assert_paper_only(rows: Sequence[ScoredTrial]) -> None:
    """Symmetric to `assert_live_only`: refuse the paper tally if any row is
    not a `paper_replay/current_rung_hold/trial/...` row (6b, L-22
    provenance -- a live row must never pool into a mechanism-test tally
    either)."""
    offenders = tuple(
        row.trial_id for row in rows if not row.trial_id.startswith(_PAPER_TRIAL_ID_PREFIX)
    )
    if offenders:
        raise ValueError(
            "refusing to tally: non-paper trial_id(s) found "
            f"(live trials are never pooled into a paper_replay tally): {offenders!r}"
        )


def _rows_from_scored(scored: Sequence[ScoredTrial]) -> Sequence[CurrentRungTrial]:
    rows = tuple(_PricedRow(entry_ask=float(t.entry_ask), held=t.held) for t in scored)
    return cast(Sequence[CurrentRungTrial], rows)


def _station_strata(scored: Sequence[ScoredTrial]) -> tuple[RealizedStratum, ...]:
    by_station: dict[str, list[ScoredTrial]] = defaultdict(list)
    for trial in scored:
        by_station[trial.station].append(trial)
    strata = (
        build_realized_stratum(f"station:{station}", _rows_from_scored(by_station[station]))
        for station in sorted(by_station)
    )
    return tuple(stratum for stratum in strata if stratum is not None)


def _ask_band_strata(scored: Sequence[ScoredTrial]) -> tuple[RealizedStratum, ...]:
    by_band: dict[tuple[float, float], list[ScoredTrial]] = defaultdict(list)
    for trial in scored:
        by_band[classify_ask_band(float(trial.entry_ask))].append(trial)
    strata = []
    for lo, hi in ASK_BANDS:
        group = by_band.get((lo, hi), [])
        stratum = build_realized_stratum(f"ask:({lo},{hi}]", _rows_from_scored(group))
        if stratum is not None:
            strata.append(stratum)
    return tuple(strata)


def _slippage_summary(scored: Sequence[ScoredTrial]) -> SlippageSummary:
    if not scored:
        return SlippageSummary(n=0, mean=None, max=None)
    values = tuple(trial.slippage for trial in scored)
    mean = sum(values, start=Decimal(0)) / len(values)
    return SlippageSummary(n=len(values), mean=mean, max=max(values))


def _roi_bound_line(all_rows: Sequence[ScoredTrial]) -> str:
    """`format_roi_bound(compute_roi_bound(...))` with cost = fill_px + fee.

    Uses every scored row, priced and excluded alike -- `compute_roi_bound`
    itself computes the exclusion fraction and refuses (or not) accordingly;
    this function must not pre-filter.
    """
    inputs = tuple(
        ROIInputRow(
            pnl=trial.pnl,
            cost=trial.fill_px + trial.fee,
            excluded_reason=trial.excluded_reason,
        )
        for trial in all_rows
    )
    return format_roi_bound(compute_roi_bound(inputs))


def build_live_family_tally(
    rows: Sequence[ScoredTrial],
    *,
    provenance: str = "live",
    covered_listed_station_days: int | None = None,
    filled_takes: int | None = None,
) -> LiveFamilyTally:
    """Build the pooled/station/ask-band strata, verdict, and BCa line.

    `covered_listed_station_days`: the v1 section 5:105-106 structural-dead
    stop's denominator (see `structural_dead_stop.py`), supplied by a caller
    that has already run the catalog reader; `None` (default) means the
    stop is not evaluated and every existing fixture's output is byte-for-
    byte unchanged (golden -- see
    `tests/unit/test_live_family_tally_structural_dead.py`).

    `filled_takes` MUST be a FILL-TIME count (fills, including any not yet
    settled/scored) -- e.g. a live fill-state store -- supplied by the
    caller. It is deliberately NEVER derived from `len(rows)` here: `rows`
    is the 6c SCORED-trial store, which only carries trials that have
    already resolved a settlement basis (`trial_scorer.score_trial`
    requires an NWS final or an elapsed venue fallback), so a Take that
    filled today but has not settled yet is invisible to `rows` -- counting
    it as zero fires a false KILL against the pin "one fill defeats it".
    `None` (default, or whenever no fill-time source is reachable) FAILS
    CLOSED via `structural_dead_stop.structural_dead`'s own `evaluable`
    flag: the stop never fires, and `render_markdown` prints that it was
    skipped. When both `covered_listed_station_days` and `filled_takes` are
    given, `filled_takes` must be `>= len(rows)` by construction (a
    fill-time count can only be a superset of the settled/scored subset);
    violating this indicates a wired-in settled-only count and is refused.

    `provenance` selects which unforgeable barrier runs: `"live"` (default)
    dispatches to `assert_live_only`, UNMODIFIED; `"paper_replay"` dispatches
    to `assert_paper_only`. Excludes any row with a non-`None`
    `excluded_reason` from every stratum (review item 2) -- such rows are
    still counted by the BCa exclusion fraction below, via `_roi_bound_line`,
    which sees the full input.
    """
    if provenance == "paper_replay":
        assert_paper_only(rows)
    else:
        assert_live_only(rows)
    if filled_takes is not None and filled_takes < len(rows):
        raise ValueError(
            f"filled_takes={filled_takes} is less than len(rows)={len(rows)}: a "
            "fill-time count can only be a superset of the settled/scored rows; "
            "this looks like a settled-only count, which must never be passed here"
        )
    priced = tuple(row for row in rows if row.excluded_reason is None)
    excluded_count = len(rows) - len(priced)

    pooled = build_realized_stratum("pooled", _rows_from_scored(priced))
    station_strata = _station_strata(priced)
    ask_band_strata = _ask_band_strata(priced)
    cell_dead = tuple(
        stratum for stratum in (*station_strata, *ask_band_strata) if stratum.cell_dead
    )
    total_pnl = sum((row.pnl for row in priced), start=Decimal(0))

    pooled_kill = pooled is not None and pooled.cell_dead
    pooled_survive = (
        pooled is not None
        and pooled.survives
        and not cell_dead
        and total_pnl > 0
    )

    n_taken = pooled.n if pooled is not None else 0

    # v1 section 5:105-106, additive: evaluated ALONGSIDE the existing
    # pooled_kill/cell_dead computation above, never altering it. `None`
    # (the default) means the caller supplied no reader output, and this
    # branch never fires -- every existing fixture is unchanged (golden).
    structural = (
        None
        if covered_listed_station_days is None
        else structural_dead(
            covered_listed_station_days=covered_listed_station_days,
            filled_takes=filled_takes,
        )
    )
    structural_fired = structural is not None and structural.structural_dead

    if pooled_kill or bool(cell_dead) or structural_fired:
        outcome = "KILL"
        if pooled_kill:
            assert pooled is not None
            detail = (
                f"pooled Wilson-upper {pooled.wilson_upper:.4f} < "
                f"break-even {pooled.break_even:.4f} at n={n_taken}"
            )
        elif cell_dead:
            detail = (
                f"{len(cell_dead)} stratum(-a) cell-dead: "
                f"{', '.join(s.label for s in cell_dead)}"
            )
        else:
            assert structural is not None
            detail = (
                f"structural-dead: {structural.covered_listed_station_days} "
                f"covered-listed station-day(s), {structural.filled_takes} filled Take(s)"
            )
    elif pooled_survive:
        outcome = "SURVIVE"
        assert pooled is not None
        detail = (
            f"n={n_taken}, pooled Wilson-lower {pooled.wilson_lower:.4f} > "
            f"break-even {pooled.break_even:.4f}, no stratum cell-dead, "
            f"SigmaPnL={total_pnl} > 0"
        )
    else:
        outcome = "UNDERPOWERED"
        detail = f"n={n_taken}; not dead, not (yet) a SURVIVE"

    return LiveFamilyTally(
        pooled=pooled,
        station_strata=station_strata,
        ask_band_strata=ask_band_strata,
        outcome=outcome,
        detail=detail,
        total_pnl=total_pnl,
        n_scored=len(rows),
        n_excluded=excluded_count,
        slippage=_slippage_summary(priced),
        bca_line=_roi_bound_line(rows),
        structural_dead=structural,
    )


def _fmt_stratum_row(stratum: RealizedStratum) -> str:
    dead = "CELL-DEAD" if stratum.cell_dead else ""
    return (
        f"| {stratum.label} | {stratum.n} | {stratum.k} | {stratum.realized_hold_rate:.4f} | "
        f"{stratum.mean_ask:.4f} | {stratum.break_even:.4f} | {stratum.wilson_lower:.4f} | "
        f"{stratum.wilson_upper:.4f} | {dead} |"
    )


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 -- a report must render even without git
        return "unknown"


def render_markdown(
    tally: LiveFamilyTally,
    *,
    source_paths: Sequence[Path],
    as_of: str,
    provenance: str = "live",
) -> str:
    lines: list[str] = []

    def add(line: str) -> None:
        lines.append(line)

    add("# Live family tally")
    add("")
    add(f"provenance: {provenance}")
    add(f"as_of: {as_of}")
    add(f"git sha: {_git_sha()}")
    add(f"row count: {tally.n_scored} (excluded: {tally.n_excluded})")
    add("source parquet: " + ", ".join(str(p) for p in source_paths))
    add(
        "live trials only -- archive trials are never pooled here (analogous "
        "to L-13/L-21; no lesson states this rule verbatim -- it is a plan "
        "decision of this brief)."
    )
    add("")
    add(STRATUM_TABLE_HEADER)
    add(STRATUM_TABLE_DIVIDER)
    if tally.pooled is not None:
        add(_fmt_stratum_row(tally.pooled))
    for stratum in (*tally.station_strata, *tally.ask_band_strata):
        add(_fmt_stratum_row(stratum))
    add("")
    add(f"**{tally.outcome}** -- {tally.detail}")
    add("")
    if tally.structural_dead is not None and not tally.structural_dead.evaluable:
        add(
            "structural-dead stop (v1 section 5:105-106): SKIPPED -- no fill-time "
            "count was available; never inferred from settled/scored rows alone."
        )
        add("")
    if tally.slippage.n == 0:
        add("slippage (fill_px - entry_ask): n=0")
    else:
        add(
            f"slippage (fill_px - entry_ask): n={tally.slippage.n}, "
            f"mean={tally.slippage.mean}, max={tally.slippage.max}"
        )
    add("")
    add("realized ROI point estimate: SigmaPnL / Sigma(fill_px+fee) -- see BCa line below")
    add(tally.bca_line)
    add("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_dir", type=Path, help="6c scored-trial parquet directory")
    parser.add_argument("--output", type=Path, default=None, help="path to write the report")
    parser.add_argument("--as-of", type=str, default="", help="as-of stamp for the header")
    parser.add_argument(
        "--provenance", choices=("live", "paper_replay"), default="live",
        help="which unforgeable barrier to run -- see build_live_family_tally",
    )
    args = parser.parse_args(argv)

    rows = read_scored_trials(args.store_dir)
    tally = build_live_family_tally(rows, provenance=args.provenance)
    report = render_markdown(
        tally, source_paths=(args.store_dir,), as_of=args.as_of, provenance=args.provenance,
    )
    print(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
