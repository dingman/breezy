"""Label-run memory sizing and the slot hold (AUT-2 r7 WP6, section 4 and sections 3.10/3.2.2).

``size_from_peak`` sizes the unit from the label run's OWN measured cgroup ``memory.peak``:
``MemoryMax = min(ceil_GiB(1.5 x peak), 14 GiB)`` and ``MemoryHigh = min(0.9 x MemoryMax, 12 GiB)``,
refusing (``SizingExceedsCap``) when the 14 GiB ceiling is exceeded or the capped ``MemoryHigh`` is
below ``1.35 x peak`` (V9).

``label_slot_held`` is the slot's gate. A unit whose effective ``MemoryMax`` exceeds 4 GiB is an
autonomy study and never starts the scorer until AUT-6's ``aut6.memory_budget`` HEALTH verdict is a
valid PASS; a missing or unreadable verdict holds (fail closed). A sizing above the cap holds every
slot with its own named cause. The reading of AUT-6's verdict is injected; until AUT-6 lands, the
default reading is "missing", which holds above 4 GiB.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from breezy.analysis.labeling.constants import (
    LABEL_MEMORY_CEILING_GIB,
    LABEL_MEMORY_HEADROOM,
    LABEL_MEMORY_HIGH_CAP_GIB,
    LABEL_MEMORY_TARGET_GIB,
)
from breezy.analysis.labeling.skip_journal import utc_day, write_json_once
from breezy.persistence.autonomy.single_read import SingleReadRefused

__all__ = [
    "HOLD_DIR",
    "Aut6Reading",
    "Hold",
    "HoldJournalWriteFailed",
    "MemorySizing",
    "SizingExceedsCap",
    "label_slot_held",
    "missing_aut6_reading",
    "record_hold",
    "size_from_peak",
]

HOLD_DIR: Final[tuple[str, ...]] = ("evidence", "aut2", "holds")
HOLD_SCHEMA: Final = "aut2_hold/v1"
HOLD_UNIT: Final = "breezy-label-outcomes"
_GIB: Final = 1024**3
_HIGH_FRACTION_NUM: Final = 9  # MemoryHigh = 9/10 of MemoryMax
_HIGH_FRACTION_DEN: Final = 10
_HEADROOM_NUM: Final = (
    3  # LABEL_MEMORY_HEADROOM = 1.5 = 3/2, in integers so a boundary never rounds up
)
_HEADROOM_DEN: Final = 2


class HoldJournalWriteFailed(Exception):
    """The hold journal file could not be created; the skip path exits 1 (L1)."""


@dataclass(frozen=True)
class MemorySizing:
    memory_max_bytes: int
    memory_high_bytes: int


@dataclass(frozen=True)
class SizingExceedsCap:
    """The measured peak cannot be sized inside ARCH 5.2's studies cap."""

    peak_bytes: int


@dataclass(frozen=True)
class Aut6Reading:
    """The newest ``aut6.memory_budget`` HEALTH verdict as the gate sees it."""

    status: Literal["pass", "not_pass", "missing", "corrupt"]
    verdict_id: str | None = None


@dataclass(frozen=True)
class Hold:
    cause: Literal["memory_gate", "memory_sizing_exceeds_cap"]
    reason: Literal["verdict_not_pass", "verdict_missing", "verdict_corrupt", "sizing"]
    memory_max_bytes: int
    measured_peak_bytes: int | None
    aut6_memory_verdict_id: str | None


def missing_aut6_reading() -> Aut6Reading:
    """The default reading until AUT-6 exists: no verdict, which holds above 4 GiB."""
    return Aut6Reading("missing")


def size_from_peak(peak_bytes: int) -> MemorySizing | SizingExceedsCap:
    if isinstance(peak_bytes, bool) or not isinstance(peak_bytes, int) or peak_bytes <= 0:
        raise ValueError("the measured peak must be a positive int of bytes")
    assert (
        LABEL_MEMORY_HEADROOM * _HEADROOM_DEN == _HEADROOM_NUM
    )  # the integer form is the constant
    wanted = peak_bytes * _HEADROOM_NUM
    max_gib = -(-wanted // (_HEADROOM_DEN * _GIB))  # ceil, in integers
    if max_gib > LABEL_MEMORY_CEILING_GIB:
        return SizingExceedsCap(peak_bytes)
    memory_max = max_gib * _GIB
    high_cap = LABEL_MEMORY_HIGH_CAP_GIB * _GIB
    # MemoryHigh = min(0.9 x MemoryMax, cap) must be >= 1.35 x peak (27/20); compared in integers so
    # a boundary peak is neither refused nor accepted by float rounding
    if min(memory_max * 18, high_cap * 20) < 27 * peak_bytes:
        return SizingExceedsCap(peak_bytes)
    memory_high = min(memory_max * _HIGH_FRACTION_NUM // _HIGH_FRACTION_DEN, high_cap)
    return MemorySizing(memory_max, memory_high)


def label_slot_held(
    *, unit_max_bytes: int, aut6: Aut6Reading, measured_peak_bytes: int | None = None
) -> Hold | None:
    """The hold for this slot, or ``None`` when the scorer may start."""
    if measured_peak_bytes is not None and isinstance(
        size_from_peak(measured_peak_bytes), SizingExceedsCap
    ):
        return Hold(
            "memory_sizing_exceeds_cap",
            "sizing",
            unit_max_bytes,
            measured_peak_bytes,
            aut6.verdict_id,
        )
    if unit_max_bytes <= LABEL_MEMORY_TARGET_GIB * _GIB:
        return None
    reasons = {
        "pass": None,
        "not_pass": "verdict_not_pass",
        "missing": "verdict_missing",
        "corrupt": "verdict_corrupt",
    }
    reason = reasons[aut6.status]
    if reason is None:
        return None
    return Hold(
        "memory_gate",
        reason,  # type: ignore[arg-type]
        unit_max_bytes,
        measured_peak_bytes,
        aut6.verdict_id,
    )


def record_hold(data_root: Path, hold: Hold, *, now_ns: int, slot_ns: int) -> Path:
    """Write ``evidence/aut2/holds/<day>/<now_ns>_label-outcomes.json`` once (0600)."""
    body = {
        "schema": HOLD_SCHEMA,
        "unit": HOLD_UNIT,
        "slot_ns": slot_ns,
        "cause": hold.cause,
        "reason": hold.reason,
        "memory_max_bytes": hold.memory_max_bytes,
        "measured_peak_bytes": hold.measured_peak_bytes,
        "aut6_memory_verdict_id": hold.aut6_memory_verdict_id,
    }
    try:
        return write_json_once(
            data_root, (*HOLD_DIR, utc_day(now_ns), f"{now_ns}_label-outcomes.json"), body
        )
    except (OSError, SingleReadRefused) as exc:
        raise HoldJournalWriteFailed("the hold journal file could not be written") from exc
