"""Leakage assertions for forward evaluation (AUT-4 r11 §3.1, §3.5). Pure; each raises on breach.

The first forward day is consumed by name from ``DEFAULT_SPLITS.holdout_end_exclusive``
(ARCH C4.1; ruling 2026-10-03 cl.1/cl.4) and never restated here.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS
from breezy.analysis.stats.scoring_core import LeakageError

#: Forward screening and shadow evaluation use climate days on or after this date (§3.5).
FIRST_FORWARD_DAY: Final[dt.date] = DEFAULT_SPLITS.holdout_end_exclusive


class LeakageViolation(LeakageError):
    """An input would let an evaluation see information it could not have had."""


def assert_forward_day(day: dt.date, train_end_exclusive: dt.date) -> None:
    """``day >= max(FIRST_FORWARD_DAY, train_end_exclusive)``: no training or pre-forward day."""
    floor = max(FIRST_FORWARD_DAY, train_end_exclusive)
    if day < floor:
        raise LeakageViolation(f"{day} precedes the first forward day {floor}")


def assert_outside_frozen_window(
    day: dt.date, frozen_start: dt.date, frozen_end_exclusive: dt.date
) -> None:
    """``day`` lies outside the sealed ``[frozen_start, frozen_end_exclusive)`` holdout."""
    if frozen_start <= day < frozen_end_exclusive:
        raise LeakageViolation(f"{day} lies inside the frozen window")


def assert_screening_day_before_nomination(day: dt.date, nomination_date: dt.date) -> None:
    """Screening days are never confirmation days: ``day < nomination_date``."""
    if day >= nomination_date:
        raise LeakageViolation(f"screening day {day} is not before nomination {nomination_date}")


def assert_confirmation_day_after_nomination(day: dt.date, nomination_date: dt.date) -> None:
    """Confirmation days are strictly after the nomination date."""
    if day <= nomination_date:
        raise LeakageViolation(f"confirmation day {day} is not after nomination {nomination_date}")


def assert_reference_before_decision(reference_ts_ns: int, decision_ts_ns: int) -> None:
    """A reference observation is strictly earlier than the decision it informs."""
    if reference_ts_ns >= decision_ts_ns:
        raise LeakageViolation(
            f"reference ts {reference_ts_ns} is not before decision ts {decision_ts_ns}"
        )
