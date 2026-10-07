"""F13 C1-R1: availability-only collector legs ``lav`` / ``mos`` / ``obs``.

Each leg records ONE first-seen row per (station, nominal run) in its own poll ledger and writes
nothing else (like the NBP leg): no raw store, no normalised rows. The rows feed
``scripts/analysis/c1_lag_evidence.py``.

* ``lav``: IEM LAV CSV, nominal = the hourly IEM run label (HH:00Z), five stations.
* ``mos``: IEM GFS MOS (MAV) CSV, nominal = model runtime (00/06/12/18Z), five stations.
* ``obs``: the live observation endpoint (api.weather.gov ``/stations/{icao}/observations``), one
  row per routine report (minute = the station's pinned routine minute, never SPECI), nominal =
  the report timestamp.

The IEM CSV and the observation API carry no usable Last-Modified, so availability is the first
poll that saw the row (``first_seen@host``), an upper bound by at most one poll interval (C1-R3).
A row first seen after ``late_after`` past nominal is flagged ``late`` (right-censored, F13-R21).

This module is pure orchestration over injected fetchers and the collector's ledger; it never
touches the network itself and imports nothing from ``breezy.runtime`` or ``breezy.exec``.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Final

import us_source_guards as guards

from breezy.ingest.http import TransportError
from breezy.ingest.us_source_availability import LagPrereg, Observation, available_at

__all__ = [
    "IEM_LEGS",
    "OBS_FETCH_LIMIT",
    "OBS_LATE_AFTER_NS",
    "OBS_ROUTINE_MINUTE",
    "OBS_SOURCE_KEY",
    "STATIONS",
    "FetchedPayload",
    "IemLeg",
    "LegOutcome",
    "NotPublishedError",
    "iem_csv_has_run",
    "iem_cycle",
    "obs_cycle",
]

_NS: Final[int] = 1_000_000_000
_MINUTE_NS: Final[int] = 60 * _NS
_HOUR_NS: Final[int] = 3600 * _NS
_AVAILABILITY_VERSION: Final[str] = "v1"
_HOST_OBS: Final[str] = "nws"

STATIONS: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")
#: Pinned routine METAR minute per station (prereg obs_routine_minute_by_station).
OBS_ROUTINE_MINUTE: Final[dict[str, int]] = {
    "KLAX": 53,
    "KMDW": 53,
    "KMIA": 53,
    "KNYC": 51,
    "KSFO": 56,
}
OBS_SOURCE_KEY: Final[str] = "us-obs-avail"
#: Same order of size as the live actor's steady-state fetch; the API returns newest-first.
OBS_FETCH_LIMIT: Final[int] = 12
OBS_LATE_AFTER_NS: Final[int] = _HOUR_NS
_OBS_SPACING_S: Final[float] = 1.0  # S2: never two requests for one host within a second


class NotPublishedError(Exception):
    """The product is not there yet (404 / no row): a routine miss, never data."""


@dataclass(frozen=True, slots=True)
class FetchedPayload:
    body: bytes
    fetched_at_ns: int
    last_modified: str | None
    host_tag: str


@dataclass(frozen=True, slots=True)
class IemLeg:
    """One IEM CSV leg: where its runs sit and when polling for a run starts and stops."""

    cli: str
    source_key: str
    availability_source: str
    step_ns: int
    start_offset_ns: int
    late_after_ns: int

    @property
    def lookback_ns(self) -> int:
        return self.late_after_ns + 30 * _MINUTE_NS


IEM_LEGS: Final[dict[str, IemLeg]] = {
    "lav": IemLeg("lav", "us-lav-iem-avail", "LAV_IEM", _HOUR_NS, 10 * _MINUTE_NS, 2 * _HOUR_NS),
    "mos": IemLeg(
        "mos", "us-mos-gfs-avail", "GFS_MOS_IEM", 6 * _HOUR_NS, 2 * _HOUR_NS, 8 * _HOUR_NS
    ),
}


@dataclass(slots=True)
class LegOutcome:
    collected: int = 0
    misses: int = 0
    errors: int = 0
    refused: int = 0
    deadline: bool = False


def _log(message: str) -> None:
    print(f"us-source-collector: {message}", file=sys.stderr)


def _prereg(source: str, late_after_ns: int) -> LagPrereg:
    return LagPrereg(sanity_floors_ns={source: 0}, conservative_lags_ns={source: late_after_ns})


def _seen_event(
    col: Any,
    *,
    availability_source: str,
    station: str,
    run_ts_ns: int,
    payload: FetchedPayload,
    late_after_ns: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    miss = col.ledger.last_miss_ns(col.source_key, station, run_ts_ns)
    ts, basis, miss_ts, clamped = available_at(
        availability_source,
        _AVAILABILITY_VERSION,
        run_ts_ns,
        Observation(
            first_seen_ns=payload.fetched_at_ns, last_miss_ns=miss, host_tag=payload.host_tag
        ),
        prereg=_prereg(availability_source, late_after_ns),
    )
    return {
        "kind": "seen",
        "station": station,
        "run_ts_ns": run_ts_ns,
        "sha256": hashlib.sha256(payload.body).hexdigest(),
        "fetched_at_ns": payload.fetched_at_ns,
        "first_seen_ns": payload.fetched_at_ns,
        "last_modified": None,
        "host_tag": payload.host_tag,
        "wmo_header_ns": None,
        "available_ts_ns": ts,
        "basis": basis,
        "miss_ts_ns": miss_ts,
        "clamped_to_miss": clamped,
        "late": payload.fetched_at_ns > run_ts_ns + late_after_ns,
        "ntp_offset_ns": col.ntp_offset,
        **(extra or {}),
    }


# -- IEM CSV legs (lav, mos) -----------------------------------------------------------------


def _run_label(run_ts_ns: int) -> str:
    return dt.datetime.fromtimestamp(run_ts_ns // _NS, dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


def iem_csv_has_run(text: str, station: str, run_ts_ns: int) -> bool:
    """True when the CSV carries a row for ``station`` at exactly this ``runtime``.

    A header without the ``runtime`` / ``station`` columns is a malformed payload (ValueError),
    an empty body or a header-only body is simply "not there yet".
    """
    if not text.strip():
        return False
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {"runtime", "station"} <= set(reader.fieldnames):
        raise ValueError("IEM CSV has no runtime/station columns")
    label = _run_label(run_ts_ns)
    return any(
        (row.get("runtime") or "").strip() == label
        and (row.get("station") or "").strip() == station
        for row in reader
    )


def pending_runs(leg: IemLeg, now_ns: int) -> Iterator[int]:
    """Nominal runs whose polling window is open at ``now_ns``, newest first."""
    newest = (now_ns - leg.start_offset_ns) // leg.step_ns * leg.step_ns
    run = newest
    while run > now_ns - leg.lookback_ns:
        yield run
        run -= leg.step_ns


def _over_budget(col: Any, cli: str, start_ns: int) -> bool:
    now = col.ctx.clock()
    return guards.worked_seconds_outside_window(start_ns, now) > guards.MAX_WORK_SECONDS[
        cli
    ] or not guards.attempt_allowed(now)


def iem_cycle(col: Any, leg: IemLeg, fetch: Callable[[str, int], FetchedPayload]) -> LegOutcome:
    """One pass: every (run, station) in an open window with no ``seen`` row is polled once."""
    out = LegOutcome()
    start = col.ctx.clock()
    for run in pending_runs(leg, start):
        for station in STATIONS:
            if col.ledger.find_seen(leg.source_key, station, run) is not None:
                continue
            if _over_budget(col, leg.cli, start):
                out.deadline = True
                return out
            _poll_one(col, leg, fetch, station, run, out)
    return out


def _poll_one(
    col: Any,
    leg: IemLeg,
    fetch: Callable[[str, int], FetchedPayload],
    station: str,
    run: int,
    out: LegOutcome,
) -> None:
    now = col.ctx.clock()
    try:
        payload = fetch(station, run)
    except NotPublishedError:
        col.record_miss(station, run, now)
        out.misses += 1
        return
    except (TransportError, OSError) as exc:
        _log(f"{leg.cli} {station} fetch failed: {type(exc).__name__}")
        out.errors += 1
        return
    except ValueError as exc:
        col.refuse_payload(station, run, b"", exc)
        out.refused += 1
        return
    event = _seen_event(
        col,
        availability_source=leg.availability_source,
        station=station,
        run_ts_ns=run,
        payload=payload,
        late_after_ns=leg.late_after_ns,
    )
    col.ledger.record(leg.source_key, event)
    out.collected += 1


# -- routine observations (obs) --------------------------------------------------------------


def _reports(body: bytes) -> list[tuple[int, str]]:
    """``(timestamp_ns, rawMessage)`` of every feature; ValueError on a non-feature payload."""
    payload = json.loads(body.decode("utf-8"))
    features = payload["features"]
    if not isinstance(features, list):
        raise TypeError("features is not a list")
    found: list[tuple[int, str]] = []
    for feature in features:
        props = feature["properties"]
        stamp = dt.datetime.fromisoformat(props["timestamp"])
        if stamp.tzinfo is None:
            raise ValueError("observation timestamp has no timezone")
        found.append((int(stamp.timestamp()) * _NS, str(props.get("rawMessage") or "")))
    return found


def _is_routine(station: str, report_ns: int, raw: str) -> bool:
    minute = (report_ns // _MINUTE_NS) % 60
    return minute == OBS_ROUTINE_MINUTE[station] and not raw.lstrip().startswith("SPECI")


def obs_cycle(col: Any, fetch: Callable[[str], FetchedPayload]) -> LegOutcome:
    """One pass over the five stations; a routine report is recorded once, at first sight."""
    out = LegOutcome()
    start = col.ctx.clock()
    for index, station in enumerate(STATIONS):
        if _over_budget(col, "obs", start):
            out.deadline = True
            return out
        if index:
            col.ctx.sleep(_OBS_SPACING_S)
        try:
            payload = fetch(station)
        except (TransportError, OSError) as exc:
            _log(f"obs {station} fetch failed: {type(exc).__name__}")
            out.errors += 1
            continue
        _record_reports(col, station, payload, out)
    return out


def _record_reports(col: Any, station: str, payload: FetchedPayload, out: LegOutcome) -> None:
    try:
        reports = _reports(payload.body)
    except (ValueError, KeyError, TypeError) as exc:
        col.refuse_payload(station, None, payload.body, exc)
        out.refused += 1
        return
    for report_ns, raw in reports:
        if not _is_routine(station, report_ns, raw):
            continue
        if col.ledger.find_seen(OBS_SOURCE_KEY, station, report_ns) is not None:
            continue
        event = _seen_event(
            col,
            availability_source="NWS_OBS",
            station=station,
            run_ts_ns=report_ns,
            payload=payload,
            late_after_ns=OBS_LATE_AFTER_NS,
            extra={"routine": True},
        )
        col.ledger.record(OBS_SOURCE_KEY, event)
        out.collected += 1
