"""Contract: Nautilus risk caps are INERT until an ``AccountState`` is cached.

Pinned against **``nautilus-trader==1.231.0``** (asserted below). Every
assertion here drives the REAL Nautilus objects -- a real ``Cache``, a real
``MessageBus``, a real ``Portfolio``, a real ``RiskEngine``, and a real
``BinaryOption`` parsed from a captured Polymarket.us payload. Nothing is
mocked, and in particular ``Cache.account_for_venue`` is never stubbed: a
mock there would make this file pass while proving nothing, because the
account lookup IS the behaviour under test.

The hazard being pinned
-----------------------
``risk/engine.pyx:682-692`` (``_check_orders_risk_for_account``, defined at
``:666``)::

    cdef Account account = self._cache.account_for_venue(instrument.id.venue, account_id)

    if account is None:
        self._log.debug(...)
        return True  # TODO: Temporary early return until handling routing/multiple venues

    if account.is_margin_account:
        return True  # TODO: Determine risk controls for margin

Every notional and position cap Nautilus offers -- ``max_notional_per_order``
among them -- lives BELOW that early return (the ``NOTIONAL_EXCEEDS_MAX_PER_ORDER``
denial is at ``risk/engine.pyx:912-917``, reason string ``:915``). So a configured cap is **inert**
until a real ``AccountState`` is in the cache. A trading process that submits
an order before publishing an account is unprotected by every cap it appears
to have configured.

**This file asserts the hazardous behaviour on purpose. It does NOT endorse
it.** ``test_risk_caps_are_inert_without_account`` deliberately asserts that
an over-cap order is NOT denied, so that:

* the hazard cannot silently change under us on a Nautilus upgrade -- if
  upstream fixes the fail-open, that test goes RED and tells us the ordering
  constraint has changed; and
* the ordering constraint it implies is enforced by a test rather than by
  prose: **no increment that can submit an order may land before the
  increment that publishes an ``AccountState`` into the cache.**

A failure of the first test is therefore GOOD NEWS that needs re-reading, not
a broken test. Do not "fix" it by weakening the assertion, and never by
patching, monkeypatching, or vendoring Nautilus -- Nautilus is immutable here.

Non-vacuity
-----------
Tests two and three exist so the first cannot be read as "the engine denies
nothing in this rig":

* ``test_the_cap_denies_an_over_cap_order_once_an_account_exists`` -- same
  order, same cap, account published -> ``OrderDenied``. It fails if the
  account publication is removed, which is exactly the R-4 regression it
  guards.
* ``test_an_under_cap_order_is_accepted_with_the_same_account`` -- proves the
  denial above was on the CAP, not on account presence.

Scope guards
------------
No test here opens a socket, starts a node, or touches a venue. The engine,
cache, and message bus are built in-process; the instrument comes from the
committed raw-capture corpus on disk. Runs under
``scripts/ci/run_tests_no_egress.sh`` with no live network.

Note on values: ``MAX_NOTIONAL_PER_ORDER`` below is a TEST-LOCAL number chosen
only to sit between the two order sizes. It is not a production risk setting,
and this file assigns no value to either operator-reserved control.
"""

from __future__ import annotations

from dataclasses import dataclass
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
from nautilus_trader.model.enums import AccountType, OrderSide
from nautilus_trader.model.events import AccountState, OrderDenied
from nautilus_trader.model.identifiers import AccountId, StrategyId, TraderId
from nautilus_trader.model.objects import AccountBalance, Money, Price, Quantity
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.risk.engine import RiskEngine

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION = "1.231.0"

TRADER_ID = TraderId("BREEZY-RISK-ORDERING-001")
STRATEGY_ID = StrategyId("S-RISK-ORDERING")

#: Test-local cap, in the instrument's quote currency. Sits strictly between
#: the under-cap and over-cap notionals below. Typed `int` because
#: `RiskEngineConfig.max_notional_per_order` is declared `dict[str, int]`
#: (`config/common.py`) even though `_initialize_risk_checks` converts with
#: `Decimal(value)` -- passing a string type-checks as a lie.
MAX_NOTIONAL_PER_ORDER = 10

#: Limit price used by every order here. Well inside the [0.01, 0.99] band a
#: binary option quotes in, and aligned to the instrument's 0.01 increment.
LIMIT_PRICE = 0.50

OVER_CAP_QUANTITY = 100  # 100 * 0.50 = 50.00 -> far over the cap
UNDER_CAP_QUANTITY = 10  # 10 * 0.50 = 5.00 -> comfortably under it

#: Free balance the published account carries. Large enough that the balance
#: check (`risk/engine.pyx:949-954`) can never be the reason for a denial, so
#: a denial here can only be the notional cap.
ACCOUNT_BALANCE = 1_000_000


def test_pinned_nautilus_version() -> None:
    """Every `path:line` in this module's docstring was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION, (
        f"These pins were verified against nautilus-trader "
        f"{PINNED_NAUTILUS_VERSION}, running against "
        f"{nautilus_trader.__version__}. Re-read `risk/engine.pyx` around the "
        f"`account is None` early return before updating this constant."
    )


def _instrument() -> BinaryOption:
    """A real captured Polymarket.us market, never a fabricated instrument.

    The venue on its `InstrumentId` is what `account_for_venue` is keyed on,
    so it has to be the real one.
    """
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


def _account_state(instrument: BinaryOption) -> AccountState:
    """A CASH account whose issuer IS the instrument's venue.

    Both halves matter. The issuer must match the venue or
    `Cache._cache_venue_account_id` indexes it under a different venue and
    `account_for_venue` still returns `None` -- the test would then "pass"
    step one for the wrong reason. And the type must be CASH: a MARGIN
    account hits the second early return at `risk/engine.pyx:691-692` and is
    just as unprotected.
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
    orders: OrderFactory
    instrument: BinaryOption
    denied: list[OrderDenied]
    forwarded: list[SubmitOrder]

    def submit(self, quantity: int) -> None:
        order = self.orders.limit(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,  # Breezy never shorts (`allow_short=False`)
            quantity=Quantity(quantity, self.instrument.size_precision),
            price=Price(LIMIT_PRICE, self.instrument.price_precision),
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


def _rig(*, with_account: bool) -> _Rig:
    """Build the engine in-process. No node, no clients, no sockets."""
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

    # Stand in for the ExecutionEngine. `_deny_order` sends the `OrderDenied`
    # to `ExecEngine.process` (`risk/engine.pyx:1123`); a passing order is
    # forwarded to `ExecEngine.execute` (`:1186`). Recording both is what lets
    # a test distinguish "denied" from "not denied" rather than inferring one
    # from the absence of the other.
    denied: list[OrderDenied] = []
    forwarded: list[SubmitOrder] = []
    msgbus.register(endpoint="ExecEngine.process", handler=denied.append)
    msgbus.register(endpoint="ExecEngine.execute", handler=forwarded.append)

    return _Rig(
        engine=engine,
        orders=OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=clock),
        instrument=instrument,
        denied=denied,
        forwarded=forwarded,
    )


def test_the_cap_is_actually_configured() -> None:
    """Guard against a vacuous rig: the cap must really be registered.

    Without this, a typo in the `max_notional_per_order` key would make
    `test_risk_caps_are_inert_without_account` pass for a reason that has
    nothing to do with the missing account.
    """
    rig = _rig(with_account=False)

    assert rig.engine.max_notional_per_order(rig.instrument.id) == MAX_NOTIONAL_PER_ORDER
    assert (
        rig.instrument.notional_value(
            Quantity(OVER_CAP_QUANTITY, rig.instrument.size_precision),
            Price(LIMIT_PRICE, rig.instrument.price_precision),
        ).as_decimal()
        > MAX_NOTIONAL_PER_ORDER
    )
    assert (
        rig.instrument.notional_value(
            Quantity(UNDER_CAP_QUANTITY, rig.instrument.size_precision),
            Price(LIMIT_PRICE, rig.instrument.price_precision),
        ).as_decimal()
        < MAX_NOTIONAL_PER_ORDER
    )


def test_risk_caps_are_inert_without_account() -> None:
    """PINS A KNOWN UPSTREAM HAZARD -- it does not endorse it.

    With no `AccountState` in the cache, `account_for_venue` returns `None`,
    `_check_orders_risk_for_account` takes the `return True` at
    `risk/engine.pyx:684-689`, and the configured `max_notional_per_order` is
    never consulted. The over-cap order is forwarded to execution.

    **If this test goes RED, Nautilus changed and that is important**: the
    ordering constraint it encodes (no order-submitting increment before an
    account is published) may no longer be load-bearing. Re-read
    `risk/engine.pyx` and this file's docstring; do not weaken the assertion.
    """
    rig = _rig(with_account=False)

    rig.submit(OVER_CAP_QUANTITY)

    assert rig.denied == [], (
        "The account fail-open at `risk/engine.pyx:684-689` appears to be "
        "gone: an over-cap order was denied with no account in the cache. "
        "Re-read the upstream source before changing this test."
    )
    assert len(rig.forwarded) == 1
    assert rig.forwarded[0].order.quantity == Quantity(
        OVER_CAP_QUANTITY,
        rig.instrument.size_precision,
    )


def test_the_cap_denies_an_over_cap_order_once_an_account_exists() -> None:
    """The same order, the same cap, and an `AccountState` in cache -> denied.

    Non-vacuity for the test above: remove the `cache.add_account(...)` in
    `_rig` and this goes RED, which is precisely the regression that would
    re-open the hazard in a live process.
    """
    rig = _rig(with_account=True)

    rig.submit(OVER_CAP_QUANTITY)

    assert rig.forwarded == []
    assert len(rig.denied) == 1
    event = rig.denied[0]
    assert isinstance(event, OrderDenied)
    assert "NOTIONAL_EXCEEDS_MAX_PER_ORDER" in event.reason


def test_an_under_cap_order_is_accepted_with_the_same_account() -> None:
    """Proves the denial above was on the CAP, not on account presence.

    Same rig, same account, an order whose notional sits under the cap: it is
    forwarded to execution untouched.
    """
    rig = _rig(with_account=True)

    rig.submit(UNDER_CAP_QUANTITY)

    assert rig.denied == []
    assert len(rig.forwarded) == 1
    assert rig.forwarded[0].order.quantity == Quantity(
        UNDER_CAP_QUANTITY,
        rig.instrument.size_precision,
    )
