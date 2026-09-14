"""RED-first tests for S3b (plan ``NO_SIDE_EDGE_2026-09-14.md`` S3/S4):
strategy wiring of the NO side into ``ContinuousRungHoldStrategy``, SHADOW
ONLY -- see ``NO_SIDE_SHADOW_ONLY``.

Key facts about the shared fixtures (`tests.unit.test_current_rung_hold_strategy`):
``STATION="LAX"``, ``CLIMATE_DAY=2026-09-04`` -> ``season_for == "SON"``,
``WINDOW_OPEN_NS`` local hour 12. ``INTERIOR_ID`` is ``[86, 87]``
(``width_code=0``). A ``temp_c_tenths=300`` observation resolves
``m_code=0`` -> key ``("LAX", "SON", 12, 0, 0)``, whose
``P_HOLD_LOWER=0.6982`` / ``P_HOLD_UPPER=0.7789``. The byte-identity case
(a) reuses the existing ``ask="0.40"`` YES-clears fixture verbatim. The
NO-clears cases use ``ask="0.90"``/``bid="0.85"`` instead (a valid,
non-crossed book: ``bid < ask``, unlike ``0.85``/``0.40`` which would be
crossed) -- ``NO_ask=1-0.85=0.15``, fee ``round(0.06*0.15*0.85, 2)=0.01`` ->
break-even ``0.16``, and ``p_miss_lower = 1 - 0.7789 = 0.2211 > 0.16``
clears the NO break-even (the YES side independently refuses
``edge_below_break_even`` at ``ask=0.90``, which is irrelevant to these
cases).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.strategy.current_rung_hold.continuous_strategy import NO_SIDE_SHADOW_ONLY
from breezy.strategy.current_rung_hold.decision import Take
from tests.unit.test_continuous_rung_hold_strategy import _register_and_start
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    OPEN_UPPER_ID,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)

_NO_ASK_CLEARS_BID = "0.85"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


@pytest.fixture
def open_upper_instrument() -> BinaryOption:
    return _instrument(OPEN_UPPER_ID, lower_f=88, upper_f=None)


_NO_INTERIOR_ID = sibling_instrument_id(INTERIOR_ID)


def test_no_side_shadow_only_constant_is_true() -> None:
    """RED (item 3): pins the constant; the never-submit test below stays
    valid across S5 by asserting this value explicitly."""
    assert NO_SIDE_SHADOW_ONLY is True


def test_yes_take_sequence_is_byte_identical_to_before_this_slice(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """(a) The YES path (offer tape reason, no submit) is unaffected by the
    NO-side wiring -- default bid ("0.01") makes NO_ask=0.99, refused
    ``not_executable``, so this also proves the "no NO log" default case."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert submitted == []
    assert any(rec.reason == "taken" for rec in strategy.offer_tape.records())
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse is None
    # Item 3: `submitted == []` above already proves `submit_order` was
    # never called at all this tick (YES or NO); `NO_SIDE_SHADOW_ONLY`
    # being `True` is WHY -- pinned explicitly so this test stays a valid
    # never-submit proof after S5 flips only the constant.
    assert NO_SIDE_SHADOW_ONLY is True


def test_a_clearing_no_frame_logs_exactly_one_shadow_line_and_submits_nothing(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """(b) NO clears -> exactly one `no_take_shadow:` line, never armed/consumed/submitted."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is not None
    assert strategy.last_no_take_shadow.startswith("no_take_shadow: ")
    assert str(_NO_INTERIOR_ID) in strategy.last_no_take_shadow
    assert strategy.last_no_refuse is None
    assert strategy._latch is not None
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID)
        )
        is False
    )
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID)
        )
        is False
    )


def test_sibling_yes_filled_refuses_the_no_take_with_sibling_leg_traded(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """(c) A filled YES TRIAL on the sibling forbids the NO leg (S4)."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    strategy._latch.consume(
        STATION,
        CLIMATE_DAY.isoformat(),
        latched_at_ns=WINDOW_OPEN_NS,
        instrument_id=str(INTERIOR_ID.symbol),
        ask=Decimal("0.40"),
        reason="taken",
        key_instrument_id=str(INTERIOR_ID.symbol),
        fee=Decimal("0.02"),
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse == "no_refuse: reason=sibling_leg_traded"


def test_admission_breach_refuses_station_day_admission(
    store_path: Path,
    interior_instrument: BinaryOption,
    open_upper_instrument: BinaryOption,
) -> None:
    """(d) A filled YES TRIAL on a DIFFERENT rung whose q already saturates
    Sigma-q refuses the NO candidate with `station_day_admission` (R3-7)."""
    strategy = _register_and_start(
        store_path=store_path, instruments=(interior_instrument, open_upper_instrument),
    )
    assert strategy._latch is not None
    # A filled YES trial on OPEN_UPPER_ID with BE=0.90 alone nearly
    # saturates Sigma-q; the NO candidate's own q (>=0.2211) pushes it over 1.
    strategy._latch.consume(
        STATION,
        CLIMATE_DAY.isoformat(),
        latched_at_ns=WINDOW_OPEN_NS,
        instrument_id=str(OPEN_UPPER_ID.symbol),
        ask=Decimal("0.85"),
        reason="taken",
        key_instrument_id=str(OPEN_UPPER_ID.symbol),
        fee=Decimal("0.05"),
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse == "no_refuse: reason=station_day_admission"


def test_open_intent_refuses_before_the_sibling_check(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """(e) An OPEN account-wide intent refuses the NO shadow evaluation
    before the sibling-leg check ever runs.

    `_hunt_tick`'s OWN pre-filter (Resolution B) already returns before
    `evaluate_both_sides` whenever the intent is open, so this gate is
    unreachable end-to-end through `on_quote_tick` while the intent is
    open (by design -- see `_evaluate_no_side_shadow`'s docstring). This
    test therefore calls the gated method directly, with NO sibling fill
    and NO admission breach on record: if the intent check did not fire
    FIRST, the sibling check (`None`, no sibling exists) and the admission
    check (a lone NO candidate's own q is < 1) would both pass, and a
    `no_take_shadow:` line would be emitted instead -- observing an
    `intent_open` refusal instead proves ordering (a).
    """
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    # Arm the SAME account-wide intent singleton this running strategy's
    # `TrialDayLatch` already shares (`_intent_latch`), directly -- no
    # sibling fill, no admission breach on record for this station-day.
    strategy._latch._intent_latch.arm("a" * 64, now_ns=WINDOW_OPEN_NS)  # type: ignore[union-attr]
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
    assert strategy.last_no_refuse == "no_refuse: reason=intent_open"


def test_a_crossed_frame_refuses_both_sides_with_no_log_flood(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """(f) A crossed book (bid >= ask) refuses BOTH sides `not_executable`
    (decision-layer, silent) across many repeated ticks -- never a
    `no_take_shadow:`/`no_refuse:` line, since the NO side never reaches a
    Take at all."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    for minute in range(5):
        strategy.on_quote_tick(
            _quote(
                INTERIOR_ID,
                ask="0.40",
                bid="0.95",  # bid >= ask -> crossed
                ts_event=WINDOW_OPEN_NS + minute * 60_000_000_000,
            )
        )
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse is None
    assert strategy.refusals.count("not_executable") >= 1


def test_v2_current_rung_hold_strategy_harness_is_unaffected(
    store_path: Path,
) -> None:
    """(g) v2 (`CurrentRungHoldStrategy`) never imports/uses the NO-side
    wiring added to `ContinuousRungHoldStrategy` -- confirmed structurally:
    the byte-frozen v2 module is untouched by this slice (no import edit),
    so its own existing test module (run as part of the broader bundle)
    passing unedited IS the proof; this test only pins that the two
    strategy classes remain distinct and v2 carries no NO-side symbol."""
    import breezy.strategy.current_rung_hold.strategy as v2_strategy

    assert not hasattr(v2_strategy, "NO_SIDE_SHADOW_ONLY")
    assert not hasattr(v2_strategy, "evaluate_both_sides")
