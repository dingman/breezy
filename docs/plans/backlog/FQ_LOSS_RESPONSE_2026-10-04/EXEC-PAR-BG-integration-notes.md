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
