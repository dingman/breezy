"""AUT-4 WP2: forward-window / slot arithmetic and leakage assertions (r11 §3.1 Z4, §3.5 W7)."""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.analysis.autonomy import leakage, windows
from breezy.persistence.autonomy import pins

_ANCHOR = dt.date(2026, 10, 2)


def test_tumbling_windows_partition_the_calendar() -> None:
    first = windows.forward_window(_ANCHOR, 28, _ANCHOR)
    assert (first.index, first.start, first.end) == (0, _ANCHOR, dt.date(2026, 10, 29))
    last_day = windows.forward_window(_ANCHOR, 28, dt.date(2026, 10, 29))
    next_day = windows.forward_window(_ANCHOR, 28, dt.date(2026, 10, 30))
    assert last_day == first
    assert (next_day.index, next_day.start) == (1, dt.date(2026, 10, 30))
    assert next_day.end == dt.date(2026, 11, 26)


def test_window_days_are_held_to_the_pins_range() -> None:
    for bad in (pins.FORWARD_WINDOW_DAYS_MIN - 1, pins.FORWARD_WINDOW_DAYS_MAX + 1):
        with pytest.raises(ValueError):
            windows.forward_window(_ANCHOR, bad, _ANCHOR)
    windows.forward_window(_ANCHOR, pins.FORWARD_WINDOW_DAYS_MAX, _ANCHOR)


def test_a_day_before_the_anchor_has_no_window() -> None:
    with pytest.raises(ValueError):
        windows.forward_window(_ANCHOR, 28, _ANCHOR - dt.timedelta(days=1))


def test_nominee_uses_only_days_after_nomination_up_to_window_end() -> None:
    nominated, end = dt.date(2026, 10, 10), dt.date(2026, 10, 29)
    assert not windows.nominee_may_use_day(nominated, nominated, end)  # not the nomination day
    assert windows.nominee_may_use_day(nominated + dt.timedelta(days=1), nominated, end)
    assert windows.nominee_may_use_day(end, nominated, end)
    assert not windows.nominee_may_use_day(end + dt.timedelta(days=1), nominated, end)


def test_slot_start_and_validity_are_anchored_to_the_slot() -> None:
    start = windows.slot_start_ns(dt.date(2026, 10, 6), "11:00")
    assert start == int(dt.datetime(2026, 10, 6, 11, 0, tzinfo=dt.UTC).timestamp()) * 10**9
    assert windows.valid_until_ns(start) == start + 26 * 3600 * 10**9  # ends at 13:00 next day
    assert windows.valid_until_ns(start) <= start + pins.MAX_VERDICT_VALIDITY_H * 3600 * 10**9


def test_validity_never_exceeds_the_ceiling() -> None:
    start = windows.slot_start_ns(dt.date(2026, 10, 6), "14:45")
    with pytest.raises(ValueError):
        windows.valid_until_ns(start, pins.MAX_VERDICT_VALIDITY_H + 1)
    with pytest.raises(ValueError):
        windows.valid_until_ns(start, 0)


def test_forward_day_floor_is_the_later_of_first_forward_day_and_train_end() -> None:
    leakage.assert_forward_day(dt.date(2026, 10, 2), dt.date(2026, 9, 1))
    leakage.assert_forward_day(dt.date(2026, 10, 20), dt.date(2026, 10, 20))
    with pytest.raises(leakage.LeakageViolation):
        leakage.assert_forward_day(dt.date(2026, 10, 1), dt.date(2026, 9, 1))
    with pytest.raises(leakage.LeakageViolation):
        leakage.assert_forward_day(dt.date(2026, 10, 19), dt.date(2026, 10, 20))


def test_frozen_window_is_half_open() -> None:
    start, end = dt.date(2026, 7, 1), dt.date(2026, 10, 2)
    leakage.assert_outside_frozen_window(dt.date(2026, 6, 30), start, end)
    leakage.assert_outside_frozen_window(end, start, end)
    for inside in (start, dt.date(2026, 10, 1)):
        with pytest.raises(leakage.LeakageViolation):
            leakage.assert_outside_frozen_window(inside, start, end)


def test_screening_and_confirmation_days_never_overlap() -> None:
    nominated = dt.date(2026, 10, 10)
    leakage.assert_screening_day_before_nomination(dt.date(2026, 10, 9), nominated)
    leakage.assert_confirmation_day_after_nomination(dt.date(2026, 10, 11), nominated)
    with pytest.raises(leakage.LeakageViolation):
        leakage.assert_screening_day_before_nomination(nominated, nominated)
    with pytest.raises(leakage.LeakageViolation):
        leakage.assert_confirmation_day_after_nomination(nominated, nominated)


def test_reference_must_be_strictly_before_the_decision() -> None:
    leakage.assert_reference_before_decision(1, 2)
    for ref, decision in ((2, 2), (3, 2)):
        with pytest.raises(leakage.LeakageViolation):
            leakage.assert_reference_before_decision(ref, decision)


@pytest.mark.parametrize("bad", ["", "11", "11:00:00", "ab:cd", "24:00", "11:60", "-1:00"])
def test_malformed_slot_string_raises_named_value_error(bad: str) -> None:
    with pytest.raises(ValueError, match="slot_utc"):
        windows.slot_start_ns(dt.date(2026, 10, 6), bad)


def test_leakage_violation_is_a_scoring_core_leakage_error() -> None:
    from breezy.analysis.stats.scoring_core import LeakageError

    assert issubclass(leakage.LeakageViolation, LeakageError)
    with pytest.raises(LeakageError):
        leakage.assert_reference_before_decision(2, 2)
