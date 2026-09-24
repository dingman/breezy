"""AUD-08b: fold the unregistered-city sighting sidecar into the station-candidate register.

ADVISORY ONLY. A candidate record never makes a city tradeable: it queues a
strategy-lead ruling plus the ``sites.toml`` re-verification gate (AUD-08
§6c steps 3-4, both OUTSIDE this item). ``SUPPORTED_STATIONS`` and
``sites.toml`` are read here, never written.

One nightly run, riding ``breezy-quote-tape-rotate.service``:

1. Refuse -- exit 1 having written NOTHING -- when ``--catalog-root`` is not a
   directory, when its ``data/order_book_depths`` is absent, or when the
   covered-station-day counter raises ``QuoteTapeGapDataUnavailable``
   (round-4 A8-6). An unreadable catalog is never read as ``count=0``.
2. Read every retained sidecar day (``[today-35d, today)``; today's file is
   still being appended by the recorder and is never folded). Fold them with
   the registry seeds (the registered-but-unsupported cities, in the
   ``venue_city_token`` domain) through the pure ``merge_sightings``.
3. Refuse a flood: more NEW sighting cities in one fold than the settlement
   registry holds ``(venue, city)`` pairs for the venue (§9).
4. Write the register atomically, emit ONE ``BREEZY_STATION_CANDIDATE_NEW``
   alert per sighting-origin record first recorded today, advance the
   ``last_folded_day`` watermark, prune sidecar files older than 35 days,
   print one summary line.

No venue call. Sufficiency reuses the KILL clock's own counter and floor
(``structural_dead_stop``), never a second threshold.

The ``last_folded_day`` watermark is NOT an input filter -- every retained
sidecar day is re-read each run, which is what keeps ``distinct_*`` exact
over the window and the fold idempotent. Its roles are: (a) naming which days
are newly folded (summary), (b) counting expired days pruned before any
successful run could fold them (``sidecar_days_lost``), and (c) the
staleness alarm -- after every successful run it is YESTERDAY, so an age of
more than two days means the fold has been skipped or refused, and the run
(or the wrapper's lock-skip path, ``--check-staleness``) raises
``BREEZY_STATION_CANDIDATE_STALE``.

Clearing a persistent flood refusal (operator): the refusal repeats every
night while the offending ``sightings/sightings-<day>.jsonl`` files remain
inside the 35-day window. Review them (a venue-shape event, not a batch of
candidates), then move them OUT of ``sightings/`` (e.g. to a dated
``quarantine/`` directory beside it); the next run folds the rest. Never raise
the cap: it is derived from the settlement registry on purpose.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ma_prelock_winner_ask_study import DEFAULT_QUOTE_TAPE_CATALOG
from structural_dead_stop import (
    MIN_STRUCTURAL_DEAD_STATION_DAYS,
    QuoteTapeGapDataUnavailable,
    count_covered_listed_station_days_from_catalog,
)

from breezy.persistence.station_candidates import (
    STATION_CANDIDATES_DIR,
    SightingSidecarCorruptError,
    StationCandidate,
    StationCandidateRegisterCorruptError,
    Sufficiency,
    UnknownSightingSchemaError,
    UnknownStationCandidateSchemaError,
    UnregisteredCitySighting,
    compact_station_candidates,
    merge_sightings,
    read_last_folded_day,
    read_sightings_file,
    read_station_candidates,
    sighting_file_days,
    sighting_path,
    stale_record_count,
    write_last_folded_day,
    write_station_candidates,
)
from breezy.registry.sites import SiteRegistry, default_registry
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert, resolve_alert_sink
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS

__all__ = [
    "DEFAULT_QUOTE_TAPE_CATALOG",
    "MIN_STRUCTURAL_DEAD_STATION_DAYS",
    "SIDECAR_RETENTION_DAYS",
    "QuoteTapeGapDataUnavailable",
    "check_staleness",
    "count_covered_listed_station_days_from_catalog",
    "flood_cap",
    "main",
    "parse_args",
    "registry_seed_cities",
    "run",
    "sufficiency_from_covered_listed_days",
]

VENUE: Final[str] = "polymarket_us"
SIDECAR_RETENTION_DAYS: Final[int] = 35
ALERT_EVENT: Final[str] = "BREEZY_STATION_CANDIDATE_NEW"
STALE_ALERT_EVENT: Final[str] = "BREEZY_STATION_CANDIDATE_STALE"
#: A healthy watermark is yesterday (age 1). Older than this means the fold has
#: been skipped (studies lock) or refused for more than two nights.
STALE_WATERMARK_DAYS: Final[int] = 2
_PREFIX: Final[str] = "station-candidate-register"

_READ_ERRORS: Final[tuple[type[Exception], ...]] = (
    OSError,
    SightingSidecarCorruptError,
    StationCandidateRegisterCorruptError,
    UnknownSightingSchemaError,
    UnknownStationCandidateSchemaError,
)


class _Refused(Exception):
    """The emitter refuses: nothing is written, the watermark does not move."""


def sufficiency_from_covered_listed_days(count: int) -> Sufficiency:
    """AUD-08 §6b.3's total mapping; the boundary is the KILL clock's own floor."""
    if count < 0:
        raise ValueError(f"covered-listed station-day count cannot be negative: {count}")
    if count == 0:
        return "REGISTRY_ONLY_NO_CAPTURE"
    if count < MIN_STRUCTURAL_DEAD_STATION_DAYS:
        return "CAPTURED_INSUFFICIENT"
    return "CAPTURE_SUFFICIENT"


def registry_seed_cities(
    venue: str, registry: SiteRegistry | None = None
) -> tuple[tuple[str, str, str], ...]:
    """``(venue, venue_city_token, station_code)`` for registered-but-unsupported cities.

    Same comprehension body as ``discovery_city_codes_from_registry``, so the
    token is in the domain a sighting and the AUD-09a join use (round-3 A8-4).
    """
    active = default_registry() if registry is None else registry
    return tuple(
        (venue, active.venue_symbology(registered_venue, city).venue_city_token, city)
        for registered_venue, city in active.pairs()
        if registered_venue == venue and city not in SUPPORTED_STATIONS
    )


def flood_cap(venue: str, registry: SiteRegistry | None = None) -> int:
    """§9: a one-day jump larger than the venue's whole known surface needs a human."""
    active = default_registry() if registry is None else registry
    return sum(1 for registered_venue, _city in active.pairs() if registered_venue == venue)


def _require_catalog(catalog_root: Path) -> None:
    if not catalog_root.is_dir():
        raise _Refused(f"catalog root is not a readable directory: {catalog_root}")
    depth_root = catalog_root / "data" / "order_book_depths"
    if not depth_root.is_dir():
        raise _Refused(f"depth_root_present=false under {catalog_root}")


def _seed_sufficiency(
    catalog_root: Path, seeds: Sequence[tuple[str, str, str]]
) -> dict[tuple[str, str], Sufficiency]:
    by_city: dict[tuple[str, str], Sufficiency] = {}
    for venue, token, station in seeds:
        try:
            count = count_covered_listed_station_days_from_catalog(
                catalog_root=catalog_root, cities=(station,)
            )
        except QuoteTapeGapDataUnavailable as exc:
            raise _Refused(f"counter refused for {station}: {exc}") from exc
        by_city[(venue, token)] = sufficiency_from_covered_listed_days(count)
    return by_city


def _alert_detail(city_token: str) -> str:
    return (
        f"new venue city {city_token} recorded; to make it eligible a strategy-lead "
        "ruling under docs/evidence/ plus the sites.toml re-verification gate must be "
        "opened - see AUD-08 §6c"
    )


def run(
    *,
    catalog_root: Path,
    state_dir: Path,
    today: dt.date,
    alert_sink: AlertSink,
    venue: str = VENUE,
) -> int:
    """One emission. Returns the process exit status."""
    try:
        return _run(
            catalog_root=catalog_root,
            state_dir=state_dir,
            today=today,
            alert_sink=alert_sink,
            venue=venue,
        )
    except _Refused as exc:
        print(
            f"{_PREFIX}: REFUSED -- {exc}; register, watermark and sidecars untouched",
            file=sys.stderr,
        )
        return 1


def _run(
    *,
    catalog_root: Path,
    state_dir: Path,
    today: dt.date,
    alert_sink: AlertSink,
    venue: str,
) -> int:
    register_path = state_dir / "station_candidates.jsonl"
    watermark_path = state_dir / "last_folded_day.json"
    sightings_dir = state_dir / "sightings"
    today_iso = today.isoformat()
    horizon = (today - dt.timedelta(days=SIDECAR_RETENTION_DAYS)).isoformat()

    _require_catalog(catalog_root)
    watermark = read_last_folded_day(watermark_path)
    _alert_if_stale(watermark, today=today, alert_sink=alert_sink)
    all_days = sighting_file_days(sightings_dir)
    retained = [day for day in all_days if horizon <= day < today_iso]
    expired = [day for day in all_days if day < horizon]
    lost = [day for day in expired if watermark is None or day > watermark]
    newly_folded = [day for day in retained if watermark is None or day > watermark]

    try:
        existing = read_station_candidates(register_path)
        sightings: list[UnregisteredCitySighting] = []
        partial = 0
        for day in retained:
            read = read_sightings_file(sighting_path(sightings_dir, day))
            sightings.extend(s for s in read.sightings if s.venue == venue)
            partial += read.partial_lines_skipped
    except _READ_ERRORS as exc:
        raise _Refused(f"{type(exc).__name__}: {exc}") from exc

    seeds = registry_seed_cities(venue)
    sufficiency_by_city = _seed_sufficiency(catalog_root, seeds)
    for sighting in sightings:
        key = (sighting.venue, sighting.city_token)
        sufficiency_by_city.setdefault(key, "NO_SETTLEMENT_TRUTH")

    merged = merge_sightings(
        existing,
        sightings,
        seed_cities=tuple((v, token) for v, token, _station in seeds),
        today=today_iso,
        sufficiency_by_city=sufficiency_by_city,
    )
    records = compact_station_candidates(
        merged, today=today_iso, sufficiency_by_city=sufficiency_by_city
    )
    existing_keys = {record.key for record in existing}
    new_sighted = [r for r in records if r.origin == "SIGHTING" and r.key not in existing_keys]
    cap = flood_cap(venue)
    if len(new_sighted) > cap:
        raise _Refused(
            f"flood: {len(new_sighted)} new cities in one fold exceeds the {cap} "
            f"registered {venue} pairs"
        )

    try:
        write_station_candidates(register_path, records)
    except OSError as exc:
        raise _Refused(f"register write failed: {exc}") from exc
    alerts = _emit_new_candidate_alerts(records, today=today_iso, alert_sink=alert_sink)
    # Every day before today has now been considered, whether or not it had a
    # sidecar file: a quiet venue (no unregistered city, the normal case) must
    # not read as a stale emitter.
    write_last_folded_day(watermark_path, (today - dt.timedelta(days=1)).isoformat())
    for day in expired:
        sighting_path(sightings_dir, day).unlink(missing_ok=True)

    print(
        f"{_PREFIX}: sightings_read={len(sightings)} partial_lines_skipped={partial} "
        f"days_folded={len(newly_folded)} sidecar_days_lost={len(lost)} "
        f"records_written={len(records)} "
        f"records_compacted={stale_record_count(records, today=today_iso)} "
        f"sidecars_pruned={len(expired)} alerts={alerts}"
    )
    return 0


def _alert_if_stale(watermark: str | None, *, today: dt.date, alert_sink: AlertSink) -> bool:
    """One alert per call when the last successful fold is > 2 days old.

    Absent watermark (fresh install) is not stale. Called once per nightly
    run -- both the full run and the lock-skip path -- so at most once a day.
    """
    if watermark is None:
        return False
    age_days = (today - dt.date.fromisoformat(watermark)).days
    if age_days <= STALE_WATERMARK_DAYS:
        return False
    emit_alert(
        alert_sink,
        AlertPayload(
            severity="WARN",
            event=STALE_ALERT_EVENT,
            site=f"{VENUE}/register",
            detail=(
                f"station-candidate register last folded {watermark} ({age_days} days "
                "ago); the nightly fold is being skipped or refused - check "
                "breezy-station-candidate-register.service"
            ),
        ),
    )
    return True


def check_staleness(*, state_dir: Path, today: dt.date, alert_sink: AlertSink) -> int:
    """The cheap lock-skip mode: no catalog read, no fold, no write."""
    watermark = read_last_folded_day(state_dir / "last_folded_day.json")
    stale = _alert_if_stale(watermark, today=today, alert_sink=alert_sink)
    print(f"{_PREFIX}: staleness check last_folded_day={watermark} stale={stale}")
    return 0


def _emit_new_candidate_alerts(
    records: Sequence[StationCandidate], *, today: str, alert_sink: AlertSink
) -> int:
    """Once per candidate: the durable register is the dedupe (A16), seeds never alert."""
    emitted = 0
    for record in records:
        if record.origin != "SIGHTING" or record.first_seen_day != today:
            continue
        emit_alert(
            alert_sink,
            AlertPayload(
                severity="WARN",
                event=ALERT_EVENT,
                site=f"{record.venue}/{record.city_token}",
                detail=_alert_detail(record.city_token),
            ),
        )
        emitted += 1
    return emitted


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog-root",
        default=str(DEFAULT_QUOTE_TAPE_CATALOG),
        help="quote-tape Parquet catalog root (same default as structural_dead_stop.py)",
    )
    parser.add_argument(
        "--state-dir",
        default=str(STATION_CANDIDATES_DIR),
        help="directory holding station_candidates.jsonl, last_folded_day.json, sightings/",
    )
    parser.add_argument("--today", default=None, help="UTC fold day (YYYY-MM-DD); default now")
    parser.add_argument(
        "--check-staleness",
        action="store_true",
        help="only alert if last_folded_day is stale; no catalog read, no fold (lock-skip path)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    today = (
        dt.date.fromisoformat(args.today)
        if args.today is not None
        else dt.datetime.now(dt.UTC).date()
    )
    state_dir = Path(args.state_dir).expanduser()
    if args.check_staleness:
        return check_staleness(state_dir=state_dir, today=today, alert_sink=resolve_alert_sink(env))
    return run(
        catalog_root=Path(args.catalog_root).expanduser(),
        state_dir=state_dir,
        today=today,
        alert_sink=resolve_alert_sink(env),
    )


if __name__ == "__main__":
    raise SystemExit(main())
