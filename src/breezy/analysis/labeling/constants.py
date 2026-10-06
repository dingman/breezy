"""AUT-2 labelling constants (plan r7 section 3.2, ``constants.py``). Every value is pinned.

The budget identities (P8, V6, V8) are asserted by ``tests/unit/test_aut2_constants.py``; the unit
files that must equal them are asserted by the WP6 and WP9 deploy tests.
"""

import datetime as dt
from typing import Final

__all__ = [
    "AUT2_DELIVERY_DEADLINE_S",
    "BRIDGE_INIT_TO_FILL_MAX_S",
    "BRIDGE_TAKE_TO_INIT_MAX_S",
    "CATCHUP_DENY_UTC",
    "INCONCLUSIVE_ALERT_DAYS",
    "INTRADAY_INCONCLUSIVE_CRITICAL_CONSECUTIVE",
    "INTRADAY_PERIOD_MIN",
    "INTRADAY_POST_READ_BUDGET_S",
    "INTRADAY_READ_DEADLINE_S",
    "LABEL_FLOCK_WAIT_S",
    "LABEL_LAG_MAX_H",
    "LABEL_MARKER_STALE_H",
    "LABEL_MEMORY_CEILING_GIB",
    "LABEL_MEMORY_HEADROOM",
    "LABEL_MEMORY_HIGH_CAP_GIB",
    "LABEL_MEMORY_HIGH_MIN_RATIO",
    "LABEL_MEMORY_ROUND_GIB",
    "LABEL_MEMORY_TARGET_GIB",
    "LABEL_TIMEOUT_START_S",
    "LOCK_SKIP_CRITICAL_CONSECUTIVE",
    "MEASURE_MEMAVAILABLE_FLOOR_GIB",
    "POSITION_SETTLE_GRACE_S",
    "POST_READ_WRITE_RESERVE_S",
    "POST_STOP_FLOCK_WAIT_S",
    "POST_STOP_INCONCLUSIVE_CRITICAL_CONSECUTIVE_DAYS",
    "POST_STOP_POST_READ_BUDGET_S",
    "POST_STOP_READ_DEADLINE_S",
    "POST_STOP_TIMEOUT_START_S",
    "PROOF_MIN_REAL_FILLS",
    "PROOF_QUALIFYING_DAYS",
    "RECON_DAILY_VALIDITY_H",
    "RECON_INTRADAY_FLOCK_WAIT_S",
    "RECON_INTRADAY_TIMEOUT_START_S",
    "RECON_INTRADAY_VALIDITY_H",
    "SLOT_GUARD_REFUSED_RC",
    "SNAPSHOT_MAX_AGE_MIN",
    "SYSTEMD_DEFAULT_TIMEOUT_STOP_S",
    "TIMEOUT_STOP_S",
    "TIMER_ACCURACY_S",
    "VENUE_READ_REQUEST_TIMEOUT_S",
    "WINDOW_INCOMPLETE_MAX_H",
]

# label horizons and verdict validity (hours)
LABEL_LAG_MAX_H: Final = 24
WINDOW_INCOMPLETE_MAX_H: Final = 48
RECON_DAILY_VALIDITY_H: Final = 26
RECON_INTRADAY_VALIDITY_H: Final = 8
LABEL_MARKER_STALE_H: Final = 26  # V9; equals label_store.MARKER_STALE_H (test-pinned)

# live-proof window (section 6): qualifying days and real fills it needs
PROOF_QUALIFYING_DAYS: Final = 7
PROOF_MIN_REAL_FILLS: Final = 5

# cadence and snapshot freshness
INTRADAY_PERIOD_MIN: Final = 30
SNAPSHOT_MAX_AGE_MIN: Final = 45
INCONCLUSIVE_ALERT_DAYS: Final = 2

# the decision bridge (backfill only) and the position fence
BRIDGE_TAKE_TO_INIT_MAX_S: Final = 2
BRIDGE_INIT_TO_FILL_MAX_S: Final = 300
POSITION_SETTLE_GRACE_S: Final = 60

# unit timing (Q1, P7; r7 V6 re-split 239->234 and 99->94)
LABEL_FLOCK_WAIT_S: Final = 600
LABEL_TIMEOUT_START_S: Final = 1800
RECON_INTRADAY_FLOCK_WAIT_S: Final = 30
RECON_INTRADAY_TIMEOUT_START_S: Final = 234
POST_STOP_FLOCK_WAIT_S: Final = 20
POST_STOP_TIMEOUT_START_S: Final = 94
TIMEOUT_STOP_S: Final = 5
SYSTEMD_DEFAULT_TIMEOUT_STOP_S: Final = 90
TIMER_ACCURACY_S: Final = 1

# the venue read (P8; r7 V6: 60->55 and 50->45)
VENUE_READ_REQUEST_TIMEOUT_S: Final = 10
INTRADAY_READ_DEADLINE_S: Final = 55
POST_STOP_READ_DEADLINE_S: Final = 45
INTRADAY_POST_READ_BUDGET_S: Final = 149
POST_STOP_POST_READ_BUDGET_S: Final = 29

# delivery (V8)
AUT2_DELIVERY_DEADLINE_S: Final = 8
POST_READ_WRITE_RESERVE_S: Final = 5

# alert streaks and exits
POST_STOP_INCONCLUSIVE_CRITICAL_CONSECUTIVE_DAYS: Final = 2  # V4
SLOT_GUARD_REFUSED_RC: Final = 10  # V1; mapped to exit 1 by slot-guard-run.sh
LOCK_SKIP_CRITICAL_CONSECUTIVE: Final = 2  # P11
INTRADAY_INCONCLUSIVE_CRITICAL_CONSECUTIVE: Final = 4  # Q3

# label-run memory sizing (Q1, V9)
LABEL_MEMORY_HEADROOM: Final = 1.5
LABEL_MEMORY_ROUND_GIB: Final = 1
LABEL_MEMORY_TARGET_GIB: Final = 4
LABEL_MEMORY_CEILING_GIB: Final = 14  # AUT-6 #31 study cap
LABEL_MEMORY_HIGH_CAP_GIB: Final = 12  # ARCH 5.2 studies MemoryHigh
LABEL_MEMORY_HIGH_MIN_RATIO: Final = 1.35
MEASURE_MEMAVAILABLE_FLOOR_GIB: Final = 16  # V3

#: Start times the score-live-trials catch-up guard refuses (L2; r7 V6 adds the 90 s stop term):
#: the launch window and the heavy night, as ``(from, until)`` UTC pairs.
CATCHUP_DENY_UTC: Final = (
    (dt.time(16, 7, 30), dt.time(17, 10, 0)),
    (dt.time(1, 0, 0), dt.time(4, 30, 0)),
)
