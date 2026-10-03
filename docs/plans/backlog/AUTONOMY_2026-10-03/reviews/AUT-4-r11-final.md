# AUT-4 r11: FINAL (APPROVED 2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| prediction-market-reviewer | 95 | 0 |
| mle-reviewer | 96 | 0 |

**Status.** Plan `AUT-4-evaluation_plan_r11.md` is **READY** and supersedes r6.

**Errata.** AUT-4 ER-1 and ER-2 are ADOPTED as **E-13** in `ARCH-ERRATA-rev9_2.md`.

**I-5 is accepted under option (a).** `safety`, `credentials` and `secure` form a named run-time set. `E7B_EVAL_OFFLINE_DEFERRED_PERMIT_TTL` is an exact set, with module-level stack attribution.

## Binding build items

Brief these together with the plan, `reviews/AUT-4-r6-final.md` (where it is not superseded), and the errata.

1. **Before `os._exit`.** Write and fsync the run-record failure line before calling `os._exit(EXIT_INTEGRITY)`, so the run record names the child. `os._exit` skips `finally` blocks and buffered writers.
2. **Plan text cleanup.** Delete the dangling "r10 self-score (historical)" heading, and reconcile the self-score note so it reads as conservative, not as a downgrade.
3. **`test_systemexit_in_atexit_does_not_set_exit_code`.** Its failure message must read: "interpreter behaviour changed — re-review the blocker design, not a regression".
4. **Live path.** The W1–W5 live-path edits follow §3.9b in full:
   - sha pins and a whole-diff allowlist;
   - a fresh-process boot smoke against the deployed tree;
   - eager resolution;
   - a supervisor restart in 01:00–16:40Z, plus the scripted permit-line check;
   - an immediate tree-only revert path.
