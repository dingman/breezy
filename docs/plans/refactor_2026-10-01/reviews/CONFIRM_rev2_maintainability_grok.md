I'll re-read Rev 2 against the prior maintainability review and score only whether each required revision landed.Rev 2 claims the eleven revisions landed. I’ll check the new placement and test-tier wording against the layer contract before scoring them.Rev 2 addresses all five blockers. One required revision is only partial, and one new citability objection remains.

| # | Status | Where Rev 2 handles it |
|---|---|---|
| 1 | **ADDRESSED** | R1.3 dropped. §3.1 declined steps; §5(b) F1. |
| 2 | **ADDRESSED** | R1.1 dropped. §3.1; §2.1 item 5. Neither `persistence` nor `domain`. |
| 3 | **ADDRESSED** | R2.3 targets `scripts/analysis`, moves every name imported by the paper-replay pair and the census, and states that BC-3 still breaks `breezy-replay-daily` until that import is gone. §3.2 R2.3; BC-3. |
| 4 | **ADDRESSED** | `catalog.instruments()` stays out of `breezy.analysis`. Ceilings `scripts/analysis: 364` and `src/breezy/analysis: 13` change in the same commit. §3.2 R2.2. |
| 5 | **ADDRESSED** | `live_family_tally.py` is not moved or edited. §3.1 STUDY row; BC-6. |
| 6 | **PARTIAL** | R2.4 is dropped (§3.1). R1.2 is not dropped. Appendix A keeps it, gated by [R3]: per-actor characterization, fee probe excluded, and dropped outright if BC-4 removes `nbm_forecast_actor`. |
| 7 | **ADDRESSED** | R0.3+R0.4+R0.6+R0.7 are one commit (R0.A). R0.5 is pruned to the gating CTs. CT-9 is detached from R3.6 and from C3. |
| 8 | **ADDRESSED** | R3.5 stays deferred. If done: mixin so `self.`-shaped callees stay valid; same-commit N2 list (`:738-772`) and `EXEC_ASYNC_LIFECYCLE_MODULES` (`:1788`); no X3 exemption. |
| 9 | **ADDRESSED** | BC-4 lists the forbidden row, `IEM_HOST_ALLOWED_MODULES`, and the extra test files. BC-5 lists the layers equality (`:68-86`), forbidden `source_modules` (`pyproject.toml:158-161`, test `:124-136`), and the layer row. |
| 10 | **ADDRESSED** | §4.4 and §3.3 use the real deltas (~961 / ~1,020–1,060 / ~1,806; duplicate LOC removed ~40–80). No "under 800". Gate target is ~17.3 min after R0.8, not "≤ baseline". Byte-identity is the stripped payload on frozen `--as-of` inputs (§3.2, before R2.1). |
| 11 | **ADDRESSED** | R0.1 comments ride the commit that already edits the file. R0.7 rides R0.A, and §4.6 now exists. R1.6 destination is `breezy.runtime`. R2.1 stays a parity pin. |

**New objection.** R2.2's preferred citability mechanism is false. `PLAN_Rev2.md:409` says re-export shims stay "at their current line positions" so `RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md:96` keeps resolving. That ruling cites `scripts/analysis/score_live_trials.py:611,675,689,707,861,1079,1788`. The moved defs start at `:376`, `:468`, `:557`, and `:950` (`PLAN_Rev2.md:407`). A shorter shim at `:376` shifts every later cite, and a cite inside a moved body is no longer in the file. The citation-map alternative in the same sentence is the one that works. Make the map the committed path and list the moved cite lines. Do not claim line-stable shims.

Not material: the R0.A partition sum (`PLAN_Rev2.md:296`) double-counts a test that is both `heavy` and under `tests/integration`, because `|T1|` is path-scoped (`:543`). Define the buckets as disjoint. `breezy-score-live-trials.service:28` is `Type=oneshot`, so R1.6's no-shim exception does not fight the §3.0 re-export rule.

Verdict for Rev 2: **APPROVE-WITH-CHANGES**
