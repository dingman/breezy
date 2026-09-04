"""v1 structural-dead stop -- PREREG v1 section 5:105-106, additive.

Ruled implementable on v1 (BE computation, `build_realized_stratum`,
`break_even`, `FEE_THETA`, the Wilson z, the 60/150 floors, and the
existing `cell_dead`/`pooled_survive` logic in `live_family_tally.py` are
UNCHANGED by this module) in
`docs/evidence/grok_prereg_v2_ratification_2026-09-04.md`, Final ruling
(1)(f) and (3) "Allowed on v1".

Distinct from the D0+165 stop. Fires when the family (LAX, MDW, MIA, SFO)
has accumulated >= `MIN_STRUCTURAL_DEAD_STATION_DAYS` "afternoon-covered
listed" station-days with ZERO filled Takes across them. This is a
structural-absence test, not a Wilson take-rate test: one fill anywhere in
the set defeats it outright, no epsilon, no partial credit.

Definitions (pinned verbatim from the ruling):
  * window: `[12:00, 17:00)` LST (PREREG v1 section 2:35-36).
  * "afternoon-covered": the span of distinct captured Depth10/quote
    instants in that window is >= 30 minutes; 0 or 1 instant -> 0. This is
    EXACTLY `ma_prelock_winner_ask_study.collect_window_instants` /
    `afternoon_coverage_minutes` / `MIN_AFTERNOON_COVERAGE_MINUTES`,
    imported below rather than re-declared (a second copy of a 30-minute
    span rule is a second policy that can silently disagree with M_A's).
  * "listed": the venue listed that station-day. A day the venue never
    listed is never captured and therefore never appears in the discovered
    station-day set at all (`discover_station_days`,
    `ma_prelock_winner_ask_study.py:547-560`) -- so "listed" is exactly
    "present in that discovered set", with skip-days excluded by
    construction, never by a second re-derivation of the census (PREREG v1
    section 2:45-47: skip-days are NOT in the denominator).
  * denominator: covered-listed station-days of the family set (LAX, MDW,
    MIA, SFO) -- `cli_basis_setup_win_rate_study.DENSE_STATIONS`, reused
    rather than re-listing the four cities as a local literal.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_setup_win_rate_study import DENSE_STATIONS
from h4_preliminary_economic_read import DepthObservation, load_depth
from ma_prelock_winner_ask_study import (
    ASOS_FETCH_END,
    ASOS_FETCH_START,
    DEFAULT_QUOTE_TAPE_CATALOG,
    MIN_AFTERNOON_STATION_DAYS,
    afternoon_coverage_minutes,
    collect_window_instants,
    discover_station_days,
    instrument_ids_for,
)
from settlement_alignment_study import load_sites

__all__ = [
    "MIN_STRUCTURAL_DEAD_STATION_DAYS",
    "StructuralDeadVerdict",
    "structural_dead",
    "covered_listed_station_days",
    "count_covered_listed_station_days_from_catalog",
    "main",
]

#: Reused verbatim from `ma_prelock_winner_ask_study` (SS2/SS3 K-A) -- this
#: stop shares the exact same "15 station-days to discriminate" floor,
#: never a second, potentially-drifting literal.
MIN_STRUCTURAL_DEAD_STATION_DAYS = MIN_AFTERNOON_STATION_DAYS


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuralDeadVerdict:
    """The v1 section 5:105-106 verdict, plus the two counts it is built from.

    `filled_takes=None` means the FILL-TIME count (fills, including any not
    yet settled/scored) could not be sourced -- `evaluable` is `False` and
    `structural_dead` is unconditionally `False` in that case. A SETTLED-only
    count (e.g. `len(scored rows)`) would undercount a Take that filled but
    has not settled yet, which would fire a false KILL against the pin "one
    fill defeats it" -- so this verdict must never be built from a settled-
    only count.
    """

    structural_dead: bool
    evaluable: bool
    covered_listed_station_days: int
    filled_takes: int | None


def structural_dead(
    *, covered_listed_station_days: int, filled_takes: int | None
) -> StructuralDeadVerdict:
    """`>= MIN_STRUCTURAL_DEAD_STATION_DAYS` covered-listed days, zero fills.

    One fill anywhere in the set defeats it -- this is a structural-absence
    test, not a Wilson take-rate test: no epsilon is applied to
    `filled_takes`. FAILS CLOSED (never fires) when `filled_takes` is `None`
    -- see `StructuralDeadVerdict`.
    """
    evaluable = filled_takes is not None
    fired = (
        evaluable
        and covered_listed_station_days >= MIN_STRUCTURAL_DEAD_STATION_DAYS
        and filled_takes == 0
    )
    return StructuralDeadVerdict(
        structural_dead=fired,
        evaluable=evaluable,
        covered_listed_station_days=covered_listed_station_days,
        filled_takes=filled_takes,
    )


#: Injected so the counting core is testable without a real Parquet catalog
#: -- the catalog-touching wrapper below is the only caller that needs one.
DepthLoader = Callable[[str, dt.date], Mapping[str, Sequence[DepthObservation]]]


def covered_listed_station_days(
    *,
    station_days: Sequence[tuple[str, dt.date]],
    load_depth_for_day: DepthLoader,
    std_utc_offset_by_city: Mapping[str, float],
) -> int:
    """Count "afternoon-covered" days among the given "listed" station-days.

    `station_days` IS the listed set: a venue-skipped day is never in it
    (see module docstring), so this function performs no independent
    listing/skip-day logic of its own -- only the coverage test.

    CAVEAT (no cheap census reader is currently wired in): a station-day the
    venue DID list but whose capture had an OUTAGE (recorder down, disk
    full, feed disconnect -- `docs/evidence/recorder hangs disconnected`
    class of failure) is INDISTINGUISHABLE here from a day the venue never
    listed at all -- both are simply absent from `station_days`, since
    `discover_station_days` only sees what was actually captured. This
    under-counts "listed" in exactly the outage case, which is
    conservative for this stop (fewer covered-listed days delays a KILL,
    never manufactures one) but would silently suppress a real dead-cell
    signal if outages were frequent. `docs/evidence/venue_city_census_
    2026-09-03.md` records the venue's independently-observed listing
    calendar and could resolve this distinction, but it is a Markdown
    evidence artifact, not a machine-readable store, so no code path here
    cross-checks against it; a future census reader should compare its
    count against `len(station_days)` and warn on a mismatch.
    """
    count = 0
    for city, climate_day in station_days:
        depth = load_depth_for_day(city, climate_day)
        instants = collect_window_instants(
            depth,
            climate_day=climate_day,
            std_utc_offset_hours=std_utc_offset_by_city[city],
        )
        if afternoon_coverage_minutes(instants) >= 30.0:
            count += 1
    return count


def count_covered_listed_station_days_from_catalog(
    *,
    catalog_root: Path,
    cities: Sequence[str] = DENSE_STATIONS,
    fetch_start: dt.date = ASOS_FETCH_START,
    fetch_end: dt.date = ASOS_FETCH_END,
) -> int:
    """The I/O wrapper: discovers listed station-days, then counts coverage.

    Reuses `discover_station_days` / `instrument_ids_for`
    (`ma_prelock_winner_ask_study.py:547-567`) for "listed", and `load_depth`
    (`h4_preliminary_economic_read.py:572`) for the captured instants --
    the same quote-tape catalog reader the M_A/M_B studies already use.
    """
    depth_root = catalog_root / "data" / "order_book_depths"
    station_days = discover_station_days(
        depth_root=depth_root, cities=cities, fetch_start=fetch_start, fetch_end=fetch_end
    )
    std_utc_offset_by_city = {spec.city: spec.std_utc_offset_hours for spec in load_sites()}

    def _loader(city: str, climate_day: dt.date) -> Mapping[str, Sequence[DepthObservation]]:
        instrument_ids = instrument_ids_for(
            depth_root=depth_root, city=city, climate_day=climate_day
        )
        return load_depth(catalog_root=catalog_root, instrument_ids=instrument_ids)

    return covered_listed_station_days(
        station_days=station_days,
        load_depth_for_day=_loader,
        std_utc_offset_by_city=std_utc_offset_by_city,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog-root",
        default=str(DEFAULT_QUOTE_TAPE_CATALOG),
        help="quote-tape Parquet catalog root (mirrors --quote-catalog on "
        "ma_prelock_winner_ask_study.py / mb_current_rung_edge_study.py)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    count = count_covered_listed_station_days_from_catalog(
        catalog_root=Path(args.catalog_root).expanduser()
    )
    print(f"covered-listed station-days: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
