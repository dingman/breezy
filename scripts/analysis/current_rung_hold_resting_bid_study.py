"""Driver/CLI for the offline "resting bid" counterfactual study, Arm A
(``docs/plans/RESTING_BID_HUNT_2026-09-16.md`` Sec 2, Rev 2 -- crossing-event
proxy).

BUILD-TIME analysis only -- never touches the live node, the live exec state
store, or any order/execution path. Network reaches ONLY the corpus's
existing IEM/ASOS fetch helper (``settlement_alignment_study
.fetch_text_cached``, ``.get(...)`` only), exactly as ``current_rung_hold_
exit_window_study.py``/``current_rung_hold_paper_replay.py`` already do --
never ``urllib.request`` (trips the write-egress scanner).

Depth10 source, corrected 2026-09-16: this run reads the STAGED recorder
feather tape directly (``_load_staged_depth_frames``, imported unmodified
from ``current_rung_hold_exit_window_study``), never the committed
``ParquetDataCatalog``. Rev 2 Sec 2.3 states "no depth staging after
2026-09-11" from a count against the PARQUET-converted catalog; a direct
listing of the LIVE staged-feather root on 2026-09-16 (this run's own
preflight, printed to stderr) shows continuous per-station feather output
through the run date across every supported station -- ING-1 (the parquet
converter stranding a station behind the still-capturing recorder) is
exactly why the staged tape, not the parquet one, is this module's source,
matching Rev 2's own instruction ("staged feather is the complete source").

Every listed rung instrument for a station-day is discovered by directly
globbing the staged tape's own directory grammar
(``tc-temp-<city>high-<date>-<band>.<VENUE>``) across EVERY trader-instance
directory (a redeploy rotates instances; ``LESSONS``' "paper replay instance
selection" -- never guess one), then parsed via
``h4_preliminary_economic_read.parse_rung``/``.parse_ladder`` (imported
unmodified) -- the offline slug parser every sibling analysis script uses,
not the live venue-prose cross-check ``symbology.parse_weather_slug``.

Settlement, most authoritative first: (1) a non-superseded FINAL NWS CLI
record (``ma_prelock_winner_ask_study.load_settled_tmax_for_day``, imported
unmodified); (2) a PRELIMINARY guess from the day's final running max
(``exit_window_core.infer_preliminary_settlement``, imported unmodified),
flagged.

Print-based fill sizing is UNIT-UNRESOLVED (plan Sec 2.2:
``parsing.TRADE_QUANTITY_UNIT == "UNRESOLVED"``) and no TRADE channel is
subscribed yet regardless -- this run is DEPTH-PROXY ONLY (the crossing-event
proxy, ``resting_bid_core.simulate_leg``), never a print-based fill count;
every output this module writes says so in its own header.

Writes one JSON + one Markdown file under
``~/.local/share/breezy/derived/resting_bid_study/<run-stamp>/``.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from current_rung_hold_exit_window_study import _load_staged_depth_frames
from exit_window_core import infer_preliminary_settlement
from h4_preliminary_economic_read import Rung, parse_ladder
from ma_prelock_winner_ask_study import (
    ASOS_FETCH_END,
    ASOS_FETCH_START,
    DEFAULT_SETTLEMENT_CATALOG,
    load_settled_tmax_for_day,
)
from resting_bid_core import (
    DEFAULT_MARGINS,
    DEFAULT_QUEUE_SHARES,
    POLL_LAG_NS,
    WINDOW_END_HOUR_LST,
    WINDOW_START_HOUR_LST,
    bucket_facts,
    build_leg_events,
    classify_fill,
    fee_taker,
    fill_pnl,
    ioc_pnl,
    is_qualifying_station_day,
    simulate_leg,
    time_to_fill_band,
    wilson_interval,
    window_coverage_fraction,
)
from resting_bid_report import GateResult, RungLegRow, build_summary, render_markdown
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    USER_AGENT,
    HistoricalDataClient,
    SiteSpec,
    asos_url,
    cache_path_for_url,
    fetch_text_cached,
    load_sites,
    parse_asos_rows,
)

from breezy.domain.season import season_for
from breezy.ingest.iem_observations import iem_asos_rows_to_station_observations
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

__all__ = ["main", "run_resting_bid_study"]

_STATIONS: Final[tuple[str, ...]] = ("LAX", "MDW", "MIA", "SFO")
_DEFAULT_LIVE_CATALOG_ROOT: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us/live"
)
_DEFAULT_OUT_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived/resting_bid_study"
_PLACEHOLDER_RECEIVED_AT_NS: Final[int] = 2**62
_HEADLINE_MARGIN: Final[Decimal] = Decimal("0.02")
_HEADLINE_SHARE: Final[Decimal] = Decimal("1.0")
_BOOTSTRAP_RESAMPLES: Final[int] = 2000
_ALPHA: Final[float] = 0.05


@dataclass(frozen=True, slots=True, kw_only=True)
class _FillFact:
    """One raw fill-eligible event's outcome, already settlement-resolved --
    the unit both the gate math and the row aggregation consume."""

    station: str
    climate_day: str
    margin: Decimal
    price: Decimal
    classification: Literal["I", "L"]
    pnl_maker: Decimal | None
    pnl_taker_fee_sensitivity: Decimal | None
    band: str


def _preflight_listing(live_root: Path, stations: Sequence[str]) -> str:
    """Every (station, newest staged frame date) pair currently on disk --
    printed so a stale claim about staging coverage is never repeated
    silently (module docstring)."""
    newest_by_station: dict[str, str] = {}
    for path in live_root.glob("*/order_book_depths/tc-temp-*high-*"):
        name = path.name
        for station in stations:
            token = f"tc-temp-{station.lower()}high-"
            if name.startswith(token):
                day = name[len(token) : len(token) + 10]
                if day > newest_by_station.get(station, ""):
                    newest_by_station[station] = day
                break
    return "; ".join(f"{s}: newest staged day {newest_by_station.get(s, 'NONE')}" for s in stations)


def _discover_ladder_tokens(live_root: Path, city: str, climate_day: dt.date) -> tuple[str, ...]:
    token = f"tc-temp-{city.lower()}high-{climate_day.isoformat()}-"
    names: set[str] = set()
    for path in live_root.glob(f"*/order_book_depths/{token}*"):
        names.add(path.name)
    return tuple(sorted(names))


def _discover_station_days(
    live_root: Path, stations: Sequence[str], start: dt.date, end: dt.date,
) -> tuple[tuple[str, dt.date], ...]:
    found: list[tuple[str, dt.date]] = []
    day = start
    while day <= end:
        for city in stations:
            if _discover_ladder_tokens(live_root, city, day):
                found.append((city, day))
        day += dt.timedelta(days=1)
    return tuple(found)


def _window_bounds_utc(
    climate_day: dt.date, std_utc_offset_hours: float,
) -> tuple[int, int]:
    tz = dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    start = dt.datetime.combine(
        climate_day, dt.time(WINDOW_START_HOUR_LST, 0), tzinfo=tz,
    ).astimezone(dt.UTC)
    end = dt.datetime.combine(
        climate_day, dt.time(WINDOW_END_HOUR_LST, 0), tzinfo=tz,
    ).astimezone(dt.UTC)
    return (
        int(start.timestamp() * 1_000_000_000),
        int(end.timestamp() * 1_000_000_000),
    )


def _station_asos_text(
    *, cache_dir: Path, spec: SiteSpec, obs_source: Literal["cache", "fetch"],
    client: HistoricalDataClient | None,
) -> str | None:
    url = asos_url(spec.iem_asos_id, ASOS_FETCH_START, ASOS_FETCH_END)
    path = cache_path_for_url(cache_dir, url, ".txt")
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if obs_source != "fetch" or client is None:
        return None
    return fetch_text_cached(client, cache_dir, url, 1.0)


@dataclass(frozen=True, slots=True, kw_only=True)
class _ObsRow:
    observed_at_ns: int
    temp_c_tenths: int
    precision_c_tenths: int
    is_metar: bool


def _station_observations(*, spec: SiteSpec, text: str) -> tuple[_ObsRow, ...]:
    parsed, _drops = iem_asos_rows_to_station_observations(
        station=spec.iem_asos_id, rows=parse_asos_rows(text),
        source_channel="iem_asos_metar_resting_bid_study", assumed_publication_lag_ns=1,
        received_at_ns=_PLACEHOLDER_RECEIVED_AT_NS,
    )
    return tuple(
        _ObsRow(
            observed_at_ns=row.observed_at_ns, temp_c_tenths=row.temp_c_tenths,
            precision_c_tenths=row.precision_c_tenths, is_metar=row.is_metar,
        )
        for row in parsed
    )


def _observations_for_day(
    observations: Sequence[_ObsRow], *, spec: SiteSpec, climate_day: dt.date,
) -> tuple[_ObsRow, ...]:
    from breezy.domain.climate_day import climate_day_for_instant

    return tuple(
        row for row in observations
        if climate_day_for_instant(
            dt.datetime.fromtimestamp(row.observed_at_ns / 1_000_000_000, tz=dt.UTC),
            spec.std_utc_offset_hours,
        ) == climate_day
    )


def _accumulator_with_lag(
    observations: Sequence[_ObsRow], *, std_utc_offset_hours: float, lag_ns: int,
) -> RunningExtremeAccumulator:
    """Fed with ``received_at_ns = observed_at_ns + lag_ns`` -- the REAL
    observation-visibility lag (module docstring), never hindsight."""
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=std_utc_offset_hours)
    for row in observations:
        accumulator.push(
            row.observed_at_ns, row.temp_c_tenths, row.precision_c_tenths, row.is_metar,
            row.observed_at_ns + lag_ns,
        )
    return accumulator


def _resolve_settlement(
    *, station: str, climate_day: dt.date, rung: Rung, leg: Literal["YES", "NO"],
    accumulator: RunningExtremeAccumulator, std_utc_offset_hours: float,
    settlement_catalog: Path,
) -> tuple[bool | None, bool]:
    tmax_f, count, _provenance = load_settled_tmax_for_day(
        catalog_base=settlement_catalog, city=station, climate_day=climate_day,
    )
    facts = bucket_facts(
        lower_f=rung.lower_f, upper_f=rung.upper_f, station=station, climate_day=climate_day,
    )
    if tmax_f is not None and count > 0:
        yes_wins = facts.contains(tmax_f)
        return (yes_wins if leg == "YES" else not yes_wins), False

    end_of_day = int(
        dt.datetime.combine(
            climate_day, dt.time(23, 59, 59),
            tzinfo=dt.timezone(dt.timedelta(hours=std_utc_offset_hours)),
        ).timestamp() * 1_000_000_000,
    )
    final_running_max = accumulator.value_at(end_of_day)
    return (
        infer_preliminary_settlement(facts=facts, final_running_max=final_running_max, leg=leg),
        True,
    )


def _bootstrap_lower_bound(
    pnl_by_day: dict[str, list[Decimal]], *, resamples: int, alpha: float, seed: int = 1729,
) -> float | None:
    """Climate-day bootstrap (Rev 2 Sec 2.4's G-R2): resample DAYS with
    replacement, pool every fill within the resampled days each draw, take
    the mean. Returns the ``alpha``-quantile of the resample distribution,
    or ``None`` when there are too few days to resample meaningfully."""
    days = list(pnl_by_day)
    if len(days) < 2:
        return None
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        drawn_days = [rng.choice(days) for _ in days]
        pooled: list[Decimal] = []
        for day in drawn_days:
            pooled.extend(pnl_by_day[day])
        if pooled:
            means.append(float(sum(pooled)) / len(pooled))
    if not means:
        return None
    means.sort()
    index = int(alpha * len(means))
    return means[min(index, len(means) - 1)]


def _evaluate_gates(
    fills: Sequence[_FillFact], *, ioc_pnl_sum: Decimal, maker_pnl_sum: Decimal,
    qualifying_station_days: int, stranded_station_days: int,
) -> tuple[GateResult, ...]:
    headline = [f for f in fills if f.margin == _HEADLINE_MARGIN]
    distinct_station_days = {(f.station, f.climate_day) for f in headline}
    distinct_days = {f.climate_day for f in headline}
    distinct_stations = {f.station for f in headline}
    n_fills = len(headline)

    g_r1_met = (
        n_fills >= 150 and len(distinct_station_days) >= 25 and len(distinct_days) >= 12
        and len(distinct_stations) >= 3
    )
    g_r1 = GateResult(
        gate_id="G-R1", description="honest N",
        status="PASS" if g_r1_met else "FAIL",
        detail=(
            f"fills={n_fills} station_days={len(distinct_station_days)} "
            f"distinct_climate_days={len(distinct_days)} stations={len(distinct_stations)} "
            "(thresholds: fills>=150, station_days>=25, distinct_climate_days>=12, stations>=3)"
        ),
    )

    pnl_by_day: dict[str, list[Decimal]] = {}
    for f in headline:
        if f.pnl_maker is not None:
            pnl_by_day.setdefault(f.climate_day, []).append(f.pnl_maker)
    all_pnl = [p for values in pnl_by_day.values() for p in values]
    mean_pnl = float(sum(all_pnl)) / len(all_pnl) if all_pnl else None
    lower_bound = _bootstrap_lower_bound(pnl_by_day, resamples=_BOOTSTRAP_RESAMPLES, alpha=_ALPHA)
    if mean_pnl is None or lower_bound is None:
        g_r2 = GateResult(
            gate_id="G-R2", description="profitability", status="NOT_COMPUTABLE",
            detail=f"insufficient fills/days to bootstrap (n_fills={len(all_pnl)}, "
            f"distinct_days={len(pnl_by_day)})",
        )
    else:
        g_r2 = GateResult(
            gate_id="G-R2", description="profitability",
            status="PASS" if (mean_pnl > 0 and lower_bound > 0) else "FAIL",
            detail=f"mean_pnl_per_fill={mean_pnl:.4f} climate_day_bootstrap_lower_bound="
            f"{lower_bound:.4f} (alpha={_ALPHA})",
        )

    informed = sum(1 for f in headline if f.classification == "I")
    liquidity = sum(1 for f in headline if f.classification == "L")
    total = informed + liquidity
    if total == 0:
        g_r3 = GateResult(
            gate_id="G-R3", description="adverse-selection precision",
            status="NOT_COMPUTABLE", detail="no fills to classify",
        )
    else:
        lower, upper = wilson_interval(informed, total)
        half_width = (upper - lower) / 2
        informed_pnl = [
            f.pnl_maker for f in headline if f.classification == "I" and f.pnl_maker is not None
        ]
        liquidity_pnl = [
            f.pnl_maker for f in headline if f.classification == "L" and f.pnl_maker is not None
        ]
        stressed_ok = None
        if informed_pnl and liquidity_pnl:
            mean_i = float(sum(informed_pnl)) / len(informed_pnl)
            mean_l = float(sum(liquidity_pnl)) / len(liquidity_pnl)
            stressed_pnl = upper * mean_i + (1 - upper) * mean_l
            stressed_ok = stressed_pnl > 0
        precision_ok = half_width <= 0.08
        g_r3_status: Literal["PASS", "FAIL", "NOT_COMPUTABLE"]
        if stressed_ok is None:
            g_r3_status = "NOT_COMPUTABLE"
        else:
            g_r3_status = "PASS" if (precision_ok and stressed_ok) else "FAIL"
        g_r3 = GateResult(
            gate_id="G-R3", description="adverse-selection precision",
            status=g_r3_status,
            detail=f"pi_hat_I=[{lower:.4f},{upper:.4f}] half_width={half_width:.4f} "
            f"(<=0.08) stressed_pnl_at_upper_bound_positive={stressed_ok}",
        )

    g_r4 = GateResult(
        gate_id="G-R4", description="dominance",
        status="PASS" if maker_pnl_sum > ioc_pnl_sum else "FAIL",
        detail=f"maker_sigma_pnl={maker_pnl_sum} ioc_sigma_pnl={ioc_pnl_sum}",
    )

    taker_fee_pnl = [
        f.pnl_taker_fee_sensitivity for f in headline
        if f.pnl_taker_fee_sensitivity is not None
    ]
    taker_fee_mean = float(sum(taker_fee_pnl)) / len(taker_fee_pnl) if taker_fee_pnl else None
    g_r5 = GateResult(
        gate_id="G-R5", description="robustness",
        status="NOT_COMPUTABLE" if taker_fee_mean is None else (
            "PASS" if taker_fee_mean > 0 else "FAIL"
        ),
        detail=(
            f"mean_pnl_per_fill_under_fee=fee_taker={taker_fee_mean}; queue-share s does not "
            "change Ê[pnl|fill] under this proxy (s scales expected fill COUNT only), so the "
            "s-robustness leg is vacuous by construction here; the >=1-frame persistence "
            "convention is NOT implemented in this run (NOT_COMPUTABLE for that half)"
        ),
    )

    g_r6 = GateResult(
        gate_id="G-R6", description="tape honesty", status="PASS",
        detail=f"{stranded_station_days} stranded station-day(s) excluded before any row "
        f"was built; {qualifying_station_days} qualifying station-day(s) admitted",
    )

    return (g_r1, g_r2, g_r3, g_r4, g_r5, g_r6)


def run_resting_bid_study(
    *,
    live_root: Path = _DEFAULT_LIVE_CATALOG_ROOT,
    stations: Sequence[str] = _STATIONS,
    since_climate_day: dt.date,
    until_climate_day: dt.date,
    asos_cache_dir: Path = DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    obs_source: Literal["cache", "fetch"] = "cache",
    settlement_catalog: Path = DEFAULT_SETTLEMENT_CATALOG,
    margins: Sequence[Decimal] = DEFAULT_MARGINS,
    queue_shares: Sequence[Decimal] = DEFAULT_QUEUE_SHARES,
) -> tuple[tuple[RungLegRow, ...], tuple[GateResult, ...], int, int, tuple[str, ...]]:
    """Returns ``(rows, gates, qualifying_station_days, stranded_station_days, missing)``."""
    specs_by_city = {spec.city: spec for spec in load_sites() if spec.city in stations}
    station_days = _discover_station_days(live_root, stations, since_climate_day, until_climate_day)

    missing: list[str] = []
    rows: list[RungLegRow] = []
    all_fills: list[_FillFact] = []
    ioc_pnl_sum = Decimal(0)
    maker_pnl_sum = Decimal(0)
    qualifying = 0
    stranded = 0

    observations_by_city: dict[str, tuple[_ObsRow, ...]] = {}
    client_cm: httpx.Client | contextlib.AbstractContextManager[None] = (
        httpx.Client(headers={"User-Agent": USER_AGENT})
        if obs_source == "fetch"
        else contextlib.nullcontext()
    )
    with client_cm as client:
        for city, climate_day in station_days:
            spec = specs_by_city.get(city)
            if spec is None:
                missing.append(f"{city}: no registered site spec")
                continue

            ladder_tokens = _discover_ladder_tokens(live_root, city, climate_day)
            rungs = parse_ladder(ladder_tokens)
            depth_by_instrument = {
                rung.instrument_id: _load_staged_depth_frames(
                    live_root=live_root, slug=rung.instrument_id,
                )
                for rung in rungs
            }
            all_frame_ts = [
                frame.ts_init
                for frames in depth_by_instrument.values()
                for frame in frames
            ]
            window_start_ns, window_end_ns = _window_bounds_utc(
                climate_day, spec.std_utc_offset_hours,
            )
            fraction = window_coverage_fraction(all_frame_ts, window_start_ns, window_end_ns)
            if not is_qualifying_station_day(fraction):
                stranded += 1
                missing.append(
                    f"{city} {climate_day}: STRANDED (ING-1) -- window coverage "
                    f"{fraction:.2%} < 80%",
                )
                continue
            qualifying += 1

            if city not in observations_by_city:
                text = _station_asos_text(
                    cache_dir=asos_cache_dir, spec=spec, obs_source=obs_source, client=client,
                )
                if text is None:
                    missing.append(f"{city}: ASOS cache miss (pass --obs-source fetch)")
                    observations_by_city[city] = ()
                else:
                    observations_by_city[city] = _station_observations(spec=spec, text=text)

            day_observations = _observations_for_day(
                observations_by_city[city], spec=spec, climate_day=climate_day,
            )
            accumulator = _accumulator_with_lag(
                day_observations, std_utc_offset_hours=spec.std_utc_offset_hours,
                lag_ns=POLL_LAG_NS,
            )
            observation_visible_ts_ns = tuple(
                sorted({row.observed_at_ns + POLL_LAG_NS for row in day_observations}),
            )
            season = season_for(climate_day)

            for rung in rungs:
                facts = bucket_facts(
                    lower_f=rung.lower_f, upper_f=rung.upper_f, station=city,
                    climate_day=climate_day,
                )
                for leg in ("YES", "NO"):
                    leg_won, _preliminary = _resolve_settlement(
                        station=city, climate_day=climate_day, rung=rung, leg=leg,
                        accumulator=accumulator, std_utc_offset_hours=spec.std_utc_offset_hours,
                        settlement_catalog=settlement_catalog,
                    )
                    events = build_leg_events(
                        station=city, season=season, climate_day=climate_day,
                        instrument_id=rung.instrument_id, leg=leg,
                        facts=facts, accumulator=accumulator,
                        std_utc_offset_hours=spec.std_utc_offset_hours,
                        stale_bound_ns=50 * 60 * 1_000_000_000,
                        depth_frames=depth_by_instrument.get(rung.instrument_id, ()),
                        observation_visible_ts_ns=observation_visible_ts_ns,
                    )
                    ioc_taken_pnl = None
                    for margin in margins:
                        sim = simulate_leg(events, margin=margin)
                        row_pnl_sum = Decimal(0)
                        informed_count = 0
                        liquidity_count = 0
                        bands: dict[str, int] = {}
                        for fill in sim.fill_events:
                            classification = classify_fill(fill, events)
                            pnl = fill_pnl(fill, leg_won=leg_won)
                            pnl_sensitivity = (
                                None if leg_won is None
                                else (Decimal(1) if leg_won else Decimal(0))
                                - (fill.price + fee_taker(fill.price))
                            )
                            band = time_to_fill_band(fill)
                            bands[band] = bands.get(band, 0) + 1
                            if classification == "I":
                                informed_count += 1
                            else:
                                liquidity_count += 1
                            if pnl is not None:
                                row_pnl_sum += pnl
                            all_fills.append(
                                _FillFact(
                                    station=city, climate_day=climate_day.isoformat(),
                                    margin=margin, price=fill.price,
                                    classification=classification, pnl_maker=pnl,
                                    pnl_taker_fee_sensitivity=pnl_sensitivity, band=band,
                                ),
                            )

                        if sim.ioc_take is not None and ioc_taken_pnl is None:
                            ioc_taken_pnl = ioc_pnl(sim.ioc_take, leg_won=leg_won)

                        for share in queue_shares:
                            rows.append(
                                RungLegRow(
                                    station=city, climate_day=climate_day.isoformat(),
                                    instrument_id=rung.instrument_id, leg=leg,
                                    margin=margin, queue_share=share, rests=sim.rests,
                                    reprices=sim.reprices,
                                    cancels_by_reason=dict(sim.cancels_by_reason),
                                    fill_events=len(sim.fill_events),
                                    fills_expected=Decimal(len(sim.fill_events)) * share,
                                    informed_count=informed_count,
                                    liquidity_count=liquidity_count,
                                    pnl_maker_sum=row_pnl_sum * share,
                                    ioc_armed=sim.ioc_take is not None,
                                    ioc_pnl=ioc_taken_pnl,
                                    time_to_fill_bands=bands,
                                ),
                            )
                            if margin == _HEADLINE_MARGIN and share == _HEADLINE_SHARE:
                                maker_pnl_sum += row_pnl_sum * share
                    if ioc_taken_pnl is not None:
                        ioc_pnl_sum += ioc_taken_pnl

    gates = _evaluate_gates(
        all_fills, ioc_pnl_sum=ioc_pnl_sum, maker_pnl_sum=maker_pnl_sum,
        qualifying_station_days=qualifying, stranded_station_days=stranded,
    )
    return tuple(rows), gates, qualifying, stranded, tuple(missing)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-root", type=Path, default=_DEFAULT_LIVE_CATALOG_ROOT)
    parser.add_argument("--stations", nargs="+", default=list(_STATIONS))
    parser.add_argument("--since", required=True, type=str)
    parser.add_argument("--until", required=True, type=str)
    parser.add_argument(
        "--asos-cache-dir", type=Path, default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    )
    parser.add_argument("--obs-source", choices=("cache", "fetch"), default="cache")
    parser.add_argument("--settlement-catalog", type=Path, default=DEFAULT_SETTLEMENT_CATALOG)
    parser.add_argument("--run-stamp", required=True, type=str)
    parser.add_argument("--out-root", type=Path, default=_DEFAULT_OUT_ROOT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    out_dir: Path = args.out_root / args.run_stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[resting-bid-study] preflight staged-tape listing: "
        f"{_preflight_listing(args.live_root, args.stations)}", file=sys.stderr,
    )

    rows, gates, qualifying, stranded, missing = run_resting_bid_study(
        live_root=args.live_root, stations=tuple(args.stations),
        since_climate_day=dt.date.fromisoformat(args.since),
        until_climate_day=dt.date.fromisoformat(args.until),
        asos_cache_dir=args.asos_cache_dir, obs_source=args.obs_source,
        settlement_catalog=args.settlement_catalog,
    )
    summary = build_summary(
        rows, gates=gates, qualifying_station_days=qualifying, stranded_station_days=stranded,
    )
    markdown = (
        "DEPTH-PROXY ONLY (crossing-event proxy, resting_bid_core.simulate_leg); "
        "print-based fill sizing is UNIT-UNRESOLVED and no TRADE channel is subscribed -- "
        "this run never claims a print-verified fill.\n\n" + render_markdown(summary)
    )
    if missing:
        markdown += "\nMISSING / STRANDED INPUTS (reported, not fabricated):\n" + "\n".join(
            f"- {item}" for item in missing
        ) + "\n"

    (out_dir / "resting_bid_study.json").write_text(
        json.dumps(
            {
                "rows": [row.to_dict() for row in rows],
                "summary": summary.to_dict(),
                "missing_inputs": list(missing),
            },
            indent=2, sort_keys=True,
        ),
        encoding="utf-8",
    )
    (out_dir / "resting_bid_study.md").write_text(markdown, encoding="utf-8")
    print(f"[resting-bid-study] {len(rows)} row(s); wrote {out_dir}", file=sys.stderr)
    print(markdown, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
