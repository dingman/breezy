"""AUT-1 WP1 part A: ``CaptureStreamWriter`` over a real native ``StreamingFeatherWriter``
(plan r12 section 3.4.2, option B). Every behavioural test uses a real writer on ``tmp_path``."""

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
from nautilus_trader.common.component import TimeEvent
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.events import OrderFilled, PositionEvent
from nautilus_trader.persistence.writer import RotationMode
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
from breezy.persistence.autonomy.capture_stream import (
    CAPTURE_INCLUDE_TYPES,
    ROTATION_INTERVAL,
    ROTATION_MODE,
    ROTATION_TIME,
    ROTATION_TIMEZONE,
    CaptureStreamWriter,
    capture_root,
)
from breezy.runtime import node_config
from tests.unit.aut1_premises_support import (
    PremiseEmptyEncoding,
    _clock_at,
    _iso_ns,
    _RaisingStream,
    _read_rows,
    _recorded_lifecycle,
    _table_bytes,
    _table_files,
)

T10 = "2026-10-04T10:00:00.000000000Z"
DECISION = "custom_decision_record"


def _decision(n: int = 1) -> DecisionRecord:
    return make_record(DecisionRecord, ts_event=n, ts_init=n, decision_id=f"d{n}", eval_ns=n)


def _open(tmp_path: Path, stamp: str = T10, **kw: Any) -> CaptureStreamWriter:
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1", **kw)
    assert stream.open(TestComponentStubs.cache(), _clock_at(stamp)) is True
    return stream


def _first_write_with(
    stream: CaptureStreamWriter, table: str, replacement: Any
) -> Callable[[], None]:
    """Make the native writer's lazy ``_create_writer`` install ``replacement`` for ``table``."""
    native = stream.native_writer
    original = native._create_writer

    def patched(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        if table in native._writers:
            native._writers[table] = replacement

    native._create_writer = patched  # type: ignore[method-assign]
    return lambda: setattr(native, "_create_writer", original)


def test_capture_root_is_disjoint_from_quote_tape_root(tmp_path: Path) -> None:
    """The stream lives under ``derived/``, never under the quote-tape catalog the ingest, disk
    monitor and retention watch. MUTATION: placing it under ``catalog/quote_tape`` fails both."""
    data_root = Path("/data/breezy-root")
    quote_tape = data_root / "catalog" / "quote_tape"
    root = capture_root(data_root, "polymarket_us")
    assert root == data_root / "derived" / "capture_stream" / "polymarket_us"
    assert not root.is_relative_to(quote_tape)
    assert not quote_tape.is_relative_to(root)
    stream = CaptureStreamWriter(root=root, instance_id="inst-1")
    assert stream.stream_dir == root / "live" / "inst-1"
    assert not stream.stream_dir.is_relative_to(quote_tape)
    for bad in ("../x", "a/b", "", "x" * 200, "a b"):
        with pytest.raises(ValueError):
            CaptureStreamWriter(root=root, instance_id=bad)


def test_include_types_exact() -> None:
    from nautilus_trader.model.events import OrderInitialized

    expected = [
        DecisionRecord,
        FrameCopy,
        OrderEventRecord,
        DetectorEvent,
        CaptureHeartbeat,
        ForecastPoint,
        OrderInitialized,
        OrderFilled,
        *PositionEvent.__subclasses__(),
    ]
    assert CAPTURE_INCLUDE_TYPES == expected
    assert len(set(CAPTURE_INCLUDE_TYPES)) == len(CAPTURE_INCLUDE_TYPES)
    names = {c.__name__ for c in CAPTURE_INCLUDE_TYPES}
    assert {"PositionOpened", "PositionChanged", "PositionClosed"} <= names


def test_rotation_matches_recorder_constants(tmp_path: Path) -> None:
    assert ROTATION_MODE == node_config.QUOTE_TAPE_ROTATION_MODE == RotationMode.SCHEDULED_DATES
    assert ROTATION_INTERVAL == node_config.QUOTE_TAPE_ROTATION_INTERVAL == pd.Timedelta(days=1)
    assert ROTATION_TIME == node_config.QUOTE_TAPE_ROTATION_TIME == dt.time(0, 0)
    assert ROTATION_TIMEZONE == node_config.QUOTE_TAPE_ROTATION_TIMEZONE == "UTC"
    native = _open(tmp_path).native_writer
    assert native.rotation_mode == RotationMode.SCHEDULED_DATES
    assert native.rotation_interval == pd.Timedelta(days=1)
    assert native.rotation_time == dt.time(0, 0)
    assert str(native.rotation_timezone) == "UTC"
    assert native.include_types == CAPTURE_INCLUDE_TYPES


def test_canary_writer_root_is_capture_root_canary(tmp_path: Path) -> None:
    live = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    canary = CaptureStreamWriter(root=tmp_path, instance_id="inst-1", source="canary")
    assert live.stream_dir == tmp_path / "live" / "inst-1"
    assert canary.stream_dir == tmp_path / "canary" / "inst-1"
    with pytest.raises(ValueError):
        CaptureStreamWriter(root=tmp_path, instance_id="inst-1", source="other")


def test_open_creates_a_private_stream_directory(tmp_path: Path) -> None:
    stream = _open(tmp_path)
    assert stream.stream_dir.is_dir()
    assert oct(stream.stream_dir.stat().st_mode & 0o777) == "0o700"
    stream.close()


def test_open_never_raises_when_the_root_is_absent(tmp_path: Path) -> None:
    stream = CaptureStreamWriter(root=tmp_path / "missing", instance_id="inst-1")
    assert stream.open(TestComponentStubs.cache(), _clock_at(T10)) is False
    assert stream.health.ok is False and stream.health.cause == "open_failed"
    assert stream.write(_decision()) is False


def test_wrapper_catches_serialize_batch_outside_writer_try(tmp_path: Path) -> None:
    """A registered class whose encoder raises propagates out of the native ``write`` (the
    serialisation sits outside its try block, ``writer.py:259``). The wrapper returns False, counts
    a failure and never raises. MUTATION: no ``try`` in the wrapper lets the ``TypeError`` out."""
    stream = _open(tmp_path, include_types=[*CAPTURE_INCLUDE_TYPES, _ExplodingEncoding])
    assert stream.write(_ExplodingEncoding()) is False
    assert stream.write_failures == 1
    assert stream.write_drops == 0
    assert stream.health.ok is False
    assert stream.health.cause == "write_exception:custom_exploding_encoding"
    # still usable for every other table
    assert stream.write(_decision()) is True


def test_write_before_open_returns_false(tmp_path: Path) -> None:
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    assert stream.write(_decision()) is False
    assert stream.write_failures == 1
    assert stream.health.ok is False
    assert stream.health.cause == "write_before_open"
    assert stream.flush() is False


def test_table_bytes_refuses_symlinks(tmp_path: Path) -> None:
    stream = _open(tmp_path)
    assert stream.write(_decision())
    stream.flush()
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 10_000)
    os.symlink(big, stream.stream_dir / "custom_sneaky_1.feather")
    os.symlink(big, stream.stream_dir / f"{DECISION}_999.feather")
    sizes = stream.table_bytes()
    assert "custom_sneaky" not in sizes
    real = sum(
        p.lstat().st_size for p in _table_files(stream.stream_dir, DECISION) if not p.is_symlink()
    )
    assert sizes[DECISION] == real


def test_table_bytes_ignores_non_matching_names(tmp_path: Path) -> None:
    stream = _open(tmp_path)
    (stream.stream_dir / "readme.txt").write_text("x", encoding="utf-8")
    (stream.stream_dir / "custom_x_notanumber.feather").write_text("x", encoding="utf-8")
    sizes = stream.table_bytes()
    assert "readme" not in sizes and not any(k.startswith("custom_x") for k in sizes)
    assert all(size == 0 for size in sizes.values())  # the native tables exist, empty


def test_no_config_json_is_written(tmp_path: Path) -> None:
    """Option A's kernel dump is gone; ER-6's config clause is dropped."""
    stream = _open(tmp_path)
    stream.write(_decision())
    stream.flush()
    stream.close()
    assert [p for p in tmp_path.rglob("*") if p.name == "config.json"] == []
    assert not list(tmp_path.rglob("*.json"))


def test_unchanged_size_and_creation_time_is_a_drop_sets_health_not_ok(tmp_path: Path) -> None:
    """A raising ``write_table`` on an existing table leaves ``(size, creation_time)`` unchanged:
    one drop, health down, ``False``, and the count of landed rows does not move.

    MUTATION: judging by "the call returned" leaves ``write_drops == 0`` and health ok (red).
    """
    stream = _open(tmp_path)
    assert stream.write(_decision(1)) is True
    stream.native_writer._writers[DECISION] = cast("Any", _RaisingStream())
    assert stream.write(_decision(2)) is False
    assert stream.write_drops == 1
    assert stream.write_failures == 0
    assert stream.health.ok is False
    assert stream.health.cause == f"write_dropped:{DECISION}"
    assert stream.counters().written_by_type == {DECISION: 1}


def test_unregistered_class_missing_writer_path_is_a_drop(tmp_path: Path) -> None:
    """``writer.py:250-255``: an included class with no registered schema has no writer, so the
    table key stays absent before and after: one drop, not an exception."""
    stream = _open(tmp_path, include_types=[TimeEvent])
    assert stream.write(TimeEvent("x", UUID4(), 1, 1)) is False
    assert stream.write_drops == 1 and stream.write_failures == 0
    assert stream.health.cause == "write_dropped:time_event"


def test_rotation_reset_counts_as_success(tmp_path: Path) -> None:
    """A sparse table rotated at 00:00Z resets its size to 0 and takes a new creation time: a
    success, including when the size returns to its earlier value (0 -> 0).

    MUTATION: comparing ``size`` only turns the second-day write into a drop.
    """
    clock = _clock_at("2026-10-04T23:59:58.000000000Z")
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    assert stream.open(TestComponentStubs.cache(), clock)
    assert stream.write(_decision(1)) is True
    clock.set_time(_iso_ns("2026-10-05T00:00:01.000000000Z"))
    assert stream.write(_decision(2)) is True
    clock.set_time(_iso_ns("2026-10-06T00:00:01.000000000Z"))
    assert stream.write(_decision(3)) is True
    assert stream.write_drops == 0
    assert stream.health.ok is True
    assert stream.counters().written_by_type == {DECISION: 3}


def test_dedupe_and_excluded_class_are_not_judged(tmp_path: Path) -> None:
    """An id already in the dedupe window and a class outside the include list are neither drops
    nor counted. MUTATION: judging them reads an unchanged pair as a drop (``write_drops`` 2)."""
    life = _recorded_lifecycle()
    stream = _open(tmp_path)
    assert stream.write(life.filled) is True
    assert stream.write(life.filled) is True  # duplicate id: the native writer skips it
    assert stream.write(TimeEvent("x", UUID4(), 1, 1)) is True  # outside include_types
    assert stream.write_drops == 0 and stream.health.ok is True
    assert stream.counters().written_by_type == {"order_filled": 1}


def test_native_events_are_counted_once_per_event_id_and_match_rows(tmp_path: Path) -> None:
    life = _recorded_lifecycle()
    stream = _open(tmp_path)
    for event in (life.initialized, life.filled, life.opened, life.filled, life.opened):
        assert stream.write(event) is True
    stream.flush()
    counts = stream.counters().written_by_type
    assert counts == {"order_initialized": 1, "order_filled": 1, "position_opened": 1}
    for table, count in counts.items():
        assert len(_read_rows(stream.stream_dir, table)) == count


def test_midnight_rotation_is_not_type_bytes_flat(tmp_path: Path) -> None:
    """``table_bytes`` sums every file of a table, so the new post-midnight file beside the closed
    one grows the total. MUTATION: summing only the newest file reads flat/shrunk after rotation."""
    clock = _clock_at("2026-10-04T23:59:58.000000000Z")
    stream = CaptureStreamWriter(root=tmp_path, instance_id="inst-1")
    assert stream.open(TestComponentStubs.cache(), clock)
    big = make_record(
        FrameCopy, ts_event=1, ts_init=1, decision_id="d", frame_body={"pad": "x" * 20_000}
    )
    assert stream.write(big)
    stream.flush()
    before = stream.table_bytes()["custom_frame_copy"]
    clock.set_time(_iso_ns("2026-10-05T00:00:01.000000000Z"))
    assert stream.write(make_record(FrameCopy, ts_event=2, ts_init=2, decision_id="e")) is True
    stream.flush()
    files = _table_files(stream.stream_dir, "custom_frame_copy")
    assert len(files) == 2
    after = stream.table_bytes()["custom_frame_copy"]
    assert after > before
    newest_only = files[-1].lstat().st_size
    assert newest_only < before  # the mutation's total would have SHRUNK
    assert after == sum(f.lstat().st_size for f in files)
    assert _table_bytes(stream.stream_dir, "custom_frame_copy") == after


def test_drop_is_counted_and_never_retried(tmp_path: Path) -> None:
    """One call, one native ``write_table`` attempt, one drop: no retry loop."""
    calls: list[int] = []

    class Counting(_RaisingStream):
        def write_table(self, table: Any) -> None:
            calls.append(1)
            super().write_table(table)

    stream = _open(tmp_path)
    assert stream.write(_decision(1))
    stream.native_writer._writers[DECISION] = cast("Any", Counting())
    assert stream.write(_decision(2)) is False
    assert calls == [1]
    assert stream.write_drops == 1


def test_first_write_to_lazily_created_table_with_zero_size_is_a_drop(tmp_path: Path) -> None:
    """r12 item 1: on the FIRST write the writer creates the table (``absent -> (0, t)``) before
    serialising, so an empty serialisation or a raising ``write_table`` still changes the pair.
    Absent-before requires ``size > 0`` after. MUTATION: the plain "pair changed" rule reads
    both as success (0 drops)."""
    (tmp_path / "e").mkdir()
    (tmp_path / "r").mkdir()
    empty = _open(tmp_path / "e", include_types=[*CAPTURE_INCLUDE_TYPES, PremiseEmptyEncoding])
    assert "custom_premise_empty_encoding" not in empty.native_writer.get_current_file_info()
    assert empty.write(PremiseEmptyEncoding()) is False
    assert empty.write_drops == 1
    info = empty.native_writer.get_current_file_info()
    assert info["custom_premise_empty_encoding"]["size"] == 0

    raising = _open(tmp_path / "r")
    restore = _first_write_with(raising, DECISION, _RaisingStream())
    assert DECISION not in raising.native_writer.get_current_file_info()
    assert raising.write(_decision()) is False
    assert raising.write_drops == 1
    restore()


def test_first_write_to_lazily_created_table_with_rows_is_success(tmp_path: Path) -> None:
    stream = _open(tmp_path)
    assert DECISION not in stream.native_writer.get_current_file_info()
    assert stream.write(_decision()) is True
    assert stream.native_writer.get_current_file_info()[DECISION]["size"] > 0
    assert stream.write_drops == 0 and stream.health.ok is True


def test_drops_since_submit_flush_counter_is_consumed_once(tmp_path: Path) -> None:
    stream = _open(tmp_path)
    assert stream.write(_decision(1))
    stream.native_writer._writers[DECISION] = cast("Any", _RaisingStream())
    stream.write(_decision(2))
    stream.write(_decision(3))
    assert stream.consume_drops_since_submit_flush() == 2
    assert stream.consume_drops_since_submit_flush() == 0
    assert stream.write_drops == 2  # the cumulative count is untouched


def test_flush_returns_true_then_false_when_the_native_flush_raises(tmp_path: Path) -> None:
    stream = _open(tmp_path)
    assert stream.flush() is True
    original = stream.native_writer.flush

    def boom() -> None:
        raise OSError("disk")

    stream.native_writer.flush = boom  # type: ignore[method-assign]
    assert stream.flush() is False
    assert stream.health.ok is False and stream.health.cause == "flush_exception"
    stream.native_writer.flush = original  # type: ignore[method-assign]


def test_close_never_raises_and_is_idempotent(tmp_path: Path) -> None:
    stream = _open(tmp_path)
    stream.write(_decision())
    stream.close()
    stream.close()
    CaptureStreamWriter(root=tmp_path, instance_id="inst-2").close()  # never opened
    assert len(_read_rows(stream.stream_dir, DECISION)) == 1


class _ExplodingEncoding:
    ts_event = 0
    ts_init = 0


def _explode(_obj: object) -> Any:
    raise TypeError("premise: encoder raised")


def _register_exploding() -> None:
    import pyarrow as pa
    from nautilus_trader.serialization.arrow.serializer import register_arrow

    register_arrow(
        _ExplodingEncoding,
        pa.schema([("n", pa.int64())]),
        encoder=_explode,
        decoder=lambda metadata, batch: [],
    )


_register_exploding()
