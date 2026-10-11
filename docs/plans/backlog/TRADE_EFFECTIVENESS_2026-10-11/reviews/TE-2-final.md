# TE-2 convergence record: READY (2026-10-11)

**Final plan:** `TE-2_plan_r3_2.md`. It is r3.1 with two coordinator statistical-correction passes.

## Score trajectory

| Round | Domain (stats) | Python | Architecture | Codex |
|---|---|---|---|---|
| r1 | 68 RWC | 66 NOT-READY | 60 NOT-READY | 74 NOT-READY |
| r2 | 78 RWC | 82 RWC | 76 NOT-READY | 86 NOT-READY |
| r3 | 88 READY | 90 READY | 89 NOT-READY (pin BLOCKER) | 92 RWC |
| r3.1 | 82 RWC (2 HIGH: T-SPREAD direction, T-LOC collapse) | — | **94 READY** | — |
| r3.2 | **91 READY** | — | — | — |

Every r3.2 confirmation finding (D1–D4) was applied. No BLOCKER or HIGH finding is open.

## What the loop caught (each was a real defect)

- **Wrong premises:**
  - a holdout premise that was wrong;
  - a coverage-gap STOP guaranteed to fail;
  - a ladder partition that could not be recovered from same-`now_ns` lines;
  - a Take join that is not keyed by `client_order_id`.
- **Inputs not available:**
  - the boot logs carry no commit sha;
  - committer-time pinning is unsound for rebased branches (`4ac87414`).
- **Scope and wrong figures:**
  - 5 out-of-scope fills, left behind by the failed 10-05 halt;
  - the band-semantics correction (2/25 wins, not 0/25).
- **Statistical design:**
  - a verdict space that was forced before any data was seen, now handled by NOT-TESTABLE and min-p;
  - an anti-conservative T-SPREAD null;
  - an unproven T-LOC collapse, now relabelled indicative.

## Evidence captured

`docs/evidence/te2/REFLOG_SNAPSHOT_2026-10-01_to_10-06.txt` was captured before the reflog expires.

## Next

Build per the plan:
- **WP0:** RED tests via Codex.
- **WP1:** Phase A, run by the coordinator.
- **WP2:** freeze plus peer review.
- **WP3:** Phase B.

Soft target 2026-10-20.
