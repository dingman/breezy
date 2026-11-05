# CF-12-W3 r4: FINAL (APPROVED 2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| python-reviewer | 96 | 0 |
| code-reviewer | 96 | 0 |

**Plan:** `CF-12-W3_plan_r4.md` is **READY**. It supersedes r3.

**Ordering:** it lands after CF-12-STAGE r1. The Stage 0 precondition gates this ordering.

**Re-measurement:** the python-reviewer reproduced S-T2 exactly, with `PYTHONPATH` set. The counts are 152 / 3 / 11 / 5 / 1271. `src/breezy/app` is 0, which confirms the earlier `app: 6` count was phantom, so it is dropped. STAGE's ceiling of 1288 is correct.

## Binding build items

1. **Tighten the Stage 0 bands to ±2 on every group.** Expect exact equality with the measured values, and record and explain any deviation. If the ceilings differ from 3/352/7/1288, re-derive the bounds rather than relying on the band.
2. **§4.1:** describe `replay_sufficiency_census.py:88` as a swap (one `import-not-found` becomes one `attr-defined`), not as an ignore becoming needed.
3. **Name the STAGE commit B in the brief** for the `git merge-base --is-ancestor` check.
4. **Every mypy run sets `PYTHONPATH=<tree>/src`.** Any `src/breezy/app` error is a STOP.
