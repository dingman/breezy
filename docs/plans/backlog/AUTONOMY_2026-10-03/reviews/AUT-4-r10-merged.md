# AUT-4 r10: merged blind review (2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| prediction-market-reviewer | 95 | 0 |
| mle-reviewer | 94 | 0 |

The lower score is 94, so the plan goes to r11 with targeted edits.

**Verified by both reviewers**
- FH1/W5 is real: there is a mid-run exec load at `strategy.py:308`.
- The W5 move is safe. No test patches the moved name.
- The R-1 function-local import is behaviour-neutral.

**Agreed by both reviewers**
- **I-5 = (a).** Accept `safety`, `credentials` and `secure` as a named run-time set. `E7B_EVAL_OFFLINE_DEFERRED_PERMIT_TTL` is an exact set and carries stack attribution.
- **ER-1: ADOPT.**
- **ER-2: ADOPT.**

## Owed in r11

1. **[MED, MLE] Blocker exit path.** A `SystemExit` raised inside an `atexit` handler does not change the exit code. Fix:
   - Run `assert_clean_or_exit()` *before* output is written, and gate the output write on an empty record.
   - Where a hard exit is needed, use `os._exit(EXIT_INTEGRITY)`.
   - `::test_blocker_fails_closed_when_import_error_is_swallowed` asserts both the non-zero exit code and that no output file exists.
2. **[LOW, MLE] Out-of-scope note.** State that `importlib.reload` is out of scope. The pre-install `sys.modules` check covers modules that are already imported.
3. **[LOW, MLE] I-5 stack attribution.** Assert "the loader frame lies within module `nbp_shadow_parity_pure`", not an exact frame depth.
4. **[LOW, PM] Blocker install scope.** Add a test that no `LIVE_ENTRIES` module installs or references the `sys.meta_path` blocker.
5. **[LOW, PM] W5 identity.** Add a structural test that `strategy._d1_candidate_ids` resolves to the same function object as `composition._d_plus_1_climate_days`.
6. **[LOW, MLE] Malformed-size test.** Make sure the malformed `--size` fail-closed test (ER-1) is named.
