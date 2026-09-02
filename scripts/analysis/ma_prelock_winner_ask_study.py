"""M_A -- the single first read-only measurement before strategy spend stops.

Grok's design memo (``docs/evidence/grok_no_edge_verdict_2026-09-02.md``
SS2/SS3, verbatim and binding for this module's shape) asks one question: per
DENSE station-day, at every captured Depth10 snapshot in local-standard
12:00-17:00, is the WINNER rung's ask ever inside ``(0.05, 0.95)`` while the
true intraday running maximum ``R(t)`` already sits inside the winner rung?

WHAT THIS IS
------------
A descriptive join over three read-only sources -- the venue quote tape
(``OrderBookDepth10``), a fresh IEM ASOS fetch (``R(t)``), and Breezy's own
CLI settlement archive (the winner) -- exactly as SS2 specifies. It constructs
no order, no fill, no position, no fee and no P&L. NautilusTrader remains the
exclusive owner of backtesting and execution; this is a price/size statistic
over a captured book, nothing more.

KILL SENTENCE (SS2, K-A in SS3)
--------------------------------
Dead if >= 15 afternoon-covered dense station-days (>= 30 min of Depth10 in
the 12:00-17:00 LST window) contain ZERO winner asks in (0.05, 0.95) while
R(t) is in-rung. Below 15, the measurement is UNDERPOWERED, not dead. A
surviving cell still needs K-depth: level-0 size < 1.0 contract at the
recorded ask is unexecutable (BL-25 / ``insufficient_depth``).

NULL HYPOTHESIS, checked before this module was written
---------------------------------------------------------
Every piece of I/O and basis arithmetic this measurement needs already exists
and is reused verbatim via import:

* ``Rung`` / ``parse_rung`` / ``parse_ladder`` / ``rung_containing`` /
  ``running_max_series`` / ``running_max_at`` / ``load_depth`` /
  ``DepthObservation`` -- ``h4_preliminary_economic_read.py``. The minute-
  resolution ``R(t)`` fold there is the SAME single-forward-pass,
  ``rounded_f``-basis accumulator ``pmr_climatology_study.build_running_max_days``
  uses, but resolved to an arbitrary INSTANT rather than an hour boundary --
  exactly what joining against Depth10 timestamps (which do not land on hour
  boundaries) needs. Reused as the finer-grained sibling of the same fold,
  not a rewrite of it (see the module-level note in ``main`` for the one place
  this was NOT a drop-in reuse).
* ``SiteSpec`` / ``load_sites`` / ``asos_url`` / ``cache_path_for_url`` /
  ``parse_asos_rows`` / ``MetarTemperature`` / ``metar_temperatures`` --
  ``settlement_alignment_study.py``. NATIVE-EXISTS-AND-REUSED.
* ``DENSE_STATIONS`` (the registry minus the contaminated station(s), L-13) --
  ``cli_basis_setup_win_rate_study.py``. Reused verbatim rather than
  re-deriving "the four non-NYC stations" a second time.
* ``standard_time_zone`` -- ``breezy.normalize.climate_day``. Never
  ``zoneinfo.ZoneInfo``, which would follow DST.
* ``list_instance_ids`` / ``scan_instance`` -- ``breezy.persistence.
  feather_preflight`` (LESSON L-8): the same truncation-detection this
  module's own attestation string is built from.

GENUINE GAPS, built here
--------------------------
``h4_preliminary_economic_read.load_settled_tmax`` and ``load_asos_series``
are hard-coded to ONE module-global ``TARGET_CLIMATE_DAY``; M_A needs the same
two reads across MANY station-days. ``load_settled_tmax_for_day`` and
``load_asos_series_for_day`` below are that constant parameterised into an
argument -- same catalog calls, same filtering, same disagreement guard,
nothing reinterpreted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_setup_win_rate_study import DENSE_STATIONS
from h4_preliminary_economic_read import (
    DepthObservation,
    Rung,
    RunningMaxSeries,
    load_depth,
    parse_ladder,
    require_preflight_attestation,
    rung_containing,
    running_max_at,
    running_max_series,
)
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    MetarTemperature,
    SiteSpec,
    asos_url,
    cache_path_for_url,
    load_sites,
    metar_temperatures,
    parse_asos_rows,
)

from breezy.normalize.climate_day import standard_time_zone
from breezy.persistence.catalog import read_climate_days, station_catalog_path
from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    PreflightError,
    list_instance_ids,
    scan_instance,
)

__all__ = [
    "AFTERNOON_WINDOW_END",
    "AFTERNOON_WINDOW_START",
    "ASK_HIGH_THRESHOLD",
    "ASK_QUALIFYING_HIGH",
    "ASK_QUALIFYING_LOW",
    "ASOS_FETCH_END",
    "ASOS_FETCH_START",
    "DENSE_STATIONS",
    "MIN_AFTERNOON_COVERAGE_MINUTES",
    "MIN_AFTERNOON_STATION_DAYS",
    "MIN_EXECUTABLE_SIZE",
    "AfternoonSnapshot",
    "DepthObservation",
    "KAVerdict",
    "Rung",
    "StationDaySummary",
    "afternoon_coverage_minutes",
    "build_afternoon_snapshots",
    "build_report",
    "build_station_day_summary",
    "collect_preflight_summary",
    "collect_window_instants",
    "default_asos_fetch_end",
    "discover_station_days",
    "evaluate_family_a",
    "first_ask_at_or_above",
    "first_ask_vanish",
    "in_afternoon_window",
    "instrument_ids_for",
    "load_asos_series_for_day",
    "load_settled_tmax_for_day",
    "main",
    "parse_ladder",
    "qualifying_cells",
    "rung_containing",
]

# -- SS2/SS3 pre-registered parameters, copied from the memo, never re-derived --

#: Local-standard afternoon window, half-open: ``[12:00, 17:00)``.
AFTERNOON_WINDOW_START: Final[dt.time] = dt.time(12, 0)
AFTERNOON_WINDOW_END: Final[dt.time] = dt.time(17, 0)

#: SS2 quantity (i): winner ask strictly inside this open interval.
ASK_QUALIFYING_LOW: Final[float] = 0.05
ASK_QUALIFYING_HIGH: Final[float] = 0.95

#: SS2 quantity (iii): first time the ask reaches this level.
ASK_HIGH_THRESHOLD: Final[float] = 0.99

#: SS2 sample: >= 30 min of Depth10 captured inside the afternoon window.
MIN_AFTERNOON_COVERAGE_MINUTES: Final[float] = 30.0

#: SS2/SS3 K-A: >= 15 afternoon-covered dense station-days to discriminate.
MIN_AFTERNOON_STATION_DAYS: Final[int] = 15

#: K-depth (SS3): level-0 size below one contract is unexecutable.
MIN_EXECUTABLE_SIZE: Final[float] = 1.0

def default_asos_fetch_end(*, today: dt.date | None = None) -> dt.date:
    """"2026-08-30 -> through today" -- a daily unattended run (deploy/systemd/
    breezy-mb-daily.timer) must advance this window itself; a hard-coded date
    here is exactly the hand-maintained value that timer replaces. Through
    TODAY, not yesterday: a station-day whose CLI final has not posted yet is
    already scored PENDING, never a false zero-qualifying result (see
    `load_settled_tmax_for_day` / the PENDING-vs-SCORED tests), so including
    today's still-open climate day is safe, and it is what lets
    `asos_recent_refresh.py --since` (the matching absolute-anchor fetch)
    land on the exact same URL this module's cache-only read requires.
    """
    return today if today is not None else dt.date.today()


#: "2026-08-30 -> last complete climate day." Fixed anchor; the end advances
#: daily via `default_asos_fetch_end` rather than being hand-edited.
ASOS_FETCH_START: Final[dt.date] = dt.date(2026, 8, 30)
ASOS_FETCH_END: Final[dt.date] = default_asos_fetch_end()

DEFAULT_QUOTE_TAPE_CATALOG: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_SETTLEMENT_CATALOG: Final[Path] = Path.home() / ".local/share/breezy/catalog"
DEFAULT_OUTPUT: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/ma_prelock_winner_ask_2026-09-02.md"
)


# ---------------------------------------------------------------------------
# Afternoon window membership and the per-snapshot record
# ---------------------------------------------------------------------------


def in_afternoon_window(ts_lst: dt.datetime, *, climate_day: dt.date) -> bool:
    """True for an instant inside ``[climate_day 12:00, climate_day 17:00)`` LST."""
    return ts_lst.date() == climate_day and AFTERNOON_WINDOW_START <= ts_lst.time() < (
        AFTERNOON_WINDOW_END
    )


@dataclass(frozen=True, slots=True)
class AfternoonSnapshot:
    """One captured Depth10 snapshot on the WINNER rung, inside the window."""

    ts_event: dt.datetime
    ts_lst: dt.datetime
    hour_lst: int
    ask_px: float | None
    ask_sz: float | None
    running_f: int | None
    #: `R(t) - winner_floor`. `None` on an open-lower-tail winner (no floor).
    m: int | None
    #: `winner_rung.contains(R(t))` -- well-defined on every tail shape.
    in_rung: bool


def _ask_size_at_best(row: DepthObservation) -> float | None:
    if row.ask_ladder:
        return row.ask_ladder[0][1]
    return None


def build_afternoon_snapshots(
    *,
    winner_rung: Rung,
    winner_depth: Sequence[DepthObservation],
    series: RunningMaxSeries,
    climate_day: dt.date,
    std_utc_offset_hours: float,
) -> tuple[AfternoonSnapshot, ...]:
    """Reduce the winner instrument's own captured rows to the SS2 quantity.

    One entry per captured Depth10 snapshot on the winner rung that falls
    inside the afternoon window -- never synthesised, never resampled.
    """
    tz = standard_time_zone(std_utc_offset_hours)
    snapshots: list[AfternoonSnapshot] = []
    for row in sorted(winner_depth, key=lambda item: item.ts_event):
        ts_lst = row.ts_event.astimezone(tz)
        if not in_afternoon_window(ts_lst, climate_day=climate_day):
            continue
        running = running_max_at(series, row.ts_event)
        m = (
            None
            if running is None or winner_rung.lower_f is None
            else running - winner_rung.lower_f
        )
        in_rung = running is not None and winner_rung.contains(running)
        snapshots.append(
            AfternoonSnapshot(
                ts_event=row.ts_event,
                ts_lst=ts_lst,
                hour_lst=ts_lst.hour,
                ask_px=row.best_ask,
                ask_sz=_ask_size_at_best(row),
                running_f=running,
                m=m,
                in_rung=in_rung,
            )
        )
    return tuple(snapshots)


def qualifying_cells(snapshots: Sequence[AfternoonSnapshot]) -> tuple[AfternoonSnapshot, ...]:
    """SS2 quantity (i): winner ask in (0.05, 0.95) while R(t) is in-rung."""
    return tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.ask_px is not None
        and ASK_QUALIFYING_LOW < snapshot.ask_px < ASK_QUALIFYING_HIGH
        and snapshot.in_rung
    )


def first_ask_vanish(snapshots: Sequence[AfternoonSnapshot]) -> dt.datetime | None:
    """SS2 quantity (ii): LST of the first snapshot with no winner ask at all."""
    for snapshot in snapshots:
        if snapshot.ask_px is None:
            return snapshot.ts_lst
    return None


def first_ask_at_or_above(
    snapshots: Sequence[AfternoonSnapshot], *, threshold: float = ASK_HIGH_THRESHOLD
) -> dt.datetime | None:
    """SS2 quantity (iii): LST of the first snapshot with ask >= `threshold`."""
    for snapshot in snapshots:
        if snapshot.ask_px is not None and snapshot.ask_px >= threshold:
            return snapshot.ts_lst
    return None


def collect_window_instants(
    depth: Mapping[str, Sequence[DepthObservation]],
    *,
    climate_day: dt.date,
    std_utc_offset_hours: float,
) -> tuple[dt.datetime, ...]:
    """Every distinct captured instant, ACROSS ALL RUNGS, inside the window.

    Tape coverage is a property of the CAPTURE, not of one instrument -- the
    same reasoning `h4_preliminary_economic_read._evaluate` uses for its
    "distinct captured instant" set, applied here to a fixed time window
    instead of a trigger hour.
    """
    tz = standard_time_zone(std_utc_offset_hours)
    instants: set[dt.datetime] = set()
    for rows in depth.values():
        for row in rows:
            ts_lst = row.ts_event.astimezone(tz)
            if in_afternoon_window(ts_lst, climate_day=climate_day):
                instants.add(row.ts_event)
    return tuple(sorted(instants))


def afternoon_coverage_minutes(instants: Sequence[dt.datetime]) -> float:
    """Span between the first and last captured instant in the window.

    Zero for 0 or 1 instants: a single snapshot covers no SPAN, even though it
    is one real observation -- consistent with the >= 30 min sample gate,
    which asks about duration of capture, not snapshot count.
    """
    if len(instants) < 2:
        return 0.0
    return (max(instants) - min(instants)).total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Per-station-day summary and the K-A verdict
# ---------------------------------------------------------------------------

StationDayStatus = Literal["SCORED", "PENDING"]


@dataclass(frozen=True, slots=True)
class StationDaySummary:
    """One row of the SS2 output table."""

    city: str
    climate_day: dt.date
    status: StationDayStatus
    winner_instrument_id: str | None
    settled_tmax_f: int | None
    afternoon_coverage_minutes: float
    afternoon_snapshot_count: int
    qualifying: tuple[AfternoonSnapshot, ...]
    min_ask: float | None
    size_at_min_ask: float | None
    first_ask_vanish_lst: dt.datetime | None
    first_ask_ge_099_lst: dt.datetime | None

    @property
    def afternoon_covered(self) -> bool:
        return self.afternoon_coverage_minutes >= MIN_AFTERNOON_COVERAGE_MINUTES

    @property
    def unexecutable(self) -> tuple[AfternoonSnapshot, ...]:
        """K-depth: a qualifying cell whose level-0 size is below one contract."""
        return tuple(
            cell
            for cell in self.qualifying
            if cell.ask_sz is None or cell.ask_sz < MIN_EXECUTABLE_SIZE
        )


def build_station_day_summary(
    *,
    city: str,
    climate_day: dt.date,
    ladder: Sequence[Rung],
    depth: Mapping[str, Sequence[DepthObservation]],
    series: RunningMaxSeries,
    settled_tmax_f: int | None,
    std_utc_offset_hours: float,
) -> StationDaySummary:
    """One (station, climate-day) row -- PENDING if there is no final CLI yet."""
    window_instants = collect_window_instants(
        depth, climate_day=climate_day, std_utc_offset_hours=std_utc_offset_hours
    )
    coverage = afternoon_coverage_minutes(window_instants)

    if settled_tmax_f is None:
        return StationDaySummary(
            city=city,
            climate_day=climate_day,
            status="PENDING",
            winner_instrument_id=None,
            settled_tmax_f=None,
            afternoon_coverage_minutes=coverage,
            afternoon_snapshot_count=0,
            qualifying=(),
            min_ask=None,
            size_at_min_ask=None,
            first_ask_vanish_lst=None,
            first_ask_ge_099_lst=None,
        )

    winner = rung_containing(ladder, settled_tmax_f)
    if winner is None:
        raise ValueError(
            f"{city} {climate_day}: settled tmax_f={settled_tmax_f} matches no rung in "
            f"the captured ladder ({[rung.instrument_id for rung in ladder]}); refusing "
            f"to guess a winner"
        )

    winner_depth = depth.get(winner.instrument_id, ())
    snapshots = build_afternoon_snapshots(
        winner_rung=winner,
        winner_depth=winner_depth,
        series=series,
        climate_day=climate_day,
        std_utc_offset_hours=std_utc_offset_hours,
    )
    priced = [snapshot for snapshot in snapshots if snapshot.ask_px is not None]
    ask_prices: list[float] = [
        snapshot.ask_px for snapshot in priced if snapshot.ask_px is not None
    ]
    min_ask = min(ask_prices, default=None)
    size_at_min_ask = None
    if min_ask is not None:
        for snapshot in priced:
            if snapshot.ask_px == min_ask:
                size_at_min_ask = snapshot.ask_sz
                break

    return StationDaySummary(
        city=city,
        climate_day=climate_day,
        status="SCORED",
        winner_instrument_id=winner.instrument_id,
        settled_tmax_f=settled_tmax_f,
        afternoon_coverage_minutes=coverage,
        afternoon_snapshot_count=len(snapshots),
        qualifying=qualifying_cells(snapshots),
        min_ask=min_ask,
        size_at_min_ask=size_at_min_ask,
        first_ask_vanish_lst=first_ask_vanish(snapshots),
        first_ask_ge_099_lst=first_ask_at_or_above(snapshots),
    )


@dataclass(frozen=True, slots=True)
class KAVerdict:
    """SS3 K-A, reduced from a list of per-station-day summaries."""

    outcome: Literal["FAMILY_A_DEAD", "UNDERPOWERED", "ALIVE"]
    n_afternoon: int
    qualifying_count: int
    afternoon_covered: tuple[StationDaySummary, ...]
    detail: str


def evaluate_family_a(summaries: Sequence[StationDaySummary]) -> KAVerdict:
    """K-A: `n_afternoon >= 15 AND count(qualifying) == 0` -> family A dead."""
    scored = [summary for summary in summaries if summary.status == "SCORED"]
    covered = tuple(summary for summary in scored if summary.afternoon_covered)
    n_afternoon = len(covered)
    qualifying_count = sum(len(summary.qualifying) for summary in covered)

    if n_afternoon < MIN_AFTERNOON_STATION_DAYS:
        outcome: Literal["FAMILY_A_DEAD", "UNDERPOWERED", "ALIVE"] = "UNDERPOWERED"
        detail = (
            f"n_afternoon={n_afternoon} < {MIN_AFTERNOON_STATION_DAYS}; the sample "
            f"cannot discriminate yet -- not a verdict in either direction"
        )
    elif qualifying_count == 0:
        outcome = "FAMILY_A_DEAD"
        detail = (
            f"n_afternoon={n_afternoon} >= {MIN_AFTERNOON_STATION_DAYS} and zero winner "
            f"asks in (0.05, 0.95) while R(t) was in-rung across all of them"
        )
    else:
        outcome = "ALIVE"
        detail = (
            f"n_afternoon={n_afternoon}, {qualifying_count} qualifying cell(s) found; "
            f"apply K-depth to each before treating any as a live cell"
        )
    return KAVerdict(
        outcome=outcome,
        n_afternoon=n_afternoon,
        qualifying_count=qualifying_count,
        afternoon_covered=covered,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# I/O: settlement, ASOS, catalog discovery, preflight (genuine parameterised
# gaps over h4_preliminary_economic_read -- see the module docstring)
# ---------------------------------------------------------------------------


def load_settled_tmax_for_day(
    *, catalog_base: Path, city: str, climate_day: dt.date
) -> tuple[int | None, int, str]:
    """`h4_preliminary_economic_read.load_settled_tmax`, parameterised by day."""
    path = station_catalog_path(catalog_base, "polymarket_us", city)
    records = read_climate_days(ParquetDataCatalog(str(path)))
    finals = [
        record
        for record in records
        if record.climate_day == climate_day and record.is_final and not record.is_superseded
    ]
    if not finals:
        return None, 0, str(path)
    values = {record.tmax_f for record in finals}
    if len(values) > 1:
        rendered = sorted(str(value) for value in values)
        raise SystemExit(
            f"{city} {climate_day}: non-superseded finals disagree on tmax_f "
            f"({rendered}); refusing to pick one silently"
        )
    return finals[0].tmax_f, len(finals), str(path)


def load_asos_series_for_day(
    *,
    cache_dir: Path,
    spec: SiteSpec,
    fetch_start: dt.date,
    fetch_end: dt.date,
    climate_day: dt.date,
) -> tuple[RunningMaxSeries, tuple[MetarTemperature, ...], object]:
    """`h4_preliminary_economic_read.load_asos_series`, parameterised by day."""
    url = asos_url(spec.iem_asos_id, fetch_start, fetch_end)
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
    on_day = tuple(row for row in temperatures if row.climate_day == climate_day)
    return running_max_series(on_day), on_day, drops


def discover_station_days(
    *, depth_root: Path, cities: Sequence[str], fetch_start: dt.date, fetch_end: dt.date
) -> tuple[tuple[str, dt.date], ...]:
    """Every (city, climate_day) with at least one captured rung in `depth_root`."""
    names = tuple(sorted(entry.name for entry in depth_root.iterdir() if entry.is_dir()))
    found: list[tuple[str, dt.date]] = []
    day = fetch_start
    while day <= fetch_end:
        for city in cities:
            token = f"tc-temp-{city.lower()}high-{day.isoformat()}-"
            if any(name.startswith(token) for name in names):
                found.append((city, day))
        day += dt.timedelta(days=1)
    return tuple(found)


def instrument_ids_for(*, depth_root: Path, city: str, climate_day: dt.date) -> tuple[str, ...]:
    token = f"tc-temp-{city.lower()}high-{climate_day.isoformat()}-"
    return tuple(
        sorted(entry.name for entry in depth_root.iterdir() if entry.name.startswith(token))
    )


def collect_preflight_summary(
    *,
    catalog_root: Path,
    station_days: Sequence[tuple[str, dt.date]],
    subdirectory: str = DEFAULT_SUBDIRECTORY,
) -> str:
    """LESSON L-8: an attestation sentence scoped to M_A's own target files."""
    tokens = tuple(
        f"tc-temp-{city.lower()}high-{day.isoformat()}-" for city, day in station_days
    )
    total_files = 0
    total_rows = 0
    empty = 0
    truncated: list[str] = []
    unreadable: list[str] = []
    for instance_id in list_instance_ids(catalog_root, subdirectory):
        try:
            report = scan_instance(catalog_root, instance_id, subdirectory)
        except PreflightError:
            continue
        for file in report.files:
            if not any(token in file.path.name for token in tokens):
                continue
            total_files += 1
            total_rows += file.rows
            if file.is_truncated:
                truncated.append(file.path.name)
            elif file.status.name == "UNREADABLE":
                unreadable.append(file.path.name)
            elif file.is_empty:
                empty += 1
    if truncated or unreadable:
        bad = ", ".join(sorted(set(truncated) | set(unreadable)))
        return (
            f"breezy-quote-tape-preflight over {catalog_root}: of {total_files} staged "
            f"files carrying M_A's target station-day instruments, "
            f"{len(truncated)} TRUNCATED and {len(unreadable)} UNREADABLE "
            f"({total_rows} rows recovered from the rest). Do NOT read the affected "
            f"station-days as quiet markets: {bad or 'see above'}."
        )
    return (
        f"breezy-quote-tape-preflight over {catalog_root}: all {total_files} staged "
        f"files carrying M_A's target station-day instruments are INTACT -- "
        f"{total_rows} rows, 0 truncated, 0 unreadable, {empty} empty."
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _fmt_lst(value: dt.datetime | None) -> str:
    return "-" if value is None else value.strftime("%m-%d %H:%M")


def _fmt_price(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def _fmt_size(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def build_report(
    summaries: Sequence[StationDaySummary],
    verdict: KAVerdict,
    *,
    generated_at: dt.datetime,
    preflight: str,
    quote_catalog: Path,
    cache_dir: Path,
    asos_fetch_report: str,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# M_A -- pre-lock winner-ask afternoon measurement")
    add("")
    add(f"Generated {generated_at.isoformat()} from")
    add("`scripts/analysis/ma_prelock_winner_ask_study.py`. Spec: ")
    add("`docs/evidence/grok_no_edge_verdict_2026-09-02.md` SS2 / SS3 K-A, K-depth.")
    add("")
    add(
        "A descriptive join, not a backtest: no order, fill, position, fee or P&L "
        "appears anywhere in this pipeline. NautilusTrader is the exclusive owner of "
        "backtesting and execution."
    )
    add("")
    add("## Tape integrity (LESSONS L-8) -- verified before interpretation")
    add("")
    add(f"> {preflight}")
    add("")
    add(f"Depth catalog: `{quote_catalog}`")
    add(f"ASOS archive cache: `{cache_dir}`")
    add("")
    add("## IEM ASOS fetch")
    add("")
    add(asos_fetch_report)
    add("")
    add("## Per-station-day summary")
    add("")
    add(
        "| station | day | status | winner | coverage (min) | afternoon snapshots | "
        "qualifying cells | min ask | size@min | first vanish (LST) | first >=0.99 (LST) |"
    )
    add("|---|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for summary in sorted(summaries, key=lambda item: (item.city, item.climate_day)):
        add(
            f"| {summary.city} | {summary.climate_day.isoformat()} | {summary.status} | "
            f"{summary.winner_instrument_id or '-'} | "
            f"{summary.afternoon_coverage_minutes:.1f} | "
            f"{summary.afternoon_snapshot_count} | {len(summary.qualifying)} | "
            f"{_fmt_price(summary.min_ask)} | {_fmt_size(summary.size_at_min_ask)} | "
            f"{_fmt_lst(summary.first_ask_vanish_lst)} | "
            f"{_fmt_lst(summary.first_ask_ge_099_lst)} |"
        )
    add("")
    pending = [summary for summary in summaries if summary.status == "PENDING"]
    if pending:
        add(
            f"PENDING (no final, non-superseded CLI yet; never scored): "
            f"{', '.join(f'{s.city} {s.climate_day.isoformat()}' for s in pending)}"
        )
        add("")
    add("## K-A verdict")
    add("")
    add(f"**{verdict.outcome}** -- {verdict.detail}")
    add("")
    if verdict.outcome == "ALIVE":
        add("### Surviving cells (K-depth applied)")
        add("")
        for summary in verdict.afternoon_covered:
            for cell in summary.qualifying:
                depth_verdict = (
                    "UNEXECUTABLE (size < 1.0 contract)"
                    if cell in summary.unexecutable
                    else "size >= 1.0 contract"
                )
                add(
                    f"- {summary.city} {summary.climate_day.isoformat()} "
                    f"{cell.ts_lst.strftime('%H:%M')} LST: ask={cell.ask_px:.4f} "
                    f"size={_fmt_size(cell.ask_sz)} m={cell.m} -- {depth_verdict}"
                )
        add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR)
    )
    parser.add_argument("--quote-catalog", default=str(DEFAULT_QUOTE_TAPE_CATALOG))
    parser.add_argument("--settlement-catalog", default=str(DEFAULT_SETTLEMENT_CATALOG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--preflight-attestation",
        default=None,
        help="Precomputed attestation string. If omitted, computed in-process from "
        "the feather staging directories (LESSONS L-8).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    cache_dir = Path(args.cache_dir).expanduser()
    quote_catalog = Path(args.quote_catalog).expanduser()
    settlement_catalog = Path(args.settlement_catalog).expanduser()

    depth_root = quote_catalog / "data" / "order_book_depths"
    if not depth_root.is_dir():
        raise SystemExit(f"no depth catalog at {depth_root}")

    station_days = discover_station_days(
        depth_root=depth_root,
        cities=DENSE_STATIONS,
        fetch_start=ASOS_FETCH_START,
        fetch_end=ASOS_FETCH_END,
    )
    if not station_days:
        raise SystemExit(
            f"no dense-station instruments captured for "
            f"{ASOS_FETCH_START}..{ASOS_FETCH_END} under {depth_root}"
        )

    if args.preflight_attestation:
        preflight = require_preflight_attestation(args.preflight_attestation)
    else:
        preflight = collect_preflight_summary(
            catalog_root=quote_catalog, station_days=station_days
        )

    specs_by_city = {spec.city: spec for spec in load_sites()}
    summaries: list[StationDaySummary] = []
    for city, climate_day in station_days:
        spec = specs_by_city[city]
        instrument_ids = instrument_ids_for(
            depth_root=depth_root, city=city, climate_day=climate_day
        )
        ladder = parse_ladder(instrument_ids)
        depth = load_depth(catalog_root=quote_catalog, instrument_ids=instrument_ids)
        series, _on_day, _drops = load_asos_series_for_day(
            cache_dir=cache_dir,
            spec=spec,
            fetch_start=ASOS_FETCH_START,
            fetch_end=ASOS_FETCH_END,
            climate_day=climate_day,
        )
        settled_tmax_f, _final_count, _provenance = load_settled_tmax_for_day(
            catalog_base=settlement_catalog, city=city, climate_day=climate_day
        )
        summaries.append(
            build_station_day_summary(
                city=city,
                climate_day=climate_day,
                ladder=ladder,
                depth=depth,
                series=series,
                settled_tmax_f=settled_tmax_f,
                std_utc_offset_hours=spec.std_utc_offset_hours,
            )
        )

    verdict = evaluate_family_a(summaries)
    report = build_report(
        summaries,
        verdict,
        generated_at=dt.datetime.now(tz=dt.UTC).replace(microsecond=0),
        preflight=preflight,
        quote_catalog=quote_catalog,
        cache_dir=cache_dir,
        asos_fetch_report=(
            f"fetched {ASOS_FETCH_START.isoformat()}..{ASOS_FETCH_END.isoformat()} "
            f"for {', '.join(DENSE_STATIONS)}; see the run log for per-site outcomes."
        ),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[ma] wrote {output}", file=sys.stderr)
    print(
        f"[ma] verdict={verdict.outcome} n_afternoon={verdict.n_afternoon} "
        f"qualifying={verdict.qualifying_count}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
