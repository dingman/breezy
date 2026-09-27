#!/usr/bin/env python
"""T-MEM child process (ING-2-RSS): measures one EXTEND-dedupe call's ru_maxrss.

Launched via ``subprocess.run([sys.executable, __file__, ...])`` from a fresh
interpreter -- L-49 (never ``multiprocessing`` fork: a forked child inherits
the parent's already-resident pages and high-water mark, which would corrupt
the measurement). Mirrors ``tests/unit/_bounded_rss_child.py``'s shape.

Prints one JSON line to stdout: ``{"baseline_kb": int, "peak_kb": int,
"dropped": int}``. ``ru_maxrss`` is already in KiB on Linux.

The ``OrderBookDepth10`` builder is duplicated from
``test_extend_dedupe_filtered.py`` rather than imported (that helper is
private to its module) -- kept in lock-step with it deliberately, the same
precedent ``test_quote_tape_ingest_bounded_read.py``'s ``_write_flat_stream``
sets for ``_write_typed_ipc_stream``.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys

from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.runtime.quote_tape_salvage import _drop_already_landed_unfiltered

TARGET_ID = InstrumentId.from_str("TGT/USD.SIM")


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
    _drop_already_landed_unfiltered(warmup_catalog, OrderBookDepth10, [_depth10(TARGET_ID, 1)])

    baseline_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    catalog = ParquetDataCatalog(args.catalog_root)
    chunk = [_depth10(TARGET_ID, args.base_ts + i) for i in range(args.count)]
    # Every chunk row is already landed for the target instrument (by
    # construction, see the caller), so `fresh` -- the SURVIVORS, not a
    # removed-count -- must be empty; a non-zero value means the compare
    # itself is broken, not just slow.
    fresh = _drop_already_landed_unfiltered(catalog, OrderBookDepth10, chunk)

    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    print(json.dumps({"baseline_kb": baseline_kb, "peak_kb": peak_kb, "fresh": len(fresh)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
