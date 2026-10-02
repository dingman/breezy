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
| R3.6 `nws_actor` health extraction | `62778b4a` (live) | Claude tdd-guide | done on day 2 after R1.5b (see Day 2 evening) | DONE |
| R3.1, R3.2a/b, R3.4 | `6e99a7ae` (live) | Claude tdd-guide | hold lifted by the operator; see Day 2 evening | DONE (R3.2 loads at the 01:00Z supervisor restart) |
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

## Day 2 evening (2026-10-02, 17:00–20:10Z): holds lifted, Part 3 executed

The operator overrode the plan's §3.0 hold ("do it now. there is no reason to wait.") and later set a standing rule: activate merged code immediately unless there is a concrete technical reason not to.

| Live tip | What | Gate | Activation |
|---|---|---|---|
| `806a8942` | EMIT-HEALTH-CRITICAL (3 consecutive `_emit_health` failures → one bounded off-loop CRITICAL) | green | nws-ingest restart 19:03Z: all actors RUNNING, snapshots refreshed with identical key sets, 0 failure lines |
| `62778b4a` | **R3.6**: `ingest/nws_health.py` takes over `emit_health`, `alert_conditions` and `_emit_all`; thin delegators remain on the actor (2,524 → 2,184 lines) | 1 failed (CT-13, flaky: does not import the diff, passes 3/3 alone; logged as CT13-FLAKE), 14,454 passed | nws-ingest restart 19:35Z: the 5 snapshots refreshed with identical key sets and schema, 0 failure lines, NRestarts 0 |
| `6e99a7ae` | **R3.1** (`trade.run` halt-latch preamble plus typed per-kind builders; boot logs byte-identical in 6 scenarios; SL-13p2 parity 0/720,597), **R3.2a/b** (supervisor decisions moved into pure core functions plus 71 tests; shells thinned), **R3.4** (`continuous_helpers.py` and `continuous_no_side.py`; moved definitions AST-identical; flag-retarget proven red by mutation; operator-controls importer pin widened with a declaration) | one combined gate on the exact tip: 14,526 passed, 17m50s | Node hand-relaunched 20:05Z (`relaunch_node.py` mirrors `_do_midday_watch`: env copied from the supervisor, A-1 permit ceiling, open-intent probe after stop). All 4 boot lines present; permit within ceiling; supervisor `permit_watch_adopted_live_node` at 20:05:55Z. The **supervisor restart for R3.2 waits for 01:00Z**: `next_due` dispatches MIDDAY_WATCH only when `launch_done and readiness_observed`, and a mid-session restart resets both |

**Reviews.** R3.1: APPROVE, follow-up applied (typed dispatch, proven by a mypy mutation). R3.2: APPROVE. R3.4: APPROVE. All by trading-bot-architect, independent of the implementers (Claude tdd-guide agents; Grok was at 402).

**Defect found during activation (not caused by the refactor): AMBIG-LATCH-CLEAR.**
1. At 16:50Z an FQ IOC miss (MDW) latched the exec client's in-memory AMBIGUOUS refusal.
2. At 16:52:54Z the resolver retired the durable intent as a terminal zero-fill but never cleared `_trading_refusals`.
3. The node refused every take until the 20:05Z relaunch; one take was denied, at 17:38Z.

The fix is tracked in PROGRESS.

## Close-out (2026-10-02, 20:15–22:10Z)
- **AMBIG-LATCH-CLEAR, merged `3eb4a108`.**
  - The resolver's terminal zero-fill retirement now clears the AMBIGUOUS refusal. It does so only as the last step, after retire, true-up and permit restore succeed.
  - The exec-client sha pin was re-pinned after reviewer approval.
  - Reviews: prediction-market-reviewer APPROVE; silent-failure-hunter found 2 MEDIUM issues, both applied.
  - Gate: 14,534 passed. Live via a node relaunch at 20:55Z.
  - DEGRADED-resume is a follow-up. Calling it from the resolver would widen E0-NOSEND-RESOLVER.
- **CRH-MIXIN-TYPES, merged `d8e8fd92`.**
  - `NoSideShadowMixin` methods now type `self` against the `_NoSideHost` Protocol. A typo mutation is caught as `attr-defined`, and the method bodies are AST-identical.
  - Gate: 14,534 passed.
  - It is typing-only (no runtime behaviour change), so it was not restarted and loads at the next spawn.
- **CT13-FLAKE.** 0/100 reproductions under capped load. It is moved to a watch item, with the hypothesis recorded in PROGRESS.
- **R3.2 activated.** The supervisor was restarted at 22:07:32Z, moved up from 01:00Z after an impact assessment.
  - The cost was losing MIDDAY_WATCH auto-relaunch until 01:00Z. `next_due` gates it on `launch_done and readiness_observed`. The permit watch still runs, so a dead node is still detected.
  - That cost was covered by a coordinator node-liveness watch (hand relaunch with the A-1 ceiling) until 01:00Z.
  - The node pid is unchanged (1223483). `permit_watch_adopted_live_node` appeared at 22:07:33Z, and no alert followed.
- **Plan status: COMPLETE.** Every Rev 2.1 step is merged and loaded in its consumer, except the explicit drops and deferrals (R1.5 → R1.5b, Appendix A dropped with BC-4, and R3.5 / conditional items out of scope by plan).
