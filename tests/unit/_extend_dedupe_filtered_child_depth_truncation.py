#!/usr/bin/env python
"""T-MEM child process (ING-2-AMEND2): measures one EXTEND-dedupe call's
``ru_maxrss`` for ``DepthTruncation``, the custom-type sibling of
``_extend_dedupe_filtered_child.py``'s ``OrderBookDepth10`` case.

Launched via ``subprocess.run([sys.executable, __file__, ...])`` from a fresh
interpreter -- L-49 (never ``multiprocessing`` fork: a forked child inherits
the parent's already-resident pages and high-water mark, which would corrupt
the measurement). Mirrors ``_extend_dedupe_filtered_child.py``'s shape.

Prints one JSON line to stdout: ``{"baseline_kb": int, "peak_kb": int,
"fresh": int}``. ``ru_maxrss`` is already in KiB on Linux.

The ``DepthTruncation`` builder is duplicated from
``test_extend_dedupe_filtered.py`` rather than imported (that helper is
private to its module) -- kept in lock-step with it deliberately, the same
precedent ``_extend_dedupe_filtered_child.py`` and
``test_quote_tape_ingest_bounded_read.py``'s ``_write_typed_ipc_stream`` set.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.tape_records import DepthTruncation
from breezy.runtime.quote_tape_salvage import _drop_already_landed_unfiltered

TARGET_ID = InstrumentId.from_str("TGT/USD.SIM")


def _depth_truncation(instrument_id: InstrumentId, ts: int) -> DepthTruncation:
    return DepthTruncation(
        instrument_id=instrument_id,
        bid_levels_seen=12,
        ask_levels_seen=14,
        levels_dropped=2,
        ts_event=ts,
        ts_init=ts,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-root", required=True)
    parser.add_argument("--warmup-root", required=True)
    parser.add_argument("--base-ts", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()

    # Warm-up: a DISTINCT, empty catalog absorbs lazy pyarrow/parquet/nautilus
    # initialisation before the baseline sample -- never the target catalog.
    warmup_catalog = ParquetDataCatalog(args.warmup_root)
    _drop_already_landed_unfiltered(
        warmup_catalog, DepthTruncation, [_depth_truncation(TARGET_ID, 1)]
    )

    baseline_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    catalog = ParquetDataCatalog(args.catalog_root)
    chunk = [_depth_truncation(TARGET_ID, args.base_ts + i) for i in range(args.count)]
    # Every chunk row is already landed for the target instrument (by
    # construction, see the caller), so `fresh` -- the SURVIVORS, not a
    # removed-count -- must be empty; a non-zero value means the compare
    # itself is broken, not just slow.
    fresh = _drop_already_landed_unfiltered(catalog, DepthTruncation, chunk)

    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    print(json.dumps({"baseline_kb": baseline_kb, "peak_kb": peak_kb, "fresh": len(fresh)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
