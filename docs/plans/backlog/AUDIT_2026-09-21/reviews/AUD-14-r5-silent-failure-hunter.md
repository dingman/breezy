# AUD-14 — Round 5 review (silent-failure-hunter, FINAL, reconciled)

**Plan file:** AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
**SHA256:** c7646c8da5fe70b6f5eaf4b09bdfa4735c578c2442274c5cd752abf46e5e5db3 (verified via `sha256sum`)
**Round:** 5 (final)
**Reviewer:** silent-failure-hunter (independent, blind)

## Verification of the reported change

§6 now carries a new bullet ("The state operand on a fault load, and what is written back — STATED, not left to the implementer") stating: on `CORRUPT` and `UNAVAILABLE`, `_load_self_check_escalation`'s state operand is the same `SelfCheckEscalationState()` default as `ABSENT`; `store.set` **is** attempted on both fault paths, carrying the **reducer's output**, never the bare default and never skipped. Three sequences are reasoned through and the "skip the write" alternative is rejected by name. §7 step 4 gains three write-back assertions tied to existing tests; §8 item 9 and §9 both reflect the rule. Cross-checked against source this session (`sqlite_store.py:155-176`, `trade_supervisor.py:1198-1207,1297-1303`) — all citations accurate, unchanged from round 4's confirmed baseline.

## The coordinator's attack: trace FAIL, FAIL, (corrupt)FAIL, FAIL

Working the stated design (`escalated_self_check_severity`: CRITICAL iff `result_is_fail and (not count_known or consecutive_failures >= 2)`; `record_self_check_result` increments on FAIL, resets to 0 on PASS, from whatever operand it is fed):

| Poll | Read outcome | Operand fed to reducer | Reducer output | `count_known` | Severity | Persisted |
|---|---|---|---|---|---|---|
| 1 | ABSENT (first boot) | `SelfCheckEscalationState()` (0) | 1 | True | WARN (1 < 2) | 1 |
| 2 | normal | 1 (from disk) | 2 | True | **CRITICAL** (2 ≥ 2) | 2 |
| 3 | **CORRUPT** | `SelfCheckEscalationState()` (0) — the true persisted 2 is discarded, unreadable | 1 | **False** | **CRITICAL** (via `not count_known` override — independent of the persisted value) | 1 (reducer's output, not the bare 0) |
| 4 | normal (store recovered) | 1 (from poll 3's write) | 2 | True | **CRITICAL** (2 ≥ 2, by count) | 2 |

**Every FAIL after the first is CRITICAL: WARN, CRITICAL, CRITICAL, CRITICAL. No under-alert.** The design resists the exact failure mode the coordinator asked about for two independent reasons, both load-bearing: (1) a FAIL under an UNKNOWN count is *unconditionally* escalated by the `not count_known` disjunct, regardless of what the corrupted read's operand happens to be — poll 3 cannot be a WARN no matter what is persisted; (2) because the write-back carries the **reducer's output** (1) rather than the bare pre-reducer default (0), the baseline poll 4 resumes from is 1, not 0 — so the very next genuine FAIL reaches the ≥2 threshold on its own, reproducing a correct by-count CRITICAL rather than requiring a second "wasted" FAIL to rebuild the streak. I additionally traced a harder case — two consecutive corrupt reads (FAIL,FAIL,(corrupt)FAIL,(corrupt)FAIL,FAIL) — and it holds the same way: each corrupt poll escalates via the override (independent of persisted state), and the resumed baseline after any corrupt-FAIL write is always ≥1, so the next genuine FAIL always crosses 2. §7 step 4's `test_a_corrupt_stored_value_escalates_a_failure_to_critical_instead_of_resetting_to_zero` "drives a **second** poll against that repaired value asserting the next FAIL reaches CRITICAL by count" — this is exactly the poll-3→poll-4 transition traced above, not a vacuous or unrelated assertion.

One residual, worth naming though it does not under-alert: the *persisted count value itself* is not historically accurate after a CORRUPT event (poll 3 writes 1, not the true 2) — a reader of the raw store between polls 3 and 4 would see a number lower than the real streak. This is a data-integrity nicety, not a silent-failure risk, because severity decisions never depend on trusting a stale/corrupted persisted number without either the override (unknown) or a freshly-incremented value (known) — I looked for but could not construct a sequence where this produces an under-alert.

## Reconciliation of previously-withheld points (round 4: 93/100)

| Criterion | R4 | Reason given | Disposition |
|---|---|---|---|
| Fidelity | 18/20 | G-13's "hands-off" headline stays observable not fixed; self-check-never-runs case only halved | **(b) AWARDED — 20/20.** Both are explicit, reasoned scope exclusions (§5): deploy-restart automation is correctly out of scope (automating it would be a live-trading-enablement posture change, not a build-side call); the dead-man's-switch residual is named with its owner (`AMENDMENT B-4`) and a concrete technical reason (the watch window and permit-lapse boundary differ, verified in a prior item). Neither is an oversight a plan-text change should close within AUD-14's own scope. |
| Technical correctness | 19/20 | "a self-contradiction inside one section survived a baseline, two review rounds and a revision" | **(b) AWARDED — 20/20.** This is a historical/process observation, not a currently-present inaccuracy — the contradiction it refers to (round 3's fallback) is gone from the text. No new inaccuracy found this session; the write-back mechanism (this round's subject) traces correctly under adversarial stress (above). |
| Implementation specificity | 13/15 | (1) write-back state on fault load unspecified [MY round-4 MINOR]; (2) "decode helper's placement and json encode call are still the implementer's" | **(a) then (b).** (1) is CLOSED — verified above, with a concrete, source-consistent, tested rule. (2) is **(b) AWARDED**: exact intra-module code organization (where a private helper is defined) is not a specificity requirement any other AUD item in this backlog is held to either (e.g. AUD-13's fixtures are specified by class/signature/citation, not by file layout); the key, JSON shape, reducer signature, severity truth table and event names are all literal. Award: 15/15. |
| Acceptance | 19/20 | "item 5 still lands after merge, and the over-alerting consequence... is accepted by argument rather than measured against a real outage" | **(b) AWARDED — 20/20.** Item 5 (a real deploy-restart `revision=` line differing across restarts) cannot exist before deployment — structural, same class as "live proof lands after merge" already reconciled for AUD-13. "Measured against a real outage" would require inducing a genuine production store failure to validate — not something a responsible plan should require; the multi-poll sustained-failure unit test (§7 step 4) is the correct, safe substitute and already exists. |
| Autonomous operation | 14/15 | "sustained outage over-alerts... genuinely noisy and untested against a real outage; the never-ran case is still halved, named with its owner" | **(b) AWARDED — 15/15.** Same reasoning as acceptance (real-outage testing is not obtainable safely) and as fidelity (the never-ran case is a named, owned exclusion, not a gap). |
| Portfolio | 10/10 | (full) | Unchanged — 10/10. |

## Per-criterion points (final)

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 |
| Technical correctness and evidence grounding | 20 | 20 |
| Implementation specificity and feasibility | 15 | 15 |
| Acceptance criteria and validation quality | 20 | 20 |
| Autonomous operation, failure handling, recovery | 15 | 15 |
| Portfolio objective alignment, scope, dependencies | 10 | 10 |
| **Total** | **100** | **100** |

## Required changes

None. The round-4 MINOR is closed and verified sound under the specific adversarial trace requested. No new defect found.

## Blockers

None. No cap is read or valued, no enablement flag is touched, no second permit mint — unchanged across all five rounds.
