# AUT-5 r1: merged review (coordinator). security-reviewer 82, trading-bot-architect 70. Final 70, NOT READY.
Duplicates merged; no contradictions. The feasibility arithmetic is verified, and `promote_enabled=false` is honest.

## CRITICAL / HIGH
- **M1 [sec1, tr1, tr4]: rebase on ARCH Rev 5.** `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev5.md`, sha 5d2b75fa….
  - Add every Rev 5 test RED-first to the right WP:
    - `test_hwm_reset_cannot_unhalt`, `test_hwm_reset_never_refunds_counters`, `test_resolver_resolves_after_hwm_reset`
    - `test_entry_guard_exact_key_reads_only`, `…_cache_invalidated_on_fill`, `…_unreadable_index_vetoes`
    - `test_compose_refuses_without_entry_veto_slot`, `test_prelaunch_requires_post_stop_reconciliation`
    - `test_attest_cadence_has_no_expiry_gap`, `test_resume_clears_registry_halted_without_relaunch`
    - `test_mint_refused_past_k_max_in_window`, `test_drill_refused_over_halted_incumbent`
    - `test_detectors_and_drawdown_include_drill_fills`, `test_drill_resume_never_charges_model_budget`
  - Implement:
    - W1: ATTEST in the intraday pass at least every 6 h, validity ≤ 8 h. The intraday writer is allowed ATTEST.
    - W7: `forward_window_days` and anchor in the policy block, with K_max mints per window enforced in the store.
    - W8: see M2.
    - W4: HWM reset at least as restrictive, with no counter refund.
- **M2 [tr2]: post-STOP reconciliation (W8).**
  - Add the `breezy-autonomy-reconcile-poststop` 16:41Z unit and the supervisor's journaled STOP-completion signal; AUT-2 produces the verdict.
  - The prelaunch pass requires a RECONCILIATION produced after STOP. `reconciliation_horizon_h` applies to intraday RESUME only.
- **M3 [sec2]**: Add `POLICY_RULING_PIN` in `pins.py`, introduced early (WP1 or WP3), so the engine runs in stages S and L1. WP9 reuses it, with a test that the two pins are equal.
- **M4 [sec3, tr10]: restrictive latency under the daily lock.** Either the daily pass releases the lock between phases (restrictive step first, early release), or the locks are split, or intraday queues and retries. Add a test that holds the daily lock and asserts the 15-minute SLO.
- **M5 [sec10, tr3, tr7]: drawdown.**
  - The statistic includes drill and voided-pair fills (W12). Add `test_detectors_and_drawdown_include_drill_fills`.
  - H0 calibration: add `test_h0_calibration_has_feasible_limit` and `test_filed_drawdown_limit_meets_h0_bound`. If no limit ≤ 1.0 meets 0.05, raise `min_settled_admissible_fills`; never make the limit vacuous.
  - State the fallback after a false-positive TERMINAL.
- **M6 [tr5]: drawdown producer ownership.** AUT-5 OWNS a pinned drawdown producer, with a handshake test against the AUT-2 labels. Do not assign it to AUT-4.
- **M7 [tr6]**: Add `test_promote_executes_when_enabled_and_evidence_met`, an end-to-end fold with an injected policy fixture, so the PROMOTE path is tested although disabled in production.
- **M8 [tr8]: budget across namespaces.** Write a design paragraph: where spend persists (`DailySpendLedger` is re-seeded at boot from durable fills, `exec/client.py:2214`; the budget store is venue-scoped, G21), and how a relaunch or SWAP_CANCEL inherits it. Back it with the named test.
- **M9 [sec4]**: Implement the Rev 5 C5 HWM reset rule and its three tests.

## MEDIUM
- **M10 [sec5]**: On a policy or pin failure, the engine falls back to restrictive-only mode using the code-pinned detector classes. This resolves the contradiction with `test_demotion_never_requires_policy`.
- **M11 [sec6]**: Add a pinned stage flag `widening_kinds_enabled`, enforced in `RegistryStore.append`, with `test_daily_refuses_widening_before_stage_flag`.
- **M12 [sec7]**: `append(mode=…)` enforces the kind mask inside the store, not only in the caller.
- **M13 [sec8]**: State the same-uid threat model. The resolver and watch actor replay `transitions.validate` over the full fold, and check that PROMOTE `cause_verdict_ids` resolve and that artefact bytes equal the row sha. Add tests.
- **M14 [sec9]**: The relaunch request is valid for 60 s, unlinked on handling, and deduplicated by `request_id`. Add `test_stale_request_ignored`.
- **M15 [sec11]**: Widen the drill-clause window to cover the planning date plus slack, or state the re-pin cost.
- **M16 [tr9]**: The import-closure hash at runtime comes from a gate-verified module-list manifest, hashing file bytes only. Add a benchmark under the 120 s and 512M limits. Note that `RuntimeMaxSec` does nothing on oneshot units; use `TimeoutStartSec`.
- **M17 [tr11]**: The watch actor's SQLite read uses `busy_timeout` ≤ 250 ms. Add a test with the writer holding a lock.
- **M18 [tr12]**: Add a challenger-versus-champion paired forward-shadow predicate.

## LOW
- **M19 [sec12]**: Owner-RED placeholders are tracked in the L2 gate.
- **M20 [sec13]**: The drill marker path is root-keyed. Test that shadow does not trip on the production marker.
- **M21 [sec14]**: An alert failure never blocks or rolls back a commit. Add a payload-hygiene test per alert code.
- **M22 [tr13]**: State the 60-day minimum and M=30 as inert in v1.
- **M23 [tr14]**: Assert the timing of the drill D+2 cooldown in a test.

## Other contradictions from planners (anticipate them; ARCH Rev 6 is in progress)
- Use the same fq_v1 bootstrap exemption and ∅→CHAMPION / ∅→RETIRED rows as your r1 (P5-1, P5-2).
- The C2 widening adds `voided_pair`, `slippage_defect` and `unattributed`.
- Systemd: use `TimeoutStartSec`.
