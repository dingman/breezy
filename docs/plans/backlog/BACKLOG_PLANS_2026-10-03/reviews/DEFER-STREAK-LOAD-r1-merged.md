# DEFER-STREAK-LOAD r1: merged review (coordinator)

Scores: python-reviewer 91, silent-failure-hunter 90 (one HIGH). The final score is 90, so the plan goes to r2.

## Items

**HIGH**
- **D1 [sfh HIGH]:** S2's delivered alert is **mandatory** and ships in the same change as S1.
  - Merge the two slices.
  - Remove the rollback option "S1 can stay if only S2 is reverted".
  - Make the alert fire on any reset where work is pending.

**MEDIUM**
- **D2 [both reviewers]:** add an `IO_ERROR`/`UNREADABLE` reason for `OSError` on load. Handle a `save_state` failure as well. Neither may crash-loop. Add tests for both.
- **D3 [sfh]:** tie the reset alert condition to the same `pending` boolean that is passed to `step`. Define it exactly.
- **D4 [both reviewers]:** prove the alert path.
  - Add a notifier-mapping test showing that exit 4 reaches `breezy-study-failed@%n` and that the notifier output contains `DEFERRAL_STREAK_RESET`, so the operator sees the reset rather than "stalled".
  - Cite the 09-20 alert-delivery fix.
- **D5 [python]:** quote the EDGE-6 6f ruling and justify the T10 amendment, which changes the expected exit from 0 to 4.

**LOW**
- Note the type rule for `0`, `""` and `false`.
- Name the local `_require_*` helpers.
- T11 asserts that `runs_since_alert` is unchanged.
- File the future-dated timestamp as a PROGRESS row candidate. List it in §8; do not edit PROGRESS.
