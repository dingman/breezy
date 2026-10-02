# Refactoring Plan Rev 2.1: execution log, 2026-10-02 (overnight)

Coordinator: Claude main session, working in the worktree `emdash-refactor-y4qj4` on branch `emdash/refactor-y4qj4`, rebased onto live `99067d4a`. The plan is `REFACTORING_PLAN_Rev2.1_2026-10-01.md`.

**Delegation route.**
1. Grok ran first, until it hit 402 (exhausted) at about 04:15Z.
2. Codex ran second, until its usage limit at about 04:00Z (resets 07:49Z).
3. Claude specialist agents took over after that. The trigger is reported per item below.

**Gate.** Every gate ran through `scripts/ci/run_tests_no_egress.sh` in a detached gate worktree, with `PYTHONPATH=<wt>/src` and the primary interpreter.

## Step status

| Step | Commit (integration) | Implementer | Verification | Status |
|---|---|---|---|---|
| R0.2 docs drift | `757deaa8` | Codex | claims fact-checked against src/host (drop-in names, seed path, gaps caller) | DONE |
| R0.A tier infra + contract marks + KillMode pin + private-import tripwire | `ce87fe21` | Grok | `-m contract` 277 → 326; every pin shown red | DONE |
| R0.5 CT-1, CT-12 | `f95d287f` (+ strengthening `7665c6d7`) | Grok, then Claude tdd-guide | red on the named mutations. An independent Grok review rated CT-12 WEAK (the exec-client `submit_veto` and `try_submit` were not exercised); fixed in `7665c6d7` | DONE |
| R0.5 CT-2, CT-8, CT-13 | `19d81fd3` (+ `7665c6d7`) | Grok, then Claude | red on the named mutations; 412 supervisor tests green | DONE |
| R0.5 CT-4, CT-7 | `298f0022` (+ `7665c6d7`) | Grok, then Claude | red on the named mutations | DONE |
| R0.8 speedups | `d1eeed09` | Grok | exit-window file −260 s; census −107 s (the plan's −200 s assumed the second pass could go; it is kept by design) | DONE |
| R0.9 heavy marks | `fcd78e54` | Grok | allowlist red; T1 run under 3 seeds at 12.0–12.8 min (target ≤ 10 min **not met**) | DONE (target missed) |
| R1.4 filesystem probe split | `c5c9b26f` | Grok | `catalog.py` 1,202 → 961; catalog taxonomy contract widened to both modules (fixup), red shown | DONE |
| R1.5 health types below ingest | — | Grok (branch `refactor/r15`, not merged) | **DROPPED** under the plan's own clause. `nws_actor` also needs `emit_alert`, `resolve_alert_sink` and `write_snapshot_atomic`, so the payoff would move the HTTP webhook alert sink into `registry` and re-point four safety-scan tests. That is too much safety-surface churn for one debt row | DROPPED |
| R1.6 `quote_tape_gaps` → runtime | `5a6a5cfc` | Codex | debt rows 4 → 3 (`lint-imports` 7 kept); `structural_dead_stop` old-vs-new output byte-identical on `pm_us_crh_v2` and `pm_us_crh_fq_v1` | DONE |
| R2.1 boundary-solver parity pin | `6e252b86` | Codex | red shown; parity holds within 1e-6 on the registered artefacts (no drift found on registered parameters) | DONE |
| R2.3 tape-instrument seam | `46ccba7d` | Codex | AST-identical moved definitions (reviewer); `whole_tape_paper_replay` dry-run output identical; census old-vs-new: see below | DONE |
| R2.2 PREREG admission → `breezy.analysis` | `89dc3ef1` + `a8165cfe` | Codex (stopped on quota; WIP edited the ruling-frozen `live_family_tally.py`, discarded), Grok (402 mid-task), then Claude tdd-guide | Claude found and restored a dropped `mode=ro`; AST-identical; trading-bot-architect **APPROVE**; `_TAKEN_REASON` single-sourced | DONE |
| R3.3 quote-tape ingest split | `77170029` | Codex (rejected: the core imported the CLI back), then Grok redo | no core → cli import (AST pin); 10 retargeted monkeypatches red when pointed back; CLI 2,441 → 547 lines | DONE |
| R3.6 `nws_actor` health extraction | — | — | **DEFERRED**: depends on R1.5. Without R1.5 an ingest sibling module would add a second runtime-health debt row | DEFERRED |
| R3.1, R3.2a/b, R3.4 | — | — | **HELD** by plan §3.0: requires the FQ live proof plus one clean trading day (FQ d0 is today) | HELD |
| R3.5, Appendix A (R1.2), BC-* | — | — | out of scope by plan (deferred / conditional / need rulings) | — |

## Gates (full suite, MEASURED)

| Tip | Steps | Result | Wall |
|---|---|---|---|
| `fdd98b99` | 6 | 3 failed (pins reacting to moves); fixed by fixups | 25m19s |
| `b21cd6ac` | 9 | 1 failed (entry-point pin); fixed | 18m43s |
| `298f0022` | 9 | GATE_EXIT=0, 14,962 passed | 20m18s |
| `77170029` | 13 | GATE_EXIT=0, 14,972 passed | 19m18s |
| `7665c6d7` | 17 | GATE_EXIT=0, 14,978 passed | 18m04s |

Baseline was 25m03s (S6). The plan projected ~17.3 min after R0.8.

## Findings surfaced (not fixed; tracked in PROGRESS)
- `python -m importlinter.cli lint-imports` is a **no-op**. Some implementers' "lint green" claims used it. The coordinator re-ran the real console script: 7 kept, 0 broken.
- `test_mypy_ratchet.py` failed under `FORCE_COLOR=1`. Fixed in `8f6575c5`, which runs mypy with colour disabled.
- `ContinuousRungHoldStrategy subscribed` in the supervisor's `COMPOSITION_KIND_SUBSCRIBED_MARKERS` is emitted by no source (the subclass inherits the parent's line). It looks like a dead marker. Not pinned or changed (R3.2/R3.4 scope).
- `scripts/analysis/tape_instruments.py` relies on the scripts-dir `sys.path` convention, so it is on `STAGE0_EXCLUDED_ENTRY_MODULES`. Its runtime import is covered through the runner.
