"""QuantileLadderLatch -- first-qualifying-snapshot latch per (station-day,
rung, side); plan §3.3. Pure in-memory; SL-12 is shadow-only (not wired to
the persistent ``TrialDayLatch``/exec submission path -- that is SL-13).
"""

from __future__ import annotations

import datetime as dt


def _day() -> dt.date:
    return dt.date(2026, 10, 1)


def test_a_fresh_latch_is_not_latched() -> None:
    from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch

    latch = QuantileLadderLatch()

    assert latch.is_latched(station="KMIA", climate_day=_day(), rung_id="i0", side="yes") is False


def test_latching_marks_exactly_that_key() -> None:
    from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch

    latch = QuantileLadderLatch()
    latch.latch(station="KMIA", climate_day=_day(), rung_id="i0", side="yes")

    assert latch.is_latched(station="KMIA", climate_day=_day(), rung_id="i0", side="yes") is True
    assert latch.is_latched(station="KMIA", climate_day=_day(), rung_id="i1", side="yes") is False
    assert latch.is_latched(station="KMIA", climate_day=_day(), rung_id="i0", side="no") is False
    assert latch.is_latched(station="KSFO", climate_day=_day(), rung_id="i0", side="yes") is False


def test_a_new_cycle_never_re_opens_an_already_latched_rung() -> None:
    """A later, distinct call to ``latch`` for the same key is idempotent."""
    from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch

    latch = QuantileLadderLatch()
    latch.latch(station="KMIA", climate_day=_day(), rung_id="i0", side="yes")
    latch.latch(station="KMIA", climate_day=_day(), rung_id="i0", side="yes")

    assert latch.is_latched(station="KMIA", climate_day=_day(), rung_id="i0", side="yes") is True
