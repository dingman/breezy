# G-09 Loader-Side Gap Enforcement

## Problem

`QuoteTapeGap.gap_seq` is not globally unique. It restarts per instrument and
per recorder process, while raw catalog rows are append-only and retain both the
open and resolved edge for the same outage. A consumer that reads
`QuoteTapeGap` rows directly from `ParquetDataCatalog.query(...)` and keys only
on `gap_seq` can silently merge unrelated outages.

The writer-side fix made correct partitioning possible by adding
`recorder_instance_id`, sourced from the native `NautilusKernelConfig.instance_id`
that also names the streaming directory. The outstanding issue is that nothing
forces readers to use that field. A raw flat read still lets downstream analysis
under-exclude contaminated intervals, which is the dangerous failure direction.

The loader-side requirement is therefore structural: Breezy consumers need a
sanctioned gap loader that returns already-collapsed partitions keyed by
`(recorder_instance_id, instrument_id)`, and any attempt to request a flat
sequence from that sanctioned loader must raise.

## Existing Surfaces Checked

- `src/breezy/adapters/polymarket_us/tape_records.py` defines `QuoteTapeGap` and
  the existing `resolved_gaps_by_seq(...)` reducer. The reducer already uses the
  correct full key `(recorder_instance_id, instrument_id, gap_seq)`.
- `src/breezy/adapters/polymarket_us/data.py` writes `QuoteTapeGap` on both feed
  edges for every subscribed instrument, stamping each row with the recorder
  instance id supplied by config.
- `src/breezy/runtime/node_config.py` generates one native Nautilus
  `UUID4` instance id and passes the same value to both `TradingNodeConfig` and
  the Polymarket data-client config.
- `src/breezy/runtime/quote_tape_cli.py` documents the native readback path:
  convert each streaming run with `ParquetDataCatalog.convert_stream_to_data(...)`
  and query through Nautilus.
- `src/breezy/persistence/catalog.py` is NWS settlement persistence. It does not
  currently own quote-tape loading, and its station-root rules should not be
  mixed with the venue tape root.

## Approach

Add a thin Breezy loader module for venue quote-tape gaps. It will use the
native Nautilus `ParquetDataCatalog` read mechanism rather than reimplementing
catalog storage:

1. Introduce `src/breezy/persistence/quote_tape_gaps.py`.
2. Define `GapPartitionKey` as a frozen dataclass with
   `recorder_instance_id: str` and `instrument_id: InstrumentId`.
3. Define `PartitionedQuoteTapeGaps` as a mapping-like wrapper around
   `dict[GapPartitionKey, tuple[QuoteTapeGap, ...]]`.
4. Expose `load_partitioned_quote_tape_gaps(catalog: ParquetDataCatalog)`.
   It will:
   - query `QuoteTapeGap` through Nautilus,
   - unwrap `CustomData.data`,
   - collapse append-only open/resolved rows with `resolved_gaps_by_seq(...)`,
   - group the collapsed rows by `(recorder_instance_id, instrument_id)`, and
   - return immutable tuples sorted by `gap_seq`.
5. Deliberately omit iteration over `PartitionedQuoteTapeGaps` and provide a
   `flat()` method that raises `UnpartitionedQuoteTapeGapReadError`. Consumers
   can still access explicit partitions via `.items()`, `.keys()`, `.values()`,
   `.get(...)`, and `__getitem__`.

This cannot and should not monkeypatch or restrict `ParquetDataCatalog.query`.
Nautilus is immutable and other record types need raw catalog reads. The
enforcement point is Breezy's sanctioned loader API: the API has no successful
flat-return path, so a consumer that opts into Breezy's loader cannot accidentally
receive unpartitioned rows.

## Files Touched

- `docs/plans/backlog/archive/G-09-loader-side-gap-enforcement.md` first, before code.
- `src/breezy/persistence/quote_tape_gaps.py` for the loader API.
- `src/breezy/persistence/__init__.py` only if exporting the new loader follows
  existing package style after inspection.
- `tests/unit/test_quote_tape_gap_loader.py` for RED/GREEN coverage.

Forbidden files remain untouched:

- `pyproject.toml`
- `tests/conftest.py`

## RED Test

Add a regression test that writes colliding gap rows for two instruments into a
native `ParquetDataCatalog`. The fixture will include:

- instrument A, `gap_seq=1`, unresolved from `100` onward;
- instrument B, `gap_seq=1`, resolved from `900` to `950`.

The test will demonstrate the concrete hazard by implementing the naive flat
consumer locally in the test: key raw rows only by `gap_seq`, prefer the resolved
row, and show that the result drops instrument A's still-open outage. That is a
wrong gap set, because `instrument A` no longer covers `10_000`.

The same test will assert that `load_partitioned_quote_tape_gaps(...)` returns
two partitions and preserves instrument A's unresolved outage independently
from instrument B's resolved outage.

A second focused test will assert that the sanctioned loader refuses a flat read
by raising `UnpartitionedQuoteTapeGapReadError`.

The RED state should fail with an import error or missing symbol before the
loader implementation exists.

## GREEN Criterion

- The new focused loader tests pass.
- Existing `tests/unit/test_quote_tape_consumer_contract.py` continues to pass.
- The project gates finish with exit code 0:
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run mypy`

## Risks And Limits

- Full prevention of every raw Nautilus catalog read is impossible without
  patching, wrapping globally, or restricting Nautilus itself. That is out of
  scope and would violate the immutable-foundation constraint.
- The loader must not create a parallel persistence path. It should only call
  Nautilus' existing catalog query surface and then enforce Breezy's join
  contract on the returned data.
- The wrapper must be inconvenient to misuse but not obscure: consumers need
  obvious partitioned accessors and a loud failure when requesting a flat
  sequence.
- The reducer already owns append-only edge collapse. The loader should reuse it
  to avoid creating a second, divergent collapse policy.
