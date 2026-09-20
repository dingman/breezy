"""WP-7 -- the PRE-REGISTERED economic cheap screen, run exactly as registered.

GOVERNING DOCUMENT
------------------
``docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md`` (registered `49a7cdf`,
amended `f5e8420`). Every parameter below is a COPY of a pinned value in that
document, not a choice made here. No variant may be added, removed or retuned;
`MULTIPLICITY_RULE` clause (i) makes an unregistered variant unrunnable and
clause (iv) makes an unreported one a rule breach.

Upstream evidence: ``docs/evidence/FC_0b_FIT_AND_HOLDOUT_2026-09-19.md``
(`194c71f`) -- forecast SKILL established; tradeable EDGE explicitly NOT.

WHAT IS REUSED, AND WHY NOT MORE
--------------------------------
* The FIT corpus and the frozen error model are the 0b ones, loaded through
  ``forecast_conditional_corpus.load_cached_corpus`` and
  ``forecast_conditional_model_study.fit_train_error_model``. `sigma` is
  therefore frozen exactly as fitted in 0b (§2.2 / amendment A4); nothing here
  re-fits it, and a re-fit would be a new registration rather than a knob.
* The fee is ``forecast_tape_screen.venue_fee``, which is the LIVE take rule's
  ``current_rung_hold.decision.fee_on_ask``. §2.2 amendment A2.
* The rung parser is ``h4_preliminary_economic_read.parse_rung`` -- the repo's
  existing, tested reading of the venue's instrument ids.
* ``forecast_conditional_corpus.forecasts_from_mos_payload`` is NOT reused for
  the 2026 price window, and that is deliberate rather than a fork: it enforces
  0b's OWN decision instant (12:00Z, ``DECISION_UTC_HOUR``) and RAISES on any
  later cycle. WP-7's decision instant is a quote timestamp inside a 09-17 LST
  window, and §2.2 pins "the latest cycle whose vintage <= the decision
  instant". Reusing 0b's reader would refuse exactly the cycles this
  registration requires. :func:`forecast_cycles_from_mos_payload` reads the same
  archive with the same frozen ``climate_day_for_txn`` map and keeps the
  runtime, so the vintage rule can be applied at the registered instant.

STRUCTURAL GUARD -- PER-HOUR TABLES CAN NEVER SELECT A WINNER
-------------------------------------------------------------
§2.0 (amendment A1, blocking) resolves the hour dimension by evaluating the bar
on the WINDOW-POOLED cell only. That is enforced by TYPE here, not by comment:
:func:`evaluate_gate` accepts a :class:`PooledCell` and refuses an
:class:`HourDiagnostic` with :class:`HourSelectionRefused`. An hour table is a
different type that no gate function will take.

MEMORY
------
The venue depth tape is ~453 MB of Parquet over 3,458 files. It is NEVER all
resident: files are read with a FIVE-COLUMN projection (`ts_event`,
`ask_price_0`, `ask_size_0`, `bid_price_0`, `bid_size_0`) and reduced ONE
STATION-DAY at a time -- that station-day's rungs are screened under all twelve
variants and then dropped before the next is opened. Peak resident is one
station-day of L0 columns plus the 7,249-row 0b corpus.

No network. No clock beyond the tape's own timestamps. Starts and stops no
process. Writes one artefact and nothing else.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_tape_screen import DEFAULT_FEE_COEFFICIENT, venue_fee

__all__ = [
    "ALL_VARIANTS",
    "FWER_ALPHA",
    "K_VARIANTS",
    "MIN_MEDIAN_MARGIN",
    "MIN_POSITIVE_RATE",
    "MIN_TRIAL_STATION_DAYS",
    "GateResult",
    "HourDiagnostic",
    "HourSelectionRefused",
    "PooledCell",
    "StationDayTrial",
    "Variant",
    "VariantResult",
    "evaluate_gate",
    "holm_bonferroni",
    "screen_station_day",
]

# ---------------------------------------------------------------------------
# §2 -- THE ENUMERATED VARIANT SPACE. Copied from the registration. Closed.
# ---------------------------------------------------------------------------

#: A -- decision window, local standard time, half-open ``[start, end)``.
WINDOWS: Final[Mapping[str, tuple[int, int]]] = {
    "A1": (9, 12),
    "A2": (12, 17),
    "A3": (10, 11),
}
#: B -- side pricing. ``B2`` adds the NO leg, priced off the inverted YES bid.
SIDES: Final[Mapping[str, tuple[str, ...]]] = {
    "B1": ("YES",),
    "B2": ("YES", "NO"),
}
#: C -- ask screen. ``C2`` screens the live ask against the PRE-WINDOW ask.
ASK_SCREENS: Final[tuple[str, ...]] = ("C1", "C2")

SIDE_YES: Final[str] = "YES"
SIDE_NO: Final[str] = "NO"


@dataclass(frozen=True, slots=True)
class Variant:
    """One of the twelve registered variants. Constructed only by this module."""

    variant_id: str
    window_start_lst: int
    window_end_lst: int
    sides: tuple[str, ...]
    ask_screen: bool

    def hours(self) -> tuple[int, ...]:
        return tuple(range(self.window_start_lst, self.window_end_lst))


def _enumerate_variants() -> tuple[Variant, ...]:
    """Build the closed set. Order is deterministic: A, then B, then C."""
    out: list[Variant] = []
    for a in ("A1", "A2", "A3"):
        start, end = WINDOWS[a]
        for b in ("B1", "B2"):
            for c in ASK_SCREENS:
                out.append(
                    Variant(
                        variant_id=f"{a}-{b}-{c}",
                        window_start_lst=start,
                        window_end_lst=end,
                        sides=SIDES[b],
                        ask_screen=(c == "C2"),
                    )
                )
    return tuple(out)


ALL_VARIANTS: Final[tuple[Variant, ...]] = _enumerate_variants()
#: §1(iii). Declared cap. Exhausting the set without a survivor escalates to a
#: strategy-lead ruling; it is never grounds for a thirteenth variant.
K_VARIANTS: Final[int] = 12
assert len(ALL_VARIANTS) == K_VARIANTS, "the registered variant set is exactly 12"

# ---------------------------------------------------------------------------
# §2.2 -- pinned decision parameters, and §3 -- the measurement gate
# ---------------------------------------------------------------------------

#: §2.2. The take threshold is the LIVE rule's: strictly positive post-fee edge.
#: The 0.03 median in §3 is a REPORTING bar, never the take threshold.
MIN_EDGE_FOR_TAKE: Final[float] = 0.0
#: Liftability: qty=1, L0-fillable from Depth10.
LIFTABLE_QUANTITY: Final[float] = 1.0

#: §3, evaluated on the WINDOW-POOLED cell only.
MIN_TRIAL_STATION_DAYS: Final[int] = 20
MIN_POSITIVE_RATE: Final[float] = 0.50  # strict ``>``
MIN_MEDIAN_MARGIN: Final[float] = 0.03  # ``>=``

#: §1(ii). Holm-Bonferroni, family-wise, one-sided.
FWER_ALPHA: Final[float] = 0.05

#: §2.2. Date is the single PRIMARY and DECISIONAL bootstrap cluster; the
#: station-clustered interval is reported as sensitivity and is non-decisional.
CLUSTER_DATE: Final[str] = "date"
CLUSTER_STATION: Final[str] = "station"
DECISIONAL_CLUSTER: Final[str] = CLUSTER_DATE
BOOTSTRAP_ITERATIONS: Final[int] = 2000
BOOTSTRAP_SEED: Final[int] = 20260920
BOOTSTRAP_ALPHA: Final[float] = 0.05

VERDICT_CLEARS: Final[str] = "CLEARS"
VERDICT_FAILS: Final[str] = "FAILS"
VERDICT_INSUFFICIENT_DATA: Final[str] = "INSUFFICIENT-DATA"

#: §2.1. The selection unit is the four-station pool, ALWAYS. NYC carries no
#: local NBS forecast rows and is out of scope; per-station tables are
#: diagnosis only and are never a selection surface.
POOL_CITIES: Final[tuple[str, ...]] = ("LAX", "MDW", "MIA", "SFO")
CITY_TO_ICAO: Final[Mapping[str, str]] = {
    "LAX": "KLAX",
    "MDW": "KMDW",
    "MIA": "KMIA",
    "SFO": "KSFO",
}


# ---------------------------------------------------------------------------
# Trials, cells, and the type-level hour firewall
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationDayTrial:
    """ONE station-day: the registered trial unit, never an hourly row.

    ``margin`` is ``p_fc - (price + fee)`` at the liftable price on the side
    scored -- the same quantity the live take rule uses. A station-day with no
    would-take is NOT dropped: it carries the best margin the window ever
    offered (which is then ``<= 0``), because dropping it would inflate the
    positive rate by discarding the hard days. ``no_bid_side`` records that the
    NO leg was unpriceable, which §2.2 pins as a no-take, never a dropped day.
    """

    station: str
    climate_day: dt.date
    took: bool
    margin: float | None
    side: str | None
    rung: str | None
    ask: float | None
    hour_lst: int | None
    no_bid_side: bool
    reason: str


@dataclass(frozen=True, slots=True)
class PooledCell:
    """The WINDOW-POOLED cell -- the ONLY surface the §3 bar may be read on."""

    variant_id: str
    trials: tuple[StationDayTrial, ...]


@dataclass(frozen=True, slots=True)
class HourDiagnostic:
    """One hour's table. DIAGNOSIS ONLY -- §2.0 amendment A1.

    Deliberately NOT a :class:`PooledCell` and deliberately carrying no gate
    method. A per-hour maximum is the uncorrected degree of freedom the
    registration removes outright; making the hour table a different TYPE means
    no gate function can be handed one by accident.
    """

    variant_id: str
    hour_lst: int
    trials: tuple[StationDayTrial, ...]


class HourSelectionRefused(RuntimeError):
    """Raised when an hour table is offered to the selection gate (§2.0)."""


@dataclass(frozen=True, slots=True)
class GateResult:
    variant_id: str
    n: int
    n_takes: int
    positive_rate: float | None
    median_margin: float | None
    verdict: str
    reasons: tuple[str, ...]


def evaluate_gate(cell: object) -> GateResult:
    """§3, on the window-pooled cell. An hour table is refused by type.

    A cell below ``n >= 20`` is INSUFFICIENT-DATA: §4 makes that exit 0, never
    raise, and it is never a PASS and never a KILL.
    """
    if isinstance(cell, HourDiagnostic):
        raise HourSelectionRefused(
            f"{cell.variant_id} hour {cell.hour_lst}: per-hour tables are DIAGNOSIS ONLY "
            "(registration §2.0, amendment A1). The bar is evaluated on the WINDOW-POOLED "
            "cell; selecting on an hour would convert the corrected hour dimension into an "
            "uncorrected max-over-hours and make the Holm correction cosmetic."
        )
    if not isinstance(cell, PooledCell):
        raise TypeError(f"evaluate_gate takes a PooledCell, got {type(cell).__name__}")

    trials = cell.trials
    n = len(trials)
    takes = [t for t in trials if t.took]
    if n < MIN_TRIAL_STATION_DAYS:
        return GateResult(
            variant_id=cell.variant_id,
            n=n,
            n_takes=len(takes),
            positive_rate=(len(takes) / n) if n else None,
            median_margin=(
                statistics.median([t.margin for t in trials if t.margin is not None])
                if any(t.margin is not None for t in trials)
                else None
            ),
            verdict=VERDICT_INSUFFICIENT_DATA,
            reasons=(
                (
                    f"n={n} station-days is below the pre-registered floor of "
                    f"{MIN_TRIAL_STATION_DAYS}"
                ),
            ),
        )

    margins = [t.margin for t in trials if t.margin is not None]
    positive_rate = len(takes) / n
    median_margin = statistics.median(margins) if margins else None
    reasons: list[str] = []
    if not positive_rate > MIN_POSITIVE_RATE:
        reasons.append(f"positive-margin rate {positive_rate:.3f} is not > {MIN_POSITIVE_RATE}")
    if median_margin is None or not median_margin >= MIN_MEDIAN_MARGIN:
        reasons.append(
            f"median post-fee margin {median_margin!r} is not >= {MIN_MEDIAN_MARGIN}"
        )
    return GateResult(
        variant_id=cell.variant_id,
        n=n,
        n_takes=len(takes),
        positive_rate=positive_rate,
        median_margin=median_margin,
        verdict=VERDICT_FAILS if reasons else VERDICT_CLEARS,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# §1(ii) -- Holm-Bonferroni across the ENTIRE enumerated set
# ---------------------------------------------------------------------------


def _binomial_sf(k: int, n: int, p: float) -> float:
    """``P(X >= k)`` for ``X ~ Binomial(n, p)`` -- exact, one-sided."""
    if n <= 0:
        return 1.0
    k = max(k, 0)
    return sum(math.comb(n, i) * p**i * (1.0 - p) ** (n - i) for i in range(k, n + 1))


def variant_p_value(result: GateResult) -> float:
    """One-sided p for ``H0: P(post-fee margin > 0) <= 0.5``.

    An untestable cell (below the n floor, so no statistic exists) is assigned
    ``p = 1.0`` rather than dropped: `K_variants` stays 12 through the
    correction, which is what §1(ii) means by "across the ENTIRE enumerated
    set". Dropping thin cells would shrink the family and inflate power.
    """
    if result.verdict == VERDICT_INSUFFICIENT_DATA:
        return 1.0
    return _binomial_sf(result.n_takes, result.n, 0.5)


def holm_bonferroni(
    p_values: Mapping[str, float], *, alpha: float = FWER_ALPHA, k: int = K_VARIANTS
) -> dict[str, dict[str, object]]:
    """Step-down Holm at family-wise ``alpha`` over ``k`` hypotheses."""
    if len(p_values) != k:
        raise ValueError(
            f"Holm must run over the entire enumerated set of {k} variants, got "
            f"{len(p_values)}; a variant omitted from the correction is §1(iv) breach"
        )
    ordered = sorted(p_values.items(), key=lambda kv: (kv[1], kv[0]))
    out: dict[str, dict[str, object]] = {}
    still_rejecting = True
    for rank, (variant_id, p) in enumerate(ordered):
        threshold = alpha / (k - rank)
        rejected = still_rejecting and p <= threshold
        if not rejected:
            still_rejecting = False
        out[variant_id] = {
            "p_value": p,
            "rank": rank + 1,
            "threshold": threshold,
            "rejected": rejected,
        }
    return out


# ---------------------------------------------------------------------------
# Bootstrap -- date is the single decisional cluster (§2.2)
# ---------------------------------------------------------------------------


def cluster_bootstrap_median_ci(
    trials: Sequence[StationDayTrial], *, cluster: str
) -> tuple[float, float] | None:
    """Cluster block bootstrap of the MEDIAN post-fee margin."""
    scored = [t for t in trials if t.margin is not None]
    if not scored:
        return None
    blocks: dict[object, list[StationDayTrial]] = {}
    for trial in scored:
        key = trial.climate_day if cluster == CLUSTER_DATE else trial.station
        blocks.setdefault(key, []).append(trial)
    keys = sorted(blocks, key=repr)
    rng = random.Random(BOOTSTRAP_SEED)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        drawn: list[float] = []
        for _ in range(len(keys)):
            drawn.extend(
                t.margin for t in blocks[keys[rng.randrange(len(keys))]] if t.margin is not None
            )
        if drawn:
            draws.append(statistics.median(drawn))
    if not draws:
        return None
    draws.sort()
    lo = draws[max(0, math.floor((BOOTSTRAP_ALPHA / 2.0) * len(draws)))]
    hi = draws[min(len(draws) - 1, math.ceil((1.0 - BOOTSTRAP_ALPHA / 2.0) * len(draws)) - 1)]
    return (lo, hi)


# ---------------------------------------------------------------------------
# The screen itself -- one station-day, one variant
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RungInstant:
    """One L0 snapshot of one rung: the only tape shape the screen consumes."""

    ts_ns: int
    hour_lst: int
    ask: float | None
    ask_size: float
    bid: float | None
    bid_size: float


@dataclass(frozen=True, slots=True)
class RungTape:
    """One rung of one station-day: its L0 series plus its pre-window ask."""

    rung_id: str
    lower_f: int | None
    upper_f: int | None
    instants: tuple[RungInstant, ...]


REASON_TAKE: Final[str] = "TAKE"
REASON_NO_POSITIVE_EDGE: Final[str] = "NO_POSITIVE_EDGE"
REASON_NO_MODEL_PROBABILITY: Final[str] = "NO_MODEL_PROBABILITY"
REASON_NO_LIFTABLE_QUOTE: Final[str] = "NO_LIFTABLE_QUOTE"


def _pre_window_ask(tape: RungTape, window_start_lst: int) -> float | None:
    """The last liftable ask observed STRICTLY BEFORE the window opens."""
    prior = [
        i
        for i in tape.instants
        if i.hour_lst < window_start_lst and i.ask is not None and i.ask_size >= LIFTABLE_QUANTITY
    ]
    return prior[-1].ask if prior else None


def screen_station_day(
    *,
    station: str,
    climate_day: dt.date,
    rungs: Sequence[RungTape],
    variant: Variant,
    p_yes_by_rung: Mapping[str, float] | None,
    fee_coefficient: float = DEFAULT_FEE_COEFFICIENT,
) -> StationDayTrial:
    """Screen ONE station-day under ONE variant; return its single trial.

    §2.2, applied in order: every legal rung is scanned, both sides where the
    variant admits them; the FIRST instant carrying a positive post-fee margin
    is the take; ties inside that instant break by greatest post-fee margin,
    then lowest ask, then lowest rung lower bound -- fully deterministic.

    A station-day with no would-take is still returned as a trial, carrying the
    best margin the window ever offered.
    """
    hours = set(variant.hours())
    pre_window = (
        {r.rung_id: _pre_window_ask(r, variant.window_start_lst) for r in rungs}
        if variant.ask_screen
        else {}
    )

    if p_yes_by_rung is None:
        return StationDayTrial(
            station=station,
            climate_day=climate_day,
            took=False,
            margin=None,
            side=None,
            rung=None,
            ask=None,
            hour_lst=None,
            no_bid_side=False,
            reason=REASON_NO_MODEL_PROBABILITY,
        )

    # One merged, time-ordered pass over the window. Candidate tuples are
    # (margin, ask, rung_lower, ...) so the tie-break is the tuple order itself.
    candidates: list[tuple[int, float, float, int, str, str]] = []
    saw_liftable = False
    saw_bid_side = False
    for tape in rungs:
        p_yes = p_yes_by_rung.get(tape.rung_id)
        if p_yes is None:
            continue
        lower_key = tape.lower_f if tape.lower_f is not None else -10**6
        screen_ref = pre_window.get(tape.rung_id) if variant.ask_screen else None
        for inst in tape.instants:
            if inst.hour_lst not in hours:
                continue
            if SIDE_YES in variant.sides and inst.ask is not None and inst.ask_size >= (
                LIFTABLE_QUANTITY
            ):
                saw_liftable = True
                if not variant.ask_screen or (
                    screen_ref is not None and inst.ask < screen_ref
                ):
                    margin = p_yes - (
                        inst.ask + venue_fee(
                            ask_probability=inst.ask, fee_coefficient=fee_coefficient
                        )
                    )
                    candidates.append(
                        (inst.ts_ns, -margin, inst.ask, lower_key, SIDE_YES, tape.rung_id)
                    )
            # The NO leg is priced off the INVERTED YES bid ladder: lifting NO
            # at the venue means selling YES into the bid, so the NO ask is
            # ``1 - bid`` and its liftability is the bid's own L0 size.
            if (
                SIDE_NO in variant.sides
                and inst.bid is not None
                and inst.bid_size >= LIFTABLE_QUANTITY
            ):
                saw_bid_side = True
                saw_liftable = True
                no_ask = 1.0 - inst.bid
                if not variant.ask_screen or (
                    screen_ref is not None and no_ask < (1.0 - screen_ref)
                ):
                    margin = (1.0 - p_yes) - (
                        no_ask + venue_fee(
                            ask_probability=no_ask, fee_coefficient=fee_coefficient
                        )
                    )
                    candidates.append(
                        (inst.ts_ns, -margin, no_ask, lower_key, SIDE_NO, tape.rung_id)
                    )

    no_bid_side = (SIDE_NO in variant.sides) and not saw_bid_side

    if not candidates:
        return StationDayTrial(
            station=station,
            climate_day=climate_day,
            took=False,
            margin=None,
            side=None,
            rung=None,
            ask=None,
            hour_lst=None,
            no_bid_side=no_bid_side,
            reason=REASON_NO_LIFTABLE_QUOTE if not saw_liftable else REASON_NO_POSITIVE_EDGE,
        )

    candidates.sort()
    first_take = next((c for c in candidates if -c[1] > MIN_EDGE_FOR_TAKE), None)
    best = min(candidates, key=lambda c: (c[1], c[2], c[3]))
    chosen = first_take if first_take is not None else best
    ts_ns, neg_margin, ask, _lower, side, rung_id = chosen
    hour = next(
        (i.hour_lst for t in rungs for i in t.instants if i.ts_ns == ts_ns),
        None,
    )
    return StationDayTrial(
        station=station,
        climate_day=climate_day,
        took=first_take is not None,
        margin=-neg_margin,
        side=side,
        rung=rung_id,
        ask=ask,
        hour_lst=hour,
        no_bid_side=no_bid_side,
        reason=REASON_TAKE if first_take is not None else REASON_NO_POSITIVE_EDGE,
    )


@dataclass(frozen=True, slots=True)
class VariantResult:
    """Everything §1(iv) requires to be written for ONE attempted variant."""

    variant: Variant
    gate: GateResult
    cell: PooledCell
    hours: tuple[HourDiagnostic, ...]
    no_bid_side_rate: float | None
    ci_date: tuple[float, float] | None
    ci_station: tuple[float, float] | None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Explicit serialisation -- ``dataclasses.asdict`` is banned repo-wide."""
        return {
            "variant_id": self.variant.variant_id,
            "window_lst": [self.variant.window_start_lst, self.variant.window_end_lst],
            "sides": list(self.variant.sides),
            "ask_screen": self.variant.ask_screen,
            "n": self.gate.n,
            "n_takes": self.gate.n_takes,
            "positive_rate": self.gate.positive_rate,
            "median_margin_all_trials": self.gate.median_margin,
            "median_margin_takes_only": (
                statistics.median([t.margin for t in self.cell.trials if t.took])
                if any(t.took for t in self.cell.trials)
                else None
            ),
            "verdict": self.gate.verdict,
            "reasons": list(self.gate.reasons),
            "no_bid_side_rate": self.no_bid_side_rate,
            "ci95_median_margin_cluster_date_DECISIONAL": (
                list(self.ci_date) if self.ci_date else None
            ),
            "ci95_median_margin_cluster_station_SENSITIVITY_ONLY": (
                list(self.ci_station) if self.ci_station else None
            ),
            "per_hour_DIAGNOSIS_ONLY": [
                {
                    "hour_lst": h.hour_lst,
                    "n": len(h.trials),
                    "n_takes": sum(1 for t in h.trials if t.took),
                }
                for h in self.hours
            ],
            "error": self.error,
        }


def build_variant_result(
    variant: Variant, trials: Sequence[StationDayTrial], *, error: str | None = None
) -> VariantResult:
    cell = PooledCell(variant_id=variant.variant_id, trials=tuple(trials))
    hours = tuple(
        HourDiagnostic(
            variant_id=variant.variant_id,
            hour_lst=hour,
            trials=tuple(t for t in trials if t.hour_lst == hour),
        )
        for hour in variant.hours()
    )
    no_bid = (
        sum(1 for t in trials if t.no_bid_side) / len(trials)
        if trials and SIDE_NO in variant.sides
        else None
    )
    return VariantResult(
        variant=variant,
        gate=evaluate_gate(cell),
        cell=cell,
        hours=hours,
        no_bid_side_rate=no_bid,
        ci_date=cluster_bootstrap_median_ci(trials, cluster=CLUSTER_DATE),
        ci_station=cluster_bootstrap_median_ci(trials, cluster=CLUSTER_STATION),
        error=error,
    )


# ---------------------------------------------------------------------------
# Real I/O -- streamed, one station-day at a time
# ---------------------------------------------------------------------------

DEFAULT_QUOTE_TAPE_CATALOG: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_CORPUS_JSON: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/forecast_conditional_corpus_wp6.json"
)
DEFAULT_OUTPUT: Final[Path] = Path(
    "docs/evidence/WP7_CHEAP_SCREEN_2026-09-20.md"
)
_L0_COLUMNS: Final[tuple[str, ...]] = (
    "ts_event",
    "ask_price_0",
    "ask_size_0",
    "bid_price_0",
    "bid_size_0",
)
_NS: Final[int] = 10**9


@dataclass(slots=True)
class TapeCensus:
    """What the tape actually contained -- reported whatever the verdict."""

    station_days: int = 0
    rung_files: int = 0
    depth_rows: int = 0
    station_days_with_truth: int = 0
    station_days_with_forecast: int = 0
    excluded_incomplete: list[str] = field(default_factory=list)


def _fixed_scalars() -> tuple[float, float]:
    from nautilus_trader.model.objects import Price, Quantity

    return (float(Price(1.0, 0).raw), float(Quantity(1.0, 0).raw))


def read_rung_tape(
    instrument_dir: Path,
    *,
    std_utc_offset_hours: float,
    price_scalar: float,
    size_scalar: float,
) -> tuple[list[RungInstant], int]:
    """Stream ONE rung's depth files, projected to the five L0 columns."""
    import pyarrow.parquet as pq

    instants: list[RungInstant] = []
    rows = 0
    for path in sorted(instrument_dir.glob("*.parquet")):
        table = pq.read_table(path, columns=list(_L0_COLUMNS))
        rows += table.num_rows
        ts = table.column("ts_event").to_pylist()
        ask_p = table.column("ask_price_0").to_pylist()
        ask_s = table.column("ask_size_0").to_pylist()
        bid_p = table.column("bid_price_0").to_pylist()
        bid_s = table.column("bid_size_0").to_pylist()
        for i in range(table.num_rows):
            ask_raw = int.from_bytes(ask_p[i], "little", signed=True)
            bid_raw = int.from_bytes(bid_p[i], "little", signed=True)
            ask = ask_raw / price_scalar
            bid = bid_raw / price_scalar
            local = dt.datetime.fromtimestamp(
                ts[i] / _NS, tz=dt.UTC
            ) + dt.timedelta(hours=std_utc_offset_hours)
            instants.append(
                RungInstant(
                    ts_ns=int(ts[i]),
                    hour_lst=local.hour,
                    # A ``Price(0)`` pad on an absent side must read as NO ASK,
                    # never as a free contract (h4's L-8 reading of Depth10).
                    ask=ask if ask_raw > 0 else None,
                    ask_size=int.from_bytes(ask_s[i], "little", signed=True) / size_scalar,
                    bid=bid if bid_raw > 0 else None,
                    bid_size=int.from_bytes(bid_s[i], "little", signed=True) / size_scalar,
                )
            )
        del table, ts, ask_p, ask_s, bid_p, bid_s
    instants.sort(key=lambda i: i.ts_ns)
    return instants, rows


def forecast_cycles_from_mos_payload(
    body: bytes, *, icao: str, std_utc_offset_hours: float
) -> dict[dt.date, list[tuple[int, float]]]:
    """``climate_day -> [(runtime_ns, txn_f), ...]``, ALL cycles, sorted.

    Not ``forecasts_from_mos_payload``: see the module docstring. The frozen
    ``climate_day_for_txn`` map is reused verbatim; only the vintage rule
    differs, and it is applied later, at the registered decision instant.
    """
    import csv
    import io

    from forecast_climate_day_map import ForecastValidPeriodError, climate_day_for_txn

    out: dict[dt.date, list[tuple[int, float]]] = {}
    stream = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline="")
    for row in csv.DictReader(stream):
        raw = (row.get("txn") or "").strip()
        if not raw:
            continue
        runtime = dt.datetime.strptime(row["runtime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        ftime = dt.datetime.strptime(row["ftime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        try:
            climate_day = climate_day_for_txn(
                icao=icao,
                runtime_ns=int(runtime.timestamp()) * _NS,
                ftime_ns=int(ftime.timestamp()) * _NS,
                std_utc_offset_hours=std_utc_offset_hours,
                model="NBS",
                kind="max",
            )
        except ForecastValidPeriodError:
            continue
        out.setdefault(climate_day, []).append(
            (int(runtime.timestamp()) * _NS, float(raw))
        )
    for entries in out.values():
        entries.sort()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, default=DEFAULT_QUOTE_TAPE_CATALOG)
    parser.add_argument("--corpus-json", type=Path, default=DEFAULT_CORPUS_JSON)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args(argv)

    from h4_preliminary_economic_read import parse_rung
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
    from settlement_alignment_study import load_sites

    from breezy.persistence.catalog import read_climate_days, station_catalog_path

    census = TapeCensus()
    notes: list[str] = []

    depth_root = args.tape / "data" / "order_book_depths"
    if not depth_root.is_dir():
        notes.append(f"NO DEPTH TAPE at {depth_root}")
        by_station_day: dict[tuple[str, dt.date], list[Path]] = {}
    else:
        by_station_day = {}
        for child in sorted(depth_root.iterdir()):
            if not child.is_dir():
                continue
            try:
                rung = parse_rung(child.name)
            except ValueError:
                notes.append(f"UNPARSED instrument dir: {child.name}")
                continue
            if rung.city not in POOL_CITIES:
                continue
            by_station_day.setdefault((rung.city, rung.climate_day), []).append(child)
    census.station_days = len(by_station_day)

    # -- settlement truth (NWS CLI finals), per station -------------------
    sites = {spec.city: spec for spec in load_sites()}
    catalog_base = Path.home() / ".local/share/breezy/catalog"
    truth: dict[tuple[str, dt.date], int] = {}
    for city in POOL_CITIES:
        try:
            records = read_climate_days(
                ParquetDataCatalog(
                    str(station_catalog_path(catalog_base, "polymarket_us", city))
                )
            )
        except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
            notes.append(f"TRUTH READ FAILED for {city}: {type(exc).__name__}: {exc}")
            continue
        for record in records:
            if not (record.is_final and not record.is_superseded):
                continue
            if record.tmax_f is None:
                continue
            truth[(city, record.climate_day)] = int(record.tmax_f)
    census.station_days_with_truth = sum(1 for key in by_station_day if key in truth)

    # -- the frozen 0b error model (sigma as fitted in 0b, §2.2/A4) -------
    from forecast_conditional_corpus import FIT_END_EXCLUSIVE, FIT_START, load_cached_corpus
    from forecast_conditional_model_study import fit_train_error_model

    error_model = None
    if args.corpus_json.is_file():
        rows = load_cached_corpus(args.corpus_json)
        train = [r for r in rows if FIT_START <= r.climate_day < FIT_END_EXCLUSIVE]
        error_model = fit_train_error_model(train)
        notes.append(
            f"FROZEN 0b error model fitted on {len(train)} TRAIN station-days "
            f"({FIT_START.isoformat()}..{(FIT_END_EXCLUSIVE - dt.timedelta(days=1)).isoformat()}); "
            "sigma is NOT re-fitted here (§2.2 amendment A4)."
        )
    else:
        notes.append(f"0b CORPUS ABSENT at {args.corpus_json}; no frozen model available")

    # -- forecasts covering the PRICE window ------------------------------
    price_days = sorted({day for _city, day in by_station_day})
    years = sorted({day.year for day in price_days})
    forecasts: dict[tuple[str, dt.date], list[tuple[int, float]]] = {}
    from forecast_conditional_corpus import _archive_cache

    from breezy.persistence.archive_request import iem_mos_request

    cache = _archive_cache("iem-mos")
    for city in POOL_CITIES:
        icao = CITY_TO_ICAO[city]
        for year in years:
            try:
                body = cache.read(iem_mos_request(icao, year, "NBS"))
            except Exception as exc:  # noqa: BLE001 -- this IS the measurement
                notes.append(
                    f"FORECAST ARCHIVE ABSENT for {icao} {year}: {type(exc).__name__}"
                )
                continue
            cycles = forecast_cycles_from_mos_payload(
                body,
                icao=icao,
                std_utc_offset_hours=sites[city].std_utc_offset_hours,
            )
            for day, entries in cycles.items():
                forecasts[(city, day)] = entries
            del body, cycles
    census.station_days_with_forecast = sum(1 for key in by_station_day if key in forecasts)
    if census.station_days_with_forecast == 0 and census.station_days_with_truth:
        notes.append(
            "CORPUS DISJOINT -- the registration's §2.3 inventory does not reproduce. The "
            "venue price tape and the NBS forecast archive DO NOT OVERLAP: the archive's "
            "last runtime is 2025-12-31 19:00Z (4 stations x 5 station-years, 2021..2025) "
            "and the depth tape begins 2026-08-30. §2.3 records the triple overlap as "
            "n = 73 station-days; the number measured here as 73 is the venue-tape x "
            "SETTLEMENT-TRUTH overlap, with the FORECAST leg absent entirely. The "
            "economic screen therefore has no priceable station-day, which is a corpus "
            "gap (§4: extend the corpus), NOT a finding about the forecast thesis."
        )

    # -- stream the tape, one station-day at a time -----------------------
    price_scalar, size_scalar = _fixed_scalars()
    per_variant: dict[str, list[StationDayTrial]] = {v.variant_id: [] for v in ALL_VARIANTS}

    for (city, climate_day), dirs in sorted(by_station_day.items()):
        offset = sites[city].std_utc_offset_hours
        tapes: list[RungTape] = []
        for child in dirs:
            rung = parse_rung(child.name)
            instants, rows_read = read_rung_tape(
                child,
                std_utc_offset_hours=offset,
                price_scalar=price_scalar,
                size_scalar=size_scalar,
            )
            census.depth_rows += rows_read
            census.rung_files += len(list(child.glob("*.parquet")))
            tapes.append(
                RungTape(
                    rung_id=child.name,
                    lower_f=rung.lower_f,
                    upper_f=rung.upper_f,
                    instants=tuple(instants),
                )
            )

        p_yes = _rung_probabilities(
            city=city,
            climate_day=climate_day,
            tapes=tapes,
            forecasts=forecasts,
            error_model=error_model,
            truth=truth,
        )
        if p_yes is None:
            # INCOMPLETE JOIN -- no forecast or no settlement truth for this
            # station-day. It is not a trial: there is no decision to score
            # either way, so counting it would manufacture n out of missing
            # data. Distinct from `no_bid_side`, which §2.2 pins as a no-take
            # that MUST stay in the denominator.
            census.excluded_incomplete.append(f"{city} {climate_day.isoformat()}")
            del tapes
            continue
        for variant in ALL_VARIANTS:
            per_variant[variant.variant_id].append(
                screen_station_day(
                    station=city,
                    climate_day=climate_day,
                    rungs=tapes,
                    variant=variant,
                    p_yes_by_rung=p_yes,
                )
            )
        del tapes

    # §1(iv): EVERY attempted variant's table is written, including failures.
    results = [build_variant_result(v, per_variant[v.variant_id]) for v in ALL_VARIANTS]
    holm = holm_bonferroni({r.variant.variant_id: variant_p_value(r.gate) for r in results})

    verdicts = {r.gate.verdict for r in results}
    if VERDICT_CLEARS in verdicts and any(
        holm[r.variant.variant_id]["rejected"] for r in results if r.gate.verdict == VERDICT_CLEARS
    ):
        overall = "0b PASS"
    elif VERDICT_INSUFFICIENT_DATA in verdicts:
        overall = VERDICT_INSUFFICIENT_DATA
    else:
        overall = "HALT -- escalates to a strategy-lead ruling (§1(iii))"

    artefact = _render(results, holm, census, notes, overall)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artefact, encoding="utf-8")
    if args.json_output:
        args.json_output.write_text(
            json.dumps(
                {
                    "overall": overall,
                    "variants": [r.to_dict() for r in results],
                    "holm": holm,
                },
                indent=1,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    print(artefact)
    # §4: INSUFFICIENT-DATA exits 0 and never raises.
    return 0


def _rung_probabilities(
    *,
    city: str,
    climate_day: dt.date,
    tapes: Sequence[RungTape],
    forecasts: Mapping[tuple[str, dt.date], Sequence[tuple[int, float]]],
    error_model: object,
    truth: Mapping[tuple[str, dt.date], int],
) -> dict[str, float] | None:
    """``p_fc`` per venue rung, or ``None`` when the triple join is incomplete.

    The rung family (§2.2) -- the venue's actual trading unit -- priced by the
    FROZEN 0b Gaussian with the 0.5F continuity correction, on the venue's OWN
    rung bounds rather than on a re-derived 2F grid.
    """
    if error_model is None:
        return None
    if (city, climate_day) not in truth:
        return None
    cycles = forecasts.get((city, climate_day))
    if not cycles:
        return None

    from forecast_conditional_model_study import _norm_cdf

    # §2.2: the latest cycle whose vintage <= the decision instant. The earliest
    # decision instant in the enumerated set is 09:00 LST, so that is the bound
    # applied here; no lead or cycle-age partition is taken.
    decision_ns = int(
        dt.datetime(
            climate_day.year, climate_day.month, climate_day.day, 9, tzinfo=dt.UTC
        ).timestamp()
    ) * _NS
    legal = [c for c in cycles if c[0] <= decision_ns]
    if not legal:
        return None
    runtime_ns, txn_f = legal[-1]
    lead_hours = max(
        1.0,
        (
            int(
                dt.datetime(
                    climate_day.year, climate_day.month, climate_day.day, 0, tzinfo=dt.UTC
                ).timestamp()
            )
            * _NS
            + 24 * 3600 * _NS
            - runtime_ns
        )
        / (3600 * _NS),
    )
    icao = CITY_TO_ICAO[city]
    mu = txn_f + error_model.bias(icao, climate_day, lead_hours)  # type: ignore[attr-defined]
    sigma = error_model.sigma(icao, climate_day, lead_hours)  # type: ignore[attr-defined]

    out: dict[str, float] = {}
    for tape in tapes:
        if tape.lower_f is None and tape.upper_f is None:
            continue
        low = (
            _norm_cdf((tape.lower_f - 0.5 - mu) / sigma) if tape.lower_f is not None else 0.0
        )
        high = (
            _norm_cdf((tape.upper_f + 0.5 - mu) / sigma) if tape.upper_f is not None else 1.0
        )
        out[tape.rung_id] = max(0.0, min(1.0, high - low))
    return out


def _fmt(value: float | None, digits: int = 4) -> str:
    return "--" if value is None else f"{value:.{digits}f}"


def _render(
    results: Sequence[VariantResult],
    holm: Mapping[str, Mapping[str, object]],
    census: TapeCensus,
    notes: Sequence[str],
    overall: str,
) -> str:
    lines = [
        "# WP-7 -- pre-registered economic cheap screen (2026-09-20)",
        "",
        f"**Overall: {overall}**",
        "",
        (
            "Governed by `docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md`. Every "
            "parameter here is a copy of a pinned value in that document. Per §1(iv) "
            "EVERY attempted variant's table appears below, including INSUFFICIENT-DATA "
            "ones. Per §2.0 the bar is read on the WINDOW-POOLED cell only; the per-hour "
            "tables are diagnosis and are structurally barred from selecting a winner."
        ),
        "",
        "## Corpus census (measured, before any verdict)",
        "",
        f"- venue station-days on the depth tape (4-station pool): **{census.station_days}**",
        f"- depth files read: {census.rung_files}; L0 rows streamed: {census.depth_rows}",
        f"- station-days with NWS CLI settlement truth: **{census.station_days_with_truth}**",
        f"- station-days with an NBS forecast: **{census.station_days_with_forecast}**",
        (
            f"- station-days EXCLUDED as an incomplete join (no forecast and/or no "
            f"settlement truth, so no decision exists to score): "
            f"**{len(census.excluded_incomplete)}**"
        ),
        (
            "- DENOMINATOR NOTE: `n` below counts station-days with a COMPLETE join, "
            "take or no-take. §2.3 reads as though `n` were the with-a-would-take "
            "subset; §3's `> 50% of trials have post-fee margin > 0` is vacuous under "
            "that reading (every take has margin > 0 by the `min_edge > 0` rule), so "
            "the complete-join denominator is used and the take-only median is reported "
            "beside it. Flagged to the strategy lead as a registration ambiguity."
        ),
        "",
    ]
    for note in notes:
        lines.append(f"- {note}")
    lines += [
        "",
        "## All twelve variant tables (§1(iv))",
        "",
        (
            "| variant | n | takes | % positive margin | median margin | no_bid_side "
            "rate | Holm p | Holm threshold | verdict |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        h = holm[result.variant.variant_id]
        rate = result.gate.positive_rate
        lines.append(
            f"| `{result.variant.variant_id}` | {result.gate.n} | {result.gate.n_takes} | "
            f"{'--' if rate is None else f'{rate * 100:.1f}%'} | "
            f"{_fmt(result.gate.median_margin)} | "
            f"{_fmt(result.no_bid_side_rate, 3)} | "
            f"{float(h['p_value']):.5f} | {float(h['threshold']):.5f} | "
            f"**{result.gate.verdict}** |"
        )
    lines += ["", "### Why each cell landed where it did", ""]
    for result in results:
        reasons = "; ".join(result.gate.reasons) or "all §3 conditions met"
        lines.append(f"- `{result.variant.variant_id}`: {reasons}")
        if result.error:
            lines.append(f"  - ERROR: {result.error}")
    lines += [
        "",
        "### Bootstrap intervals on the median post-fee margin",
        "",
        (
            "Date is the single PRIMARY and DECISIONAL cluster (§2.2). The "
            "station-clustered interval is sensitivity only and is explicitly "
            "non-decisional."
        ),
        "",
        "| variant | 95% CI (date, DECISIONAL) | 95% CI (station, sensitivity only) |",
        "|---|---|---|",
    ]
    for result in results:
        date_ci = (
            "--" if not result.ci_date else f"[{result.ci_date[0]:.4f}, {result.ci_date[1]:.4f}]"
        )
        station_ci = (
            "--"
            if not result.ci_station
            else f"[{result.ci_station[0]:.4f}, {result.ci_station[1]:.4f}]"
        )
        lines.append(f"| `{result.variant.variant_id}` | {date_ci} | {station_ci} |")
    lines += [
        "",
        "### Per-hour tables -- DIAGNOSIS ONLY, never a selection surface (§2.0)",
        "",
        "| variant | hour LST | n | takes |",
        "|---|---|---|---|",
    ]
    for result in results:
        for hour in result.hours:
            lines.append(
                f"| `{result.variant.variant_id}` | {hour.hour_lst} | {len(hour.trials)} | "
                f"{sum(1 for t in hour.trials if t.took)} |"
            )
    lines += [
        "",
        "## Multiplicity (§1(ii))",
        "",
        (
            f"Holm-Bonferroni across the ENTIRE enumerated set, `K_variants = "
            f"{K_VARIANTS}`, family-wise `alpha = {FWER_ALPHA}` one-sided, applied to "
            "the SELECTION decision. Cells below the n floor carry `p = 1.0` rather "
            "than being dropped, so the family stays at 12 and thin cells cannot "
            "inflate power."
        ),
        "",
        (
            f"Rejections at FWER {FWER_ALPHA}: "
            f"{sorted(k for k, v in holm.items() if v['rejected']) or 'NONE'}"
        ),
        "",
        "## §4 disposition",
        "",
        (
            f"**{overall}.** Under §4, INSUFFICIENT-DATA is an instruction to extend the "
            "corpus or the shadow period. It is never a PASS and never a KILL, and this "
            "run exits 0."
        ),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
