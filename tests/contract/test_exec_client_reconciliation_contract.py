"""Contract: the R-4 client reconciles a flat account through the REAL engine.

Pinned against ``nautilus-trader==1.231.0`` (asserted below). Nothing here is
mocked except the venue read, which is injected: the engine, message bus,
cache, portfolio and instrument are real, and the entry point is Nautilus's
own ``LiveExecutionEngine.reconcile_execution_state`` -- the coroutine a
``TradingNode`` awaits before it will start.

WHY THIS FILE EXISTS SEPARATELY FROM THE UNIT SUITE

``EXEC_SPINE`` R-4 is "done when the node starts, reconciles a flat account,
and refuses every order". The unit suite asserts the client's own behaviour;
this one asserts the property that behaviour exists FOR -- that the native
reconciliation path accepts it -- because the failure mode it defends against
is invisible from inside the client:

    ``live/execution_client.py:512-514`` catches every exception and returns
    ``None``; ``live/execution_engine.py:1723-1729`` turns a ``None`` into
    ``results.append(False)`` and one WARNING line. A node whose
    reconciliation returns ``False`` does not start, and nothing says why.

``test_a_failed_venue_read_still_reconciles`` is the measurement of that, and
``test_a_client_returning_none_fails_reconciliation`` is its non-vacuity
half: the same engine, the same call, a client that returns ``None``, and
reconciliation goes ``False``. Without the second, the first would pass
against an engine that could not fail at all.

This file assigns no value to either operator-reserved control, submits no
order, and opens no socket. Every order it does hand to the engine is denied.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import nautilus_trader
import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.live.config import LiveExecEngineConfig
from nautilus_trader.live.execution_engine import LiveExecutionEngine
from nautilus_trader.model.identifiers import ClientId, TraderId
from nautilus_trader.model.objects import Money
from nautilus_trader.portfolio.portfolio import Portfolio

from breezy.adapters.polymarket_us.exec.client import (
    DurableFillRecord,
    PolymarketUSExecutionClient,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.fees import polymarket_us_fee
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.unit.polymarket_us_exec_shapes import (
    TS_EVENT_TEXT,
    build_instrument,
    build_position,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping
    from pathlib import Path

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION: Final[str] = "1.231.0"

TRADER_ID: Final[TraderId] = TraderId("BREEZY-R4-RECON-001")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
BALANCE: Final[Decimal] = Decimal("125.50")


def test_pinned_nautilus_version() -> None:
    """Every ``path:line`` in this module's docstring was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION


async def _flat_account_read(path: str) -> Mapping[str, Any]:
    """The venue, flat and orderless: a balance and no positions."""
    if path == ACCOUNT_BALANCES_PATH:
        return {
            "balances": [
                {
                    "currency": "USD",
                    "currentBalance": BALANCE,
                    "buyingPower": BALANCE,
                    "lastUpdated": TS_EVENT_TEXT,
                },
            ],
        }
    if path == PORTFOLIO_POSITIONS_PATH:
        return {"positions": {}}
    raise AssertionError(f"unexpected private read of {path!r}")


def _position_read(slug: str, *, bought: str = "4", sold: str = "0") -> Any:
    """A venue holding one LONG of 4 in ``slug``, with the cost basis dialled."""
    position = build_position(slug)
    position["qtyBought"] = bought
    position["qtySold"] = sold

    async def _read(path: str) -> Mapping[str, Any]:
        if path == PORTFOLIO_POSITIONS_PATH:
            return {"positions": {slug: position}}
        return await _flat_account_read(path)

    return _read


async def _broken_read(path: str) -> Mapping[str, Any]:
    """A venue that answers the balance and then fails the position read."""
    if path == ACCOUNT_BALANCES_PATH:
        return await _flat_account_read(path)
    raise RuntimeError("the venue position read failed")


#: The engine configuration every test here builds. Held as a module constant
#: so the settlement pin below reads the SAME object the engine is built from.
#:
#: ``position_check_interval_secs=None`` is a SAFETY condition, not tidiness --
#: see ``test_the_settlement_landmine_stays_disarmed_only_while_the_position_
#: check_is_off``.
ENGINE_CONFIG: Final[LiveExecEngineConfig] = LiveExecEngineConfig(
    # R-2's pins: the in-flight and open/position background checks are
    # disabled so this contract does not arm timers it never awaits.
    inflight_check_interval_ms=0,
    open_check_interval_secs=None,
    position_check_interval_secs=None,
)


def test_the_settlement_landmine_stays_disarmed_only_while_the_position_check_is_off() -> None:
    """The condition Decision B is accepted UNDER, pinned where it is relied on.

    This client never forwards a FLAT position report: on a settled binary
    ``calculate_reconciliation_price`` (``live/reconciliation.py:549``) returns
    ``avg_px_open`` itself for a long-to-flat target, so the close books at the
    OPEN price and every settled trade realizes exactly zero. R-9 must close a
    settled market on the NWS print, through an order/fill report -- the
    settlement price cannot be injected through a position report at all.

    The client's refusal is NOT sufficient on its own. With
    ``position_check_interval_secs`` set, ``_create_flat_position_report``
    (``live/execution_engine.py:1022``, called at ``:967-975``) SYNTHESISES the
    very FLAT report this client declines to send, from config alone and with
    no venue involvement. So the disarm is a two-part condition and both parts
    are pinned: the client (unit suite) and the engine (here).
    """
    assert ENGINE_CONFIG.position_check_interval_secs is None
    loop = asyncio.new_event_loop()
    try:
        engine, _, _, _, _ = _build_engine(loop)
        assert engine.position_check_interval_secs is None
    finally:
        loop.close()


def _build_engine(
    loop: asyncio.AbstractEventLoop,
) -> tuple[LiveExecutionEngine, Cache, MessageBus, LiveClock, Portfolio]:
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    cache.add_instrument(build_instrument())
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    engine = LiveExecutionEngine(
        loop=loop,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        config=ENGINE_CONFIG,
    )
    return engine, cache, msgbus, clock, portfolio


def _build_client(
    loop: asyncio.AbstractEventLoop,
    tmp_path: Path,
    *,
    read: Any,
    cache: Cache,
    msgbus: MessageBus,
    clock: LiveClock,
) -> PolymarketUSExecutionClient:
    provider = InstrumentProvider()
    provider.add(build_instrument())
    return PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=read,
        state_store_opener=lambda: SqliteStateStore(tmp_path / "exec_state.db"),
        account_number="001",
        instrument_wait_timeout_s=2.0,
        account_registration_timeout_s=2.0,
    )


@pytest.mark.asyncio
async def test_the_client_reconciles_a_flat_account_through_the_real_engine(
    tmp_path: Path,
) -> None:
    """R-4's done-when, measured on Nautilus's own start-up coroutine.

    ``reconcile_execution_state`` is what a ``TradingNode`` awaits before it
    runs. `True` here IS "the node starts".
    """
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock, _portfolio = _build_engine(loop)
    client = _build_client(
        loop,
        tmp_path,
        read=_flat_account_read,
        cache=cache,
        msgbus=msgbus,
        clock=clock,
    )
    engine.register_client(client)
    await client._connect()

    account = cache.account_for_venue(POLYMARKET_US_VENUE)
    assert account is not None, "the risk engine stays INERT without this"
    assert account.balance_total(account.base_currency) == Money(
        BALANCE,
        account.base_currency,
    )

    assert await engine.reconcile_execution_state(timeout_secs=5.0) is True
    assert client.trading_refusals == ()
    assert cache.positions_open() == []
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_failed_venue_read_still_reconciles_and_latches_a_refusal(
    tmp_path: Path,
) -> None:
    """The trap, defused end to end.

    The native client would have returned ``None`` here and the node would
    never have started. Instead reconciliation succeeds against an honest,
    empty mass status, and the reason it is empty is on the record.
    """
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock, _portfolio = _build_engine(loop)
    client = _build_client(
        loop,
        tmp_path,
        read=_broken_read,
        cache=cache,
        msgbus=msgbus,
        clock=clock,
    )
    engine.register_client(client)
    await client._connect()

    assert await engine.reconcile_execution_state(timeout_secs=5.0) is True
    assert client.trading_refusals != ()
    await client._disconnect()


@pytest.mark.asyncio
async def test_an_unattributable_long_reaches_the_portfolio_as_real_exposure(
    tmp_path: Path,
) -> None:
    """Why every LONG is forwarded, measured on the real engine.

    A position EXCLUDED from the mass status reconciles to a portfolio
    ``net_position`` of ZERO, and every Breezy cap that sizes off
    ``net_position`` would then buy into a bucket the account already holds.
    Forwarded, the same position is visible -- and the client's latched refusal
    is what stops Breezy trading it.

    The module docstring's central claim -- "Breezy's own caps size off
    ``Strategy.portfolio.net_position``" -- is asserted directly here, on the
    SAME real ``Portfolio`` the engine reconciles into, rather than left as
    prose no test actually exercises.
    """
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock, portfolio = _build_engine(loop)
    instrument = build_instrument()
    client = _build_client(
        loop,
        tmp_path,
        read=_position_read(str(instrument.symbol.value)),
        cache=cache,
        msgbus=msgbus,
        clock=clock,
    )
    engine.register_client(client)
    await client._connect()

    assert await engine.reconcile_execution_state(timeout_secs=5.0) is True

    positions = cache.positions_open(instrument_id=instrument.id)
    assert len(positions) == 1, "an excluded position reads as ZERO exposure"
    assert positions[0].quantity == instrument.make_qty(4)
    assert client.trading_refusals != (), "visible, and untradeable"
    assert portfolio.net_position(instrument.id) == Decimal(4), (
        "the docstring's central claim: caps size off THIS, not off the mass status directly"
    )
    await client._disconnect()


@pytest.mark.asyncio
async def test_an_unpriced_forward_books_at_zero_which_is_what_the_refusal_pays_for(
    tmp_path: Path,
) -> None:
    """MEASURED, because the opposite was believed and written down.

    An unpriced ``PositionStatusReport`` does NOT "generate nothing". With no
    cached quote and an empty position cache, the engine synthesises a MARKET
    ``OrderStatusReport`` with ``price=None`` and ``avg_px=None``
    (``live/execution_engine.py:2947-3011``), and
    ``create_inferred_order_filled_event`` then reaches
    ``instrument.make_price(0.0)`` (``live/reconciliation.py:484-493``). So
    ``make_price(0.0)`` IS reachable from a position report.

    That is the accepted cost of forwarding, not an argument against it: the
    QUANTITY is right (which is what every cap reads), the entry price is
    wrong, and the latched refusal guarantees no Breezy order is ever sized or
    exited against that price. Dropping the position instead would have made
    the quantity wrong too, which is the failure that trades.
    """
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock, _portfolio = _build_engine(loop)
    instrument = build_instrument()
    client = _build_client(
        loop,
        tmp_path,
        # `qtySold != 0` -> the venue cost basis cannot price it either.
        read=_position_read(str(instrument.symbol.value), bought="5", sold="1"),
        cache=cache,
        msgbus=msgbus,
        clock=clock,
    )
    engine.register_client(client)
    await client._connect()

    assert await engine.reconcile_execution_state(timeout_secs=5.0) is True

    positions = cache.positions_open(instrument_id=instrument.id)
    assert len(positions) == 1
    assert positions[0].quantity == instrument.make_qty(4)  # the number caps read
    assert positions[0].avg_px_open == 0.0  # the number nobody may act on
    assert any("UNPRICED" in reason for reason in client.trading_refusals), client.trading_refusals
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_client_returning_none_fails_reconciliation(tmp_path: Path) -> None:
    """Non-vacuity: the engine CAN fail, so the two greens above mean something.

    Same engine, same call, one line different in the client: the native
    ``None``. `live/execution_engine.py:1723-1729` turns it into `False`, and
    a `False` is a node that does not start.
    """
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock, _portfolio = _build_engine(loop)
    client = _build_client(
        loop,
        tmp_path,
        read=_flat_account_read,
        cache=cache,
        msgbus=msgbus,
        clock=clock,
    )
    engine.register_client(client)
    await client._connect()

    async def _native_none(lookback_mins: int | None = None) -> None:
        return None

    client.generate_mass_status = _native_none  # type: ignore[assignment,method-assign]

    assert await engine.reconcile_execution_state(timeout_secs=5.0) is False
    await client._disconnect()


class _SwitchableRead:
    """The venue read for the FLAT-on-HELD contract test.

    Balances are always flat; the position side of the read starts as a LONG
    of 4 and can be switched to the venue reporting the SAME instrument
    FLAT, exactly the settlement shape the module docstring's landmine note
    warns about.
    """

    def __init__(self, slug: str) -> None:
        self._slug = slug
        self.flat = False

    async def __call__(self, path: str) -> Any:
        if path == ACCOUNT_BALANCES_PATH:
            return await _flat_account_read(path)
        if path == PORTFOLIO_POSITIONS_PATH:
            position = build_position(self._slug)
            if self.flat:
                position["netPosition"] = "0"
                position["qtyBought"] = "4"
                position["qtySold"] = "4"
            return {"positions": {self._slug: position}}
        raise AssertionError(f"unexpected private read of {path!r}")


@pytest.mark.asyncio
async def test_a_flat_venue_report_on_a_held_long_is_never_forwarded(
    tmp_path: Path,
) -> None:
    """The FLAT-on-HELD suppression, measured end to end through the real engine.

    ``_map_position`` declines to forward a FLAT report at all (module
    docstring's landmine note): on a settled binary
    ``calculate_reconciliation_price`` (``live/reconciliation.py:549``) books
    the close at the OPEN price and every settled trade realizes exactly
    zero. Reconcile a LONG priced from a durable fill record so the cache
    holds a real position, then make the SAME venue report FLAT, and prove
    NOTHING closes: no ``PositionStatusReport`` is produced for it, the
    cached position is byte-identical, and no synthetic close fill is booked.
    """
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock, _portfolio = _build_engine(loop)
    instrument = build_instrument()
    slug = str(instrument.symbol.value)
    read = _SwitchableRead(slug)
    client = _build_client(
        loop,
        tmp_path,
        read=read,
        cache=cache,
        msgbus=msgbus,
        clock=clock,
    )
    engine.register_client(client)
    await client._connect()
    client.record_fill(
        DurableFillRecord(
            venue_order_id="V-OPEN-1",
            client_order_id="O-19700101-000000-001-001-1",
            instrument_id=str(instrument.id),
            order_side="BUY",
            cumulative_qty=Decimal(4),
            cumulative_cost=Decimal("1.48"),
            ts_event=clock.timestamp_ns(),
        ),
    )

    assert await engine.reconcile_execution_state(timeout_secs=5.0) is True
    assert client.trading_refusals == ()

    positions = cache.positions_open(instrument_id=instrument.id)
    assert len(positions) == 1
    position = positions[0]
    assert position.avg_px_open == 0.37  # 1.48 / 4, from the record
    original_qty = position.quantity
    original_avg_px = position.avg_px_open
    original_realized_pnl = position.realized_pnl

    # The suppression itself, isolated: a direct read against the FLAT venue
    # produces NO position report for this instrument.
    read.flat = True
    reports = await client.generate_position_status_reports(None)
    assert reports == [], reports

    # And through the full engine reconciliation a second time: still nothing
    # closes, because no report ever arrives to reconcile against.
    assert await engine.reconcile_execution_state(timeout_secs=5.0) is True

    positions_after = cache.positions_open(instrument_id=instrument.id)
    assert len(positions_after) == 1, "the FLAT report must not close the position"
    position_after = positions_after[0]
    assert position_after.is_open
    assert position_after.quantity == original_qty
    assert position_after.avg_px_open == original_avg_px
    assert position_after.realized_pnl == original_realized_pnl
    await client._disconnect()


@pytest.mark.asyncio
async def test_balance_after_reconciling_a_priced_forward_reads_the_real_venue_balance(
    tmp_path: Path,
) -> None:
    """MEASURED CORRECTION to the R-4 review's balance-debit premise.

    The review's premise: ``_connect`` publishes the venue's ``currentBalance``
    B BEFORE reconciliation; a priced forward (a durable record q@p) then
    makes Nautilus synthesize an inferred BUY fill q@p, and
    ``Portfolio.update_order`` -> ``CashAccount.calculate_pnls`` would debit
    q*p (``portfolio/portfolio.pyx:531-536``,
    ``accounting/accounts/cash.pyx:455-471``) even though the venue's own
    balance B is already net of that purchase -- a wrong number in a Breezy
    cap (``max_equity_fraction`` reads ``balance_total``,
    ``strategy/forecast_mispricing/strategy.py:419``).

    **Measured here: the debit never happens, and does not happen for a
    structural reason, not a lucky ordering.**
    ``Portfolio.update_order`` (``portfolio.pyx:500-501``) returns immediately
    unless ``account.calculate_account_state`` is ``True``:

        if not account.calculate_account_state:
            return  # Nothing to calculate

    That flag is set from ``_ISSUER_ACCOUNT_CALCULATED`` at account creation
    (``accounting/factory.pyx:125,155``), which defaults ``False`` and is only
    ever flipped by an explicit
    ``AccountFactory.register_calculated_account(issuer)`` call -- which does
    not appear anywhere in ``src/`` (verified: ``grep -rn
    'register_calculated_account\\|AccountFactory' src/`` is empty). Both the
    manual account-creation path this client's own tests wire
    (``tests/unit/test_polymarket_us_exec_client.py``) and the REAL
    ``Portfolio.update_account`` path (``portfolio.pyx:1891-1899``) build the
    account through the identical ``AccountFactory.create_c``, so this is not
    an artifact of how a test wires the account -- it is how Breezy's account
    is actually built in production. The balance this client publishes at
    ``_connect`` is therefore never touched by a reconciled fill, in either
    direction: it reads the venue's own number, unchanged, exactly because
    Breezy has not opted into Nautilus recomputing it.

    This closes the review's item D with NO code change in the PRODUCTION
    (live-only-process) case: there is no wrong number to correct there. The
    test below asserts both branches of ``calculate_account_state`` rather
    than hard-coding one, because that flag is a PROCESS-GLOBAL registry keyed
    by issuer string and Breezy's own backtest harness flips it for this same
    issuer the moment a backtest runs in-process -- see the comment at the
    assertion for the measured trigger.
    """
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock, _portfolio = _build_engine(loop)
    instrument = build_instrument()
    slug = str(instrument.symbol.value)
    client = _build_client(
        loop,
        tmp_path,
        read=_position_read(slug),
        cache=cache,
        msgbus=msgbus,
        clock=clock,
    )
    engine.register_client(client)
    await client._connect()
    client.record_fill(
        DurableFillRecord(
            venue_order_id="V-1",
            client_order_id="O-19700101-000000-001-001-1",
            instrument_id=str(instrument.id),
            order_side="BUY",
            cumulative_qty=Decimal(4),
            cumulative_cost=Decimal("1.48"),  # 4 @ 0.37
            ts_event=clock.timestamp_ns(),
        ),
    )
    account = cache.account_for_venue(POLYMARKET_US_VENUE)
    assert account is not None

    assert await engine.reconcile_execution_state(timeout_secs=5.0) is True

    positions = cache.positions_open(instrument_id=instrument.id)
    assert len(positions) == 1
    assert positions[0].avg_px_open == 0.37

    # `calculate_account_state` is a PROCESS-GLOBAL flag keyed by issuer
    # string (`accounting/factory.pyx`'s `_ISSUER_ACCOUNT_CALCULATED`), not a
    # per-test or per-Cache setting, and it is never reset between tests.
    # Breezy's OWN backtest harness registers this SAME issuer
    # ("POLYMARKET_US") as calculated the moment ANY backtest against that
    # venue runs in this interpreter (`backtest/execution_client.pyx:84`,
    # `AccountFactory.register_calculated_account(exchange.id.value)`) --
    # measured directly: running `tests/unit/test_runtime_backtest_harness.py`
    # before this file flips it to `True` for the rest of the pytest session.
    # Live and backtest never share a process in production, so this cannot
    # happen there -- but a shared pytest session can trigger it, so BOTH
    # branches are asserted here, correctly, rather than hard-coding one and
    # letting suite ordering silently falsify it.
    if account.calculate_account_state:
        # The debit is the purchase cost AND the reconciliation commission
        # this client's own `calculate_commission` override prices (TAKER,
        # `theta * C * p * (1-p)`) -- measured: leaving the commission out of
        # this expectation understates the debit by ~0.06 on this fixture.
        commission = polymarket_us_fee(
            instrument,
            instrument.make_qty(4),
            instrument.make_price(Decimal("0.37")),
        )
        assert account.balance_total(account.base_currency) == Money(
            BALANCE - Decimal("1.48") - commission.as_decimal(),
            account.base_currency,
        ), "calculate_account_state flipped True in-process: the debit is real"
    else:
        # The number that matters in the PRODUCTION (live-only-process) case:
        # unchanged from what `_connect` published, NOT debited by the
        # reconciled purchase.
        assert account.balance_total(account.base_currency) == Money(
            BALANCE,
            account.base_currency,
        )
    await client._disconnect()
