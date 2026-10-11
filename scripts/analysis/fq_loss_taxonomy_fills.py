"""TE-2 WP1c: Phase B per-fill records, flags, station-day records and alternative truth.

Joins the (outcome-blind) Phase A rows with the settled outcome and classifies every fill through
``classify_fills``. Geometry comes only from ``edge_distance``, which wraps
``bucket_facts_from_instrument_id``. Plan sections 2 and 3.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from breezy.registry.sites import default_registry
from scripts.analysis.fq_loss_taxonomy_battery import DayRecord
from scripts.analysis.fq_loss_taxonomy_classify import (
    FillClass,
    FillFacts,
    classify_fills,
    edge_distance,
)
from scripts.analysis.fq_loss_taxonomy_stats import (
    LOC_MEDIAN_CDF,
    loc_pi,
    pit_midpoint_of,
    spread_fill,
    station_day_probability,
    upper_tail,
)
from scripts.analysis.fq_loss_taxonomy_truth import ScoredFill

VENUE: Final = "polymarket_us"
_PIT_PLACEHOLDER: Final = (
    0.5  # only for fills without a pmf; their pmf-based classes are overridden
)
_PMF_CLASSES: Final = frozenset(
    {FillClass.BOUNDARY, FillClass.TAIL, FillClass.BAND_SELECTION, FillClass.BODY_MISS}
)
_METAR_COLUMNS: Final = ("valid_utc", "tmpf")


@dataclass(frozen=True)
class FillRecord:
    fill_id: str
    instrument_id: str
    station: str
    climate_day: dt.date
    decision_now_ns: int
    tmax_f: int
    won: bool
    pnl: Decimal
    p_hat: float
    ask_proxy: float
    edge_dist: int
    pmf: Mapping[int, float] | None
    pit: float | None
    z: float | None
    corr_median: int | None
    raw_q50: float | None
    corr_err: float | None
    raw_err: float | None
    cls: FillClass
    flags: tuple[str, ...]
    rungs_same_day: int
    partition_complete: bool
    day_has_win: bool
    row: Mapping[str, Any]


def pmf_median(pmf: Mapping[int, float]) -> int:
    """The smallest degree with CDF >= 1/2 (the T-LOC median rule)."""
    total = 0.0
    for degree in sorted(pmf):
        total += pmf[degree]
        if total >= LOC_MEDIAN_CDF:
            return degree
    return max(pmf)


def _pmf_of(row: Mapping[str, Any]) -> dict[int, float] | None:
    raw = row.get("pmf")
    return None if not raw else {int(k): float(v) for k, v in raw.items()}


def _mean_sd(pmf: Mapping[int, float]) -> tuple[float, float]:
    mean = math.fsum(t * m for t, m in pmf.items())
    var = math.fsum(m * (t - mean) ** 2 for t, m in pmf.items())
    return mean, math.sqrt(var)


def break_even(ask: float, theta: float) -> float:
    """The ask-implied win probability net of the taker fee ``theta * a * (1 - a)``."""
    return min(1.0, ask + theta * ask * (1.0 - ask))


def _z(pmf: Mapping[int, float] | None, tmax_f: int) -> float | None:
    if not pmf:
        return None
    mean, sd = _mean_sd(pmf)
    return (tmax_f - mean) / sd if sd > 0 else None


def _flags(
    row: Mapping[str, Any],
    *,
    corr_err: float | None,
    raw_err: float | None,
    has_pmf: bool,
    k1b: bool,
    th: Mapping[str, Any],
    alt: tuple[bool | None, bool | None],
) -> tuple[str, ...]:
    raw_sd = row.get("raw_sd")
    found = {
        "K1a": row["s0d_class"] == "K1a",
        "K1b": k1b,
        "K2": row["newest_visible"] is False
        or (row["cycle_age_s"] is not None and row["cycle_age_s"] > th["cycle_age_max_s"]),
        "K3": bool(alt[0]),
        "K4": bool(alt[1]),
        "LOC_ARTEFACT": corr_err is not None
        and raw_err is not None
        and abs(corr_err) > abs(raw_err),
        "LOC_SOURCE": raw_err is not None and raw_sd is not None and abs(raw_err) > raw_sd,
        "FLANK_CHEAP": row["ask_proxy"] < th["flank_cheap_ask"],
        "CYCLE_AMBIGUOUS": row["s0d_class"] == "CYCLE_AMBIGUOUS",
        "UNTESTABLE": row["s0d_class"] == "UNTESTABLE"
        or row["pin_state"] == "UNTESTABLE"
        or not has_pmf,
    }
    return tuple(name for name, present in found.items() if present)


def build_fill_records(
    rows: Sequence[Mapping[str, Any]],
    days: Mapping[tuple[str, dt.date], Mapping[str, Any]],
    scored: Mapping[str, ScoredFill],
    *,
    thresholds: Mapping[str, Any],
    terminal_climate_day: dt.date,
    k3: Mapping[str, bool] | None,
    k4: Mapping[str, bool] | None,
) -> list[FillRecord]:
    """One record per Phase A row, joined to its settled outcome and classified."""
    parsed = [(r, dt.date.fromisoformat(str(r["climate_day"])), scored[r["fill_id"]]) for r in rows]
    edge = {r["fill_id"]: edge_distance(s.instrument_id, s.tmax_f) for r, _d, s in parsed}
    facts = [
        FillFacts(
            r["fill_id"], r["station"], day, edge[r["fill_id"]],
            pit_midpoint_of(pmf, s.tmax_f) if (pmf := _pmf_of(r)) else _PIT_PLACEHOLDER,
            s.won, bool(days[(r["station"], day)]["partition_complete"]),
        )
        for r, day, s in parsed
    ]  # fmt: skip
    classes = classify_fills(facts)
    by_day: dict[tuple[str, dt.date], list[ScoredFill]] = {}
    for r, day, s in parsed:
        by_day.setdefault((r["station"], day), []).append(s)
    records = []
    for r, day, s in parsed:
        pmf = _pmf_of(r)
        median = pmf_median(pmf) if pmf else None
        corr = None if median is None else float(s.tmax_f - median)
        raw = None if r.get("raw_q50") is None else s.tmax_f - float(r["raw_q50"])
        cls = classes[r["fill_id"]]
        if pmf is None and cls in _PMF_CLASSES:
            cls = FillClass.UNTESTABLE
        flags = _flags(
            r, corr_err=corr, raw_err=raw, has_pmf=pmf is not None, th=thresholds,
            k1b=day > terminal_climate_day,
            alt=((k3 or {}).get(r["fill_id"]), (k4 or {}).get(r["fill_id"])),
        )  # fmt: skip
        siblings = by_day[(r["station"], day)]
        records.append(
            FillRecord(
                fill_id=r["fill_id"], instrument_id=s.instrument_id, station=r["station"],
                climate_day=day, decision_now_ns=int(r["decision_now_ns"]), tmax_f=s.tmax_f,
                won=s.won, pnl=s.pnl, p_hat=float(r["p_hat"]), ask_proxy=float(r["ask_proxy"]),
                edge_dist=edge[r["fill_id"]], pmf=pmf,
                pit=None if pmf is None else pit_midpoint_of(pmf, s.tmax_f),
                z=_z(pmf, s.tmax_f), corr_median=median,
                raw_q50=None if r.get("raw_q50") is None else float(r["raw_q50"]),
                corr_err=corr, raw_err=raw, cls=cls, flags=flags, rungs_same_day=len(siblings),
                partition_complete=bool(days[(r["station"], day)]["partition_complete"]),
                day_has_win=any(x.won for x in siblings), row=r,
            )
        )  # fmt: skip
    return records


def day_records(
    records: Sequence[FillRecord],
    days: Mapping[tuple[str, dt.date], Mapping[str, Any]],
    theta: float,
) -> list[DayRecord]:
    """One ``DayRecord`` per station-day; T-LOC / T-ART use the day's EARLIEST fill (declared)."""
    grouped: dict[tuple[str, dt.date], list[FillRecord]] = {}
    for rec in records:
        grouped.setdefault((rec.station, rec.climate_day), []).append(rec)
    out = []
    for key in sorted(grouped):
        recs = grouped[key]
        earliest = min(recs, key=lambda r: r.decision_now_ns)
        spreads = [None if r.pmf is None else spread_fill(r.pmf, r.tmax_f) for r in recs]
        complete = all(s is not None for s in spreads)
        out.append(
            DayRecord(
                station=key[0], climate_day=key[1],
                p_d=station_day_probability([r.p_hat for r in recs]),
                won=any(r.won for r in recs),
                ask_prob=min(1.0, math.fsum(break_even(r.ask_proxy, theta) for r in recs)),
                fill_qs=tuple(s.q_f for s in spreads if s) if complete else None,
                tail_flags=tuple(s.is_tail_miss for s in spreads if s) if complete else None,
                pi=None if earliest.pmf is None else loc_pi(earliest.pmf),
                corr_err=earliest.corr_err, raw_err=earliest.raw_err,
            )
        )  # fmt: skip
    return out


def t_edge(records: Sequence[FillRecord]) -> dict[str, Any]:
    """Exploratory (outside every family): P(X >= k), X = losing fills at edge distance 1."""
    nulls = []
    for rec in records:
        if rec.won or rec.pmf is None:
            continue
        dist = {t: edge_distance(rec.instrument_id, t) for t in rec.pmf}
        inside = math.fsum(m for t, m in rec.pmf.items() if dist[t] == 0)
        one = math.fsum(m for t, m in rec.pmf.items() if dist[t] == 1)
        nulls.append((one / (1.0 - inside) if inside < 1.0 else 0.0, rec.edge_dist == 1))
    k = sum(1 for _p, hit in nulls if hit)
    p = upper_tail([min(1.0, p) for p, _h in nulls], k)
    return {
        "x_obs": k, "n": len(nulls), "p_value": p, "exploratory": True, "confirmatory_weight": 0
    }  # fmt: skip


# ---- alternative truth (S0-G) -------------------------------------------------------------


def _utc(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(value[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def metar_daily_max(
    archive_root: Path, icao: str, climate_day: dt.date, std_utc_offset_hours: float
) -> int | None:
    """The METAR/ASOS max (``tmpf`` rounded) over the local-standard climate day, or ``None``."""
    start = dt.datetime.combine(climate_day, dt.time(), tzinfo=dt.UTC) - dt.timedelta(
        hours=std_utc_offset_hours
    )
    end = start + dt.timedelta(days=1)
    best: float | None = None
    for csv_file in sorted((archive_root / "metar-routine" / icao).glob("*.csv")):
        lines = csv_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines:
            continue
        header = lines[0].split(",")
        if not all(name in header for name in _METAR_COLUMNS):
            continue
        when_at, temp_at = (header.index(name) for name in _METAR_COLUMNS)
        for line in lines[1:]:
            fields = line.split(",", max(when_at, temp_at) + 1)
            if len(fields) <= max(when_at, temp_at):
                continue
            when = _utc(fields[when_at])
            if when is None or not start <= when < end:
                continue
            try:
                value = float(fields[temp_at])
            except ValueError:
                continue
            best = value if best is None else max(best, value)
    return None if best is None else round(best)


def k3_flips(
    records: Sequence[FillRecord], archive_root: Path | None, *, present: bool
) -> dict[str, bool] | None:
    """fill_id -> does the outcome flip when the METAR max replaces the CLI tmax (covered fills
    only); ``None`` when the source is absent or covers no fill (UNTESTABLE, never zero)."""
    if archive_root is None or not present:
        return None
    registry = default_registry()
    flips: dict[str, bool] = {}
    for rec in records:
        icao = registry.settlement_site(VENUE, rec.station).icao
        offset = registry.climate_day_window(VENUE, rec.station).std_utc_offset_hours
        metar = metar_daily_max(archive_root, icao, rec.climate_day, offset)
        if metar is not None:
            flips[rec.fill_id] = (edge_distance(rec.instrument_id, metar) == 0) != rec.won
    return flips or None


def k4_mismatches(
    records: Sequence[FillRecord], venue_outcomes: Path | None
) -> dict[str, bool] | None:
    """fill_id -> venue-resolved YES outcome differs from the slug-parsed one. The file is a JSON
    object ``{instrument_id: bool}``; an absent file or no overlap is UNTESTABLE."""
    if venue_outcomes is None or not venue_outcomes.is_file():
        return None
    resolved = json.loads(venue_outcomes.read_text())
    mismatches = {
        r.fill_id: bool(resolved[r.instrument_id]) != r.won
        for r in records
        if r.instrument_id in resolved
    }
    return mismatches or None
