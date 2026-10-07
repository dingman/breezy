"""F13 Phase A feature build: the NBP, PFM and GFS-MOS readers.

Read-only, no network. Everything reuses an existing reader or selector so the blend scores the
SAME inputs the champion does:

* NBP (FB-R5): ``nbp_skill_study.iter_nbp_derived_rows`` / ``complete_percentile_windows`` (now
  carries ``available_at_ns``, the max over the window's rows) and ``_select_d1_window`` with
  ``QUALIFYING_CYCLE_HOURS`` and ``climate_day_for_txn`` (the champion's own D+1 selector). The
  availability basis is the store's nominal ``max(LastModified, cycle + floor)``, flagged by the
  builder;
* PFM (FB-R8): the first-seen revision (``-r0``) keyed on the WMO issuance, ``parse_pfm_product``;
  available at issuance + the pinned lag. A later revision never replaces it, and the first stored
  row is asserted to be the earliest fetched;
* GFS MOS (FB-R7): ``resolve_mos_coverage`` / ``read_mos_windows`` and
  ``forecast_cycles_from_mos_payload(model="GFS")``. A coverage gap is reported, not fatal; a
  payload whose rows are not all the requested model is refused (``refuse_model_mix``, L-13).

Rows dated on or after the caller's end (the sealed holdout) are never read.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_cheap_screen_wp7 import (  # type: ignore[import-not-found]
    forecast_cycles_from_mos_payload,
)
from forecast_conditional_corpus import (  # type: ignore[import-not-found]
    MosCoverageGapError,
    read_mos_windows,
    resolve_mos_coverage,
)

from breezy.analysis.multisource_blend_features import SourceVintage
from breezy.ingest.gaps import local_standard_date
from breezy.ingest.pfm_parse import PfmParseError, parse_pfm_product
from breezy.persistence.archive_cache import ArchiveCache, ArchiveCacheError, CoverageEntry
from breezy.persistence.us_source_request import (
    US_PFM_AFOS_SOURCE,
    US_SOURCE_PRODUCTS,
    revision_product_pattern,
    revision_request,
)
from breezy.strategy.ladder_ev.quantile_density import Percentiles
from scripts.analysis import nbp_skill_study as nss
from scripts.archive.iem_mos_backfill import ModelMixError, refuse_model_mix

__all__ = [
    "FeatureInputError",
    "MosResult",
    "NbpCandidate",
    "collect_mos_vintages",
    "collect_nbp_candidates",
    "collect_pfm_vintages",
    "select_nbp",
]

_NS: Final[int] = 1_000_000_000
_DAY: Final[dt.timedelta] = dt.timedelta(days=1)
#: GFS MOS runs at 00/06/12/18Z and reaches a few days out; three days of earlier runtimes cover
#: every cycle that can still be the latest one before a D-1 anchor.
_MOS_RUNTIME_LOOKBACK: Final[dt.timedelta] = dt.timedelta(days=3)


class FeatureInputError(ValueError):
    """An input that cannot be used point-in-time (never imputed, never guessed)."""


# ------------------------------------------------------------------ NBP (FB-R5)


@dataclass(frozen=True, slots=True)
class NbpCandidate:
    """One qualifying cycle's complete D+1 window for one settlement-station climate day."""

    station: str
    climate_day: dt.date
    cycle_runtime_ns: int
    available_at_ns: int | None
    version: str
    percentiles: Percentiles


def collect_nbp_candidates(
    root: Path,
    registry: nss.StationRegistry,
    *,
    end_exclusive: dt.date,
    counts: Counter[str],
) -> dict[tuple[str, dt.date], list[NbpCandidate]]:
    """``(settlement station, climate day) -> candidate cycles``, streamed one partition at a time.

    Uses the champion's own selector (``_select_d1_window`` over ``QUALIFYING_CYCLE_HOURS``), so a
    candidate exists exactly where ``build_version_rows`` would mint a champion row. Cycles whose
    explicit D+1 target is on or after ``end_exclusive`` are dropped before anything is kept.
    """
    out: dict[tuple[str, dt.date], list[NbpCandidate]] = defaultdict(list)
    for _path, rows in nss.iter_nbp_derived_rows(root):
        if rows is None:
            counts["nbp_partition_unreadable"] += 1
            continue
        group_counts = nss._WindowGroupCounts()
        windows = nss.complete_percentile_windows(rows, counts=group_counts)
        counts["nbp_incomplete_windows"] += group_counts.incomplete_windows
        by_cycle: dict[tuple[str, int], list[nss.NbpPercentileWindow]] = defaultdict(list)
        for window in windows:
            by_cycle[(window.station, window.cycle_runtime_ns)].append(window)
        for (icao, cycle_ns), group in by_cycle.items():
            _keep_cycle(out, registry, icao, cycle_ns, group, end_exclusive, counts)
    for candidates in out.values():
        candidates.sort(key=lambda c: c.cycle_runtime_ns)
    return dict(out)


def _keep_cycle(
    out: dict[tuple[str, dt.date], list[NbpCandidate]],
    registry: nss.StationRegistry,
    icao: str,
    cycle_ns: int,
    group: Sequence[nss.NbpPercentileWindow],
    end_exclusive: dt.date,
    counts: Counter[str],
) -> None:
    if nss._cycle_hour(cycle_ns) not in nss.QUALIFYING_CYCLE_HOURS:
        counts["nbp_non_qualifying_cycle"] += 1
        return
    offset = registry.std_utc_offset_hours_by_icao.get(icao)
    settlement_station = registry.settlement_station_by_icao.get(icao)
    if offset is None or settlement_station is None:
        counts["nbp_unmapped_station"] += 1
        return
    target = local_standard_date(cycle_ns, offset) + _DAY
    if target >= end_exclusive:
        counts["nbp_holdout_excluded"] += 1
        return
    gaps: Counter[str] = Counter()
    chosen = nss._select_d1_window(
        group,
        station=icao,
        cycle_runtime_ns=cycle_ns,
        offset=offset,
        target_day=target,
        gaps=gaps,
    )
    for name, count in gaps.items():
        counts[f"nbp_{name}"] += count
    if chosen is None:
        return
    out[(settlement_station, target)].append(
        NbpCandidate(
            station=settlement_station,
            climate_day=target,
            cycle_runtime_ns=cycle_ns,
            available_at_ns=chosen.available_at_ns,
            version=chosen.nbm_version_era,
            percentiles=chosen.percentiles,
        )
    )


def select_nbp(
    candidates: Sequence[NbpCandidate], *, anchor_ns: int, extra_lag_ns: int = 0
) -> NbpCandidate | None:
    """Latest cycle whose availability (+ the twin's extra lag) is strictly before the anchor."""
    best: NbpCandidate | None = None
    for candidate in candidates:
        if candidate.available_at_ns is None:
            raise FeatureInputError(
                f"NBP window {candidate.station} {candidate.climate_day} cycle "
                f"{candidate.cycle_runtime_ns} has no available_at_ns; refused, never imputed"
            )
        if candidate.available_at_ns + extra_lag_ns >= anchor_ns:
            continue
        if best is None or candidate.cycle_runtime_ns > best.cycle_runtime_ns:
            best = candidate
    return best


# ------------------------------------------------------------------ PFM (FB-R8)


def collect_pfm_vintages(
    cache: ArchiveCache,
    *,
    icao: str,
    lag_ns: int,
    end_exclusive: dt.date,
    counts: Counter[str],
) -> dict[dt.date, list[SourceVintage]]:
    """``forecast day -> vintages`` from the first-seen PFM revision of every issuance."""
    pattern = revision_product_pattern(US_SOURCE_PRODUCTS[US_PFM_AFOS_SOURCE])
    by_issue: dict[int, list[tuple[int, CoverageEntry]]] = defaultdict(list)
    for entry in cache.entries(US_PFM_AFOS_SOURCE):
        matched = pattern.fullmatch(entry.product) if entry.station == icao else None
        if matched is not None:
            by_issue[entry.window_start].append((int(matched.group(1)), entry))
    out: dict[dt.date, list[SourceVintage]] = defaultdict(list)
    for issue_ns in sorted(by_issue):
        issued = dt.datetime.fromtimestamp(issue_ns // _NS, tz=dt.UTC)
        if issued.date() >= end_exclusive:
            counts["pfm_after_end_skipped"] += 1
            continue
        revisions = sorted(by_issue[issue_ns], key=lambda item: item[0])
        number, first = revisions[0]
        fetched = [e.fetched_at_ns for _n, e in revisions]
        if number != 0:
            counts["pfm_first_revision_missing"] += 1
        elif fetched[0] > min(fetched):
            counts["pfm_first_revision_not_earliest"] += 1
        else:
            _add_pfm(out, cache, icao, issue_ns, issued, first, lag_ns, end_exclusive, counts)
    return dict(out)


def _add_pfm(
    out: dict[dt.date, list[SourceVintage]],
    cache: ArchiveCache,
    icao: str,
    issue_ns: int,
    issued: dt.datetime,
    first: CoverageEntry,
    lag_ns: int,
    end_exclusive: dt.date,
    counts: Counter[str],
) -> None:
    request = revision_request(
        US_PFM_AFOS_SOURCE,
        icao,
        issue_ns,
        0,
        model=first.model,
    )
    try:
        point = parse_pfm_product(cache.read(request), station=icao, reference_time=issued)
    except PfmParseError:
        counts["pfm_unparseable"] += 1
        return
    except ArchiveCacheError:
        counts["pfm_payload_unreadable"] += 1
        return
    for day, high in point.max_by_day:
        if day < end_exclusive:
            out[day].append(SourceVintage(available_at_ns=issue_ns + lag_ns, mu_f=float(high)))


# ------------------------------------------------------------------ GFS MOS (FB-R7)


@dataclass(frozen=True, slots=True)
class MosResult:
    vintages_by_day: Mapping[dt.date, Sequence[SourceVintage]]
    #: UTC runtime days no manifested entry claims: reported, never fatal, never imputed.
    coverage_gap_days: tuple[dt.date, ...]


def _assert_single_model(body: bytes, model: str) -> None:
    """Refuse a payload whose rows are not all ``model`` (``refuse_model_mix``, L-13)."""
    stream = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline="")
    models = {(row.get("model") or "").strip() for row in csv.DictReader(stream)}
    if not models:
        return
    found = refuse_model_mix(models)
    if found != model:
        raise ModelMixError(f"the payload holds {found!r} rows but {model!r} was requested (L-13)")


def collect_mos_vintages(
    cache: ArchiveCache,
    *,
    icao: str,
    std_utc_offset_hours: float,
    first_day: dt.date,
    last_day: dt.date,
    lag_ns: int,
    model: str,
    counts: Counter[str],
) -> MosResult:
    """``climate day -> vintages`` (one per runtime) for ``[first_day, last_day]``."""
    start = first_day - _MOS_RUNTIME_LOOKBACK
    end = last_day + _DAY
    gaps: tuple[dt.date, ...] = ()
    try:
        coverage = resolve_mos_coverage(cache, station=icao, start=start, end=end, model=model)
    except MosCoverageGapError as exc:
        coverage, gaps = exc.coverage, exc.missing_days
    counts["mos_coverage_gap_days"] += len(gaps)
    out: dict[dt.date, list[SourceVintage]] = defaultdict(list)
    for body, owned_days in read_mos_windows(cache, coverage):
        _assert_single_model(body, model)
        cycles = forecast_cycles_from_mos_payload(
            body,
            icao=icao,
            std_utc_offset_hours=std_utc_offset_hours,
            runtime_days=owned_days,
            model=model,
        )
        for day, entries in cycles.items():
            if first_day <= day <= last_day:
                out[day].extend(
                    SourceVintage(runtime + lag_ns, value) for runtime, value in entries
                )
        del body, cycles
    for vintages in out.values():
        vintages.sort(key=lambda v: v.available_at_ns)
    return MosResult(dict(out), gaps)
