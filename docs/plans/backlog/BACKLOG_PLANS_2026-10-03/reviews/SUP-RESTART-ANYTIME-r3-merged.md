# SUP-RESTART-ANYTIME r3: merged blind review (2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| trading-bot-architect | 95 | 0 |
| silent-failure-hunter | 93 | 0 |

The lower score is 93, so the plan goes to r4. Each item below is a small, targeted edit.

## Owed in r4

1. **[MED, TBA] Future timestamps can pin "fresh".** A line stamped later than `now_ns + 60 s` currently counts as fresh forever, because of max-wins together with R7 treating a negative age as fresh. Treat such a line as unparseable / not fresh. Add test cases T7b and T11b.
2. **[MED, SFH] Goal 3 over-claims.** If a restart lands in [17:00, 17:10) while the node is down, there is no launch, and no page fires until B1 `NO_NODE` at 17:10. This gap predates the plan. State it as a residual and add a §3 row.
3. **[MED, SFH] Check 9 binding is overstated.**
   - `find_adopted_node_log` can bind a newer node-stamped log written by a refused duplicate launch. The result is a wrong-log deferral (a page), never a false mark.
   - Reword "excluded".
   - Add T18b case (e): a sibling stamped log written after the start.
4. **[LOW] Deferral-counter gaps.**
   - With `tracked_pid is None` the step neither counts nor resets; B1 `NO_NODE` covers this case. State that in C4 and goal 5.
   - If a non-OSError escapes, the step discards its state; B1 `[D8]` pages WATCH_FAILED. Note this, or add a test.
5. **[LOW] R1 and T15 wording.** After a restart, the anchor is the adopted child's expiry, which is ≤ the true anchor and therefore safe. A hand-launched child with a full TTL would widen it; note that.
6. **[LOW] T16c brittleness.** Pin the scenario to `NO_FRESH_ACTIVITY` with a valid permit. Assert only on `TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED` payloads.
7. **[LOW] The bound of ≤ 8 CRITICALs.** State its assumptions: deferral must be consecutive; a raising sink retries every poll; terminal flapping resets the count. Add a minimum gap, or a comment.
8. **[LOW] Implementer brief.** The brief must carry the merge-blocking SM3 re-measurement verbatim.
