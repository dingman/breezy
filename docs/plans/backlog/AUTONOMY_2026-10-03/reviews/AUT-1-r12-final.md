# AUT-1 r12: FINAL (APPROVED 2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| trading-bot-architect | 97 | 0 |
| silent-failure-hunter | 96 | 0 |

- Plan `AUT-1-data-capture_plan_r12.md` is **READY**. It supersedes r8 as the AUT-1 build plan and covers AUT-1a and AUT-1b. It is native-first, per `reviews/AUT-1-native-pressure-test.md`.
- Errata: ER-1..ER-10 are ADOPTED as **E-12** in `ARCH-ERRATA-rev9_2.md`.

## Binding build items

Brief these together with the plan, `reviews/AUT-1-r8-final.md` (where it is not superseded), the X-1..X-7 rulings in `reviews/AUT-6-r14-merged.md`, and the errata.

1. **Re-run V-23 on the merge tree in WP0.** ING-2 is changing the ingest units, and V-23 must confirm that no unit moves or deletes `live/<instance_id>`.
2. **Accepted residual: the first table write coincides with the 00:00Z rotation.** That write is counted as a drop. This fails closed: it refuses only a Take, never an exit.
3. **Cross-plan.** The recorder-side deliverables are checked by AUT-6 r15 WP4 tests:
   - `OnFailure=`;
   - `READY=1` once connected and subscribed;
   - `Type=notify`;
   - `NotifyAccess=all`;
   - the `RECORDER_WATCHDOG_DEFERRED` journal line (post-READY only);
   - the stop hook (evidence only).

   The rotate bound and the max start derive from `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS`.
4. **Option B (an actor-owned native `StreamingFeatherWriter`) is the shipped mechanism.** Option A is dropped.
