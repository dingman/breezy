"""M1: a model-free market calibration scan of the Polymarket.us weather ladder (FQ-R9, FQ-R14).

QUESTION. Is the venue's own price mispriced in any (window, side, ask-bin) cell, net of the venue
fee? Every rung, every station-day, YES and NO, with NO forecast model of any kind: the only inputs
are the recorder's Depth10 tape and the realised NWS CLI finals in ``settlement_truth.csv``.

SCREENING ONLY. This data never doubles as nomination evidence (FQ-R14): a cell that screens
positive becomes a hypothesis for FORWARD days after a freeze, nothing more. Read-only: no network,
no Nautilus runtime, no write outside ``--out``, never into the live data root.

DEFINITIONS (pre-registered here; changing one is a new scan, not a tuned one)
  * Ask. YES ask = lowest Depth10 ask level with size >= 1. NO ask = ``1 - best YES bid`` over bid
    levels with size >= 1 (the venue represents a NO buy as a sell of the YES side,
    ``leg_prices.py``); a NO observation exists ONLY when that bid level exists, never synthesised.
    ``QuoteTick`` is never read: it cannot show an empty bid (L-35).
  * Reference row. The FIRST Depth10 row whose ``ts_event`` lies inside a fixed one-hour window,
    scoped by calendar date AND hour (``WINDOWS``).
  * Excess = ``hit - (ask + fee)``, ``fee = round_half_even(theta * ask * (1 - ask), 0.01)`` at
    ``theta = 0.0695``. The cell statistic is the mean excess; n counts observations.
  * Bootstrap. Whole CALENDAR DAYS (the climate day, shared by all stations) are resampled with
    replacement; B and the seed are ``roi_bound``'s pinned values.
  * Multiplicity. Bonferroni over every tested cell, plus White's reality check and Hansen's
    consistent SPA p-value for the best cell, from one joint day resampling.
  * Validity STOP. Join coverage below 95% or a failed look-ahead assert marks the output INVALID,
    and no cell table or conclusion is emitted.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Final

import numpy as np

from breezy.analysis.capture_audit_tape import DEPTH_DIR, RecorderCatalogTape
from breezy.settlement.roi_bound import B_RESAMPLES, SEED

__all__ = [
    "ASK_BIN_EDGES",
    "JOIN_COVERAGE_FLOOR",
    "THETA",
    "WINDOWS",
    "LookAheadError",
    "Observation",
    "RungSpec",
    "ScanResult",
    "TruthRow",
    "Window",
    "ask_bin",
    "assert_no_lookahead",
    "best_ask",
    "build_scan",
    "collect",
    "load_truth",
    "main",
    "no_ask",
    "parse_slug",
    "rung_outcome",
    "venue_fee",
    "write_outputs",
]

THETA: Final[Decimal] = Decimal("0.0695")
_CENT: Final[Decimal] = Decimal("0.01")
_ONE: Final[Decimal] = Decimal(1)
_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3600 * _NS
_DAY_NS: Final[int] = 24 * _HOUR_NS
JOIN_COVERAGE_FLOOR: Final[float] = 0.95
MIN_CELL_N: Final[int] = 30
MIN_CELL_DAYS: Final[int] = 5
LIVE_DATA_ROOT: Final[Path] = Path.home() / ".local" / "share" / "breezy"
DEFAULT_CATALOG: Final[Path] = LIVE_DATA_ROOT / "catalog" / "quote_tape" / "polymarket_us"
DEFAULT_TRUTH: Final[Path] = (
    LIVE_DATA_ROOT / "derived" / "settlement-truth" / "settlement_truth.csv"
)

#: Decile ask bins, the same edges as ``forecast_conditional_corpus.RELIABILITY_BUCKET_EDGES``
#: (restated: importing that module would pull the forecast study into a model-free scan).
ASK_BIN_EDGES: Final[tuple[float, ...]] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

SCREENING_NOTICE: Final[str] = (
    "SCREENING ONLY. This data never doubles as nomination evidence (FQ-R14): a positive cell is "
    "a hypothesis for forward days after a freeze, never a trade rule and never a nomination."
)
_SLUG_RE: Final[re.Pattern[str]] = re.compile(
    r"\Atc-temp-(?P<st>[a-z]+)high-(?P<day>\d{4}-\d\d-\d\d)-"
    r"(?:gte(?P<lo>\d+))?(?:lt(?P<hi>\d+))?f\.POLYMARKET_US\Z"
)


class LookAheadError(AssertionError):
    """A reference timestamp is not strictly before the settlement or the outcome."""


@dataclass(frozen=True, slots=True)
class Window:
    """A fixed one-hour UTC window: ``hour`` o'clock on climate day ``D + day_offset``."""

    label: str
    day_offset: int
    hour: int


#: Pre-registered. D-1 evening (market just listed), D morning, D late morning (pre-peak).
WINDOWS: Final[tuple[Window, ...]] = (
    Window("D-1_18Z", -1, 18),
    Window("D_12Z", 0, 12),
    Window("D_17Z", 0, 17),
)


@dataclass(frozen=True, slots=True)
class RungSpec:
    """One rung. ``lower``/``upper`` are INCLUSIVE strikes (the venue's ``strike_*_f``)."""

    station: str
    climate_day: dt.date
    lower: int | None
    upper: int | None


@dataclass(frozen=True, slots=True)
class TruthRow:
    tmax_f: int
    settled_ns: int


@dataclass(frozen=True, slots=True)
class Observation:
    station: str
    climate_day: dt.date
    window: str
    rung: str
    side: str
    ask: Decimal
    ref_ts_ns: int
    settled_ns: int
    hit: bool


def parse_slug(name: str) -> RungSpec | None:
    """The rung of an instrument directory name, or None when it is not a HIGH temperature rung."""
    match = _SLUG_RE.fullmatch(name)
    if match is None or (match["lo"] is None and match["hi"] is None):
        return None
    lower = None if match["lo"] is None else int(match["lo"])
    # The slug token is not the interval: ``gte{A}lt{A+1}f`` is the CLOSED two-degree bucket
    # ``[A, A+1]`` (title "A to A+1"), and ``lt{X}f`` is "X-1 or below" (``strike_upper_f=X-1``).
    upper: int | None = None
    if match["hi"] is not None:
        upper = int(match["hi"]) if lower is not None else int(match["hi"]) - 1
    return RungSpec(
        station=match["st"].upper(),
        climate_day=dt.date.fromisoformat(match["day"]),
        lower=lower,
        upper=upper,
    )


def rung_outcome(spec: RungSpec, tmax_f: int) -> bool:
    """True when the settled high lies in the rung's CLOSED interval ``[lower, upper]``."""
    return (spec.lower is None or tmax_f >= spec.lower) and (
        spec.upper is None or tmax_f <= spec.upper
    )


def venue_fee(price: Decimal, theta: Decimal = THETA) -> Decimal:
    """``theta * p * (1 - p)`` for one contract, banker's-rounded to the cent (venue formula)."""
    if price < 0 or price > _ONE:
        raise ValueError(f"price {price} is outside [0, 1]")
    return (theta * price * (_ONE - price)).quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _levels(body: Mapping[str, Any], key: str) -> list[tuple[Decimal, Decimal]]:
    out = [(Decimal(p), Decimal(s)) for p, s in body.get(key, ())]
    return [(p, s) for p, s in out if s >= 1]


def best_ask(body: Mapping[str, Any]) -> Decimal | None:
    """The lowest Depth10 ask with size >= 1, or None when no such level exists."""
    asks = _levels(body, "asks")
    return min(p for p, _ in asks) if asks else None


def no_ask(body: Mapping[str, Any]) -> Decimal | None:
    """``1 - best YES bid`` (size >= 1). None when the bid side is empty: never synthesised."""
    bids = _levels(body, "bids")
    return _ONE - max(p for p, _ in bids) if bids else None


def ask_bin(ask: Decimal) -> str:
    """The decile bin label of an ask in ``[0, 1)``."""
    index = sum(1 for edge in ASK_BIN_EDGES if float(ask) >= edge)
    lows = (0.0, *ASK_BIN_EDGES)
    highs = (*ASK_BIN_EDGES, 1.0)
    return f"{lows[index]:.1f}-{highs[index]:.1f}"


def window_bounds_ns(climate_day: dt.date, window: Window) -> tuple[int, int]:
    day = climate_day + dt.timedelta(days=window.day_offset)
    start = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS
    start += window.hour * _HOUR_NS
    return start, start + _HOUR_NS


def assert_no_lookahead(observation: Observation) -> None:
    """The reference must precede the settlement publication and the end of the climate day."""
    day_end = (
        int(
            dt.datetime(
                observation.climate_day.year,
                observation.climate_day.month,
                observation.climate_day.day,
                tzinfo=dt.UTC,
            ).timestamp()
        )
        * _NS
        + _DAY_NS
    )
    if observation.ref_ts_ns >= observation.settled_ns:
        raise LookAheadError(
            f"{observation.station} {observation.climate_day}: ref_ts {observation.ref_ts_ns} is "
            f"not before settlement {observation.settled_ns}"
        )
    if observation.ref_ts_ns >= day_end:
        raise LookAheadError(
            f"{observation.station} {observation.climate_day}: ref_ts {observation.ref_ts_ns} is "
            f"not before the outcome observation (climate day end {day_end})"
        )


def load_truth(path: Path) -> tuple[dict[tuple[str, dt.date], TruthRow], dt.date | None]:
    """FINAL CLI rows keyed by (station, climate day), and the last FINAL climate day."""
    rows: dict[tuple[str, dt.date], TruthRow] = {}
    with path.open(newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw["is_final"] != "True" or not raw["tmax_f"]:
                continue
            key = (raw["station"], dt.date.fromisoformat(raw["climate_day"]))
            issued = dt.datetime.fromisoformat(raw["issued_at_utc"])
            row = TruthRow(int(raw["tmax_f"]), int(issued.timestamp()) * _NS)
            kept = rows.get(key)
            if kept is None or row.settled_ns > kept.settled_ns:
                rows[key] = row
    last = max((day for _, day in rows), default=None)
    return rows, last


@dataclass(frozen=True, slots=True)
class Collected:
    observations: tuple[Observation, ...]
    tape_station_days: int
    joined_station_days: int
    horizon_station_days: int
    horizon_joined_station_days: int
    truth_last_day: dt.date | None
    lookahead_failures: tuple[str, ...]
    skipped_no_ask: int
    skipped_no_bid_side: int
    skipped_degenerate_price: int
    unparsed_directories: int


def _first_row(
    tape: RecorderCatalogTape, instrument: str, lo_ns: int, hi_ns: int
) -> Mapping[str, Any] | None:
    for row in tape.depth_rows(instrument, lo_ns, hi_ns):
        return row
    return None


def collect(
    catalog_root: Path,
    truth: Mapping[tuple[str, dt.date], TruthRow],
    truth_last_day: dt.date | None,
    windows: Sequence[Window] = WINDOWS,
) -> Collected:
    """Join the Depth10 tape to the truth. Reads ``order_book_depths`` only."""
    base = catalog_root / "data" / DEPTH_DIR
    by_day: dict[dt.date, list[tuple[str, RungSpec]]] = defaultdict(list)
    unparsed = 0
    for entry in sorted(base.iterdir()) if base.is_dir() else ():
        spec = parse_slug(entry.name) if entry.is_dir() else None
        if spec is None:
            unparsed += 1
        else:
            by_day[spec.climate_day].append((entry.name, spec))
    tape_days = {(s.station, d) for d, items in by_day.items() for _, s in items}
    joined = {key for key in tape_days if key in truth}
    horizon = {key for key in tape_days if truth_last_day and key[1] <= truth_last_day}
    obs: list[Observation] = []
    failures: list[str] = []
    counts = {"ask": 0, "bid": 0, "price": 0}
    for day in sorted(by_day):
        members = [(n, s) for n, s in by_day[day] if (s.station, day) in truth]
        if not members:
            continue
        names = frozenset(n for n, _ in members)
        tapes: dict[dt.date, RecorderCatalogTape] = {}
        for window in windows:
            lo, hi = window_bounds_ns(day, window)
            utc_day = day + dt.timedelta(days=window.day_offset)
            tape = tapes.setdefault(utc_day, RecorderCatalogTape(catalog_root, utc_day, names))
            for name, spec in members:
                row = _first_row(tape, name, lo, hi)
                if row is None:
                    continue
                ts = int(row["ts_event"])
                if not lo <= ts < hi:
                    raise LookAheadError(f"{name}: row {ts} escaped window {window.label}")
                found = truth[(spec.station, day)]
                outcome = rung_outcome(spec, found.tmax_f)
                for side, ask, hit in (
                    ("YES", best_ask(row), outcome),
                    ("NO", no_ask(row), not outcome),
                ):
                    if ask is None:
                        counts["ask" if side == "YES" else "bid"] += 1
                    elif not 0 < ask < 1:
                        counts["price"] += 1
                    else:
                        candidate = Observation(
                            spec.station,
                            day,
                            window.label,
                            name.removesuffix(".POLYMARKET_US"),
                            side,
                            ask,
                            ts,
                            found.settled_ns,
                            hit,
                        )
                        try:
                            assert_no_lookahead(candidate)
                        except LookAheadError as exc:
                            failures.append(str(exc))
                        obs.append(candidate)
    return Collected(
        tuple(obs),
        len(tape_days),
        len(joined),
        len(horizon),
        len(horizon & joined),
        truth_last_day,
        tuple(failures),
        counts["ask"],
        counts["bid"],
        counts["price"],
        unparsed,
    )


def excess(observation: Observation) -> float:
    cost = observation.ask + venue_fee(observation.ask)
    return float(Decimal(int(observation.hit)) - cost)


@dataclass(frozen=True, slots=True)
class ScanResult:
    cells: tuple[dict[str, Any], ...]
    multiplicity: dict[str, Any]
    n_days: int
    untested_cells: int


def _day_matrices(
    obs: Iterable[Observation], min_n: int, min_days: int
) -> tuple[list[tuple[str, str, str]], list[dt.date], np.ndarray, np.ndarray, int]:
    sums: dict[tuple[str, str, str], dict[dt.date, list[float]]] = defaultdict(
        lambda: defaultdict(lambda: [0.0, 0.0])
    )
    for o in obs:
        cell = sums[(o.window, o.side, ask_bin(o.ask))][o.climate_day]
        cell[0] += excess(o)
        cell[1] += 1.0
    days = sorted({d for per in sums.values() for d in per})
    index = {d: i for i, d in enumerate(days)}
    keys = sorted(
        k
        for k, per in sums.items()
        if sum(v[1] for v in per.values()) >= min_n and len(per) >= min_days
    )
    s_mat = np.zeros((len(days), len(keys)))
    n_mat = np.zeros((len(days), len(keys)))
    for j, key in enumerate(keys):
        for day, (total, count) in sums[key].items():
            s_mat[index[day], j], n_mat[index[day], j] = total, count
    return keys, days, s_mat, n_mat, len(sums) - len(keys)


def build_scan(
    observations: Iterable[Observation],
    *,
    min_n: int = MIN_CELL_N,
    min_days: int = MIN_CELL_DAYS,
    resamples: int = B_RESAMPLES,
    seed: int = SEED,
) -> ScanResult:
    """Per-cell mean excess with a calendar-day block bootstrap and multiplicity control."""
    keys, days, s_mat, n_mat, untested = _day_matrices(observations, min_n, min_days)
    if not keys:
        return ScanResult((), {"tested_cells": 0}, len(days), untested)
    n_days = len(days)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_days, size=(resamples, n_days))
    weights = (draws[:, :, None] == np.arange(n_days)).sum(axis=1).astype(float)
    total_n = n_mat.sum(axis=0)
    observed = s_mat.sum(axis=0) / total_n
    num, den = weights @ s_mat, weights @ n_mat
    boot = np.where(den > 0, num / np.where(den > 0, den, 1.0), observed)
    se = np.maximum(boot.std(axis=0, ddof=1), 1e-12)
    lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
    p_cell = (1 + (boot <= 0).sum(axis=0)) / (resamples + 1)
    k_tested = len(keys)
    centred = boot - observed
    rc_p = float((1 + (centred.max(axis=1) >= observed.max()).sum()) / (resamples + 1))
    threshold = se * math.sqrt(2.0 * math.log(math.log(max(n_days, 3))))
    drift = np.where(observed <= -threshold, observed, 0.0)
    z_boot = np.maximum((centred + drift) / se, -np.inf).max(axis=1)
    t_obs = float(max((observed / se).max(), 0.0))
    spa_p = float((1 + (np.maximum(z_boot, 0.0) >= t_obs).sum()) / (resamples + 1))
    cells: tuple[dict[str, Any], ...] = tuple(
        {
            "window": key[0],
            "side": key[1],
            "ask_bin": key[2],
            "n": int(total_n[j]),
            "n_days": int((n_mat[:, j] > 0).sum()),
            "mean_excess": float(observed[j]),
            "ci95_lo": float(lo[j]),
            "ci95_hi": float(hi[j]),
            "p_one_sided": float(p_cell[j]),
            "p_bonferroni": float(min(1.0, p_cell[j] * k_tested)),
            "t_stat": float(observed[j] / se[j]),
        }
        for j, key in enumerate(keys)
    )
    best = int(np.argmax(observed / se))
    multiplicity = {
        "tested_cells": k_tested,
        "bonferroni_alpha_per_cell": 0.05 / k_tested,
        "best_cell_by_t": {k: cells[best][k] for k in ("window", "side", "ask_bin")},
        "best_cell_p_bonferroni": cells[best]["p_bonferroni"],
        "reality_check_p": rc_p,
        "spa_p": spa_p,
        "any_cell_bonferroni_significant": any(c["p_bonferroni"] < 0.05 for c in cells),
        "resamples": resamples,
        "seed": seed,
    }
    return ScanResult(cells, multiplicity, n_days, untested)


def build_report(
    collected: Collected, scan: ScanResult | None, *, floor: float = JOIN_COVERAGE_FLOOR
) -> dict[str, Any]:
    """The JSON report. INVALID carries reasons only: no cell table, no conclusion."""
    horizon = collected.horizon_station_days
    coverage = collected.horizon_joined_station_days / horizon if horizon else 0.0
    raw = (
        collected.joined_station_days / collected.tape_station_days
        if collected.tape_station_days
        else 0.0
    )
    reasons: list[str] = []
    if coverage < floor:
        reasons.append(f"join_coverage {coverage:.4f} < {floor}")
    if collected.lookahead_failures:
        reasons.append(f"{len(collected.lookahead_failures)} look-ahead assert failure(s)")
    report: dict[str, Any] = {
        "kind": "market_calibration_scan/v1",
        "notice": SCREENING_NOTICE,
        "status": "INVALID" if reasons else "VALID",
        "invalid_reasons": reasons,
        "join_coverage": {
            "validity_metric": "horizon",
            "horizon": coverage,
            "horizon_note": "tape station-days with climate_day <= last FINAL truth day that "
            "have truth / all such tape station-days",
            "all_tape_station_days": raw,
            "tape_station_days": collected.tape_station_days,
            "joined_station_days": collected.joined_station_days,
            "horizon_station_days": horizon,
            "horizon_joined_station_days": collected.horizon_joined_station_days,
            "truth_last_day": None
            if collected.truth_last_day is None
            else collected.truth_last_day.isoformat(),
        },
        "windows": [
            {"label": w.label, "day_offset": w.day_offset, "hour_utc": w.hour} for w in WINDOWS
        ],
        "theta": str(THETA),
        "observations": len(collected.observations),
        "skipped": {
            "no_yes_ask": collected.skipped_no_ask,
            "no_bid_side_for_no_ask": collected.skipped_no_bid_side,
            "degenerate_price": collected.skipped_degenerate_price,
            "unparsed_directories": collected.unparsed_directories,
        },
        "caveat": (
            "Reads the converted data/ catalog only (L-20): unconverted live/ streams are not "
            "scanned. The ask is the best level at size >= 1 of the first Depth10 row in each "
            "window: no depth walk, no slippage, no fill probability. Overlapping rungs of one "
            "station-day are dependent; the day-block bootstrap is the only clustering applied."
        ),
    }
    if not reasons and scan is not None:
        report.update(
            n_days=scan.n_days,
            untested_cells=scan.untested_cells,
            cells=list(scan.cells),
            multiplicity=scan.multiplicity,
            conclusion="SCREENING ONLY: see cells and multiplicity; no nomination from this data.",
        )
    return report


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Market calibration scan (M1)",
        "",
        f"**{report['notice']}**",
        "",
        f"Status: **{report['status']}**",
    ]
    lines += [f"- INVALID: {r}" for r in report["invalid_reasons"]]
    cov = report["join_coverage"]
    lines += [
        (
            f"- Join coverage (validity, horizon): {cov['horizon']:.4f}; raw over all tape "
            f"station-days: {cov['all_tape_station_days']:.4f}; "
            f"truth last day {cov['truth_last_day']}"
        ),
        f"- Observations: {report['observations']}; theta {report['theta']}",
        f"- {report['caveat']}",
    ]
    if report["status"] == "VALID":
        lines += [
            "",
            "| window | side | ask bin | n | days | mean excess | CI95 lo | CI95 hi | p (Bonf.) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for c in sorted(report.get("cells", []), key=lambda c: -c["t_stat"]):
            lines.append(
                f"| {c['window']} | {c['side']} | {c['ask_bin']} | {c['n']} | {c['n_days']} | "
                f"{c['mean_excess']:+.4f} | {c['ci95_lo']:+.4f} | {c['ci95_hi']:+.4f} | "
                f"{c['p_bonferroni']:.3f} |"
            )
        lines += ["", "```json", json.dumps(report.get("multiplicity", {}), indent=2), "```"]
    return "\n".join(lines) + "\n"


def _refuse_live_root(out_dir: Path) -> Path:
    resolved = out_dir.resolve()
    if resolved == LIVE_DATA_ROOT.resolve() or LIVE_DATA_ROOT.resolve() in resolved.parents:
        raise ValueError(f"refusing to write into the live data root: {resolved}")
    return resolved


def write_outputs(out_dir: Path, report: Mapping[str, Any]) -> tuple[Path, Path]:
    """Write JSON and markdown under ``out_dir``; refuses the live data root."""
    resolved = _refuse_live_root(out_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    json_path, md_path = (
        resolved / "market_calibration_scan.json",
        resolved / "market_calibration_scan.md",
    )
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    md_path.write_text(_markdown(report))
    return json_path, md_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--truth", type=Path, default=DEFAULT_TRUTH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=B_RESAMPLES)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    _refuse_live_root(args.out)
    truth, last_day = load_truth(args.truth)
    collected = collect(args.catalog, truth, last_day)
    preview = build_report(collected, None)
    scan = (
        build_scan(collected.observations, resamples=args.resamples, seed=args.seed)
        if preview["status"] == "VALID"
        else None
    )
    report = build_report(collected, scan)
    json_path, _ = write_outputs(args.out, report)
    print(f"{report['status']} {json_path}")
    return 0 if report["status"] == "VALID" else 2


if __name__ == "__main__":
    sys.exit(main())
