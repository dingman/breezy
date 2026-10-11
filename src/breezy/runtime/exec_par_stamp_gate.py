"""EXEC-PAR BG-6: the stage-eval stamp gate (D-PREREG r4 1a "Boot-pass gate", r3.2 E7), pure.

At configured K>1 ``SubmitIntentLatch._breaker_denial`` denies ENTRIES (never exits, never the
resolver) until a stamp written by THIS boot exists:

* ``stamp.boot_ns == latch.boot_ns`` and ``stamp.ts_ns >= latch.boot_ns``; a stamp from a previous
  boot never counts. Until then the reason is ``stage_eval_boot_pending`` (an entry denial, not a
  halt).
* A matching stamp older than 26 h is ``stage_eval_stamp_stale`` (integrity). So is a stamp more
  than 5 s in the future (a clock fault, like the heartbeat's). "Never written after the first K>1
  climate day" is read as: no matching stamp 26 h after this boot (a climate day plus the 2 h
  slack the 26 h bound allows).
* A stamp row that cannot be read is ``stage_eval_stamp_unreadable`` (fail closed).

Imports nothing but the stamp record type, so the latch can use it without a cycle.
"""

from __future__ import annotations

from typing import Final

from breezy.runtime.exec_par_records import StageEvalStamp

__all__ = [
    "REASON_BOOT_PENDING",
    "REASON_STAMP_STALE",
    "REASON_STAMP_UNREADABLE",
    "STAMP_FUTURE_SKEW_NS",
    "STAMP_MAX_AGE_NS",
    "stamp_denial",
]

_NS: Final[int] = 1_000_000_000

#: r4 1a: "Stale means older than 26 h".
STAMP_MAX_AGE_NS: Final[int] = 26 * 3600 * _NS
#: The same clock-fault skew the heartbeat uses (``BREAKER_FUTURE_SKEW_NS``), restated so this
#: module stays dependency-free.
STAMP_FUTURE_SKEW_NS: Final[int] = 5 * _NS

REASON_BOOT_PENDING: Final[str] = "stage_eval_boot_pending"
REASON_STAMP_STALE: Final[str] = "stage_eval_stamp_stale"
REASON_STAMP_UNREADABLE: Final[str] = "stage_eval_stamp_unreadable"


def stamp_denial(stamp: StageEvalStamp | None, *, boot_ns: int, now_ns: int) -> str | None:
    """The entry-denial reason for this stamp, or ``None`` when the gate is clear."""
    if stamp is None or stamp.boot_ns != boot_ns or stamp.ts_ns < boot_ns:
        if now_ns - boot_ns > STAMP_MAX_AGE_NS:
            return REASON_STAMP_STALE
        return REASON_BOOT_PENDING
    if not -STAMP_FUTURE_SKEW_NS <= now_ns - stamp.ts_ns <= STAMP_MAX_AGE_NS:
        return REASON_STAMP_STALE
    return None
