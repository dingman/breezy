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

Pre-2022 LOT layout (real capture `pfm_lot_real_20210101.txt`): the `UTC 3hrly` row is printed
ABOVE the local `CST 3hrly` row and the extrema label is upper case (`MIN/MAX`, `MAX/MIN`); the
columns, the point names and the zone lines are the same. Both row orders are accepted.

An extrema cell that is the NWS missing marker `MM` (a real SFO block of 2022-08-24 prints it for
every cell) is skipped: that day has no MAX. A product left with no MAX at all is refused
(`no_max_values`); any other non-integer cell is still refused (`bad_extrema_cell`).

Layout VERIFIED against real captures of all five offices
(`tests/fixtures/us_sources/pfm_*_real_20261006.txt`). Each point block holds two
tables, a 3-hourly one and a 6-hourly one, each introduced by three header rows::

    Date           10/05/26      Tue 10/06/26            Wed 10/07/26            Thu
    EDT 3hrly     17 20 23 02 05 08 11 14 17 20 23 02 05 08 ...
    UTC 3hrly     21 00 03 06 09 12 15 18 21 00 03 06 09 12 ...

    Min/Max                      49          63          47          68          55

(`Max/Min` in the 6-hourly table). Columns are 2 characters wide, right-aligned, and
data rows are aligned to the header rows by character position, so a value is matched
to its column by END position. The MAX is the value under the UTC 00 column and the MIN
the value under UTC 12 (any value under another hour is a layout this parser does not
understand and refuses). The MAX's forecast day is the LOCAL date of its UTC 00 column
(20:00 EDT / 19:00 CDT / 17:00 PDT, so never past local midnight). Local dates come
from the first `Date` label (the first column's date; the second table's label has no
year, which is taken from the issuance) plus a rollover whenever the local hour
decreases; every printed date label is cross-checked against its column.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

MAX_RAW_BYTES: Final = 1024 * 1024
MAX_LINES: Final = 5000
MAX_LINE_BYTES: Final = 256
MAX_FIELDS_PER_ROW: Final = 64
DEFAULT_MAX_AGE: Final = dt.timedelta(days=2)
TEMP_MIN_F: Final = -80
TEMP_MAX_F: Final = 140

_HEADER_SCAN_LINES: Final = 10
_WMO_RE: Final = re.compile(r"^[A-Z]{4}\d{2} ([A-Z]{4}) (\d{2})(\d{2})(\d{2})$")
_ZONE_RE: Final = re.compile(r"^([A-Z]{2}Z\d{3})(?:[->]\d{3})*-\d{6}-$")
_LATLON_RE: Final = re.compile(r"^\d{1,2}\.\d{2}[NS]\s+\d{1,3}\.\d{2}[EW]\b")
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
    """The MAX temperatures of one mapped station point."""

    station: str
    wfo: str
    point_name: str
    zone_code: str
    issued_at: dt.datetime
    #: (forecast local date, MAX degrees F) in date order; see the module docstring.
    max_by_day: tuple[tuple[dt.date, int], ...]


_STATION_BY_POINT: Final = MappingProxyType(
    {(point.wfo, point.point_name): station for station, point in PFM_POINT_MAP.items()}
)


def resolve_pfm_station(wfo: str, point_name: str) -> str:
    """Return the station for `(wfo, point_name)`, or refuse an unmapped point."""
    try:
        return _STATION_BY_POINT[(wfo, point_name)]
    except KeyError:
        raise PfmParseError("unmapped_point", f"{wfo} / {point_name!r}") from None


def _decode_lines(raw: bytes, max_lines: int) -> list[str]:
    if len(raw) > MAX_RAW_BYTES:
        raise PfmParseError("raw_too_large", f"{len(raw)} > {MAX_RAW_BYTES} bytes")
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


_LABEL_WIDTH: Final = 14
_MAX_TABLES: Final = 4
_DATE_BEFORE: Final = dt.timedelta(days=2)
_DATE_AFTER: Final = dt.timedelta(days=10)
_MAX_UTC_HOUR: Final = 0
_MIN_UTC_HOUR: Final = 12
_DATE_LABEL_RE: Final = re.compile(r"(?:[A-Z][a-z]{2} )?(\d{2})/(\d{2})(?:/(\d{2}))?")
_LOCAL_ROW_RE: Final = re.compile(r"^(?!UTC )[A-Z]{3} [36]hrly\s")
_UTC_ROW_RE: Final = re.compile(r"^UTC [36]hrly\s")
_EXTREMA_RE: Final = re.compile(r"^(?:Min/Max|Max/Min)\s", re.IGNORECASE)
_EXTREMA_LABELS: Final = ("MIN/MAX", "MAX/MIN")
_MISSING_MARKER: Final = "MM"


@dataclass(frozen=True, slots=True)
class _Column:
    end: int
    local_hour: int
    utc_hour: int
    local_date: dt.date


def _hour_tokens(line: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"\S+", line[_LABEL_WIDTH:]):
        if not re.fullmatch(r"\d{2}", m.group()) or not 0 <= int(m.group()) <= 23:
            raise PfmParseError("bad_hour_token", m.group())
        out.append((_LABEL_WIDTH + m.end(), int(m.group())))
        if len(out) > MAX_FIELDS_PER_ROW:
            raise PfmParseError("too_many_fields", f"hour row over {MAX_FIELDS_PER_ROW}")
    return out


def _first_date(label: re.Match[str], anchor: dt.date) -> dt.date:
    """The first column's date. A yearless label takes the year (of anchor.year -1/0/+1)
    that lands nearest `anchor`: the previous table's last date, or the issuance date."""
    month, day, short_year = int(label.group(1)), int(label.group(2)), label.group(3)
    years = (
        [2000 + int(short_year)] if short_year else [anchor.year - 1, anchor.year, anchor.year + 1]
    )
    dates: list[dt.date] = []
    for year in years:
        try:
            dates.append(dt.date(year, month, day))
        except ValueError:
            continue
    if not dates:
        raise PfmParseError("bad_date_label", label.group())
    return min(dates, key=lambda d: abs((d - anchor).days))


def _columns(
    date_row: str,
    local_row: str,
    utc_row: str,
    anchor: dt.date,
    issued_at: dt.datetime,
    previous: _Column | None = None,
) -> list[_Column]:
    """The table's columns with local dates.

    The first table takes its first date from the first printed label. A later table CONTINUES
    from `previous`, the last column of the table before it: a block too narrow for any label
    (the Pacific 09Z-grid cycle opens its 6hrly table with a single Thu 23 PDT column) prints
    none, so the first printed label belongs to the NEXT day and cannot date column 0. Every
    printed label is still cross-checked against its column either way."""
    local, utc = _hour_tokens(local_row), _hour_tokens(utc_row)
    if not local or [e for e, _ in local] != [e for e, _ in utc]:
        raise PfmParseError("hour_rows_misaligned")
    labels = list(_DATE_LABEL_RE.finditer(date_row, len("Date")))
    if not labels:
        raise PfmParseError("no_date_label")
    if previous is None:
        date = _first_date(labels[0], anchor)
        previous_hour = -1
    else:
        date, previous_hour = previous.local_date, previous.local_hour
    columns: list[_Column] = []
    for (end, hour), (_, utc_hour) in zip(local, utc, strict=True):
        if hour <= previous_hour:
            date += dt.timedelta(days=1)
        previous_hour = hour
        columns.append(_Column(end, hour, utc_hour, date))
    lo = issued_at.date() - _DATE_BEFORE
    hi = issued_at.date() + _DATE_AFTER
    if any(not lo <= c.local_date <= hi for c in columns):
        raise PfmParseError(
            "date_out_of_range", f"{columns[0].local_date}..{columns[-1].local_date}"
        )
    for label in labels:
        column = next((c for c in columns if c.end > label.start()), None)
        month, day = int(label.group(1)), int(label.group(2))
        if column is None or (column.local_date.month, column.local_date.day) != (month, day):
            raise PfmParseError("date_label_mismatch", label.group())
    return columns


def _hour_rows(table: list[str]) -> tuple[str, str] | None:
    """`(local row, UTC row)` of a table, or None when the two rows after `Date` are not that pair.

    Today's products print the local row first; the pre-2022 LOT PFM prints the UTC row first
    (`UTC 3hrly` over `CST 3hrly`, both aligned to the same columns). Either order is accepted;
    two rows that are not one local and one UTC are not.
    """
    if len(table) < 3:
        return None
    first, second = table[1], table[2]
    if _LOCAL_ROW_RE.match(first) and _UTC_ROW_RE.match(second):
        return first, second
    if _UTC_ROW_RE.match(first) and _LOCAL_ROW_RE.match(second):
        return second, first
    return None


def _table_max(
    table: list[str], anchor: dt.date, issued_at: dt.datetime, previous: _Column | None
) -> tuple[dict[dt.date, int], _Column]:
    hour_rows = _hour_rows(table)
    if hour_rows is None:
        raise PfmParseError("table_header", table[0][:40])
    local_row, utc_row = hour_rows
    extrema = [ln for ln in table[3:] if _EXTREMA_RE.match(ln)]
    if len(extrema) != 1:
        raise PfmParseError("extrema_row", f"{len(extrema)} Min/Max rows in table")
    ordered = _columns(table[0], local_row, utc_row, anchor, issued_at, previous)
    columns = {c.end: c for c in ordered}
    if extrema[0][:_LABEL_WIDTH].strip().upper() not in _EXTREMA_LABELS:
        raise PfmParseError("extrema_label")
    found: dict[dt.date, int] = {}
    for count, m in enumerate(re.finditer(r"\S+", extrema[0][_LABEL_WIDTH:]), start=1):
        if count > MAX_FIELDS_PER_ROW:
            raise PfmParseError("too_many_fields", f"extrema row over {MAX_FIELDS_PER_ROW}")
        end = _LABEL_WIDTH + m.end()
        if m.group() == _MISSING_MARKER and end in columns:
            continue  # the NWS missing-data marker: that extremum is simply not forecast
        if not _INT_RE.match(m.group()) or end not in columns:
            raise PfmParseError("bad_extrema_cell", m.group())
        value = int(m.group())
        if not TEMP_MIN_F <= value <= TEMP_MAX_F:
            raise PfmParseError("extrema_out_of_range", m.group())
        column = columns[end]
        if column.utc_hour == _MAX_UTC_HOUR:
            found[column.local_date] = value
        elif column.utc_hour != _MIN_UTC_HOUR:
            raise PfmParseError("extrema_under_unexpected_hour", str(column.utc_hour))
    return found, ordered[-1]


def _max_by_day(body: list[str], issued_at: dt.datetime) -> tuple[tuple[dt.date, int], ...]:
    starts = [i for i, ln in enumerate(body) if ln.startswith("Date ")]
    if not starts or len(starts) > _MAX_TABLES:
        raise PfmParseError("tables", f"{len(starts)} tables in point block")
    merged: dict[dt.date, int] = {}
    last: _Column | None = None
    for begin, end in zip(starts, [*starts[1:], len(body)], strict=True):
        found, last = _table_max(body[begin:end], issued_at.date(), issued_at, last)
        for date, value in found.items():
            if date in merged:
                raise PfmParseError("duplicate_day", date.isoformat())
            merged[date] = value
    if not merged:  # e.g. a point block whose every extremum is MM
        raise PfmParseError("no_max_values", "no MAX under any UTC 00 column")
    return tuple(sorted(merged.items()))


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
    matches = [s for s in _sections(lines) if _STATION_BY_POINT.get((wfo, s[1])) == station]
    if len(matches) != 1:
        raise PfmParseError("point_not_unique", f"{target.point_name!r}: {len(matches)} sections")
    zone, name, body = matches[0]
    return PfmPoint(
        station=station,
        wfo=wfo,
        point_name=name,
        zone_code=zone,
        issued_at=issued_at,
        max_by_day=_max_by_day(body, issued_at),
    )
