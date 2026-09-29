"""Parse the NBM **NBP** probabilistic percentile bulletin (`blend_nbptx.tHHz`).

PURE module: no I/O, no clock access, no `nautilus_trader` import, no global
state, no `breezy.strategy`/`breezy.runtime` import. Mirrors
`nbm_forecast_parse.py` (the NBS collective-bulletin parser) in style and in
the drift-raises-never-coerces posture (L-17), adapted to NBP's different
grid layout.

Grammar, VERIFIED 2026-09-29 against real captures of the 13Z/19Z/01Z v5.0
cycles and one v4.2-era cycle (see `tests/fixtures/nbm/nbptx_*_excerpt.txt`,
each carrying a provenance header: source URL, fetch time, raw-file sha256).
One bulletin holds every station as a block, e.g.::

     KLAX    NBM V5.0 NBP GUIDANCE    9/28/2026  1300 UTC
        TUE 29| WED 30| THU 01| FRI 02| ...
     UTC    12| 00  12| 00  12| 00  12| ...
     FHR    23| 35  47| 59  71| 83  95| ...
     TXNMN  67| 82  68| 81  67| 81  69| ...
     TXNSD   2|  3   2|  3   1|  2   2| ...
     TXNP1  64| 79  66| 78  65| 79  67| ...
     ...

Unlike NBS's fixed-3-character-column grid, NBP's grid is PIPE-DELIMITED:
each `|`-separated group covers one calendar day and holds either ONE value
(the day's only available column -- the very first group of a 13Z/19Z cycle
carries just the MIN, and the last group of any cycle may carry just the
MAX) or TWO values (MAX then MIN, both 00Z/12Z-labelled) separated by one
space. Every value slot is right-justified within a 3-character field,
matching NBS's own `_COLUMN_WIDTH` convention (and confirmed independently
by the NBM text-card's own clamping note: ">998 prints as 998", "<-98 prints
as -98" -- a 3-character field's own natural bounds). Values are extracted
RIGHT TO LEFT within each group so the parser never depends on how wide a
row's own LABEL happens to be (`TXNMN` is 5 characters, `UTC`/`FHR` are 3).

TXN's MAX/MIN split, VERIFIED against the primary source
(https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0, "NBP" section, "Begin
Key"): "TXNMN = QMD Mean minimum/maximum temperature, F. Minimum is listed
at 12z, and Maximum is listed at 00z." -- identically worded for
TXNSD/TXNP1/P2/P5/P7/P9. This module extracts ONLY the MAX (00Z) column: the
daily-max quantile fields this bot trades (§3.2 item 1/8 of the plan). The
TRUE window length behind a MAX column is recorded as UNKNOWN here -- see
`docs/evidence/NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md`. The card states an
18-hour window (12Z current-day to 06Z next-day, reported at 00Z following
day) under the NBS/NBE sections' own "Elements" key, but does NOT restate
that window text under NBP's own section -- only the 00Z/12Z column split is
independently confirmed for NBP. Per L-17, a length this parser cannot
itself verify is never asserted: `valid_start_ns == valid_end_ns` is the
00Z grid instant only (mirrors `nbm_forecast_parse.py`'s identical choice
for the identical reason).

Drift RAISES; it never coerces. A missing required row, an unrecognised
station-header shape, or a UTC/FHR cross-check mismatch (the derived hour
`(cycle_hour + FHR) % 24` disagreeing with the row's own labelled UTC hour)
is a bulletin this parser does not understand (L-37): it names the station,
the missing/mismatched row, and the row labels actually present in that
block (the "header key tree"), rather than guessing. ABSENCES, by contrast,
are DATA: `not_published` (blank cell), `sentinel` (the published missing
code -- the NBM text-card's own words: "For all Elements, a value of -99
indicates missing data"; `-99` is already one of
`breezy.domain.forecast_point.FORECAST_VALUE_SENTINELS`, reused unchanged
here rather than re-declared), `parse_failure` (an unreadable token). None of
the three is ever turned into a number.

Station blocks are located as SPANS (mirroring `nbm_forecast_parse.py`'s
`_station_block_spans`/`_block_lines` split): a live NBP body carries every
NBM station and this bot trades four, so only the requested stations' blocks
are ever sliced and split.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass
from typing import Final

from breezy.domain.forecast_point import forecast_value_or_none
from breezy.ingest.gaps import local_standard_date

__all__ = [
    "NBM_NBP_MODEL",
    "NBP_MAX_COLUMN_UTC_HOUR",
    "NBP_MIN_COLUMN_UTC_HOUR",
    "TXN_VARIABLE_BY_ROW_LABEL",
    "NbpBulletinDriftError",
    "NbpQuantilePoint",
    "bbb_correction_token",
    "max_column_lst_climate_day",
    "parse_nbp_bulletin",
]

NBM_NBP_MODEL: Final[str] = "NBM_NBP"

_NS_PER_SECOND: Final[int] = 1_000_000_000
_SECONDS_PER_HOUR: Final[int] = 3_600
_HOURS_PER_DAY: Final[int] = 24
_FIELD_WIDTH: Final[int] = 3

#: MEASURED against the live NBM v5.0 text-card ("NBP" section, "Begin
#: Key"), 2026-09-29 -- see the module docstring and the SL-2 evidence note.
#: Maximum temperature is listed at 00Z; minimum at 12Z. This parser only
#: ever extracts the 00Z (maximum) column.
NBP_MAX_COLUMN_UTC_HOUR: Final[int] = 0
NBP_MIN_COLUMN_UTC_HOUR: Final[int] = 12

#: NBP row label -> the plan's target `ForecastPoint`-row variable name
#: (§7 SL-2/SL-8: "TXN_Q10..TXN_Q90, TXN_MEAN and TXN_SD"). A later slice
#: maps these onto actual `ForecastPoint` rows; this module never constructs
#: one itself.
TXN_VARIABLE_BY_ROW_LABEL: Final[dict[str, str]] = {
    "TXNMN": "TXN_MEAN",
    "TXNSD": "TXN_SD",
    "TXNP1": "TXN_Q10",
    "TXNP2": "TXN_Q25",
    "TXNP5": "TXN_Q50",
    "TXNP7": "TXN_Q75",
    "TXNP9": "TXN_Q90",
}

#: Every row this parser requires to be present in a station block, in the
#: order they are checked. `UTC`/`FHR` describe the grid; the seven TXN rows
#: are the fields this slice is contracted to extract (§3.2 item 1).
_REQUIRED_ROW_LABELS: Final[tuple[str, ...]] = ("UTC", "FHR", *TXN_VARIABLE_BY_ROW_LABEL)

#: The per-station header. `V\d+\.\d+` generalises ONLY the version number
#: (the one field expected to change across NBM releases, verified against
#: both a v5.0 and a v4.2-era real capture); every surrounding token is
#: exactly what the live bulletin carried. `{3,7}` admits both a numeric
#: site id (e.g. `086092`) and a short alnum id (e.g. `LRRA4`), matching the
#: range of station ids observed in a live body -- this bot only ever
#: requests KLAX/KMDW/KMIA/KSFO (4 characters each).
_STATION_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ ]?(?P<station>[A-Z0-9]{3,7})\s+NBM\s+V(?P<version>\d+\.\d+)\s+NBP\s+GUIDANCE"
    r"\s+(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\s+(?P<cycle>\d{4})\s+UTC",
    re.MULTILINE,
)

_ROW_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<label>[A-Z0-9]+)")


class NbpBulletinDriftError(ValueError):
    """The bulletin does not have the shape this parser verified. Never coerced."""


@dataclass(frozen=True, slots=True)
class NbpQuantilePoint:
    """One station's one TXN quantile/summary-stat field, one MAX (00Z) column.

    `valid_start_ns == valid_end_ns`: the 00Z grid instant. The window's true
    LENGTH is UNVERIFIED for NBP specifically -- see the module docstring.
    """

    station: str
    model_version: str
    cycle_runtime_ns: int
    variable: str
    valid_start_ns: int
    valid_end_ns: int
    value_f: float | None
    absence_reason: str | None


def bbb_correction_token(header_line: str) -> str | None:
    """Return a WMO-style correction/retransmission token trailing a header
    line's `... UTC`, or `None` if the header ends cleanly at `UTC`.

    R3-08: real NBP captures (this module's own fixtures, four cycles across
    two NBM eras) carry NO WMO abbreviated-header line and NO token after
    `UTC` on the station-header line -- this bulletin is served flat from
    AWS/NOMADS, not routed through the NWS telecommunications gateway that
    stamps a WMO `BBB` correction indicator. This function is the parse-if-
    present half of that finding: it is never invoked to invent a token, only
    to report one if a future capture ever carries one.
    """
    match = _STATION_HEADER_RE.match(header_line)
    if match is None:
        raise NbpBulletinDriftError(
            f"not a recognised NBP station-header line: {header_line!r}"
        )
    trailing = header_line[match.end():].strip()
    return trailing or None


def max_column_lst_climate_day(
    point: NbpQuantilePoint, *, std_utc_offset_hours: float
) -> dt.date:
    """Return the station-local-standard-time calendar day `point` targets.

    Thin wrapper over `breezy.ingest.gaps.local_standard_date` -- the ONE
    copy of this derivation (reused, never re-implemented) -- applied to the
    00Z grid instant itself (never a fabricated window end): converting the
    REPORTED instant is what the primary source's own "reported at 00z
    (following day)" wording describes, and it is the only conversion that
    agrees with `scripts/analysis/forecast_climate_day_map.climate_day_for_txn`
    at every station offset this bot trades (LAX/SFO -8, MDW -6, MIA -5) --
    converting a longer, assumed window instead disagrees with it at the -5
    offset. `std_utc_offset_hours` is the caller's to supply (from the site
    registry): this module stays pure and never loads one itself.
    """
    return local_standard_date(point.valid_end_ns, std_utc_offset_hours)


def _row_label(line: str) -> str:
    match = _ROW_LABEL_RE.match(line)
    if match is None:
        return ""
    return match.group("label")


def _required_row(block_lines: list[str], label: str, station: str) -> str:
    for line in block_lines:
        if _row_label(line) == label:
            return line
    present = sorted({_row_label(line) for line in block_lines if _row_label(line)})
    raise NbpBulletinDriftError(
        f"{station}: the NBP block carries no {label!r} row; the bulletin layout "
        f"changed and is refused rather than parsed on a guess. Row labels "
        f"actually present: {present}"
    )


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


def _strip_row_label(group: str, label: str, *, station: str, row_label: str) -> str:
    """Remove a row's own leading label token from its first pipe-group.

    Only the FIRST group (before the first `|`) carries the label; every
    later group is pure value content.
    """
    stripped = group.strip()
    if not stripped.startswith(label):
        raise NbpBulletinDriftError(
            f"{station}: the {row_label!r} row's first column does not start "
            f"with its own label {label!r}: {group!r}"
        )
    return stripped[len(label):]


def _slot_count(group: str) -> int:
    """How many value slots one FHR/UTC pipe-group holds: always 1 or 2.

    FHR/UTC are never blank -- every offered grid column has a forecast
    hour -- so counting whitespace-separated tokens is reliable ONLY for
    these two rows; TXN rows reuse the FHR row's own slot counts instead of
    counting their own tokens, because a genuinely missing TXN value must
    still occupy its slot (never silently collapse the grid -- see
    `_slot_values`).
    """
    tokens = group.split()
    count = len(tokens)
    if count not in (1, 2):
        raise NbpBulletinDriftError(
            f"a grid column holds {count} value(s), expected 1 or 2: {group!r}"
        )
    return count


def _slot_values(group: str, slots: int) -> list[str]:
    """Extract `slots` right-justified `_FIELD_WIDTH`-character values, right to left.

    Slicing from the right (rather than assuming a fixed left offset) is
    what lets this one function serve both the label-bearing first group
    (whose left padding varies with the row label's own length: `UTC` is 3
    characters, `TXNMN` is 5) and every later, unlabelled group. `rstrip`
    first: a real v4.2-era capture trailed the FHR row's last group with two
    extra spaces (`"227  "`), which right-to-left slicing must not count as
    part of the field.
    """
    values: list[str] = []
    rest = group.rstrip()
    for _ in range(slots):
        values.insert(0, rest[-_FIELD_WIDTH:].strip())
        rest = rest[: len(rest) - _FIELD_WIDTH]
        if rest.endswith(" "):
            rest = rest[:-1]
    return values


def _flat_row_values(
    row: str, label: str, slot_counts: list[int], *, station: str
) -> list[str]:
    groups = row.split("|")
    if len(groups) != len(slot_counts):
        raise NbpBulletinDriftError(
            f"{station}: the {label!r} row has {len(groups)} pipe-group(s), "
            f"the FHR row has {len(slot_counts)}; the grid shape disagrees"
        )
    groups[0] = _strip_row_label(groups[0], label, station=station, row_label=label)
    values: list[str] = []
    for group, slots in zip(groups, slot_counts, strict=True):
        values.extend(_slot_values(group, slots))
    return values


def _absence_from_token(token: str) -> tuple[float | None, str | None]:
    """Return `(value_f, absence_reason)` for one TXN cell. Never invents a value."""
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


def _station_block_spans(text: str) -> dict[str, tuple[re.Match[str], int, int]]:
    """Locate every station block as a SPAN. Nothing is sliced or split here.

    Mirrors `nbm_forecast_parse._station_block_spans` (same memory-bound
    reasoning): a live NBP body carries every NBM station; only the
    requested stations' blocks are ever sliced and split.
    """
    matches = list(_STATION_HEADER_RE.finditer(text))
    if not matches:
        raise NbpBulletinDriftError(
            "no NBP station block was found in the bulletin; either the body "
            "is not an NBP text product or its per-station header changed"
        )
    spans: dict[str, tuple[re.Match[str], int, int]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        spans[match.group("station")] = (match, match.start(), end)
    return spans


def _block_lines(text: str, start: int, end: int) -> list[str]:
    return text[start:end].splitlines()


def parse_nbp_bulletin(
    text: str,
    *,
    stations: frozenset[str],
) -> tuple[tuple[NbpQuantilePoint, ...], Counter[str]]:
    """Return the daily-MAX TXN quantile/summary-stat records for `stations`.

    Only the 00Z (MAX) column is ever returned -- see the module docstring.
    A requested station absent from this bulletin is COUNTED
    (`station_block_missing`) and never silently omitted.
    """
    spans = _station_block_spans(text)
    drops: Counter[str] = Counter()
    points: list[NbpQuantilePoint] = []

    for station in sorted(stations):
        span = spans.get(station)
        if span is None:
            drops["station_block_missing"] += 1
            continue
        match, start, end = span
        points.extend(
            _station_points(station, match, _block_lines(text, start, end))
        )

    return tuple(points), drops


def _station_points(
    station: str,
    match: re.Match[str],
    lines: list[str],
) -> list[NbpQuantilePoint]:
    cycle_runtime_ns = _cycle_runtime_ns(match)
    model_version = match.group("version")
    cycle_hour = (cycle_runtime_ns // (_SECONDS_PER_HOUR * _NS_PER_SECOND)) % _HOURS_PER_DAY

    utc_line = _required_row(lines, "UTC", station)
    fhr_line = _required_row(lines, "FHR", station)

    fhr_groups_raw = fhr_line.split("|")
    fhr_groups_raw[0] = _strip_row_label(
        fhr_groups_raw[0], "FHR", station=station, row_label="FHR"
    )
    slot_counts = [_slot_count(group) for group in fhr_groups_raw]

    utc_values = _flat_row_values(utc_line, "UTC", slot_counts, station=station)
    fhr_values = _flat_row_values(fhr_line, "FHR", slot_counts, station=station)
    if len(utc_values) != len(fhr_values):
        raise NbpBulletinDriftError(
            f"{station}: the UTC row yields {len(utc_values)} value(s) and the "
            f"FHR row {len(fhr_values)}; the two must describe the same grid"
        )

    hours: list[int] = []
    projections: list[int] = []
    for index, (hour_token, fhr_token) in enumerate(zip(utc_values, fhr_values, strict=True)):
        if not hour_token.isdigit() or not fhr_token.isdigit():
            raise NbpBulletinDriftError(
                f"{station}: column {index} has a non-numeric UTC/FHR token "
                f"({hour_token!r}/{fhr_token!r}); the column grid changed shape"
            )
        hour, projection = int(hour_token), int(fhr_token)
        derived = (cycle_hour + projection) % _HOURS_PER_DAY
        if derived != hour:
            raise NbpBulletinDriftError(
                f"{station}: column {index} is labelled {hour:02d}Z but its FHR "
                f"{projection} off the {cycle_hour:02d}Z cycle disagrees "
                f"({derived:02d}Z); the column grid cannot be trusted"
            )
        hours.append(hour)
        projections.append(projection)

    points: list[NbpQuantilePoint] = []
    for row_label, variable in TXN_VARIABLE_BY_ROW_LABEL.items():
        row = _required_row(lines, row_label, station)
        values = _flat_row_values(row, row_label, slot_counts, station=station)
        if len(values) != len(hours):
            raise NbpBulletinDriftError(
                f"{station}: the {row_label!r} row yields {len(values)} value(s), "
                f"the grid has {len(hours)}; the two must describe the same grid"
            )
        for hour, projection, token in zip(hours, projections, values, strict=True):
            if hour != NBP_MAX_COLUMN_UTC_HOUR:
                continue
            value, absence_reason = _absence_from_token(token)
            valid_ns = cycle_runtime_ns + projection * _SECONDS_PER_HOUR * _NS_PER_SECOND
            points.append(
                NbpQuantilePoint(
                    station=station,
                    model_version=model_version,
                    cycle_runtime_ns=cycle_runtime_ns,
                    variable=variable,
                    valid_start_ns=valid_ns,
                    valid_end_ns=valid_ns,
                    value_f=value,
                    absence_reason=absence_reason,
                )
            )
    return points
