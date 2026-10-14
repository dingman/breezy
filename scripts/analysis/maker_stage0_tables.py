"""MAKER-S2 WP5: CSV contract, byte-stable Markdown blocks and the rerun-from-CSV entry.

Plan ``docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r4_delta.md`` (g): the three CSVs
(``scored_episodes.csv``, ``station_days.csv``, ``tail_reliability.csv``) reproduce every
reproducible block byte-for-byte via ``tables_from_csvs``; blocks that need run-time sidecars are
labelled "run-time only, sha-pinned". The only I/O is the CSV re-read of a path the driver passes.
"""

from __future__ import annotations

import csv
import io
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import fields
from functools import partial
from pathlib import Path
from typing import Any, Final, cast, get_args, get_type_hints

from breezy.analysis.maker_tape_census import N_EFF_FLOOR
from scripts.analysis import maker_stage0_stats as st
from scripts.analysis import maker_stage0_verdict as vd
from scripts.analysis.maker_stage0_fill_events import StationDaySummary

NS_PER_S: Final[int] = 1_000_000_000
UNPINNED: Final[str] = "UNPINNED-RERUN"
RUNTIME_ONLY_LABEL: Final[str] = "run-time only, sha-pinned"
RUNTIME_ONLY_BLOCKS: Final[dict[str, str]] = {
    "overlay": "overlay_station_days.csv", "wp0_agreement": "wp0_agreement.json",
    "stress_plus60": "stress_plus60_station_days.csv", "progress": "progress.jsonl",
    "stress_poll_lag": "stress_poll_lag_station_days.csv", "bench": "bench output",
}  # fmt: skip
REPRODUCIBLE_BLOCKS: Final[tuple[str, ...]] = (
    "v0", "verdict", "rates", "hours", "s69", "expectancy", "bids", "s3", "tail", "delta",
    "coverage", "non_covered",
)  # fmt: skip
BANNER: Final[str] = "EXPLORATORY: never promotion evidence; Stage 0 never emits a go verdict."
_SHARED: Final[tuple[str, ...]] = tuple(
    f.name for f in fields(vd.SdRow) if f.name in {g.name for g in fields(StationDaySummary)}
)

# --- CSV --------------------------------------------------------------------------------------


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(value) if isinstance(value, float) else str(value)


def _coerce(raw: str, hint: object) -> object:
    args = get_args(hint)
    base = next((a for a in args if a is not type(None)), hint)
    if raw == "":
        if type(None) in args or base is str:
            return None if type(None) in args else ""
        raise ValueError("blank cell in a non-null column")
    if base is bool:
        if raw not in ("true", "false"):
            raise ValueError(f"bad boolean cell {raw!r}")
        return raw == "true"
    return cast(Callable[[str], object], base)(raw)


def _to_csv(cls: type, rows: Sequence[object]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    names = [f.name for f in fields(cls)]
    writer.writerow(names)
    writer.writerows([_cell(getattr(row, n)) for n in names] for row in rows)
    return out.getvalue()


def _from_csv[T](text: str, ctor: Callable[..., T], optional: Sequence[str] = ()) -> list[T]:
    hints = get_type_hints(ctor)
    reader = csv.DictReader(io.StringIO(text))
    missing = set(hints) - set(reader.fieldnames or ()) - set(optional)
    if missing:
        raise ValueError(f"csv is missing columns {sorted(missing)}")
    return [ctor(**{k: _coerce(row[k], hints[k]) for k in hints if k in row}) for row in reader]


sd_rows_to_csv = partial(_to_csv, vd.SdRow)
pos_rows_to_csv = partial(_to_csv, vd.PosRow)
tail_rows_to_csv = partial(_to_csv, st.TailRow)
read_station_days_csv = partial(
    _from_csv, ctor=vd.SdRow, optional=("rung_trials_attempted", "n_no_book_wants")
)
read_scored_csv = partial(_from_csv, ctor=vd.PosRow)
read_tail_csv = partial(_from_csv, ctor=st.TailRow)


def sd_row_from_summary(
    s: StationDaySummary,
    *,
    census_reason: str,
    covered_bidlive: bool,
    covered: bool,
    outage_excluded: bool,
    node_log_absent: bool,
    n_depth_frames: int,
    truth_final: bool | None = None,
    truth_tmax_f: int | None = None,
    void: bool | None = None,
    unresolved_d14: bool | None = None,
    theta: float | None = None,
    n_no_book_wants: int = 0,
) -> vd.SdRow:
    """A replayed row from WP4's summary; WP6 supplies the census, depth and truth fields."""
    copied: dict[str, Any] = {name: getattr(s, name) for name in _SHARED}
    in_den = covered and not outage_excluded and (s.bid_bearing or n_no_book_wants > 0)
    return vd.SdRow(
        **copied, cluster_id=s.climate_day, census_reason=census_reason,
        covered_bidlive=covered_bidlive, covered=covered, outage_excluded=outage_excluded,
        node_log_absent=node_log_absent, n_depth_frames=n_depth_frames,
        has_depth_frame=n_depth_frames > 0, nogo_driving=in_den and s.filled_pairs_stress == 0,
        positions_filled_k2_base=s.filled_pairs_base,
        positions_filled_k2_stress=s.filled_pairs_stress,
        positions_filled_k1_base=s.k1_filled_base, positions_filled_k1_stress=s.k1_filled_stress,
        truth_final=truth_final, truth_tmax_f=truth_tmax_f, void=void,
        unresolved_d14=unresolved_d14, theta=theta, n_no_book_wants=n_no_book_wants,
    )  # fmt: skip


# --- rendering helpers ------------------------------------------------------------------------


def _f(x: float | None, nd: int = 4) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def _md(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    return "\n".join([*lines, *("| " + " | ".join(r) + " |" for r in rows)]) + "\n"


def _span(ci: tuple[float, float] | None) -> str:
    return "n/a" if ci is None else f"[{ci[0]:.4f}, {ci[1]:.4f}]"


def _boot(b: st.BootInterval | None) -> str:
    return "not estimable" if b is None else _span((b.low, b.high))


def _clusters(b: st.BootInterval | None) -> str:
    return "<5" if b is None else str(b.n_clusters)


def _hypotheses(sds: Sequence[vd.SdRow]) -> list[tuple[str, list[vd.SdRow]]]:
    names = sorted({r.unit_hypothesis for r in sds})
    return [(n, [r for r in sds if r.unit_hypothesis == n and vd.in_denominator(r)]) for n in names]


# --- blocks -----------------------------------------------------------------------------------


def render_v0(analyses: Sequence[vd.HypAnalysis]) -> str:
    def rho(fit: st.IccFit) -> str:
        return "undefined" if fit.rho is None else _f(fit.rho)

    head = ["hypothesis", "n_sd", "n0", "n_eff_gov", f"floor {N_EFF_FLOOR}", "V0"]
    v0 = [
        [a.name, str(a.n_sd), str(a.n0), _f(a.n_eff_gov, 2), str(N_EFF_FLOOR),
         "fires" if a.n_eff_gov < N_EFF_FLOOR else "clear"]
        for a in analyses
    ]  # fmt: skip
    fitted = [
        [a.name, rho(a.icc_station_day), _f(a.icc_station_day.deff_hat),
         _f(a.icc_station_day.n_eff_hat, 2), _f(a.icc_station_day.msb), _f(a.icc_station_day.msw),
         _f(a.icc_station_day.m0)]
        for a in analyses
    ]  # fmt: skip
    banners = [
        f"FITTED-ICC DISAGREES ON THE FLOOR ({a.name}; report-only)\n"
        for a in analyses
        if a.fitted_icc_disagrees
    ]
    fit_head = ["hypothesis", "fill_icc_station_day", "deff_hat", "n_eff_hat", "MSB", "MSW", "m0"]
    return (
        "V0 (decided by n_eff_gov, never by fill outcomes)\n" + _md(head, v0)
        + "\nFitted ICC (report-only)\n" + _md(fit_head, fitted) + "".join(banners)
    )  # fmt: skip


def render_verdict(
    decision: vd.Decision, analyses: Sequence[vd.HypAnalysis], tail: st.TailTable
) -> str:
    gov = next(a for a in analyses if a.name == decision.governing)
    lines = [f"Verdict: {decision.label}", BANNER, f"governing hypothesis: {decision.governing}"]
    if decision.label == vd.UNDERPOWERED:
        lines.append("V1-V5 below: descriptive, not a label (V0 fired; no build starts)")
    else:
        lines.append(f"failing rows: {', '.join(decision.failing) or 'none'}")
    lines += [f"- {c}" for c in decision.comparisons]
    if decision.label != vd.UNDERPOWERED:
        lines += [f"- {n}: {label}" for n, label in sorted(decision.per_hypothesis.items())]
    lines.append(f"base rate (stricter unit) {gov.base_rate:.4f}; stressed {gov.stress_rate:.4f}")
    if tail.miscalibrated:
        lines.append("TAIL-MISCALIBRATED (annotation; never changes the label)")
    return "\n".join(lines) + "\n"


_RATE_LABELS: Final[dict[str, tuple[str, str]]] = {
    "base_sd": ("station-day", "base"), "stress_sd": ("station-day", "stressed"),
    "base_pos": ("position", "base"), "stress_pos": ("position", "stressed"),
    "base_k1": ("K1 station-day", "base"), "stress_k1": ("K1 station-day", "stressed"),
}  # fmt: skip


def render_rates(analyses: Sequence[vd.HypAnalysis]) -> str:
    rows = [
        [a.name, unit, rule, str(r.k), str(r.n), _f(r.point), _span(r.wilson), _boot(r.boot),
         _clusters(r.boot)]
        for a in analyses
        for key, (unit, rule) in _RATE_LABELS.items()
        for r in (a.rates[key],)
    ]  # fmt: skip
    head = ["hypothesis", "unit", "rule", "k", "n", "point", "Wilson (sidecar)",
            "cluster bootstrap (interval is n_eff-adjusted)", "clusters"]  # fmt: skip
    keys = ("k2_base", "k2_stress", "k1_base", "k1_stress")
    days = [[a.name, *(_f(a.days_to_200[k], 1) for k in keys)] for a in analyses]
    return (
        _md(head, rows) + "\nImplied days to 200 positions (MAX_RUNGS 2 / 1)\n"
        + _md(["hypothesis", *keys], days)
    )  # fmt: skip


def render_hours(sds: Sequence[vd.SdRow]) -> str:
    rows = []
    for name, den in _hypotheses(sds):
        for station in sorted({r.station for r in den}):
            rs = [r for r in den if r.station == station]
            live, valid, gap, eps, refused, cuts = (
                sum(vd.nz(getattr(r, k)) for r in rs)
                for k in ("process_live_h", "forecast_valid_h", "gap_h", "n_episodes", "n_refused",
                          "n_process_cuts")
            )  # fmt: skip
            placed = eps + refused
            rows.append([name, station, str(len(rs)), _f(live, 2), _f(valid, 2), _f(gap, 2),
                         _f(gap / valid if valid else None),
                         _f(refused / placed if placed else None),
                         _f(cuts / eps if eps else None)])  # fmt: skip
    head = ["hypothesis", "station", "n_sd", "process_live_h", "forecast_valid_h", "gap_h",
            "gap share", "refused share", "process-cut share"]  # fmt: skip
    return _md(head, rows)


def render_s69(r: vd.Section69) -> str:
    tests = _md(
        ["test", "p-value", "climate-date clusters", "FAIL if"],
        [
            ["Test A (model; p is p_yes_point_live, 1.5 margin)", _f(r.p_a, 6), str(r.clusters_a),
             "< 0.05"],
            ["Test B Poisson-conditional rate-ratio test (approximation, valid at p <= 0.06)",
             _f(r.p_b, 6), str(r.clusters_b), "< 0.05"],
        ],
    )  # fmt: skip
    power = _md(["k", "P(Test A FAIL | k)"], [[str(p.k), _f(p.power)] for p in r.power.rows])
    strata = _md(
        ["stratum (p_NO, descriptive only)", "n_f", "n_u", "L_f", "L_u", "E", "p_A", "p_B"],
        [[s.label, str(s.n_f), str(s.n_u), str(s.l_f), str(s.l_u), _f(s.expected), _f(s.p_a, 6),
          _f(s.p_b, 6)] for s in r.strata],
    )  # fmt: skip
    return (
        f"state: {r.state} (pooled; strata never set it)\n"
        f"n filled {r.n_filled}, n unfilled {r.n_unfilled}, expected losses "
        f"{r.expected_losses:.4f}, observed losses filled {r.losses_filled} "
        f"unfilled {r.losses_unfilled}\n{tests}\n"
        f"stratum-mix-adjusted rate ratio (descriptive): {_f(r.mix_adjusted_ratio)}\n\n"
        f"Power line (analytic; critical count {r.power.critical_count}; pooled fills needed "
        f"for E >= 10: {r.power.fills_needed_for_ten_expected_losses})\n{power}\n{strata}\n"
        f"excluded for lacking CLI FINAL: {r.excluded_no_final_filled} filled, "
        f"{r.excluded_no_final_unfilled} unfilled rows on {r.excluded_no_final_days} "
        f"station-days; void excluded: {r.n_void_excluded}\n"
        "UNSCREENED-TERMINAL (spec :300-302) is not a Stage 0 object.\n"
    )


def render_expectancy(analyses: Sequence[vd.HypAnalysis]) -> str:
    rows = [
        [a.name, str(e.n_fills), _f(e.win_rate), _f(e.mean_p_no), _boot(e.win_rate_boot),
         _clusters(e.win_rate_boot), _span(e.win_rate_cp), _f(e.net_mean),
         "not estimable" if e.net_upper_bound is None else _f(e.net_upper_bound),
         str(e.n_excluded_no_final)]
        for a in analyses
        for e in (a.expectancy,)
    ]  # fmt: skip
    head = ["hypothesis", "fills", "win rate", "mean p_NO", "win-rate cluster bootstrap",
            "clusters", "Clopper-Pearson (sidecar)", "net per fill",
            "one-sided 95% upper bound", "no CLI FINAL"]  # fmt: skip
    return _md(head, rows) + "A negative net expectancy is reported, never a kill.\n"


def render_bids(poss: Sequence[vd.PosRow]) -> str:
    rows = []
    for name in sorted({p.unit_hypothesis for p in poss}):
        mine = [p for p in poss if p.unit_hypothesis == name]
        for cents in sorted({round(p.bid * 100) for p in mine}):
            at = [p for p in mine if round(p.bid * 100) == cents]
            rows.append([name, str(cents), str(sum(p.filled_base for p in at)), str(len(at))])
    return _md(["hypothesis", "bid (cents)", "fills (base)", "all posted"], rows)


def render_tail(t: st.TailTable) -> str:
    rows = [
        [b.label, str(b.n), str(b.n_dates), _f(b.mean_p), _f(b.observed), _span(b.ci)]
        for b in t.bins
    ]
    return _md(["bin", "n", "dates", "mean p", "observed", "Clopper-Pearson"], rows) + (
        f"pooled n {t.n}, expected {t.expected:.4f}, observed {t.observed}, "
        f"two-sided exact p {_f(t.p_value, 6)}\n"
    )


def render_delta(sds: Sequence[vd.SdRow]) -> str:
    rows = []
    for name, den in _hypotheses(sds):
        d = [abs(r.delta_ns) / NS_PER_S for r in den if r.delta_ns is not None]
        med, top = (statistics.median(d), max(d)) if d else (None, None)
        rows.append([name, str(len(d)), str(sum(x > 0 for x in d)), _f(med, 1), _f(top, 1)])
    return _md(["hypothesis", "replayed", "nonzero", "median |delta| s", "max |delta| s"], rows)


def render_coverage(analyses: Sequence[vd.HypAnalysis]) -> str:
    rows = [
        [a.name, str(c.n_all), str(c.n_sd), _f(c.base_sd), _f(c.stress_sd), _f(c.base_pos),
         _f(c.stress_pos), str(c.nogo_driving), str(c.nogo_gap_gt_half),
         _f(c.nogo_gap_gt_half / c.nogo_driving if c.nogo_driving else None)]
        for a in analyses
        for c in (a.coverage,)
    ]  # fmt: skip
    head = ["hypothesis", "n_sd", "n_sd with covered_live_h >= 0.5 x process_live_h", "base day",
            "stressed day", "base position", "stressed position", "nogo_driving days",
            "of which gap_share > 0.5", "share"]  # fmt: skip
    return "Coverage sensitivity (report-only; never changes the label)\n" + _md(head, rows)


def render_non_covered(sds: Sequence[vd.SdRow]) -> str:
    days: dict[tuple[str, str], vd.SdRow] = {}
    for r in sorted(sds, key=lambda x: (x.station, x.climate_day, x.unit_hypothesis)):
        days.setdefault((r.station, r.climate_day), r)
    reasons: dict[str, int] = defaultdict(int)
    for r in days.values():
        reasons[r.census_reason or "unknown"] += not r.covered
    frame = sum(1 for r in days.values() if r.has_depth_frame)
    rate = _f(frame / len(days) if days else None)
    rows = [[k, str(v)] for k, v in sorted(reasons.items()) if v]
    return _md(["non-COVERED reason", "station-days"], rows) + (
        f"census station-days {len(days)}; with >= 1 depth frame {frame} ({rate}; report-only)\n"
    )


# --- entry points -----------------------------------------------------------------------------


def render_tables(
    sds: Sequence[vd.SdRow],
    poss: Sequence[vd.PosRow],
    tail: Sequence[st.TailRow],
    *,
    code_sha: str = UNPINNED,
) -> dict[str, str]:
    analyses = vd.analyse_all(sds, poss)
    decision = vd.decide(analyses)
    tail_table = st.tail_table(tail)
    s3 = vd.build_s3_inputs(decision, analyses, code_sha=code_sha)
    s69 = "".join(f"#### {a.name}\n{render_s69(a.s69)}\n" for a in analyses)
    blocks = {
        "v0": render_v0(analyses),
        "verdict": render_verdict(decision, analyses, tail_table),
        "rates": render_rates(analyses),
        "hours": render_hours(sds),
        "s69": s69,
        "expectancy": render_expectancy(analyses),
        "bids": render_bids(poss),
        "s3": json.dumps(s3, indent=2, sort_keys=True) + "\n",
        "tail": render_tail(tail_table),
        "delta": render_delta(sds),
        "coverage": render_coverage(analyses),
        "non_covered": render_non_covered(sds),
    }
    blocks.update({k: f"{RUNTIME_ONLY_LABEL}: {v}\n" for k, v in RUNTIME_ONLY_BLOCKS.items()})
    return blocks


def tables_from_csvs(
    scored_csv: Path, station_days_csv: Path, tail_csv: Path, *, code_sha: str = UNPINNED
) -> dict[str, str]:
    """``maker_stage0_stats --scored``: every reproducible table from the three CSVs."""
    return render_tables(
        read_station_days_csv(station_days_csv.read_text(encoding="utf-8")),
        read_scored_csv(scored_csv.read_text(encoding="utf-8")),
        read_tail_csv(tail_csv.read_text(encoding="utf-8")),
        code_sha=code_sha,
    )
