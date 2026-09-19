"""Parse the collective NBM/NBS text bulletin into `ForecastPoint` records.

Grammar, VERIFIED 2026-09-19 against a live 28 MB body captured by
``scripts/venue/nbm_nomads_discovery_probe.py`` (EVIDENCE ONLY -- never read
at runtime; this module opens nothing). One bulletin holds every station as a
block::

     KMIA    NBM V5.0 NBS GUIDANCE    9/19/2026  1200 UTC
     DT /SEP  19/SEP  20                /SEP  21 ...
     UTC  18 21 00 03 06 09 12 15 18 21 00 03 06 ...
     FHR  06 09 12 15 18 21 24 27 30 33 36 39 42 ...
     TXN        84          76          84       ...

Fixed width: the row LABEL occupies columns 0-3 and every data column is
exactly three characters starting at index 5. A value therefore belongs to
the projection its column names -- which is why this parser cross-checks the
``UTC`` row against the ``FHR`` row rather than trusting either alone.

`TXN` is a period aggregate. The FC-0a live census measured its occupancy at
exactly two projection hours -- 00Z (daily MAX) and 12Z (daily MIN), 0/14,720
rows anywhere else -- so a `TXN` value at any other hour is upstream drift and
raises. The period LENGTH is still UNVERIFIED, so a record's validity window
is the period END INSTANT (``valid_start_ns == valid_end_ns``): asserting a
length nobody measured would be an invention, and an instantaneous window is
the honest encoding of "this is the value at the moment the period closes".

ONE body, four stations. The live bulletin measured 29,720,949 bytes
(~28.35 MiB) on 2026-09-19 and carries every NBM station, while this bot
trades four. Station blocks are therefore located as SPANS and only the
requested ones are sliced and split -- peak memory scales with the stations
asked for, not with the body. This parser runs inside the live trade node,
where a per-cycle several-hundred-megabyte spike is an availability risk
against a unit ``MemoryMax``, not merely waste. The selection changes memory
shape ONLY: every drift check below still runs, per column, on every block
that is parsed.

Drift RAISES; it never coerces. A missing row, a reshaped column grid, a
changed header token or a `TXN` outside the measured hours is a bulletin this
parser does not understand, and a confidently wrong forecast is worse than no
forecast (L-17). ABSENCES, by contrast, are DATA and are recorded by name:
``not_published`` (the column is blank), ``sentinel`` (a published
missing-value code, mapped through the one home of that rule,
`forecast_value_or_none`), ``parse_failure`` (a token this parser could not
read). None of the three is ever turned into a number.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from typing import Final

from breezy.domain.forecast_point import ForecastPoint, forecast_value_or_none

__all__ = [
    "NBM_NBS_MODEL",
    "TXN_PERIOD_END_UTC_HOURS",
    "TXN_VARIABLE",
    "NbsBulletinDriftError",
    "parse_nbs_bulletin",
]

NBM_NBS_MODEL: Final[str] = "NBM_NBS"
TXN_VARIABLE: Final[str] = "TXN"

#: FC-0a live census (``docs/evidence/FC_0a_TXN_OCCUPANCY_2026-09-19.md``):
#: 00Z is the daily MAX period end, 12Z the daily MIN. Nothing else.
TXN_PERIOD_END_UTC_HOURS: Final[tuple[int, ...]] = (0, 12)

_NS_PER_SECOND: Final[int] = 1_000_000_000
_SECONDS_PER_HOUR: Final[int] = 3_600

#: Column geometry (see the module docstring). Measured, not assumed.
_LABEL_WIDTH: Final[int] = 4
_COLUMN_START: Final[int] = 5
_COLUMN_WIDTH: Final[int] = 3

#: The per-station header. ``V\d+\.\d+`` generalises ONLY the version number,
#: which is the one field expected to change across NBM releases; every
#: surrounding token is exactly what the live bulletin carried. The station
#: field is not assumed to be an ICAO: the first block of the real capture was
#: the numeric site ``086092``.
_STATION_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ ]?(?P<station>[A-Z0-9]{4,6})\s+NBM\s+V(?P<version>\d+\.\d+)\s+NBS\s+GUIDANCE"
    r"\s+(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\s+(?P<cycle>\d{4})\s+UTC",
    re.MULTILINE,
)


class NbsBulletinDriftError(ValueError):
    """The bulletin does not have the shape this parser verified. Never coerced."""


def _row_label(line: str) -> str:
    return line[:_LABEL_WIDTH].strip()


def _cell(line: str, index: int) -> str:
    start = _COLUMN_START + index * _COLUMN_WIDTH
    return line[start : start + _COLUMN_WIDTH].strip()


def _column_count(line: str) -> int:
    """The number of COMPLETE three-character columns in a grid row.

    ``rstrip`` first: the live bulletin's ``UTC``/``FHR`` rows carry one
    trailing space, and counting it as a 24th (empty) column would report a
    grid the row does not have.
    """
    return max(0, (len(line.rstrip()) - _COLUMN_START) // _COLUMN_WIDTH)


def _required_row(block_lines: list[str], label: str, station: str) -> str:
    for line in block_lines:
        if _row_label(line) == label:
            return line
    raise NbsBulletinDriftError(
        f"{station}: the NBS block carries no {label} row; the bulletin layout "
        f"changed and is refused rather than parsed on a guess"
    )


def _int_cells(line: str, count: int, *, label: str, station: str) -> list[int]:
    values: list[int] = []
    for index in range(count):
        token = _cell(line, index)
        if not token.isdigit():
            raise NbsBulletinDriftError(
                f"{station}: {label} column {index} is {token!r}, not a projection "
                f"number; the column grid changed shape"
            )
        values.append(int(token))
    return values


def _cycle_runtime_ns(match: re.Match[str]) -> int:
    cycle = match.group("cycle")
    hour, minute = int(cycle[:2]), int(cycle[2:])
    instant = dt.datetime(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        hour,
        minute,
        tzinfo=dt.UTC,
    )
    return int(instant.timestamp()) * _NS_PER_SECOND


def _block_lines(text: str, start: int, end: int) -> list[str]:
    """Materialise ONE station block's lines. The only slice-and-split in this module.

    Factored out so the memory bound is assertable: a test counts calls and
    pins one call per REQUESTED station, never one per block in the body.
    """
    return text[start:end].splitlines()


def _station_block_spans(text: str) -> dict[str, tuple[re.Match[str], int, int]]:
    """Locate every station block as a SPAN. Nothing is sliced or split here.

    The live bulletin measured 29,720,949 bytes and carries every NBM station,
    so materialising a line list for each block before choosing the handful
    this bot trades made peak memory a multiple of the body -- inside the live
    trade node, against a unit ``MemoryMax``. ``finditer`` walks the text once
    and the returned matches hold offsets into it, not copies, so the caller
    can split only the blocks it actually wants.
    """
    matches = list(_STATION_HEADER_RE.finditer(text))
    if not matches:
        raise NbsBulletinDriftError(
            "no NBS station block was found in the bulletin; either the body is "
            "not an NBS text product or its per-station header changed"
        )
    spans: dict[str, tuple[re.Match[str], int, int]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        spans[match.group("station")] = (match, match.start(), end)
    return spans


def _absence_from_token(token: str) -> tuple[float | None, str | None]:
    """Return ``(value_f, absence_reason)`` for one TXN cell. Never invents a value."""
    if not token:
        return None, "not_published"
    try:
        raw = float(int(token))
    except ValueError:
        return None, "parse_failure"
    value = forecast_value_or_none(raw)
    if value is None:
        return None, "sentinel"
    return value, None


def parse_nbs_bulletin(
    text: str,
    *,
    stations: frozenset[str],
    measured_publication_lag_ns: int,
    ingested_at_ns: int,
    issuance_seq: int = 0,
) -> tuple[tuple[ForecastPoint, ...], Counter[str]]:
    """Return the TXN records for `stations`, plus a per-reason drop count.

    `measured_publication_lag_ns` is the caller's MEASURED delay between the
    cycle instant and publication -- never a default and never a clock read
    here. The vintage is derived from it exactly once, by `ForecastPoint`.

    A requested station that has no block in this bulletin is COUNTED
    (``station_block_missing``) and never silently omitted.
    """
    spans = _station_block_spans(text)
    drops: Counter[str] = Counter()
    points: list[ForecastPoint] = []

    for station in sorted(stations):
        span = spans.get(station)
        if span is None:
            drops["station_block_missing"] += 1
            continue
        match, start, end = span
        # Split HERE, after the station filter: see `_station_block_spans`.
        points.extend(
            _station_points(
                station,
                match,
                _block_lines(text, start, end),
                measured_publication_lag_ns=measured_publication_lag_ns,
                ingested_at_ns=ingested_at_ns,
                issuance_seq=issuance_seq,
            )
        )

    return tuple(points), drops


def _station_points(
    station: str,
    match: re.Match[str],
    lines: list[str],
    *,
    measured_publication_lag_ns: int,
    ingested_at_ns: int,
    issuance_seq: int,
) -> list[ForecastPoint]:
    cycle_runtime_ns = _cycle_runtime_ns(match)
    model_version = match.group("version")

    utc_line = _required_row(lines, "UTC", station)
    fhr_line = _required_row(lines, "FHR", station)
    txn_line = _required_row(lines, TXN_VARIABLE, station)

    utc_columns = _column_count(utc_line)
    fhr_columns = _column_count(fhr_line)
    if utc_columns != fhr_columns or utc_columns == 0:
        raise NbsBulletinDriftError(
            f"{station}: the UTC row has {utc_columns} column(s) and the FHR row "
            f"{fhr_columns}; the two must describe the same grid"
        )

    hours = _int_cells(utc_line, utc_columns, label="UTC", station=station)
    projections = _int_cells(fhr_line, fhr_columns, label="FHR", station=station)
    cycle_hour = cycle_runtime_ns // (_SECONDS_PER_HOUR * _NS_PER_SECOND) % 24

    points: list[ForecastPoint] = []
    for index, (hour, projection) in enumerate(zip(hours, projections, strict=True)):
        derived = (cycle_hour + projection) % 24
        if derived != hour:
            raise NbsBulletinDriftError(
                f"{station}: column {index} is labelled {hour:02d}Z but its FHR "
                f"{projection} off the {cycle_hour:02d}Z cycle disagrees "
                f"({derived:02d}Z); the column grid cannot be trusted"
            )
        token = _cell(txn_line, index)
        if hour not in TXN_PERIOD_END_UTC_HOURS:
            if token:
                raise NbsBulletinDriftError(
                    f"{station}: a TXN value {token!r} appears at the {hour:02d}Z "
                    f"projection; the measured occupancy is {TXN_PERIOD_END_UTC_HOURS} "
                    f"only, so this bulletin's period shape changed"
                )
            continue
        value, absence_reason = _absence_from_token(token)
        period_end_ns = cycle_runtime_ns + projection * _SECONDS_PER_HOUR * _NS_PER_SECOND
        points.append(
            ForecastPoint(
                station=station,
                model=NBM_NBS_MODEL,
                model_version=model_version,
                variable=TXN_VARIABLE,
                cycle_runtime_ns=cycle_runtime_ns,
                # The period END instant; the LENGTH is still UNVERIFIED.
                valid_start_ns=period_end_ns,
                valid_end_ns=period_end_ns,
                value_f=value,
                issuance_seq=issuance_seq,
                measured_publication_lag_ns=measured_publication_lag_ns,
                available_at_ns=cycle_runtime_ns + measured_publication_lag_ns,
                ingested_at_ns=ingested_at_ns,
                absence_reason=absence_reason,
            )
        )
    return points
