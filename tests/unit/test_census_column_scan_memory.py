"""D-7 memory-bound tests for the column-scan replay-sufficiency path
(REPLAY-BIGINST): the object-free depth scan's peak RSS growth must not
scale with instance size, unlike the object-based path it replaces.

Fresh child process, peak RSS via ``/proc/<pid>/status``'s ``VmHWM`` (L-49
-- read from a FRESH child, never inferred from the test process itself).
``VmHWM`` is used instead of ``resource.getrusage(...).ru_maxrss``: measured
directly in this sandboxed dev environment, a child spawned via
``subprocess.run`` from a process that already holds a large RSS reports
``ru_maxrss`` values contaminated by the PARENT's peak (reproduced with a toy
harness: a parent that allocates ~400MB, then a `subprocess.run` child that
does nothing but call `getrusage` immediately, reports ~400MB too).
``/proc/self/status``'s ``VmHWM`` does not show this contamination in the
same harness (the same child reports a normal, small value) and is the
number this module relies on throughout.

Two separate steps, run as two separate subprocesses:

1. ``_build_catalog`` writes the synthetic parquet fixture in a plain,
   UNMEASURED subprocess. Building N `OrderBookDepth10` Python objects to
   feed `write_data` is itself a large, N-scaling allocation, and an early
   dry run showed it dominates peak RSS enough to mask the READ-side signal
   entirely if build and read share one process.
2. ``_read_child`` opens the ALREADY-BUILT catalog fresh, takes its RSS
   baseline immediately AFTER importing (never before -- the import itself
   costs roughly 250MB via nautilus/pyarrow and is identical across every
   comparison, so it must not appear in the delta), then runs the scan/read
   step and reports ``after - baseline``.

Calibration (2026-09-27, this machine, `delta_kib` in KiB -- see
`_read_child`'s printed JSON) is recorded per test class below, since a
"calibrated" bound with no attached measurement is unverifiable archaeology
six months later.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_BUILD_TEMPLATE = r"""
import sys
from pathlib import Path

repo = Path(sys.argv[1])
num_files = int(sys.argv[2])
rows_per_file = int(sys.argv[3])
catalog_root = Path(sys.argv[4])
sys.path.insert(0, str(repo / "src"))

from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

VENUE = Venue("BREEZY_TEST")
IID = InstrumentId(symbol=Symbol("MEM-A"), venue=VENUE)


def _row(ts: int) -> OrderBookDepth10:
    filler = BookOrder(OrderSide.SELL, Price(0, 2), Quantity(0, 0), 0)
    real = BookOrder(OrderSide.SELL, Price.from_str("0.51"), Quantity.from_int(5), 0)
    asks = [real] + [filler] * 9
    bids = [filler] * 10
    ask_counts = [1] + [0] * 9
    bid_counts = [0] * 10
    return OrderBookDepth10(
        instrument_id=IID,
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts,
        ts_init=ts,
    )


catalog = ParquetDataCatalog(catalog_root)
base = 0
for _file_idx in range(num_files):
    rows = [_row(base + i) for i in range(rows_per_file)]
    catalog.write_data(rows)
    base += rows_per_file + 1_000_000  # keep successive files' ts_init disjoint
"""

_READ_TEMPLATE = r"""
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1])
catalog_root = Path(sys.argv[2])
mode = sys.argv[3]  # "new" or "oracle"
sys.path.insert(0, str(repo / "src"))


def _vmhwm_kib() -> int:
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith("VmHWM"):
                return int(line.split()[1])
    raise RuntimeError("VmHWM not found in /proc/self/status")


from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

VENUE = Venue("BREEZY_TEST")
IID = InstrumentId(symbol=Symbol("MEM-A"), venue=VENUE)

# Every import THIS MODE needs happens before the baseline is taken, so the
# ~250MB fixed cost of importing nautilus_trader/pyarrow never appears in
# the delta.
if mode == "new":
    from nautilus_trader.persistence.funcs import urisafe_identifier

    from breezy.persistence.catalog_column_scan import (
        group_files_by_identifier,
        scan_depth_window,
    )
elif mode != "oracle":
    raise ValueError(f"unknown mode {mode!r}")

catalog = ParquetDataCatalog(catalog_root)
baseline_kib = _vmhwm_kib()

if mode == "new":
    grouped = group_files_by_identifier(catalog, OrderBookDepth10)
    files = grouped[urisafe_identifier(IID)]
    scan_depth_window(files, start_ns=0, end_ns=10**18, should_stop=lambda: None)
else:
    catalog.order_book_depth10(instrument_ids=[IID.value])

after_kib = _vmhwm_kib()
print(json.dumps({
    "baseline_kib": baseline_kib,
    "after_kib": after_kib,
    "delta_kib": after_kib - baseline_kib,
}))
"""


def _build_catalog(num_files: int, rows_per_file: int, tmp_path: Path, *, tag: str) -> Path:
    root = tmp_path / f"catalog-{tag}"
    root.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-c",
            _BUILD_TEMPLATE,
            str(REPO_ROOT),
            str(num_files),
            str(rows_per_file),
            str(root),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    return root


def _read_child(catalog_root: Path, *, mode: str) -> dict[str, int]:
    result = subprocess.run(
        [sys.executable, "-c", _READ_TEMPLATE, str(REPO_ROOT), str(catalog_root), mode],
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestNewPathDeltaRssDoesNotScaleWithFileCount:
    """Dry-run calibration (2026-09-27, this machine), delta_kib from a fresh
    read-only child (baseline taken after import, see module docstring):
    D=1 x 20k rows/day -> 35232; D=4 x 20k rows/day -> 52656 (delta +17424).
    Growth is real but small and clearly SUB-linear in total rows written (4x
    the files/rows, ~1.5x the delta) -- the invariant under test, contrasted
    with the old object-based path in `TestOraclePositiveControl`."""

    def test_d1_vs_d4_at_20k_rows_per_day(self, tmp_path: Path) -> None:
        cat1 = _build_catalog(1, 20_000, tmp_path, tag="d1")
        cat4 = _build_catalog(4, 20_000, tmp_path, tag="d4")

        d1 = _read_child(cat1, mode="new")
        d4 = _read_child(cat4, mode="new")

        assert d4["delta_kib"] - d1["delta_kib"] <= 32 * 1024
        assert d4["delta_kib"] <= 160 * 1024


class TestOraclePositiveControl:
    """Dry-run calibration (2026-09-27, this machine): D=2 x 5k rows/day,
    new path delta_kib=16252, oracle (object-based) delta_kib=81036 -- ~5.0x.
    The plan requires >= 3x; comfortably met at this row count, so the row
    count was NOT raised. If a future Nautilus/pyarrow version narrows this
    margin below 3x, raise `_ROWS_PER_FILE` here and record the new
    measurement (D-7)."""

    _ROWS_PER_FILE = 5_000

    def test_oracle_delta_rss_is_at_least_3x_the_new_paths_at_d2_5k(
        self, tmp_path: Path
    ) -> None:
        catalog_root = _build_catalog(2, self._ROWS_PER_FILE, tmp_path, tag="oracle-control")

        new = _read_child(catalog_root, mode="new")
        oracle = _read_child(catalog_root, mode="oracle")

        assert oracle["delta_kib"] >= 3 * max(new["delta_kib"], 1)


@pytest.mark.slow
class TestNewPathDeltaRssBoundAtD6_150k:
    """Dry-run calibration (2026-09-27, this machine), delta_kib from a
    fresh read-only child: D=1 x 150k rows/day -> 65512; D=6 x 150k rows/day
    -> 99288 (delta +33776), for 6x the files and 6x the total rows --
    clearly sub-linear, but ABOVE the plan r1 text's original 32 MiB figure,
    which predates this measurement. The bound below is the r2/r3-mandated
    real calibration (D-7: "calibrated in a dry run and written down with
    the measured numbers"), not the r1 guess: 40 MiB delta (real ~33 MiB +
    headroom), 160 MiB absolute (real ~97 MiB + headroom). This is the
    plan's own D=6 x 150k case; opts into the gate via BREEZY_RUN_SLOW=1
    (the `slow` marker itself is not deselected by the pinned addopts, so
    this environment-variable skip is what actually keeps it out of the
    default run)."""

    @pytest.mark.skipif(
        os.environ.get("BREEZY_RUN_SLOW") != "1",
        reason="slow D=6x150k memory test; set BREEZY_RUN_SLOW=1 to run",
    )
    def test_d1_vs_d6_at_150k_rows_per_day(self, tmp_path: Path) -> None:
        cat1 = _build_catalog(1, 150_000, tmp_path, tag="d1-150k")
        cat6 = _build_catalog(6, 150_000, tmp_path, tag="d6-150k")

        d1 = _read_child(cat1, mode="new")
        d6 = _read_child(cat6, mode="new")

        assert d6["delta_kib"] - d1["delta_kib"] <= 40 * 1024
        assert d6["delta_kib"] <= 160 * 1024
