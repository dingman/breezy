"""AUT-4 WP2: slot-anchored validity and the offline successor gap (r11 §3.1 Z4, §3.9 K5).

The unit-file leg of `test_offline_successor_lands_before_predecessor_expiry` (parse
`TimeoutStartSec` from `breezy-autonomy-eval-offline.service`) lands with WP6, which writes the
unit. Until then the assertion runs on the `budget.py` literal that the unit must equal.
"""

from __future__ import annotations

import datetime as dt

from breezy.analysis.autonomy import budget, windows
from breezy.persistence.autonomy import pins

_ACCURACY_SEC = 1
_VALIDITY_SLACK_S = (pins.MAX_VERDICT_VALIDITY_H - 24) * 3600  # 7200 s: 26 h validity, 24 h cadence
_SUCCESSOR_MARGIN_S = 900


def test_validity_anchored_to_slot_never_exceeds_ceiling() -> None:
    for slot in ("11:00", "14:45"):
        start = windows.slot_start_ns(dt.date(2026, 10, 6), slot)
        assert windows.valid_until_ns(start) - start <= pins.MAX_VERDICT_VALIDITY_H * 3600 * 10**9


def test_worst_case_start_jitter_bounded() -> None:
    """A run ends by slot + AccuracySec + TimeoutStartSec, inside the 26 h validity."""
    for slot, timeout_s in (("11:00", budget.EVAL_OFFLINE_TIMEOUT_START_S), ("14:45", 1500)):
        start = windows.slot_start_ns(dt.date(2026, 10, 6), slot)
        worst_end = start + (_ACCURACY_SEC + timeout_s) * 10**9
        assert worst_end < windows.valid_until_ns(start)


def test_offline_successor_lands_before_predecessor_expiry() -> None:
    assert (
        budget.EVAL_OFFLINE_TIMEOUT_START_S + _ACCURACY_SEC
        <= _VALIDITY_SLACK_S - _SUCCESSOR_MARGIN_S
    )
    assert (
        budget.EVAL_OFFLINE_TIMEOUT_START_S + _ACCURACY_SEC == 6300
    )  # no slack: r4's 6300 failed by 1 s
