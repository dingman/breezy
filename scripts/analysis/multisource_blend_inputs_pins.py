"""F13 Phase A feature build: the prereg pins the builder reads.

Split out of ``multisource_blend_features_build.py`` (behaviour-neutral); the anchor arithmetic
lives in ``multisource_blend_inputs_anchors.py`` and is re-exported here. A null, mistyped or
unaccepted pin is a :class:`BuildRefusal`; the builder never guesses a pin.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from scripts.analysis import multisource_blend_inputs_obs as obsmod
from scripts.analysis.multisource_blend_inputs_anchors import (
    OFFSET_RULE,
    Anchors,
    BuildRefusal,
    anchor_ns_for,
    parse_anchors,
)
from scripts.analysis.multisource_blend_inputs_obs_coverage import (
    COVERAGE_PIN,
    check_coverage_pin,
    check_share_pin,
)

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
#: R29 conservative floors: a pinned lag below its floor is refused (FB-R4).
LAG_FLOORS_NS: Final[Mapping[str, int]] = {
    "lamp-mdl": 60 * _MIN_NS,
    "lav-iem": 90 * _MIN_NS,
    "pfm": 60 * _MIN_NS,
    "mos-gfs": 300 * _MIN_NS,
    "obs": 15 * _MIN_NS,
}


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
    #: ``obs_min_coverage_per_station_year``: a station-year below it is excluded (PIN-R4).
    obs_min_coverage_per_station_year: float
    #: ``obs_max_pin_minute_excluded_share``: a station-year above it is excluded (PIN-R4).
    obs_max_pin_minute_excluded_share: float


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
    try:
        coverage = check_coverage_pin(pins.get(COVERAGE_PIN))
    except (
        ValueError
    ) as exc:  # a null pin is refused too: the coordinator pins it, never the builder
        raise BuildRefusal(str(exc)) from exc
    try:
        share = check_share_pin(pins.get("obs_max_pin_minute_excluded_share"))
    except ValueError as exc:
        raise BuildRefusal(str(exc)) from exc
    return Pins(anchors, pins["anchors"], lags, minutes, coverage, share)
