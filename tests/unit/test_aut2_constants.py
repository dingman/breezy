"""AUT-2 r7 WP2: the pinned labelling constants and the budget identities the plan states."""

from __future__ import annotations

from breezy.analysis.labeling import constants as c
from breezy.persistence.autonomy import label_store, pins
from breezy.runtime import venue_positions_read


def test_label_horizons_and_markers_are_pinned() -> None:
    assert (c.LABEL_LAG_MAX_H, c.WINDOW_INCOMPLETE_MAX_H, c.LABEL_MARKER_STALE_H) == (24, 48, 26)
    assert c.LABEL_LAG_MAX_H <= pins.MAX_VERDICT_VALIDITY_H
    assert c.LABEL_MARKER_STALE_H == label_store.MARKER_STALE_H
    assert c.POSITION_SETTLE_GRACE_S == 60
    assert (c.BRIDGE_TAKE_TO_INIT_MAX_S, c.BRIDGE_INIT_TO_FILL_MAX_S) == (2, 300)


def test_unit_budget_identities_hold() -> None:
    # P8 / V6: flock wait + read deadline + post-read budget == TimeoutStartSec, per mode
    assert (
        c.RECON_INTRADAY_FLOCK_WAIT_S + c.INTRADAY_READ_DEADLINE_S + c.INTRADAY_POST_READ_BUDGET_S
        == c.RECON_INTRADAY_TIMEOUT_START_S
        == 234
    )
    assert (
        c.POST_STOP_FLOCK_WAIT_S + c.POST_STOP_READ_DEADLINE_S + c.POST_STOP_POST_READ_BUDGET_S
        == c.POST_STOP_TIMEOUT_START_S
        == 94
    )
    # V8: the post-STOP budget is the write reserve plus three bounded deliveries
    assert (
        c.POST_STOP_POST_READ_BUDGET_S
        == c.POST_READ_WRITE_RESERVE_S + 3 * c.AUT2_DELIVERY_DEADLINE_S
    )
    assert c.POST_STOP_FLOCK_WAIT_S + c.POST_STOP_TIMEOUT_START_S + c.TIMEOUT_STOP_S <= (
        pins.POST_STOP_RECONCILE_RUNTIME_S
    )
    assert c.VENUE_READ_REQUEST_TIMEOUT_S == venue_positions_read.VENUE_READ_REQUEST_TIMEOUT_S


def test_cadence_slots_and_memory_constants() -> None:
    assert c.INTRADAY_PERIOD_MIN == 30 and c.SNAPSHOT_MAX_AGE_MIN == 45
    assert c.RECON_INTRADAY_VALIDITY_H == 8 and c.RECON_DAILY_VALIDITY_H == 26
    assert c.LABEL_TIMEOUT_START_S == 1800 and c.LABEL_FLOCK_WAIT_S == 600
    assert (c.LABEL_MEMORY_TARGET_GIB, c.LABEL_MEMORY_CEILING_GIB) == (4, 14)
    assert (c.LABEL_MEMORY_HIGH_CAP_GIB, c.LABEL_MEMORY_HIGH_MIN_RATIO) == (12, 1.35)
    assert c.SLOT_GUARD_REFUSED_RC == 10
    assert (
        c.POST_STOP_INCONCLUSIVE_CRITICAL_CONSECUTIVE_DAYS,
        c.LOCK_SKIP_CRITICAL_CONSECUTIVE,
    ) == (2, 2)
    assert (c.INTRADAY_INCONCLUSIVE_CRITICAL_CONSECUTIVE, c.INCONCLUSIVE_ALERT_DAYS) == (4, 2)
