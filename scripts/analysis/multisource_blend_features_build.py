"""F13 Phase A feature assembly: builds the blend runner's two feature files, offline.

Spec: ``docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-phaseA-feature-build_design.md`` (r1 plus
rulings FB-R1..R12). It writes the primary file and the +60 min lag twin that
``multisource_blend_skill.py`` consumes, plus a ``<file>.manifest.json`` sidecar per file and a JSON
report. Every row goes through ``assemble_feature_row`` (leakage checks at assembly), is re-checked
before writing, and the feature files stay header-free.

Inputs (read-only, no network, never the live data root as an output):

* ``--nbp-root`` NBP derived store; ``--us-source-root`` the ``us-lamp-mdl`` / ``us-lav-iem`` /
  ``us-pfm-afos`` revision stores; ``--mos-root`` the ``iem-mos`` cache root (GFS);
  ``--asos-root`` the ``iem-asos-1min`` cache root; ``--truth`` the champion's
  ``settlement_truth.parquet`` (read below the holdout only);
* ``--prereg`` the draft/frozen prereg: it supplies the ``anchors``, ``source_lags_ns``,
  ``obs_source``, ``obs_cadence_seconds`` (3600) and ``obs_routine_minute_by_station`` pins
  (a null or unaccepted pin is refused).

Anchors (FB-R1): D-1 is a UTC hour on the day before; D0 is a local-STANDARD hour (never DST).
``--anchor-variant d0_12lst`` builds the sensitivity pair (D0 at 12:00 LST), never mixed in.

The twin (FB-R2) shifts EVERY source lag by 60 min, NBP included; the CLI label is never shifted.
A row whose NBP window or station-day is shifted out is simply absent from the twin and reported as
lost per horizon. ``obs_available_at_ns`` is shifted in the twin.

Exit codes: 0 complete; 1 degraded (a payload was unreadable; outputs written); 2 refused, leak or
an unexpected error (only the report is written; its ``status`` is ``refused`` or ``error``). The
two feature files and their sidecars are written as one set (temp files, then renames). Holdout
(>= 2026-07-01) rows are never read or emitted; this module never opens the holdout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from settlement_truth_dataset import final_rows_for_gate  # type: ignore[import-not-found]

from breezy.analysis import multisource_blend as msb
from breezy.analysis.memory_cap import apply_address_space_cap
from breezy.analysis.multisource_blend_features import (
    HOLDOUT_START,
    HORIZONS,
    LAG_SHIFT_NS,
    HoldoutLeakError,
    LeakageError,
    ObsReading,
    assemble_feature_row,
)
from breezy.persistence.archive_cache import ArchiveCache
from breezy.persistence.us_source_request import (
    US_LAMP_MDL_SOURCE,
    US_LAV_IEM_SOURCE,
    US_PFM_AFOS_SOURCE,
)
from scripts.analysis import multisource_blend_inputs_obs as obsmod
from scripts.analysis import nbp_skill_study as nss
from scripts.analysis.multisource_blend_inputs_forecast import (
    FeatureInputError,
    NbpCandidate,
    collect_mos_vintages,
    collect_nbp_candidates,
    collect_pfm_vintages,
    select_nbp,
)
from scripts.analysis.multisource_blend_inputs_lamp import LampArchive
from scripts.analysis.multisource_blend_inputs_pins import (
    LAG_FLOORS_NS,
    Anchors,
    BuildRefusal,
    Pins,
    anchor_ns_for,
    load_pins,
    parse_anchors,
)
from scripts.analysis.multisource_blend_inputs_report import (
    lag_report,
    lamp_breaks,
    nbp_version_breaks,
    obs_report,
    source_lags,
    truth_concordance,
)
from scripts.analysis.multisource_blend_sidecar import (
    ANCHOR_VARIANTS,
    PRIMARY_VARIANT,
    SIDECAR_SCHEMA,
    SIDECAR_SUFFIX,
    sha256_file,
)
from scripts.analysis.multisource_blend_skill import content_digest
from scripts.archive.iem_mos_backfill import ModelMixError

__all__ = [
    "EXIT_DEGRADED",
    "EXIT_OK",
    "EXIT_REFUSED",
    "LAG_FLOORS_NS",
    "Anchors",
    "BuildRefusal",
    "Pins",
    "anchor_ns_for",
    "load_pins",
    "main",
    "parse_anchors",
    "read_only_cache",
]

EXIT_OK: Final[int] = 0
EXIT_DEGRADED: Final[int] = 1
EXIT_REFUSED: Final[int] = 2
DEFAULT_MAX_MEMORY_GIB: Final[float] = 4.0
DEFAULT_STATIONS: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")
LIVE_DATA_ROOT: Final[Path] = Path.home() / ".local" / "share" / "breezy"
_DAY: Final[dt.timedelta] = dt.timedelta(days=1)
MOS_MODEL: Final[str] = "GFS"
#: Counts meaning a payload could not be used: the run is degraded (exit 1), outputs written.
DEGRADING_COUNTS: Final[tuple[str, ...]] = (
    "nbp_partition_unreadable",
    "lamp_run_unreadable",
    "pfm_unparseable",
    "pfm_payload_unreadable",
    "pfm_first_revision_missing",
    "pfm_first_revision_not_earliest",
    "year_payload_unavailable",
    "out_of_order",
)
_REFUSALS: Final[tuple[type[Exception], ...]] = (
    FeatureInputError,
    LeakageError,
    HoldoutLeakError,
    ModelMixError,
    obsmod.ObsQuantisationError,
)


_CAUGHT: Final[tuple[type[Exception], ...]] = (BuildRefusal, *_REFUSALS)


class _NoClock:
    def timestamp_ns(self) -> int:
        return 0


def _refuse_fetch(_request: object) -> bytes:
    raise RuntimeError("the feature builder never fetches; every payload must already be on disk")


def read_only_cache(root: Path) -> ArchiveCache:
    """An ``ArchiveCache`` that can only read: any miss would call a fetcher that always refuses."""
    return ArchiveCache(root, fetch=_refuse_fetch, clock=_NoClock())


# ------------------------------------------------------------------ configuration and path guards


@dataclass(frozen=True, slots=True)
class Config:
    prereg: Path
    nbp_root: Path
    us_root: Path
    mos_root: Path
    asos_root: Path
    truth: Path
    start: dt.date
    end: dt.date
    stations: tuple[str, ...]
    out_features: Path
    out_lag: Path
    report: Path
    variant: str
    f2_truth: Path | None


def _inside(path: Path, root: Path) -> bool:
    resolved, base = path.resolve(), root.resolve()
    return resolved == base or base in resolved.parents


def _guard_outputs(cfg: Config) -> None:
    """Writes are refused under the live data root and under any input; existing files are kept."""
    inputs = [cfg.nbp_root, cfg.us_root, cfg.mos_root, cfg.asos_root, cfg.truth, cfg.prereg]
    if cfg.f2_truth is not None:
        inputs.append(cfg.f2_truth)
    for path in (cfg.out_features, cfg.out_lag, cfg.report):
        if _inside(path, LIVE_DATA_ROOT):
            raise BuildRefusal(f"refusing to write into the live data root: {path}")
        if any(_inside(path, root) for root in inputs):
            raise BuildRefusal(f"refusing to write inside an input root: {path}")
    for path in (cfg.out_features, cfg.out_lag):
        for target in (path, Path(str(path) + SIDECAR_SUFFIX)):
            if target.exists():
                raise BuildRefusal(f"{target} already exists; outputs are write-once")


def _tmp_name(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _stage(path: Path, data: bytes) -> Path:
    """Write ``data`` to ``<path>.tmp`` (a stale one from an interrupted run is replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_name(path)
    tmp.unlink(missing_ok=True)
    with tmp.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return tmp


def _publish(staged: Sequence[tuple[Path, Path]]) -> None:
    published: list[Path] = []
    try:
        for tmp, path in staged:
            os.replace(tmp, path)
            published.append(path)
    except BaseException:
        for path in published:  # none of them existed before: _guard_outputs checked
            path.unlink(missing_ok=True)
        raise


def _write_set(items: Sequence[tuple[Path, bytes]]) -> None:
    """Write every file to a temp name, then rename the set; a failure leaves none of them."""
    staged: list[tuple[Path, Path]] = []
    try:
        for path, data in items:
            tmp = _tmp_name(path)
            staged.append((tmp, path))  # registered first so a partial write is cleaned too
            _stage(path, data)
        _publish(staged)
    except BaseException:
        for tmp, _path in staged:
            tmp.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    return sha256_file(path) if path.is_file() else "absent"


# ------------------------------------------------------------------ the build


@dataclass(slots=True)
class _Tally:
    counts: Counter[str]
    by_horizon: dict[str, Counter[str]]
    obs_raw_differs: int = 0
    obs_five_min_differs: int = 0


@dataclass(slots=True)
class _Context:
    tally: _Tally
    truth: Mapping[tuple[str, dt.date], Any]
    nbp: Mapping[tuple[str, dt.date], list[NbpCandidate]]
    lamp: LampArchive
    us_cache: ArchiveCache
    mos_cache: ArchiveCache
    asos_cache: ArchiveCache


@dataclass(frozen=True, slots=True)
class _Station:
    icao: str
    key: str
    offset: float


@dataclass(frozen=True, slots=True)
class _RowInputs:
    station: _Station
    day: dt.date
    horizon: str
    anchor_ns: int
    lamp_runs: Sequence[Any]
    readings: Sequence[ObsReading]
    pfm: Sequence[Any]
    mos: Sequence[Any]


@dataclass(slots=True)
class _Rows:
    """The two files' rows, and the LAMP basis seen per station, horizon and day."""

    primary: list[msb.FeatureRow]
    lag: list[msb.FeatureRow]
    lamp_bases: dict[str, dict[str, dict[dt.date, str | None]]]


def _day_range(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _shifted(readings: Sequence[ObsReading], shift_ns: int) -> list[ObsReading]:
    return [ObsReading(r.ts_ns, r.available_at_ns + shift_ns, r.temp_f, r.source) for r in readings]


def _routine_minute(pins: Pins, station: _Station) -> int:
    minute = pins.obs_routine_minute_by_station.get(station.icao)
    if minute is None:
        raise BuildRefusal(
            f"pins.obs_routine_minute_by_station has no entry for {station.icao} (FB-R13)"
        )
    return minute


def _station_days(cfg: Config, ctx: _Context, station: _Station) -> list[dt.date]:
    days: list[dt.date] = []
    for day in _day_range(cfg.start, cfg.end):
        if (station.key, day) in ctx.truth:
            days.append(day)
        else:
            for horizon in HORIZONS:
                ctx.tally.by_horizon[horizon]["truth_missing"] += 1
    return days


def _assemble(ctx: _Context, item: _RowInputs, shift_ns: int) -> msb.FeatureRow | None:
    candidates: Sequence[NbpCandidate] = ctx.nbp.get((item.station.key, item.day), ())
    nbp = select_nbp(candidates, anchor_ns=item.anchor_ns, extra_lag_ns=shift_ns)
    if nbp is None:
        ctx.tally.by_horizon[item.horizon]["nbp_missing_lag" if shift_ns else "nbp_missing"] += 1
        return None
    truth = ctx.truth[(item.station.key, item.day)]
    readings = _shifted(item.readings, shift_ns) if shift_ns else list(item.readings)
    return assemble_feature_row(
        station=item.station.key,
        climate_day=item.day,
        version=nbp.version,
        horizon=item.horizon,
        anchor_ns=item.anchor_ns,
        std_utc_offset_hours=item.station.offset,
        percentiles=nbp.percentiles,
        cli_tmax_f=float(truth.tmax_f),
        obs_readings=readings,
        lamp_runs=item.lamp_runs,
        pfm_vintages=item.pfm,
        mos_vintages=item.mos,
        extra_lag_ns=shift_ns,
        nbp_cycle_ns=nbp.cycle_runtime_ns,
    )


def _tally_row(tally: _Tally, row: msb.FeatureRow, shift_ns: int) -> None:
    cell = tally.by_horizon[row.horizon]
    suffix = "_lag" if shift_ns else ""
    cell[f"rows{suffix}"] += 1
    if shift_ns:
        return
    cell["lamp_missing"] += int(row.lamp.missing)
    cell["pfm_missing"] += int(row.pfm_mu_f is None)
    cell["mos_missing"] += int(row.mos_mu_f is None)
    cell["obs_missing"] += int(row.obs_so_far_f is None)


def _tally_obs_arms(
    tally: _Tally, row: msb.FeatureRow, obs_year: obsmod.ObsYear, day: dt.date, anchor: int
) -> None:
    """The descriptive raw 1-min and 5-min arms: counted against the feature, never a feature."""
    raw = obsmod.raw_running_max_at(obs_year.raw_max_by_day.get(day, ()), anchor)
    tally.obs_raw_differs += int(raw != row.obs_so_far_f)
    five = obsmod.raw_running_max_at(obs_year.five_min_max_by_day.get(day, ()), anchor)
    tally.obs_five_min_differs += int(five != row.obs_so_far_f)


def _emit_rows(ctx: _Context, item: _RowInputs, obs_year: obsmod.ObsYear, rows: _Rows) -> None:
    for shift, target in ((0, rows.primary), (LAG_SHIFT_NS, rows.lag)):
        row = _assemble(ctx, item, shift)
        if row is None:
            continue
        target.append(row)
        _tally_row(ctx.tally, row, shift)
        if shift == 0 and item.horizon == "D0":
            _tally_obs_arms(ctx.tally, row, obs_year, item.day, item.anchor_ns)


@dataclass(frozen=True, slots=True)
class _StationSources:
    pfm: Mapping[dt.date, Sequence[Any]]
    mos: Mapping[dt.date, Sequence[Any]]
    routine_minute: int


def _load_sources(cfg: Config, pins: Pins, station: _Station, ctx: _Context) -> _StationSources:
    minute = _routine_minute(pins, station)
    counts = ctx.tally.counts
    pfm = collect_pfm_vintages(
        ctx.us_cache,
        icao=station.icao,
        lag_ns=pins.lags["pfm"],
        end_exclusive=cfg.end + _DAY,
        counts=counts,
    )
    mos = collect_mos_vintages(
        ctx.mos_cache,
        icao=station.icao,
        std_utc_offset_hours=station.offset,
        first_day=cfg.start,
        last_day=cfg.end,
        lag_ns=pins.lags["mos-gfs"],
        model=MOS_MODEL,
        counts=counts,
    )
    return _StationSources(pfm, mos.vintages_by_day, minute)


def _build_year(
    pins: Pins,
    station: _Station,
    ctx: _Context,
    sources: _StationSources,
    year: int,
    anchors: Mapping[tuple[dt.date, str], int],
    year_days: Sequence[dt.date],
    rows: _Rows,
) -> None:
    cutoffs = {d: max(anchors[(d, h)] for h in HORIZONS) for d in year_days}
    obs_year = obsmod.read_obs_year(
        ctx.asos_cache,
        station.icao,
        year,
        std_utc_offset_hours=station.offset,
        routine_minute=sources.routine_minute,
        lag_ns=pins.lags["obs"],
        cutoff_ns_by_day=cutoffs,
    )
    ctx.tally.counts.update(obs_year.counts)
    bases = rows.lamp_bases[station.icao]
    for day in year_days:
        readings = obs_year.readings_by_day.get(day, ())
        for horizon in HORIZONS:
            anchor = anchors[(day, horizon)]
            choice = ctx.lamp.runs_for(station.icao, anchor_ns=anchor)
            bases[horizon][day] = choice.basis
            item = _RowInputs(
                station, day, horizon, anchor, choice.runs, readings,
                sources.pfm.get(day, ()), sources.mos.get(day, ()),
            )  # fmt: skip
            _emit_rows(ctx, item, obs_year, rows)


def _build_station(cfg: Config, pins: Pins, station: _Station, ctx: _Context, rows: _Rows) -> None:
    sources = _load_sources(cfg, pins, station, ctx)
    days = _station_days(cfg, ctx, station)
    anchors = {
        (day, h): anchor_ns_for(h, day, station.offset, pins.anchors, variant=cfg.variant)
        for day in days
        for h in HORIZONS
    }
    rows.lamp_bases[station.icao] = {h: {} for h in HORIZONS}
    for year in sorted({d.year for d in days}):
        year_days = [d for d in days if d.year == year]
        _build_year(pins, station, ctx, sources, year, anchors, year_days, rows)


def _truth_lookup(cfg: Config) -> dict[tuple[str, dt.date], Any]:
    rows = nss.read_settlement_truth_rows(cfg.truth, climate_day_before=HOLDOUT_START)
    return {
        (r.station, r.climate_day): r
        for r in final_rows_for_gate(rows)
        if r.climate_day < HOLDOUT_START and r.tmax_f is not None
    }


def _check_unique(rows: Sequence[msb.FeatureRow], name: str) -> None:
    keys = [(r.station, r.climate_day, r.horizon) for r in rows]
    if len(keys) != len(set(keys)):
        raise BuildRefusal(f"{name}: more than one row for a (station, climate_day, horizon) key")


def _check_rows(primary: Sequence[msb.FeatureRow], lag: Sequence[msb.FeatureRow]) -> None:
    """The post-build re-check: unique keys, pre-holdout, and no leak under each file's own lag."""
    _check_unique(primary, "primary")
    _check_unique(lag, "lag")
    for rows, extra_lag_ns in ((primary, 0), (lag, LAG_SHIFT_NS)):
        msb.assert_pre_holdout(rows)
        for row in rows:
            msb.assert_row_leakage_free(row, extra_lag_ns=extra_lag_ns)


def _inputs_sha(cfg: Config) -> dict[str, str]:
    manifests = {
        "nbp_manifest": cfg.nbp_root / "_manifest.json",
        "us_lamp_mdl": cfg.us_root / US_LAMP_MDL_SOURCE / "coverage.json",
        "us_lav_iem": cfg.us_root / US_LAV_IEM_SOURCE / "coverage.json",
        "us_pfm_afos": cfg.us_root / US_PFM_AFOS_SOURCE / "coverage.json",
        "iem_mos": cfg.mos_root / "iem-mos" / "coverage.json",
        "iem_asos_1min": cfg.asos_root / "iem-asos-1min" / "coverage.json",
        "truth": cfg.truth,
        "prereg": cfg.prereg,
    }
    return {name: _sha256(path) for name, path in manifests.items()}


def _sidecar(
    role: str,
    data: bytes,
    digest: str,
    pins: Pins,
    cfg: Config,
    rows: int,
    breaks: Mapping[str, Any],
) -> bytes:
    body = {
        "schema": SIDECAR_SCHEMA,
        "role": role,
        "prereg_content_sha256": digest,
        "features_sha256": hashlib.sha256(data).hexdigest(),
        "n_rows": rows,
        "anchor_variant": cfg.variant,
        "anchors": pins.anchors_raw,
        "source_lags_ns": dict(pins.lags),
        "obs_source": obsmod.OBS_SOURCE_LABEL,
        "obs_cadence_seconds": obsmod.ROUTINE_OBS_CADENCE_SECONDS,
        "obs_routine_minute_by_station": dict(pins.obs_routine_minute_by_station),
        "source_breaks_observed": breaks,
        "lag_shift_ns": LAG_SHIFT_NS if role == "lag" else 0,
        "obs_available_at_ns_shifted": role == "lag",
    }
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _lines(rows: Sequence[msb.FeatureRow]) -> bytes:
    ordered = sorted(rows, key=lambda r: (r.station, r.climate_day, r.horizon))
    body = "\n".join(json.dumps(msb.feature_row_to_json(r), sort_keys=True) for r in ordered)
    return (body + "\n").encode("utf-8") if ordered else b""


def _make_context(cfg: Config, pins: Pins, registry: nss.StationRegistry) -> _Context:
    counts: Counter[str] = Counter()
    return _Context(
        tally=_Tally(counts, {h: Counter() for h in HORIZONS}),
        truth=_truth_lookup(cfg),
        nbp=collect_nbp_candidates(
            cfg.nbp_root, registry, end_exclusive=cfg.end + _DAY, counts=counts
        ),
        lamp=LampArchive(
            read_only_cache(cfg.us_root),
            cfg.us_root,
            lag_ns_by_source=pins.lags,
            holdout_start=HOLDOUT_START,
            counts=counts,
        ),
        us_cache=read_only_cache(cfg.us_root),
        mos_cache=read_only_cache(cfg.mos_root),
        asos_cache=read_only_cache(cfg.asos_root),
    )


def _build_all(cfg: Config, pins: Pins, registry: nss.StationRegistry, ctx: _Context) -> _Rows:
    rows = _Rows([], [], {})
    for icao in cfg.stations:
        key = registry.settlement_station_by_icao[icao]
        station = _Station(icao, key, registry.std_utc_offset_hours_by_icao[icao])
        _build_station(cfg, pins, station, ctx, rows)
    return rows


def _write_outputs(
    cfg: Config,
    pins: Pins,
    digest: str,
    rows: _Rows,
    breaks: Mapping[str, Any],
    report: dict[str, Any],
) -> None:
    items: list[tuple[Path, bytes]] = []
    for role, role_rows, path in (
        ("primary", rows.primary, cfg.out_features),
        ("lag", rows.lag, cfg.out_lag),
    ):
        data = _lines(role_rows)
        side = _sidecar(role, data, digest, pins, cfg, len(role_rows), breaks)
        items += [(Path(str(path) + SIDECAR_SUFFIX), side), (path, data)]
        report.setdefault("output_sha256", {})[role] = hashlib.sha256(data).hexdigest()
        report.setdefault("n_rows", {})[role] = len(role_rows)
    _write_set(items)


def _validated_registry(cfg: Config) -> nss.StationRegistry:
    registry = nss.station_registry(stations=cfg.stations)
    unknown = [s for s in cfg.stations if s not in registry.std_utc_offset_hours_by_icao]
    if unknown:
        raise BuildRefusal(f"stations {unknown} are not in the registry")
    return registry


def run_build(cfg: Config, report: dict[str, Any]) -> int:
    """Build both files; returns the exit code. Raises on refusal (the caller writes the report)."""
    if cfg.end >= HOLDOUT_START:
        raise BuildRefusal(
            f"--end {cfg.end} is on or after the sealed holdout start {HOLDOUT_START}"
        )
    if cfg.start > cfg.end:
        raise BuildRefusal("--start is after --end")
    _guard_outputs(cfg)
    design = json.loads(cfg.prereg.read_text(encoding="utf-8"))
    digest = content_digest(design)
    report.update(
        prereg_content_sha256=digest, anchor_variant=cfg.variant, inputs_sha256=_inputs_sha(cfg)
    )
    pins = load_pins(design)
    report["source_lags"] = source_lags(pins)
    registry = _validated_registry(cfg)
    ctx = _make_context(cfg, pins, registry)
    rows = _build_all(cfg, pins, registry, ctx)
    _check_rows(rows.primary, rows.lag)
    breaks = {**lamp_breaks(rows.lamp_bases), "nbp_versions": nbp_version_breaks(rows.primary)}
    counts, tally = ctx.tally.counts, ctx.tally
    report.update(
        counts=dict(counts),
        by_horizon={h: dict(c) for h, c in tally.by_horizon.items()},
        lag_file=lag_report(rows.primary, rows.lag),
        obs=obs_report(
            five_min_differs=tally.obs_five_min_differs,
            raw_differs=tally.obs_raw_differs,
            pins=pins,
        ),
        source_breaks_observed=breaks,
        truth_concordance=truth_concordance(cfg.f2_truth, ctx.truth),
        nbp_availability_basis="nominal: store max(LastModified, cycle + floor), flagged",
        pfm_iem_entered_time="unavailable_in_archive",
        mos_model=MOS_MODEL,
    )
    _write_outputs(cfg, pins, digest, rows, breaks, report)
    degraded = [k for k in DEGRADING_COUNTS if counts.get(k)]
    report["degraded_reasons"] = degraded
    return EXIT_DEGRADED if degraded else EXIT_OK


# ------------------------------------------------------------------ CLI


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--nbp-root", type=Path, required=True)
    parser.add_argument("--us-source-root", type=Path, required=True)
    parser.add_argument("--mos-root", type=Path, required=True)
    parser.add_argument("--asos-root", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--stations", nargs="+", default=list(DEFAULT_STATIONS))
    parser.add_argument("--out-features", type=Path, required=True)
    parser.add_argument("--out-lag-features", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--anchor-variant", choices=ANCHOR_VARIANTS, default=PRIMARY_VARIANT)
    parser.add_argument("--f2-truth", type=Path, default=None)
    parser.add_argument("--max-memory-gib", type=float, default=DEFAULT_MAX_MEMORY_GIB)
    return parser.parse_args(sys.argv[1:] if argv is None else list(argv))


def _config(args: argparse.Namespace) -> Config:
    return Config(
        prereg=args.prereg,
        nbp_root=args.nbp_root,
        us_root=args.us_source_root,
        mos_root=args.mos_root,
        asos_root=args.asos_root,
        truth=args.truth,
        start=args.start,
        end=args.end,
        stations=tuple(args.stations),
        out_features=args.out_features,
        out_lag=args.out_lag_features,
        report=args.report_json,
        variant=args.anchor_variant,
        f2_truth=args.f2_truth,
    )


def _run_reporting(cfg: Config, report: dict[str, Any]) -> int:
    """Run the build; every failure is recorded in ``report`` and exits 2 (never a bare swallow)."""
    try:
        code = run_build(cfg, report)
    except _CAUGHT as exc:
        status = "refused"
        reason = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - any unexpected failure must still reach the report
        status = "error"
        reason = f"{type(exc).__name__}: {exc}"
    else:
        report.update(status="complete" if code == EXIT_OK else "degraded", exit_code=code)
        return code
    report.update(status=status, exit_code=EXIT_REFUSED, reason=reason)
    print(f"{status.upper()}: {reason}", file=sys.stderr)
    return EXIT_REFUSED


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = _config(args)
    apply_address_space_cap(args.max_memory_gib)
    if _inside(cfg.report, LIVE_DATA_ROOT) or cfg.report.exists():
        print(f"REFUSED: refusing to write the report at {cfg.report}", file=sys.stderr)
        return EXIT_REFUSED
    report: dict[str, Any] = {"status": "refused", "exit_code": EXIT_REFUSED, "reason": None}
    code = _run_reporting(cfg, report)
    body = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    _write_set([(cfg.report, body.encode("utf-8"))])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
