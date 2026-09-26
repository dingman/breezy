#!/usr/bin/env python
"""T5' child process (ING-2 S3a, AC-S3-1): measures one feather read's ru_maxrss.

Launched via ``subprocess.run([sys.executable, __file__, ...])`` from a fresh
interpreter -- NEVER ``multiprocessing`` fork (P2), because a forked child
inherits the parent's already-resident pages and high-water mark, which would
corrupt the measurement. Both the control (native) and treatment (coalesced)
readers run through this exact same script, differing only in ``--reader``.

Prints one JSON line to stdout: ``{"baseline_kb": int, "peak_kb": int,
"nbytes": int}``. ``ru_maxrss`` is already in KiB on Linux.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
from pathlib import Path

import pyarrow as pa
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.persistence.feather_read import read_feather_coalesced


def _catalog_root_for(feather_path: str) -> str:
    # <root>/live/<instance>/<file>.feather
    return str(Path(feather_path).parents[2])


def _read(reader: str, catalog: ParquetDataCatalog, path: str) -> pa.Table | None:
    if reader == "native":
        return catalog._read_feather_file(path)
    if reader == "coalesced":
        return read_feather_coalesced(catalog.fs, path)
    raise ValueError(f"unknown reader: {reader}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--warmup-path", required=True)
    parser.add_argument("--reader", choices=["native", "coalesced"], required=True)
    args = parser.parse_args()

    # Warm-up: a DISTINCT 10-row fixture, its own directory, its own
    # throwaway catalog -- never a partial read of the target, and never the
    # target's own catalog (r3 AC-S3-1). This absorbs lazy pyarrow/parquet/
    # compute initialisation before the baseline is taken.
    warmup_catalog = ParquetDataCatalog(_catalog_root_for(args.warmup_path))
    _read(args.reader, warmup_catalog, args.warmup_path)

    baseline_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    catalog = ParquetDataCatalog(_catalog_root_for(args.path))
    table = _read(args.reader, catalog, args.path)

    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    if table is None:
        print("read failed: reader returned None", file=sys.stderr)
        return 75

    nbytes = int(table.nbytes)

    print(json.dumps({"baseline_kb": baseline_kb, "peak_kb": peak_kb, "nbytes": nbytes}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
