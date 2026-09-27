"""Contract (AUD-13b): the two report generators rebuild the book from Breezy's
durable fill records, through the REAL ``LiveExecutionEngine``.

Plan: ``docs/plans/backlog/AUDIT_2026-09-21/AUD-13-native-venue-reconciliation-
from-durable-records.md`` sub-item 13b (§6, §7 steps 1-5, §8). Field map:
``docs/evidence/AUD13A_RECONCILIATION_EVIDENCE_2026-09-24.md`` §5. Ruling:
``docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`` (R-1 = O4).

Native surface (installed ``nautilus_trader`` 1.231.0, asserted below):
``ExecutionClient.generate_order_status_reports`` / ``generate_fill_reports``
(``live/execution_client.py:371,394``), gathered by ``generate_mass_status``
(``:440``) and reconciled by ``LiveExecutionEngine.reconcile_execution_state``
(``live/execution_engine.py:1670``). A ``FillReport`` is reachable only through
the order report naming its venue order id (``:1880-1881``), so both land
together. ``OrderStatusReport`` (``execution/reports.py:181``) and
``FillReport`` (``:667``) are the only report types used; nothing is patched.

Every ``N >= 1`` assertion below is over a CONSTRUCTED fixture store, never the
live store (coordinator decision 3; evidence pack F4: today's store gates to
zero records). No socket is opened: the venue read is an injected coroutine.
No operator-reserved control (max daily budget, max per position) is read or
assigned here.
"""

from __future__ import annotations

import asyncio
import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import nautilus_trader
import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.live.config import LiveExecEngineConfig
from nautilus_trader.live.execution_engine import LiveExecutionEngine
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import OrderSide, OrderStatus
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import ClientId, ClientOrderId, TraderId, VenueOrderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money
from nautilus_trader.portfolio.portfolio import Portfolio

from breezy.adapters.polymarket_us.exec.client import (
    DURABLE_REPORTS_BUILD_FAILED,
    FEE_COEFFICIENT_AMBIGUOUS,
    FEE_SOURCE_MODELLED_AT_FILL_TIME,
    FEE_SOURCE_RECORDED,
    POSITIONS_READ_FAILED,
    RECONCILIATION_REFUSAL_EVENT,
    RECORD_VENUE_DISAGREEMENT,
    DurableFillRecord,
    PolymarketUSExecutionClient,
    format_reconciliation_counts_line,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option, parse_binary_option_pair
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.node_config import build_trade_node_config
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.unit.polymarket_us_exec_shapes import (
    RAW,
    TS_EVENT_TEXT,
    TS_INIT,
    build_position,
    build_second_instrument,
)
from tests.unit.test_runtime_trade_node_config import (
    make_data_client_config,
    make_exec_client_config,
    make_trade_settings,
)

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION: Final[str] = "1.231.0"
TRADER_ID: Final[TraderId] = TraderId("BREEZY-A13B-RECON-001")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
BALANCE: Final[Decimal] = Decimal("125.50")
OPERATOR_ORDER_CEILING_USD: Final[str] = "25"

#: Fee-schedule epochs (``FEE_SCHEDULE_PIN_2026-09-18.md``), as the fixtures
#: need them. 2026-09-15T20:12:06Z is the real CGY0... record's fill time
#: (evidence pack §1): PRE-drift.
PRE_DRIFT_NS: Final[int] = 1_789_503_126_000_000_000  # 2026-09-15T20:12:06Z
AMBIGUOUS_NS: Final[int] = 1_789_603_200_000_000_000 + 3_600_000_000_000  # 2026-09-17T01:00Z
POST_DRIFT_NS: Final[int] = 1_790_022_095_000_000_000  # 2026-09-21T20:21:35Z

_RAW_MARKET: Final[Path] = RAW / "market_open_510636_by_slug.json"


def test_pinned_nautilus_version() -> None:
    """Every native ``path:line`` in this module was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION


@pytest.fixture(autouse=True)
def _operator_order_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-local stand-in for the per-order USD ceiling ``build_trade_node_
    config`` fails closed without -- not an operator-reserved control."""
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_ORDER_CEILING_USD)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _market(theta: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(_RAW_MARKET.read_text(encoding="utf-8"))
    payload["market"]["feeCoefficient"] = Decimal(theta)
    return payload


def _pair(theta: str = "0.06") -> tuple[BinaryOption, BinaryOption]:
    yes, no = parse_binary_option_pair(
        _market(theta), venue=POLYMARKET_US_VENUE, ts_init=TS_INIT,
    )
    assert no is not None
    return yes, no


def _post_drift_yes() -> BinaryOption:
    """The SAME market, as a boot on or after 2026-09-17 would load it."""
    return parse_binary_option(_market("0.0695"), venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def _slug(instrument: BinaryOption) -> str:
    return str(instrument.symbol.value).split("^", 1)[0]


def _engine_config() -> LiveExecEngineConfig:
    config = build_trade_node_config(
        make_trade_settings(), make_data_client_config(), make_exec_client_config()
    )
    assert config.exec_engine is not None
    return config.exec_engine


class _Rig:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        tmp_path: Path,
        *,
        cached: tuple[BinaryOption, ...],
        provided: tuple[BinaryOption, ...] | None = None,
    ) -> None:
        self.clock = LiveClock()
        self.msgbus = MessageBus(trader_id=TRADER_ID, clock=self.clock)
        self.cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
        for instrument in cached:
            self.cache.add_instrument(instrument)
        self.portfolio = Portfolio(msgbus=self.msgbus, cache=self.cache, clock=self.clock)
        self.engine = LiveExecutionEngine(
            loop=loop,
            msgbus=self.msgbus,
            cache=self.cache,
            clock=self.clock,
            config=_engine_config(),
        )
        provider = InstrumentProvider()
        for instrument in cached if provided is None else provided:
            provider.add(instrument)
        self.positions: dict[str, Any] = {}
        self.position_reads = 0
        self.fail_positions = False
        self.client = PolymarketUSExecutionClient(
            loop=loop,
            client_id=CLIENT_ID,
            venue=POLYMARKET_US_VENUE,
            instrument_provider=provider,
            msgbus=self.msgbus,
            cache=self.cache,
            clock=self.clock,
            private_read=self._read,
            state_store_opener=lambda: SqliteStateStore(tmp_path / "exec_state.db"),
            account_number="001",
            instrument_wait_timeout_s=2.0,
            account_registration_timeout_s=2.0,
        )
        self.engine.register_client(self.client)

    async def _read(self, path: str) -> Any:
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
            self.position_reads += 1
            if self.fail_positions:
                raise RuntimeError("the venue position read failed")
            return {"positions": copy.deepcopy(self.positions), "eof": True}
        return {}

    def hold(self, slug: str, net: int, *, no_leg: bool = False) -> None:
        position = build_position(slug)
        position["netPosition"] = str(-net if no_leg else net)
        position["qtyBought"] = str(net)
        position["qtySold"] = "0"
        if no_leg:
            position["marketMetadata"] = {"slug": slug, "outcome": "No"}
        self.positions[slug] = position

    async def reconcile(self) -> bool:
        return bool(await self.engine.reconcile_execution_state(timeout_secs=5.0))


def _record(
    instrument: BinaryOption,
    *,
    venue_order_id: str,
    client_order_id: str,
    qty: str = "1",
    cost: str = "0.44",
    side: str = "BUY",
    ts_event: int = PRE_DRIFT_NS,
    fee: str = "0",
    fee_reconciled: bool = False,
    venue_fee_raw: str | None = None,
    trade_id: str | None = None,
    order_qty: str | None = "1",
    fee_coefficient_at_fill: str | None = None,
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=client_order_id,
        instrument_id=str(instrument.id),
        order_side=side,
        cumulative_qty=Decimal(qty),
        cumulative_cost=Decimal(cost),
        cumulative_fee=Decimal(fee),
        fee_reconciled=fee_reconciled,
        ts_event=ts_event,
        venue_fee_raw=venue_fee_raw,
        trade_id=trade_id,
        order_qty=None if order_qty is None else Decimal(order_qty),
        fee_coefficient_at_fill=(
            None if fee_coefficient_at_fill is None else Decimal(fee_coefficient_at_fill)
        ),
    )


def _refusals_by_latch(client: PolymarketUSExecutionClient) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in client.reconciliation_refusals:
        grouped.setdefault(entry["latch"], []).append(dict(entry))
    return grouped


def _fills(cache: Cache) -> list[OrderFilled]:
    return [
        event
        for order in cache.orders()
        for event in order.events
        if isinstance(event, OrderFilled)
    ]


# ---------------------------------------------------------------------------
# §7 13b step 1 -- the fail-closed walks, pinned before any report is emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_positions_read_yields_empty_reports_and_a_latched_refusal(
    tmp_path: Path,
) -> None:
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-READ-1", client_order_id="O-READ-1"))
    rig.fail_positions = True

    status = await rig.client.generate_mass_status()

    assert status.order_reports == {}
    assert status.fill_reports == {}
    latched = _refusals_by_latch(rig.client)
    assert list(latched) == [POSITIONS_READ_FAILED]
    (entry,) = latched[POSITIONS_READ_FAILED]
    assert entry["event"] == RECONCILIATION_REFUSAL_EVENT
    assert entry["detail"] == "POSITIONS_READ_FAILED"
    counts = rig.client.reconciliation_counts
    assert counts["order_reports"] == 0
    assert counts["refusals_positions_read_failed"] == 1
    assert counts["refusals"] == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_partially_parseable_positions_payload_fails_the_whole_read(
    tmp_path: Path,
) -> None:
    """A dropped unparseable row would turn "the venue says we hold this" into
    "the venue does not" -- the fail-OPEN direction. So one bad row fails the
    WHOLE read for the durable reports, even though a good row is present."""
    yes, _ = _pair()
    second = build_second_instrument()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes, second))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-PART-1", client_order_id="O-PART-1"))
    rig.hold(_slug(yes), 1)
    rig.hold(_slug(second), 1)
    rig.positions[_slug(second)]["netPosition"] = "not-a-number"

    status = await rig.client.generate_mass_status()

    assert status.order_reports == {}
    assert status.fill_reports == {}
    assert list(_refusals_by_latch(rig.client)) == [POSITIONS_READ_FAILED]
    assert rig.client.reconciliation_counts["refusals_positions_read_failed"] == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_client_order_id_disagreement_emits_nothing(tmp_path: Path) -> None:
    """F3: the venue-id map names a DIFFERENT client order id than the record.
    Never pick one -- nothing is reported for that instrument."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-COID-1", client_order_id="O-COID-1"))
    rig.client.record_venue_order_id(VenueOrderId("V-COID-1"), ClientOrderId("O-SOMEONE-ELSE"))
    rig.hold(_slug(yes), 1)

    order_reports = await rig.client.generate_order_status_reports(None)
    fill_reports = await rig.client.generate_fill_reports(None)

    assert order_reports == []
    assert fill_reports == []
    (entry,) = _refusals_by_latch(rig.client)[RECORD_VENUE_DISAGREEMENT]
    assert entry["subject"] == str(yes.id)
    assert entry["detail"] == "RECORD_VENUE_DISAGREEMENT"
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_missing_venue_id_map_row_is_not_a_disagreement(tmp_path: Path) -> None:
    """Coordinator decision 2 / evidence F7: CEBP... has no ``venue_id`` row
    (pre-A1). An ABSENT row is not a disagreement."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-NOMAP-1", client_order_id="O-NOMAP-1"))
    assert rig.client.client_order_id_for(VenueOrderId("V-NOMAP-1")) is None
    rig.hold(_slug(yes), 1)

    order_reports = await rig.client.generate_order_status_reports(None)

    assert len(order_reports) == 1
    assert rig.client.reconciliation_refusals == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_quantity_disagreement_emits_nothing_for_that_instrument_only(
    tmp_path: Path,
) -> None:
    yes, _ = _pair()
    second = build_second_instrument()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes, second))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-QTY-1", client_order_id="O-QTY-1"))
    rig.client.record_fill(
        _record(second, venue_order_id="V-QTY-2", client_order_id="O-QTY-2", cost="0.09"),
    )
    rig.hold(_slug(yes), 3)  # the record says 1
    rig.hold(_slug(second), 1)

    order_reports = await rig.client.generate_order_status_reports(None)

    assert [report.instrument_id for report in order_reports] == [second.id]
    (entry,) = _refusals_by_latch(rig.client)[RECORD_VENUE_DISAGREEMENT]
    assert entry["subject"] == str(yes.id)
    assert rig.client.reconciliation_counts["refusals_record_venue_disagreement"] == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_an_instrument_absent_from_the_cache_is_counted_not_silently_dropped(
    tmp_path: Path,
) -> None:
    """Coordinator decision 2 / evidence F8: the engine skips a report whose
    instrument is not cached (``live/execution_engine.py:3056-3062``). It is
    counted as its OWN field, never folded into ``gated_out``."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(), provided=(yes,))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-ABS-1", client_order_id="O-ABS-1"))
    rig.hold(_slug(yes), 1)

    order_reports = await rig.client.generate_order_status_reports(None)

    assert order_reports == []
    counts = rig.client.reconciliation_counts
    assert counts["instrument_absent"] == 1
    assert counts["gated_out"] == 0
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# §7 13b step 1b/1c -- the ruling-mandated tests
# ---------------------------------------------------------------------------


class _ExitSpy:
    def __init__(self) -> None:
        self.exit_events: list[OrderFilled] = []
        self.entry_joins: list[Any] = []


@pytest.mark.asyncio
async def test_a_sell_side_durable_record_reconciles_to_a_sell_report_never_a_buy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling finding 8: a partial-exit SELL record for an instrument the venue
    still holds reconciles to SELL on BOTH reports, and the reconciled
    ``OrderFilled`` routes to ``_on_exit_order_filled``
    (``continuous_strategy.py:2271-2277``), never the entry path."""
    from tests.unit.test_continuous_rung_hold_strategy import _register_and_start
    from tests.unit.test_current_rung_hold_strategy import INTERIOR_ID, _instrument

    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-ENTRY-1", client_order_id="O-ENTRY-1",
                qty="3", cost="1.20", order_qty="3"),
    )
    rig.client.record_fill(
        _record(yes, venue_order_id="V-EXIT-1", client_order_id="O-EXIT-1", side="SELL",
                qty="1", cost="0.50", order_qty="1", ts_event=PRE_DRIFT_NS + 60_000_000_000),
    )
    rig.hold(_slug(yes), 2)

    order_reports = await rig.client.generate_order_status_reports(None)
    fill_reports = await rig.client.generate_fill_reports(None)
    sides = {str(r.venue_order_id): r.order_side for r in order_reports}
    fill_sides = {str(r.venue_order_id): r.order_side for r in fill_reports}
    assert sides == {"V-ENTRY-1": OrderSide.BUY, "V-EXIT-1": OrderSide.SELL}
    assert fill_sides == sides

    assert await rig.reconcile() is True
    exit_fills = [f for f in _fills(rig.cache) if str(f.venue_order_id) == "V-EXIT-1"]
    assert len(exit_fills) == 1
    reconciled_exit = exit_fills[0]
    assert reconciled_exit.order_side is OrderSide.SELL
    positions = rig.cache.positions_open(instrument_id=yes.id)
    assert len(positions) == 1
    assert positions[0].quantity == yes.make_qty(2)

    strategy = _register_and_start(
        store_path=tmp_path / "strategy.db",
        instruments=(_instrument(INTERIOR_ID, lower_f=86, upper_f=87),),
    )
    spy = _ExitSpy()
    monkeypatch.setattr(strategy, "_on_exit_order_filled", spy.exit_events.append)
    monkeypatch.setattr(strategy, "_join_fill_to_station_day", spy.entry_joins.append)
    strategy.on_order_filled(reconciled_exit)
    assert spy.exit_events == [reconciled_exit]
    assert spy.entry_joins == [], "a SELL must never reach the entry join"
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_pre_drift_fill_reconciled_on_a_post_drift_boot_books_the_fill_time_coefficient(
    tmp_path: Path,
) -> None:
    """Ruling Revision 2's HIGH item. Evidence pack F2: the price must be one
    where 0.06 and 0.0695 differ AT THE CENT -- 0.44 (0.01 vs 0.02), the real
    CGY0... price. At 0.22 this test would pass under the defect.

    0.06   * 1 * 0.44 * 0.56 = 0.014784 -> 0.01
    0.0695 * 1 * 0.44 * 0.56 = 0.0171248 -> 0.02
    """
    post_drift = _post_drift_yes()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(post_drift,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(post_drift, venue_order_id="V-PRE-1", client_order_id="O-PRE-1",
                cost="0.44", ts_event=PRE_DRIFT_NS),
    )
    rig.hold(_slug(post_drift), 1)

    await rig.client.generate_order_status_reports(None)
    (fill,) = await rig.client.generate_fill_reports(None)

    assert fill.commission == Money(Decimal("0.01"), USD), fill.commission
    assert rig.client.reconciled_fee_sources == {"V-PRE-1": FEE_SOURCE_MODELLED_AT_FILL_TIME}
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_new_record_books_its_own_fee_coefficient_at_fill_over_the_schedule(
    tmp_path: Path,
) -> None:
    """B0 mechanism (a): a record carrying ``fee_coefficient_at_fill`` is
    priced at THAT theta, whatever the dated schedule says for its time."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-OWN-1", client_order_id="O-OWN-1", cost="0.44",
                ts_event=POST_DRIFT_NS, fee_coefficient_at_fill="0.06"),
    )
    rig.hold(_slug(yes), 1)

    await rig.client.generate_order_status_reports(None)
    (fill,) = await rig.client.generate_fill_reports(None)

    assert fill.commission == Money(Decimal("0.01"), USD)
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_legacy_record_inside_the_ambiguous_fee_window_is_refused_not_defaulted(
    tmp_path: Path,
) -> None:
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-AMBIG-1", client_order_id="O-AMBIG-1",
                cost="0.44", ts_event=AMBIGUOUS_NS),
    )
    rig.hold(_slug(yes), 1)

    assert await rig.client.generate_order_status_reports(None) == []
    assert await rig.client.generate_fill_reports(None) == []

    (entry,) = _refusals_by_latch(rig.client)[FEE_COEFFICIENT_AMBIGUOUS]
    assert entry["detail"] == "FEE_COEFFICIENT_AMBIGUOUS"
    assert entry["subject"] == "V-AM…", "the venue order id travels REDACTED"
    assert entry["ts_event_bucket"] == "AMBIGUOUS"
    assert "V-AMBIG-1" not in json.dumps(entry)
    assert rig.client.reconciliation_counts["refusals_fee_coefficient_ambiguous"] == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_the_ambiguous_fee_window_refusal_is_observably_distinct_from_the_other_latches(
    tmp_path: Path,
) -> None:
    """Three named refusals, three DIFFERENT latch keys, detail members and
    per-cause counters.

    Stated rather than papered over: a failed positions read and a
    record/venue disagreement CANNOT co-occur on one read -- the disagreement
    needs a successful read to compare against. So the read failure is driven
    on one pass and the other two together on the next, over ONE client whose
    latches persist; the per-pass counts lines show each cause in its own
    field."""
    yes, _ = _pair()
    second = build_second_instrument()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes, second))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-D-1", client_order_id="O-D-1"))
    rig.client.record_fill(
        _record(second, venue_order_id="V-A-1", client_order_id="O-A-1", ts_event=AMBIGUOUS_NS),
    )
    rig.hold(_slug(yes), 2)  # record says 1 -> disagreement
    rig.hold(_slug(second), 1)

    rig.fail_positions = True
    await rig.client.generate_mass_status()
    first = dict(rig.client.reconciliation_counts)
    rig.fail_positions = False
    await rig.client.generate_mass_status()
    second_pass = dict(rig.client.reconciliation_counts)

    latched = _refusals_by_latch(rig.client)
    assert set(latched) == {
        POSITIONS_READ_FAILED,
        RECORD_VENUE_DISAGREEMENT,
        FEE_COEFFICIENT_AMBIGUOUS,
    }
    details = {entries[0]["detail"] for entries in latched.values()}
    assert details == {
        "POSITIONS_READ_FAILED",
        "RECORD_VENUE_DISAGREEMENT",
        "FEE_COEFFICIENT_AMBIGUOUS",
    }
    assert {e["event"] for es in latched.values() for e in es} == {RECONCILIATION_REFUSAL_EVENT}
    assert (
        first["refusals_positions_read_failed"],
        first["refusals_record_venue_disagreement"],
        first["refusals_fee_coefficient_ambiguous"],
    ) == (1, 0, 0)
    assert (
        second_pass["refusals_positions_read_failed"],
        second_pass["refusals_record_venue_disagreement"],
        second_pass["refusals_fee_coefficient_ambiguous"],
    ) == (0, 1, 1)
    assert second_pass["refusals"] == 2
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_recorded_fee_reports_the_recorded_commission_and_feesource_recorded(
    tmp_path: Path,
) -> None:
    """O4 upper branch. The recorded fee (0.02, CMSN...'s real shape) is NOT
    what either model gives at this price and time (0.0695 at 0.09 -> 0.01),
    so a model leaking through would be visible."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-REC-1", client_order_id="O-REC-1", cost="0.09",
                ts_event=POST_DRIFT_NS, fee="0.0200", fee_reconciled=True,
                venue_fee_raw="0.0200", trade_id="trd-rec-1"),
    )
    rig.hold(_slug(yes), 1)

    await rig.client.generate_order_status_reports(None)
    (fill,) = await rig.client.generate_fill_reports(None)

    assert fill.commission == Money(Decimal("0.02"), USD)
    assert str(fill.trade_id) == "trd-rec-1"
    assert rig.client.reconciled_fee_sources == {"V-REC-1": FEE_SOURCE_RECORDED}
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_feesource_is_never_recorded_without_a_raw_venue_fee(tmp_path: Path) -> None:
    """``fee_reconciled`` alone is not a venue attestation: without the raw
    venue fee the commission is MODELLED -- even if the stored ``feeSource``
    claims otherwise."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    record = _record(yes, venue_order_id="V-NORAW-1", client_order_id="O-NORAW-1",
                     cost="0.44", fee="0.0500", fee_reconciled=True, venue_fee_raw=None)
    raw = json.loads(record.to_bytes())
    raw["feeSource"] = FEE_SOURCE_RECORDED
    forged = DurableFillRecord.from_bytes(json.dumps(raw).encode("utf-8"))
    rig.client.record_fill(forged)
    rig.hold(_slug(yes), 1)

    await rig.client.generate_order_status_reports(None)
    (fill,) = await rig.client.generate_fill_reports(None)

    assert fill.commission == Money(Decimal("0.01"), USD), "modelled at 0.06, never 0.05"
    assert rig.client.reconciled_fee_sources == {"V-NORAW-1": FEE_SOURCE_MODELLED_AT_FILL_TIME}
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# §7 13b step 2/3 -- gating and the regression detector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_record_for_an_instrument_the_venue_no_longer_holds_is_not_reported(
    tmp_path: Path,
) -> None:
    """The gating rule: no phantom LONG after settlement. The venue reports the
    market EXPIRED (settled) -> nothing is reported for its record."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-GONE-1", client_order_id="O-GONE-1"))
    rig.hold(_slug(yes), 1)
    rig.positions[_slug(yes)]["expired"] = True

    status = await rig.client.generate_mass_status()

    assert status.order_reports == {}
    assert status.fill_reports == {}
    counts = rig.client.reconciliation_counts
    assert counts["gated_out"] == 1
    assert counts["records_considered"] == 0
    assert rig.client.reconciliation_refusals == ()
    await rig.client._disconnect()


def test_the_reconciliation_counts_line_distinguishes_zero_records_from_zero_reports() -> None:
    """A silent regression to ``[]`` reads ``order_reports=0 records_considered=N``
    -- a different, greppable shape from a legitimate ``records_considered=0``."""
    base = {
        "order_reports": 0,
        "fill_reports": 0,
        "records_considered": 0,
        "gated_out": 0,
        "instrument_absent": 0,
        "refusals": 0,
        "refusals_positions_read_failed": 0,
        "refusals_record_venue_disagreement": 0,
        "refusals_fee_coefficient_ambiguous": 0,
        "refusals_durable_reports_build_failed": 0,
    }
    nothing = format_reconciliation_counts_line(base)
    regressed = format_reconciliation_counts_line({**base, "records_considered": 3})
    assert nothing == (
        "durable reconciliation: order_reports=0 fill_reports=0 records_considered=0 "
        "gated_out=0 instrument_absent=0 refusals=0 refusals_positions_read_failed=0 "
        "refusals_record_venue_disagreement=0 refusals_fee_coefficient_ambiguous=0 "
        "refusals_durable_reports_build_failed=0"
    )
    assert "order_reports=0" in regressed
    assert "records_considered=3" in regressed
    assert nothing != regressed


@pytest.mark.asyncio
async def test_one_mass_status_reads_the_venue_positions_once(tmp_path: Path) -> None:
    """The three generators share ONE memoised positions read per pass, so the
    gating and the position report can never see two different books."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-ONCE-1", client_order_id="O-ONCE-1"))
    rig.hold(_slug(yes), 1)
    before = rig.position_reads

    status = await rig.client.generate_mass_status()

    assert rig.position_reads - before == 1
    assert len(status.order_reports) == 1
    assert len(status.position_reports) == 1
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# §7 13b steps 4-5 -- engine-driven goal state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_2026_09_11_order_2_fill_reconciles_on_the_first_boot(tmp_path: Path) -> None:
    """The G-10 incident shape, constructed (evidence pack §1 row CEBP...): a
    resolver-written record -- ``fee_reconciled=False``, no ``venueFeeRaw``,
    NO ``tradeId`` and NO ``orderQty`` (legacy), no ``venue_id`` row -- written
    before any reconciling boot, and a venue positions read showing it open.

    One reconciliation adopts it under Breezy's client order id; a second
    reconciliation of the same fill is a no-op."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="CEBPX0EVTTMX", client_order_id="O-20260911-202029-L001-SFO-1",
                cost="0.22", ts_event=1_789_179_830_000_000_000,  # 2026-09-12T02:23:50Z
                trade_id=None, order_qty=None),
    )
    rig.hold(_slug(yes), 1)

    assert await rig.reconcile() is True

    orders = rig.cache.orders()
    assert [str(o.client_order_id) for o in orders] == ["O-20260911-202029-L001-SFO-1"]
    (order,) = orders
    assert order.status is OrderStatus.FILLED
    assert order.quantity == yes.make_qty(1), "L-2: legacy quantity = the filled portion"
    (fill,) = _fills(rig.cache)
    assert str(fill.trade_id) == "GET-CEBPX0EVTTMX"
    assert fill.commission == Money(Decimal("0.01"), USD)
    assert len(rig.cache.positions_open(instrument_id=yes.id)) == 1

    assert await rig.reconcile() is True
    assert len(rig.cache.orders()) == 1
    assert len(_fills(rig.cache)) == 1, "the second reconciliation must be a no-op"
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_one_durable_record_reconciles_to_our_client_order_id_not_external(
    tmp_path: Path,
) -> None:
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-OURS-1", client_order_id="O-OURS-1", trade_id="trd-1"),
    )
    rig.hold(_slug(yes), 1)

    assert await rig.reconcile() is True

    (order,) = rig.cache.orders()
    assert order.client_order_id == ClientOrderId("O-OURS-1"), "never a UUID4"
    assert order.venue_order_id == VenueOrderId("V-OURS-1")
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_no_inferred_fill_is_generated_when_the_reports_cover_the_position(
    tmp_path: Path,
) -> None:
    """Measured on the cache, not on log text (the Nautilus logger is not
    capturable): an inferred fill would bring a second order with a synthetic
    client order id and a fill carrying a trade id that is not ours."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-INF-1", client_order_id="O-INF-1", qty="2",
                cost="0.88", order_qty="2", trade_id="trd-inf-1"),
    )
    rig.hold(_slug(yes), 2)

    assert await rig.reconcile() is True

    assert [str(o.client_order_id) for o in rig.cache.orders()] == ["O-INF-1"]
    assert [str(f.trade_id) for f in _fills(rig.cache)] == ["trd-inf-1"]
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_exactly_one_position_exists_for_the_instrument(tmp_path: Path) -> None:
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-ONE-1", client_order_id="O-ONE-1", qty="2",
                cost="0.88", order_qty="2"),
    )
    rig.hold(_slug(yes), 2)

    assert await rig.reconcile() is True

    positions = rig.cache.positions(instrument_id=yes.id)
    assert len(positions) == 1
    assert positions[0].quantity == yes.make_qty(2)
    assert positions[0].avg_px_open == pytest.approx(0.44)
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_no_leg_record_reconciles_to_its_no_instrument_never_the_yes_leg(
    tmp_path: Path,
) -> None:
    """Coordinator decision 1 / evidence F5: gate on ``_map_position``'s
    leg-resolved id. 3 of 9 real records are ``^no``; a YES-leg lookup of the
    slug would miss every one of them."""
    yes, no = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes, no))
    await rig.client._connect()
    rig.client.record_fill(
        _record(no, venue_order_id="V-NO-1", client_order_id="O-NO-1", cost="0.09"),
    )
    rig.hold(_slug(yes), 1, no_leg=True)

    order_reports = await rig.client.generate_order_status_reports(None)
    assert [r.instrument_id for r in order_reports] == [no.id]

    assert await rig.reconcile() is True
    (order,) = rig.cache.orders()
    assert order.instrument_id == no.id
    assert order.client_order_id == ClientOrderId("O-NO-1")
    assert len(rig.cache.positions_open(instrument_id=no.id)) == 1
    assert rig.cache.positions_open(instrument_id=yes.id) == []
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_partially_filled_ioc_reconciles_as_canceled_with_its_fill(
    tmp_path: Path,
) -> None:
    """``orderQty`` 3, ``cumulativeQty`` 1: the IOC remainder was cancelled
    by the venue. Reported ``CANCELED`` with ``filled_qty=1`` -- never
    ``FILLED`` with ``filled < quantity``, a contradictory report -- and the
    engine books exactly the filled 1."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-IOC-1", client_order_id="O-IOC-1", order_qty="3"),
    )
    rig.hold(_slug(yes), 1)

    (report,) = await rig.client.generate_order_status_reports(None)
    assert report.order_status is OrderStatus.CANCELED
    assert (report.quantity, report.filled_qty) == (yes.make_qty(3), yes.make_qty(1))

    assert await rig.reconcile() is True
    (order,) = rig.cache.orders()
    assert order.client_order_id == ClientOrderId("O-IOC-1")
    assert order.filled_qty == yes.make_qty(1)
    assert order.is_closed
    (position,) = rig.cache.positions_open(instrument_id=yes.id)
    assert position.quantity == yes.make_qty(1)
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_latched_refusal_reaches_the_alert_sink_once_after_a_real_reconciliation(
    tmp_path: Path,
) -> None:
    """AUD-13b delivery, end to end: the REAL client's latched refusal, read
    by the runtime watch on the SAME bus after a real engine reconciliation,
    reaches the sink exactly once with the fixed-enum detail and no id."""
    from nautilus_trader.common.enums import ComponentState
    from nautilus_trader.common.messages import ComponentStateChanged
    from nautilus_trader.core.uuid import UUID4

    from breezy.runtime.component_health_watch import install_reconciliation_refusal_alert
    from breezy.runtime.health import AlertPayload

    class _Sink:
        def __init__(self) -> None:
            self.payloads: list[AlertPayload] = []

        def emit(self, payload: AlertPayload) -> None:
            self.payloads.append(payload)

    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    sink = _Sink()
    install_reconciliation_refusal_alert(
        rig.msgbus, refusals=lambda: rig.client.reconciliation_refusals, sink=sink,
    )
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-ALERT-1", client_order_id="O-ALERT-1",
                ts_event=AMBIGUOUS_NS),
    )
    rig.hold(_slug(yes), 1)
    assert await rig.reconcile() is True
    for _ in range(2):  # what the kernel's OrderEmulator/trader starts publish
        rig.msgbus.publish(
            topic="events.system.OrderEmulator",
            msg=ComponentStateChanged(
                trader_id=TRADER_ID,
                component_id=ClientId("OrderEmulator"),
                component_type="OrderEmulator",
                state=ComponentState.RUNNING,
                config={},
                event_id=UUID4(),
                ts_event=0,
                ts_init=0,
            ),
        )

    (payload,) = [p for p in sink.payloads if p.event == "reconciliation_refusal"]
    assert payload.detail == "FEE_COEFFICIENT_AMBIGUOUS"
    assert payload.severity == "WARN"
    assert "V-AL" not in payload.detail
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# AUD-13b review fixes: `_durable_reconciliation_pass` must never raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_mapping_defect_folds_into_positions_read_failed_never_escapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A defect in `_map_positions` used to run in the `else:` of a
    try/except -- NOT covered by that except's `try:`. Called directly (not
    through `generate_mass_status`, which has its own unrelated safety net),
    the generator itself must not raise, and the defect must fold into the
    SAME positions_read_failed refusal a foreign payload shape gets."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-MAPBUG-1", client_order_id="O-MAPBUG-1"))
    rig.hold(_slug(yes), 1)

    def _boom(positions: Any) -> Any:
        raise RuntimeError("mapping defect")

    monkeypatch.setattr(rig.client, "_map_positions", _boom)

    order_reports = await rig.client.generate_order_status_reports(None)

    assert order_reports == []
    assert list(_refusals_by_latch(rig.client)) == [POSITIONS_READ_FAILED]
    assert rig.client.reconciliation_counts["refusals_positions_read_failed"] == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_per_position_build_defect_is_isolated_other_positions_still_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-position loop in `_durable_reconciliation_pass` used to run
    outside any try. A defect building ONE position's reports must not drop
    every other position's reports, and must never escape to the native
    handler -- it latches its OWN named refusal instead."""
    yes, _ = _pair()
    second = build_second_instrument()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes, second))
    await rig.client._connect()
    rig.client.record_fill(_record(yes, venue_order_id="V-GOOD-1", client_order_id="O-GOOD-1"))
    rig.client.record_fill(
        _record(second, venue_order_id="V-BAD-1", client_order_id="O-BAD-1", cost="0.09"),
    )
    rig.hold(_slug(yes), 1)
    rig.hold(_slug(second), 1)

    original = type(rig.client)._durable_reports_for_position

    def _patched(
        self: PolymarketUSExecutionClient,
        position: Any,
        counts: dict[str, int],
        order_reports: list[Any],
        fill_reports: list[Any],
        fee_sources: dict[str, str],
    ) -> None:
        if position.instrument_id == second.id:
            raise RuntimeError("build defect")
        return original(self, position, counts, order_reports, fill_reports, fee_sources)

    monkeypatch.setattr(type(rig.client), "_durable_reports_for_position", _patched)

    order_reports = await rig.client.generate_order_status_reports(None)
    fill_reports = await rig.client.generate_fill_reports(None)

    assert [r.instrument_id for r in order_reports] == [yes.id]
    assert [r.instrument_id for r in fill_reports] == [yes.id]
    (entry,) = _refusals_by_latch(rig.client)[DURABLE_REPORTS_BUILD_FAILED]
    assert entry["subject"] == str(second.id)
    assert rig.client.reconciliation_counts["refusals_durable_reports_build_failed"] == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_corrupt_fee_input_folds_into_fee_coefficient_ambiguous_never_escapes(
    tmp_path: Path,
) -> None:
    """``taker_fee_at_fill`` correctly raises ``ValueError`` for a price
    outside ``[0, 1]`` -- reachable from a corrupt
    ``cumulative_cost``/``cumulative_qty`` pair that survives
    ``_records_explain_position``'s own (qty > 0, cost > 0) check. That
    validation is left alone; the CALL SITE must fold the raise into the
    existing fee-ambiguous refusal rather than let it escape."""
    yes, _ = _pair()
    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yes,))
    await rig.client._connect()
    rig.client.record_fill(
        _record(yes, venue_order_id="V-CORRUPT-1", client_order_id="O-CORRUPT-1",
                qty="1", cost="2.00", ts_event=PRE_DRIFT_NS),
    )
    rig.hold(_slug(yes), 1)

    order_reports = await rig.client.generate_order_status_reports(None)
    fill_reports = await rig.client.generate_fill_reports(None)

    assert order_reports == []
    assert fill_reports == []
    (entry,) = _refusals_by_latch(rig.client)[FEE_COEFFICIENT_AMBIGUOUS]
    assert entry["subject"] == "V-CO…"
    assert rig.client.reconciliation_counts["refusals_fee_coefficient_ambiguous"] == 1
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# Increment C (09-12 plan §4 row C; ruling R-2 condition 1) -- engine-driven
# characterisation of replay idempotence for a CLAIMED instrument. No
# production change: the claim is registered here exactly as
# ``Trader.add_strategy`` does (``trading/trader.py:435`` ->
# ``execution/engine.pyx:532-560``), so this pins Nautilus + strategy
# behaviour independently of how Breezy's composition sets the claim.
# ---------------------------------------------------------------------------


def _claiming_continuous_strategy(
    rig: _Rig,
    *,
    store_path: Path,
    instrument: BinaryOption,
) -> Any:
    """A RUNNING ``ContinuousRungHoldStrategy`` on the rig's own bus/cache,
    claiming ``instrument``. It is started BEFORE the reconciliation -- the
    worst case for R-2: a real boot starts strategies only after
    ``reconcile_execution_state`` (``system/kernel.py:1027-1039``) and
    ``Strategy.handle_event`` drops every event while not ``RUNNING``
    (``trading/strategy.pyx:1917``), so a boot-time reconciled fill never
    reaches ``on_order_filled`` at all. Here it does."""
    from nautilus_trader.common.component import TestClock

    from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
    from breezy.strategy.current_rung_hold.continuous_strategy import (
        ContinuousRungHoldStrategy,
    )
    from tests.unit.test_continuous_rung_hold_strategy import (
        _PERMISSIVE_EVIDENCE,
        _cont_latch_factory,
    )
    from tests.unit.test_current_rung_hold_strategy import STATION, WINDOW_OPEN_NS

    config = CurrentRungHoldConfig(
        instrument_ids=(instrument.id,),
        stations=(STATION,),
        strategy_id="ContinuousRungHoldStrategy",
        order_id_tag=STATION,
        external_order_claims=[instrument.id],
    )
    strategy = ContinuousRungHoldStrategy(
        config,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    strategy.register(
        trader_id=TRADER_ID,
        portfolio=rig.portfolio,
        msgbus=rig.msgbus,
        cache=rig.cache,
        clock=clock,
    )
    rig.engine.register_external_order_claims(strategy)
    strategy.start()
    return strategy


@pytest.mark.asyncio
async def test_three_consecutive_reconciliations_leave_the_halt_key_absent(
    tmp_path: Path,
) -> None:
    """Three boots (fresh engine, cache and bus each; the SAME durable exec
    store and the SAME strategy store) each reconcile the one durable fill
    into a CLAIMED book and deliver its ``OrderFilled`` to a running
    strategy. Boot 1 consumes the TRIAL; boots 2 and 3 are replays keyed on
    ``venue_order_id`` (``trial_day_latch.py::consume_if_absent``) and must
    write no ``duplicate_fill`` bucket and never set
    ``continuous_rung_hold/halt``."""
    from breezy.strategy.current_rung_hold.trial_day_latch import (
        DUPLICATE_FILL_KEY_PREFIX,
        FAMILY_HALT_KEY_PREFIX,
        LEGACY_FAMILY_HALT_KEY,
    )
    from tests.unit.test_current_rung_hold_strategy import (
        CLIMATE_DAY,
        INTERIOR_ID,
        STATION,
        _instrument,
    )

    interior = _instrument(INTERIOR_ID, lower_f=86, upper_f=87)
    strategy_store = tmp_path / "strategy.db"
    for boot in (1, 2, 3):
        rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(interior,))
        await rig.client._connect()
        if boot == 1:
            rig.client.record_fill(
                _record(interior, venue_order_id="V-REPLAY-1", client_order_id="O-REPLAY-1",
                        cost="0.40", trade_id="trd-replay-1", fee_coefficient_at_fill="0.06"),
            )
        rig.hold(_slug(interior), 1)
        strategy = _claiming_continuous_strategy(
            rig, store_path=strategy_store, instrument=interior,
        )

        assert await rig.reconcile() is True, f"boot {boot}"

        (order,) = rig.cache.orders()
        assert order.strategy_id == strategy.id, f"boot {boot}: claimed, never EXTERNAL"
        (fill,) = _fills(rig.cache)
        assert str(fill.venue_order_id) == "V-REPLAY-1"
        latch = strategy._latch
        assert latch is not None
        record = latch.record(STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID))
        assert record is not None, f"boot {boot}: the reconciled fill reached on_order_filled"
        assert record.venue_order_id == "V-REPLAY-1"
        assert latch.is_family_halted() is False, f"boot {boot}"
        assert latch._store.get(LEGACY_FAMILY_HALT_KEY) is None, f"boot {boot}"
        # AM-2: a prefix scan, not a single literal -- a write to the WRONG
        # family's key must fail this pin too.
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(strategy_store)
        try:
            all_keys = {row[0] for row in conn.execute("SELECT key FROM state")}
        finally:
            conn.close()
        assert not any(k.startswith(FAMILY_HALT_KEY_PREFIX) for k in all_keys), f"boot {boot}"
        assert latch._store.get(f"{DUPLICATE_FILL_KEY_PREFIX}V-REPLAY-1") is None, f"boot {boot}"
        strategy.stop()
        await rig.client._disconnect()


# ---------------------------------------------------------------------------
# AUD-13c (increment B2; ruling R-2 = R2-B conditional) -- the composed
# continuous strategy claims its station's instruments, so a reconciled fill
# books under the Breezy strategy id, never ``StrategyId("EXTERNAL")``
# (``live/execution_engine.py:3551-3572``).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_claimed_instrument_reconciles_under_the_breezy_strategy_id(
    tmp_path: Path,
) -> None:
    from nautilus_trader.model.identifiers import InstrumentId, StrategyId, Symbol
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    from breezy.strategy.current_rung_hold.composition import (
        build_continuous_rung_hold_strategies,
    )
    from tests.unit.test_continuous_rung_hold_strategy import _cont_latch_factory
    from tests.unit.test_current_rung_hold_strategy import CLIMATE_DAY, _instrument

    rung = _instrument(
        InstrumentId(Symbol("tc-temp-laxhigh-2026-09-04-gte86lt87f"), POLYMARKET_US_VENUE),
        lower_f=86,
        upper_f=87,
    )
    catalog_root = tmp_path / "catalog"
    ParquetDataCatalog(str(catalog_root)).write_data([rung])
    (strategy,) = build_continuous_rung_hold_strategies(
        catalog_root=catalog_root,
        today_by_station={"LAX": CLIMATE_DAY},
        trial_day_latch_factory=_cont_latch_factory(tmp_path / "strategy.db"),
        enable_position_monitor=False,
    )

    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(rung,))
    # Exactly what `Trader.add_strategy` does with a composed strategy
    # (`trading/trader.py:435`).
    rig.engine.register_external_order_claims(strategy)
    await rig.client._connect()
    rig.client.record_fill(
        _record(rung, venue_order_id="V-CLAIM-1", client_order_id="O-CLAIM-1",
                cost="0.40", trade_id="trd-claim-1", fee_coefficient_at_fill="0.06"),
    )
    rig.hold(_slug(rung), 1)

    assert await rig.reconcile() is True

    (order,) = rig.cache.orders()
    assert str(strategy.id) == "ContinuousRungHoldStrategy-LAX"
    assert order.strategy_id == strategy.id
    assert order.strategy_id != StrategyId("EXTERNAL")
    assert order.tags is None, "a claimed order carries no VENUE/RECONCILIATION tag"
    (position,) = rig.cache.positions(instrument_id=rung.id)
    assert str(position.id).endswith("-ContinuousRungHoldStrategy-LAX"), position.id
    assert position.strategy_id == strategy.id
    assert rig.cache.positions(strategy_id=StrategyId("EXTERNAL")) == []
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_yesterdays_no_leg_fill_reconciles_under_the_breezy_strategy_id(
    tmp_path: Path,
) -> None:
    """The claim covers the NO leg (``^no`` composite id) of YESTERDAY's
    market too: the daily boot reconciles a fill whose market has not yet
    settled, and a NO buy fills on the NO-leg id."""
    import datetime as dt

    from nautilus_trader.model.identifiers import InstrumentId, Symbol
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id
    from breezy.domain.weather_bucket_facts import CLIMATE_DAY_KEY
    from breezy.strategy.current_rung_hold.composition import (
        build_continuous_rung_hold_strategies,
    )
    from tests.unit.test_continuous_rung_hold_strategy import _cont_latch_factory
    from tests.unit.test_current_rung_hold_strategy import CLIMATE_DAY, _instrument

    today_slug = "tc-temp-laxhigh-2026-09-04-gte86lt87f"
    yesterday_slug = "tc-temp-laxhigh-2026-09-03-gte86lt87f"
    today = _instrument(
        InstrumentId(Symbol(today_slug), POLYMARKET_US_VENUE), lower_f=86, upper_f=87,
    )
    yesterday_info = dict(today.info)
    yesterday_info[CLIMATE_DAY_KEY] = (CLIMATE_DAY - dt.timedelta(days=1)).isoformat()
    yesterday_yes = BinaryOption.from_dict(
        {
            **BinaryOption.to_dict(today),
            "id": f"{yesterday_slug}.POLYMARKET_US",
            "raw_symbol": yesterday_slug,
            "info": yesterday_info,
        },
    )
    yesterday_no = _instrument(no_leg_instrument_id(yesterday_slug), lower_f=86, upper_f=87)
    catalog_root = tmp_path / "catalog"
    ParquetDataCatalog(str(catalog_root)).write_data([today, yesterday_yes])
    (strategy,) = build_continuous_rung_hold_strategies(
        catalog_root=catalog_root,
        today_by_station={"LAX": CLIMATE_DAY},
        trial_day_latch_factory=_cont_latch_factory(tmp_path / "strategy.db"),
        enable_position_monitor=False,
    )
    assert yesterday_no.id in strategy.external_order_claims

    rig = _Rig(asyncio.get_running_loop(), tmp_path, cached=(yesterday_yes, yesterday_no))
    rig.engine.register_external_order_claims(strategy)
    await rig.client._connect()
    rig.client.record_fill(
        _record(yesterday_no, venue_order_id="V-NOCLAIM-1", client_order_id="O-NOCLAIM-1",
                cost="0.09", trade_id="trd-noclaim-1", fee_coefficient_at_fill="0.06"),
    )
    rig.hold(yesterday_slug, 1, no_leg=True)

    assert await rig.reconcile() is True

    (order,) = rig.cache.orders()
    assert order.instrument_id == yesterday_no.id
    assert order.strategy_id == strategy.id
    (position,) = rig.cache.positions(instrument_id=yesterday_no.id)
    assert position.strategy_id == strategy.id
    await rig.client._disconnect()
