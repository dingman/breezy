"""Unit tests for `breezy.runtime.backtest_feed` -- the backtest wiring seam.

Scope: the ONE `ClientId` under which weather custom data is registered in a
backtest, and the `CustomData` wrapping that makes weather records survive
`DataEngine._handle_data`. Both are pinned against a REAL `BacktestEngine`
rather than against the type contract alone, because both defects they close
are invisible to a type check and to an equality assertion.

The two defects, measured against the installed `nautilus-trader==1.231.0`
-----------------------------------------------------------------------------

**D1 -- a bare record is logged and DROPPED.** `DataEngine._handle_data`
(`data/engine.pyx:2544-2573`) dispatches on `isinstance`; its terminal `else`
calls `self._log.error("Cannot handle data: unrecognized type ...")` and
returns. It does not raise. `breezy.persistence.catalog.read_climate_days`
returns records UNWRAPPED by design (its own docstring says so, and `on_data`
delivers that shape), so the obvious `add_data(read_climate_days(catalog))`
loses every record to an ERROR line in a log nobody is reading. Pinned by
`test_bare_records_added_to_a_backtest_are_silently_dropped`.

**D2 -- the two call sites can disagree about the client.** `add_data(...,
client_id=X)` registers a `BacktestDataClient` under `X`; a subscriber naming
`Y` has its `SubscribeData` command dropped by `DataEngine._execute_command`
with an ERROR line ("no data client configured for ... `client_id` Y") and no
exception. One shared module constant is the only thing that makes the two
sites agree by construction rather than by proofreading. Pinned by
`test_a_client_id_the_backtest_never_registered_is_refused_silently`.

A THIRD hazard is pinned here without being fixed, because it cannot be:
`Actor.subscribe_data(..., instrument_id=...)` scopes the message-bus topic
to that instrument while `DataType(NwsClimateDay).topic` carries no
instrument, so an instrument-scoped subscription to weather data receives
NOTHING. See `test_an_instrument_scoped_subscription_receives_nothing`.

Nothing here touches the network or the filesystem: every record is built in
memory and the backtest runs with no venue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from nautilus_trader.backtest.data_client import BacktestDataClient
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.core.data import Data
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.data.messages import SubscribeData
from nautilus_trader.model.data import DataType
from nautilus_trader.model.identifiers import ClientId, InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest.nws_actor import nws_climate_day_data_type, nws_raw_product_data_type
from breezy.runtime.backtest_feed import (
    NWS_BACKTEST_CLIENT_ID,
    UnfeedableRecordError,
    as_backtest_data,
)
from tests.unit.test_persistence_catalog import (
    _RETRIEVED_NS,
    make_climate_day,
    make_raw_product,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

TRADER_ID = TraderId("BACKTEST-001")

#: Any instrument at all; only its SCOPING effect on the topic is under test.
WEATHER_MARKET = InstrumentId(Symbol("nyc-high-lt79"), Venue("POLYMARKET_US"))


def climate_days(count: int) -> list[NwsClimateDay]:
    """`count` distinct records, ascending in `ts_init` as the engine requires."""
    return [make_climate_day(retrieved_at_ns=_RETRIEVED_NS + i) for i in range(count)]


def raw_products(count: int) -> list[NwsRawProduct]:
    return [
        make_raw_product(
            retrieved_at_ns=_RETRIEVED_NS + i,
            raw_text=f"CDUS41 KOKX 230627\nCLINYC\n{i}\n",
            product_uuid=f"00000000-0000-4000-8000-00000000000{i}",
        )
        for i in range(count)
    ]


class Collector(Actor):  # type: ignore[misc]  # Actor is a compiled Cython class erasing to Any
    """The minimal subscriber. Deliberately an `Actor`, not a `Strategy`.

    A `Strategy` is what would call `submit_order`; introducing one is a
    separate change, and the read-only cage pinned by
    `tests/unit/test_runtime_node_config.py` says so.
    """

    def __init__(
        self,
        data_type: DataType,
        *,
        client_id: ClientId | None = NWS_BACKTEST_CLIENT_ID,
        instrument_id: InstrumentId | None = None,
    ) -> None:
        super().__init__()
        self._data_type = data_type
        self._client_id = client_id
        self._instrument_id = instrument_id
        self.received: list[Any] = []

    def on_start(self) -> None:
        self.subscribe_data(
            self._data_type,
            client_id=self._client_id,
            instrument_id=self._instrument_id,
        )

    def on_data(self, data: Any) -> None:
        self.received.append(data)


def run_backtest(payload: Sequence[Data], collector: Collector) -> list[Any]:
    """Feed `payload` to a real `BacktestEngine` and return what arrived."""
    engine = BacktestEngine(BacktestEngineConfig(trader_id=TRADER_ID))
    try:
        engine.add_data(list(payload), client_id=NWS_BACKTEST_CLIENT_ID)
        engine.add_actor(collector)
        engine.run()
        return list(collector.received)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# D1 -- the drop, and the wrapper that closes it
# ---------------------------------------------------------------------------


def test_bare_records_added_to_a_backtest_are_silently_dropped() -> None:
    """The hazard itself, pinned rather than assumed.

    This is the shape `read_climate_days` returns, fed the obvious way. Zero
    records arrive and the run completes successfully -- the only trace is an
    ERROR line per record from `DataEngine._handle_data`.
    """
    collector = Collector(nws_climate_day_data_type())

    received = run_backtest(climate_days(3), collector)

    assert received == []


def test_wrapped_climate_days_are_delivered_unwrapped_and_in_order() -> None:
    """The fix: same records, wrapped, all three arrive as bare records.

    `DataEngine._handle_data` publishes `data.data` on the `CustomData`'s own
    topic, so a subscriber's `on_data` sees the record itself -- the wrapper is
    a transport envelope, not a change of handler contract.
    """
    records = climate_days(3)
    collector = Collector(nws_climate_day_data_type())

    received = run_backtest(as_backtest_data(records), collector)

    assert len(received) == 3
    assert all(type(item) is NwsClimateDay for item in received)
    assert [item.ts_init for item in received] == [r.ts_init for r in records]


def test_wrapped_raw_products_are_delivered_unwrapped() -> None:
    """The second record class travels the same seam."""
    records = raw_products(2)
    collector = Collector(nws_raw_product_data_type())

    received = run_backtest(as_backtest_data(records), collector)

    assert len(received) == 2
    assert all(type(item) is NwsRawProduct for item in received)


def test_the_wrapper_uses_the_shared_data_type_factories_by_identity() -> None:
    """Not merely an EQUAL `DataType` -- the same cached object.

    Equality is the weak check here: `DataType(cls, {"p": 1, "q": 2})` and
    `DataType(cls, {"q": 2, "p": 1})` compare equal with equal hashes while
    their `.topic` strings differ, so an equality assertion would pass on a
    `DataType` that routes somewhere else. Identity is what the shared
    factories exist to provide.
    """
    wrapped = as_backtest_data([*climate_days(1), *raw_products(1)])

    assert [w.data_type for w in wrapped] == [
        nws_climate_day_data_type(),
        nws_raw_product_data_type(),
    ]
    assert wrapped[0].data_type is nws_climate_day_data_type()
    assert wrapped[1].data_type is nws_raw_product_data_type()


def test_the_wrapper_preserves_the_record_object_itself() -> None:
    records = climate_days(2)

    wrapped = as_backtest_data(records)

    assert [w.data for w in wrapped] == records
    assert all(w.data is r for w, r in zip(wrapped, records, strict=True))


def test_an_empty_feed_wraps_to_an_empty_feed() -> None:
    assert as_backtest_data([]) == []


def test_a_record_class_with_no_shared_data_type_is_refused_loudly() -> None:
    """The one place this seam is allowed to be strict.

    A record class the factories do not cover has no canonical topic, so
    wrapping it would invent one. Refusing is the whole point: the failure
    mode being closed here is a SILENT drop, and a silent invention is the
    same defect wearing a wrapper.
    """

    class NotWeather(Data):  # type: ignore[misc]  # Data is a compiled Cython class erasing to Any
        @property
        def ts_event(self) -> int:
            return 0

        @property
        def ts_init(self) -> int:
            return 0

    with pytest.raises(UnfeedableRecordError):
        as_backtest_data([make_climate_day(), NotWeather()])


# ---------------------------------------------------------------------------
# D2 -- one `ClientId`, named once
# ---------------------------------------------------------------------------


def test_the_canonical_client_id_carries_both_call_sites() -> None:
    """`add_data(client_id=...)` and `subscribe_data(client_id=...)` agree.

    `run_backtest` supplies the constant to `add_data`; `Collector` defaults
    to the same constant for `subscribe_data`. Neither call site names a
    string literal, which is exactly the property under test.
    """
    collector = Collector(nws_climate_day_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)

    received = run_backtest(as_backtest_data(climate_days(1)), collector)

    assert len(received) == 1


def test_a_client_id_the_backtest_never_registered_is_refused_silently() -> None:
    """The mismatch's real signature: a dropped command, not an exception.

    `DataEngine._execute_command` resolves the client from `client_id`, and on
    a miss logs "no data client configured for ... `client_id` ..." and
    returns. The subscription simply never reaches a client -- which in a
    backtest means nothing warms up, nothing requests, and nothing complains.
    """
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    client = BacktestDataClient(
        client_id=NWS_BACKTEST_CLIENT_ID, msgbus=msgbus, cache=cache, clock=clock
    )
    engine.register_client(client)

    def subscribe(client_id: ClientId) -> None:
        engine.execute(
            SubscribeData(
                data_type=nws_climate_day_data_type(),
                instrument_id=None,
                client_id=client_id,
                venue=None,
                command_id=UUID4(),
                ts_init=0,
            )
        )

    subscribe(ClientId(NWS_BACKTEST_CLIENT_ID.value + "-TYPO"))
    assert client.subscribed_custom_data() == []

    subscribe(NWS_BACKTEST_CLIENT_ID)
    assert nws_climate_day_data_type() in client.subscribed_custom_data()


# ---------------------------------------------------------------------------
# The third hazard: instrument scoping, pinned as UNUSABLE
# ---------------------------------------------------------------------------


def test_an_instrument_scoped_subscription_receives_nothing() -> None:
    """Why the client, and not the instrument, is the scoping key here.

    `DataType(NwsClimateDay).topic` is `"NwsClimateDay*"`, so the published
    topic is `"data.NwsClimateDay*"`, while an instrument-scoped subscription
    builds the pattern `"data.NwsClimateDay.POLYMARKET_US.nyc-high-lt79"`.
    `is_matching_py` (`common/component`) returns False for that pair, so the
    subscriber receives ZERO records while every log line reads normally.

    A weather record is not per-market data -- one climate day settles many
    markets -- so the fix is to scope by client, never to bolt an
    `instrument_id` onto the subscription.
    """
    collector = Collector(
        nws_climate_day_data_type(),
        client_id=NWS_BACKTEST_CLIENT_ID,
        instrument_id=WEATHER_MARKET,
    )

    received = run_backtest(as_backtest_data(climate_days(3)), collector)

    assert received == []
