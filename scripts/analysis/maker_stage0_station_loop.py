"""MAKER-S2 WP6: one station-day, every unit hypothesis and every variant (no truth, no verdict).

Plan r3 WP6 flow step (1) + r4 delta (d)(e)(g)(i)1/(i)3. The PRIMARY variant writes its episodes
into the ``EpisodeSink`` one at a time (WP4 returns one station-day's episode list per variant, so
the memory bound is one station-day x one variant of episodes; across station-days only the
per-rung position fold, ``out.seeds`` and ``out.rows`` are retained) and yields the verdict rows;
the report-only variants (logged-relaunch overlay, +60 min and poll-lag availability stress,
Delta = 0) re-run the same raw data and write only their own rows.
The raw capture slice is read once per station-day and each hypothesis' event stream is built once.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.maker_tape_census import CensusedDay
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.quantile_density import Rung
from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_adapter import SelectorConfig, WantTracker, build_selector
from scripts.analysis.maker_stage0_catalog_read import (
    CatalogSession,
    StationDayPlan,
    query_window_ns,
)
from scripts.analysis.maker_stage0_events_build import (
    CutSpec,
    DataEvents,
    InstanceSlice,
    ReplayResult,
    assert_before_local_midnight,
    build_data_events,
    clock_events,
    replay_station_day,
)
from scripts.analysis.maker_stage0_fill_events import (
    Decision,
    DecisionContext,
    Episode,
    ForecastVector,
    RungSelector,
)
from scripts.analysis.maker_stage0_inputs import UnitHypothesis
from scripts.analysis.maker_stage0_nodelog import LogStatus
from scripts.analysis.maker_stage0_pno import AbstainReason, classify_p_no, release_instants
from scripts.analysis.maker_stage0_pno_store import PNoStore, Stress, site
from scripts.analysis.maker_stage0_runio import (
    PositionFold,
    PositionSeed,
    theta_for_day,
)
from scripts.analysis.maker_stage0_schedule import (
    GTD_MIDNIGHT,
    PERMIT_EXPIRY,
    RELAUNCH,
    STOP_PRIOR,
    DaySchedule,
)
from scripts.analysis.maker_stage0_tables import sd_row_from_summary
from scripts.analysis.maker_stage0_verdict import SdRow

__all__ = [
    "VARIANTS",
    "EpisodeWriter",
    "Key",
    "LoopContext",
    "LoopOutput",
    "replays",
    "run_station_day",
]

PRIMARY: Final[str] = "primary"
#: name -> (schedule, availability stress, Delta forced to zero)
VARIANTS: Final[dict[str, tuple[str, Stress, bool]]] = {
    PRIMARY: ("primary", "none", False),
    "overlay": ("overlay", "none", False),
    "plus60": ("primary", "plus60", False),
    "poll_lag": ("primary", "poll_lag", False),
    "delta0": ("primary", "none", True),
}
_CUT_REASON: Final[dict[str, tuple[str, bool]]] = {
    GTD_MIDNIGHT: ("GTD_EXPIRY", True),
    PERMIT_EXPIRY: ("CANCEL_PROCESS", False),
    STOP_PRIOR: ("CANCEL_PROCESS", False),
    RELAUNCH: ("CANCEL_PROCESS", True),
}
_NS: Final[int] = 10**9
Key = tuple[str, dt.date]


class EpisodeWriter(Protocol):
    def write(self, episode: Episode) -> None: ...


@dataclass
class LoopContext:
    units: Sequence[UnitHypothesis]
    primary: Mapping[dt.date, DaySchedule]
    overlay: Mapping[dt.date, DaySchedule]
    statuses: Mapping[dt.date, LogStatus]
    census: Mapping[tuple[str, dt.date], CensusedDay]
    deltas: Mapping[tuple[str, dt.date], int]
    plans: Mapping[tuple[str, dt.date], StationDayPlan]
    session: CatalogSession
    nbp_root: Path
    calibration: LiveCalibration
    sink: EpisodeWriter | None
    variants: Sequence[str] = tuple(VARIANTS)
    #: station-days listed after D-1 12:00Z: replayed (covered) but never bid (listing abstention)
    abstained: frozenset[tuple[str, dt.date]] = frozenset()
    watch: Callable[[], None] | None = None  # called after every (hypothesis, variant) pass


@dataclass
class LoopOutput:
    rows: dict[str, list[SdRow]] = field(default_factory=dict)
    seeds: list[PositionSeed] = field(default_factory=list)
    consumed: set[tuple[int, str]] = field(default_factory=set)
    abstentions: dict[str, int] = field(default_factory=dict)  # primary decisions, by reason
    parity: dict[str, int] = field(default_factory=dict)
    listing_abstained: list[str] = field(default_factory=list)  # "STATION YYYY-MM-DD"
    rounding: dict[str, dict[str, int]] = field(default_factory=dict)  # by unit hypothesis
    unknown_delta: int = 0  # station-days with no clock-offset sample (Delta taken as 0)

    def add_rounding(self, unit: str, data: DataEvents) -> None:
        mine = self.rounding.setdefault(
            unit, {"levels": 0, "levels_ceil_raised": 0, "prints": 0, "prints_floored_zero": 0}
        )
        mine["levels"] += data.n_levels
        mine["levels_ceil_raised"] += data.n_levels_ceil_raised
        mine["prints"] += data.n_prints
        mine["prints_floored_zero"] += data.n_prints_floored_zero

    def add_abstentions(self, counts: Mapping[str, int]) -> None:
        for reason, n in counts.items():
            self.abstentions[reason] = self.abstentions.get(reason, 0) + n

    def add_row(self, variant: str, row: SdRow) -> None:
        self.rows.setdefault(variant, []).append(row)


def _cut_specs(schedule: DaySchedule, station: str, day: dt.date) -> list[CutSpec]:
    specs = [CutSpec(c.instant_ns, *_CUT_REASON[c.kind]) for c in schedule.cuts]
    hard = rule.hard_cancel_ns(day, int(site(station).offset_hours))
    return [*specs, CutSpec(hard, "CANCEL_HARD", False)]


def _ladder(instruments: Sequence[str]) -> tuple[list[Rung], dict[str, float]]:
    rungs: list[Rung] = []
    edges: dict[str, float] = {}
    for instrument in instruments:
        facts = bucket_facts_from_instrument_id(instrument)
        if facts is None:
            raise ValueError(f"{instrument} has no rung facts")
        rungs.append(Rung(rung_id=instrument, lo=facts.lower_f, hi=facts.upper_f))
        edges[instrument] = float("-inf") if facts.lower_f is None else float(facts.lower_f)
    return rungs, edges


def _vectors(store: PNoStore, station: str, day: dt.date, stress: Stress) -> list[ForecastVector]:
    shas = dict(sorted(store.consumed_cycles()))
    out: list[ForecastVector] = []
    for release in release_instants(store, station, day, stress=stress):
        served = classify_p_no(store, station, day, release + 1, stress=stress)
        if isinstance(served, AbstainReason):
            continue
        out.append(
            ForecastVector(
                available_at_ns=release,
                p_yes_point=served.p_yes_point_live,
                p_yes_upper={k: b.upper for k, b in served.bounds.items()},
                cycle_runtime_ns=served.vector.cycle_runtime_ns,
                raw_sha256=shas.get(served.vector.cycle_runtime_ns, ""),
                nbm_era=served.vector.model_version,
            )
        )
    return out


def _unreplayed(
    unit: str, key: tuple[str, dt.date], cr: CensusedDay, status: LogStatus | None
) -> SdRow:
    iso = key[1].isoformat()
    return SdRow(
        station=key[0], climate_day=iso, cluster_id=iso, unit_hypothesis=unit,
        census_reason=cr.reason, covered_bidlive=cr.covered_bidlive,
        covered=cr.reason == "COVERED" and cr.covered_bidlive,
        outage_excluded=status is LogStatus.OUTAGE,
        node_log_absent=status is LogStatus.NODE_LOG_ABSENT, theta=theta_for_day(key[1]),
    )  # fmt: skip


def replays(cr: CensusedDay, status: LogStatus | None) -> bool:
    return cr.reason == "COVERED" and cr.covered_bidlive and status is not LogStatus.OUTAGE


@dataclass
class _Prepared:
    slices: list[InstanceSlice]
    store: PNoStore | None
    edges: dict[str, float]
    vectors: dict[Stress, list[ForecastVector]]


def _prepare(ctx: LoopContext, key: tuple[str, dt.date], out: LoopOutput) -> _Prepared:
    station, day = key
    plan = ctx.plans.get(key)
    if plan is None or not plan.instruments:
        return _Prepared([], None, {}, {})
    window = query_window_ns(station, day)
    slices = ctx.session.read(plan, window)
    rungs, edges = _ladder(plan.instruments)
    if key in ctx.abstained:  # listing abstention: the book is replayed, no forecast is consulted
        return _Prepared(slices, None, edges, {})
    store = PNoStore.from_root(
        ctx.nbp_root, stations=[station], days=[day], calibration=ctx.calibration,
        ladders={key: rungs},
    )  # fmt: skip
    stresses: set[Stress] = {VARIANTS[v][1] for v in ctx.variants}
    vectors = {s: _vectors(store, station, day, s) for s in stresses}
    out.consumed |= set(store.consumed_cycles())
    lows = {r.lo % 2 for r in rungs if r.lo is not None}
    if len(lows) == 1:
        out.parity.setdefault(station, lows.pop())
    return _Prepared(slices, store, edges, vectors)


def _data(prep: _Prepared, unit: UnitHypothesis, key: tuple[str, dt.date]) -> DataEvents:
    return build_data_events(prep.slices, size_of=unit.to_contracts, window=query_window_ns(*key))


def _selector_for(
    prep: _Prepared, key: Key, stress: Stress, delta: int, tracker: WantTracker
) -> RungSelector:
    if prep.store is None:
        return _no_selector
    cfg = SelectorConfig(
        store=prep.store,
        station=key[0],
        day=key[1],
        stress=stress,
        delta_ns=delta,
        theta=theta_for_day(key[1]),
        lower_edges_f=prep.edges,
    )
    return build_selector(cfg, tracker)


def _stream(
    sink: EpisodeWriter, replay: ReplayResult, key: Key, unit: str, out: LoopOutput
) -> None:
    """Write every episode before the next is pulled; keep only the per-rung position fold."""
    fold = PositionFold(key[0], key[1], unit)
    for episode in replay.result.episodes:
        assert_before_local_midnight(episode, key[0], key[1])
        sink.write(episode)
        fold.add(episode)
    out.seeds += fold.seeds()


def _run_variant(
    ctx: LoopContext,
    name: str,
    key: Key,
    unit: UnitHypothesis,
    prep: _Prepared,
    data: DataEvents,
    out: LoopOutput,
) -> int:
    station, day = key
    schedule_key, stress, zero = VARIANTS[name]
    sched = (ctx.primary if schedule_key == "primary" else ctx.overlay)[day]
    delta = 0 if zero else ctx.deltas.get(key, 0)
    tracker = WantTracker()
    clock = clock_events(_cut_specs(sched, station, day), prep.vectors.get(stress, ()))
    replay = replay_station_day(
        data,
        clock,
        selector=_selector_for(prep, key, stress, delta, tracker),
        tracker=tracker,
        station=station,
        day=day,
        unit_hypothesis=unit.name,
        live_from_ns=sched.window_start_ns,
        delta_ns=delta,
    )
    if name == PRIMARY:
        out.add_abstentions(tracker.abstentions)
        if ctx.sink is not None:
            _stream(ctx.sink, replay, key, unit.name, out)
    cr = ctx.census[key]
    row = sd_row_from_summary(
        replay.result.summary,
        census_reason=cr.reason,
        covered_bidlive=cr.covered_bidlive,
        covered=True,
        outage_excluded=False,
        node_log_absent=ctx.statuses.get(day) is LogStatus.NODE_LOG_ABSENT,
        n_depth_frames=data.n_depth_frames,
        theta=theta_for_day(day),
        n_no_book_wants=replay.n_no_book_wants,
    )
    out.add_row(name, row)
    return replay.n_events


def _no_selector(_ctx: DecisionContext, /) -> Decision:
    return Decision()


def run_station_day(ctx: LoopContext, key: tuple[str, dt.date], out: LoopOutput) -> int:
    """Simulate ``key`` for every hypothesis and variant; returns the primary event count."""
    cr, status = ctx.census[key], ctx.statuses.get(key[1])
    if not replays(cr, status):
        for unit in ctx.units:
            for name in ctx.variants:
                out.add_row(name, _unreplayed(unit.name, key, cr, status))
        return 0
    prep = _prepare(ctx, key, out)
    if key in ctx.abstained and ctx.plans.get(key) is not None:
        out.listing_abstained.append(f"{key[0]} {key[1].isoformat()}")
    n_events = 0
    for unit in ctx.units:
        data = _data(prep, unit, key)
        out.add_rounding(unit.name, data)
        for name in ctx.variants:
            count = _run_variant(ctx, name, key, unit, prep, data, out)
            n_events = n_events or count
            if ctx.watch is not None:
                ctx.watch()
    return n_events
