"""SCREEN -- not confirmatory; upper bound (zero slippage).

GAP-1 D0 champion (LAMP-augmented blend, arm M3 of ``oof_rows.jsonl``) joined to the
Polymarket.us YES ask at a pre-stated gating instant, net of the venue taker fee.

Composes existing repo pieces (never reimplements them):
  * slug -> rung:        scripts/analysis/market_calibration_scan.classify_directory
                         (parse_weather_slug + slug_closed_interval; inclusive [A,B])
  * gating window:       scripts/analysis/p2_nbp_ask_murphy.first_snapshot_in_window
  * tape reader:         scripts/analysis/forecast_cheap_screen_wp7.read_rung_tape
  * rung probability:    breezy.analysis.multisource_blend_fit.student_t_cdf with the
                         [lo-0.5, hi+0.5) latent-integer rule of quantile_density.rung_probabilities
  * fee:                 breezy.strategy.current_rung_hold.decision.fee_on_ask with theta from
                         breezy.adapters.polymarket_us.fees.taker_fee_coefficient_as_of
  * bootstrap:           breezy.analysis.nbp_calibration.cluster_bootstrap_draws with
                         breezy.settlement.roi_bound.{B_RESAMPLES, SEED}

Gating-instant rule (pre-stated): the GAP-1 D0 forecast anchor is 10:00 LST on D0
(``f.jsonl.anchor_ns``), which is LATER than P2's 16:50Z D-1 instant, so the ask is the
first Depth10 L0 snapshot at or after ``anchor_ns`` inside a closed 10-minute window;
no snapshot in the window -> the rung is dropped. No ask observed before the forecast
issue time is ever used; settlement-time prices are never used.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

REPO = Path("/home/jon/breezy")
sys.path.insert(0, str(REPO / "scripts/analysis"))

from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of  # noqa: E402
from breezy.analysis.multisource_blend_fit import student_t_cdf  # noqa: E402
from breezy.analysis.nbp_calibration import cluster_bootstrap_draws, percentile_interval  # noqa: E402
from breezy.settlement.roi_bound import B_RESAMPLES, SEED  # noqa: E402
from breezy.strategy.current_rung_hold.decision import fee_on_ask  # noqa: E402
from breezy.strategy.no_ladder_maker.pno_store import site  # noqa: E402
from forecast_cheap_screen_wp7 import _fixed_scalars, read_rung_tape  # noqa: E402
from market_calibration_scan import classify_directory  # noqa: E402
from p2_nbp_ask_murphy import TEN_MINUTES_NS, first_snapshot_in_window  # noqa: E402

LABEL = "SCREEN -- not confirmatory; upper bound (zero slippage)"
OUT = Path(__file__).resolve().parent
RUN = Path("/mnt/storage/breezy/derived/gap1_source_resolution/gap1_j3_2026-11-02")
OOF = RUN / "j3/oof_rows.jsonl"
FEATURES = RUN / "f.jsonl"
TRUTH = Path.home() / ".local/share/breezy/derived/settlement-truth/settlement_truth.csv"
TAPE = Path(
    os.environ.get("BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG")
    or "/mnt/storage/breezy/catalog/quote_tape/polymarket_us"
)
DEPTH_ROOT = TAPE / "data/order_book_depths"
STATIONS = ("LAX", "MDW", "MIA", "SFO")
ARM = "M3"  # highest-level LAMP-augmented blend; PASS cell M3:D0 (dRES 0.0491)
HORIZON = "D0"
RULES = {"R1": 0.0, "R2": 0.03, "R3": 0.05}
BIN_EDGES = [i / 10 for i in range(11)]
_PROGRESS_S = 60.0


@dataclass(frozen=True, slots=True)
class Forecast:
    station: str
    climate_day: str
    mu: float
    sigma: float
    nu: float
    observed_f: float
    anchor_ns: int


@dataclass(frozen=True, slots=True)
class Joined:
    station: str
    climate_day: str
    rung_id: str
    lo: int | None
    hi: int | None
    ask: float
    ask_ts_ns: int
    p: float
    fee: float
    outcome: int
    edge: float
    pnl: float


def log(msg: str) -> None:
    print(f"{dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} {msg}", flush=True)


def load_forecasts() -> tuple[dict[tuple[str, str], Forecast], dict[str, int]]:
    """OOF D0 rows for ARM, anchor_ns from f.jsonl. Fields used are recorded in counts."""
    anchors: dict[tuple[str, str], int] = {}
    with FEATURES.open() as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("horizon") == HORIZON and "climate_day" in row:
                anchors[(row["station"], row["climate_day"])] = int(row["anchor_ns"])
    counts: Counter[str] = Counter()
    out: dict[tuple[str, str], Forecast] = {}
    with OOF.open() as fh:
        for line in fh:
            row = json.loads(line)
            if "header" in row:
                continue
            counts["oof_rows_total"] += 1
            if row["horizon"] != HORIZON:
                continue
            counts["oof_rows_d0"] += 1
            arm = row["arm_predictions"].get(ARM)
            if arm is None:
                counts["d0_rows_missing_arm"] += 1
                continue
            key = (row["station"], row["climate_day"])
            anchor = anchors.get(key)
            if anchor is None:
                counts["d0_rows_missing_anchor"] += 1
                continue
            if key in out:
                counts["d0_duplicate_station_day"] += 1
                continue
            out[key] = Forecast(
                key[0], key[1], float(arm["mu"]), float(arm["sigma"]), float(arm["nu"]),
                float(row["observed_f"]), anchor,
            )
    counts["d0_forecasts_usable"] = len(out)
    return out, dict(counts)


def load_truth() -> tuple[dict[tuple[str, str], int], int]:
    """NWS CLI FINAL tmax_f per station-day; conflicting finals are excluded, never averaged."""
    import csv

    seen: dict[tuple[str, str], set[int]] = defaultdict(set)
    with TRUTH.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row["is_final"] != "True" or row["tmax_f"] == "":
                continue
            seen[(row["station"], row["climate_day"])].add(int(row["tmax_f"]))
    truth = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
    return truth, sum(1 for v in seen.values() if len(v) > 1)


def list_rungs(wanted: set[tuple[str, str]]) -> tuple[dict[tuple[str, str], list], dict[str, int]]:
    """HIGH rung directories (names only; no parquet read) restricted to wanted station-days."""
    by_day: dict[tuple[str, str], list] = defaultdict(list)
    counts: Counter[str] = Counter()
    tape_days: set[tuple[str, str]] = set()
    for entry in os.scandir(DEPTH_ROOT):
        if not entry.is_dir():
            continue
        counts["depth_dirs_total"] += 1
        if "^no" in entry.name:
            counts["depth_dirs_no_leg"] += 1
            continue
        spec, kind = classify_directory(entry.name)
        if kind != "rung" or spec is None or spec.station not in STATIONS:
            counts["depth_dirs_not_high_rung_4stn"] += 1
            continue
        key = (spec.station, spec.climate_day.isoformat())
        tape_days.add(key)
        counts["depth_dirs_high_rung_4stn"] += 1
        if key in wanted:
            by_day[key].append((spec, entry.path))
    days = sorted(d for _, d in tape_days)
    counts["tape_station_days_high_4stn"] = len(tape_days)
    counts["tape_climate_day_min"] = days[0] if days else None  # type: ignore[assignment]
    counts["tape_climate_day_max"] = days[-1] if days else None  # type: ignore[assignment]
    counts["station_days_in_both_oof_and_tape"] = len(by_day)
    counts["rung_dirs_in_join"] = sum(len(v) for v in by_day.values())
    return by_day, dict(counts)


def rung_p(fc: Forecast, lo: int | None, hi: int | None) -> float:
    cdf = student_t_cdf(fc.mu, fc.sigma, fc.nu)
    upper = 1.0 if hi is None else cdf(float(hi) + 0.5)
    lower = 0.0 if lo is None else cdf(float(lo) - 0.5)
    return upper - lower


def join(
    forecasts: dict[tuple[str, str], Forecast],
    rungs: dict[tuple[str, str], list],
    truth: dict[tuple[str, str], int],
) -> tuple[list[Joined], dict[str, int]]:
    price_scalar, size_scalar = _fixed_scalars()
    counts: Counter[str] = Counter()
    rows: list[Joined] = []
    last = time.monotonic()
    total = sum(len(v) for v in rungs.values())
    done = 0
    for key in sorted(rungs):
        fc = forecasts[key]
        placed = site(key[0])
        tmax = truth.get(key)
        for spec, path in sorted(rungs[key], key=lambda t: t[1]):
            done += 1
            if time.monotonic() - last >= _PROGRESS_S:
                log(f"progress rung {done}/{total} joined={len(rows)}")
                last = time.monotonic()
            if tmax is None:
                counts["drop_no_cli_truth"] += 1
                continue
            instants, _n = read_rung_tape(
                Path(path), std_utc_offset_hours=placed.offset_hours,
                price_scalar=price_scalar, size_scalar=size_scalar, city=key[0],
            )
            snap = first_snapshot_in_window(instants, fc.anchor_ns)
            del instants
            if snap is None:
                counts["drop_no_book_in_window"] += 1
                continue
            if snap.ask is None or not 0.0 < snap.ask < 1.0:
                counts["drop_no_yes_ask"] += 1
                continue
            theta = taker_fee_coefficient_as_of(snap.ts_ns)
            if theta is None:
                counts["drop_fee_unpinned"] += 1
                continue
            ask = Decimal(str(round(snap.ask, 4)))
            fee = float(fee_on_ask(ask, theta))
            p = rung_p(fc, spec.lower, spec.upper)
            outcome = int(
                (spec.lower is None or tmax >= spec.lower) and (spec.upper is None or tmax <= spec.upper)
            )
            edge = p - float(ask) - fee
            rows.append(Joined(
                key[0], key[1], f"{spec.lower}_{spec.upper}", spec.lower, spec.upper,
                float(ask), snap.ts_ns, p, fee, outcome, edge, outcome - float(ask) - fee,
            ))
    counts["joined_rows"] = len(rows)
    counts["joined_station_days"] = len({(r.station, r.climate_day) for r in rows})
    return rows, dict(counts)


def summarise(rows: list[Joined]) -> dict:
    def mean(xs: list[float]) -> float | None:
        return sum(xs) / len(xs) if xs else None

    def ci(items: list[Joined], stat) -> list[float] | None:
        if len({(r.station, r.climate_day) for r in items}) < 2:
            return None
        draws = cluster_bootstrap_draws(
            items, statistic=stat, cluster_key=lambda r: (r.station, r.climate_day),
            seed=SEED, iterations=B_RESAMPLES,
        )
        return list(percentile_interval(draws))

    rules = {}
    for name, thr in RULES.items():
        takes = [r for r in rows if r.edge > thr]
        rules[name] = {
            "threshold": thr,
            "n_takes": len(takes),
            "n_station_days": len({(r.station, r.climate_day) for r in takes}),
            "hit_rate": mean([float(r.outcome) for r in takes]),
            "mean_pnl_per_take": mean([r.pnl for r in takes]),
            "total_pnl": sum(r.pnl for r in takes) if takes else None,
            "ci95_mean_pnl_station_day": ci(takes, lambda xs: sum(r.pnl for r in xs) / len(xs)),
        }
    bins = []
    for lo, hi in zip(BIN_EDGES[:-1], BIN_EDGES[1:]):
        b = [r for r in rows if lo <= r.p < hi or (hi == 1.0 and r.p == 1.0)]
        bins.append({"bin": f"[{lo:.1f},{hi:.1f})", "n": len(b), "mean_p": mean([r.p for r in b]),
                     "realized_freq": mean([float(r.outcome) for r in b]), "mean_ask": mean([r.ask for r in b])})
    return {
        "rules": rules,
        "model_free": {"n": len(rows), "mean_p_minus_ask": mean([r.p - r.ask for r in rows]),
                       "ci95_station_day": ci(rows, lambda xs: sum(r.p - r.ask for r in xs) / len(xs))},
        "calibration_10bin": bins,
    }


def main() -> int:
    t0 = time.monotonic()
    log(f"{LABEL}; arm={ARM} horizon={HORIZON} depth_root={DEPTH_ROOT}")
    forecasts, c_fc = load_forecasts()
    log(f"forecasts: {c_fc}")
    truth, truth_conflicts = load_truth()
    agree = sum(1 for k, f in forecasts.items() if k in truth and truth[k] == int(f.observed_f))
    covered = sum(1 for k in forecasts if k in truth)
    log(f"truth: finals={len(truth)} conflicts={truth_conflicts} oof_covered={covered} observed_f==cli={agree}")
    rungs, c_tape = list_rungs(set(forecasts))
    log(f"tape: {c_tape}")
    rows, c_join = join(forecasts, rungs, truth)
    log(f"join: {c_join}")
    summary = summarise(rows)
    days = sorted(r.climate_day for r in rows)
    result = {
        "label": LABEL,
        "question": "GAP-1 D0 champion vs PM.us YES ask after taker fee, qty-1 taker, zero slippage",
        "fields_used": {
            "oof_rows.jsonl": ["station", "climate_day", "horizon==D0", f"arm_predictions.{ARM}.{{mu,sigma,nu}}",
                                "observed_f (cross-check only)"],
            "f.jsonl": ["station", "climate_day", "horizon==D0", "anchor_ns (forecast issue instant)"],
            "settlement_truth.csv": ["station", "climate_day", "is_final==True", "tmax_f"],
            "tape": ["order_book_depths/<slug>.POLYMARKET_US/*.parquet L0 ask_price_0 at first snapshot in [anchor_ns, anchor_ns+10min]"],
        },
        "gating_rule": "first Depth10 L0 snapshot at or after the GAP-1 D0 anchor (10:00 LST D0, f.jsonl.anchor_ns), "
                       "closed 10-minute window, else drop; anchor is later than P2's 16:50Z D-1 so P2's instant is NOT used",
        "truth_source": "NWS CLI FINAL tmax_f from settlement_truth.csv (oof observed_f cross-checked)",
        "counts": {**c_fc, "truth_finals": len(truth), "truth_conflicts_excluded": truth_conflicts,
                   "oof_station_days_with_cli_truth": covered, "oof_observed_f_equals_cli": agree, **c_tape, **c_join},
        "oof_climate_day_range": [min(f.climate_day for f in forecasts.values()), max(f.climate_day for f in forecasts.values())],
        "joined_climate_day_range": [days[0], days[-1]] if days else None,
        "decision_rules": RULES,
        "bootstrap": {"B": B_RESAMPLES, "seed": SEED, "cluster": "station_day"},
        "summary": summary,
        "rows": [asdict(r) for r in rows],
        "elapsed_s": round(time.monotonic() - t0, 1),
    }
    (OUT / "results.json").write_text(json.dumps(result, indent=1, default=str))
    log(f"wrote results.json joined_rows={len(rows)} elapsed={result['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
