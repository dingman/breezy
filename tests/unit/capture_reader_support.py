"""Shared builders for the AUT-1 WP1 part B reader and forecast-ref tests.

Every stream is written by the real ``CaptureStreamWriter`` over a real native
``StreamingFeatherWriter`` on ``tmp_path``; nothing here fakes the on-disk format.
"""

from pathlib import Path
from typing import Any

from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderFilled, OrderInitialized
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.forecast_point import ForecastPoint
from breezy.persistence.autonomy.capture_records import (
    CaptureHeartbeat,
    DecisionRecord,
    DetectorEvent,
    FrameCopy,
    OrderEventRecord,
    make_record,
)
from breezy.persistence.autonomy.capture_stream import CaptureStreamWriter
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_VARIABLES
from tests.unit.aut1_premises_support import (
    _STRATEGY,
    _TRADER,
    RECORDED_ORDER_FILLED,
    _clock_at,
    _filled_from_recorded,
    _initialized,
)

HOUR_NS = 3_600_000_000_000
T10 = "2026-10-04T10:00:00.000000000Z"
INSTANCE = "inst-1"
STATION = "KLAX"
STD_OFFSET_HOURS = -8.0
YES_INSTRUMENT = "tc-temp-laxhigh-2026-10-04-gte93lt94f.POLYMARKET_US"
FAMILY = "pm_us_fq_test"


def open_stream(
    root: Path, *, instance_id: str = INSTANCE, source: str = "live"
) -> CaptureStreamWriter:
    stream = CaptureStreamWriter(root=root, instance_id=instance_id, source=source)
    assert stream.open(TestComponentStubs.cache(), _clock_at(T10)) is True
    return stream


def boot_dir(root: Path, *, instance_id: str = INSTANCE, source: str = "live") -> Path:
    return root / source / instance_id


def decision(n: int = 1, **fields: Any) -> DecisionRecord:
    base: dict[str, Any] = {
        "ts_event": n,
        "ts_init": 1000 + n,
        "schema": "capture_decision/v2",
        "decision_id": f"d{n}",
        "family_id": FAMILY,
        "kind": "Take",
        "eval_ns": n,
        "eval_seq": 0,
        "station": "LAX",
        "instrument": YES_INSTRUMENT,
        "frame_kind": "depth10",
        "frame_ts_event": 500 + n,
        "forecast_station": STATION,
        "forecast_cycle_ns": 100 * HOUR_NS,
        "forecast_available_at_ns": 102 * HOUR_NS,
    }
    base.update(fields)
    return make_record(DecisionRecord, **base)


def frame_copy(decision_id: str, *, body: dict[str, Any] | None = None, **fields: Any) -> Any:
    base: dict[str, Any] = {
        "ts_event": 501,
        "ts_init": 1501,
        "schema": "capture_frame_copy/v1",
        "decision_id": decision_id,
        "frame_kind": "depth10",
        "instrument": YES_INSTRUMENT,
        "frame_ts_event": 501,
        "frame_body": {"ask": "0.15"} if body is None else body,
    }
    base.update(fields)
    return make_record(FrameCopy, **base)


def order_event(event_type: str, client_order_id: str, **fields: Any) -> Any:
    base: dict[str, Any] = {
        "ts_event": 700,
        "ts_init": 1700,
        "schema": "capture_order_event/v1",
        "event_type": event_type,
        "client_order_id": client_order_id,
    }
    base.update(fields)
    return make_record(OrderEventRecord, **base)


def detector(**fields: Any) -> Any:
    base: dict[str, Any] = {
        "ts_event": 800,
        "ts_init": 1800,
        "schema": "capture_detector_event/v2",
        "detector": "md_feed_freshness",
        "state": "AGREE",
    }
    base.update(fields)
    return make_record(DetectorEvent, **base)


def heartbeat(seq: int = 1) -> Any:
    return make_record(
        CaptureHeartbeat,
        ts_event=900 + seq,
        ts_init=900 + seq,
        schema="capture_heartbeat/v1",
        seq=seq,
        health_ok=True,
    )


def forecast_point(
    variable: str,
    value: float | None,
    *,
    cycle_ns: int = 100 * HOUR_NS,
    lag_ns: int = 2 * HOUR_NS,
    issuance_seq: int = 0,
    station: str = STATION,
    model: str = "NBM_NBP",
    model_version: str = "5.0",
) -> ForecastPoint:
    return ForecastPoint(
        station=station,
        model=model,
        model_version=model_version,
        variable=variable,
        cycle_runtime_ns=cycle_ns,
        valid_start_ns=cycle_ns + 10 * HOUR_NS,
        valid_end_ns=cycle_ns + 30 * HOUR_NS,
        value_f=value,
        issuance_seq=issuance_seq,
        measured_publication_lag_ns=lag_ns,
        available_at_ns=cycle_ns + lag_ns,
        ingested_at_ns=cycle_ns + lag_ns + 1,
        absence_reason=None if value is not None else "not_published",
    )


def full_cycle(
    *, cycle_ns: int = 100 * HOUR_NS, lag_ns: int = 2 * HOUR_NS, base: float = 70.0, **kw: Any
) -> list[ForecastPoint]:
    return [
        forecast_point(variable, base + i, cycle_ns=cycle_ns, lag_ns=lag_ns, **kw)
        for i, variable in enumerate(NBP_QUANTILE_VARIABLES)
    ]


def write_all(stream: CaptureStreamWriter, objects: list[Any]) -> None:
    for obj in objects:
        assert stream.write(obj) is True, type(obj).__name__
    assert stream.flush() is True


def initialized(
    *, client_order_id: str, price: str, tags: list[str] | None, instrument_id: Any = None
) -> OrderInitialized:
    return _initialized(
        instrument_id=instrument_id or InstrumentId.from_str(YES_INSTRUMENT),
        client_order_id=client_order_id,
        price=price,
        tags=tags,
        ts_init=2_000,
    )


def filled(client_order_id: str, *, trade_id: str = "T-1", venue_order_id: str = "V-1") -> Any:
    recorded = (
        RECORDED_ORDER_FILLED.replace("O-20261002-202032-L001-LAX-1", client_order_id)
        .replace("CVWEANWH8YHR", trade_id)
        .replace("CVW455HKJYGE", venue_order_id)
    )
    fill: OrderFilled = _filled_from_recorded(recorded)
    return fill


def limit_order(
    instrument_id: InstrumentId, price: str, tags: list[str] | None, *, ordinal: int = 1
) -> Any:
    """A real BUY IOC ``LimitOrder`` (the shape FQ submits); ``order.init_event`` is what streams.

    ``ordinal`` is the client-order-id counter: two orders with the same ordinal share an id."""
    factory = OrderFactory(
        trader_id=_TRADER, strategy_id=_STRATEGY, clock=_clock_at("2026-10-04T12:00:00.000000000Z")
    )
    factory.set_client_order_id_count(ordinal - 1)
    return factory.limit(
        instrument_id=instrument_id,
        order_side=OrderSide.BUY,
        quantity=Quantity.from_str("1.00"),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
        tags=tags,
    )
