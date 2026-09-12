"""RED/GREEN coverage for `node_expected_alive` (SP-6 B1/AM-12, AM-14
form, row 11)."""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.runtime import trade_supervisor_core as core
from breezy.runtime.trade_supervisor_core import node_expected_alive

_DAY = dt.date(2026, 9, 12)


def _at(hour: int, minute: int, second: int = 0) -> dt.datetime:
    return dt.datetime(_DAY.year, _DAY.month, _DAY.day, hour, minute, second, tzinfo=dt.UTC)


def test_alive_expected_at_0200z() -> None:
    """The specific guard against rev2's 16h55m double-blind."""
    assert node_expected_alive(_at(2, 0)) is True


def test_alive_expected_one_minute_before_stop_prior() -> None:
    assert node_expected_alive(_at(16, 39)) is True


def test_not_alive_expected_at_stop_prior_itself() -> None:
    assert node_expected_alive(_at(16, 40)) is False


def test_not_alive_expected_during_the_relaunch_budget() -> None:
    """AM-14: 16:57Z is still inside the launch/relaunch retry budget."""
    assert node_expected_alive(_at(16, 57)) is False


def test_alive_expected_at_the_relaunch_cutoff() -> None:
    """AM-14: the exclusion end is exclusive -- 17:00:00Z is alive-expected."""
    assert node_expected_alive(_at(17, 0, 0)) is True


def test_the_window_is_derived_from_the_schedule_constants_not_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monkeypatches STOP_PRIOR_UTC/RELAUNCH_CUTOFF_UTC and asserts the
    boundary MOVES -- proving no literal is baked into the body."""
    monkeypatch.setattr(core, "STOP_PRIOR_UTC", dt.time(10, 0))
    monkeypatch.setattr(core, "RELAUNCH_CUTOFF_UTC", dt.time(11, 0))

    assert core.node_expected_alive(_at(10, 30)) is False
    assert core.node_expected_alive(_at(9, 59)) is True
    assert core.node_expected_alive(_at(11, 0, 0)) is True
