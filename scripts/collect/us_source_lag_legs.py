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

from breezy.ingest.http import ForbiddenError, RateLimitedError, ServerError, TransportError
from breezy.ingest.us_source_availability import LagPrereg, Observation, available_at

__all__ = [
    "BACKOFF_KINDS",
    "BACKOFF_NS",
    "IEM_LEGS",
    "OBS_BACKOFF_NS",
    "OBS_FETCH_LIMIT",
    "OBS_LATE_AFTER_NS",
    "OBS_ROUTINE_MINUTE",
    "OBS_SOURCE_KEY",
    "OBS_TRANSPORT_FAILURES_TO_BACKOFF",
    "REFUSAL_ALERT_REPEAT_NS",
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
#: A routine report is polled for only in [routine minute, +35 min]; one first seen after that is
#: right-censored (F13-R21) and recorded at the next firing that fetches it.
OBS_LATE_AFTER_NS: Final[int] = 35 * _MINUTE_NS
#: Firings land up to AccuracySec past the nominal slot; the window end tolerates that.
_OBS_WINDOW_SLACK_NS: Final[int] = 30 * _NS
#: After a 429 / 5xx / 403 from a leg's host the leg stays silent this long.
BACKOFF_NS: Final[int] = 30 * _MINUTE_NS
OBS_BACKOFF_NS: Final[int] = BACKOFF_NS
#: A repeated shape refusal alerts at most this often per leg (each is still ledgered).
REFUSAL_ALERT_REPEAT_NS: Final[int] = 6 * _HOUR_NS
#: The errors that stop a pass and start the back-off (IEM and the observation host alike).
BACKOFF_KINDS: Final[tuple[type[Exception], ...]] = (RateLimitedError, ServerError, ForbiddenError)
#: Consecutive firings in which every fetch failed (timeout / OSError) before the obs leg backs off.
OBS_TRANSPORT_FAILURES_TO_BACKOFF: Final[int] = 3
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
    an empty body or a header-only body is simply "not there yet". IEM prints a runtime column
    whose rows are all 00:00:00 as a bare date, so a 00Z run also matches ``YYYY-MM-DD``.
    """
    if not text.strip():
        return False
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {"runtime", "station"} <= set(reader.fieldnames):
        raise ValueError("IEM CSV has no runtime/station columns")
    label = _run_label(run_ts_ns)
    labels = {label, label[:10]} if label.endswith(" 00:00:00") else {label}
    return any(
        (row.get("runtime") or "").strip() in labels
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
    if start < _backoff_until(col, leg.source_key):
        _log(f"{leg.cli} is backing off after a rate-limit or server error; skipping this firing")
        return out
    for run in pending_runs(leg, start):
        for station in STATIONS:
            if col.ledger.find_seen(leg.source_key, station, run) is not None:
                continue
            if _over_budget(col, leg.cli, start):
                out.deadline = True
                return out
            if not _poll_one(col, leg, fetch, station, run, out):
                return out  # back-off entered: the pass stops
    return out


def _poll_one(
    col: Any,
    leg: IemLeg,
    fetch: Callable[[str, int], FetchedPayload],
    station: str,
    run: int,
    out: LegOutcome,
) -> bool:
    """Poll one (station, run); False when a back-off was entered and the pass must stop."""
    now = col.ctx.clock()
    try:
        payload = fetch(station, run)
    except NotPublishedError:
        col.record_miss(station, run, now)
        out.misses += 1
        return True
    except BACKOFF_KINDS as exc:
        _enter_backoff(col, leg.source_key, leg.cli, station, exc, col.ctx.clock(), out)
        return False
    except (TransportError, OSError) as exc:
        _log(f"{leg.cli} {station} fetch failed: {type(exc).__name__}")
        out.errors += 1
        return True
    except ValueError as exc:
        col.refuse_payload(station, run, b"", exc)
        out.refused += 1
        return True
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
    return True


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


def obs_window_start(station: str, now_ns: int) -> int | None:
    """The routine-report time whose polling window is open at ``now_ns``, else None."""
    hour = now_ns // _HOUR_NS * _HOUR_NS
    minute_ns = OBS_ROUTINE_MINUTE[station] * _MINUTE_NS
    start = max(c for c in (hour - _HOUR_NS + minute_ns, hour + minute_ns) if c <= now_ns)
    return start if now_ns - start <= OBS_LATE_AFTER_NS + _OBS_WINDOW_SLACK_NS else None


def _backoff_until(col: Any, source_key: str) -> int:
    stamps = [
        int(e["until_ns"]) for e in col.ledger.events(source_key) if e.get("kind") == "backoff"
    ]
    return max(stamps, default=0)


def _eligible(col: Any, now_ns: int) -> list[str]:
    """Stations whose report window is open and whose report is not yet seen."""
    found: list[str] = []
    for station in STATIONS:
        window = obs_window_start(station, now_ns)
        if window is not None and col.ledger.find_seen(OBS_SOURCE_KEY, station, window) is None:
            found.append(station)
    return found


def _enter_backoff(
    col: Any,
    source_key: str,
    cli: str,
    station: str,
    exc: Exception,
    now_ns: int,
    out: LegOutcome,
) -> None:
    until = now_ns + BACKOFF_NS
    col.ledger.record(
        source_key,
        {"kind": "backoff", "station": station, "fetched_at_ns": now_ns, "until_ns": until},
    )
    _log(f"{cli} {station} {type(exc).__name__}: backing off until {until}")
    col.ctx.alert("rate_limited", source_key, f"{station}: {type(exc).__name__}; backing off")
    out.errors += 1


def _transport_failure_streak(col: Any) -> int:
    """Consecutive all-failed obs firings recorded since the last success or back-off."""
    streak = 0
    for event in col.ledger.events(OBS_SOURCE_KEY):
        kind = event.get("kind")
        if kind == "transport_fail":
            streak += 1
        elif kind in ("transport_ok", "backoff"):
            streak = 0
    return streak


def _settle_firing(col: Any, now_ns: int, fetched: int, failed: int, out: LegOutcome) -> None:
    """Record the firing-level transport outcome; enough failed firings in a row back off."""
    if failed and not fetched:
        col.ledger.record(OBS_SOURCE_KEY, {"kind": "transport_fail", "fetched_at_ns": now_ns})
        if _transport_failure_streak(col) >= OBS_TRANSPORT_FAILURES_TO_BACKOFF:
            exc = TransportError("consecutive transport failures")
            _enter_backoff(col, OBS_SOURCE_KEY, "obs", "*", exc, col.ctx.clock(), out)
    elif fetched and _transport_failure_streak(col):
        col.ledger.record(OBS_SOURCE_KEY, {"kind": "transport_ok", "fetched_at_ns": now_ns})


def obs_cycle(col: Any, fetch: Callable[[str], FetchedPayload]) -> LegOutcome:
    """One pass over the stations whose report window is open (the host is shared with the live
    node, so no station is polled outside [routine minute, +35 min] or after its report is seen);
    a 429 / 5xx / 403 stops the pass and silences the leg for ``OBS_BACKOFF_NS``."""
    out = LegOutcome()
    start = col.ctx.clock()
    if start < _backoff_until(col, OBS_SOURCE_KEY):
        _log("obs is backing off after a rate-limit or server error; skipping this firing")
        return out
    fetched = failed = 0
    for index, station in enumerate(_eligible(col, start)):
        if _over_budget(col, "obs", start):
            out.deadline = True
            break
        if index:
            col.ctx.sleep(_OBS_SPACING_S)
        try:
            payload = fetch(station)
        except BACKOFF_KINDS as exc:
            _enter_backoff(col, OBS_SOURCE_KEY, "obs", station, exc, col.ctx.clock(), out)
            return out
        except (TransportError, OSError) as exc:
            _log(f"obs {station} fetch failed: {type(exc).__name__}")
            out.errors += 1
            failed += 1
            continue
        fetched += 1
        _record_reports(col, station, payload, out)
    _settle_firing(col, start, fetched, failed, out)
    return out


def _record_reports(col: Any, station: str, payload: FetchedPayload, out: LegOutcome) -> None:
    try:
        reports = _reports(payload.body)
    except (ValueError, KeyError, TypeError) as exc:
        col.refuse_payload(
            station, None, payload.body, exc, alert_repeat_ns=REFUSAL_ALERT_REPEAT_NS
        )
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
