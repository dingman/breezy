# P3 r1 review — security-reviewer

**VERDICT: APPROVE-WITH-CHANGES** (confidence 78)

**Required changes**

1. **Authorization basis is overstated.**
   - The audit's item 3 (`AUDIT_independent_2026-10-22.md` L46) is a "2-hour GTD venue probe". It names no order count and no capital ceiling.
   - `AGENT_ARCHITECTURE.md` L57/L168 governs skill #2's allowlist. It requires a "named per-dispatch operator exception with a capital ceiling", and the plan cannot grant that to itself.
   - Fix: say plainly that the exception is the plan's own, with a $0.04 ceiling. State the deviation from the 2 h scope (H of 4 h or more, plus a 10 h order A). Add a one-line heads-up in the run report. Do not ask the operator. The "B2 ran the same shape" precedent is reasonable, but its ceiling was a 600 s rest.

2. **Orphan handling when the process dies hard.**
   - SIGTERM is handled (`_maker_control_core.py:533`). SIGKILL, an OOM kill (`MemoryMax=1G`) or a power loss is not.
   - Add one sentence: the backstop is the GTD itself, with B at most 6 h and A at most 10 h. For A, either cancel it as the plan says or give it a short rest. The preflight on the next run, or the 16:50Z boot check, would show any survivor.
   - Item 5 below separates the cancel-failure case, where A could stay open for 10 h.

3. **The shared `EXPIRY_POLLS`/`EXPIRY_INTERVAL_S` in `_cleanup` are tuned for 600 s rests.** `_cleanup` (`polymarket_us_maker_positive_control.py:937-988`) polls `left_to_gtd` orders with those constants.
   - If the 2-cancel budget refuses a cancel, B is left resting for hours and the cleanup poll will not wait for it.
   - Specify that in horizon mode this path reports `LEFT_ORDER_NOT_LAPSED` plus a stderr warning. Do not make it wait.
   - The budget is exactly 2 cancels: A's cancel and B's F4 or cleanup cancel. A retry after a 5xx would then be refused. Set `max_cancels=3`; the order-hygiene risk of a spare cancel is nil.

4. **Node-appearance handling must cancel by id before returning INVALID.**
   - The plan has `probe_production_node()` at each heartbeat, but not what happens next.
   - The existing `probe_production_node` is the R13 guard and raises. Confirm it raises through `run_control`'s `BaseException` path, so `_cleanup` runs and B is cancelled.
   - Add this to the "node appears" test. Right now that test only asserts INVALID.

5. **Order A's cancel must not depend on B's flow.**
   - Cancel A and confirm it is terminal before resting B, as written. Cancel A before arming B's rest.
   - If A's cancel fails, either fail fast (cleanup, INVALID) or accept 10 h of exposure. The plan must say which. Recommendation: fail fast and cancel by id on retry.

6. **The firewall re-digest is under-specified.**
   - Pin the exact test names plus the "prior digest" comment.
   - The claim "call-site sets unchanged" must be machine-checked by those two tests. The plan says that already, but add that `_cleanup_by_listing`'s use of `is_own_probe_shape(ceiling_secs=…)` must not widen the shape match.
   - In horizon mode, the shape match must pin the exact GTD. It must not be a ceiling-width window of 36,000 s, which would match any account order.

**Not a defect**

- Taking the shadow node down is fine. It yields no evidence per the audit, the supervisor reboots it at 16:50Z, and the open-order check runs at boot. Add a line to confirm the supervisor will not relaunch before the probe ends. That is the R13 and heartbeat check.
- The preflight of zero open orders, and the final-clean check that also GETs each own order for fills, are sound.
- The create hard caps (2 creates) are sound.

**Over-engineering to cut**

- Drop `P3_A_ECHO` as a separate verdict. Record it as a `details` field, not a verdict code.
- Drop the `--select-only` mutual-exclusion arg and the `[3600, 21600]` range validation, or keep only a single clamp. They are a flag for a one-shot run.
- Drop the 8-case test suite. Keep four: PASS, FAIL_LATE then cancel by id, node appears then cancel, and "GTD above ceiling refused before signing". Keep the no-flag regression because it is free. The rest are fake-clock permutations of a $0.04 one-shot.
- Drop the full `Budget(max_gets=60, max_aux_gets=20)` tuning to a looser value. A tight GET budget can turn a healthy 6 h watch into BUDGET_EXHAUSTED. It is one more way to get INVALID with an order still resting.
- Step 0's rest-horizon computation is reasonable, but cap H at 4 h flat if the printout is fine. The "rounded up plus 30 min, capped at 6 h" rule adds nothing.
- Do not run the python-reviewer and security-reviewer as two separate review rounds. One security-reviewer pass on the diff is enough.

**Substantive question (1)**

PASS and FAIL are fixed before data and are specific. One gap: F3 "EARLY" counts CANCELED, but a venue halt or sweep also yields CANCELED. The plan handles this with the public market-status read, which is fine. Add that a CANCELED with a non-user cancel reason (for example `UNSOLICITED_CXL_REASON_*`) is recorded verbatim, since that reason is the evidence for audit item 4.