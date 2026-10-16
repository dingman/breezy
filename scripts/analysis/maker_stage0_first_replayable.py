"""MAKER-S2 second look C3: the pure first-replayable-day check.

Block 1 keeps the equality between the day the first print implies and the frozen block's first
day. A v2 block never refuses on it: the first print can fall on a licensed 10-14 rung, so the
observed day may legitimately differ; the value stays recorded in ``wp0_agreement.json``.
"""

from __future__ import annotations

from typing import Any

__all__ = ["check_first_replayable"]


def check_first_replayable(probed: Any, frozen: Any) -> str | None:
    """The refusal message for a v1 mismatch, else ``None`` (always ``None`` for a v2 block)."""
    if getattr(frozen, "block", 1) != 1:
        return None
    if probed.first_replayable_day == frozen.first_replayable_day.isoformat():
        return None
    return (
        f"first print implies replayable day {probed.first_replayable_day}, the frozen "
        f"block says {frozen.first_replayable_day}"
    )
