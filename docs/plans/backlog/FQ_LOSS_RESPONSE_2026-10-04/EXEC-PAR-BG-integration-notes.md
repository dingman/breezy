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
