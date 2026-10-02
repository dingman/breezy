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
- ~~SUB-MARKER-DEAD~~: struck on day 2 (the claim was wrong; see below).
- `scripts/analysis/tape_instruments.py` relies on the scripts-dir `sys.path` convention, so it is on `STAGE0_EXCLUDED_ENTRY_MODULES`. Its runtime import is covered through the runner.

## Day 2 (2026-10-02, 14:00–17:00Z): open items worked

Merged to live, in order, each with a pre-merge full gate on the exact tip and a fast-forward-only merge:

| Live tip | What | Gate |
|---|---|---|
| `e0c89f23` | **Family-tally FQ skip.** Pre-existing defect: since b58bb4c8, score-live-trials skips for a `forecast_quantile_ladder` sender, so the v2/v4 tallies failed daily at 17:20Z with OnFailure alerts. The wrapper now skips by design (red shown) | 14,982 passed |
| `d6914fca` | **R1.5b**, the redesigned R1.5. Pure types move to `registry/health_model.py`. All egress stays in `runtime.health`. The actor gets the health module injected as a `HealthIO` Protocol, with a fail-closed boot guard (`health_io`, `alert_sink`). The debt row is paid. Zero safety-scan edits. Planner: code-architect. Reviews: architect and security, both APPROVE-WITH-CHANGES, changes applied | 15,015 passed |
| `d26ef211` | **BC-5** (`features/` removed); **BC-3 C2** (`strike_ladder` re-hosted as `tests/support/multi_strike_ladder_strategy.py`); **BC-4** (NBS chain + `archive_records` removed; `archived_selection` kept as PARKED; WP12 egress scan re-homed; IEM host is now a pure ban) | 14,939 passed |
| `a15fefd2` | **BC-3 C3a/C3b/C4**: runner deleted, lib trimmed, 5 shells + `forecast_edge` + `resting_ladder` + 3 `weather_common` modules removed. **T1 speedups**: heavy re-marks, waits removed, `run_tier.sh --lanes N` with an exact-partition proof | 14,443 passed, 17m03s |

**BC plan.** Planner, then trading-bot-architect review (APPROVE-WITH-CHANGES, B1 and M1–M6 applied). Citation anchor: tag `bc3-pre-removal-2026-10-02` → 763527b6 (pushed).

**C3a timer proof (B1).** It is satisfied by construction:
- the consumer scripts are byte-unchanged;
- `tape_instruments` changed only in its docstring;
- every surviving lib definition is AST-identical;
- no code references a removed name;
- all 5 consumers import cleanly.

A census rerun was judged redundant. Replay-daily and score-live-trials skip by design while FQ sends.

**Stale bytecode in the primary tree.** After the merges, five orphan strategy directories (importable namespace packages) and the removed modules' `.pyc` files were deleted (review M6).

**T1:** 12m16s → **9m34s serial / 6m32s with 3 lanes** (target ≤ 10 min met).

**Struck.** SUB-MARKER-DEAD was wrong. `ContinuousRungHoldStrategy` is not a subclass and emits its own marker (`continuous_strategy.py:875`), which is seen in the 09-20 node log. The only unemitted row, `forecast_ladder`, is intentionally pre-wired.

**Dropped by plan clause.** Appendix A (R1.2) was dropped when BC-4 removed `nbm_forecast_actor`.

**Deferred.** The nws-ingest restart that loads R1.5b waits until after FQ d0. The restart would deploy 37 files of changes made since 09-28.

**Tooling traps recorded.**
- `python -m importlinter.cli` is a no-op.
- `lint-imports` reads `pyproject.toml` from the current directory.
