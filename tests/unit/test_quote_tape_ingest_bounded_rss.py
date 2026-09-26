"""T5' (ING-2 S3a, AC-S3-1): the coalesced read materializes far fewer chunks
than the native, uncoalesced read -- measured residency-invariantly.

History (why this file changed): the original design (r3) measured
child-process ``ru_maxrss`` deltas. Under host memory pressure the OS is free
to evict the CONTROL arm's clean, file-backed pages between the baseline and
peak samples faster than they accumulate, so the control's observed ΔRSS can
read as ~0 even though the full stream was genuinely read and every message's
small ``RecordBatch`` was genuinely materialized. ``ru_maxrss`` measures
*instantaneous concurrent residency*, not *total bytes ever materialized* --
under reclaim pressure those two diverge, and the test went RED for a host
condition, not a code regression (see docs/core/PROGRESS.md, gate RED since
2d36198).

New metric: the number of **retained Arrow chunks** in the table each reader
returns (``table.column(0).num_chunks``). This is a property of the returned
Python/Arrow object graph, not of OS page residency -- unaffected by page
eviction, swapping, or concurrent host memory pressure, and (unlike
``tracemalloc``/the default pyarrow memory pool, both dead ends per the S3
Stage-0 findings) it is populated for both readers because it is read AFTER
the call returns, off the object itself, never off an allocator's bookkeeping
during the call.

It captures exactly the mechanism this test exists to pin (module docstring,
``feather_read.py``): native ``_read_feather_file`` calls ``reader.read_all()``,
which never combines chunks, so its result table retains one chunk per
Arrow IPC message -- for a one-row-per-message stream (the recorder's actual
shape) that is one chunk per ROW. ``read_feather_coalesced`` periodically
calls ``combine_chunks()`` every ``COALESCE_ROWS`` rows, so its result table
retains one chunk per coalesce GROUP. Verified empirically (N=100_000,
COALESCE_ROWS=8_192): native chunks == 100_000 (exactly, every run); coalesced
chunks == 13 == ceil(100_000 / 8_192) (exactly, every run). Both counts are
completely deterministic -- run twice, get the same answer, independent of
free memory, swap pressure, or any other resident-set state on the host.

Runs in the DEFAULT gate by design (r3-8 note, retained): this is the only
standing guard against a regression back to plain ``read_all()``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pyarrow as pa
import pytest
from nautilus_trader.model.data import InstrumentStatus
from nautilus_trader.model.enums import MarketStatusAction
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

from breezy.persistence.feather_read import COALESCE_ROWS, read_feather_coalesced

pytestmark = pytest.mark.memory

_IID = InstrumentId.from_str("EUR/USD.SIM")

#: Design budget (plan r3, units changed r3.1): the treatment must retain no
#: more than this fraction of the control's chunk count. Kept numerically
#: identical to the original ΔRSS-based ratio ceiling -- it is dimensionless
#: and the "coalesced must cost far less than uncoalesced" intent is unchanged.
_TREATMENT_RATIO_CEILING = 0.25

#: Growth-bound multiplier on the coalescer's OWN expected chunk growth
#: (ceil(n/COALESCE_ROWS)), kept numerically identical to the original
#: ΔRSS-vs-Δnbytes scaling factor: growth must not exceed k times what the
#: coalescing arithmetic itself predicts.
_SCALING_K = 2

#: Fixed additive headroom on the scaling bound, in CHUNKS. Replaces the
#: original 32 MiB byte-scale slack (meaningless for a chunk count that is a
#: two-digit number); this absorbs ceil()-boundary rounding between the two
#: N values, nothing more.
_SCALING_SLACK_CHUNKS = 4


def _status(index: int) -> InstrumentStatus:
    return InstrumentStatus(
        instrument_id=_IID,
        action=MarketStatusAction.TRADING,
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _write_stream(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    first = ArrowSerializer.serialize_batch([_status(0)], data_cls=InstrumentStatus)
    schema = first.schema
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, schema)
        for i in range(count):
            piece = ArrowSerializer.serialize_batch([_status(i)], data_cls=InstrumentStatus)
            writer.write_table(piece)
        writer.close()


def _read_native(catalog: ParquetDataCatalog, path: Path) -> pa.Table:
    table = catalog._read_feather_file(str(path))
    assert table is not None, (
        f"the native control read of {path} returned no table -- likely a "
        f"transient read failure under host memory pressure, not a code "
        f"regression; rerun in a quiet window before treating this as real"
    )
    return table


def _read_coalesced(catalog: ParquetDataCatalog, path: Path) -> pa.Table:
    table = read_feather_coalesced(catalog.fs, str(path))
    assert table is not None, (
        f"the coalesced treatment read of {path} returned no table -- likely "
        f"a transient read failure under host memory pressure, not a code "
        f"regression; rerun in a quiet window before treating this as real"
    )
    return table


def _chunks(table: pa.Table) -> int:
    return int(table.column(0).num_chunks)


@pytest.fixture(scope="module")
def _fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, int]]:
    root = tmp_path_factory.mktemp("t5prime")

    n100k = 100_000
    path_100k = root / "n100k" / "live" / "instance-1" / "instrument_status_0.feather"
    _write_stream(path_100k, n100k)

    n200k = 200_000
    path_200k = root / "n200k" / "live" / "instance-1" / "instrument_status_0.feather"
    _write_stream(path_200k, n200k)

    return {"n100k": (path_100k, n100k), "n200k": (path_200k, n200k)}


def test_control_scales_far_faster_than_the_coalesced_treatment(
    _fixtures: dict[str, tuple[Path, int]],
) -> None:
    path_100k, n100k = _fixtures["n100k"]
    path_200k, n200k = _fixtures["n200k"]

    catalog_100k = ParquetDataCatalog(str(path_100k.parents[2]))
    catalog_200k = ParquetDataCatalog(str(path_200k.parents[2]))

    control_table = _read_native(catalog_100k, path_100k)
    treatment_100k_table = _read_coalesced(catalog_100k, path_100k)
    treatment_200k_table = _read_coalesced(catalog_200k, path_200k)

    # Materialization sanity: every row actually landed. Guards against a
    # degenerate mutation (e.g. an early return of an empty table) that would
    # otherwise trivially minimize chunk counts and pass the ratio/scaling
    # checks below for the wrong reason.
    assert control_table.num_rows == n100k
    assert treatment_100k_table.num_rows == n100k
    assert treatment_200k_table.num_rows == n200k

    control_chunks = _chunks(control_table)
    treatment_100k_chunks = _chunks(treatment_100k_table)
    treatment_200k_chunks = _chunks(treatment_200k_table)

    # Fixture/control sanity: native `read_all()` never combines chunks, so
    # it retains exactly one chunk per Arrow IPC message. This is a
    # deterministic property (not a noisy physical measurement like RSS), so
    # an exact equality is the right bound, not a floor/ceiling band.
    assert control_chunks == n100k, (
        f"control fixture drift: native read retained {control_chunks} chunks, "
        f"expected exactly {n100k} (one chunk per message) -- either the "
        f"fixture no longer writes one message per row, or native "
        f"`_read_feather_file` started combining chunks"
    )

    ratio = treatment_100k_chunks / control_chunks
    assert ratio <= _TREATMENT_RATIO_CEILING, (
        f"treatment chunk count ({treatment_100k_chunks}) is {ratio:.1%} of control "
        f"({control_chunks}); must be <= {_TREATMENT_RATIO_CEILING:.0%}"
    )

    growth_chunks = treatment_200k_chunks - treatment_100k_chunks
    expected_growth_chunks = math.ceil(n200k / COALESCE_ROWS) - math.ceil(n100k / COALESCE_ROWS)
    bound_chunks = _SCALING_K * expected_growth_chunks + _SCALING_SLACK_CHUNKS
    assert growth_chunks <= bound_chunks, (
        f"coalesced-read chunk growth from 100K->200K ({growth_chunks}) exceeds "
        f"k={_SCALING_K} * expected-coalescer-growth({expected_growth_chunks}) + "
        f"{_SCALING_SLACK_CHUNKS} slack chunks ({bound_chunks})"
    )
