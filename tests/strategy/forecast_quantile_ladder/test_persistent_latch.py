"""``PersistentQuantileLadderLatch`` (SL-13) -- durable, flock-backed
``QuantileLadderLatch`` adapter. Mirrors
``tests/unit/test_current_rung_hold_trial_day_latch.py``'s
``open_trial_day_latch``-through-a-real-``SqliteStateStore`` style.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import date
from pathlib import Path

import pytest

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
    InvalidLatchKeyError,
    PersistentQuantileLadderLatch,
)

STATION = "LAX"
CLIMATE_DAY = date(2026, 10, 1)
RUNG_ID = "i1"
FAMILY_ID = "pm_us_crh_fq_test"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def latch(store_path: Path) -> Iterator[PersistentQuantileLadderLatch]:
    with ExitStack() as stack:
        intent_latch = stack.enter_context(
            open_submit_intent_latch(SqliteStateStore(store_path), store_path),
        )
        trial_latch = open_trial_day_latch(
            intent_latch, key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX, family_id=FAMILY_ID,
        )
        yield PersistentQuantileLadderLatch(trial_latch)


def test_a_fresh_latch_is_not_latched(latch: PersistentQuantileLadderLatch) -> None:
    assert not latch.is_latched(
        station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes",
    )


def test_latching_marks_exactly_that_key(latch: PersistentQuantileLadderLatch) -> None:
    latch.latch(station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes")

    assert latch.is_latched(station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes")
    assert not latch.is_latched(
        station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="no",
    )
    assert not latch.is_latched(
        station=STATION, climate_day=CLIMATE_DAY, rung_id="i2", side="yes",
    )
    assert not latch.is_latched(
        station="SFO", climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes",
    )


def test_latching_an_already_latched_key_is_an_idempotent_no_op(
    latch: PersistentQuantileLadderLatch,
) -> None:
    latch.latch(station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes")

    # Must not raise (unlike TrialDayLatch.consume, which raises
    # TrialDayAlreadyConsumed on a second call for the same key).
    latch.latch(station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes")

    assert latch.is_latched(station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes")


def test_the_persistent_latch_survives_a_simulated_restart(store_path: Path) -> None:
    """The whole point of SL-13's wiring: a fresh process (a fresh
    ``TrialDayLatch``, bound to the SAME on-disk store) still sees the rung
    as latched, and a repeat ``latch()`` call from that fresh process is
    still a no-op -- never a second trial, never a raise.
    """
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        first_trial_latch = open_trial_day_latch(
            intent_latch, key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX, family_id=FAMILY_ID,
        )
        first = PersistentQuantileLadderLatch(first_trial_latch)
        first.latch(station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes")
    # `intent_latch`'s flock is released here -- simulates process exit.

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch_2:
        second_trial_latch = open_trial_day_latch(
            intent_latch_2, key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX, family_id=FAMILY_ID,
        )
        second = PersistentQuantileLadderLatch(second_trial_latch)

        assert second.is_latched(
            station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes",
        )
        # Never re-takes the same rung after "restart".
        second.latch(station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes")
        assert second.is_latched(
            station=STATION, climate_day=CLIMATE_DAY, rung_id=RUNG_ID, side="yes",
        )
        # A DIFFERENT rung on the same restarted latch still works normally.
        assert not second.is_latched(
            station=STATION, climate_day=CLIMATE_DAY, rung_id="i2", side="yes",
        )


@pytest.mark.parametrize(
    ("rung_id", "side"),
    [("i1:x", "yes"), ("i1/x", "yes"), ("i1", "yes:no"), ("i1", "yes/no")],
)
def test_a_rung_id_or_side_containing_a_reserved_separator_is_refused(
    latch: PersistentQuantileLadderLatch, rung_id: str, side: str,
) -> None:
    with pytest.raises(InvalidLatchKeyError):
        latch.latch(station=STATION, climate_day=CLIMATE_DAY, rung_id=rung_id, side=side)  # type: ignore[arg-type]
