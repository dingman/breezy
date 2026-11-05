# S2 r2 final — prediction-market-reviewer — 2026-10-12
Verdict: NOT-READY — the r1 changes are present in the plan body, but r2 contradicts spec v0.3 on the base fill rule, STALE_H, the process-schedule simulation, the §6.9 verdict rule and the denominator, and each of these moves the NO-GO / NOT-KILLED label.

## Disposition check
| r1 review | # | r2 claims | verified? |
|---|---|---|---|
| PM | 1 | One NO-space rule, price-priority bracket, through/same-level split, regime split | PARTLY. The bracket, split and regime are in WP4. The BASE rule is still the r1 rule (R1 below). Only the bracket carries the trade-through logic |
| PM | 2 | Frozen table, no GO, power line, exact sidecar | YES, in §1.1 and WP5. Contradicts v0.3 §6.9 on exact-test primacy and the 10-loss minimum (R4) |
| PM | 3 | V4 stress rule, days-to-200 | YES (V4, goal item 2) |
| PM | 4 | Point p at fill instant, last live p for unfilled, pair and station-day units | YES (WP4 record, WP5 units) |
| PM | 5 | Stratum-standardised T2 | YES (WP5) |
| PM | 6 | (i) REBUTTED: fit ends 2026-06-30. (ii) tail table | (i) TRUE: `nbp_calibration.py:273-278` has validate to 05-03, v5_fit_slice to 06-30, holdout from 07-01. (ii) YES (WP5 `tail_reliability`) |
| PM | 7 | §3 table, live-hours reporting | PRESENT, but computed at 6 h, not v0.3's 8 h (R2) |
| PM | 8 | Marketability, `q_censored`, gap-free frame | YES (WP3, WP4) |
| PM | 9 | DEFERRED: continuous fee conservative | TRUE: 0.0111 quantises to 0.01, so the continuous fee overstates cost |
| PM | 10-12 | WP0 mid test, P2 pre-step, cluster counts | YES (WP0.1, P2, goal item 5) |
| MLE | 1 | UNSCREENED label, degenerate draws, power, exact p | PRESENT. The UNSCREENED rule differs from v0.3 (R4) |
| MLE | 2-3 | Sidecar, seed, manifest, `pin_inputs` | YES (goal item 9, WP1) |
| MLE | 4 | Gaps and truncation, measured coverage | PRESENT in WP0/WP4. "Eligibility uses measured print coverage" conflicts with the v0.3 denominator (R5) |
| MLE | 5 | Total event order, Δ clock rule | YES (WP4) |
| MLE | 6 | Naked-short reason; two variants; third REBUTTED | Cites TRUE: `backtest_order_guard.py:118` (`NakedShortRefusedError`) and `:284` (`_refuse_naked_short`), `ladder_ev/config.py:171`, `parsing.py:936-938`. The rebuttal of the third variant is now moot: the spec rule is that third variant (R1) |
| MLE | 7-14 | Units, tail table, E4, P2 flags, +60 min stress, mid test, point p, stratified benchmark | YES (WP5, WP0, E4, P2, WP2, WP6) |
| MLE | 8 | "sealed 05-05..06-30" REBUTTED as `v5_fit_slice` | TRUE (`nbp_calibration.py:276`; ruling cl.1 freezes [07-01, 10-02)) |

## Spec v0.3 contradictions (plan line -> spec section)
- **R1 [MAJOR] Base fill rule (plan WP4, L188-192; Q2 L308 -> spec §6.1).** Plan base is `V(t) = prints with q <= b`, filled when `V >= Q0 + 1`. v0.3 is price-priority trade-through: a BUYER print at NO price > b REDUCES Q0, then prints at q <= b consume the remainder. r2 omits the Q0 reduction. That is the r1 PM #1 bias: deep better-priced size is never cleared, so the base rate is biased low and is the row that decides V2. The plan's "base = spec rule as here" is therefore false. The pp variant (any print with q < b fills) is a looser upper bracket, not the spec rule. Fix: make the v0.3 rule the base, with the stress at 2x(Q0 + 1). Keep the old rule and pp only as report-only brackets, and drop `RULE-SENSITIVE` as a rescue label. Add RED tests `test_better_priced_buyer_print_reduces_q0` and `test_print_at_or_below_b_consumes_remaining_q0`.
- **R2 [MAJOR] STALE_H (plan L84-92, WP3 L167, L318 -> spec §3 "STALE_H = 8").** The plan uses 6 h throughout. At 8 h the bid window runs to about 10Z on D, not 08:04Z. The 20:04Z hole and the daily cancel-replace it forces disappear. The §3 table, live hours and dead hours are all wrong, and the 6 h windows depress bid-live hours and fill rate. Fix: STALE_H = 8 as a pinned constant (extend `test_constants_match_spec`), recompute the table, and drop Q5 and spec input 5. The `forecast_stale` cancel and its test names stay.
- **R3 [MAJOR] No process-schedule simulation (no WP; spec input 11 L324 only -> spec §3 window paragraph, §6.0).** v0.3 requires Stage 0 to simulate boot, the 10 h permit and relaunch cancels so the fill rate transfers. The plan has no permit TTL, daily boot, relaunch, or `expire_time = min(09:00 LST, permit, end of UTC day)` episode cut. The UTC-day-end cut alone starts a new episode at 00:00Z every day. Without these cuts the queue-reset churn is absent and the base rate is biased UP, which can produce a false NOT-KILLED. Fix: add a `process_schedule` input (episode cut times per day: UTC midnight, permit expiry, and boot and relaunch instants taken from node/supervisor logs, or a pinned stylised schedule if the logs are unavailable), one `CANCEL_PROCESS` end reason, a WP4 test `test_process_cut_starts_new_episode_and_resets_queue`, and report the share of episodes cut.
- **R4 [MAJOR] Verdict and §6.9 (L40-42, L47, L221-227 -> spec §6.0, §6.9).** (a) v0.3 §6.9 FAIL uses an EXACT tail test at 0.05. The plan decides on the bootstrap and demotes exact to a sidecar. (b) v0.3 says any §6.9 verdict needs >= 10 expected losses, else UNSCREENED. The plan's V3 can emit FAIL at any count, and V5 uses a different bar (power at k=2 >= 0.80, filled >= 20, defined draws >= 0.90). V6 can therefore emit NOT-KILLED with fewer than 10 expected losses. (c) The spec table has no row for base >= 0.10 and stress < 0.10. The plan's V4 `NO-GO (stress)` is a defensible fill but is stricter than the spec's NO-GO definition, so it must be written back to the spec explicitly. Fix: V3 and V5 use the exact test and the 10-expected-loss minimum (the bootstrap and power line stay as descriptive sidecars). Record V4 as a spec input.
- **R5 [MAJOR] Denominator (L76, L181, WP0.2 -> spec §6.0).** v0.3: denominator is all covered bid-bearing station-days, never only print-eligible days. The plan says "eligibility uses measured print coverage", censors TAPE_GAP episodes out of denominators, and counts a pair only if it has >= 1 uncensored episode. Define eligibility by recorder/depth coverage (gap records) only, never by print presence. Report print-less windows as bid-bearing with zero credited volume (they enter the denominator as unfilled), and report the censored share beside the rate. Also reconcile the start day: the spec says 09-18 is the first replayable day, the plan says 09-19. Either is fine if measured, but state it.
- **R6 [MINOR] Holdout clause 3 (L290, Q1 L306, S-6 L63 -> spec §6.0).** The plan's reading matches v0.3: the plan cites cl. 3 ("descriptive evidence only") and the S-6 contingency is no longer needed. Ruling cl. 3 is true as quoted (touched [07-01, 10-01)). Close Q1 and S-6 as resolved by v0.3, and keep the holdout-touch disclosure line. The tail table also reads the frozen [07-01, 10-02) NBP rows; it is covered by the same clause, so no new issue.

## Residual items
- R1-R5: MAJOR each, so NOT-READY. None is BLOCKER-level (the plan is internally coherent and no invariant is breached), but together they make the NO-GO / NOT-KILLED output non-conformant with v0.3.
- R7 [MINOR] Section cross-refs "§1.2/§1.3/§1.5/§1.9" in the disposition table point to goal items, not subsections.
- R8 [MINOR] Spec inputs 1-3, 5, 9 (L313-318, L322) are now folded into v0.3. Prune that list so it does not contradict the spec.
- R9 [MINOR] Simplest path: ~23 agent-hours across 7 WPs, price-priority bracket, power sims and tail table, for an exploratory kill screen. The operator asked for simplicity. After R1 the pp variant can go and the tail table can be marked optional if cost binds.
- E4 (disk 4.7 GB < 10 GB) blocks execution regardless; this is a coordinator action.

## Invariants
- Nautilus immutable / no native reimplementation: PASS (native queue_position rejected on the naked-short evidence above).
- allow_short False: PASS. Firewall/safety tests: PASS (S2 touches only scripts/analysis and tests/unit; import-guard test present).
- Operator caps / enablement / BREEZY_ORDERS_ENABLED: PASS. Frozen PREREG and dates: PASS.
- Stage 0 exploratory, never promotion evidence, never GO: PASS. NO-TRADE ruling in force: PASS.
- No leakage (strict available_at + Δ < t0, ns scoping, score after simulation): PASS.
- Holdout (`open_holdout` never called, disclosure line): PASS.
