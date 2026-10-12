# S1 r1 review — architect — 2026-10-12
Verdict: SOUND-WITH-CAVEATS — the separate census script and the B-3/SEARCH reading are right, but WP1's Depth10 and gap readers rest on two false reuse claims, print counting can double-count, F1 cannot resolve, and S-1 contradicts the firewall.

## Charter answers (short)
- Separate script vs window parameter: a separate script is JUSTIFIED, and the plan undersells why.
  (a) The `ReplaySufficiency` schema has no print counts and 20 callers (verified).
  (b) The census span cache key is `(instance_id, fingerprint, SPAN_ALGO_VERSION, PREFLIGHT_CLASSIFIER_VERSION)` (`replay_sufficiency_census.py:969-974`). It has no window identity, so a second window through `run_census` would poison `DEFAULT_INSTANCE_SPANS_PATH`.
  (c) The census converts each CLEAN instance (QuoteTick+Depth10) into a parquet work catalog (`_discover_clean_spans:830-871`, `tape_instruments._convert_live_capture:121-148`). That is disk-heavy at 5 GB free.
  (d) The maker window crosses the 09:00Z rotation, so it is a union of two instances, not one winning instance.
  Put (b) and (c) into §3.1 as the concrete reasons.
- RA-13 B-3 / SEARCH: described correctly. The text is at `RA-13:89-92` and `EDGE-4_DISPOSITION:19` ("both plans"). The carve-outs are named at `RA-13-FW:13-14`. The exit-window precedent is at `RA-13-FW:21-29`. TE-3 read nothing after the freeze (`TE-3:5,49`).

## Findings (ranked)
1. [MAJOR] §5.1 row 2 / WP1 "Fold Depth10 ts via catalog_column_scan (UNVERIFIED on raw feather)".
   - Defect: this is not unverified, it is known false. `scan_depth_window` and `scan_quote_window` open `pq.ParquetFile` on "already-converted parquet" (`catalog_column_scan.py:216,249,291`). Raw feather is an Arrow IPC stream.
   - The fallback (deserialize Depth10 into objects per file) brings back the object-materialisation path that REPLAY-BIGINST removed. Over ~4 stations × 45 days of the 293 GB tape, that means hours of runtime on a one-heavy-job host.
   - Required change, either of:
     - (i) Preferred, simplest: S1 does not read Depth10 at all. Print eligibility needs recorder-alive coverage (instance capture span minus gap records) plus `trade_tick`. Depth10 density is S2's concern. This removes most of the I/O.
     - (ii) Read only the `ts_event` column straight from IPC batches with `pa.ipc.open_stream`, reusing the streaming idea in `feather_preflight._scan_stream:299-365`. No Nautilus objects, memory bounded by batch size.
2. [MAJOR] §5.1 row "Capture gaps ... already read by `replay_sufficiency.py`" and WP1 "Subtract custom_quote_tape_gap intervals".
   - Defect: wrong. The approved reader is `runtime/quote_tape_gaps.load_partitioned_quote_tape_gaps(catalog: ParquetDataCatalog)` (`quote_tape_gaps.py:86-106`). It collapses rows by seq (`resolved_gaps_by_seq`) and refuses unpartitioned reads (`:56-61,79-83`, pinned by `test_quote_tape_gap_loader.py`).
   - Reading the raw feather flat skips both the collapse and the partition contract.
   - Required change: per instance, natively convert only `QuoteTapeGap` (+`BinaryOption`) into a work dir under `~/.cache`, then delete it. Mirror `_cleanup_work_catalog:758-773`. Partition the gaps by `(recorder_instance_id, instrument_id)`.
   - Separately, define coverage from recorder liveness, not Depth10 spacing. Overnight books in `[D−1 12:00Z, D 09:00 LST)` are quiet, so a 30-min max gap on Depth10 timestamps would treat a quiet market as a capture outage. This also answers Q3.
3. [MAJOR] WP1 "Load trade_tick with `_load_stream`".
   - Defect: `_load_stream` dedupes on `(instrument_id, ts_event, ts_init)` (`cli_basis_offer_gate_scan.py:626-631`). A print captured by both instances around the rotation has different `ts_init` values, so it is counted twice. That inflates E, the STOP metric.
   - `_load_stream` also prints and continues on a parse failure (`:619-624`), so a lost file silently lowers the count.
   - Required change: dedupe prints on `trade_id`. It comes from venue fields only and is designed to collide on replays (`parsing.py:940-948,981-991`). Count parse failures into `reason` and refuse the station-day on any failure.
   - RED test: `test_a_print_seen_by_two_overlapping_instances_counts_once`.
4. [MAJOR] WP2 F1 and the `classify_trade_quantity_unit` rule "≥1 NO-leg match".
   - Defect: TE-3 states the 3 NO fills are ALL the NO fills among the 34 (`TE-3:9-12`). So the 25 post-freeze fills are YES-leg, and F1 can never meet the NO-leg requirement. S-2's "both fallbacks" is therefore one real fallback (F2), which "never alone" decides anything.
   - The NO-leg rule is also stricter than it needs to be. YES-leg matches do separate CONTRACTS (qty 1) from both USD hypotheses (both give `cost`). "Exactly one hypothesis consistent with all matches" already makes a NO leg necessary only when the answer is USD.
   - Required change: replace the rule with "the set of hypotheses consistent with all matches has size 1, and n ≥ 2". State that F1 can confirm CONTRACTS but cannot split the two USD hypotheses. Drop F2 (YAGNI: by construction it cannot change the verdict).
5. [MAJOR] §2 S-1 and S-4.
   - Defect: "Stage 0 waits for tape" plus "projected date when E reaches 25" assumes future tape can be read. Every day after 10-13 is post-freeze and outside WP0's declared range. Under S-4 (WP0 refused), waiting is impossible by construction.
   - Pre-run arithmetic: Pass A cannot reach E=25.
     - Trade capture's first evidence is 09-17 09:00Z (§7), so maker windows are complete only from about D=09-18.
     - That leaves 8 days × 4 stations = 32 station-days at most.
     - TE-3 records holes at 09-19 and 09-23 (`TE-3:37-38`), so the realistic count is ≤ ~24 even before the print requirement.
   - Required change: S-1's projection must name the declaration extension it needs (dates, cost). S-4 must say "S1 ends UNDERPOWERED; route to Q1", not "wait". Q4 is answered now: Pass B is required.
6. [MINOR] §3.2 cost / WP4 tally: "≤72 station-days" is gross. Some post-freeze days on these stations may already be SEARCH, because the exit-window study reads Depth10 for exits of live fills (`RA-13-FW:25-28`), and the FQ-live fills were 10-01..10-05. The tally must be net of station-days already forfeited, with the source cited.
7. [MINOR] WP1 Pass A range 08-30..09-15: no trade capture exists, so these days can never be eligible. Emit rows with `reason=NO_TRADE_CAPTURE` without reading tape, and scan 09-16..09-25 only.
8. [MINOR] WP1 `FREEZE_LAST_DAY`: this would be a third copy. `PRE_FREEZE_END = date(2026, 9, 25)` already exists in `nbp_shadow_parity_pure.py:100` and `nbp_market_comparison.py:72`. Keep the name `PRE_FREEZE_END` in the new src module. Do not refactor the scripts in S1.
9. [MINOR] WP1 listing precondition: whether D's ladder is listed and subscribed at D−1 12:00Z is UNVERIFIED (the WS cap of 10 subscriptions per connection is shared). Add `first_registration_ns` per station-day so a structural listing gap is not misread as tape shortage under S-1.
10. [MINOR] WP2 `fill_cost`: assert that `cumulative_cost` is the NO premium excluding fee before comparing it with `1 − p_yes`. This is consistent with `fq_loss_stop_core.BuyFill:61-62` (fee kept separately), but the crosscheck should refuse when `fee_reconciled` is False. Otherwise S-3 could fire falsely on a fee-inclusive cost.
11. [MINOR] WP0 machine line: parsing governance markdown in code is fragile. Pin the declaration file's sha256 as a constant in the module, with a test, and keep `--search-declaration` only as a provenance input. Equivalent effort, less parsing.
12. [MINOR] WP2 F1 must skip any NYC fill. WP0 excludes NYC.

## Cited-vs-actual mismatches
- `catalog_column_scan` "UNVERIFIED on raw feather": actually parquet-only (`catalog_column_scan.py:216,249,291`).
- Gap stream "already read by `replay_sufficiency.py`": actually `runtime/quote_tape_gaps.py:86` (needs a `ParquetDataCatalog`). No reference to the gap stream was found in `replay_sufficiency`.
- `scan_instance`/`classify_instance` at `replay_sufficiency_census.py:1031-1067`: those are the call sites. The definitions are `feather_preflight.py:525` and `cli_basis_offer_gate_scan.py:391`.
- `RULING_TE-3…:4,48`: actual lines are `:5` (no tape after 09-25 read) and `:49` (WP-4 refuses days after 09-25).
- Verified correct: `RA-13:89-92`, `EDGE-4_DISPOSITION:19`, `replay_sufficiency.py:207-222`, `parsing.py:231,283-290,936-938,993-1001`, `data.py:1865`, `test_polymarket_us_depth_parsing.py:431-438`, `capture_audit_fill_support.py:183`, and `ReplaySufficiency` with 20 callers.

## What the plan gets right
- A separate census script over a changed shared census schema, and no AUD-09a re-run inside S1.
- B-3 read correctly: the census does not lift the firewall; a dated SEARCH declaration does, with the cost in both records.
- The unit question is reduced to a pure classifier over own-fill/print matches, with UNRESOLVED as an explicit token, no conversion in the parser, and the tape left byte-stable.
- Run hygiene: subset benchmark first, studies slice, flock, MemoryMax 4G, RuntimeMaxSec, a progress-line stall watch, basetemp under `~/.cache`, and a ≥10 GB entry gate.

## Unverified
- The exec store holds 34 fills, and the 3 named pre-freeze fills (incl. SFO YES 09-21) are present. I had no shell or sqlite access. Require WP2 to print every fill key with its tsEvent and climate day.
- The 293 GB / 81 instances and 5.0 GB free figures, and that the raw `trade_tick/` folder name matches what `_instance_files` expects.
- The import-linter contract name quoted for WP1, the `trade-execution.md:3,29-34,96` citation, and `_load_stream` imported at census `:904`.
```"}],"container":null,"stop_reason":"end_turn","stop_sequence":null,"stop_details":null,"usage":{"input_tokens":2,"cache_creation_input_tokens":9406,"cache_read_input_tokens":164775,"output_tokens":10938,"output_tokens_details":{"thinking_tokens":6382},"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":0,"ephemeral_5m_input_tokens":9406},"inference_geo":"global","iterations":[{"input_tokens":2,"output_tokens":10938,"cache_read_input_tokens":164775,"cache_creation_input_tokens":9406,"cache_creation":{"ephemeral_5m_input_tokens":9406,"ephemeral_1h_input_tokens":0},"type":"message"}],"speed":"standard","fallback_credit":null},"input_transformations":[],"diagnostics":null,"context_management":null},"apiBlockIndex":1,"requestId":"req_011CfxsuhDYnxEgMxTyhPvUx","requestedModel":"claude-opus-5-5","attributionAgent":"architect","attributionMcpServer":"codegraph","attributionMcpTool":"codegraph_explore","type":"assistant","uuid":"a61f6b4b-7398-4e04-b450-ceb4056d1b8b","timestamp":"2026-10-12T19:17:28.178Z","advisorModel":"claude-opus-5-5","effort":"medium","perTurnEffort":"medium","userType":"external","entrypoint":"cli","cwd":"/home/jon/breezy","sessionId":"009a8004-88db-4ace-97bf-db9d2c8234ad","version":"2.1.296","gitBranch":"feat/data-capture-and-risk"}
