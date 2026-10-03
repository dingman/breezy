# CF-12-W3: sibling-script `import-not-found`, plan r1 (2026-10-03)

- Backlog row: `docs/core/PROGRESS.md:83` (CF-12-W3, LOW).
- Parent plan: `docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md`. Its execution log (`:119-121`) records the failed config-only trial and requires a separate plan plus peer review. This is that plan.
- Status: **r1, awaiting peer review.** No code has changed. Every number below was measured on 2026-10-03 at HEAD `f45f5a65`, using the shared interpreter (`/home/jon/breezy/.venv/bin/python -m mypy`, mypy 2.3.1) with a fresh `--cache-dir`. Trials ran on a scratch **copy** of `src/ scripts/ tests/ pyproject.toml`. The repo was never touched.
- Evidence files are in the session scratchpad, `.../scratchpad/cf12w3/`:
  - `baseline.txt` (HEAD);
  - `t1.txt` (config-only);
  - `t2.txt` (chosen design);
  - `t3.txt` (rewrite only, as a control).

---

## §0 Problem and goal state

**Problem.** HEAD reports **310** `[import-not-found]` errors. PROGRESS says 314, but that count is from 09-29 and has drifted.

| Group | Errors |
|---|---|
| `scripts/analysis` | 198 |
| `tests/unit` | 96 |
| `scripts/venue` | 10 |
| `scripts/archive` | 3 |
| `tests/contract` | 3 |

These name **75 distinct modules**:
- **74** resolve to a file under `scripts/{analysis,venue,archive,ops}/` (65 in analysis, 6 in venue, 2 in archive, 1 in ops);
- **1** is `breezy.runtime.position_reporting_lag`. That is a *deliberate* negative import inside `pytest.raises(ModuleNotFoundError)` at `tests/unit/test_position_reporting_lag.py:113`. It is not a sibling-script import.

At runtime, every one of these imports works, because each importer puts the sibling directory on `sys.path` first. There are 109 `sys.path` sites in `scripts/` and 121 in `tests/`. Directly executing `python scripts/analysis/x.py` also puts `scripts/analysis` on `sys.path[0]` by itself. mypy cannot see any of this, so each of these imports becomes `Any`, and the code across that seam goes **unchecked**.

**Why the config-only fix fails (reproduced, T1).** Setting `mypy_path = ["src", "scripts/analysis", "scripts/venue", "scripts/archive", "scripts/ops"]` makes mypy exit 2 with:
`scripts/analysis/discovery_set_equality.py: error: Source file found twice under different module names: "discovery_set_equality" and "scripts.analysis.discovery_set_equality"`

The cause: `explicit_package_bases = true` (`pyproject.toml`, the `[tool.mypy]` block) names each file from its closest base. Once `scripts/analysis` is a base, every file under it is named bare (`x`). But **28 import statements in 16 files** still import scripts by the package-qualified name `scripts.analysis.x` or `scripts.venue.x`. One file can only have one module name, so no mypy configuration satisfies both conventions at once.

**Goal state (acceptance test).**
1. A full-config mypy run reports **0** `[import-not-found]` errors whose module resolves to `scripts/**`. With the one negative test converted (see §5), it reports 0 `[import-not-found]` errors anywhere.
2. The `CLEAN`/`CEILINGS` ratchet (`tests/unit/test_mypy_ratchet.py:323-364`) is re-pinned to the measured post-change counts, and it passes.
3. Every live systemd unit, wrapper, and test invokes every script **exactly as it does today**. No `ExecStart=`, wrapper `.sh`, or `WorkingDirectory=` changes. No new runtime behaviour.
4. `scripts/ci/run_tests_no_egress.sh` exits 0.

---

## §1 Null-hypothesis check (L-1): does an existing mechanism already solve this?

Each mechanism below was measured or checked against the code. None of them solves the problem alone. The chosen design combines two of them: native `mypy_path`, plus the repo's existing bare-import convention.

| Mechanism | Verdict | Evidence |
|---|---|---|
| `mypy_path` += script dirs (config only) | **Necessary, not sufficient** | T1: exit 2, duplicate module name (above). |
| `explicit_package_bases` | Already on | It *causes* the bare naming once the script dirs are bases. Turning it off reintroduces the `src.breezy.*` vs `breezy.*` collision recorded in the config comment. |
| `namespace_packages` | Already the default (mypy ≥0.991) | `scripts.analysis.x` already resolves through it. That is exactly why the qualified convention works for mypy *today* and collides once the dirs are bases. |
| Per-module `ignore_missing_imports` for 74 modules | **Rejected** | It turns 309 seams into `Any`. That is the silencing the CF-12 "Carve-outs and don'ts" forbids ("using Any … to silence an error"), and it never reaches the goal of the seam being *checked*. |
| Add `scripts/__init__.py` and `scripts/analysis/__init__.py` | **Rejected** | It would make every file `scripts.analysis.x`, which forces either the qualified convention everywhere (Option Q) or `-m` invocation everywhere (Option I). The repo comment also records that the `__init__`-free layout is deliberate. |
| Change unit invocation to `python -m scripts.…` | **Rejected** | It edits about 20 live `ExecStart`/wrapper lines, which violates goal 3. |
| pytest `pythonpath = [...]` ini option (native) | **Deferred (YAGNI)** | This is pytest's native fix for the *test-side* `sys.path`, and it would make the 121 per-test inserts redundant. But it changes `sys.path` for the whole session and can mask an order-dependent import bug. The 12 test files that W3 touches follow the existing per-file pattern instead. If a peer prefers this option, it is a one-line, separable follow-up. |
| Existing `scripts/__init__.py` layout | None exists | `ls scripts/*/__init__.py` finds nothing. |
| Existing per-script self-bootstrap | **Exists, and is reused** | `scripts/analysis/score_live_trials.py:160` uses `sys.path.insert(0, str(Path(__file__).resolve().parent))`. `nbp_market_comparison.py:20-25` and `nbp_learning_nightly.py:24-29` use a guarded loop. `test_runtime_import_isolation.py:136-145` depends on this: `tape_instruments` is excluded precisely because it lacks the bootstrap. |

**Basename-collision check (measured).** The 112 `.py` basenames under `scripts/*/` are pairwise unique. None of them shadows a stdlib module (`sys.stdlib_module_names`) or anything importable from the venv. So a flat, bare namespace across all four dirs is safe.

---

## §2 Invocation inventory (every path that imports or executes a script)

**Live systemd units (`deploy/systemd/`; all `WorkingDirectory=/home/jon/breezy`):**

| Unit | Invocation | Affected by W3? |
|---|---|---|
| `breezy-discovery-pull.service:67` | `.venv/bin/python -m scripts.analysis.discovery_venue_pull …` | **Yes.** This is the only `-m` script unit. W3 rewrites its 3 qualified imports to bare, so the script has to self-bootstrap `scripts/analysis` and `scripts/venue` (§5). |
| `breezy-fee-evidence-pull.service:55` | direct file `scripts/venue/fee_drift_evidence_pull.py` | No: the file has no sibling imports. |
| `breezy-nbp-learning-nightly.service:26` | direct file `scripts/analysis/nbp_learning_nightly.py` | Its bare imports are unchanged. Only the 2 now-unused `# type: ignore[import-not-found]` comments are removed (comment-only). |
| `asos-refresh-run.sh:86,102,116,133` | direct file: `asos_recent_refresh`, `asos_cache_freshness_check`, `archive/iem_mos_backfill`, `archive/iem_mos_freshness_check` | No. |
| `capital-flow-pull-run.sh:33`, `decision-funnel-digest-run.sh:82`, `decisions-retention-run.sh:45` (`scripts/ops`), `exit-window-study-run.sh:140`, `family-tally-v2-run.sh:328`, `hypothesis-triage-run.sh:42`, `live-tally-run.sh:254`, `portfolio-roi-run.sh:110`, `position-monitor-report-run.sh:193`, `replay-daily-run.sh:82,181,201,217`, `score-live-trials-run.sh:217,266,339`, `station-candidate-register-run.sh:47,49` | direct file (`"$PY" "$REPO/scripts/…py"`) | No. |
| `family-tally-v2-run.sh:180,188`, `live-tally-run.sh:142`, `score-live-trials-run.sh:137` | `-m breezy.runtime.*` | No (`src`, not scripts). |
| trade supervisor, node, quote-tape, NWS ingest | `breezy.*` only | No. `src/` never imports `scripts` (grep: only docstring mentions). |

- **Crontab:** no Breezy entries (`crontab -l` shows only codegraph maintenance and Doppler).
- **Shell inside scripts:** `scripts/analysis/aud07_m1c_sweep.sh` manipulates `sys.path` but never invokes `-m scripts`.

**Tests:**
- About 100 test files insert `scripts/analysis` (or venue/archive) and import bare. They are unaffected.
- **12 test files** import the qualified name (§5, list). These resolve today only because `python -m pytest` puts the CWD (repo root) on `sys.path`.
- Subprocess guards that run scripts as production does, and therefore act as W3's runtime safety net:
  - `tests/unit/test_unit_execstart_imports.py` runs each venv-python `ExecStart` under its own `WorkingDirectory`, with a scrubbed env and no repo root on `PYTHONPATH`;
  - `tests/unit/test_discovery_pull_exec_import.py`;
  - `tests/unit/test_runtime_import_isolation.py::test_entry_module_imports_cleanly` runs `python -c "import scripts.analysis.<entry>"` in a child for `discovery_venue_pull`, `nbp_shadow_parity`, `nbp_shadow_parity_pure`, `nbp_market_comparison` and others (`:81-128`).

**Incident precedent (binding context).** On 2026-09-26 at 16:52Z, `breezy-discovery-pull` died with `ModuleNotFoundError: No module named 'scripts'`. The cause was exactly the qualified-vs-direct-file mismatch (`test_unit_execstart_imports.py:25-34`). W3 touches the same seam, so the subprocess guards above are mandatory GREEN evidence. They cannot be waived.

---

## §3 Options

| # | Option | Sites touched | Runtime risk | Verdict |
|---|---|---|---|---|
| **B** | **Normalize to bare imports (the majority convention)** and add the 4 script dirs to `mypy_path` | 28 statements in 16 files; a self-bootstrap in the 3 qualified-convention scripts that lack one; 1 config line | Low. Direct-file units are unchanged. The 1 `-m` unit gets a bootstrap, guarded by 3 existing subprocess tests. | **CHOSEN** |
| Q | Normalize to qualified `scripts.analysis.x` everywhere | 309 import sites in about 75 files, plus a repo-root bootstrap in every script run by about 20 direct-file units. Tests that `monkeypatch` bare module objects would also have to change. | **High.** Every live unit's import path changes, which repeats the 09-26 incident class about 20 times over. | Rejected |
| I | Change invocation to `python -m` for all units, with `__init__.py` | About 20 `ExecStart`/wrapper edits | High, and it violates goal 3 | Rejected |
| C | Per-module `ignore_missing_imports` | 1 config block | None at runtime | Rejected: it is silencing, it is forbidden, and it misses the goal |
| P | Option B, but tests get `sys.path` from pytest `pythonpath` instead of per-file inserts | B minus the test inserts, plus 1 ini line | Session-wide `sys.path` change | Deferred (see §1) |

**Why B.** Bare imports are the convention of 74 of the 75 modules and about 300 of the roughly 330 sites. Python itself supports it for direct-file execution, which is how 19 of the 20 script units run. Option B moves the 28-site minority onto the majority convention. Option Q would instead rewrite the majority and the live invocation contract. Option B also removes a latent **double-module-identity** hazard: today one pytest process can hold both `discovery_set_equality` and `scripts.analysis.discovery_set_equality` as separate module objects with separate globals, so a monkeypatch on one does not affect the other.

---

## §4 Measured effect of the chosen design (T2), and what it exposes

T2 is the scratch copy with the §5 import rewrite and `mypy_path = ["src", "scripts/analysis", "scripts/venue", "scripts/archive", "scripts/ops"]`. Result: **exit 1** (a normal report), `Found 1624 errors in 171 files`. Baseline was 1875 in 240 files.

- **`[import-not-found]`: 310 → 1.** The remaining 1 is the deliberate `position_reporting_lag` negative test, which §5 handles.
- The ratchet, run against the real `assess_ratchet` with the current `CLEAN`/`CEILINGS`, produces:
  - **lower ceilings:**
    - `scripts/analysis` 360 → **158**
    - `scripts/archive` 8 → **3**
    - `scripts/venue` 23 → **11**
    - `tests/contract` 11 → **9**
    - `tests/unit` 1451 → **1412**
  - **two newly visible paths with no CLEAN/CEILINGS entry:**
    1. `scripts/ops/decisions_retention.py`: 3 errors at `:140`. These are `attr-defined` on `opener: object`, plus the existing `# type: ignore[call-arg]` becoming `unused-ignore`. This file was never type-checked before. It becomes reachable now because tests import it bare.
    2. **`src/breezy/app/trade.py`: 6 errors at `:1189-1207`.**
       - `SettingsLike` protocol members are settable, but `BreezyTradeSettings` provides read-only attributes (`arg-type`).
       - `permit: LiveTradingPermit | None` is passed into `OrderSubmissionPermit.issue` and dereferenced (`arg-type`, 4× `union-attr`).
- Control T3 (the rewrite with the *original* `mypy_path`) also shows the `trade.py` errors. So it is the import-graph change, not `mypy_path`, that unmasks them.
- **Mechanism not yet explained.** `trade.py` and `order_enablement.py` are byte-identical across the runs. The masking at HEAD is consistent with mypy's import-cycle (SCC) processing order deferring a type to `Any`. Stage 0 below must re-measure this twice to confirm it is deterministic.
- **These are latent, pre-existing type defects in the live trade boot path.** W3 does not introduce them. W3 makes them visible, which is the point of CF-12.
- Error-code mix after T2: `arg-type` 296 → 332 and `attr-defined` 156 → 212. This is the expected cost of previously-`Any` seams now being checked. It is not a regression in code.

**Handling inside W3.** CF-12 forbids runtime edits in a typing wave, and the `trade.py` fix touches the permit path, which is safety-relevant. So W3 pins:
- `"src/breezy/app": 6`
- `"scripts/ops": 3`

as **new `CEILINGS` entries**, each with a dated comment that names the follow-up. W3 does **not** fix them. Two follow-up rows go into PROGRESS:
- **CF-12-W3b**: `trade.py` permit narrowing and `SettingsLike` read-only protocol members. This touches the live trade boot path, so it gets its own plan, a security-reviewer pass, and the full gate.
- **CF-12-W3c**: type the `decisions_retention` opener as a `Callable`, the same pattern as `trial_day_latch` in CF-12 W1.

Re-pinning a `CEILINGS` entry for newly *visible* errors in existing code is the ratchet's sanctioned mechanism. It does not weaken the ratchet: `CLEAN` is untouched, and every ceiling only goes down or is new.

---

## §5 Chosen design: file-by-file changes

Build in a worktree from `feat/data-capture-and-risk`, with `PYTHONPATH=<wt>/src`. Run mypy exactly as `/home/jon/breezy/.venv/bin/python -m mypy --cache-dir <wt-private>`. **Never `uv run`, `uv sync`, `pip`, or `git stash`.** Run `lint-imports` with the console script, from the worktree root.

### 5.1 Config (1 line)
- `pyproject.toml` `[tool.mypy]`:
  - set `mypy_path = ["src", "scripts/analysis", "scripts/venue", "scripts/archive", "scripts/ops"]`;
  - extend the existing comment to state that script dirs are bases because scripts import siblings by bare name (the convention), and that a package-qualified `scripts.<dir>.x` import is therefore forbidden (guarded by test R2);
  - `files` is unchanged. `scripts/ops` is added as a *base* only, not as a `files` entry. `scripts/operator` and `scripts/ci` are not added, because nothing imports them (YAGNI).

### 5.2 Scripts: 4 files, imports only, plus a bootstrap where `-m` or a child import needs it

| File | Lines | Change |
|---|---|---|
| `scripts/analysis/discovery_venue_pull.py` | 29, 250, 373 | Rewrite `from scripts.analysis.discovery_set_equality import …` → `from discovery_set_equality import …` (×2), and `from scripts.venue.fee_drift_evidence_pull import build_default_client` → `from fee_drift_evidence_pull import …`. **Add a guarded bootstrap** before line 29 that inserts `Path(__file__).resolve().parent` and `…parents[1] / "venue"`, in the `nbp_market_comparison.py:20-25` idiom (only if not already present). Required because the live unit runs it with `-m`, where `sys.path[0]` is the CWD. |
| `scripts/analysis/nbp_shadow_parity.py` | 86 | `from scripts.analysis.nbp_shadow_parity_pure import` → `from nbp_shadow_parity_pure import`. **Add the guarded bootstrap of its own dir.** Required by `test_runtime_import_isolation` (`import scripts.analysis.nbp_shadow_parity` in a child) and to keep any `-m` invocation working. |
| `scripts/analysis/nbp_backfill.py` | 105 | `from scripts.analysis.nbp_lag_census import` → `from nbp_lag_census import`. **Add the guarded bootstrap.** |
| `scripts/analysis/nbp_market_comparison.py` | 53, 54, 64 | Rewrite to bare. Its bootstrap already exists at `:20-25`. |

- Behaviour: under direct-file execution, the bootstrap is a no-op, because the dir is already `sys.path[0]` and the insert is guarded. Under `-m` or a qualified child import, it makes the bare siblings resolvable. This is the same contract that `score_live_trials` and the other bare-convention entries already satisfy in `test_runtime_import_isolation`.
- No logic, argument, or output change.
- Put `# noqa: E402` only where ruff actually reports it, matching the existing scripts.

### 5.3 Remove now-unused `# type: ignore[import-not-found]` (comment-only)
These 7 files carry `ignore[...import-not-found]` that T2 reports as `unused-ignore`:
- `scripts/analysis/{whole_tape_paper_replay,replay_sufficiency_census,tape_instruments,nbp_learning_nightly,current_rung_hold_paper_replay,nbp_skill_study}.py`
- `tests/unit/test_nbp_skill_study.py`

Remove the ignore, or drop just the `import-not-found` code if the ignore lists others, **only** where the implementer's own mypy run reports `unused-ignore` for it. Re-measure; do not edit blindly. Any ignore that *still* suppresses something stays.

### 5.4 Tests: 12 files, imports plus `sys.path`

Each file gets the existing module-level idiom (`_SCRIPTS_ANALYSIS_DIR = …; if str(...) not in sys.path: sys.path.insert(0, ...)`, as at `tests/unit/test_structural_dead_stop.py:32-33`) before its bare import. The qualified imports are then rewritten:

| File | Lines |
|---|---|
| `tests/unit/test_discovery_set_equality.py` | 16, 725 |
| `tests/unit/test_discovery_venue_pull.py` | 19, plus the **string** monkeypatch target `:279` `"scripts.venue.fee_drift_evidence_pull.build_default_client"` → `"fee_drift_evidence_pull.build_default_client"`. It must match the module object that `discovery_venue_pull` now imports. This file also inserts `scripts/venue`. |
| `tests/unit/test_nbp_backfill.py` | 36 |
| `tests/unit/test_nbp_lag_census.py` | 13 |
| `tests/unit/test_nbp_market_comparison.py` | 18: `from scripts.analysis import nbp_market_comparison as m` → `import nbp_market_comparison as m` |
| `tests/unit/test_nbp_shadow_parity_live.py` | 28, 53, 54 |
| `tests/unit/test_nbp_shadow_parity_load.py` | 15, 22, 133, 189, 345 |
| `tests/unit/test_nbp_shadow_parity_no_side_synthetic.py` | 46, 47 |
| `tests/unit/test_nbp_shadow_parity_pure.py` | 27 |
| `tests/unit/test_nbp_skill_study.py` | 36 (it already inserts the dir) |
| `tests/unit/test_fq_live_analysis_point_cdf_parity.py` | 65 |
| `tests/strategy/forecast_quantile_ladder/test_lst_margin_horizon.py` | 25 |

- **Not changed:** the qualified **strings** in `tests/unit/test_runtime_import_isolation.py:81-145`, `test_unit_execstart_imports.py`, `test_discovery_pull_exec_import.py`, and `test_polymarket_us_readonly_guard.py:1196`. These model how *production* invokes or imports the entry, in a child process. They are the guards, and they must keep passing unmodified.
- **Negative import** `tests/unit/test_position_reporting_lag.py:113`: replace `import breezy.runtime.position_reporting_lag` inside `pytest.raises(ModuleNotFoundError)` with `importlib.import_module("breezy.runtime.position_reporting_lag")`. Same assertion and same semantics, and mypy no longer resolves the import statically. Without this change the global count stays at 1.

### 5.5 Ratchet constants (`tests/unit/test_mypy_ratchet.py:354-364`)
- Lower the 5 ceilings to the values the implementer measures. The T2 expectations are 158, 3, 11, 9, 1412; re-measure, because concurrent merges move these.
- Add `"src/breezy/app": 6` and `"scripts/ops": 3`, each with a dated W3 comment naming W3b or W3c.
- `CLEAN` is unchanged.

### 5.6 Docs
- `PROGRESS.md`:
  - close CF-12-W3 with the commit SHA and the measured counts;
  - add rows CF-12-W3b (`trade.py` permit typing; security-reviewer required) and CF-12-W3c (`decisions_retention` opener).
- Append a W3 execution-log entry to the CF-12 Rev2 plan.

---

## §6 RED → GREEN tests

| ID | Test (new, in `tests/unit/test_mypy_ratchet.py` unless noted) | RED at HEAD | GREEN after |
|---|---|---|---|
| R1a | `test_import_not_found_lines_are_extracted_with_their_module_names`: a pure parser unit test on fake mypy text, for a new pure helper `parse_import_not_found(output) -> list[tuple[path, module]]`. It drops notes and keeps only `[import-not-found]`. | Fails (helper absent) | Passes |
| R1b | `test_full_config_mypy_reports_zero_import_not_found`: reuses the module-scoped `mypy_report` run by extending the fixture to also keep the raw text, so there is still **one** mypy run. It asserts that `parse_import_not_found(...) == []`. On failure it lists `path → module`. | **Fails with 310 entries** (measured) | 0 (T2 plus §5.4 negative-import fix) |
| R2 | `tests/unit/test_scripts_import_convention.py::test_no_package_qualified_sibling_script_import`: an AST scan (not regex) of `scripts/**/*.py` and `tests/**/*.py` for `Import`/`ImportFrom` nodes whose module starts with `scripts.analysis`, `scripts.venue`, `scripts.archive` or `scripts.ops` (or `from scripts import <dir>`). String literals are ignored, so the production-modelling guards in §5.4 stay legal. It includes a positive control that feeds a synthetic source string and asserts a hit. | **Fails: 28 sites in 16 files** | 0 |
| R3 | `test_mypy_stays_within_the_cf12_clean_set_and_ceilings` (existing) | Passes at HEAD. After §5.1–5.4 *without* §5.5, it fails with the 5 "lower the ceiling" plus 2 "no CLEAN or CEILINGS entry" messages (T2 measured). | Passes after §5.5 |
| G1 | `test_unit_execstart_imports.py` and `test_discovery_pull_exec_import.py` (existing, unmodified) | Pass | **Must still pass**: the `-m scripts.analysis.discovery_venue_pull` unit, run as systemd would, with the new bootstrap. **Required negative check (RED evidence):** with the bootstrap temporarily omitted from `discovery_venue_pull.py`, `test_unit_execstart_imports` must fail with `ModuleNotFoundError: discovery_set_equality`. This proves the guard covers the change. Record that output, then restore. |
| G2 | `test_runtime_import_isolation.py::test_entry_module_imports_cleanly` (existing, unmodified) | Pass | Must still pass for `discovery_venue_pull`, `nbp_shadow_parity`, `nbp_shadow_parity_pure`, `nbp_market_comparison`. The bootstrap in §5.2 is what keeps it green. Same omit-bootstrap RED check for `nbp_shadow_parity`. |
| G3 | Each of the 12 §5.4 test files run **alone** (`pytest <file>`), not only in the suite | — | Pass. This proves each file inserts its own `sys.path` and does not depend on test ordering. |
| G4 | Manual smoke of the live `-m` unit's import path, without touching the unit: `cd /home/jon/breezy && env -i PATH=/usr/bin HOME=$HOME /home/jon/breezy/.venv/bin/python -m scripts.analysis.discovery_venue_pull --help` (from the worktree root) | — | Exit 0. This duplicates G1 by design, as the 09-26 incident class warrants. |

**Ordering:** R1a, R1b and R2 are written first and their RED output captured. Then §5.1–5.4 are applied, then §5.5. The final step is the full gate: `scripts/ci/run_tests_no_egress.sh` with `EXIT=0` read **before** any push (lesson "read gate EXIT before push").

Cost: R1b adds no extra mypy run, because it shares the fixture. R2 is a sub-second AST scan.

---

## §7 Build sequence
0. **Stage 0 (re-measure, read-only).**
   - In the worktree, re-run baseline mypy, then T2, using fresh caches.
   - Run T2 **twice** to confirm the `trade.py` 6 and `decisions_retention` 3 are deterministic, not a mypy SCC-order flake.
   - **STOP and return to plan review** if T2 differs from §4 by more than ±5% on any ceiling, or if any new uncovered path appears beyond the two named.
1. Write R1a, R1b and R2, and capture RED.
2. §5.1 config, then §5.2 scripts, then §5.3 ignores, then §5.4 tests. R2 turns GREEN.
3. Run mypy, then §5.5 ratchet re-pin. R1b and R3 turn GREEN.
4. Run the G1/G2 omit-bootstrap RED checks, then restore. Run G1–G4 GREEN, then `ruff check`, `ruff format --check` on the touched files, and `lint-imports` (demand "N kept, 0 broken").
5. Full gate `scripts/ci/run_tests_no_egress.sh` with EXIT=0.
6. Independent review: `python-reviewer` on the diff. The trigger for `security-reviewer` is **not** met, because W3 does not touch `trade.py` (W3b will).
7. Commit by explicit path. Merge, then §5.6 docs.

**Activation:** no restart is required. The supervisor and node never import `scripts/`. The only affected live unit, `breezy-discovery-pull`, is a timer-fired oneshot, so its next run picks up the new code. Check its next timer run in the journal for exit 0 (`systemctl --user status breezy-discovery-pull.service`).

---

## §8 Rollback
- One commit, or one merge. `git revert <sha>` restores the qualified imports, the old `mypy_path` and the old ceilings atomically.
- No unit file, wrapper, data, state DB or venv changes, so no `daemon-reload` and no restart.
- If `breezy-discovery-pull` fails after merge with `ModuleNotFoundError`, revert. The next timer run self-heals. A missed discovery run loses one evidence snapshot only, and has no trading impact.

---

## §9 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The `-m` discovery unit loses a sibling import (repeat of 09-26) | Low | One evidence run lost; no trading impact | G1 and G4, plus a mandatory omit-bootstrap RED proof that the guard bites |
| A test passes only because another test inserted `sys.path` (order dependence) | Medium | Hidden fragility | G3 runs each touched file alone |
| A monkeypatch string still targets the qualified module, so the patch silently misses | Low (1 site found, `:279`) | False GREEN | R2 covers import nodes; the plan names the 1 string site; reviewer greps `"scripts\.(analysis\|venue)\.` in `monkeypatch`/`patch(` calls |
| Newly visible `trade.py` errors are read as "W3 broke trading" | Medium (perception) | Mis-triage | §4 documents that they are latent and pre-existing (T3 control). W3 changes no runtime file except the 4 scripts' import lines and bootstraps. W3b owns the fix, with a security review. |
| mypy SCC-order nondeterminism moves counts between runs | Low–Medium | A flaky ratchet | Stage 0 double-run; STOP if not reproducible |
| Concurrent merges move the ceilings before W3 lands | High | Stale pins | §5.5 says "re-measure"; R3's "lower the ceiling to N" message reports the exact value |
| A future script basename collides across dirs or with a dependency (flat bare namespace) | Low (0 of 112 today) | mypy exit 2, or a wrong module at runtime | Out of W3 scope. Note it as a reviewer item. A uniqueness test is a cheap follow-up if a peer wants it now. |
| The `ignore` removal in §5.3 strips an ignore that still suppresses something | Low | A new error | Edit only lines that the implementer's own run flags as `unused-ignore` |

**Invariants honoured:**
- Nautilus is untouched.
- No `ExecStart`, wrapper or unit edits.
- No test is weakened or deleted:
  - the negative-import test keeps its assertion;
  - the guard tests are unmodified;
  - `CLEAN` is unchanged;
  - ceilings only go down or are new, with comments.
- None of the forbidden forms are used (no blanket `type: ignore`, no `ignore_errors`, no `disable_error_code`, no `files` removal, no `Any` or `cast` silencing).
- No operator-reserved controls are touched.
- The NO-SEND firewall and `allow_short` are not touched.

---

## §10 Open questions for peer review
1. Ceiling the `trade.py` 6 in W3 and fix them in W3b (as proposed), or block W3 on fixing them first? The proposal ceilings them, because CF-12 forbids runtime edits in a typing wave and the permit path deserves its own security-reviewed change.
2. Per-file test `sys.path` inserts (proposed) or pytest `pythonpath` (Option P)?
3. Should W3 also add a basename-uniqueness test for `scripts/*/`, or defer it?

## Self-score
**86/100.**
- Strengths:
  - the failure was reproduced (T1) and the chosen design was measured end-to-end (T2), with a control (T3);
  - the full invocation inventory is checked against the unit files;
  - the RED guards include an omit-bootstrap proof for the incident-class seam.
- Deductions:
  - the `trade.py` masking mechanism is measured but not explained (−6);
  - the ceilings will drift before execution (−4);
  - T2 rewrote imports by regex in a copy, so the real edit may surface ruff E402/I001 noise that was not measured (−4).
