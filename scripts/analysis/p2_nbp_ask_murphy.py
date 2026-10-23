"""P2 — NBP resolution and YES taker P&L versus the PM.us YES ask.

Pre-registered in ``docs/plans/backlog/AUDIT_PATH_2026-10-22/P2_plan_r2.md``.
The r2.1 amendments at the end of that file win on every conflict. This module
does not choose a threshold: the gate is 16:50Z on LST date D−1, the book
window is ten minutes closed, the fee is the dated taker schedule, and the
verdict table checks PASS before FAIL.

The quote tape under ``/mnt/storage`` is read only. One station-day is in
memory at a time. Importing this module does not run the study.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, NoReturn, Protocol, cast

TEN_MINUTES_NS = 600 * 1_000_000_000
_NS = 1_000_000_000
_CENT = Decimal("0.01")
_IDENTITY_TOLERANCE = 1e-12
_D_RES_PASS_LB = 0.005

_SCORE_END = dt.date(2026, 10, 13)
_FIT_START = dt.date(2021, 1, 1)
_FIT_END = dt.date(2026, 6, 30)
_HOLDOUT_NOT_AFTER = dt.date(2026, 6, 30)
_STATIONS = ("LAX", "MDW", "MIA", "SFO")
_CALIBRATION_SHA = "9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e"
_VENUE_SUFFIX = ".POLYMARKET_US"
_MIN_EVENTS = 200
_MIN_CLUSTERS = 30
_MIN_TAKES = 30
_FULL_RUN_BUDGET_S = 1800.0

_DROP_REASONS = (
    "duplicate_rung",
    "no_vector",
    "vector_day_mismatch",
    "no_book",
    "no_truth",
    "truth_conflict",
    "no_yes_ask",
    "ask_out_of_range",
    "unknown_era",
    "nonfinite_or_out_of_range",
)


class IdentityError(RuntimeError):
    """``|brier − reconstructed_brier|`` exceeded 1e-12."""


class NullError(RuntimeError):
    """Setting p = ask did not give D_res of exactly 0."""


class _HasTs(Protocol):
    @property
    def ts_ns(self) -> int: ...


class _BookSnap(Protocol):
    """One tape instant the runner can score: a timestamp and optional L0 prices."""

    @property
    def ts_ns(self) -> int: ...

    @property
    def ask(self) -> float | None: ...

    @property
    def bid(self) -> float | None: ...


class _ForecastVector(Protocol):
    @property
    def available_at_ns(self) -> int: ...

    @property
    def climate_day(self) -> dt.date: ...


class _MurphyView(Protocol):
    @property
    def brier(self) -> float: ...

    @property
    def reliability(self) -> float: ...

    @property
    def resolution(self) -> float: ...

    @property
    def uncertainty(self) -> float: ...


class _Decomposition(Protocol):
    @property
    def brier(self) -> float: ...

    @property
    def reconstructed_brier(self) -> float: ...


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """One L0 instant the book rule can see. ``ask`` is absent when None."""

    ts_ns: int
    ask: float | None = None
    bid: float | None = None


def gate_instant_ns(climate_day: dt.date) -> int:
    """16:50:00Z on LST date D−1, as integer nanoseconds.

    ``int(timestamp()) * 1e9`` is not used: nanoseconds near 1.79e18 are not
    exact in float64. Whole UTC seconds in 2026 are exact in float, so the
    second is taken with ``timestamp()`` and scaled in integers.
    """
    prev = climate_day - dt.timedelta(days=1)
    stamp = dt.datetime(prev.year, prev.month, prev.day, 16, 50, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * _NS


def first_snapshot_in_window[SnapT: _HasTs](
    snapshots: Sequence[SnapT], gate_ns: int
) -> SnapT | None:
    """The earliest snapshot in the closed interval ``[gate, gate + 10 min]``.

    Input order is not assumed. An empty window returns None. On a timestamp
    tie the first object in ``snapshots`` with that timestamp is kept.
    """
    end = gate_ns + TEN_MINUTES_NS
    chosen: SnapT | None = None
    chosen_ts = end + 1
    for snap in snapshots:
        ts = snap.ts_ns
        if gate_ns <= ts <= end and ts < chosen_ts:
            chosen = snap
            chosen_ts = ts
    return chosen


def assert_brier_identity(decomp: _Decomposition) -> None:
    """STOP check: ``|brier − (REL − RES + UNC + W − C)| ≤ 1e-12``."""
    gap = abs(decomp.brier - decomp.reconstructed_brier)
    if gap > _IDENTITY_TOLERANCE:
        raise IdentityError(
            f"|brier - reconstructed_brier| = {gap!r} exceeds {_IDENTITY_TOLERANCE}"
        )


def d_res(probs_a: Sequence[float], probs_b: Sequence[float], outcomes: Sequence[bool]) -> float:
    """``RES(probs_a) − RES(probs_b)`` on the ten reliability bins."""
    from breezy.analysis.brier_decomposition import bin_by_edges, resolution_difference
    from breezy.analysis.nbp_calibration import RELIABILITY_BUCKET_EDGES

    return resolution_difference(probs_a, probs_b, outcomes, bin_by_edges(RELIABILITY_BUCKET_EDGES))


def assert_null_dres(asks: Sequence[float], outcomes: Sequence[bool]) -> None:
    """STOP check: the same probabilities on both sides give D_res exactly 0.

    ``-0.0 == 0.0`` in IEEE comparison, so a signed zero is not a failure.
    The check always sets p equal to ``asks``; it does not depend on swapping
    the outcome vector.
    """
    value = d_res(asks, asks, outcomes)
    if value != 0.0:
        raise NullError(f"D_res(ask, ask) = {value!r}, expected exactly 0")


def cash_taker_fee_usd(ask: Decimal, ts_event_ns: int) -> Decimal | None:
    """``θ·ask·(1−ask)`` for one contract, half-even to the cent, or None.

    ``θ`` is :func:`taker_fee_coefficient_as_of`. None (the 2026-09-17
    ambiguous window, or an unpinned date) is a refusal, not a default of 0.
    The quantum is one cent, the same rule ``_round_bankers`` applies to USD.
    """
    from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of

    theta = taker_fee_coefficient_as_of(ts_event_ns)
    if theta is None:
        return None
    exact = theta * ask * (Decimal(1) - ask)
    return exact.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def yes_taker_pnl_usd(*, outcome: int, ask: Decimal, ts_event_ns: int) -> Decimal | None:
    """``outcome − ask − fee`` in dollars, or None when the fee is unpinned."""
    fee = cash_taker_fee_usd(ask, ts_event_ns)
    if fee is None:
        return None
    return Decimal(outcome) - ask - fee


def verdict(
    *,
    dres_evaluable: bool,
    dres_lb: float,
    pnl_evaluable: bool,
    pnl_lb: float,
    pnl_ub: float,
) -> str:
    """r2.1 table. PASS is tested first, so it wins an overlap with FAIL.

    A bound of 0 does not pass (P&L lower bound must be strictly positive)
    and does not fail (P&L upper bound must be strictly negative). A statistic
    that is not evaluable does not contribute its bounds.
    """
    if (dres_evaluable and dres_lb >= _D_RES_PASS_LB) or (pnl_evaluable and pnl_lb > 0.0):
        return "PASS"
    if pnl_evaluable and pnl_ub < 0.0:
        return "FAIL"
    return "INCONCLUSIVE"


# --- study runner (not imported by the pure tests) -----------------------------------------


def _stop(message: str, code: int = 2) -> NoReturn:
    print(f"STOP {message}", file=sys.stderr)
    raise SystemExit(code)


def _ask_cash(ask: float) -> Decimal:
    """Cent-valued float to Decimal without ``Decimal(float)`` binary junk."""
    return Decimal(format(ask, ".10f"))


def _rung_id(lower: int | None, upper: int | None) -> str:
    lo = "lt" if lower is None else str(lower)
    hi = "gte" if upper is None else str(upper)
    return f"{lo}_{hi}"


@dataclass(frozen=True, slots=True)
class _Dir:
    station: str
    climate_day: dt.date
    lower: int | None
    upper: int | None
    rung_id: str
    instrument_id: str
    path: str


@dataclass(frozen=True, slots=True)
class _Drop:
    station: str
    climate_day: dt.date
    rung_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class _Event:
    station: str
    climate_day: dt.date
    rung_id: str
    p_nbp: float
    ask: float
    bid: float | None
    outcome: bool
    ts_ns: int
    fee_unpinned: bool


@dataclass(frozen=True, slots=True)
class _Take:
    station: str
    climate_day: dt.date
    side: str
    pnl: Decimal


def _wider(
    station_ci: tuple[float, float], climate_ci: tuple[float, float]
) -> tuple[str, tuple[float, float]]:
    """The wider 95% interval. On a width tie, the smaller lower bound."""
    station_width = station_ci[1] - station_ci[0]
    climate_width = climate_ci[1] - climate_ci[0]
    if station_width > climate_width:
        return "station-day", station_ci
    if climate_width > station_width:
        return "climate-day", climate_ci
    if station_ci[0] <= climate_ci[0]:
        return "station-day (width tie, smaller lower bound)", station_ci
    return "climate-day (width tie, smaller lower bound)", climate_ci


def _run(smoke: bool) -> int:
    import time
    from collections import Counter, defaultdict
    from pathlib import Path

    from breezy.analysis.brier_decomposition import (
        bin_by_edges,
        murphy_decomposition,
    )
    from breezy.analysis.nbp_calibration import (
        BOOTSTRAP_ITERATIONS,
        BOOTSTRAP_SEED,
        RELIABILITY_BUCKET_EDGES,
        cluster_bootstrap_draws,
        percentile_interval,
    )
    from breezy.strategy.forecast_quantile_ladder.artefact_bounds import ArtefactBoundsProvider
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
        CalibrationArtefactPinMismatchError,
        CalibrationArtefactUnknownVersionError,
        load_live_calibration,
    )
    from breezy.strategy.forecast_quantile_ladder.decision import (
        NotDPlus1,
        NotExecutable,
        SidedAsk,
        Take,
        evaluate,
    )
    from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
    from breezy.strategy.forecast_quantile_ladder.margin import hours_to_settlement
    from breezy.strategy.ladder_ev.config import LadderEvConfig
    from breezy.strategy.ladder_ev.quantile_density import Rung
    from breezy.strategy.no_ladder_maker.pno_store import (
        _complement,
        _is_complete_partition,
        build_chain,
        build_state,
        ladder_p_yes,
        read_pinned,
        site,
    )

    repo = Path(__file__).resolve().parents[2]
    analysis = Path(__file__).resolve().parent
    if str(analysis) not in sys.path:
        sys.path.insert(0, str(analysis))
    run_date = dt.datetime.now(dt.UTC).date()
    started = time.perf_counter()
    calibration_path = (
        repo / "deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
    )
    try:
        calibration = load_live_calibration(
            cast(str, calibration_path), expected_sha256=_CALIBRATION_SHA
        )
    except CalibrationArtefactPinMismatchError as exc:
        _stop(f"sha pin: {exc}")

    truth, conflicts = _load_truth(
        Path.home() / ".local/share/breezy/derived/fq-truth/truth_cli_finals.csv"
    )
    depth_root = Path("/mnt/storage/breezy/catalog/quote_tape/polymarket_us/data/order_book_depths")
    if not depth_root.is_dir():
        _stop(f"quote tape depth root is not a directory: {depth_root}")

    classified, no_dirs, full_n = _list_rungs(depth_root)
    selected, smoke_n = _select_smoke(classified, smoke=smoke)
    if smoke and smoke_n == 0:
        _stop("smoke found no SFO HIGH rung directories")

    from forecast_cheap_screen_wp7 import (  # type: ignore[import-not-found]
        _fixed_scalars,
        read_rung_tape,
    )

    price_scalar, size_scalar = _fixed_scalars()
    source = _NbpSource(Path.home() / ".local/share/breezy/derived/nbp")
    ladder_cfg = LadderEvConfig()
    bounds = ArtefactBoundsProvider(cdf_method=calibration.cdf_method)
    bins = bin_by_edges(RELIABILITY_BUCKET_EDGES)

    by_day: dict[dt.date, dict[str, list[_Dir]]] = defaultdict(lambda: defaultdict(list))
    for item in selected:
        by_day[item.climate_day][item.station].append(item)

    events: list[_Event] = []
    drops: list[_Drop] = []
    yes_takes: list[_Take] = []
    no_takes: list[_Take] = []
    decision_reasons: Counter[str] = Counter()
    fee_unpinned = 0
    vector_differs = 0
    no_books_used = 0
    unpriced_no = 0
    days_with_snapshot: set[dt.date] = set()

    for climate_day in sorted(by_day):
        for station in _STATIONS:
            items = by_day[climate_day].get(station)
            if not items:
                continue
            day_events, day_drops, day_yes, day_no, notes = _station_day(
                items,
                climate_day=climate_day,
                station=station,
                source=source,
                calibration=calibration,
                ladder_cfg=ladder_cfg,
                bounds=bounds,
                truth=truth,
                conflicts=conflicts,
                no_dirs=no_dirs,
                read_rung_tape=read_rung_tape,
                price_scalar=price_scalar,
                size_scalar=size_scalar,
                Take=Take,
                NotDPlus1=NotDPlus1,
                NotExecutable=NotExecutable,
                SidedAsk=SidedAsk,
                evaluate=evaluate,
                QuantileLadderLatch=QuantileLadderLatch,
                hours_to_settlement=hours_to_settlement,
                Rung=Rung,
                complement=_complement,
                is_complete=_is_complete_partition,
                build_chain=build_chain,
                build_state=build_state,
                ladder_p_yes=ladder_p_yes,
                read_pinned=read_pinned,
                site=site,
                unknown_era=CalibrationArtefactUnknownVersionError,
            )
            events.extend(day_events)
            drops.extend(day_drops)
            yes_takes.extend(day_yes)
            no_takes.extend(day_no)
            decision_reasons.update(notes["reasons"])
            fee_unpinned += notes["fee_unpinned"]
            vector_differs += notes["vector_differs"]
            no_books_used += notes["no_books_used"]
            unpriced_no += notes["unpriced_no"]
            if notes["saw_snapshot"]:
                days_with_snapshot.add(climate_day)
            print(
                f"{station} {climate_day.isoformat()} rungs={len(items)} "
                f"scored={len(day_events)} drops={len(day_drops)}",
                file=sys.stderr,
            )
        source.clear()

    if not days_with_snapshot:
        _stop("no Depth10 snapshot inside the 10-minute gate on any selected day")
    scored_start = min(days_with_snapshot)
    events = [e for e in events if e.climate_day >= scored_start]
    drops = [d for d in drops if d.climate_day >= scored_start]
    yes_takes = [t for t in yes_takes if t.climate_day >= scored_start]
    no_takes = [t for t in no_takes if t.climate_day >= scored_start]
    population = [item for item in selected if scored_start <= item.climate_day <= _SCORE_END]
    if len(population) != len(events) + len(drops):
        _stop(
            f"census does not add up: population {len(population)} != "
            f"scored {len(events)} + drops {len(drops)}"
        )
    earliest_d_minus_1 = scored_start - dt.timedelta(days=1)
    if earliest_d_minus_1 <= _HOLDOUT_NOT_AFTER:
        _stop(f"min(D-1) {earliest_d_minus_1.isoformat()} is not after 2026-06-30")
    if not events:
        _stop("empty ASK set")

    ask_probs = [e.ask for e in events]
    nbp_probs = [e.p_nbp for e in events]
    outcomes = [e.outcome for e in events]
    nbp_decomp = murphy_decomposition(nbp_probs, outcomes, bins)
    ask_decomp = murphy_decomposition(ask_probs, outcomes, bins)
    try:
        assert_brier_identity(nbp_decomp)
        assert_brier_identity(ask_decomp)
        assert_null_dres(ask_probs, outcomes)
    except (IdentityError, NullError) as exc:
        _stop(f"ASK set check: {exc}")
    point_dres = nbp_decomp.resolution - ask_decomp.resolution

    mid = [e for e in events if e.bid is not None and e.bid > 0.01]
    mid_nbp = mid_ask = None
    if mid:
        mid_nbp = murphy_decomposition([e.p_nbp for e in mid], [e.outcome for e in mid], bins)
        mid_ask = murphy_decomposition([e.ask for e in mid], [e.outcome for e in mid], bins)
        try:
            assert_brier_identity(mid_nbp)
            assert_brier_identity(mid_ask)
            assert_null_dres([e.ask for e in mid], [e.outcome for e in mid])
        except (IdentityError, NullError) as exc:
            _stop(f"MID set check: {exc}")

    def _dres_stat(drawn: Sequence[_Event]) -> float:
        return d_res([e.p_nbp for e in drawn], [e.ask for e in drawn], [e.outcome for e in drawn])

    dres_station_ci, dres_climate_ci = _cluster_cis(
        events,
        _dres_stat,
        cluster_bootstrap_draws,
        percentile_interval,
        seed=BOOTSTRAP_SEED,
        iterations=BOOTSTRAP_ITERATIONS,
    )
    dres_which, dres_wider = _wider(dres_station_ci, dres_climate_ci)
    n_station = len({(e.station, e.climate_day) for e in events})
    n_climate = len({e.climate_day for e in events})
    dres_evaluable = len(events) >= _MIN_EVENTS and n_climate >= _MIN_CLUSTERS

    pnl_station_ci = pnl_climate_ci = None
    pnl_which = ""
    pnl_wider = (0.0, 0.0)
    pnl_mean = 0.0
    pnl_sum = Decimal(0)
    n_take_station = len({(t.station, t.climate_day) for t in yes_takes})
    n_take_climate = len({t.climate_day for t in yes_takes})
    pnl_evaluable = len(yes_takes) >= _MIN_TAKES and n_take_climate >= _MIN_CLUSTERS
    if yes_takes:
        pnl_values = [float(t.pnl) for t in yes_takes]
        pnl_mean = sum(pnl_values) / len(pnl_values)
        pnl_sum = sum((t.pnl for t in yes_takes), start=Decimal(0))

        def _pnl_stat(drawn: Sequence[_Take]) -> float:
            return sum(float(t.pnl) for t in drawn) / len(drawn)

        pnl_station_ci, pnl_climate_ci = _cluster_cis(
            yes_takes,
            _pnl_stat,
            cluster_bootstrap_draws,
            percentile_interval,
            seed=BOOTSTRAP_SEED,
            iterations=BOOTSTRAP_ITERATIONS,
        )
        pnl_which, pnl_wider = _wider(pnl_station_ci, pnl_climate_ci)

    name = verdict(
        dres_evaluable=dres_evaluable,
        dres_lb=dres_wider[0],
        pnl_evaluable=pnl_evaluable,
        pnl_lb=pnl_wider[0],
        pnl_ub=pnl_wider[1],
    )
    elapsed = time.perf_counter() - started
    if smoke:
        extrapolated = elapsed * (full_n / smoke_n)
        print(f"smoke_seconds={elapsed:.3f}")
        print(f"smoke_rung_dirs={smoke_n}")
        print(f"full_rung_dirs={full_n}")
        print(f"extrapolated_seconds={extrapolated:.3f}")
        print(
            f"smoke_ask_events={len(events)} smoke_yes_takes={len(yes_takes)} "
            f"smoke_scored_start={scored_start.isoformat()}",
            file=sys.stderr,
        )
        if extrapolated > _FULL_RUN_BUDGET_S:
            _stop(
                f"extrapolated full run {extrapolated:.1f}s exceeds {_FULL_RUN_BUDGET_S:.0f}s",
                code=3,
            )
        return 0

    no_sum = sum((t.pnl for t in no_takes), start=Decimal(0)) if no_takes else Decimal(0)
    text = _evidence(
        run_date=run_date,
        scored_start=scored_start,
        population=len(population),
        events=events,
        drops=drops,
        n_station=n_station,
        n_climate=n_climate,
        nbp_decomp=nbp_decomp,
        ask_decomp=ask_decomp,
        point_dres=point_dres,
        dres_station_ci=dres_station_ci,
        dres_climate_ci=dres_climate_ci,
        dres_which=dres_which,
        dres_evaluable=dres_evaluable,
        mid=mid,
        mid_nbp=mid_nbp,
        mid_ask=mid_ask,
        yes_takes=yes_takes,
        pnl_sum=pnl_sum,
        pnl_mean=pnl_mean,
        pnl_station_ci=pnl_station_ci,
        pnl_climate_ci=pnl_climate_ci,
        pnl_which=pnl_which,
        n_take_station=n_take_station,
        n_take_climate=n_take_climate,
        pnl_evaluable=pnl_evaluable,
        no_takes=no_takes,
        no_sum=no_sum,
        no_books_captured=len(no_dirs),
        no_books_used=no_books_used,
        unpriced_no=unpriced_no,
        fee_unpinned=fee_unpinned,
        vector_differs=vector_differs,
        decision_reasons=decision_reasons,
        conflicts=len(conflicts),
        verdict_name=name,
        seed=BOOTSTRAP_SEED,
        iterations=BOOTSTRAP_ITERATIONS,
        elapsed=elapsed,
        slippage=ladder_cfg.slippage_floor_prob,
    )
    evidence = repo / "docs/evidence" / f"P2_NBP_VS_ASK_MURPHY_{run_date.isoformat()}.md"
    if not str(evidence).startswith(str(repo / "docs/evidence")):
        _stop(f"refusing to write evidence outside docs/evidence: {evidence}")
    evidence.write_text(text)
    print(f"VERDICT {name}")
    return 0


@dataclass
class _NbpSource:
    """``PartitionSource`` over ``nbp_derived_store``, cached for one climate day."""

    root: Path
    _cache: dict[Path, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._cache = {}

    def partition_path(self, cycle_date: dt.date, hour: int) -> Path:
        from breezy.persistence.nbp_derived_store import partition_path

        return partition_path(self.root, cycle_date, hour)

    def read_partition(self, path: Path) -> Any:
        cached = self._cache.get(path)
        if cached is None:
            from breezy.persistence.nbp_derived_store import read_partition

            cached = read_partition(path)
            self._cache[path] = cached
        return cached

    def clear(self) -> None:
        self._cache.clear()


def _load_truth(
    path: Path,
) -> tuple[dict[tuple[str, dt.date], int], set[tuple[str, dt.date]]]:
    import csv

    values: dict[tuple[str, dt.date], set[int]] = {}
    with path.open(newline="") as handle:
        for raw in csv.DictReader(handle):
            station = (raw.get("station") or "").strip().upper()
            day_text = (raw.get("climate_day") or "").strip()
            tmax_text = (raw.get("tmax_f") or "").strip()
            if not station or not day_text or not tmax_text:
                continue
            key = (station, dt.date.fromisoformat(day_text))
            values.setdefault(key, set()).add(int(tmax_text))
    usable = {key: next(iter(tmaxes)) for key, tmaxes in values.items() if len(tmaxes) == 1}
    conflicts = {key for key, tmaxes in values.items() if len(tmaxes) > 1}
    return usable, conflicts


def _list_rungs(depth_root: Path) -> tuple[list[_Dir], dict[str, str], int]:
    """HIGH rung dirs for the four stations. NO-leg dirs are indexed, not scored."""
    from market_calibration_scan import classify_directory  # type: ignore[import-not-found]

    classified: list[_Dir] = []
    no_dirs: dict[str, str] = {}
    full_n = 0
    import os

    for entry in os.scandir(depth_root):
        if not entry.is_dir():
            continue
        name = entry.name
        if name.endswith("^no" + _VENUE_SUFFIX) or "^no." in name:
            no_dirs[name] = entry.path
            continue
        spec, kind = classify_directory(name)
        if kind != "rung" or spec is None:
            continue
        if spec.station not in _STATIONS or spec.climate_day > _SCORE_END:
            continue
        full_n += 1
        classified.append(
            _Dir(
                station=spec.station,
                climate_day=spec.climate_day,
                lower=spec.lower,
                upper=spec.upper,
                rung_id=_rung_id(spec.lower, spec.upper),
                instrument_id=name,
                path=entry.path,
            )
        )
    return classified, no_dirs, full_n


def _select_smoke(classified: list[_Dir], *, smoke: bool) -> tuple[list[_Dir], int]:
    if not smoke:
        return classified, len(classified)
    sfo = [item for item in classified if item.station == "SFO"]
    if not sfo:
        return [], 0
    start = min(item.climate_day for item in sfo)
    end = min(_SCORE_END, start + dt.timedelta(days=6))
    window = [item for item in sfo if start <= item.climate_day <= end]
    return window, len(window)


def _station_day(
    items: Sequence[_Dir], **kw: Any
) -> tuple[list[_Event], list[_Drop], list[_Take], list[_Take], dict[str, Any]]:
    from collections import Counter
    from pathlib import Path

    climate_day = kw["climate_day"]
    station = kw["station"]
    groups: dict[str, list[_Dir]] = {}
    for item in items:
        groups.setdefault(item.rung_id, []).append(item)
    kept: list[_Dir] = []
    drops: list[_Drop] = []
    saw_snapshot = False
    gate = gate_instant_ns(climate_day)
    placed = _site_of(kw["site"], station)

    def _window(item: _Dir) -> _BookSnap | None:
        instants, _rows = kw["read_rung_tape"](
            Path(item.path),
            std_utc_offset_hours=placed.offset_hours,
            price_scalar=kw["price_scalar"],
            size_scalar=kw["size_scalar"],
            city=station,
        )
        chosen = first_snapshot_in_window(instants, gate)
        del instants
        return chosen

    snapshots: dict[str, _BookSnap | None] = {}
    for rung_id, group in groups.items():
        group.sort(key=lambda item: item.instrument_id)
        for extra in group[1:]:
            extra_snap = _window(extra)
            if extra_snap is not None:
                saw_snapshot = True
            drops.append(_Drop(station, climate_day, rung_id, "duplicate_rung"))
        primary = group[0]
        kept.append(primary)
        snapshots[primary.instrument_id] = _window(primary)

    ladder = tuple(
        kw["Rung"](rung_id=item.rung_id, lo=item.lower, hi=item.upper)
        for item in sorted(kept, key=lambda item: item.rung_id)
    )
    complete = kw["is_complete"](ladder) if ladder else False
    pinned = kw["read_pinned"](kw["source"], placed.icao, climate_day)
    state = kw["build_state"](pinned.rows, placed.offset_hours, "none")
    chain = kw["build_chain"](state, climate_day)
    gate_vector = chain.at(gate)

    survivors: list[tuple[_Dir, _BookSnap, _ForecastVector]] = []
    for item in kept:
        snap = snapshots[item.instrument_id]
        if snap is not None:
            saw_snapshot = True
        vector = chain.at(snap.ts_ns) if snap is not None else gate_vector
        reason = _drop_reason(item, snap, vector, climate_day, kw["truth"], kw["conflicts"])
        if reason is not None:
            drops.append(_Drop(station, climate_day, item.rung_id, reason))
            continue
        assert snap is not None and vector is not None
        survivors.append((item, snap, vector))

    events: list[_Event] = []
    yes_takes: list[_Take] = []
    no_takes: list[_Take] = []
    reasons: Counter[str] = Counter()
    fee_unpinned = 0
    vector_differs = 0
    no_books_used = 0
    unpriced_no = 0
    if survivors:
        by_vector: dict[int, list[tuple[_Dir, _BookSnap, _ForecastVector]]] = {}
        p_by_vector: dict[int, Any] = {}
        for item, snap, vector in survivors:
            by_vector.setdefault(vector.available_at_ns, []).append((item, snap, vector))
        for available, rows in by_vector.items():
            vector = rows[0][2]
            try:
                computed = kw["ladder_p_yes"](
                    vector, ladder, kw["calibration"], placed.latitude_deg
                )
            except kw["unknown_era"]:
                for item, _snap, _vector in rows:
                    drops.append(_Drop(station, climate_day, item.rung_id, "unknown_era"))
                continue
            p_by_vector[available] = computed
        latch = kw["QuantileLadderLatch"]()
        for item, snap, vector in survivors:
            computed = p_by_vector.get(vector.available_at_ns)
            if computed is None:
                continue
            triple = computed.get(item.rung_id)
            if triple is None or not _point_ok(triple.point):
                drops.append(_Drop(station, climate_day, item.rung_id, "nonfinite_or_out_of_range"))
                continue
            if gate_vector is None or vector is not gate_vector:
                vector_differs += 1
            theta_missing = _fee_missing(snap.ts_ns)
            if theta_missing:
                fee_unpinned += 1
            events.append(
                _Event(
                    station=station,
                    climate_day=climate_day,
                    rung_id=item.rung_id,
                    p_nbp=float(triple.point),
                    ask=float(cast(float, snap.ask)),
                    bid=None if snap.bid is None else float(snap.bid),
                    outcome=_hit(item, kw["truth"][(station, climate_day)]),
                    ts_ns=int(snap.ts_ns),
                    fee_unpinned=theta_missing,
                )
            )
            if not theta_missing:
                rung = kw["Rung"](rung_id=item.rung_id, lo=item.lower, hi=item.upper)
                eval_ladder = ladder if complete else kw["complement"](rung)
                decision = _evaluate_side(
                    kw,
                    station=station,
                    climate_day=climate_day,
                    item=item,
                    snap=snap,
                    vector=vector,
                    side="yes",
                    instrument_id=item.instrument_id,
                    price=float(cast(float, snap.ask)),
                    ladder=eval_ladder,
                    latch=latch,
                    placed=placed,
                )
                reasons[type(decision).__name__ + ":" + _reason_of(decision)] += 1
                if isinstance(decision, kw["Take"]):
                    pnl = yes_taker_pnl_usd(
                        outcome=1 if events[-1].outcome else 0,
                        ask=_ask_cash(float(cast(float, snap.ask))),
                        ts_event_ns=int(snap.ts_ns),
                    )
                    if pnl is None:
                        _stop(
                            f"fee refused after evaluate for {station} {climate_day} {item.rung_id}"
                        )
                    yes_takes.append(_Take(station, climate_day, "yes", pnl))
            no_take, used, unpriced = _maybe_no(
                kw,
                station=station,
                climate_day=climate_day,
                item=item,
                vector_at_gate=gate_vector,
                chain=chain,
                outcome_yes=events[-1].outcome,
                ladder=ladder,
                complete=complete,
                latch=latch,
                placed=placed,
                gate=gate,
            )
            if used:
                no_books_used += 1
            if unpriced:
                unpriced_no += 1
            if no_take is not None:
                no_takes.append(no_take)
    notes = {
        "reasons": reasons,
        "fee_unpinned": fee_unpinned,
        "vector_differs": vector_differs,
        "no_books_used": no_books_used,
        "unpriced_no": unpriced_no,
        "saw_snapshot": saw_snapshot,
    }
    return events, drops, yes_takes, no_takes, notes


def _site_of(site_fn: Callable[..., Any], station: str) -> Any:
    return site_fn(station)


def _point_ok(point: float) -> bool:
    import math

    return math.isfinite(point) and 0.0 <= point <= 1.0


def _fee_missing(ts_ns: int) -> bool:
    from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of

    return taker_fee_coefficient_as_of(ts_ns) is None


def _hit(item: _Dir, tmax_f: int) -> bool:
    return (item.lower is None or tmax_f >= item.lower) and (
        item.upper is None or tmax_f <= item.upper
    )


def _drop_reason(
    item: _Dir,
    snap: _BookSnap | None,
    vector: _ForecastVector | None,
    climate_day: dt.date,
    truth: Mapping[tuple[str, dt.date], int],
    conflicts: set[tuple[str, dt.date]],
) -> str | None:
    """One reason, in the pre-registered order. None means the rung is scored."""
    if vector is None:
        return "no_vector"
    if vector.climate_day != climate_day:
        return "vector_day_mismatch"
    if snap is None:
        return "no_book"
    key = (item.station, climate_day)
    if key in conflicts:
        return "truth_conflict"
    if key not in truth:
        return "no_truth"
    ask = snap.ask
    if ask is None:
        return "no_yes_ask"
    import math

    if not math.isfinite(ask) or ask <= 0.0 or ask > 1.0:
        return "ask_out_of_range"
    return None


def _reason_of(decision: object) -> str:
    return str(getattr(decision, "reason", "take"))


def _evaluate_side(kw: Mapping[str, Any], **args: Any) -> Any:
    from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of

    theta = taker_fee_coefficient_as_of(int(args["snap"].ts_ns))
    if theta is None:
        raise RuntimeError("evaluate called without a pinned fee coefficient")
    h_hours = kw["hours_to_settlement"](
        now_ns=int(args["snap"].ts_ns),
        climate_day=args["climate_day"],
        std_utc_offset_hours=args["placed"].offset_hours,
    )
    decision = kw["evaluate"](
        now_ns=int(args["snap"].ts_ns),
        std_utc_offset_hours=args["placed"].offset_hours,
        permit_covers=True,
        vector=args["vector"],
        station=args["station"],
        climate_day=args["climate_day"],
        ladder=args["ladder"],
        rung_id=args["item"].rung_id,
        side=args["side"],
        ask=kw["SidedAsk"](
            side=args["side"],
            instrument_id=args["instrument_id"],
            price=float(args["price"]),
        ),
        fee_coefficient=float(theta),
        slippage_floor_prob=kw["ladder_cfg"].slippage_floor_prob,
        h_hours=h_hours,
        cfg=kw["ladder_cfg"],
        calibration=kw["calibration"],
        latitude_deg=args["placed"].latitude_deg,
        bounds_provider=kw["bounds"],
        latch=args["latch"],
    )
    if isinstance(decision, (kw["NotDPlus1"], kw["NotExecutable"])):
        _stop(
            f"{type(decision).__name__} for {args['station']} "
            f"{args['climate_day']} {args['item'].rung_id} side={args['side']}"
        )
    return decision


def _maybe_no(kw: Mapping[str, Any], **args: Any) -> tuple[_Take | None, bool, bool]:
    """Price a NO take only from a captured NO book. Never synthesize 1 − bid."""
    from breezy.domain.instrument_leg import sibling_symbol_of

    base = args["item"].instrument_id.removesuffix(_VENUE_SUFFIX)
    no_name = sibling_symbol_of(base) + _VENUE_SUFFIX
    no_path = kw["no_dirs"].get(no_name)
    if no_path is None:
        return None, False, True
    from pathlib import Path

    instants, _rows = kw["read_rung_tape"](
        Path(no_path),
        std_utc_offset_hours=args["placed"].offset_hours,
        price_scalar=kw["price_scalar"],
        size_scalar=kw["size_scalar"],
        city=args["station"],
    )
    snap = first_snapshot_in_window(instants, args["gate"])
    del instants
    if snap is None or snap.ask is None:
        return None, True, True
    import math

    if not math.isfinite(snap.ask) or snap.ask <= 0.0 or snap.ask > 1.0:
        return None, True, True
    vector = args["chain"].at(snap.ts_ns)
    if vector is None or vector.climate_day != args["climate_day"]:
        return None, True, True
    if _fee_missing(snap.ts_ns):
        return None, True, True
    rung = kw["Rung"](rung_id=args["item"].rung_id, lo=args["item"].lower, hi=args["item"].upper)
    eval_ladder = args["ladder"] if args["complete"] else kw["complement"](rung)
    decision = _evaluate_side(
        kw,
        station=args["station"],
        climate_day=args["climate_day"],
        item=args["item"],
        snap=snap,
        vector=vector,
        side="no",
        instrument_id=no_name,
        price=float(snap.ask),
        ladder=eval_ladder,
        latch=args["latch"],
        placed=args["placed"],
    )
    if not isinstance(decision, kw["Take"]):
        return None, True, False
    pnl = yes_taker_pnl_usd(
        outcome=0 if args["outcome_yes"] else 1,
        ask=_ask_cash(float(snap.ask)),
        ts_event_ns=int(snap.ts_ns),
    )
    if pnl is None:
        return None, True, True
    take = _Take(args["station"], args["climate_day"], "no", pnl)
    return take, True, False


def _cluster_cis(
    items: Sequence[Any],
    statistic: Any,
    draw_fn: Any,
    interval_fn: Any,
    *,
    seed: int,
    iterations: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    station = draw_fn(
        items,
        statistic=statistic,
        cluster_key=lambda item: (item.station, item.climate_day),
        seed=seed,
        iterations=iterations,
    )
    climate = draw_fn(
        items,
        statistic=statistic,
        cluster_key=lambda item: item.climate_day,
        seed=seed,
        iterations=iterations,
    )
    return interval_fn(station), interval_fn(climate)


def _fmt(value: float) -> str:
    return f"{value:.10f}"


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return "not computed"
    return f"[{_fmt(ci[0])}, {_fmt(ci[1])}]"


def _fmt_decomp(decomp: _MurphyView) -> str:
    return (
        f"Brier {_fmt(decomp.brier)}; REL {_fmt(decomp.reliability)}; "
        f"RES {_fmt(decomp.resolution)}; UNC {_fmt(decomp.uncertainty)}"
    )


def _evidence(**kw: Any) -> str:
    from collections import Counter

    events = kw["events"]
    drops = kw["drops"]
    by_reason: Counter[str] = Counter(drop.reason for drop in drops)
    by_station: dict[str, Counter[str]] = {station: Counter() for station in _STATIONS}
    for drop in drops:
        by_station[drop.station][drop.reason] += 1
    header = "| reason | " + " | ".join(_STATIONS) + " | total |"
    reason_lines = [header, "|---|---|---|---|---|---|"]
    for reason in _DROP_REASONS:
        cells = [str(by_station[station][reason]) for station in _STATIONS]
        reason_lines.append(f"| {reason} | " + " | ".join(cells) + f" | {by_reason[reason]} |")
    scored_counts = Counter(event.station for event in events)
    scored_line = " | ".join(f"{station} {scored_counts[station]}" for station in _STATIONS)
    mid_block = "MID set empty (no report)."
    if kw["mid"]:
        mid_dres = kw["mid_nbp"].resolution - kw["mid_ask"].resolution
        mid_block = (
            f"n events {len(kw['mid'])}. NBP {_fmt_decomp(kw['mid_nbp'])}. "
            f"Ask {_fmt_decomp(kw['mid_ask'])}. D_res {_fmt(mid_dres)}. "
            "Report only; not an input to the verdict."
        )
    if kw["pnl_station_ci"] is None:
        yes_ci = "not computed (no YES takes)"
    else:
        _which, _chosen = _wider(kw["pnl_station_ci"], kw["pnl_climate_ci"])
        yes_ci = (
            f"station-day {_fmt_ci(kw['pnl_station_ci'])}; "
            f"climate-day {_fmt_ci(kw['pnl_climate_ci'])}; "
            f"wider = {_which} {_fmt_ci(_chosen)}"
        )
    follow = {
        "PASS": "A forecast-taker plan may be written later. This study deletes nothing.",
        "FAIL": (
            "A FAIL leads to its own reviewed change with its own impact check. "
            "This study deletes nothing."
        ),
        "INCONCLUSIVE": (
            "Keep the code. No further forecast-taker work follows from this result. "
            "The backlog proceeds through P4. INCONCLUSIVE is not a deletion mandate."
        ),
    }[kw["verdict_name"]]
    reasons = ", ".join(f"{key}={value}" for key, value in sorted(kw["decision_reasons"].items()))
    no_mean = (
        sum((t.pnl for t in kw["no_takes"]), start=Decimal(0)) / len(kw["no_takes"])
        if kw["no_takes"]
        else Decimal(0)
    )
    wider_dres = _fmt_ci(_wider(kw["dres_station_ci"], kw["dres_climate_ci"])[1])
    fit = f"{_FIT_START.isoformat()}..{_FIT_END.isoformat()}"
    lines: list[str] = []

    def add(*parts: str) -> None:
        lines.append("".join(parts))

    add("# P2 NBP vs YES ask — Murphy resolution and taker P&L")
    add("")
    add(
        f"Run date: {kw['run_date'].isoformat()} (UTC). ",
        f"Elapsed seconds: {kw['elapsed']:.3f}.",
    )
    add(
        "Plan: `docs/plans/backlog/AUDIT_PATH_2026-10-22/P2_plan_r2.md`, ",
        "r2.1 amendments overriding r2.",
    )
    add("Thresholds were not moved after the tape was read.")
    add("")
    add("## Ranges")
    add("")
    add(
        f"- Scored climate days: {kw['scored_start'].isoformat()} ",
        f"through {_SCORE_END.isoformat()}.",
    )
    add(
        f"- Fit range of the sealed FQ v1 artefact: {fit} (`DEFAULT_SPLITS`). ",
        "The JSON has no fit-date keys; this is the plan's range.",
    )
    add("- The scored range spends days from the sealed S2 holdout (from 2026-07-01).")
    add(
        f"- Stations: {', '.join(_STATIONS)}. No NYC. ",
        "No NBP re-derive after 2026-10-12. No refit.",
    )
    add(f"- Calibration sha256: `{_CALIBRATION_SHA}`.")
    add("")
    add("## Gate")
    add("")
    add(
        "The gating instant is the first Depth10 snapshot at or after 16:50:00Z ",
        "on LST date D−1, inside a closed 10-minute window, else the rung is dropped. ",
        "One instant only. The forecast vector is the newest pinned-cycle vector with ",
        "`available_at_ns` at or before that snapshot's own timestamp, which is also ",
        "`evaluate`'s `now_ns` and the cash-fee timestamp. The 19Z cycle of D−1 cannot ",
        "become available inside that window, so the vector matches a lookup pinned at ",
        "16:50:00Z unless a later cycle was already visible. Rows whose snapshot vector ",
        f"was not the 16:50:00Z vector: {kw['vector_differs']}.",
    )
    add("")
    add(
        "`evaluate` is the production FQ v1 rule: `permit_covers=True`, the default ",
        f"`LadderEvConfig()` (slippage floor {kw['slippage']}), a fresh latch per ",
        "station-day, YES before NO. The hurdle uses `float(θ)` from ",
        "`taker_fee_coefficient_as_of` of the snapshot. Cash P&L uses ",
        "`θ·price·(1−price)` rounded half-even to the cent. θ is 0.06 before ",
        "2026-09-17T00:00Z, refused until 17:00Z that day, then 0.0695. ",
        "Fee-unpinned ASK events stay in D_res and are not takes: ",
        f"{kw['fee_unpinned']}.",
    )
    add("")
    add("Qty-1 P&L at the L0 ask ignores depth, so it is optimistic, which leans toward PASS.")
    add("")
    add("## Census")
    add("")
    add(
        "Population (classified HIGH rung directories on the four stations, ",
        f"climate day in the scored range): {kw['population']}.",
    )
    add(f"ASK events: {len(events)}. Drops: {len(drops)}. ASK + drops = population.")
    add(f"Scored by station: {scored_line}.")
    add(
        "Truth keys excluded for conflicting `tmax_f` ",
        f"(anywhere in the file, not only this range): {kw['conflicts']}.",
    )
    add("")
    lines.extend(reason_lines)
    add("")
    add(
        "`no_vector` is no pinned vector at the instant (the snapshot timestamp, or ",
        "16:50:00Z when the window is empty). `vector_day_mismatch` is a vector whose ",
        "climate day is not D. `no_book` is no Depth10 snapshot in the closed 10-minute ",
        "window. `truth_conflict` is a station-day whose finals disagree on `tmax_f` ",
        "(excluded, not averaged). A station-day with no directory is not a drop.",
    )
    add("")
    add("## ASK set (primary)")
    add("")
    add(f"- n events: {len(events)}")
    add(f"- station-day clusters: {kw['n_station']}")
    add(f"- climate-day clusters: {kw['n_climate']}")
    add(f"- NBP: {_fmt_decomp(kw['nbp_decomp'])}")
    add(f"- YES ask: {_fmt_decomp(kw['ask_decomp'])}")
    add(f"- D_res = RES(NBP) − RES(ask): {_fmt(kw['point_dres'])}")
    add(f"- station-day 95% CI: {_fmt_ci(kw['dres_station_ci'])}")
    add(f"- climate-day 95% CI: {_fmt_ci(kw['dres_climate_ci'])}")
    add(f"- wider CI: {kw['dres_which']} {wider_dres}")
    add(
        "- evaluable ",
        f"(n events ≥ {_MIN_EVENTS} and climate-day clusters ≥ {_MIN_CLUSTERS}): ",
        f"{kw['dres_evaluable']}",
    )
    add("")
    add(
        "Identity `|brier − reconstructed_brier| ≤ 1e-12` held for both systems. ",
        "The null `D_res(ask, ask) = 0` held exactly. Both ran before the bootstrap ",
        "and before the verdict.",
    )
    add("")
    add(
        f"Bootstrap: B={kw['iterations']}, seed {kw['seed']}, each clustering calling ",
        "`cluster_bootstrap_draws` with that seed so each builds its own `Random`. ",
        "The P&L interval is on the mean dollars per qty-1 take. On a width tie the ",
        "smaller lower bound is the wider choice (harder to PASS).",
    )
    add("")
    add("## MID set (report only)")
    add("")
    add(mid_block)
    add("")
    add("## YES taker P&L (decides FAIL; also a PASS input)")
    add("")
    add(f"- takes: {len(kw['yes_takes'])}")
    add(f"- station-day clusters among takes: {kw['n_take_station']}")
    add(f"- climate-day clusters among takes: {kw['n_take_climate']}")
    add(f"- sum USD: {kw['pnl_sum']}")
    add(f"- mean USD per qty-1 take: {kw['pnl_mean']:.10f}")
    add(f"- 95% CIs: {yes_ci}")
    add(
        "- evaluable ",
        f"(takes ≥ {_MIN_TAKES} and climate-day clusters among takes ≥ {_MIN_CLUSTERS}): ",
        f"{kw['pnl_evaluable']}",
    )
    add(f"- YES decision reasons: {reasons or 'none'}")
    add("")
    add("## NO taker P&L (report only, not in the verdict)")
    add("")
    add(
        "NO asks come only from a captured NO-instrument book under the same ",
        "10-minute rule. `1 − YES bid` is not used.",
    )
    add("")
    add(
        "- NO-instrument directories captured under the depth root: ",
        f"{kw['no_books_captured']}",
    )
    add(f"- NO books read for an ASK event: {kw['no_books_used']}")
    add(f"- priced NO takes: {len(kw['no_takes'])}")
    add(
        "- unpriced NO legs (ASK events with no usable NO ask in the window): ",
        f"{kw['unpriced_no']}",
    )
    add(f"- NO P&L sum USD: {kw['no_sum']}")
    add(f"- NO P&L mean USD: {no_mean}")
    add("")
    add("## Verdict")
    add("")
    add(
        "Pre-registered r2.1 table, PASS tested first. An overlap (D_res lower bound ",
        "≥ +0.005 and YES P&L upper bound < 0) is PASS, not a threshold change. ",
        "Bounds of a statistic that is not evaluable are ignored. A lower bound of 0 ",
        "does not PASS. An upper bound of 0 does not FAIL.",
    )
    add("")
    add(f"**{kw['verdict_name']}**")
    add("")
    add(follow)
    add("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="P2 NBP vs YES-ask Murphy study (r2.1)")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="SFO only, first 7 climate days; print timing; do not write evidence",
    )
    args = parser.parse_args(argv)
    return _run(smoke=args.smoke)


if __name__ == "__main__":
    raise SystemExit(main())
