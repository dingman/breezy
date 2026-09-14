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

import json
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    DurableFillRecord,
)
from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.continuous_strategy import NO_SIDE_SHADOW_ONLY
from breezy.strategy.current_rung_hold.decision import Take
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    open_trial_day_latch,
    refuse_if_sibling_leg_traded,
    station_day_admission,
)
from tests.unit.test_continuous_rung_hold_fill_wiring import _fill
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _register_and_start,
)
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    NS_PER_MIN,
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
    """(c) Safety review finding 1 (2026-09-14, commit f2d33f4): a filled
    YES TRIAL written through the REAL fill path (`on_order_filled` ->
    `consume_if_absent`, keyed by the DOTTED `str(InstrumentId)` --
    `continuous_strategy.py`'s only writer) must still forbid the sibling
    NO leg. RED on f2d33f4: the gates read the BARE symbol, which never
    matches a dotted-keyed record, so `refuse_if_sibling_leg_traded`
    silently returned `None` and the NO take was wrongly admitted.

    Calls the gated method directly (not `on_quote_tick`): once
    INTERIOR_ID's OWN trial is filled, `_hunt_tick`'s PRE-EXISTING (YES-
    only, unrelated to this slice) `is_consumed(iid)` guard short-circuits
    the ENTIRE tick for that instrument -- including the NO-side
    evaluation this slice adds further down -- before any tick for that
    instrument can reach it again. That guard is not this test's target;
    the REAL fill write (via `on_order_filled`) and the gate function
    (`refuse_if_sibling_leg_traded`, reached through
    `_evaluate_no_side_shadow`) are.
    """
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-sibling"),
    )
    assert strategy._latch is not None
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    assert record is not None
    assert record.reason == "taken"

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
        now_ns=WINDOW_OPEN_NS + NS_PER_MIN,
        bid_size=Decimal(2),
    )
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse == "no_refuse: reason=sibling_leg_traded"


def test_admission_breach_refuses_station_day_admission(
    store_path: Path,
    interior_instrument: BinaryOption,
    open_upper_instrument: BinaryOption,
) -> None:
    """(d) Safety review finding 1: `station_day_admission` must COUNT a
    real-path fill on a DIFFERENT rung, not silently skip it. The real
    writer (`_consume_or_flag_duplicate`) never sets `fee`, so a found
    record with `fee=None` correctly refuses (R3-7: an unknown `q` is
    never guessed as zero) -- RED on f2d33f4: the bare-keyed lookup never
    found this dotted-keyed record at all, so the loop skipped it
    entirely and the NO candidate was wrongly ADMITTED instead of refused.
    """
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, open_upper_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(
            strategy, instrument_id=OPEN_UPPER_ID, venue_order_id="ord-other-rung",
            last_px="0.85",
        ),
    )
    assert strategy._latch is not None
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(OPEN_UPPER_ID),
    )
    assert record is not None
    assert record.fee is None

    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse == "no_refuse: reason=station_day_admission"


def test_a_fill_absent_from_todays_facts_still_contributes_to_admission(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """[HIGH] finding 2: a rung filled EARLIER and since dropped from
    `self._facts` (a mid-day relaunch resolved a narrower ladder) must
    still be found -- via `TrialDayLatch.iter_fill_records` over
    `_candidate_instrument_ids()` (which still spans `self._config.
    instrument_ids`/`self.cache.instrument_ids()`, NOT just `self._facts`)
    -- and contribute its `q` to the admission sum.

    Mirrors `test_slug_fallback_joins_a_fill_for_an_instrument_missing_
    from_facts` (`test_continuous_rung_hold_fill_wiring.py`): a REAL,
    parseable weather slug instrument (`_join_fill_to_station_day`'s slug
    fallback requires this -- the plain test fixture ids like
    `OPEN_UPPER_ID` do not parse) stays configured and cached (so it is a
    genuine `_candidate_instrument_ids()` member and its fill genuinely
    joins), but its `self._facts` entry is removed post-boot to model the
    "ladder rebuild dropped this rung" gap.
    """
    dropped_instrument = _instrument(
        InstrumentId(Symbol("tc-temp-laxhigh-2026-09-04-gte88f"), Venue("POLYMARKET_US")),
        lower_f=88,
        upper_f=None,
    )
    dropped_iid = dropped_instrument.id
    # A durable VENUE fill (exec-client-owned; `DurableFillRecord`, a
    # different index than the strategy's own `TrialDayRecord`) for the
    # dropped rung exists BEFORE boot -- mirrors
    # `test_never_arm_walk_consumes_a_durable_fill_with_no_trial`. This is
    # what `_run_never_arm_walk` (called from `on_start`, unconditionally)
    # durably converts into a `TrialDayRecord` via `iter_fill_records` over
    # `_candidate_instrument_ids()` -- BEFORE `self._facts` is ever pruned.
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        fill_record = DurableFillRecord(
            venue_order_id="ord-dropped-rung",
            client_order_id="C-ord-dropped-rung",
            instrument_id=str(dropped_iid),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.85"),
            cumulative_fee=Decimal(0),
            fee_reconciled=True,
            ts_event=WINDOW_OPEN_NS,
        )
        store.set(
            f"{FILL_INDEX_KEY_PREFIX}{dropped_iid}",
            json.dumps(["ord-dropped-rung"]).encode("utf-8"),
        )
        store.set(f"{FILL_KEY_PREFIX}ord-dropped-rung", fill_record.to_bytes())
    store.close()

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, dropped_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    # Phase 0 never arms (`_submission_armed()` is False), so `on_start`
    # skips the never-arm walk automatically -- call it directly, exactly
    # as `test_never_arm_walk_consumes_a_durable_fill_with_no_trial` does.
    assert strategy._run_never_arm_walk() is True
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(dropped_iid),
    )
    assert record is not None
    assert record.fee is None
    # Model "this rung's ladder entry was dropped on a mid-day relaunch" --
    # removed from `self._facts` ONLY; it stays in `self._config.
    # instrument_ids`/`self.cache.instrument_ids()`, so
    # `_candidate_instrument_ids()` still names it.
    del strategy._facts[str(dropped_iid)]
    assert str(dropped_iid) not in strategy._facts
    assert str(dropped_iid) in strategy._candidate_instrument_ids()

    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid=_NO_ASK_CLEARS_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert submitted == []
    assert strategy.last_no_take_shadow is None
    assert strategy.last_no_refuse == "no_refuse: reason=station_day_admission"


def test_a_record_written_dotted_is_found_when_queried_bare_and_vice_versa(
    store_path: Path,
) -> None:
    """Latch-level pin (item 3): `_key`'s normalisation makes a single
    canonical durable key regardless of which form (bare symbol or dotted
    `str(InstrumentId)`) either the writer or the reader used."""
    store = SqliteStateStore(store_path)
    bare = "poly-lax-tmax-92-94"
    dotted = f"{bare}.POLYMARKET_US"
    with open_submit_intent_latch(store, store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        latch.consume(
            STATION,
            CLIMATE_DAY.isoformat(),
            latched_at_ns=WINDOW_OPEN_NS,
            instrument_id=dotted,
            ask=Decimal("0.40"),
            reason="taken",
            key_instrument_id=dotted,
            fee=Decimal("0.02"),
        )
        # Written DOTTED, found via a BARE-form query.
        found_via_bare = latch.record(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=bare,
        )
    assert found_via_bare is not None
    assert found_via_bare.instrument_id == dotted

    other_bare = "poly-lax-tmax-70-71"
    other_dotted = f"{other_bare}.POLYMARKET_US"
    with open_submit_intent_latch(store, store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        latch.consume(
            STATION,
            CLIMATE_DAY.isoformat(),
            latched_at_ns=WINDOW_OPEN_NS,
            instrument_id=other_bare,
            ask=Decimal("0.40"),
            reason="taken",
            key_instrument_id=other_bare,
            fee=Decimal("0.02"),
        )
        # Written BARE, found via a DOTTED-form query.
        found_via_dotted = latch.record(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=other_dotted,
        )
    assert found_via_dotted is not None
    assert found_via_dotted.instrument_id == other_bare


def test_refuse_if_sibling_leg_traded_matches_a_dotted_written_record_via_bare_input(
    store_path: Path,
) -> None:
    """Latch-level pin for `refuse_if_sibling_leg_traded` itself, isolated
    from the strategy: a YES sibling written DOTTED (the real convention)
    is found when the NO candidate is queried with the BARE symbol (S4's
    original tested contract)."""
    store = SqliteStateStore(store_path)
    yes_bare = "poly-lax-tmax-86-87"
    yes_dotted = f"{yes_bare}.POLYMARKET_US"
    no_bare = "poly-lax-tmax-86-87^no"
    with open_submit_intent_latch(store, store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        latch.consume(
            STATION,
            CLIMATE_DAY.isoformat(),
            latched_at_ns=WINDOW_OPEN_NS,
            instrument_id=yes_dotted,
            ask=Decimal("0.40"),
            reason="taken",
            key_instrument_id=yes_dotted,
        )
        got = refuse_if_sibling_leg_traded(
            store, CONTINUOUS_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY.isoformat(), no_bare,
        )
    assert got is not None
    assert got.reason == "sibling_leg_traded"


def test_station_day_admission_counts_a_dotted_written_record_via_bare_input(
    store_path: Path,
) -> None:
    """Latch-level pin for `station_day_admission` itself: an existing
    trial written DOTTED is counted when its id is passed BARE."""
    store = SqliteStateStore(store_path)
    other_bare = "poly-lax-tmax-70-71"
    other_dotted = f"{other_bare}.POLYMARKET_US"
    with open_submit_intent_latch(store, store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        latch.consume(
            STATION,
            CLIMATE_DAY.isoformat(),
            latched_at_ns=WINDOW_OPEN_NS,
            instrument_id=other_dotted,
            ask=Decimal("0.50"),
            reason="taken",
            key_instrument_id=other_dotted,
            fee=Decimal("0.01"),
        )
        got = station_day_admission(
            store,
            CONTINUOUS_TRIAL_KEY_PREFIX,
            STATION,
            CLIMATE_DAY.isoformat(),
            "yes",
            Decimal("0.55"),
            existing_instrument_ids=(other_bare,),
        )
    # 0.51 + 0.55 == 1.06 > 1
    assert got is not None
    assert got.reason == "station_day_admission"


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
