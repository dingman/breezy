# AUT-4 r9: merged blind review (2026-10-03)

| Reviewer | Score | Verdict |
|---|---|---|
| prediction-market-reviewer | 91 | NOT READY (3 MED) |
| mle-reviewer | 86 | NOT READY (1 HIGH) |

## Verified sound

- All 10 sha pins match HEAD.
- W1–W4 edit no permit, exec, safety or `operator_controls` file.
- W4 is safe because of `from __future__ import annotations`.
- The existing AST barriers are not tripped.
- The Arrow allowance is sound (both reviewers agree): Nautilus fails loudly on an unregistered type.
- No invariant is violated.

## Coordinator rulings

- **R-1 (safety out of the closure).** Both reviewers raised this. Make `nbp_shadow_parity_pure.py:43`'s `PERMIT_TTL_NS` import function-local. Re-measure, and drop `safety`, `credentials` and `secure` from the named exception. The golden replay covers the edit. Do not re-declare the constant. Fix the "moved byte-identically" wording, because only the import moves.
- **R-2 (ER-1 conflict).** PM said ADOPT and MLE said AMEND. Ruling: the shared wrapper applies a **default** tmpfs cap to any row with no per-row `--size`, so other plans' rows never break. AUT-4 rows carry explicit per-row values. Fail-closed applies only to a malformed value. Restate ER-1 with that text.
- **R-3 (ER-2).** AMEND, combining both reviews. The waiver is scoped to the eval-offline row only. It requires the WP1 measurement and the (b) guard tests to be green. It never reaches `order_enablement` or `exec*`. It does not waive (b)'s "needs" condition.

## Owed in r10

- **FH1 [HIGH, MLE]: the closure guard only sees import time.** `plan:655` snapshots `sys.modules` after the entry import only. The `_LAZY` maps and function-local imports can load `http`/`exec`/`write_transport` mid-run. Required:
  - (a) Re-snapshot after the golden replay and after a `replay_daily_runner` smoke run.
  - (b) Add a `sys.meta_path` blocker in the eval-offline entry and in the test. It rejects `exec*`, `factories`, `http`, `websocket`, `transport`, `write_transport` and `order_enablement`.
- **FM1 [PM]: revert path.** The first post-restart boot is about 16:50Z, outside the window. Allow an immediate tree-only `git revert`, because the node reads source at spawn. Only the supervisor restart waits for 01:00–16:40Z. Run the boot smoke against the real deployed tree before the restart.
- **FM2 [PM]: W3 structural test.** Assert the exact import delta, i.e. the set of removed names that ruff F401 forces. Assert that `strategy.py:65` keeps the module-level name `bucket_station_instrument_ids`, because `test_d1_cache_union.py:300,330` patches it. Correct the claim "no test patches moved names".
- **FM3 [PM]: whole-diff allowlist.** Require `git diff --name-only <base> HEAD` ⊆ {W1–W4 files, new tests, fixtures, `permit_line_check.py`}. This covers the unpinned `fees.py`, `parsing.py` and `exec/refusals|reports|no_side_keys.py`.
- **FM4 [MLE]: cold-import order.** Add a fresh-process, first-import test for every module under both lazy packages and for `instrument_buckets`.
- **FM5 [MLE]: golden replay breadth.** Add a golden over a clean real-tape slice through `backtest_harness`, covering catalog decode and the `BacktestEngine` fee path. SFO 09-01 is the known clean slice.
- **FL1.**
  - Add the new eval-offline and fs_replay entries to `STAGE0_ENTRY_MODULES`, and assert that every `register_arrow` type referenced in their closure is registered.
  - Extend the Arrow-loss reference test to cover string literals and `data_cls`.
  - Add a golden-catalog smoke run of the 8 offline scripts.

## Approval bar

Both reviewers ≥95 and zero CRIT/HIGH.
