"""AUT-1 WP0 premises, V-6, V-7, V-14 item 10: order stream, cache ordering, fill index day key.

Shared helpers live in ``aut1_premises_support`` (WP0-R10).
"""

import hashlib
import json
from types import SimpleNamespace
from typing import Any, cast

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.model.enums import (
    OrderSide,
    TimeInForce,
    order_side_from_str,
    time_in_force_from_str,
)
from nautilus_trader.model.events import (
    OrderInitialized,
)
from nautilus_trader.model.identifiers import (
    InstrumentId,
)
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.serialization.arrow.serializer import (
    ArrowSerializer,
)
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.test_kit.stubs.data import TestDataStubs

from breezy.adapters.polymarket_us.exec.submit_chain import intent_fingerprint
from breezy.adapters.polymarket_us.symbology import leg_of, no_leg_instrument_id
from tests.unit.aut1_premises_support import (
    _STRATEGY,
    _TRADER,
    NS,
    _clock_at,
)

# ---------------------------------------------------------------------------
# V-6  streamed OrderInitialized forms recompute intent_fingerprint
# ---------------------------------------------------------------------------


def _limit_order(instrument_id: InstrumentId, price: str) -> Any:
    clock = _clock_at("2026-10-04T12:00:00.000000000Z")
    factory = OrderFactory(trader_id=_TRADER, strategy_id=_STRATEGY, clock=clock)
    return factory.limit(
        instrument_id=instrument_id,
        order_side=OrderSide.BUY,
        quantity=Quantity.from_str("1.00"),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
        tags=["premise-tag"],
    )


def _fingerprint_from_stream_row(row: dict[str, Any], *, map_enums: bool) -> str:
    side = row["order_side"]
    tif = row["time_in_force"]
    if map_enums:
        side = str(order_side_from_str(side))
        tif = str(time_in_force_from_str(tif))
    payload = "\n".join(
        (
            row["instrument_id"],
            side,
            row["quantity"],
            json.loads(row["options"])["price"],
            tif,
            row["client_order_id"],
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_order_initialized_stream_fields_recompute_intent_fingerprint() -> None:
    """V-6, against a real ``LimitOrder`` on the YES and the NO leg.

    FINDING (the plan's "If it fails" branch applies): the streamed ``order_side`` and
    ``time_in_force`` are enum NAMES (``BUY``, ``IOC``) but ``intent_fingerprint`` hashes
    ``str(order.side)`` and ``str(order.time_in_force)``, which are the enum INTEGER values
    (``1``, ``2``). The raw streamed strings do NOT recompute the fingerprint; mapping the names
    back through ``order_side_from_str`` / ``time_in_force_from_str`` and ``str()`` does. The
    price is only in the ``options`` JSON (the ``price`` column is null). The reader owns this map.

    MUTATION (red): reading the null ``price`` column instead of ``options['price']`` yields
    ``'None'`` and a different digest.
    """
    yes = InstrumentId.from_str("tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US")
    no = no_leg_instrument_id("tc-temp-laxhigh-2026-10-04-gte93lt94f")
    assert (leg_of(yes), leg_of(no)) == ("yes", "no")
    for instrument_id, price in ((yes, "0.15"), (no, "0.85")):
        order = _limit_order(instrument_id, price)
        batch = ArrowSerializer.serialize_batch([order.init_event], data_cls=OrderInitialized)
        (row,) = batch.to_pylist()
        expected = intent_fingerprint(order)
        assert _fingerprint_from_stream_row(row, map_enums=True) == expected
        assert _fingerprint_from_stream_row(row, map_enums=False) != expected
        assert (str(order.side), str(order.time_in_force)) == ("1", "2")
        assert (row["order_side"], row["time_in_force"]) == ("BUY", "IOC")
        assert row["price"] is None


# ---------------------------------------------------------------------------
# V-7  the cache is populated before the strategy handler runs
# ---------------------------------------------------------------------------


def _data_engine_with_actor() -> tuple[DataEngine, Any, list[tuple[str, bool]], Any, MessageBus]:
    clock = TestClock()
    bus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=bus, cache=cache, clock=clock)
    instrument = TestInstrumentProvider.equity()
    cache.add_instrument(instrument)
    seen: list[tuple[str, bool]] = []

    class Probe(Actor):  # type: ignore[misc]
        def on_quote_tick(self, tick: Any) -> None:
            seen.append(("quote", self.cache.quote_tick(tick.instrument_id) is not None))

        def on_order_book_depth(self, depth: Any) -> None:
            seen.append(("depth", self.cache.quote_tick(depth.instrument_id) is not None))

    probe = Probe()
    probe.register_base(
        portfolio=TestComponentStubs.portfolio(), msgbus=bus, cache=cache, clock=clock
    )
    probe.start()
    probe.subscribe_quote_ticks(instrument.id)
    probe.subscribe_order_book_depth(instrument.id)
    return engine, instrument, seen, probe, bus


def test_quote_tick_cached_before_on_quote_tick() -> None:
    """V-7 (``engine.pyx:2716`` ``add_quote_tick`` < ``:2728`` ``publish_c``): inside
    ``on_quote_tick`` the tick is already in the cache.

    MUTATION (red): publishing the tick on the bus directly, bypassing ``DataEngine.process``,
    reaches the handler with no cached quote, so the assertion fails.
    """
    engine, instrument, seen, _probe, _bus = _data_engine_with_actor()
    engine.process(TestDataStubs.quote_tick(instrument=instrument))
    assert seen == [("quote", True)]


def test_depth_frame_is_not_cached_before_on_order_book_depth() -> None:
    """V-7 (``engine.pyx:2691-2696``): a depth frame is published first and caches no quote, so
    a depth-triggered evaluation on an instrument with no earlier quote sees none. Once a quote
    has been cached, the same handler sees it.

    MUTATION (red): ``process``-ing a quote first makes the first depth callback see a cached
    quote, so ``("depth", False)`` fails.
    """
    engine, instrument, seen, _probe, _bus = _data_engine_with_actor()
    depth = TestDataStubs.order_book_depth10(instrument_id=instrument.id)
    engine.process(depth)
    engine.process(TestDataStubs.quote_tick(instrument=instrument))
    engine.process(depth)
    assert seen == [("depth", False), ("quote", True), ("depth", True)]


# ---------------------------------------------------------------------------
# V-14 item 10  fill_by_fingerprint <day>
# ---------------------------------------------------------------------------


def test_client_order_id_embeds_utc_date() -> None:
    """V-14 item 10 (``client.py:2101-2123``, ``:4677-4681``). The Nautilus ``client_order_id``
    embeds the UTC date of the clock at creation; ``record_fill`` and ``_has_durable_fill_record``
    both key ``fill_by_fingerprint`` by ``utc_day_for_ns(intent_created_ns)``, never by the
    reading clock, across a UTC midnight.

    MUTATION (red): expecting the day of the READ time (``created_ns + 2 s``) instead of the
    creation time fails the key equality on the 23:59:59.9 case.
    """
    from breezy.adapters.polymarket_us.exec.client import (
        FILL_BY_FINGERPRINT_KEY_PREFIX,
        PolymarketUSExecutionClient,
    )

    instrument_id = InstrumentId.from_str("tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US")
    for stamp, date_tag, day in (
        ("2026-10-03T23:59:59.900000000Z", "20261003", "2026-10-03"),
        ("2026-10-04T00:00:00.000000000Z", "20261004", "2026-10-04"),
    ):
        clock = _clock_at(stamp)
        order = OrderFactory(trader_id=_TRADER, strategy_id=_STRATEGY, clock=clock).limit(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_str("1.00"),
            price=Price.from_str("0.15"),
            time_in_force=TimeInForce.IOC,
        )
        assert order.client_order_id.value.startswith(f"O-{date_tag}-")
        created_ns = clock.timestamp_ns()
        fingerprint = intent_fingerprint(order)
        reads: list[str] = []
        probe = SimpleNamespace(
            _store_get=reads.append,
            _log=SimpleNamespace(warning=lambda message: None),
        )
        assert (
            PolymarketUSExecutionClient._has_durable_fill_record(
                cast("Any", probe),
                fingerprint,
                created_ns,
            )
            is False
        )
        assert reads == [f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{fingerprint}"]

        writes: list[str] = []
        recorder = SimpleNamespace(
            _read_fill_index=lambda key: [],
            _store_set=lambda key, value, sink=writes: sink.append(key),
        )
        record = SimpleNamespace(
            instrument_id="i",
            venue_order_id="V",
            ts_event=created_ns + 2 * NS,
            to_bytes=lambda: b"{}",
        )
        PolymarketUSExecutionClient.record_fill(
            recorder,  # type: ignore[arg-type]
            record,  # type: ignore[arg-type]
            intent_fingerprint=fingerprint,
            intent_created_ns=created_ns,
        )
        assert writes[-1] == f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{fingerprint}"
