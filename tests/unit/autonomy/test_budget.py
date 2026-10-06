"""AUT-4 WP2: the eval-offline budget literals (r11 §3.12, K5)."""

from __future__ import annotations

import pytest

from breezy.analysis.autonomy import budget
from breezy.persistence.autonomy import pins


def test_replay_wall_budget_is_3599() -> None:
    assert budget.REPLAY_WALL_BUDGET_S == 6299 - 900 - 900 - 600 - 300 == 3599


def test_child_timeout_derived_from_budget() -> None:
    denominator = 4 * (pins.MAX_NOMINATIONS_PER_FORWARD_WINDOW + 1)
    for parallelism in (1, 2):
        expected = (parallelism * 3599) // denominator
        assert budget.fs_replay_child_timeout_s(parallelism) == expected
    assert budget.fs_replay_child_timeout_s(2) == 899
    assert budget.fs_replay_child_timeout_s(1) == 449


def test_literals_are_the_plan_values() -> None:
    assert budget.EVAL_OFFLINE_TIMEOUT_START_S == 6299
    assert (budget.SCREEN_BUDGET_S, budget.SCORING_RESERVE_S) == (900, 600)
    assert (budget.SAFETY_S, budget.FLOCK_WAIT_S) == (300, 900)
    assert budget.MAX_BACKLOG_DAYS_PER_RUN == 3


def test_parallelism_below_one_is_refused() -> None:
    with pytest.raises(ValueError):
        budget.fs_replay_child_timeout_s(0)
