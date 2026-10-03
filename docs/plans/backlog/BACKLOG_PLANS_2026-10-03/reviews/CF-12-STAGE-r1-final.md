# CF-12-STAGE r1: FINAL (APPROVED 2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| python-reviewer | 96 | 0 |
| code-reviewer | 95 | 0 |

**Status.** Plan `CF-12-STAGE_plan_r1.md` is **READY**.

**Order.** It lands before CF-12-W3. W3 is re-planned as r4 because of the phantom-error finding.

**Verified by both reviewers:**
- The branch is 136 commits behind and 5 ahead of HEAD.
- There is exactly one conflict, in `tests/unit/test_mypy_ratchet.py`.
- The 185-ignore set matches HEAD exactly.
- The new ceilings are 3 / 352 / 7 / 1288.
- The ratchet edit only adds checks.
- Rollback is sound.

## Binding build items

1. **No Post-STAGE note in the approved W3 review file.** Do not append it to `reviews/CF-12-W3-r3-final.md`. W3 r4 carries the dependency instead. The plan directory is committed by the coordinator before the build, so the worktree contains it.
2. **Rebase path (step 6.2).** If an unused ignore appears in between, re-measure and re-pin the ceiling to the measured N. Record the drift in the commit body. Never leave it in place so that the gate fails.
3. **Rollback after W3 lands.** Both plans edit `CEILINGS`, so a `git revert` of STAGE will conflict. In that case the rollback is a manual re-pin, with a full gate run.
4. **Step 1.4 positive control.**
   - Stage 0 confirms that the control produces mypy exit 2.
   - Run `git diff --stat` immediately before commit A, so the temporary `mypy_path` edit is never committed.
5. **`PYTHONPATH` on every mypy run.** Any mypy run outside the primary tree sets `PYTHONPATH=<tree>/src`. Without it, `breezy.pth` resolves to the primary `src` and adds 6 phantom `trade.py` errors.
6. **(Added after the W3 r4 review.)** STAGE step 7's Post-STAGE note is withdrawn. The authoritative W3 bounds are in `CF-12-W3_plan_r4.md` §4.1, where `tests/unit` is 1271, not [1249, 1266]. STAGE's own ceilings, 3/352/7/1288, are confirmed.
