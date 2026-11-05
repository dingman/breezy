# CF-12-W3e: typing slice for call sites W3 makes visible, plan r1 (2026-10-09)

- **Backlog row:** `docs/core/PROGRESS.md:91` (CF-12-W3e, "NEEDS PLAN").
- **Parent:** `docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md`. **Trigger:** W3 r5.1 amendment A4, after the Stage 0 STOP on 10-09 (tests/unit FIN 1308 > 1288).
- **Status:** DRAFT r1, for peer review (python-reviewer and code-reviewer).
- **Measurement basis.** Code at HEAD `99018be9` is identical to `316b50c4` for `src`, `scripts`, `tests` and `pyproject.toml` (`git diff --stat` is empty).
  - Every number below was measured with the W3 plan's header mypy command, using `PYTHONPATH=<tree>/src` and a private cache under `/home/jon/.cache/breezy-agent/w3e/`.
  - Scratch evidence lives in `/tmp/claude-1000/-home-jon-breezy/40ab7227-004e-45e9-9c06-f7e3674039ac/scratchpad/w3e/`:
    - `w3e_apply.py`: the reference edit script;
    - `normalize.sh`: the RUF022 sort step;
    - `w3e.diff`: 332 changed lines across 26 files;
    - mypy outputs `head_w3e_r{1,2}.out`, `fin_w3e_r{1,2}.out` and `fin_w3e_1.out`;
    - the Stage 0 inputs in `../cf12w3/`.
  - The scratch tree that confirmed the §5.3 `misc`-ignore removal (archive = 5) has been deleted; only its measured result is recorded here.

## §0 Problem and goal state

**Problem.** W3 makes 75 sibling-script modules resolvable. The call sites that used to be `Any` then become checked. At Stage 0, FIN measured:
- `tests/unit` 1308 against a ceiling of 1288 (STOP);
- `scripts/analysis` 193 against 351, with the excess over projection unattributed.

FIN versus base gives these new error lines:

| Group | New lines | Not-explicitly-exported (`attr-defined`) | `name-defined` | Other |
|---|---|---|---|---|
| tests/unit | 134 | 67 | 11 | 56 |
| scripts/analysis | 78 | 67 | 0 | 11 |

**Root cause (one mechanism).** `strict = true` implies `no_implicit_reexport`. A name that module M only imports is not part of M's interface to mypy unless M lists it in `__all__` or imports it as `X as X`. The seams that W3 opens are almost all of this kind:
- tests and scripts reach `breezy.*` or sibling objects through a script that imported them (shims, re-export blocks, patch seams);
- tests reach stdlib modules through a script (`mod.os`).

The `name-defined` ×11 errors (`gs.LookRow` used in annotations) are the same thing: `LookRow` is not exported from the shim, so mypy cannot use it as a type. **None of these are runtime bugs.** Every name exists at runtime, and `test_moved_source_pinned.py::test_script_wrappers_delegate` already asserts by identity that the WRAPPERS names are the stats objects.

**Goal state (acceptance test).**
1. **Pre-W3 tree with W3e applied:**
   - mypy reports 0 new error lines versus HEAD;
   - `import-not-found` = 310 and `unused-ignore` = 0;
   - per-group counts are ≤ `CEILINGS`, and every group that drops is re-pinned. Measured: only tests/unit, 1288 → 1285.
2. **That tree with W3's `xform.py` applied (the FIN simulation):** every group is ≤ its current ceiling with margin. Measured: tests/unit 1176/1285; scripts/analysis 126/351; scripts/archive 7/8 (5/8 with the W3 §5.3 addition); scripts/venue 13/23; tests/contract 5/7; scripts/ops 3 (new key, ≤ 10 per W3 A1); scripts/collect 0; src/breezy/app 0.
3. **Runtime no-op.**
   - No test is added or deleted, and no assertion is weakened. Four sites gain an extra assertion (`is not None` / `isinstance`).
   - Script edits are `__all__` declarations, plus deletion of `# noqa: F401` comments that the declaration makes unused. No script import statement changes, and no script's import graph changes.
   - No module under `scripts/` is star-imported anywhere (grep-verified).
4. No byte under `src/`, `scripts/venue/`, `tests/contract/` or the exec client changes. No new test imports a `breezy.adapters.polymarket_us.exec` module.
5. `scripts/ci/run_tests_no_egress.sh` gives EXIT=0.

## §1 Option decision (key question)

| Option | Verdict | Evidence |
|---|---|---|
| **(A) W3e lands before W3. Verify on the pre-W3 tree for no-rise and runtime, and on the W3e + `xform` scratch for the FIN effect.** | **CHOSEN** | 1. A4 is BINDING: "open CF-12-W3e first … and stop".<br>2. Deterministic: `fin_1.out` == `fin_2.out`, `fin_w3e_r1` == `_r2`, `head_w3e_r1` == `_r2`.<br>3. **Order-independent:** applying xform on top of W3e gives a tree that `diff -rq` finds identical to applying W3e on top of FIN. So the scratch FIN *is* the post-W3 tree.<br>4. Pre-W3 neutral: 0 new lines, 3 genuine fixes already visible today.<br>5. Not one fix needed a bare sibling import that only resolves after W3, so A loses nothing to B. |
| (B) Fold into W3 as an extra stage | Rejected | W3 is a peer-reviewed, mechanical 83-file rewrite. Adding 26 judgement edits makes it harder to review. W3's rollback is already a manual re-pin (§8), and mixing in typing edits would make it worse. B also contradicts A4, and its only advantage (bare imports resolving) is unused (point 5 above). |
| (C) W3 lowers ceilings and pins the new errors without fixing them | Rejected | tests/unit FIN 1308 > 1288 is a ceiling rise, which A4 forbids. |

**Weakness of (A), and how it is handled.** On the pre-W3 tree mypy cannot show most of W3e's effect. So:
- RED→GREEN is recorded on the FIN scratch: `fin_1.out` is the RED; the FIN tree with W3e applied is the GREEN.
- The in-tree RED→GREEN is the ratchet re-pin (R1 below).
- W3's own Stage 0 re-measures everything and is the binding check.

## §2 Fix principle (decides every edit)

**Rule (b), default.** The consumer names the object at its defining module, and only when that changes no import graph:
- the defining module is `breezy.*`, the stdlib, or a sibling the file already imports;
- **and** the consumer keeps importing the intermediary.

Runtime is unchanged because it is the same `sys.modules` object.

**Rule (a).** The intermediary declares the binding in `__all__` when any of these holds:
1. it is a **declared re-export shim**: WRAPPERS in `test_moved_source_pinned.py`, a docstring, or a `# noqa: F401` re-export block;
2. a test **pins or patches the intermediary's binding**: an identity assert, or reading the original before `monkeypatch.setattr` on it;
3. Rule (b) would add a sibling-script import, which is `import-not-found` before W3 and therefore a ceiling rise;
4. Rule (b) would change a script's import graph.

Mechanics of Rule (a):
- `__all__` is the only mechanism. `X as X` fails `PLC0414` (useless-import-alias), and noqa is not allowed.
- mypy probe: with `__all__` defined, locally defined names left out of it stay accessible, so a partial list breaks nothing. Even so, a **new** `__all__` lists the module's own public names plus the re-exports, so it is an honest interface.
- `__all__` goes directly after the module's last top-level import. New lists are in RUF022 order. Existing lists get appended names without being re-sorted (`nbp_skill_study` is already unsorted at HEAD and stays so).
- Any `# noqa: F401` on a now-listed name becomes `RUF100` (unused-noqa) and is removed. This is a comment-only change.

**Rule (T).** Typing-only annotation or narrowing in test code:
- allowed: `Literal`, `Any` for pass-through `**kwargs` bags, `Callable[..., object]` for a deliberately mis-called function, `assert x is not None`, `assert isinstance(...)`;
- forbidden: `cast`, `# type: ignore`, and raising any ceiling.

## §3 Edit list (file by file; all located by text in `w3e_apply.py`)

### 3.1 Rule (a): `__all__` in scripts/analysis (10 files)

| File | Change | Trigger | Fixes (FIN) |
|---|---|---|---|
| `crh_group_sequential_boundaries.py` | New `__all__`: 14 own public names + the 14 WRAPPERS names. Drop the block `# noqa: F401`. | WRAPPERS | test_crh: 23 `attr-defined` + 11 `name-defined` |
| `forecast_conditional_scoring.py` | New `__all__`: `PointError`, `point_error_by_lead` + the whole scoring_core block. Drop the block noqa. | WRAPPERS | 41 lines in fcms, fc_report, hourly_ask_relative_edge, wp7b |
| `forecast_conditional_corpus.py` | New `__all__`: 45 own public names + 5 block names. Drop the block noqa. | WRAPPERS | 8 lines in fcms, fc_report |
| `score_live_trials.py` | New `__all__` (21 names): 9 own public names + the R2.2 block (`_TICK`, `FillExclusion`, `FillSourceUnreadableError`, `StorePositiveControlFailedError`, `_admit_fill`, `_admit_one_fill`, `compute_residual`, `read_filled_trials_state_db`) + `RESIDUAL_EXCLUSION_REASONS`, `TAKEN_FROM_FILL_WALK_REASON`, `_bucket_facts_from_instrument_id`, `_read_bucket_facts_by_instrument_id`. Drop 5 `# noqa: F401`. | Declared re-export (`:110-113`, WP-31 comment). Three scripts consume it, and Rule (b) would drop `family_tally_v2`'s only import of a module that imports the exec client, which changes its import graph. | 21 tests/unit + 11 scripts/analysis |
| `fill_time_count.py` | Append `_open_readonly`. Drop its noqa. | Docstring declares the shim | 3 scripts/analysis |
| `replay_daily_runner.py` | Append `argv_sha256`. | Identity pin `test_replay_daily_runner.py:1597` | 1 |
| `mb_current_rung_edge_study.py` | Append `wilson_interval`. | Patch seam (`test_archive_table_upper_bound…:146,181`); Rule (b) would add a sibling import | 2 |
| `k1_cheap_open_settlement.py` | Append `_read_arrow_table`. | Patch seam `test_k1…:679`; same reason | 1 |
| `current_rung_hold_paper_replay.py` | Append `_convert_live_capture`, `_select_capture_instruments`. | Rule (b) would remove census's only cprh import, which changes its graph | 3 scripts/analysis (incl. the r4 "swap" at `replay_sufficiency_census.py:88`) |
| `nbp_skill_study.py` | Append `load_frozen_0b_error_model`. | Script consumer `nbp_learning_nightly.py:454`; consumer stays untouched | 1 |

### 3.2 Rule (b): tests name the defining module (6 files)

| File | Change |
|---|---|
| `test_ambig_latch_phase_a_check.py` | `chk.subprocess` → `subprocess` (×3). Same module object; already imported. |
| `test_decisions_retention.py` | `mod.gzip` → `gzip`; `mod.os` → `os` (×4). Delete the now-unused local `import decisions_retention as mod` in the utime test (that is a ruff F401 fix). |
| `test_census_column_scan.py` | `census_module._convert_live_capture` → `_convert_live_capture`, added to the existing `from tape_instruments import` line. `census_module.default_registry` → `from breezy.registry import default_registry`, the same source census uses. |
| `test_replay_sufficiency_census.py` | `fcntl` → stdlib. `write_replay_sufficiency`, `staggered_last_full_scan`, `PreflightError`, `scan_depth_window`/`scan_quote_window` → their `breezy.*` homes (extending existing imports; one new `breezy.persistence.catalog_column_scan` import). The monkeypatched census bindings keep their string targets. |
| `test_current_rung_hold_exit_window_study.py` | `study_mod.read_scored_trials_pooled` → `breezy.persistence.scored_trial_store`. `study_mod.httpx` → `httpx`; reword the comment. `settlement.time` → `time` (add `import time`). |
| `test_no_side_first_order_pending_2026_09_14.py` | `FilledTrial` → `breezy.settlement.trial_scorer`. It keeps `from score_live_trials import _admit_fill`. |

### 3.3 Rule (T): typing-only edits in tests (11 files; each justified)

| File / site | Edit | Justification |
|---|---|---|
| `test_replay_daily_runner.py:1118-1156` | Return type becomes `Callable[[Sequence[str]], subprocess.CompletedProcess[str]]`; **delete `# type: ignore[return-value]`**. | **Real typing defect:** a wrong annotation hidden by an ignore. |
| `test_replay_daily_runner.py:1849,1959` | `lambda i=index: …` / `lambda root=day_root: …` → a nested `def work_dir(i: int = index) -> Path` and `def work_dir(root: Path = day_root) -> Path`. | mypy "Cannot infer type of lambda". Same default-argument capture. |
| `test_replay_daily_runner_batch.py:455` | Rename the spy parameter `path` → `family_manifest_path`. | The assignment must match the attribute's declared signature. |
| `test_replay_daily_runner_batch_wiring.py:319` | Add `assert isinstance(config_new, runner.RunConfig)`. | **Real defect:** `_config_for -> object`. Fixes 2 errors visible today plus 1 at FIN. Adds an assertion. |
| `test_current_rung_hold_exit_window_study.py` | `leg: Literal["YES","NO"]`. Payload narrowing via `last = payloads[-1]; assert last is not None` (×2) and `assert payload is not None` at `:603`. Spies use `**kwargs: Any` (×4). | Narrowing adds assertions. `:603` is visible today. Pass-through spies forward arbitrary keywords. |
| `test_current_rung_hold_resting_bid_study.py:79` | Module-level alias `_EventKind = Literal["depth", "obs"]` (mirrors `rbc.LegEvent.kind`); parameter typed with it. | Keeps the line within 100 characters, so no E501 or format drift. |
| `test_aud07_live_rule_crossing_sim.py:81` | `base: dict[str, Any]`. | A kwargs bag for a heterogeneous dataclass. |
| `test_aud07_m2_gate.py:22,108-117` | Import `Verdict`; annotate the four tuples `tuple[Verdict, ...]`; `tuple(["V"] * 16)` → `("V",) * 16`, which gives the same value. | Literal typing. |
| `test_archive_table_upper_bound_2026_09_14.py:148,183` | `**kwargs: float` (matches `wilson_interval(*, z: float)`). | Precise type. |
| `test_no_leg_mark_fidelity.py:229` | `assert row.fill_px is not None` and `assert row.derived_entry_px is not None` before the comparison. | Narrowing that adds assertions. |
| `test_k1_cheap_open_settlement.py:246-249` | `call_without_theta: Callable[..., object] = break_even_probability`, then call that inside `pytest.raises(TypeError)`. | The test deliberately mis-calls the function. This is a sound widening to a callable type, not a cast. The `pytest.raises(TypeError)` assertion is unchanged. |
| `test_k1_cheap_open_settlement.py:1308,1344-1348` | `k1.AskObservation = …` with `try/finally` → a `monkeypatch` fixture parameter and `monkeypatch.setattr(k1, "AskObservation", …)`. | "Cannot assign to a type." Restore moves from `finally` to fixture teardown; nothing after the call reads `k1.AskObservation`. |
| `test_census_column_scan.py:1226` | `kwdefaults = …__kwdefaults__; assert kwdefaults is not None`. | Same dict object; adds an assertion. |
| `test_nbp_window_available_at.py:83-87` | Remove the `dict[…, object]` local and pass `{}` to both calls; keep the comment. | Inferred from context. `build_version_rows` takes a `Mapping` (read-only by type). |

## §4 Measured results

| Group | CEILINGS today | HEAD + W3e (pre-W3) | FIN Stage 0 (`fin_1`) | **FIN + W3e** | Margin | With W3 §5.3 `misc` addition |
|---|---|---|---|---|---|---|
| src/breezy/analysis | 3 | 3 | 3 | 3 | 0 (untouched) | 3 |
| scripts/analysis | 351 | 351 | 193 | **126** | 225 | 126 |
| scripts/archive | 8 | 8 | 7 | **7** | 1 | **5** (3) |
| scripts/venue | 23 | 23 | 13 | 13 | 10 | 13 |
| tests/contract | 7 | 7 | 5 | 5 | 2 | 5 |
| tests/integration / strategy / support | 1 / 6 / 2 | same | same | same | 0 (untouched) | same |
| tests/unit | 1288 | **1285** (re-pin) | 1308 | **1176** | 109 vs 1285 | 1176 |
| scripts/ops (new key) | — | 0 | 3 | 3 | ≤ 10 (A1) | 3 |
| scripts/collect | — | 0 | 0 | 0 | — | 0 |
| src/breezy/app | — | 0 | 0 | 0 | — | 0 |

- **Pre-W3 diff versus base:** 0 new lines.
- **Removed pre-W3:** `test_current_rung_hold_exit_window_study.py:603` (`union-attr`) and `test_replay_daily_runner_batch_wiring.py:320,326` (`attr-defined`).
- **FIN + W3e versus FIN:** 0 new lines; tests/unit −132, scripts/analysis −67.
- **Lint:** ruff findings on the 26 touched files equal HEAD's (32 → 32, `diff` empty). Per-file `ruff format --diff` line counts are unchanged.

## §5 RED → GREEN

| ID | Check | RED | GREEN |
|---|---|---|---|
| R1 (in-tree) | `tests/unit/test_mypy_ratchet.py::test_mypy_stays_within_the_cf12_clean_set_and_ceilings` | After the §3 edits and before the re-pin: "tests/unit … lower the ceiling" (1288 vs measured 1285) | `CEILINGS["tests/unit"] = 1285` → passes |
| R2 (in-tree mypy) | Error lines `…exit_window_study.py:603`, `…batch_wiring.py:320,326` | Present at HEAD (`base.out`) | Absent (`head_w3e_r1.out`) |
| R3 (scratch FIN) | Apply W3's `xform.py` (imports, then ignores, driven by its own T2 run) to a scratch copy of the W3e worktree, then mypy | `fin_1.out`: 134 + 78 new lines; tests/unit 1308 | FIN + W3e: tests/unit 1176, scripts/analysis 126, and every group ≤ its ceiling; the only lines left are those listed in §6 |
| R4 (runtime) | Every touched test module, run alone, plus `tests/unit/analysis/stats/test_moved_source_pinned.py` (WRAPPERS identity; `__all__` is an Assign, which the `_top_level_names` scan correctly ignores) | — | Same pass and collection counts as at HEAD, module by module |

## §6 Residuals: deliberately not fixed in W3e, and pinned by W3's lowered ceilings

| File:line | Code | Why it stays | Follow-up |
|---|---|---|---|
| `tests/unit/test_asos_cache_freshness_check.py:39,42`, `test_asos_refresh_re_home.py:147` | arg-type (`site=object()`) | The fix needs a real `SettlementSite` fixture, which is a test-data change and out of typing-only scope | CF-12-W3r |
| `tests/unit/test_hourly_ask_relative_edge.py:72` | func-returns-value | The fix would reword `assert … is None`, and the invariant forbids touching assertions | CF-12-W3r (assertion review) |
| `scripts/analysis/wp7b_market_as_forecaster.py:1005-1008,1137,1248,1260` | arg-type, assignment | Script-internal: `takes: list[object]`; Optional fields narrowed by `trial.took` | CF-12-W3r |
| `scripts/analysis/family_tally_v2.py:1201-1202` | union-attr | Optional narrowed by the verdict invariant | CF-12-W3r |
| `scripts/analysis/forecast_conditional_model_study.py:585` | assignment | A variable reused as tuple and list | CF-12-W3r |
| `scripts/analysis/whole_tape_paper_replay.py:184` | assignment | The `_Classifier` Protocol does not match `classify_instance` (`grace_ns`); a likely Protocol typing defect | CF-12-W3r |
| `tests/contract/test_live_fill_scoring_chain_contract.py:384` | attr-defined (`family_tally_v2.read_scored_trials`) | W3e edits no contract test; group stays 5 ≤ 7 | CF-12-W3r |
| `scripts/venue/…positions_value_capture.py:80`, `…private_shape_probe.py:89` | attr-defined | `scripts/venue` is FORBIDDEN; 13 ≤ 23 | none (W3 pins) |
| `scripts/archive/iem_cli_fetch.py:547`, `iem_mos_freshness_check.py:112`, `lamp_archive_backfill.py:683` | various | 5 ≤ 8 after §5.3 | CF-12-W3r |
| `scripts/ops/decisions_retention.py:140` (×3) | — | Already pinned by W3 §4.2; W3c owns it | W3c |

**`src/` blockers: none.** No error, fixed or residual, needs an edit under `src/`.

## §7 Build sequence

0. **Stage 0 (read-only, in the W3e worktree).**
   - Preconditions, otherwise STOP:
     - `CEILINGS` matches §4's "today" column;
     - `mypy_path == "src:scripts/collect"`;
     - `git diff 316b50c4..HEAD -- src scripts tests pyproject.toml` is empty, or §4 is re-measured.
   - Re-run `w3e_apply.py` and `normalize.sh` on a scratch copy of the worktree. Every edit asserts exactly one match; a miss means the tree drifted, so STOP and re-plan that edit.
   - Measure mypy twice on the pre-W3 tree with W3e applied, then twice on the FIN simulation built from it. Each pair must be identical.
   - STOP if any of these hold:
     - any new line appears pre-W3;
     - `import-not-found` ≠ 310;
     - any group rises;
     - any FIN group exceeds its ceiling;
     - the FIN tests/unit margin is < 50;
     - an unlisted residual appears;
     - mypy exits 2.
1. Capture RED: R1 (apply the edits without the re-pin) and R3 (`fin_1.out`).
2. Apply §3.1, then §3.2, then §3.3 to the worktree by hand. `w3e_apply.py` is the reference, not the tool.
   - RUF022-sort the **new** `__all__` lists only. Never re-sort `nbp_skill_study`'s list.
   - Run `ruff check` and `ruff format --diff` on the touched files only, and diff against HEAD's findings; the delta must be zero.
   - Format only your own files. Check `git status` for stray reformatting.
3. Re-pin `CEILINGS["tests/unit"]` 1288 → 1285 in `tests/unit/test_mypy_ratchet.py`. R1 goes GREEN.
4. **Focused gate** (`PYTHONPATH=<wt>/src`, `--basetemp` under `~/.cache`; read every exit code):
   - all 16 touched test modules, each run alone;
   - `tests/unit/test_mypy_ratchet.py`;
   - `tests/unit/analysis/stats/test_moved_source_pinned.py`;
   - `tests/unit/test_prereg_v1_is_byte_unmodified.py`;
   - `tests/unit/test_polymarket_us_readonly_guard.py`;
   - `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` (exec pin);
   - `tests/unit/test_execution_egress_firewall_guard.py`;
   - `tests/unit/test_current_rung_hold_backtest_only.py` and `test_continuous_rung_hold_backtest_only.py`;
   - `tests/unit/test_polymarket_us_fee_schedule_pin.py`;
   - `tests/unit/test_runtime_import_isolation.py` and `test_unit_execstart_imports.py`;
   - all `tests/unit/test_autonomy_*.py`;
   - `tests/contract/`.

   Then run `lint-imports` from the worktree; it must print "N kept, 0 broken".
5. Run the full gate, `scripts/ci/run_tests_no_egress.sh`, and read EXIT=0 **before** any merge or push.
6. **Independent review.**
   - `python-reviewer` on the diff (`PYTHONPATH` set in its brief).
   - No security-reviewer trigger: no permit, egress, credential or `src/` code, and no exec import changes.
7. **Commit and record.**
   - Commit by explicit path. The body carries §4, the R1/R3 RED→GREEN evidence and the §6 residual list.
   - Add a PROGRESS row CF-12-W3r for the §6 residuals.
   - Update CF-12-W3: unblocked; re-run Stage 0 with the W3 §R5.2 amendments.
   - Append a line to the Rev2 log.

**Activation:** none. No unit, wrapper or runtime import changes. `__all__` only affects `import *`, which no module under `scripts/` is used with.

## §8 Invariants carried into every brief (BINDING)
- Nautilus Trader is immutable. `allow_short` stays `False`. Never weaken or delete a safety, settlement or contract test. Never assign operator caps. Never touch live enablement or the NO-SEND firewall.
- No `cast`, no `# type: ignore`, no ceiling raise, no new `# noqa`.
- No edits under `src/`, `scripts/venue/` or `tests/contract/`, and no exec-client byte changes.
- No new sibling-script import anywhere.
- Never `git stash`, never `uv sync`, never `uv run`. Use `/home/jon/breezy/.venv/bin/python` with the worktree's `PYTHONPATH`.

## §9 Rollback
- `git revert <W3e sha>` puts back the `CEILINGS` value of 1288, which matches HEAD's measured count with the edits gone. Run the full gate before pushing.
- W3 must not land on a tree without W3e: its Stage 0 STOP (FIN > ceiling) would fire again.

## §10 Risks
| Risk | Mitigation |
|---|---|
| A new consumer of an implicit re-export lands between W3e and W3 | W3's Stage 0 re-measures, and the STOP binds. |
| `__all__` misread as the module's full public API | New lists include all own public names (§2). |
| Tree drift moves edit anchors | Text-located edits with exact-count asserts; Stage 0 STOP. |
| The k1 `monkeypatch` changes when the original class is restored | Nothing after `build_population` reads `k1.AskObservation`; R4 checks the test's pass count. |

## §R5.2 Consequential amendments to CF-12-W3 r5.1 (apply when W3e merges)
1. **§7 precondition:** `CEILINGS["tests/unit"]` reads **1285**. All other values are unchanged.
2. **§4.1 projection rebased to measured values (±2 band, all components now measured):** scripts/analysis 126; scripts/archive 5; scripts/venue 13 (the +2 over r5's 11 is `_validate_endpoint` at `positions_value_capture.py:80` and `private_shape_probe.py:89`); tests/contract 5; tests/unit 1176; scripts/ops 3 (the `decisions_retention.py:140` triple; `ambig_latch_phase_a_check` adds 0); scripts/collect 0. The "+52 unattributed" is resolved: the 67 export-class lines are fixed by W3e, and the 11 left are named in W3e §6.
3. **§5.3 edit list:** add the two `# type: ignore[misc]` comments (`scripts/archive/iem_cli_fetch.py:233` `class IemCliTransport(PacedIemTransport)`, and `scripts/archive/metar_routine_minute_probe.py:419` `class MetarTransport(PacedIemTransport)`). Each exists only because the `PacedIemTransport` import is unresolved before W3: `disallow_subclassing_any` fires on an `Any` base. Before W3 they are used; after W3 they are `[unused-ignore]`. The rule becomes "remove `import-not-found` ignores, plus these two whole-comment `misc` ignores; nothing else". `decisions_retention.py:140` is still not touched. Measured effect: scripts/archive 7 → 5, with no group rising.
4. **R2 and R6 inventories:** unchanged. W3e adds no qualified or bare sibling-script imports. Verified: applying xform after W3e rewrites the same 83 files, 271 statements and 3 strings as applying it to HEAD alone.
