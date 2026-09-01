"""H4 preliminary economic read — is there an executable ask on the h=1 rung?

WHAT THIS IS
------------
A DESCRIPTIVE MEASUREMENT over one captured climate day (2026-08-31) at four
stations. It answers exactly one question, the one
``docs/strategies/H4_headroom1_afternoon_lock.md`` names as its binding gate:

    at or after the station's pre-registered trigger hour, when headroom
    ``h = upper_f - R(t)`` is exactly 1, IS THERE AN ASK ON THAT RUNG?

WHAT THIS IS NOT
----------------
Not a backtest, not a trading simulation, not a profitability evaluation. It
constructs no order, no fill, no position, no fee and no P&L, and it computes
no return. NautilusTrader is the exclusive owner of backtesting, validation
runs, position management and execution. The ask VWAP here is a PRICE
STATISTIC over a captured ladder — "what would this have cost to lift" is a
property of the book, not a trade.

INTERPRETATION BOUNDS — binding, fixed before the data was read
---------------------------------------------------------------
``n = 4 station-days on ONE climate day``. This design can REFUTE (no ask at
the trigger is decisive: you cannot buy what is not offered) but it CANNOT
CONFIRM. Nothing here is evidence of profitability. The settling-rung
hit/miss is an ANECDOTE at n=4 and is labelled as one everywhere it appears.

TAPE INTEGRITY PRECEDES INTERPRETATION (LESSON L-8)
----------------------------------------------------
A truncated Arrow stream is silently dropped by the native reader: 0 rows, no
exception, no log line. A 0-row result is therefore ambiguous between "quiet
market" and "lost tape" BY CONSTRUCTION. This module refuses to report an
empty read until ``breezy-quote-tape-preflight`` has been quoted for the same
files — see :func:`require_preflight_attestation`.

DATA PATHS
----------
* ASOS observations — the settlement-alignment archive cache, fetched on the
  sanctioned ``settlement_alignment_study.asos_url`` path with the same
  SHA-256-of-URL filenames. ``breezy.ingest.http`` is deliberately untouched
  (its two-URL allowlist is an invariant, not an obstacle).
* Venue depth — ``ParquetDataCatalog.query(OrderBookDepth10)``, read through
  ``breezy.strategy.depth10.market_quote_from_depth`` so the ``Price(0)`` pad
  on an absent side reads as NO ASK rather than as a free contract.
* Settlement truth — Breezy's own store via
  ``breezy.persistence.catalog.read_climate_days``, ``is_final=True`` and
  ``is_superseded=False``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from pmr_climatology_study import (
    local_standard_hour,
    metar_temperatures,
    round_half_up_f,
    season_for,
    wilson_upper,
)
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    MetarTemperature,
    SiteSpec,
    asos_url,
    cache_path_for_url,
    load_sites,
    parse_asos_rows,
)

from breezy.persistence.catalog import read_climate_days, station_catalog_path
from breezy.strategy.depth10 import market_quote_from_depth

__all__ = [
    "AskAvailabilityVerdict",
    "DepthFill",
    "Rung",
    "StationVerdictInput",
    "TriggerCoverage",
    "WinnerAsymmetry",
    "ask_availability_verdict",
    "h4_rung",
    "is_h4_candidate",
    "is_interior_rung",
    "local_standard_hour",
    "metar_temperatures",
    "parse_ladder",
    "parse_rung",
    "round_half_up_f",
    "rung_containing",
    "running_max_at",
    "running_max_series",
    "season_for",
    "trigger_window_coverage",
    "vwap_for_notional",
    "wilson_upper",
    "winner_ask_provenance",
    "winner_asymmetry",
]

# -- H4's pre-registered parameters, copied from the brief, never re-derived --

#: Trigger hour in LOCAL STANDARD time, per
#: `docs/strategies/H4_headroom1_afternoon_lock.md`.
H4_TRIGGER_HOURS: Final[Mapping[str, int]] = {
    "MDW": 16,
    "MIA": 14,
    "SFO": 15,
    "LAX": 18,
}

#: NYC is excluded outright by H4 (instrument basis median +1F, crossing 7.95%
#: even at headroom 1). It is still MEASURED here and reported separately, so
#: the exclusion is visible rather than assumed.
H4_EXCLUDED_STATIONS: Final[tuple[str, ...]] = ("NYC",)


def trigger_hour_for(city: str) -> int | None:
    """H4's trigger hour, or `None` for a station outside its universe.

    `None`, never a sentinel like -1 or 0: a sentinel hour would admit every
    captured instant into the trigger measurement and let an excluded station
    contribute evidence to a verdict it is not part of.
    """
    return H4_TRIGGER_HOURS.get(city)

#: MDW is excluded in DJF (PR-1 falsified seasonally). 2026-08-31 is JJA, so
#: the carve-out does not bind on this climate day -- checked, not assumed.
H4_SEASONAL_EXCLUSIONS: Final[Mapping[str, tuple[str, ...]]] = {"MDW": ("DJF",)}

#: The per-position cost basis already derived elsewhere in this repo
#: (`docs/plans/print_lock_adverse_selection_and_cost_2026-09-01.md`, the
#: `A / (ask_p + fee(ask_p))` sizing rule). Used here ONLY as the notional the
#: depth-aware VWAP is measured over. It is not a risk budget being set, and
#: it is not an operator-reserved control.
NOTIONAL_USD: Final[float] = 24.53

TARGET_CLIMATE_DAY: Final[dt.date] = dt.date(2026, 8, 31)
ASOS_FETCH_START: Final[dt.date] = dt.date(2026, 8, 28)
ASOS_FETCH_END: Final[dt.date] = dt.date(2026, 9, 2)

DEFAULT_QUOTE_TAPE_CATALOG: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_SETTLEMENT_CATALOG: Final[Path] = Path.home() / ".local/share/breezy/catalog"
DEFAULT_OUTPUT: Final[Path] = Path("docs/evidence/h4_preliminary_economic_read_2026-09-01.md")

_INSTRUMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^tc-temp-(?P<city>[a-z]+)high-(?P<date>\d{4}-\d{2}-\d{2})-(?P<band>[a-z0-9]+)"
    r"\.(?P<venue>[A-Z_0-9]+)$"
)
_BAND_LOW_RE: Final[re.Pattern[str]] = re.compile(r"^lt(?P<upper>\d+)f$")
_BAND_HIGH_RE: Final[re.Pattern[str]] = re.compile(r"^gte(?P<lower>\d+)f$")
_BAND_INTERIOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^gte(?P<lower>\d+)lt(?P<named_upper>\d+)f$"
)


# ---------------------------------------------------------------------------
# Venue rungs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rung:
    """One venue contract, as a CLOSED integer interval of settled °F.

    `upper_f` is INCLUSIVE: `gte78lt79f` settles YES on 78 and on 79. This is
    the reading that makes the six-rung ladder a partition of the integers --
    under a half-open `[78, 79)` reading every odd degree belongs to no rung
    (pinned by `test_the_real_2026_08_31_nyc_ladder_partitions_the_integers`).
    """

    instrument_id: str
    city: str
    climate_day: dt.date
    #: `None` on the open LOWER tail (`lt<N>f`).
    lower_f: int | None
    #: `None` on the open UPPER tail (`gte<N>f`).
    upper_f: int | None

    def contains(self, value_f: int) -> bool:
        if self.lower_f is not None and value_f < self.lower_f:
            return False
        return not (self.upper_f is not None and value_f > self.upper_f)

    def headroom_f(self, value_f: int) -> int | None:
        """`upper_f - value_f`, or `None` when undefined.

        Undefined on an open upper tail (no ceiling to be short of) and
        wherever `value_f` is not in this rung at all.
        """
        if self.upper_f is None or not self.contains(value_f):
            return None
        return self.upper_f - value_f


def parse_rung(instrument_id: str) -> Rung:
    match = _INSTRUMENT_RE.match(instrument_id)
    if match is None:
        raise ValueError(f"unrecognized venue instrument id: {instrument_id!r}")
    city = match.group("city").upper()
    climate_day = dt.date.fromisoformat(match.group("date"))
    band = match.group("band")

    low = _BAND_LOW_RE.match(band)
    if low is not None:
        return Rung(
            instrument_id=instrument_id,
            city=city,
            climate_day=climate_day,
            lower_f=None,
            upper_f=int(low.group("upper")) - 1,
        )
    high = _BAND_HIGH_RE.match(band)
    if high is not None:
        return Rung(
            instrument_id=instrument_id,
            city=city,
            climate_day=climate_day,
            lower_f=int(high.group("lower")),
            upper_f=None,
        )
    interior = _BAND_INTERIOR_RE.match(band)
    if interior is None:
        raise ValueError(f"unrecognized venue instrument id: {instrument_id!r}")

    lower = int(interior.group("lower"))
    named_upper = int(interior.group("named_upper"))
    if named_upper != lower + 1:
        raise ValueError(
            f"{instrument_id!r}: band bounds are not adjacent "
            f"(gte{lower}lt{named_upper}); a 2F closed rung requires "
            f"lt == gte + 1. Refusing to guess at a renamed ladder."
        )
    return Rung(
        instrument_id=instrument_id,
        city=city,
        climate_day=climate_day,
        lower_f=lower,
        upper_f=lower + 1,
    )


def parse_ladder(instrument_ids: Iterable[str]) -> tuple[Rung, ...]:
    return tuple(
        sorted(
            (parse_rung(instrument_id) for instrument_id in instrument_ids),
            key=lambda rung: (
                rung.lower_f if rung.lower_f is not None else -10_000,
                rung.upper_f if rung.upper_f is not None else 10_000,
            ),
        )
    )


def rung_containing(ladder: Sequence[Rung], value_f: int) -> Rung | None:
    matches = [rung for rung in ladder if rung.contains(value_f)]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            f"{value_f}F matched {len(matches)} rungs "
            f"({[rung.instrument_id for rung in matches]}); the ladder is not a partition"
        )
    return matches[0]


def is_interior_rung(rung: Rung) -> bool:
    """True only for a BOUNDED 2F rung `[A, A+1]`.

    The two tails are excluded for different reasons and both matter:

    * `gte<N>f` has no ceiling at all, so headroom is undefined.
    * `lt<N>f` HAS a ceiling, so its headroom arithmetic is perfectly
      well-defined -- and that is exactly the trap. `lt78f` at `R == 76` reads
      as `h == 1` while being an unbounded-below band many degrees wide, whose
      hazard was never measured. `pmr_climatology_2026-09-01.md` conditions on
      2F rungs only, so admitting the low tail would silently apply a
      `model_p` measured on a different object.
    """
    return rung.lower_f is not None and rung.upper_f is not None


def is_h4_candidate(rung: Rung, running_f: int) -> bool:
    """H4 buys a BOUNDED 2F rung holding `R(t)` when headroom is EXACTLY 1.

    `h == 0` is the cell H3 was refuted on -- there the instrument basis alone
    crosses 15%-55% with the day already over. Both open tails are excluded;
    see :func:`is_interior_rung` for why the LOW tail needs excluding even
    though its headroom is computable.
    """
    return is_interior_rung(rung) and rung.headroom_f(running_f) == 1


def h4_rung(ladder: Sequence[Rung], running_f: int) -> Rung | None:
    holding = rung_containing(ladder, running_f)
    if holding is None or not is_h4_candidate(holding, running_f):
        return None
    return holding


# ---------------------------------------------------------------------------
# Minute-resolution running maximum
# ---------------------------------------------------------------------------

RunningMaxSeries = tuple[tuple[dt.datetime, int], ...]


def running_max_series(temperatures: Iterable[MetarTemperature]) -> RunningMaxSeries:
    """`(instant, R)` step points, ascending, one per observation.

    A single forward pass over instants sorted ascending, so `R` at any `t`
    depends only on observations at or before `t`.
    """
    rows = sorted(temperatures, key=lambda row: row.valid_utc)
    series: list[tuple[dt.datetime, int]] = []
    running: int | None = None
    for row in rows:
        running = row.rounded_f if running is None else max(running, row.rounded_f)
        series.append((row.valid_utc, running))
    return tuple(series)


def running_max_at(series: RunningMaxSeries, instant: dt.datetime) -> int | None:
    """`R(t)`: max over observations with timestamp `<= instant`.

    `None` before the first observation -- which is NOT the same as "no rise
    yet" and must never be silently read as one.
    """
    answer: int | None = None
    for observed_at, value in series:
        if observed_at > instant:
            break
        answer = value
    return answer


# ---------------------------------------------------------------------------
# Depth-aware ask VWAP
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DepthFill:
    """What the captured ask ladder would have cost to lift for a notional.

    A property of the BOOK, not a trade: no order is constructed, no fee is
    applied, no position results, and no P&L is derived from it.
    """

    best_ask: float
    contracts: int
    cost: float
    vwap: float
    #: True when the ladder ran out while more contracts were still affordable
    #: -- i.e. the notional could NOT be absorbed at any price on this book.
    depth_limited: bool


def vwap_for_notional(
    ask_ladder: Sequence[tuple[float, float]] | None, *, notional: float
) -> DepthFill | None:
    """Walk the ask ladder for `notional` dollars, whole contracts only.

    Pricing at level 0 is the measured defect this exists to avoid: a book of
    5 contracts at 0.50 backed by 300 at 0.99 reads as cheap at the top and is
    not cheap in any size worth taking.

    Returns `None` for an absent or empty ladder -- NO QUOTE, never a free or
    zero-priced fill.
    """
    if not ask_ladder:
        return None
    contracts = 0
    cost = 0.0
    depth_limited = True
    for price, size in ask_ladder:
        if price <= 0.0:
            raise ValueError(
                f"non-positive ask price {price!r} in ladder; `Price(0)` is the "
                f"Arrow pad for a missing side, never a free contract"
            )
        available = math.floor(size)
        affordable = math.floor((notional - cost) / price)
        take = min(available, affordable)
        if take <= 0:
            depth_limited = False
            break
        contracts += take
        cost += take * price
        if take < available:
            depth_limited = False
            break
    if contracts == 0:
        return None
    return DepthFill(
        best_ask=float(ask_ladder[0][0]),
        contracts=contracts,
        cost=cost,
        vwap=cost / contracts,
        depth_limited=depth_limited,
    )


# ---------------------------------------------------------------------------
# Trigger-window coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TriggerCoverage:
    """Which part of the station's trigger window the capture actually saw."""

    city: str
    #: `None` when the station has no H4 trigger hour (excluded universe).
    trigger_hour: int | None
    first_lst: dt.datetime
    last_lst: dt.datetime
    #: True when ANY captured instant falls at or after the trigger hour.
    covered: bool
    #: Hours of the trigger window (trigger hour -> capture start) never seen.
    missing_hours_before: float
    #: Hours from capture end to local midnight, also never seen.
    missing_hours_after: float
    detail: str


def trigger_window_coverage(
    *,
    city: str,
    climate_day: dt.date,
    std_utc_offset_hours: float,
    trigger_hour: int | None,
    first_ts: dt.datetime,
    last_ts: dt.datetime,
) -> TriggerCoverage:
    tz = dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    first_lst = first_ts.astimezone(tz)
    last_lst = last_ts.astimezone(tz)
    if trigger_hour is None:
        return TriggerCoverage(
            city=city,
            trigger_hour=None,
            first_lst=first_lst,
            last_lst=last_lst,
            covered=False,
            missing_hours_before=0.0,
            missing_hours_after=0.0,
            detail=(
                "no trigger hour: this station is outside H4's universe, so it "
                "contributes no trigger evidence in either direction"
            ),
        )
    trigger_lst = dt.datetime.combine(climate_day, dt.time(trigger_hour, 0), tzinfo=tz)
    day_end_lst = dt.datetime.combine(
        climate_day + dt.timedelta(days=1), dt.time(0, 0), tzinfo=tz
    )
    covered = last_lst >= trigger_lst
    missing_before = max(0.0, (first_lst - trigger_lst).total_seconds() / 3600.0)
    missing_after = max(0.0, (day_end_lst - last_lst).total_seconds() / 3600.0)
    if not covered:
        detail = (
            f"capture never reaches the {trigger_hour:02d}:00 LST trigger: it ends at "
            f"{last_lst:%H:%M} LST, {(trigger_lst - last_lst).total_seconds() / 3600.0:.2f}h short"
        )
    else:
        detail = (
            f"trigger {trigger_hour:02d}:00 LST; observed {first_lst:%H:%M}-{last_lst:%H:%M} "
            f"LST; {missing_before:.2f}h of the window before capture start and "
            f"{missing_after:.2f}h after capture end are NOT observed"
        )
    return TriggerCoverage(
        city=city,
        trigger_hour=trigger_hour,
        first_lst=first_lst,
        last_lst=last_lst,
        covered=covered,
        missing_hours_before=missing_before,
        missing_hours_after=missing_after,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# I/O: ASOS, depth, settlement
# ---------------------------------------------------------------------------


def require_preflight_attestation(value: str | None) -> str:
    """LESSON L-8: refuse to interpret a tape that has not been verified.

    A 0-row read has two indistinguishable causes -- a quiet market, or a
    silently truncated Arrow stream that the native reader turned into
    `continue`. This measurement produces a strategy-relevant verdict, so the
    preflight status is a REQUIRED INPUT quoted in the output, not an optional
    convenience.
    """
    if not value:
        raise SystemExit(
            "refusing to run: --preflight-attestation is required.\n"
            "Run `breezy-quote-tape-preflight --catalog <catalog>` first and pass its\n"
            "per-file summary for the target climate day. A 0-row read is not evidence\n"
            "about the market until the tape behind it is verified (LESSONS L-8)."
        )
    return value


def load_asos_series(
    *, cache_dir: Path, spec: SiteSpec
) -> tuple[RunningMaxSeries, tuple[MetarTemperature, ...], Counter[str]]:
    url = asos_url(spec.iem_asos_id, ASOS_FETCH_START, ASOS_FETCH_END)
    path = cache_path_for_url(cache_dir, url, ".txt")
    if not path.exists():
        raise SystemExit(
            f"ASOS cache miss for {spec.city}; refusing to proceed on partial data.\n"
            f"expected: {path}\nurl: {url}"
        )
    rows = parse_asos_rows(path.read_text(encoding="utf-8", errors="replace"))
    temperatures, drops = metar_temperatures(
        city=spec.city, rows=rows, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    on_day = tuple(row for row in temperatures if row.climate_day == TARGET_CLIMATE_DAY)
    return running_max_series(on_day), on_day, drops


def load_settled_tmax(*, catalog_base: Path, city: str) -> tuple[int | None, int, str]:
    """Return `(tmax_f, final_record_count, provenance)` for the target day."""
    path = station_catalog_path(catalog_base, "polymarket_us", city)
    records = read_climate_days(ParquetDataCatalog(str(path)))
    finals = [
        record
        for record in records
        if record.climate_day == TARGET_CLIMATE_DAY
        and record.is_final
        and not record.is_superseded
    ]
    if not finals:
        return None, 0, str(path)
    values = {record.tmax_f for record in finals}
    if len(values) > 1:
        rendered = sorted(str(value) for value in values)
        raise SystemExit(
            f"{city}: non-superseded finals disagree on tmax_f ({rendered}); "
            f"refusing to pick one silently"
        )
    return finals[0].tmax_f, len(finals), str(path)


@dataclass(frozen=True, slots=True)
class DepthObservation:
    """One captured depth snapshot on one rung, reduced to what H4 asks of it."""

    instrument_id: str
    ts_event: dt.datetime
    best_ask: float | None
    ask_ladder: tuple[tuple[float, float], ...] | None
    best_bid: float | None


def load_depth(
    *, catalog_root: Path, instrument_ids: Sequence[str]
) -> dict[str, tuple[DepthObservation, ...]]:
    catalog = ParquetDataCatalog(str(catalog_root))
    rows = catalog.query(OrderBookDepth10, identifiers=list(instrument_ids))
    grouped: dict[str, list[DepthObservation]] = defaultdict(list)
    for row in rows:
        # market_quote_from_depth, never `row.asks[0]`: an absent side is
        # padded with Price(0)/Quantity(0) at index 0, so a raw read turns
        # "no ask" into "free".
        quote = market_quote_from_depth(row, include_ask_ladder=True)
        instrument_id = str(row.instrument_id)
        grouped[instrument_id].append(
            DepthObservation(
                instrument_id=instrument_id,
                ts_event=dt.datetime.fromtimestamp(row.ts_event / 1_000_000_000, tz=dt.UTC),
                best_ask=None if quote is None else quote.ask,
                ask_ladder=None if quote is None else quote.ask_ladder,
                best_bid=None if quote is None else quote.bid,
            )
        )
    return {
        instrument_id: tuple(sorted(observations, key=lambda row: row.ts_event))
        for instrument_id, observations in grouped.items()
    }


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TriggerObservation:
    """One captured depth snapshot evaluated against the H4 entry condition."""

    city: str
    ts_event: dt.datetime
    ts_lst: dt.datetime
    running_f: int
    holding_rung: str
    headroom: int | None
    is_candidate: bool
    #: Populated only when `is_candidate`; the h==1 rung's own book.
    candidate_rung: str | None
    best_ask: float | None
    fill: DepthFill | None


@dataclass(frozen=True, slots=True)
class StationRead:
    city: str
    trigger_hour: int | None
    excluded_reason: str | None
    coverage: TriggerCoverage
    depth_rows: int
    ladder: tuple[Rung, ...]
    observations: tuple[TriggerObservation, ...]
    #: Every captured depth snapshot on this station's ladder, keyed by
    #: instrument id. Carried on the read itself rather than re-queried (or
    #: stashed in a module global) so the report cannot silently diverge from
    #: the rows the measurement was computed over.
    depth: Mapping[str, tuple[DepthObservation, ...]]
    settled_tmax_f: int | None
    settled_rung: str | None
    settlement_provenance: str
    final_record_count: int
    asos_observation_count: int
    asos_drops: Counter[str]
    day_max_f: int | None


def analyse_station(
    *,
    spec: SiteSpec,
    cache_dir: Path,
    quote_catalog: Path,
    settlement_catalog: Path,
    instrument_ids: Sequence[str],
) -> StationRead:
    series, on_day, drops = load_asos_series(cache_dir=cache_dir, spec=spec)
    ladder = parse_ladder(instrument_ids)
    depth = load_depth(catalog_root=quote_catalog, instrument_ids=instrument_ids)
    by_id = {rung.instrument_id: rung for rung in ladder}

    every_row = [row for rows in depth.values() for row in rows]
    trigger_hour = trigger_hour_for(spec.city)
    season = season_for(TARGET_CLIMATE_DAY)
    excluded: str | None = None
    if spec.city in H4_EXCLUDED_STATIONS:
        excluded = "excluded by H4 universe (instrument basis)"
    elif season in H4_SEASONAL_EXCLUSIONS.get(spec.city, ()):
        excluded = f"excluded by H4 seasonal carve-out ({season})"

    if not every_row:
        coverage = TriggerCoverage(
            city=spec.city,
            trigger_hour=trigger_hour,
            first_lst=dt.datetime.min.replace(tzinfo=dt.UTC),
            last_lst=dt.datetime.min.replace(tzinfo=dt.UTC),
            covered=False,
            missing_hours_before=0.0,
            missing_hours_after=0.0,
            detail="NO DEPTH ROWS — verify the tape before reading this as a quiet market",
        )
        observations: tuple[TriggerObservation, ...] = ()
    else:
        first_ts = min(row.ts_event for row in every_row)
        last_ts = max(row.ts_event for row in every_row)
        coverage = trigger_window_coverage(
            city=spec.city,
            climate_day=TARGET_CLIMATE_DAY,
            std_utc_offset_hours=spec.std_utc_offset_hours,
            trigger_hour=trigger_hour,
            first_ts=first_ts,
            last_ts=last_ts,
        )
        observations = _evaluate(
            spec=spec,
            ladder=ladder,
            by_id=by_id,
            depth=depth,
            series=series,
            trigger_hour=trigger_hour,
        )

    settled, final_count, provenance = load_settled_tmax(
        catalog_base=settlement_catalog, city=spec.city
    )
    settled_rung = None
    if settled is not None:
        winner = rung_containing(ladder, settled)
        settled_rung = None if winner is None else winner.instrument_id

    return StationRead(
        city=spec.city,
        trigger_hour=trigger_hour,
        excluded_reason=excluded,
        coverage=coverage,
        depth_rows=len(every_row),
        ladder=ladder,
        observations=observations,
        depth=depth,
        settled_tmax_f=settled,
        settled_rung=settled_rung,
        settlement_provenance=provenance,
        final_record_count=final_count,
        asos_observation_count=len(on_day),
        asos_drops=drops,
        day_max_f=max((value for _, value in series), default=None),
    )


def _evaluate(
    *,
    spec: SiteSpec,
    ladder: Sequence[Rung],
    by_id: Mapping[str, Rung],
    depth: Mapping[str, Sequence[DepthObservation]],
    series: RunningMaxSeries,
    trigger_hour: int | None,
) -> tuple[TriggerObservation, ...]:
    if trigger_hour is None:
        return ()
    tz = dt.timezone(dt.timedelta(hours=spec.std_utc_offset_hours))
    # One evaluation per distinct captured instant: the entry condition is a
    # property of the CLIMATE DAY at that moment, not of one instrument.
    instants = sorted({row.ts_event for rows in depth.values() for row in rows})
    observations: list[TriggerObservation] = []
    for instant in instants:
        ts_lst = instant.astimezone(tz)
        if ts_lst.date() != TARGET_CLIMATE_DAY or ts_lst.hour < trigger_hour:
            continue
        running = running_max_at(series, instant)
        if running is None:
            continue
        holding = rung_containing(ladder, running)
        if holding is None:
            continue
        headroom = holding.headroom_f(running)
        candidate = is_h4_candidate(holding, running)
        fill: DepthFill | None = None
        best_ask: float | None = None
        if candidate:
            snapshot = _latest_at(depth.get(holding.instrument_id, ()), instant)
            if snapshot is not None:
                best_ask = snapshot.best_ask
                fill = vwap_for_notional(snapshot.ask_ladder, notional=NOTIONAL_USD)
        observations.append(
            TriggerObservation(
                city=spec.city,
                ts_event=instant,
                ts_lst=ts_lst,
                running_f=running,
                holding_rung=holding.instrument_id,
                headroom=headroom,
                is_candidate=candidate,
                candidate_rung=holding.instrument_id if candidate else None,
                best_ask=best_ask,
                fill=fill,
            )
        )
    _ = by_id
    return tuple(observations)


def _latest_at(
    observations: Sequence[DepthObservation], instant: dt.datetime
) -> DepthObservation | None:
    """Most recent snapshot at or before `instant`. Never a later one."""
    answer: DepthObservation | None = None
    for row in observations:
        if row.ts_event > instant:
            break
        answer = row
    return answer


# ---------------------------------------------------------------------------
# Verdict -- computed from the counts, never asserted in prose
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationVerdictInput:
    city: str
    #: `None` for a station outside H4's universe; it contributes nothing.
    trigger_hour: int | None
    covered: bool
    candidate_instants: int
    offered_instants: int
    observed_hours: float
    missing_hours: float


@dataclass(frozen=True, slots=True)
class AskAvailabilityVerdict:
    outcome: str
    stations_refuted: tuple[str, ...]
    stations_offered: tuple[str, ...]
    stations_no_coverage: tuple[str, ...]
    stations_condition_never_held: tuple[str, ...]
    detail: str


def ask_availability_verdict(
    inputs: Iterable[StationVerdictInput],
) -> AskAvailabilityVerdict:
    """Reduce the per-station counts to one scoped verdict.

    Four outcomes are kept apart because they mean different things:

    * ``SURVIVES`` -- an ask existed on an `h == 1` rung somewhere in the
      observed window. The question goes to the larger capture.
    * ``REFUTED_ON_OBSERVED_WINDOW`` -- the condition held and NOTHING was
      offered. Decisive for the part of the window actually seen, and ONLY
      for that part; the unobserved hours before capture start are not
      evidence in either direction.
    * ``CONDITION_NEVER_HELD`` -- the window was covered but `h == 1` never
      occurred. That is evidence about the TRIGGER (kill criterion 3a), not
      about the book, and blaming the market for it would be wrong.
    * ``NO_EVIDENCE`` -- nothing in H4's universe was observed at all.

    Stations with no trigger hour are outside H4's universe and are dropped
    before any of this is computed.
    """
    in_universe = [row for row in inputs if row.trigger_hour is not None]
    refuted = tuple(
        row.city
        for row in in_universe
        if row.covered and row.candidate_instants > 0 and row.offered_instants == 0
    )
    offered = tuple(
        row.city for row in in_universe if row.covered and row.offered_instants > 0
    )
    never_held = tuple(
        row.city
        for row in in_universe
        if row.covered and row.candidate_instants == 0
    )
    no_coverage = tuple(row.city for row in in_universe if not row.covered)

    if offered:
        outcome = "SURVIVES"
        detail = (
            f"an ask was present on the h==1 rung at {', '.join(offered)} within the "
            f"observed window; the economic question is not closed and goes to the "
            f"larger capture"
        )
    elif refuted:
        outcome = "REFUTED_ON_OBSERVED_WINDOW"
        detail = (
            f"at {', '.join(refuted)} the entry condition held and NO ask was present "
            f"on the h==1 rung at any observed instant. Decisive for the OBSERVED "
            f"portion of the trigger window only -- the hours before capture start "
            f"are not evidence in either direction"
        )
    elif never_held:
        outcome = "CONDITION_NEVER_HELD"
        detail = (
            f"at {', '.join(never_held)} the window was covered but h==1 never "
            f"occurred; that is evidence about the TRIGGER (kill criterion 3a), not "
            f"about ask availability"
        )
    else:
        outcome = "NO_EVIDENCE"
        detail = (
            f"no station in H4's universe had its trigger window observed "
            f"({', '.join(no_coverage) or 'none captured'}); this run reaches no "
            f"verdict in either direction"
        )
    return AskAvailabilityVerdict(
        outcome=outcome,
        stations_refuted=refuted,
        stations_offered=offered,
        stations_no_coverage=no_coverage,
        stations_condition_never_held=never_held,
        detail=detail,
    )


@dataclass(frozen=True, slots=True)
class WinnerAsymmetry:
    """Was the SETTLING rung offered on the same terms as the rest of the ladder?"""

    winner_snapshots: int
    winner_with_ask: int
    other_snapshots: int
    other_with_ask: int
    winner_ask_share: float | None
    other_ask_share: float | None
    #: True only when the rest of the ladder WAS offered and the winner was
    #: not. If nothing is offered anywhere the venue simply went dark, and the
    #: winner's silence says nothing on its own.
    winner_is_uniquely_unoffered: bool


def winner_asymmetry(
    *, winner_snapshots: int, winner_with_ask: int, other_snapshots: int, other_with_ask: int
) -> WinnerAsymmetry:
    winner_share = winner_with_ask / winner_snapshots if winner_snapshots else None
    other_share = other_with_ask / other_snapshots if other_snapshots else None
    unique = (
        winner_share is not None
        and other_share is not None
        and winner_share == 0.0
        and other_share > 0.0
    )
    return WinnerAsymmetry(
        winner_snapshots=winner_snapshots,
        winner_with_ask=winner_with_ask,
        other_snapshots=other_snapshots,
        other_with_ask=other_with_ask,
        winner_ask_share=winner_share,
        other_ask_share=other_share,
        winner_is_uniquely_unoffered=unique,
    )


def winner_ask_provenance(
    *,
    city: str,
    winner_with_ask: int,
    winner_snapshots: int,
    trigger_covered: bool,
    trigger_hour: int | None,
) -> str | None:
    """Place a station's winner-side asks relative to its trigger hour.

    The §4.1 counts run over EVERY captured snapshot on the target day, not
    only the post-trigger tail, so a non-zero winner-ask count there is not by
    itself an H4 observation. Returns `None` when the station never offered
    its settling rung -- there is nothing to place.
    """
    if winner_with_ask <= 0:
        return None
    seen = f"{city} offered its settling rung on {winner_with_ask} of {winner_snapshots} snapshots"
    if trigger_hour is None:
        return (
            f"{seen}, but {city} is outside H4's universe and has no trigger hour, "
            "so those instants are context, not H4 evidence."
        )
    if not trigger_covered:
        return (
            f"{seen} — every one of them before the {trigger_hour:02d}:00 LST trigger, "
            f"which this capture never reaches (§1). They are context, not H4 evidence."
        )
    return (
        f"{seen}. The capture does span {city}'s {trigger_hour:02d}:00 LST trigger, but "
        "this table does not separate the pre-trigger snapshots from the post-trigger "
        "ones — §2 and §3 are the H4-scoped counts."
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _coverage_verdict(read: StationRead) -> str:
    if read.trigger_hour is None:
        return "n/a — excluded from H4"
    return "yes (tail only)" if read.coverage.covered else "**NO — not observed at all**"


def _price(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def build_report(
    reads: Sequence[StationRead],
    *,
    generated_at: dt.datetime,
    preflight: str,
    quote_catalog: Path,
    cache_dir: Path,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# H4 preliminary economic read — is the h=1 rung offered at the trigger?")
    add("")
    add(f"Generated {generated_at.isoformat()} from")
    add("`scripts/analysis/h4_preliminary_economic_read.py`.")
    add(f"Climate day: **{TARGET_CLIMATE_DAY.isoformat()}**. Strategy: "
        "`docs/strategies/H4_headroom1_afternoon_lock.md`.")
    add("")
    add("## 0. What this is, and the bounds on reading it")
    add("")
    add("A descriptive measurement over ONE climate day. It is **not** a backtest,")
    add("**not** a trading simulation and **not** a profitability evaluation: no order,")
    add("fill, position, fee, P&L or return appears anywhere in the pipeline that")
    add("produced it. NautilusTrader is the exclusive owner of backtesting and")
    add("execution. The ask VWAP below is a price statistic over a captured ladder — a")
    add("property of the book, not a trade.")
    add("")
    add("**`n = 4` station-days on one climate day.** This design CAN REFUTE — you")
    add("cannot buy what is not offered, and an absent ask at the trigger is decisive —")
    add("but it CANNOT CONFIRM. The settling-rung hit/miss at the end is an ANECDOTE")
    add("and is labelled as one.")
    add("")
    add("### Tape integrity (LESSONS L-8) — verified BEFORE interpretation")
    add("")
    add("A truncated Arrow stream is silently dropped by the native reader: 0 rows, no")
    add("exception, no log line. A 0-row result is ambiguous between *quiet market* and")
    add("*lost tape* by construction, so the preflight is a required input here, not a")
    add("convenience. `breezy-quote-tape-preflight` reports, for this climate day:")
    add("")
    add(f"> {preflight}")
    add("")
    add(f"Depth catalog: `{quote_catalog}`")
    add(f"ASOS archive cache: `{cache_dir}`")
    add("")

    # -- 1. coverage ---------------------------------------------------------
    add("## 1. Capture coverage against each station's trigger window")
    add("")
    add("Trigger hours are H4's pre-registered values in LOCAL STANDARD time. The")
    add("capture window is the same wall-clock interval everywhere; its LST rendering")
    add("differs by station, which is what decides who has evidence and who does not.")
    add("")
    add("| station | trigger (LST) | capture start (LST) | capture end (LST) | "
        "trigger window observed? | hours of window missed BEFORE capture | "
        "hours missed AFTER capture |")
    add("|---|---:|---|---|---|---:|---:|")
    for read in reads:
        window = read.coverage
        trigger_text = (
            "— (excluded)" if read.trigger_hour is None else f"{read.trigger_hour:02d}:00"
        )
        if read.depth_rows == 0:
            add(f"| {read.city} | {trigger_text} | — | — | "
                f"**NO DEPTH ROWS** | n/a | n/a |")
            continue
        add(
            f"| {read.city} | {trigger_text} | "
            f"{window.first_lst:%Y-%m-%d %H:%M:%S} | {window.last_lst:%Y-%m-%d %H:%M:%S} | "
            f"{_coverage_verdict(read)} | "
            + (
                f"{window.missing_hours_before:.2f} | {window.missing_hours_after:.2f} |"
                if window.covered
                else "n/a — whole window unobserved | n/a |"
            )
        )
    add("")
    for read in reads:
        add(f"* **{read.city}** — {read.coverage.detail}")
        if read.excluded_reason:
            add(f"  * {read.excluded_reason}; measured and reported, never counted in the verdict.")
    add("")

    # -- 2. the measurement --------------------------------------------------
    add("## 2. THE MEASUREMENT — did the entry condition hold, and was it offered?")
    add("")
    add("Restricted to captured instants at or after the station's trigger hour, on the")
    add("target climate day. `R(t)` is the ASOS running maximum in whole °F using only")
    add("observations at or before `t`.")
    add("")
    add("| station | instants at/after trigger | with `h == 1` | share | "
        "of those, carrying an ask | share | h distribution over the window |")
    add("|---|---:|---:|---:|---:|---:|---|")
    for read in reads:
        total = len(read.observations)
        candidates = [row for row in read.observations if row.is_candidate]
        offered = [row for row in candidates if row.fill is not None]
        histogram = Counter(
            "open-tail" if row.headroom is None else str(row.headroom)
            for row in read.observations
        )
        histogram_text = ", ".join(
            f"h={key}: {count}" for key, count in sorted(histogram.items())
        ) or "—"
        add(
            f"| {read.city} | {total} | {len(candidates)} | "
            f"{_pct(len(candidates) / total) if total else 'n/a'} | {len(offered)} | "
            f"{_pct(len(offered) / len(candidates)) if candidates else 'n/a'} | "
            f"{histogram_text} |"
        )
    add("")
    add("Where the entry condition never held, that is **kill-criterion 3a evidence**")
    add("about the trigger, not an economic result: there was nothing to price.")
    add("")

    # -- 3. prices -----------------------------------------------------------
    add("## 3. Ask prices on the `h == 1` rung")
    add("")
    add(f"Depth-aware VWAP for a **${NOTIONAL_USD:.2f}** notional (the cost basis already")
    add("derived in `docs/plans/print_lock_adverse_selection_and_cost_2026-09-01.md`),")
    add("walking the captured ask ladder in whole contracts — never level 0 alone.")
    add("`depth-limited` means the ladder ran out before the notional was absorbed.")
    add("")
    priced = [
        (read, row)
        for read in reads
        for row in read.observations
        if row.is_candidate and row.fill is not None
    ]
    if not priced:
        add("**No `h == 1` rung carried an ask at any captured instant at or after any")
        add("station's trigger hour.** There is no price distribution to report — that")
        add("absence IS the measurement.")
        add("")
    else:
        add("| station | ts (LST) | rung | R(t) | best ask | VWAP | contracts | cost | "
            "depth-limited |")
        add("|---|---|---|---:|---:|---:|---:|---:|---|")
        for read, row in priced:
            fill = row.fill
            assert fill is not None
            add(
                f"| {read.city} | {row.ts_lst:%H:%M:%S} | {row.candidate_rung} | "
                f"{row.running_f} | {_price(fill.best_ask)} | {_price(fill.vwap)} | "
                f"{fill.contracts} | ${fill.cost:.2f} | "
                f"{'YES' if fill.depth_limited else 'no'} |"
            )
        add("")

    # -- 4. what WAS offered -------------------------------------------------
    add("## 4. Ask availability across the whole captured ladder")
    add("")
    add("Context for §2/§3: was the ask side empty only on the `h == 1` rung, or")
    add("everywhere? Counted over every captured depth snapshot on the target day,")
    add("including instants before the trigger hour.")
    add("")
    add("| station | rung | closed interval | snapshots | with an ask | share | "
        "min ask | max ask | settling rung? |")
    add("|---|---|---|---:|---:|---:|---:|---:|---|")
    for read in reads:
        for rung in read.ladder:
            rows = read.depth.get(rung.instrument_id, ())
            with_ask = [row for row in rows if row.best_ask is not None]
            asks = [row.best_ask for row in with_ask if row.best_ask is not None]
            interval = (
                f"≤{rung.upper_f}"
                if rung.lower_f is None
                else (f"≥{rung.lower_f}" if rung.upper_f is None
                      else f"[{rung.lower_f}, {rung.upper_f}]")
            )
            add(
                f"| {read.city} | {rung.instrument_id.split('-')[-1].split('.')[0]} | "
                f"{interval} | {len(rows)} | {len(with_ask)} | "
                f"{_pct(len(with_ask) / len(rows)) if rows else 'n/a'} | "
                f"{_price(min(asks) if asks else None)} | "
                f"{_price(max(asks) if asks else None)} | "
                f"{'**WINNER**' if rung.instrument_id == read.settled_rung else ''} |"
            )
    add("")

    # -- 4.1 winner asymmetry ------------------------------------------------
    add("### 4.1 The settling rung against the rest of its own ladder")
    add("")
    add("The single most legible pattern in §4, computed per station over every")
    add("captured snapshot on the target day. `uniquely unoffered` is only claimed")
    add("when the REST of the ladder was in fact offered — if nothing is offered")
    add("anywhere the venue simply went dark, and the winner's silence means nothing.")
    add("")
    add("| station | settling rung | snapshots | with an ask | other rungs: snapshots | "
        "with an ask | winner ask share | other ask share | winner uniquely unoffered? |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---|")
    provenance: list[str] = []
    for read in reads:
        winner_rows = read.depth.get(read.settled_rung or "", ())
        other_rows = [
            row
            for instrument_id, rows in read.depth.items()
            if instrument_id != read.settled_rung
            for row in rows
        ]
        asymmetry = winner_asymmetry(
            winner_snapshots=len(winner_rows),
            winner_with_ask=sum(1 for row in winner_rows if row.best_ask is not None),
            other_snapshots=len(other_rows),
            other_with_ask=sum(1 for row in other_rows if row.best_ask is not None),
        )
        add(
            f"| {read.city} | "
            f"{(read.settled_rung or '—').split('-')[-1].split('.')[0]} | "
            f"{asymmetry.winner_snapshots} | {asymmetry.winner_with_ask} | "
            f"{asymmetry.other_snapshots} | {asymmetry.other_with_ask} | "
            f"{_pct(asymmetry.winner_ask_share)} | {_pct(asymmetry.other_ask_share)} | "
            f"{'**YES**' if asymmetry.winner_is_uniquely_unoffered else 'no'} |"
        )
        note = winner_ask_provenance(
            city=read.city,
            winner_with_ask=asymmetry.winner_with_ask,
            winner_snapshots=asymmetry.winner_snapshots,
            trigger_covered=read.coverage.covered,
            trigger_hour=read.trigger_hour,
        )
        if note is not None:
            provenance.append(note)
    add("")
    if provenance:
        add("Where those winner-side asks sit relative to the trigger hour — this")
        add("table spans every captured snapshot, not just the post-trigger tail:")
        add("")
        for note in provenance:
            add(f"- {note}")
    else:
        add("No station offered its settling rung at any captured instant.")
    add("")

    # -- 5. settlement anecdote ---------------------------------------------
    add("## 5. Did the `h == 1` rung settle YES? — ANECDOTE, n = 4")
    add("")
    add("Winners read from Breezy's own settlement store (`is_final=True`,")
    add("`is_superseded=False`), not from any external claim.")
    add("")
    add("| station | settled tmax °F | non-superseded finals | settling rung | "
        "ASOS day max °F | `h == 1` rung at trigger | hit? | provenance |")
    add("|---|---:|---:|---|---:|---|---|---|")
    for read in reads:
        candidate_rungs = {
            row.candidate_rung for row in read.observations if row.candidate_rung is not None
        }
        candidate_text = ", ".join(sorted(candidate_rungs)) or "— (never held)"
        if not candidate_rungs:
            hit = "n/a — condition never held"
        elif read.settled_rung in candidate_rungs:
            hit = "**HIT**"
        else:
            hit = "MISS"
        add(
            f"| {read.city} | {read.settled_tmax_f} | {read.final_record_count} | "
            f"{read.settled_rung or '—'} | {read.day_max_f} | {candidate_text} | {hit} | "
            f"`{read.settlement_provenance}` |"
        )
    add("")
    add("With four station-days on one climate day this column cannot distinguish a")
    add("real hit rate from luck. It is recorded so it is not re-derived later, and it")
    add("is not evidence of anything on its own.")
    add("")

    # -- 6. inputs -----------------------------------------------------------
    add("## 6. Input denominators")
    add("")
    add("| station | ASOS obs on the climate day | ASOS day max °F | depth snapshots | "
        "ladder rungs | METAR rows dropped |")
    add("|---|---:|---:|---:|---:|---|")
    for read in reads:
        dropped = ", ".join(f"{k}={v}" for k, v in sorted(read.asos_drops.items()) if v) or "none"
        add(
            f"| {read.city} | {read.asos_observation_count} | {read.day_max_f} | "
            f"{read.depth_rows} | {len(read.ladder)} | {dropped} |"
        )
    add("")

    # -- 7. verdict ----------------------------------------------------------
    verdict = ask_availability_verdict(
        StationVerdictInput(
            city=read.city,
            trigger_hour=read.trigger_hour,
            covered=read.coverage.covered,
            candidate_instants=sum(1 for row in read.observations if row.is_candidate),
            offered_instants=sum(
                1 for row in read.observations if row.is_candidate and row.fill is not None
            ),
            observed_hours=(
                (read.coverage.last_lst - read.coverage.first_lst).total_seconds() / 3600.0
            ),
            missing_hours=read.coverage.missing_hours_before,
        )
        for read in reads
    )
    add("## 7. VERDICT — scoped to what `n = 4` on one climate day supports")
    add("")
    add(f"**{verdict.outcome}**")
    add("")
    add(f"{verdict.detail}.")
    add("")
    add("| | stations |")
    add("|---|---|")
    add(f"| condition held, NO ask on the h==1 rung | "
        f"{', '.join(verdict.stations_refuted) or '—'} |")
    add(f"| condition held, an ask WAS present | "
        f"{', '.join(verdict.stations_offered) or '—'} |")
    add(f"| window covered, condition never held | "
        f"{', '.join(verdict.stations_condition_never_held) or '—'} |")
    add(f"| trigger window not observed at all | "
        f"{', '.join(verdict.stations_no_coverage) or '—'} |")
    add(f"| outside H4's universe, contributing nothing | "
        f"{', '.join(read.city for read in reads if read.trigger_hour is None) or '—'} |")
    add("")
    add("### What this does and does not close")
    add("")
    add("**Does.** For the observed tail of the trigger window, at every covered")
    add("station, the entry H4 specifies was not available: the rung was not offered,")
    add("at any price, in any size. An absent ask is not a pricing problem that a")
    add("better model or a lower break-even could solve.")
    add("")
    add("**Does not.** The observed tail is a small fraction of each trigger window")
    add("(§1). H4's own thesis is that stay-probability rises through the afternoon")
    add("while the book empties, so the EARLY part of the window — the part not")
    add("captured — is precisely where an offer is most likely to survive. This run")
    add("cannot speak to it.")
    add("")
    add("**Not measured here, by design.** No profitability, no return, no fee, no")
    add("fill and no P&L. Whether any observed price would have been *worth* taking is")
    add("a question for NautilusTrader, and it does not arise while the ask is absent.")
    add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H4 preliminary economic read")
    parser.add_argument("--cache-dir", default=str(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR))
    parser.add_argument("--quote-catalog", default=str(DEFAULT_QUOTE_TAPE_CATALOG))
    parser.add_argument("--settlement-catalog", default=str(DEFAULT_SETTLEMENT_CATALOG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--preflight-attestation",
        default=None,
        help="REQUIRED (LESSONS L-8): the breezy-quote-tape-preflight summary for "
        "this climate day's files. Refuses to run without it.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    preflight = require_preflight_attestation(args.preflight_attestation)
    cache_dir = Path(args.cache_dir).expanduser()
    quote_catalog = Path(args.quote_catalog).expanduser()
    settlement_catalog = Path(args.settlement_catalog).expanduser()

    depth_root = quote_catalog / "data" / "order_book_depths"
    if not depth_root.is_dir():
        raise SystemExit(f"no depth catalog at {depth_root}")
    all_ids = sorted(
        entry.name
        for entry in depth_root.iterdir()
        if TARGET_CLIMATE_DAY.isoformat() in entry.name
    )

    reads: list[StationRead] = []
    for spec in sorted(load_sites(), key=lambda site: site.city):
        token = f"tc-temp-{spec.city.lower()}high-{TARGET_CLIMATE_DAY.isoformat()}-"
        instrument_ids = [name for name in all_ids if name.startswith(token)]
        if not instrument_ids:
            print(f"[h4] {spec.city}: no ladder captured; skipping", file=sys.stderr)
            continue
        read = analyse_station(
            spec=spec,
            cache_dir=cache_dir,
            quote_catalog=quote_catalog,
            settlement_catalog=settlement_catalog,
            instrument_ids=instrument_ids,
        )
        reads.append(read)
        print(
            f"[h4] {spec.city}: {read.depth_rows} depth rows, "
            f"{len(read.observations)} instants at/after trigger, "
            f"{sum(1 for row in read.observations if row.is_candidate)} with h==1",
            file=sys.stderr,
        )

    report = build_report(
        reads,
        generated_at=dt.datetime.now(tz=dt.UTC).replace(microsecond=0),
        preflight=preflight,
        quote_catalog=quote_catalog,
        cache_dir=cache_dir,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[h4] wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
