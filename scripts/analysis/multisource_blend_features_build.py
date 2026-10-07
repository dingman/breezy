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
  ``obs_source`` and ``obs_cadence_seconds`` pins (a null or unaccepted pin is refused).

Anchors (FB-R1): D-1 is a UTC hour on the day before; D0 is a local-STANDARD hour (never DST).
``--anchor-variant d0_12lst`` builds the sensitivity pair (D0 at 12:00 LST), never mixed in.

The twin (FB-R2) shifts EVERY source lag by 60 min, NBP included; the CLI label is never shifted.
A row whose NBP window or station-day is shifted out is simply absent from the twin and reported as
lost per horizon. ``obs_available_at_ns`` is shifted in the twin.

Exit codes: 0 complete; 1 degraded (a payload was unreadable; outputs written); 2 refused or leak
(only the report is written). Holdout (>= 2026-07-01) rows are never read or emitted; this module
never opens the holdout.
"""

from __future__ import annotations

import argparse
import csv
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
from scripts.analysis.multisource_blend_inputs_lamp import LampArchive, basis_breaks
from scripts.analysis.multisource_blend_skill import SIDECAR_SCHEMA, SIDECAR_SUFFIX, content_digest
from scripts.archive.iem_mos_backfill import ModelMixError

__all__ = [
    "EXIT_DEGRADED",
    "EXIT_OK",
    "EXIT_REFUSED",
    "BuildRefusal",
    "anchor_ns_for",
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
_MIN_NS: Final[int] = 60 * 1_000_000_000
_DAY: Final[dt.timedelta] = dt.timedelta(days=1)
MOS_MODEL: Final[str] = "GFS"
VARIANTS: Final[tuple[str, ...]] = ("primary", "d0_12lst")
OFFSET_RULE: Final[str] = "fixed_standard_time_never_dst"
#: R29 conservative floors: a pinned lag below its floor is refused (FB-R4).
LAG_FLOORS_NS: Final[Mapping[str, int]] = {
    "lamp-mdl": 60 * _MIN_NS,
    "lav-iem": 90 * _MIN_NS,
    "pfm": 60 * _MIN_NS,
    "mos-gfs": 300 * _MIN_NS,
    "obs": 15 * _MIN_NS,
}
_LAG_BASIS: Final[Mapping[str, str]] = {
    "lamp-mdl": "nominal run time + max(60 min, C1 max)",
    "lav-iem": "nominal run label + max(60 min, C1 max) + 30 min (label HH:00, real run HH:30)",
    "pfm": "WMO issuance + 60 min (IEM entered time is not in the archive)",
    "mos-gfs": "runtime + 5 h",
    "obs": "report time + 15 min",
}
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


class BuildRefusal(Exception):
    """The build is refused; only the report is written."""


_CAUGHT: Final[tuple[type[Exception], ...]] = (BuildRefusal, *_REFUSALS)


class _NoClock:
    def timestamp_ns(self) -> int:
        return 0


def _refuse_fetch(_request: object) -> bytes:
    raise RuntimeError("the feature builder never fetches; every payload must already be on disk")


def read_only_cache(root: Path) -> ArchiveCache:
    """An ``ArchiveCache`` that can only read: any miss would call a fetcher that always refuses."""
    return ArchiveCache(root, fetch=_refuse_fetch, clock=_NoClock())


# ------------------------------------------------------------------ pins


@dataclass(frozen=True, slots=True)
class Anchors:
    d_minus_1_utc_hour: int
    d0_lst_hour: int
    d0_sensitivity_lst_hour: int


def _hour(raw: Any, kind: str, name: str) -> int:
    ok = isinstance(raw, Mapping) and raw.get("kind") == kind
    hour = raw.get("hour") if isinstance(raw, Mapping) else None
    if not ok or isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise BuildRefusal(
            f"pins.anchors.{name} must be {{kind: {kind}, hour: 0..23}}, was {raw!r}"
        )
    return hour


def parse_anchors(raw: Any) -> Anchors:
    """FB-R1: validate the ``anchors`` pin (D-1 UTC hour, D0 and D0-sensitivity LST hours)."""
    if not isinstance(raw, Mapping):
        raise BuildRefusal(f"pins.anchors must be an object, was {raw!r}")
    if raw.get("offset_rule") != OFFSET_RULE:
        raise BuildRefusal(f"pins.anchors.offset_rule must be {OFFSET_RULE!r}")
    return Anchors(
        _hour(raw.get("D-1"), "utc", "D-1"),
        _hour(raw.get("D0"), "lst", "D0"),
        _hour(raw.get("D0_sensitivity"), "lst", "D0_sensitivity"),
    )


def anchor_ns_for(
    horizon: str,
    day: dt.date,
    std_utc_offset_hours: float,
    anchors: Anchors,
    *,
    variant: str = "primary",
) -> int:
    """The anchor instant (ns): D-1 is a UTC hour the day before; D0 an LST hour (fixed offset)."""
    midnight = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
    if horizon == "D-1":
        moment = midnight - _DAY + dt.timedelta(hours=anchors.d_minus_1_utc_hour)
    elif horizon == "D0":
        hour = anchors.d0_sensitivity_lst_hour if variant == "d0_12lst" else anchors.d0_lst_hour
        moment = midnight - dt.timedelta(hours=std_utc_offset_hours) + dt.timedelta(hours=hour)
    else:
        raise ValueError(f"horizon must be one of {HORIZONS}, was {horizon!r}")
    return int(moment.timestamp()) * 1_000_000_000


def _parse_lags(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Mapping) or set(raw) != set(LAG_FLOORS_NS):
        raise BuildRefusal(
            f"pins.source_lags_ns must be an object with keys {sorted(LAG_FLOORS_NS)}"
        )
    lags: dict[str, int] = {}
    for key, floor in LAG_FLOORS_NS.items():
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise BuildRefusal(f"pins.source_lags_ns.{key} must be integer ns, was {value!r}")
        if value < floor:
            raise BuildRefusal(
                f"pins.source_lags_ns.{key} = {value} ns is below the conservative floor {floor} ns"
            )
        lags[key] = value
    return lags


@dataclass(frozen=True, slots=True)
class Pins:
    anchors: Anchors
    anchors_raw: Mapping[str, Any]
    lags: Mapping[str, int]


def load_pins(design: Mapping[str, Any]) -> Pins:
    pins = design.get("pins")
    if not isinstance(pins, Mapping):
        raise BuildRefusal("the prereg has no `pins` object")
    anchors = parse_anchors(pins.get("anchors"))
    lags = _parse_lags(pins.get("source_lags_ns"))
    if pins.get("obs_source") != obsmod.OBS_SOURCE_LABEL:
        raise BuildRefusal(
            f"pins.obs_source must be {obsmod.OBS_SOURCE_LABEL!r}, was {pins.get('obs_source')!r}"
        )
    cadence = pins.get("obs_cadence_seconds")
    if isinstance(cadence, bool) or cadence != obsmod.LIVE_OBS_CADENCE_SECONDS:
        raise BuildRefusal(
            f"pins.obs_cadence_seconds must be the live cadence {obsmod.LIVE_OBS_CADENCE_SECONDS}, "
            f"was {cadence!r} (L-13)"
        )
    return Pins(anchors, pins["anchors"], lags)


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
    inputs = (cfg.nbp_root, cfg.us_root, cfg.mos_root, cfg.asos_root, cfg.truth, cfg.prereg)
    for path in (cfg.out_features, cfg.out_lag, cfg.report):
        if _inside(path, LIVE_DATA_ROOT):
            raise BuildRefusal(f"refusing to write into the live data root: {path}")
        if any(_inside(path, root) for root in inputs):
            raise BuildRefusal(f"refusing to write inside an input root: {path}")
    for path in (cfg.out_features, cfg.out_lag):
        for target in (path, Path(str(path) + SIDECAR_SUFFIX)):
            if target.exists():
                raise BuildRefusal(f"{target} already exists; outputs are write-once")


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    if not path.is_file():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ the build


@dataclass(slots=True)
class _Tally:
    counts: Counter[str]
    by_horizon: dict[str, Counter[str]]
    obs_raw_differs: int = 0


def _day_range(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _shifted(readings: Sequence[ObsReading], shift_ns: int) -> list[ObsReading]:
    return [ObsReading(r.ts_ns, r.available_at_ns + shift_ns, r.temp_f, r.source) for r in readings]


@dataclass(frozen=True, slots=True)
class _Station:
    icao: str
    key: str
    offset: float


def _build_station(
    cfg: Config,
    pins: Pins,
    station: _Station,
    ctx: _Context,
    primary: list[msb.FeatureRow],
    lag: list[msb.FeatureRow],
) -> dict[dt.date, str | None]:
    tally = ctx.tally
    end_exclusive = cfg.end + _DAY
    pfm = collect_pfm_vintages(
        ctx.us_cache,
        icao=station.icao,
        lag_ns=pins.lags["pfm"],
        end_exclusive=end_exclusive,
        counts=tally.counts,
    )
    mos = collect_mos_vintages(
        ctx.mos_cache,
        icao=station.icao,
        std_utc_offset_hours=station.offset,
        first_day=cfg.start,
        last_day=cfg.end,
        lag_ns=pins.lags["mos-gfs"],
        model=MOS_MODEL,
        counts=tally.counts,
    )
    days = []
    for day in _day_range(cfg.start, cfg.end):
        if (station.key, day) in ctx.truth:
            days.append(day)
        else:
            for horizon in HORIZONS:
                tally.by_horizon[horizon]["truth_missing"] += 1
    anchors = {
        (day, h): anchor_ns_for(h, day, station.offset, pins.anchors, variant=cfg.variant)
        for day in days
        for h in HORIZONS
    }
    bases: dict[dt.date, str | None] = {}
    for year in sorted({d.year for d in days}):
        year_days = [d for d in days if d.year == year]
        cutoffs = {d: max(anchors[(d, h)] for h in HORIZONS) for d in year_days}
        obs_year = obsmod.read_obs_year(
            ctx.asos_cache,
            station.icao,
            year,
            std_utc_offset_hours=station.offset,
            cadence_seconds=obsmod.LIVE_OBS_CADENCE_SECONDS,
            lag_ns=pins.lags["obs"],
            cutoff_ns_by_day=cutoffs,
        )
        tally.counts.update(obs_year.counts)
        for day in year_days:
            readings = obs_year.readings_by_day.get(day, ())
            for horizon in HORIZONS:
                anchor = anchors[(day, horizon)]
                choice = ctx.lamp.runs_for(station.icao, anchor_ns=anchor)
                bases[day] = bases.get(day) or choice.basis
                inputs = _RowInputs(
                    station, day, horizon, anchor, choice.runs, readings,
                    pfm.get(day, ()), mos.vintages_by_day.get(day, ()),
                )  # fmt: skip
                for shift, target in ((0, primary), (LAG_SHIFT_NS, lag)):
                    row = _assemble(ctx, inputs, shift)
                    if row is not None:
                        target.append(row)
                        _tally_row(tally, row, shift)
                        if shift == 0 and horizon == "D0":
                            raw = obsmod.raw_running_max_at(
                                obs_year.raw_max_by_day.get(day, ()), anchor
                            )
                            tally.obs_raw_differs += int(raw != row.obs_so_far_f)
    return bases


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


@dataclass(slots=True)
class _Context:
    tally: _Tally
    truth: Mapping[tuple[str, dt.date], Any]
    nbp: Mapping[tuple[str, dt.date], list[NbpCandidate]]
    lamp: LampArchive
    us_cache: ArchiveCache
    mos_cache: ArchiveCache
    asos_cache: ArchiveCache


def _truth_lookup(cfg: Config) -> dict[tuple[str, dt.date], Any]:
    rows = nss.read_settlement_truth_rows(cfg.truth, climate_day_before=HOLDOUT_START)
    return {
        (r.station, r.climate_day): r
        for r in final_rows_for_gate(rows)
        if r.climate_day < HOLDOUT_START and r.tmax_f is not None
    }


def _truth_concordance(f2: Path | None, truth: Mapping[tuple[str, dt.date], Any]) -> dict[str, Any]:
    """FB-R6: the F2 truth is a concordance diagnostic only; the champion's truth is the label."""
    if f2 is None:
        return {"status": "not_requested"}
    overlap, bad = 0, []
    with f2.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = dt.date.fromisoformat(row["climate_day"])
            ours = truth.get((row["city"], day))
            if day >= HOLDOUT_START or ours is None or not row["tmax_f"].strip():
                continue
            overlap += 1
            if int(float(row["tmax_f"])) != int(ours.tmax_f):
                bad.append(
                    {
                        "station": row["city"],
                        "climate_day": day.isoformat(),
                        "champion": int(ours.tmax_f),
                        "f2": int(float(row["tmax_f"])),
                    }
                )
    return {"n_overlap": overlap, "n_disagree": len(bad), "disagreements": bad[:50]}


def _nbp_version_breaks(rows: Sequence[msb.FeatureRow]) -> list[str]:
    last: dict[str, str] = {}
    breaks: set[str] = set()
    for row in sorted(rows, key=lambda r: (r.station, r.climate_day)):
        if row.station in last and last[row.station] != row.version:
            breaks.add(row.climate_day.isoformat())
        last[row.station] = row.version
    return sorted(breaks)


def _check_unique(rows: Sequence[msb.FeatureRow], name: str) -> None:
    keys = [(r.station, r.climate_day, r.horizon) for r in rows]
    if len(keys) != len(set(keys)):
        raise BuildRefusal(f"{name}: more than one row for a (station, climate_day, horizon) key")


def _lag_report(primary: Sequence[msb.FeatureRow], lag: Sequence[msb.FeatureRow]) -> dict[str, Any]:
    base = {(r.station, r.climate_day, r.horizon) for r in primary}
    shifted = {(r.station, r.climate_day, r.horizon) for r in lag}
    lost: dict[str, int] = {}
    for _station, _day, horizon in sorted(base - shifted):
        lost[horizon] = lost.get(horizon, 0) + 1
    return {
        "rows_lost_by_horizon": lost,
        "source_rows_lost": msb.lag_rows_lost(primary, lag),
        "obs_available_at_ns_shifted": True,
        "shift_ns": LAG_SHIFT_NS,
        "nbp_shifted": True,
        "label_shifted": False,
    }


def _source_lags(pins: Pins) -> dict[str, Any]:
    lags: dict[str, Any] = {
        key: {"ns": ns, "basis": _LAG_BASIS[key], "provisional": True}
        for key, ns in pins.lags.items()
    }
    lags["nbp"] = {
        "ns": None,
        "basis": "nominal: store max(LastModified, cycle + floor), not a measured vintage",
        "provisional": True,
    }
    return lags


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
        "obs_cadence_seconds": obsmod.LIVE_OBS_CADENCE_SECONDS,
        "source_breaks_observed": breaks,
        "lag_shift_ns": LAG_SHIFT_NS if role == "lag" else 0,
        "obs_available_at_ns_shifted": role == "lag",
    }
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _lines(rows: Sequence[msb.FeatureRow]) -> bytes:
    ordered = sorted(rows, key=lambda r: (r.station, r.climate_day, r.horizon))
    body = "\n".join(json.dumps(msb.feature_row_to_json(r), sort_keys=True) for r in ordered)
    return (body + "\n").encode("utf-8") if ordered else b""


def _obs_report(tally: _Tally) -> dict[str, Any]:
    return {
        "source": obsmod.OBS_SOURCE_LABEL,
        "live_path": obsmod.LIVE_PATH_CITATION,
        "cadence_seconds": obsmod.LIVE_OBS_CADENCE_SECONDS,
        "quantisation": "whole degF -> tenths C -> breezy.domain.temperature.round_half_up_f",
        "interval_rows_not_emulated": True,
        "interval_rows_note": (
            "the NWS integer-C interval rows (precision 10 tenths) cannot be derived from a "
            "whole-degF archive; only the METAR-exact rows are emulated"
        ),
        "raw_1min_running_max_is_descriptive_only": True,
        "d0_rows_where_raw_1min_max_differs": tally.obs_raw_differs,
        "qc_revision_risk": (
            "the 1-min archive is post-QC and may differ from what the live path saw; not "
            "measurable offline"
        ),
    }


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
    report["source_lags"] = _source_lags(pins)
    registry = nss.station_registry(stations=cfg.stations)
    unknown = [s for s in cfg.stations if s not in registry.std_utc_offset_hours_by_icao]
    if unknown:
        raise BuildRefusal(f"stations {unknown} are not in the registry")
    counts: Counter[str] = Counter()
    tally = _Tally(counts, {h: Counter() for h in HORIZONS})
    truth = _truth_lookup(cfg)
    ctx = _Context(
        tally=tally,
        truth=truth,
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
    primary: list[msb.FeatureRow] = []
    lag: list[msb.FeatureRow] = []
    lamp_bases: dict[str, dict[dt.date, str | None]] = {}
    for icao in cfg.stations:
        key = registry.settlement_station_by_icao[icao]
        station = _Station(icao, key, registry.std_utc_offset_hours_by_icao[icao])
        lamp_bases[icao] = _build_station(cfg, pins, station, ctx, primary, lag)
    _check_unique(primary, "primary")
    _check_unique(lag, "lag")
    for rows in (primary, lag):
        msb.assert_pre_holdout(rows)
        for row in rows:
            msb.assert_row_leakage_free(row)
    breaks = {
        "lamp": sorted(
            {d.isoformat() for bases in lamp_bases.values() for d in basis_breaks(bases)}
        ),
        "nbp_versions": _nbp_version_breaks(primary),
    }
    report.update(
        counts=dict(counts),
        by_horizon={h: dict(c) for h, c in tally.by_horizon.items()},
        lag_file=_lag_report(primary, lag),
        obs=_obs_report(tally),
        source_breaks_observed=breaks,
        truth_concordance=_truth_concordance(cfg.f2_truth, truth),
        nbp_availability_basis="nominal: store max(LastModified, cycle + floor), flagged",
        pfm_iem_entered_time="unavailable_in_archive",
        mos_model=MOS_MODEL,
    )
    for role, rows, path in (("primary", primary, cfg.out_features), ("lag", lag, cfg.out_lag)):
        data = _lines(rows)
        _write_new(path, data)
        _write_new(
            Path(str(path) + SIDECAR_SUFFIX),
            _sidecar(role, data, digest, pins, cfg, len(rows), breaks),
        )
        report.setdefault("output_sha256", {})[role] = hashlib.sha256(data).hexdigest()
        report.setdefault("n_rows", {})[role] = len(rows)
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
    parser.add_argument("--anchor-variant", choices=VARIANTS, default="primary")
    parser.add_argument("--f2-truth", type=Path, default=None)
    parser.add_argument("--max-memory-gib", type=float, default=DEFAULT_MAX_MEMORY_GIB)
    return parser.parse_args(sys.argv[1:] if argv is None else list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = Config(
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
    apply_address_space_cap(args.max_memory_gib)
    if _inside(cfg.report, LIVE_DATA_ROOT) or cfg.report.exists():
        print(f"REFUSED: refusing to write the report at {cfg.report}", file=sys.stderr)
        return EXIT_REFUSED
    report: dict[str, Any] = {"status": "refused", "exit_code": EXIT_REFUSED, "reason": None}
    try:
        code = run_build(cfg, report)
    except _CAUGHT as exc:
        report.update(
            status="refused", exit_code=EXIT_REFUSED, reason=f"{type(exc).__name__}: {exc}"
        )
        print(f"REFUSED: {exc}", file=sys.stderr)
        code = EXIT_REFUSED
    else:
        report.update(status="complete" if code == EXIT_OK else "degraded", exit_code=code)
    body = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    _write_new(cfg.report, body.encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
