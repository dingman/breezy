"""LAT-1 scorer core: markout maths, event scoring, census, statistics and stage runners.

Split from ``nbp_revision_latency`` (the CLI shell). Pure over an injected station-day loader."""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from decimal import Decimal
from typing import Any, Final

from breezy.analysis.nbp_calibration import cluster_bootstrap_draws, percentile_interval
from breezy.analysis.release_timing import EventObservation
from breezy.analysis.revision_latency import (
    CI_ALPHA,
    KILL_BOOTSTRAP_DRAWS,
    KILL_SEED,
    SEARCH_END,
    STAGE1_FRAMING,
    KillRow,
    TauCycle,
    TauReport,
    VariantSummary,
    aligned_mark_change,
    assert_guard_3,
    assert_guard_4,
    assert_guard_7,
    assert_guard_8,
    assert_guard_10,
    assert_guard_11,
    derive_tau,
    fraction_of_move,
    kill_cost,
    mechanism_slope_ci,
    missing_attribution,
    placebo_instants,
    rung_deltas,
    select,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactUnknownVersionError,
    LiveCalibration,
)
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker.pno_store import VectorChain
from breezy.strategy.weather_common.revision_gate import (
    NS,
    W_NS,
    BookRow,
    BookSeries,
    ExitBid,
    GapSpan,
    MissingClass,
    SignedBands,
    decision_instant,
    first_bid_in_window,
    is_missing,
    mid,
    signed_bands,
)
from scripts.analysis.nbp_market_comparison import is_inside_nominal_permit
from scripts.analysis.p2_nbp_ask_murphy import cash_taker_fee_usd

L_PRIMARY_NS: Final[int] = 300 * NS
L_ALT_NS: Final[int] = 120 * NS
X_PRIMARY_NS: Final[int] = 60 * 60 * NS
X_SHORT_NS: Final[int] = 15 * 60 * NS
X_LONG_NS: Final[int] = 180 * 60 * NS
ASK_CAP: Final[float] = 0.97
RULE_B_SHARE: Final[float] = 0.5
STRESS_TICK: Final[float] = 0.01
PRICE_CEILING: Final[float] = 0.99
PRE_RELEASE_SHIFT_NS: Final[int] = 90 * 60 * NS
STAGE1_SEED: Final[int] = 20260929
MECHANISM_GRID_NS: Final[tuple[int, ...]] = tuple(
    seconds * NS for seconds in (30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800)
)
MECHANISM_BOOT: Final[int] = 20000
_DAY_NS: Final[int] = 86400 * NS
_EPOCH: Final[dt.date] = dt.date(1970, 1, 1)

#: ``(day offset of the cycle runtime from D, cycle Z) -> stratum``; only 19Z of D-1 is tradable.
STRATA: Final[Mapping[tuple[int, int], str]] = {
    (-1, 19): "19Z_D-1",
    (0, 1): "01Z_D",
    (-1, 13): "13Z_D-1",
}
TRADABLE_STRATUM: Final[str] = "19Z_D-1"

DROP_REPORT_ONLY: Final[str] = "report_only_stratum"
DROP_NO_PREV: Final[str] = "no_prev_same_day"
DROP_UNKNOWN_ERA: Final[str] = "unknown_era"
DROP_NONFINITE: Final[str] = "nonfinite_p_yes"
DROP_NO_R_PLUS: Final[str] = "no_r_plus"
DROP_BELOW_TAU: Final[str] = "below_tau"
DROP_SUPERSEDED: Final[str] = "superseded"
DROP_NO_BOOK: Final[str] = "no_book"
DROP_BOOK_GAP: Final[str] = "book_missing_quote_tape_gap"
DROP_BOOK_HEARTBEAT: Final[str] = "book_missing_heartbeat"
DROP_NO_ASK: Final[str] = "no_ask"
DROP_ASK_ABOVE_CAP: Final[str] = "ask_above_cap"
DROP_RULE_B_REFERENCE: Final[str] = "rule_b_no_reference"
DROP_RULE_B_MOVED: Final[str] = "rule_b_already_moved"
DROP_PERMIT: Final[str] = "permit"
DROP_ENTRY_FEE: Final[str] = "fee_unpinned"
DROP_EXIT_FEE: Final[str] = "exit_fee_unpinned"


# ------------------------------------------------------------------------ variants


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    primary: bool
    lag_ns: int
    x_ns: int
    tau_key: str  # "primary" or "alt"


VARIANTS: Final[tuple[Variant, ...]] = (
    Variant("V0", True, L_PRIMARY_NS, X_PRIMARY_NS, "primary"),
    Variant("V1", False, L_PRIMARY_NS, X_SHORT_NS, "primary"),
    Variant("V2", False, L_PRIMARY_NS, X_LONG_NS, "primary"),
    Variant("V3", False, L_PRIMARY_NS, X_PRIMARY_NS, "alt"),
    Variant("V4", False, L_ALT_NS, X_PRIMARY_NS, "primary"),
)


# --------------------------------------------------------------------- price maths


def _cash(price: float) -> Decimal:
    return Decimal(str(round(price, 6)))


def permit_ok(t_dec_ns: int, t_exit_ns: int, w_ns: int = W_NS) -> bool:
    """R5: the nominal permit must hold at ``t_dec``, ``t_exit`` and ``t_exit + W``."""
    return all(is_inside_nominal_permit(t) for t in (t_dec_ns, t_exit_ns, t_exit_ns + w_ns))


@dataclass(frozen=True, slots=True)
class MarkoutResult:
    pnl: float
    entry_fee: float
    exit_fee: float
    ask: float
    bid: float
    missing_exit: bool
    filled_inside_window: bool


def markout_pnl(
    *, ask: float, t_dec_ns: int, exit_bid: ExitBid, tick: float = 0.0
) -> MarkoutResult | str:
    """``bid(t') - ask - fee(ask, t_dec) - fee(bid, t')``, two cent-rounded fees (R4).

    No bid in the window means ``bid = 0`` and no exit fee, never a drop. A fee the schedule
    refuses (None) returns the drop reason. ``tick`` is the one-tick-worse stress."""
    entry_price = min(ask + tick, PRICE_CEILING)
    entry_fee = cash_taker_fee_usd(_cash(entry_price), t_dec_ns)
    if entry_fee is None:
        return DROP_ENTRY_FEE
    if exit_bid.missing_exit or exit_bid.ts_ns is None:
        return MarkoutResult(
            pnl=0.0 - entry_price - float(entry_fee),
            entry_fee=float(entry_fee),
            exit_fee=0.0,
            ask=entry_price,
            bid=0.0,
            missing_exit=True,
            filled_inside_window=False,
        )
    bid = max(exit_bid.bid - tick, 0.0)
    exit_fee = cash_taker_fee_usd(_cash(bid), exit_bid.ts_ns)
    if exit_fee is None:
        return DROP_EXIT_FEE
    return MarkoutResult(
        pnl=bid - entry_price - float(entry_fee) - float(exit_fee),
        entry_fee=float(entry_fee),
        exit_fee=float(exit_fee),
        ask=entry_price,
        bid=bid,
        missing_exit=False,
        filled_inside_window=exit_bid.filled_inside_window,
    )


# ------------------------------------------------------------------- event model


@dataclass(frozen=True, slots=True)
class StationDayData:
    station: str
    climate_day: dt.date
    chain: VectorChain
    ladder: tuple[Rung, ...]
    calibration: LiveCalibration
    latitude_deg: float
    offset_hours: float
    books: Mapping[str, BookSeries]
    gaps: Mapping[str, tuple[GapSpan, ...]]
    heartbeat: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class EventContext:
    station: str
    climate_day: dt.date
    stratum: str | None
    cur: ForecastQuantileVector
    bands: SignedBands | None
    prev_reason: str | None


def stratum_of(cycle_runtime_ns: int, climate_day: dt.date) -> str | None:
    day = _EPOCH + dt.timedelta(days=cycle_runtime_ns // _DAY_NS)
    cycle_z = (cycle_runtime_ns % _DAY_NS) // (3600 * NS)
    return STRATA.get(((day - climate_day).days, cycle_z))


def build_events(data: StationDayData) -> list[EventContext]:
    """One context per release of the station-day's own climate day, deltas computed once."""
    contexts: list[EventContext] = []
    for cur in data.chain.vectors:
        if cur.climate_day != data.climate_day:
            continue
        prev = data.chain.at(cur.available_at_ns - 1)
        stratum = stratum_of(cur.cycle_runtime_ns, data.climate_day)
        reason: str | None = None
        bands: SignedBands | None = None
        if prev is None or prev.climate_day != data.climate_day:
            reason = DROP_NO_PREV
        else:
            try:
                deltas = rung_deltas(
                    prev=prev,
                    cur=cur,
                    ladder=data.ladder,
                    calibration=data.calibration,
                    latitude_deg=data.latitude_deg,
                    climate_day=data.climate_day,
                )
            except CalibrationArtefactUnknownVersionError:
                reason = DROP_UNKNOWN_ERA
            else:
                if all(math.isfinite(v) for v in deltas.values()):
                    bands = signed_bands(deltas)
                else:
                    reason = DROP_NONFINITE
        contexts.append(EventContext(data.station, data.climate_day, stratum, cur, bands, reason))
    return contexts


@dataclass(frozen=True, slots=True)
class Take:
    station: str
    climate_day: dt.date
    stratum: str
    rung_id: str
    available_at_ns: int
    t_dec_ns: int
    t_exit_ns: int
    delta: float
    ask: float
    bid: float
    pnl: float
    stress_pnl: float | None
    cost_e: float
    y_raw: float | None
    missing_exit: bool
    filled_inside_window: bool


def _as_of(series: BookSeries, t_ns: int) -> BookRow | None:
    row = series.as_of(t_ns)
    if row is not None:
        assert_guard_3((row,), t_ns)
    return row


def _half_spread(row: BookRow | None) -> float:
    if row is None or math.isnan(row.bid) or math.isnan(row.ask):
        return 0.0
    return (row.ask - row.bid) / 2.0


def _entry_reason(
    data: StationDayData, ctx: EventContext, rung: str, t_dec: int
) -> tuple[BookRow | None, str | None]:
    series = data.books.get(rung)
    if series is None:
        return None, DROP_NO_BOOK
    verdict = is_missing(data.gaps.get(rung, ()), data.heartbeat, t_dec)
    if verdict.missing:
        return None, DROP_BOOK_GAP if verdict.reason == "quote_tape_gap" else DROP_BOOK_HEARTBEAT
    row = _as_of(series, t_dec)
    if row is None or math.isnan(row.ask):
        return None, DROP_NO_ASK
    if row.ask > ASK_CAP:
        return None, DROP_ASK_ABOVE_CAP
    return row, None


def score_event(
    data: StationDayData,
    ctx: EventContext,
    variant: Variant,
    tau: float,
    *,
    apply_rule_b: bool = True,
    shift_ns: int = 0,
) -> Take | str:
    """One event under one variant: a ``Take`` or exactly one drop reason (census identity).

    ``shift_ns`` < 0 is the deliberate look-ahead pre-release placebo take (diagnostic only)."""
    if ctx.stratum != TRADABLE_STRATUM:
        return DROP_REPORT_ONLY
    if ctx.prev_reason is not None:
        return ctx.prev_reason
    bands = ctx.bands
    if bands is None or bands.r_plus is None or bands.delta_plus is None:
        return DROP_NO_R_PLUS
    if bands.delta_plus < tau:
        return DROP_BELOW_TAU
    cur = ctx.cur
    assert_guard_4(available_at_ns=cur.available_at_ns, cycle_runtime_ns=cur.cycle_runtime_ns)
    t_dec = decision_instant(cur.available_at_ns, variant.lag_ns) + shift_ns
    live = data.chain.at(t_dec)
    if shift_ns == 0 and (live is None or live.available_at_ns != cur.available_at_ns):
        return DROP_SUPERSEDED
    assert_guard_7(climate_day=ctx.climate_day, t_dec_ns=t_dec, pre_stage2=True)
    rung = bands.r_plus
    entry, reason = _entry_reason(data, ctx, rung, t_dec)
    if reason is not None or entry is None:
        return reason or DROP_NO_ASK
    series = data.books[rung]
    if apply_rule_b:
        reference = _as_of(series, cur.available_at_ns + shift_ns)
        if reference is None or math.isnan(reference.ask):
            return DROP_RULE_B_REFERENCE
        if entry.ask > reference.ask + RULE_B_SHARE * bands.delta_plus:
            return DROP_RULE_B_MOVED
    t_exit = t_dec + variant.x_ns
    if not permit_ok(t_dec, t_exit):
        return DROP_PERMIT
    assert_guard_11(t_dec, t_exit, t_exit + W_NS, inside_permit=is_inside_nominal_permit)
    exit_bid = first_bid_in_window(series, t_exit, W_NS)
    result = markout_pnl(ask=entry.ask, t_dec_ns=t_dec, exit_bid=exit_bid)
    if isinstance(result, str):
        return result
    assert_guard_8(result.entry_fee)
    stress = markout_pnl(ask=entry.ask, t_dec_ns=t_dec, exit_bid=exit_bid, tick=STRESS_TICK)
    exit_row = _as_of(series, t_exit)
    cost = result.entry_fee + result.exit_fee + _half_spread(entry) + _half_spread(exit_row)
    return Take(
        station=ctx.station,
        climate_day=ctx.climate_day,
        stratum=ctx.stratum,
        rung_id=rung,
        available_at_ns=cur.available_at_ns,
        t_dec_ns=t_dec,
        t_exit_ns=t_exit,
        delta=bands.delta_plus,
        ask=entry.ask,
        bid=result.bid,
        pnl=result.pnl,
        stress_pnl=None if isinstance(stress, str) else stress.pnl,
        cost_e=cost,
        y_raw=aligned_mark_change(series, t_dec_ns=t_dec, x_ns=variant.x_ns),
        missing_exit=result.missing_exit,
        filled_inside_window=result.filled_inside_window,
    )


@dataclass(slots=True)
class Census:
    """Guard 10: ``population == takes + sum(drops)`` per variant."""

    population: int = 0
    takes: int = 0
    drops: Counter[str] = field(default_factory=Counter)

    def record(self, outcome: Take | str) -> None:
        self.population += 1
        if isinstance(outcome, str):
            self.drops[outcome] += 1
        else:
            self.takes += 1

    def check(self) -> None:
        assert_guard_10(self.population, self.takes, self.drops)

    def report(self) -> dict[str, Any]:
        self.check()
        return {
            "population": self.population,
            "takes": self.takes,
            "drops": dict(sorted(self.drops.items())),
        }


@dataclass(slots=True)
class VariantRun:
    census: Census = field(default_factory=Census)
    takes: list[Take] = field(default_factory=list)
    placebo_takes: list[Take] = field(default_factory=list)


def merge_run(into: VariantRun, other: VariantRun) -> None:
    into.census.population += other.census.population
    into.census.takes += other.census.takes
    into.census.drops.update(other.census.drops)
    into.takes.extend(other.takes)
    into.placebo_takes.extend(other.placebo_takes)


def tau_for(variant: Variant, report: TauReport) -> float:
    return report.tau_primary if variant.tau_key == "primary" else report.tau_alt


def score_station_day(
    data: StationDayData,
    contexts: Sequence[EventContext],
    variant: Variant,
    tau: float,
    run: VariantRun,
    *,
    apply_rule_b: bool = True,
) -> None:
    for ctx in contexts:
        outcome = score_event(data, ctx, variant, tau, apply_rule_b=apply_rule_b)
        run.census.record(outcome)
        if isinstance(outcome, Take):
            run.takes.append(outcome)
            shifted = score_event(
                data, ctx, variant, tau, apply_rule_b=apply_rule_b, shift_ns=-PRE_RELEASE_SHIFT_NS
            )
            if isinstance(shifted, Take):
                run.placebo_takes.append(shifted)


# ---------------------------------------------------------------------- statistics


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values) if values else 0.0


def _wider_take_interval(
    takes: Sequence[Take], *, iterations: int, seed: int
) -> tuple[float, float, float]:
    """``(lo, hi, one_sided_p)`` from the wider of the station-day and climate-day bootstraps."""

    def _stat(drawn: Sequence[Take]) -> float:
        return _mean([take.pnl for take in drawn])

    lows, highs, ps = [], [], []
    for key in (lambda t: (t.station, t.climate_day), lambda t: t.climate_day):
        draws = cluster_bootstrap_draws(
            takes, statistic=_stat, cluster_key=key, seed=seed, iterations=iterations
        )
        lo, hi = percentile_interval(draws, alpha=CI_ALPHA)
        lows.append(lo)
        highs.append(hi)
        ps.append(sum(1 for d in draws if d <= 0.0) / len(draws))
    return min(lows), max(highs), max(ps)


def summarize(
    variant: Variant, run: VariantRun, *, iterations: int, seed: int = STAGE1_SEED
) -> VariantSummary:
    takes = run.takes
    if not takes:
        return VariantSummary(
            variant.name, variant.primary, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0, 1.0, True
        )
    pnl = [t.pnl for t in takes]
    point = _mean(pnl)
    lo, hi, p_value = _wider_take_interval(takes, iterations=iterations, seed=seed)
    sd = statistics.stdev(pnl) if len(pnl) > 1 else 0.0
    return VariantSummary(
        name=variant.name,
        primary=variant.primary,
        point=point,
        lo=lo,
        hi=hi,
        n=len(takes),
        n_climate=len({t.climate_day for t in takes}),
        missing_exit_rate=sum(1 for t in takes if t.missing_exit) / len(takes),
        hit_rate=sum(1 for p in pnl if p > 0.0) / len(pnl),
        mean_over_sd=point / sd if sd > 0.0 else 0.0,
        placebo_point=_mean([t.pnl for t in run.placebo_takes]),
        p_value=p_value,
        leak_ok=True,
    )


def exit_mix(takes: Sequence[Take]) -> dict[str, Any]:
    groups: dict[str, list[float]] = {
        "exit_at_t_exit": [],
        "exit_in_window": [],
        "missing_exit": [],
    }
    for take in takes:
        key = (
            "missing_exit"
            if take.missing_exit
            else "exit_in_window"
            if take.filled_inside_window
            else "exit_at_t_exit"
        )
        groups[key].append(take.pnl)
    return {k: {"n": len(v), "mean_pnl": _mean(v)} for k, v in groups.items()}


def json_default(value: object) -> object:
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, set | frozenset):
        return sorted(value)
    return str(value)


def to_plain(obj: object) -> dict[str, Any]:
    """Shallow dataclass -> dict via ``fields`` (no ``asdict``)."""
    return {f.name: getattr(obj, f.name) for f in fields(obj)}  # type: ignore[arg-type]


# --------------------------------------------------------------------------- stages

Loader = Callable[[str, dt.date], "StationDayData | None"]


def _iter_data(
    loader: Loader, stations: Sequence[str], days: Sequence[dt.date], census: Counter[str]
) -> Any:
    for day in days:
        if day > SEARCH_END:
            census["excluded_day"] += 1
            continue
        for station in stations:
            data = loader(station, day)
            if data is None:
                census["no_station_day_data"] += 1
                continue
            yield data


def run_stage_tau(
    loader: Loader, stations: Sequence[str], days: Sequence[dt.date], *, freeze_ns: int
) -> dict[str, Any]:
    """tau from NBP data alone: the max positive dP of each 19Z-D-1 cycle that exists at freeze."""
    cycles: list[TauCycle] = []
    counts: Counter[str] = Counter()
    for data in _iter_data(loader, stations, days, counts):
        for ctx in build_events(data):
            counts["events"] += 1
            if ctx.stratum != TRADABLE_STRATUM or ctx.bands is None:
                continue
            delta = ctx.bands.delta_plus
            if delta is not None:
                cycles.append(TauCycle(ctx.cur.available_at_ns, 19, delta))
    report = derive_tau(cycles, freeze_ns=freeze_ns)
    return {"stage": "tau", "tau": to_plain(report), "counts": dict(counts)}


def _placebos_for(
    data: StationDayData, take: Take, variant: Variant, *, shift: int = 0
) -> list[float]:
    minute = (take.available_at_ns // (60 * NS)) % 60
    releases = data.chain.releases
    days = tuple(data.climate_day + dt.timedelta(days=d) for d in (-1, 0, 1))
    series = data.books[take.rung_id]
    out: list[float] = []
    for instant in placebo_instants(
        minute_of_hour=minute,
        releases_ns=releases,
        days=days,
        climate_day=data.climate_day,
        offset_hours=data.offset_hours,
        instrument_id=take.rung_id,
        event_instrument_id=take.rung_id,
    ):
        change = aligned_mark_change(
            series, t_dec_ns=instant + variant.lag_ns + 1 + shift, x_ns=variant.x_ns
        )
        if change is not None:
            out.append(change)
    return out


def _kill_rows(
    data: StationDayData, takes: Sequence[Take], variant: Variant
) -> tuple[list[KillRow], int]:
    rows: list[KillRow] = []
    unscorable = 0
    for take in takes:
        if take.y_raw is None:
            unscorable += 1
            continue
        rows.append(
            KillRow(
                station=take.station,
                climate_day=take.climate_day,
                y_raw=take.y_raw,
                placebo_ys=tuple(_placebos_for(data, take, variant)),
                cost_e=take.cost_e,
                missing_exit=take.missing_exit,
            )
        )
    return rows, unscorable


def _mechanism(data: StationDayData, contexts: Sequence[EventContext]) -> list[dict[str, Any]]:
    """Both signs, every stratum: signed mid change over the grid from ``t_a``."""
    rows: list[dict[str, Any]] = []
    for ctx in contexts:
        bands = ctx.bands
        if bands is None:
            continue
        for sign, rung, delta in (
            (1.0, bands.r_plus, bands.delta_plus),
            (-1.0, bands.r_minus, bands.delta_minus),
        ):
            series = data.books.get(rung) if rung is not None else None
            if series is None or delta is None:
                continue
            t_a = ctx.cur.available_at_ns
            level0 = mid(series.as_of(t_a))
            path = [(t_a + g, mid(series.as_of(t_a + g))) for g in MECHANISM_GRID_NS]
            if level0 is None or any(v is None for _, v in path):
                rows.append({"stratum": ctx.stratum, "sign": sign, "scorable": False})
                continue
            levels = [(ts, sign * (v - level0)) for ts, v in path if v is not None]
            pre = mid(series.as_of(t_a - 3600 * NS))
            rows.append(
                {
                    "stratum": ctx.stratum,
                    "sign": sign,
                    "scorable": True,
                    "day": ctx.climate_day,
                    "abs_dp": abs(delta),
                    "y60": levels[1][1] if len(levels) > 1 else 0.0,
                    "y_grid": [v for _, v in levels],
                    "half_life_s": fraction_of_move(levels, t_a, 0.0),
                    "y_pre": None if pre is None else sign * (level0 - pre),
                }
            )
    return rows


def _slope_report(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    events = [
        EventObservation(r["day"], r["abs_dp"], r[key]) for r in rows if r.get(key) is not None
    ]
    try:
        ci = mechanism_slope_ci(events, n_boot=MECHANISM_BOOT, seed=KILL_SEED)
    except ValueError as exc:
        return {"n": len(events), "refused": str(exc)}
    return {"n": len(events), "slope": ci.slope, "lo": ci.lo, "hi": ci.hi}


def run_stage_0(
    loader: Loader,
    stations: Sequence[str],
    days: Sequence[dt.date],
    tau: TauReport,
    *,
    iterations: int = KILL_BOOTSTRAP_DRAWS,
) -> dict[str, Any]:
    """Mechanism gate (outcome-free): beta, half-life, F(tau) and the one raw KILL-COST rule."""
    primary = VARIANTS[0]
    mech: list[dict[str, Any]] = []
    runs = {True: VariantRun(), False: VariantRun()}
    unscorable = {True: 0, False: 0}
    kill_rows: dict[bool, list[KillRow]] = {True: [], False: []}
    flags: list[MissingClass] = []
    counts: Counter[str] = Counter()
    for data in _iter_data(loader, stations, days, counts):
        contexts = build_events(data)
        mech.extend(_mechanism(data, contexts))
        for rule_b in (True, False):
            day_run = VariantRun()
            score_station_day(
                data, contexts, primary, tau.tau_primary, day_run, apply_rule_b=rule_b
            )
            merge_run(runs[rule_b], day_run)
            rows, missing_mid = _kill_rows(data, day_run.takes, primary)
            kill_rows[rule_b].extend(rows)
            unscorable[rule_b] += missing_mid
            if rule_b:
                flags.extend(
                    is_missing(data.gaps.get(t.rung_id, ()), data.heartbeat, t.t_dec_ns)
                    for t in day_run.takes
                )
    scorable = [r for r in mech if r.get("scorable")]
    half_lives = [r["half_life_s"] for r in scorable if r.get("half_life_s") is not None]
    kill = {
        ("after_rule_b" if rule_b else "before_rule_b"): to_plain(
            kill_cost(
                kill_rows[rule_b],
                iterations=iterations,
                seed=KILL_SEED,
                extra_missing=unscorable[rule_b],
            )
        )
        for rule_b in (True, False)
    }
    median_half_life = statistics.median(half_lives) if half_lives else None
    return {
        "stage": "0",
        "counts": dict(counts),
        "mechanism": {
            "n_events": len(mech),
            "n_scorable": len(scorable),
            "beta_y60_on_abs_dp": _slope_report(scorable, "y60"),
            "pre_release_slope": _slope_report(scorable, "y_pre"),
            "median_half_life_s": median_half_life,
            "too_fast": median_half_life is not None and median_half_life < primary.lag_ns / NS,
            "covariate_adjusted_beta": "not_built: observed-temperature loader is out of scope",
        },
        "kill_cost": kill,
        "census_after_rule_b": runs[True].census.report(),
        "census_before_rule_b": runs[False].census.report(),
        "missing_attribution": to_plain(missing_attribution(flags)),
    }


def run_stage_1(
    loader: Loader,
    stations: Sequence[str],
    days: Sequence[dt.date],
    tau: TauReport,
    *,
    iterations: int = KILL_BOOTSTRAP_DRAWS,
) -> dict[str, Any]:
    runs = {variant.name: VariantRun() for variant in VARIANTS}
    counts: Counter[str] = Counter()
    for data in _iter_data(loader, stations, days, counts):
        contexts = build_events(data)
        for variant in VARIANTS:
            score_station_day(data, contexts, variant, tau_for(variant, tau), runs[variant.name])
    summaries = [summarize(v, runs[v.name], iterations=iterations) for v in VARIANTS]
    selection = select(summaries)
    return {
        "stage": "1",
        "framing": STAGE1_FRAMING,
        "counts": dict(counts),
        "tau": to_plain(tau),
        "variants": {
            s.name: {
                **to_plain(s),
                "census": runs[s.name].census.report(),
                "exit_mix": exit_mix(runs[s.name].takes),
                "stress_one_tick_mean": _mean(
                    [t.stress_pnl for t in runs[s.name].takes if t.stress_pnl is not None]
                ),
            }
            for s in summaries
        },
        "selection": to_plain(selection),
        "settlement_pnl": "not_built: report-only; truth opens only via report_settlement()",
    }
