# TE-1 convergence record: READY (2026-10-11)

**Final plan:** `TE-1_plan_r3_3.md`. It is r3.2 with the three text-sized final-confirmation findings applied.

## Score trajectory

| Round | Domain | Python | Architecture | Codex |
|---|---|---|---|---|
| r1 | 74 NOT-READY | 72 RWC | 78 RWC | 58 NOT-READY |
| r2 | 86 RWC | 78 RWC | 81 RWC | 78 NOT-READY (band correction) |
| r3 | 93 READY | 86 RWC (2 HIGH) | 90 READY | 88 NOT-READY (1 BLOCKER) |
| r3.1 | — | 92 RWC (1 MED) | — | no verdict (usage limit) |
| r3.2 | — | **93 RWC, final adversarial confirm** (2 MED, 1 LOW, no BLOCKER/HIGH) | — | — |

**Fallback stated:**
- The r3.1/r3.2 adversarial confirmation was run by a Claude `python-reviewer` instead of Codex.
- Trigger: Codex usage limit (resets around 19:06). Grok was 402 at the same time.

**Last findings, all applied in r3.3, no code risk:**
- the S0-9 `breezy-autonomy-failed@` scope;
- `test_autonomy_pins.py:747,764` named;
- a note on WP-D gate ordering.

The coordinator verified both MED findings against the code before applying them. No BLOCKER or HIGH finding is open.

## What the loop caught

- **Band semantics (P19).** The coordinator's audit re-score treated the bands as half-open. The correct result is 4 wins / −2.63, recorded in `CORRECTION_2026-10-11_band_semantics.md`.
- **Where the accounting predicate lives.** `accounting_rows` cannot live in `persistence`. It is now a static predicate in `breezy.analysis.labeling.accounting`.
- **Shared closure re-pin.** The `aut6.health` and `aut2.label` producers share a closure, so a change to either re-pins both, and rollback carries both re-pins.
- **Test widenings:**
  - `not_wired` becomes a renamed fail-closed test (`producer_unpinned`), never a deletion.
  - The schema-widening rows are listed explicitly.
- **Dropped guard.** The import-linter contract was vacuous and is dropped. The AST guard over `src/` and `scripts/` is the only guard.
- **Pre-build search patterns (S0-9).** False positives were removed: `== 4` is now `== 4(?![0-9])` and `not_wired` is now `\bnot_wired\b`.
- **`UnitFactory` contract.** The factory stays `factory(args) -> UnitWiring`, called through one `_resolve_factory` helper.

## Goal state (acceptance)

`portfolio_roi` self-reports every live fill:
- 34 fills / 4 wins / −2.63;
- FQ −2.17 / crh −0.46 / fees 0.27;
- `n_settlement_disagree=0`;
- `portfolio_roi` is no longer NO_INPUT;
- LAG_BACKLOG n=25.

## Next

Build in this order: WP-A → WP-B → WP-D → WP-C → WP-E.
- **Routing:** Grok → Codex → Claude tdd-guide.
- **Gate:** the coordinator runs `scripts/ci/run_tests_no_egress.sh` after every WP.
- **AUT-6 co-sign:** required on the `aut6.health` re-pins.

## Re-convergence after the Stage 0 STOP (2026-10-11 evening)
- Stage 0 STOP at S0-2 (5 FQ fills on 10-06 vs retroactive terminal 10-05; `te1/TE1_STAGE0_RECORD_2026-10-11.md`). S0-2b PASS.
- r3.4 (planner, Ruling R11 post-terminal straddle) → round 4: domain 80 RWC, python 84 RWC, architecture 88 RC → r3.5 merge → confirmations domain 90 RWC, python 86 RWC (same control-flow defect) → r3.6 coordinator text pass. Both confirmers: READY once r3.6 text applied. **READY r3.6.** Fallback: Claude reviewers (Grok 402; Codex not used for confirmation).
- Binding stack: r3.3 + r3.4 + r3.5 + r3.6.
