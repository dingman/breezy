"""AUT-1 WP0 part (a): characterisation of the Nautilus 1.231.0 premises AUT-1 r12 relies on.

Plan: ``docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md`` section 4
"AUT-1.WP0" (premises V-1, V-1b, V-3, V-5, V-6, V-7, V-12, V-13..V-17, V-19). Every test pins a
behaviour of native Nautilus or of existing Breezy code and carries, in its docstring, the
mutation it was shown red against (L-33).

Honesty rules (brief, binding):

* "Recorded" events are RECORDED. The three FQ lifecycle events and the resolver-inferred fill
  below are verbatim ``str(event)`` lines copied from retained node logs (provenance beside each).
  The tests rebuild the event from the repr's fields and assert ``str(event) == recorded``,
  so a field that does not round-trip fails loudly. Fields that a repr does not carry
  (``event_id``, ``ts_init``) are filled and labelled. Events no retained log contains
  (``PositionChanged``/``PositionClosed``, a NO-leg order, tagged orders) are CONSTRUCTED and
  named ``constructed``.
* ``CAPTURE_INCLUDE_TYPES`` and the capture records do not exist yet (WP1). Where a premise
  needs them, ``PremiseRecord`` and friends are minimal test-local ``@customdataclass``
  stand-ins that follow the section 3.4.1 encoding rule (``str``/``int``/``bool`` only, no
  field named ``instrument_id``). ``_JudgedWriter`` is a test-local restatement of the section
  3.4.2 per-write landing rule, not production code.
"""

import ast
import asyncio
import datetime as dt
import hashlib
import json
import logging
import re
import subprocess
import sys
import textwrap
import threading
import traceback
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast

import pandas as pd
import pyarrow as pa
import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import MessageBus, TestClock, TimeEvent
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.model.enums import (
    AssetClass,
    ContingencyType,
    LiquiditySide,
    OrderSide,
    OrderType,
    TimeInForce,
    TriggerType,
    order_side_from_str,
    time_in_force_from_str,
)
from nautilus_trader.model.events import (
    OrderFilled,
    OrderInitialized,
    PositionChanged,
    PositionClosed,
    PositionEvent,
    PositionOpened,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    InstrumentId,
    PositionId,
    StrategyId,
    TradeId,
    TraderId,
    VenueOrderId,
)
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.persistence.funcs import class_to_filename
from nautilus_trader.persistence.writer import RotationMode, StreamingFeatherWriter
from nautilus_trader.serialization.arrow.serializer import (
    ArrowSerializer,
    list_schemas,
    register_arrow,
)
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.test_kit.stubs.data import TestDataStubs
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.exec.submit_chain import intent_fingerprint
from breezy.adapters.polymarket_us.symbology import leg_of, no_leg_instrument_id
from breezy.domain.forecast_point import ForecastPoint
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.ingest.nbm_quantile_parse import parse_nbp_bulletin

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SRC_DIR: Final[Path] = REPO_ROOT / "src"
NBM_FIXTURE: Final[Path] = REPO_ROOT / "tests" / "fixtures" / "nbm" / "nbptx_t13z_excerpt.txt"
NT_ROOT: Final[Path] = Path(sys.modules["nautilus_trader"].__file__ or "").parent
NS: Final[int] = 1_000_000_000

# ---------------------------------------------------------------------------
# Recorded FQ events (verbatim reprs from retained node logs; ANSI colour stripped)
# ---------------------------------------------------------------------------

#: ``~/.local/share/breezy/logs/breezy-trade-20261002T200526Z.log`` line 19766.
RECORDED_ORDER_INITIALIZED: Final[str] = (
    "OrderInitialized(instrument_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US, "
    "client_order_id=O-20261002-202032-L001-LAX-1, side=BUY, type=LIMIT, quantity=1.00, "
    "time_in_force=IOC, post_only=False, reduce_only=False, quote_quantity=False, "
    "options={'price': '0.15', 'display_qty': None, 'expire_time_ns': 0}, "
    "emulation_trigger=NO_TRIGGER, trigger_instrument_id=None, contingency_type=NO_CONTINGENCY, "
    "order_list_id=None, linked_order_ids=None, parent_order_id=None, exec_algorithm_id=None, "
    "exec_algorithm_params=None, exec_spawn_id=None, tags=None)"
)
#: Same log, line 19766's timestamp (the repr carries no ts_init).
RECORDED_ORDER_INITIALIZED_LOG_TS: Final[str] = "2026-10-02T20:20:32.925256413Z"
#: Same log, line 19776.
RECORDED_ORDER_FILLED: Final[str] = (
    "OrderFilled(instrument_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US, "
    "client_order_id=O-20261002-202032-L001-LAX-1, venue_order_id=CVW455HKJYGE, "
    "account_id=POLYMARKET_US-MAIN, trade_id=CVWEANWH8YHR, "
    "position_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US-FORECAST-QUANTILE-LADDER-LAX, "
    "order_side=BUY, order_type=LIMIT, last_qty=1.00, last_px=0.15 USD, commission=0.01 USD, "
    "liquidity_side=TAKER, ts_event=1790972433034078620)"
)
#: Same log, line 19779.
RECORDED_POSITION_OPENED: Final[str] = (
    "PositionOpened(instrument_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US, "
    "position_id=tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US-FORECAST-QUANTILE-LADDER-LAX, "
    "account_id=POLYMARKET_US-MAIN, opening_order_id=O-20261002-202032-L001-LAX-1, "
    "closing_order_id=None, entry=BUY, side=LONG, signed_qty=1.0, quantity=1.00, peak_qty=1.00, "
    "currency=USD, avg_px_open=0.15, avg_px_close=0.0, realized_return=0.00000, "
    "realized_pnl=-0.01 USD, unrealized_pnl=0.00 USD, ts_opened=1790972433034078620, "
    "ts_last=1790972433034078620, ts_closed=0, duration_ns=0)"
)
#: ``breezy-trade-20260912T022344Z.log`` line 282: a resolver ("inferred") fill, the
#: ``-EXTERNAL`` position and a UUID ``client_order_id``.
RECORDED_INFERRED_FILL: Final[str] = (
    "OrderFilled(instrument_id=tc-temp-sfohigh-2026-09-11-gte70lt71f.POLYMARKET_US, "
    "client_order_id=7cbfa701-6b58-4076-8b62-5b1b75da8232, "
    "venue_order_id=7b73c937-3b12-599c-9684-3003ab3abb08, account_id=POLYMARKET_US-MAIN, "
    "trade_id=70dad803-d614-5541-ac47-9e3f68325e15, "
    "position_id=tc-temp-sfohigh-2026-09-11-gte70lt71f.POLYMARKET_US-EXTERNAL, order_side=BUY, "
    "order_type=LIMIT, last_qty=1.00, last_px=0.23 USD, commission=0.01 USD, "
    "liquidity_side=NO_LIQUIDITY_SIDE, ts_event=1789179826984834900)"
)

_TRADER: Final[TraderId] = TraderId("BREEZY-L001")
_STRATEGY: Final[StrategyId] = StrategyId("FORECAST-QUANTILE-LADDER")
_ACCOUNT: Final[AccountId] = AccountId("POLYMARKET_US-MAIN")
_FIELD_RE: Final[re.Pattern[str]] = re.compile(r"(\w+)=")


def _iso_ns(stamp: str) -> int:
    whole, _, frac = stamp.removesuffix("Z").partition(".")
    base = dt.datetime.fromisoformat(whole).replace(tzinfo=dt.UTC)
    return int(base.timestamp()) * NS + int(frac.ljust(9, "0"))


def _field(recorded: str, key: str) -> str:
    """The raw text of ``key=...`` inside a recorded repr (up to the next ``, key=``)."""
    start = recorded.index(f"{key}=") + len(key) + 1
    match = re.search(r", \w+=", recorded[start:])
    return recorded[start : start + match.start()] if match else recorded[start:].rstrip(")")


def _price(text: str) -> Price:
    return Price.from_str(text.split()[0])


def _instrument(instrument_id: InstrumentId) -> BinaryOption:
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description="premise instrument",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        size_precision=2,
        size_increment=Quantity.from_str("0.01"),
        activation_ns=0,
        expiration_ns=1_800_000_000_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_str("0.01"),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
    )


def _filled_from_recorded(recorded: str) -> OrderFilled:
    liquidity = {"TAKER": LiquiditySide.TAKER, "NO_LIQUIDITY_SIDE": LiquiditySide.NO_LIQUIDITY_SIDE}
    ts_event = int(_field(recorded, "ts_event"))
    return OrderFilled(
        _TRADER,
        _STRATEGY,
        InstrumentId.from_str(_field(recorded, "instrument_id")),
        ClientOrderId(_field(recorded, "client_order_id")),
        VenueOrderId(_field(recorded, "venue_order_id")),
        AccountId(_field(recorded, "account_id")),
        TradeId(_field(recorded, "trade_id")),
        PositionId(_field(recorded, "position_id")),
        OrderSide[_field(recorded, "order_side")],
        OrderType[_field(recorded, "order_type")],
        Quantity.from_str(_field(recorded, "last_qty")),
        _price(_field(recorded, "last_px")),
        USD,
        Money(Decimal(_field(recorded, "commission").split()[0]), USD),
        liquidity[_field(recorded, "liquidity_side")],
        UUID4(),  # not in the repr: a fresh id
        ts_event,
        ts_event,  # ts_init is not in the repr: set to ts_event
    )


def _initialized(
    *,
    instrument_id: InstrumentId,
    client_order_id: str,
    price: str,
    tags: list[str] | None,
    ts_init: int,
) -> OrderInitialized:
    return OrderInitialized(
        _TRADER,
        _STRATEGY,
        instrument_id,
        ClientOrderId(client_order_id),
        OrderSide.BUY,
        OrderType.LIMIT,
        Quantity.from_str("1.00"),
        TimeInForce.IOC,
        False,
        False,
        False,
        {"price": price, "display_qty": None, "expire_time_ns": 0},
        TriggerType.NO_TRIGGER,
        None,
        ContingencyType.NO_CONTINGENCY,
        None,
        None,
        None,
        None,
        None,
        None,
        tags,
        UUID4(),
        ts_init,
    )


@dataclass(frozen=True)
class RecordedLifecycle:
    """The recorded FQ YES-leg lifecycle plus the recorded resolver fill, rebuilt and verified."""

    initialized: OrderInitialized
    filled: OrderFilled
    opened: PositionOpened
    inferred_fill: OrderFilled

    def events(self) -> list[Any]:
        return [self.initialized, self.filled, self.opened, self.inferred_fill]


def _recorded_lifecycle() -> RecordedLifecycle:
    initialized = _initialized(
        instrument_id=InstrumentId.from_str(_field(RECORDED_ORDER_INITIALIZED, "instrument_id")),
        client_order_id=_field(RECORDED_ORDER_INITIALIZED, "client_order_id"),
        price="0.15",
        tags=None,
        ts_init=_iso_ns(RECORDED_ORDER_INITIALIZED_LOG_TS),
    )
    filled = _filled_from_recorded(RECORDED_ORDER_FILLED)
    position = Position(_instrument(filled.instrument_id), filled)
    opened = PositionOpened.create(position, filled, UUID4(), filled.ts_event)
    inferred = _filled_from_recorded(RECORDED_INFERRED_FILL)
    life = RecordedLifecycle(initialized, filled, opened, inferred)
    # Honesty check: every rebuilt event renders (``str``) EXACTLY as the retained log has it.
    assert str(life.initialized) == RECORDED_ORDER_INITIALIZED
    assert str(life.filled) == RECORDED_ORDER_FILLED
    assert str(life.opened) == RECORDED_POSITION_OPENED
    assert str(life.inferred_fill) == RECORDED_INFERRED_FILL
    return life


def _constructed_events(life: RecordedLifecycle) -> list[Any]:
    """CONSTRUCTED (not recorded): NO leg, tags, ``PositionChanged``, ``PositionClosed``."""
    yes_id = life.filled.instrument_id
    no_id = no_leg_instrument_id("tc-temp-laxhigh-2026-10-03-gte93lt94f")
    tagged = _initialized(
        instrument_id=no_id,
        client_order_id="O-20261002-202033-L001-LAX-2",
        price="0.85",
        tags=["decision_id=constructed-not-recorded"],
        ts_init=life.initialized.ts_init + 1,
    )
    position = Position(_instrument(yes_id), life.filled)
    add = _filled_from_recorded(
        RECORDED_ORDER_FILLED.replace("O-20261002-202032-L001-LAX-1", "O-X-2")
    )
    changed_fill = OrderFilled(
        _TRADER,
        _STRATEGY,
        yes_id,
        ClientOrderId("O-X-2"),
        VenueOrderId("V-X-2"),
        _ACCOUNT,
        TradeId("T-X-2"),
        life.filled.position_id,
        OrderSide.BUY,
        OrderType.LIMIT,
        Quantity.from_str("1.00"),
        Price.from_str("0.16"),
        USD,
        Money(Decimal("0.01"), USD),
        LiquiditySide.TAKER,
        UUID4(),
        add.ts_event + 1,
        add.ts_event + 1,
    )
    position.apply(changed_fill)
    changed = PositionChanged.create(position, changed_fill, UUID4(), changed_fill.ts_event)
    closing_fill = OrderFilled(
        _TRADER,
        _STRATEGY,
        yes_id,
        ClientOrderId("O-X-3"),
        VenueOrderId("V-X-3"),
        _ACCOUNT,
        TradeId("T-X-3"),
        life.filled.position_id,
        OrderSide.SELL,
        OrderType.LIMIT,
        Quantity.from_str("2.00"),
        Price.from_str("0.20"),
        USD,
        Money(Decimal("0.01"), USD),
        LiquiditySide.TAKER,
        UUID4(),
        add.ts_event + 2,
        add.ts_event + 2,
    )
    position.apply(closing_fill)
    closed = PositionClosed.create(position, closing_fill, UUID4(), closing_fill.ts_event)
    return [tagged, changed, closed]


# ---------------------------------------------------------------------------
# Test-local stand-ins (section 3.4.1 encoding rule) and the real writer on tmp_path
# ---------------------------------------------------------------------------


@customdataclass
class PremiseRecord:
    """Stand-in for ``DecisionRecord``: ``str``/``int``/``bool`` only; no ``instrument_id``."""

    schema: str = ""
    decision_id: str = ""
    eval_ns: int = 0
    drill: bool = False


@customdataclass
class PremiseSibling:
    """A second stand-in table, for per-table independence."""

    schema: str = ""
    n: int = 0


@customdataclass
class PremiseWithInstrumentId:
    """The V-5 MUTATION: a field named ``instrument_id`` reroutes the writer per instrument."""

    schema: str = ""
    instrument_id: InstrumentId = InstrumentId.from_str("absent-from-cache.POLYMARKET_US")


class PremiseEmptyEncoding:
    """Registered with an encoder that yields zero rows: the writer's empty-serialisation drop."""

    ts_event = 0
    ts_init = 0


_EMPTY_SCHEMA: Final[pa.Schema] = pa.schema([("n", pa.int64())])
register_arrow(
    PremiseEmptyEncoding,
    _EMPTY_SCHEMA,
    encoder=lambda obj: pa.RecordBatch.from_pylist([], schema=_EMPTY_SCHEMA),
    decoder=lambda metadata, batch: [],
)

CAPTURE_LIKE_TYPES: Final[list[type]] = [
    PremiseRecord,
    PremiseSibling,
    PremiseEmptyEncoding,
    ForecastPoint,
    OrderInitialized,
    OrderFilled,
    *PositionEvent.__subclasses__(),
]


def _open_writer(
    root: Path, clock: TestClock, include_types: list[type] | None = None
) -> StreamingFeatherWriter:
    return StreamingFeatherWriter(
        path=str(root / "live" / "premise"),
        cache=TestComponentStubs.cache(),
        clock=clock,
        include_types=CAPTURE_LIKE_TYPES if include_types is None else include_types,
        rotation_mode=RotationMode.SCHEDULED_DATES,
        rotation_interval=pd.Timedelta(days=1),
        rotation_time=dt.time(0, 0),
        rotation_timezone="UTC",
    )


def _clock_at(stamp: str) -> TestClock:
    clock = TestClock()
    clock.set_time(_iso_ns(stamp))
    return clock


def _make(cls: type, **fields: Any) -> Any:
    """``@customdataclass`` classes are untyped to mypy: build them through one Any boundary."""
    return cls(**fields)


def _record(n: int = 1) -> Any:
    return _make(
        PremiseRecord, ts_event=n, ts_init=n, schema="premise/v1", decision_id=f"d{n}", eval_ns=n
    )


def _table_files(writer_dir: Path, table: str) -> list[Path]:
    return sorted(writer_dir.glob(f"{table}_*.feather"))


def _read_rows(writer_dir: Path, table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _table_files(writer_dir, table):
        with path.open("rb") as handle:
            rows.extend(pa.ipc.open_stream(handle).read_all().to_pylist())
    return rows


def _table_bytes(writer_dir: Path, table: str) -> int:
    return sum(path.lstat().st_size for path in _table_files(writer_dir, table))


@dataclass
class _JudgedWriter:
    """Test-local restatement of the section 3.4.2 per-write landing rule (NOT production code).

    ``write`` returns False for a drop. Not judged, never a drop: a class outside
    ``include_types`` and a native event whose ``id`` is already in this mirror of the writer's
    10,000-id dedupe window.
    """

    writer: StreamingFeatherWriter
    include_types: list[type]
    mirror: OrderedDict[UUID4, None] = field(default_factory=OrderedDict)
    drops: int = 0
    written_by_type: dict[str, int] = field(default_factory=dict)

    def _pair(self, table: str) -> tuple[int, Any] | None:
        info = self.writer.get_current_file_info().get(table)
        return None if info is None else (info["size"], info["creation_time"])

    def write(self, obj: Any) -> bool:
        if type(obj) not in self.include_types:
            return True
        event_id = getattr(obj, "id", None)
        if isinstance(event_id, UUID4):
            if event_id in self.mirror:
                return True
            self.mirror[event_id] = None
            if len(self.mirror) > 10_000:
                self.mirror.popitem(last=False)
        table = class_to_filename(type(obj))
        before = self._pair(table)
        self.writer.write(obj)
        after = self._pair(table)
        if after is None:
            landed = False
        elif before is None:
            landed = after[0] > 0
        else:
            landed = before != after
        if not landed:
            self.drops += 1
            return False
        self.written_by_type[table] = self.written_by_type.get(table, 0) + 1
        return True


class _RaisingStream:
    """Replaces a table's ``RecordBatchStreamWriter``; ``write_table`` raises (swallowed)."""

    def write_table(self, table: pa.Table) -> None:
        raise OSError("premise: write_table failed")

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# V-1  schemas are registered before the first write
# ---------------------------------------------------------------------------

_FRESH_INTERPRETER_SCRIPT: Final[str] = textwrap.dedent(
    """
    import datetime as dt, sys, tempfile
    import pandas as pd
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.model.custom import customdataclass
    from nautilus_trader.model.events import OrderFilled, OrderInitialized, PositionEvent
    from nautilus_trader.persistence.writer import RotationMode, StreamingFeatherWriter
    from nautilus_trader.serialization.arrow.serializer import list_schemas
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    MODE = sys.argv[1]

    def build_types():
        from breezy.domain.forecast_point import ForecastPoint

        @customdataclass
        class PremiseFreshRecord:
            schema: str = ""

        return [PremiseFreshRecord, ForecastPoint, OrderInitialized, OrderFilled,
                *PositionEvent.__subclasses__()]

    def build_writer(include):
        return StreamingFeatherWriter(
            path=tempfile.mkdtemp() + "/live/x", cache=TestComponentStubs.cache(),
            clock=TestClock(), include_types=include, rotation_mode=RotationMode.SCHEDULED_DATES,
            rotation_interval=pd.Timedelta(days=1), rotation_time=dt.time(0, 0),
            rotation_timezone="UTC")

    schemas = list_schemas()
    if MODE == "types_first":
        include = build_types()
        registered_at_build = frozenset(schemas)
        writer = build_writer(include)
    else:  # writer_first: the MUTATION
        registered_at_build = frozenset(schemas)
        writer = build_writer(None)
        include = build_types()
    missing = [c.__name__ for c in include if c not in registered_at_build]
    assert not missing, f"unregistered before any writer exists: {missing}"
    assert writer._schemas is schemas, "the writer must hold the live global dict"
    print("V1-OK")
    """
)


def _run_fresh_interpreter(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _FRESH_INTERPRETER_SCRIPT, mode],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={"PYTHONPATH": str(SRC_DIR), "PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )


def test_capture_types_registered_before_kernel_writer_exists(tmp_path: Path) -> None:
    """V-1. In a fresh interpreter every include type is in ``list_schemas()`` before any writer
    is built, and the writer holds that same live dict (``writer.py:129``,
    ``serializer.py:85-86``).

    Stand-in: ``PremiseFreshRecord`` replaces the WP1 capture records.

    MUTATION (red): the ``writer_first`` run builds the writer before the types exist; its
    assertion fails. FINDING on 1.231.0: that ordering alone does NOT raise ``KeyError`` (the
    writer's dict is live, so a late ``@customdataclass`` is still found). The ``KeyError`` at
    ``writer.py:460`` (``schema = self._schemas[cls]``) needs a class that is never registered
    at all, asserted second.
    """
    good = _run_fresh_interpreter("types_first")
    assert good.returncode == 0, good.stderr
    assert "V1-OK" in good.stdout

    mutated = _run_fresh_interpreter("writer_first")
    assert mutated.returncode != 0
    assert "unregistered before any writer exists" in mutated.stderr

    class NeverRegistered:
        ts_event = 0
        ts_init = 0

    writer = _open_writer(tmp_path, _clock_at("2026-10-04T10:00:00.000000000Z"), [NeverRegistered])
    with pytest.raises(KeyError) as excinfo:
        writer.write(NeverRegistered())
    last = traceback.extract_tb(excinfo.value.__traceback__)[-1]
    assert Path(last.filename).name == "writer.py"
    assert last.name == "_create_writer"
    assert last.line == "schema = self._schemas[cls]"


def test_customdataclass_rejects_optional_and_decimal_fields() -> None:
    """V-1b (``custom.py:259-265``): the decorator refuses ``Optional``/union and ``Decimal``
    fields at class-definition time, which is why section 3.4.1 encodes null as ``""``/``0``.

    MUTATION (red): replacing the offending annotation with ``str`` makes the definition succeed,
    so ``pytest.raises`` fails.
    """
    with pytest.raises(TypeError, match="Unsupported custom data field type"):

        @customdataclass
        class _WithOptionalInt:
            value: int | None = None

    with pytest.raises(TypeError, match="Unsupported custom data field type"):

        @customdataclass
        class _WithOptionalStr:
            value: str | None = None

    with pytest.raises(TypeError, match="Unsupported custom data field type"):

        @customdataclass
        class _WithDecimal:
            value: Decimal = Decimal(0)

    # Found while building this file: stringified annotations are rejected too, so a module that
    # defines capture records must NOT use ``from __future__ import annotations``.
    future_source = (
        "from __future__ import annotations\n"
        "from nautilus_trader.model.custom import customdataclass\n"
        "@customdataclass\n"
        "class PremiseFutureAnnotations:\n"
        "    schema: str = ''\n"
    )
    with pytest.raises(TypeError, match="Unsupported custom data annotation: 'str'"):
        exec(compile(future_source, "<premise>", "exec"), {})  # noqa: S102


# ---------------------------------------------------------------------------
# V-3  every included native type and every ForecastPoint serialises; handler errors unwind
# ---------------------------------------------------------------------------


def _fixture_forecast_points() -> list[ForecastPoint]:
    """Real ``ForecastPoint``s: the byte-identical recorded NBP bulletin through the real parser."""
    text = NBM_FIXTURE.read_text(encoding="utf-8")
    points, _drops = parse_nbp_bulletin(text, stations=frozenset({"KLAX", "KMDW", "KMIA", "KSFO"}))
    cycle_ns = points[0].cycle_runtime_ns
    lag_ns = 65 * 60 * NS
    return [
        ForecastPoint(
            station=p.station,
            model="NBM_NBP",
            model_version=p.model_version,
            variable=p.variable,
            cycle_runtime_ns=p.cycle_runtime_ns,
            valid_start_ns=p.valid_start_ns,
            valid_end_ns=p.valid_end_ns,
            value_f=p.value_f,
            issuance_seq=0,
            measured_publication_lag_ns=lag_ns,
            available_at_ns=cycle_ns + lag_ns,
            ingested_at_ns=cycle_ns + lag_ns,
            absence_reason=p.absence_reason,
        )
        for p in points
    ]


def test_streamed_native_event_serialisation_never_raises() -> None:
    """V-3. Every included native type, a recorded resolver fill, NO-leg/tagged/changed/closed
    variants and every fixture ``ForecastPoint`` (absent-value points included) serialise to one
    Arrow row without raising.

    Recorded: ``OrderInitialized``, ``OrderFilled``, ``PositionOpened``, the inferred fill.
    Constructed: the tagged NO-leg ``OrderInitialized``, ``PositionChanged``, ``PositionClosed``.
    MUTATION (red): an object of a class with no registered schema (``NeverSerialisable``) makes
    ``serialize_batch`` raise ``TypeError``, so the loop below is not vacuous.
    """
    life = _recorded_lifecycle()
    events = [*life.events(), *_constructed_events(life)]
    assert {type(e) for e in events} == {
        OrderInitialized,
        OrderFilled,
        PositionOpened,
        PositionChanged,
        PositionClosed,
    }
    for event in events:
        batch = ArrowSerializer.serialize_batch([event], data_cls=type(event))
        assert batch.num_rows == 1, type(event).__name__
    points = _fixture_forecast_points()
    assert len(points) > 28
    for point in points:
        assert ArrowSerializer.serialize_batch([point], data_cls=ForecastPoint).num_rows == 1

    class NeverSerialisable:
        ts_event = 0
        ts_init = 0

    with pytest.raises(TypeError):
        ArrowSerializer.serialize_batch([NeverSerialisable()], data_cls=NeverSerialisable)


def test_msgbus_handler_exception_unwinds_into_publisher() -> None:
    """V-3 (``component.pyx:2832-2834``): a raising handler propagates out of ``publish`` into the
    publisher and later subscribers are skipped. This is the rationale for the catch-all wrapper.

    MUTATION (red): wrapping the handler body in ``try/except`` makes ``publish`` return normally
    and the second subscriber run, so both assertions fail.
    """
    bus: MessageBus = TestComponentStubs.msgbus()
    later: list[object] = []

    def raising(message: object) -> None:
        raise RuntimeError("premise: handler failure")

    bus.subscribe(topic="premise.unwind", handler=raising, priority=5)
    bus.subscribe(topic="premise.unwind", handler=later.append, priority=1)
    with pytest.raises(RuntimeError, match="premise: handler failure"):
        bus.publish("premise.unwind", "payload")
    assert later == []


# ---------------------------------------------------------------------------
# V-5  a custom type without instrument_id writes one regular file
# ---------------------------------------------------------------------------


def test_custom_type_without_instrument_id_writes_regular_file(tmp_path: Path) -> None:
    """V-5 (``writer.py:230-239``). A stand-in with no ``instrument_id`` lands in ONE regular
    ``custom_premise_record_*.feather`` in the stream directory, and a plain ``str`` table key.

    MUTATION (red): ``PremiseWithInstrumentId`` (adds ``instrument_id: InstrumentId``, instrument
    absent from the cache) writes ZERO rows and creates no file, silently.
    """
    root = tmp_path
    writer = _open_writer(root, _clock_at("2026-10-04T10:00:00.000000000Z"))
    writer.write(_record(1))
    writer.close()
    stream_dir = root / "live" / "premise"
    assert len(_table_files(stream_dir, "custom_premise_record")) == 1
    rows = _read_rows(stream_dir, "custom_premise_record")
    assert [r["decision_id"] for r in rows] == ["d1"]

    mutated_root = tmp_path / "mutated"
    mutated = _open_writer(
        mutated_root,
        _clock_at("2026-10-04T10:00:00.000000000Z"),
        [PremiseWithInstrumentId],
    )
    mutated.write(_make(PremiseWithInstrumentId, ts_event=1, ts_init=1, schema="x"))
    mutated.close()
    assert (
        _table_files(mutated_root / "live" / "premise", "custom_premise_with_instrument_id") == []
    )
    assert (
        list((mutated_root / "live" / "premise").glob("custom_premise_with_instrument_id*")) == []
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
# V-12  ForecastPoint stream
# ---------------------------------------------------------------------------

_FORECAST_TOPIC: Final[str] = "data.ForecastPoint*"


class _CaptureStandIn(Actor):  # type: ignore[misc]
    """Stand-in for ``CaptureActor``: subscribes in ``on_start`` and records what arrives."""

    def __init__(self, topic: str = _FORECAST_TOPIC) -> None:
        super().__init__()
        self.topic = topic
        self.received: list[Any] = []

    def on_start(self) -> None:
        self.msgbus.subscribe(topic=self.topic, handler=self.received.append)


def _nbm_harness() -> Any:
    from tests.unit.test_nbm_quantile_actor import build

    return build()


def _register_capture(harness: Any, topic: str = _FORECAST_TOPIC) -> _CaptureStandIn:
    capture = _CaptureStandIn(topic)
    capture.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=harness.actor.msgbus,
        cache=TestComponentStubs.cache(),
        clock=harness.clock,
    )
    return capture


@pytest.mark.asyncio
async def test_forecast_point_topic_pinned_by_publish_probe() -> None:
    """V-12. The topic ``NbmQuantileActor._publish`` publishes on is exactly ``data.ForecastPoint*``
    (``DataType.topic`` is ``ForecastPoint*``): a subscriber on that literal receives every point
    from the real actor fed the recorded bulletin.

    MUTATION (red): subscribing to ``data.ForecastPoint`` (no ``*``) receives nothing.
    """
    assert nbm_forecast_point_data_type().topic == "ForecastPoint*"
    harness = _nbm_harness()
    capture = _register_capture(harness)
    capture.start()
    harness.actor.start()
    await harness.drain()
    assert len(capture.received) == 28
    assert {type(p) for p in capture.received} == {ForecastPoint}
    assert capture.received == harness.published


@pytest.mark.asyncio
async def test_capture_actor_subscribed_before_first_forecast_publish() -> None:
    """V-12 (``trader.py:251-271``, ``nbm_quantile_actor.py:286-300``). Even if the producing
    actor starts FIRST, its first poll is an asynchronous task: nothing is published before
    ``start()`` returns, so a subscriber made in a later actor's ``on_start`` still gets all 28
    points. And a real ``Trader`` (from a ``BacktestEngine``) starts actors before strategies even
    when the strategy was registered first.

    MUTATION (red): starting the capture stand-in only after ``drain()`` receives zero points;
    making the ordering probe a ``Strategy`` instead of an ``Actor`` starts it after the strategy.
    """
    harness = _nbm_harness()
    capture = _register_capture(harness)
    harness.actor.start()
    assert harness.published == []
    capture.start()
    await harness.drain()
    assert len(capture.received) == 28

    started: list[str] = []

    class StartOrderActor(Actor):  # type: ignore[misc]
        def on_start(self) -> None:
            started.append("actor")

    class StartOrderStrategy(Strategy):  # type: ignore[misc]
        def on_start(self) -> None:
            started.append("strategy")

    engine = BacktestEngine(BacktestEngineConfig(trader_id=_TRADER))
    try:
        engine.add_strategy(StartOrderStrategy())  # registered FIRST on purpose
        engine.add_actor(StartOrderActor())
        engine.trader.start()
        assert started == ["actor", "strategy"]
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_forecast_point_streams_to_regular_custom_file(tmp_path: Path) -> None:
    """V-12. Real ``ForecastPoint``s written through the real writer land in one regular
    ``custom_forecast_point_*.feather`` (no ``instrument_id``), one row each, values intact.

    MUTATION (red): an ``include_types`` without ``ForecastPoint`` writes no file.
    """
    harness = _nbm_harness()
    capture = _register_capture(harness)
    capture.start()
    harness.actor.start()
    await harness.drain()
    writer = _open_writer(tmp_path, _clock_at("2026-10-04T10:00:00.000000000Z"))
    for point in capture.received:
        writer.write(point)
    writer.close()
    stream_dir = tmp_path / "live" / "premise"
    assert len(_table_files(stream_dir, "custom_forecast_point")) == 1
    rows = _read_rows(stream_dir, "custom_forecast_point")
    assert len(rows) == len(capture.received) == 28
    assert sorted((r["station"], r["variable"]) for r in rows) == sorted(
        (p.station, p.variable) for p in capture.received
    )
    assert all("instrument_id" not in r for r in rows)


# ---------------------------------------------------------------------------
# V-13  feed-watch cadence; sample_feed_health runs on the event loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_feed_health_runs_on_loop_thread() -> None:
    """V-13 (``data.py:1947-1960``): the cadence is ``DEFAULT_FEED_WATCH_INTERVAL_SECS`` = 5.0 s,
    and ``_watch_feed`` calls ``sample_feed_health`` from the event-loop thread, not a worker.

    MUTATION (red): calling ``sample_feed_health`` through ``run_in_executor`` records a worker
    thread id different from the loop's.
    """
    from breezy.adapters.polymarket_us.data import DEFAULT_FEED_WATCH_INTERVAL_SECS
    from tests.unit.test_polymarket_us_data import build_harness

    assert DEFAULT_FEED_WATCH_INTERVAL_SECS == 5.0
    harness = build_harness()
    assert harness.client._feed_watch_interval_secs == DEFAULT_FEED_WATCH_INTERVAL_SECS
    harness.client._feed_watch_interval_secs = 0.01
    seen: list[int] = []

    def recording() -> bool:
        seen.append(threading.get_ident())
        return False

    harness.client.sample_feed_health = recording  # type: ignore[method-assign]
    await harness.client._connect()
    watchdog = harness.client._feed_watchdog
    assert watchdog is not None
    await asyncio.wait_for(watchdog, timeout=5)
    await harness.client._disconnect()
    assert seen == [threading.get_ident()]


# ---------------------------------------------------------------------------
# V-14  fill_by_fingerprint <day>; supervisor spawn lines; one SHADOW_DECISION; disposal line
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


@pytest.fixture
def supervisor_logger_restored() -> Iterator[logging.Logger]:
    from breezy.runtime import trade_supervisor

    log = trade_supervisor.logger
    saved = (list(log.handlers), log.level, log.propagate)
    yield log
    for handler in list(log.handlers):
        if handler not in saved[0]:
            handler.close()
            log.removeHandler(handler)
    log.handlers[:] = saved[0]
    log.setLevel(saved[1])
    log.propagate = saved[2]


#: ``~/.local/share/breezy/logs/breezy-trade-supervisor.log``: a retained, recorded line.
RECORDED_SUPERVISOR_LAUNCHED: Final[str] = (
    "2026-10-03T16:50:45Z INFO breezy.runtime.trade_supervisor launched pid=529436"
)
_SUPERVISOR_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO breezy\.runtime\.trade_supervisor "
    r"(?P<event>[a-z_]+)(?P<fields>( \w+=\S+)*)$"
)


def test_supervisor_spawn_sites_and_their_log_lines(
    tmp_path: Path, supervisor_logger_restored: logging.Logger
) -> None:
    """V-14 item 11. There are FOUR ``ports.spawn`` call sites, not r8's three. Only
    ``_do_launch`` (``launched pid=<n>``) and ``_launch_boot_retry_child``
    (``boot_retry_launched pid=<n>``) log the pid; ``_do_relaunch_check`` logs ``relaunching
    attempt=<n>`` and the new site in ``_do_midday_watch`` logs ``midday_relaunching phase=...
    attempt=<n>``, both BEFORE the spawn and with no pid. The real ``log_decision`` through the
    supervisor's own formatter renders a line matching the recorded journal text.

    MUTATION (red, source edit in the worktree, reverted): renaming ``"launched"`` to
    ``"started"`` at the ``_do_launch`` site breaks both the AST map and the rendered line.
    """
    from breezy.runtime import trade_supervisor

    tree = ast.parse(Path(trade_supervisor.__file__).read_text(encoding="utf-8"))
    sites: dict[str, tuple[int, list[str]]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        spawns = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "spawn"]
        if not spawns:
            continue
        events = sorted(
            c.args[0].value
            for c in calls
            if isinstance(c.func, ast.Name)
            and c.func.id == "log_decision"
            and c.args
            and isinstance(c.args[0], ast.Constant)
            and c.args[0].value
            in {"launched", "relaunching", "boot_retry_launched", "midday_relaunching"}
        )
        sites[fn.name] = (len(spawns), events)
    assert sites == {
        "_do_launch": (1, ["launched"]),
        "_do_relaunch_check": (1, ["relaunching"]),
        "_launch_boot_retry_child": (1, ["boot_retry_launched"]),
        "_do_midday_watch": (1, ["midday_relaunching"]),
    }

    trade_supervisor.configure_supervisor_logging(tmp_path)
    trade_supervisor.log_decision("launched", pid=529436)
    trade_supervisor.log_decision("boot_retry_launched", pid=7)
    for handler in supervisor_logger_restored.handlers:
        handler.flush()
    lines = trade_supervisor.supervisor_log_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line, event in zip(lines, ("launched", "boot_retry_launched"), strict=True):
        match = _SUPERVISOR_LINE_RE.fullmatch(line)
        assert match is not None and match["event"] == event
        assert re.fullmatch(r" pid=\d+", match["fields"])
    recorded = _SUPERVISOR_LINE_RE.fullmatch(RECORDED_SUPERVISOR_LAUNCHED)
    assert recorded is not None and recorded["event"] == "launched"


_FQ_DAY: Final[dt.date] = dt.date(2026, 10, 1)
_FQ_OFFSET: Final[float] = -5.0
_FQ_NOW_NS: Final[int] = _iso_ns("2026-09-30T12:00:00.000000000Z")


def _build_fq_strategy(
    *, permit_expires_at_ns: int | None, sink: Callable[[Any], None], shadow_only: bool = True
) -> Any:
    """A real ``ForecastQuantileLadderStrategy`` (the construction ``tests/strategy/
    forecast_quantile_ladder/test_strategy.py`` uses), with a no-forecast quantile actor."""
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
    from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
    from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
    from breezy.strategy.ladder_ev.config import LadderEvConfig
    from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
    from breezy.strategy.ladder_ev.location_correction import CorrectionForm
    from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams

    clock = TestClock()
    clock.set_time(_FQ_NOW_NS)
    actor = ForecastQuantileStateActor(
        stations=("KMIA",), std_utc_offset_hours={"KMIA": _FQ_OFFSET}
    )
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.start()
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    calibration = LiveCalibration(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={"": identity},
        draws_by_version={"": (identity,)},
    )
    strategy = ForecastQuantileLadderStrategy(
        ForecastQuantileLadderConfig(
            stations=("KMIA",),
            calibration_artefact_path="/tmp/unused.json",
            calibration_artefact_sha256="a" * 64,
            shadow_only=shadow_only,
        ),
        quantile_actor=actor,
        calibration=calibration,
        ladder_cfg=LadderEvConfig(),
        bounds_provider=lambda **kwargs: None,  # type: ignore[arg-type]
        order_submission_permit=(
            None
            if permit_expires_at_ns is None
            else SimpleNamespace(expires_at_ns=permit_expires_at_ns)
        ),
        shadow_decision_sink=sink,
    )
    strategy.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    return strategy


def test_every_evaluation_emits_one_shadow_decision_line() -> None:
    """V-14 item 12 (``strategy.py:535-581``). Each ``evaluate_snapshot`` call hands exactly ONE
    record to the shadow sink and goes through ``_emit_shadow_decision``, the only writer of the
    ``SHADOW_DECISION`` log text, for each non-Take ``Decision`` variant reached with the real
    ``evaluate`` (no permit, not D+1, no forecast). FINDING: a ``Take`` that reaches
    ``_maybe_submit`` with ``shadow_only=False`` emits a SECOND record (``kind=TrySubmit``), so the
    line count per Take evaluation is 2, not 1. The ``Take`` branch of ``_shadow_log_line`` is
    covered by ``test_strategy.py``.

    MUTATION (red, source edit in the worktree, reverted): a second ``_emit_shadow_decision``
    call in ``evaluate_snapshot`` makes the per-call count 2.
    """
    from breezy.strategy.forecast_quantile_ladder.decision import SidedAsk
    from breezy.strategy.ladder_ev.quantile_density import Rung

    ladder = (Rung("lt", None, 77), Rung("i0", 78, 79), Rung("i1", 80, 81), Rung("gte", 82, None))
    open_permit = _FQ_NOW_NS + 10 * 3_600 * NS
    cases = [
        ("NotExecutable", None, _FQ_DAY),
        ("NotDPlus1", open_permit, _FQ_DAY + dt.timedelta(days=3)),
        ("Refuse", open_permit, _FQ_DAY),
    ]
    for kind, permit, climate_day in cases:
        records: list[Any] = []
        strategy = _build_fq_strategy(permit_expires_at_ns=permit, sink=records.append)
        emitted: list[Any] = []
        original = strategy._emit_shadow_decision
        strategy._emit_shadow_decision = lambda line, o=original, e=emitted: (
            e.append(line),
            o(line),
        )[1]
        strategy.evaluate_snapshot(
            now_ns=_FQ_NOW_NS,
            std_utc_offset_hours=_FQ_OFFSET,
            station="KMIA",
            climate_day=climate_day,
            ladder=ladder,
            rung_id="i1",
            ask=SidedAsk(side="yes", instrument_id="KMIA-premise-i1.POLY_US", price=0.30),
            fee_coefficient=0.0695,
            slippage_floor_prob=0.01,
            h_hours=6.0,
        )
        assert [r["kind"] for r in records] == [kind]
        assert len(emitted) == 1
    # FINDING: a Take adds a SECOND SHADOW_DECISION record. With ``shadow_only=False``,
    # ``_maybe_submit`` -> ``_emit_decision_outcome`` writes one ``TrySubmit`` record through the
    # same sink and the same log line (``strategy.py:630-660``, ``:688-701``).
    from breezy.strategy.forecast_quantile_ladder.decision import Take

    live_records: list[Any] = []
    live = _build_fq_strategy(
        permit_expires_at_ns=None, sink=live_records.append, shadow_only=False
    )
    take = Take(
        instrument_id="KMIA-premise-i1.POLY_US",
        station="KMIA",
        climate_day=_FQ_DAY,
        side="yes",
        rung_id="i1",
        qty=1,
        ev_net=0.1,
        p_hat=0.2,
        p_lower=0.17,
        p_upper=0.23,
    )
    live._maybe_submit(take, limit_price=Decimal("0.30"))
    assert [(r["kind"], r["reason"]) for r in live_records] == [
        ("TrySubmit", "phase0_permit_absent")
    ]
    source = (
        SRC_DIR / "breezy" / "strategy" / "forecast_quantile_ladder" / "strategy.py"
    ).read_text(encoding="utf-8")
    assert source.count('self.log.info(f"SHADOW_DECISION {line!r}")') == 1
    assert (
        source.count("self._emit_shadow_decision(") == 2
    )  # evaluate_snapshot + _emit_decision_outcome


#: ``breezy-trade-20261002T200526Z.log`` line 70915: the retained disposal line, ANSI stripped.
RECORDED_DISPOSED_LINE: Final[str] = (
    "2026-10-02T20:55:21.478676119Z [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: DISPOSED"
)
_DISPOSED_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z \[INFO\] (?P<component>\S+): DISPOSED$"
)


def test_nautilus_disposal_line_text_is_component_colon_disposed() -> None:
    """V-14 item 8. Disposing a Nautilus component logs ``<component id>: DISPOSED`` at INFO
    (``component.pyx:2202`` logs the FSM state name), the same text the retained node log holds.

    MUTATION (red): a regex expecting ``DISPOSING`` (the transient state) matches neither line.
    """
    from tests.support.nautilus_log_capture import capture_nautilus_logs

    read = capture_nautilus_logs()
    clock = TestClock()
    actor = Actor()
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.start()
    actor.stop()
    actor.dispose()
    disposed = [line for line in read() if line.endswith(": DISPOSED")]
    assert len(disposed) == 1
    live = _DISPOSED_RE.fullmatch(re.sub(r"\x1b\[[0-9;]*m", "", disposed[0]))
    assert live is not None and live["component"].endswith(actor.id.value)
    recorded = _DISPOSED_RE.fullmatch(RECORDED_DISPOSED_LINE)
    assert recorded is not None and recorded["component"].endswith("FORECAST-QUANTILE-LADDER")
    source = (NT_ROOT / "common" / "component.pyx").read_text(encoding="utf-8")
    assert 'self._log.info(f"{self._fsm.state_string_c()}")' in source


# ---------------------------------------------------------------------------
# V-15  adapter-free closures; submit_chain.py is not byte-pinned
# ---------------------------------------------------------------------------


def _module_file(name: str) -> tuple[Path, bool] | None:
    base = SRC_DIR.joinpath(*name.split("."))
    if (base / "__init__.py").is_file():
        return base / "__init__.py", True
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py"), False
    return None


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _module_level_imports(name: str) -> list[str]:
    located = _module_file(name)
    assert located is not None
    path, is_package = located
    package = name if is_package else name.rpartition(".")[0]
    found: list[str] = []

    def visit(statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split(".")
                    parts = parts[: len(parts) - (node.level - 1)]
                    module = ".".join([*parts, *([node.module] if node.module else [])])
                else:
                    module = node.module or ""
                found.append(module)
                found.extend(f"{module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.If):
                if _is_type_checking(node.test):
                    visit(node.orelse)
                else:
                    visit(node.body)
                    visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def static_module_closure(entry: str) -> set[str]:
    """AUT-6 r12's static walk: module-level imports only (function bodies and ``TYPE_CHECKING``
    blocks skipped, both branches of a top-level ``if``/``try`` kept), plus every ancestor
    package ``__init__``, because Python executes it."""
    seen: set[str] = set()
    stack = [entry]
    while stack:
        module = stack.pop()
        if module in seen or not module.startswith("breezy") or _module_file(module) is None:
            continue
        seen.add(module)
        parts = module.split(".")
        stack.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        stack.extend(_module_level_imports(module))
    return seen


def _adapter_modules(closure: set[str]) -> list[str]:
    return sorted(m for m in closure if m.startswith("breezy.adapters"))


def _fresh_process_modules(entry: str) -> set[str]:
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import sys, {entry}\n"
                "print('\\n'.join(m for m in sys.modules if m.startswith('breezy')))"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
        env={"PYTHONPATH": str(SRC_DIR), "PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )
    return set(done.stdout.split())


#: Planned AUT-1 entry-point dependencies that exist today (WP1/WP5 modules do not).
CLEAN_PLANNED_DEPENDENCIES: Final[tuple[str, ...]] = (
    "breezy.domain.forecast_point",
    "breezy.persistence.exit_tags",
    "breezy.runtime.submit_intent",
    "breezy.persistence.nbp_derived_store",
    "breezy.domain.instrument_leg",
)


def test_static_walk_positive_and_negative_controls() -> None:
    """V-15 controls. The walk agrees with a fresh-process ``sys.modules`` import on adapter
    membership for a clean module and for a module known to reach the adapters (33 modules,
    AUT-6 r12 fact 18), so a zero is a measurement.

    MUTATION (red): making ``_module_level_imports`` ignore ``ImportFrom`` drops the adapter
    count of ``trade_supervisor`` to 0 and fails the positive control.
    """
    clean = "breezy.domain.instrument_leg"
    dirty = "breezy.runtime.trade_supervisor"
    assert _adapter_modules(static_module_closure(clean)) == []
    assert [m for m in _fresh_process_modules(clean) if m.startswith("breezy.adapters")] == []
    walked = _adapter_modules(static_module_closure(dirty))
    assert len(walked) == 33
    imported = sorted(m for m in _fresh_process_modules(dirty) if m.startswith("breezy.adapters"))
    assert walked == imported


@pytest.mark.parametrize("entry", CLEAN_PLANNED_DEPENDENCIES)
def test_aut1_entry_point_closures_are_free_of_venue_adapter_modules(entry: str) -> None:
    """V-15. The planned post-move dependencies that exist today reach no ``breezy.adapters.*``
    module and no ``current_rung_hold`` package ``__init__``.

    MUTATION (red): ``breezy.adapters.polymarket_us.exec.submit_chain`` (where
    ``intent_fingerprint`` lives today) has 33 adapter modules, which is why it moves.
    """
    closure = static_module_closure(entry)
    assert _adapter_modules(closure) == []
    assert "breezy.strategy.current_rung_hold" not in closure


@pytest.mark.xfail(
    strict=True,
    reason=(
        "V-15 FAILS on this tree: capture_forecast_ref.py -> strategy.ladder_ev.forecast_state "
        "pulls 33 adapter modules and the current_rung_hold __init__: ladder_ev/__init__ -> "
        "ladder_ev.decision -> current_rung_hold.decision -> current_rung_hold/__init__ -> "
        "trial_day_latch -> adapters.polymarket_us.symbology. Returns to review; remove this "
        "marker only when the closure is clean."
    ),
)
def test_forecast_state_closure_is_adapter_free() -> None:
    """V-15, the planned ``capture_forecast_ref.py`` dependency. Strict xfail records the plan
    premise failing today: the closure of ``breezy.strategy.ladder_ev.forecast_state`` contains
    adapter modules. It flips to XPASS (a failure) the moment WP5 cleans it, forcing the marker off.
    """
    closure = static_module_closure("breezy.strategy.ladder_ev.forecast_state")
    assert _adapter_modules(closure) == []


def test_forecast_state_closure_reaches_adapters_through_ladder_ev_init() -> None:
    """V-15 evidence for the xfail above: the adapter edge is the ``ladder_ev`` package
    ``__init__`` (``ladder_ev.decision`` -> ``current_rung_hold`` package -> ``trial_day_latch``
    -> ``adapters.polymarket_us.symbology``), not ``forecast_state`` itself.

    MUTATION (red): asserting ``forecast_state``'s own imports contain an adapter module fails.
    """
    closure = static_module_closure("breezy.strategy.ladder_ev.forecast_state")
    assert len(_adapter_modules(closure)) == 33
    assert "breezy.strategy.current_rung_hold" in closure
    own = {m for m in _module_level_imports("breezy.strategy.ladder_ev.forecast_state")}
    assert not [m for m in own if m.startswith("breezy.adapters")]
    init_closure = static_module_closure("breezy.strategy.ladder_ev")
    assert _adapter_modules(init_closure) == _adapter_modules(closure)


def test_submit_chain_is_not_byte_pinned_in_tests() -> None:
    """V-15 second half. No test file carries the sha256 of ``exec/submit_chain.py`` or of the
    source of ``intent_fingerprint``. Positive control: the same scan DOES find
    ``exec/client.py``'s pin. (Other pins exist but are not whole-file or ``intent_fingerprint``
    pins: ``classify_create_order_outcome`` + ``CreateOrderOutcome`` source hash, the firewall
    scans of the file's path, and the callee name ``submit_chain.intent_fingerprint``.)

    MUTATION (red): adding the file's own digest as a literal in a scanned test file makes the
    scan find it (shown on a temporary copy).
    """
    import inspect

    from breezy.adapters.polymarket_us.exec import submit_chain

    exec_dir = SRC_DIR / "breezy" / "adapters" / "polymarket_us" / "exec"
    pins = {
        "submit_chain.py": hashlib.sha256((exec_dir / "submit_chain.py").read_bytes()).hexdigest(),
        "intent_fingerprint": hashlib.sha256(
            inspect.getsource(submit_chain.intent_fingerprint).encode("utf-8")
        ).hexdigest(),
    }
    control = hashlib.sha256((exec_dir / "client.py").read_bytes()).hexdigest()
    hits: dict[str, list[str]] = {key: [] for key in (*pins, "client.py")}
    needles = {**pins, "client.py": control}
    this_file = Path(__file__).resolve()
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        if path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8")
        for key, digest in needles.items():
            if digest in text:
                hits[key].append(str(path.relative_to(REPO_ROOT)))
    assert hits["client.py"], "positive control: the exec client's pin must be findable"
    assert hits["submit_chain.py"] == []
    assert hits["intent_fingerprint"] == []


# ---------------------------------------------------------------------------
# V-16  each streamed native event is counted once per event id
# ---------------------------------------------------------------------------


def test_native_event_counted_once_per_event_id(tmp_path: Path) -> None:
    """V-16. The recorded FQ lifecycle, delivered to a ``events.order.*``/``events.position.*``
    wildcard handler on two topics (a native event can reach one wildcard subscriber twice),
    is counted once per event ``id`` by the wrapper's mirror and writes exactly one row per event.

    MUTATION (red): counting every delivery (no mirror) gives 2 per event against 1 row.
    """
    life = _recorded_lifecycle()
    events = [life.initialized, life.filled, life.opened]
    writer = _open_writer(tmp_path, _clock_at("2026-10-04T10:00:00.000000000Z"))
    judged = _JudgedWriter(writer, CAPTURE_LIKE_TYPES)
    bus: MessageBus = TestComponentStubs.msgbus()
    deliveries: list[object] = []

    def handler(message: object) -> None:
        deliveries.append(message)
        judged.write(message)

    bus.subscribe(topic="events.order.*", handler=handler)
    bus.subscribe(topic="events.position.*", handler=handler)
    for event in events:
        topic_kind = "position" if isinstance(event, PositionEvent) else "order"
        bus.publish(f"events.{topic_kind}.FORECAST-QUANTILE-LADDER", event)
        bus.publish(f"events.{topic_kind}.DUPLICATE-TOPIC", event)
    writer.close()
    assert len(deliveries) == 6
    assert judged.written_by_type == {
        "order_initialized": 1,
        "order_filled": 1,
        "position_opened": 1,
    }
    assert judged.drops == 0
    stream_dir = tmp_path / "live" / "premise"
    for table in judged.written_by_type:
        assert len(_read_rows(stream_dir, table)) == 1


# ---------------------------------------------------------------------------
# V-17  each silent writer drop leaves count rising and bytes flat
# ---------------------------------------------------------------------------


def _first_write_with(
    writer: StreamingFeatherWriter, table: str, stream: Any
) -> Callable[[], None]:
    """Make the writer's lazy ``_create_writer`` install ``stream`` as the table's stream."""
    original = writer._create_writer

    def patched(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        if table in writer._writers:
            writer._writers[table] = stream

    writer._create_writer = patched  # type: ignore[method-assign]
    return lambda: setattr(writer, "_create_writer", original)


def _drop_scenarios(tmp_path: Path) -> dict[str, tuple[_JudgedWriter, Callable[[], Any], str]]:
    """name -> (judged writer, a factory for the next object, table)."""
    scenarios: dict[str, tuple[_JudgedWriter, Callable[[], Any], str]] = {}
    clock = _clock_at("2026-10-04T10:00:00.000000000Z")

    raising = _open_writer(tmp_path / "raising", clock)
    raising.write(_record(1))
    raising._writers["custom_premise_record"] = cast("Any", _RaisingStream())
    scenarios["raising_write_table"] = (
        _JudgedWriter(raising, CAPTURE_LIKE_TYPES),
        lambda: _record(2),
        "custom_premise_record",
    )

    empty = _open_writer(tmp_path / "empty", clock)
    scenarios["empty_serialisation"] = (
        _JudgedWriter(empty, CAPTURE_LIKE_TYPES),
        lambda: _empty_encoding(),
        "custom_premise_empty_encoding",
    )

    unregistered = _open_writer(tmp_path / "unreg", clock, [TimeEvent])
    scenarios["unregistered_class"] = (
        _JudgedWriter(unregistered, [TimeEvent]),
        lambda: TimeEvent("premise", UUID4(), 1, 1),
        "time_event",
    )
    return scenarios


def _empty_encoding() -> PremiseEmptyEncoding:
    return PremiseEmptyEncoding()


def test_each_silent_writer_drop_is_seen_by_the_per_type_check(tmp_path: Path) -> None:
    """V-17 (``writer.py:285-288``, ``:261``, ``:250-255``). For a raising ``write_table``, an
    empty serialisation and an unregistered class, the per-type count rises while the table's
    on-disk bytes (``lstat`` over ``<table>_*.feather``, after ``flush``) stay flat; a healthy
    table's bytes grow with its count.

    MUTATION (red): the healthy control writes the same stand-in without sabotage and its bytes
    grow, so asserting flatness for it fails.
    """
    for name, (judged, make, table) in _drop_scenarios(tmp_path).items():
        writer_dir = Path(judged.writer.path)
        counted = 0  # what the wrapper's ``written_by_type`` does: +1 per call that returned

        def naive_write(obj: Any, writer: StreamingFeatherWriter = judged.writer) -> int:
            writer.write(obj)  # returns None and never raises on a silent drop
            return 1

        counted += naive_write(make())  # settle: creates the file (empty/raising) or nothing
        judged.writer.flush()
        flat_from = _table_bytes(writer_dir, table)
        for _ in range(3):
            counted += naive_write(make())
        judged.writer.flush()
        assert counted == 4, name  # the count rose with every call ...
        assert _table_bytes(writer_dir, table) == flat_from, name  # ... the bytes did not

    healthy = _open_writer(tmp_path / "healthy", _clock_at("2026-10-04T10:00:00.000000000Z"))
    healthy.write(_record(1))
    healthy.flush()
    before = _table_bytes(Path(healthy.path), "custom_premise_record")
    healthy.write(_record(2))
    healthy.flush()
    assert _table_bytes(Path(healthy.path), "custom_premise_record") > before


# ---------------------------------------------------------------------------
# V-19  the per-write (size, creation_time) delta
# ---------------------------------------------------------------------------


def test_per_write_delta_flags_each_silent_drop(tmp_path: Path) -> None:
    """V-19. The ``(size, creation_time)`` delta flags exactly one drop per call for each of: a
    raising ``write_table`` (``writer.py:285-288``), an empty serialisation (``:261``) and an
    unregistered class (``:250-255``); a healthy write beside them is never flagged.

    MUTATION (red): judging by "the call returned" (``landed = True``) leaves every drop count at 0.
    """
    for name, (judged, make, _table) in _drop_scenarios(tmp_path).items():
        for call in (1, 2):
            before = judged.drops
            assert judged.write(make()) is False, (name, call)
            assert judged.drops == before + 1, (name, call)
    healthy = _JudgedWriter(
        _open_writer(tmp_path / "healthy", _clock_at("2026-10-04T10:00:00.000000000Z")),
        CAPTURE_LIKE_TYPES,
    )
    assert healthy.write(_record(1)) is True
    assert healthy.write(_record(2)) is True
    assert healthy.drops == 0


def test_first_write_to_lazily_created_table_with_zero_size_is_a_drop(tmp_path: Path) -> None:
    """V-19 (r12 item 1). The writer creates a ``custom_`` table's stream BEFORE it serialises
    (``writer.py:240-245``, ``:463-473``), so on the FIRST write the key goes absent -> ``(0, t)``
    even when the row is lost. An empty serialisation and a raising ``write_table`` on that first
    write are each exactly one drop, via the "absent before => size must be > 0 after" rule.

    MUTATION (red): the unmodified "pair changed" rule reads both as success (0 drops).
    """
    clock = _clock_at("2026-10-04T10:00:00.000000000Z")

    empty = _JudgedWriter(_open_writer(tmp_path / "e", clock), CAPTURE_LIKE_TYPES)
    assert "custom_premise_empty_encoding" not in empty.writer.get_current_file_info()
    assert empty.write(_empty_encoding()) is False
    assert empty.drops == 1
    assert empty.writer.get_current_file_info()["custom_premise_empty_encoding"]["size"] == 0

    raising_writer = _open_writer(tmp_path / "r", clock)
    restore = _first_write_with(raising_writer, "custom_premise_record", _RaisingStream())
    raising = _JudgedWriter(raising_writer, CAPTURE_LIKE_TYPES)
    assert "custom_premise_record" not in raising_writer.get_current_file_info()
    assert raising.write(_record(1)) is False
    assert raising.drops == 1
    restore()


def test_per_write_delta_has_no_false_positive(tmp_path: Path) -> None:
    """V-19. Zero drops for: an id already in the dedupe window; a class outside ``include_types``;
    a ``SCHEDULED_DATES`` rotation inside the call, including a sparse table whose size returns to
    0 (only ``creation_time`` differs); and the successful first write of a lazily created custom
    table (absent before, ``size > 0`` after). Run against a real writer with a ``TestClock``
    crossing 00:00Z.

    MUTATION (red): comparing ``size`` only turns the sparse-rotation case into a drop.
    """
    life = _recorded_lifecycle()
    clock = _clock_at("2026-10-04T23:59:58.000000000Z")
    writer = _open_writer(tmp_path, clock)
    judged = _JudgedWriter(writer, CAPTURE_LIKE_TYPES)

    assert (
        judged.write(_record(1)) is True
    )  # first write of a lazily created table: absent -> size>0
    assert judged.write(life.filled) is True
    assert judged.write(life.filled) is True  # duplicate id: native writer skips, not judged
    before = writer.get_current_file_info()["order_filled"]
    assert before["size"] > 0

    outside = TimeEvent("premise", UUID4(), 1, 1)  # a class outside include_types
    assert judged.write(outside) is True

    clock.set_time(_iso_ns("2026-10-05T00:00:01.000000000Z"))
    sparse_before = writer.get_current_file_info()["custom_premise_record"]
    assert judged.write(_record(2)) is True  # rotation inside the call: size resets, ct changes
    sparse_after = writer.get_current_file_info()["custom_premise_record"]
    assert sparse_after["size"] == 0
    assert sparse_after["creation_time"] != sparse_before["creation_time"]
    clock.set_time(_iso_ns("2026-10-06T00:00:01.000000000Z"))
    assert writer.get_current_file_info()["custom_premise_record"]["size"] == 0
    zero_before = writer.get_current_file_info()["custom_premise_record"]
    assert judged.write(_record(3)) is True  # size 0 -> 0, creation_time moves
    zero_after = writer.get_current_file_info()["custom_premise_record"]
    assert (zero_before["size"], zero_after["size"]) == (0, 0)
    assert zero_before["creation_time"] != zero_after["creation_time"]
    assert judged.drops == 0
    writer.close()


def test_capture_include_types_use_plain_str_size_keys(tmp_path: Path) -> None:
    """V-19 key shape. After one write of each include type, every table is a regular table keyed
    by its plain ``class_to_filename`` string (never a ``(table, instrument)`` tuple), and none is
    a per-instrument table (``writer.py:136-146``).

    MUTATION (red): the ``PremiseWithInstrumentId`` stand-in is a tuple key or no key at all, so
    the all-``str`` assertion fails.
    """
    life = _recorded_lifecycle()
    writer = _open_writer(tmp_path, _clock_at("2026-10-04T10:00:00.000000000Z"))
    sample = [
        _record(1),
        _make(PremiseSibling, ts_event=1, ts_init=1, schema="s", n=1),
        *life.events()[:3],
    ]
    sample.extend(_fixture_forecast_points()[:1])
    sample.extend(_constructed_events(life)[1:])
    for obj in sample:
        writer.write(obj)
    info = writer.get_current_file_info()
    tables = {class_to_filename(type(obj)) for obj in sample}
    assert tables <= set(info), tables - set(info)
    assert all(isinstance(key, str) for key in info)
    assert not tables & writer._per_instrument_writers
    assert all(info[table]["size"] > 0 for table in tables)
    assert "custom_premise_record" in info and "custom_forecast_point" in info
    writer.close()
    assert list_schemas() is writer._schemas
