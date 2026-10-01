"""S10 / D10: one side per (station, climate_day, rung).

Once either side Takes, the other side refuses ``opposite_side_latched``.
The refusal is durable across a ``PersistentQuantileLadderLatch`` restart
because the composite key is already ``rung_id:side``.

Check order pinned here (also commented in ``decision.evaluate``), earliest
wins, so a later rebase cannot silently reorder it:

1. D+1 gating → ``NotDPlus1`` (ahead of both latch checks)
2. permit → ``NotExecutable`` (ahead of both latch checks)
3. own-side latch → ``already_latched``
4. opposite-side latch → ``opposite_side_latched``
5. ``forecast_unavailable``
6. ``vector_day_mismatch``
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import cast

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.forecast_quantile_ladder.decision import (
    NotDPlus1,
    NotExecutable,
    Refuse,
    Take,
    decision_log_fields,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
    PersistentQuantileLadderLatch,
)
from tests.strategy.forecast_quantile_ladder.test_decision import (
    _DAY,
    _STATION,
    _no_ask,
    _ns,
    _run,
    _vector,
    _yes_ask,
)

_FAMILY_ID = "pm_us_crh_fq_test"
_RUNG = "i1"


def _yes_take(latch: QuantileLadderLatch) -> Take:
    decision = _run(side="yes", rung_id=_RUNG, ask=_yes_ask(0.10), latch=latch)
    assert isinstance(decision, Take)
    return decision


def test_a_yes_take_then_no_on_the_same_rung_refuses_opposite_side_latched() -> None:
    latch = QuantileLadderLatch()
    _yes_take(latch)

    refused = _run(side="no", rung_id=_RUNG, ask=_no_ask(0.05), latch=latch)

    assert isinstance(refused, Refuse)
    assert refused.reason == "opposite_side_latched"
    assert latch.is_latched(station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="yes") is True
    assert latch.is_latched(station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="no") is False


def test_a_no_take_then_yes_on_the_same_rung_refuses_opposite_side_latched() -> None:
    latch = QuantileLadderLatch()
    taken = _run(side="no", rung_id=_RUNG, ask=_no_ask(0.05), latch=latch)
    assert isinstance(taken, Take)

    refused = _run(side="yes", rung_id=_RUNG, ask=_yes_ask(0.10), latch=latch)

    assert isinstance(refused, Refuse)
    assert refused.reason == "opposite_side_latched"
    assert latch.is_latched(station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="no") is True
    assert latch.is_latched(station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="yes") is False


def test_a_different_rung_on_the_same_station_day_is_unaffected() -> None:
    latch = QuantileLadderLatch()
    _yes_take(latch)

    other_no = _run(
        side="no", rung_id="lt", ask=_no_ask(0.05), slippage_floor_prob=0.0, latch=latch,
    )
    other_yes = _run(side="yes", rung_id="i0", ask=_yes_ask(0.01), latch=latch)

    assert isinstance(other_no, Take)
    assert other_no.rung_id == "lt"
    assert isinstance(other_yes, Take)
    assert other_yes.rung_id == "i0"


def test_the_decision_log_round_trips_opposite_side_latched() -> None:
    latch = QuantileLadderLatch()
    _yes_take(latch)
    refused = _run(side="no", rung_id=_RUNG, ask=_no_ask(0.05), latch=latch)

    assert decision_log_fields(refused) == {"reason": "opposite_side_latched"}


def test_a_restarted_persistent_latch_refuses_the_opposite_side(tmp_path: Path) -> None:
    """A YES Take written through the durable latch, then a new
    ``PersistentQuantileLadderLatch`` on the same store (a restart), refuses
    NO on that rung with ``opposite_side_latched``."""
    store_path = tmp_path / "state.db"

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        first = PersistentQuantileLadderLatch(
            open_trial_day_latch(
                intent_latch,
                key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
                family_id=_FAMILY_ID,
            ),
        )
        taken = _run(
            side="yes",
            rung_id=_RUNG,
            ask=_yes_ask(0.10),
            latch=cast(QuantileLadderLatch, first),
        )
        assert isinstance(taken, Take)

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch_2:
        second = PersistentQuantileLadderLatch(
            open_trial_day_latch(
                intent_latch_2,
                key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
                family_id=_FAMILY_ID,
            ),
        )
        refused = _run(
            side="no",
            rung_id=_RUNG,
            ask=_no_ask(0.05),
            latch=cast(QuantileLadderLatch, second),
        )

        assert isinstance(refused, Refuse)
        assert refused.reason == "opposite_side_latched"
        assert second.is_latched(
            station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="yes",
        )
        assert not second.is_latched(
            station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="no",
        )


def test_evaluate_check_order_pins_opposite_side_between_own_side_and_later_refusals() -> None:
    """Earliest true condition wins. See the module docstring for the order.

    The forecast-missing and vector-mismatch cases are the ones a rebase
    would silently flip if ``opposite_side_latched`` slid below them.
    """
    latch = QuantileLadderLatch()
    _yes_take(latch)

    missing_forecast = _run(side="no", rung_id=_RUNG, ask=_no_ask(0.05), vector=None, latch=latch)
    assert isinstance(missing_forecast, Refuse)
    assert missing_forecast.reason == "opposite_side_latched"

    mismatched = _run(
        side="no",
        rung_id=_RUNG,
        ask=_no_ask(0.05),
        vector=_vector(climate_day=_DAY + dt.timedelta(days=1)),
        latch=latch,
    )
    assert isinstance(mismatched, Refuse)
    assert mismatched.reason == "opposite_side_latched"

    # Own-side wins when BOTH sides are latched, and it wins over a missing
    # forecast too. Swapping the two latch checks would report the opposite.
    both = QuantileLadderLatch()
    both.latch(station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="yes")
    both.latch(station=_STATION, climate_day=_DAY, rung_id=_RUNG, side="no")
    own = _run(side="yes", rung_id=_RUNG, ask=_yes_ask(0.10), vector=None, latch=both)
    assert isinstance(own, Refuse)
    assert own.reason == "already_latched"

    # D+1 and the permit stay ahead of both latch checks: same latched rung,
    # but the snapshot is not a trial, so the reason is not a latch reason.
    not_d_plus_1 = _run(
        side="no",
        rung_id=_RUNG,
        ask=_no_ask(0.05),
        now_ns=_ns(2026, 10, 1, 12, 0),
        vector=None,
        latch=latch,
    )
    assert isinstance(not_d_plus_1, NotDPlus1)

    outside_permit = _run(
        side="no",
        rung_id=_RUNG,
        ask=_no_ask(0.05),
        permit_covers=False,
        vector=None,
        latch=latch,
    )
    assert isinstance(outside_permit, NotExecutable)

    # The later reasons still fire when nothing is latched.
    unlatched_missing = _run(vector=None)
    assert isinstance(unlatched_missing, Refuse)
    assert unlatched_missing.reason == "forecast_unavailable"
    unlatched_mismatch = _run(vector=_vector(climate_day=_DAY + dt.timedelta(days=1)))
    assert isinstance(unlatched_mismatch, Refuse)
    assert unlatched_mismatch.reason == "vector_day_mismatch"


def test_opposite_side_latched_constant_is_exported() -> None:
    import breezy.strategy.forecast_quantile_ladder.decision as decision_mod

    assert decision_mod.OPPOSITE_SIDE_LATCHED == "opposite_side_latched"
    assert "OPPOSITE_SIDE_LATCHED" in decision_mod.__all__
