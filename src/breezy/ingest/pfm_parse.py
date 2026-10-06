"""Parse an NWS Point Forecast Matrix (PFM) text product (F13-C1, A0-R2).

PURE module: no network, no clock access, no `nautilus_trader` import, no global
state.

* The WMO header (e.g. `FOUS51 KOKX 051901`, DDHHMM UTC) is the exact issuance
  time. It carries no month/year, so the caller supplies `reference_time` (the
  retrieval or archive-entry instant) and the latest instant at or before it with
  that day/hour/minute, no older than `max_age`, is taken.
* The station point is selected by `(WFO, point_name)` from the closed
  five-entry :data:`PFM_POINT_MAP`. The zone code (`NYZ072`) is recorded and
  NEVER used as a key: zone codes are shared between stations (ILZ104 is both
  O'Hare and Midway). KMIA's point is inferred (A0-R2) and confirmed by lat/lon
  in B0.
* An unmapped or ambiguous (duplicate) point is refused. Every malformed row
  refuses the whole product (H3); nothing is skipped.

`PfmParseError` is a local refusal class: not a `TransportError`, `CliParseError`
or `CliSanityError` (R18).

The fixture under `tests/fixtures/us_sources/` is SYNTHETIC: the MAX-row column
layout (one value per forecast day, space separated) is an assumption pending a
real first-capture sample, so `max_f` is returned in column order only.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

MAX_LINES: Final = 5000
MAX_LINE_BYTES: Final = 256
MAX_FIELDS_PER_ROW: Final = 64
DEFAULT_MAX_AGE: Final = dt.timedelta(days=2)
TEMP_MIN_F: Final = -80
TEMP_MAX_F: Final = 140

_HEADER_SCAN_LINES: Final = 10
_WMO_RE: Final = re.compile(r"^[A-Z]{4}\d{2} ([A-Z]{4}) (\d{2})(\d{2})(\d{2})$")
_ZONE_RE: Final = re.compile(r"^([A-Z]{2}Z\d{3})(?:[->]\d{3})*-\d{6}-$")
_LATLON_RE: Final = re.compile(r"^\d{1,2}\.\d{2}[NS] \d{1,3}\.\d{2}[EW]\b")
_INT_RE: Final = re.compile(r"^-?\d{1,4}$")


@dataclass(frozen=True, slots=True)
class _Point:
    wfo: str
    point_name: str


#: station -> (WFO, point name); the ONLY key is (WFO, point_name) (A0-R2).
PFM_POINT_MAP: Final = MappingProxyType(
    {
        "KNYC": _Point("OKX", "Central Park-New York NY"),
        "KLAX": _Point("LOX", "Los Angeles Airport CA"),
        "KMDW": _Point("LOT", "Chicago Midway Airport-Cook IL"),
        "KSFO": _Point("MTR", "San Francisco Airport-San Mateo CA"),
        "KMIA": _Point("MFL", "Miami-Miami Dade FL"),
    }
)


class PfmParseError(ValueError):
    """The PFM input is not a product this parser may trust; the run is refused."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"PFM parse refused: {reason}" + (f" ({detail})" if detail else ""))


@dataclass(frozen=True, slots=True)
class PfmPoint:
    """The MAX-temperature row of one mapped station point."""

    station: str
    wfo: str
    point_name: str
    zone_code: str
    issued_at: dt.datetime
    max_f: tuple[int, ...]


def resolve_pfm_station(wfo: str, point_name: str) -> str:
    """Return the station for `(wfo, point_name)`, or refuse an unmapped point."""
    for station, point in PFM_POINT_MAP.items():
        if point.wfo == wfo and point.point_name == point_name:
            return station
    raise PfmParseError("unmapped_point", f"{wfo} / {point_name!r}")


def _decode_lines(raw: bytes, max_lines: int) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PfmParseError("non_utf8", str(exc)) from exc
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    if len(lines) > max_lines:
        raise PfmParseError("too_many_lines", f"over {max_lines}")
    for ln in lines:
        if len(ln.encode("utf-8")) > MAX_LINE_BYTES:
            raise PfmParseError("line_too_long", f"over {MAX_LINE_BYTES} bytes")
    return lines


def _month_back(year: int, month: int, back: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) - back
    return index // 12, index % 12 + 1


def _issuance(
    lines: list[str], reference: dt.datetime, max_age: dt.timedelta
) -> tuple[str, dt.datetime]:
    if reference.tzinfo is None:
        raise PfmParseError("naive_reference_time")
    hits = [m for ln in lines[:_HEADER_SCAN_LINES] if (m := _WMO_RE.match(ln.strip()))]
    if len(hits) != 1:
        raise PfmParseError(
            "wmo_header", f"{len(hits)} headers in first {_HEADER_SCAN_LINES} lines"
        )
    cccc, day, hour, minute = hits[0].groups()
    ref = reference.astimezone(dt.UTC)
    best: dt.datetime | None = None
    for back in (0, 1):
        year, month = _month_back(ref.year, ref.month, back)
        try:
            cand = dt.datetime(year, month, int(day), int(hour), int(minute), tzinfo=dt.UTC)
        except ValueError:
            continue
        if cand <= ref and (best is None or cand > best):
            best = cand
    if best is None or ref - best > max_age:
        raise PfmParseError("wmo_time_unresolvable", f"{day}{hour}{minute} vs {ref.isoformat()}")
    return cccc[1:], best


def _max_row(section: list[str]) -> tuple[int, ...]:
    rows = [ln.split() for ln in section if ln.split()[:1] == ["MAX"]]
    if len(rows) != 1:
        raise PfmParseError("max_row", f"{len(rows)} MAX rows in point section")
    tokens = rows[0][1:]
    if not tokens or len(tokens) > MAX_FIELDS_PER_ROW:
        raise PfmParseError("max_row_fields", f"{len(tokens)} fields")
    values: list[int] = []
    for token in tokens:
        if not _INT_RE.match(token):
            raise PfmParseError("bad_token", f"MAX: {token!r}")
        value = int(token)
        if not TEMP_MIN_F <= value <= TEMP_MAX_F:
            raise PfmParseError("max_out_of_range", str(value))
        values.append(value)
    return tuple(values)


def _sections(lines: list[str]) -> list[tuple[str, str, list[str]]]:
    """(zone_code, point_name, body lines) for each zone-headed section."""
    found: list[tuple[str, str, list[str]]] = []
    i = 0
    while i < len(lines):
        zone = _ZONE_RE.match(lines[i].strip())
        if zone is None:
            i += 1
            continue
        if i + 2 >= len(lines) or not _LATLON_RE.match(lines[i + 2].strip()):
            raise PfmParseError("bad_point_header", lines[i].strip())
        name = lines[i + 1].strip()
        j = i + 3
        while j < len(lines) and lines[j].strip() != "$$" and not _ZONE_RE.match(lines[j].strip()):
            j += 1
        found.append((zone.group(1), name, lines[i + 3 : j]))
        i = j
    return found


def parse_pfm_product(
    raw: bytes,
    *,
    station: str,
    reference_time: dt.datetime,
    max_lines: int = MAX_LINES,
    max_age: dt.timedelta = DEFAULT_MAX_AGE,
) -> PfmPoint:
    """Parse `raw` and return `station`'s point MAX row; refuse anything unexpected."""
    target = PFM_POINT_MAP.get(station)
    if target is None:
        raise PfmParseError("unmapped_station", station)
    lines = _decode_lines(raw, max_lines)
    wfo, issued_at = _issuance(lines, reference_time, max_age)
    if wfo != target.wfo:
        raise PfmParseError("wfo_mismatch", f"{wfo} != {target.wfo} for {station}")
    matches = [s for s in _sections(lines) if resolve_or_none(wfo, s[1]) == station]
    if len(matches) != 1:
        raise PfmParseError("point_not_unique", f"{target.point_name!r}: {len(matches)} sections")
    zone, name, body = matches[0]
    return PfmPoint(
        station=station,
        wfo=wfo,
        point_name=name,
        zone_code=zone,
        issued_at=issued_at,
        max_f=_max_row(body),
    )


def resolve_or_none(wfo: str, point_name: str) -> str | None:
    """`resolve_pfm_station`, but None instead of a refusal (for scanning sections)."""
    try:
        return resolve_pfm_station(wfo, point_name)
    except PfmParseError:
        return None
