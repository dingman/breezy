"""AUT-1 WP0 premises, V-1, V-1b, V-3, V-5, V-16, V-17, V-19: capture-writer premises.

Shared helpers live in ``aut1_premises_support`` (WP0-R10).
"""

import subprocess
import sys
import textwrap
import traceback
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

import pytest
from nautilus_trader.common.component import MessageBus, TimeEvent
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.model.events import (
    OrderFilled,
    OrderInitialized,
    PositionChanged,
    PositionClosed,
    PositionEvent,
    PositionOpened,
)
from nautilus_trader.persistence.funcs import class_to_filename
from nautilus_trader.persistence.writer import StreamingFeatherWriter
from nautilus_trader.serialization.arrow.serializer import (
    ArrowSerializer,
    list_schemas,
)
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.forecast_point import ForecastPoint
from breezy.ingest.nbm_quantile_parse import parse_nbp_bulletin
from tests.unit.aut1_premises_support import (
    CAPTURE_LIKE_TYPES,
    NBM_FIXTURE,
    NS,
    SRC_DIR,
    PremiseEmptyEncoding,
    PremiseSibling,
    PremiseWithInstrumentId,
    _clock_at,
    _constructed_events,
    _iso_ns,
    _JudgedWriter,
    _make,
    _open_writer,
    _RaisingStream,
    _read_rows,
    _record,
    _recorded_lifecycle,
    _table_bytes,
    _table_files,
)

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
