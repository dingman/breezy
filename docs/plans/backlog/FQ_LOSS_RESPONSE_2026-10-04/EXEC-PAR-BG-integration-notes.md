# EXEC-PAR BG integration notes

These are binding inputs for the BG-1 store implementation, BG-5 and BG-6. They come from the BG-1b, BG-1c and BG-1d reviews of 2026-10-11.

1. **The store implementation of `CounterStorePort` belongs to the integration package.** That port comes from BG-1d (`exec_par_reconcile.py`).
   - It is satisfied over the BG-1b latch counters, including `retire_pending_rebuild`.
   - `clear_gappy_mark` must **delete** the `gappy/<day>` row, not tombstone it. A later fault on the same day re-creates the mark, because BG-1b `write_gappy_mark` is first-write-wins.
2. **BG-6 integrity halt triggers.** BG-6 must raise an integrity halt on **any** increase of `ingest_fault_count`. It must also do so on any increase of `gappy_write_failures` (BG-1b `IngestGuard`), because a failed gappy write is not retried.
3. **AMBIGUOUS mark recording.** BG-5/BG-6 wiring calls `ledger.enable_ambiguous_mark_recording()` only at K>1, when the consumer is attached.
4. **Settled-P&L reads (BG-5).**
   - Source `today` from the injected clock.
   - Read `SettledPnlReading` counts: pending, overdue and fee_unreconciled.
   - Never treat an absent row as zero.
   - The caller maps each fill's instrument to the outcome of the side that was held. For NO, flip the sibling.
5. **Entry and exit discrimination everywhere.** Use the slot `is_exit` flag or the Nautilus `order_side`. Never use `wire*` fields.
6. **2-of-5 station-day flags (BG-5).** Per-day flags are evaluated against that day's budget. If the operator changes the budget, the flags are not comparable across days, so the stage report must state that.
7. **Known residual (BG-1b).** A dropped anchor on queue overflow orphans its fills. Each orphan is gappy-marked, and BG-1d reconciliation rebuilds the day from durable fill records.
8. **Amendment reference convention (BG-3, N4).** A frozen `EXEC-PAR-D-PREREG-A<n>.md` lifts the cleanup-demotion pause only if it is sha-valid against its `.sha256` sibling AND contains a standalone line `cleanup_demotion_ts_ns: <n>` with an exact integer match. A number in prose does not count. Any amendment that re-promotes after a demotion must carry this line.

## BG-9 freeze-marker convention

BG-9 (`tests/unit/test_exec_par_wp5b_config.py`, `freeze_violations`) reads the frozen `EXEC-PAR-D-PREREG.md` at configured K>1 only (skipped at K=1).

- **Marker.** The frozen doc must carry the line `<!-- EXEC_PAR_FROZEN_BUCKET: 0.05 -->`, which must equal `node_config.EXEC_PAR_FROZEN_BUCKET`. If the marker is absent the parse falls back to the §3 prose line ``**Frozen label `0.05`.**``. Conflicting or duplicate values fail the check.
- **Status.** The doc's `Status:` line must read FROZEN.
- **Hash.** `EXEC-PAR-D-PREREG.sha256` holds the sha256 hex of the doc bytes (optionally `sha256sum` style, followed by the filename).
- **Freeze step.** Add the marker to the doc before the §13 freeze commit.

9. **O3 promotion record format (r4.5; BG-3 boot guard, BG-9 config guard, BG-10(f) emitter).**
   - **Path.** `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/promo/exec_par_bg10_promo_<stage>_<YYYY-MM-DD>.json`. The stage is the one being promoted FROM: `S1` (K=2) for configured K 3-4, `S2` (K=4) for K 5-6. A configured K above 6 never validates.
   - **Fields (all required).** `stage` and `look_date` must equal the file name. `verdict` and each of `v1`, `v2`, `v3` are the string `PASS` or `FAIL`; all four must be `PASS`. `icc_v` is a finite number >= 0.4147. `bound_level` is 90 or 95. `input_snapshot_sha256` is 64-char hex. `created_ts_ns` is a positive integer.
   - **Pin.** A sha-valid frozen `EXEC-PAR-D-PREREG-A<n>.md` carries the standalone line `bg10_promo_record_sha256: <sha256 of the record file bytes>`. Prose mentions do not count; editing the record after pinning invalidates it.
   - **Names and dates.** Any file with the `exec_par_bg10_promo_` prefix (case-insensitive) that is not strictly `exec_par_bg10_promo_<stage>_<YYYY-MM-DD>.json` with a real date is a problem for every stage. A `look_date` after today (UTC, injected at the boot call site) is a problem. Duplicate JSON keys and overflow or recursion errors are problems, not boot aborts.
   - **Latest wins.** Only the record with the latest `look_date` for the stage is considered. A later FAIL, an unpinned record or an unparseable file supersedes an earlier PASS; there is no fallback.
   - **Guards.** `runtime/exec_par_promo_record.py`: `promo_record_problems(repo_root, k)` is pure and does zero reads at K <= 2. BG-3 (`apply_promo_guard`, called from `force_k1_on_durable_flag`) forces K=1 and raises a CRITICAL alert on any problem at K > 2. BG-9 (`test_real_repo_o3_promotion_record_enforcement`) fails on any problem at the configured K.

## BG-5b in-node stage evaluator: store keys and wiring (binding for BG-6, BG-7, BG-8, BG-10(f))

All keys sit under `exec/polymarket_us/exec_par/`. Every record is canonical sorted-key JSON `{"v": 1, ...}` with the strict BG-1a codec (`exec_par_records.py`). Single writer: the node's loop thread, through `SubmitIntentLatch` methods in `exec_par_latch_stage.py`, each under `_require_held()` and taking `_mutex` once.

10. **Look record (EXCLUSIVE).** `look/<YYYY-MM-DD>` = `{day, outcome, ts_ns}`; `outcome` is `passed`, `failed` or `not_taken`.
    - The key suffix must equal `day`. An identical rewrite is a no-op, a different row for the day raises, an unknown outcome raises. A mis-keyed or garbled row makes `read_looks()` raise (corrupt), never a default.
    - The in-node evaluator only READS looks. It never writes one (r4.5 O5). The writer (`write_look`) is for the BG-4 / BG-10(f) side.
11. **Stamp.** `stage_eval/stamp` = `{ts_ns, boot_ns}`; `boot_ns` is `SubmitIntentLatch.boot_ns`.
    - Written by every healthy pass: PASS, HOLD, PROMOTION_ELIGIBLE, and a STOP whose marker was written.
    - NOT written by a FAIL pass or a `stage_eval_slow` pass. BG-6's boot-pending gate compares `stamp.boot_ns == latch.boot_ns` and `stamp.ts_ns >= latch.boot_ns`.
12. **Liveness (N3).**
    - `stage_eval/liveness` = `{stage_eval_last_start_ns, stage_eval_last_ok_ns}`. The start is written when the evaluate phase begins; the ok is written after the stamp.
    - `stage_eval/reconcile_phase` = `{reconcile_start_ns, reconcile_ok_ns}`. It is written by `run_reconcile_pass` through `CounterStorePort.write_reconcile_phase`.
    - D-PREREG r4 1a says the heartbeat record carries these fields. They live in their own rows instead, because `BreakerRecord` is the shared denial-gate record and the per-tick checks use the in-memory mirror anyway. This is a deliberate deviation.
13. **Report.** `stage_eval/report` = `{ts_ns, verdict, reason, report_json}`; the latest pass wins.
    - `report_json` is the compact sorted JSON of `StageReport`: counts, ratios and flags only, including the per-day AMBIGUOUS counts (`day_stats`) that BG-10(f) consumes.
14. **`CounterStorePort` over the latch (`exec_par_counter_store.py`).**
    - BG-1b keeps no running totals, so a day's stored counts are `scan(rows) + counts_delta/<day>`. `counts_delta/<day>` holds signed deltas (durable minus scan at rebuild time), so later or retried event rows keep counting.
    - `rebuild/<day>` is the pending rebuild note. `retire_pending_rebuild` writes the audit row `rebuild_log/<day>/<ts_ns>` first, then deletes the pending note.
    - `clear_gappy_mark` DELETES `gappy/<day>` (note 1) through the new `SqliteStateStore.delete`; a store without `delete` fails closed.
15. **Alert events (value-free).**
    - `EXEC_PAR_STAGE_STOP`, `EXEC_PAR_STAGE_EVAL_FAIL`, `EXEC_PAR_STAGE_HOLD`, `EXEC_PAR_STAGE_PROMOTION_ELIGIBLE`
    - `EXEC_PAR_STAGE_EVAL_STUCK`, `EXEC_PAR_STAGE_EVAL_SLOW`, `EXEC_PAR_STAGE_EVAL_TASK_DIED`, `EXEC_PAR_RECONCILE_STUCK`, `EXEC_PAR_STAGE_INTEGRITY_HALT`
    - `EXEC_PAR_FORCE_K1_FLAG_WRITE_FAILED`, `EXEC_PAR_COUNTER_REBUILT`, `EXEC_PAR_DAY_EXCLUDED`
16. **Not wired in `app/trade.py` (open for the integration package).**
    - The watcher takes `stage_eval_ports` (`StageEvalPorts`) and arms the evaluator at K>1 only. `app/trade.py` does not pass it yet.
    - Still to be supplied: the durable-fill, slot-table and ledger-registry readers (`DurableDaySources`), the mass-status ingest probe (`await_ready` / `mass_status_ingested`), the governed-station climate-day functions (`today_of`, `day_of_ns`), the serial baseline, the settled-P&L accumulator driver (`refresh_settled_pnl`), and the BG-11 denial classifier.
    - Until then no K>1 pass runs, so no stamp is written and BG-6's boot-pending gate fails closed. K=1 is unchanged.
17. **Open ruling: cleanup demotion and look blockers.**
    - M5 `HOLD_CLEANUP_DEMOTION` alerts and reports only. It does not write `cleanup_demotion/<ts_ns>`, because that record forces K=1 at the next boot (BG-3) and the coordinator commits the lower K.
    - `PROMOTION_ELIGIBLE.look_blockers` are reported only. The node writes no failed look (r4.5 O5: "nothing more").
