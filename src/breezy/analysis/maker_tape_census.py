"""MAKER S1 WP1 -- the pure core of the maker-window print census.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md`` WP1.
Spec: ``docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md`` section 3, 6.0, 6.1.

Question asked of the tape: for each (station, climate day), was the recorder
alive for the maker window, and did any print happen that could have filled a
resting NO bid? Nothing here reads a book. A quiet overnight book is a covered
day, not an outage: liveness is the recorder's alive span minus its recorded
gaps.

Pure by construction: plain ints, strings, ``Decimal`` and ``date`` only. No
Nautilus, no pyarrow (import-linter contract "The offline analysis layer never
DIRECTLY imports Nautilus"). The sidecar script owns every read.

Constants are fixed before any run; changing one needs a plan revision.

**ASSUMPTION, not a measurement:** ``RHO_ASSUMED = 0.5``, the within-date
correlation of the four stations' fill outcomes used by ``n_eff_ub``. It has not
been estimated from data. The bound is a necessary-only, crude floor
(plan section 2.1) and every report must label rho as assumed.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, NamedTuple

__all__ = [
    "AliveSpan",
    "CensusSummary",
    "CensusedDay",
    "FirewallRefused",
    "GapInterval",
    "MakerWindow",
    "PrintRecord",
    "PrintTally",
    "admit_print",
    "bidlive_window_ns",
    "classify",
    "covered_intervals",
    "maker_window_ns",
    "read_censused_days",
    "require_firewall_clearance",
    "summarise",
    "tally_prints",
    "write_censused_days",
]

_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3_600 * _NS
_MINUTE_NS: Final[int] = 60 * _NS

# --- Firewall (RA-13 B-3) -------------------------------------------------------------
PRE_FREEZE_END: Final[dt.date] = dt.date(2026, 9, 25)  # same value as nbp_market_comparison.py
MAKER_STATIONS: Final[frozenset[str]] = frozenset({"LAX", "MDW", "MIA", "SFO"})


class SearchDeclared(NamedTuple):
    stations: frozenset[str]
    first_day: dt.date
    last_day: dt.date


SEARCH_DECLARED: Final[SearchDeclared] = SearchDeclared(
    MAKER_STATIONS, dt.date(2026, 9, 26), dt.date(2026, 10, 13)
)
#: sha256 over the committed bytes of
#: ``docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md`` (6068a00e).
SEARCH_DECLARATION_SHA256: Final[str] = (
    "38663caad38e455ab1512ca91a049f97d31c2dcfb1477c42db02ceca407abbc6"
)

# --- Maker window (spec section 3) ----------------------------------------------------
#: Trade capture starts 2026-09-17T09:00Z (journal evidence, plan section 7).
TRADE_CAPTURE_START_NS: Final[int] = (
    int(dt.datetime(2026, 9, 17, 9, 0, tzinfo=dt.UTC).timestamp()) * _NS
)
STALE_H: Final[int] = 8
LAST_CYCLE_UTC_HOUR: Final[int] = 1
NBP_LAG_UB_H: Final[int] = 2
CANCEL_LST_HOUR: Final[int] = 9
_WINDOW_START_UTC_HOUR: Final[int] = 12  # D-1 12:00Z, the listing line

# --- Coverage gates -------------------------------------------------------------------
COVERAGE_MIN: Final[float] = 0.90
LONGEST_HOLE_MAX_MIN: Final[int] = 60

# --- Power and fillability (plan section 2) -------------------------------------------
RHO_ASSUMED: Final[float] = 0.5
N_EFF_FLOOR: Final[int] = 30
C_STOP: Final[float] = 0.05
C_FLAG: Final[float] = 0.10
#: Lower bound of YES price at which a BUYER print can fill a resting NO bid:
#: 1 - B_CAP with B_CAP 0.80 (plan section 5.2).
QUALIFY_MIN_PRICE: Final[Decimal] = Decimal("0.20")
#: YES-price buckets, lower bound inclusive, upper exclusive.
PRICE_BUCKETS: Final[tuple[tuple[Decimal, Decimal], ...]] = (
    (Decimal(0), Decimal("0.10")),
    (Decimal("0.10"), Decimal("0.20")),
    (Decimal("0.20"), Decimal("0.30")),
    (Decimal("0.30"), Decimal("1.01")),
)

BUYER: Final[str] = "BUYER"
SELLER: Final[str] = "SELLER"
NO_AGGRESSOR: Final[str] = "NO_AGGRESSOR"

#: S-5 is a NO-GO pre-screen on a point estimate; below this many covered
#: bid-bearing station-days it is reported UNSCREENED, never NO-GO/KILL-LIKELY.
S5_MIN_COVERED: Final[int] = 10

#: Bid-live sub-window (spec section 3: the permit binds first; 16:50Z launch +
#: 10 h). A resting bid for climate day D can only exist from D-1 16:50Z to
#: D 02:50Z. The plan window (23 h) stays the pre-registered STOP basis; the
#: bid-live columns are a parallel report, intersected with it.
BIDLIVE_START_HHMM_UTC: Final[tuple[int, int]] = (16, 50)  # on D-1
BIDLIVE_END_HHMM_UTC: Final[tuple[int, int]] = (2, 50)  # on D

REASONS: Final[tuple[str, ...]] = (
    "PRE_TRADE_CAPTURE",
    "NEVER_LISTED",
    "AMBIGUOUS_NO_CLEAN_INSTANCE",
    "TRADE_PARSE_FAILURE",
    "LOW_COVERAGE",
    "LONG_HOLE",
    "COVERED",
)
FirewallClass = Literal["PRE_FREEZE", "SEARCH_DECLARED"]
_FIREWALL_CLASSES: Final[frozenset[str]] = frozenset({"PRE_FREEZE", "SEARCH_DECLARED"})


class FirewallRefused(Exception):
    """A station-day may not be read (NYC, or post-freeze without a matching declaration)."""


class MakerWindow(NamedTuple):
    start_ns: int
    end_ns: int
    binding: Literal["STALE_DERIVED", "CANCEL_LST"]


def _utc_ns(day: dt.date, hour: int) -> int:
    moment = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
    return int(moment.timestamp()) * _NS


def maker_window_ns(*, climate_day: dt.date, std_utc_offset_hours: float) -> MakerWindow:
    """``[D-1 12:00Z, min(D 01:00Z + STALE_H + NBP_LAG_UB_H, D 09:00 LST))`` in integer ns.

    The D 01Z vector is the last for D; its bids stop ``STALE_H`` after it is
    available, allowing ``NBP_LAG_UB_H`` of publication lag. 09:00 LST is the
    backstop (``std_utc_offset_hours`` is the fixed standard-time offset, never
    DST-aware) and never binds at this lag for any registered station.
    """
    start = _utc_ns(climate_day - dt.timedelta(days=1), _WINDOW_START_UTC_HOUR)
    stale_end = _utc_ns(climate_day, LAST_CYCLE_UTC_HOUR + STALE_H + NBP_LAG_UB_H)
    lst_end = _utc_ns(climate_day, CANCEL_LST_HOUR) - int(std_utc_offset_hours * _HOUR_NS)
    if lst_end < stale_end:
        return MakerWindow(start, lst_end, "CANCEL_LST")
    return MakerWindow(start, stale_end, "STALE_DERIVED")


def bidlive_window_ns(*, climate_day: dt.date, window: MakerWindow) -> tuple[int, int]:
    """``[D-1 16:50Z, D 02:50Z)`` intersected with the plan window (spec section 3)."""
    prior = climate_day - dt.timedelta(days=1)
    start = _utc_ns(prior, BIDLIVE_START_HHMM_UTC[0]) + BIDLIVE_START_HHMM_UTC[1] * _MINUTE_NS
    end = _utc_ns(climate_day, BIDLIVE_END_HHMM_UTC[0]) + BIDLIVE_END_HHMM_UTC[1] * _MINUTE_NS
    return max(start, window.start_ns), min(end, window.end_ns)


def require_firewall_clearance(
    station: str, day: dt.date, declaration_sha256: str | None
) -> FirewallClass:
    """Clear a station-day for reading or raise :class:`FirewallRefused`.

    Pre-freeze days (<= ``PRE_FREEZE_END``) need no declaration. A later day is
    cleared only inside ``SEARCH_DECLARED`` AND with the supplied sha256 equal
    to the pinned one. No markdown is parsed: the hash is the whole check.
    """
    if station not in MAKER_STATIONS:
        raise FirewallRefused(f"station {station!r} is outside the maker stations")
    if day <= PRE_FREEZE_END:
        return "PRE_FREEZE"
    if station not in SEARCH_DECLARED.stations or not (
        SEARCH_DECLARED.first_day <= day <= SEARCH_DECLARED.last_day
    ):
        raise FirewallRefused(f"{station} {day.isoformat()} is post-freeze and not SEARCH-declared")
    if declaration_sha256 != SEARCH_DECLARATION_SHA256:
        raise FirewallRefused(
            f"{station} {day.isoformat()} is post-freeze and the supplied declaration "
            "sha256 does not match the pinned value"
        )
    return "SEARCH_DECLARED"


def admit_print(
    station: str,
    climate_day: dt.date,
    requested_days: Collection[dt.date],
    requested_stations: Collection[str] = MAKER_STATIONS,
) -> bool:
    """True only for a maker station x requested, cleared day.

    Applied BEFORE any bucketing, count or log: a rejected print (NYC, a D+1
    slug, an out-of-range day) is discarded unrecorded -- no row, no counter,
    no value logged.
    """
    return (
        station in MAKER_STATIONS
        and station in requested_stations
        and climate_day in requested_days
    )


# --- Liveness -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GapInterval:
    """A recorded gap. ``end_ns`` None is an unresolved gap: it runs to +infinity."""

    start_ns: int
    end_ns: int | None


@dataclass(frozen=True, slots=True)
class AliveSpan:
    """One recorder instance's alive span (first..last ``VenueClockOffset`` ``ts_init``)
    with the gaps recorded BY THAT INSTANCE for the station-day's instruments."""

    start_ns: int
    end_ns: int
    gaps: tuple[GapInterval, ...]


def _merge(intervals: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _subtract(span: tuple[int, int], gaps: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    cursor = span[0]
    for start, end in _merge(gaps):
        if end <= cursor:
            continue
        if start >= span[1]:
            break
        if start > cursor:
            pieces.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < span[1]:
        pieces.append((cursor, span[1]))
    return pieces


def covered_intervals(
    window: tuple[int, int], spans: Sequence[AliveSpan]
) -> tuple[tuple[int, int], ...]:
    """Union over instances of (alive span clipped to the window) minus that instance's gaps.

    A gap belongs to the instance that recorded it: an unresolved gap (the
    process died with it open) runs to infinity but is clipped by its own
    instance's alive span, so a successor instance still covers its own span.
    """
    lo, hi = window
    pieces: list[tuple[int, int]] = []
    for span in spans:
        clipped = (max(span.start_ns, lo), min(span.end_ns, hi))
        if clipped[1] <= clipped[0]:
            continue
        gaps = [(g.start_ns, hi if g.end_ns is None else g.end_ns) for g in span.gaps]
        pieces.extend(_subtract(clipped, gaps))
    return _merge(pieces)


def _holes(window: tuple[int, int], covered: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    holes: list[tuple[int, int]] = []
    cursor = window[0]
    for start, end in covered:
        if start > cursor:
            holes.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window[1]:
        holes.append((cursor, window[1]))
    return holes


class _Coverage(NamedTuple):
    fraction: float
    longest_hole_ns: int
    tail_hole: tuple[int, int] | None


def _coverage(window: tuple[int, int], covered: Sequence[tuple[int, int]]) -> _Coverage:
    length = window[1] - window[0]
    holes = _holes(window, covered)
    covered_ns = length - sum(end - start for start, end in holes)
    longest = max((end - start for start, end in holes), default=0)
    tail = holes[-1] if holes and holes[-1][1] == window[1] else None
    return _Coverage(covered_ns / length if length > 0 else 0.0, longest, tail)


def _passes(fraction: float, longest_hole_ns: int) -> bool:
    return fraction >= COVERAGE_MIN and longest_hole_ns <= LONGEST_HOLE_MAX_MIN * _MINUTE_NS


def _tail_span_only(window: tuple[int, int], covered: Sequence[tuple[int, int]]) -> bool:
    """True when the day fails coverage but would pass with its trailing hole counted covered.

    The last ``VenueClockOffset`` is written once per 200 quote frames, so a quiet
    feed can end the measured alive span well before the instance really did.
    This isolates the days whose ONLY failure is that trailing hole -- an UPPER
    bound on the days the under-statement dropped, since a recorder that really
    died looks the same without a book read (a diagnostic count for the
    evidence doc; it never changes a verdict).
    """
    here = _coverage(window, covered)
    if _passes(here.fraction, here.longest_hole_ns) or here.tail_hole is None:
        return False
    patched = _merge([*covered, here.tail_hole])
    there = _coverage(window, patched)
    return _passes(there.fraction, there.longest_hole_ns)


# --- Prints ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PrintRecord:
    """One YES-instrument print, already admitted. ``rung`` is its instrument id."""

    trade_id: str
    ts_event_ns: int
    price_yes: Decimal
    aggressor: str
    rung: str
    size: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class PrintTally:
    buyer_by_bucket: tuple[int, int, int, int]
    prints_seller: int
    prints_no_aggressor: int
    rungs_with_qualifying_buyer: int
    n_prints: int = 0


def _bucket_index(price: Decimal) -> int | None:
    for index, (low, high) in enumerate(PRICE_BUCKETS):
        if low <= price < high:
            return index
    return None


def tally_prints(prints: Iterable[PrintRecord], start_ns: int, end_ns: int) -> PrintTally:
    """Count deduplicated prints inside ``[start_ns, end_ns)``.

    Deduplicated on ``trade_id`` (the same print is seen by every overlapping
    recorder instance). Only BUYER prints are bucketed; a BUYER at YES price
    >= ``QUALIFY_MIN_PRICE`` is the only thing that can fill a resting NO bid.
    """
    seen: set[str] = set()
    buyers = [0, 0, 0, 0]
    sellers = 0
    no_aggressor = 0
    qualifying_rungs: set[str] = set()
    for record in prints:
        if not (start_ns <= record.ts_event_ns < end_ns) or record.trade_id in seen:
            continue
        seen.add(record.trade_id)
        if record.aggressor == SELLER:
            sellers += 1
        elif record.aggressor == BUYER:
            index = _bucket_index(record.price_yes)
            if index is not None:
                buyers[index] += 1
            if record.price_yes >= QUALIFY_MIN_PRICE:
                qualifying_rungs.add(record.rung)
        else:
            no_aggressor += 1
    return PrintTally(
        (buyers[0], buyers[1], buyers[2], buyers[3]),
        sellers,
        no_aggressor,
        len(qualifying_rungs),
        len(seen),
    )


# --- Rows -----------------------------------------------------------------------------
_ROW_KEYS: Final[tuple[str, ...]] = (
    "buyer_by_bucket",
    "buyer_by_bucket_bidlive",
    "climate_day",
    "covered_bidlive",
    "coverage_fraction",
    "firewall_class",
    "first_seen_ns",
    "instances_clean",
    "instances_corrupt_unread",
    "instances_live_unread",
    "longest_hole_min",
    "n_prints",
    "n_prints_bidlive",
    "prints_no_aggressor",
    "prints_seller",
    "reason",
    "rungs_with_qualifying_buyer",
    "station",
    "tail_span_only",
)
_ZERO4: Final[tuple[int, int, int, int]] = (0, 0, 0, 0)


def _four(raw: object) -> tuple[int, int, int, int]:
    if not isinstance(raw, list) or len(raw) != len(PRICE_BUCKETS):
        raise ValueError("bucket columns must be a list of four counts")
    return (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))


@dataclass(frozen=True, slots=True)
class CensusedDay:
    """One station-day. ``instances_corrupt_unread`` / ``instances_live_unread`` count
    CORRUPT / LIVE instances whose directory names list this station-day; their
    bytes are never read (only the classifier's verdict is used)."""

    station: str
    climate_day: dt.date
    firewall_class: str
    reason: str
    coverage_fraction: float
    longest_hole_min: int
    tail_span_only: bool
    buyer_by_bucket: tuple[int, int, int, int]
    prints_seller: int
    prints_no_aggressor: int
    rungs_with_qualifying_buyer: int
    first_seen_ns: int | None
    instances_clean: int
    instances_corrupt_unread: int
    instances_live_unread: int = 0
    n_prints: int = 0
    # Parallel bid-live columns (sub-window; the plan window above stays the STOP basis).
    covered_bidlive: bool = False
    buyer_by_bucket_bidlive: tuple[int, int, int, int] = _ZERO4
    n_prints_bidlive: int = 0

    @property
    def has_qualifying_buyer(self) -> bool:
        return self.buyer_by_bucket[2] + self.buyer_by_bucket[3] > 0

    @property
    def has_qualifying_buyer_bidlive(self) -> bool:
        return self.buyer_by_bucket_bidlive[2] + self.buyer_by_bucket_bidlive[3] > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "buyer_by_bucket": list(self.buyer_by_bucket),
            "buyer_by_bucket_bidlive": list(self.buyer_by_bucket_bidlive),
            "climate_day": self.climate_day.isoformat(),
            "covered_bidlive": self.covered_bidlive,
            "coverage_fraction": self.coverage_fraction,
            "firewall_class": self.firewall_class,
            "first_seen_ns": self.first_seen_ns,
            "instances_clean": self.instances_clean,
            "instances_corrupt_unread": self.instances_corrupt_unread,
            "instances_live_unread": self.instances_live_unread,
            "longest_hole_min": self.longest_hole_min,
            "n_prints": self.n_prints,
            "n_prints_bidlive": self.n_prints_bidlive,
            "prints_no_aggressor": self.prints_no_aggressor,
            "prints_seller": self.prints_seller,
            "reason": self.reason,
            "rungs_with_qualifying_buyer": self.rungs_with_qualifying_buyer,
            "station": self.station,
            "tail_span_only": self.tail_span_only,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> CensusedDay:
        if set(raw) != set(_ROW_KEYS):
            diff = sorted(set(raw) ^ set(_ROW_KEYS))
            raise ValueError(f"censused day keys differ from the schema: {diff}")
        reason = str(raw["reason"])
        if reason not in REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        firewall = str(raw["firewall_class"])
        if firewall not in _FIREWALL_CLASSES:
            raise ValueError(f"unknown firewall_class {firewall!r}")
        first_seen = raw["first_seen_ns"]
        return cls(
            station=str(raw["station"]),
            climate_day=dt.date.fromisoformat(str(raw["climate_day"])),
            firewall_class=firewall,
            reason=reason,
            coverage_fraction=float(str(raw["coverage_fraction"])),
            longest_hole_min=int(str(raw["longest_hole_min"])),
            tail_span_only=bool(raw["tail_span_only"]),
            buyer_by_bucket=_four(raw["buyer_by_bucket"]),
            prints_seller=int(str(raw["prints_seller"])),
            prints_no_aggressor=int(str(raw["prints_no_aggressor"])),
            rungs_with_qualifying_buyer=int(str(raw["rungs_with_qualifying_buyer"])),
            first_seen_ns=None if first_seen is None else int(str(first_seen)),
            instances_clean=int(str(raw["instances_clean"])),
            instances_corrupt_unread=int(str(raw["instances_corrupt_unread"])),
            instances_live_unread=int(str(raw["instances_live_unread"])),
            n_prints=int(str(raw["n_prints"])),
            covered_bidlive=bool(raw["covered_bidlive"]),
            buyer_by_bucket_bidlive=_four(raw["buyer_by_bucket_bidlive"]),
            n_prints_bidlive=int(str(raw["n_prints_bidlive"])),
        )


class _Bidlive(NamedTuple):
    covered: bool
    buckets: tuple[int, int, int, int]
    n_prints: int


_NO_BIDLIVE: Final[_Bidlive] = _Bidlive(False, _ZERO4, 0)


def _bidlive(
    climate_day: dt.date,
    window: MakerWindow,
    spans: Sequence[AliveSpan],
    prints: Sequence[PrintRecord],
) -> _Bidlive:
    """Same coverage gates and print tally, on the bid-live sub-window."""
    bounds = bidlive_window_ns(climate_day=climate_day, window=window)
    if bounds[1] <= bounds[0]:
        return _NO_BIDLIVE
    cover = _coverage(bounds, covered_intervals(bounds, spans))
    if not _passes(cover.fraction, cover.longest_hole_ns):
        return _NO_BIDLIVE
    tally = tally_prints(prints, *bounds)
    return _Bidlive(True, tally.buyer_by_bucket, tally.n_prints)


def _row(
    station: str,
    climate_day: dt.date,
    firewall_class: str,
    reason: str,
    *,
    clean: int,
    corrupt_unread: int,
    live_unread: int,
    first_seen_ns: int | None,
    coverage_fraction: float = 0.0,
    longest_hole_min: int = 0,
    tail_span_only: bool = False,
    tally: PrintTally | None = None,
    bidlive: _Bidlive = _NO_BIDLIVE,
) -> CensusedDay:
    counted = tally if tally is not None else PrintTally(_ZERO4, 0, 0, 0, 0)
    return CensusedDay(
        station=station,
        climate_day=climate_day,
        firewall_class=firewall_class,
        reason=reason,
        coverage_fraction=coverage_fraction,
        longest_hole_min=longest_hole_min,
        tail_span_only=tail_span_only,
        buyer_by_bucket=counted.buyer_by_bucket,
        prints_seller=counted.prints_seller,
        prints_no_aggressor=counted.prints_no_aggressor,
        rungs_with_qualifying_buyer=counted.rungs_with_qualifying_buyer,
        first_seen_ns=first_seen_ns,
        instances_clean=clean,
        instances_corrupt_unread=corrupt_unread,
        instances_live_unread=live_unread,
        n_prints=counted.n_prints,
        covered_bidlive=bidlive.covered,
        buyer_by_bucket_bidlive=bidlive.buckets,
        n_prints_bidlive=bidlive.n_prints,
    )


def classify(
    *,
    station: str,
    climate_day: dt.date,
    firewall_class: str,
    window: MakerWindow,
    clean_instances: int,
    trade_parse_failed: bool,
    spans: Sequence[AliveSpan],
    prints: Iterable[PrintRecord],
    first_seen_ns: int | None,
    corrupt_unread: int = 0,
    live_unread: int = 0,
) -> CensusedDay:
    """One row per station-day, ``reason`` from the closed alphabet.

    Precedence: PRE_TRADE_CAPTURE (from the window alone, no tape consulted);
    with no CLEAN instance, AMBIGUOUS_NO_CLEAN_INSTANCE (a LIVE/CORRUPT instance
    lists the day, so the absence is not evidence) or NEVER_LISTED;
    TRADE_PARSE_FAILURE (never a silent lower count); LOW_COVERAGE; LONG_HOLE;
    COVERED. Plan-window counts are populated only for COVERED days. The
    bid-live columns are computed whenever the tape was read cleanly, even if
    the 23 h plan window failed its gates.
    """
    if window.start_ns < TRADE_CAPTURE_START_NS:
        return _row(
            station, climate_day, firewall_class, "PRE_TRADE_CAPTURE",
            clean=0, corrupt_unread=0, live_unread=0, first_seen_ns=None,
        )  # fmt: skip
    if clean_instances == 0:
        ambiguous = corrupt_unread + live_unread > 0
        reason = "AMBIGUOUS_NO_CLEAN_INSTANCE" if ambiguous else "NEVER_LISTED"
        return _row(
            station, climate_day, firewall_class, reason,
            clean=0, first_seen_ns=first_seen_ns,
            corrupt_unread=corrupt_unread, live_unread=live_unread,
        )  # fmt: skip
    if trade_parse_failed:
        return _row(
            station, climate_day, firewall_class, "TRADE_PARSE_FAILURE",
            clean=clean_instances, first_seen_ns=first_seen_ns,
            corrupt_unread=corrupt_unread, live_unread=live_unread,
        )  # fmt: skip

    materialised = tuple(prints)
    bounds = (window.start_ns, window.end_ns)
    covered = covered_intervals(bounds, spans)
    cover = _coverage(bounds, covered)
    hole_min = cover.longest_hole_ns // _MINUTE_NS
    bidlive = _bidlive(climate_day, window, spans, materialised)
    failure = (
        "LOW_COVERAGE"
        if cover.fraction < COVERAGE_MIN
        else "LONG_HOLE"
        if cover.longest_hole_ns > LONGEST_HOLE_MAX_MIN * _MINUTE_NS
        else None
    )
    if failure is not None:
        return _row(
            station, climate_day, firewall_class, failure,
            clean=clean_instances, first_seen_ns=first_seen_ns,
            corrupt_unread=corrupt_unread, live_unread=live_unread,
            coverage_fraction=cover.fraction, longest_hole_min=hole_min,
            tail_span_only=_tail_span_only(bounds, covered), bidlive=bidlive,
        )  # fmt: skip
    return _row(
        station, climate_day, firewall_class, "COVERED",
        clean=clean_instances, first_seen_ns=first_seen_ns,
            corrupt_unread=corrupt_unread, live_unread=live_unread,
        coverage_fraction=cover.fraction, longest_hole_min=hole_min,
        tally=tally_prints(materialised, *bounds), bidlive=bidlive,
    )  # fmt: skip


# --- Summary --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CensusSummary:
    n_cov: int
    d_cov: int
    n_eff_ub: float
    c: float | None
    c_030: float | None
    tail_span_only: int
    stops: tuple[str, ...]
    flag: str | None
    s5_unscreened: bool = False
    n_cov_bidlive: int = 0
    d_cov_bidlive: int = 0
    c_bidlive: float | None = None
    n_eff_ub_bidlive: float = 0.0


def _per_date(rows: Iterable[CensusedDay]) -> dict[dt.date, int]:
    counts: dict[dt.date, int] = defaultdict(int)
    for row in rows:
        counts[row.climate_day] += 1
    return counts


def _n_eff(per_date: dict[dt.date, int]) -> float:
    return sum(m / (1 + (m - 1) * RHO_ASSUMED) for m in per_date.values())


def summarise(rows: Iterable[CensusedDay]) -> CensusSummary:
    """``N_cov``, ``D_cov``, ``n_eff_ub`` (rho ASSUMED), ``C`` and the STOP lines.

    ``n_eff_ub = sum_d m_d / (1 + (m_d - 1) * RHO_ASSUMED)`` over covered
    station-day units ``m_d`` per climate date. ``C`` = covered station-days
    with >= 1 YES BUYER print at p_yes >= 0.20 in the window / ``N_cov``
    (any rung, queue-blind: loose upward). Rows that are not COVERED
    (PRE_TRADE_CAPTURE, NEVER_LISTED, AMBIGUOUS_NO_CLEAN_INSTANCE, ...) are
    excluded from every denominator. S-1 and S-5 are evaluated on the PLAN
    window; S-5 only once ``S5_MIN_COVERED`` station-days are covered, else it
    is UNSCREENED. The ``*_bidlive`` figures are a parallel report on the
    bid-live sub-window and never gate a STOP.
    """
    materialised = list(rows)
    covered = [r for r in materialised if r.reason == "COVERED"]
    per_date = _per_date(covered)
    n_eff = _n_eff(per_date)
    n_cov = len(covered)
    c = sum(1 for r in covered if r.has_qualifying_buyer) / n_cov if n_cov else None
    c_030 = sum(1 for r in covered if r.buyer_by_bucket[3] > 0) / n_cov if n_cov else None
    screened = n_cov >= S5_MIN_COVERED
    stops: list[str] = []
    if n_eff < N_EFF_FLOOR:
        stops.append("S-1")
    if screened and c is not None and c < C_STOP:
        stops.append("S-5")
    flag = "KILL-LIKELY" if screened and c is not None and C_STOP <= c < C_FLAG else None
    live = [r for r in materialised if r.covered_bidlive]
    live_dates = _per_date(live)
    c_live = sum(1 for r in live if r.has_qualifying_buyer_bidlive) / len(live) if live else None
    return CensusSummary(
        n_cov=n_cov,
        d_cov=len(per_date),
        n_eff_ub=n_eff,
        c=c,
        c_030=c_030,
        tail_span_only=sum(1 for r in materialised if r.tail_span_only),
        stops=tuple(stops),
        flag=flag,
        s5_unscreened=not screened,
        n_cov_bidlive=len(live),
        d_cov_bidlive=len(live_dates),
        c_bidlive=c_live,
        n_eff_ub_bidlive=_n_eff(live_dates),
    )


# --- JSONL ----------------------------------------------------------------------------
def write_censused_days(path: Path, rows: Iterable[CensusedDay]) -> None:
    """Sorted, byte-idempotent JSONL. Refuses duplicate (station, day) keys."""
    ordered = sorted(rows, key=lambda r: (r.station, r.climate_day))
    keys = [(r.station, r.climate_day) for r in ordered]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate (station, climate_day) rows refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        json.dumps(r.to_dict(), sort_keys=True, separators=(",", ":")) + "\n" for r in ordered
    )
    path.write_text(body, encoding="utf-8")


def read_censused_days(path: Path) -> list[CensusedDay]:
    """Read back; refuses unknown/missing keys, an unknown reason and duplicates."""
    rows = [
        CensusedDay.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    keys = [(r.station, r.climate_day) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate (station, climate_day) rows in {path}")
    return rows
