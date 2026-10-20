"""MAKER S2 WP0 -- the Stage-0 probe report (pure data; no I/O).

``ProbeReport`` and ``CLOCKS`` moved out of ``maker_stage0_probe`` so the I/O module stays
under the line ceiling. ``maker_stage0_probe`` re-exports both. This module does not import
``breezy.runtime`` or ``breezy.persistence``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from scripts.analysis.maker_stage0_clock_offset import InstanceDayDelta
from scripts.analysis.maker_stage0_probe_core import (
    CensusCounts,
    DirectionResult,
    StationDayCoverage,
    enforce_direction,
    flat_fields,
    reassert_census,
)

CLOCKS: Final[Mapping[str, str]] = {
    "depth_ts_event": "venue transactTime (parsing.py:777-779)",
    "print_ts_event": "venue tradeTime (parsing.py:971)",
    "gap_started_ns_ended_ns": "recorder node clock (data.py _clock.timestamp_ns), compared "
    "with venue-clock frame ts_event; edge skew is bounded by delta_ns",
    "listing_ns": "BinaryOption.ts_init, recorder receipt (same field as S1 first_seen_ns)",
    "forecast_available_at_ns": "UTC-anchored",
}


@dataclass(frozen=True, slots=True)
class ProbeReport:
    """Everything WP0 measures; ``to_dict`` is the ``wp0_agreement.json`` sidecar."""

    days: tuple[str, ...]
    stations: tuple[str, ...]
    first_print_ns: int | None
    first_replayable_day: str | None
    direction: DirectionResult
    control: DirectionResult | None
    census: CensusCounts
    depth_frames: int
    truncated_frames: int
    coverage: tuple[StationDayCoverage, ...]
    delta_instance_days: tuple[InstanceDayDelta, ...]
    delta_distribution: Mapping[str, int | None]
    ladder_parity: Mapping[str, Mapping[str, object]]
    skipped: Mapping[str, str] = field(default_factory=dict)  # instance_id -> reason

    def require_clean(self) -> None:
        """Raise ``CensusViolation`` / ``StopS2``; the sidecar is written BEFORE this is called."""
        reassert_census(self.census)
        enforce_direction(self.direction)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable sidecar payload."""
        share = self.truncated_frames / self.depth_frames if self.depth_frames else None
        return {
            "days": list(self.days),
            "stations": list(self.stations),
            "first_print_ns": self.first_print_ns,
            "first_replayable_day": self.first_replayable_day,
            "direction": self.direction.to_dict(),
            "positive_control": None if self.control is None else self.control.to_dict(),
            "census": flat_fields(self.census),
            "depth_frames": self.depth_frames,
            "truncated_frames": self.truncated_frames,
            "truncated_frame_share": share,
            "coverage": [flat_fields(c) for c in self.coverage],
            "delta_instance_days": [flat_fields(d) for d in self.delta_instance_days],
            "delta_distribution": dict(self.delta_distribution),
            "ladder_parity": {k: dict(v) for k, v in self.ladder_parity.items()},
            "skipped_instances": dict(self.skipped),
            "clocks": dict(CLOCKS),
        }
