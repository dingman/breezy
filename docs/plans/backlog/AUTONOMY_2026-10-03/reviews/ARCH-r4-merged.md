# ARCH r4: merged peer review (coordinator merge), scored sha 17531011…dd508e

Scores: architect 90, trading-bot-architect 86 (1 HIGH), security-reviewer 90. Final 86. Duplicates merged; no contradictions.

## HIGH
- **W1 [trade N1]: the ATTEST cadence leaves an expiry gap.** A daily ATTEST at 15:30 cites verdicts from 05:00–05:30 that are valid ≤26 h, which leaves about 8 h a day under `registry_attest_expired`, covering the 10–11Z hunt window.
  - State the invariant `ATTEST period + production→ATTEST lag ≤ MAX_VERDICT_VALIDITY_H`, with margin.
  - Preferred fix: the intraday engine pass issues ATTEST at most every 6 h, citing intraday-produced HEALTH and RECONCILIATION verdicts with 8 h validity.
  - Add `test_attest_cadence_has_no_expiry_gap` over the schedule table.

## MEDIUM
- **W2 [sec N2, arch N2]: drill budget and eligibility.**
  - `DRILL_INJECT` gets its own `DRILL` cause class that charges only `drill_resumes`. Add `test_drill_resume_never_charges_model_budget`.
  - DRILL_ADMIT and DRILL_PROMOTE require the incumbent to be CHAMPION and not `demoted_for_cause`. Add `test_drill_refused_over_halted_incumbent`.
- **W3 [trade M2, arch N8, sec N2]: the drill ROLLBACK target.** "Drill-episode family" means the minted child only. The superseded incumbent (fq_v1) gets `rollback_eligible=true`. Add a test that the drill ROLLBACK to fq_v1 is admitted.
- **W4 [sec N1, arch N1]: HWM_RESET.**
  - The fold of the post-reset chain, with the restrictive effects of the dropped rows replayed, must be at least as restrictive as the fold of the full export. Otherwise the CLI refuses. Add `test_hwm_reset_cannot_unhalt`.
  - The CLI writes a new export (restored prefix plus the reset row). Readers verify against the newest export, and the journal cites the export it replaced.
  - After a reset the resolver must resolve.
- **W5 [arch N3]**: `registry_halted` and `registry_not_champion` clear on the first verified tick whose fold names the family CHAMPION. Add `test_resume_clears_registry_halted_without_relaunch`.
- **W6 [arch N4]: `entry_guard` data source.**
  - Use an exact-key read path, such as a `fill_by_day/` index. The venue key schema is injected from the adapter layer, because persistence cannot import `exec/client.py`.
  - Add a lint-imports contract and a per-tick cache on the `try_submit` hot path.
  - Add this to §10 AUT-5.
- **W7 [arch N5]: forward window.** Define the window length in the policy block, under a `pins.py` ceiling. Either a candidate past K_max gets `ERROR(k_exceeded)` and counts as consumed, or AUT-3 limits mints to K_max per window. Pick one.
- **W8 [trade M1]: fresh reconciliation at the swap.** Add a post-STOP RECONCILIATION producer slot at 16:41–16:43Z, with its own lock and a bounded runtime. Define the §4.4 horizon as "produced after STOP that day". Update §10 AUT-2.
- **W9 [trade M3]: node-side delivery must not block trading.** Run `deliver_with_proof` via `run_in_executor` or a bounded outbox drained off the loop, with a hard deadline. Add a test that `try_submit` latency is independent of webhook latency.
- **W10 [sec N3]**: The `entry_veto` slot is a required, non-Optional parameter. Add `test_compose_refuses_without_entry_veto_slot` per composable kind.
- **W11 [sec N4]**: Persist the self-heal restart counter (in `evidence/selfheal/<date>.json` or on the chain). Add a test that the cap survives a process restart.
- **W12 [sec N5]**: Detectors and the drawdown limit DO include `drill=true` fills. Add a test.

## LOW
- **W13 [trade L1, arch N7]: canary.**
  - `alerts_undeliverable` reads the last 2 days' journals and applies `ALERT_CANARY_MAX_AGE_H` to the newest `delivered=true` row.
  - Specify a canary retry cadence, for example hourly after a failure.
- **W14 [trade L2, arch N8]**: Fills of a voided pair are labelled under that family with `excluded_reason=voided_pair`, outside both drill and production n.
- **W15 [arch N6]**: Name the actor that clears an INTEGRITY freeze as build-side incident handling, never an operator decision, or state it as an accepted residual.
- **W16 [sec N6]**: Retired demand files move to `evidence/demand/` instead of being unlinked.
