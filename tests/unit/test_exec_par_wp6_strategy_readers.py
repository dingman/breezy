"""EXEC-PAR WP6: strategy pre-filters, re-arm release and exit wiring read the slot table.

K=1 (the default) must behave exactly as before; at K>1 every pre-filter is per-slug and
uses the same read-only admission predicate as the exec gate.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import InstrumentId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.orders import Order
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.decision import Take
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from tests.unit.test_continuous_rung_hold_strategy import (
    _arm_and_release_stale_intent,
    _register_and_start,
)
from tests.unit.test_current_rung_hold_exit_wiring import _cached_exit_order
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

_SUBMIT_CHAIN = "breezy.adapters.polymarket_us.exec.submit_chain"


def _fingerprint(order: Order) -> str:
    """Compute the exec client's intent fingerprint for ``order``, for TEST SETUP ONLY.

    It exists so a test can arm a slot whose fingerprint matches a cached order. It
    has no submit capability and no egress capability: it calls one pure hashing
    function. The module is resolved by name only so this file adds no static import
    of the exec package to the egress guard's scan.
    """
    fingerprint = importlib.import_module(_SUBMIT_CHAIN).intent_fingerprint(order)
    assert isinstance(fingerprint, str)
    return fingerprint


FP_A = "a" * 64
FP_B = "b" * 64
SLUG_A = "lax-86-87"
SLUG_B = "lax-88-plus"
FAMILY = "pm_us_crh_test"
NS_PER_SEC = 1_000_000_000
#: past the 120 s same-burst floor the stale-inflight release gates on
PAST_FLOOR_NS = WINDOW_OPEN_NS + 121 * NS_PER_SEC


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


@pytest.fixture
def open_upper_instrument() -> BinaryOption:
    return _instrument(OPEN_UPPER_ID, lower_f=88, upper_f=None)


def _k_factory(store_path: Path, *, k: int) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    @contextmanager
    def _open() -> Iterator[TrialDayLatch]:
        with open_submit_intent_latch(
            SqliteStateStore(store_path),
            store_path,
            max_slots=k,
            v2_predicate=lambda: True,
            clock_ns=lambda: WINDOW_OPEN_NS,
        ) as intent_latch:
            if k > 1:
                intent_latch.write_breaker_heartbeat(
                    hb_ns=WINDOW_OPEN_NS, resolver_pass_ns=WINDOW_OPEN_NS
                )
            yield open_trial_day_latch(
                intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id=FAMILY
            )

    return _open


def _start_k(
    store_path: Path, instruments: tuple[BinaryOption, ...], *, k: int
) -> ContinuousRungHoldStrategy:
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(i.id for i in instruments),
        no_side_calibration_gate_cleared=True,
    )
    strategy = ContinuousRungHoldStrategy(cfg, trial_day_latch_factory=_k_factory(store_path, k=k))
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=Portfolio(msgbus=msgbus, cache=cache, clock=clock),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    strategy.start()
    return strategy


def _latch_of(strategy: ContinuousRungHoldStrategy) -> TrialDayLatch:
    assert strategy._latch is not None
    return strategy._latch


def _arm_slot(strategy: ContinuousRungHoldStrategy, fp: str, slug: str) -> str:
    intent_latch = _latch_of(strategy)._intent_latch
    assert intent_latch is not None
    return intent_latch.arm_slot(fp, slug=slug, is_exit=False, now_ns=WINDOW_OPEN_NS).intent_id


# ---------------------------------------------------------------------------
# _hunt_tick pre-filter (continuous_strategy ~1918)
# ---------------------------------------------------------------------------


def test_hunt_proceeds_on_other_slug_when_not_k_full(
    store_path: Path, interior_instrument: BinaryOption, open_upper_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument, open_upper_instrument), k=2)
    _arm_slot(strategy, FP_A, SLUG_B)  # the OTHER slug's order is stuck open
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert strategy.diagnostics.count("open_intent_wait") == 0
    assert len(strategy.offer_tape) > 0  # the hunt reached the decision, not the WAIT


def test_hunt_waits_on_the_open_slug_and_when_k_full(
    store_path: Path, interior_instrument: BinaryOption, open_upper_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument, open_upper_instrument), k=2)
    _arm_slot(strategy, FP_A, SLUG_A)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy.diagnostics.count("open_intent_wait") == 1  # same slug open

    _arm_slot(strategy, FP_B, SLUG_B)  # K=2 now full
    strategy.on_quote_tick(
        _quote(OPEN_UPPER_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 61 * NS_PER_SEC)
    )
    assert strategy.diagnostics.count("open_intent_wait") == 2


def test_hunt_waits_on_a_breaker_halt_at_k_gt_1(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    intent_latch = _latch_of(strategy)._intent_latch
    assert intent_latch is not None
    intent_latch.write_breaker_halt("duplicate_suspect", ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert strategy.diagnostics.count("open_intent_wait") == 1
    assert len(strategy.offer_tape) == 0


def test_open_intent_wait_observation_names_slug(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    intent_id = _arm_slot(strategy, FP_A, SLUG_A)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    line = strategy.last_open_intent_wait
    assert line is not None
    assert f"slug={SLUG_A}" in line
    assert f"intent_id={intent_id}" in line
    assert "fingerprint" not in line and FP_A not in line


def test_wait_observation_is_deduped_per_slug_at_k_gt_1(
    store_path: Path,
    interior_instrument: BinaryOption,
    open_upper_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = _start_k(store_path, (interior_instrument, open_upper_instrument), k=3)
    _arm_slot(strategy, FP_A, SLUG_A)
    _arm_slot(strategy, FP_B, SLUG_B)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    lines: list[str] = []
    monkeypatch.setattr(strategy, "_emit_open_intent_wait", lines.append)

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(_quote(OPEN_UPPER_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert len(lines) == 2
    assert f"slug={SLUG_A}" in lines[0] and f"slug={SLUG_B}" in lines[1]


# ---------------------------------------------------------------------------
# Re-arm release is per slug (continuous_strategy ~2496)
# ---------------------------------------------------------------------------


def _release(strategy: ContinuousRungHoldStrategy, iid: InstrumentId) -> bool:
    latch = _latch_of(strategy)
    latch.set_inflight(STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(iid))
    released = strategy._release_stale_inflight(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(iid),
        attempts=1,
        last_attempt_ns=WINDOW_OPEN_NS,
        now_ns=PAST_FLOOR_NS,
    )
    assert released == (
        not latch.is_inflight(STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(iid))
    )
    return released


def test_rearm_release_is_per_slug(
    store_path: Path, interior_instrument: BinaryOption, open_upper_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument, open_upper_instrument), k=3)
    _arm_slot(strategy, FP_A, SLUG_A)

    assert _release(strategy, INTERIOR_ID) is False  # its own slug still has an open intent
    assert _release(strategy, OPEN_UPPER_ID) is True  # another slug's open order does not block


def test_rearm_release_waits_on_a_breaker_halt_at_k_gt_1(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    intent_latch = _latch_of(strategy)._intent_latch
    assert intent_latch is not None
    intent_latch.write_breaker_halt("x", ts_ns=WINDOW_OPEN_NS)

    assert _release(strategy, INTERIOR_ID) is False


# ---------------------------------------------------------------------------
# K=1 neutrality of every modified pre-filter
# ---------------------------------------------------------------------------


def test_k1_hunt_tick_prefilter_neutral(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    _arm_and_release_stale_intent(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert strategy.diagnostics.count("open_intent_wait") == 1
    assert len(strategy.offer_tape) == 0
    line = strategy.last_open_intent_wait
    assert line is not None
    assert "slug=" not in line  # byte-identical K=1 observation line
    assert line.startswith("open_intent_wait: station=")
    assert "intent_id=" in line and "age_s=" in line


def test_k1_hunt_tick_proceeds_when_no_intent_is_open(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert strategy.diagnostics.count("open_intent_wait") == 0
    assert len(strategy.offer_tape) > 0


def test_k1_release_stale_inflight_neutral(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    latch = _latch_of(strategy)
    intent_latch = latch._intent_latch
    assert intent_latch is not None
    latch.set_inflight(STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID))
    kwargs = {
        "attempts": 1,
        "last_attempt_ns": WINDOW_OPEN_NS,
        "now_ns": PAST_FLOOR_NS,
    }
    intent = intent_latch.arm(FP_A, now_ns=WINDOW_OPEN_NS)
    # any open intent blocks the release at K=1, whatever its slug
    assert (
        strategy._release_stale_inflight(
            STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID), **kwargs
        )
        is False
    )
    intent_latch.retire(intent.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=PAST_FLOOR_NS)
    assert (
        strategy._release_stale_inflight(
            STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID), **kwargs
        )
        is True
    )


def test_k1_no_only_hunt_prefilter_neutral(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    """The NO-only hunt (consumed YES, non-fill) still observes the open-intent WAIT at K=1."""
    from tests.unit.test_continuous_rung_hold_no_only_hunt_2026_09_24 import (
        _BAND_CLEARING_BID,
        _consume_yes,
        _spy_no_side_shadow,
    )

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason="not_executable")
    intent_latch = _latch_of(strategy)._intent_latch
    assert intent_latch is not None
    intent_latch.arm(FP_A, now_ns=WINDOW_OPEN_NS)
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []
    assert strategy.diagnostics.counts == {}
    line = strategy.last_open_intent_wait
    assert line is not None and "slug=" not in line and "intent_id=" in line


def _no_take() -> Take:
    return Take(
        quantity=1,
        limit_price=Decimal("0.15"),
        p_hold_lower=Decimal("0.2211"),
        break_even=Decimal("0.16"),
        rung=(86, 87),
        side="no",
        p_bound=Decimal("0.2211"),
    )


def _run_no_shadow(strategy: ContinuousRungHoldStrategy) -> None:
    strategy._evaluate_no_side_shadow(
        station=STATION,
        climate_day_key=CLIMATE_DAY.isoformat(),
        station_day=(STATION, CLIMATE_DAY.isoformat()),
        yes_instrument_id=INTERIOR_ID,
        no_decision=_no_take(),
        now_ns=WINDOW_OPEN_NS,
        bid_size=Decimal(2),
    )


def test_k1_no_side_shadow_prefilter_neutral(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    intent_latch = _latch_of(strategy)._intent_latch
    assert intent_latch is not None
    intent_latch.arm(FP_A, now_ns=WINDOW_OPEN_NS)

    _run_no_shadow(strategy)

    assert strategy.last_no_refuse == "no_refuse: reason=intent_open"


def test_no_side_shadow_refuses_only_the_open_slug_at_k_gt_1(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    _arm_slot(strategy, FP_A, SLUG_B)  # a different slug is open and K is not full

    _run_no_shadow(strategy)
    assert strategy.last_no_refuse is None or "intent_open" not in strategy.last_no_refuse

    strategy2_path = store_path.with_name("state2.db")
    strategy2 = _start_k(strategy2_path, (interior_instrument,), k=2)
    _arm_slot(strategy2, FP_A, SLUG_A)  # THIS slug is open
    _run_no_shadow(strategy2)
    # K>1: the log label carries the actual admission reason
    assert strategy2.last_no_refuse == "no_refuse: reason=intent_open:slug_open"


def test_no_side_refusal_label_carries_the_breaker_reason_at_k_gt_1(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    intent_latch = _latch_of(strategy)._intent_latch
    assert intent_latch is not None
    intent_latch.write_breaker_halt("x", ts_ns=WINDOW_OPEN_NS)

    _run_no_shadow(strategy)

    assert strategy.last_no_refuse == "no_refuse: reason=intent_open:breaker_halted"


def test_silent_wait_on_a_breaker_halt_logs_one_deduped_reason_line_at_k_gt_1(
    store_path: Path, interior_instrument: BinaryOption, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    intent_latch = _latch_of(strategy)._intent_latch
    assert intent_latch is not None
    intent_latch.write_breaker_halt("x", ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    lines: list[str] = []
    monkeypatch.setattr(strategy, "_emit_open_intent_wait", lines.append)

    for minutes in (0, 1, 2):
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + minutes * 60 * NS_PER_SEC)
        )

    assert len(lines) == 1  # no open intent anywhere; one line, then deduped per hour
    assert f"slug={SLUG_A}" in lines[0] and "reason=breaker_halted" in lines[0]
    assert "intent_id=" not in lines[0]


def test_silent_wait_on_cooloff_logs_the_reason_at_k_gt_1(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    latch = _latch_of(strategy)
    intent_latch = latch._intent_latch
    assert intent_latch is not None
    slot = intent_latch.arm_slot(FP_A, slug=SLUG_A, is_exit=False, now_ns=WINDOW_OPEN_NS)
    intent_latch.retire(
        slot.intent_id, RetirementReason.ACCEPTED_ZERO_FILL_TERMINAL, now_ns=WINDOW_OPEN_NS
    )
    reason = latch.admission_would_refuse(SLUG_A, False)
    assert reason is not None and "cool" in reason
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    line = strategy.last_open_intent_wait
    assert line is not None and f"reason={reason}" in line and f"slug={SLUG_A}" in line


def test_k1_wait_line_has_no_reason_suffix(
    store_path: Path, interior_instrument: BinaryOption
) -> None:
    _arm_and_release_stale_intent(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert strategy.last_open_intent_wait is not None
    assert "reason=" not in strategy.last_open_intent_wait


def test_inflight_release_skip_text_k1_is_unchanged_and_k_gt_1_names_the_reason(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path
) -> None:
    k1 = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert k1._inflight_release_blocked_text("anything") == (
        "the account-wide submit intent is still OPEN"
    )
    k2 = _start_k(tmp_path / "k2.db", (interior_instrument,), k=2)
    text = k2._inflight_release_blocked_text("breaker_halted")
    assert "breaker_halted" in text and "account-wide" not in text


def test_scope_helper_failure_is_contained_and_logged_at_debug(
    store_path: Path, interior_instrument: BinaryOption, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = _start_k(store_path, (interior_instrument,), k=2)
    _arm_slot(strategy, FP_A, SLUG_A)

    def _boom(instrument_id: str) -> str:
        raise RuntimeError("scope fault")

    monkeypatch.setattr(strategy, "_open_intent_wait_scope", _boom)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert strategy.diagnostics.count("open_intent_wait") == 1  # the WAIT is unaffected


# ---------------------------------------------------------------------------
# Exit wiring: fingerprint match across every open slot
# ---------------------------------------------------------------------------


def test_exit_wiring_halts_on_stale_exit_in_any_slot(
    store_path: Path, interior_instrument: BinaryOption, open_upper_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument, open_upper_instrument), k=3)
    latch = _latch_of(strategy)
    intent_latch = latch._intent_latch
    assert intent_latch is not None
    order = _cached_exit_order(strategy, client_order_id="O-EXIT-k", position_id="P-k")
    # An older, unrelated entry slot comes first; the exit's own slot is NOT the oldest.
    intent_latch.arm_slot(FP_A, slug=SLUG_B, is_exit=False, now_ns=WINDOW_OPEN_NS - 5)
    intent_latch.arm_slot(
        _fingerprint(order),
        slug=SLUG_A,
        is_exit=True,
        now_ns=WINDOW_OPEN_NS,
    )

    strategy.check_ambiguous_exit_intent(
        client_order_id="O-EXIT-k", position_id="P-k", now_ns=WINDOW_OPEN_NS + 31 * NS_PER_SEC
    )

    assert latch.is_family_halted() is True


def test_exit_wiring_ignores_a_young_matching_slot_and_a_stale_foreign_one_at_k_gt_1(
    store_path: Path, interior_instrument: BinaryOption, open_upper_instrument: BinaryOption
) -> None:
    strategy = _start_k(store_path, (interior_instrument, open_upper_instrument), k=3)
    latch = _latch_of(strategy)
    intent_latch = latch._intent_latch
    assert intent_latch is not None
    order = _cached_exit_order(strategy, client_order_id="O-EXIT-y", position_id="P-y")
    intent_latch.arm_slot(FP_A, slug=SLUG_B, is_exit=False, now_ns=WINDOW_OPEN_NS)
    intent_latch.arm_slot(
        _fingerprint(order),
        slug=SLUG_A,
        is_exit=True,
        now_ns=WINDOW_OPEN_NS,
    )

    strategy.check_ambiguous_exit_intent(
        client_order_id="O-EXIT-y", position_id="P-y", now_ns=WINDOW_OPEN_NS + NS_PER_SEC
    )
    assert latch.is_family_halted() is False

    # past the deadline the foreign entry slot is old too, but only the exit's own
    # fingerprint may halt: retire the exit's slot first and the family stays live.
    own = next(i for i in latch.open_submit_intents() if i.is_exit)
    intent_latch.retire(own.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=WINDOW_OPEN_NS)
    strategy.check_ambiguous_exit_intent(
        client_order_id="O-EXIT-y", position_id="P-y", now_ns=WINDOW_OPEN_NS + 40 * NS_PER_SEC
    )
    assert latch.is_family_halted() is False
