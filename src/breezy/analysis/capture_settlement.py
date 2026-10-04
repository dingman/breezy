"""AUT-1 capture settlement writer (plan r12 section 3.12, unchanged from r8 section 3.9).

Settlement truth is the NWS CLI product the ingest already stored in the per-station catalog. This
module READS it (``read_climate_day_including_corrections``, the audit accessor) and appends one
``SettlementRecord`` per ``(station, climate_day, raw_sha256)`` to
``<decisions_dir>/settlement_<climate_day>.jsonl``. It fetches nothing and opens no network
connection; the catalog is opened read-only and never created.

* Scan: ``[today - 7, today - 1]`` climate days, for every station of the venue.
* Once per ``raw_sha256``: an existing line with the same key is skipped. A correction has a new
  ``raw_sha256`` and appends a new line; readers take the greatest ``ts_ns`` (the catalog record's
  ``retrieved_at_ns``, so the order is deterministic and survives a re-run).
* ``basis`` is venue-owned (``VENUE_BASIS``). An unknown venue is refused, never defaulted.
* Only a final record with a ``tmax_f`` is settlement truth. A preliminary or an empty day is
  *pending*: it is not written and not an error (the audit's 48 h check is the backstop).
* One writer: this module owns ``settlement_*.jsonl``. A file is rewritten whole, existing bytes
  first, through ``single_read.replace_atomic`` (a temp file in ``<decisions_dir>``, which is the
  unit's bind), under the module's own lock ``<decisions_dir>/.capture_settlement.lock``.
* Failure: a read or write error for a station-day offers a CRITICAL ``CAPTURE_SETTLEMENT_ERROR``
  (detail ``station=<s> climate_day=<d> cause=<ErrorType>``, never the message) and the run goes
  on. The result's ``exit_code`` is 1 on any error and on any alert the outbox did not accept.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.autonomy.capture_alerts import CAPTURE_ALERT_SEVERITIES
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    open_root,
    read_once_at,
    replace_atomic,
)
from breezy.persistence.catalog import (
    open_station_catalog,
    read_climate_day_including_corrections,
    station_catalog_path,
)
from breezy.registry.sites import SiteRegistry

__all__ = [
    "ERROR_EVENT",
    "LOCK_FILE",
    "SCAN_BACK_DAYS",
    "VENUE_BASIS",
    "AlertOffer",
    "CatalogMissing",
    "SettlementError",
    "SettlementFileCorrupt",
    "SettlementLockBusy",
    "SettlementRecord",
    "SettlementRunResult",
    "SettlementSite",
    "StationDayError",
    "UnknownVenueBasis",
    "read_catalog_day",
    "run_settlement",
    "scan_days",
    "settlement_file_name",
    "settlement_lock",
    "venue_sites",
]

ERROR_EVENT: Final[str] = "CAPTURE_SETTLEMENT_ERROR"
SCAN_BACK_DAYS: Final[int] = 7
LOCK_FILE: Final[str] = ".capture_settlement.lock"
#: The venue's settlement source. Polymarket.us settles on the NWS CLI. A Kalshi family adds its own
#: row when it lands (memory: Kalshi settles on The Weather Company); there is no default.
VENUE_BASIS: Final[Mapping[str, str]] = {"polymarket_us": "NWS_CLI"}

_FILE_MODE: Final[int] = 0o600
_LOCK_MODE: Final[int] = 0o600
_MAX_FILE_BYTES: Final[int] = 8 * 1024 * 1024
_RECORD_KEYS: Final[tuple[str, ...]] = (
    "station",
    "climate_day",
    "settlement_tmax_f",
    "basis",
    "raw_sha256",
    "ts_ns",
)

#: ``(event, severity, detail) -> accepted``: the outbox seam shared with WP1 and WP4.
AlertOffer = Callable[[str, str, str], bool]


class SettlementError(Exception):
    """Base of this module's errors; the class name is the alert ``cause``."""


class CatalogMissing(SettlementError):
    """The station's catalog directory does not exist (it is never created here)."""


class SettlementFileCorrupt(SettlementError):
    """An existing ``settlement_<day>.jsonl`` is not a clean file of settlement records."""


class SettlementLockBusy(SettlementError):
    """Another run holds the settlement lock."""


class UnknownVenueBasis(SettlementError):
    """The venue has no entry in the basis table."""


@dataclass(frozen=True, slots=True)
class SettlementSite:
    """A venue city and the CLI location its catalog records carry in ``station``."""

    city: str
    cli_location: str


@dataclass(frozen=True, slots=True)
class SettlementRecord:
    station: str
    climate_day: str
    settlement_tmax_f: int
    basis: str
    raw_sha256: str
    ts_ns: int

    def key(self) -> tuple[str, str, str]:
        return (self.station, self.climate_day, self.raw_sha256)

    def to_line(self) -> str:
        body = {name: getattr(self, name) for name in _RECORD_KEYS}
        return json.dumps(body, separators=(",", ":")) + "\n"


@dataclass(frozen=True, slots=True)
class StationDayError:
    station: str
    climate_day: str
    cause: str

    def detail(self) -> str:
        return f"station={self.station} climate_day={self.climate_day} cause={self.cause}"


@dataclass(frozen=True, slots=True)
class SettlementRunResult:
    appended: int = 0
    already_present: int = 0
    pending: int = 0
    errors: tuple[StationDayError, ...] = ()
    delivery_failed: bool = False
    undelivered: tuple[str, ...] = field(default=())

    @property
    def exit_code(self) -> int:
        return 1 if self.errors or self.delivery_failed else 0


def scan_days(today: dt.date) -> tuple[dt.date, ...]:
    """``[today - 7, today - 1]``, oldest first."""
    return tuple(today - dt.timedelta(days=back) for back in range(SCAN_BACK_DAYS, 0, -1))


def settlement_file_name(climate_day: dt.date | str) -> str:
    day = climate_day.isoformat() if isinstance(climate_day, dt.date) else climate_day
    return f"settlement_{day}.jsonl"


def venue_sites(registry: SiteRegistry, venue: str) -> tuple[SettlementSite, ...]:
    """The venue's cities with the registry's CLI location (never derived from the city key)."""
    return tuple(
        SettlementSite(city, registry.settlement_site(venue, city).cli_location)
        for pair_venue, city in registry.pairs()
        if pair_venue == venue
    )


def read_catalog_day(
    catalog_base: Path, venue: str, site: SettlementSite, day: dt.date
) -> NwsClimateDay | None:
    """The audit answer for one station-day, from an existing catalog (read-only, no mkdir)."""
    root = station_catalog_path(catalog_base, venue, site.city)
    if root.is_symlink() or not root.is_dir():
        raise CatalogMissing(site.city)
    # The root exists, so ``open_station_catalog``'s mkdir is a no-op: it creates nothing.
    catalog = open_station_catalog(catalog_base, venue, site.city)
    return read_climate_day_including_corrections(
        catalog, station=site.cli_location, climate_day=day
    )


def _acquire_lock(decisions_dir: Path) -> int:
    fd = os.open(
        decisions_dir / LOCK_FILE,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
        _LOCK_MODE,
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise SettlementLockBusy(LOCK_FILE) from None
    return fd


@contextmanager
def settlement_lock(decisions_dir: Path) -> Iterator[None]:
    """This unit's own lock (non-blocking: a second run is refused, never queued)."""
    fd = _acquire_lock(decisions_dir)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _parse_existing(raw: bytes) -> tuple[SettlementRecord, ...]:
    if raw and not raw.endswith(b"\n"):
        raise SettlementFileCorrupt("no trailing newline")
    records: list[SettlementRecord] = []
    for line in raw.decode("utf-8", errors="strict").splitlines():
        body: Any = json.loads(line)
        if not isinstance(body, dict) or tuple(body) != _RECORD_KEYS:
            raise SettlementFileCorrupt("unexpected keys")
        try:
            records.append(SettlementRecord(**body))
        except TypeError as exc:  # pragma: no cover - keys already checked
            raise SettlementFileCorrupt("unexpected fields") from exc
    return tuple(records)


def _read_existing(decisions_dir: Path, day: str) -> tuple[bytes, tuple[SettlementRecord, ...]]:
    rootfd = open_root(decisions_dir)
    try:
        raw = read_once_at(
            rootfd, settlement_file_name(day), max_bytes=_MAX_FILE_BYTES, policy=ReadPolicy.STRICT
        )
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.NOT_FOUND:
            return b"", ()
        raise
    finally:
        os.close(rootfd)
    try:
        return raw, _parse_existing(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SettlementFileCorrupt(type(exc).__name__) from exc


def _record_for(
    record: NwsClimateDay | None, site: SettlementSite, day: dt.date, basis: str
) -> SettlementRecord | None:
    if record is None or not record.is_final or record.tmax_f is None:
        return None
    return SettlementRecord(
        station=site.cli_location,
        climate_day=day.isoformat(),
        settlement_tmax_f=record.tmax_f,
        basis=basis,
        raw_sha256=record.raw_sha256,
        ts_ns=record.ts_init,
    )


def _deliver(offer: AlertOffer, errors: Sequence[StationDayError]) -> tuple[bool, tuple[str, ...]]:
    severity = CAPTURE_ALERT_SEVERITIES[ERROR_EVENT]
    undelivered: list[str] = []
    for error in errors:
        try:
            accepted = offer(ERROR_EVENT, severity, error.detail())
        except Exception:  # noqa: BLE001 - an outbox failure is a failed delivery, not a crash
            accepted = False
        if not accepted:
            undelivered.append(error.detail())
    return bool(undelivered), tuple(undelivered)


_ReadDay = Callable[[Path, str, SettlementSite, dt.date], "NwsClimateDay | None"]


@dataclass(slots=True)
class _Tally:
    appended: int = 0
    already: int = 0
    pending: int = 0
    errors: list[StationDayError] = field(default_factory=list)


def _collect_day(
    day: dt.date,
    venue: str,
    basis: str,
    sites: Sequence[SettlementSite],
    catalog_base: Path,
    read_day: _ReadDay,
    tally: _Tally,
) -> list[SettlementRecord]:
    found: list[SettlementRecord] = []
    for site in sites:
        try:
            record = _record_for(read_day(catalog_base, venue, site, day), site, day, basis)
        except Exception as exc:  # noqa: BLE001 - per-station-day isolation; only the type is kept
            tally.errors.append(
                StationDayError(site.cli_location, day.isoformat(), type(exc).__name__)
            )
            continue
        if record is None:
            tally.pending += 1
        else:
            found.append(record)
    return found


def _settle_day(
    decisions_dir: Path,
    day: dt.date,
    found: list[SettlementRecord],
    replace: Callable[..., None],
    tally: _Tally,
) -> None:
    """Read the day's file once, then append what it does not hold, as one atomic rewrite."""
    try:
        existing_raw, existing = _read_existing(decisions_dir, day.isoformat())
        held = {record.key() for record in existing}
        new = [record for record in found if record.key() not in held]
        tally.already += len(found) - len(new)
        if new:
            data = existing_raw + "".join(record.to_line() for record in new).encode("utf-8")
            replace(
                decisions_dir / settlement_file_name(day),
                data,
                root=decisions_dir,
                mode=_FILE_MODE,
            )
            tally.appended += len(new)
    except Exception as exc:  # noqa: BLE001 - one day's file failing must not stop the others
        cause = type(exc).__name__
        tally.errors.extend(StationDayError(r.station, r.climate_day, cause) for r in found)


def run_settlement(
    *,
    venue: str,
    today: dt.date,
    decisions_dir: Path,
    catalog_base: Path,
    sites: Sequence[SettlementSite],
    offer: AlertOffer,
    basis_by_venue: Mapping[str, str] = VENUE_BASIS,
    read_day: _ReadDay = read_catalog_day,
    replace: Callable[..., None] = replace_atomic,
) -> SettlementRunResult:
    """Append every new settlement record for the trailing window, under the module lock."""
    basis = basis_by_venue.get(venue)
    if basis is None:
        raise UnknownVenueBasis(venue)
    tally = _Tally()
    with settlement_lock(decisions_dir):
        for day in scan_days(today):
            found = _collect_day(day, venue, basis, sites, catalog_base, read_day, tally)
            if found:
                _settle_day(decisions_dir, day, found, replace, tally)
    failed, undelivered = _deliver(offer, tally.errors)
    return SettlementRunResult(
        appended=tally.appended,
        already_present=tally.already,
        pending=tally.pending,
        errors=tuple(tally.errors),
        delivery_failed=failed,
        undelivered=undelivered,
    )
