"""ING-2 S3a: the coalesced feather read is bounded, native-equivalent, and wired in.

Covers T-R1, T-R2, T-R3, T-R4, T-R6, T-R7 and T-R8 of the ING-2 S3 plan
(``docs/plans/backlog/ING-2_2026-09-25/ING-2_S3_plan_r2_2026-09-26.md``,
r3/r3.1 amendments). Every fixture is a real Arrow IPC stream, written the
same way ``StreamingFeatherWriter`` does (one message per ``write_batch``/
``write_table`` call), never a hand-built parquet file standing in for one.

``InstrumentStatus`` is used wherever the test needs a data class whose
identifier survives round-tripping WITHOUT ``instrument_id``/``bar_type``
schema metadata: unlike ``QuoteTick`` (whose wrangler needs
``instrument_id`` IN METADATA to deserialise at all, since it carries no
per-row ``instrument_id`` column), ``InstrumentStatus`` carries
``instrument_id`` as an ordinary per-row column and only
``{"type": "InstrumentStatus"}`` in its schema metadata -- exactly the F3
shape the Stage-0 findings measured, and exactly what T-R8's r3.1 fixture
note requires (native's identifier is genuinely ``None`` for it, so a
flat write is possible without breaking deserialisation).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from nautilus_trader.model.data import InstrumentStatus, QuoteTick
from nautilus_trader.model.enums import MarketStatusAction
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog, _timestamps_to_filename
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

from breezy.persistence.feather_preflight import inspect_feather_file, salvage_feather_file
from breezy.persistence.feather_read import COALESCE_ROWS, BatchCoalescer, read_feather_coalesced
from breezy.runtime.quote_tape_ingest_cli import (
    EXTEND_CHUNK_ROWS,
    FILE_MARKER_PREFIX,
    _convert_one_tick_type_per_file,
    _convert_stream_natively,
    _extend_overlapping_stream,
    _extend_table_chunked,
    _is_non_disjoint_refusal,
    default_convert,
)
from breezy.runtime.quote_tape_salvage import (
    ExtendWriteMismatch,
    _drop_already_landed_unfiltered,
    write_fresh_capture_rows,
)
from tests.unit.test_quote_tape_ingest_cli import (
    _quote_tick,
    _truncate_tail,
    _write_typed_ipc_stream,
)

IID = InstrumentId.from_str("EUR/USD.SIM")


def _status(index: int) -> InstrumentStatus:
    return InstrumentStatus(
        instrument_id=IID,
        action=MarketStatusAction.TRADING,
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _write_flat_stream(
    path: Path, objects: list[Any], data_cls: type, *, close: bool = True
) -> None:
    """Write ``objects`` as one Arrow IPC stream, one message per object.

    Byte-for-byte the ``StreamingFeatherWriter`` shape (:func:`_write_typed_ipc_stream`
    in ``test_quote_tape_ingest_cli.py``), duplicated here because that helper
    is private to its module; kept in lock-step with it deliberately.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    first = ArrowSerializer.serialize_batch([objects[0]], data_cls=data_cls)
    first_table = pa.Table.from_batches([first]) if isinstance(first, pa.RecordBatch) else first
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, first_table.schema)
        for obj in objects:
            piece = ArrowSerializer.serialize_batch([obj], data_cls=data_cls)
            table = pa.Table.from_batches([piece]) if isinstance(piece, pa.RecordBatch) else piece
            writer.write_table(table)
        if close:
            writer.close()


def _age(path: Path, minutes: float = 60.0) -> None:
    import os

    stamp = time.time() - minutes * 60
    os.utime(path, (stamp, stamp))


# ---------------------------------------------------------------------------
# T-R1: coalesced read equals native read_all in rows, schema, and order.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rows", [0, 1, 7, 8192, 8193, 20_000])
@pytest.mark.parametrize("coalesce_rows", [7, COALESCE_ROWS])
def test_coalesced_read_matches_native_read_all(
    tmp_path: Path, rows: int, coalesce_rows: int
) -> None:
    path = tmp_path / "live" / "instance-1" / "instrument_status_0.feather"
    path.parent.mkdir(parents=True, exist_ok=True)

    if rows == 0:
        # Schema-only stream: open and close with no messages written.
        schema = ArrowSerializer.serialize_batch([_status(0)], data_cls=InstrumentStatus).schema
        with path.open("wb") as handle:
            writer = pa.ipc.new_stream(handle, schema)
            writer.close()
    else:
        _write_flat_stream(path, [_status(i) for i in range(rows)], InstrumentStatus)

    catalog = ParquetDataCatalog(str(tmp_path))
    native_table = catalog._read_feather_file(str(path))
    mirror_table = read_feather_coalesced(catalog.fs, str(path), coalesce_rows=coalesce_rows)

    assert native_table is not None
    assert mirror_table is not None
    assert mirror_table.num_rows == rows
    assert mirror_table.equals(native_table, check_metadata=True)
    # Row order (ts_init sequence) must match exactly.
    if rows:
        assert mirror_table["ts_init"].to_pylist() == native_table["ts_init"].to_pylist()

    import math

    num_chunks = len(mirror_table.to_batches())
    assert num_chunks <= max(1, math.ceil(rows / coalesce_rows))


# ---------------------------------------------------------------------------
# T-R2: invalid-stream parity with native.
# ---------------------------------------------------------------------------


def test_a_truncated_mid_message_stream_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "live" / "instance-1" / "instrument_status_0.feather"
    _write_flat_stream(path, [_status(i) for i in range(20)], InstrumentStatus, close=False)
    _truncate_tail(path)

    catalog = ParquetDataCatalog(str(tmp_path))
    assert catalog._read_feather_file(str(path)) is None
    assert read_feather_coalesced(catalog.fs, str(path)) is None


def test_a_missing_path_returns_none(tmp_path: Path) -> None:
    catalog = ParquetDataCatalog(str(tmp_path))
    missing = str(tmp_path / "live" / "instance-1" / "does_not_exist.feather")
    assert catalog._read_feather_file(missing) is None
    assert read_feather_coalesced(catalog.fs, missing) is None


# ---------------------------------------------------------------------------
# T-R3: tripwire -- no path may call the native whole-file reader.
# ---------------------------------------------------------------------------


def test_no_path_calls_the_native_reader(tmp_path: Path) -> None:
    """Every S3a path must go through :func:`read_feather_coalesced`, never
    ``ParquetDataCatalog._read_feather_file`` or
    ``pyarrow.ipc.RecordBatchStreamReader.read_all``. Positive control: rows
    still land on every path, so this cannot pass vacuously by every path
    silently doing nothing.

    Fixture setup (writing the source streams, and seeding the EXTEND case's
    prior native conversion) happens BEFORE the patch is installed --
    exercising the real code path under test is what must never call the
    banned methods, not building the fixture for it.
    """

    def _boom_read_feather_file(self: ParquetDataCatalog, path: str) -> None:
        raise AssertionError("native _read_feather_file must never be called (T-R3)")

    def _boom_read_all(self: object) -> None:
        raise AssertionError("native RecordBatchStreamReader.read_all must never be called (T-R3)")

    # (a) fast path
    fast_dir = tmp_path / "fast"
    fast_path = fast_dir / "live" / "instance-1" / "instrument_status_0.feather"
    _write_flat_stream(fast_path, [_status(i) for i in range(5)], InstrumentStatus)
    _age(fast_path)
    fast_catalog = ParquetDataCatalog(str(fast_dir))

    # (b) per-file path
    per_file_dir = tmp_path / "per_file"
    instance_dir = per_file_dir / "live" / "instance-1"
    per_file_path = instance_dir / "instrument_status_0.feather"
    _write_flat_stream(per_file_path, [_status(i) for i in range(5)], InstrumentStatus)
    _age(per_file_path)
    per_file_catalog = ParquetDataCatalog(str(per_file_dir))
    report = inspect_feather_file(per_file_path)

    # (c) EXTEND path -- the FIRST (native) conversion is real setup, done
    # before the patch below is installed.
    extend_dir = tmp_path / "extend"
    extend_instance_dir = extend_dir / "live" / "instance-1"
    extend_path = extend_instance_dir / "instrument_status_0.feather"
    _write_flat_stream(extend_path, [_status(i) for i in range(5)], InstrumentStatus)
    extend_catalog = ParquetDataCatalog(str(extend_dir))
    extend_catalog.convert_stream_to_data("instance-1", InstrumentStatus, subdirectory="live")
    _write_flat_stream(extend_path, [_status(i) for i in range(20)], InstrumentStatus)

    # (d) salvage collect
    salvage_path = tmp_path / "salvage" / "live" / "instance-1" / "instrument_status_0.feather"
    _write_flat_stream(salvage_path, [_status(i) for i in range(20)], InstrumentStatus, close=False)
    _truncate_tail(salvage_path)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ParquetDataCatalog, "_read_feather_file", _boom_read_feather_file)
        mp.setattr(pa.ipc.RecordBatchStreamReader, "read_all", _boom_read_all)

        outcome = default_convert(fast_catalog, "instance-1", InstrumentStatus, "live")
        assert outcome == "converted"
        assert len(fast_catalog.query(data_cls=InstrumentStatus)) == 5

        _result, converted, _open = _convert_one_tick_type_per_file(
            per_file_catalog,
            instance_dir,
            "instance-1",
            InstrumentStatus,
            frozenset(),
            {per_file_path: report},
            instance_is_dead=True,
            dry_run=False,
        )
        assert converted
        assert len(per_file_catalog.query(data_cls=InstrumentStatus)) == 5

        outcome = _extend_overlapping_stream(extend_catalog, "instance-1", InstrumentStatus, "live")
        assert outcome == "converted"
        assert len(extend_catalog.query(data_cls=InstrumentStatus)) == 20

        salvage_result = salvage_feather_file(salvage_path)
        assert salvage_result.table is not None
        assert salvage_result.rows_recovered > 0


# ---------------------------------------------------------------------------
# T-R4: the mirror is layout-identical to native.
# ---------------------------------------------------------------------------


def test_mirror_matches_native_on_a_flat_layout(tmp_path: Path) -> None:
    """Flat layout (InstrumentStatus), sorted: same files, same rows, same order."""
    native_root = tmp_path / "native"
    mirror_root = tmp_path / "mirror"
    objects = [_status(i) for i in range(50)]
    for root in (native_root, mirror_root):
        path = root / "live" / "instance-1" / "instrument_status_0.feather"
        _write_flat_stream(path, objects, InstrumentStatus)

    native_catalog = ParquetDataCatalog(str(native_root))
    native_catalog.convert_stream_to_data("instance-1", InstrumentStatus, subdirectory="live")

    mirror_catalog = ParquetDataCatalog(str(mirror_root))
    _convert_stream_natively(mirror_catalog, "instance-1", InstrumentStatus, "live")

    native_files = sorted(
        p.relative_to(native_root).as_posix() for p in native_root.rglob("*.parquet")
    )
    mirror_files = sorted(
        p.relative_to(mirror_root).as_posix() for p in mirror_root.rglob("*.parquet")
    )
    assert native_files == mirror_files

    native_rows = native_catalog.query(data_cls=InstrumentStatus)
    mirror_rows = mirror_catalog.query(data_cls=InstrumentStatus)
    assert [r.ts_init for r in native_rows] == [r.ts_init for r in mirror_rows]
    assert {r.ts_init for r in native_rows} == {o.ts_init for o in objects}


def test_mirror_matches_native_on_a_per_instrument_layout_with_ties(tmp_path: Path) -> None:
    """Per-instrument layout (QuoteTick), UNSORTED with a tie: mirror ties native.

    The P3 assumption (``pc.sort_indices`` is stable on ties) is checked here:
    both catalogs apply the identical native sort inside
    ``_apply_stream_conversion_transforms``/``_enforce_monotonic_ts``, so an
    unsorted-with-ties input must produce the identical full row sequence.
    """
    objects = [_quote_tick(i) for i in [0, 2, 1, 1, 4, 3]]  # unsorted, tie at index 1
    native_root = tmp_path / "native"
    mirror_root = tmp_path / "mirror"
    for root in (native_root, mirror_root):
        path = root / "live" / "instance-1" / "quote_tick_0.feather"
        _write_typed_ipc_stream(path, objects, QuoteTick, close=True)

    native_catalog = ParquetDataCatalog(str(native_root))
    native_catalog.convert_stream_to_data("instance-1", QuoteTick, subdirectory="live")

    mirror_catalog = ParquetDataCatalog(str(mirror_root))
    _convert_stream_natively(mirror_catalog, "instance-1", QuoteTick, "live")

    native_files = sorted(
        p.relative_to(native_root).as_posix() for p in native_root.rglob("*.parquet")
    )
    mirror_files = sorted(
        p.relative_to(mirror_root).as_posix() for p in mirror_root.rglob("*.parquet")
    )
    assert native_files == mirror_files

    native_rows = native_catalog.query(data_cls=QuoteTick)
    mirror_rows = mirror_catalog.query(data_cls=QuoteTick)
    native_seq = [(r.ts_init, r.ts_event) for r in native_rows]
    mirror_seq = [(r.ts_init, r.ts_event) for r in mirror_rows]
    assert sorted(r.ts_init for r in native_rows) == sorted(r.ts_init for r in mirror_rows)
    assert native_seq == mirror_seq, (
        "P3 assumption violated: pc.sort_indices was not stable across the same "
        "unsorted-with-ties input read two different ways"
    )


# ---------------------------------------------------------------------------
# T-R6: salvage collect output is coalesced; prefix semantics unchanged.
# ---------------------------------------------------------------------------


def test_salvage_collect_is_coalesced_via_the_shared_batchcoalescer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import breezy.persistence.feather_preflight as feather_preflight_module

    calls: list[int] = []
    real_coalescer = BatchCoalescer

    def small_coalescer(schema: pa.Schema, coalesce_rows: int = COALESCE_ROWS) -> BatchCoalescer:
        calls.append(1)
        return real_coalescer(schema, coalesce_rows=3)

    monkeypatch.setattr(feather_preflight_module, "BatchCoalescer", small_coalescer)

    path = tmp_path / "live" / "instance-1" / "instrument_status_0.feather"
    _write_flat_stream(path, [_status(i) for i in range(20)], InstrumentStatus, close=False)
    _truncate_tail(path)

    before_truncate_rows = 20 - 1  # truncation drops at least the last message
    result = salvage_feather_file(path)

    assert calls, "the collect branch must construct a BatchCoalescer"
    assert result.table is not None
    assert 0 < result.rows_recovered <= before_truncate_rows
    import math

    assert len(result.table.to_batches()) <= math.ceil(result.rows_recovered / 3)


# ---------------------------------------------------------------------------
# T-R7 (A1): default_convert routes reads through catalog, writes through target.
# ---------------------------------------------------------------------------


def test_default_convert_routes_writes_to_target_and_reads_from_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    work_root = tmp_path / "work"
    path = source_root / "live" / "instance-1" / "instrument_status_0.feather"
    _write_flat_stream(path, [_status(i) for i in range(5)], InstrumentStatus)
    _age(path)

    source_catalog = ParquetDataCatalog(str(source_root))
    work_catalog = ParquetDataCatalog(str(work_root))

    outcome = default_convert(
        source_catalog, "instance-1", InstrumentStatus, "live", target=work_catalog
    )

    assert outcome == "converted"
    assert len(work_catalog.query(data_cls=InstrumentStatus)) == 5
    assert not (source_root / "data").exists()


def test_default_convert_without_target_writes_to_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    path = source_root / "live" / "instance-1" / "instrument_status_0.feather"
    _write_flat_stream(path, [_status(i) for i in range(5)], InstrumentStatus)
    _age(path)

    source_catalog = ParquetDataCatalog(str(source_root))
    outcome = default_convert(source_catalog, "instance-1", InstrumentStatus, "live")

    assert outcome == "converted"
    assert len(source_catalog.query(data_cls=InstrumentStatus)) == 5


# ---------------------------------------------------------------------------
# T-R8 (A8): the write-mismatch detector.
# ---------------------------------------------------------------------------


class _TR8Fixture:
    """Builds the r3.1 fixture shape: a flat native seed, then an overlapping
    growth that routes to EXTEND, with a planted collision at write_data's
    exact target path.
    """

    def __init__(self, tmp_path: Path, name: str = "instance-1") -> None:
        self.root = tmp_path / name
        self.instance = "instance-1"
        self.instance_dir = self.root / "live" / self.instance
        self.catalog = ParquetDataCatalog(str(self.root))

    def seed(self, seed_rows: range) -> None:
        seed_path = self.instance_dir / "instrument_status_seed.feather"
        _write_flat_stream(seed_path, [_status(i) for i in seed_rows], InstrumentStatus)
        self.catalog.convert_stream_to_data(self.instance, InstrumentStatus, subdirectory="live")
        # The feather source is deliberately removed once landed: only the
        # resulting flat parquet matters for the seeded, already-landed
        # state, and leaving it in `instance_dir` would spuriously appear as
        # an unrelated per-file candidate in the tests below.
        seed_path.unlink()
        assert self.instance_dir.exists() is False or not list(self.instance_dir.glob("*seed*"))

    def fresh_of(self, path: Path) -> list[Any]:
        table = self.catalog._read_feather_file(str(path))
        objects = list(self.catalog._handle_table_nautilus(table=table, data_cls=InstrumentStatus))
        return _drop_already_landed_unfiltered(self.catalog, InstrumentStatus, objects)

    def plant_collision(self, fresh: list[Any]) -> str:
        directory = self.catalog._make_path(data_cls=InstrumentStatus, identifier=IID.value)
        filename = _timestamps_to_filename(fresh[0].ts_init, fresh[-1].ts_init)
        collision_path = f"{directory}/{filename}"
        self.catalog.fs.mkdirs(directory, exist_ok=True)
        foreign = self.catalog._objects_to_table([_status(1_000_000)], data_cls=InstrumentStatus)
        pq.write_table(foreign, where=collision_path, filesystem=self.catalog.fs)
        return collision_path


def test_a8_extend_collision_raises_extend_write_mismatch(tmp_path: Path) -> None:
    fixture = _TR8Fixture(tmp_path)
    fixture.seed(range(5))  # lands T0..T4, flat

    grow_path = fixture.instance_dir / "instrument_status_0.feather"
    _write_flat_stream(grow_path, [_status(i) for i in range(3, 10)], InstrumentStatus)  # T3..T9
    assert grow_path.exists()

    with pytest.raises(ValueError) as exc_info:
        fixture.catalog.convert_stream_to_data(
            fixture.instance, InstrumentStatus, subdirectory="live"
        )
    assert _is_non_disjoint_refusal(exc_info.value)

    fresh = fixture.fresh_of(grow_path)
    assert [o.ts_init for o in fresh] == [1_000_000_005 + i for i in range(5)]  # T5..T9
    fixture.plant_collision(fresh)

    with pytest.raises(ExtendWriteMismatch) as mismatch_info:
        write_fresh_capture_rows(fixture.catalog, InstrumentStatus, fresh)
    message = str(mismatch_info.value)
    assert "non-disjoint" not in message
    assert "instrument_status" in message
    assert "expected 5" in message


def test_a8_positive_control_no_collision_writes_cleanly(tmp_path: Path) -> None:
    fixture = _TR8Fixture(tmp_path)
    fixture.seed(range(5))

    grow_path = fixture.instance_dir / "instrument_status_0.feather"
    _write_flat_stream(grow_path, [_status(i) for i in range(3, 10)], InstrumentStatus)

    with pytest.raises(ValueError):
        fixture.catalog.convert_stream_to_data(
            fixture.instance, InstrumentStatus, subdirectory="live"
        )

    fresh = fixture.fresh_of(grow_path)
    written = write_fresh_capture_rows(fixture.catalog, InstrumentStatus, fresh)

    assert written == len(fresh) == 5
    landed = fixture.catalog.query(data_cls=InstrumentStatus)
    assert {r.ts_init for r in landed} == {1_000_000_000 + i for i in range(10)}


def test_a8_per_file_sibling_isolation(tmp_path: Path) -> None:
    """One instance, two per-file EXTEND-routed feathers: a collision in file
    1 must not block file 2 from converting.
    """
    fixture = _TR8Fixture(tmp_path)
    fixture.seed(range(5))  # T0..T4 landed, flat

    file1 = fixture.instance_dir / "instrument_status_0.feather"
    _write_flat_stream(file1, [_status(i) for i in range(3, 10)], InstrumentStatus)  # T3..T9
    _age(file1)

    file2 = fixture.instance_dir / "instrument_status_1.feather"
    _write_flat_stream(file2, [_status(i) for i in range(3, 15)], InstrumentStatus)  # T3..T14
    _age(file2)

    reports = {file1: inspect_feather_file(file1), file2: inspect_feather_file(file2)}

    fresh1 = fixture.fresh_of(file1)
    fixture.plant_collision(fresh1)  # collides exactly with file1's fresh window [T5, T9]

    result, converted, _open = _convert_one_tick_type_per_file(
        fixture.catalog,
        fixture.instance_dir,
        fixture.instance,
        InstrumentStatus,
        frozenset(),
        reports,
        instance_is_dead=True,
        dry_run=False,
    )

    assert "failed=1" in result.outcome
    assert "converted=1" in result.outcome
    assert converted
    assert not (fixture.instance_dir / f"{FILE_MARKER_PREFIX}{file1.name}").exists()
    assert (fixture.instance_dir / f"{FILE_MARKER_PREFIX}{file2.name}").exists()
    landed = fixture.catalog.query(
        data_cls=InstrumentStatus, start=1_000_000_010, end=1_000_000_014
    )
    assert {r.ts_init for r in landed} == {
        1_000_000_010,
        1_000_000_011,
        1_000_000_012,
        1_000_000_013,
        1_000_000_014,
    }


def test_write_data_group_and_parquet_set_on_a_flat_type_root(tmp_path: Path) -> None:
    """(d): the flat case. A type root containing one identifier
    subdirectory must not have that subdirectory's files appear in the
    depth-1 parquet set.
    """
    from breezy.runtime.quote_tape_salvage import _parquet_set, _write_data_group

    catalog = ParquetDataCatalog(str(tmp_path))
    status = _status(0)
    cls, identifier = _write_data_group(status)
    assert cls is InstrumentStatus
    assert identifier == IID.value

    flat_root = catalog._make_path(data_cls=InstrumentStatus, identifier=None)
    sub_dir = catalog._make_path(data_cls=InstrumentStatus, identifier=IID.value)
    catalog.fs.mkdirs(sub_dir, exist_ok=True)
    (Path(sub_dir) / "nested.parquet").write_bytes(b"not a real parquet file")
    (Path(flat_root) / "flat.parquet").write_bytes(b"not a real parquet file")

    flat_set = _parquet_set(catalog, flat_root)
    assert flat_set == {f"{flat_root}/flat.parquet"}
    assert all("nested.parquet" not in entry for entry in flat_set)


# ---------------------------------------------------------------------------
# S3b (ING-2 S3 plan r2, Arch §4/§5b): chunked EXTEND bounds overlapping-
# stream memory. T4, T8a, T8b, T-R5, plus wiring checks for §5b.
# ---------------------------------------------------------------------------


def _extend_status_table(catalog: ParquetDataCatalog, path: Path, ts_inits: list[int]) -> Any:
    """A raw (untransformed) table of ``InstrumentStatus`` rows at the given
    ``ts_init`` values, read back through the S3a coalesced reader -- exactly
    what ``_extend_overlapping_stream``/the per-file fallback hand to EXTEND.
    """
    objects = [
        InstrumentStatus(
            instrument_id=IID,
            action=MarketStatusAction.TRADING,
            ts_event=ts,
            ts_init=ts,
        )
        for ts in ts_inits
    ]
    _write_flat_stream(path, objects, InstrumentStatus)
    return read_feather_coalesced(catalog.fs, str(path))


def test_extend_chunk_rows_default_matches_the_plan() -> None:
    assert EXTEND_CHUNK_ROWS == 50_000


def test_extend_chunked_never_exceeds_the_bound_and_dedupe_window_is_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4: EXTEND never holds more than one chunk; each chunk's dedupe query
    uses that chunk's OWN [lo, hi], not the full table's."""
    catalog = ParquetDataCatalog(str(tmp_path))
    path = tmp_path / "live" / "instance-1" / "instrument_status_0.feather"
    ts_inits = [1_000_000_000 + i for i in range(12)]  # no ties, 12 rows
    table = _extend_status_table(catalog, path, ts_inits)
    assert table is not None

    query_windows: list[tuple[int, int]] = []
    real_query = ParquetDataCatalog.query

    def spy_query(self: ParquetDataCatalog, *args: Any, **kwargs: Any) -> list[Any]:
        if "start" in kwargs and "end" in kwargs:
            query_windows.append((kwargs["start"], kwargs["end"]))
        return real_query(self, *args, **kwargs)

    write_calls: list[int] = []
    real_write = write_fresh_capture_rows

    def spy_write(write_target: ParquetDataCatalog, data_cls: type, objects: list[Any]) -> int:
        write_calls.append(len(objects))
        return real_write(write_target, data_cls, objects)

    monkeypatch.setattr(ParquetDataCatalog, "query", spy_query)
    monkeypatch.setattr("breezy.runtime.quote_tape_ingest_cli.write_fresh_capture_rows", spy_write)

    written, streamed_any = _extend_table_chunked(
        catalog, catalog, InstrumentStatus, table, chunk_rows=5
    )

    assert streamed_any
    assert written == 12
    assert write_calls == [5, 5, 2]
    assert all(count <= 5 for count in write_calls)
    assert query_windows == [
        (1_000_000_000, 1_000_000_004),
        (1_000_000_005, 1_000_000_009),
        (1_000_000_010, 1_000_000_011),
    ]
    landed = catalog.query(data_cls=InstrumentStatus)
    assert {r.ts_init for r in landed} == set(ts_inits)


def test_extend_chunked_tie_pair_on_boundary_matches_unchunked(tmp_path: Path) -> None:
    """T8a (a): a same-ts_init tie straddling a chunk boundary lands both rows
    when chunked, exactly as unchunked EXTEND does (no silent drop). Without
    the tie-advance, the second row of the pair is silently dropped by the
    NEXT chunk's own [lo, hi] dedupe query, which finds the first row of the
    pair already landed under the identical (instrument_id, ts_init) key.
    """
    ts_inits = (
        [1_000_000_000 + i for i in range(4)]
        + [1_000_000_004, 1_000_000_004]
        + [1_000_000_005 + i for i in range(4)]
    )  # 10 rows; positions 4 and 5 (0-indexed) tie at ts_init=...004

    unchunked_catalog = ParquetDataCatalog(str(tmp_path / "unchunked"))
    unchunked_path = tmp_path / "unchunked" / "live" / "instance-1" / "instrument_status_0.feather"
    unchunked_table = _extend_status_table(unchunked_catalog, unchunked_path, ts_inits)
    unchunked_objects = list(
        unchunked_catalog._handle_table_nautilus(table=unchunked_table, data_cls=InstrumentStatus)
    )
    unchunked_written = write_fresh_capture_rows(
        unchunked_catalog, InstrumentStatus, unchunked_objects
    )

    chunked_catalog = ParquetDataCatalog(str(tmp_path / "chunked"))
    chunked_path = tmp_path / "chunked" / "live" / "instance-1" / "instrument_status_0.feather"
    chunked_table = _extend_status_table(chunked_catalog, chunked_path, ts_inits)
    chunked_written, chunked_streamed = _extend_table_chunked(
        chunked_catalog, chunked_catalog, InstrumentStatus, chunked_table, chunk_rows=5
    )

    assert chunked_streamed
    assert chunked_written == unchunked_written == 10
    unchunked_rows = sorted(r.ts_init for r in unchunked_catalog.query(data_cls=InstrumentStatus))
    chunked_rows = sorted(r.ts_init for r in chunked_catalog.query(data_cls=InstrumentStatus))
    assert unchunked_rows == chunked_rows == sorted(ts_inits)


def test_extend_chunked_all_equal_ts_init_collapses_to_one_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T8a (b): every row shares one ts_init -> a single chunk, matching
    today's unchunked EXTEND (the plan's stated degenerate case, Arch §4)."""
    ts_inits = [1_000_000_000] * 6
    catalog = ParquetDataCatalog(str(tmp_path))
    path = tmp_path / "live" / "instance-1" / "instrument_status_0.feather"
    table = _extend_status_table(catalog, path, ts_inits)

    calls: list[int] = []
    real_write = write_fresh_capture_rows

    def counting_write(write_target: ParquetDataCatalog, data_cls: type, objects: list[Any]) -> int:
        calls.append(len(objects))
        return real_write(write_target, data_cls, objects)

    import breezy.runtime.quote_tape_ingest_cli as cli_module

    monkeypatch.setattr(cli_module, "write_fresh_capture_rows", counting_write)

    written, streamed_any = _extend_table_chunked(
        catalog, catalog, InstrumentStatus, table, chunk_rows=3
    )

    assert streamed_any
    assert written == 6
    assert calls == [6]  # ONE chunk, never three of size <= 3


def test_extend_chunked_bar_internal_stays_internal(tmp_path: Path) -> None:
    """T8a (c): a Bar-INTERNAL feather's objects keep '-INTERNAL' through
    chunked EXTEND (A4: convert_bar_type_to_external=False, matching what
    unchunked EXTEND has always done implicitly via ``_handle_table_nautilus``'s
    own defaults)."""
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity

    bar_type = BarType.from_str("EUR/USD.SIM-1-MINUTE-BID-INTERNAL")
    bars = [
        Bar(
            bar_type=bar_type,
            open=Price.from_str("1.0"),
            high=Price.from_str("1.0"),
            low=Price.from_str("1.0"),
            close=Price.from_str("1.0"),
            volume=Quantity.from_str("1"),
            ts_event=1_000_000_000 + i,
            ts_init=1_000_000_000 + i,
        )
        for i in range(6)
    ]
    catalog = ParquetDataCatalog(str(tmp_path))
    path = tmp_path / "live" / "instance-1" / "bar_0.feather"
    _write_flat_stream(path, bars, Bar)
    table = read_feather_coalesced(catalog.fs, str(path))
    assert table is not None

    written, streamed_any = _extend_table_chunked(catalog, catalog, Bar, table, chunk_rows=3)

    assert streamed_any
    assert written == 6
    landed = catalog.query(data_cls=Bar)
    assert len(landed) == 6
    assert all(str(bar.bar_type).endswith("-INTERNAL") for bar in landed)
    assert not any(str(bar.bar_type).endswith("-EXTERNAL") for bar in landed)


def test_extend_chunked_crash_then_rerun_is_idempotent(tmp_path: Path) -> None:
    """T8b: a crash after chunk k, then a rerun over the same (unmodified)
    source, lands exactly the full row set with no ``ExtendWriteMismatch``."""
    ts_inits = [1_000_000_000 + i for i in range(9)]
    catalog = ParquetDataCatalog(str(tmp_path))
    path = tmp_path / "live" / "instance-1" / "instrument_status_0.feather"
    table = _extend_status_table(catalog, path, ts_inits)

    import breezy.runtime.quote_tape_ingest_cli as cli_module

    real_write = cli_module.write_fresh_capture_rows
    call_count = {"n": 0}

    def crashing_write(
        write_target: ParquetDataCatalog, data_cls: type, objects: list[Any]
    ) -> int:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated crash mid-EXTEND")
        return real_write(write_target, data_cls, objects)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli_module, "write_fresh_capture_rows", crashing_write)
        with pytest.raises(RuntimeError, match="simulated crash"):
            _extend_table_chunked(catalog, catalog, InstrumentStatus, table, chunk_rows=3)

    landed_after_crash = {r.ts_init for r in catalog.query(data_cls=InstrumentStatus)}
    assert landed_after_crash == {1_000_000_000, 1_000_000_001, 1_000_000_002}  # chunk 1 only

    rerun_table = read_feather_coalesced(catalog.fs, str(path))
    written, streamed_any = _extend_table_chunked(
        catalog, catalog, InstrumentStatus, rerun_table, chunk_rows=3
    )

    assert streamed_any
    landed_final = {r.ts_init for r in catalog.query(data_cls=InstrumentStatus)}
    assert landed_final == set(ts_inits)
    assert written == 6  # only the 6 rows chunk 2+3 hold; chunk 1's 3 dedupe to 0


def test_extend_chunked_unsorted_input_each_chunk_dedupe_window_is_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-R5: an unsorted source is sorted ONCE (P3), then each chunk's dedupe
    window is that chunk's own [lo, hi] on the SORTED order, never the file's
    original (unsorted) order or the full table's range."""
    catalog = ParquetDataCatalog(str(tmp_path))
    path = tmp_path / "live" / "instance-1" / "instrument_status_0.feather"
    unsorted_order = [3, 1, 4, 0, 2, 5, 8, 6, 7, 9]  # 10 rows, out of order
    ts_inits = [1_000_000_000 + i for i in unsorted_order]
    table = _extend_status_table(catalog, path, ts_inits)

    query_windows: list[tuple[int, int]] = []
    real_query = ParquetDataCatalog.query

    def spy_query(self: ParquetDataCatalog, *args: Any, **kwargs: Any) -> list[Any]:
        if "start" in kwargs and "end" in kwargs:
            query_windows.append((kwargs["start"], kwargs["end"]))
        return real_query(self, *args, **kwargs)

    monkeypatch.setattr(ParquetDataCatalog, "query", spy_query)

    written, streamed_any = _extend_table_chunked(
        catalog, catalog, InstrumentStatus, table, chunk_rows=4
    )

    assert streamed_any
    assert written == 10
    assert query_windows == [
        (1_000_000_000, 1_000_000_003),
        (1_000_000_004, 1_000_000_007),
        (1_000_000_008, 1_000_000_009),
    ]
    landed = sorted(r.ts_init for r in catalog.query(data_cls=InstrumentStatus))
    assert landed == sorted(ts_inits)


def test_extend_overlapping_stream_routes_through_extend_table_chunked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5b wiring: the whole-instance EXTEND path calls
    :func:`_extend_table_chunked`, not the raw unchunked pair directly."""
    fixture_dir = tmp_path / "extend"
    instance_dir = fixture_dir / "live" / "instance-1"
    path = instance_dir / "instrument_status_0.feather"
    _write_flat_stream(path, [_status(i) for i in range(5)], InstrumentStatus)
    catalog = ParquetDataCatalog(str(fixture_dir))
    catalog.convert_stream_to_data("instance-1", InstrumentStatus, subdirectory="live")
    _write_flat_stream(path, [_status(i) for i in range(20)], InstrumentStatus)

    import breezy.runtime.quote_tape_ingest_cli as cli_module

    calls: list[int] = []
    real_chunked = cli_module._extend_table_chunked

    def spy_chunked(
        catalog_arg: ParquetDataCatalog,
        write_target: ParquetDataCatalog,
        data_cls: type,
        table: Any,
        **kwargs: Any,
    ) -> tuple[int, bool]:
        calls.append(len(table))
        return real_chunked(catalog_arg, write_target, data_cls, table, **kwargs)

    monkeypatch.setattr(cli_module, "_extend_table_chunked", spy_chunked)

    outcome = _extend_overlapping_stream(catalog, "instance-1", InstrumentStatus, "live")

    assert outcome == "converted"
    assert calls == [20]
    assert len(catalog.query(data_cls=InstrumentStatus)) == 20


def test_per_file_extend_fallback_routes_through_extend_table_chunked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5b wiring: the per-file EXTEND fallback calls
    :func:`_extend_table_chunked` too."""
    fixture = _TR8Fixture(tmp_path)
    fixture.seed(range(5))
    path = fixture.instance_dir / "instrument_status_0.feather"
    _write_flat_stream(path, [_status(i) for i in range(3, 10)], InstrumentStatus)
    _age(path)
    report = inspect_feather_file(path)

    import breezy.runtime.quote_tape_ingest_cli as cli_module

    calls: list[int] = []
    real_chunked = cli_module._extend_table_chunked

    def spy_chunked(
        catalog_arg: ParquetDataCatalog,
        write_target: ParquetDataCatalog,
        data_cls: type,
        table: Any,
        **kwargs: Any,
    ) -> tuple[int, bool]:
        calls.append(len(table))
        return real_chunked(catalog_arg, write_target, data_cls, table, **kwargs)

    monkeypatch.setattr(cli_module, "_extend_table_chunked", spy_chunked)

    _result, converted, _open = _convert_one_tick_type_per_file(
        fixture.catalog,
        fixture.instance_dir,
        fixture.instance,
        InstrumentStatus,
        frozenset(),
        {path: report},
        instance_is_dead=True,
        dry_run=False,
    )

    assert converted
    assert calls == [7]


def _patch_zero_row_file(
    monkeypatch: pytest.MonkeyPatch, zero_row_count: int
) -> None:
    """Make ``_extend_table_chunked`` report ``(0, False)`` for the one file
    whose source table has ``zero_row_count`` rows -- simulating a
    non-empty source that transforms to zero rows -- and behave normally
    (real chunking) for every other file, exactly like
    :func:`test_extend_overlapping_stream_routes_through_extend_table_chunked`.
    """
    import breezy.runtime.quote_tape_ingest_cli as cli_module

    real_chunked = cli_module._extend_table_chunked

    def spy_chunked(
        catalog_arg: ParquetDataCatalog,
        write_target: ParquetDataCatalog,
        data_cls: type,
        table: Any,
        **kwargs: Any,
    ) -> tuple[int, bool]:
        if len(table) == zero_row_count:
            return 0, False
        return real_chunked(catalog_arg, write_target, data_cls, table, **kwargs)

    monkeypatch.setattr(cli_module, "_extend_table_chunked", spy_chunked)


def test_extend_overlapping_stream_zero_row_file_fails_like_the_fast_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """FU-14 (review of e199f07, TRUE PARITY): one file's post-transform
    table comes back empty despite a non-empty source table. The fast path's
    equivalent guard (quote_tape_ingest_cli.py:1459-1470) logs ERROR and
    counts the file ``failed`` so the type is never marked converted; the
    whole-instance EXTEND path must match -- a WARNING plus a silent
    ``CONVERTED`` return is permanent, silent row loss (the type is never
    revisited). The other, good file's rows still land this run (only the
    rerun test asserts they are not duplicated)."""
    instance_dir = tmp_path / "live" / "instance-1"
    empty_path = instance_dir / "instrument_status_0.feather"
    good_path = instance_dir / "instrument_status_1.feather"
    _write_flat_stream(empty_path, [_status(i) for i in range(5)], InstrumentStatus)
    _write_flat_stream(good_path, [_status(50 + i) for i in range(7)], InstrumentStatus)
    catalog = ParquetDataCatalog(str(tmp_path))

    import breezy.runtime.quote_tape_ingest_cli as cli_module

    _patch_zero_row_file(monkeypatch, zero_row_count=5)

    with (
        caplog.at_level(logging.ERROR, logger=cli_module.__name__),
        pytest.raises(ValueError, match="InstrumentStatus"),
    ):
        _extend_overlapping_stream(catalog, "instance-1", InstrumentStatus, "live")

    # The good file's rows still land this run -- only a rerun (see below)
    # proves they are not duplicated.
    assert len(catalog.query(data_cls=InstrumentStatus)) == 7

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "the empty-post-transform file must log an ERROR, not skip silently"
    message = errors[0].getMessage()
    assert "instance-1" in message
    assert str(empty_path) in message
    assert "5" in message


def test_extend_overlapping_stream_zero_row_rerun_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FU-14: because the type is never marked converted, a second run over
    the SAME unchanged tape retries -- and must not duplicate the good
    file's rows (dedupe via ``_drop_already_landed_unfiltered``)."""
    instance_dir = tmp_path / "live" / "instance-1"
    empty_path = instance_dir / "instrument_status_0.feather"
    good_path = instance_dir / "instrument_status_1.feather"
    _write_flat_stream(empty_path, [_status(i) for i in range(5)], InstrumentStatus)
    _write_flat_stream(good_path, [_status(50 + i) for i in range(7)], InstrumentStatus)
    catalog = ParquetDataCatalog(str(tmp_path))

    _patch_zero_row_file(monkeypatch, zero_row_count=5)

    for _ in range(2):
        with pytest.raises(ValueError, match="InstrumentStatus"):
            _extend_overlapping_stream(catalog, "instance-1", InstrumentStatus, "live")

    assert len(catalog.query(data_cls=InstrumentStatus)) == 7


def test_ingest_instance_treats_extends_zero_row_file_as_a_failed_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FU-14: through :func:`ingest_instance` (:func:`_extend_overlapping_stream`
    used directly as ``convert_fn``, matching its ``ConvertFn`` signature),
    the zero-row-file ``ValueError`` must be caught exactly like any other
    type failure -- ``TypeConversionResult.outcome == "failed"``, the
    ``.converted-instrument_status`` marker is never written, and the
    INSTANCE outcome is ``"failed"`` (never silently ``"converted"``)."""
    instance_dir = tmp_path / "live" / "instance-1"
    empty_path = instance_dir / "instrument_status_0.feather"
    good_path = instance_dir / "instrument_status_1.feather"
    _write_flat_stream(empty_path, [_status(i) for i in range(5)], InstrumentStatus)
    _write_flat_stream(good_path, [_status(50 + i) for i in range(7)], InstrumentStatus)
    catalog = ParquetDataCatalog(str(tmp_path))

    _patch_zero_row_file(monkeypatch, zero_row_count=5)

    from breezy.runtime.quote_tape_ingest_cli import ingest_instance

    result = ingest_instance(
        catalog,
        tmp_path,
        "instance-1",
        "live",
        (InstrumentStatus,),
        convert_fn=_extend_overlapping_stream,
    )

    assert result.outcome == "failed"
    assert result.type_results[0].outcome == "failed"
    assert not (instance_dir / ".converted-instrument_status").exists()
    assert len(catalog.query(data_cls=InstrumentStatus)) == 7
