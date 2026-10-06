"""Run-time budget literals of the eval-offline unit (AUT-4 r11 §3.12, §3.9).

Every number here is derived from, or equal to, a value the plan states. Nothing is a tunable.
``REPLAY_PARALLELISM`` (P) is measured by WP0 and is deliberately not defined here: the derived
child timeout takes it as an argument.
"""

from __future__ import annotations

from typing import Final

from breezy.persistence.autonomy.pins import MAX_NOMINATIONS_PER_FORWARD_WINDOW

#: ``TimeoutStartSec`` of ``breezy-autonomy-eval-offline`` (includes the flock wait).
EVAL_OFFLINE_TIMEOUT_START_S: Final[int] = 6299
SCREEN_BUDGET_S: Final[int] = 900
SCORING_RESERVE_S: Final[int] = 600
SAFETY_S: Final[int] = 300
FLOCK_WAIT_S: Final[int] = 900
MAX_BACKLOG_DAYS_PER_RUN: Final[int] = 3
#: Stations a replay day covers (the committed root manifest's count today).
REPLAY_STATIONS: Final[int] = 4

#: 6299 - 900 (flock) - 900 (screen) - 600 (scoring) - 300 (safety) = 3599 s at the worst wait.
REPLAY_WALL_BUDGET_S: Final[int] = (
    EVAL_OFFLINE_TIMEOUT_START_S - FLOCK_WAIT_S - SCREEN_BUDGET_S - SCORING_RESERVE_S - SAFETY_S
)


def fs_replay_child_timeout_s(parallelism: int) -> int:
    """``floor(P * REPLAY_WALL_BUDGET_S / (4 * (MAX_NOMINATIONS_PER_FORWARD_WINDOW + 1)))``.

    The denominator counts the stations times the open-window nominee plus the champion's
    ``eval_replay_path`` replay. 899 s at P = 2, 449 s at P = 1.
    """
    if parallelism < 1:
        raise ValueError(f"parallelism must be at least 1, was {parallelism!r}")
    return (parallelism * REPLAY_WALL_BUDGET_S) // (
        REPLAY_STATIONS * (MAX_NOMINATIONS_PER_FORWARD_WINDOW + 1)
    )
