"""EXEC-PAR WP6: the read-only slot-table readers (latch surface and exit guard).

``TrialDayLatch.admission_would_refuse`` must be the SAME predicate the exec gate
applies (``SubmitIntentLatch.admission_refusal``), so a strategy pre-filter can never
disagree with the gate it fronts. At K=1 it must equal the old ``is_intent_open``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    RetirementReason,
    SubmitIntentCorrupt,
    SubmitIntentLatch,
    open_submit_intent_latch,
)
from breezy.settlement.exit_guard import SettlementCloseRefused, assert_settlement_close_permitted
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayLatch,
    TrialDayLatchError,
    open_trial_day_latch,
)
from tests.unit.test_submit_intent_slots import (
    COOLOFF_NS,
    FP,
    NOW,
    SEC,
    Clock,
    Store,
    _b64,
    _id,
    _rec,
    _v2,
)

SLUGS = ("lax-86-87", "lax-88-plus", "sfo-70-71", "nyc-60-61")


@contextmanager
def _latches(
    store: Store,
    tmp_path: Path,
    *,
    k: int,
    clock: Clock | None = None,
    breaker: bool = True,
    subdir: str = "",
) -> Iterator[tuple[SubmitIntentLatch, TrialDayLatch]]:
    clk = Clock() if clock is None else clock
    base = tmp_path / subdir if subdir else tmp_path
    base.mkdir(parents=True, exist_ok=True)
    with open_submit_intent_latch(
        store,
        base / "state.db",
        max_slots=k,
        cooloff_ns=COOLOFF_NS,
        v2_predicate=lambda: True,
        clock_ns=clk,
    ) as intent_latch:
        if breaker and k > 1:
            intent_latch.write_breaker_heartbeat(hb_ns=clk(), resolver_pass_ns=clk())
        yield intent_latch, open_trial_day_latch(intent_latch)


# ---------------------------------------------------------------------------
# admission_would_refuse mirrors the exec gate's reasons
# ---------------------------------------------------------------------------


def test_admission_would_refuse_reflects_breaker_halt(tmp_path: Path) -> None:
    with _latches(Store(), tmp_path, k=3) as (intent_latch, latch):
        assert latch.admission_would_refuse(SLUGS[0], False) is None
        intent_latch.write_breaker_halt("duplicate_suspect", ts_ns=NOW)
        assert latch.admission_would_refuse(SLUGS[0], False) == "breaker_halted"
        # exits are exempt from the entry halt, exactly as at the gate
        assert latch.admission_would_refuse(SLUGS[0], True) is None


def test_admission_would_refuse_reflects_stale_heartbeat(tmp_path: Path) -> None:
    clock = Clock()
    with _latches(Store(), tmp_path, k=3, clock=clock) as (_, latch):
        assert latch.admission_would_refuse(SLUGS[0], False) is None
        clock.now_ns += 3600 * SEC
        assert latch.admission_would_refuse(SLUGS[0], False) == "breaker_heartbeat_stale"
        assert latch.admission_would_refuse(SLUGS[0], True) is None


def test_admission_would_refuse_reflects_stale_resolver_pass(tmp_path: Path) -> None:
    clock = Clock()
    with _latches(Store(), tmp_path, k=3, clock=clock) as (intent_latch, latch):
        intent_latch.write_breaker_heartbeat(
            hb_ns=clock.now_ns, resolver_pass_ns=clock.now_ns - 601 * SEC
        )
        assert latch.admission_would_refuse(SLUGS[0], False) == "breaker_resolver_stale"


def test_admission_would_refuse_reflects_quarantine_k_full_and_same_slug(tmp_path: Path) -> None:
    store = Store(
        {CURRENT_INTENT_KEY: _v2({_id(1): _rec(1, SLUGS[0])}, raw={"u1": _b64({"y": 2})})}
    )
    with _latches(store, tmp_path, k=3) as (_, latch):
        assert latch.admission_would_refuse(SLUGS[1], False) == "quarantine"
        assert latch.admission_would_refuse(SLUGS[1], True) == "quarantine"
    store2 = Store()
    with _latches(store2, tmp_path, k=2, subdir="b") as (intent_latch, latch):
        clock_ns = NOW
        intent_latch.arm_slot(FP, slug=SLUGS[0], is_exit=False, now_ns=clock_ns)
        assert latch.admission_would_refuse(SLUGS[0], False) == "slug_open"
        assert latch.admission_would_refuse(SLUGS[1], False) is None
        intent_latch.arm_slot(FP, slug=SLUGS[1], is_exit=False, now_ns=clock_ns)
        assert latch.admission_would_refuse(SLUGS[2], False) == "k_full"
        assert latch.admission_would_refuse(SLUGS[2], True) is None  # exits are K-exempt


def test_admission_would_refuse_is_read_only(tmp_path: Path) -> None:
    store = Store()
    with _latches(store, tmp_path, k=2) as (_, latch):
        store.sets.clear()
        for slug in SLUGS:
            latch.admission_would_refuse(slug, False)
            latch.admission_would_refuse(slug, True)
        assert store.sets == []


def test_admission_would_refuse_on_a_latch_without_an_intent_latch_raises(tmp_path: Path) -> None:
    with _latches(Store(), tmp_path, k=1) as (intent_latch, _):
        store, lock = intent_latch.shared_state_binding()
        bare = TrialDayLatch(store, lock)
        with pytest.raises(TrialDayLatchError):
            bare.admission_would_refuse(SLUGS[0], False)
        with pytest.raises(TrialDayLatchError):
            bare.open_submit_intents()


def test_open_submit_intents_and_max_slots_delegate(tmp_path: Path) -> None:
    with _latches(Store(), tmp_path, k=2) as (intent_latch, latch):
        assert latch.max_slots() == 2
        assert latch.open_submit_intents() == ()
        a = intent_latch.arm_slot(FP, slug=SLUGS[0], is_exit=False, now_ns=NOW)
        b = intent_latch.arm_slot(FP, slug=SLUGS[1], is_exit=True, now_ns=NOW + 1)
        assert [i.intent_id for i in latch.open_submit_intents()] == [a.intent_id, b.intent_id]
        assert [i.slug for i in latch.open_submit_intents()] == [SLUGS[0], SLUGS[1]]
        intent_latch.retire(a.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 2)
        assert [i.intent_id for i in latch.open_submit_intents()] == [b.intent_id]
        intent_latch.force_k1("test")
        assert latch.max_slots() == 1


# ---------------------------------------------------------------------------
# Property: the pre-filter predicate IS the exec admission predicate
# ---------------------------------------------------------------------------

_slot_entry = st.tuples(
    st.sampled_from(SLUGS), st.booleans(), st.booleans()
)  # slug, is_exit, legacy slug-less
_table_st = st.fixed_dictionaries(
    {
        "k": st.sampled_from([1, 2, 3]),
        "slots": st.lists(_slot_entry, max_size=4),
        "unreadable": st.integers(min_value=0, max_value=2),
        "cooloff": st.dictionaries(
            st.sampled_from(SLUGS),
            st.integers(min_value=NOW - 300 * SEC, max_value=NOW + 300 * SEC),
        ),
        "breaker": st.sampled_from(["healthy", "halted", "stale_hb", "stale_resolver", "absent"]),
        "corrupt": st.booleans(),
    }
)


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(table=_table_st)
def test_prefilter_equals_exec_admission_for_all_tables(
    tmp_path: Path, table: dict[str, object]
) -> None:
    k = table["k"]
    slots = table["slots"]
    assert isinstance(k, int) and isinstance(slots, list)
    unreadable = table["unreadable"]
    cooloff = table["cooloff"]
    assert isinstance(unreadable, int) and isinstance(cooloff, dict)
    live: dict[str, object] = {}
    for n, (slug, is_exit, legacy) in enumerate(slots, start=1):
        live[_id(n)] = _rec(n, None if legacy else slug, is_exit=is_exit)
    raw = {f"u{i}": _b64({"y": i}) for i in range(unreadable)}
    if k == 1:
        # a v1 singleton is one OPEN record under the key
        data = json.dumps(_rec(1, None), sort_keys=True).encode("utf-8") if slots else b""
        store = Store({CURRENT_INTENT_KEY: data} if slots else {})
    else:
        store = Store({CURRENT_INTENT_KEY: _v2(live, raw=raw, cooloff=cooloff)})
    if table["corrupt"]:
        store.data[CURRENT_INTENT_KEY] = b"\xff not json"
    clock = Clock()
    sub = uuid.uuid4().hex
    with _latches(store, tmp_path, k=k, clock=clock, breaker=False, subdir=sub) as (
        intent_latch,
        latch,
    ):
        mode = table["breaker"]
        if k > 1 and mode != "absent":
            hb = clock.now_ns - (3600 * SEC if mode == "stale_hb" else 0)
            rp = clock.now_ns - (700 * SEC if mode == "stale_resolver" else 0)
            intent_latch.write_breaker_heartbeat(hb_ns=hb, resolver_pass_ns=rp)
            if mode == "halted":
                intent_latch.write_breaker_halt("x", ts_ns=clock.now_ns)
        for slug in SLUGS:
            for is_exit in (False, True):
                assert latch.admission_would_refuse(
                    slug, is_exit
                ) == intent_latch.admission_refusal(slug, is_exit)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(arm_first=st.booleans(), retire_after=st.booleans(), slug=st.sampled_from(SLUGS))
def test_k1_admission_would_refuse_equals_is_intent_open(
    tmp_path: Path, arm_first: bool, retire_after: bool, slug: str
) -> None:
    with _latches(Store(), tmp_path, k=1, subdir=uuid.uuid4().hex) as (intent_latch, latch):
        if arm_first:
            intent = intent_latch.arm(FP, now_ns=NOW)
            if retire_after:
                intent_latch.retire(
                    intent.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=NOW + 1
                )
        for is_exit in (False, True):
            assert (
                latch.admission_would_refuse(slug, is_exit) is not None
            ) == latch.is_intent_open()


def test_k1_corrupt_singleton_is_refused_like_is_intent_open(tmp_path: Path) -> None:
    store = Store({CURRENT_INTENT_KEY: b"\xff not json"})
    with _latches(store, tmp_path, k=1) as (_, latch):
        assert latch.is_intent_open() is True
        assert latch.admission_would_refuse(SLUGS[0], False) is not None
        with pytest.raises(SubmitIntentCorrupt):
            latch.open_submit_intents()


def test_admission_reason_is_a_closed_nonempty_string_when_refused(tmp_path: Path) -> None:
    with _latches(Store(), tmp_path, k=1) as (intent_latch, latch):
        intent_latch.arm(FP, now_ns=NOW)
        reason = latch.admission_would_refuse(SLUGS[0], False)
        assert isinstance(reason, str) and reason


# ---------------------------------------------------------------------------
# exit_guard: scoped refusals (existing signature and behaviour unchanged)
# ---------------------------------------------------------------------------


def test_exit_guard_scoped_refusal_permits_other_slug_close() -> None:
    assert_settlement_close_permitted(
        trading_refusals=("ambiguous send",),
        instrument_id="lax-88-plus.POLYMARKET_US",
        attributed_order_id="SETTLE-1",
        refusal_scopes=("lax-86-87",),
    )


def test_exit_guard_scoped_refusal_on_the_same_slug_still_refuses() -> None:
    with pytest.raises(SettlementCloseRefused, match="unresolved trading refusal"):
        assert_settlement_close_permitted(
            trading_refusals=("ambiguous send",),
            instrument_id="lax-86-87.POLYMARKET_US",
            attributed_order_id="SETTLE-1",
            refusal_scopes=("lax-86-87",),
        )


def test_exit_guard_unscoped_still_refuses() -> None:
    for scopes in (None, ("",), ("lax-86-87", "")):
        with pytest.raises(SettlementCloseRefused, match="unresolved trading refusal"):
            assert_settlement_close_permitted(
                trading_refusals=("ambiguous send", "other"),
                instrument_id="lax-88-plus.POLYMARKET_US",
                attributed_order_id="SETTLE-1",
                refusal_scopes=scopes,
            )


def test_exit_guard_scope_length_mismatch_fails_closed() -> None:
    with pytest.raises(SettlementCloseRefused, match="unresolved trading refusal"):
        assert_settlement_close_permitted(
            trading_refusals=("a", "b"),
            instrument_id="lax-88-plus.POLYMARKET_US",
            attributed_order_id="SETTLE-1",
            refusal_scopes=("sfo-70-71",),
        )


def test_exit_guard_scoped_permit_still_requires_attribution() -> None:
    with pytest.raises(SettlementCloseRefused, match="no Breezy order"):
        assert_settlement_close_permitted(
            trading_refusals=("ambiguous send",),
            instrument_id="lax-88-plus.POLYMARKET_US",
            attributed_order_id=None,
            refusal_scopes=("lax-86-87",),
        )


def test_exit_guard_with_no_refusals_ignores_scopes() -> None:
    assert_settlement_close_permitted(
        trading_refusals=(),
        instrument_id="x",
        attributed_order_id="SETTLE-1",
        refusal_scopes=(),
    )
