# D-PREREG r4.4 delta: rulings on the r4.3 failure-mode confirm

- **Base:** r4 + r4.1–r4.3 (93b7ed20).
- **Review:** NOT-READY, 90/100. One MEDIUM finding and four LOW findings remain.
- **Status:** these rulings are binding, and they fold into the frozen text (§13).
- **Freeze condition:** the freeze-time full three-lens review of the folded text stays mandatory (r4.3 header).

## N1. Marker consumption is tied to `stage_reset` (MEDIUM)

This replaces M3's consumption rule.

- **When a marker counts as consumed.** A `stop_verdict` marker is consumed **only** by a `stage_reset` whose `ts` is later than the marker's `ts_ns`.
  - `--clear-force-k1` always writes `stage_reset` (cause `stop_clear`), so a clear consumes markers through that write.
  - A clear never consumes a marker by any other means.
- **When `--reset-entry-halt` path (a) is refused.** Path (a) is refused if either of these holds:
  - any `stop_verdict` has `ts_ns` ≥ the latest `stage_reset.ts`;
  - `flag_write_failed` is set.
- **What happens after a clear.** The halt being reset has a matching `force_k1_cleared` record, so it must take path (b). A masked stop is never consumed silently: it always moves the floor, and the ramp outcome follows the §1 table.

## N2. `flag_write_failed` clearing (LOW)

`flag_write_failed` is cleared **only** by `--clear-force-k1`, which also writes `stage_reset`. Nothing else clears it.

## N3. Phase bounds (LOW)

A pass has two separately timestamped phases. The reconcile phase always precedes the evaluate phase.

| Phase | Timestamps | Bound | Halt if exceeded |
|---|---|---|---|
| Reconcile | `reconcile_start_ns`, `reconcile_ok_ns` | 300 s | `reconcile_stuck` |
| Evaluate | `stage_eval_last_start_ns`, `stage_eval_last_ok_ns` | 60 s; 2 s on pure CPU | `stage_eval_stuck` / `stage_eval_slow` |

## N4. Cleanup demotion record (LOW)

- **Durable record.** An M5 cleanup demotion writes `exec_par/cleanup_demotion/<ts_ns> {from_k, to_k, ts_ns, reason: low_volume}`.
- **Floor.** The lower-K boot then writes a `k_change` `stage_reset` (§1). The 30-day hold counter counts from the latest `stage_reset.ts`.
- **Enforcing the pause to K=1.** BG-9 fails at configured K>1 when a `cleanup_demotion` with `to_k = 1` exists and no frozen amendment (`EXEC-PAR-D-PREREG-A<n>.md`, sha-checked) references that record's `ts_ns`.
  - This needs a store read in the test. Alternatively, a boot assertion in BG-3 forces K=1 on the same condition.
  - BG-3's boot check is preferred, and BG-9 mirrors it.

## N5. Stop-class membership (LOW)

**Stop-class reasons** are every §5, §6, §7, §9 and §15 rule, including §15-cumulative and §6 at S3, plus demotion verdicts.

**Outcomes** still follow the r4 §1 table:

| Reason | Outcome |
|---|---|
| §15-cumulative | K=1, plus an amendment |
| §6 at S3 | Suspension |
| Demotion verdicts | Down one stage |
| Other stop rules | Back to S1 |

**Cleanup demotions (M5) are not stop-class.** They set no flag and no marker.
