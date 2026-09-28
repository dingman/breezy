"""ING-2-RSS: the EXTEND dedupe (``_drop_already_landed_unfiltered``) takes a
guarded, identifier-filtered native ``query`` for the metadata-keyed tick
types (``QuoteTick``, ``TradeTick``, ``OrderBookDepth10``) whenever their
type root holds no FLAT file, instead of always deserialising every landed
instrument's rows in the chunk's time window -- the root cause of EXTEND's
memory and wall-time blow-up (docs plan: scratchpad ``plan_r1.md`` /
``plan_r2_delta.md``, binding delta).

Safety note on the FLAT-guard tests (found during implementation, not
anticipated by the plan): a ``QuoteTick``/``OrderBookDepth10`` parquet file
with NO ``instrument_id`` footer metadata is a HARD Rust panic
(``crates/persistence/src/backend/session.rs``,
``MissingMetadata("instrument_id")``) the moment ANY *unfiltered* ``query()``
tries to deserialise it -- an uncatchable process abort (SIGABRT), not a
Python exception, and identical in TODAY'S unmodified code (this fix does
not introduce it: the unfiltered branch that would hit it is byte-identical
to before). Such a file is therefore built here with the real native writer
(``convert_stream_to_data``, confirmed to write it successfully without ever
reading it back), used only to make ``_type_root_has_flat_files`` -- a
filename-only ``fs.ls`` check that never opens the file -- see it; the
dispatch decision itself is proven with a ``query`` spy that intercepts the
call before the real (crash-prone) read would run, and the "leak" mutation
proof only ever exercises the identifier-FILTERED query, which is safe
because ``filter_files`` excludes FLAT files by path before any file is
opened (``TestTheMixedCatalogLayoutIsPinned``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import class_to_filename
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

from breezy.adapters.polymarket_us.tape_records import DepthTruncation
from breezy.runtime import quote_tape_salvage
from breezy.runtime.quote_tape_salvage import (
    _drop_already_landed_unfiltered,
    _type_root_has_flat_files,
)

_A = InstrumentId.from_str("A/USD.SIM")
_B = InstrumentId.from_str("B/USD.SIM")


def _depth10(instrument_id: InstrumentId, ts: int) -> OrderBookDepth10:
    """Minimal Depth10 frame: one real bid/ask level, nine padding levels."""
    bid = BookOrder(OrderSide.BUY, Price.from_str("1.00000"), Quantity.from_int(1), 0)
    ask = BookOrder(OrderSide.SELL, Price.from_str("1.00010"), Quantity.from_int(1), 0)
    pad_bid = BookOrder(OrderSide.BUY, Price.from_str("0.00000"), Quantity.from_int(0), 0)
    pad_ask = BookOrder(OrderSide.SELL, Price.from_str("0.00000"), Quantity.from_int(0), 0)
    counts = [1, *[0] * 9]
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=[bid, *[pad_bid] * 9],
        asks=[ask, *[pad_ask] * 9],
        bid_counts=counts,
        ask_counts=counts,
        flags=0,
        sequence=0,
        ts_event=ts,
        ts_init=ts,
    )


def _quote(instrument_id: InstrumentId, ts: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str("1.00000"),
        ask_price=Price.from_str("1.00010"),
        bid_size=Quantity.from_int(1),
        ask_size=Quantity.from_int(1),
        ts_event=ts,
        ts_init=ts,
    )


def _depth_truncation(instrument_id: InstrumentId, ts: int) -> DepthTruncation:
    return DepthTruncation(
        instrument_id=instrument_id,
        bid_levels_seen=12,
        ask_levels_seen=14,
        levels_dropped=2,
        ts_event=ts,
        ts_init=ts,
    )


_BUILDERS = {QuoteTick: _quote, OrderBookDepth10: _depth10, DepthTruncation: _depth_truncation}


def _keys(objects: list[Any]) -> set[tuple[str, int]]:
    return {(obj.instrument_id.value, obj.ts_init) for obj in objects}


# ---------------------------------------------------------------------------
# T-EQ
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("data_cls", [QuoteTick, OrderBookDepth10, DepthTruncation])
def test_filtered_drop_set_matches_forced_unfiltered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_cls: type
) -> None:
    """The default (filtered) path drops exactly the same rows the legacy
    always-unfiltered path would: landed vs fresh, cross-instrument
    same-``ts_init`` (must NOT be dropped), inclusive bounds, and a chunk
    spanning two instruments. A query spy also proves the default path is
    genuinely identifier-filtered (ING-2-AMEND2 plan r1 test 1) -- RED for
    ``DepthTruncation`` on today's code, which dispatches it unfiltered.
    """
    build = _BUILDERS[data_cls]
    catalog = ParquetDataCatalog(str(tmp_path))

    # Landed: A at ts 200..209; B at ts 205..214 -- overlapping on the high
    # side, including the SAME ts_init values (205..209) as A.
    catalog.write_data([build(_A, ts) for ts in range(200, 210)])
    catalog.write_data([build(_B, ts) for ts in range(205, 215)])
    assert not _type_root_has_flat_files(catalog, data_cls)

    # One chunk, both instruments, ts 200..214 each (30 rows total). A's
    # landed range (200..209) sits inside this; B's landed range (205..214)
    # too. A's 210..214 are landed only for B (must survive for A); B's
    # 200..204 are landed only for A (must survive for B).
    chunk = [build(_A, ts) for ts in range(200, 215)] + [build(_B, ts) for ts in range(200, 215)]

    real_query = catalog.query
    calls: list[dict[str, Any]] = []

    def spy_query(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return real_query(*args, **kwargs)

    monkeypatch.setattr(catalog, "query", spy_query)

    filtered_fresh = _drop_already_landed_unfiltered(catalog, data_cls, list(chunk))
    filtered_keys = _keys(filtered_fresh)

    assert calls and calls[-1].get("identifiers"), (
        f"{data_cls.__name__}: the default dispatch must call query with "
        "identifiers= (ING-2-AMEND2 widens the identifier-filterable set to "
        "include this type)"
    )

    monkeypatch.setattr(quote_tape_salvage, "_type_root_has_flat_files", lambda *a, **k: True)
    forced_unfiltered_fresh = _drop_already_landed_unfiltered(catalog, data_cls, list(chunk))
    forced_unfiltered_keys = _keys(forced_unfiltered_fresh)

    assert filtered_keys == forced_unfiltered_keys

    expected = _keys([build(_A, ts) for ts in range(210, 215)]) | _keys(
        [build(_B, ts) for ts in range(200, 205)]
    )
    assert filtered_keys == expected


@pytest.mark.parametrize("data_cls", [QuoteTick, OrderBookDepth10])
def test_boundary_ts_init_is_inclusive_both_ends(tmp_path: Path, data_cls: type) -> None:
    build = _BUILDERS[data_cls]
    catalog = ParquetDataCatalog(str(tmp_path))
    # Landed exactly at what will be the chunk's lo (100) and hi (104), plus
    # one ns on either side of that window (99, 105).
    catalog.write_data([build(_A, ts) for ts in (99, 100, 104, 105)])

    chunk = [build(_A, ts) for ts in range(100, 105)]  # lo=100, hi=104
    fresh = _drop_already_landed_unfiltered(catalog, data_cls, list(chunk))

    # 100 and 104 are landed and inclusive-bound -- dropped. 99 and 105 are
    # landed but outside [100, 104]; the chunk never offered a candidate at
    # either value, so they can neither be dropped nor leak into `fresh`.
    assert {obj.ts_init for obj in fresh} == {101, 102, 103}


# ---------------------------------------------------------------------------
# T-FLAT-GUARD
# ---------------------------------------------------------------------------


_OTHER_FLAT = InstrumentId.from_str("OTHFLAT/USD.SIM")


def _write_flat_file_without_instrument_id_metadata(
    catalog: ParquetDataCatalog, instance_id: str, data_cls: type, ts: int
) -> None:
    """Land a row at ``ts`` (for :data:`_A`) as a genuine FLAT file at
    ``data_cls``'s type root, via the real native writer
    (``convert_stream_to_data``).

    For ``QuoteTick``/``OrderBookDepth10``, this strips the ``instrument_id``
    schema-metadata key -- the one condition that makes native's own
    converter place the result FLAT instead of per-instrument. ``DepthTruncation``
    carries no schema metadata at all (confirmed empirically, ING-2-AMEND2:
    ``ArrowSerializer.serialize_batch`` returns a bare ``pa.Table`` with
    ``schema.metadata is None`` for it -- its wrangler keys off the ordinary
    ``instrument_id`` COLUMN, not footer metadata), so metadata-stripping
    cannot produce a FLAT file for it. A FLAT write is instead produced the
    way native itself produces one for this type: two DIFFERENT instruments'
    rows (``_A`` at ``ts``, :data:`_OTHER_FLAT` at the same ``ts``) in the
    SAME feather stream, which ``convert_stream_to_data`` cannot key to a
    single per-instrument directory and writes to the type root instead
    (empirically confirmed: still a genuine ``_type_root_has_flat_files``
    hit, and an identifier-filtered query for ``_A`` alone excludes it, same
    as the metadata-stripped case). This file must NEVER be read back
    through an *unfiltered* ``query()`` in this test file -- see the module
    docstring for why that aborts the whole process for the Rust-native types.
    """
    if data_cls is DepthTruncation:
        objects = [_BUILDERS[data_cls](_A, ts), _BUILDERS[data_cls](_OTHER_FLAT, ts)]
        instance_dir = Path(catalog.path) / "live" / instance_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        feather_path = instance_dir / f"{class_to_filename(data_cls)}_0.feather"
        first = ArrowSerializer.serialize_batch([objects[0]], data_cls=data_cls)
        with feather_path.open("wb") as handle:
            writer = pa.ipc.new_stream(handle, first.schema)
            for obj in objects:
                piece = ArrowSerializer.serialize_batch([obj], data_cls=data_cls)
                table = (
                    pa.Table.from_batches([piece]) if isinstance(piece, pa.RecordBatch) else piece
                )
                writer.write_table(table)
            writer.close()
        catalog.convert_stream_to_data(instance_id, data_cls, subdirectory="live")
        return

    obj = _BUILDERS[data_cls](_A, ts)
    piece = ArrowSerializer.serialize_batch([obj], data_cls=data_cls)
    table = pa.Table.from_batches([piece]) if isinstance(piece, pa.RecordBatch) else piece
    stripped_meta = {k: v for k, v in table.schema.metadata.items() if k != b"instrument_id"}
    stripped_table = table.cast(table.schema.with_metadata(stripped_meta))

    instance_dir = Path(catalog.path) / "live" / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    feather_path = instance_dir / f"{class_to_filename(data_cls)}_0.feather"
    with feather_path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, stripped_table.schema)
        writer.write_table(stripped_table)
        writer.close()
    catalog.convert_stream_to_data(instance_id, data_cls, subdirectory="live")


@pytest.mark.parametrize("data_cls", [QuoteTick, OrderBookDepth10, DepthTruncation])
def test_a_flat_file_at_the_type_root_forces_the_unfiltered_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_cls: type
) -> None:
    """Behaviour-preserving regression check for ``DepthTruncation`` (plan r2
    delta note 2): NOT RED on today's code, because today's dispatch is
    unconditionally unfiltered for it regardless of any flat file."""
    catalog = ParquetDataCatalog(str(tmp_path))
    catalog.write_data([_BUILDERS[data_cls](_A, ts) for ts in range(300, 310)])
    _write_flat_file_without_instrument_id_metadata(catalog, "instance-flat", data_cls, 305)
    assert _type_root_has_flat_files(catalog, data_cls)

    calls: list[dict[str, Any]] = []

    def spy_query(*args: Any, **kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return []  # never actually deserialise the FLAT file -- see module docstring

    monkeypatch.setattr(catalog, "query", spy_query)
    chunk = [_BUILDERS[data_cls](_A, ts) for ts in range(300, 310)]
    _drop_already_landed_unfiltered(catalog, data_cls, list(chunk))

    assert len(calls) == 1
    assert calls[0].get("identifiers") is None, (
        "a FLAT file is present at the type root -- the dispatch must take "
        "the unfiltered path (no `identifiers`), exactly as before this fix"
    )


@pytest.mark.parametrize("data_cls", [QuoteTick, OrderBookDepth10, DepthTruncation])
def test_forcing_the_filtered_path_over_a_flat_file_leaks_the_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_cls: type
) -> None:
    """Mutation proof: the guard is load-bearing. If it were bypassed
    (always filtered), the flat-landed row would leak back in as "fresh" --
    silently re-written as a duplicate. Safe: an identifier-filtered query
    excludes FLAT files by PATH before any file is opened, so this never
    touches the metadata-less file's contents.

    RED for ``DepthTruncation`` on today's code (plan r1 test 2): it is not
    yet in the identifier-filterable set, so forcing ``_type_root_has_flat_files``
    to lie has no effect -- the dispatch stays unfiltered either way, and the
    already-landed row does NOT leak back in, failing the ``len(fresh) == 1``
    assertion below.
    """
    catalog = ParquetDataCatalog(str(tmp_path))
    _write_flat_file_without_instrument_id_metadata(catalog, "instance-flat", data_cls, 305)
    assert _type_root_has_flat_files(catalog, data_cls)

    monkeypatch.setattr(quote_tape_salvage, "_type_root_has_flat_files", lambda *a, **k: False)
    chunk = [_BUILDERS[data_cls](_A, 305)]
    fresh = _drop_already_landed_unfiltered(catalog, data_cls, list(chunk))

    assert len(fresh) == 1, (
        "forcing the filtered path over a FLAT-file root must leak the "
        "already-landed row back in as fresh -- proving the guard, not "
        "luck, is what keeps it out normally"
    )


# ---------------------------------------------------------------------------
# T-ERR
# ---------------------------------------------------------------------------


def test_a_read_error_propagates_never_as_no_rows_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = ParquetDataCatalog(str(tmp_path))
    catalog.write_data([_quote(_A, ts) for ts in range(400, 405)])

    def boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise pa.lib.ArrowInvalid("synthetic corrupt read")

    monkeypatch.setattr(catalog, "query", boom)
    chunk = [_quote(_A, ts) for ts in range(400, 405)]
    with pytest.raises(pa.lib.ArrowInvalid):
        _drop_already_landed_unfiltered(catalog, QuoteTick, list(chunk))


# ---------------------------------------------------------------------------
# T-MEM (L-49): ru_maxrss delta, fresh child process, never tracemalloc.
# ---------------------------------------------------------------------------

_CHILD_SCRIPT = Path(__file__).with_name("_extend_dedupe_filtered_child.py")
#: Kept small enough that fixture build + two child runs stay well under the
#: file's ~60s budget; the RATIO signal, not the absolute row count, is what
#: the assertion needs (a real production chunk is 50_000, EXTEND_CHUNK_ROWS).
_ROWS_PER_INSTRUMENT = 2_000
_TARGET_ID_MEM = InstrumentId.from_str("TGT/USD.SIM")
#: Design ceiling (plan r2 delta): filtered ΔRSS must not scale with K.
_RATIO_CEILING = 1.5
#: KiB slack absorbing allocator/measurement noise between two otherwise
#: near-identical child runs -- small next to the multi-hundred-MiB signal
#: this scaling bound exists to catch.
_SLACK_KIB = 8 * 1024


def _other_id(index: int) -> InstrumentId:
    return InstrumentId.from_str(f"OTH{index}/USD.SIM")


def _build_mem_catalog(root: Path, *, other_count: int, base_ts: int) -> None:
    """Land ``_ROWS_PER_INSTRUMENT`` rows for the target instrument, plus for
    ``other_count`` OTHER instruments, all in the SAME ``[base_ts, base_ts +
    _ROWS_PER_INSTRUMENT)`` window -- via the real ``write_data`` writer.
    """
    catalog = ParquetDataCatalog(str(root))
    rows = [_depth10(_TARGET_ID_MEM, base_ts + i) for i in range(_ROWS_PER_INSTRUMENT)]
    for other in range(other_count):
        oid = _other_id(other)
        rows.extend(_depth10(oid, base_ts + i) for i in range(_ROWS_PER_INSTRUMENT))
    catalog.write_data(rows)


def _run_child(catalog_root: Path, warmup_root: Path, base_ts: int, count: int) -> dict[str, int]:
    result = subprocess.run(
        [
            sys.executable,
            str(_CHILD_SCRIPT),
            "--catalog-root",
            str(catalog_root),
            "--warmup-root",
            str(warmup_root),
            "--base-ts",
            str(base_ts),
            "--count",
            str(count),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    result.check_returncode()
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.memory
def test_filtered_extend_dedupe_rss_does_not_scale_with_other_instruments(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """RED against the base (no guard): the unfiltered call deserialises
    every other landed instrument in the window too, so ΔRSS(K=20) scales
    with K and blows past the ceiling. GREEN once the filtered path reads
    only the target instrument's own rows, independent of K.
    """
    root = tmp_path_factory.mktemp("t_mem")
    warmup_root = root / "warmup"
    warmup_root.mkdir()

    base_ts = 1_000_000_000
    catalog_k1 = root / "k1"
    catalog_k20 = root / "k20"
    _build_mem_catalog(catalog_k1, other_count=1, base_ts=base_ts)
    _build_mem_catalog(catalog_k20, other_count=20, base_ts=base_ts)

    k1 = _run_child(catalog_k1, warmup_root, base_ts, _ROWS_PER_INSTRUMENT)
    k20 = _run_child(catalog_k20, warmup_root, base_ts, _ROWS_PER_INSTRUMENT)

    # Correctness sanity, not just speed/memory: every chunk row was already
    # landed for the target, so nothing should survive as "fresh" either way.
    assert k1["fresh"] == 0
    assert k20["fresh"] == 0

    delta_k1 = k1["peak_kb"] - k1["baseline_kb"]
    delta_k20 = k20["peak_kb"] - k20["baseline_kb"]

    assert delta_k20 <= _RATIO_CEILING * delta_k1 + _SLACK_KIB, (
        f"ΔRSS(K=20)={delta_k20} KiB is more than {_RATIO_CEILING}x "
        f"ΔRSS(K=1)={delta_k1} KiB + {_SLACK_KIB} KiB slack -- the EXTEND "
        f"dedupe is still scaling with the number of OTHER landed instruments"
    )


# ---------------------------------------------------------------------------
# T-MEM, DepthTruncation sibling (ING-2-AMEND2 plan r1 test 3 / r2 delta).
#
# Opt-in via BREEZY_RUN_SLOW (L-54): the shared ``pyproject.toml`` addopts
# and the ``memory`` marker's own default-gate wording are containment-pinned
# (``test_probe_containment.py``) and must not be edited for this feature;
# this test opts itself out of the default run the same way
# ``test_census_column_scan_memory.py``'s ``TestNewPathDeltaRssBoundAtD6_150k``
# does, via a plain ``skipif`` on the test itself, never a change to the
# pinned filter string.
# ---------------------------------------------------------------------------

_CHILD_SCRIPT_DEPTH_TRUNCATION = Path(__file__).with_name(
    "_extend_dedupe_filtered_child_depth_truncation.py"
)

#: ``DepthTruncation``'s per-row footprint (4 small ints + an id string) is
#: far smaller than ``OrderBookDepth10``'s (20 price levels x qty/count
#: fields), so the shared sibling's ``_ROWS_PER_INSTRUMENT`` (2_000) measured
#: a ΔRSS(K=20) signal too small to reliably clear process-startup RSS noise
#: (calibrated empirically, ING-2-AMEND2: 2_000 rows/instrument alternated
#: between a real ~50-67 MiB delta and a noise-masked ~0 MiB delta across
#: back-to-back runs; 20_000 rows/instrument gave a consistent ~240-250 MiB
#: delta across repeated runs). Kept separate from ``_ROWS_PER_INSTRUMENT`` so
#: the sibling test's own calibration is untouched.
_ROWS_PER_INSTRUMENT_DEPTH_TRUNCATION = 20_000


def _build_mem_catalog_depth_truncation(root: Path, *, other_count: int, base_ts: int) -> None:
    """Land ``_ROWS_PER_INSTRUMENT_DEPTH_TRUNCATION`` ``DepthTruncation`` rows
    for the target instrument, plus for ``other_count`` OTHER instruments, all
    in the SAME ``[base_ts, base_ts + _ROWS_PER_INSTRUMENT_DEPTH_TRUNCATION)``
    window -- via the real ``write_data`` writer.
    """
    catalog = ParquetDataCatalog(str(root))
    rows = [
        _depth_truncation(_TARGET_ID_MEM, base_ts + i)
        for i in range(_ROWS_PER_INSTRUMENT_DEPTH_TRUNCATION)
    ]
    for other in range(other_count):
        oid = _other_id(other)
        rows.extend(
            _depth_truncation(oid, base_ts + i)
            for i in range(_ROWS_PER_INSTRUMENT_DEPTH_TRUNCATION)
        )
    catalog.write_data(rows)


def _run_child_depth_truncation(
    catalog_root: Path, warmup_root: Path, base_ts: int, count: int
) -> dict[str, int]:
    result = subprocess.run(
        [
            sys.executable,
            str(_CHILD_SCRIPT_DEPTH_TRUNCATION),
            "--catalog-root",
            str(catalog_root),
            "--warmup-root",
            str(warmup_root),
            "--base-ts",
            str(base_ts),
            "--count",
            str(count),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    result.check_returncode()
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.memory
@pytest.mark.skipif(
    os.environ.get("BREEZY_RUN_SLOW") != "1",
    reason="slow child-process RSS-scaling test; set BREEZY_RUN_SLOW=1 to run",
)
def test_filtered_extend_dedupe_rss_does_not_scale_with_other_instruments_depth_truncation(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """RED against today's code (no guard for ``DepthTruncation``): the
    unfiltered call deserialises every other landed instrument in the window
    too, so ΔRSS(K=20) scales with K and blows past the ceiling. GREEN once
    ``DepthTruncation`` joins the identifier-filterable set and the filtered
    path reads only the target instrument's own rows, independent of K.
    """
    root = tmp_path_factory.mktemp("t_mem_dt")
    warmup_root = root / "warmup"
    warmup_root.mkdir()

    base_ts = 1_000_000_000
    catalog_k1 = root / "k1"
    catalog_k20 = root / "k20"
    _build_mem_catalog_depth_truncation(catalog_k1, other_count=1, base_ts=base_ts)
    _build_mem_catalog_depth_truncation(catalog_k20, other_count=20, base_ts=base_ts)

    k1 = _run_child_depth_truncation(
        catalog_k1, warmup_root, base_ts, _ROWS_PER_INSTRUMENT_DEPTH_TRUNCATION
    )
    k20 = _run_child_depth_truncation(
        catalog_k20, warmup_root, base_ts, _ROWS_PER_INSTRUMENT_DEPTH_TRUNCATION
    )

    # Correctness sanity, not just speed/memory: every chunk row was already
    # landed for the target, so nothing should survive as "fresh" either way.
    assert k1["fresh"] == 0
    assert k20["fresh"] == 0

    delta_k1 = k1["peak_kb"] - k1["baseline_kb"]
    delta_k20 = k20["peak_kb"] - k20["baseline_kb"]

    assert delta_k20 <= _RATIO_CEILING * delta_k1 + _SLACK_KIB, (
        f"ΔRSS(K=20)={delta_k20} KiB is more than {_RATIO_CEILING}x "
        f"ΔRSS(K=1)={delta_k1} KiB + {_SLACK_KIB} KiB slack -- the EXTEND "
        f"dedupe is still scaling with the number of OTHER landed instruments"
    )
