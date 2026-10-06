"""Parse the GFS LAMP station text bulletin (`lavtxt`) and derive a daily max (F13-C1).

PURE module: no network, no clock access, no `nautilus_trader` import, no global
state. It holds the streaming line readers (plain bytes and the concatenated
monthly MDL `.gz` archive, A0-R4) and the block parser.

Bulletin shape (A0-R3)::

     KNYC   GFS LAMP GUIDANCE   10/06/2026  0130 UTC
     UTC  02 03 04 ...
     TMP  59 57 57 ...

There is NO explicit max row: the climate-day max is derived from hourly `TMP`
over the climate day's local-STANDARD-time window (`lamp_daily_max_f`, using
`breezy.domain.climate_day`). A window that is not fully covered is MISSING
(`None`), never imputed (A0-R4: missing days are real).

H3 posture: strict UTF-8, bounded lines/fields/bytes, physical-range checks. A bad
row in a closed-set station block REFUSES the whole run (`LampParseError`); it is
never skipped. `LampParseError` is a local refusal class: it is not a
`TransportError`, `CliParseError` or `CliSanityError` (R18).

Blocks of stations outside :data:`LAMP_STATIONS` (a live bulletin carries
thousands) are not parsed or validated; they only count against the line bound.

Layout VERIFIED against a real capture (`lamp_lavtxt_real_20261005_2330z.txt`): rows
are a 4-character label, a space, then 3-character right-justified columns (so values
glue), 25 hourly columns for a `HH30` run, the first column being the hour after the run;
`999` is the missing marker (that hour is MISSING; the run is not refused). A day whose
24 window hours include a missing hour is MISSING.
"""

from __future__ import annotations

import datetime as dt
import re
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from breezy.domain.climate_day import climate_day_for_instant

LAMP_STATIONS: Final[frozenset[str]] = frozenset({"KLAX", "KMDW", "KMIA", "KSFO", "KNYC"})

MAX_LINE_BYTES: Final = 4096
MAX_FIELDS_PER_ROW: Final = 64
MAX_LINES: Final = 8_000_000
MAX_COMPRESSED_BYTES: Final = 64 * 1024 * 1024
MAX_DECOMPRESSED_BYTES: Final = 512 * 1024 * 1024

#: Physical range for a surface temperature, degrees Fahrenheit.
TMP_MIN_F: Final = -80
TMP_MAX_F: Final = 140
#: The published missing-data value in a 3-character column (real bulletin, 2026-10-05).
MISSING_MARKER: Final = 999

_HOURS_PER_LST_DAY: Final = 24
_INFLATE_STEP: Final = 64 * 1024
_HEADER_MARK: Final = "GFS LAMP GUIDANCE"
_HEADER_RE: Final = re.compile(
    r"^\s*([A-Z0-9]{3,4})\s+GFS LAMP GUIDANCE\s+(\d{2})/(\d{2})/(\d{4})\s+(\d{4}) UTC\s*$"
)
_INT_RE: Final = re.compile(r"^-?\d{1,3}$")
_COLUMN_WIDTH: Final = 3
_RUN_MINUTE: Final = 30  # only the HH30 runs are in scope (A0-R3)


class LampParseError(ValueError):
    """The LAMP input is not a bulletin this parser may trust; the run is refused."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"LAMP parse refused: {reason}" + (f" ({detail})" if detail else ""))


@dataclass(frozen=True, slots=True)
class LampBlock:
    """One closed-set station's hourly `TMP` series from one bulletin run."""

    station: str
    issued_at: dt.datetime
    valid_times: tuple[dt.datetime, ...]
    #: Hourly temperatures, `None` where the bulletin printed the missing marker.
    tmp_f: tuple[int | None, ...]


class _LineSplitter:
    """Incremental bytes -> strict-UTF-8 lines with a per-line byte bound."""

    def __init__(self, max_line_bytes: int) -> None:
        self._max = max_line_bytes
        self._buf = bytearray()

    def feed(self, data: bytes) -> Iterator[str]:
        self._buf += data
        start = 0
        while (nl := self._buf.find(b"\n", start)) != -1:
            yield self._decode(bytes(self._buf[start:nl]))
            start = nl + 1
        del self._buf[:start]
        if len(self._buf) > self._max:
            raise LampParseError("line_too_long", f"over {self._max} bytes")

    def finish(self) -> Iterator[str]:
        if self._buf:
            tail = bytes(self._buf)
            self._buf.clear()
            yield self._decode(tail)

    def _decode(self, raw: bytes) -> str:
        if len(raw) > self._max:
            raise LampParseError("line_too_long", f"over {self._max} bytes")
        try:
            return raw.decode("utf-8").rstrip("\r")
        except UnicodeDecodeError as exc:
            raise LampParseError("non_utf8", str(exc)) from exc


def iter_plain_lines(
    chunks: Iterable[bytes], *, max_line_bytes: int = MAX_LINE_BYTES
) -> Iterator[str]:
    """Stream strict-UTF-8 lines from plain byte chunks."""
    splitter = _LineSplitter(max_line_bytes)
    for chunk in chunks:
        yield from splitter.feed(chunk)
    yield from splitter.finish()


def iter_gzip_lines(
    chunks: Iterable[bytes],
    *,
    max_compressed_bytes: int = MAX_COMPRESSED_BYTES,
    max_decompressed_bytes: int = MAX_DECOMPRESSED_BYTES,
    max_line_bytes: int = MAX_LINE_BYTES,
    inflate_step: int = _INFLATE_STEP,
) -> Iterator[str]:
    """Stream lines from a (possibly multi-member) gzip byte stream (A0-R4).

    Inflates in bounded steps (`inflate_step`, via `max_length`), so a gzip bomb trips
    `max_decompressed_bytes` after at most one step of excess output, never after
    buffering it. Compressed input is counted before it is inflated. Truncated
    streams and bytes trailing a member that are not another gzip member refuse.
    """
    splitter = _LineSplitter(max_line_bytes)
    inflater = zlib.decompressobj(wbits=31)
    total_in = total_out = members = 0
    member_open = False
    for chunk in chunks:
        total_in += len(chunk)
        if total_in > max_compressed_bytes:
            raise LampParseError("compressed_cap", f"over {max_compressed_bytes} bytes")
        pending = chunk
        drain = False
        while pending or drain:
            member_open = True
            try:
                out = inflater.decompress(pending, inflate_step)
            except zlib.error as exc:
                raise LampParseError("bad_gzip", str(exc)) from exc
            total_out += len(out)
            if total_out > max_decompressed_bytes:
                raise LampParseError("decompressed_cap", f"over {max_decompressed_bytes} bytes")
            yield from splitter.feed(out)
            if inflater.eof:
                members += 1
                member_open = False
                pending = inflater.unused_data
                drain = False
                inflater = zlib.decompressobj(wbits=31)
            else:
                pending = inflater.unconsumed_tail
                # A full step may leave output inside zlib with no input left: keep
                # draining until a step comes up short.
                drain = not pending and len(out) == inflate_step
    if member_open:
        raise LampParseError("truncated_gzip")
    if members == 0:
        raise LampParseError("empty_gzip")
    yield from splitter.finish()


def _fixed_fields(line: str, label: str, max_fields: int) -> list[int | None]:
    """Decode a row's fixed 3-character columns (A0-R3, real layout).

    The label occupies columns 0-4 and every value is right-justified in a 3-character
    column starting at column 5, so negatives and `999` glue to their neighbours
    (`" TMP  -5-12 -3"`). `999` is the published missing marker and decodes to None.
    """
    body = line[5:].rstrip()
    if line[4:5] != " " or not body or len(body) % _COLUMN_WIDTH:
        raise LampParseError("bad_row_shape", label)
    count = len(body) // _COLUMN_WIDTH
    if count > max_fields:
        raise LampParseError("too_many_fields", f"{label}: {count} > {max_fields}")
    values: list[int | None] = []
    for i in range(0, len(body), _COLUMN_WIDTH):
        cell = body[i : i + _COLUMN_WIDTH]
        token = cell.strip()
        if " " in token or not _INT_RE.match(token):
            raise LampParseError("bad_token", f"{label}: {cell!r}")
        values.append(None if int(token) == MISSING_MARKER else int(token))
    return values


def _issued_at(match: re.Match[str]) -> dt.datetime:
    month, day, year, hhmm = (int(g) for g in match.groups()[1:])
    if hhmm % 100 != _RUN_MINUTE:
        raise LampParseError("run_minute_not_30", match.group(0).strip())
    try:
        return dt.datetime(year, month, day, hhmm // 100, hhmm % 100, tzinfo=dt.UTC)
    except ValueError as exc:
        raise LampParseError("bad_header_time", match.group(0).strip()) from exc


def _build_block(
    station: str,
    issued: dt.datetime,
    utc_row: list[int | None] | None,
    tmp_row: list[int | None] | None,
) -> LampBlock:
    if utc_row is None or tmp_row is None:
        raise LampParseError("missing_row", f"{station}: UTC and TMP rows are both required")
    if len(utc_row) != len(tmp_row):
        raise LampParseError("row_length_mismatch", f"{station}: {len(utc_row)} vs {len(tmp_row)}")
    hours = [h for h in utc_row if h is not None and 0 <= h <= 23]
    first = issued.replace(minute=0) + dt.timedelta(hours=1)
    if len(hours) != len(utc_row) or hours[0] != first.hour:
        raise LampParseError("utc_row_misaligned", f"{station}: {utc_row[:1]}")
    if any((b - a) % 24 != 1 for a, b in pairwise(hours)):
        raise LampParseError("utc_row_not_hourly", station)
    for value in tmp_row:
        if value is not None and not TMP_MIN_F <= value <= TMP_MAX_F:
            raise LampParseError("tmp_out_of_range", f"{station}: {value}")
    times = tuple(first + dt.timedelta(hours=i) for i in range(len(utc_row)))
    return LampBlock(station=station, issued_at=issued, valid_times=times, tmp_f=tuple(tmp_row))


def iter_lamp_blocks(
    lines: Iterable[str],
    *,
    max_lines: int = MAX_LINES,
    max_fields: int = MAX_FIELDS_PER_ROW,
) -> Iterator[LampBlock]:
    """Yield one `LampBlock` per closed-set station block; refuse the run on a bad row.

    LAZY: blocks that precede a bad row have already been yielded when the refusal is
    raised. A caller that persists must drain the whole stream first (or use
    :func:`parse_lamp_blocks`, which is all-or-nothing). A repeated (station, issued_at)
    block in one stream is refused.
    """
    seen: set[tuple[str, dt.datetime]] = set()
    station: str | None = None
    issued: dt.datetime | None = None
    rows: dict[str, list[int | None]] = {}

    def flush() -> LampBlock | None:
        if station is None or issued is None:
            return None
        if (station, issued) in seen:
            raise LampParseError("duplicate_block", f"{station} {issued.isoformat()}")
        seen.add((station, issued))
        return _build_block(station, issued, rows.get("UTC"), rows.get("TMP"))

    for count, line in enumerate(lines, start=1):
        if count > max_lines:
            raise LampParseError("too_many_lines", f"over {max_lines}")
        header = _HEADER_RE.match(line)
        if header is None and _HEADER_MARK in line:
            raise LampParseError("bad_header", line.strip()[:80])
        if header is not None or not line.strip():
            if (block := flush()) is not None:
                yield block
            station, issued, rows = None, None, {}
            if header is not None and header.group(1) in LAMP_STATIONS:
                station, issued = header.group(1), _issued_at(header)
            continue
        if station is None:
            continue
        label = line.split(None, 1)[0]
        if label in ("UTC", "TMP"):
            if label in rows:
                raise LampParseError("duplicate_row", f"{station}: {label}")
            rows[label] = _fixed_fields(line, label, max_fields)
    if (block := flush()) is not None:
        yield block


def parse_lamp_blocks(
    lines: Iterable[str],
    *,
    max_lines: int = MAX_LINES,
    max_fields: int = MAX_FIELDS_PER_ROW,
) -> tuple[LampBlock, ...]:
    """All-or-nothing: every closed-set block of the run, or a `LampParseError` and nothing."""
    return tuple(iter_lamp_blocks(lines, max_lines=max_lines, max_fields=max_fields))


def lamp_daily_max_f(
    block: LampBlock, climate_day: dt.date, std_utc_offset_hours: float
) -> int | None:
    """Max hourly `TMP` over `climate_day`'s local-standard-time window, or None (MISSING).

    The window is the 24 hourly instants whose local-standard date is `climate_day`.
    Any absent hour makes the day MISSING; nothing is imputed.
    """
    by_time = dict(zip(block.valid_times, block.tmp_f, strict=True))
    window = [
        v
        for t, v in by_time.items()
        if climate_day_for_instant(t, std_utc_offset_hours) == climate_day
    ]
    if len(window) != _HOURS_PER_LST_DAY or any(v is None for v in window):
        return None
    return max(v for v in window if v is not None)
