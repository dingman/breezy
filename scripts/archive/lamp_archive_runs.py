"""Pure helpers for the F13 A1 LAMP archive backfill: run grouping, LAV splitting, the manifest.

No network, no clock. Everything the CLI (``lamp_archive_backfill.py``) needs that is not a
request loop lives here:

* ``iter_lamp_runs``: group the station-filtered lines of one archive file into one RUN (one HH30
  bulletin) per issuance, keeping only the closed-set station blocks. A header that disagrees with
  the file it came from, a run that reappears after another began, and a repeated station block
  are dropped and COUNTED, never repaired.
* ``split_lav_runs``: split an IEM LAV CSV into one payload per ``runtime``.
* the availability manifest: an append-only JSONL sidecar next to the revision store that carries
  what the store cannot (availability, basis, holdout tag). The revision store key is untouched.

Availability is ``archive`` basis: ``run + the prereg conservative lag`` (``available_at`` with
nothing observed). The archive's own ``Last-Modified`` is the posting time, weeks later, and is
never used as the availability anchor (it would hide the product for weeks and still not be a
measurement of when it was public).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from breezy.ingest.us_source_availability import LagPrereg, available_at
from breezy.persistence.us_source_request import (
    US_LAMP_MDL_SOURCE,
    US_LAV_IEM_SOURCE,
    US_SOURCE_STATIONS,
)

__all__ = [
    "ARCHIVE_PREREG",
    "ARCHIVE_VERSION",
    "HOLDOUT_START",
    "MANIFEST_NAME",
    "MAX_BLOCK_BYTES",
    "MAX_BLOCK_LINES",
    "LampRun",
    "LavPayloadError",
    "Manifest",
    "availability_row",
    "iter_lamp_runs",
    "missing_stations",
    "split_lav_runs",
]

_NS: Final[int] = 1_000_000_000
_MINUTE_NS: Final[int] = 60 * _NS
#: Plan §Phase A1: only days < 2026-07-01 reach a fit or a score. Pinned equal to the
#: calibration split by a test; restated here so this script imports no analysis code.
HOLDOUT_START: Final[dt.date] = dt.date(2026, 7, 1)
#: An HH30 run forecasts 38 h ahead (``lavtxt`` 1-25 h plus ``lavtxt_ext`` 26-38 h).
_RUN_HORIZON: Final[dt.timedelta] = dt.timedelta(hours=38)
MANIFEST_NAME: Final[str] = "availability_manifest.jsonl"
ARCHIVE_VERSION: Final[str] = "archive-v1"

#: ``us-lamp-mdl`` lag: the plan's conservative LAMP lag (>= 60 min, r3 section 2), which is
#: above the A0-measured 6-10 min after :30 and above the 5 min sanity floor. C1 has not yet
#: produced its >= 14 days of measured lags, so no cycle has a C1 measurement; this lag is the
#: plan's, not a measurement. ``us-lav-iem`` is labelled HH:00 while the real run is probably
#: HH:30 (A0, inferred), so it gets a further 30 min.
ARCHIVE_PREREG: Final[LagPrereg] = LagPrereg(
    sanity_floors_ns={US_LAMP_MDL_SOURCE: 5 * _MINUTE_NS, US_LAV_IEM_SOURCE: 5 * _MINUTE_NS},
    conservative_lags_ns={
        US_LAMP_MDL_SOURCE: 60 * _MINUTE_NS,
        US_LAV_IEM_SOURCE: 90 * _MINUTE_NS,
    },
    measured_max_lag_ns={US_LAMP_MDL_SOURCE: 10 * _MINUTE_NS},
)
_BASIS_TAG: Final[Mapping[str, str]] = {
    US_LAMP_MDL_SOURCE: "archive",
    US_LAV_IEM_SOURCE: "iem-lav",
}
_BASIS_FLAG: Final[Mapping[str, str]] = {
    US_LAMP_MDL_SOURCE: "archive_mdl",
    US_LAV_IEM_SOURCE: "iem_lav_gap_fill_run_label_inferred",
}

_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<station>[A-Z0-9]{3,6})\s+(?:GFS\s+)?LAMP\s+GUIDANCE\b"
)
_STAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"\bGUIDANCE\s+(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\s+(?P<hhmm>\d{4})\s+UTC\b"
)
_LAV_TIME_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
_LAV_MODEL: Final[str] = "LAV"
#: A real closed-set station block is ~30 lines and ~2 KiB; a block past either cap is not a
#: LAMP block (a runaway or hostile stream) and is dropped and tallied, never held or stored.
MAX_BLOCK_LINES: Final[int] = 200
MAX_BLOCK_BYTES: Final[int] = 64 * 1024


def _bump(tally: dict[str, int], key: str, count: int = 1) -> None:
    tally[key] = tally.get(key, 0) + count


# ----------------------------------------------------------------------- LAMP runs


@dataclass(frozen=True, slots=True)
class LampRun:
    """One HH30 bulletin's closed-set station blocks; ``blocks`` maps station -> block text."""

    run_at: dt.datetime
    blocks: Mapping[str, str] = field(default_factory=dict)

    def payload(self) -> bytes:
        """The raw revision body: the blocks in station order, each ended by one blank line."""
        return "".join(self.blocks[s] for s in sorted(self.blocks)).encode("utf-8")


def missing_stations(run: LampRun, stations: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(s for s in stations if s not in run.blocks))


def _stamp(line: str) -> dt.datetime | None:
    found = _STAMP_RE.search(line)
    if found is None:
        return None
    try:
        return dt.datetime(
            int(found["year"]),
            int(found["month"]),
            int(found["day"]),
            int(found["hhmm"][:2]),
            int(found["hhmm"][2:]),
            tzinfo=dt.UTC,
        )
    except ValueError:
        return None


def iter_lamp_runs(
    lines: Iterable[str],
    *,
    expect_year_month: tuple[int, int],
    expect_hhmm: str,
    tally: dict[str, int],
    stations: frozenset[str] = frozenset(US_SOURCE_STATIONS),
) -> Iterator[LampRun]:
    """Group lines into runs; ``tally`` counts every drop by reason (never repaired)."""
    seen: set[dt.datetime] = set()
    current: dt.datetime | None = None
    blocks: dict[str, str] = {}
    station: str | None = None
    held: list[str] = []
    held_bytes = 0
    oversize = False
    skipping: dt.datetime | None = None

    def close_block() -> None:
        nonlocal station, held, held_bytes, oversize
        if station is not None:
            if oversize:
                _bump(tally, "oversize_blocks")
            elif station in blocks:
                _bump(tally, "duplicate_block")
            else:
                blocks[station] = "".join(held) + "\n"
        station, held, held_bytes, oversize = None, [], 0, False

    def hold(line: str) -> None:
        nonlocal held_bytes, oversize
        if oversize:
            return
        held_bytes += len(line.encode("utf-8"))
        if len(held) >= MAX_BLOCK_LINES or held_bytes > MAX_BLOCK_BYTES:
            oversize = True
            held.clear()
            return
        held.append(line)

    def run_ready() -> LampRun | None:
        close_block()
        if current is None or not blocks:
            return None
        return LampRun(run_at=current, blocks=dict(blocks))

    for line in lines:
        header = _HEADER_RE.match(line)
        if header is not None:
            close_block()
            if header["station"] not in stations:
                continue
            issued = _stamp(line)
            if issued is None:
                _bump(tally, "bad_header")
                continue
            if (issued.year, issued.month) != expect_year_month or (
                f"{issued:%H%M}" != expect_hhmm
            ):
                _bump(tally, "header_mismatch")
                continue
            if issued != current:
                finished = run_ready()
                if finished is not None:
                    yield finished
                if issued in seen:
                    if issued != skipping:  # one reappearance is one drop, not one per block
                        _bump(tally, "run_reappeared")
                    skipping = issued
                    current, blocks = None, {}
                    continue
                current, blocks, skipping = issued, {}, None
                seen.add(issued)
            station = header["station"]
            hold(line)
        elif station is not None:
            if line.strip():
                hold(line)
            else:
                close_block()
    finished = run_ready()
    if finished is not None:
        yield finished


# ------------------------------------------------------------------------ IEM LAV


class LavPayloadError(ValueError):
    """The IEM LAV CSV is not in a shape this backfill may split."""


def split_lav_runs(text: str, station: str, tally: dict[str, int]) -> dict[dt.datetime, bytes]:
    """One CSV payload (header + that run's rows) per ``runtime``, ascending.

    A row for another station or model, with the wrong width, or with an unparseable runtime is
    dropped and counted.
    """
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise LavPayloadError("empty LAV response")
    header = [cell.strip().lower() for cell in rows[0]]
    if "runtime" not in header:
        raise LavPayloadError(f"LAV header has no runtime column: {rows[0]!r}")
    at = header.index("runtime")
    station_at = header.index("station") if "station" in header else None
    model_at = header.index("model") if "model" in header else None
    grouped: dict[dt.datetime, list[list[str]]] = {}
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            _bump(tally, "short_row")
            continue
        if station_at is not None and row[station_at].strip() != station:
            _bump(tally, "wrong_station")
            continue
        if model_at is not None and row[model_at].strip() != _LAV_MODEL:
            _bump(tally, "wrong_model")
            continue
        try:
            run_at = dt.datetime.strptime(row[at].strip(), _LAV_TIME_FORMAT).replace(tzinfo=dt.UTC)
        except ValueError:
            _bump(tally, "bad_runtime")
            continue
        grouped.setdefault(run_at, []).append(row)
    out: dict[dt.datetime, bytes] = {}
    for run_at in sorted(grouped):
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(rows[0])
        writer.writerows(grouped[run_at])
        out[run_at] = buffer.getvalue().encode("utf-8")
    return out


# --------------------------------------------------------------- availability + tag


def availability_row(
    *,
    source: str,
    station: str,
    run_at: dt.datetime,
    sha256: str,
    revision: int | None,
    leg: str,
    origin: str,
) -> dict[str, Any]:
    """The sidecar row: archive-basis availability and the holdout tag for one stored run."""
    run_ns = int(run_at.timestamp()) * _NS
    result = available_at(source, ARCHIVE_VERSION, run_ns, None, prereg=ARCHIVE_PREREG)
    sealed = run_at.date() >= HOLDOUT_START
    return {
        "source": source,
        "station": station,
        "run_ts_ns": run_ns,
        "sha256": sha256,
        "revision": revision,
        "available_at_ns": result.ts,
        "availability_basis": f"{result.basis}@{_BASIS_TAG[source]}",
        "basis_flag": _BASIS_FLAG[source],
        # Run date >= the holdout start: stored for the forward feed; no fit or score may read it.
        "holdout_sealed": sealed,
        # An earlier run whose 38 h window reaches a holdout day: usable only for pre-holdout days.
        "spans_holdout_days": (not sealed) and (run_at + _RUN_HORIZON).date() >= HOLDOUT_START,
        "leg": leg,
        "origin": origin,
    }


class Manifest:
    """Append-only JSONL, one row per ``(station, run_ts_ns, sha256)``; idempotent by key."""

    def __init__(self, root: Path, source: str) -> None:
        self._path = root / source / MANIFEST_NAME
        self._keys: set[tuple[str, int, str]] | None = None
        self._torn_offset: int | None = None
        #: Torn trailing lines skipped on load (a crash mid-append); never a non-trailing one.
        self.torn_lines = 0

    def _load(self) -> set[tuple[str, int, str]]:
        if self._keys is None:
            self._keys = set()
            if self._path.exists():
                self._read_rows(self._path.read_bytes())
        return self._keys

    def _read_rows(self, data: bytes) -> None:
        """Index every row. An invalid LAST line is a torn append: skip, count, truncate later."""
        assert self._keys is not None
        offset = 0
        entries: list[tuple[int, bytes]] = []
        for raw in data.split(b"\n"):
            if raw.strip():
                entries.append((offset, raw))
            offset += len(raw) + 1
        for index, (start, raw) in enumerate(entries):
            try:
                row = json.loads(raw.decode("utf-8"))
                key = (row["station"], row["run_ts_ns"], row["sha256"])
            except (ValueError, KeyError, TypeError):
                if index != len(entries) - 1:
                    raise
                self.torn_lines += 1
                self._torn_offset = start
                return
            self._keys.add(key)

    def record(self, row: Mapping[str, Any]) -> bool:
        """Append ``row`` unless its key is present; True when a line was written."""
        keys = self._load()
        key = (str(row["station"]), int(row["run_ts_ns"]), str(row["sha256"]))
        if key in keys:
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
        try:
            if self._torn_offset is not None:  # cut the torn tail so the next row starts clean
                os.ftruncate(fd, self._torn_offset)
                self._torn_offset = None
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        keys.add(key)
        return True
