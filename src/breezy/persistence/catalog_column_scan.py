"""Object-free, column-projected catalog scans (REPLAY-BIGINST).

Why this module exists
-----------------------
The replay-sufficiency census (``scripts/analysis/replay_sufficiency_census.py``)
used to discover a station-day's depth/quote span by asking
``run_weather_strategy_backtests._select_capture_instruments`` for the FULL
``OrderBookDepth10``/``QuoteTick`` object lists for every instrument, via
``ParquetDataCatalog.order_book_depth10``/``.quote_ticks``. That builds one
Python object per row for every row in the file -- the census only ever reads
``ts_event`` and whether any ask level is populated (``breezy.strategy.depth10.
best_order``), so almost all of that memory is wasted, and it scales with the
size of the largest captured instance rather than the census's own working set
(``docs/plans/backlog/EDGE_2026-09-27/REPLAY-BIGINST_plan_r1_2026-09-27.md``).

This module reads the SAME converted parquet files with
``pyarrow.parquet.ParquetFile.iter_batches``, projecting only the columns the
census actually consumes (``ts_event`` plus ``ask_size_0..9`` for depth), and
folding the result with a plain running min/max (:func:`_fold_extent`)
instead of materialising rows. That fold is deliberately NOT
``breezy.analysis.replay_sufficiency.WindowExtentFold``, even though it is
the same algorithm: the layering contract
(``pyproject.toml``'s ``[[tool.importlinter.contracts]]``, "Breezy top-level
source packages follow the documented layer direction" /
"The live trading path never imports the offline analysis layer") forbids
``breezy.persistence`` from importing ``breezy.analysis`` at all, so this
module keeps its own copy of the (three-line) reduction rather than importing
across that boundary. Nautilus itself is never modified: every entry point
here is a native, public ``ParquetDataCatalog``/``pyarrow.parquet`` API
(``get_file_list_from_data_cls``, schema introspection, ``iter_batches``).

Ask-mask semantics mirror ``breezy.strategy.depth10.best_order`` exactly: a
level is "populated" iff its size is not the Arrow zero-fill pad. Sizes are
raw ``binary(w)`` (``w`` = ``nautilus_pyo3.PRECISION_BYTES``, read from the
file's own schema, never hard-coded -- D-3/E-B3c), so "size > 0" is exactly
"any byte in the ``w``-byte value is not zero", i.e. the raw bytes are not all
zero -- decoding the fixed-point decimal is never needed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Final

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.schema import NAUTILUS_ARROW_SCHEMA

__all__ = [
    "CatalogColumnScanError",
    "count_depth_rows",
    "group_files_by_identifier",
    "scan_depth_window",
    "scan_quote_window",
]

_TS_EVENT_COLUMN: Final[str] = "ts_event"
_ASK_SIZE_COLUMNS: Final[tuple[str, ...]] = tuple(f"ask_size_{i}" for i in range(10))
_DEFAULT_BATCH_SIZE: Final[int] = 65_536


class CatalogColumnScanError(ValueError):
    """The on-disk parquet schema does not match what this object-free scan
    assumes. Raised instead of silently mis-reading a future Nautilus column
    rename/retype (R1 in the plan's risk table)."""


def group_files_by_identifier(catalog: ParquetDataCatalog, data_cls: type) -> dict[str, list[str]]:
    """Every ``data_cls`` parquet file under ``catalog``, grouped by the SAME
    identifier :meth:`ParquetDataCatalog.filter_files` derives from a file
    path (``file_path.split("/")[-2]``) -- i.e.
    ``nautilus_trader.persistence.funcs.urisafe_identifier(instrument_id)``
    for a normally ``write_data``-produced layout, since ``_make_path``
    (``parquet.py:2465-2477``) writes each instrument under exactly that
    directory name (R3-1). Grouping by the RAW id would silently miss every
    id containing a character ``urisafe_identifier`` strips (currently ``/``).

    Globbed ONCE per instance/type: ``get_file_list_from_data_cls`` is called
    a single time here, rather than once per instrument id via
    ``catalog.filter_files(identifiers=[id])`` in a loop (r2 "smaller items").
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for file_path in catalog.get_file_list_from_data_cls(data_cls):
        grouped[file_path.split("/")[-2]].append(file_path)
    return dict(grouped)


def count_depth_rows(files: Sequence[str]) -> int:
    """All-time Depth10 row count for one instrument's files, footer-only.

    No window, no ask mask: this reproduces the oracle's own book-backed
    test, ``len(catalog.order_book_depth10(instrument_ids=[id])) > 0``
    (``run_weather_strategy_backtests.py:1392-1399``,
    ``weather_strategy_backtest_lib.py:492-513``), without ever reading a row
    -- ``pyarrow.parquet.ParquetFile(f).metadata.num_rows`` reads only the
    file footer, so memory here is O(1) per file (D-1).

    Each file is opened via ``with`` (review finding 1) so its handle closes
    deterministically even if a later file in ``files`` raises.
    """
    total = 0
    for file_path in files:
        with pq.ParquetFile(file_path) as parquet_file:
            total += parquet_file.metadata.num_rows
    return total


def _field_type(schema: pa.Schema, name: str, *, file_path: str) -> pa.DataType:
    if name not in schema.names:
        raise CatalogColumnScanError(f"{file_path}: missing required column {name!r}")
    return schema.field(name).type


def _assert_ts_event_type(
    file_schema: pa.Schema, expected_schema: pa.Schema, *, file_path: str
) -> None:
    actual = _field_type(file_schema, _TS_EVENT_COLUMN, file_path=file_path)
    expected = expected_schema.field(_TS_EVENT_COLUMN).type
    if actual != expected:
        raise CatalogColumnScanError(
            f"{file_path}: column {_TS_EVENT_COLUMN!r} has type {actual}, expected {expected}"
        )


def _ask_size_byte_width(
    file_schema: pa.Schema, expected_schema: pa.Schema, *, file_path: str
) -> int:
    """Presence + type-category check for every ``ask_size_k``, then the
    WIDTH check -- kept as its own explicit step (not folded into a generic
    per-column type-equality loop) because it is also the value the
    zero-scalar ask mask is built from. A mutant that hard-codes the width
    instead of deriving-and-asserting it here (M16) skips exactly this
    check, so a file whose ask-size width has drifted from
    ``NAUTILUS_ARROW_SCHEMA`` still reaches the (then wrong) mask
    construction downstream -- see ``test_census_column_scan.py`` E-B3c.
    """
    expected_width = expected_schema.field(_ASK_SIZE_COLUMNS[0]).type.byte_width
    width: int | None = None
    for name in _ASK_SIZE_COLUMNS:
        actual = _field_type(file_schema, name, file_path=file_path)
        if not pa.types.is_fixed_size_binary(actual):
            raise CatalogColumnScanError(
                f"{file_path}: column {name!r} has type {actual}, expected fixed-size binary"
            )
        if width is None:
            width = actual.byte_width
        elif actual.byte_width != width:
            raise CatalogColumnScanError(
                f"{file_path}: column {name!r} width {actual.byte_width} does not match "
                f"{_ASK_SIZE_COLUMNS[0]!r} width {width}"
            )
    if width != expected_width:
        raise CatalogColumnScanError(
            f"{file_path}: ask_size width {width} does not match "
            f"NAUTILUS_ARROW_SCHEMA width {expected_width}"
        )
    # `width is None` would mean `_ASK_SIZE_COLUMNS` was empty, which is
    # statically impossible (it is a fixed 10-element tuple) -- and would
    # have raised just above anyway, since `None != expected_width`. The
    # assert narrows the type for mypy instead of a bare `# type: ignore`.
    assert width is not None
    return width


def _assert_no_nulls(batch: pa.RecordBatch, columns: Sequence[str], *, file_path: str) -> None:
    for name in columns:
        if batch.column(name).null_count:
            raise CatalogColumnScanError(f"{file_path}: column {name!r} contains null values")


def _zero_binary_scalar(width: int) -> pa.Scalar:
    return pa.scalar(bytes(width), type=pa.binary(width))


def _ask_mask(batch: pa.RecordBatch, zero: pa.Scalar) -> pa.Array:
    mask = pc.not_equal(batch.column(_ASK_SIZE_COLUMNS[0]), zero)
    for name in _ASK_SIZE_COLUMNS[1:]:
        mask = pc.or_(mask, pc.not_equal(batch.column(name), zero))
    return mask


def _window_mask(ts_column: pa.Array, *, start_ns: int, end_ns: int) -> pa.Array:
    start = pa.scalar(start_ns, type=ts_column.type)
    end = pa.scalar(end_ns, type=ts_column.type)
    return pc.and_(pc.greater_equal(ts_column, start), pc.less(ts_column, end))


def _fold_extent(
    first_ns: int | None, last_ns: int | None, values: list[int]
) -> tuple[int | None, int | None]:
    """Running min/max over already window-filtered ``values`` (plain Python
    ``int``s, M13). Associative, so batches may be folded in any order --
    the same property ``WindowExtentFold`` documents, kept as a local copy
    here rather than an import: see the module docstring."""
    if not values:
        return first_ns, last_ns
    batch_lo, batch_hi = min(values), max(values)
    new_first = batch_lo if first_ns is None else min(first_ns, batch_lo)
    new_last = batch_hi if last_ns is None else max(last_ns, batch_hi)
    return new_first, new_last


def scan_depth_window(
    files: Sequence[str],
    *,
    start_ns: int,
    end_ns: int,
    should_stop: Callable[[], None],
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> tuple[int, int | None, int | None]:
    """In-window, ask-masked Depth10 row count + first/last ``ts_event``,
    for one instrument's already-converted parquet files.

    Object-free: projects only ``ts_event`` and ``ask_size_0..9`` per row
    group via ``pyarrow.parquet.ParquetFile.iter_batches``, so memory is
    O(batch) + O(#instruments) rather than O(#rows) -- no ``OrderBookDepth10``
    is ever built (r1 option (b)).

    ``should_stop()`` is called after EVERY batch and is expected to RAISE to
    signal a stop request (the census's own ``SystemExit(143)``, R3-4); this
    function never catches ``BaseException``, so a stop request always
    propagates and this function never returns a partial extent (D-4).

    ``should_stop`` stays typed ``Callable[[], None]`` rather than
    ``Callable[[], NoReturn]``: the injected callable, the census's own
    ``_raise_if_terminating``, only raises CONDITIONALLY (when a stop has
    actually been requested) and otherwise returns normally, so it is not a
    ``NoReturn`` function -- mypy rejects binding a ``Callable[[], None]``
    where a ``Callable[[], NoReturn]`` is expected (confirmed locally), since
    that would claim the call itself never returns.

    Returns plain Python ``int``s (never ``numpy`` scalars, M13): the row
    count, and the first/last in-window ``ts_event`` (``None`` if no row
    qualified).
    """
    expected_schema = NAUTILUS_ARROW_SCHEMA[OrderBookDepth10]
    columns = (_TS_EVENT_COLUMN, *_ASK_SIZE_COLUMNS)
    first_ns: int | None = None
    last_ns: int | None = None
    row_count = 0
    for file_path in files:
        # `with` (review finding 1) closes the file deterministically even
        # when `should_stop()` raises mid-scan -- never left to the garbage
        # collector.
        with pq.ParquetFile(file_path) as parquet_file:
            file_schema = parquet_file.schema_arrow
            _assert_ts_event_type(file_schema, expected_schema, file_path=file_path)
            width = _ask_size_byte_width(file_schema, expected_schema, file_path=file_path)
            zero = _zero_binary_scalar(width)
            for batch in parquet_file.iter_batches(batch_size=batch_size, columns=list(columns)):
                should_stop()
                _assert_no_nulls(batch, columns, file_path=file_path)
                ts_column = batch.column(_TS_EVENT_COLUMN)
                combined_mask = pc.and_(
                    _ask_mask(batch, zero),
                    _window_mask(ts_column, start_ns=start_ns, end_ns=end_ns),
                )
                matched = ts_column.filter(combined_mask).to_pylist()
                row_count += len(matched)
                first_ns, last_ns = _fold_extent(first_ns, last_ns, matched)
    return row_count, first_ns, last_ns


def scan_quote_window(
    files: Sequence[str],
    *,
    start_ns: int,
    end_ns: int,
    should_stop: Callable[[], None],
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> tuple[int, int | None, int | None]:
    """In-window QuoteTick row count + first/last ``ts_event``.

    No ask mask -- the oracle never filters quotes on ask depth, only on
    whether the instrument itself is book-backed (that filter is applied by
    the CALLER, before this function is ever invoked for a given id). Same
    object-free, batch-folded, ``should_stop``-raises contract as
    :func:`scan_depth_window`.
    """
    expected_schema = NAUTILUS_ARROW_SCHEMA[QuoteTick]
    columns = (_TS_EVENT_COLUMN,)
    first_ns: int | None = None
    last_ns: int | None = None
    row_count = 0
    for file_path in files:
        # `with` (review finding 1): see `scan_depth_window`.
        with pq.ParquetFile(file_path) as parquet_file:
            _assert_ts_event_type(parquet_file.schema_arrow, expected_schema, file_path=file_path)
            for batch in parquet_file.iter_batches(batch_size=batch_size, columns=list(columns)):
                should_stop()
                _assert_no_nulls(batch, columns, file_path=file_path)
                ts_column = batch.column(_TS_EVENT_COLUMN)
                matched = ts_column.filter(
                    _window_mask(ts_column, start_ns=start_ns, end_ns=end_ns)
                ).to_pylist()
                row_count += len(matched)
                first_ns, last_ns = _fold_extent(first_ns, last_ns, matched)
    return row_count, first_ns, last_ns
