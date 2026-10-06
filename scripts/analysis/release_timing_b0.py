"""F13 Phase B0: tape inventory, 60 s resolution, placebo feasibility, MDE, B1 family size.

READ-ONLY and CLI-free, champion-free, outcome-free. It reads:

* the quote-tape catalog's ``order_book_depths`` (Depth10) directories, never the quote ticks
  (a QuoteTick cannot show an empty bid; a Depth10 side with size 0 can);
* the release census JSON (``release_census.py``): PFM issuance times and the NBP-vintage flag.

It reads no model or CLI value and no outcome, opens no network connection and writes exactly
one JSON file (``--out``). SD for the MDE comes only from the pre-window and placebo arms of
the ladder-implied mean's own change (R14); no post-release arm is computed here and no effect
is estimated (``effect_estimate`` is null by construction).

Conventions (binding text in the F13 plan r3 + review fixes S1-S5):

* Rung values: an interior band ``gteLltU`` of ANY width is represented by ``L + (U - L) / 2``;
  a rung that still cannot be parsed is counted (``skipped_rungs``), never guessed. Tails sit one
  band-width beyond the neighbouring interior midpoint on both sides (``TAIL_CONVENTION``).
* Placebo SD is hour-matched: placebo instants are kept only in the UTC hours in which the
  source really releases (+-1 h). The pooled SD is reported beside it; the hour-matched one is
  USED for the MDE. The MDE is one-sided (alpha = 0.025, Holm family m in {1, 2}).
* Release -> market assignment (``RELEASE_DAY_ASSIGNMENT``): a release is matched to every open
  market whose climate day it precedes, so a D-1 release is also an event of the D market.
* ``n_eff`` clusters by climate date across stations and by station-day; the smaller is used.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pyarrow.parquet as pq

from breezy.analysis import release_timing as rt
from breezy.analysis.memory_cap import apply_address_space_cap
from breezy.normalize.climate_day import local_standard_date
from breezy.persistence.us_source_request import PFM_POINTS, US_SOURCE_STATIONS

__all__ = [
    "RungSeries",
    "TopOfBook",
    "WindowChange",
    "ladder_snapshot",
    "main",
    "parse_instrument",
    "read_top_of_book",
    "window_change",
]

_NS: Final[int] = 1_000_000_000
_FIXED_SCALE: Final[float] = 1e16
_BATCH_ROWS: Final[int] = 65_536
DEPTH_DIR: Final[str] = "order_book_depths"
DEFAULT_TAPE_START: Final[dt.date] = dt.date(2026, 8, 30)
DEFAULT_MAX_MEMORY_GIB: Final[float] = 8.0
DEFAULT_WINDOW_MIN: Final[int] = 60
DEFAULT_MAX_PLACEBO_PER_STATION: Final[int] = 400
SAME_CLOCK_TOLERANCE_S: Final[int] = 300
#: A placebo window may not overlap an event window: exclude +-60 min around every release.
PLACEBO_EXCLUSION_S: Final[int] = 3600
#: Tail rungs have no bounded width. Convention only: a tail sits ``TAIL_OFFSET_F`` (one band
#: width) beyond the midpoint of its neighbouring interior band, on both sides.
TAIL_OFFSET_F: Final[float] = 1.0
TAIL_CONVENTION: Final[str] = (
    "low tail lt<U>f = U - 0.5 - 1.0 and high tail gte<L>f = L + 0.5 + 1.0: one band-width "
    "beyond the neighbouring interior midpoint on both sides; interior = lower + width / 2"
)
RELEASE_DAY_ASSIGNMENT: Final[str] = (
    "a release is matched to every open market whose climate day it precedes within the study "
    "horizon (a D-1 release is also an event of the D market); a release after a market's "
    "climate day closed is never matched to it"
)
#: Release hours widen by this many hours either side to form the placebo hour band.
HOUR_BAND_MARGIN_H: Final[int] = 1
#: A pre-window arm is dropped when a previous release is closer than this (strictly less).
OVERLAP_WINDOW_S: Final[int] = 3600
_SKIPPED_EXAMPLES: Final[int] = 20
_EXIT_REFUSED: Final[int] = 2
_ALPHA: Final[float] = rt.ALPHA

CITY_TO_STATION: Final[Mapping[str, str]] = {
    "nyc": "KNYC",
    "mia": "KMIA",
    "mdw": "KMDW",
    "lax": "KLAX",
    "sfo": "KSFO",
}
#: Fixed local-standard-time offsets (no DST) that define each station's climate day.
STATION_STD_OFFSET_HOURS: Final[Mapping[str, float]] = {
    "KNYC": -5.0,
    "KMIA": -5.0,
    "KMDW": -6.0,
    "KLAX": -8.0,
    "KSFO": -8.0,
}
_STATION_BY_WFO: Final[Mapping[str, str]] = {p.wfo: s for s, p in PFM_POINTS.items()}
_INSTRUMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^tc-temp-(?P<city>[a-z]+)high-(?P<date>\d{4}-\d{2}-\d{2})-(?P<band>[a-z0-9]+)"
    r"\.(?P<venue>[A-Z_0-9]+)$"
)
_LOW_RE: Final[re.Pattern[str]] = re.compile(r"^lt(?P<upper>\d+)f$")
_HIGH_RE: Final[re.Pattern[str]] = re.compile(r"^gte(?P<lower>\d+)f$")
_INTERIOR_RE: Final[re.Pattern[str]] = re.compile(r"^gte(?P<lower>\d+)lt(?P<upper>\d+)f$")

_Floats = npt.NDArray[np.float64]
_Ints = npt.NDArray[np.uint64]


# ------------------------------------------------------------------ instruments


@dataclass(frozen=True, slots=True)
class InstrumentKey:
    station: str
    climate_day: dt.date
    rung_id: str
    value_f: float


def classify_instrument(name: str) -> tuple[InstrumentKey | None, bool]:
    """``(key, skipped)``; ``skipped`` marks a known-station rung with an unparseable band."""
    match = _INSTRUMENT_RE.match(name)
    if match is None or match["city"] not in CITY_TO_STATION:
        return None, False
    try:
        day = dt.date.fromisoformat(match["date"])
    except ValueError:
        return None, False
    band = match["band"]
    value: float
    if (low := _LOW_RE.match(band)) is not None:
        value = int(low["upper"]) - 0.5 - TAIL_OFFSET_F
    elif (high := _HIGH_RE.match(band)) is not None:
        value = int(high["lower"]) + 0.5 + TAIL_OFFSET_F
    elif (interior := _INTERIOR_RE.match(band)) is not None:
        lower, upper = int(interior["lower"]), int(interior["upper"])
        if upper <= lower:
            return None, True
        value = lower + (upper - lower) / 2.0
    else:
        return None, True
    return InstrumentKey(CITY_TO_STATION[match["city"]], day, band, value), False


def parse_instrument(name: str) -> InstrumentKey | None:
    """The station, climate day and rung value of a tape instrument id; None if unusable."""
    return classify_instrument(name)[0]


# ----------------------------------------------------------------------- reader


@dataclass(frozen=True, slots=True)
class TopOfBook:
    """Level-0 Depth10 bid and ask per row; NaN marks an EMPTY side (size 0)."""

    ts: _Ints
    bid: _Floats
    ask: _Floats
    empty_bid_rows: int

    @property
    def n_rows(self) -> int:
        return int(self.ts.shape[0])


@dataclass(frozen=True, slots=True)
class RungSeries:
    rung_id: str
    value_f: float
    top: TopOfBook


def _words(array: Any) -> npt.NDArray[np.uint64]:
    """A fixed_size_binary(16) column as ``(n, 2)`` little-endian (low, high) words."""
    start = array.offset * 2
    flat = np.frombuffer(array.buffers()[1], dtype="<u8")[start : start + len(array) * 2]
    return flat.reshape(-1, 2)


def _price_or_nan(price_col: Any, size_col: Any) -> _Floats:
    prices, sizes = _words(price_col), _words(size_col)
    present = (sizes[:, 0] != 0) | (sizes[:, 1] != 0)
    values = prices[:, 0].astype(np.float64) / _FIXED_SCALE
    return np.where(present, values, np.nan)


def read_top_of_book(instrument_dir: Path) -> TopOfBook:
    """Stream one instrument's Depth10 parquet files; no ``to_table``, bounded batches."""
    ts_parts: list[_Ints] = []
    bid_parts: list[_Floats] = []
    ask_parts: list[_Floats] = []
    columns = ["ts_event", "bid_price_0", "bid_size_0", "ask_price_0", "ask_size_0"]
    for path in sorted(instrument_dir.glob("*.parquet")):
        with pq.ParquetFile(path) as handle:
            for batch in handle.iter_batches(batch_size=_BATCH_ROWS, columns=columns):
                ts_parts.append(batch.column("ts_event").to_numpy(zero_copy_only=False))
                bid_parts.append(
                    _price_or_nan(batch.column("bid_price_0"), batch.column("bid_size_0"))
                )
                ask_parts.append(
                    _price_or_nan(batch.column("ask_price_0"), batch.column("ask_size_0"))
                )
    if not ts_parts:
        empty_ts: _Ints = np.empty(0, dtype=np.uint64)
        return TopOfBook(empty_ts, np.empty(0), np.empty(0), 0)
    ts = np.concatenate(ts_parts).astype(np.uint64)
    order = np.argsort(ts, kind="stable")
    bid = np.concatenate(bid_parts)[order]
    ask = np.concatenate(ask_parts)[order]
    return TopOfBook(ts[order], bid, ask, int(np.isnan(bid).sum()))


# ----------------------------------------------------------------- ladder reads


def _maybe(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


def ladder_snapshot(rungs: Sequence[RungSeries], instant_ns: int) -> dict[str, rt.RungQuote]:
    """Each rung's latest row at or before ``instant_ns``; unlisted rungs are omitted."""
    snapshot: dict[str, rt.RungQuote] = {}
    for rung in rungs:
        index = int(np.searchsorted(rung.top.ts, np.uint64(instant_ns), side="right")) - 1
        if index < 0:
            continue
        snapshot[rung.rung_id] = rt.RungQuote(
            rung.rung_id,
            rung.value_f,
            _maybe(float(rung.top.bid[index])),
            _maybe(float(rung.top.ask[index])),
        )
    return snapshot


@dataclass(frozen=True, slots=True)
class WindowChange:
    change: float
    panel_rungs: int
    dropout_rungs: int
    empty_side_rungs: int
    panel_mass: float = 0.0
    dropout_mass: float = 0.0


def window_change(rungs: Sequence[RungSeries], start_ns: int, end_ns: int) -> WindowChange | None:
    """Signed change of the ladder-implied mean over ``[start, end]``; None for an empty panel."""
    panel = rt.build_matched_panel(ladder_snapshot(rungs, start_ns), ladder_snapshot(rungs, end_ns))
    if not panel.rungs:
        return None
    return WindowChange(
        rt.signed_change(panel),
        len(panel.rungs),
        panel.dropout_count,
        panel.empty_side_count,
        panel_mass=sum(r.p_t for r in panel.rungs),
        dropout_mass=sum(r.p_t for r in panel.rungs if r.carried_forward),
    )


# -------------------------------------------------------------------- inventory


def _hour_bins(ts_ns: Iterable[int]) -> set[int]:
    return {t // (3600 * _NS) for t in ts_ns}


def window_inventory(station: str, day: dt.date, rungs: Sequence[RungSeries]) -> dict[str, Any]:
    """Depth10 cadence and coverage of one station-window (union of its rungs' rows)."""
    union = (
        np.unique(np.concatenate([r.top.ts for r in rungs])) if rungs else np.empty(0, np.uint64)
    )
    n_rows = sum(r.top.n_rows for r in rungs)
    summary = rt.cadence_summary([int(t) for t in union])
    bins = _hour_bins(int(t) for t in union)
    spanned = (max(bins) - min(bins) + 1) if bins else 0
    return {
        "station": station,
        "climate_day": day.isoformat(),
        "n_instruments": len(rungs),
        "n_rows": n_rows,
        "n_union_rows": int(union.shape[0]),
        "first_utc": _utc(int(union[0])) if union.size else None,
        "last_utc": _utc(int(union[-1])) if union.size else None,
        "median_gap_s": summary.median_gap_s,
        "p90_gap_s": summary.p90_gap_s,
        "max_gap_s": summary.max_gap_s,
        "resolves_60s": rt.resolves_resolution(summary),
        "hours_spanned": spanned,
        "hours_with_rows": len(bins),
        "coverage_fraction": (len(bins) / spanned) if spanned else 0.0,
        "empty_bid_row_share": (sum(r.top.empty_bid_rows for r in rungs) / n_rows)
        if n_rows
        else 0.0,
    }


def _utc(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / _NS, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cadence_verdict(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    resolving = sum(1 for w in windows if w["resolves_60s"])
    if windows and resolving == len(windows):
        verdict = "RESOLVES"
    elif resolving:
        verdict = "PARTIAL"
    else:
        verdict = "DOES_NOT_RESOLVE"
    return {
        "resolution_s": rt.RESOLUTION_S,
        "rule": f"a window resolves when its p90 inter-row gap <= {rt.RESOLUTION_S} s",
        "n_windows": len(windows),
        "n_resolving": resolving,
        "verdict": verdict,
        "b2_60s_stop_testable": verdict != "DOES_NOT_RESOLVE",
    }


# ---------------------------------------------------------------------- targets


@dataclass(slots=True)
class _ArmTally:
    n_events: int = 0
    n_evaluated: int = 0
    n_unevaluable: int = 0
    panel_rungs: int = 0
    dropout_rungs: int = 0
    empty_side_rungs: int = 0
    overlapping_windows: int = 0
    panel_mass: float = 0.0
    dropout_mass: float = 0.0

    def record(self, result: WindowChange | None) -> None:
        self.n_events += 1
        if result is None:
            self.n_unevaluable += 1
            return
        self.n_evaluated += 1
        self.panel_rungs += result.panel_rungs
        self.dropout_rungs += result.dropout_rungs
        self.empty_side_rungs += result.empty_side_rungs
        self.panel_mass += result.panel_mass
        self.dropout_mass += result.dropout_mass

    def as_dict(self) -> dict[str, int]:
        return {
            "n_events": self.n_events,
            "n_evaluated": self.n_evaluated,
            "n_unevaluable": self.n_unevaluable,
            "panel_rungs": self.panel_rungs,
            "dropout_rungs": self.dropout_rungs,
            "empty_side_rungs": self.empty_side_rungs,
            "overlapping_windows": self.overlapping_windows,
        }

    def diagnostics(self) -> dict[str, float | None]:
        """Dropout share (by rung count and by probability mass) and mean panel mass per window."""
        return {
            "dropout_share": _ratio(self.dropout_rungs, self.panel_rungs),
            "dropout_mass_share": _ratio(self.dropout_mass, self.panel_mass),
            "panel_mass_mean": _ratio(self.panel_mass, self.n_evaluated),
        }


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


#: Value variants kept per arm: every window / hour-matched windows, each also restricted to the
#: windows with no dropout rung (the sensitivity arm: a dropout rung is carried flat, which
#: shrinks the SD, so the sensitivity SD is read from windows that have none).
_VARIANTS: Final[tuple[str, ...]] = ("pooled", "matched", "pooled_excl", "matched_excl")
_Values = dict[str, dict[str, list[float]]]


def _new_values() -> _Values:
    return {variant: defaultdict(list) for variant in _VARIANTS}


def _record_values(values: _Values, arm: str, result: WindowChange, *, hour_matched: bool) -> None:
    values["pooled"][arm].append(result.change)
    if hour_matched:
        values["matched"][arm].append(result.change)
    if result.dropout_rungs == 0:  # sensitivity: a carried-forward rung contributes a flat 0
        values["pooled_excl"][arm].append(result.change)
        if hour_matched:
            values["matched_excl"][arm].append(result.change)


@dataclass(slots=True)
class _Stratum:
    station: str
    wfo: str
    releases_ns: list[int]
    same_clock_by_day: dict[dt.date, list[int]]
    metar_by_day: dict[dt.date, list[int]]
    hour_band: tuple[int, ...]
    overlapping_ns: frozenset[int]
    tape_days: int = 0
    same_clock_pool: int = 0
    metar_pool: int = 0
    metar_matched_pool: int = 0


def _utc_days(since: dt.date, until: dt.date) -> list[dt.date]:
    return [since + dt.timedelta(days=i) for i in range((until - since).days + 1)]


def _stride(items: list[int], cap: int) -> list[int]:
    step = max(1, math.ceil(len(items) / cap)) if cap > 0 else 1
    return items[::step]


def _by_climate_day(instants: Iterable[int], station: str) -> dict[dt.date, list[int]]:
    offset = STATION_STD_OFFSET_HOURS[station]
    grouped: dict[dt.date, list[int]] = defaultdict(list)
    for instant in sorted(instants):
        grouped[local_standard_date(instant, offset)].append(instant)
    return grouped


def _utc_hour(instant_ns: int) -> int:
    return (instant_ns // _NS // 3600) % 24


def release_hour_band(releases_ns: Iterable[int]) -> tuple[int, ...]:
    """UTC hours in which the source releases, widened by ``HOUR_BAND_MARGIN_H`` each side."""
    hours = {_utc_hour(t) for t in releases_ns}
    return tuple(
        sorted(
            {
                (hour + step) % 24
                for hour in hours
                for step in range(-HOUR_BAND_MARGIN_H, HOUR_BAND_MARGIN_H + 1)
            }
        )
    )


def overlapping_releases(sorted_releases_ns: Sequence[int]) -> frozenset[int]:
    """Releases whose pre-window would contain the previous release (gap < ``OVERLAP_WINDOW_S``)."""
    limit = OVERLAP_WINDOW_S * _NS
    return frozenset(b for a, b in pairwise(sorted_releases_ns) if b - a < limit)


def events_for_market(
    stratum: _Stratum, climate_day: dt.date, first_ns: int, last_ns: int
) -> list[int]:
    """Releases inside the market's tape span whose climate day does not follow the market's."""
    lo = bisect.bisect_left(stratum.releases_ns, first_ns)
    hi = bisect.bisect_right(stratum.releases_ns, last_ns)
    offset = STATION_STD_OFFSET_HOURS[stratum.station]
    return [t for t in stratum.releases_ns[lo:hi] if local_standard_date(t, offset) <= climate_day]


def _build_stratum(
    station: str,
    wfo: str,
    releases: Sequence[int],
    days: Sequence[dt.date],
    cap: int,
) -> _Stratum:
    ordered = sorted(releases)
    slots = sorted({(t // _NS) % 86_400 // 60 * 60 for t in ordered})
    same_clock = [
        int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp()) * _NS + slot * _NS
        for slot in slots
        for d in rt.same_clock_placebo_days(slot, ordered, days, tolerance_s=SAME_CLOCK_TOLERANCE_S)
    ]
    minutes = sorted({(t // _NS) % 3600 // 60 for t in ordered})
    metar = [
        instant
        for minute in minutes
        for instant in rt.metar_offset_placebo_instants(
            minute_of_hour=minute, releases_ns=ordered, days=days, exclusion_s=PLACEBO_EXCLUSION_S
        )
    ]
    return _Stratum(
        station,
        wfo,
        ordered,
        _by_climate_day(_stride(sorted(same_clock), cap), station),
        _by_climate_day(_stride(sorted(set(metar)), cap), station),
        release_hour_band(ordered),
        overlapping_releases(ordered),
    )


# ----------------------------------------------------------------------- the run


def _discover(
    tape: Path, stations: Sequence[str], since: dt.date, until: dt.date
) -> tuple[dict[tuple[str, dt.date], list[tuple[InstrumentKey, Path]]], list[str]]:
    """Group the tape's rungs by (station, climate day); also name every unparseable rung."""
    groups: dict[tuple[str, dt.date], list[tuple[InstrumentKey, Path]]] = defaultdict(list)
    skipped: list[str] = []
    base = tape / "data" / DEPTH_DIR
    if not base.is_dir():
        return groups, skipped
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        key, unparseable = classify_instrument(directory.name)
        if unparseable and _in_scope(directory.name, stations, since, until):
            skipped.append(directory.name)
        if key is None or key.station not in stations or not since <= key.climate_day <= until:
            continue
        groups[(key.station, key.climate_day)].append((key, directory))
    return groups, skipped


def _in_scope(name: str, stations: Sequence[str], since: dt.date, until: dt.date) -> bool:
    match = _INSTRUMENT_RE.match(name)
    if match is None or CITY_TO_STATION.get(match["city"]) not in stations:
        return False
    return since <= dt.date.fromisoformat(match["date"]) <= until


def _load_rungs(members: Sequence[tuple[InstrumentKey, Path]]) -> list[RungSeries]:
    return [
        RungSeries(key.rung_id, key.value_f, read_top_of_book(path))
        for key, path in sorted(members, key=lambda m: (m[0].value_f, m[0].rung_id))
    ]


def _covered(instants: Sequence[int], first_ns: int, last_ns: int, delta_ns: int) -> list[int]:
    return [t for t in instants if first_ns <= t and t + delta_ns <= last_ns]


def _evaluate_window(
    stratum: _Stratum,
    day: dt.date,
    rungs: Sequence[RungSeries],
    window_s: int,
    tallies: dict[str, _ArmTally],
    values: _Values,
) -> int:
    span = window_s * _NS
    firsts = [int(r.top.ts[0]) for r in rungs if r.top.n_rows]
    lasts = [int(r.top.ts[-1]) for r in rungs if r.top.n_rows]
    if not firsts:
        return 0
    first, last = min(firsts), max(lasts)
    stratum.tape_days += 1
    same = _covered(stratum.same_clock_by_day.get(day, []), first, last, span)
    metar = _covered(stratum.metar_by_day.get(day, []), first, last, span)
    stratum.same_clock_pool += len(same)
    stratum.metar_pool += len(metar)
    stratum.metar_matched_pool += sum(_utc_hour(t) in stratum.hour_band for t in metar)
    plan = (
        ("pre_window", events_for_market(stratum, day, first, last), -span, 0),
        ("placebo_same_clock", same, 0, span),
        ("placebo_metar_offset", metar, 0, span),
    )
    evaluated_events = 0
    for arm, instants, lo, hi in plan:
        for instant in instants:
            if arm == "pre_window" and instant in stratum.overlapping_ns:
                tallies[arm].overlapping_windows += 1
                continue
            result = window_change(rungs, instant + lo, instant + hi)
            tallies[arm].record(result)
            if result is None:
                continue
            matched = arm == "pre_window" or _utc_hour(instant) in stratum.hour_band
            _record_values(values, arm, result, hour_matched=matched)
            evaluated_events += arm == "pre_window"
    return evaluated_events


def _sd_and_mde(
    series: Mapping[str, Sequence[float]], n_eff: float, family_size: int
) -> dict[str, Any]:
    """SD over the supplied arms and the MDE at each Holm family size; ``error`` on failure."""
    arms = sorted(name for name, values in series.items() if values)
    out: dict[str, Any] = {"sd_arms": arms, "sd": None, "mde": None, "by_family_size": None}
    try:
        sd = rt.pooled_sd({name: series[name] for name in arms})
        by_family = {str(m): rt.mde(sd=sd, n_eff=n_eff, family_size=m) for m in (1, 2)}
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    out.update(sd=sd, by_family_size=by_family, mde=by_family[str(family_size)])
    return out


def _mde_section(
    values: _Values,
    clusters: Mapping[str, Sequence[int]],
    chosen: int,
    plausible: float | None,
    icc: float,
    tallies: Mapping[str, _ArmTally],
) -> dict[str, Any]:
    n_eff_station_day = rt.effective_n(clusters["station_day"], icc=icc)
    n_eff_date = rt.effective_n(clusters["climate_date"], icc=icc)
    n_eff = min(n_eff_station_day, n_eff_date)
    matched = _sd_and_mde(values["matched"], n_eff, chosen)
    pooled = _sd_and_mde(values["pooled"], n_eff, chosen)
    sensitivity = _sd_and_mde(values["matched_excl"], n_eff, chosen)
    section: dict[str, Any] = {
        "sd_arms": matched["sd_arms"],
        "chosen_family_size": chosen,
        "sidedness": "one-sided",
        "sd_basis": "hour_matched",
        "n_eff": n_eff,
        "n_eff_station_day": n_eff_station_day,
        "n_eff_climate_date": n_eff_date,
        "n_clusters": len(clusters["station_day"]),
        "n_clusters_climate_date": len(clusters["climate_date"]),
        "units": "ladder-implied expected daily max, degrees F per window",
        "plausible_effect": plausible,
        "sd": matched["sd"],
        "sd_hour_matched": matched["sd"],
        "sd_pooled": pooled["sd"],
        "by_family_size": matched["by_family_size"],
        "by_family_size_pooled": pooled["by_family_size"],
        "mde": matched["mde"],
        "underpowered": None,
        "sensitivity_excluding_dropout": {
            key: sensitivity[key] for key in ("sd_arms", "sd", "mde", "by_family_size")
        },
        "per_arm": {
            arm: {
                **tally.diagnostics(),
                "n_values_pooled": len(values["pooled"].get(arm, [])),
                "n_values_hour_matched": len(values["matched"].get(arm, [])),
            }
            for arm, tally in sorted(tallies.items())
        },
    }
    if "error" in matched:
        section["error"] = matched["error"]
    if "error" in sensitivity:
        section["sensitivity_excluding_dropout"]["error"] = sensitivity["error"]
    if matched["mde"] is not None:
        section["underpowered"] = rt.is_underpowered(
            mde_value=matched["mde"], plausible_effect=plausible
        )
    return section


def _b1_family(nbp_present: bool) -> dict[str, Any]:
    size = rt.holm_family_size(nbp_vintages_present=nbp_present)
    return {
        "size": size,
        "members": ["PFM", "NBP"] if nbp_present else ["PFM"],
        "alpha": _ALPHA,
        "reason": (
            "NBP vintages present in the node catalog"
            if nbp_present
            else "NBP vintages absent from the node catalog"
        ),
    }


def _stratum_report(
    stratum: _Stratum, evaluated: Mapping[tuple[str, dt.date], int]
) -> dict[str, Any]:
    per_day = sorted(n for (st, _d), n in evaluated.items() if st == stratum.station and n)
    return {
        "source": "PFM",
        "wfo": stratum.wfo,
        "n_events": len(stratum.releases_ns),
        "n_tape_days": stratum.tape_days,
        "n_event_days": len(per_day),
        "events_per_day": per_day,
        "same_clock_pool_days_total": stratum.same_clock_pool,
        "metar_offset_pool_instants_total": stratum.metar_pool,
        "metar_offset_pool_hour_matched_total": stratum.metar_matched_pool,
        "release_hour_band_utc": list(stratum.hour_band),
    }


def _placebo_section(strata: Mapping[str, _Stratum]) -> dict[str, Any]:
    same = sum(s.same_clock_pool for s in strata.values())
    metar = sum(s.metar_pool for s in strata.values())
    controls = ["pre_window"]
    if same:
        controls.append("placebo_same_clock")
    if metar:
        controls.append("placebo_metar_offset")
    return {
        "pfm_pool_empty": same == 0,
        "pfm_mode": "descriptive_only" if same == 0 else "placebo_available",
        "same_clock_pool_total": same,
        "metar_offset_pool_total": metar,
        "controls_available": controls,
    }


def build_report(args: argparse.Namespace, census: Mapping[str, Any]) -> dict[str, Any]:
    stations = list(args.stations)
    days = _utc_days(args.since, args.until + dt.timedelta(days=1))
    floor, ceil = _bounds_ns(args.since, args.until)
    strata: dict[str, _Stratum] = {}
    for wfo, block in sorted(census.get("pfm", {}).items()):
        station = _STATION_BY_WFO.get(wfo)
        if station is None or station not in stations:
            continue
        times = [t for t in block.get("issuance_times_ns", []) if floor <= t < ceil]
        strata[station] = _build_stratum(station, wfo, times, days, args.max_placebo_per_station)
    tallies = {
        name: _ArmTally() for name in ("pre_window", "placebo_same_clock", "placebo_metar_offset")
    }
    values = _new_values()
    evaluated: dict[tuple[str, dt.date], int] = {}
    windows: list[dict[str, Any]] = []
    discovered, skipped = _discover(args.tape_catalog, stations, args.since, args.until)
    for (station, day), members in sorted(discovered.items()):
        rungs = _load_rungs(members)
        windows.append(window_inventory(station, day, rungs))
        if station in strata:
            evaluated[(station, day)] = _evaluate_window(
                strata[station], day, rungs, args.window_min * 60, tallies, values
            )
    nbp = bool(census.get("nbp", {}).get("vintages_present", False))
    family = _b1_family(nbp)
    by_date: dict[dt.date, int] = defaultdict(int)
    for (_station, day), count in evaluated.items():
        by_date[day] += count
    clusters = {
        "station_day": [n for n in evaluated.values() if n],
        "climate_date": [n for n in by_date.values() if n],
    }
    return {
        "inputs": {
            "tape_catalog": str(args.tape_catalog),
            "census_json": str(args.census_json),
            "since": args.since.isoformat(),
            "until": args.until.isoformat(),
            "window_min": args.window_min,
            "outcomes_read": False,
            "model_values_read": False,
            "network_used": False,
            "quote_ticks_read": False,
        },
        "power_prereg": {
            "alpha": _ALPHA,
            "holm_family_max": 2,
            "power": rt.POWER,
            "analysis_unit": "event-day",
            "cluster": "climate_day",
            "icc": args.icc,
        },
        "tape_inventory": {
            "n_station_windows": len(windows),
            "station_windows": windows,
            "skipped_rungs": len(skipped),
            "skipped_rung_examples": skipped[:_SKIPPED_EXAMPLES],
        },
        "tail_convention": TAIL_CONVENTION,
        "release_day_assignment": RELEASE_DAY_ASSIGNMENT,
        "cadence_60s": cadence_verdict(windows),
        "strata": {s: _stratum_report(st, evaluated) for s, st in sorted(strata.items())},
        "placebo": _placebo_section(strata),
        "arms": {name: tally.as_dict() for name, tally in tallies.items()},
        "mde": _mde_section(
            values, clusters, family["size"], args.plausible_effect, args.icc, tallies
        ),
        "b1_family": family,
        "effect_estimate": None,
    }


def _bounds_ns(since: dt.date, until: dt.date) -> tuple[int, int]:
    floor = int(dt.datetime(since.year, since.month, since.day, tzinfo=dt.UTC).timestamp()) * _NS
    after = until + dt.timedelta(days=1)
    return floor, int(
        dt.datetime(after.year, after.month, after.day, tzinfo=dt.UTC).timestamp()
    ) * _NS


# ------------------------------------------------------------------------- main


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape-catalog", required=True, type=Path)
    parser.add_argument("--census-json", required=True, type=Path)
    parser.add_argument("--since", type=dt.date.fromisoformat, default=DEFAULT_TAPE_START)
    parser.add_argument("--until", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--stations", nargs="+", default=list(US_SOURCE_STATIONS))
    parser.add_argument("--window-min", type=int, default=DEFAULT_WINDOW_MIN)
    parser.add_argument(
        "--max-placebo-per-station", type=int, default=DEFAULT_MAX_PLACEBO_PER_STATION
    )
    parser.add_argument("--plausible-effect", type=float, default=None)
    parser.add_argument("--icc", type=float, default=1.0)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-memory-gib", type=float, default=DEFAULT_MAX_MEMORY_GIB)
    return parser.parse_args(list(argv))


def _write_atomic(out: Path, payload: Mapping[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(tmp_name, out)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def main(
    argv: Sequence[str] | None = None, *, cap: Callable[[float], int] = apply_address_space_cap
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.out.resolve().is_relative_to(args.tape_catalog.resolve()):
        sys.stderr.write("REFUSED: --out must not sit inside the tape catalog\n")
        return _EXIT_REFUSED
    if args.until is None:
        args.until = dt.datetime.now(dt.UTC).date()
    cap(args.max_memory_gib)
    census = json.loads(args.census_json.read_text(encoding="utf-8"))
    _write_atomic(args.out, build_report(args, census))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
