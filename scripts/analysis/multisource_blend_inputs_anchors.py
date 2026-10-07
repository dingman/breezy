"""F13 Phase A: the anchor pin, its arithmetic and the runner's per-row anchor check (FB-R1).

Split out of ``multisource_blend_inputs_pins.py`` (behaviour-neutral for the builder) so the
runner can re-derive every row's anchor from the sidecar's declared pins without importing the
builder's input readers. A malformed pin is a :class:`BuildRefusal`; a row that contradicts the
declared anchors is a runner :class:`Refusal`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.analysis.multisource_blend_features import HORIZONS, FeatureRow
from scripts.analysis import nbp_skill_study as nss
from scripts.analysis.multisource_blend_refusal import Refusal
from scripts.analysis.multisource_blend_sidecar import PRIMARY_VARIANT, SENSITIVITY_VARIANT

__all__ = [
    "DEFAULT_STATIONS",
    "OFFSET_RULE",
    "Anchors",
    "BuildRefusal",
    "anchor_ns_for",
    "check_row_anchors",
    "parse_anchors",
]

_DAY: Final[dt.timedelta] = dt.timedelta(days=1)
OFFSET_RULE: Final[str] = "fixed_standard_time_never_dst"
#: The builder's default stations: the only ones a feature row can carry.
DEFAULT_STATIONS: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")


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


def check_row_anchors(rows: Sequence[FeatureRow], meta: Mapping[str, Any], path: Path) -> None:
    """Every row's ``anchor_ns`` equals the anchor the sidecar's variant and pins imply.

    The station offsets come from the same registry the builder uses; a row for a station outside
    it, an unparseable ``anchors`` pin or any mismatching anchor is a :class:`Refusal`.
    """
    try:
        anchors = parse_anchors(meta["anchors"])
    except BuildRefusal as exc:
        raise Refusal(f"{path}: the sidecar's anchors are unusable: {exc}") from exc
    registry = nss.station_registry(stations=DEFAULT_STATIONS)
    offsets = {
        registry.settlement_station_by_icao[icao]: hours
        for icao, hours in registry.std_utc_offset_hours_by_icao.items()
    }
    variant = meta["anchor_variant"]
    for row in rows:
        if row.station not in offsets:
            raise Refusal(f"{path}: row station {row.station!r} is not in the station registry")
        expected = anchor_ns_for(
            row.horizon, row.climate_day, offsets[row.station], anchors, variant=variant
        )
        if row.anchor_ns != expected:
            raise Refusal(
                f"{path}: anchor_ns {row.anchor_ns} of {row.station} {row.climate_day} "
                f"{row.horizon} contradicts the sidecar's anchors (variant {variant!r}: "
                f"{expected})"
            )
