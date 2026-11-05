"""LADDER_EV §12 C12 pre-check: afternoon Depth10 coverage census.

Cites `docs/strategies/breezy_strategy_ladder_ev_2026-09-07.md` §12. Counts
afternoon-covered listed station-days in the train window before any fill
simulation. If that count is < 15, the structural-dead branch is UNREACHABLE
and the result is INSUFFICIENT DATA, not KILL.

COVERED = span of distinct Depth10 ``ts_event`` instants inside
``[12:00, 17:00)`` LST ≥ 30 min (0–1 instants ⇒ 0), union across HIGH rungs.
Offsets from ``src/breezy/registry/sites.toml`` ``std_utc_offset_hours``
(LST, never DST). Instrument-dir grammar from
``src/breezy/adapters/polymarket_us/symbology.py`` ``_WEATHER_SLUG_RE`` +
venue suffix. Best-ask skips size-0 / price-0 pad
(``src/breezy/strategy/depth10.py:best_order``).

Writes ``census.json`` / ``census.md`` under ``--out-dir`` only (default
``~/.local/share/breezy/derived/ladder_ev/coverage/``, created if missing).
Never writes the catalog.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import resource
import time
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

CATALOG = Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
DEPTH_ROOT = CATALOG / "data" / "order_book_depths"
QUOTE_ROOT = CATALOG / "data" / "quote_tick"

#: Env override for the containment root -- same shape as
#: `scripts/analysis/whole_tape_paper_replay.py` (`BREEZY_DERIVED_ROOT`).
DERIVED_ROOT_ENV_VAR = "BREEZY_DERIVED_ROOT"
DEFAULT_START = dt.date(2026, 8, 30)
DEFAULT_END = dt.date(2026, 9, 6)
DEFAULT_HOLDOUT_DAYS = 2

STATIONS = ("LAX", "SFO", "MDW", "MIA", "NYC")
# src/breezy/registry/sites.toml std_utc_offset_hours (LST, never DST)
OFFSETS: dict[str, float] = {
    "LAX": -8.0,
    "SFO": -8.0,
    "MDW": -6.0,
    "MIA": -5.0,
    "NYC": -5.0,
}
EXCLUDED = frozenset({"NYC"})
WINDOW_START = dt.time(12, 0)
WINDOW_END = dt.time(17, 0)
MIN_SPAN_MINUTES = 30.0
FIXED = 10**16  # nautilus_trader.model.objects.FIXED_SCALAR
ASK_LO = 0.05
ASK_HI = 0.95
MIN_SZ = 1.0

# instrument-dir grammar: tc-temp-<city><measure>-<YYYY-MM-DD>-<bounds>.POLYMARKET_US
# src/breezy/adapters/polymarket_us/symbology.py _WEATHER_SLUG_RE + venue suffix
DIR_RE = re.compile(
    r"^tc-temp-(?P<city>[a-z]{3})(?P<measure>high|low)"
    r"-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"-(?P<bounds>[a-z0-9]+)\.POLYMARKET_US$"
)
FILE_RE = re.compile(
    r"^(?P<a>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-(?P<afrac>\d+)Z_"
    r"(?P<b>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-(?P<bfrac>\d+)Z\.parquet$"
)


def default_derived_root() -> Path:
    """The derived directory every other systemd job writes under.

    Mirrors `whole_tape_paper_replay.default_derived_root`: `$BREEZY_DERIVED_ROOT`
    if set, else ``~/.local/share/breezy/derived``.
    """
    override = os.environ.get(DERIVED_ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "breezy" / "derived"


def default_out_dir() -> Path:
    return default_derived_root() / "ladder_ev" / "coverage"


def climate_day_range(start: dt.date, end: dt.date) -> list[dt.date]:
    n = (end - start).days + 1
    return [start + dt.timedelta(days=i) for i in range(n)]


def holdout_split(days: list[dt.date], holdout_days: int) -> tuple[set[str], set[str]]:
    n_hold = min(holdout_days, len(days))
    hold = days[-n_hold:] if n_hold else []
    hold_iso = {d.isoformat() for d in hold}
    train_iso = {d.isoformat() for d in days if d.isoformat() not in hold_iso}
    return train_iso, hold_iso


def _mmdd_span(dates: list[dt.date]) -> str:
    if not dates:
        return "—"
    first = dates[0].strftime("%m-%d")
    last = dates[-1].strftime("%m-%d")
    return first if first == last else f"{first}..{last}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "Directory for census.json and census.md (created if missing). "
            "Default: <derived>/ladder_ev/coverage/ where derived is "
            "$BREEZY_DERIVED_ROOT or ~/.local/share/breezy/derived."
        ),
    )
    parser.add_argument(
        "--start",
        type=dt.date.fromisoformat,
        default=DEFAULT_START,
        help="Inclusive climate-day start (YYYY-MM-DD). Default: 2026-08-30.",
    )
    parser.add_argument(
        "--end",
        type=dt.date.fromisoformat,
        default=DEFAULT_END,
        help="Inclusive climate-day end (YYYY-MM-DD). Default: 2026-09-06.",
    )
    parser.add_argument(
        "--holdout-days",
        type=int,
        default=DEFAULT_HOLDOUT_DAYS,
        help="Trailing climate days reserved as holdout. Default: 2.",
    )
    return parser.parse_args(argv)


def lst_tz(offset_hours: float) -> dt.timezone:
    return dt.timezone(dt.timedelta(hours=offset_hours))


def window_utc(climate_day: dt.date, offset_hours: float) -> tuple[dt.datetime, dt.datetime]:
    tz = lst_tz(offset_hours)
    start = dt.datetime.combine(climate_day, WINDOW_START, tzinfo=tz).astimezone(dt.UTC)
    end = dt.datetime.combine(climate_day, WINDOW_END, tzinfo=tz).astimezone(dt.UTC)
    return start, end


def parse_file_span(name: str) -> tuple[dt.datetime, dt.datetime] | None:
    m = FILE_RE.match(name)
    if m is None:
        return None

    def parse_one(stamp: str, frac: str) -> dt.datetime:
        aware = dt.datetime.strptime(stamp, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=dt.UTC)
        ns = int(frac)
        # frac is leftover ns digits after whole seconds in the filename
        # e.g. 916533210 from ...40-916533210Z
        micro = ns // 1000
        return aware + dt.timedelta(microseconds=micro)

    return parse_one(m.group("a"), m.group("afrac")), parse_one(m.group("b"), m.group("bfrac"))


def file_may_overlap(path: Path, start: dt.datetime, end: dt.datetime) -> bool:
    span = parse_file_span(path.name)
    if span is None:
        return True
    a, b = span
    return a < end and b >= start


def i128_le(b: bytes) -> int:
    return int.from_bytes(b, "little", signed=True)


def raw_to_float(b: bytes) -> float:
    return i128_le(b) / FIXED


def best_ask(
    price_bytes: list[bytes], size_bytes: list[bytes]
) -> tuple[float | None, float | None]:
    """Skip size-0 / price-0 pad (depth10.py:best_order)."""
    for pb, sb in zip(price_bytes, size_bytes, strict=True):
        px = raw_to_float(pb)
        sz = raw_to_float(sb)
        if sz > 0.0:
            return px, sz
    return None, None


def index_dirs(root: Path) -> dict[tuple[str, dt.date, str], list[Path]]:
    """(STATION, climate_day, measure) -> instrument dirs."""
    out: dict[tuple[str, dt.date, str], list[Path]] = defaultdict(list)
    if not root.is_dir():
        return out
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        m = DIR_RE.match(entry.name)
        if m is None:
            continue
        city = m.group("city").upper()
        day = dt.date(int(m.group("year")), int(m.group("month")), int(m.group("day")))
        out[(city, day, m.group("measure"))].append(entry)
    return out


def parquet_files(instrument_dir: Path) -> list[Path]:
    return sorted(p for p in instrument_dir.iterdir() if p.suffix == ".parquet" and p.is_file())


def read_ts_event(path: Path) -> list[int]:
    pf = pq.ParquetFile(path)
    tbl = pf.read(columns=["ts_event"])
    return tbl.column("ts_event").to_pylist()


def read_ts_and_ask(path: Path) -> list[tuple[int, float | None, float | None]]:
    cols = (
        ["ts_event"] + [f"ask_price_{i}" for i in range(10)] + [f"ask_size_{i}" for i in range(10)]
    )
    pf = pq.ParquetFile(path)
    tbl = pf.read(columns=cols)
    ts = tbl.column("ts_event").to_pylist()
    prices = [tbl.column(f"ask_price_{i}").to_pylist() for i in range(10)]
    sizes = [tbl.column(f"ask_size_{i}").to_pylist() for i in range(10)]
    rows: list[tuple[int, float | None, float | None]] = []
    n = len(ts)
    for i in range(n):
        px, sz = best_ask([prices[k][i] for k in range(10)], [sizes[k][i] for k in range(10)])
        rows.append((ts[i], px, sz))
    return rows


def ns_to_utc(ns: int) -> dt.datetime:
    seconds, rem = divmod(ns, 1_000_000_000)
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(microseconds=rem // 1_000)


def in_window(ts_lst: dt.datetime, climate_day: dt.date) -> bool:
    return ts_lst.date() == climate_day and WINDOW_START <= ts_lst.time() < WINDOW_END


def census_one(
    city: str,
    day: dt.date,
    dirs: list[Path],
    *,
    want_asks: bool,
) -> dict:
    offset = OFFSETS[city]
    tz = lst_tz(offset)
    wstart, wend = window_utc(day, offset)
    n_rungs = len(dirs)
    window_ts: list[int] = []
    # per-rung window frames for snapshots: list of (ts_ns, px, sz)
    per_rung: dict[str, list[tuple[int, float | None, float | None]]] = {}
    files_read = 0
    files_skipped = 0
    for idir in dirs:
        iid = idir.name
        rung_rows: list[tuple[int, float | None, float | None]] = []
        for f in parquet_files(idir):
            if not file_may_overlap(f, wstart, wend):
                files_skipped += 1
                continue
            files_read += 1
            if want_asks:
                for ts_ns, px, sz in read_ts_and_ask(f):
                    ts_lst = ns_to_utc(ts_ns).astimezone(tz)
                    if in_window(ts_lst, day):
                        window_ts.append(ts_ns)
                        rung_rows.append((ts_ns, px, sz))
            else:
                for ts_ns in read_ts_event(f):
                    ts_lst = ns_to_utc(ts_ns).astimezone(tz)
                    if in_window(ts_lst, day):
                        window_ts.append(ts_ns)
        if want_asks:
            per_rung[iid] = rung_rows
    n_frames = len(window_ts)
    distinct = sorted(set(window_ts))
    n_distinct = len(distinct)
    minute_buckets: set[tuple[int, int, int, int, int]] = set()
    for ts_ns in distinct:
        t = ns_to_utc(ts_ns).astimezone(tz)
        minute_buckets.add((t.year, t.month, t.day, t.hour, t.minute))
    n_minutes = len(minute_buckets)
    if n_distinct < 2:
        span = 0.0
        first_lst = None
        last_lst = None
    else:
        first = ns_to_utc(distinct[0]).astimezone(tz)
        last = ns_to_utc(distinct[-1]).astimezone(tz)
        span = (last - first).total_seconds() / 60.0
        first_lst = first.isoformat()
        last_lst = last.isoformat()
    covered = span >= MIN_SPAN_MINUTES
    snapshots: dict[str, list[dict]] = {}
    if want_asks and covered:
        for label, hour in (("13:00", 13), ("15:00", 15)):
            target = dt.datetime.combine(day, dt.time(hour, 0), tzinfo=tz).astimezone(dt.UTC)
            target_ns = int(target.timestamp() * 1_000_000_000)
            rows_out: list[dict] = []
            for iid in sorted(per_rung):
                frames = per_rung[iid]
                if not frames:
                    rows_out.append(
                        {
                            "instrument_id": iid,
                            "ask": None,
                            "size": None,
                            "frame_lst": None,
                            "delta_min": None,
                        }
                    )
                    continue
                nearest = min(frames, key=lambda r: abs(r[0] - target_ns))
                frame_lst = ns_to_utc(nearest[0]).astimezone(tz)
                delta_min = (frame_lst.astimezone(dt.UTC) - target).total_seconds() / 60.0
                px, sz = nearest[1], nearest[2]
                in_band = (
                    px is not None and sz is not None and ASK_LO < px < ASK_HI and sz >= MIN_SZ
                )
                rows_out.append(
                    {
                        "instrument_id": iid,
                        "ask": px,
                        "size": sz,
                        "frame_lst": frame_lst.isoformat(),
                        "delta_min": round(delta_min, 3),
                        "in_band": in_band,
                    }
                )
            snapshots[label] = rows_out
    return {
        "station": city,
        "climate_day": day.isoformat(),
        "excluded": city in EXCLUDED,
        "listed_rung_count": n_rungs,
        "depth_frames_in_window": n_frames,
        "distinct_instants": n_distinct,
        "minutes_covered_distinct_buckets": n_minutes,
        "span_minutes": round(span, 3),
        "first_frame_lst": first_lst,
        "last_frame_lst": last_lst,
        "covered": covered,
        "files_read": files_read,
        "files_skipped_by_name": files_skipped,
        "snapshots": snapshots,
    }


def quote_tick_window_count(dirs: list[Path], city: str, day: dt.date) -> tuple[int, int]:
    """Return (n_frames_in_window, n_distinct_ts) from quote_tick for the same dirs-by-name."""
    offset = OFFSETS[city]
    tz = lst_tz(offset)
    wstart, wend = window_utc(day, offset)
    window_ts: list[int] = []
    for idir in dirs:
        if not idir.is_dir():
            continue
        for f in parquet_files(idir):
            if not file_may_overlap(f, wstart, wend):
                continue
            for ts_ns in read_ts_event(f):
                ts_lst = ns_to_utc(ts_ns).astimezone(tz)
                if in_window(ts_lst, day):
                    window_ts.append(ts_ns)
    return len(window_ts), len(set(window_ts))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.end < args.start:
        raise SystemExit(f"--end {args.end.isoformat()} is before --start {args.start.isoformat()}")
    if args.holdout_days < 0:
        raise SystemExit("--holdout-days must be >= 0")
    days = climate_day_range(args.start, args.end)
    train_days, hold_days = holdout_split(days, args.holdout_days)
    out_dir = (args.out_dir or default_out_dir()).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    depth_index = index_dirs(DEPTH_ROOT)
    quote_index = index_dirs(QUOTE_ROOT)
    unparsed_depth = []
    if DEPTH_ROOT.is_dir():
        for entry in DEPTH_ROOT.iterdir():
            if entry.is_dir() and DIR_RE.match(entry.name) is None:
                unparsed_depth.append(entry.name)
    rows: list[dict] = []
    for city in STATIONS:
        for day in days:
            high_dirs = sorted(depth_index.get((city, day, "high"), []), key=lambda p: p.name)
            low_dirs = depth_index.get((city, day, "low"), [])
            row = census_one(city, day, high_dirs, want_asks=False)
            row["listed_low_rung_count"] = len(low_dirs)
            # quote_tick listed high dirs
            q_high = quote_index.get((city, day, "high"), [])
            row["quote_tick_listed_rung_count"] = len(q_high)
            rows.append(row)
    # second pass: snapshots only for covered
    covered_keys = {(r["station"], r["climate_day"]) for r in rows if r["covered"]}
    snap_rows: list[dict] = []
    for city in STATIONS:
        for day in days:
            if (city, day.isoformat()) not in covered_keys:
                continue
            high_dirs = sorted(depth_index.get((city, day, "high"), []), key=lambda p: p.name)
            snap_rows.append(census_one(city, day, high_dirs, want_asks=True))
    snap_by_key = {(r["station"], r["climate_day"]): r for r in snap_rows}
    for r in rows:
        extra = snap_by_key.get((r["station"], r["climate_day"]))
        if extra is not None:
            r["snapshots"] = extra["snapshots"]
            # refresh window stats from the ask pass (same filter)
            for k in (
                "depth_frames_in_window",
                "distinct_instants",
                "minutes_covered_distinct_buckets",
                "span_minutes",
                "first_frame_lst",
                "last_frame_lst",
                "covered",
                "files_read",
                "files_skipped_by_name",
            ):
                r[k] = extra[k]
        # quote_tick window for listed days only (cheap ts_event)
        if r["listed_rung_count"] > 0:
            q_dirs = quote_index.get(
                (r["station"], dt.date.fromisoformat(r["climate_day"]), "high"), []
            )
            q_frames, q_distinct = quote_tick_window_count(
                q_dirs, r["station"], dt.date.fromisoformat(r["climate_day"])
            )
            r["quote_tick_frames_in_window"] = q_frames
            r["quote_tick_distinct_instants"] = q_distinct
        else:
            r["quote_tick_frames_in_window"] = 0
            r["quote_tick_distinct_instants"] = 0

    elapsed = time.perf_counter() - t0
    ru = resource.getrusage(resource.RUSAGE_SELF)
    rss_mb = ru.ru_maxrss / 1024.0  # Linux: kilobytes
    payload = {
        "catalog": str(CATALOG),
        "depth_root": str(DEPTH_ROOT),
        "quote_root": str(QUOTE_ROOT),
        "rule": {
            "window": "[12:00, 17:00) LST",
            "covered": "span of distinct Depth10 ts_event in window >= 30 min; 0-1 instants => 0",
            "listed": "instrument dir startswith tc-temp-{city.lower()}high-{day}-",
            "offsets": OFFSETS,
        },
        "unparsed_depth_dirs": unparsed_depth,
        "runtime_s": round(elapsed, 3),
        "rss_mb": round(rss_mb, 1),
        "rows": rows,
    }
    (out_dir / "census.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # compact markdown tables
    lines = []
    lines.append(
        "| stn | climate_day | listed | frames | dist_ts | min_bkts | "
        "span_min | first_LST | last_LST | COVERED | note |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---|---|---|---|")
    for r in rows:
        note = "EXCLUDED" if r["excluded"] else ""
        if r["listed_rung_count"] == 0:
            note = (note + " unlisted").strip()
        first = r["first_frame_lst"] or "—"
        last = r["last_frame_lst"] or "—"
        cov = "YES" if r["covered"] else "no"
        lines.append(
            f"| {r['station']} | {r['climate_day']} | {r['listed_rung_count']} | "
            f"{r['depth_frames_in_window']} | {r['distinct_instants']} | "
            f"{r['minutes_covered_distinct_buckets']} | {r['span_minutes']:.1f} | "
            f"{first} | {last} | {cov} | {note} |"
        )
    family = [r for r in rows if not r["excluded"]]
    covered_family = [r for r in family if r["covered"]]
    train = [r for r in covered_family if r["climate_day"] in train_days]
    hold = [r for r in covered_family if r["climate_day"] in hold_days]
    train_span = _mmdd_span([d for d in days if d.isoformat() in train_days])
    hold_span = _mmdd_span([d for d in days if d.isoformat() in hold_days])
    lines.append("")
    lines.append(
        f"family covered (LAX/SFO/MDW/MIA): {len(covered_family)}  "
        f"train {train_span}: {len(train)}  holdout {hold_span}: {len(hold)}  "
        f"train>=15: {len(train) >= 15}"
    )
    lines.append(f"runtime_s={payload['runtime_s']} rss_mb={payload['rss_mb']}")
    lines.append("")
    lines.append(
        "## snapshots (covered only; nearest in-window frame; * = ask in (0.05,0.95) and size>=1)"
    )
    for r in rows:
        if not r["covered"]:
            continue
        snaps = r.get("snapshots") or {}
        lines.append(f"### {r['station']} {r['climate_day']}  listed={r['listed_rung_count']}")
        for label in ("13:00", "15:00"):
            items = snaps.get(label, [])
            n_band = sum(1 for x in items if x.get("in_band"))
            bits = []
            for x in items:
                bounds = x["instrument_id"].split("-")[-1].removesuffix(".POLYMARKET_US")
                if x["ask"] is None:
                    bits.append(f"{bounds}=NA")
                    continue
                star = "*" if x.get("in_band") else ""
                bits.append(
                    f"{bounds}={x['ask']:.4g}/{x['size']:.4g}{star}(Δ{x['delta_min']:+.1f}m)"
                )
            lines.append(f"- {label} LST n_in_band={n_band}: " + "; ".join(bits))
    (out_dir / "census.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote {out_dir / 'census.json'} and census.md "
        f"runtime_s={payload['runtime_s']} rss_mb={payload['rss_mb']}"
    )
    print(f"family_covered={len(covered_family)} train={len(train)} hold={len(hold)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
