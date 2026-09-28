# ING-2-AMEND2 — plan r2 delta (binding amendments to r1)

**Review:** python-reviewer, READY-WITH-AMENDMENTS, confidence 78. The design premise is confirmed: `filter_files` and `urisafe_identifier` are generic over `data_cls`, and the `custom_` prefix comes from `not is_nautilus_class`.

1. **Citation fix.** The deadline gate is `ingest_cli.py:1300-1304`, and it runs per conversion unit (per type), not only between instances.
2. **RED classification.**
   - Truly RED: test #1 (filtered drop set equals the oracle, AND the spy shows `identifiers=`), test #3 (the RSS-scaling test), and test #4 (the `by_type` line).
   - The flat-file-forces-unfiltered parametrize for `DepthTruncation` is a **behaviour-preserving regression check**, not RED, because today's dispatch is unconditionally unfiltered. Label it that way.
3. **Fixture.**
   - Add a `DepthTruncation` builder to `_BUILDERS` (`test_extend_dedupe_filtered.py:89`). The fields are `instrument_id`, `bid_levels_seen`, `ask_levels_seen`, `levels_dropped`, `ts_event` and `ts_init`.
   - Before trusting the flat-file tests, prove that the harness `_write_flat_file_without_instrument_id_metadata` really produces a FLAT `custom_depth_truncation` file for a `register_arrow` custom type. If it cannot, write the flat file directly with pyarrow and say so.
4. **AC4 metric.** The removal criterion stays as ruled: `memory.peak` ≤2G, ≤600 s, deferred_instances=0, and `custom_depth_truncation:<n>/0`. It is measured **directly** from the unit's cgroup `memory.peak` (the journal "memory peak" line), never inferred from `rss_peak_mb`.
   - The 09:45Z run showed a cgroup/RSS ratio of about 2.37 (page cache).
   - If the post-fix run has deferred=0 and elapsed ≤600 s, but its cgroup peak is >2G while RSS is ≪2G, the criterion is re-ruled on page-cache evidence (e.g. `memory.stat` file vs anon). It is never silently relaxed. The drop-in stays until then.
5. **Scope.** No other type is widened (see the `by_type` evidence).
