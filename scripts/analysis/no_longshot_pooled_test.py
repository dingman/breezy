"""M1-v3: a pre-registered FORWARD screen of buying NO at an ask >= 0.90 (Lane E, AS-R6).

Plan: docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/M1v3-no-longshot-forward-screen_plan.md
(r1 < r2 < r3 < r3.1; rulings M1V3-R1..R18). Model-free: the only inputs are the recorder's
Depth10 tape and the NWS CLI finals. Venue prices are execution cost only. The output never enters
model-variant evidence; a WINNER verdict nominates an execution-side admissibility filter on top of
a weather-sourced NO decision, never a standalone signal. Read-only: no network, no Nautilus
runtime, no write anywhere near the live data root.

HOW IT REUSES M1 (``market_calibration_scan``, unchanged)
  * ``collect`` is called ONCE per forward climate day with ``truth`` restricted to that day and
    ``windows=(D_12Z,)`` (R14); the first Depth10 row in [12:00, 13:00) UTC is the reference.
  * The bootstrap is M1's ``_bootstrap_stats`` on a day x 1 matrix built HERE from the R4 primary
    cost (R13): M1's ``excess`` / ``_day_matrices`` (rounded fee, no slippage) are never used.

FREEZE (R8). The tool refuses to produce a verdict unless ``frozen_sha`` is a real commit that is an
ancestor of HEAD and the PREREG blob equals the one committed there (``check_frozen_blob``). The
first forward day is DERIVED from git (UTC committer date of ``frozen_sha`` + 1 day, R18).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
import warnings
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

import numpy as np
from scipy import stats as scipy_stats

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.capture_audit_tape import DEPTH_DIR, RecorderCatalogTape
from breezy.settlement.roi_bound import B_RESAMPLES, SEED
from scripts.analysis import market_calibration_scan as m1
from scripts.analysis.prereg_precommit_check import (
    _canonical,
    _git,
    check_frozen_blob,
)

__all__ = [
    "SEED",
    "THETA",
    "Pooled",
    "Refusal",
    "Take",
    "ask_bin_table",
    "check_pins",
    "decide",
    "fee",
    "m1",
    "main",
    "net_ev",
    "per_ladder",
    "pool",
    "run_screen",
    "select_takes",
]

THETA: Final[Decimal] = m1.THETA
PRIMARY_WINDOW: Final[m1.Window] = next(w for w in m1.WINDOWS if w.label == "D_12Z")
SENSITIVITY_WINDOWS: Final[tuple[m1.Window, ...]] = tuple(
    w for w in m1.WINDOWS if w.label != PRIMARY_WINDOW.label
)
THRESHOLD: Final[Decimal] = Decimal("0.90")
BAND_TOP: Final[Decimal] = Decimal("0.97")
SLIPPAGE: Final[Decimal] = Decimal("0.01")
ALPHA: Final[float] = 0.05
LOWER_PERCENTILE: Final[float] = 100.0 * ALPHA
K_LOOKS: Final[int] = 1
MIN_TAKES: Final[int] = 620
MIN_DAYS: Final[int] = 40
MIN_LOSS_DAYS: Final[int] = 5
READ_OFFSET_DAYS: Final[int] = 61
DEPTH_MIN_CONTRACTS: Final[Decimal] = Decimal(10)
UNFROZEN: Final[str] = "UNFROZEN"
FIRST_FORWARD_RULE: Final[str] = "utc_committer_date(frozen_sha)+1d"
REPORT_NAME: Final[str] = "no_longshot_report.json"
DEFAULT_PREREG: Final[Path] = _REPO_ROOT / "docs" / "evidence" / "m1v3" / "PREREG.json"
DEFAULT_OUT: Final[Path] = DEFAULT_PREREG.parent
EXIT_OK: Final[int] = 0
EXIT_INVALID: Final[int] = 2
EXIT_REFUSED: Final[int] = 3
#: Ask bins (R4 composition table): half-open ``[lo, hi)`` on the ask.
_ASK_BINS: Final[tuple[tuple[str, Decimal, Decimal], ...]] = (
    ("0.90-0.92", Decimal("0.90"), Decimal("0.93")),
    ("0.93-0.95", Decimal("0.93"), Decimal("0.96")),
    ("0.96-0.99", Decimal("0.96"), Decimal(1)),
)
NOTICE: Final[str] = (
    "Lane E execution-structure screen (AS-R6): model-free, never model-variant evidence, never "
    "read by screen.py. A WINNER nominates only an execution-side admissibility filter applied on "
    "top of a weather-sourced NO decision. The venue nets a NO holding as short YES; the scan is "
    "execution-blind. Expected outcome (pre-registered): NO-EDGE or UNDERPOWERED."
)


class Refusal(Exception):
    """The tool refuses to run (unfrozen or tampered prereg, drifted pin, live-root output)."""


# --------------------------------------------------------------------------- cost and takes


@dataclass(frozen=True, slots=True)
class Take:
    station: str
    day: dt.date
    rung: str
    ask: Decimal
    hit: bool
    ref_ts_ns: int
    depth: Decimal | None = None


def fee(ask: Decimal, mode: str = "primary") -> Decimal:
    """Per-contract fee at ``ask``: ``primary`` = max(rounded, unrounded) (R4); the others are
    sensitivities. The rounded fee is zero for asks >= ~0.93, which could decide the verdict."""
    if mode == "rounded":
        return m1.venue_fee(ask)
    unrounded = THETA * ask * (Decimal(1) - ask)
    if mode == "unrounded":
        return unrounded
    if mode == "primary":
        return max(m1.venue_fee(ask), unrounded)
    raise ValueError(f"unknown fee mode {mode!r}")


def net_ev(
    ask: Decimal, hit: bool, *, fee_mode: str = "primary", slippage: Decimal = SLIPPAGE
) -> Decimal:
    """``hit - (ask + fee + slippage)`` for one contract."""
    return Decimal(int(hit)) - (ask + fee(ask, fee_mode) + slippage)


def select_takes(
    observations: Iterable[m1.Observation], *, window: str = PRIMARY_WINDOW.label
) -> list[Take]:
    """NO observations of ``window`` with ask >= 0.90 (inclusive)."""
    return [
        Take(o.station, o.climate_day, o.rung, o.ask, o.hit, o.ref_ts_ns)
        for o in observations
        if o.side == "NO" and o.window == window and o.ask >= THRESHOLD
    ]


# --------------------------------------------------------------------------- statistics


@dataclass(frozen=True, slots=True)
class Pooled:
    n_takes: int
    n_days: int
    loss_days: int
    n_losses: int
    loss_rate: float
    mean: float | None
    lb_primary: float | None
    lb_bca: float | None
    p_cell: float | None


def _matrices(
    takes: Iterable[Take], days: Sequence[dt.date], fee_mode: str, slippage: Decimal
) -> tuple[np.ndarray, np.ndarray]:
    index = {d: i for i, d in enumerate(sorted(set(days)))}
    s_mat = np.zeros((len(index), 1))
    n_mat = np.zeros((len(index), 1))
    for t in takes:
        if t.day not in index:
            raise ValueError(f"take on {t.day} is outside the day vector")
        s_mat[index[t.day], 0] += float(net_ev(t.ask, t.hit, fee_mode=fee_mode, slippage=slippage))
        n_mat[index[t.day], 0] += 1.0
    return s_mat, n_mat


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _bca_lower(s_mat: np.ndarray, n_mat: np.ndarray, resamples: int, seed: int) -> float | None:
    def ratio(s: np.ndarray, n: np.ndarray, axis: int = -1) -> Any:
        return s.sum(axis=axis) / n.sum(axis=axis)

    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        try:
            result = scipy_stats.bootstrap(
                (s_mat[:, 0], n_mat[:, 0]),
                ratio,
                paired=True,
                vectorized=True,
                method="BCa",
                alternative="greater",
                confidence_level=1.0 - ALPHA,
                n_resamples=resamples,
                rng=np.random.default_rng(seed),
            )
        except ValueError:
            return None
    return _finite(float(result.confidence_interval.low))


def _primary_bound(
    s_mat: np.ndarray, n_mat: np.ndarray, resamples: int, seed: int
) -> tuple[float, float, float]:
    """``(observed, lower bound, p_cell)`` from M1's day-block draws (R12): the lower bound is
    ``observed + percentile(centred, 5)``, never M1's 2.5th-percentile ``lo``."""
    boot = m1._bootstrap_stats(s_mat, n_mat, resamples, seed)
    observed = float(boot.observed[0])
    lower = observed + float(np.percentile(boot.centred[:, 0], LOWER_PERCENTILE))
    return observed, lower, float(boot.p_cell[0])


def pool(
    takes: Sequence[Take],
    days: Sequence[dt.date],
    *,
    resamples: int = B_RESAMPLES,
    seed: int = SEED,
    fee_mode: str = "primary",
    slippage: Decimal = SLIPPAGE,
) -> Pooled:
    """Ratio-of-sums mean net EV per take over the whole-day vector ``days`` (zero days stay)."""
    s_mat, n_mat = _matrices(takes, days, fee_mode, slippage)
    losses = [t for t in takes if not t.hit]
    n_takes = len(takes)
    loss_rate = len(losses) / n_takes if n_takes else 0.0
    base = (n_takes, len(set(days)), len({t.day for t in losses}), len(losses), loss_rate)
    if not n_takes:
        return Pooled(*base, None, None, None, None)
    observed, lower, p_cell = _primary_bound(s_mat, n_mat, resamples, seed)
    return Pooled(
        *base, _finite(observed), _finite(lower), _bca_lower(s_mat, n_mat, resamples, seed), p_cell
    )


def _positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def decide(pooled: Pooled) -> str:
    """UNDERPOWERED when any floor is unmet, else WINNER iff BOTH lower bounds are > 0."""
    if pooled.n_takes < MIN_TAKES or pooled.n_days < MIN_DAYS or pooled.loss_days < MIN_LOSS_DAYS:
        return "UNDERPOWERED"
    if _positive(pooled.lb_primary) and _positive(pooled.lb_bca):
        return "WINNER"
    return "NO-EDGE"


def ask_bin_table(takes: Sequence[Take]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, lo, hi in _ASK_BINS:
        members = [t for t in takes if lo <= t.ask < hi]
        total = sum((net_ev(t.ask, t.hit) for t in members), Decimal(0))
        rows.append(
            {
                "bin": label,
                "n": len(members),
                "n_losses": sum(1 for t in members if not t.hit),
                "mean": float(total / len(members)) if members else None,
            }
        )
    return rows


def per_ladder(
    takes: Sequence[Take], days: Sequence[dt.date], *, resamples: int = B_RESAMPLES
) -> dict[str, Any]:
    """Secondary: one value per (station, day) ladder (its mean net EV), day-block bootstrapped.
    Within a ladder at most one rung loses (mutually exclusive rungs)."""
    ladders: dict[tuple[str, dt.date], list[Take]] = defaultdict(list)
    for t in takes:
        ladders[(t.station, t.day)].append(t)
    index = {d: i for i, d in enumerate(sorted(set(days)))}
    s_mat = np.zeros((len(index), 1))
    n_mat = np.zeros((len(index), 1))
    for (_station, day), members in ladders.items():
        s_mat[index[day], 0] += sum(float(net_ev(t.ask, t.hit)) for t in members) / len(members)
        n_mat[index[day], 0] += 1.0
    out: dict[str, Any] = {
        "n_ladders": len(ladders),
        "ladders_with_loss": sum(1 for m in ladders.values() if any(not t.hit for t in m)),
        "ladders_with_multiple_losses": sum(
            1 for m in ladders.values() if sum(1 for t in m if not t.hit) > 1
        ),
        "mean": None,
        "lb_primary": None,
    }
    if ladders:
        observed, lower, _p = _primary_bound(s_mat, n_mat, resamples, SEED)
        out.update(mean=_finite(observed), lb_primary=_finite(lower))
    return out


# --------------------------------------------------------------------------- freeze and pins


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def check_pins(design: Mapping[str, Any]) -> list[str]:
    """Every pinned value that is missing from, or differs from, the tool's imported constants."""
    decimals: dict[str, Decimal] = {
        "theta": THETA,
        "slippage": SLIPPAGE,
        "ask_threshold": THRESHOLD,
    }
    exact: dict[str, Any] = {
        "window": PRIMARY_WINDOW.label,
        "bootstrap_B": B_RESAMPLES,
        "bootstrap_seed": SEED,
        "alpha": ALPHA,
        "K": K_LOOKS,
        "min_takes": MIN_TAKES,
        "min_days": MIN_DAYS,
        "min_loss_days": MIN_LOSS_DAYS,
        "read_offset_days": READ_OFFSET_DAYS,
        "ask_threshold_inclusive": True,
    }
    problems: list[str] = []
    for key, want in decimals.items():
        if key not in design:
            problems.append(f"{key}: missing from the prereg")
        elif _dec(design[key]) != want:
            problems.append(f"{key}: prereg {design[key]!r} != tool constant {want}")
    for key, expected in exact.items():
        if key not in design:
            problems.append(f"{key}: missing from the prereg")
        elif design[key] != expected or type(design[key]) is not type(expected):
            problems.append(f"{key}: prereg {design[key]!r} != tool constant {expected!r}")
    return problems


@dataclass(frozen=True, slots=True)
class Freeze:
    sha: str
    committer_date: dt.date
    epoch_ns: int
    first_forward_day: dt.date


def derive_freeze(sha: str, cwd: Path) -> Freeze:
    """First forward day = UTC committer date of ``sha`` + 1 (R18); never read from the JSON."""
    done = _git(cwd, "show", "-s", "--format=%cI|%ct", sha)
    if done.returncode != 0:
        raise Refusal(f"cannot read the freeze commit {sha}: {done.stderr.strip()}")
    iso, epoch = done.stdout.strip().split("|")
    committed = dt.datetime.fromisoformat(iso).astimezone(dt.UTC).date()
    return Freeze(sha, committed, int(epoch) * m1._NS, committed + dt.timedelta(days=1))


def _check_first_forward(design: Mapping[str, Any], derived: dt.date) -> None:
    pinned = design.get("first_forward_day", FIRST_FORWARD_RULE)
    if pinned == FIRST_FORWARD_RULE:
        return
    try:
        stated = dt.date.fromisoformat(str(pinned))
    except ValueError:
        stated = None
    if stated != derived:
        raise Refusal(
            f"first_forward_day {pinned!r} in the prereg disagrees with git ({derived}); "
            "the value is derived from the freeze commit, never trusted from JSON"
        )


def _load_verified_design(prereg: Path) -> tuple[Mapping[str, Any], Freeze]:
    design = json.loads(prereg.read_text(encoding="utf-8"))
    if not isinstance(design, Mapping):
        raise Refusal(f"{prereg}: the prereg must be a JSON object")
    sha = design.get("frozen_sha")
    if sha == UNFROZEN:
        raise Refusal("frozen_sha is UNFROZEN: the draft prereg has not been frozen; no verdict")
    defects = check_frozen_blob(prereg, design)
    if defects:
        raise Refusal("; ".join(f"[{d.code}] {d.message}" for d in defects))
    problems = check_pins(design)
    if problems:
        raise Refusal("pin check failed: " + "; ".join(problems))
    freeze = derive_freeze(str(sha), prereg.resolve().parent)
    _check_first_forward(design, freeze.first_forward_day)
    return design, freeze


def _refuse_live(out_dir: Path) -> Path:
    try:
        return m1._refuse_live_root(out_dir)
    except ValueError as exc:
        raise Refusal(str(exc)) from exc


# --------------------------------------------------------------------------- population


@dataclass(frozen=True, slots=True)
class DayRecord:
    day: dt.date
    takes: int
    no_obs: int
    no_bid_side: int
    windows_without_depth: int
    station_days_used: int
    station_days_excluded: int


@dataclass(slots=True)
class Gathered:
    takes: list[Take] = field(default_factory=list)
    days: list[dt.date] = field(default_factory=list)
    records: list[DayRecord] = field(default_factory=list)
    excluded_days: list[dt.date] = field(default_factory=list)
    excluded_station_days: int = 0
    pre_freeze_refs_dropped: int = 0
    reasons: list[str] = field(default_factory=list)


def _collect(
    catalog: Path,
    rows: Mapping[tuple[str, dt.date], m1.TruthRow],
    day: dt.date,
    window: m1.Window,
    out: Gathered,
) -> m1.Collected | None:
    try:
        return m1.collect(catalog, rows, day, windows=(window,))
    except m1.LookAheadError as exc:
        out.reasons.append(f"look-ahead raise on {day}: {exc}")
        return None


def _validity(collected: m1.Collected, day: dt.date, out: Gathered) -> None:
    if collected.lookahead_failures:
        out.reasons.append(
            f"{len(collected.lookahead_failures)} look-ahead assert failure(s) on {day}"
        )
    out.reasons.extend(
        f"{name}: {n} on {day}" for name, n in sorted(collected.invalid_counts.items())
    )


def _usable_parts(
    catalog: Path,
    day_truth: Mapping[tuple[str, dt.date], m1.TruthRow],
    day: dt.date,
    window: m1.Window,
    first: m1.Collected,
    out: Gathered,
) -> tuple[list[m1.Collected], int, int]:
    """``(collections to keep, station-days used, station-days excluded)``. A station-day is
    excluded whole when ANY of its listed rungs lacks Depth10 in the window (R14)."""
    if not first.windows_without_depth:
        return [first], first.joined_station_days, 0
    kept: list[m1.Collected] = []
    excluded = 0
    for station in sorted({s for s, _d in day_truth}):
        sub = {k: v for k, v in day_truth.items() if k[0] == station}
        part = _collect(catalog, sub, day, window, out)
        if part is None:
            return [], 0, 0
        _validity(part, day, out)
        if part.windows_without_depth:
            excluded += part.joined_station_days
        else:
            kept.append(part)
    return kept, sum(p.joined_station_days for p in kept), excluded


def gather(
    catalog: Path,
    truth: Mapping[tuple[str, dt.date], m1.TruthRow],
    forward_days: Sequence[dt.date],
    window: m1.Window,
    freeze: Freeze,
    *,
    strict: bool,
) -> Gathered:
    """One ``collect`` per forward climate day, truth restricted to that day (R14). ``strict``
    (the primary window) turns a reference row at or before the freeze into an INVALID reason; a
    labelled sensitivity window drops and counts it instead."""
    out = Gathered()
    for day in forward_days:
        day_truth = {k: v for k, v in truth.items() if k[1] == day}
        first = _collect(catalog, day_truth, day, window, out)
        if first is None:
            return out
        _validity(first, day, out)
        parts, used, excluded = _usable_parts(catalog, day_truth, day, window, first, out)
        out.excluded_station_days += excluded
        if out.reasons and not parts:
            return out
        if not used:
            out.excluded_days.append(day)
            continue
        observations = [o for p in parts for o in p.observations]
        takes: list[Take] = []
        for take in select_takes(observations, window=window.label):
            if take.ref_ts_ns > freeze.epoch_ns:
                takes.append(take)
            elif strict:
                out.reasons.append(f"ref_ts {take.ref_ts_ns} is not after the freeze commit time")
            else:
                out.pre_freeze_refs_dropped += 1
        out.days.append(day)
        out.takes.extend(takes)
        out.records.append(
            DayRecord(
                day,
                len(takes),
                sum(1 for o in observations if o.side == "NO"),
                sum(p.skipped_no_bid_side for p in parts),
                first.windows_without_depth,
                used,
                excluded,
            )
        )
    return out


def attach_depth(catalog: Path, takes: Sequence[Take], window: m1.Window) -> list[Take]:
    """Descriptive: contracts resting at the first-row best YES bid behind each NO take."""
    by_day: dict[dt.date, list[Take]] = defaultdict(list)
    for t in takes:
        by_day[t.day].append(t)
    result: list[Take] = []
    for day, members in sorted(by_day.items()):
        names = {t.rung + m1._VENUE_SUFFIX for t in members}
        utc_day = day + dt.timedelta(days=window.day_offset)
        tape = RecorderCatalogTape(catalog, utc_day, frozenset(names))
        lo, hi = m1.window_bounds_ns(day, window)
        for t in members:
            row = m1._first_row(tape, t.rung + m1._VENUE_SUFFIX, lo, hi)
            bids = m1._levels(row, "bids") if row is not None else []
            best = max((p for p, _s in bids), default=None)
            depth = sum((s for p, s in bids if p == best), Decimal(0)) if bids else None
            result.append(replace(t, depth=depth))
    return result


def _depth_report(takes: Sequence[Take]) -> dict[str, Any]:
    known = [t for t in takes if t.depth is not None]
    deep = sum(1 for t in known if t.depth is not None and t.depth >= DEPTH_MIN_CONTRACTS)
    return {
        "min_contracts": int(DEPTH_MIN_CONTRACTS),
        "n_known": len(known),
        "share_ge_10": deep / len(known) if known else None,
        "note": "descriptive only; a fixed constant unrelated to any operator cap",
    }


# --------------------------------------------------------------------------- report


def _pooled_dict(p: Pooled) -> dict[str, Any]:
    return {
        "n_takes": p.n_takes,
        "n_days": p.n_days,
        "loss_days": p.loss_days,
        "mean": p.mean,
        "lb_primary": p.lb_primary,
        "lb_bca": p.lb_bca,
    }


def _population(forward_days: Sequence[dt.date], g: Gathered) -> dict[str, Any]:
    return {
        "forward_days_with_truth": len(forward_days),
        "n_days": len(g.days),
        "excluded_days": [d.isoformat() for d in g.excluded_days],
        "excluded_station_days": g.excluded_station_days,
        "skipped_no_bid_side": sum(r.no_bid_side for r in g.records),
        "windows_without_depth": sum(r.windows_without_depth for r in g.records),
        "pre_freeze_refs_dropped": g.pre_freeze_refs_dropped,
        "per_day": [
            {
                "day": r.day.isoformat(),
                "takes": r.takes,
                "no_observations": r.no_obs,
                "no_bid_side": r.no_bid_side,
                "windows_without_depth": r.windows_without_depth,
                "station_days_used": r.station_days_used,
                "station_days_excluded": r.station_days_excluded,
            }
            for r in g.records
        ],
    }


def _counts(takes: Sequence[Take], days: Sequence[dt.date]) -> dict[str, Any]:
    losses = [t for t in takes if not t.hit]
    return {
        "n_takes": len(takes),
        "n_days": len(set(days)),
        "loss_days": len({t.day for t in losses}),
        "n_losses": len(losses),
        "loss_rate": len(losses) / len(takes) if takes else 0.0,
    }


def _sensitivities(
    takes: Sequence[Take], days: Sequence[dt.date], resamples: int
) -> dict[str, Any]:
    cases: dict[str, tuple[Sequence[Take], str, Decimal]] = {
        "rounded_fee_only": (takes, "rounded", SLIPPAGE),
        "unrounded_fee_only": (takes, "unrounded", SLIPPAGE),
        "slippage_0c": (takes, "primary", Decimal(0)),
        "slippage_2c": (takes, "primary", Decimal("0.02")),
        "ask_0.90-0.97": ([t for t in takes if t.ask <= BAND_TOP], "primary", SLIPPAGE),
    }
    return {
        name: _pooled_dict(pool(subset, days, resamples=resamples, fee_mode=mode, slippage=slip))
        for name, (subset, mode, slip) in cases.items()
    }


def _window_sensitivities(
    catalog: Path,
    truth: Mapping[tuple[str, dt.date], m1.TruthRow],
    forward_days: Sequence[dt.date],
    freeze: Freeze,
    resamples: int,
    reasons: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for window in SENSITIVITY_WINDOWS:
        g = gather(catalog, truth, forward_days, window, freeze, strict=False)
        reasons.extend(g.reasons)
        out[window.label] = {
            **_pooled_dict(pool(g.takes, g.days, resamples=resamples)),
            "pre_freeze_refs_dropped": g.pre_freeze_refs_dropped,
            "label": "sensitivity only; windows are never summed",
        }
    return out


def _catalog_day_digest(catalog: Path) -> str:
    by_day = m1._index_directories(catalog / "data" / DEPTH_DIR, m1._Tally())
    return hashlib.sha256("\n".join(d.isoformat() for d in sorted(by_day)).encode()).hexdigest()


def _head_sha(cwd: Path) -> str:
    done = _git(cwd, "rev-parse", "HEAD")
    return done.stdout.strip() if done.returncode == 0 else "UNKNOWN"


def write_report(out_dir: Path, report: Mapping[str, Any]) -> Path:
    resolved = _refuse_live(out_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    path = resolved / REPORT_NAME
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path


def _read_branch(
    report: dict[str, Any],
    primary: Gathered,
    catalog: Path,
    truth: Mapping[tuple[str, dt.date], m1.TruthRow],
    forward_days: Sequence[dt.date],
    freeze: Freeze,
    resamples: int,
) -> None:
    pooled = pool(primary.takes, primary.days, resamples=resamples)
    reasons: list[str] = []
    windows = _window_sensitivities(catalog, truth, forward_days, freeze, resamples, reasons)
    if reasons:
        report.update(status="INVALID", verdict="INVALID", invalid_reasons=sorted(set(reasons)))
        return
    report.update(
        status="READ",
        verdict=decide(pooled),
        stats={
            "mean": pooled.mean,
            "lb_primary": pooled.lb_primary,
            "lb_bca": pooled.lb_bca,
            "p_cell": pooled.p_cell,
            "alpha": ALPHA,
            "note": "p_cell is reported by analogy to FQ-R27 at K=1; it is not Hansen SPA",
        },
        floors={
            "min_takes": MIN_TAKES,
            "min_days": MIN_DAYS,
            "min_loss_days": MIN_LOSS_DAYS,
            "met": {
                "takes": pooled.n_takes >= MIN_TAKES,
                "days": pooled.n_days >= MIN_DAYS,
                "loss_days": pooled.loss_days >= MIN_LOSS_DAYS,
            },
        },
        ask_bins=ask_bin_table(primary.takes),
        per_ladder=per_ladder(primary.takes, primary.days, resamples=resamples),
        sensitivities=_sensitivities(primary.takes, primary.days, resamples),
        window_sensitivities=windows,
    )


def run_screen(
    *,
    prereg: Path,
    catalog: Path,
    truth: Path,
    out_dir: Path | None,
    as_of: dt.date,
    resamples: int = B_RESAMPLES,
) -> tuple[dict[str, Any], int]:
    """Run the screen. Raises ``Refusal`` (exit 3, no verdict) on any freeze or output defect;
    returns ``(report, exit code)`` otherwise (INVALID exits 2)."""
    if out_dir is not None:
        _refuse_live(out_dir)
    design, freeze = _load_verified_design(prereg)
    loaded = m1.load_truth_checked(truth)
    forward_days = sorted({d for _s, d in loaded.rows if d >= freeze.first_forward_day})
    primary = gather(catalog, loaded.rows, forward_days, PRIMARY_WINDOW, freeze, strict=True)
    reasons = [f"truth: {name}: {n}" for name, n in sorted(loaded.invalid_counts.items())]
    reasons += primary.reasons
    read_date = freeze.first_forward_day + dt.timedelta(days=READ_OFFSET_DAYS)
    primary.takes = attach_depth(catalog, primary.takes, PRIMARY_WINDOW) if not reasons else []
    report: dict[str, Any] = {
        "kind": "m1v3_no_longshot_forward_screen/report",
        "notice": NOTICE,
        "frozen_sha": freeze.sha,
        "head_sha": _head_sha(prereg.resolve().parent),
        "prereg_canonical_sha256": hashlib.sha256(_canonical(design).encode()).hexdigest(),
        "truth_sha256": hashlib.sha256(truth.read_bytes()).hexdigest(),
        "catalog_day_list_sha256": _catalog_day_digest(catalog),
        "first_forward_day": freeze.first_forward_day.isoformat(),
        "read_date": read_date.isoformat(),
        "as_of": as_of.isoformat(),
        "window": PRIMARY_WINDOW.label,
        "population": _population(forward_days, primary),
        "counts": _counts(primary.takes, primary.days),
        "invalid_reasons": sorted(set(reasons)),
    }
    if reasons:
        report.update(status="INVALID", verdict="INVALID")
    elif as_of < read_date:
        report.update(status="PROGRESS")
    else:
        _read_branch(report, primary, catalog, loaded.rows, forward_days, freeze, resamples)
    if report["status"] != "INVALID":
        report["depth"] = _depth_report(primary.takes)
    code = EXIT_INVALID if report["status"] == "INVALID" else EXIT_OK
    if out_dir is not None:
        write_report(out_dir, report)
    return report, code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--prereg", type=Path, default=DEFAULT_PREREG)
    parser.add_argument("--catalog", type=Path, default=m1.DEFAULT_CATALOG)
    parser.add_argument("--truth", type=Path, default=m1.DEFAULT_TRUTH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    as_of = args.as_of or dt.datetime.now(dt.UTC).date()
    try:
        report, code = run_screen(
            prereg=args.prereg,
            catalog=args.catalog,
            truth=args.truth,
            out_dir=args.out,
            as_of=as_of,
        )
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"{report.get('verdict', report['status'])} {args.out / REPORT_NAME}")
    return code


if __name__ == "__main__":
    sys.exit(main())
