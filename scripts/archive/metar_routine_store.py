#!/usr/bin/env python
"""Routine-METAR archive store, reader and 1-min derivation diagnostic (F13 FB-R13).

Two subcommands
---------------
``fetch``
    Persists IEM ASOS routine METAR (``report_type=3``) per station-year under
    ``--archive-root`` (default ``~/.local/share/breezy/us_source_archive/metar-routine/``) as
    ``<STATION>/<year>.csv`` plus a sha256 ``manifest.json``. One request per station-year over
    2021-01-01 .. 2026-06-30. The sealed holdout (>= 2026-07-01) is refused. Idempotent: a
    station-year whose file matches its manifest sha256 is never re-requested. Writes are
    atomic (temp, fsync, ``os.replace``, directory fsync), manifest last; one writer at a time
    (flock). Same budget / 4 s pacing / launch-window / report / exit-code discipline as
    ``metar_routine_minute_probe`` (whose transport it reuses; egress is IEM ``asos.py`` only).

``diag``
    Offline. Joins the stored METAR T-group temperature against the local 1-min ASOS archive
    under several derivations (1-min row at offsets -5..+2 minutes, mean/max/min of the 5
    one-minute values ending at the report minute, alternative METAR roundings) and reports the
    mismatch rate per variant per station. Never touches the network.

Columns: ``station, valid_utc, tmpf, tgroup_c, report_type, tmpf_source, metar``. ``tmpf`` is the
whole degF of the T-group through ``round_half_up_f`` (``tmpf_source=tgroup``), else the IEM
``tmpf`` column rounded half up (``column``), else empty (``missing``).

``rederive``
    Offline. Recomputes ``tmpf`` / ``tgroup_c`` / ``tmpf_source`` of every stored row from its raw
    ``metar`` column with the LIVE T-group parser (``breezy.ingest.iem_observations``), so a store
    written with an older, looser parse matches what the live ingest would have kept. ``--dry-run``
    reports the rows that would change; ``--apply`` rewrites the changed station-years atomically
    (body first, manifest sha256 after) under the store lock. A row that loses its T group keeps
    its stored ``tmpf`` (the IEM column equals the T-group value) as ``column``. No network.

``read_routine_metar(station, start, end, root)`` is the read helper for the Phase A obs reader.

EXIT CODES: 0 complete; 1 a station-year failed; 2 refusal or error (report still written);
3 aborted (request budget exhausted, or another writer holds the lock); 6 launch window.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import math
import os
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
for _sibling in ("analysis", "venue", "archive"):  # pragma: no cover - bootstrap
    _sibling_path = str(_SCRIPTS_ROOT / _sibling)
    if _sibling_path not in sys.path:
        sys.path.insert(0, _sibling_path)

import metar_routine_minute_probe as _probe  # type: ignore[import-not-found]
from iem_mos_probe_transport import IemPacer  # type: ignore[import-not-found]
from metar_routine_minute_probe import (
    HOLDOUT_START,
    IEM_METAR_STATION_IDS,
    LIVE_ENV_VAR,
    PACING_NS,
    FetchedText,
    MetarFetcher,
    MetarRow,
    MetarTransport,
    OneMinReader,
    RefusalError,
    _fetch_with_retry,
    _may_run,
    _now,
    cache_onemin_reader,
    metar_url,
    parse_metar_csv,
    parse_tgroup_tenths,
    tgroup_to_f,
    write_report,
)

from breezy.domain.temperature import round_half_up_f
from breezy.ingest.http import TransportError
from breezy.ingest.probe_transport import RequestBudget, RequestBudgetExceededError

EXIT_OK: Final[int] = int(_probe.EXIT_OK)
EXIT_FAILED: Final[int] = int(_probe.EXIT_FAILED)
EXIT_REFUSED: Final[int] = int(_probe.EXIT_REFUSED)
EXIT_ABORTED: Final[int] = int(_probe.EXIT_ABORTED)
EXIT_LAUNCH_WINDOW: Final[int] = int(_probe.EXIT_LAUNCH_WINDOW)

__all__ = [
    "RoutineMetar",
    "RoutineMetarError",
    "main",
    "read_routine_metar",
    "serialise_year",
]

SCHEMA: Final[str] = "metar_routine_store/v1"
COLUMNS: Final[tuple[str, ...]] = (
    "station",
    "valid_utc",
    "tmpf",
    "tgroup_c",
    "report_type",
    "tmpf_source",
    "metar",
)
FIRST_YEAR: Final[int] = 2021
LAST_YEAR: Final[int] = 2026
DEFAULT_STATIONS: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")
DEFAULT_ARCHIVE_ROOT: Final[Path] = (
    Path.home() / ".local" / "share" / "breezy" / "us_source_archive" / "metar-routine"
)
DEFAULT_ASOS_ROOT: Final[Path] = (
    Path.home() / ".local" / "share" / "breezy" / "archive" / "iem-asos-1min"
)
MANIFEST_NAME: Final[str] = "manifest.json"
LOCK_NAME: Final[str] = ".lock"
OFFSETS: Final[tuple[int, ...]] = tuple(range(-5, 3))
_MIN: Final[dt.timedelta] = dt.timedelta(minutes=1)


class RoutineMetarError(RuntimeError):
    """The stored routine METAR cannot be read as requested (missing, corrupt, holdout)."""


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _row_record(station: str, row: MetarRow) -> list[str]:
    tenths = parse_tgroup_tenths(row.raw)
    if tenths is not None:
        tmpf, source, tgroup = str(tgroup_to_f(tenths)), "tgroup", f"{tenths / 10:.1f}"
    elif row.tmpf is not None:
        tmpf, source, tgroup = str(math.floor(row.tmpf + 0.5)), "column", ""
    else:
        tmpf, source, tgroup = "", "missing", ""
    stamp = row.valid.strftime("%Y-%m-%dT%H:%MZ")
    return [station, stamp, tmpf, tgroup, "3", source, row.raw]


def serialise_year(station: str, rows: Sequence[MetarRow]) -> bytes:
    """Deterministic CSV bytes: sorted by time, one row per instant (first wins)."""
    seen: dict[dt.datetime, MetarRow] = {}
    for row in sorted(rows, key=lambda r: r.valid):
        seen.setdefault(row.valid, row)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in seen.values():
        writer.writerow(_row_record(station, row))
    return out.getvalue().encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    """Temp file, fsync, atomic replace, directory fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    if not path.exists():
        return {"schema": SCHEMA, "entries": {}}
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("entries"), dict):
        raise RefusalError(f"{path}: not a {SCHEMA} manifest")
    return manifest


def _entry_key(station: str, year: int) -> str:
    return f"{station}/{year}"


def _is_cached(root: Path, manifest: Mapping[str, Any], station: str, year: int) -> bool:
    entry = manifest["entries"].get(_entry_key(station, year))
    path = root / station / f"{year}.csv"
    return bool(entry) and path.is_file() and _sha256(path.read_bytes()) == entry["sha256"]


# ---------------------------------------------------------------------------
# Read helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoutineMetar:
    valid_utc: dt.datetime
    tmpf: int | None
    tgroup_c: float | None
    tmpf_source: str
    raw: str


def _as_utc(value: dt.date | dt.datetime) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    return dt.datetime.combine(value, dt.time(), dt.UTC)


def read_routine_metar(
    station: str, start: dt.date | dt.datetime, end: dt.date | dt.datetime, root: Path
) -> list[RoutineMetar]:
    """Routine METAR rows with ``start <= valid_utc < end`` (UTC), oldest first.

    Verifies every station-year file against the manifest sha256. A missing or corrupt
    station-year raises :class:`RoutineMetarError`; nothing is ever fabricated. A window reaching
    the sealed holdout is refused.
    """
    lo, hi = _as_utc(start), _as_utc(end)
    if hi > _as_utc(HOLDOUT_START):
        raise RoutineMetarError(f"window ends {hi.isoformat()}, past the sealed holdout")
    if hi <= lo:
        return []
    manifest = _load_manifest(root)
    out: list[RoutineMetar] = []
    for year in range(lo.year, (hi - _MIN).year + 1):
        path = root / station / f"{year}.csv"
        entry = manifest["entries"].get(_entry_key(station, year))
        if entry is None or not path.is_file():
            raise RoutineMetarError(f"{station} {year}: not in the routine-METAR archive")
        data = path.read_bytes()
        if _sha256(data) != entry["sha256"]:
            raise RoutineMetarError(f"{station} {year}: sha256 does not match the manifest")
        for record in csv.DictReader(io.StringIO(data.decode("utf-8"))):
            when = dt.datetime.strptime(record["valid_utc"], "%Y-%m-%dT%H:%MZ").replace(
                tzinfo=dt.UTC
            )
            if lo <= when < hi:
                out.append(
                    RoutineMetar(
                        when,
                        int(record["tmpf"]) if record["tmpf"] else None,
                        float(record["tgroup_c"]) if record["tgroup_c"] else None,
                        record["tmpf_source"],
                        record["metar"],
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Fetch leg
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoreRequest:
    station: str
    year: int
    start: dt.date
    end: dt.date
    url: str


def build_store_plan(
    stations: Sequence[str], years: Sequence[int], end_exclusive: dt.date
) -> list[StoreRequest]:
    if end_exclusive > HOLDOUT_START:
        raise RefusalError(f"--end-exclusive {end_exclusive} is past the sealed holdout")
    plan: list[StoreRequest] = []
    for station in stations:
        if station not in IEM_METAR_STATION_IDS:
            raise RefusalError(f"station {station!r} has no verified IEM METAR identifier")
        for year in years:
            start = dt.date(year, 1, 1)
            end = min(dt.date(year + 1, 1, 1), end_exclusive)
            if year < FIRST_YEAR or start >= end:
                raise RefusalError(f"year {year} has no days before {end_exclusive}")
            plan.append(StoreRequest(station, year, start, end, metar_url(station, start, end)))
    return plan


async def _fetch_all(
    todo: Sequence[StoreRequest],
    fetcher: MetarFetcher,
    clock: Callable[[], int],
    sleep: Callable[[float], Awaitable[None]],
    root: Path,
    manifest: dict[str, Any],
    results: dict[str, str],
) -> int:
    code = EXIT_OK
    for item in todo:
        key = _entry_key(item.station, item.year)
        if not _may_run(clock, 1):
            results[key] = "paused_launch_window"
            return EXIT_LAUNCH_WINDOW
        try:
            response: FetchedText = await _fetch_with_retry(fetcher, item.url, sleep)
        except RequestBudgetExceededError:
            results[key] = "budget_exhausted"
            return EXIT_ABORTED
        except TransportError as exc:
            results[key], code = f"fetch_error: {type(exc).__name__}", EXIT_FAILED
            continue
        if response.status_code != 200:
            results[key], code = f"http_{response.status_code}", EXIT_FAILED
            continue
        try:
            rows = [
                r for r in parse_metar_csv(response.text) if item.start <= r.valid.date() < item.end
            ]
        except ValueError as exc:
            results[key], code = f"bad_body: {exc}", EXIT_FAILED
            continue
        if not rows:
            results[key], code = "empty", EXIT_FAILED
            continue
        data = serialise_year(item.station, rows)
        atomic_write(root / item.station / f"{item.year}.csv", data)  # body first, manifest last
        manifest["entries"][key] = {
            "path": f"{item.station}/{item.year}.csv",
            "sha256": _sha256(data),
            "rows": len(rows),
            "window": [item.start.isoformat(), item.end.isoformat()],
            "fetched_at": _now(clock).isoformat(),
        }
        atomic_write(
            root / MANIFEST_NAME, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        )
        results[key] = "fetched"
    return code


def _run_fetch(
    args: argparse.Namespace,
    report: dict[str, Any],
    clock: Callable[[], int],
    fetcher: MetarFetcher | None,
    sleep: Callable[[float], Awaitable[None]],
) -> int:
    plan = build_store_plan(args.stations, args.years, args.end_exclusive)
    root: Path = args.archive_root
    manifest = _load_manifest(root)
    cached = [p for p in plan if _is_cached(root, manifest, p.station, p.year)]
    todo = [p for p in plan if p not in cached]
    report.update(
        planned_station_years=len(plan),
        cached_station_years=len(cached),
        planned_requests=len(todo),
        plan=[{"station": p.station, "year": p.year, "url": p.url} for p in todo],
        archive_root=str(root),
    )
    if not args.apply:
        report["status"] = "dry_run"
        return EXIT_OK
    if os.environ.get(LIVE_ENV_VAR) != "1":
        raise RefusalError(f"{LIVE_ENV_VAR}=1 is required before this tool may dispatch a request")
    if todo and (not args.request_budget or args.request_budget < len(todo)):
        raise RefusalError(f"--request-budget must be given and cover the {len(todo)} requests")
    if todo and not _may_run(clock, len(todo)):
        report["status"] = "refused_launch_window"
        return EXIT_LAUNCH_WINDOW
    results = {_entry_key(p.station, p.year): "cached" for p in cached}
    root.mkdir(parents=True, exist_ok=True)
    with open(root / LOCK_NAME, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            report["status"] = "store_busy"
            return EXIT_ABORTED
        resolved = fetcher or MetarTransport(
            budget=RequestBudget(limit=args.request_budget or 1),
            pacer=IemPacer(clock=clock, min_interval_ns=PACING_NS),
            clock=clock,
        )
        code = asyncio.run(_fetch_all(todo, resolved, clock, sleep, root, manifest, results))
    report["results"] = dict(sorted(results.items()))
    report["status"] = {EXIT_OK: "complete", EXIT_ABORTED: "budget_exhausted"}.get(code, "partial")
    if code == EXIT_LAUNCH_WINDOW:
        report["status"] = "paused_launch_window"
    return code


# ---------------------------------------------------------------------------
# Re-derive leg
# ---------------------------------------------------------------------------

REDERIVE_TAG: Final[str] = "live_t_group_parser/v1"
_KIND_TGROUP_LOST: Final[str] = "tgroup_to_column"
_KIND_TGROUP_GAINED: Final[str] = "column_or_missing_to_tgroup"
_KIND_TGROUP_CHANGED: Final[str] = "tgroup_value_changed"


def _rederive_record(record: Mapping[str, str]) -> tuple[dict[str, str], str | None]:
    """The row recomputed from its raw METAR, and the kind of change (``None`` if unchanged)."""
    out = dict(record)
    tenths = parse_tgroup_tenths(record["metar"])
    was_tgroup = record["tmpf_source"] == "tgroup"
    if tenths is not None:
        out.update(
            tmpf=str(tgroup_to_f(tenths)), tgroup_c=f"{tenths / 10:.1f}", tmpf_source="tgroup"
        )
    elif was_tgroup:
        out.update(tgroup_c="", tmpf_source="column")
    if out == dict(record):
        return out, None
    if tenths is None:
        return out, _KIND_TGROUP_LOST
    return out, _KIND_TGROUP_CHANGED if was_tgroup else _KIND_TGROUP_GAINED


def _rederive_year(data: bytes) -> tuple[bytes, Counter[str], int]:
    """New CSV bytes, the change counts by kind, and the row count of one stored station-year."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise RoutineMetarError(f"unexpected store columns {reader.fieldnames}")
    kinds: Counter[str] = Counter()
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    total = 0
    for record in reader:
        total += 1
        row, kind = _rederive_record(record)
        if kind is not None:
            kinds[kind] += 1
        writer.writerow([row[column] for column in COLUMNS])
    return out.getvalue().encode("utf-8"), kinds, total


def _verified_year(root: Path, manifest: Mapping[str, Any], station: str, year: int) -> bytes:
    entry = manifest["entries"].get(_entry_key(station, year))
    path = root / station / f"{year}.csv"
    if entry is None or not path.is_file():
        raise RoutineMetarError(f"{station} {year}: not in the routine-METAR archive")
    data = path.read_bytes()
    if _sha256(data) != entry["sha256"]:
        raise RoutineMetarError(f"{station} {year}: sha256 does not match the manifest")
    return data


def _run_rederive(args: argparse.Namespace, report: dict[str, Any]) -> int:
    root: Path = args.archive_root
    manifest = _load_manifest(root)
    plan: list[tuple[str, int, bytes, bytes, Counter[str], int]] = []
    for station in args.stations:  # verify and compute everything before any write
        for year in args.years:
            old = _verified_year(root, manifest, station, year)
            new, kinds, total = _rederive_year(old)
            plan.append((station, year, old, new, kinds, total))
    totals: Counter[str] = Counter()
    per_year: dict[str, Any] = {}
    for station, year, _old, _new, kinds, total in plan:
        changed = sum(kinds.values())
        per_year[_entry_key(station, year)] = {"rows": total, "rows_changed": changed, **kinds}
        totals.update(kinds)
        totals["rows_total"] += total
        totals["rows_changed"] += changed
    report.update(
        archive_root=str(root),
        rows_total=totals["rows_total"],
        rows_changed=totals["rows_changed"],
        **{k: totals[k] for k in (_KIND_TGROUP_LOST, _KIND_TGROUP_GAINED, _KIND_TGROUP_CHANGED)},
        per_station_year=dict(sorted(per_year.items())),
    )
    if not args.apply:
        report["status"] = "dry_run"
        return EXIT_OK
    with open(root / LOCK_NAME, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            report["status"] = "store_busy"
            return EXIT_ABORTED
        for station, year, old, new, kinds, _total in plan:
            if not kinds or new == old:
                continue
            atomic_write(root / station / f"{year}.csv", new)  # body first, manifest last
            manifest["entries"][_entry_key(station, year)].update(
                sha256=_sha256(new), rederived=REDERIVE_TAG
            )
            atomic_write(
                root / MANIFEST_NAME,
                (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
            )
    report["status"] = "applied"
    return EXIT_OK


# ---------------------------------------------------------------------------
# Diagnostic leg
# ---------------------------------------------------------------------------


def f_to_c_tenths(fahrenheit: float) -> int:
    """degF to integer tenths of a degree C, round half up."""
    return math.floor((fahrenheit - 32) * 50 / 9 + 0.5)


def metar_exact_f_floor_ceil(tenths: int) -> tuple[int, int]:
    """Floor and ceiling of the exact degF of a tenths-C reading (integer arithmetic)."""
    numerator = tenths * 9 + 1600  # exact degF = numerator / 50
    return numerator // 50, -(-numerator // 50)


def variant_values(
    when: dt.datetime, tenths: int, onemin: Mapping[dt.datetime, float]
) -> dict[str, tuple[int, int]]:
    """``variant -> (derived value, METAR reference)`` for every variant computable at ``when``."""
    reference = round_half_up_f(tenths)
    out: dict[str, tuple[int, int]] = {}
    for offset in OFFSETS:
        value = onemin.get(when + offset * _MIN)
        if value is not None:
            out[f"offset{offset:+d}"] = (math.floor(value + 0.5), reference)
    here = onemin.get(when)
    if here is not None:
        floor_f, ceil_f = metar_exact_f_floor_ceil(tenths)
        out["metar_floor_vs_offset+0"] = (math.floor(here + 0.5), floor_f)
        out["metar_ceil_vs_offset+0"] = (math.floor(here + 0.5), ceil_f)
        out["roundtrip_c_tenths_offset+0"] = (round_half_up_f(f_to_c_tenths(here)), reference)
    window = [onemin.get(when + o * _MIN) for o in range(-4, 1)]
    if all(v is not None for v in window):
        values = [v for v in window if v is not None]
        mean = sum(values) / len(values)
        out["mean5_via_round_half_up_f"] = (round_half_up_f(f_to_c_tenths(mean)), reference)
        out["max5"] = (math.floor(max(values) + 0.5), reference)
        out["min5"] = (math.floor(min(values) + 0.5), reference)
    wide = [onemin.get(when + o * _MIN) for o in OFFSETS]
    present = [math.floor(v + 0.5) for v in wide if v is not None]
    if present:
        out["any_offset_-5..+2_equals"] = (
            reference if reference in present else present[0],
            reference,
        )
    return out


class DiagAccumulator:
    def __init__(self) -> None:
        self.diffs: dict[str, Counter[int]] = {}
        self.n_rows = 0
        self.years_missing: list[int] = []

    def add(self, when: dt.datetime, tenths: int, onemin: Mapping[dt.datetime, float]) -> None:
        self.n_rows += 1
        for name, (value, reference) in variant_values(when, tenths, onemin).items():
            self.diffs.setdefault(name, Counter())[value - reference] += 1

    def report(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, diffs in sorted(self.diffs.items()):
            n = sum(diffs.values())
            out[name] = {
                "n": n,
                "mismatch_rate": sum(c for d, c in diffs.items() if d) / n,
                "mean_signed_bias": sum(d * c for d, c in diffs.items()) / n,
                "max_abs_diff": max(abs(d) for d in diffs),
            }
        return {
            "variants": out,
            "n_metar_rows": self.n_rows,
            "years_missing_onemin": self.years_missing,
        }


def read_onemin_year(body: bytes) -> dict[dt.datetime, float]:
    reader = csv.reader(io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline=""))
    header = next(reader, None)
    if header is None or "valid(UTC)" not in header or "tmpf" not in header:
        raise ValueError("1-min payload has no valid(UTC)/tmpf header")
    i_valid, i_tmpf = header.index("valid(UTC)"), header.index("tmpf")
    out: dict[dt.datetime, float] = {}
    for record in reader:
        cell = record[i_tmpf].strip()
        if cell and cell != "M":
            out[dt.datetime.fromisoformat(record[i_valid]).replace(tzinfo=dt.UTC)] = float(cell)
    return out


def _run_diag(
    args: argparse.Namespace, report: dict[str, Any], onemin_reader: OneMinReader | None
) -> int:
    reader = onemin_reader if onemin_reader is not None else cache_onemin_reader(args.asos_root)
    stations: dict[str, Any] = {}
    for station in args.stations:
        acc = DiagAccumulator()
        for year in args.years:
            end = min(dt.date(year + 1, 1, 1), HOLDOUT_START)
            rows = read_routine_metar(station, dt.date(year, 1, 1), end, args.archive_root)
            body = reader(station, year)
            if body is None:
                acc.years_missing.append(year)
                continue
            onemin = read_onemin_year(body)
            for row in rows:
                if row.tgroup_c is not None:
                    acc.add(row.valid_utc, round(row.tgroup_c * 10), onemin)
        stations[station] = acc.report()
    report["stations"] = stations
    report["status"] = "complete"
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="persist routine METAR per station-year")
    mode = fetch.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true", help=f"needs {LIVE_ENV_VAR}=1")
    fetch.add_argument("--request-budget", type=int, default=None)
    fetch.add_argument("--end-exclusive", type=dt.date.fromisoformat, default=HOLDOUT_START)
    diag = sub.add_parser("diag", help="offline 1-min derivation diagnostic")
    diag.add_argument("--asos-root", type=Path, default=DEFAULT_ASOS_ROOT)
    rederive = sub.add_parser("rederive", help="offline re-parse of the stored raw METAR column")
    redo = rederive.add_mutually_exclusive_group(required=True)
    redo.add_argument("--dry-run", action="store_true")
    redo.add_argument("--apply", action="store_true", help="rewrite changed station-years")
    for command in (fetch, diag, rederive):
        command.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
        command.add_argument("--report-json", type=Path, required=True)
        command.add_argument("--stations", nargs="+", default=list(DEFAULT_STATIONS))
        command.add_argument(
            "--years", nargs="+", type=int, default=list(range(FIRST_YEAR, LAST_YEAR + 1))
        )
    return parser.parse_args(list(argv))


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], int] | None = None,
    fetcher: MetarFetcher | None = None,
    onemin_reader: OneMinReader | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> int:
    """``clock``, ``fetcher``, ``onemin_reader`` and ``sleep`` are test seams, never CLI flags."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    resolved_clock = clock if clock is not None else time.time_ns
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "command": args.command,
        "generated_at": _now(resolved_clock).isoformat(),
        "mode": "apply" if getattr(args, "apply", False) else "dry_run_or_offline",
        "status": "started",
        "holdout_start": HOLDOUT_START.isoformat(),
    }
    try:
        if args.command == "diag":
            code = _run_diag(args, report, onemin_reader)
        elif args.command == "rederive":
            code = _run_rederive(args, report)
        elif not _may_run(resolved_clock, 1):
            report["status"] = "refused_launch_window"
            code = EXIT_LAUNCH_WINDOW
        else:
            code = _run_fetch(args, report, resolved_clock, fetcher, sleep or asyncio.sleep)
    except Exception as exc:  # noqa: BLE001 - the report is always written (exit 2)
        report["status"], report["error"] = "error", f"{type(exc).__name__}: {exc}"
        print(f"refused: {exc}", file=sys.stderr)
        code = EXIT_REFUSED
    report["exit_code"] = code
    try:
        write_report(args.report_json, report)
    except OSError as exc:
        print(f"report not written: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if code == EXIT_OK and args.command == "diag":
        for station, body in report["stations"].items():
            for name, stats in body["variants"].items():
                print(f"{station} {name} n={stats['n']} mismatch={stats['mismatch_rate']:.4f}")
    elif code == EXIT_OK and args.command == "rederive":
        print(f"rows_total={report['rows_total']} rows_changed={report['rows_changed']}")
    elif code == EXIT_OK and not getattr(args, "apply", False):
        print(
            f"planned_requests={report['planned_requests']} cached={report['cached_station_years']}"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
