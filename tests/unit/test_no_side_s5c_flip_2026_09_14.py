"""RED-first tests for S5 Track C, commit 1 (plan ``NO_SIDE_S5_EXEC_2026-09-14.md``
§5): real NO arming/consuming/submitting behind the still-True
``NO_SIDE_SHADOW_ONLY`` flag. Every test that exercises the real arm path
monkeypatches the flag ``False`` locally -- the flip itself is a separate,
later commit.

Client-side pieces originally named in the brief (a C1-prefix first-order-
key write and a synchronous pending refusal, both inside `_submit_order`)
were NOT implemented there: both require calling `self._store_set`/
`self._store_get`/`leg_of` from inside `_submit_order`, which is scanned
by `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`
(`tests/unit/test_execution_egress_firewall_guard.py`) and is not on that
allowlist. That STOP was adjudicated: the ruled placement is STRATEGY-
SIDE. `_evaluate_no_side_shadow` itself now writes
`NO_SIDE_FIRST_LIVE_ORDER_KEY` (via the shared, I/O-free
`no_side_keys.first_live_order_payload` helper) immediately before the
arm block, with zero `await` between the `pending` read and this write --
see the tests below (a)-(d) and the SAFETY comment at the write site.
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
from breezy.strategy.current_rung_hold.decision import Take
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

_NO_TAKE = Take(
    quantity=1,
    limit_price=Decimal("0.15"),
    p_hold_lower=Decimal("0.2211"),
    break_even=Decimal("0.16"),
    rung=(86, 87),
    side="no",
    p_bound=Decimal("0.2211"),
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the flag forced ``True`` (S5 flip: the default is now
    ``False`` -- this proves the S3b shadow-only code path is still fully
    reachable and byte-identical, never removed by the flip)."""
    monkeypatch.setattr(cs, "NO_SIDE_SHADOW_ONLY", True)
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
    L-42 to bite on), the strategy never ARMS a further NO take account-
    wide -- a silent WAIT (E3-5: the evaluation itself, and its shadow
    log, stay observable; only arming/submission is skipped, never a
    `no_refuse:` line), even after a simulated relaunch that only reads
    the durable key back (a fresh ``TrialDayLatch`` open over the same
    store)."""
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
    assert strategy.last_no_refuse is None
    assert strategy.last_no_take_shadow is not None
    assert strategy.last_no_take_shadow.endswith("pending=1")
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


# ---------------------------------------------------------------------------
# S5 Track C, strategy-side first-order key write (adjudicated placement).
# ---------------------------------------------------------------------------


def test_a_two_call_synchronous_burst_leaves_exactly_one_no_take_submitted(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) Two direct `_evaluate_no_side_shadow` calls, back-to-back with
    no `await` between them (plain synchronous methods, exactly what a
    real two-station tick sequence looks like in one process) -- the
    FIRST writes `NO_SIDE_FIRST_LIVE_ORDER_KEY` and submits; the SECOND
    (a different rung/day, so it clears every earlier gate on its own
    merits) observes `pending=True` and WAITs silently."""
    monkeypatch.setattr(cs, "NO_SIDE_SHADOW_ONLY", False)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy._order_submission_permit = object()  # type: ignore[assignment]
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    assert strategy._latch is not None

    strategy._evaluate_no_side_shadow(
        station=STATION,
        climate_day_key=CLIMATE_DAY.isoformat(),
        station_day=(STATION, CLIMATE_DAY.isoformat()),
        yes_instrument_id=INTERIOR_ID,
        no_decision=_NO_TAKE,
        now_ns=WINDOW_OPEN_NS,
        bid_size=Decimal(2),
    )
    assert len(submitted) == 1
    assert strategy._latch._store.get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is not None

    # A different station-day, own gates clear on their own merits, in the
    # SAME synchronous burst.
    strategy._evaluate_no_side_shadow(
        station="SFO",
        climate_day_key="2026-09-05",
        station_day=("SFO", "2026-09-05"),
        yes_instrument_id=INTERIOR_ID,
        no_decision=_NO_TAKE,
        now_ns=WINDOW_OPEN_NS + 1,
        bid_size=Decimal(2),
    )
    assert len(submitted) == 1
    assert strategy.last_no_take_shadow is not None
    assert strategy.last_no_take_shadow.endswith("pending=1")
    assert strategy.last_no_refuse is None


def test_a_refused_submit_still_leaves_the_key_set_and_no_order(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(b) `_maybe_submit` refusing downstream of the write (here: no
    submission permit at all -- `_submission_armed()` False) leaves the
    key SET and does not submit -- "pending with no order" fails closed,
    it is never cleared by this method."""
    monkeypatch.setattr(cs, "NO_SIDE_SHADOW_ONLY", False)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._order_submission_permit is None
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    assert strategy._latch is not None

    strategy._evaluate_no_side_shadow(
        station=STATION,
        climate_day_key=CLIMATE_DAY.isoformat(),
        station_day=(STATION, CLIMATE_DAY.isoformat()),
        yes_instrument_id=INTERIOR_ID,
        no_decision=_NO_TAKE,
        now_ns=WINDOW_OPEN_NS,
        bid_size=Decimal(2),
    )
    assert submitted == []
    assert strategy._latch._store.get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is not None


def test_the_key_persists_across_a_simulated_relaunch_and_blocks_further_arming(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c) A fresh `TrialDayLatch`/strategy opened over the SAME store
    (a simulated relaunch) reads the durable key back and stays blocked."""
    monkeypatch.setattr(cs, "NO_SIDE_SHADOW_ONLY", False)
    first = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    first._order_submission_permit = object()  # type: ignore[assignment]
    first.submit_order = lambda order: None  # type: ignore[method-assign]
    first._evaluate_no_side_shadow(
        station=STATION,
        climate_day_key=CLIMATE_DAY.isoformat(),
        station_day=(STATION, CLIMATE_DAY.isoformat()),
        yes_instrument_id=INTERIOR_ID,
        no_decision=_NO_TAKE,
        now_ns=WINDOW_OPEN_NS,
        bid_size=Decimal(2),
    )
    assert first._latch is not None
    assert first._latch._store.get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is not None
    first.stop()

    # Simulated relaunch: a fresh strategy/latch pair opened over the
    # SAME store path -- the durable key is read back, never re-derived
    # from in-process state.
    relaunched = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, no_interior_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    relaunched._order_submission_permit = object()  # type: ignore[assignment]
    submitted: list[object] = []
    relaunched.submit_order = submitted.append  # type: ignore[method-assign]
    relaunched._evaluate_no_side_shadow(
        station="SFO",
        climate_day_key="2026-09-05",
        station_day=("SFO", "2026-09-05"),
        yes_instrument_id=INTERIOR_ID,
        no_decision=_NO_TAKE,
        now_ns=WINDOW_OPEN_NS + 1,
        bid_size=Decimal(2),
    )
    assert submitted == []
    assert relaunched.last_no_take_shadow is not None
    assert relaunched.last_no_take_shadow.endswith("pending=1")


def test_the_yes_path_is_untouched_by_the_strategy_side_key_write(
    store_path: Path,
    interior_instrument: BinaryOption,
    no_interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(d) A YES take (default bid -> NO_ask=0.99, no NO evaluation ever
    reaches `Take`) still arms/submits normally with the flag `False` and
    the strategy-side key write present in the module -- the YES arm
    block (:1020-1041) is byte-unchanged by this commit."""
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
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert len(submitted) == 1
    assert submitted[0].instrument_id == INTERIOR_ID
    assert strategy.last_no_take_shadow is None
    assert strategy._latch is not None
    assert strategy._latch._store.get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is None
