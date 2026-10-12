# S3 r2 final — prediction-market-reviewer (domain math; architect dispositions co-checked) — 2026-10-12
Verdict: NOT-READY — all 24 r1 dispositions are present in the plan body, but two MAJOR contradictions with spec v0.3 remain (the kill anchor is not the stressed fill rate, and the deff-1.5 stop variance is neither modelled nor shown to cancel). Both are small text/test edits.

## Disposition check
| r1 review | # | r2 claims | verified? |
|---|---|---|---|
| architect | 1 | g1_unreachable/M-yes, empty groups safe | YES: §3.1, WP0 pin, WP1 RED. sim.py:71-72 guards `groups` only; `prepare_mix_groups` (engine.py:90-107) appends an empty list per date, so groups is never empty |
| architect | 2 | mixes ("M-pool",), engine.py:355 untouched | YES: §3.2, FloorSpec validation, equivalence test; engine.py:355 hard-codes M-pool as cited |
| architect | 3 | WP2 cut, DEFAULT_FREEZE/HORIZON as 110-day label | YES: §4.3 Window; gate.py:57-58 and :345-348 true |
| architect | 4 | two hashed documents, CLI diff minus provenance | YES: WP0 table plus WP1 completion 3 |
| architect | 5 | OUTER 20/2000 | YES: §4.3, WP3 pins, test; evidence json :1656-1657 true |
| architect | 6-9 | path_families, e2/outer threading, canonical FQ_SPEC in gate.py, constants test | YES: WP1 body |
| architect | 10, 11 | two JSONs/git_head/clean tree; binding gated on window ruling | YES: §1, §2 item 3 |
| PMR | 1 | rho_hat=0.5 binds S5 at 0.5, no code | YES: `rho_bind` = max(0.25 floor, rho_hat) (rows.py:286-289) gives 0.5; `_BINDING` still contains S5-bind (report.py:80). Simpler than r1's binding_rows; accepted |
| PMR | 2 | S8 persist3 binding, S9 report, conditionality | YES: §4.2, WP1 sim persist, MAKER_SPEC binding tuple |
| PMR | 3 | 2x rule, base-point terminal, UNDERDETERMINED, beta-binomial | PARTIAL: mechanics present; the anchor choice contradicts spec v0.3 (see R1) |
| PMR | 4 | A1 certified, LD-OBF to v0.3 | YES, and v0.3 §4 now agrees; plan text is stale (R3) |
| PMR | 5 | worst-feasible G1 | YES: WP1 rows.worst_feasible_z plus tests; all_lose_z at rows.py:326-334 sums h=0 over all legs as cited |
| PMR | 6 | lambda_sd/r_sd/tick_share from templates | YES: §4.1 plus WP3 tests |
| PMR | 7 | sub-0.70 cells, NOT-APPLICABLE | YES in body, but now moot (R3) |
| PMR | 8-13 | alpha both ways, R4 ruling, borderline rerun, pin vs RED, rebate sign, tripwire wording | YES: §4.6, §4.5, WP0/WP1, §4.1, §1 |

## Spec v0.3 contradictions (plan line -> spec section)
- Plan "Spec" header (v0.2 §4,§6.1,...) and the Review disposition -> spec is v0.3. Re-cite.
- Plan §4.5 f_kill (= base-rule point) -> spec §4 "must not freeze as unreachable_veto ... at the Stage 0 stressed fill rate". The plan's first-look kill is at the optimistic rate, so a family unreachable at the stressed rate is held as UNDERDETERMINED, not "not registrable".
- Plan §4.4/§10 item 1 (LD-OBF conditional, spec input) -> spec §4 "One loss stop ... LD-OBF dropped". Resolved; delete the conditional and the "new S3 WP" branch.
- Plan §4.5 NOT-APPLICABLE row, one-leg b in {0.50, 0.60} cells, `test_two_leg_bid_below_070_is_refused`, §4.1 Bernoulli-fallback prose, §10 item 3 -> spec §3 `bid < B_FLOOR(0.70): cancel`. No bid below 0.70 can exist. This is dead machinery against the operator's simplicity directive. Keep one assertion that templates refuse b < 0.70.
- Plan §4.3/§4.4 certify the unchanged FQ clock -> spec §4 "stop's variance carries the cluster design-effect inflation (1.5 ceiling)" and the PREREG freezes "exactly the object S3 certifies". The plan never mentions this inflation (fq_loss_stop_core has no deff parameter; sigma comes from production_variance).
- Plan §4.6 "harm-side A1 alpha spends no FWER" -> spec §4 "harm stop, outside the RA-13 efficacy alpha spend": AGREES. MAX_RUNGS 2 conditional: AGREES (cells k in {2,1}). B_FLOOR 0.70: AGREES.

## Residual items
- R1 [MAJOR] Kill anchor vs spec. Set `f_kill` = the 2x-rule POINT estimate (the stressed fill rate, spec §4), and keep `f_pass` = the 2x 95% lower bound. This keeps PMR F3 (no terminal kill on a lower bound) and matches the spec. UNDERDETERMINED then means pass at the 2x point and fail at the 2x lower bound. Update §1 table, §4.5, the second-look rule, `test_verdict_kill_reads_f_kill_and_pass_reads_f_pass`, §8 row, and Q2. The base-rule point is printed as context only.
- R2 [MAJOR] Deff-1.5 stop variance. State and pin which of two things S3 certifies. (a) Inflation is a uniform sigma rescale that is absorbed because c is re-solved on H0: add a WP1/WP3 test showing c scales and G3 is invariant, and say the clustered-null risk is carried by S8/S9 plus the beta-binomial fills. (b) Inflation changes the statistic (for example a fixed c or a floor on the increment): then add the inflated cells to the verdict. Without this entry the S5 freeze can differ from the certified object.
- R3 [MINOR] Delete the stale text listed above (v0.2 header, LD-OBF branch, sub-0.70 machinery, §10 items 1 and 3). Re-cite the spec as v0.3.
- R4 [MINOR] Spec §6.7 gated stress theta = 0.08 is not in the verdict cells. Add one printed cell at theta 0.08 (BE moves about +0.0005 to +0.0013), or state it belongs to S5. Spec "looks ordered by settlement time": the sim ticks by climate date, so say so.
- R5 [MINOR] Open question 3 (FILL_ICC): pin max(S2 ICC, 0.5/7); spec §6.4 uses deff 1.5 as a ceiling, so a lower floor would be optimistic.

## Invariants: PASS/FAIL
- Nautilus immutable, allow_short False: PASS (no Nautilus edits; FQ tooling parameterised only).
- No safety/contract/NO-SEND test weakened: PASS (np_bound untouched; aliases pinned; WIDENED-row rule restated).
- No operator-reserved value, enablement, or BREEZY_ORDERS_ENABLED touched: PASS.
- No frozen PREREG/amendment/f5 evidence edited, no date moved: PASS (110-day label on FQ's own freeze/horizon; other freeze/horizon refused).
- Stage 0 exploratory, NO-TRADE in force: PASS, except R1 (kill anchor should be the stressed point, which is still not promotion evidence).
- FQ A1 reproducibility: PASS (two hashed documents plus CLI diff).
- Bar not laxened: PASS (core constants imported; G1 stricter; rho 0.5; S8 binding), subject to R2.
