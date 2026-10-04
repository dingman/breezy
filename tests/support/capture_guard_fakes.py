"""Shared fakes and builders for the AUT-1 WP2 adapter and guard tests.

``RecordingStream`` is a duck-typed ``StreamLike`` that records every write and flush in ONE
ordered list, so a test can assert the order a Take-path publish happened in. ``RecordingOutbox``
is the node outbox's ``offer(event, severity, detail)`` seam. ``registered_guard`` builds a real,
registered Nautilus ``Strategy`` subclass and captures the commands it routes to the risk engine.
Nothing here imports another test module.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from nautilus_trader.common.component import TestClock
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.trading.config import StrategyConfig

from breezy.persistence.autonomy.capture_publish import (
    CaptureHealth,
    CapturePublisher,
    StreamCounters,
)
from breezy.strategy.autonomy_capture.guarded_strategy import (
    CaptureGuardedStrategy,
    CaptureIdentity,
)

__all__ = [
    "ARTEFACT",
    "FAMILY",
    "MANIFEST",
    "NOW_NS",
    "YES_ID",
    "GuardHarness",
    "RecordingOutbox",
    "RecordingStream",
    "build_depth",
    "build_quote",
    "identity",
    "registered_guard",
]

FAMILY: Final[str] = "pm_us_fq_test"
ARTEFACT: Final[str] = "a" * 64
MANIFEST: Final[str] = "b" * 64
DEPTH_LEVELS: Final[int] = 10
NOW_NS: Final[int] = 1_700_000_000_000_000_000
YES_ID: Final[InstrumentId] = InstrumentId(Symbol("lax-80-81"), Venue("POLYMARKET_US"))


def identity(**overrides: Any) -> CaptureIdentity:
    fields: dict[str, Any] = {
        "family_id": FAMILY,
        "node_boot_id": "boot-1",
        "build_sha": "c" * 40,
        "registry_seq": 7,
        "drill": False,
        "source": "live",
        "artefact_sha256": ARTEFACT,
        "manifest_sha256": MANIFEST,
    }
    fields.update(overrides)
    return CaptureIdentity(**fields)


class RecordingStream:
    """``StreamLike`` with one ordered event list: ``("write", record)`` and ``("flush", None)``."""

    def __init__(self) -> None:
        self.health = CaptureHealth()
        self.events: list[tuple[str, object]] = []
        self.write_ok = True
        self.flush_ok = True
        self.pending_drops = 0

    def write(self, obj: object) -> bool:
        if not self.write_ok:
            self.health.mark_failed("write_dropped:test")
            return False
        self.events.append(("write", obj))
        return True

    def flush(self) -> bool:
        self.events.append(("flush", None))
        return self.flush_ok

    def consume_drops_since_submit_flush(self) -> int:
        drops, self.pending_drops = self.pending_drops, 0
        return drops

    def counters(self) -> StreamCounters:
        return StreamCounters(written_by_type={}, write_failures=0, write_drops=0)

    @property
    def written(self) -> list[Any]:
        return [obj for kind, obj in self.events if kind == "write"]

    def written_of(self, record_type: type) -> list[Any]:
        return [obj for obj in self.written if isinstance(obj, record_type)]

    @property
    def flushes(self) -> int:
        return sum(1 for kind, _ in self.events if kind == "flush")


class RecordingOutbox:
    def __init__(self, *, accept: bool = True) -> None:
        self.offers: list[tuple[str, str, str]] = []
        self.accept = accept

    def offer(self, event: str, severity: str, detail: str) -> bool:
        self.offers.append((event, severity, detail))
        return self.accept


def build_depth(
    *,
    ts_event: int,
    bids: tuple[tuple[str, str], ...] = (("0.14", "10"),),
    asks: tuple[tuple[str, str], ...] = (("0.15", "20"), ("0.16", "5")),
    instrument_id: InstrumentId = YES_ID,
) -> OrderBookDepth10:
    def side(levels: tuple[tuple[str, str], ...], order_side: OrderSide) -> list[BookOrder]:
        # A Depth10 always carries ten levels a side; a short side is padded with size-0 levels.
        padded = [*levels, *[("0.00", "0")] * (DEPTH_LEVELS - len(levels))]
        return [
            BookOrder(order_side, Price.from_str(px), Quantity.from_str(sz), i)
            for i, (px, sz) in enumerate(padded)
        ]

    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=side(bids, OrderSide.BUY),
        asks=side(asks, OrderSide.SELL),
        bid_counts=[1] * DEPTH_LEVELS,
        ask_counts=[1] * DEPTH_LEVELS,
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_event,
    )


def build_quote(
    *, ts_event: int, bid: str = "0.14", ask: str = "0.15", instrument_id: InstrumentId = YES_ID
) -> QuoteTick:
    return QuoteTick(
        instrument_id,
        Price.from_str(bid),
        Price.from_str(ask),
        Quantity.from_str("10"),
        Quantity.from_str("20"),
        ts_event,
        ts_event,
    )


@dataclass
class GuardHarness:
    strategy: Any
    stream: RecordingStream
    outbox: RecordingOutbox
    publisher: CapturePublisher
    commands: list[Any] = field(default_factory=list)

    def order(
        self,
        *,
        side: OrderSide = OrderSide.BUY,
        tags: list[str] | None = None,
        price: str = "0.15",
    ) -> Any:
        return self.strategy.order_factory.limit(
            instrument_id=YES_ID,
            order_side=side,
            quantity=Quantity.from_int(1),
            price=Price.from_str(price),
            time_in_force=TimeInForce.IOC,
            tags=tags,
        )

    def in_cache(self, order: Any) -> bool:
        return bool(self.strategy.cache.order_exists(order.client_order_id))


def registered_guard(
    *,
    strategy_cls: Callable[..., Any] = CaptureGuardedStrategy,
    publisher_cls: type[CapturePublisher] = CapturePublisher,
    outbox: RecordingOutbox | None = None,
    stream: RecordingStream | None = None,
    capture_identity: CaptureIdentity | None = None,
) -> GuardHarness:
    stream = stream if stream is not None else RecordingStream()
    outbox = outbox if outbox is not None else RecordingOutbox()
    publisher = publisher_cls(stream, family_id=FAMILY, alert_offer=outbox.offer)
    strategy = strategy_cls(
        StrategyConfig(strategy_id="GUARD-001"),
        capture_publisher=publisher,
        alert_outbox=outbox,
        capture_identity=capture_identity if capture_identity is not None else identity(),
    )
    clock = TestClock()
    clock.set_time(NOW_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=Portfolio(msgbus=msgbus, cache=cache, clock=clock),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    harness = GuardHarness(strategy=strategy, stream=stream, outbox=outbox, publisher=publisher)
    msgbus.register(endpoint="RiskEngine.execute", handler=harness.commands.append)
    return harness
