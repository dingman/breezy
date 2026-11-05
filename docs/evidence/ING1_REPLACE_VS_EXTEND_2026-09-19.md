# ING-1 replace-vs-extend choice

**WP-0e / NB-2.** Recorded before the collision fix. No "covered station-day"
claim is legal until this file exists.

**Choice: EXTEND.** Never REPLACE.

## What collided

The 15-minute ingest (`breezy-quote-tape-ingest-frequent.timer` `OnCalendar=*:0/15`,
same oneshot as `breezy-quote-tape-ingest.service`) lands a live instance via
the whole-instance path when `_open_files_for_instance` is empty
(`quote_tape_ingest_cli.py:1215-1233` → `ingest_instance` → `default_convert`
→ `ParquetDataCatalog.convert_stream_to_data`).

`convert_stream_to_data` (`nautilus_trader 1.231.0`
`persistence/catalog/parquet.py:2604-2654`) walks each feather file and
delegates to `_convert_feather_table_to_parquet` (`:2656-2700`). That helper
is the **partial-slice writer**: it derives the parquet interval from
`min(ts_init)` / `max(ts_init)` of the table **as it exists on that run**
(`:2675-2676`) and writes one file named from those bounds (`:2680-2700`).

A later ingest of the same, now-longer stream computes a **different**
filename (same start, later end) and hits the native disjoint-interval
guard. Installed 1.231.0, `_convert_feather_table_to_parquet:2687-2693`:

```
        current_intervals = used_catalog._get_directory_intervals(directory)
        new_intervals = [*current_intervals, (start, end)]
        if not _are_intervals_disjoint(new_intervals):
            raise ValueError(
                f"Writing file {filename} with interval ({start}, {end}) would create "
                f"non-disjoint intervals. Existing intervals: {current_intervals}",
            )
```

The same raise lives on the `write_data` path at `_write_chunk:385-389`.

Breezy surfaces that `ValueError` as a per-type failure and does **not**
write the `.converted-<type>` marker (`ingest_instance:792-801`). The CLI
then exits 3 (`quote_tape_ingest_cli.py:1350-1351`). Every later timer tick
retries the same overlapping write and fails the same way. The catalog keeps
the first, short interval; in-window Depth10 stays under 30 minutes and
coverage reads 0. Journal shape (READINESS_AUDIT_2026-09-13):
`conversion of OrderBookDepth10 failed … would create non-disjoint intervals`
— that is the `ingest_instance` log line (`:795-799`), not the per-file
`conversion of %s file %s failed` line (`:992-998`).

The per-file path (`_convert_one_tick_type_per_file:982-999`) calls the
**same** `_convert_feather_table_to_parquet` writer and can lay down the
same partial slice for a closed-looking file before the whole-instance path
refuses the grown range.

Captured 2026-09-11 LAX shape (pinned by
`test_a_republished_overlapping_interval_reproduces_the_non_disjoint_refusal`):
existing `(start, early_end)`, incoming `(start, later_end)`.

## Why REPLACE is illegal here

Verified against installed `nautilus_trader` 1.231.0 in `.venv`, not against
docs or memory — **except for the Trap 2 application claim, which was NOT so
verified and was refuted on review 2026-09-19. See the correction in that
section.** The blanket assurance in this line was itself unreliable; treat
per-claim citations, not this sentence, as the evidence.

**Trap 1 — same-range rewrite is a silent skip.** `_write_chunk:378-380`:

```
        if self.fs.exists(parquet_file):
            print(f"File {parquet_file} already exists, skipping write")
            return
```

The stream converter has the identical skip at
`_convert_feather_table_to_parquet:2683-2685`. A "replace" implemented as a
rewrite of the already-written filename does not raise and does not
overwrite. It does nothing. The docstring at `write_data:291` ("Any existing
data which already exists under a filename will be overwritten") is false
for this version; the body skips.

**Trap 2 — `delete_data_range` no-ops for identifier-less / flat layout.**
`delete_data_range:1421-1441`: when `identifier is None` it only recurses
into leaf directories matching `f"/data/{data_cls_name}/"` **and**
`parts[-2] == data_cls_name` (i.e. `data/<type>/<identifier>/`). For a truly
flat `data/<type>/*.parquet` leaf, `parts[-1]` is the type name and
`parts[-2]` is `"data"`, so the recursive delete never fires and the method
returns having deleted nothing.

**CORRECTED 2026-09-19 (review): Trap 2 does NOT apply to the types this WP
handles.** The mechanism above is real as a general fact about
identifier-less custom types. The claim that it applies to `OrderBookDepth10`
here was WRONG, and it was never checked against the installed writer.
`StreamingFeatherWriter.__init__`
(`nautilus_trader/persistence/writer.py:139-148`) hard-codes
`_per_instrument_writers` containing `order_book_depths`, `quote_tick`,
`trade_tick`, `order_book_deltas` and `bar`. Those types always take
`_create_identifier_writer`, which embeds `b"instrument_id"` in the schema
metadata (`_extract_obj_metadata:499`), so production lands them at
`data/order_book_depths/<instrument_id>/...` — **per-instrument, never flat.**
Reproduced end to end against the real `StreamingFeatherWriter` +
`convert_stream_to_data`.

This repo had already measured and recorded that fact:
`src/breezy/runtime/node_config.py:493-496` states QuoteTick "carries one
[instrument_id], so the catalog partitions natively into
`data/quote_tick/<instrument_id>/` — measured, not assumed." The original
version of this section contradicted an existing measured statement in the
same repository.

**Consequence for the decision.** Trap 2 is NOT what makes REPLACE illegal
for these types, and this note never considered the option it rules out:
passing the KNOWN `instrument_id` to `delete_data_range` instead of `None`,
which would sidestep Trap 2 entirely. **Trap 1 alone still blocks REPLACE**,
and Trap 1 is layout-independent: a same-range rewrite silently skips
whatever the directory shape. EXTEND therefore stands as the choice — it
deletes nothing, rewrites no existing filename, and reuses the de-dupe
contract the definition and salvage paths already use — but it stands on
Trap 1 and on being the more conservative construction, NOT on the flat-layout
argument made below.

Delete-then-rewrite is therefore: delete no-ops, rewrite same-range silent-
skips. REPLACE cannot land the tail.

Nautilus is immutable. `skip_disjoint_check=True` without de-duplication is
not a replace; it is admitting overlapping intervals of the **same rows**.
The native contract test
`test_a_republished_overlapping_interval_reproduces_the_non_disjoint_refusal`
stays: it pins the catalog guard, not Breezy's ingest policy.

## Why EXTEND

The instrument-definition path already EXTENDs
(`convert_instrument_definitions:437-547`): read the stream, drop every
`(instrument_id, ts_init)` already in the catalog, `write_data` only what is
new. Salvage uses the same de-dupe-then-write (`quote_tape_salvage.py:209-224`).

Capture-timed ticks (Depth10, QuoteTick, …) are monotonic inside one
recorder instance. The refused write is the **same stream, later end**. The
rows not yet landed have `ts_init` after the partial slice (or are a
different `(instrument_id, ts_init)`). Writing **only those rows** as new
parquet records is EXTEND:

- It does not delete.
- It does not rewrite an existing filename (Trap 1 does not apply).
- It does not call `delete_data_range` (Trap 2 does not apply).
- De-duplication is against an **unfiltered** query. Identifier-filtered
  `query` silently omits flat files (`filter_files:2249-2257`; pinned by
  `TestTheMixedCatalogLayoutIsPinned`). The definition path already documents
  this and queries unfiltered (`convert_instrument_definitions:480-494`).
  *(2026-09-19 review: that omission mechanism is CONFIRMED, but per the Trap 2
  correction the flat-file scenario does not arise for these types today. The
  unfiltered query is kept anyway because it is layout-agnostic and therefore
  correct for BOTH layouts — verified by source tracing, not by the flat
  premise.)*
- `skip_disjoint_check=True` is earned by that de-dupe, the same contract as
  definitions and salvage — not a bypass of the guard for duplicate rows.
- `ts_event` / `ts_init` on the new rows stay the capture stamps. They are
  new records in a new file, not a later `ts_init` restamp. Restamping
  capture-timed ticks would reorder replay; the plan's "later `ts_init`"
  continuation is the weather-correction rule (WEATHER_INGESTION_PROPOSAL
  §4.3) for identifier-less **custom** revisions. Depth10 is not that type.
  If a future correction ever had to restamp, it would be a new record with
  a later `ts_init`, never a delete-then-rewrite.

First attempt remains the native `convert_stream_to_data` bulk copy
(`TestNonInstrumentTypesKeepTheSingleNativeCall`). EXTEND is only the
non-disjoint fallback.

## What this file does not claim

It does not claim any station-day is covered. Coverage is a measurement of
the catalog after the collision is gone (WP-0e GATE), not a consequence of
choosing EXTEND.
