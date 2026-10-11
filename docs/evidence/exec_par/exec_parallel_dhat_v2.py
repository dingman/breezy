"""EXEC-PAR BG-10 (a)(d)(e): the section 3 activation re-run of the WP0 simulation.

This is a COPY of ``docs/evidence/m1v3/exec_parallel_dhat.py`` (hash-pinned in D-PREREG section 11,
never edited) extended with the BG-10 controls:
  (a) ``--bucket-reader module:callable``: the ladder LABEL only is read and printed;
  (d) resamples configurable and defaulting to 20,000; three seeds, each varying BOTH the
      bootstrap seed (``boot_seed``) and the draw-seed string (``draw_seed_string``); the section 3
      stop rule passes only if EVERY seed's CI upper bound is <= 0.30;
  (e) a report-only day-overdispersed p_amb arm (beta-binomial by day, rho = 0.1).

WP0 docstring follows.

EXEC-PAR WP0: offline viability simulation of the dropped-candidate share d-hat (HARD gate).

Pure and deterministic: seeded draws, no network, no clock. Every admission decision is made by the
PRODUCTION ``breezy.domain.exec_slots.admit`` (WP1). The throttle, free-balance and AMBIGUOUS-bound
arms are layered around it and every drop is counted in d-hat.

ABSOLUTE DATA RULE. The M1-v3 pre-registered window (climate days on or after 2026-10-07) must stay
unseen. Every input (candidate file day keys, candidate timestamps, order timestamps, tape days to
extract) is refused with ``WindowDataRefused`` when it is dated on or after ``CUTOFF_DAY``.
Extraction refuses BEFORE any filesystem access.

Modes
  --extract   rebuild the candidate file (with instrument ids) from the pre-window Depth10 tape
              rows, using the same bounds and rule as ``stage_minus1_triage_dmix.py``.
  (default)   run the grid over the candidate file and write the results JSON.

Method and stop rule: plan r5 section 6 and r5.1 delta E6. See ``exec_parallel_wp0_findings.md``.
"""

from __future__ import annotations

import argparse
import ast
import csv
import dataclasses
import datetime as dt
import importlib
import json
import math
import multiprocessing
import random
import re
import statistics
import sys
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import numpy as np

from breezy.domain.exec_slots import SlotRecord, SlotTableView, Wait, admit
from breezy.domain.instrument_leg import base_symbol_of, symbol_of_instrument_id

HERE: Final[Path] = Path(__file__).resolve().parent
REPO: Final[Path] = HERE.parents[2]
CLIENT_SOURCE: Final[Path] = (
    REPO / "src" / "breezy" / "adapters" / "polymarket_us" / "exec" / "client.py"
)
M1V3: Final[Path] = HERE.parent / "m1v3"
DEFAULT_CANDS: Final[Path] = M1V3 / "exec_parallel_dhat_cands.json"
DEFAULT_OUT: Final[Path] = HERE / "exec_parallel_dhat_v2_results.json"
DEFAULT_ORDERS: Final[Path] = M1V3 / "WP0_c0_pre1007_orders.tsv"

NS: Final[int] = 10**9
DAY_NS: Final[int] = 86_400 * NS

# ---- the data rule -------------------------------------------------------------------------------
CUTOFF_DAY: Final[dt.date] = dt.date(2026, 10, 7)
CUTOFF_NS: Final[int] = int(dt.datetime(2026, 10, 7, tzinfo=dt.UTC).timestamp()) * NS
# Extraction bounds: byte-identical to ``stage_minus1_triage_dmix.py`` (a test pins the equality).
FIRST_DAY, LAST_DAY = dt.date(2026, 8, 30), dt.date(2026, 10, 6)
WINDOW_START_HOUR: Final[int] = 12  # the dmix pre-window hour: 12:00-13:00Z of the climate day
NO_ASK_FLOOR: Final[float] = 0.90
MAIN4: Final[frozenset[str]] = frozenset({"LAX", "MDW", "MIA", "SFO"})
MAIN4_NYC: Final[frozenset[str]] = MAIN4 | {"NYC"}
VENUE_SUFFIX: Final[str] = ".POLYMARKET_US"

# ---- model constants -----------------------------------------------------------------------------
DRAWS: Final[int] = 1000
RESAMPLES: Final[int] = 20_000  # D-PREREG section 3 step 4: at least 20,000
BOOT_SEED: Final[int] = 20261120
SEEDS: Final[tuple[int, ...]] = (0, 1, 2)  # three seeds; each varies BOOT_SEED AND the draw string
SEED_STRIDE: Final[int] = 1_000_003
RHO_ARM: Final[float] = 0.1  # BG-10(e): day-overdispersed p_amb, beta-binomial by day
RHO_ARM_GATES: Final[bool] = False  # report-only: it never feeds the stop rule
DEFAULT_WORKERS: Final[int] = 4  # the machine also runs the live trading node
FROZEN_LABEL: Final[str] = "0.05"
STOP_BAR: Final[float] = 0.30
UNIT: Final[int] = 1_000_000  # integer micro-budget units: exact comparisons at the f_adm boundary
F_ADM: Final[float] = 0.50
F_ADM_UNITS: Final[int] = round(F_ADM * UNIT)
COOLOFF_NS: Final[int] = 120 * NS
THROTTLE_MAX: Final[int] = 5  # node_config max_order_submit_rate "5/00:00:01"
THROTTLE_WINDOW_NS: Final[int] = NS
FREE0_DEFAULT: Final[float] = 1.0  # free balance, in daily budgets: the tightest plausible funding
BUCKETS: Final[tuple[float, ...]] = (0.02, 0.05, 0.10, 0.25, 0.50)
BUCKET_LABELS: Final[tuple[str, ...]] = ("<=0.02", "0.05", "0.10", "0.25", "0.50")
SENTINEL_LABEL: Final[str] = ">0.50"
GATE_MIN_BUCKET: Final[float] = 0.05
P_AMB_GRID: Final[tuple[float, ...]] = (0.0, 0.05, 0.10, 0.18, 0.33)
STRESS_P_AMB: Final[float] = 0.33
K_REPORT: Final[tuple[int, ...]] = (3, 4, 5, 6, 7, 8)

# Hold model (seconds). The dmix model: a non-ambiguous order frees its slot at the fill (0.3 s); an
# AMBIGUOUS one resolves on the first resolver poll (5 s) w.p. 0.2, else after the zero-fill floor
# plus polling (150 s). ``assert_hold_constants_current`` ties these to the exec client source.
HOLD_FILL_S: Final[float] = 0.3
HOLD_AMB_FAST_S: Final[float] = 5.0
HOLD_AMB_SLOW_S: Final[float] = 150.0
P_AMB_FAST: Final[float] = 0.2
NO_ID_HOLD_S: Final[float] = 305.0  # no-id floor 300 s plus one 5 s poll
FEED_LAG_DEFAULT_S: Final[float] = 300.0


class WindowDataRefused(ValueError):
    """An input is dated on or after the pre-registered M1-v3 window start."""


class CapsReadRefused(ValueError):
    """The caps reader returned something other than a bucket label."""


# ---- the data rule: guards -----------------------------------------------------------------------
def refuse_window_day(day: dt.date) -> None:
    if day >= CUTOFF_DAY:
        raise WindowDataRefused(
            f"{day} is on or after {CUTOFF_DAY}: the M1-v3 window must stay unseen"
        )


def refuse_window_ns(ts_ns: int) -> None:
    if ts_ns >= CUTOFF_NS:
        raise WindowDataRefused(f"timestamp {ts_ns} is on or after {CUTOFF_DAY}T00:00Z")


_DATE_IN_NAME = re.compile(r"(20\d\d)-?(0[1-9]|1[0-2])-?(0[1-9]|[12]\d|3[01])")


def refuse_window_path(path: Path) -> None:
    for match in _DATE_IN_NAME.finditer(path.name):
        refuse_window_day(dt.date(int(match[1]), int(match[2]), int(match[3])))


# ---- candidates ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Candidate:
    ts_ns: int
    station: str
    instrument_id: str
    no_ask: float


def slug_of(instrument_id: str) -> str:
    """The venue slug of either leg's instrument id: YES and NO of one market are ONE slot."""
    return base_symbol_of(symbol_of_instrument_id(instrument_id))


def load_candidates(path: Path) -> dict[dt.date, tuple[Candidate, ...]]:
    refuse_window_path(path)
    raw = json.loads(path.read_text())
    out: dict[dt.date, tuple[Candidate, ...]] = {}
    for key, rows in raw["days"].items():
        day = dt.date.fromisoformat(key)
        refuse_window_day(day)
        cands = []
        for row in rows:
            ts_ns = int(row["ts_ns"])
            refuse_window_ns(ts_ns)
            cands.append(
                Candidate(
                    ts_ns, str(row["station"]), str(row["instrument_id"]), float(row["no_ask"])
                )
            )
        out[day] = tuple(sorted(cands, key=lambda c: (c.ts_ns, c.instrument_id)))
    return out


def extract_candidates(
    first: dt.date, last: dt.date, root: Path | None = None
) -> dict[str, object]:
    """Candidates (NO ask >= 0.90 on the first 12:00-13:00Z depth row) WITH instrument ids.

    Same rule as ``stage_minus1_triage_dmix.py``. Refuses window days before any I/O.
    """
    refuse_window_day(first)
    refuse_window_day(last)
    if first > last:
        raise ValueError("first day is after last day")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from decimal import Decimal

    import pyarrow.dataset as pds

    from breezy.analysis import capture_audit_tape as cat
    from scripts.analysis import market_calibration_scan as m1

    tape = root if root is not None else m1.DEFAULT_CATALOG / "data" / cat.DEPTH_DIR

    def first_row(inst: str, day: dt.date) -> dict[str, object] | None:
        lo = (
            int(
                dt.datetime(
                    day.year, day.month, day.day, WINDOW_START_HOUR, tzinfo=dt.UTC
                ).timestamp()
            )
            * NS
        )
        hi = lo + 3600 * NS
        refuse_window_ns(hi - 1)
        files = []
        for p in sorted((tape / inst).iterdir()):
            span = cat._span(p)
            if span and span[1] >= lo and span[0] < hi:
                files.append(p)
        if not files:
            return None
        prec = cat._precisions(files[0])
        field_ts = pds.field("ts_event")
        best = None
        for p in files:
            table = pds.dataset([str(p)], format="parquet").to_table(
                columns=list(cat._DEPTH_COLUMNS), filter=(field_ts >= lo) & (field_ts < hi)
            )
            if table.num_rows == 0:
                continue
            row = min(table.to_pylist(), key=lambda r: r["ts_event"])
            if best is None or row["ts_event"] < best["ts_event"]:
                best = row
        return cat._depth_body(best, prec) if best else None

    by_day: dict[dt.date, list[tuple[str, object]]] = {}
    for entry in sorted(tape.iterdir()):
        spec, _kind = m1.classify_directory(entry.name)
        if spec is None or not (first <= spec.climate_day <= last):
            continue
        by_day.setdefault(spec.climate_day, []).append((entry.name, spec))
    days: dict[str, list[dict[str, object]]] = {}
    stats = {"rungs": 0, "norow": 0, "nobid": 0}
    for day in sorted(by_day):
        rows: list[dict[str, object]] = []
        for name, spec in by_day[day]:
            if spec.station not in MAIN4_NYC:
                continue
            stats["rungs"] += 1
            body = first_row(name, day)
            if body is None:
                stats["norow"] += 1
                continue
            no_ask = m1.no_ask(body)
            if no_ask is None:
                stats["nobid"] += 1
                continue
            if no_ask >= Decimal("0.90"):
                ts_ns = int(body["ts_event"])
                refuse_window_ns(ts_ns)
                rows.append(
                    {
                        "ts_ns": ts_ns,
                        "station": spec.station,
                        "instrument_id": name,
                        "no_ask": str(no_ask),
                    }
                )
        days[day.isoformat()] = sorted(
            rows, key=lambda r: (int(r["ts_ns"]), str(r["instrument_id"]))
        )
    return {
        "schema": 1,
        "extraction": {
            "first": first.isoformat(),
            "last": last.isoformat(),
            "stats": stats,
            "rule": "first 12:00-13:00Z depth row per rung; NO ask = 1 - best YES bid >= 0.90",
        },
        "days": days,
    }


# ---- the simulation ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Arm:
    """One arm. ``free_arm`` A reduces free balance at fill time; B also holds it for AMBIGUOUS."""

    k: int
    p_amb: float
    bucket: float
    free_arm: str = "A"
    stuck: int = 0
    no_id: bool = False
    throttle: bool = True
    bound: bool = True
    free0: float | None = FREE0_DEFAULT
    rho: float = 0.0
    seed: int = 0


@dataclass(frozen=True)
class DayOutcome:
    n: int
    admitted: int
    drops: dict[str, int]
    first5s_fraction: float
    arm_ns: tuple[int, ...] = ()  # arm time of each admitted (posted) entry, in order
    ambiguous: tuple[bool, ...] = ()  # whether each admitted entry ended AMBIGUOUS


@dataclass
class _Slot:
    end_ns: int | None
    key: str
    slug: str
    ambiguous: bool


def _ordered(cands: Sequence[Candidate], rng: random.Random) -> list[Candidate]:
    stamps = [c.ts_ns for c in cands]
    if len(set(stamps)) == len(stamps):
        return sorted(cands, key=lambda c: c.ts_ns)
    return sorted(cands, key=lambda c: (c.ts_ns, rng.random()))


def _hold_ns(arm: Arm, rng: random.Random) -> tuple[int, bool]:
    if arm.p_amb > 0 and rng.random() < arm.p_amb:
        if arm.no_id:
            return round(NO_ID_HOLD_S * NS), True
        fast = rng.random() < P_AMB_FAST
        return round((HOLD_AMB_FAST_S if fast else HOLD_AMB_SLOW_S) * NS), True
    return round(HOLD_FILL_S * NS), False


def simulate_day(cands: Sequence[Candidate], arm: Arm, rng: random.Random) -> DayOutcome:
    """One draw of one day. Drops are attributed to the first failing gate: admit, throttle,
    free-balance, AMBIGUOUS bound (the production order: latch, engine, ledger)."""
    cost = round(arm.bucket * UNIT)
    free0 = None if arm.free0 is None else round(arm.free0 * UNIT)
    open_: list[_Slot] = [_Slot(None, f"stuck-{i}", f"STUCK-{i}", True) for i in range(arm.stuck)]
    cooloff: list[tuple[str, int]] = []
    recent: deque[int] = deque()
    filled = admitted = first5 = 0
    drops: Counter[str] = Counter()
    arm_times: list[int] = []
    amb_flags: list[bool] = []
    for cand in _ordered(cands, rng):
        t = cand.ts_ns
        still: list[_Slot] = []
        for slot in open_:
            if slot.end_ns is not None and slot.end_ns <= t:
                filled += cost
                cooloff.append((slot.slug, slot.end_ns + COOLOFF_NS))
            else:
                still.append(slot)
        open_ = still
        cooloff = [c for c in cooloff if c[1] > t]
        slug = slug_of(cand.instrument_id)
        view = SlotTableView(
            open_slots=tuple(SlotRecord(s.key, s.slug, False) for s in open_),
            cooloff=tuple(cooloff),
        )
        decision = admit(view, slug, False, arm.k, False, t)
        if isinstance(decision, Wait):
            drops[f"admit:{decision.reason}"] += 1
            continue
        if arm.throttle:
            while recent and recent[0] <= t - THROTTLE_WINDOW_NS:
                recent.popleft()
            if len(recent) >= THROTTLE_MAX:
                drops["throttle"] += 1
                continue
        amb_open = sum(1 for s in open_ if s.ambiguous)
        if free0 is not None:
            held = amb_open * cost if arm.free_arm == "B" else 0
            if cost > free0 - filled - held:
                drops["free_balance"] += 1
                continue
        if arm.bound and amb_open * cost + cost > F_ADM_UNITS:
            drops["ambiguous_bound"] += 1
            continue
        hold_ns, ambiguous = _hold_ns(arm, rng)
        open_.append(_Slot(t + hold_ns, cand.instrument_id, slug, ambiguous))
        recent.append(t)
        admitted += 1
        arm_times.append(t)
        amb_flags.append(ambiguous)
        if t % DAY_NS < (WINDOW_START_HOUR * 3600 + 5) * NS:
            first5 += 1
    return DayOutcome(
        len(cands),
        admitted,
        dict(sorted(drops.items())),
        first5 * cost / UNIT,
        tuple(arm_times),
        tuple(amb_flags),
    )


@dataclass(frozen=True)
class DayStat:
    dhat: float
    first5s_fraction: float
    drop_mix: tuple[tuple[str, float], ...]


def boot_seed(seed: int) -> int:
    """The bootstrap seed of seed index ``seed`` (BG-10(d): varies BOOT_SEED itself)."""
    return BOOT_SEED + SEED_STRIDE * seed


def draw_seed_string(arm: Arm, day: dt.date) -> str:
    """The per-day draw seed. It ignores k, bucket and the arms so that every cell reuses the same
    random hold draws (common random numbers); it varies with the seed index (BG-10(d)) and, only
    for the overdispersed arm, with rho."""
    rho = f"|rho{arm.rho}" if arm.rho else ""
    return f"wp0|{arm.p_amb}|{arm.no_id}{rho}|{day.isoformat()}|seed{arm.seed}"


def beta_params(p: float, rho: float) -> tuple[float, float]:
    """Beta(a, b) with mean ``p`` and beta-binomial ICC ``rho`` = 1 / (a + b + 1)."""
    if not 0.0 < rho < 1.0:
        raise ValueError("rho must lie in (0, 1)")
    scale = (1.0 - rho) / rho
    return p * scale, (1.0 - p) * scale


def day_p_amb(arm: Arm, rng: random.Random) -> float:
    """The p_amb of one simulated day: ``arm.p_amb`` itself, or (rho > 0) a Beta draw by day.
    At rho = 0 (or p in {0, 1}) no randomness is consumed."""
    if arm.rho <= 0.0 or arm.p_amb <= 0.0 or arm.p_amb >= 1.0:
        return arm.p_amb
    a, b = beta_params(arm.p_amb, arm.rho)
    return rng.betavariate(a, b)


def day_stats(cands: Sequence[Candidate], arm: Arm, day: dt.date, draws: int = DRAWS) -> DayStat:
    """Mean over ``draws`` seeded draws of one day."""
    rng = random.Random(draw_seed_string(arm, day))
    dropped = first5 = 0.0
    mix: Counter[str] = Counter()
    for _ in range(draws):
        draw_arm = arm if arm.rho <= 0.0 else dataclasses.replace(arm, p_amb=day_p_amb(arm, rng))
        out = simulate_day(cands, draw_arm, rng)
        n_drop = sum(out.drops.values())
        dropped += n_drop / out.n
        first5 += out.first5s_fraction
        mix.update(out.drops)
    n = len(cands)
    return DayStat(
        dropped / draws, first5 / draws, tuple((r, c / draws / n) for r, c in sorted(mix.items()))
    )


def _arm_off(k: int, p_amb: float) -> Arm:
    return Arm(k=k, p_amb=p_amb, bucket=BUCKETS[0], throttle=False, bound=False, free0=None)


def _percentile(values: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), 100.0 * q))


def k1_p0_p90(
    by_day: Mapping[dt.date, Sequence[Candidate]],
    draws: int = DRAWS,
    stations: frozenset[str] = MAIN4,
) -> float:
    """K=1, p_amb=0 in-memory day-level p90 of d-hat (plan: 0.491); no throttle/free/bound arm."""
    arm = _arm_off(1, 0.0)
    vals = []
    for day, cands in sorted(by_day.items()):
        chosen = tuple(c for c in cands if c.station in stations)
        if chosen:
            vals.append(day_stats(chosen, arm, day, draws).dhat)
    return _percentile(vals, 0.9)


# ---- statistics and the stop rule ----------------------------------------------------------------
def cluster_bootstrap_ci(
    day_values: Sequence[float], quantile: float, resamples: int = RESAMPLES, seed: int = BOOT_SEED
) -> tuple[float, float, float]:
    """(point, lo, hi): day-clustered bootstrap, 95% percentile interval of the day quantile."""
    values = np.asarray(day_values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(resamples, len(values)))
    boot = np.percentile(values[idx], 100.0 * quantile, axis=1)
    return (
        float(np.percentile(values, 100.0 * quantile)),
        float(np.percentile(boot, 2.5)),
        float(np.percentile(boot, 97.5)),
    )


def passes_stop_rule(ci_upper: float) -> bool:
    """The stop rule reads the CI UPPER bound against the 0.30 bar (NaN never passes)."""
    return ci_upper <= STOP_BAR


@dataclass(frozen=True)
class CellKey:
    bucket: float
    k: int
    p_amb: float
    free_arm: str
    stuck: int
    no_id: bool
    rho: float = 0.0
    seed: int = 0


@dataclass(frozen=True)
class CellStat:
    p50: float
    p50_upper: float
    p90: float
    p90_lower: float
    p90_upper: float
    first5s_mean: float = 0.0
    first5s_p90: float = 0.0
    drop_mix: tuple[tuple[str, float], ...] = field(default_factory=tuple)


def worse_arm_upper(
    cells: Mapping[CellKey, CellStat],
    bucket: float,
    k: int,
    p_amb: float,
    stuck: int,
    no_id: bool,
    rho: float = 0.0,
    seed: int = 0,
) -> float:
    """The p90 CI upper bound under the WORSE of the two free-balance arms.

    A cell that was not run is NaN, which never passes the stop rule: absence is not evidence."""
    keys = [CellKey(bucket, k, p_amb, arm, stuck, no_id, rho, seed) for arm in ("A", "B")]
    if any(key not in cells for key in keys):
        return math.nan
    return max(cells[key].p90_upper for key in keys)


def seed_uppers(
    cells: Mapping[CellKey, CellStat],
    bucket: float,
    k: int,
    p_amb: float,
    stuck: int,
    no_id: bool,
    rho: float = 0.0,
) -> tuple[float, ...]:
    """The worse-arm p90 CI upper bound of every seed (BG-10(d))."""
    return tuple(worse_arm_upper(cells, bucket, k, p_amb, stuck, no_id, rho, s) for s in SEEDS)


def passes_all_seeds(uppers: Sequence[float]) -> bool:
    """The section 3 stop rule: EVERY seed's CI upper bound within the bar (NaN or none fails)."""
    return bool(uppers) and all(passes_stop_rule(u) for u in uppers)


def smallest_passing_k(
    cells: Mapping[CellKey, CellStat],
    bucket: float,
    p_amb: float = STRESS_P_AMB,
    stuck: int = 1,
    no_id: bool = False,
    rho: float = 0.0,
) -> int | None:
    for k in K_REPORT:
        if passes_all_seeds(seed_uppers(cells, bucket, k, p_amb, stuck, no_id, rho)):
            return k
    return None


def smallest_k_per_bucket(
    cells: Mapping[CellKey, CellStat],
    p_amb: float = STRESS_P_AMB,
    stuck: int = 1,
    no_id: bool = False,
) -> dict[float, int | None]:
    """K per bucket. A bucket that never passes reports None: there is NO worst-bucket fallback."""
    return {b: smallest_passing_k(cells, b, p_amb, stuck, no_id) for b in BUCKETS}


def build_gate_verdict(table: Mapping[float, int | None]) -> dict[str, object]:
    """PASS iff some bucket >= 0.05 passes at K <= 8 (the <=0.02 bucket cannot pass alone)."""
    passing = sorted(
        b for b, k in table.items() if b >= GATE_MIN_BUCKET and k is not None and k <= max(K_REPORT)
    )
    return {
        "verdict": "PASS" if passing else "STOP",
        "passing_buckets": passing,
        "smallest_k": {bucket_name(b): k for b, k in sorted(table.items())},
        "rule": "PASS iff a bucket >= 0.05 has p90 CI upper bound <= 0.30 at K <= 8 (stress arm)",
    }


# ---- buckets, cost distribution ------------------------------------------------------------------
def bucket_name(bucket: float) -> str:
    return BUCKET_LABELS[BUCKETS.index(bucket)]


def bucket_label(ratio: float) -> str:
    """Ladder label of a cap/budget (or cost/budget) ratio; above 0.50 is the K=1 sentinel."""
    for edge, label in zip(BUCKETS, BUCKET_LABELS, strict=True):
        if ratio <= edge:
            return label
    return SENTINEL_LABEL


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {
        "n": float(len(arr)),
        "min": float(arr.min()),
        "p10": float(np.percentile(arr, 10)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "max": float(arr.max()),
    }


def cost_distribution(cands: Sequence[Candidate]) -> dict[str, object]:
    """Per-order cost (ask x 1 contract, USD) and, per bucket, the distribution in BOTH units:
    realized cost / budget and cap / budget (E6). The budget is not read: it is the one for which
    the median order costs exactly the bucket's share; the cap is the 1 contract <= $1 bound."""
    usd = [c.no_ask for c in cands]
    base = _quantiles(usd)
    cap_usd = 1.0
    by_bucket: dict[str, object] = {}
    for bucket, label in zip(BUCKETS, BUCKET_LABELS, strict=True):
        budget = base["p50"] / bucket
        cap_ratio = cap_usd / budget
        by_bucket[label] = {
            "bucket": bucket,
            "implied_budget_usd": budget,
            "cost_over_budget": _quantiles([x / budget for x in usd]),
            "cap_usd": cap_usd,
            "cap_over_budget": cap_ratio,
            "cap_over_budget_label": bucket_label(cap_ratio),
        }
    return {"usd_per_order": base, "by_bucket": by_bucket}


# ---- constants tied to the exec client, caps, feed lag -------------------------------------------
_CLIENT_NAMES: Final[tuple[str, ...]] = (
    "_RESOLVER_POLL_INTERVAL_SECS",
    "_RESOLVER_ZERO_FILL_MIN_AGE_NS",
    "_RESOLVER_NO_ID_MIN_AGE_NS",
)


def _const_value(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _const_value(node.left) * _const_value(node.right)
    raise ValueError(f"unsupported constant expression: {ast.dump(node)}")


def hold_constants_from_client_source(path: Path) -> dict[str, float]:
    """The resolver constants read from the exec client's AST (never imported, never executed)."""
    found: dict[str, float] = {}
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in _CLIENT_NAMES
        ):
            if node.value is None:
                raise ValueError(f"{node.target.id} has no value")
            found[node.target.id] = _const_value(node.value)
    missing = set(_CLIENT_NAMES) - set(found)
    if missing:
        raise ValueError(f"exec client constants not found: {sorted(missing)}")
    return {
        "poll_s": found["_RESOLVER_POLL_INTERVAL_SECS"],
        "zero_fill_min_age_s": found["_RESOLVER_ZERO_FILL_MIN_AGE_NS"] / NS,
        "no_id_min_age_s": found["_RESOLVER_NO_ID_MIN_AGE_NS"] / NS,
    }


def assert_hold_constants_current(path: Path = CLIENT_SOURCE) -> None:
    c = hold_constants_from_client_source(path)
    if HOLD_AMB_FAST_S != c["poll_s"]:
        raise AssertionError("fast AMBIGUOUS hold is not the resolver poll interval")
    if HOLD_AMB_SLOW_S < c["zero_fill_min_age_s"] + c["poll_s"]:
        raise AssertionError("slow AMBIGUOUS hold is below the zero-fill floor plus one poll")
    if NO_ID_HOLD_S != c["no_id_min_age_s"] + c["poll_s"]:
        raise AssertionError("no-id hold is not the no-id floor plus one poll")


_UNICODE_LE: Final[str] = "\u2264"


def canonical_label(label: object) -> str:
    """The ASCII ladder label of ``label`` (the operator ladder spells the first rung with a
    unicode less-or-equal); anything that is not a ladder label is refused WITHOUT echoing it."""
    if isinstance(label, str):
        ascii_label = label.replace(_UNICODE_LE, "<=")
        if ascii_label in (*BUCKET_LABELS, SENTINEL_LABEL):
            return ascii_label
    raise CapsReadRefused("the caps reader returned a value that is not a bucket label")


def caps_bucket_label(reader: Callable[[], str]) -> str:
    """The bucket LABEL from a read-only reader; any other value is refused WITHOUT echoing it."""
    return canonical_label(reader())


def positions_feed_lag_bound(measurements: Sequence[float] | None) -> float:
    """L_feed: the largest measured positions-feed lag (s), else the 300 s default."""
    if not measurements:
        return FEED_LAG_DEFAULT_S
    if any(math.isnan(m) or m < 0 for m in measurements):
        raise ValueError("a feed-lag measurement is negative or NaN")
    return float(max(measurements))


def wilson_upper(successes: int, n: int, z: float = 1.96) -> float:
    p = successes / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre + half) / (1 + z * z / n)


def read_hold_inputs(path: Path) -> dict[str, object]:
    """Counts from the pre-window order table (every row's day is checked against the cutoff)."""
    refuse_window_path(path)
    with path.open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        refuse_window_day(dt.date.fromisoformat(row["submit_ts"][:10]))
    posted = [r for r in rows if r["posted"] == "Y"]
    amb = [r for r in posted if r["outcome"] == "AMBIGUOUS"]
    return {
        "orders": len(rows),
        "posted": len(posted),
        "ambiguous": len(amb),
        "ambiguous_share": len(amb) / len(posted),
        "wilson_upper_95": wilson_upper(len(amb), len(posted)),
        "ambiguous_sides": dict(Counter(r["side"] for r in amb)),
        "posted_sides": dict(Counter(r["side"] for r in posted)),
        "median_hpost_s": statistics.median(float(r["hpost_s"]) for r in posted if r["hpost_s"]),
    }


# ---- the grid ------------------------------------------------------------------------------------
_DAYS: dict[dt.date, tuple[Candidate, ...]] = {}
_DRAWS: int = DRAWS
_RESAMPLES: int = RESAMPLES


def cell_stat(arm: Arm) -> tuple[CellKey, CellStat]:
    stats = [day_stats(cands, arm, day, _DRAWS) for day, cands in sorted(_DAYS.items()) if cands]
    dhat = [s.dhat for s in stats]
    seed = boot_seed(arm.seed)
    p90, p90_lo, p90_hi = cluster_bootstrap_ci(dhat, 0.9, _RESAMPLES, seed)
    p50, _p50_lo, p50_hi = cluster_bootstrap_ci(dhat, 0.5, _RESAMPLES, seed)
    mix: Counter[str] = Counter()
    for s in stats:
        for reason, share in s.drop_mix:
            mix[reason] += share / len(stats)
    first5 = [s.first5s_fraction for s in stats]
    key = CellKey(
        arm.bucket, arm.k, arm.p_amb, arm.free_arm, arm.stuck, arm.no_id, arm.rho, arm.seed
    )
    return key, CellStat(
        p50,
        p50_hi,
        p90,
        p90_lo,
        p90_hi,
        float(np.mean(first5)),
        _percentile(first5, 0.9),
        tuple(sorted(mix.items())),
    )


def gate_arms(
    bucket: float, free0: float | None, rho: float, ks: Sequence[int] = K_REPORT
) -> list[Arm]:
    """The section 3 gate arm over every seed: p_amb 0.33, one stuck slot, throttle, f_adm and
    both free-balance arms (the id arm; the no-id variant is not part of the stop rule)."""
    return [
        Arm(k, STRESS_P_AMB, bucket, fa, 1, False, True, True, free0, rho, seed)
        for seed in SEEDS
        for k in ks
        for fa in ("A", "B")
    ]


def _run_arms(arms: Sequence[Arm], workers: int) -> dict[CellKey, CellStat]:
    """Run cells in a capped pool, logging progress to stderr so a stall is visible."""
    ctx = multiprocessing.get_context("fork")
    done: dict[CellKey, CellStat] = {}
    with ctx.Pool(workers) as pool:
        for key, stat in pool.imap_unordered(cell_stat, arms, chunksize=1):
            done[key] = stat
            print(f"progress: {len(done)}/{len(arms)} cells", file=sys.stderr, flush=True)
    return done


def _cells_json(cells: Mapping[CellKey, CellStat]) -> list[dict[str, object]]:
    rows = []
    for key in sorted(
        cells, key=lambda x: (x.bucket, x.rho, x.seed, x.free_arm, x.stuck, x.no_id, x.p_amb, x.k)
    ):
        s = cells[key]
        rows.append(
            {
                "bucket": bucket_name(key.bucket),
                "k": key.k,
                "p_amb": key.p_amb,
                "rho": key.rho,
                "seed": key.seed,
                "free_arm": key.free_arm,
                "stuck": key.stuck,
                "no_id": key.no_id,
                "p50": s.p50,
                "p50_ci_upper": s.p50_upper,
                "p90": s.p90,
                "p90_ci_lower": s.p90_lower,
                "p90_ci_upper": s.p90_upper,
                "first5s_budget_fraction_mean": s.first5s_mean,
                "first5s_budget_fraction_p90": s.first5s_p90,
                "drop_share_by_reason": dict(s.drop_mix),
            }
        )
    return rows


def _stop_block(cells: Mapping[CellKey, CellStat], bucket: float, rho: float) -> dict[str, object]:
    by_k = {
        str(k): [round(u, 6) for u in seed_uppers(cells, bucket, k, STRESS_P_AMB, 1, False, rho)]
        for k in K_REPORT
    }
    return {
        "p90_ci_upper_by_k_and_seed": by_k,
        "smallest_k_every_seed_passes": smallest_passing_k(
            cells, bucket, STRESS_P_AMB, 1, False, rho
        ),
        "k6_every_seed_passes": passes_all_seeds(
            seed_uppers(cells, bucket, 6, STRESS_P_AMB, 1, False, rho)
        ),
        "rule": "every seed's day-clustered bootstrap CI upper bound of the day-level p90 <= 0.30",
    }


def run(args: argparse.Namespace, label: str) -> dict[str, object]:
    global _DAYS, _DRAWS, _RESAMPLES
    by_day = load_candidates(args.cands)
    stations = MAIN4_NYC if args.stations == "main4+nyc" else MAIN4
    _DAYS = {d: tuple(c for c in v if c.station in stations) for d, v in by_day.items()}
    _DRAWS, _RESAMPLES = args.draws, args.resamples
    live_days = {d: v for d, v in _DAYS.items() if v}
    assert_hold_constants_current()
    all_cands = [c for v in live_days.values() for c in v]
    bucket = BUCKETS[BUCKET_LABELS.index(label)]
    result: dict[str, object] = {
        "meta": {
            "plan": "D-PREREG section 3 activation re-run (BG-10 a, d, e)",
            "data_rule": f"every input dated before {CUTOFF_DAY}; window inputs refused",
            "candidate_file": args.cands.name,
            "stations": args.stations,
            "days_total": len(_DAYS),
            "days_with_candidates": len(live_days),
            "candidates_total": len(all_cands),
            "draws_per_day": _DRAWS,
            "bootstrap_resamples": _RESAMPLES,
            "seeds": list(SEEDS),
            "bootstrap_seeds": [boot_seed(s) for s in SEEDS],
            "draw_seed_template": "wp0|{p_amb}|{no_id}[|rho{rho}]|{day}|seed{seed}",
            "ci": "95% percentile interval, day-clustered bootstrap of the day-level quantile",
            "stop_metric": "p90 of the day-level d-hat, EVERY seed's CI upper bound <= 0.30",
            "free_balance_budgets": args.free0,
            "hold_model_s": {
                "fill": HOLD_FILL_S,
                "ambiguous_fast": HOLD_AMB_FAST_S,
                "ambiguous_slow": HOLD_AMB_SLOW_S,
                "p_fast": P_AMB_FAST,
                "no_id": NO_ID_HOLD_S,
            },
            "hold_constants_from_exec_client_ast": hold_constants_from_client_source(CLIENT_SOURCE),
            "f_adm": F_ADM,
            "throttle": f"{THROTTLE_MAX}/s sliding 1 s window",
            "L_feed_s": positions_feed_lag_bound(None),
            "bucket_label": label,
            "rho_arm": RHO_ARM,
            "rho_arm_gates": RHO_ARM_GATES,
        },
        "hold_inputs": read_hold_inputs(DEFAULT_ORDERS),
        "cost_distribution": cost_distribution(all_cands),
    }
    cells = _run_arms(
        [*gate_arms(bucket, args.free0, 0.0), *gate_arms(bucket, args.free0, RHO_ARM)],
        args.workers,
    )
    result["cells"] = _cells_json(cells)
    gate = _stop_block(cells, bucket, 0.0)
    result["gate"] = gate
    result["rho_arm_report_only"] = _stop_block(cells, bucket, RHO_ARM)
    result["verdict"] = "PASS" if gate["k6_every_seed_passes"] else "STOP"
    return result


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    p.add_argument("--cands", type=Path, default=DEFAULT_CANDS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--extract", action="store_true", help="rebuild the candidate file from the pre-window tape"
    )
    p.add_argument("--stations", choices=("main4", "main4+nyc"), default="main4+nyc")
    p.add_argument(
        "--free0", type=float, default=FREE0_DEFAULT, help="free balance in daily budgets"
    )
    p.add_argument("--workers", type=_positive_int, default=DEFAULT_WORKERS)
    p.add_argument("--resamples", type=_positive_int, default=RESAMPLES)
    p.add_argument("--draws", type=_positive_int, default=DRAWS)
    p.add_argument(
        "--bucket",
        choices=BUCKET_LABELS,
        default=FROZEN_LABEL,
        help="the ladder label row to re-run when no reader is given (default: the frozen label)",
    )
    p.add_argument(
        "--bucket-reader",
        "--caps-bucket-reader",
        dest="caps_bucket_reader",
        default=None,
        help="OFF by default. 'module:callable' returning the bucket LABEL (only it is printed)",
    )
    p.add_argument(
        "--label-only",
        action="store_true",
        help="with --bucket-reader: print the ladder label and exit (no simulation)",
    )
    return p.parse_args(argv)


def _load_reader(spec: str) -> Callable[[], str]:
    module_name, _, attr = spec.partition(":")
    reader = getattr(importlib.import_module(module_name), attr)
    if not callable(reader):
        raise CapsReadRefused("the caps reader is not callable")
    return reader


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.label_only:
            if not args.caps_bucket_reader:
                print("--label-only needs --bucket-reader", file=sys.stderr)
                return 2
            print(caps_bucket_label(_load_reader(args.caps_bucket_reader)))
            return 0
        refuse_window_path(args.cands)
        refuse_window_path(args.out)
        if args.extract:
            payload = extract_candidates(FIRST_DAY, LAST_DAY)
            args.cands.write_text(json.dumps(payload, indent=1) + "\n")
            days = payload["days"]
            total = sum(len(v) for v in days.values()) if isinstance(days, dict) else 0
            print(f"wrote {args.cands.name}: {total} candidates")
            return 0
        if args.caps_bucket_reader:
            label = caps_bucket_label(_load_reader(args.caps_bucket_reader))
            print(f"caps bucket label: {label}")
        else:
            label = canonical_label(args.bucket)
        if label == SENTINEL_LABEL:
            print("label above 0.50: K stays 1, no simulation")
            return 0
        result = run(args, label)
    except WindowDataRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except CapsReadRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
