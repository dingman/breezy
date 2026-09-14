"""RED-first tests for S5 Track C, commit 1 (plan ``NO_SIDE_S5_EXEC_2026-09-14.md``
§5): real NO arming/consuming/submitting behind the still-True
``NO_SIDE_SHADOW_ONLY`` flag. Every test that exercises the real arm path
monkeypatches the flag ``False`` locally -- the flip itself is a separate,
later commit.

Client-side pieces named in the brief (the C1-prefix first-order-key write
and the synchronous pending refusal inside ``_submit_order``) are NOT
implemented here: both require calling ``self._store_set``/``self._store_get``/
``leg_of`` from inside ``_submit_order``, which is scanned by
``EXEC_ORDER_COROUTINE_PERMITTED_CALLEES``
(``tests/unit/test_execution_egress_firewall_guard.py``) and is not currently
on that allowlist. Per the brief's own instruction ("if it trips ... STOP and
report the exact pin instead of widening it"), that allowlist is left
untouched and those two client-side tests are not written.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
)
from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.strategy.current_rung_hold import continuous_strategy as cs
from tests.unit.test_continuous_rung_hold_fill_wiring import _fill
from tests.unit.test_continuous_rung_hold_no_side_shadow_2026_09_14 import _NO_ASK_CLEARS_BID
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _register,
    _register_and_start,
)
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)

_NO_INTERIOR_ID: InstrumentId = sibling_instrument_id(INTERIOR_ID)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


@pytest.fixture
def no_interior_instrument() -> BinaryOption:
    return _instrument(_NO_INTERIOR_ID, lower_f=86, upper_f=87)


def test_flag_true_keeps_shadow_behaviour_byte_identical(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
) -> None:
    """The default (still ``True``) flag never arms/consumes/submits the NO
    leg -- exactly the S3b behaviour, unedited by this commit."""
    assert cs.NO_SIDE_SHADOW_ONLY is True
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is not None


def test_a_no_take_arms_consumes_and_submits_on_the_no_instrument(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cs, "NO_SIDE_SHADOW_ONLY", False)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy._order_submission_permit = object()  # type: ignore[assignment]
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert len(submitted) == 1
    order = submitted[0]
    assert order.instrument_id == _NO_INTERIOR_ID
    assert order.side == OrderSide.BUY
    assert strategy._latch is not None
    assert strategy._latch.is_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID),
    )
    # A genuine fill then consumes the durable TRIAL on the NO instrument-day.
    strategy.on_order_filled(
        _fill(strategy, instrument_id=_NO_INTERIOR_ID, venue_order_id="ord-no-1"),
    )
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID),
    )
    assert record is not None
    assert record.reason == "taken"


def test_a_no_order_prices_itself_at_the_no_ask(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2-4: the submitted order's price is the NO decision's price
    (``1 - YES_bid``), never the YES ask."""
    monkeypatch.setattr(cs, "NO_SIDE_SHADOW_ONLY", False)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy._order_submission_permit = object()  # type: ignore[assignment]
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert len(submitted) == 1
    order = submitted[0]
    no_ask = Decimal(1) - Decimal(_NO_ASK_CLEARS_BID)
    assert order.price.as_decimal() == no_ask
    assert order.price.as_decimal() != Decimal("0.90")


def test_a_second_no_take_is_refused_while_the_first_order_is_pending(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2-1(i): once the durable first-order key exists (written by the
    real writer -- the exec client's boot-reconcile/create-path shape --
    here simulated by writing it via the SAME ``store.set`` primitive the
    client's own writer uses, since no plain-key gate ambiguity exists for
    L-42 to bite on), the strategy refuses to ARM any further NO take
    account-wide, even after a simulated relaunch that only reads the
    durable key back (a fresh ``TrialDayLatch`` open over the same store)."""
    monkeypatch.setattr(cs, "NO_SIDE_SHADOW_ONLY", False)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy._order_submission_permit = object()  # type: ignore[assignment]
    assert strategy._latch is not None
    strategy._latch._store.set(NO_SIDE_FIRST_LIVE_ORDER_KEY, b'{"instrumentId": "prior"}')
    assert strategy._latch._store.get(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY) is None

    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_refuse == "no_refuse: reason=no_side_first_order_pending"
    assert strategy._latch.is_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID),
    ) is False


def test_a_no_fill_joins_to_its_station_day(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
) -> None:
    """A NO-leg fill must join via its YES sibling's facts, never land in
    ``_unjoinable_fill_instruments`` (which halts the instrument)."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=_NO_INTERIOR_ID, venue_order_id="ord-no-join"),
    )
    assert str(_NO_INTERIOR_ID) not in strategy._unjoinable_fill_instruments
    record = strategy._latch.record(  # type: ignore[union-attr]
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID),
    )
    assert record is not None
    assert record.reason == "taken"


def test_the_never_arm_walk_arms_a_never_traded_no_leg_without_position_evidence(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
) -> None:
    """A NO leg that has never traded is decided "flat" by the never-arm
    walk with NO venue position evidence (none can ever exist, E2-1), and
    this never halts the walk -- YES still arms (``on_start`` returns True,
    i.e. the strategy does not stop)."""
    # The NO instrument is a cache-only fixture (mirroring production: it is
    # never a `CurrentRungHoldConfig.instrument_ids` member, only resolved
    # into the cache) -- `_register` (not `_register_and_start`) so it can
    # be added to the cache BEFORE `start()` runs the never-arm walk.
    strategy = _register(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.cache.add_instrument(no_interior_instrument)
    strategy.start()
    # `on_start`'s never-arm walk only runs when `_submission_armed()`
    # (Phase 0 default is unarmed) -- invoke it directly, mirroring how
    # the sibling UNKNOWN test below re-runs it too.
    assert strategy._run_never_arm_walk() is True
    assert strategy.last_startup_evidence_summary is not None
    assert f"{str(_NO_INTERIOR_ID)!r}: 'flat'" in strategy.last_startup_evidence_summary


def test_a_no_leg_with_any_fill_record_is_unknown_for_no_arming_and_never_blocks_yes(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
) -> None:
    """A NO leg WITH a durable fill record on record is decided "UNKNOWN"
    by the never-arm walk (the position-shape ruling has not fired), and
    this still never blocks the YES sibling."""
    strategy = _register(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.cache.add_instrument(no_interior_instrument)
    strategy.start()
    strategy.on_order_filled(
        _fill(strategy, instrument_id=_NO_INTERIOR_ID, venue_order_id="ord-no-prior"),
    )
    # Re-run the walk directly (mirrors on_start) to observe its decision
    # for the NO leg on a station-day where it now has a fill record.
    assert strategy._run_never_arm_walk() is True
    assert strategy.last_startup_evidence_summary is not None
    assert f"{str(_NO_INTERIOR_ID)!r}: 'UNKNOWN'" in strategy.last_startup_evidence_summary
