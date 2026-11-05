"""M1: a model-free market calibration scan of the Polymarket.us weather ladder (FQ-R9, FQ-R14).

QUESTION. Is the venue's own price mispriced in any (window, side, ask-bin) cell, net of the venue
fee? Every rung, every station-day, YES and NO, with NO forecast model of any kind: the only inputs
are the recorder's Depth10 tape and the realised NWS CLI finals in ``settlement_truth.csv``.

SCREENING ONLY. This data never doubles as nomination evidence (FQ-R14): a cell that screens
positive becomes a hypothesis for FORWARD days after a freeze, nothing more. Read-only: no network,
no Nautilus runtime, no write outside ``--out``, never into the live data root.

READER. ``RecorderCatalogTape`` is the repo's sanctioned Depth10 reader; this scan adds none.

DEFINITIONS (pre-registered here; changing one is a new scan, not a tuned one)
  * Rung. Parsed by the adapter's ``symbology.parse_weather_slug`` + ``slug_closed_interval`` (no
    local grammar). A directory that does not parse, or whose bounds family is unobserved, is an
    INVALID reason; only a parsed ``low`` (non-HIGH) measure is a pre-registered exclusion.
  * Ask. YES ask = lowest Depth10 ask level with size >= 1. NO ask = ``1 - best YES bid`` over bid
    levels with size >= 1 (the venue represents a NO buy as a sell of the YES side,
    ``leg_prices.py``); a NO observation exists ONLY when that bid level exists, never synthesised.
    ``QuoteTick`` is never read: it cannot show an empty bid (L-35). An ask <= 0 or >= 1 is INVALID.
    The ask is the top level at size >= 1 with NO slippage and no fill probability, so a positive
    cell is an UPPER BOUND on a realisable edge.
  * Reference row. The FIRST Depth10 row whose ``ts_event`` lies inside a fixed one-hour UTC window,
    scoped by calendar date AND hour (``WINDOWS``). The windows are fixed UTC hours, pre-registered;
    local-time variants would be a new scan. A window with no row is counted, not invalid (a market
    can be unlisted).
  * Excess = ``hit - (ask + fee)``, ``fee = round_half_even(theta * ask * (1 - ask), 0.01)`` at
    the single theta ``EVIDENCED_FEE_THETA`` (pinned equal to the live take rule's ``fee_on_ask``
    in the tests). The cell statistic is the mean excess; n counts observations.
  * Bootstrap. Whole CALENDAR DAYS (the climate day, shared by all stations) are resampled with
    replacement (multinomial day weights); B and the seed are ``roi_bound``'s pinned values.
  * Multiplicity. Bonferroni over every tested cell, plus White's reality check and Hansen's
    consistent SPA p-value for the best cell, from one joint day resampling. Zero-variance cells
    (se == 0) cannot be tested: they are listed separately and excluded from the best-cell and
    max statistics, but still count in K.
  * Power. Per cell ``mde_bonferroni_80 = (z_{1-alpha/(2K)} + 0.84) * se``: the smallest true edge
    the scan detects at 80% power. A null result is NOT evidence of no edge below that scale.
  * Validity STOP. Join coverage below 95%, a failed look-ahead assert, or any counted invalid
    reason marks the output INVALID, and no cell table or conclusion is emitted.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from statistics import NormalDist, median
from typing import Any, Final, NamedTuple

import numpy as np

from breezy.adapters.polymarket_us.symbology import parse_weather_slug, slug_closed_interval
from breezy.analysis.capture_audit_tape import DEPTH_DIR, RecorderCatalogTape
from breezy.analysis.hypothesis_ledger import EVIDENCED_FEE_THETA
from breezy.settlement.roi_bound import B_RESAMPLES, SEED

__all__ = [
    "ASK_BIN_EDGES",
    "JOIN_COVERAGE_FLOOR",
    "THETA",
    "WINDOWS",
    "Cell",
    "Collected",
    "LookAheadError",
    "Observation",
    "RungSpec",
    "ScanResult",
    "TruthLoad",
    "TruthRow",
    "Window",
    "ask_bin",
    "assert_no_lookahead",
    "best_ask",
    "build_report",
    "build_scan",
    "collect",
    "load_truth",
    "load_truth_checked",
    "main",
    "no_ask",
    "parse_slug",
    "rung_outcome",
    "validity_reasons",
    "venue_fee",
    "write_outputs",
]

THETA: Final[Decimal] = Decimal(str(EVIDENCED_FEE_THETA))
_CENT: Final[Decimal] = Decimal("0.01")
_ONE: Final[Decimal] = Decimal(1)
_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3600 * _NS
_DAY_NS: Final[int] = 24 * _HOUR_NS
_VENUE_SUFFIX: Final[str] = ".POLYMARKET_US"
JOIN_COVERAGE_FLOOR: Final[float] = 0.95
MIN_CELL_N: Final[int] = 30
MIN_CELL_DAYS: Final[int] = 5
ALPHA: Final[float] = 0.05
Z_POWER_80: Final[float] = 0.84
#: A bootstrap se at or below this is a zero-variance cell (floating-point dust of equal values).
SE_ZERO: Final[float] = 1e-12
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
CAVEAT: Final[str] = (
    "Reads the converted data/ catalog only (L-20): unconverted live/ streams are not scanned. "
    "The ask is the best level at size >= 1 of the first Depth10 row in each window: no depth "
    "walk, no slippage, no fill probability, so a positive cell is an upper bound. Overlapping "
    "rungs of one station-day are dependent; the day-block bootstrap is the only clustering "
    "applied."
)

R_DEGENERATE: Final[str] = "degenerate_ask"
R_UNRECOGNISED: Final[str] = "unrecognised_directory"
R_CONFLICT: Final[str] = "conflicting_truth_rows"
R_NAIVE: Final[str] = "naive_issued_at_utc"


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


_NON_HIGH: Final[str] = "non_high"


def classify_directory(name: str) -> tuple[RungSpec | None, str]:
    """``(spec, "rung")``, ``(None, "non_high")`` (pre-registered exclusion) or
    ``(None, R_UNRECOGNISED)``. The grammar is the adapter's, never a local regex."""
    if not name.endswith(_VENUE_SUFFIX):
        return None, R_UNRECOGNISED
    weather = parse_weather_slug(name.removesuffix(_VENUE_SUFFIX))
    if weather is None:
        return None, R_UNRECOGNISED
    if weather.measure != "high":
        return None, _NON_HIGH
    interval = slug_closed_interval(weather.bounds)
    if interval is None:
        return None, R_UNRECOGNISED
    day = dt.date.fromisoformat(weather.climate_date)
    return RungSpec(weather.city.upper(), day, interval[0], interval[1]), "rung"


def parse_slug(name: str) -> RungSpec | None:
    """The rung of an instrument directory name, or None when it is not a HIGH temperature rung."""
    return classify_directory(name)[0]


def rung_outcome(spec: RungSpec, tmax_f: int) -> bool:
    """True when the settled high lies in the rung's CLOSED interval ``[lower, upper]``."""
    return (spec.lower is None or tmax_f >= spec.lower) and (
        spec.upper is None or tmax_f <= spec.upper
    )


def venue_fee(price: Decimal, theta: Decimal = THETA) -> Decimal:
    """``theta * p * (1 - p)`` for one contract, banker's-rounded to the cent (venue formula).

    Same arithmetic as the live take rule's ``fee_on_ask``; pinned equal on a grid in the tests
    (importing ``breezy.strategy`` here would pull a model into a model-free scan).
    """
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
    """The decile bin label of an ask in ``(0, 1)``."""
    index = sum(1 for edge in ASK_BIN_EDGES if float(ask) >= edge)
    lows = (0.0, *ASK_BIN_EDGES)
    highs = (*ASK_BIN_EDGES, 1.0)
    return f"{lows[index]:.1f}-{highs[index]:.1f}"


def _day_start_ns(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS


def window_bounds_ns(climate_day: dt.date, window: Window) -> tuple[int, int]:
    start = _day_start_ns(climate_day + dt.timedelta(days=window.day_offset))
    start += window.hour * _HOUR_NS
    return start, start + _HOUR_NS


def assert_no_lookahead(observation: Observation) -> None:
    """The reference must precede the settlement publication and the end of the climate day."""
    day_end = _day_start_ns(observation.climate_day) + _DAY_NS
    who = f"{observation.station} {observation.climate_day}"
    if observation.ref_ts_ns >= observation.settled_ns:
        raise LookAheadError(
            f"{who}: ref_ts {observation.ref_ts_ns} is not before settlement "
            f"{observation.settled_ns}"
        )
    if observation.ref_ts_ns >= day_end:
        raise LookAheadError(
            f"{who}: ref_ts {observation.ref_ts_ns} is not before the outcome observation "
            f"(climate day end {day_end})"
        )


@dataclass(frozen=True, slots=True)
class TruthLoad:
    rows: dict[tuple[str, dt.date], TruthRow]
    last_day: dt.date | None
    invalid_counts: dict[str, int]


def _parse_issued_ns(text: str) -> int | None:
    issued = dt.datetime.fromisoformat(text)
    return None if issued.tzinfo is None else int(issued.timestamp()) * _NS


def load_truth_checked(path: Path) -> TruthLoad:
    """FINAL CLI rows keyed by (station, climate day) plus counted invalid reasons.

    A naive ``issued_at_utc`` cannot anchor the look-ahead check (invalid, row dropped); two FINAL
    rows for one key that disagree on ``tmax_f`` are invalid (the later one is kept).
    """
    rows: dict[tuple[str, dt.date], TruthRow] = {}
    invalid: Counter[str] = Counter()
    with path.open(newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw["is_final"] != "True" or not raw["tmax_f"]:
                continue
            settled = _parse_issued_ns(raw["issued_at_utc"])
            if settled is None:
                invalid[R_NAIVE] += 1
                continue
            key = (raw["station"], dt.date.fromisoformat(raw["climate_day"]))
            row = TruthRow(int(raw["tmax_f"]), settled)
            kept = rows.get(key)
            if kept is not None and kept.tmax_f != row.tmax_f:
                invalid[R_CONFLICT] += 1
            if kept is None or row.settled_ns > kept.settled_ns:
                rows[key] = row
    last = max((day for _, day in rows), default=None)
    return TruthLoad(rows, last, dict(invalid))


def load_truth(path: Path) -> tuple[dict[tuple[str, dt.date], TruthRow], dt.date | None]:
    """:func:`load_truth_checked` without the invalid counts."""
    loaded = load_truth_checked(path)
    return loaded.rows, loaded.last_day


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
    windows_without_depth: int
    invalid_counts: Mapping[str, int]
    non_high_directories: int


@dataclass(slots=True)
class _Tally:
    obs: list[Observation] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    invalid: Counter[str] = field(default_factory=Counter)
    no_ask: int = 0
    no_bid: int = 0
    no_depth: int = 0
    non_high: int = 0


def _first_row(
    tape: RecorderCatalogTape, instrument: str, lo_ns: int, hi_ns: int
) -> Mapping[str, Any] | None:
    for row in tape.depth_rows(instrument, lo_ns, hi_ns):
        return row
    return None


def _index_directories(base: Path, tally: _Tally) -> dict[dt.date, list[tuple[str, RungSpec]]]:
    by_day: dict[dt.date, list[tuple[str, RungSpec]]] = defaultdict(list)
    for entry in sorted(base.iterdir()) if base.is_dir() else ():
        spec, kind = classify_directory(entry.name) if entry.is_dir() else (None, R_UNRECOGNISED)
        if spec is not None:
            by_day[spec.climate_day].append((entry.name, spec))
        elif kind == _NON_HIGH:
            tally.non_high += 1
        else:
            tally.invalid[kind] += 1
    return by_day


def _observe_row(
    name: str,
    spec: RungSpec,
    row: Mapping[str, Any],
    window: Window,
    found: TruthRow,
    tally: _Tally,
) -> None:
    """Append the YES and NO observations of one reference row (a degenerate ask is INVALID)."""
    ts = int(row["ts_event"])
    outcome = rung_outcome(spec, found.tmax_f)
    for side, ask, hit in (("YES", best_ask(row), outcome), ("NO", no_ask(row), not outcome)):
        if ask is None:
            if side == "YES":
                tally.no_ask += 1
            else:
                tally.no_bid += 1
        elif not 0 < ask < 1:
            tally.invalid[R_DEGENERATE] += 1
        else:
            candidate = Observation(
                spec.station,
                spec.climate_day,
                window.label,
                name.removesuffix(_VENUE_SUFFIX),
                side,
                ask,
                ts,
                found.settled_ns,
                hit,
            )
            try:
                assert_no_lookahead(candidate)
            except LookAheadError as exc:
                tally.failures.append(str(exc))
            tally.obs.append(candidate)


def _scan_day(
    catalog_root: Path,
    day: dt.date,
    members: Sequence[tuple[str, RungSpec]],
    truth: Mapping[tuple[str, dt.date], TruthRow],
    windows: Sequence[Window],
    tally: _Tally,
) -> None:
    names = frozenset(n for n, _ in members)
    tapes: dict[dt.date, RecorderCatalogTape] = {}
    for window in windows:
        lo, hi = window_bounds_ns(day, window)
        utc_day = day + dt.timedelta(days=window.day_offset)
        tape = tapes.setdefault(utc_day, RecorderCatalogTape(catalog_root, utc_day, names))
        for name, spec in members:
            row = _first_row(tape, name, lo, hi)
            if row is None:
                tally.no_depth += 1
            elif not lo <= int(row["ts_event"]) < hi:
                raise LookAheadError(f"{name}: row {row['ts_event']} escaped window {window.label}")
            else:
                _observe_row(name, spec, row, window, truth[(spec.station, day)], tally)


def collect(
    catalog_root: Path,
    truth: Mapping[tuple[str, dt.date], TruthRow],
    truth_last_day: dt.date | None,
    windows: Sequence[Window] = WINDOWS,
    *,
    truth_invalid: Mapping[str, int] | None = None,
) -> Collected:
    """Join the Depth10 tape to the truth. Reads ``order_book_depths`` only."""
    tally = _Tally()
    tally.invalid.update(truth_invalid or {})
    by_day = _index_directories(catalog_root / "data" / DEPTH_DIR, tally)
    tape_days = {(s.station, d) for d, items in by_day.items() for _, s in items}
    joined = {key for key in tape_days if key in truth}
    horizon = {key for key in tape_days if truth_last_day and key[1] <= truth_last_day}
    for day in sorted(by_day):
        members = [(n, s) for n, s in by_day[day] if (s.station, day) in truth]
        if members:
            _scan_day(catalog_root, day, members, truth, windows, tally)
    return Collected(
        tuple(tally.obs),
        len(tape_days),
        len(joined),
        len(horizon),
        len(horizon & joined),
        truth_last_day,
        tuple(tally.failures),
        tally.no_ask,
        tally.no_bid,
        tally.no_depth,
        dict(tally.invalid),
        tally.non_high,
    )


def excess(observation: Observation) -> float:
    cost = observation.ask + venue_fee(observation.ask)
    return float(Decimal(int(observation.hit)) - cost)


@dataclass(frozen=True, slots=True)
class Cell:
    window: str
    side: str
    ask_bin: str
    n: int
    n_days: int
    mean_excess: float
    ci95_lo: float
    ci95_hi: float
    p_one_sided: float
    p_bonferroni: float
    t_stat: float
    se: float
    mde_bonferroni_80: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "side": self.side,
            "ask_bin": self.ask_bin,
            "n": self.n,
            "n_days": self.n_days,
            "mean_excess": self.mean_excess,
            "ci95_lo": self.ci95_lo,
            "ci95_hi": self.ci95_hi,
            "p_one_sided": self.p_one_sided,
            "p_bonferroni": self.p_bonferroni,
            "t_stat": self.t_stat,
            "se": self.se,
            "mde_bonferroni_80": self.mde_bonferroni_80,
        }


@dataclass(frozen=True, slots=True)
class ZeroVarianceCell:
    window: str
    side: str
    ask_bin: str
    n: int
    n_days: int
    mean_excess: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "side": self.side,
            "ask_bin": self.ask_bin,
            "n": self.n,
            "n_days": self.n_days,
            "mean_excess": self.mean_excess,
        }


@dataclass(frozen=True, slots=True)
class ScanResult:
    cells: tuple[Cell, ...]
    multiplicity: dict[str, Any]
    n_days: int
    untested_cells: int
    zero_variance_cells: tuple[ZeroVarianceCell, ...] = ()


CellKey = tuple[str, str, str]


def _day_matrices(
    obs: Iterable[Observation], min_n: int, min_days: int
) -> tuple[list[CellKey], list[dt.date], np.ndarray, np.ndarray, int]:
    sums: dict[CellKey, dict[dt.date, list[float]]] = defaultdict(
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


class _Boot(NamedTuple):
    observed: np.ndarray
    centred: np.ndarray
    se: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    p_cell: np.ndarray
    pooled_se: float


def _bootstrap_stats(s_mat: np.ndarray, n_mat: np.ndarray, resamples: int, seed: int) -> _Boot:
    """Day-block bootstrap of every cell mean and of the pooled mean from one resampling."""
    n_days = s_mat.shape[0]
    rng = np.random.default_rng(seed)
    weights = rng.multinomial(n_days, np.full(n_days, 1.0 / n_days), size=resamples).astype(float)
    observed = s_mat.sum(axis=0) / n_mat.sum(axis=0)
    num, den = weights @ s_mat, weights @ n_mat
    boot = np.where(den > 0, num / np.where(den > 0, den, 1.0), observed)
    pooled_den = den.sum(axis=1)
    pooled_obs = s_mat.sum() / n_mat.sum()
    pooled = np.where(
        pooled_den > 0, num.sum(axis=1) / np.where(pooled_den > 0, pooled_den, 1.0), pooled_obs
    )
    lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
    return _Boot(
        observed,
        boot - observed,
        boot.std(axis=0, ddof=1),
        lo,
        hi,
        (1 + (boot <= 0).sum(axis=0)) / (resamples + 1),
        float(pooled.std(ddof=1)),
    )


def _max_tests(boot: _Boot, valid: np.ndarray, n_days: int, resamples: int) -> tuple[float, float]:
    """White's reality-check p and Hansen's consistent SPA p over the estimable cells only."""
    observed, centred, se = boot.observed[valid], boot.centred[:, valid], boot.se[valid]
    rc_p = float((1 + (centred.max(axis=1) >= observed.max()).sum()) / (resamples + 1))
    threshold = se * math.sqrt(2.0 * math.log(math.log(max(n_days, 3))))
    drift = np.where(observed <= -threshold, observed, 0.0)
    z_boot = ((centred + drift) / se).max(axis=1)
    t_obs = float(max((observed / se).max(), 0.0))
    spa_p = float((1 + (np.maximum(z_boot, 0.0) >= t_obs).sum()) / (resamples + 1))
    return rc_p, spa_p


def _cells(
    keys: Sequence[CellKey], boot: _Boot, n_mat: np.ndarray, valid: np.ndarray
) -> tuple[tuple[Cell, ...], tuple[ZeroVarianceCell, ...]]:
    k = len(keys)
    z = NormalDist().inv_cdf(1 - ALPHA / (2 * k))
    totals = n_mat.sum(axis=0)
    cells: list[Cell] = []
    flat: list[ZeroVarianceCell] = []
    for j, key in enumerate(keys):
        n, n_days = int(totals[j]), int((n_mat[:, j] > 0).sum())
        if not valid[j]:
            flat.append(ZeroVarianceCell(*key, n, n_days, float(boot.observed[j])))
            continue
        p = float(boot.p_cell[j])
        cells.append(
            Cell(
                *key,
                n,
                n_days,
                float(boot.observed[j]),
                float(boot.lo[j]),
                float(boot.hi[j]),
                p,
                min(1.0, p * k),
                float(boot.observed[j] / boot.se[j]),
                float(boot.se[j]),
                (z + Z_POWER_80) * float(boot.se[j]),
            )
        )
    return tuple(cells), tuple(flat)


def _multiplicity(
    cells: Sequence[Cell], boot: _Boot, valid: np.ndarray, k: int, n_days: int, seed: int
) -> dict[str, Any]:
    resamples = boot.centred.shape[0]
    out: dict[str, Any] = {
        "tested_cells": k,
        "estimable_cells": len(cells),
        "bonferroni_alpha_per_cell": ALPHA / k,
        "resamples": resamples,
        "seed": seed,
    }
    if not cells:
        return {
            **out,
            "best_cell_by_t": None,
            "reality_check_p": None,
            "spa_p": None,
            "any_cell_bonferroni_significant": False,
            "median_cell_mde_80": None,
            "pooled_mde_80": None,
        }
    rc_p, spa_p = _max_tests(boot, valid, n_days, resamples)
    best = max(cells, key=lambda c: c.t_stat)
    z_pooled = NormalDist().inv_cdf(1 - ALPHA / 2)
    return {
        **out,
        "best_cell_by_t": {"window": best.window, "side": best.side, "ask_bin": best.ask_bin},
        "best_cell_p_bonferroni": best.p_bonferroni,
        "reality_check_p": rc_p,
        "spa_p": spa_p,
        "any_cell_bonferroni_significant": any(c.p_bonferroni < ALPHA for c in cells),
        "median_cell_mde_80": median(c.mde_bonferroni_80 for c in cells),
        "pooled_mde_80": (z_pooled + Z_POWER_80) * boot.pooled_se,
    }


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
    boot = _bootstrap_stats(s_mat, n_mat, resamples, seed)
    valid = boot.se > SE_ZERO
    cells, flat = _cells(keys, boot, n_mat, valid)
    mult = _multiplicity(cells, boot, valid, len(keys), len(days), seed)
    return ScanResult(cells, mult, len(days), untested, flat)


def _coverage(collected: Collected) -> tuple[float, float]:
    horizon = collected.horizon_station_days
    coverage = collected.horizon_joined_station_days / horizon if horizon else 0.0
    tape = collected.tape_station_days
    return coverage, (collected.joined_station_days / tape if tape else 0.0)


def validity_reasons(collected: Collected, *, floor: float = JOIN_COVERAGE_FLOOR) -> list[str]:
    """Every reason the run is INVALID; empty means VALID. Computed once per run."""
    coverage, _ = _coverage(collected)
    reasons: list[str] = []
    if coverage < floor:
        reasons.append(f"join_coverage {coverage:.4f} < {floor}")
    if collected.lookahead_failures:
        reasons.append(f"{len(collected.lookahead_failures)} look-ahead assert failure(s)")
    reasons += [f"{name}: {count}" for name, count in sorted(collected.invalid_counts.items())]
    return reasons


def _join_report(collected: Collected) -> dict[str, Any]:
    coverage, raw = _coverage(collected)
    last = collected.truth_last_day
    return {
        "validity_metric": "horizon",
        "horizon": coverage,
        "horizon_note": "tape station-days with climate_day <= last FINAL truth day that "
        "have truth / all such tape station-days",
        "all_tape_station_days": raw,
        "tape_station_days": collected.tape_station_days,
        "joined_station_days": collected.joined_station_days,
        "horizon_station_days": collected.horizon_station_days,
        "horizon_joined_station_days": collected.horizon_joined_station_days,
        "truth_last_day": None if last is None else last.isoformat(),
    }


def _conclusion(scan: ScanResult) -> str:
    mult = scan.multiplicity
    median_mde = mult.get("median_cell_mde_80")
    if median_mde is None:
        return (
            "SCREENING ONLY: no cell was estimable, so nothing was tested; a null here is NOT "
            "evidence of no edge."
        )
    scale = (
        f"the scan can detect only edges >= {median_mde * 100:.1f}c (median per-cell MDE at 80% "
        f"power, Bonferroni; pooled MDE {mult['pooled_mde_80'] * 100:.1f}c)"
    )
    if mult["any_cell_bonferroni_significant"]:
        return f"SCREENING ONLY: a cell survives Bonferroni; {scale}; no nomination from this data."
    return (
        f"SCREENING ONLY: no cell survives Bonferroni; {scale} - a null here is NOT evidence of "
        "no edge."
    )


def build_report(
    collected: Collected,
    scan: ScanResult | None,
    *,
    floor: float = JOIN_COVERAGE_FLOOR,
    reasons: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The JSON report. INVALID carries reasons only: no cell table, no conclusion."""
    found = list(validity_reasons(collected, floor=floor) if reasons is None else reasons)
    report: dict[str, Any] = {
        "kind": "market_calibration_scan/v2",
        "notice": SCREENING_NOTICE,
        "status": "INVALID" if found else "VALID",
        "invalid_reasons": found,
        "join_coverage": _join_report(collected),
        "windows": [
            {"label": w.label, "day_offset": w.day_offset, "hour_utc": w.hour} for w in WINDOWS
        ],
        "theta": str(THETA),
        "observations": len(collected.observations),
        "windows_without_depth": collected.windows_without_depth,
        "non_high_directories": collected.non_high_directories,
        "skipped": {
            "no_yes_ask": collected.skipped_no_ask,
            "no_bid_side_for_no_ask": collected.skipped_no_bid_side,
        },
        "caveat": CAVEAT,
    }
    if not found and scan is not None:
        report.update(
            n_days=scan.n_days,
            untested_cells=scan.untested_cells,
            cells=[c.to_dict() for c in scan.cells],
            zero_variance_cells=[c.to_dict() for c in scan.zero_variance_cells],
            multiplicity=scan.multiplicity,
            conclusion=_conclusion(scan),
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
        f"- Windows without a Depth10 row: {report['windows_without_depth']}",
        f"- {report['caveat']}",
    ]
    if report["status"] == "VALID":
        lines += ["", f"**{report.get('conclusion', '')}**", ""]
        lines += [
            (
                "| window | side | ask bin | n | days | mean excess | CI95 lo | CI95 hi | "
                "p (Bonf.) | MDE80 |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for c in sorted(report.get("cells", []), key=lambda c: -c["t_stat"]):
            lines.append(
                f"| {c['window']} | {c['side']} | {c['ask_bin']} | {c['n']} | {c['n_days']} | "
                f"{c['mean_excess']:+.4f} | {c['ci95_lo']:+.4f} | {c['ci95_hi']:+.4f} | "
                f"{c['p_bonferroni']:.3f} | {c['mde_bonferroni_80']:.4f} |"
            )
        flat = report.get("zero_variance_cells", [])
        lines += [f"- Zero-variance (untestable) cells: {len(flat)}"]
        lines += [f"  - {c['window']} {c['side']} {c['ask_bin']} n={c['n']}" for c in flat]
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
    loaded = load_truth_checked(args.truth)
    collected = collect(
        args.catalog, loaded.rows, loaded.last_day, truth_invalid=loaded.invalid_counts
    )
    reasons = validity_reasons(collected)
    scan = (
        None
        if reasons
        else build_scan(collected.observations, resamples=args.resamples, seed=args.seed)
    )
    report = build_report(collected, scan, reasons=reasons)
    json_path, _ = write_outputs(args.out, report)
    print(f"{report['status']} {json_path}")
    return 0 if report["status"] == "VALID" else 2


if __name__ == "__main__":
    sys.exit(main())
