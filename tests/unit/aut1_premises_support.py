"""Shared support for the AUT-1 WP0 premise tests (WP0-R10 split): helpers and the closure walk.

Original module docstring, kept for provenance: characterisation of the Nautilus 1.231.0
premises AUT-1 r12 relies on.

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
import datetime as dt
import re
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow as pa
from nautilus_trader.common.component import TestClock
from nautilus_trader.core.uuid import UUID4
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
    register_arrow,
)
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id
from breezy.domain.forecast_point import ForecastPoint

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
