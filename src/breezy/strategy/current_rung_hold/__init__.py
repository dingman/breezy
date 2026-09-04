"""``current_rung_hold`` trading strategy (build in progress).

Public surface, incrementally: :class:`TrialDayLatch` and
:func:`open_trial_day_latch` -- see ``trial_day_latch.py`` for the ordering
rule this latch is bound by (trial commit precedes intent arm, which
precedes the POST, which precedes intent retire) -- and
:class:`CurrentRungHoldConfig`, see ``config.py`` for its construction-time
validations -- and :func:`evaluate_decision`, see ``decision.py`` for the
PURE (no Nautilus, no I/O, no clock) rule order it follows.
"""

from __future__ import annotations

from breezy.strategy.current_rung_hold.config import (
    AllowShortNotPermittedError,
    ArchiveTablePinMismatchError,
    CurrentRungHoldConfig,
    InvalidOrderQuantityError,
    OrdersEnabledNotPermittedError,
    UnsupportedStationError,
)
from breezy.strategy.current_rung_hold.decision import (
    REFUSAL_REASONS,
    Decision,
    DecisionInputs,
    Refuse,
    Take,
    evaluate_decision,
)
from breezy.strategy.current_rung_hold.strategy import (
    CurrentRungHoldStrategy,
    MissingTrialDayLatchError,
    season_for,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayAlreadyConsumed,
    TrialDayInvalidReason,
    TrialDayLatch,
    TrialDayLatchError,
    TrialDayRecord,
    TrialDayRecordCorrupt,
    open_trial_day_latch,
)

__all__ = [
    "REFUSAL_REASONS",
    "AllowShortNotPermittedError",
    "ArchiveTablePinMismatchError",
    "CurrentRungHoldConfig",
    "CurrentRungHoldStrategy",
    "Decision",
    "DecisionInputs",
    "InvalidOrderQuantityError",
    "MissingTrialDayLatchError",
    "OrdersEnabledNotPermittedError",
    "Refuse",
    "Take",
    "TrialDayAlreadyConsumed",
    "TrialDayInvalidReason",
    "TrialDayLatch",
    "TrialDayLatchError",
    "TrialDayRecord",
    "TrialDayRecordCorrupt",
    "UnsupportedStationError",
    "evaluate_decision",
    "open_trial_day_latch",
    "season_for",
]
