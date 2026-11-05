# Open items after the F6 / F7b / F13-B0 merges (coordinator, 2026-10-06)

Merged and pushed at `17aec28b` (`feat/data-capture-and-risk`). One stacked full gate covered everything except the F6 merge-scope guard. That guard was made self-limiting in `2c5f549a` and passed on F6's own branch, and the focused re-run on the final tip passed.

## F6 FQ-BRIDGE (veto merged; it loads at the 16:50Z node launch)
- **F6b producer (NOT BUILT):** `src/breezy/analysis/fq_loss_stop.py`, `breezy-fq-loss-stop.{service,timer}`, `tests/unit/test_fq_loss_stop_producer.py`, `tests/contract/test_loss_stop_schema_writer_reader_agree.py`, `test_producer_reads_no_family_id_of_pre_epoch_rows`.
  - Until it exists, the probe reads UNKNOWN and refuses every FQ entry. That is fail-closed, per FQ-R17. It is consistent with the FQ v1 halt at 16:40Z 10-06.
  - **Blocked on:** the F5 loss-stop floor constant c (−c·√t) being pinned, and F4 labels running (AUT-6 activation).
- **Producer brief MUST carry:**
  - **Directory permissions.** Create `derived/fq-loss-stop/` and `derived/fq-parity/` as 0755 or 0700. Host umask 002 makes default directories group-writable, and the probe's parent-directory check then refuses forever.
  - **`as_of` monotonicity.** It is in-memory in the probe. A producer rewind (backfill, clock fix) leaves the probe UNKNOWN until the node restarts, so the producer must never write an earlier `as_of`.
  - **Interface values chosen by the F6 builder; the producer must match them:**
    - `MAX_AGE_H`=26 and `STALE_VETO_H`=36.
    - The `loss_stop/v1` layout.
    - Digest = `sha256(schema|verdict|as_of|c2_hwm|truth_sha)`.
    - Parity paths `derived/fq-parity/latest.json` and `live_fill_count.json`.
    - The count file's mtime is freshness-checked against `STALE_PARITY_H`, and the count must be monotonic.
  - **Stale window:** between 26 and 36 h, entries are allowed only while a CRITICAL alert is actually delivered off-box (coordinator ruling).
- **Retirement owner** (FQ-R28): the coordinator.

## F7b (core merged; dead in production by design)
- **F5 pin request (F7B-R10/R11).** Pin the following in the F5 design via a prereg amendment. Until then, `evaluate_e_process` returns `INSUFFICIENT(guard_unpinned)` and PASS is unreachable.
  - Calibration-guard thresholds: `n_guard_min`, `spiegelhalter_abs_z_max`, `slope_band`, `bin_edges` plus the CI rule, and pooled vs per-side.
  - The KILL constants copied from the MC: `KILL_GRID_POINTS=5`, the per-m λ cap `min(0.5, 0.5/max(X_max−m, 0.5))`, θ=½, and the bar `log(2/α_kill)`.
- **Forward-only shadow source registration** (E-25 rule 6b) needs an F5 ruling. The registry is empty, so `forward_shadow` refuses.
- **`market_baseline`** is absent: `bss_all_decisions` = `UNAVAILABLE(market_baseline_absent)` until AUT-4 WP1r. The per-rung PIT definition is also absent (`pit_spec_absent`).
- **Moved tests:**
  - To AUT-4 row 10: nomination, forward_shadow, eval_live, eval_offline, the parity detector, and the nomination-columns contract.
  - To AUT-5 r8 WP3 (F7B-R20): the policy-loader test.
- **Deferral:** the `is`-identity half of `test_elond_single_definition_in_persistence` waits for the first re-export of `elond`.
- **Process note:** the Slice 2 builder captured RED for two commits by moving existing source aside. The tests are real and reviewed, but this breaks the brief's TDD rule. It is recorded here; no rework.

## F13 B0
- **Census bug:** `release_census` lists nominal LAMP runs up to 23:30Z of the current day, i.e. in the future. Cap the listing at now. It is low-impact because B0 uses only tape-period windows, but fix it before B1.
- **NBP vintages are absent** from the catalog, so B1's family is PFM only (m=1, R26).
- **PFM backfill:** 2026-08-25 → 10-06 for the five WFOs, coordinator-run 10-06 (~105 paced requests). GFS leg: not run.
