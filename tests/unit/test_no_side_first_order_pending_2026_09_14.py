"""S5 plan (Rev 4, Track B commit 5) tests for the bounded first-order
containment window's strategy-side wiring, per the coordinator's mid-task
scope adjustment (2026-09-14): implements E3-2 (pending gate placement),
E3-5 (pending shadow log), the `LATCH_GATE_REFUSAL_REASONS` addition
(E4-6), E2-3 (day-budget WAIT submit-suppression) and E2-4 (partial-fill
exclusion is leg-agnostic). E3-1 (the never-arm cross-check for a NO fill)
is explicitly HELD pending new venue evidence that a NO fill may land as a
SHORT/negative on the YES slug rather than a LONG -- see the xfail test at
the bottom of this file, which documents both candidate shapes.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.exec.client import BUDGET_EXHAUSTED_KEY_PREFIX
from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
)
from breezy.adapters.polymarket_us.operator_controls import utc_day_for_ns
from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.strategy.current_rung_hold.decision import Take
from breezy.strategy.current_rung_hold.trial_day_latch import (
    LATCH_GATE_REFUSAL_REASONS,
    NO_SIDE_FIRST_ORDER_PENDING_REASON,
)
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
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

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from score_live_trials import FilledTrial, _admit_fill

_NO_ASK_CLEARS_BID = "0.85"
_NO_INTERIOR_ID = sibling_instrument_id(INTERIOR_ID)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def _write_first_order_key(store_path: Path) -> None:
    store = SqliteStateStore(store_path)
    store.set(NO_SIDE_FIRST_LIVE_ORDER_KEY, b'{"instrumentId":"x"}')
    store.close()


def _write_captured_key(store_path: Path) -> None:
    store = SqliteStateStore(store_path)
    store.set(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY, b'{"rulingPath":"x"}')
    store.close()


# ---------------------------------------------------------------------------
# E4-6: the closed-set reason addition.
# ---------------------------------------------------------------------------


def test_no_side_first_order_pending_reason_joins_the_closed_set() -> None:
    assert NO_SIDE_FIRST_ORDER_PENDING_REASON in LATCH_GATE_REFUSAL_REASONS
    assert NO_SIDE_FIRST_ORDER_PENDING_REASON == "no_side_first_order_pending"


# ---------------------------------------------------------------------------
# E3-2/E3-5: the pending gate never blocks evaluation; only the log's
# `pending=` field reflects the containment window.
# ---------------------------------------------------------------------------


def test_pending_does_not_refuse_evaluation_and_the_shadow_log_marks_pending_1(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    _write_first_order_key(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is not None
    assert strategy.last_no_take_shadow.endswith("pending=1")
    assert strategy.last_no_refuse is None


def test_not_pending_the_shadow_log_marks_pending_0(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert strategy.last_no_take_shadow is not None
    assert strategy.last_no_take_shadow.endswith("pending=0")


def test_pending_with_the_captured_key_also_present_marks_pending_0(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """Termination (amendment §8 item 4): both keys present closes the
    containment window -- `is_no_side_pending` is `False` again."""
    _write_first_order_key(store_path)
    _write_captured_key(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert strategy.last_no_take_shadow is not None
    assert strategy.last_no_take_shadow.endswith("pending=0")


def test_pending_still_lets_the_sibling_leg_traded_gate_fire_first(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """The pending check runs before any side effect but refuses NOTHING
    itself -- every downstream gate still runs exactly as before."""
    from tests.unit.test_continuous_rung_hold_fill_wiring import _fill

    _write_first_order_key(store_path)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-sibling"),
    )
    no_take = Take(
        quantity=1,
        limit_price=Decimal("0.15"),
        p_hold_lower=Decimal("0.2211"),
        break_even=Decimal("0.16"),
        rung=(86, 87),
        side="no",
        p_bound=Decimal("0.2211"),
    )
    strategy._evaluate_no_side_shadow(
        station=STATION,
        climate_day_key=CLIMATE_DAY.isoformat(),
        station_day=(STATION, CLIMATE_DAY.isoformat()),
        yes_instrument_id=INTERIOR_ID,
        no_decision=no_take,
        now_ns=WINDOW_OPEN_NS,
        bid_size=Decimal(2),
    )
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse == "no_refuse: reason=sibling_leg_traded"


# ---------------------------------------------------------------------------
# E2-3: the day-budget stop still never submits on the NO leg (a WAIT, not
# a refusal by this gate -- the existing day-budget diagnostic path).
# ---------------------------------------------------------------------------


def test_no_order_is_submitted_on_the_no_leg_after_the_day_stop(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """The YES-side day-budget stop (operator ruling 2026-09-14, `_hunt_
    tick:807-808`) returns BEFORE `evaluate_both_sides`/`_evaluate_no_side_
    shadow` are ever reached -- so the NO leg's OWN day-budget check inside
    `_evaluate_no_side_shadow` is unreachable via `on_quote_tick` (it exists
    as defence in depth for a direct call, exactly like its `is_intent_
    open` sibling above it). `_maybe_submit` is never called either way."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    utc_day = utc_day_for_ns(WINDOW_OPEN_NS).isoformat()
    strategy._latch._store.set(  # type: ignore[attr-defined]
        f"{BUDGET_EXHAUSTED_KEY_PREFIX}{utc_day}", b"1",
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse is None
    assert strategy.diagnostics.count("day_budget_exhausted") == 1

    # Direct-call proof that the NO leg's OWN gate (defence in depth) also
    # refuses cleanly and never submits, when reached directly.
    no_take = Take(
        quantity=1,
        limit_price=Decimal("0.15"),
        p_hold_lower=Decimal("0.2211"),
        break_even=Decimal("0.16"),
        rung=(86, 87),
        side="no",
        p_bound=Decimal("0.2211"),
    )
    strategy._evaluate_no_side_shadow(
        station=STATION,
        climate_day_key=CLIMATE_DAY.isoformat(),
        station_day=(STATION, CLIMATE_DAY.isoformat()),
        yes_instrument_id=INTERIOR_ID,
        no_decision=no_take,
        now_ns=WINDOW_OPEN_NS,
        bid_size=Decimal(2),
    )
    assert submitted == []
    assert strategy.last_no_refuse == "no_refuse: reason=day_budget_exhausted"


# ---------------------------------------------------------------------------
# E2-4(a): the qty != 1 exclusion is leg-agnostic (a NO-leg fill excludes
# exactly like a YES-leg fill).
# ---------------------------------------------------------------------------


def test_a_partial_no_fill_is_excluded_not_tallied_as_qty_one() -> None:
    trial = FilledTrial(
        trial_id="t-no-1",
        station=STATION,
        climate_day=CLIMATE_DAY.isoformat(),
        instrument_id=str(_NO_INTERIOR_ID),
        bucket=None,
        fill_px=Decimal("0.15"),
        fee=Decimal("0.01"),
        qty=Decimal("0.5"),
        filled_at_ns=0,
        entry_ask=Decimal("0.15"),
        scheduled_release_at_ns=0,
    )
    exclusion = _admit_fill(trial)
    assert exclusion is not None
    assert exclusion.reason == "partial_fill"


# ---------------------------------------------------------------------------
# E3-1 HELD (coordinator scope adjustment, 2026-09-14): new venue evidence
# (a NO buy preview echoes `intent: ORDER_INTENT_BUY_SHORT`,
# `side: ORDER_SIDE_SELL` on the SAME market slug) means a real NO fill's
# venue position on that slug may be reported as a SHORT/negative rather
# than the LONG the never-arm walk's fail-closed case assumes. The
# cross-check is NOT implemented pending a position-shape ruling; this
# test documents both candidate shapes and is expected to fail either way
# until the ruling lands and the real implementation replaces it.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "pending venue position-shape ruling: after a NO fill, the venue "
        "position on the YES slug may be LONG (E3-1's original assumption) "
        "or SHORT/negative (new preview evidence, "
        "intent=ORDER_INTENT_BUY_SHORT/side=ORDER_SIDE_SELL) -- the "
        "never-arm cross-check is held until the shape is captured"
    ),
)
def test_never_arm_cross_check_for_a_no_fill_shape_is_undetermined() -> None:
    """Documents the two candidate shapes without asserting either:
    (a) LONG on the YES id (E3-1's original assumption: sibling NO fill
        accounts for it, arming continues); (b) non-LONG (SHORT/negative)
        on the YES id after a NO fill (the new venue evidence's shape,
        which `_run_never_arm_walk`'s CURRENT `net_position <= 0` check
        would treat as already-flat, not as evidence needing a NO-leg
        cross-check at all). Both cannot be simultaneously implemented
        without the ruling; this test intentionally never passes yet.
    """
    raise AssertionError(
        "no implementation exists -- awaiting the position-shape ruling "
        "(candidate shapes: LONG-on-YES-id vs SHORT/negative-on-YES-id "
        "after a NO fill)"
    )
