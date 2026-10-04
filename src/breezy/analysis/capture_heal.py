"""AUT-1 WP5 stage 3a STUB: the recorder heal planner (design r3 D6; plan r12 section 3.10.3).

A pure planner: it turns the recorder's watchdog kills (journal ``UNIT_RESULT=watchdog`` entries)
and the restart evidence into the heal records the audit writes. Stage 3 stream S1 fills it in;
until then ``plan_heals`` raises ``NotImplementedError``. The two constants below are FROZEN by 3a:
S3 pins them against the unit budget (S3-R42, S3-R49) and S1 must not change them.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from breezy.analysis.capture_audit_input_types import RecorderJournalEntry

__all__ = ["HEAL_BUDGET_S", "HEAL_JOURNAL_DAYS", "plan_heals"]

#: The wall-clock budget of one heal duty (S3-R29). It is bounded below by the journal reads and
#: above by the audit work budget left after a full lock wait:
#: ``HEAL_JOURNAL_DAYS * JOURNAL_TIMEOUT_S + 30 <= HEAL_BUDGET_S``
#: ``<= AUDIT_EXEC_TIMEOUT_S - 60 - 600``.
HEAL_BUDGET_S: Final[int] = 180
#: How many UTC days of the recorder journal one heal run reads, one day at a time (S3-R3).
HEAL_JOURNAL_DAYS: Final[int] = 3


def plan_heals(kills: Sequence[RecorderJournalEntry], now_ns: int) -> tuple[Mapping[str, Any], ...]:
    """The heal records to write for ``kills`` at ``now_ns`` (stage 3 S1)."""
    raise NotImplementedError("stage 3 S1: the heal planner")
