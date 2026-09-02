"""Unit tests for the submit-time order screen.

The integration proof -- that these refusals actually fire inside a running
``BacktestEngine`` -- lives in
``tests/integration/test_backtest_run_refusals.py``. THIS module pins the rule
boundaries directly against the handler, where a live engine cannot easily
produce the cases: a sell exactly equal to the net long, a sell against
already-working sells, the ``reduce_only`` exemption, and the fact that the
screen ignores every order event except ``OrderInitialized``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.identifiers import (
    ClientOrderId,
    InstrumentId,
    StrategyId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.objects import Quantity

from breezy.runtime.backtest_harness import HARNESS_SOURCE_PATH
from breezy.runtime.backtest_order_guard import (
    ORDER_EVENT_TOPIC,
    BacktestOrderGuard,
    NakedShortRefusedError,
    PostOnlyRefusedError,
    install_order_guard,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

INSTRUMENT = InstrumentId(Symbol("synthetic-guard-market"), Venue("POLYMARKET_US"))
NO_SIDE_EVIDENCE_DOC = "docs/evidence/no_side_instrument_probe_2026-08-31.md"
_DEFAULT_WORKING_CLIENT_ORDER_ID = ClientOrderId("O-WORKING")
_DEFAULT_EVENT_CLIENT_ORDER_ID = ClientOrderId("O-1")


class _FakePortfolio:
    def __init__(self, net: Decimal) -> None:
        self._net = net

    def net_position(self, instrument_id: InstrumentId) -> Decimal:
        del instrument_id
        return self._net


class _FakeOrder:
    """Widened per `docs/plans/ORDER_LIST_BYPASS_2026-09-02.md` §6: the
    pre-Increment-1 double carried only `side`/`leaves_qty`/`is_reduce_only`,
    which is structurally blind to the INITIALIZED/SUBMITTED bypass -- it
    could only ever represent an already-`orders_open`-visible order.
    `is_closed` and `client_order_id` let a test express a not-yet-open
    (or already-terminal) order, and `status` backs the guard's
    diagnosability message (RED-23).
    """

    def __init__(
        self,
        *,
        side: OrderSide,
        leaves: Decimal,
        reduce_only: bool = False,
        is_closed: bool = False,
        status: OrderStatus = OrderStatus.SUBMITTED,
        client_order_id: ClientOrderId = _DEFAULT_WORKING_CLIENT_ORDER_ID,
    ) -> None:
        self.side = side
        self.leaves_qty = Quantity(leaves, 0)
        self.is_reduce_only = reduce_only
        self.is_closed = is_closed
        self.status = status
        self.client_order_id = client_order_id


class _FakeCache:
    """`orders` replaces `orders_open` as the guard's read (§2): a dict-backed,
    unfiltered-by-openness view, matching real `Cache.orders(...)`.

    `order(client_order_id)` is Increment 2's addition (§6): the guard's
    shim treats an entry as live only while this returns `None`, so a test
    must be able to make an order APPEAR in the cache after construction --
    `add` mimics `Strategy`/`_deny_order` calling `cache.add_order` on the
    exact same `ClientOrderId` the guard already approved.
    """

    def __init__(self, orders: Sequence[_FakeOrder] = ()) -> None:
        self._orders = list(orders)
        self._by_client_order_id = {order.client_order_id: order for order in self._orders}

    def orders(self, *, instrument_id: InstrumentId | None = None) -> list[_FakeOrder]:
        del instrument_id
        return self._orders

    def order(self, client_order_id: ClientOrderId) -> _FakeOrder | None:
        return self._by_client_order_id.get(client_order_id)

    def add(self, order: _FakeOrder) -> None:
        self._orders.append(order)
        self._by_client_order_id[order.client_order_id] = order


def _guard(
    *,
    net: Decimal = Decimal(0),
    open_orders: Sequence[_FakeOrder] = (),
) -> BacktestOrderGuard:
    return BacktestOrderGuard(_FakePortfolio(net), _FakeCache(open_orders))


def _initialized(
    *,
    side: OrderSide = OrderSide.SELL,
    quantity: int = 1,
    post_only: bool = False,
    reduce_only: bool = False,
    client_order_id: ClientOrderId = _DEFAULT_EVENT_CLIENT_ORDER_ID,
) -> OrderInitialized:
    """`client_order_id` is parametrized since Increment 2 (§6): screening
    several list-shaped members in sequence (RED-17/18/20/21/24) requires
    each to carry its OWN id, since the guard's shim keys on it -- the
    default keeps every pre-Increment-2 call site (a single event per test)
    unchanged.
    """
    return OrderInitialized(
        trader_id=TraderId("BREEZY-BACKTEST-001"),
        strategy_id=StrategyId("S-1"),
        instrument_id=INSTRUMENT,
        client_order_id=client_order_id,
        order_side=side,
        order_type=OrderType.LIMIT,
        quantity=Quantity(quantity, 0),
        time_in_force=TimeInForce.GTC,
        post_only=post_only,
        reduce_only=reduce_only,
        quote_quantity=False,
        options={},
        emulation_trigger=0,
        trigger_instrument_id=None,
        contingency_type=0,
        order_list_id=None,
        linked_order_ids=None,
        parent_order_id=None,
        exec_algorithm_id=None,
        exec_algorithm_params=None,
        exec_spawn_id=None,
        tags=None,
        event_id=UUID4(),
        ts_init=0,
    )


# ---------------------------------------------------------------------------
# post_only
# ---------------------------------------------------------------------------


def test_a_post_only_buy_is_refused() -> None:
    with pytest.raises(PostOnlyRefusedError) as excinfo:
        _guard().on_order_event(_initialized(side=OrderSide.BUY, post_only=True))

    assert "post_only=True" in str(excinfo.value)


def test_a_marketable_buy_is_accepted() -> None:
    _guard().on_order_event(_initialized(side=OrderSide.BUY, post_only=False))


# ---------------------------------------------------------------------------
# naked shorts -- the boundary is `>`, not `>=`
# ---------------------------------------------------------------------------


def test_a_sell_exactly_equal_to_the_net_long_is_accepted() -> None:
    """Flattening a position is not a naked short, and must stay writable."""
    _guard(net=Decimal(10)).on_order_event(_initialized(quantity=10))


def test_a_sell_one_unit_beyond_the_net_long_is_refused() -> None:
    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(10)).on_order_event(_initialized(quantity=11))


@pytest.mark.parametrize(
    ("net", "open_orders", "event_kwargs", "is_refused"),
    [
        pytest.param(Decimal(10), (), {"quantity": 10}, False, id="flatten-position"),
        pytest.param(Decimal(10), (), {"quantity": 11}, True, id="one-beyond-net"),
        pytest.param(Decimal(0), (), {"quantity": 1}, True, id="flat-sell"),
        pytest.param(
            Decimal(10),
            (_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10)),),
            {"quantity": 10},
            True,
            id="working-sell-plus-new-sell",
        ),
        pytest.param(
            Decimal(10),
            (_FakeOrder(side=OrderSide.BUY, leaves=Decimal(10)),),
            {"quantity": 10},
            False,
            id="working-buy-does-not-count",
        ),
        pytest.param(
            Decimal(10),
            (_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10), reduce_only=True),),
            {"quantity": 10},
            True,
            id="working-reduce-only-sell-counts",
        ),
        pytest.param(
            Decimal(0),
            (),
            {"quantity": 500, "reduce_only": True},
            True,
            id="reduce-only-confers-no-exemption",
        ),
        pytest.param(
            Decimal(0),
            (),
            {"side": OrderSide.BUY, "quantity": 500},
            False,
            id="buy",
        ),
    ],
)
def test_naked_short_refusal_set_and_exception_type_are_pinned(
    net: Decimal,
    open_orders: Sequence[_FakeOrder],
    event_kwargs: dict[str, object],
    is_refused: bool,
) -> None:
    guard = _guard(net=net, open_orders=open_orders)
    event = _initialized(**event_kwargs)

    if is_refused:
        with pytest.raises(NakedShortRefusedError):
            guard.on_order_event(event)
    else:
        guard.on_order_event(event)


def test_naked_short_refusal_message_names_same_instrument_outcome_side() -> None:
    """Substance lives in the raised MESSAGE; the evidence citation lives in
    the exception class's DOCSTRING -- a ``docs/evidence`` path is a runtime
    value if it is embedded in the raised f-string, but prose in a docstring
    is a permitted citation (``test_probe_containment.py``'s
    ``find_evidence_path_reads`` detector distinguishes exactly this).
    """
    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(0)).on_order_event(_initialized(quantity=1))

    message = str(excinfo.value)
    assert NO_SIDE_EVIDENCE_DOC not in message
    assert "outcomeSide" in message
    assert "price inversion" in message
    assert "same instrument" in message
    assert '"short YES" is spelled "buy NO"' not in message
    assert "different InstrumentId" not in message
    assert "own book" not in message

    docstring = NakedShortRefusedError.__doc__ or ""
    assert NO_SIDE_EVIDENCE_DOC in docstring
    assert "same" in docstring
    assert "instrument" in docstring


def test_a_sell_with_no_position_at_all_is_refused() -> None:
    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(0)).on_order_event(_initialized(quantity=1))

    assert str(INSTRUMENT) in str(excinfo.value)


def test_two_sells_that_are_each_within_the_net_long_are_JOINTLY_refused() -> None:
    """The case a position-only check cannot see.

    Each sell alone is fully covered; together they are naked. The working
    quantity is read from the cache, so cancels and partial fills need no
    bookkeeping in the guard.
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10))]

    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))

    assert "already working" in str(excinfo.value)


def test_a_working_BUY_does_not_count_against_the_sell_budget() -> None:
    working = [_FakeOrder(side=OrderSide.BUY, leaves=Decimal(10))]

    _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))


def test_a_working_reduce_only_sell_counts_against_the_budget() -> None:
    """RED-3. Inversion of the pre-fix `..._does_not_count_against_the_budget`.

    A working `reduce_only` SELL of 10 plus an incoming plain SELL of 10
    against a net long of 10 is jointly naked -- `_working_sell_quantity` no
    longer excludes `reduce_only` orders from `pending` (F5: Nautilus's own
    overselling accounting counts every open sell, reduce-only included).
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10), reduce_only=True)]

    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))


def test_a_reduce_only_sell_against_no_position_is_still_refused() -> None:
    """RED-1. Inversion of `test_a_reduce_only_sell_is_exempt`, same inputs.

    `reduce_only` is an ordinary, attacker-settable `OrderFactory` kwarg
    (F1); an exemption keyed on it is a documented bypass, closed by running
    the identical net-long test for every SELL.
    """
    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(0)).on_order_event(_initialized(quantity=500, reduce_only=True))


def test_an_oversized_reduce_only_sell_is_refused() -> None:
    """RED-4. Net 100, no working orders, a `reduce_only` SELL of 101 is
    refused -- without depending on Nautilus's own `position_id`-gated check
    (F2) ever firing.
    """
    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(100)).on_order_event(_initialized(quantity=101, reduce_only=True))


def test_a_legitimate_reduce_only_exit_sized_to_the_net_long_passes() -> None:
    """RED-5, MUST PASS. The anti-R-6a case: a genuinely reducing sell
    satisfies `pending + quantity <= net` by the definition of reducing, so
    running the identical test for every SELL cannot refuse a real exit.
    """
    _guard(net=Decimal(100)).on_order_event(_initialized(quantity=100, reduce_only=True))


def test_a_partial_reduce_only_exit_beside_a_working_reduce_only_exit_passes() -> None:
    """RED-6, MUST PASS. The accounting is additive, not a blanket ban: a
    working `reduce_only` exit of 40 plus an incoming `reduce_only` exit of
    60 against a net long of 100 sums to exactly the net long.
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(40), reduce_only=True)]

    _guard(net=Decimal(100), open_orders=working).on_order_event(
        _initialized(quantity=60, reduce_only=True),
    )


def test_a_mixed_working_pair_is_jointly_naked() -> None:
    """RED-7. The flag confers nothing in either direction: a working plain
    SELL of 10 plus an incoming `reduce_only` SELL of 10 against a net long
    of 10 is jointly naked exactly like the all-plain or all-reduce-only
    cases.
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10))]

    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(10), open_orders=working).on_order_event(
            _initialized(quantity=10, reduce_only=True),
        )


def test_a_buy_is_never_a_naked_short() -> None:
    _guard(net=Decimal(0)).on_order_event(_initialized(side=OrderSide.BUY, quantity=500))


def test_a_reduce_only_buy_is_never_a_naked_short() -> None:
    """RED-8. Regression floor: the side check, not the flag, is what exempts
    a BUY -- `reduce_only=True` on a BUY must not somehow trip the SELL rule.
    """
    _guard(net=Decimal(0)).on_order_event(
        _initialized(side=OrderSide.BUY, quantity=500, reduce_only=True),
    )


def test_the_refusal_message_says_reduce_only_is_not_a_licence() -> None:
    """RED-11. `:202-220` is the only remediation a future author reads --
    it must say outright that `reduce_only` does not exempt a SELL here.
    """
    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(0)).on_order_event(_initialized(quantity=1, reduce_only=True))

    message = str(excinfo.value)
    assert "reduce_only" in message
    assert "not a licence" in message


# ---------------------------------------------------------------------------
# Scope: only `OrderInitialized`, and only via the documented topic
# ---------------------------------------------------------------------------


def test_a_non_initialized_order_event_is_ignored() -> None:
    """The topic carries the whole lifecycle, including the settlement leg's
    own accepted/filled events. Screening those would be a false positive.
    """

    class _NotAnInitialization:
        post_only = True
        side = OrderSide.SELL
        quantity = Quantity(500, 0)
        reduce_only = False
        instrument_id = INSTRUMENT
        client_order_id = ClientOrderId("O-2")

    _guard().on_order_event(_NotAnInitialization())


def test_the_topic_is_the_one_strategies_publish_on() -> None:
    """`trading/strategy.pyx:322` subscribes to `events.order.<strategy_id>`;
    the guard's glob must cover every strategy in the run.
    """
    assert ORDER_EVENT_TOPIC == "events.order.*"


def test_the_harness_installs_the_guard() -> None:
    """A screen nobody wires up is a comment."""
    source = Path(HARNESS_SOURCE_PATH).read_text(encoding="utf-8")

    assert "install_order_guard(engine)" in source


# ---------------------------------------------------------------------------
# R-6a §4: the backtest installer is UNCHANGED -- bare handler, no wrapper.
# ---------------------------------------------------------------------------


class _FakeEngineMsgBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, object]] = []

    def subscribe(self, *, topic: str, handler: object) -> None:
        self.subscriptions.append((topic, handler))


class _FakeEngineKernel:
    def __init__(self) -> None:
        self.msgbus = _FakeEngineMsgBus()


class _FakeEngine:
    """Stands in for the slice of ``BacktestEngine`` ``install_order_guard`` reads."""

    def __init__(self) -> None:
        self.portfolio = _FakePortfolio(Decimal(0))
        self.cache = _FakeCache()
        self.kernel = _FakeEngineKernel()


def test_the_backtest_installer_still_subscribes_the_bare_handler() -> None:
    """RED-10. R-6a §4 adds a reporting wrapper to the LIVE installer only;
    ``install_order_guard`` (backtest) keeps subscribing the guard's bare
    bound method directly, so a refusal still aborts ``engine.run()``
    exactly as before -- no reporter, no wrapper, no behaviour change."""
    engine = _FakeEngine()

    guard = install_order_guard(engine)

    assert len(engine.kernel.msgbus.subscriptions) == 1
    topic, handler = engine.kernel.msgbus.subscriptions[0]
    assert topic == ORDER_EVENT_TOPIC
    assert handler == guard.on_order_event


# ---------------------------------------------------------------------------
# R-6a §2/D5: the naked-short remediation text names subtracting working sells.
# ---------------------------------------------------------------------------


def test_a_settlement_leg_is_refused_when_a_working_exit_sell_is_outstanding() -> None:
    """RED-8 (D5). A working, non-reduce-only exit SELL of 40 against a net
    long of 100, followed by a settlement leg sized to the FULL 100, is
    refused -- `40 + 100 > 100`. The message must name SUBTRACTING working
    sells, correcting the pre-R-6a remediation text that named only
    `net_position(...)` and would have under-sized the very fix it
    prescribes."""
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(40))]

    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(100), open_orders=working).on_order_event(_initialized(quantity=100))

    message = str(excinfo.value)
    assert "already-working" in message
    assert "_working_sell_quantity" in message


# ---------------------------------------------------------------------------
# docs/plans/REDUCE_ONLY_BYPASS_2026-09-02.md §1+§2: `reduce_only` REMEDIATED.
# ---------------------------------------------------------------------------


def test_two_reduce_only_sells_within_the_net_long_are_jointly_naked() -> None:
    """RED-2, the headline case. Was `xfail(strict=True)` under
    R-6a §3/D6b, TRACKING this exact bypass: `_refuse_naked_short` exempted
    every `reduce_only` SELL outright, and `_working_sell_quantity` excluded
    `reduce_only` orders from `pending`, so two reduce-only sells each sized
    to the net long both passed and were jointly naked.

    Both deletions were required to close it, and neither alone is
    sufficient (execution-verified, C1 of Revision 2): dropping only the
    `_refuse_naked_short` exemption still passes this exact pair, because the
    first sell stays invisible in `pending`; dropping only the
    `_working_sell_quantity` exclusion still passes one oversized
    `reduce_only` sell, because the exemption's early return fires first.
    The marker comes off in the SAME commit as both deletions -- a reviewer
    ran this body against the both-deletions module and got
    `XPASS(strict)`, which fails the suite if left on.
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10), reduce_only=True)]
    guard = _guard(net=Decimal(10), open_orders=working)

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(_initialized(quantity=10, reduce_only=True))


# ---------------------------------------------------------------------------
# docs/plans/ORDER_LIST_BYPASS_2026-09-02.md §2/§6, Increment 1: `orders_open`
# is the wrong set -- INITIALIZED/SUBMITTED are invisible to it, but already
# committed. Widen the query to `cache.orders(...)` filtered to SELL and
# `not is_closed`.
# ---------------------------------------------------------------------------


def test_a_submitted_but_unaccepted_sell_counts_against_the_budget() -> None:
    """RED-14. The mechanism, not the symptom: a `SUBMITTED` SELL is absent
    from `orders_open()` (`Order.is_open_c()` excludes it) but is a real
    commitment `_working_sell_quantity` must count -- `leaves_qty` at
    `SUBMITTED` equals the full `quantity`, no fill has touched it yet.
    """
    working = [
        _FakeOrder(
            side=OrderSide.SELL,
            leaves=Decimal(10),
            is_closed=False,
            status=OrderStatus.SUBMITTED,
        ),
    ]

    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))


def test_a_closed_sell_does_not_count_against_the_budget() -> None:
    """RED-15, MUST PASS. The anti-false-refusal floor: `FILLED` and `DENIED`
    SELLs are terminal (`Order.is_closed_c()`) and contribute 0 to `pending`,
    so a plain SELL of the whole net long still passes with either sitting in
    the cache.
    """
    closed = [
        _FakeOrder(
            side=OrderSide.SELL,
            leaves=Decimal(10),
            is_closed=True,
            status=OrderStatus.FILLED,
        ),
        _FakeOrder(
            side=OrderSide.SELL,
            leaves=Decimal(10),
            is_closed=True,
            status=OrderStatus.DENIED,
        ),
    ]

    _guard(net=Decimal(10), open_orders=closed).on_order_event(_initialized(quantity=10))


def test_a_legitimate_full_exit_still_passes_under_the_widened_set() -> None:
    """RED-16, MUST PASS. Regression floor: net 100, no working orders, a
    plain SELL of 100 -- a full, legitimate exit -- still passes under the
    widened `not is_closed` query.
    """
    _guard(net=Decimal(100)).on_order_event(_initialized(quantity=100))


def test_two_plain_submit_order_sells_within_the_net_long_are_jointly_naked_unit() -> None:
    """RED-13's unit-level twin. `submit_order` publishes `OrderInitialized`
    BEFORE `cache.add_order` (`trading/strategy.pyx:855-859`), so at the
    moment the SECOND sell is screened the FIRST is already `SUBMITTED` in
    the cache -- invisible to `orders_open()`, visible to the widened query.
    Net 10, one working plain SELL of 10 already `SUBMITTED`, an incoming
    plain SELL of 10: jointly naked, no `reduce_only` and no order list.
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10), status=OrderStatus.SUBMITTED)]

    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))


def test_the_refusal_names_every_order_it_counted() -> None:
    """RED-23. §2.1's required mitigation: the message must name each
    contributor to `pending` by `client_order_id` and `status`, so an
    operator can tell "blocked by a stuck SUBMITTED order" from "the
    strategy genuinely oversold" without instrumenting the cache by hand.
    """
    working = [
        _FakeOrder(
            side=OrderSide.SELL,
            leaves=Decimal(6),
            status=OrderStatus.SUBMITTED,
            client_order_id=ClientOrderId("O-STUCK"),
        ),
        _FakeOrder(
            side=OrderSide.SELL,
            leaves=Decimal(4),
            status=OrderStatus.ACCEPTED,
            client_order_id=ClientOrderId("O-RESTING"),
        ),
    ]

    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=1))

    message = str(excinfo.value)
    assert "O-STUCK" in message
    assert "SUBMITTED" in message
    assert "O-RESTING" in message
    assert "ACCEPTED" in message


# ---------------------------------------------------------------------------
# docs/plans/ORDER_LIST_BYPASS_2026-09-02.md §3/§6, Increment 2: a cache-
# subordinate shim closes RED-12 (the order-list bypass). An approved SELL's
# `ClientOrderId` is recorded in the shim only AFTER both refusal rules pass
# (RED-24, the ordering constraint that makes the residual `1..k-1`, not
# `1..k`); the entry counts toward `pending` only while
# `cache.order(coid) is None` (RED-20/21) -- disjoint by construction from
# the cache-sourced sum, so no order is ever double-counted.
# ---------------------------------------------------------------------------


def test_a_single_member_order_list_within_the_net_long_passes() -> None:
    """RED-17. Net 10, one screening of a SELL of 10 -- no working orders, no
    prior approvals. §1's rejection made executable: a one-member "list" is
    not itself the attack shape and must not be refused merely for existing.
    """
    _guard(net=Decimal(10)).on_order_event(_initialized(quantity=10))


def test_a_three_member_order_list_refuses_on_the_third_leg() -> None:
    """RED-18. Net 20, three plain SELLs of 10 screened one at a time -- the
    exact shape `submit_order_list`'s publish loop produces, since none
    reaches `cache.add_order` before the next is screened (RED-12's
    integration-level pin). Legs 1-2 pass and accumulate in the shim; leg 3
    is refused, with the overage in the message: the shim ACCUMULATES, it
    does not ban the list outright (§1).
    """
    guard = _guard(net=Decimal(20))

    guard.on_order_event(_initialized(quantity=10, client_order_id=ClientOrderId("OL-1")))
    guard.on_order_event(_initialized(quantity=10, client_order_id=ClientOrderId("OL-2")))

    with pytest.raises(NakedShortRefusedError) as excinfo:
        guard.on_order_event(_initialized(quantity=10, client_order_id=ClientOrderId("OL-3")))

    message = str(excinfo.value)
    assert "naked short of 10" in message
    assert "OL-1" in message
    assert "OL-2" in message
    assert "awaiting cache" in message


def test_an_approved_sell_stops_being_counted_once_the_cache_holds_it() -> None:
    """RED-20. The disjointness invariant: approve a SELL of 10 (shim-only,
    since the fake cache starts empty -- the order-list shape), then have
    the cache pick the SAME order up as `SUBMITTED` (the normal-submit
    shape, `strategy.pyx` :944-981 vs :855-871). `pending` must read 10, not
    20 -- the cache-sourced and shim-sourced sums are disjoint on one
    predicate (`cache.order(coid) is None`), so the same order is never
    counted twice regardless of which sum currently sees it.
    """
    cache = _FakeCache()
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(10)), cache)
    approved_id = ClientOrderId("OL-1")

    guard.on_order_event(_initialized(quantity=10, client_order_id=approved_id))

    cache.add(
        _FakeOrder(
            side=OrderSide.SELL,
            leaves=Decimal(10),
            status=OrderStatus.SUBMITTED,
            client_order_id=approved_id,
        ),
    )

    with pytest.raises(NakedShortRefusedError) as excinfo:
        guard.on_order_event(_initialized(quantity=1, client_order_id=ClientOrderId("OL-2")))

    assert "naked short of 1" in str(excinfo.value)


def test_a_denied_order_list_member_stops_counting() -> None:
    """RED-21. G7: `Strategy._deny_order`/`_deny_order_list` call
    `cache.add_order` BEFORE applying `OrderDenied` (closed), for all three
    denial paths (duplicate list id, duplicate client order id,
    `MARKET_EXIT_IN_PROGRESS`). By the time the NEXT member is screened, a
    denied member sits in the cache as closed -- 0 from the cache-sourced
    sum (`is_closed`) AND its shim entry is inert
    (`cache.order(coid) is not None`), so it contributes 0 from either sum:
    the collapsed eviction table (§3).
    """
    cache = _FakeCache()
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(10)), cache)
    denied_id = ClientOrderId("OL-1")

    guard.on_order_event(_initialized(quantity=10, client_order_id=denied_id))

    cache.add(
        _FakeOrder(
            side=OrderSide.SELL,
            leaves=Decimal(10),
            is_closed=True,
            status=OrderStatus.DENIED,
            client_order_id=denied_id,
        ),
    )

    # Would be jointly naked (10 + 10 > 10) if either sum still counted the
    # denied member.
    guard.on_order_event(_initialized(quantity=10, client_order_id=ClientOrderId("OL-2")))


def test_a_refused_member_leaves_no_shim_entry() -> None:
    """RED-24. §3's record-after-approve constraint, made executable: the
    guard must record an approved SELL only AFTER both refusal rules pass,
    never before screening. Net 20, three plain SELLs of 10: legs 1-2 pass
    (shim now holds 20), leg 3 is refused (naked short of 10) and must NOT
    be recorded. A probe leg of 1 afterwards sees `pending == 20`, not `30`
    -- if leg 3 had wrongly been recorded the probe's overage would read
    `11`, not `1`. Get the ordering backwards and a refused order leaves a
    live entry that refuses everything after it forever.
    """
    guard = _guard(net=Decimal(20))

    guard.on_order_event(_initialized(quantity=10, client_order_id=ClientOrderId("OL-1")))
    guard.on_order_event(_initialized(quantity=10, client_order_id=ClientOrderId("OL-2")))

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(_initialized(quantity=10, client_order_id=ClientOrderId("OL-3")))

    with pytest.raises(NakedShortRefusedError) as excinfo:
        guard.on_order_event(_initialized(quantity=1, client_order_id=ClientOrderId("OL-4")))

    assert "naked short of 1" in str(excinfo.value)
