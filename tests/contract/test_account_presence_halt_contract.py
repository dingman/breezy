"""Contract: no cached account => trading HALTS, before the fail-open can matter.

EXEC SPINE R-7-PRE (``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md``). Companion
to ``tests/contract/test_risk_engine_ordering_enforcement.py``, which PINS the
upstream hazard; this file pins the MITIGATION.

The hazard, quoted from the installed source
--------------------------------------------
``$NT/risk/engine.pyx`` (``_check_orders_risk_for_account``)::

    cdef Account account = self._cache.account_for_venue(instrument.id.venue, account_id)

    if account is None:
        self._log.debug(...)
        return True  # TODO: Temporary early return until handling routing/multiple venues

``True`` means **order allowed**. Every notional and balance cap Nautilus
offers lives BELOW that early return, so while ``account_for_venue(...)`` is
``None`` a configured ``max_notional_per_order`` is inert and the order is
forwarded to execution unopposed.

Today R-4's blanket standing refusal in
``PolymarketUSExecutionClient._submit_order`` masks that entirely: nothing can
be sent, so nothing can be sent wrongly. R-7 gives ``_submit_order`` a real
body and removes the mask, and at that instant an account-registration race --
a slow ``/v1/account/balances``, a reconnect, a cache flush -- silently allows
an order through an immutable framework path. Nautilus is immutable, so the
fail-open cannot be patched: the denial has to come from somewhere the
fail-open does not govern.

Why ``TradingState.HALTED`` and not a second ``_submit_order`` precondition
--------------------------------------------------------------------------
Two denial origins were admissible (plan, §R-7-PRE). ``TradingState.HALTED``
was chosen for three reasons, in order of weight:

1. **It is native.** ``RiskEngine.set_trading_state`` and ``TradingState`` are
   Nautilus's own; Breezy authors no denial machinery, only the one condition
   under which the native state is entered. The null hypothesis holds.
2. **It survives R-7 structurally, not by memory.** The exec client's
   ``_submit_order`` precondition survives only for as long as R-7 chooses to
   keep writing it; the halt lives in ``breezy.runtime.account_presence_halt``
   and is wired in ``trade_cli._run_node``, which R-7 has no reason to touch.
   ``test_the_trade_cli_installs_the_halt_after_build`` pins that wiring so it
   cannot be dropped silently.
3. **It denies before the execution client is reached at all.** The order
   never leaves the risk engine, so the denial is independent of whatever
   body ``_submit_order`` acquires -- including a body that sends.

Where the denial actually happens, stated precisely
---------------------------------------------------
The plan's §R-7-PRE says the denial must originate "upstream of
``_check_orders_risk_for_account``" and cites ``TradingState.HALTED`` as such
an origin. On ``nautilus-trader==1.231.0`` that is imprecise in call order and
exact in effect, and the difference is worth writing down:

* For a ``SubmitOrder`` the HALTED check is in ``_execution_gateway``
  (``risk/engine.pyx``, ``reason=f"TradingState.HALTED"``), which
  ``_handle_submit_order`` reaches AFTER ``_check_orders_risk``. The
  ``:559`` the plan cites is the ``_handle_modify_order`` path, not this one.
* It is nonetheless *dominant* over the fail-open: the fail-open can only
  return ``True`` ("no cap opinion"), and a ``True`` from it does not reach
  execution -- ``_execution_gateway`` denies regardless. So no order can be
  sent on the strength of the fail-open.

The assertions below are therefore written over the denial REASON, which is
what makes the origin provable rather than inferred.

Non-vacuity, mechanised
-----------------------
``test_without_the_halt_the_same_order_is_allowed`` runs the identical rig with
the guard NOT installed and asserts the order is FORWARDED. If that ever goes
RED, something else is denying and this file is measuring an accident rather
than the mitigation -- do not "fix" it, re-read the upstream source.

Scope guards
------------
Nothing here opens a socket, starts a node, or touches a venue. A real
``Cache``, ``MessageBus``, ``Portfolio``, ``RiskEngine`` and a real
``BinaryOption`` parsed from the committed raw-capture corpus are built
in-process. ``Cache.account_for_venue`` is never stubbed: the account lookup
IS the behaviour under test. No test here assigns a value to either
operator-reserved control; ``MAX_NOTIONAL_PER_ORDER`` is a test-local number
chosen only to sit between the two order sizes.
"""

from __future__ import annotations

import ast
import io
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import nautilus_trader
import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.config import RiskEngineConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import AccountType, OrderSide, TradingState
from nautilus_trader.model.events import AccountState, OrderDenied
from nautilus_trader.model.identifiers import AccountId, StrategyId, TraderId
from nautilus_trader.model.objects import AccountBalance, Money, Price, Quantity
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.risk.engine import RiskEngine

from breezy.adapters.polymarket_us.exec_fault import (
    clear_fatal_exec_fault,
    fatal_exec_fault,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.runtime.account_presence_halt import (
    AccountPresenceHalt,
    install_account_presence_halt,
)
from breezy.runtime.trade_cli import _account_halt_reporter
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION = "1.231.0"

REPO_ROOT = Path(__file__).resolve().parents[2]
HALT_MODULE_PATH = REPO_ROOT / "src" / "breezy" / "runtime" / "account_presence_halt.py"
TRADE_CLI_PATH = REPO_ROOT / "src" / "breezy" / "runtime" / "trade_cli.py"

TRADER_ID = TraderId("BREEZY-ACCOUNT-HALT-001")
STRATEGY_ID = StrategyId("S-ACCOUNT-HALT")

#: Test-local cap, in the instrument's quote currency. Typed `int` because
#: `RiskEngineConfig.max_notional_per_order` is declared `dict[str, int]`.
MAX_NOTIONAL_PER_ORDER = 10

LIMIT_PRICE = 0.50
OVER_CAP_QUANTITY = 100  # 100 * 0.50 = 50.00 -> far over the cap
UNDER_CAP_QUANTITY = 10  # 10 * 0.50 = 5.00 -> comfortably under it

#: Large enough that the balance check can never be the reason for a denial.
ACCOUNT_BALANCE = 1_000_000

#: The exact reason string `_execution_gateway` denies a `SubmitOrder` with
#: while the engine is halted (`$NT/risk/engine.pyx`, `reason=f"TradingState.HALTED"`).
HALTED_REASON = "TradingState.HALTED"

#: The reason the NOTIONAL cap denies with -- i.e. the origin this mitigation
#: must NOT be confused with.
NOTIONAL_REASON = "NOTIONAL_EXCEEDS_MAX_PER_ORDER"


def test_pinned_nautilus_version() -> None:
    """Every `path:line` and reason string in this module was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION, (
        f"These pins were verified against nautilus-trader "
        f"{PINNED_NAUTILUS_VERSION}, running against "
        f"{nautilus_trader.__version__}. Re-read `risk/engine.pyx` around the "
        f"`account is None` early return and the `_execution_gateway` HALTED "
        f"check before updating this constant."
    )


def _instrument() -> BinaryOption:
    """A real captured Polymarket.us market, never a fabricated instrument."""
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


def _account_state(instrument: BinaryOption) -> AccountState:
    """A CASH account whose issuer IS the instrument's venue.

    The issuer must match the venue or `Cache._cache_venue_account_id` indexes
    it under a different venue and `account_for_venue` still returns `None` --
    the "account present" tests would then pass for the wrong reason.
    """
    currency = instrument.quote_currency
    return AccountState(
        account_id=AccountId(f"{instrument.id.venue}-001"),
        account_type=AccountType.CASH,
        base_currency=currency,
        reported=True,
        balances=[
            AccountBalance(
                Money(ACCOUNT_BALANCE, currency),
                Money(0, currency),
                Money(ACCOUNT_BALANCE, currency),
            ),
        ],
        margins=[],
        info={},
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class _Rig:
    """An in-process risk engine plus the two execution endpoints it talks to."""

    engine: RiskEngine
    msgbus: MessageBus
    cache: Cache
    orders: OrderFactory
    instrument: BinaryOption
    denied: list[OrderDenied]
    forwarded: list[SubmitOrder]
    halts: list[str]

    def submit(self, quantity: int) -> None:
        """Submit exactly the way `Strategy.submit_order` does.

        `Strategy.submit_order` publishes the order's `OrderInitialized` to
        `events.order.<strategy_id>` as its FIRST action -- before
        `cache.add_order` and before the `SubmitOrder` command reaches the
        `RiskEngine` (`$NT/trading/strategy.pyx`). Reproducing that ORDER is
        the whole point: the halt has to be in force by the time the command
        arrives, and a rig that skipped the publish would prove nothing about
        the live sequence.
        """
        order = self.orders.limit(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,  # Breezy never shorts (`allow_short=False`)
            quantity=Quantity(quantity, self.instrument.size_precision),
            price=Price(LIMIT_PRICE, self.instrument.price_precision),
        )
        self.msgbus.publish(
            topic=f"events.order.{STRATEGY_ID.value}",
            msg=order.init_event,
        )
        self.engine.execute(
            SubmitOrder(
                trader_id=TRADER_ID,
                strategy_id=STRATEGY_ID,
                order=order,
                command_id=UUID4(),
                ts_init=0,
            ),
        )


def _rig(*, with_account: bool, with_halt: bool = True) -> _Rig:
    """Build the engine in-process. No node, no clients, no sockets.

    `with_halt=False` is the NON-VACUITY control: the identical rig with the
    mitigation absent. It is not a convenience switch -- it is what proves the
    fail-open is real and that this file measures the mitigation.
    """
    clock = TestClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))

    instrument = _instrument()
    cache.add_instrument(instrument)

    if with_account:
        cache.add_account(AccountFactory.create(_account_state(instrument)))

    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)

    engine = RiskEngine(
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        config=RiskEngineConfig(
            max_notional_per_order={str(instrument.id): MAX_NOTIONAL_PER_ORDER},
        ),
    )

    halts: list[str] = []
    if with_halt:
        install_account_presence_halt(msgbus, cache, engine, on_halt=halts.append)

    # Stand in for the ExecutionEngine: `_deny_order` sends `OrderDenied` to
    # `ExecEngine.process`; a passing order is forwarded to
    # `ExecEngine.execute`. Recording both is what lets a test distinguish
    # "denied" from "not denied" rather than inferring one from the other.
    denied: list[OrderDenied] = []
    forwarded: list[SubmitOrder] = []
    msgbus.register(endpoint="ExecEngine.process", handler=denied.append)
    msgbus.register(endpoint="ExecEngine.execute", handler=forwarded.append)

    return _Rig(
        engine=engine,
        msgbus=msgbus,
        cache=cache,
        orders=OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=clock),
        instrument=instrument,
        denied=denied,
        forwarded=forwarded,
        halts=halts,
    )


# -- the mitigation ---------------------------------------------------------


def test_an_order_with_no_cached_account_is_denied() -> None:
    """R-7-PRE's whole claim, on an order the notional cap would NOT deny.

    `UNDER_CAP_QUANTITY` is deliberate: the cap has no opinion on this order
    even when it IS consulted, so the denial cannot be the cap misread as the
    mitigation.
    """
    rig = _rig(with_account=False)
    assert rig.cache.account_for_venue(rig.instrument.id.venue) is None

    rig.submit(UNDER_CAP_QUANTITY)

    assert rig.forwarded == []
    assert len(rig.denied) == 1
    assert isinstance(rig.denied[0], OrderDenied)


def test_the_denial_reason_names_the_halt_and_not_the_notional_cap() -> None:
    """The ORIGIN, proven rather than inferred.

    An over-cap order this time: with no account the cap is inert
    (`_check_orders_risk_for_account` returns `True`), so if the reason were
    the cap's, the fail-open would not be what this repo says it is.
    """
    rig = _rig(with_account=False)

    rig.submit(OVER_CAP_QUANTITY)

    assert len(rig.denied) == 1
    reason = rig.denied[0].reason
    assert reason == HALTED_REASON, reason
    assert NOTIONAL_REASON not in reason
    assert rig.engine.trading_state == TradingState.HALTED


def test_the_halt_is_reported_to_the_operator_callback() -> None:
    """A halt that nobody is told about is a trading process that stops silently."""
    rig = _rig(with_account=False)

    rig.submit(UNDER_CAP_QUANTITY)

    assert len(rig.halts) == 1
    assert "account" in rig.halts[0].lower()
    assert str(rig.instrument.id.venue) in rig.halts[0]


def test_a_broken_reporter_cannot_swallow_the_halt() -> None:
    """The state change is applied BEFORE the report, and the report is contained.

    Mirrors R-6a's `install_live_order_guard` contract in the one way that
    matters here and inverts it in the other: a reporter that raises must not
    prevent the denial, and -- unlike the order guard, whose refusal IS the
    exception -- there is nothing to re-raise, so the exception is logged and
    dropped.
    """

    def _broken(_reason: str) -> None:
        raise RuntimeError("the reporter is broken")

    clock = TestClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    instrument = _instrument()
    cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    engine = RiskEngine(portfolio=portfolio, msgbus=msgbus, cache=cache, clock=clock)
    install_account_presence_halt(msgbus, cache, engine, on_halt=_broken)

    orders = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=clock)
    order = orders.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(UNDER_CAP_QUANTITY, instrument.size_precision),
        price=Price(LIMIT_PRICE, instrument.price_precision),
    )
    msgbus.publish(topic=f"events.order.{STRATEGY_ID.value}", msg=order.init_event)

    assert engine.trading_state == TradingState.HALTED


# -- non-vacuity ------------------------------------------------------------


def test_without_the_halt_the_same_order_is_allowed() -> None:
    """THE NON-VACUITY CONTROL. Remove the mitigation; the order goes through.

    Identical rig, identical order, guard not installed. The risk engine
    forwards it to execution because `_check_orders_risk_for_account` returned
    `True` on a `None` account.

    If this ever goes RED, the fail-open is not what `risk/engine.pyx` says it
    is, or something else is denying -- either way the design assumption behind
    R-7-PRE has changed. Re-read the upstream source; do not weaken this.
    """
    rig = _rig(with_account=False, with_halt=False)

    rig.submit(UNDER_CAP_QUANTITY)

    assert rig.denied == [], [event.reason for event in rig.denied]
    assert len(rig.forwarded) == 1
    assert rig.engine.trading_state == TradingState.ACTIVE


# -- the mitigation is account-conditional, not a second blanket refusal -----


def test_with_an_account_the_order_reaches_the_ordinary_risk_checks() -> None:
    """Account present: the halt stays out of the way and the CAP denies.

    Pins that R-7-PRE is conditional on the missing account. A mitigation that
    denied unconditionally would pass every test above and be useless.
    """
    rig = _rig(with_account=True)

    rig.submit(OVER_CAP_QUANTITY)

    assert rig.forwarded == []
    assert len(rig.denied) == 1
    reason = rig.denied[0].reason
    assert NOTIONAL_REASON in reason, reason
    assert HALTED_REASON not in reason
    assert rig.engine.trading_state == TradingState.ACTIVE
    assert rig.halts == []


def test_with_an_account_an_under_cap_order_is_forwarded_untouched() -> None:
    """The complement: the guard denies nothing when the account is there."""
    rig = _rig(with_account=True)

    rig.submit(UNDER_CAP_QUANTITY)

    assert rig.denied == []
    assert len(rig.forwarded) == 1
    assert rig.engine.trading_state == TradingState.ACTIVE
    assert rig.halts == []


# -- the halt does not un-latch ---------------------------------------------


def test_the_halt_does_not_clear_when_the_account_later_appears() -> None:
    """Fail-safe, matching R-4's never-self-clearing refusal latch.

    An account that appears after the halt says the race resolved; it does not
    say the orders formed during the race were sound. Returning to ACTIVE is an
    operator decision (`RiskEngine.set_trading_state`), never this guard's.
    """
    rig = _rig(with_account=False)
    rig.submit(UNDER_CAP_QUANTITY)
    assert rig.engine.trading_state == TradingState.HALTED

    rig.cache.add_account(AccountFactory.create(_account_state(rig.instrument)))
    rig.submit(UNDER_CAP_QUANTITY)

    assert rig.engine.trading_state == TradingState.HALTED
    assert rig.forwarded == []
    assert [event.reason for event in rig.denied] == [HALTED_REASON, HALTED_REASON]


# -- the wiring R-7 must not remove -----------------------------------------


def _dotted(node: ast.expr) -> str | None:
    """`node.kernel.msgbus` -> "node.kernel.msgbus"; anything else -> None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def test_the_trade_cli_installs_the_halt_after_build() -> None:
    """The pin that makes the choice survive R-7.

    R-7 rewrites `PolymarketUSExecutionClient._submit_order`. It has no reason
    to touch `trade_cli._run_node`, and this assertion is what turns "no
    reason" into "cannot, without a RED test".
    """
    tree = ast.parse(TRADE_CLI_PATH.read_text(encoding="utf-8"))
    run_node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_node"
    )
    calls = [inner for inner in ast.walk(run_node) if isinstance(inner, ast.Call)]
    callees = {_dotted(inner.func): inner.lineno for inner in calls}

    assert "node.build" in callees
    assert "install_account_presence_halt" in callees
    # By SOURCE LINE, not by walk order: `ast.walk` is breadth-first, so its
    # ordering says nothing about which statement runs first. The kernel's
    # `risk_engine` does not exist until `build()` has run.
    assert callees["install_account_presence_halt"] > callees["node.build"]


def test_the_trade_cli_halt_reporter_latches_a_fatal_exec_fault() -> None:
    """A halted node must not end the run in ``EXIT_OK``.

    ``_exit_code_for_completed_run`` reads the process-scoped exec-fault latch
    FIRST; without this the process would stop cleanly, report success to the
    supervisor, and leave the operator to discover from a log that every order
    had been denied since minute four.
    """
    clear_fatal_exec_fault()
    try:
        stderr = io.StringIO()
        _account_halt_reporter(stderr)("no account is cached for venue TEST")

        fault = fatal_exec_fault()
        assert fault is not None
        assert fault.reason == "no account is cached for venue TEST"
        assert "FATAL account-presence halt" in stderr.getvalue()
    finally:
        clear_fatal_exec_fault()


def test_the_halt_module_names_no_venue_and_owns_no_transport() -> None:
    """PORTABLE, as the plan labels R-7-PRE: Kalshi reuses this unchanged.

    The venue is read off the ORDER's own `InstrumentId` -- the same key
    `account_for_venue` is indexed by -- so the guard never needs to be told
    which venue it is protecting.
    """
    source = HALT_MODULE_PATH.read_text(encoding="utf-8")
    lowered = source.lower()
    for banned in ("polymarket", "kalshi", "httpx", "requests", "socket", "aiohttp"):
        assert banned not in lowered, banned
    assert "adapters" not in HALT_MODULE_PATH.parts


def test_the_guard_ignores_every_order_event_that_is_not_an_initialization() -> None:
    """Type-EXACT screening, the same rule `BacktestOrderGuard` uses.

    `events.order.*` carries the whole lifecycle (accepted, filled, denied).
    A guard that halted on any of them would halt on its OWN `OrderDenied`.
    """
    rig = _rig(with_account=False)
    rig.submit(UNDER_CAP_QUANTITY)
    denials_after_first_submit = len(rig.denied)

    # Republish the denial the engine itself produced, on the same topic.
    rig.msgbus.publish(
        topic=f"events.order.{STRATEGY_ID.value}",
        msg=rig.denied[0],
    )

    assert len(rig.denied) == denials_after_first_submit
    assert len(rig.halts) == 1


def test_the_guard_class_is_importable_and_exported() -> None:
    """The installer returns the guard so a caller (and a test) can hold it."""
    rig_cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    clock = TestClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    portfolio = Portfolio(msgbus=msgbus, cache=rig_cache, clock=clock)
    engine = RiskEngine(portfolio=portfolio, msgbus=msgbus, cache=rig_cache, clock=clock)

    guard = install_account_presence_halt(msgbus, rig_cache, engine, on_halt=lambda _r: None)

    assert isinstance(guard, AccountPresenceHalt)
