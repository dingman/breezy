# REPLAY-BIGINST plan r2: delta over r1 (BINDING; r2 wins where the two conflict)

## Round-1 reviews (each reviewer ran blind)
- **architect:** REQUEST_CHANGES, B1–B5.
- **python-reviewer:** C6 I8 T6 R7 S8 F7, with 2 blocking items.
- **prediction-market-reviewer:** REQUEST_CHANGES, with 2 required changes.

All three endorse option (b). None of their findings contradict each other.

The **convergent finding**, raised by all three, is that r1 never specified how the all-time book-backed count is computed. Get it wrong and the census either inflates or deflates the revival count.

## D-1. All-time book-backed count, object-free (domain CRITICAL, python blocking 1, architect suggestion)
- Add `count_depth_rows(files) -> int`: the sum of `pyarrow.parquet.ParquetFile(f).metadata.num_rows` over the id's depth files.
  - It reads only the footer, so memory is O(1).
  - It applies no window and no ask mask. This matches the oracle `len(order_book_depth10(instrument_ids=[id], start=None, end=None)) > 0` (`census:646`, `backtests:1392-1399`, `lib:492-513`).
- `_discover_clean_spans` computes the book-backed set per climate day FIRST. Only book-backed ids reach `scan_depth_window` / `scan_quote_window`.
- **E-B8:** an id whose only depth rows fall OUTSIDE the window is still book-backed. It counts in `distinct_instruments`, and its quotes count.
- **E-B9:** an id with zero depth files is not book-backed, and its quotes do NOT count. This one guards against inflation.
- **Mutants M8a / M8b** (count within the window / skip the count): both must be killed.

## D-2. Re-home the BinaryOption `TypeError` (architect B2)
- The oracle raises it in `_select_capture_instruments` (`backtests:1415-1418`), not in `_capture_instruments_by_id`. It fires for book-backed ids only, in sorted order, after every id has been queried.
- Re-implement it after the book-backed filter, in the same order.
- **E-B7:** a book-backed non-BinaryOption raises; a non-BinaryOption with zero depth does not.
- **Mutant M15:** the check is dropped, or it is applied before the filter. Must be killed.

## D-3. The zero scalar and schema asserts (python + architect)
- Build the zero scalar as `pa.scalar(bytes(w), pa.binary(w))` with `w = schema.field("ask_size_0").type.byte_width`. Never hard-code the width.
- Assert column TYPES as well as names. Assert `null_count == 0` on every mask input.

## D-4. `should_stop` RAISES; it never returns (architect B4)
- The scan never returns a partial span.
- **E-SIG:** a stop request mid-scan leaves NO cache entry for that instance (`census:843-868`) and no checkpoint line.
- M14 is killed by E-SIG.

## D-5. Replace the M9 fixture (architect B5)
- Native writes refuse overlap and sort each file by `ts_init` (`parquet.py:2687-2693,2735`), so the r1 fixture of "non-monotonic files" cannot be built.
- Replacement fixture: ONE file where `ts_init` rises while `ts_event` falls, and the min/max `ts_event` rows are neither the first nor the last row.

## D-6. The Stage 0 conversion bound (architect B3; python non-blocking)
Conversion memory grows with the largest feather file:
- `read_feather_coalesced` reads the whole file (`feather_read.py:118`);
- the monotonic sort may make a copy (`parquet.py:2758-2763`);
- the fallback `_extend_overlapping_stream` builds objects (`ingest_cli:873-880`).

Stage 0 also records:
- the size of the largest single feather file in `ea485c90`;
- whether the EXTEND fallback fired;
- the row-group size and count of the converted parquet.

**PASS** requires both:
- peak < 2.5G;
- the projection `peak / largest_file`, applied to the largest file seen in any instance of the last 7 days, leaves ≥ 25% headroom under 3G.

Otherwise, write r3 for fallback (b′). This does not block implementing (b): the object-building selection step must be removed under (b′) as well.

Stage 0 runs under REPLAY-INCR r2 I-9 conditions:
- after AUD-07;
- outside node hours;
- away from the 15:50Z timer and the ingest run after 09:00Z;
- under `breezy-studies.lock`;
- with the pinned interpreter;
- via `systemd-run` at 3G/4G with `LimitNOFILE=524288`.

## D-7. The memory test is cheap by default (python blocking 2)
- The default-gate test uses D ∈ {1, 4} × 20k rows/day. The bounds are calibrated in a dry run and written down with the measured numbers.
- The oracle positive control uses D = 2 × 5k rows. It must still show ≥ 3× the new path's ΔRSS. If it doesn't, raise the row count until it does, and record the result.
- The D = 6 × 150k test is marked `@pytest.mark.slow` and runs outside the default gate.

## D-8. Rollout compares OLD vs NEW on pinned inputs (architect B1; domain required change 2)
In ONE quiet window, on a pinned list of instance ids + file fingerprints that includes `ea485c90`:
1. Run the pre-change code (current main, installed as a detached base worktree) under the existing 10G drop-in with `--no-instance-spans-cache`.
2. Run the new code at 3G/4G with `--no-instance-spans-cache`.
3. Byte-diff both the rows and the spans. Quote both provenance lines (R3-E).

The corpus is declared as coverage metadata only (`README.md:18`): instance ids, file counts and bytes. It carries no price or outcome statistics.

Retire the TEMPORARY drop-in ONLY after:
- the byte-diff is clean; and
- one 15:50Z timer run completes at 3G/4G.

## D-9. `SPAN_ALGO_VERSION` stays 1
This is conditional on D-8's clean byte-diff and on E-B6 passing, which is the domain reviewer's condition. If either fails, bump the version.

## Smaller items
- Glob the type directory once per instance and group the files by parent directory, instead of calling `get_file_list_from_data_cls` once per id.
- Drop the M11 and M12 spies; the memory test already kills both.
- Correct the schema citation to `schema.py:59-71`.
- `iter_feather_files` in (b′) is Breezy code, not Nautilus.
- Closes are no longer loaded; the census never used them (`backtests:1408-1410`).

**Confidence after r2:** HIGH on the design. Stage 0 still gates (b) versus (b′) for the conversion step only.

## r3 amendments (round 2, BINDING; they override r2 where the two conflict)
Round-2 verdicts:
- domain: ENDORSE-WITH-CHANGES (2 required).
- architect: REQUEST_CHANGES (5 blocking). Each blocking item came with a precise fix, and every fix is adopted below.

Verified in round 2: D-1, D-2, D-4, and the claim that `--no-instance-spans-cache` is read-only against the cache (`census:1040-1047,757-767`).

- **R3-1 (domain 1 + architect).** Group files by `urisafe_identifier(id)` (`funcs.py:88`), exactly as `filter_files` does (`parquet.py:2249-2256`). Never group by the raw id.
  - New fixture **E-B11**: at least 2 instruments' files co-located under one type directory, plus one id containing "/". `count_depth_rows` and both windowed scans must attribute each row to the correct id only.
- **R3-2 (domain 2).** **E-B7b**: on the `TypeError` path, no partial `InstanceSpan`, cache entry, or checkpoint line is written for the instance that raised.
- **R3-3 (D-2 error-path divergence, documented and accepted).** The new path no longer loads closes, and it runs the type check before any scan. A corrupt close, quote or depth file may therefore surface as the TypeError, or not at all, where the old code raised an I/O error. This is fail-loud in both cases; no count changes on the success path.
- **R3-4 (D-4 conditions).**
  - `should_stop` is the census's own `_raise_if_terminating` callable, which raises `SystemExit(143)` (`census:181-183`). It is passed IN to the scan; `src/` never imports `scripts/`.
  - The scan never catches `BaseException`.
  - E-SIG uses a `batch_size` smaller than the row count, with the stop flag flipping after batch 1. Otherwise the instance-loop check at `census:774` would mask M14.
- **R3-5 (replaces the D-8 rollout; architect blocking 1–4).**
  1. **Pinned input.** Build a hardlinked snapshot root that holds only the pinned, CLOSED instances, including `ea485c90`. Verify fingerprints before and after the runs. Pass it as `--catalog-root`.
  2. **No install.** Check the old code out as a detached worktree at the pre-change sha. Run it with the pinned interpreter and `PYTHONPATH=<old-wt>/src:<old-wt>`. Run the new code the same way from its own worktree.
     - Positive control: print `breezy.__file__` and the census module path for both runs.
  3. **Isolated outputs.** Give each run its own `--output <scratch>/{old,new}.jsonl`, its own `--work-parent`, and its own EMPTY `--instance-spans-cache <scratch>/{old,new}/instance_spans.v2.jsonl`.
     - Both caches start cold by construction. Assert `cold == instances` from each provenance line.
     - Diff the rows AND the v2 span entries.
     - A third, NEW, no-cache rows-only run satisfies R3-E.
  4. **Same UTC day for every run**, because `computed_day` is written into the output. Put the memory and fd limits on the `systemd-run -p` command line itself:
     - OLD: 10G/12G;
     - NEW: 3G/4G;
     - both: `LimitNOFILE=524288`.
     The replay drop-in does not apply to these transient units. Confirm free disk space before the OLD run: it converts every instance and does not remove them as it goes.
  5. **Firewall-safe diff output.** The diff reports equal or unequal, plus the differing keys. It never prints row contents (`README.md:18`).
- **R3-6 (replaces the D-6 PASS rule).** PASS requires all of the following:
  - peak < 2.5G;
  - at least 25% projected headroom;
  - CPU/wall > 0.3 (L-49);
  - EXTEND fired on NO instance in the 7-day set.

  "Peak" means the transient unit's `memory.peak`. Record `memory.stat` anon alongside it.
- **R3-7 (new tests).**
  - **E-B10**: a null `ask_size_k` raises.
  - **E-B3b**: a wrong-type column (`binary(w')`) raises.
  - **E-B3c**: the width `w` is derived from the file's schema, asserted equal to `NAUTILUS_ARROW_SCHEMA`, and a mismatched-width file raises. This kills the hard-coded-width mutant M16.

**Confidence after round 2: HIGH.** The implementation review (python-reviewer + architect) must confirm R3-1 through R3-7.
