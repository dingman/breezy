"""F13 Phase A feature build: the report sections (lag file, breaks, obs, truth concordance).

Split out of ``multisource_blend_features_build.py`` (behaviour-neutral). Pure functions over the
built rows and counts; nothing here reads a store.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from breezy.analysis import multisource_blend as msb
from breezy.analysis.multisource_blend_features import HOLDOUT_START, HORIZONS, LAG_SHIFT_NS
from scripts.analysis import multisource_blend_inputs_obs as obsmod
from scripts.analysis.multisource_blend_inputs_lamp import basis_breaks
from scripts.analysis.multisource_blend_inputs_pins import Pins

__all__ = [
    "LAG_BASIS",
    "lag_report",
    "lamp_breaks",
    "nbp_version_breaks",
    "obs_report",
    "source_lags",
    "truth_concordance",
]

LAG_BASIS: Final[Mapping[str, str]] = {
    "lamp-mdl": "nominal run time + max(60 min, C1 max)",
    "lav-iem": "nominal run label + max(60 min, C1 max) + 30 min (label HH:00, real run HH:30)",
    "pfm": "WMO issuance + 60 min (IEM entered time is not in the archive)",
    "mos-gfs": "runtime + 5 h",
    "obs": "report time + 15 min",
}


def truth_concordance(f2: Path | None, truth: Mapping[tuple[str, dt.date], Any]) -> dict[str, Any]:
    """FB-R6: the F2 truth is a concordance diagnostic only; the champion's truth is the label.

    A sealed row (>= the holdout start) is skipped on its date alone: no other column is read.
    """
    if f2 is None:
        return {"status": "not_requested"}
    overlap, bad = 0, []
    with f2.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = dt.date.fromisoformat(row["climate_day"])
            if day >= HOLDOUT_START:
                continue
            ours = truth.get((row["city"], day))
            if ours is None or not row["tmax_f"].strip():
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


def nbp_version_breaks(rows: Sequence[msb.FeatureRow]) -> list[str]:
    last: dict[str, str] = {}
    breaks: set[str] = set()
    for row in sorted(rows, key=lambda r: (r.station, r.climate_day)):
        if row.station in last and last[row.station] != row.version:
            breaks.add(row.climate_day.isoformat())
        last[row.station] = row.version
    return sorted(breaks)


def lamp_breaks(
    bases: Mapping[str, Mapping[str, Mapping[dt.date, str | None]]],
) -> dict[str, Any]:
    """MDL -> LAV breaks per horizon (a D0-only or D-1-only break is visible) and their union."""
    by_horizon = {
        horizon: sorted(
            {
                d.isoformat()
                for per_station in bases.values()
                for d in basis_breaks(per_station[horizon])
            }
        )
        for horizon in HORIZONS
    }
    return {
        "lamp": sorted({day for days in by_horizon.values() for day in days}),
        "lamp_by_horizon": by_horizon,
    }


def lag_report(primary: Sequence[msb.FeatureRow], lag: Sequence[msb.FeatureRow]) -> dict[str, Any]:
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


def source_lags(pins: Pins) -> dict[str, Any]:
    lags: dict[str, Any] = {
        key: {"ns": ns, "basis": LAG_BASIS[key], "provisional": True}
        for key, ns in pins.lags.items()
    }
    lags["nbp"] = {
        "ns": None,
        "basis": "nominal: store max(LastModified, cycle + floor), not a measured vintage",
        "provisional": True,
    }
    return lags


def obs_report(*, five_min_differs: int, raw_differs: int, pins: Pins) -> dict[str, Any]:
    return {
        "source": obsmod.OBS_SOURCE_LABEL,
        "live_path": obsmod.LIVE_PATH_CITATION,
        "cadence_seconds": obsmod.ROUTINE_OBS_CADENCE_SECONDS,
        "routine_metar_only": True,
        "obs_routine_minute_by_station": dict(pins.obs_routine_minute_by_station),
        "quantisation": "whole degF -> tenths C -> breezy.domain.temperature.round_half_up_f",
        "interval_rows_not_emulated": True,
        "interval_rows_note": (
            "FB-R13: the NWS integer-C interval rows and METAR specials are excluded on both "
            "sides; only the routine hourly METAR reading is used"
        ),
        "descriptive_arms_feed_no_feature": True,
        "d0_rows_where_five_min_max_differs": five_min_differs,
        "raw_1min_running_max_is_descriptive_only": True,
        "d0_rows_where_raw_1min_max_differs": raw_differs,
        "qc_revision_risk": (
            "the 1-min archive is post-QC and may differ from what the live path saw; not "
            "measurable offline"
        ),
    }
