"""F13 Phase A feature build: the prereg pins the builder reads and the anchor arithmetic.

Split out of ``multisource_blend_features_build.py`` (behaviour-neutral). A null, mistyped or
unaccepted pin is a :class:`BuildRefusal`; the builder never guesses a pin.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from breezy.analysis.multisource_blend_features import HORIZONS
from scripts.analysis import multisource_blend_inputs_obs as obsmod
from scripts.analysis.multisource_blend_sidecar import PRIMARY_VARIANT, SENSITIVITY_VARIANT

__all__ = [
    "LAG_FLOORS_NS",
    "OFFSET_RULE",
    "Anchors",
    "BuildRefusal",
    "Pins",
    "anchor_ns_for",
    "load_pins",
    "parse_anchors",
]

_MIN_NS: Final[int] = 60 * 1_000_000_000
_DAY: Final[dt.timedelta] = dt.timedelta(days=1)
OFFSET_RULE: Final[str] = "fixed_standard_time_never_dst"
#: R29 conservative floors: a pinned lag below its floor is refused (FB-R4).
LAG_FLOORS_NS: Final[Mapping[str, int]] = {
    "lamp-mdl": 60 * _MIN_NS,
    "lav-iem": 90 * _MIN_NS,
    "pfm": 60 * _MIN_NS,
    "mos-gfs": 300 * _MIN_NS,
    "obs": 15 * _MIN_NS,
}


class BuildRefusal(Exception):
    """The build is refused; only the report is written."""


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
    variant: str = PRIMARY_VARIANT,
) -> int:
    """The anchor instant (ns): D-1 is a UTC hour the day before; D0 an LST hour (fixed offset)."""
    midnight = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
    if horizon == "D-1":
        moment = midnight - _DAY + dt.timedelta(hours=anchors.d_minus_1_utc_hour)
    elif horizon == "D0":
        hour = (
            anchors.d0_sensitivity_lst_hour
            if variant == SENSITIVITY_VARIANT
            else anchors.d0_lst_hour
        )
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


def _parse_routine_minutes(raw: Any) -> dict[str, int]:
    """FB-R13: ``{icao: minute of the hour}`` for every station's routine METAR report."""
    if not isinstance(raw, Mapping) or not raw:
        raise BuildRefusal(
            "pins.obs_routine_minute_by_station must be a non-empty object {icao: minute 0..59} "
            f"(FB-R13), was {raw!r}"
        )
    minutes: dict[str, int] = {}
    for icao, minute in raw.items():
        if (
            isinstance(minute, bool)
            or not isinstance(minute, int)
            or not 0 <= minute < obsmod.MINUTES_PER_HOUR
        ):
            raise BuildRefusal(
                f"pins.obs_routine_minute_by_station.{icao} must be an integer minute 0..59, "
                f"was {minute!r}"
            )
        minutes[str(icao)] = minute
    return minutes


@dataclass(frozen=True, slots=True)
class Pins:
    anchors: Anchors
    anchors_raw: Mapping[str, Any]
    lags: Mapping[str, int]
    obs_routine_minute_by_station: Mapping[str, int]


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
    if isinstance(cadence, bool) or cadence != obsmod.ROUTINE_OBS_CADENCE_SECONDS:
        raise BuildRefusal(
            f"pins.obs_cadence_seconds must be the routine-METAR cadence "
            f"{obsmod.ROUTINE_OBS_CADENCE_SECONDS}, was {cadence!r} (FB-R13)"
        )
    minutes = _parse_routine_minutes(pins.get("obs_routine_minute_by_station"))
    return Pins(anchors, pins["anchors"], lags, minutes)
