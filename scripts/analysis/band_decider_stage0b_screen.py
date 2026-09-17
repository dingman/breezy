#!/usr/bin/env python3
"""Stage 0b adverse-selection screen (read-only vs the Breezy repo).

Writes only under this directory. Streams the IEM 1-min archive per
station-month and discards each station-day after aggregation.
"""

from __future__ import annotations

import csv
import json
import math
import os
import resource
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

REPO = Path("/home/jon/breezy")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "analysis"))

from breezy.domain.season import season_for  # noqa: E402
from breezy.domain.temperature import max_rounded_f_below, round_half_up_f  # noqa: E402
from breezy.normalize.climate_day import climate_day_for_instant, standard_time_zone  # noqa: E402
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator  # noqa: E402

OUT = Path(__file__).resolve().parent
IEM_ROOT = Path(
    "/tmp/claude-1000/-home-jon-breezy/0d7dc236-f8bc-46ae-8418-026805446111/scratchpad/iem1min"
)
TAPE_PATH = Path.home() / ".local/share/breezy/catalog/quote_tape/decisions/offer_tape_2026-09-16.jsonl"
CATALOG_BASE = Path.home() / ".local/share/breezy/catalog"
STATIONS = ("MIA", "LAX", "SFO", "MDW")
OFFSETS: dict[str, float] = {"MIA": -5.0, "LAX": -8.0, "SFO": -8.0, "MDW": -6.0}
WINDOW_START_H = 12
WINDOW_END_H = 17  # exclusive
N_MIN = 90
Z_95 = 1.959963984540054
THETA = Decimal("0.06")
_CENT = Decimal("0.01")
_ONE = Decimal("1")
NS = 1_000_000_000
TARGET_MDW_MONTHS = 69
MDW_WAIT_S = 20 * 60
MDW_POLL_S = 60

# F→C: repo temperature.py only converts C→F (floor(x+0.5) half-up). §3 does
# not pin F→C; we use the same half-up direction, never banker's round().
def f_to_c_int(tmpf: int) -> int:
    return math.floor((tmpf - 32) * 5 / 9 + 0.5)


def f_to_c_tenths(tmpf: int) -> int:
    return math.floor((tmpf - 32) * 5 / 9 * 10 + 0.5)


def wilson_lower(k: int, n: int, z: float = Z_95) -> float | None:
    if n <= 0:
        return None
    phat = k / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2.0 * n)
    radius = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return (centre - radius) / denom


def fee_taker(ask: Decimal) -> Decimal:
    return (THETA * ask * (_ONE - ask)).quantize(_CENT, rounding=ROUND_HALF_EVEN)


def break_even(ask: Decimal) -> Decimal:
    return ask + fee_taker(ask)


def even_interior(value_f: int) -> tuple[int, int]:
    """Closed 2 °F interior on the even-phase partition: [2k, 2k+1]."""
    lo = value_f if value_f % 2 == 0 else value_f - 1
    return lo, lo + 1


def parse_yes_rung(instrument_id: str) -> tuple[int | None, int | None] | None:
    """Parse a YES-leg weather instrument to closed (lower_f, upper_f)."""
    import re

    m = re.match(
        r"^tc-temp-[a-z]+high-\d{4}-\d{2}-\d{2}-([a-z0-9]+)\.POLYMARKET_US$",
        instrument_id,
    )
    if m is None:
        return None
    band = m.group(1)
    low = re.match(r"^lt(\d+)f$", band)
    if low:
        return (None, int(low.group(1)) - 1)
    high = re.match(r"^gte(\d+)f$", band)
    if high:
        return (int(high.group(1)), None)
    interior = re.match(r"^gte(\d+)lt(\d+)f$", band)
    if interior is None:
        return None
    lower = int(interior.group(1))
    named = int(interior.group(2))
    if named != lower + 1:
        return None
    return (lower, lower + 1)


def rung_contains(bounds: tuple[int | None, int | None], value: int) -> bool:
    lo, hi = bounds
    if lo is not None and value < lo:
        return False
    return not (hi is not None and value > hi)


def wait_for_mdw() -> tuple[int, bool]:
    mdw = IEM_ROOT / "MDW"
    n = len(list(mdw.glob("*.csv"))) if mdw.is_dir() else 0
    if n >= TARGET_MDW_MONTHS or os.environ.get("STAGE0B_SKIP_MDW_WAIT") == "1":
        return n, n >= TARGET_MDW_MONTHS
    deadline = time.time() + MDW_WAIT_S
    while n < TARGET_MDW_MONTHS and time.time() < deadline:
        print(f"[stage0b] MDW months={n}; waiting {MDW_POLL_S}s", flush=True)
        time.sleep(MDW_POLL_S)
        n = len(list(mdw.glob("*.csv"))) if mdw.is_dir() else 0
    return n, n >= TARGET_MDW_MONTHS


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def load_cli_from_catalog() -> dict[str, dict[date, int]]:
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    from breezy.persistence.catalog import read_climate_days, station_catalog_path

    out: dict[str, dict[date, int]] = {s: {} for s in STATIONS}
    for city in STATIONS:
        path = station_catalog_path(CATALOG_BASE, "polymarket_us", city)
        records = read_climate_days(ParquetDataCatalog(str(path)))
        chosen: dict[date, tuple[int, object]] = {}
        for rec in records:
            if not rec.is_final or rec.is_superseded or rec.tmax_f is None:
                continue
            day = rec.climate_day
            prev = chosen.get(day)
            if prev is None or rec.revision_seq >= prev[0]:
                chosen[day] = (rec.revision_seq, rec.tmax_f)
        out[city] = {day: tmax for day, (_rev, tmax) in chosen.items()}
        print(
            f"[stage0b] catalog CLI {city}: {len(out[city])} finals",
            flush=True,
        )
    return out


def load_cli_from_afos() -> dict[str, dict[date, int]]:
    from pmr_climatology_study import load_cli_records
    from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
    from settlement_alignment_study import load_sites

    specs = {spec.city: spec for spec in load_sites() if spec.city in STATIONS}
    cache = Path(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR)
    out: dict[str, dict[date, int]] = {s: {} for s in STATIONS}
    # Cached AFOS zips are year-chunked. 2021-2025 is the study corpus and is
    # on disk; 2026 is not (catalog parquet covers that tail). A single
    # 2021-2026 call misses the 2026 zip and refuses the whole station.
    windows = (
        (date(2021, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 9, 16)),
    )
    for city in STATIONS:
        spec = specs.get(city)
        if spec is None:
            print(f"[stage0b] AFOS: no SiteSpec for {city}", flush=True)
            continue
        mapped: dict[date, int] = {}
        for start, end in windows:
            try:
                finals, _every, _drops = load_cli_records(
                    cache_dir=cache, spec=spec, start=start, end=end
                )
            except SystemExit as exc:
                print(f"[stage0b] AFOS {city} {start}..{end} refused: {exc}", flush=True)
                continue
            except FileNotFoundError as exc:
                print(f"[stage0b] AFOS {city} {start}..{end} miss: {exc}", flush=True)
                continue
            mapped.update(
                {
                    day: rec.tmax_f
                    for day, rec in finals.items()
                    if rec.tmax_f is not None
                }
            )
        out[city] = mapped
        print(f"[stage0b] AFOS CLI {city}: {len(mapped)} finals", flush=True)
    return out


def merge_finals(
    catalog: dict[str, dict[date, int]], afos: dict[str, dict[date, int]]
) -> dict[str, dict[date, int]]:
    merged: dict[str, dict[date, int]] = {}
    for city in STATIONS:
        m = dict(afos.get(city, {}))
        m.update(catalog.get(city, {}))  # catalog wins on overlap
        merged[city] = m
    return merged


def iem_months(station: str) -> list[Path]:
    d = IEM_ROOT / station
    if not d.is_dir():
        return []
    return sorted(d.glob("*.csv"))


def parse_iem_month(path: Path, station: str) -> dict[date, list[tuple[datetime, int]]]:
    """Stream one monthly CSV into climate-day buckets of (utc, tmpf)."""
    offset = OFFSETS[station]
    by_day: dict[date, list[tuple[datetime, int]]] = defaultdict(list)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw = row.get("tmpf", "")
            if raw in ("", "M", "m"):
                continue
            try:
                tmpf = int(float(raw))
            except ValueError:
                continue
            raw_ts = row.get("valid(UTC)", "")
            try:
                utc = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            except ValueError:
                continue
            day = climate_day_for_instant(utc, offset)
            by_day[day].append((utc, tmpf))
    for day in by_day:
        by_day[day].sort(key=lambda item: item[0])
    return by_day


def synthesize_and_push(
    acc: RunningExtremeAccumulator, rows: list[tuple[datetime, int]]
) -> dict[str, int]:
    """Push 5-min integer-C samples plus :53 METAR tenths into `acc`."""
    stats = {"n_1min": len(rows), "n_5min": 0, "n_metar": 0, "n_skip_dup": 0}
    seen_5: set[int] = set()
    seen_53: set[int] = set()
    for utc, tmpf in rows:
        if utc.minute % 5 == 0:
            ns = int(utc.timestamp()) * NS
            if ns not in seen_5:
                c_int = f_to_c_int(tmpf)
                acc.push(ns, c_int * 10, 10, False, ns)
                seen_5.add(ns)
                stats["n_5min"] += 1
        if utc.minute == 53:
            ns = int(utc.timestamp()) * NS
            if ns not in seen_53:
                acc.push(ns, f_to_c_tenths(tmpf), 5, True, ns)
                seen_53.add(ns)
                stats["n_metar"] += 1
    return stats


def window_minutes(climate_day: date, offset: float) -> list[datetime]:
    tz = standard_time_zone(offset)
    start = datetime.combine(climate_day, datetime.min.time(), tzinfo=tz).replace(
        hour=WINDOW_START_H, minute=0
    )
    out: list[datetime] = []
    cur = start
    end = start.replace(hour=WINDOW_END_H, minute=0)
    while cur < end:
        out.append(cur)
        cur = cur + timedelta(minutes=1)
    return out


def m30_bucket(minutes_since: int) -> int:
    return (minutes_since // 30) * 30


# (station, season, hour, width, m30, year) -> [n, k_lower, k_upper, n_outside]
MinuteKey = tuple[str, str, int, int, int, int]


def process_station_days(
    station: str,
    finals: dict[date, int],
    minute_counts: dict[MinuteKey, list[int]],
    verify: dict[str, object],
) -> dict[str, int]:
    offset = OFFSETS[station]
    stats = {
        "months": 0,
        "days_with_obs": 0,
        "days_with_cli": 0,
        "days_scored": 0,
        "window_minutes": 0,
        "span_minutes": 0,
        "obs_rows": 0,
    }
    months = iem_months(station)
    stats["months"] = len(months)
    # Merge month files into days without holding the whole station in RAM:
    # process month by month, but a climate day can straddle UTC months, so
    # carry the last 2 days of the previous month.
    carry: dict[date, list[tuple[datetime, int]]] = {}
    all_month_stems = [p.stem for p in months]
    for idx, path in enumerate(months):
        by_day = parse_iem_month(path, station)
        stats["obs_rows"] += sum(len(v) for v in by_day.values())
        # merge carry
        for day, rows in carry.items():
            by_day.setdefault(day, []).extend(rows)
        # days that cannot straddle into the next file (all but the last 2)
        days_sorted = sorted(by_day)
        if idx < len(months) - 1:
            hold = set(days_sorted[-2:]) if len(days_sorted) >= 2 else set(days_sorted)
        else:
            hold = set()
        ready = [d for d in days_sorted if d not in hold]
        carry = {d: by_day[d] for d in hold}
        for day in ready:
            _score_one_day(
                station, offset, day, by_day[day], finals, minute_counts, verify, stats
            )
        print(
            f"[stage0b] {station} {path.stem}: days_ready={len(ready)} rss={rss_mb():.0f}MB",
            flush=True,
        )
    for day, rows in carry.items():
        _score_one_day(station, offset, day, rows, finals, minute_counts, verify, stats)
    verify[f"{station}_iem_months"] = all_month_stems
    return stats


def _score_one_day(
    station: str,
    offset: float,
    day: date,
    rows: list[tuple[datetime, int]],
    finals: dict[date, int],
    minute_counts: dict[MinuteKey, list[int]],
    verify: dict[str, object],
    stats: dict[str, int],
) -> None:
    stats["days_with_obs"] += 1
    settled = finals.get(day)
    if settled is None:
        # still record 09-15/09-16 bands for verification
        if day in (date(2026, 9, 15), date(2026, 9, 16)):
            _record_verify_band(station, offset, day, rows, verify, settled=None)
        return
    stats["days_with_cli"] += 1
    if not rows:
        return
    acc = RunningExtremeAccumulator(std_utc_offset_hours=offset)
    synthesize_and_push(acc, rows)
    season = season_for(day)
    year = day.year
    n_span = 0
    last_band = None
    for local in window_minutes(day, offset):
        now_ns = int(local.astimezone(UTC).timestamp()) * NS
        rm = acc.value_at(now_ns)
        if rm is None:
            continue
        stats["window_minutes"] += 1
        last_band = (rm.lower_f, rm.upper_f, rm.exact_f)
        if rm.lower_f == rm.upper_f:
            continue
        lo_r = even_interior(rm.lower_f)
        up_r = even_interior(rm.upper_f)
        if lo_r == up_r:
            continue
        stats["span_minutes"] += 1
        n_span += 1
        hour = local.hour
        minutes_since = (hour - WINDOW_START_H) * 60 + local.minute
        m30 = m30_bucket(minutes_since)
        width = rm.upper_f - rm.lower_f
        key: MinuteKey = (station, season, hour, width, m30, year)
        bucket = minute_counts[key]
        bucket[0] += 1
        if rung_contains(lo_r, settled):
            bucket[1] += 1
        if rung_contains(up_r, settled):
            bucket[2] += 1
        if (not rung_contains(lo_r, settled)) and (not rung_contains(up_r, settled)):
            bucket[3] += 1
    if n_span:
        stats["days_scored"] += 1
    if day in (date(2026, 9, 15), date(2026, 9, 16)):
        _record_verify_band(station, offset, day, rows, verify, settled=settled)
        verify[f"{station}_{day.isoformat()}_last_window_band"] = last_band
        verify[f"{station}_{day.isoformat()}_span_minutes"] = n_span


def _record_verify_band(
    station: str,
    offset: float,
    day: date,
    rows: list[tuple[datetime, int]],
    verify: dict[str, object],
    settled: int | None,
) -> None:
    acc = RunningExtremeAccumulator(std_utc_offset_hours=offset)
    syn = synthesize_and_push(acc, rows)
    tz = standard_time_zone(offset)
    snapshots = {}
    for hh, mm, label in ((12, 0, "open"), (13, 30, "m90"), (16, 59, "close")):
        local = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(
            hour=hh, minute=mm
        )
        now_ns = int(local.astimezone(UTC).timestamp()) * NS
        rm = acc.value_at(now_ns)
        snapshots[label] = None if rm is None else [rm.lower_f, rm.upper_f, rm.exact_f]
    verify[f"{station}_{day.isoformat()}_syn"] = syn
    verify[f"{station}_{day.isoformat()}_bands"] = snapshots
    verify[f"{station}_{day.isoformat()}_settled"] = settled
    verify[f"{station}_{day.isoformat()}_n_obs"] = len(rows)
    if rows:
        verify[f"{station}_{day.isoformat()}_first_utc"] = rows[0][0].isoformat()
        verify[f"{station}_{day.isoformat()}_last_utc"] = rows[-1][0].isoformat()


def unit_verify_bands() -> dict[str, object]:
    """Integer-C band for whole-°F values that produce the 09-16 tape bands."""

    def band_for_f(tmpf: int) -> tuple[int, int]:
        c = f_to_c_int(tmpf)
        tenths = c * 10
        lower = round_half_up_f(tenths - 5)
        upper = max_rounded_f_below(tenths + 5)
        return lower, upper

    checks = {
        "91F_MIA": band_for_f(91),
        "78F_LAX": band_for_f(78),
        "66F_SFO": band_for_f(66),
        "c_91": f_to_c_int(91),
        "c_78": f_to_c_int(78),
        "c_66": f_to_c_int(66),
        "c_65": f_to_c_int(65),
        "metar_91_tenths": f_to_c_tenths(91),
        "metar_91_rounded_f": round_half_up_f(f_to_c_tenths(91)),
    }
    return checks


def aggregate_table(
    minute_counts: dict[MinuteKey, list[int]],
) -> list[dict[str, object]]:
    # Merge years for the published table.
    merged: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for (station, season, hour, width, m30, _year), vals in minute_counts.items():
        key = (station, season, hour, width, m30)
        b = merged[key]
        for i in range(4):
            b[i] += vals[i]
    rows: list[dict[str, object]] = []
    for (station, season, hour, width, m30), (n, k_lo, k_up, n_out) in sorted(
        merged.items()
    ):
        outside = (n_out / n) if n else 0.0
        for cand, k in (("lower", k_lo), ("upper", k_up)):
            p = (k / n) if n else 0.0
            w = wilson_lower(k, n)
            rows.append(
                {
                    "station": station,
                    "season": season,
                    "hour_lst": hour,
                    "band_width_f": width,
                    "m30": m30,
                    "candidate": cand,
                    "n": n,
                    "k": k,
                    "p_hat": p,
                    "wilson_lower": w,
                    "wilson_or_na": w if n >= N_MIN else None,
                    "n_outside": n_out,
                    "outside_mass": outside,
                }
            )
    return rows


def write_table_csv(rows: list[dict[str, object]], path: Path) -> None:
    fields = [
        "station",
        "season",
        "hour_lst",
        "band_width_f",
        "m30",
        "candidate",
        "n",
        "k",
        "p_hat",
        "wilson_lower",
        "wilson_or_na",
        "n_outside",
        "outside_mass",
    ]
    with path.open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields)
        w.writeheader()
        for row in rows:
            out = dict(row)
            for key in ("p_hat", "wilson_lower", "wilson_or_na", "outside_mass"):
                val = out[key]
                out[key] = "" if val is None else f"{val:.10f}"
            w.writerow(out)


def table_lookup(
    index: dict[tuple, dict[str, object]],
    *,
    station: str,
    season: str,
    hour: int,
    width: int,
    m30: int,
    candidate: str,
) -> dict[str, object] | None:
    return index.get((station, season, hour, width, m30, candidate))


def ask_bucket(ask: Decimal) -> str:
    if ask < Decimal("0.25"):
        return "<0.25"
    if ask <= Decimal("0.75"):
        return "0.25-0.75"
    return ">0.75"


def score_tape(
    table_rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    index = {
        (
            r["station"],
            r["season"],
            r["hour_lst"],
            r["band_width_f"],
            r["m30"],
            r["candidate"],
        ): r
        for r in table_rows
    }
    buckets: dict[str, dict[str, list]] = {
        name: {"ask": [], "margin_pt": [], "margin_w": [], "defined_w": []}
        for name in ("<0.25", "0.25-0.75", ">0.75")
    }
    diag = {
        "n_jsonl": 0,
        "n_quote": 0,
        "n_first90": 0,
        "n_candidate": 0,
        "n_scored": 0,
        "n_missing_cell": 0,
        "n_no_ask": 0,
        "n_no_band": 0,
        "stations": defaultdict(int),
        "reasons_first90": defaultdict(int),
    }
    with TAPE_PATH.open() as handle:
        for line in handle:
            diag["n_jsonl"] += 1
            rec = json.loads(line)
            if rec.get("source") != "quote":
                continue
            diag["n_quote"] += 1
            station = rec["station"]
            if station not in OFFSETS:
                continue
            ts_ns = int(rec["ts_event"])
            offset = OFFSETS[station]
            instant = datetime.fromtimestamp(ts_ns / NS, tz=UTC)
            local = instant.astimezone(standard_time_zone(offset))
            minutes_since = (local.hour - WINDOW_START_H) * 60 + local.minute
            if minutes_since < 0 or minutes_since >= 90:
                continue
            if not (WINDOW_START_H <= local.hour < WINDOW_END_H):
                continue
            diag["n_first90"] += 1
            diag["reasons_first90"][rec.get("reason") or ""] += 1
            lower_s = rec.get("running_max_lower")
            upper_s = rec.get("running_max_upper")
            if lower_s is None or upper_s is None:
                diag["n_no_band"] += 1
                continue
            lower_f = int(Decimal(str(lower_s)))
            upper_f = int(Decimal(str(upper_s)))
            iid = rec["instrument_id"]
            parsed = parse_yes_rung(iid)
            if parsed is None:
                continue
            if lower_f == upper_f:
                continue
            lo_r = even_interior(lower_f)
            up_r = even_interior(upper_f)
            if lo_r == up_r:
                continue
            is_lo = rung_contains(parsed, lower_f) and not rung_contains(parsed, upper_f)
            is_up = rung_contains(parsed, upper_f) and not rung_contains(parsed, lower_f)
            if not is_lo and not is_up:
                continue
            diag["n_candidate"] += 1
            ask_s = rec.get("ask")
            if ask_s is None:
                diag["n_no_ask"] += 1
                continue
            ask = Decimal(str(ask_s))
            be = break_even(ask)
            climate_day = date.fromisoformat(rec["climate_day"])
            season = season_for(climate_day)
            hour = int(rec["hour_lst"])
            width = upper_f - lower_f
            m30 = m30_bucket(minutes_since)
            cand = "lower" if is_lo else "upper"
            cell = table_lookup(
                index,
                station=station,
                season=season,
                hour=hour,
                width=width,
                m30=m30,
                candidate=cand,
            )
            if cell is None:
                diag["n_missing_cell"] += 1
                p_hat = None
                w_na = None
            else:
                p_hat = float(cell["p_hat"])
                w_na = cell["wilson_or_na"]
            bucket_name = ask_bucket(ask)
            b = buckets[bucket_name]
            b["ask"].append(float(ask))
            if p_hat is None:
                b["margin_pt"].append(None)
            else:
                b["margin_pt"].append(p_hat - float(be))
            if w_na is None:
                b["margin_w"].append(None)
                b["defined_w"].append(False)
            else:
                b["margin_w"].append(float(w_na) - float(be))
                b["defined_w"].append(True)
            diag["n_scored"] += 1
            diag["stations"][station] += 1
    summary: dict[str, dict[str, object]] = {}
    for name, b in buckets.items():
        n = len(b["margin_pt"])
        pt_defined = [m for m in b["margin_pt"] if m is not None]
        pt_pos = sum(1 for m in pt_defined if m > 0)
        w_defined = [m for m in b["margin_w"] if m is not None]
        w_pos = sum(1 for m in w_defined if m > 0)
        summary[name] = {
            "rows": n,
            "rows_point_defined": len(pt_defined),
            "frac_pos_point": (pt_pos / n) if n else None,
            "median_margin_point": statistics.median(pt_defined) if pt_defined else None,
            "n_pos_point": pt_pos,
            "rows_wilson_defined": len(w_defined),
            "frac_pos_wilson": (w_pos / n) if n else None,
            "median_margin_wilson": statistics.median(w_defined) if w_defined else None,
            "n_pos_wilson": w_pos,
        }
    diag["stations"] = dict(diag["stations"])
    diag["reasons_first90"] = dict(diag["reasons_first90"])
    return summary, diag


def gate_verdict(summary_row: dict[str, object], *, wilson: bool) -> str:
    n = int(summary_row["rows"])
    if wilson:
        frac = summary_row["frac_pos_wilson"]
        med = summary_row["median_margin_wilson"]
    else:
        frac = summary_row["frac_pos_point"]
        med = summary_row["median_margin_point"]
    if n < 20 or frac is None or med is None:
        return "FAIL"
    if frac >= 0.50 and med >= 0.03:
        return "PASS"
    return "FAIL"


def stage2_preview(
    minute_counts: dict[MinuteKey, list[int]],
) -> dict[str, object]:
    # Coverage cells: (station, band_width, m30) in first 90 min, any season/hour/year.
    cov: dict[tuple[str, int, int], int] = defaultdict(int)
    for (station, _season, _hour, width, m30, _year), vals in minute_counts.items():
        if m30 not in (0, 30, 60):
            continue
        cov[(station, width, m30)] += vals[0]
    n_cells = len(cov)
    n_ge90 = sum(1 for n in cov.values() if n >= N_MIN)
    by_station = defaultdict(lambda: [0, 0])
    for (station, _w, _m), n in cov.items():
        by_station[station][0] += 1
        if n >= N_MIN:
            by_station[station][1] += 1

    # LOYO Brier over candidate-rows (each minute contributes two labels).
    by_cell_year: dict[tuple, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    # key without year: (station, season, hour, width, m30, cand) -> year -> [n,k]
    for (station, season, hour, width, m30, year), vals in minute_counts.items():
        n, k_lo, k_up, _out = vals
        for cand, k in (("lower", k_lo), ("upper", k_up)):
            by_cell_year[(station, season, hour, width, m30, cand)][year][0] += n
            by_cell_year[(station, season, hour, width, m30, cand)][year][1] += k

    brier_num = 0.0
    brier_den = 0
    citl_sum_p = defaultdict(float)
    citl_sum_y = defaultdict(float)
    citl_n = defaultdict(int)
    years_used = set()
    skipped_no_train = 0
    for key, per_year in by_cell_year.items():
        station = key[0]
        years = sorted(per_year)
        total_n = sum(per_year[y][0] for y in years)
        total_k = sum(per_year[y][1] for y in years)
        for y in years:
            n_y, k_y = per_year[y]
            n_tr = total_n - n_y
            k_tr = total_k - k_y
            if n_tr <= 0 or n_y <= 0:
                skipped_no_train += n_y
                continue
            p = k_tr / n_tr
            # Brier from cell counts
            brier_num += k_y * (p - 1.0) ** 2 + (n_y - k_y) * (p**2)
            brier_den += n_y
            citl_sum_p[station] += p * n_y
            citl_sum_y[station] += k_y
            citl_n[station] += n_y
            years_used.add(y)

    citl = {}
    for station in STATIONS:
        n = citl_n.get(station, 0)
        if n == 0:
            citl[station] = None
            continue
        citl[station] = {
            "n": n,
            "mean_p": citl_sum_p[station] / n,
            "mean_y": citl_sum_y[station] / n,
            "delta_p_minus_y": citl_sum_p[station] / n - citl_sum_y[station] / n,
        }

    first90_n_by_station = defaultdict(int)
    for (station, _s, _h, _w, m30, _y), vals in minute_counts.items():
        if m30 in (0, 30, 60):
            first90_n_by_station[station] += vals[0]

    return {
        "n_cov_cells": n_cells,
        "n_cov_cells_ge90": n_ge90,
        "frac_cells_ge90": (n_ge90 / n_cells) if n_cells else None,
        "cov_by_station": {s: {"n_cells": a, "n_ge90": b} for s, (a, b) in by_station.items()},
        "brier_loyo": (brier_num / brier_den) if brier_den else None,
        "brier_n": brier_den,
        "brier_years": sorted(years_used),
        "skipped_no_train": skipped_no_train,
        "citl": citl,
        "first90_span_minutes_by_station": dict(first90_n_by_station),
        "cov_cell_ns": [
            {"station": s, "band_width_f": w, "m30": m, "n": n}
            for (s, w, m), n in sorted(cov.items(), key=lambda kv: -kv[1])[:20]
        ],
    }


def fmt(x: object, nd: int = 4) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def write_report(
    *,
    iem_stats: dict[str, dict[str, int]],
    catalog_finals: dict[str, dict[date, int]],
    afos_finals: dict[str, dict[date, int]],
    merged_finals: dict[str, dict[date, int]],
    table_rows: list[dict[str, object]],
    tape_summary: dict[str, dict[str, object]],
    tape_diag: dict[str, object],
    stage2: dict[str, object],
    verify: dict[str, object],
    mdw_months: int,
    mdw_complete: bool,
    missing_months: dict[str, list[str]],
    peak_rss_mb: float,
) -> None:
    mid = tape_summary["0.25-0.75"]
    gate_pt = gate_verdict(mid, wilson=False)
    gate_w = gate_verdict(mid, wilson=True)

    def cli_span(d: dict[date, int]) -> str:
        if not d:
            return "none"
        days = sorted(d)
        return f"{days[0].isoformat()}..{days[-1].isoformat()} n={len(days)}"

    lines: list[str] = []
    a = lines.append
    a("# STAGE 0b — adverse-selection screen")
    a("")
    a("First-cut unconditional `p_bound_band` vs 2026-09-16 YES-leg tape (first 90 min).")
    a("Label = NWS CLI `settled_f`. Denominator = all spanning-band window minutes in the cell.")
    a("")
    a("## Data coverage")
    a("")
    a("| station | IEM months | missing months | IEM days w/ obs | CLI catalog | CLI AFOS | CLI merged | scored days |")
    a("|---|---:|---|---:|---|---|---|---:|")
    for s in STATIONS:
        st = iem_stats[s]
        miss = ",".join(missing_months.get(s, [])) or "—"
        a(
            f"| {s} | {st['months']} | {miss} | {st['days_with_obs']} | "
            f"{cli_span(catalog_finals[s])} | {cli_span(afos_finals[s])} | "
            f"{cli_span(merged_finals[s])} | {st['days_scored']} |"
        )
    a("")
    a(
        f"MDW wait: {mdw_months}/69 months "
        f"({'complete' if mdw_complete else 'INCOMPLETE — proceeded with months present'})."
    )
    a(
        f"IEM 09-16 window is **absent** (files end before 12:00 LST on 09-16 for all four). "
        f"09-15 window is present."
    )
    a("")
    a("## Band reimplementation")
    a("")
    a("F→C half-up `floor((F-32)*5/9+0.5)` (choice: repo only defines C→F half-up).")
    a("5-min samples: integer °C, precision 10 tenths, `is_metar=False`.")
    a(":53 samples: tenths °C half-up, precision 5, `is_metar=True`.")
    a("Band via `RunningExtremeAccumulator.value_at` (repo, not a copy of the interval math).")
    a("")
    uv = verify["unit"]
    a(
        f"Unit (integer-C interval): 91F→{uv['c_91']}C→{uv['91F_MIA']} "
        f"(tape MIA [91,92] **match**); "
        f"78F→{uv['c_78']}C→{uv['78F_LAX']} (tape LAX [78,80] **match**); "
        f"66F→{uv['c_66']}C→{uv['66F_SFO']} (tape SFO [65,67] **match**)."
    )
    a("09-16 archive window: **gap** — cannot replay the tape day from IEM.")
    a("09-15 reconstructed bands (open / +90 min / close):")
    for s in STATIONS:
        key = f"{s}_2026-09-15_bands"
        a(f"- {s} 09-15: {verify.get(key)} settled={verify.get(f'{s}_2026-09-15_settled')}")
    a("")
    a("## 09-16 tape screen (YES `source=quote`, first 90 min, candidate rungs only)")
    a("")
    a(
        f"jsonl={tape_diag['n_jsonl']} quote={tape_diag['n_quote']} "
        f"first90={tape_diag['n_first90']} candidate={tape_diag['n_candidate']} "
        f"scored={tape_diag['n_scored']} missing_cell={tape_diag['n_missing_cell']} "
        f"by_station={tape_diag['stations']}"
    )
    a("")
    a("| ask bucket | rows | frac margin>0 (point) | median margin (point) | GATE point | frac>0 (Wilson n≥90) | median Wilson | GATE Wilson |")
    a("|---|---:|---:|---:|---|---:|---:|---|")
    for name in ("<0.25", "0.25-0.75", ">0.75"):
        r = tape_summary[name]
        gp = gate_verdict(r, wilson=False) if name == "0.25-0.75" else "—"
        gw = gate_verdict(r, wilson=True) if name == "0.25-0.75" else "—"
        a(
            f"| {name} | {r['rows']} | {fmt(r['frac_pos_point'])} | {fmt(r['median_margin_point'])} | {gp} | "
            f"{fmt(r['frac_pos_wilson'])} | {fmt(r['median_margin_wilson'])} | {gw} |"
        )
    a("")
    a(f"**GATE 0.25–0.75 point estimate: {gate_pt}**")
    a(f"**GATE 0.25–0.75 Wilson-lower (n≥90 else undefined): {gate_w}**")
    a("Wilson rows with n<90 count in the denominator and are not positive (uncalibrated).")
    a("Ask bucket edges: `<0.25`, `0.25≤ask≤0.75`, `>0.75` (choice).")
    a("")
    a("## Stage 2 preview (first 90 min spanning minutes)")
    a("")
    a(
        f"Coverage cells `(station × band_width_f × m30)`: "
        f"{stage2['n_cov_cells_ge90']}/{stage2['n_cov_cells']} have N≥90 "
        f"(frac={fmt(stage2['frac_cells_ge90'])}; Stage 2 exit wants ≥0.80)."
    )
    a(f"By station: {stage2['cov_by_station']}")
    a(
        f"LOYO Brier (point `p_hat` vs label, both candidates): "
        f"{fmt(stage2['brier_loyo'], 6)} on n={stage2['brier_n']} "
        f"years={stage2['brier_years']} skipped_no_train={stage2['skipped_no_train']}"
    )
    a("Calibration-in-the-large (LOYO p vs y) per station:")
    for s in STATIONS:
        a(f"- {s}: {stage2['citl'].get(s)}")
    a("")
    a("## Top 10 cells by N (minutes; each cell has lower+upper candidates)")
    a("")
    # unique covariate cells by n
    seen = []
    used = set()
    for r in sorted(table_rows, key=lambda x: -int(x["n"])):
        key = (r["station"], r["season"], r["hour_lst"], r["band_width_f"], r["m30"])
        if key in used:
            continue
        used.add(key)
        lo = next(
            x
            for x in table_rows
            if (x["station"], x["season"], x["hour_lst"], x["band_width_f"], x["m30"], x["candidate"])
            == (*key, "lower")
        )
        up = next(
            x
            for x in table_rows
            if (x["station"], x["season"], x["hour_lst"], x["band_width_f"], x["m30"], x["candidate"])
            == (*key, "upper")
        )
        seen.append((key, lo, up))
        if len(seen) == 10:
            break
    a("| station | season | hour | width | m30 | N | p_lower | p_upper | outside_mass |")
    a("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for key, lo, up in seen:
        a(
            f"| {key[0]} | {key[1]} | {key[2]} | {key[3]} | {key[4]} | {lo['n']} | "
            f"{fmt(lo['p_hat'])} | {fmt(up['p_hat'])} | {fmt(lo['outside_mass'])} |"
        )
    a("")
    a("## Choices (where §3 is silent)")
    a("")
    a("- Local clock = **LST year-round** (`_local_hour` / `standard_time_zone`), not IANA DST.")
    a("- 30-min bucket from **true** minutes since 12:00 LST, not the tape's hour-truncated field (`(hour-12)*60`).")
    a("- Ladder: even-phase 2 °F interiors `[2k,2k+1]` (matches 09-16 MIA/LAX/SFO). Assumed 6-rung list always contains those two interiors (climatology-centred, shifted so the observed band is listed). Open tails unused for the first-cut interior bands.")
    a("- CLI: catalog parquet is settlement truth on overlap; AFOS cache fills the 2021–2025 span the catalog does not hold.")
    a("- Wilson undefined below `N_MIN=90` (study pattern); point estimate always `k/n`.")
    a("")
    a("## Caveats")
    a("")
    a("1. **One tape day** (2026-09-16); three stations (MDW listed but no YES rows that cleared `instrument_rung_is_current`).")
    a("2. **Ladder assumption** (even-phase, always-listed interiors) is not the venue's historical listing; MDW 09-16 was odd-phase with gaps.")
    a("3. **DST:** hour_lst is standard time; 12:00 LST in September is 13:00 LDT.")
    a("4. IEM 09-16 window missing; 5-min/METAR synthesis is not the live NWS API payload.")
    a("5. Sampled maxima are biased low vs continuous peaks (plan §1); that is the quantity being screened, not a defect of this table.")
    a(f"6. Peak RSS {peak_rss_mb:.0f} MB (cap 6 GB).")
    a("")
    a("## Reproduce")
    a("")
    a("```")
    a(f"{REPO / '.venv' / 'bin' / 'python'} {OUT / 'stage0b_screen.py'}")
    a("```")
    a("Inputs: IEM CSVs under `.../scratchpad/iem1min/`, CLI catalog `~/.local/share/breezy/catalog/polymarket_us/<STA>/data/custom_nws_climate_day/`, AFOS cache `~/.local/share/breezy/archive/settlement-alignment-cache/`, tape `offer_tape_2026-09-16.jsonl`.")
    a("Outputs: `p_bound_band_table.csv`, `tape_bucket_summary.json`, `stage2_preview.json`, `verify.json`, this report.")
    a("")

    text = "\n".join(lines) + "\n"
    nlines = text.count("\n")
    if nlines > 150:
        text += f"\n<!-- line count {nlines} (trim if needed) -->\n"
    (OUT / "STAGE0B_REPORT.md").write_text(text)
    print(f"[stage0b] wrote report lines={text.count(chr(10))}", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    mdw_n, mdw_ok = wait_for_mdw()
    print(f"[stage0b] MDW months={mdw_n} complete={mdw_ok} rss={rss_mb():.0f}MB", flush=True)

    mia_months = {p.stem for p in iem_months("MIA")}
    missing = {
        s: sorted(mia_months - {p.stem for p in iem_months(s)})
        for s in STATIONS
    }
    print(f"[stage0b] missing months: {missing}", flush=True)

    verify: dict[str, object] = {"unit": unit_verify_bands()}
    print(f"[stage0b] unit bands: {verify['unit']}", flush=True)

    print("[stage0b] loading CLI catalog parquet...", flush=True)
    catalog_finals = load_cli_from_catalog()
    print("[stage0b] loading CLI AFOS cache...", flush=True)
    afos_finals = load_cli_from_afos()
    merged = merge_finals(catalog_finals, afos_finals)

    minute_counts: dict[MinuteKey, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    iem_stats: dict[str, dict[str, int]] = {}
    for station in STATIONS:
        print(f"[stage0b] processing IEM {station}...", flush=True)
        iem_stats[station] = process_station_days(
            station, merged[station], minute_counts, verify
        )
        print(f"[stage0b] {station} stats {iem_stats[station]} rss={rss_mb():.0f}MB", flush=True)

    table_rows = aggregate_table(minute_counts)
    write_table_csv(table_rows, OUT / "p_bound_band_table.csv")
    print(f"[stage0b] table cells={len(table_rows)}", flush=True)

    tape_summary, tape_diag = score_tape(table_rows)
    (OUT / "tape_bucket_summary.json").write_text(
        json.dumps({"summary": tape_summary, "diag": tape_diag}, indent=2, default=str)
    )
    print(f"[stage0b] tape summary {tape_summary}", flush=True)

    stage2 = stage2_preview(minute_counts)
    (OUT / "stage2_preview.json").write_text(json.dumps(stage2, indent=2, default=str))
    # verify.json may contain datetimes
    def _ser(o: object) -> str:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return str(o)

    (OUT / "verify.json").write_text(json.dumps(verify, indent=2, default=_ser))
    (OUT / "iem_stats.json").write_text(json.dumps(iem_stats, indent=2))

    peak = rss_mb()
    write_report(
        iem_stats=iem_stats,
        catalog_finals=catalog_finals,
        afos_finals=afos_finals,
        merged_finals=merged,
        table_rows=table_rows,
        tape_summary=tape_summary,
        tape_diag=tape_diag,
        stage2=stage2,
        verify=verify,
        mdw_months=mdw_n,
        mdw_complete=mdw_ok,
        missing_months=missing,
        peak_rss_mb=peak,
    )
    print(f"[stage0b] done peak_rss={peak:.0f}MB", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
