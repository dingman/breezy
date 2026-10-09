# CF-12-W3: sibling-script `import-not-found`, plan r5 (2026-10-09)

- Backlog row: `docs/core/PROGRESS.md:91` (CF-12-W3, LOW: "needs r5 re-plan after STAGE + WP3b").
- Parent plan: `docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md`. Its execution log (`:119-121`) records the failed config-only trial and requires a separate plan with peer review. This is that plan.
- **Status: r5**, a re-base of the APPROVED r4 (`reviews/CF-12-W3-r4-final.md`, python-reviewer 96, code-reviewer 96) onto the post-CF-12-STAGE tree. **r5 needs a fresh peer review before build**, because the rewrite scope grew about tenfold (§0, §R5 Disposition). The r1–r4 history is kept in `CF-12-W3_plan_r{1..4}.md` and is not repeated here.
- **Changelog r4 → r5 (2026-10-09):**
  - Re-based on HEAD `316b50c4`, after STAGE (commit A `816aec53`, commit B `66d7fe74`, merged via `1462514d`). The `scripts/analysis` post-STAGE ceiling is **351, not 352**: `8e6e77c6` (10-06, F7a WP1s) had already lowered it 360 → 359 before STAGE.
  - The qualified-import inventory went from 28 statements in 16 files to **274 statements in 83 files**. Patch strings went from 1 to 3. Ignored `import-not-found` lines went from 12 to 40.
  - `mypy_path` already carries `scripts/collect`. A new `scripts/ops` module and the `scripts/collect` seam are pinnable candidates.
  - Added: an exec-client exclusion statement, the R6 qualified-name child-import gate, the G5 NO-SEND classification-invariance check, a ceiling-rise STOP, a `< 800`-line constraint, and a provenance-blob disposition.
- **Measurement basis (r5).** One full-config mypy run on the primary tree at HEAD `316b50c4` (2026-10-09), using the ratchet's own invocation (`test_mypy_ratchet.py:414-433`). Command: `cd /home/jon/breezy && env -u FORCE_COLOR NO_COLOR=1 MYPY_FORCE_COLOR=0 PYTHONPATH=/home/jon/breezy/src /home/jon/breezy/.venv/bin/python -m mypy --cache-dir /home/jon/.cache/breezy-agent/cf12w3-mypy --no-color-output`. Errors were grouped with the ratchet's own `parse_mypy_report` / `_matching_entry` / `assess_ratchet`. Everything else was established read-only: source inventories, git history, codegraph. **No T2/FIN tree was measured for r5.** Every post-W3 number below is a projection, and Stage 0 (§7) is the binding measurement.
- **Dependency (satisfied).** CF-12-STAGE has landed. `git merge-base --is-ancestor 66d7fe74 HEAD` is true. `check_mypy_exit` is defined (`test_mypy_ratchet.py:72`) and is called by the fixture (`:432`). The current `CEILINGS` are listed in §0. §7 step 0 re-checks all of this mechanically.
- **Every mypy invocation in this plan** runs as `cd <tree> && env -u FORCE_COLOR NO_COLOR=1 MYPY_FORCE_COLOR=0 PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python -m mypy --cache-dir <private-cache>`. Without `PYTHONPATH`, `breezy.pth` resolves to the primary `src` and mypy reports 6 phantom `src/breezy/app/trade.py` errors (r4 §4.0). **A non-zero `src/breezy/app` count means the environment is wrong; it is not a finding.**
- **Byte-pinned exec client: EXCLUDED.** W3 edits **no file under `src/`**, and therefore never touches `src/breezy/adapters/polymarket_us/exec/client.py`. That file is byte-pinned (`tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` and the exec-import pin set) and sits inside the CLEAN `src/breezy/adapters`. W3 also edits **no file under `scripts/venue/`**, the scope of `tests/contract/test_us_source_ingest_egress_guard.py`. Close-out asserts `git diff --stat <base>..HEAD -- src/ scripts/venue/` is empty. No new W3 test imports any `breezy.adapters.polymarket_us.exec` module, because the exec import pin is a set-equality test.
- Binding build items carried from `reviews/CF-12-W3-r3-final.md` (G4b; the six LOWs) and `reviews/CF-12-W3-r4-final.md` (items 1–4) stay binding. Item 1 (±2 bands; "if the ceilings differ, re-derive the bounds") is applied in §4.1 and §7.

---

## §0 Problem and goal state

**Problem.** At HEAD `316b50c4`, mypy reports **310** `[import-not-found]` errors naming **75** distinct modules. That is unchanged from r4.

| Group | Errors |
|---|---|
| `scripts/analysis` | 198 |
| `tests/unit` | 96 |
| `scripts/venue` | 10 |
| `scripts/archive` | 3 |
| `tests/contract` | 3 |

- **74** of the modules resolve to a file under `scripts/{analysis,venue,archive,ops}/`.
- **1** is `breezy.runtime.position_reporting_lag`. It is a deliberate negative import inside `pytest.raises(ModuleNotFoundError)` at `tests/unit/test_position_reporting_lag.py:113`.
- A further **40** bare sibling imports are silenced by `# type: ignore[import-not-found]` and do not appear in the 310: `scripts/analysis` 14, `scripts/archive` 18, `scripts/collect` 1, `tests/unit` 7 (§5.3). Every one of the 40 names a module inside one of the five planned bases.

At runtime all of these imports work, because each importer puts its sibling directory on `sys.path`, or direct execution does. mypy cannot see that, so each import becomes `Any` and the code across that seam goes unchecked.

**Why the config-only fix still fails.** Adding the script dirs to `mypy_path` makes mypy exit 2 with `Source file found twice under different module names`. CF-12-STAGE's own positive control re-confirmed this on the STAGE build: r1.1 delta (c) used exactly `mypy_path = "src:scripts/collect:scripts/analysis:scripts/venue:scripts/archive:scripts/ops"`. The cause is that `explicit_package_bases = true` (`pyproject.toml:412`) names each file from its closest base, while **274 import statements in 83 files** still use the package-qualified form `scripts.<dir>.x`. That is up from 28 statements in 16 files at r4:

| Importer group | Statements | Files |
|---|---|---|
| `scripts/analysis` | 129 | 36 |
| `tests/unit` | 143 | 45 |
| `tests/contract` | 1 | 1 |
| `tests/strategy` | 1 | 1 |

By target: `scripts.analysis` 260, `scripts.archive` 13, `scripts.venue` 1. By file creation date: 16 files up to 10-01, and **67 files created 10-06 to 10-08**.

**Why the qualified form is spreading (mechanism).** A new bare sibling import raises the importer's ceilinged count by one `import-not-found` error. A qualified import resolves through namespace packages and costs nothing. The ratchet therefore rewards the convention that blocks W3. W3 removes that incentive, because bare imports resolve once the dirs are bases, and R2 forbids the qualified form. Every day without W3 adds rewrite work (see the "rewrite scope grows" risk in §9).

**Goal state (acceptance test).**
1. A full-config mypy run reports **0** `[import-not-found]` errors anywhere. The one negative test is converted in §5.4.
2. The `CLEAN`/`CEILINGS` ratchet (`tests/unit/test_mypy_ratchet.py:365-410`) is re-pinned to the measured post-change counts and passes, with **every existing ceiling equal to or lower than today's value**. Each newly visible package (`scripts/ops`, and `scripts/collect` if it reports any error) is pinned by an **exact `(code, message) → count` multiset** (R4), not only by its total.
3. Every live systemd unit, wrapper and test invokes every script **exactly as today**. There are no `ExecStart=`, wrapper `.sh`, `WorkingDirectory=` or unit-file edits, and no new runtime behaviour beyond import resolution (§5.0 carve-out). Every rewritten script stays importable under its qualified name (R6).
4. No file under `src/` or `scripts/venue/` changes. The exec client is excluded (header).
5. `scripts/ci/run_tests_no_egress.sh` exits 0.

---

## §1 Null-hypothesis check (L-1): does an existing mechanism already solve this?

No single mechanism solves it. The design combines native `mypy_path` with the bare-import convention the repo already uses, which **`scripts/collect` already proves in production**.

| Mechanism | Verdict | Evidence |
|---|---|---|
| `mypy_path` += script dirs (config only) | **Necessary, not sufficient** | Exit 2: duplicate module name (STAGE r1.1 (c) positive control). |
| **`scripts/collect` precedent (r5)** | **Exists; this is the design** | `pyproject.toml:418` `mypy_path = "src:scripts/collect"` with comment `:435` "sibling modules import each other by bare name; see mypy_path". The directory measures 0 errors at HEAD. W3 extends the same pattern to four more dirs. |
| `explicit_package_bases` | Already on | It is what names files bare once their dir is a base. Turning it off brings back the `src.breezy.*` vs `breezy.*` collision (`pyproject.toml:413-417`). |
| Per-module `ignore_missing_imports` | **Rejected** | It makes the seams `Any`, which is the silencing CF-12 forbids (Rev2 `:126-135`). |
| `scripts/__init__.py` packages | **Rejected** | The `__init__`-free layout is deliberate (`pyproject.toml:397-399`). No `__init__.py` exists under `scripts/` at HEAD. |
| `python -m scripts.…` for every unit | **Rejected** | It needs about 20 live `ExecStart`/wrapper edits, which violates goal 3. |
| pytest `pythonpath = [...]` | **Deferred (YAGNI)** | A session-wide `sys.path` change can mask an order-dependent import bug. The per-file idiom is kept. |
| Existing per-script bootstraps | **Exist, reused** | 17 of the 36 qualified-import scripts already insert the repo root (`parents[2]`). Three also insert their own dir (`multisource_blend_features_build.py:58-61`, `multisource_blend_inputs_forecast.py:33-36`, `multisource_blend_inputs_obs.py:48-51`). |
| import-linter | **Does not cover `scripts/`** | `pyproject.toml:71` `root_packages = ["breezy", "nautilus_trader"]`. R2 is the only mechanical guard of the convention. `lint-imports` still runs and must print "N kept, 0 broken". |
| bwrap sandbox `entry_modules` | **Not affected** | Every `AUTONOMY_BWRAP_TABLE` row's `entry_modules` is a `breezy.*` module (`src/breezy/runtime/autonomy_sandbox/table.py:200,268-290,455,517`). No `scripts.*` entry module exists. |

**Basename-collision check (r5, HEAD).** The five bases (`analysis`, `venue`, `archive`, `ops`, `collect`) hold **168** `.py` files. Their basenames are pairwise unique, and none matches a `sys.stdlib_module_names` entry or a key of `importlib.metadata.packages_distributions()`. R5 (§6) makes this permanent and now covers `scripts/collect`.

---

## §2 Invocation inventory

**Live systemd units (`deploy/systemd/`; all `WorkingDirectory=/home/jon/breezy`):**

| Unit | Invocation | Affected by W3? |
|---|---|---|
| `breezy-discovery-pull.service:77` | `.venv/bin/python -m scripts.analysis.discovery_venue_pull …` | **Yes.** This is still the **only** `-m scripts.` unit, and the only deploy reference among the 36 rewritten scripts. Its 3 qualified imports become bare (`:31` module-level; `:305` and `:444` function-local), and the script self-bootstraps `scripts/analysis` and `scripts/venue` (§5.2). The unit file is not edited. Its explanatory comment goes stale and is deferred to CF-12-W3d. |
| Every other script unit and wrapper (`asos-refresh-run.sh`, `score-live-trials-run.sh`, `replay-daily-run.sh`, `family-tally-v2-run.sh`, the collector units, …) | direct file, or `-m breezy.*` | No. None of those scripts carries a qualified sibling import, so they get at most comment-only `§5.3` edits. |
| Trade supervisor, node, quote-tape, NWS ingest, AUT-6 health and other bwrap rows | `breezy.*` only | No. `src/` never imports `scripts`. |

- **Operator and agent `-m` runs.** 19 of the 36 rewritten scripts have no repo-root bootstrap. Today they only work as `python -m scripts.analysis.<x>` from the repo root, or when imported. After the rewrite their bare sibling imports need their own dir on `sys.path`, so each gets the guarded append-bootstrap (§5.2), and R6 proves it.

**Tests:**
- Tests that insert a script dir and import bare are unaffected.
- **47 test files** import the qualified name (§5.4). They resolve today only because `python -m pytest` puts the repo root on `sys.path`.
- Subprocess guards (W3's runtime safety net):
  - `tests/unit/test_unit_execstart_imports.py` runs each venv-python `ExecStart` under its own `WorkingDirectory` with a scrubbed env (`PATH`, `HOME`, `PYTHONPATH=<repo_root>/src` only; `:171-182`). It maps `/home/jon/breezy` onto the checkout's own root (`:93-99`). **Limit:** it runs `--help` (`:137`), so it proves only module-level imports. The `:444` venue import is function-local, and G4b covers it.
  - `tests/unit/test_discovery_pull_exec_import.py`.
  - `tests/unit/test_runtime_import_isolation.py::test_entry_module_imports_cleanly` (`:417`). It imports about 25 qualified entry names in a child process (`:82-156`), including `scripts.analysis.nbp_market_comparison`, `nbp_shadow_parity`, `nbp_shadow_parity_pure` and `discovery_venue_pull`.
  - **New (r5): R6**, which child-imports every rewritten script by its qualified name.

**Incident precedent (binding).** On 2026-09-26 at 16:52Z, `breezy-discovery-pull` died with `ModuleNotFoundError: No module named 'scripts'`. The subprocess guards are mandatory GREEN evidence.

---

## §3 Options (re-evaluated at r5 scope)

| # | Option | Sites touched (HEAD) | Runtime risk | Verdict |
|---|---|---|---|---|
| **B** | **Normalize to bare imports** + 4 dirs added to `mypy_path` (the `scripts/collect` pattern) | 274 statements in 83 files; 3 patch strings; about 37 guarded append-bootstraps in scripts; 1 config line | Low. Only 1 live unit uses `-m` (guarded by G1, G2, G4, G4b). The 19 `-m`-only scripts are covered by R6. Direct-file units are unchanged. | **CHOSEN** |
| Q | Qualified `scripts.<dir>.x` everywhere | 310 errored bare sites plus 40 ignored sites in about 75 files, plus a repo-root bootstrap in about 20 live direct-file unit scripts | **High** (the 09-26 class of failure, about 20 times over) | Rejected |
| I | `python -m` for all units + `__init__.py` | about 20 `ExecStart` edits | High; violates goal 3 | Rejected |
| C | Per-module `ignore_missing_imports` | 1 block | None | Rejected: forbidden silencing |
| P | B, using pytest `pythonpath` instead of per-file test inserts | B minus the test inserts | Session-wide `sys.path` | Deferred |

**Why B, even at near parity.** The qualified form is no longer a small minority: 274 qualified statements against 350 bare sites (310 + 40). B still wins on runtime risk, which is what the operator pays for:
- Every live unit except one runs by direct file, where bare imports work natively (Python puts the script's dir on `sys.path[0]`).
- `scripts/collect` already runs this exact design live.
- Q would add repo-root bootstraps to about 20 live unit scripts.

B also removes the double-module-identity hazard: today one pytest process can hold both `x` and `scripts.analysis.x`, so a monkeypatch on one misses the other. And it removes the ratchet's incentive toward the qualified form (§0).

---

## §4 Measured state at HEAD and projected effect

### 4.0 HEAD measurement (r5, 2026-10-09, `316b50c4`, mypy 2.3.1)

| Metric | Value |
|---|---|
| rc | 1 |
| Summary | `Found 1689 errors in 235 files (checked 1567 source files)` |
| `assess_ratchet(report, CLEAN, CEILINGS)` | `[]` (no failures) |
| CLEAN paths with errors | none |
| Uncovered paths | none |
| `src/breezy/app` | **0** |
| `[unused-ignore]` | 0 |
| `[import-not-found]` | 310 (split in §0), 75 modules |
| Top codes | `no-untyped-def` 572, `import-not-found` 310, `arg-type` 296, `attr-defined` 156, `no-any-return` 73, `type-arg` 72 |

**Per group:**

| Group | `CEILINGS` (`:400-410`) | HEAD measured | r4 S0 (simulated post-STAGE) | Δ vs r4 |
|---|---|---|---|---|
| `src/breezy/analysis` | 3 | 3 | 3 | 0 |
| `scripts/analysis` | 351 | 351 | 352 | **−1** |
| `scripts/archive` | 8 | 8 | 8 | 0 |
| `scripts/venue` | 23 | 23 | 23 | 0 |
| `tests/contract` | 7 | 7 | 7 | 0 |
| `tests/integration` | 1 | 1 | 1 | 0 |
| `tests/strategy` | 6 | 6 | 6 | 0 |
| `tests/support` | 2 | 2 | 2 | 0 |
| `tests/unit` | 1288 | 1288 | 1288 | 0 |
| **Total** | 1689 | 1689 | 1690 | **−1** |

**Explaining the −1.** r4 took the pre-STAGE `scripts/analysis` ceiling as 360. `8e6e77c6` (2026-10-06, "move AUT-4 stats cores to analysis/stats", F7a WP1s) had already lowered it to 359, and STAGE's 8 removals then gave 351, not 352. The removed error is **not** an `import-not-found` error: the per-group `import-not-found` split, the module count, and the `arg-type`/`attr-defined` totals all equal r4's B0. **The seam W3 resolves is therefore unchanged at HEAD.**

### 4.1 Projected post-W3 counts (r5; **not measured**; Stage 0 binds)

**Method.** W3's mypy effect has three parts:
- **(a)** The 310 errored bare imports resolve and their call sites become checked. HEAD's seam is identical to r4's, so r4's measured FIN − S0 delta is carried over.
- **(b)** The 274 qualified → bare renames. Both forms resolve to the same file, so no error count should change. Stage 0 verifies this.
- **(c)** The 40 ignored bare imports resolve. Each of those ignores becomes `[unused-ignore]` and is then removed by §5.3. But the call sites behind them become checked, **regardless of the comment**: an import-line ignore suppresses only that line. r4 measured this for 12 lines. **28 of today's 40 are new since r4, so part (c) is unmeasured.** It can only add errors.

| Group | Today's ceiling | r4 FIN − S0 (measured r4) | **r5 projection (a+b)** | Unmeasured upward component (c) |
|---|---|---|---|---|
| `src/breezy/analysis` | 3 | 0 | 3 | none |
| `scripts/analysis` | 351 | −210 | **141** | 4 new ignored seams (`multisource_blend_inputs_forecast.py:38,41`, `multisource_blend_inputs_obs.py:53`, `multisource_blend_features_build.py:63`); `nbp_learning_nightly.py:571` moved to `:439` |
| `scripts/archive` | 8 | −5 | **3** | **18** new ignored seams in 6 files (`iem_cli_fetch.py`, `lamp_archive_backfill.py`, `metar_routine_store.py`, `metar_routine_minute_probe.py`, `us_source_pfm_reingest.py`, `us_source_backfill.py`) |
| `scripts/venue` | 23 | −12 | **11** | none known (venue gains no ignores; `iem_mos_probe_transport` errors land in its importers) |
| `tests/contract` | 7 | −2 | **5** | none known |
| `tests/integration` / `tests/strategy` / `tests/support` | 1 / 6 / 2 | 0 | 1 / 6 / 2 | none known |
| `tests/unit` | 1288 | −20 | **1268** | 5 new ignored seams (`test_metar_routine_minute_probe.py:236`, `test_metar_routine_store.py:158`, `test_us_source_backfill.py:153`, `test_ambig_latch_phase_a_check.py:22`, `featbuild_fixtures.py:29`) |
| `scripts/ops` (new key) | — | +3 | **≥ 3** | `ambig_latch_phase_a_check.py` (created 10-09) becomes reachable through the resolved `test_ambig_latch_phase_a_check.py:22` import, in addition to r4's `decisions_retention.py:140` triple |
| `scripts/collect` (no key) | 0 (uncovered, clean) | — | **0** | `us_source_collector.py:59` (`iem_mos_probe_transport`) seam |
| `src/breezy/app` | — | 0 | 0 | never pinned (§4.0 r4) |
| **Total** | 1689 | −246 | **≈ 1443** | (c) adds ≥ 0 |

**STAGE resurfacing set.** r4 measured 8 STAGE-removed lines that resurface as 16 errors once W3 resolves imports (r4 §4.1). That set is already inside the r4 FIN − S0 delta. Per `reviews/CF-12-W3-r4-final.md` item 2, `replay_sufficiency_census.py:88` is a **swap**: one `import-not-found` becomes one `attr-defined`. It is not an ignore becoming needed. Stage 0 re-records the set on the merged STAGE commit.

**Re-derivation per r4-final item 1.** The ceilings differ from r4's 3/352/7/1288 only in `scripts/analysis`, by −1, and that −1 is outside the W3 seam. So for every group except the four with a part (c) component, the ±2 band applies directly to the r5 projection. For `scripts/analysis`, `scripts/archive`, `tests/unit`, `scripts/ops` and `scripts/collect`, a value outside the ±2 band is acceptable **only if every error beyond the band is attributed, by file and line, to a seam named in the table above or to a renamed qualified import**. Anything unattributed is a STOP (§7 step 0).

**Ceiling-rise STOP (new, binding).** If the measured post-W3 count of any existing `CEILINGS` group **exceeds its current ceiling**, which is most plausible for `scripts/archive` (8, with 18 newly opened seams), W3 does **not** raise the ceiling. It STOPs and returns to plan review. The sanctioned remedy is a preceding CF-12 typing slice (proposed CF-12-W3e) that fixes the newly visible errors under the parent plan's rules, **never** a raise, an ignore or a `cast`.

### 4.2 What the re-pin contains (projected)

- Every existing ceiling is lowered to its measured value, or left unchanged. Expected: `scripts/analysis` 351 → ~141; `scripts/archive` 8 → ~3; `scripts/venue` 23 → ~11; `tests/contract` 7 → ~5; `tests/unit` 1288 → ~1268.
- **New key `scripts/ops`**, holding:
  - r4's three `decisions_retention.py:140` entries: `(attr-defined, "object" has no attribute "__enter__")`, `(attr-defined, "object" has no attribute "__exit__")`, and `(unused-ignore, Unused "type: ignore" comment)` for the existing `# type: ignore[call-arg]`, which is still at `:140` at HEAD;
  - whatever `ambig_latch_phase_a_check.py` reports, verbatim from Stage 0.

  The existing `decisions_retention.py:140` `call-arg` ignore is **not** touched; W3c owns it.
- **`scripts/collect`.** If it measures > 0 after §5.3, it gets a new key pinned the same way, with follow-up row CF-12-W3f. If it measures 0, it gets no entry, as today. Adding it to `CLEAN` is out of scope (YAGNI) and is recorded as a follow-up suggestion only.
- **No `src/breezy/app` entry.** `CLEAN` is unchanged.

### 4.3 The r2 C1 `trade.py` triage (superseded in r4, unchanged)

The six `trade.py` errors were a `PYTHONPATH` phantom. W3 pins nothing in `src/breezy/app`, creates no W3b, and edits no byte under `src/`.

---

## §5 Chosen design: file-by-file changes

**Where to build.** Use a worktree from `feat/data-capture-and-risk`. Fast-forward it onto the tip first, because agent worktrees can start stale.

**Environment rules for every command:**
- Run with `cd <wt>` and `PYTHONPATH=<wt>/src`.
- Run mypy exactly as in the header.
- pytest uses `/home/jon/breezy/.venv/bin/python -m pytest … --basetemp=$HOME/.cache/breezy-agent/cf12w3-<run>`. Never use `/tmp` (it is tmpfs) or the scratchpad.
- **Never run `uv run`, `uv sync`, `pip` or `git stash`.**
- Run `lint-imports` through the console script from `<wt>` and demand "N kept, 0 broken".
- Run `ruff format` **only on touched files**, never on whole directories.

### 5.0 Runtime-edit carve-out (claimed explicitly)

CF-12 Rev2 forbids runtime edits under CF-12 (`:135`). It also rules (`:121`) that W3's only choices are themselves runtime edits that need their own plan and review. This plan claims that carve-out narrowly.

**Permitted AST differences (only these):**
1. `Import`/`ImportFrom` nodes whose module changes from `scripts.<dir>.x` to `x` (§5.2, §5.4). Here `<dir>` ∈ {`analysis`, `venue`, `archive`, `ops`}.
2. One guarded, append-only `sys.path` bootstrap block per required dir in a §5.2 script (plus `sys`/`Path` imports if absent), and the existing guarded-insert test idiom in §5.4.
3. Three monkeypatch target strings:
   - `tests/unit/test_discovery_venue_pull.py:279` (`"scripts.venue.fee_drift_evidence_pull.build_default_client"` → `"fee_drift_evidence_pull.build_default_client"`);
   - `tests/unit/test_fq_loss_floor_mc_review.py:93`;
   - `tests/unit/test_fq_loss_floor_mc_review.py:113`.

   The last two change `"scripts.analysis.fq_mc_livedata.build_templates"` → `"fq_mc_livedata.build_templates"`.
4. The negative-import rewrite at `tests/unit/test_position_reporting_lag.py:113`, plus `import importlib` if absent.
5. Removal of `# type: ignore[import-not-found]` comments (§5.3). Comments are not part of the AST.
6. Docstring text in the two files named in §5.6.

**Mechanical checker** (scratchpad, not committed; required close-out evidence). It compares `before` (HEAD) with `after` for every touched `.py` file, and it **normalizes; it never deletes an import**:

1. **Import normalization (before tree only):**
   - `from scripts.<dir>.x import …` → `from x import …`, with names, aliases and `level` unchanged.
   - `import scripts.<dir>.x [as m]` → `import x [as m]` (for example `test_discovery_venue_pull.py:355`).
   - `from scripts.<dir> import a [as m], b …` → one `import a [as m]` node per alias, in order, at the same position (for example `test_prereg_precommit_check.py:289`, `test_nbp_market_comparison.py:18`, `blend_veto_descriptive.py:56`).

   **After tree:** any multi-alias `Import` node is split per alias in the same way, because ruff E401 may force the split. No other import node is edited.
2. **Import multiset check.** Compare `Counter(ast.dump(n))` over all `Import`/`ImportFrom` nodes at all depths. `B − A` must be empty. `A − B` must be a subset of `{import sys, from pathlib import Path, import importlib}`, at most once each per file and at module level. `importlib` is allowed only in `test_position_reporting_lag.py`. `sys`/`Path` are allowed only in files that also gain a bootstrap block.
3. **Bootstrap exact-template match** (by `ast.dump` after name substitution):
   - **Script (§5.2):** `<N> = Path(__file__).resolve().parent`, or `<N> = Path(__file__).resolve().parents[1] / "<venue|archive>"`, followed by `if str(<N>) not in sys.path:` whose body is exactly `sys.path.append(str(<N>))`.
   - **Test (§5.4):** `<N> = <R> / "scripts" / "<dir>"`, followed by `if str(<N>) not in sys.path:` whose body is exactly `sys.path.insert(0, str(<N>))`. Here `<R>` is either a module-level name already bound in `before` to `Path(__file__).resolve().parents[k]` (for example `_REPO_ROOT`, `REPO_ROOT`, `_REPO`), or a new `_REPO_ROOT = Path(__file__).resolve().parents[k]` with `k` ∈ {1, 2, 3}.
   - `<N>` must match `^_SCRIPTS_(ANALYSIS|VENUE|ARCHIVE|OPS)_DIR$`.
   - Any other `if`/`for` touching `sys.path` fails the check. Pre-existing bootstrap statements (for example the `for _entry in (...)` loops) must be byte-for-byte AST-unchanged. W3 never edits an existing bootstrap tuple; it adds a new template block after it instead.
4. **Strip only what is new:**
   - (a) the allowlisted added imports;
   - (b) template-matched blocks;
   - (c) `_REPO_ROOT` / `_SCRIPTS_*_DIR` assignments, only if that name is unassigned in `before`.
5. **Named literal and docstring sites.** Replace the 3 strings from rule 3 and the `:113` negative import with a sentinel in both trees, after asserting each `after` value equals the planned text exactly. Drop docstrings only in the two §5.6 files.
6. **Equality.** `ast.dump(normalized_before) == ast.dump(stripped_after)` per file. Imports therefore stay **in place**.

**Positive controls** (run once and recorded): each of the following must make the checker fail:
- a deleted import;
- an added `import os`;
- an `insert(0)` bootstrap in a §5.2 script;
- an edited pre-existing bootstrap tuple;
- an altered pre-existing `_REPO_ROOT`;
- a one-token logic change.

Any real failure stops the slice and goes to the bug-ticket path. `pyproject.toml` and `test_mypy_ratchet.py` are reviewed directly.

### 5.1 Config

- `pyproject.toml:418`: `mypy_path = "src:scripts/collect"` → `mypy_path = "src:scripts/collect:scripts/analysis:scripts/venue:scripts/archive:scripts/ops"`. This keeps the existing string form and **keeps `scripts/collect`**.
- **Rewrite the stale comment `pyproject.toml:397-411`.** It says both paths "agree on `scripts.analysis.discovery_set_equality`" (`:409`), which W3 makes false. New text:
  - script dirs are mypy bases, as `scripts/collect` already is, because scripts import siblings by bare name;
  - `explicit_package_bases` therefore names them bare;
  - a package-qualified `scripts.<dir>.x` import recreates the duplicate-module exit 2 and is forbidden (R2);
  - basenames across the five bases must be unique (R5).

  The `src` paragraph (`:413-417`) and the `files` list are unchanged. `scripts/ops` becomes a base only; it is not added to `files`. `scripts/operator` and `scripts/ci` are not added.

### 5.2 Scripts: 36 files in `scripts/analysis`, imports plus guarded append-bootstraps

**Bootstrap rule (r5, uniform).**
- Every `scripts/analysis` file whose qualified imports are rewritten gets the guarded **append** of its own dir, **unless** a pre-existing module-level statement *before its first sibling import* already puts that dir on `sys.path`. At HEAD that is true of `multisource_blend_features_build.py:58-61`, `multisource_blend_inputs_forecast.py:33-36` and `multisource_blend_inputs_obs.py:48-51`.
- A file that imports from another dir also gets a guarded append of `parents[1] / "<dir>"`, with one named exception (below). At HEAD those files are:
  - `discovery_venue_pull.py` → `venue`;
  - `multisource_blend_inputs_forecast.py:59` → `archive`;
  - `multisource_blend_inputs_lamp.py:48` → `archive`;
  - `multisource_blend_inputs_obs.py:46,274` → `archive`.
- Why append and not insert: under `-m`, the CWD (repo root) is `sys.path[0]`. Appending can never shadow the stdlib or the venv, and R5 guarantees no duplicate basename exists anywhere earlier on the path. Under direct-file execution, the guard makes the own-dir block a no-op.
- Pre-existing `insert(0)` bootstraps are **not** changed.
- Expected at HEAD: **33 own-dir blocks + 4 cross-dir blocks**. Stage 0 records the exact list.

**Named exception: `multisource_blend_features_build.py` (binding).** The file is **797 lines**, and `tests/unit/test_multisource_blend_featbuild_review_fixes.py:456` asserts `< 800`. That test must never be relaxed. A 3-line archive block would make it 800 and fail. The file therefore gets **no new block**. Its `:123` `from iem_mos_backfill import ModelMixError` resolves because `:85` imports `multisource_blend_inputs_forecast` first, and that module's own module-level `archive` append runs at import time. This is the deterministic statement order of one module, and R6 proves it in a child process. Stage 0 STOPs if `:85` no longer precedes the archive import, or if the line count at HEAD is no longer ≤ 797. Comment-only §5.3 edits in this file do not change its line count.

| File | Qualified-import lines (HEAD) | New blocks |
|---|---|---|
| `discovery_venue_pull.py` | 31, 305, 444 | own + venue (`sys` `:22` and `Path` `:28` already imported) |
| `blend_veto_descriptive.py` | 56, 57, 58 | own |
| `fq_kill_power_report.py` | 37–39, 48–53 | own |
| `fq_loss_floor_mc.py` | 27, 28, 34, 42, 43, 54, 55, 65, 66 | own |
| `fq_loss_floor_mc_draw.py` | 25, 39 | own |
| `fq_loss_floor_mc_e2.py` | 13, 14, 15 | own |
| `fq_loss_floor_mc_engine.py` | 17–19, 31–33, 42, 51, 52 | own |
| `fq_loss_floor_mc_gate.py` | 21, 22 | own |
| `fq_loss_floor_mc_outer.py` | 11, 12, 99, 107 | own |
| `fq_loss_floor_mc_rates.py` | 10, 11, 12 | own |
| `fq_loss_floor_mc_report.py` | 12, 13, 28, 29, 38, 39 | own |
| `fq_loss_floor_mc_rows.py` | 175, 386 | own |
| `fq_loss_floor_mc_sim.py` | 15 | own |
| `fq_loss_floor_np_bound.py` | 27, 35, 36, 42, 52, 53, 57, 58, 80 | own |
| `fq_loss_floor_np_stat.py` | 19, 20, 21 | own |
| `fq_mc_livedata.py` | 41, 42, 49 | own |
| `fq_mc_type1.py` | 28, 29, 39 | own |
| `fq_resume_n_mc.py` | 60, 82, 100 | own |
| `multisource_blend_features_build.py` | 82–85, 93–96, 105, 113, 122, 123 | **none (named exception)** |
| `multisource_blend_inputs_anchors.py` | 18, 19, 20 | own |
| `multisource_blend_inputs_forecast.py` | 58, 59 | archive (own dir pre-existing) |
| `multisource_blend_inputs_io.py` | 14 | own |
| `multisource_blend_inputs_lamp.py` | 48 | own + archive |
| `multisource_blend_inputs_obs.py` | 46, 64, 274 | archive (own dir pre-existing) |
| `multisource_blend_inputs_pins.py` | 14, 15, 22 | own |
| `multisource_blend_inputs_report.py` | 17, 18, 19 | own |
| `multisource_blend_lag_arm.py` | 23 | own |
| `multisource_blend_pin_guards.py` | 32 | own |
| `multisource_blend_sidecar.py` | 18, 19 | own |
| `multisource_blend_skill.py` | 66, 70, 71, 80, 85, 86, 97 | own |
| `nbp_backfill.py` | 107 | own |
| `nbp_market_comparison.py` | 53, 54, 64 | own if Stage 0 finds its existing bootstrap (`:20-25`) lacks its own dir |
| `nbp_shadow_parity.py` | 86 | own |
| `no_longshot_pooled_test.py` | 62, 63 | own |
| `prereg_amendment_check.py` | 45–48 | own |
| `prereg_precommit_check.py` | 41, 42 | own |

- The line lists are a HEAD inventory and a cross-check only. **R2's AST report is authoritative.**
- No logic, argument or output changes (§5.0 checker). Add `# noqa: E402` only where ruff reports E402.
- **Source-shape tests that read these files must stay green unmodified:**
  - `test_multisource_blend_featbuild_review_fixes.py:444-470` (`< 800` lines; no `.read_bytes()`; function length);
  - `test_multisource_blend_runner_fixes.py:189` (`run` < 40 lines, functions < 80);
  - `test_multisource_blend_skill.py:558` (banned tokens);
  - `test_prereg_precommit_check.py:295` (banned literals);
  - `test_multisource_blend.py:261-270` (`open_holdout` absent).

  Module-level 3-line blocks do not change function lengths.

**Provenance-recorded files (r5; disposition for peer review).** At HEAD, `git hash-object` of `fq_loss_floor_mc.py` = `1b9c05d0…` and of `fq_loss_floor_np_stat.py` = `927109a9…`. These **equal** the blob hashes recorded in `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json:1619` (`script_git_sha`) and `docs/evidence/f5/fq_loss_floor_np_bound_seed20261009.json:6` (`stat_blob_sha`). The F5 A1 amendment (`F5_prereg_v2_amendment_A1.json:50-56`) cites the MC module and `mc_git_head eedbb99d`.
- **No code compares these recorded hashes with the working tree.** A read-only search at HEAD finds them only as values written at run time (`fq_loss_floor_mc.py:368`, `fq_loss_floor_np_bound.py:312`). `check_frozen_blob` verifies the amendment JSON itself, not the module.
- W3 **must** rewrite both files: a single remaining qualified import is a mypy exit 2.
- After W3 the recorded hashes become historical. Reproduction stays exact through `mc_git_head` and the recorded blobs, which remain in git.
- W3 edits **no** evidence file, amendment, or `PREREG.json`.
- Stage 0 re-runs the search. If any verifier compares these blobs with the working tree, W3 **STOPs** and returns to review.
- The commit body and the W3 execution log record old → new blob hashes for both files.

### 5.3 Remove now-unused `# type: ignore[import-not-found]` (comment-only), driven by the report

- **Edit list.** It comes from the implementer's own post-§5.1/5.2/5.4 mypy report: every `[unused-ignore]` line whose unused code is `import-not-found` is a target, and nothing else is.
- **Cross-check only (40 lines at HEAD):**
  - `scripts/analysis` (14): `multisource_blend_inputs_forecast.py:38,41`; `whole_tape_paper_replay.py:43`; `multisource_blend_inputs_obs.py:53`; `replay_sufficiency_census.py:94`; `tape_instruments.py:23`; `multisource_blend_features_build.py:63`; `nbp_learning_nightly.py:31,439`; `current_rung_hold_paper_replay.py:69`; `nbp_skill_study.py:88-91`.
  - `scripts/archive` (18): `iem_cli_fetch.py:88,97,103,107`; `lamp_archive_backfill.py:79,85,97`; `metar_routine_store.py:66,67`; `metar_routine_minute_probe.py:68,74,75`; `us_source_pfm_reingest.py:24,29`; `us_source_backfill.py:62,68,1002,1011`.
  - `scripts/collect` (1): `us_source_collector.py:59`.
  - `tests/unit` (7): `test_metar_routine_minute_probe.py:236`; `test_metar_routine_store.py:158`; `test_us_source_backfill.py:153`; `test_ambig_latch_phase_a_check.py:22`; `featbuild_fixtures.py:29`; `test_nbp_skill_study.py:33,525`.

  A mismatch is recorded, not reconciled by hand.
- **Keep every trailing `# noqa: E402`.** Remove only the `  # type: ignore[import-not-found]` text. Where an ignore lists other codes, drop only `import-not-found`.
- **Re-run mypy afterwards.** The count of `unused-ignore` for `import-not-found` must be 0, and no group may rise.
- **Not touched:** the `decisions_retention.py:140` `[call-arg]` ignore.
- These edits are comment-only and add no lines. The `scripts/archive` and `scripts/collect` edits do not change those directories' line-capped files (`test_iem_cli_fetch.py:794` `< 800`).

### 5.4 Tests: 47 files, imports plus `sys.path`

Each file gets the module-level test template (§5.0 rule 3) before its first bare import, unless a pre-existing module-level statement already inserts the needed dir. Then its qualified imports are rewritten.

| File | Qualified lines (HEAD) | Dirs |
|---|---|---|
| `tests/contract/test_fq_loss_stop_writer_allowlist.py` | 33 | analysis (existing loop `:22-25` inserts root and `src` only; new block after it; `<R>` = `REPO_ROOT`) |
| `tests/strategy/forecast_quantile_ladder/test_lst_margin_horizon.py` | 25 | analysis |
| `tests/unit/featbuild_fixtures.py` | 43 | archive |
| `tests/unit/test_c1_lag_evidence.py` | 15, 16 | analysis |
| `tests/unit/test_discovery_set_equality.py` | 16, 725 | analysis |
| `tests/unit/test_discovery_venue_pull_memory.py` | 22, 23, 77 | analysis |
| `tests/unit/test_discovery_venue_pull.py` | 19, 355, plus string `:279` | analysis, venue |
| `tests/unit/test_fq_evaluate_shim.py` | 25–27 | analysis |
| `tests/unit/test_fq_kill_power_report.py` | 23–29 | analysis |
| `tests/unit/test_fq_live_analysis_point_cdf_parity.py` | 65 | analysis |
| `tests/unit/test_fq_loss_floor_mc_e2.py` | 12–14, 21–24 | analysis |
| `tests/unit/test_fq_loss_floor_mc_gate.py` | 10, 30, 31 | analysis |
| `tests/unit/test_fq_loss_floor_mc_review.py` | 19–24, 29, 30, 37, 38, plus strings `:93`, `:113` | analysis |
| `tests/unit/test_fq_loss_floor_mc_rows.py` | 14–18 | analysis |
| `tests/unit/test_fq_loss_floor_mc_solve.py` | 11, 17 | analysis |
| `tests/unit/test_fq_loss_floor_np_bound.py` | 12–15 | analysis |
| `tests/unit/test_fq_resume_n_mc.py` | 21–23 | analysis |
| `tests/unit/test_lamp_archive_backfill.py` | 45, 46 | analysis, archive |
| `tests/unit/test_multisource_blend_featbuild_review_fixes.py` | 33–37 | analysis |
| `tests/unit/test_multisource_blend_featbuild_runner.py` | 18 | analysis |
| `tests/unit/test_multisource_blend_features_build.py` | 33, 34, 520, 843, 915 | analysis, archive |
| `tests/unit/test_multisource_blend_inputs_forecast.py` | 22–25 | analysis, archive |
| `tests/unit/test_multisource_blend_inputs_lamp.py` | 19–21 | analysis, archive |
| `tests/unit/test_multisource_blend_inputs_obs.py` | 23, 24, 71, 325, 352 | analysis |
| `tests/unit/test_multisource_blend_lag_arm_and_sidecar.py` | 19 | analysis |
| `tests/unit/test_multisource_blend_obs_coverage.py` | 18, 19 | analysis |
| `tests/unit/test_multisource_blend_pin_guards.py` | 19–23, 359, 373, 390, 397, 415, 432, 447 | analysis |
| `tests/unit/test_multisource_blend_runner_fixes.py` | 25–27 | analysis |
| `tests/unit/test_multisource_blend_skill.py` | 26–28 | analysis |
| `tests/unit/test_multisource_blend_station_year_exclusion.py` | 23–26 | analysis |
| `tests/unit/test_nbp_backfill.py` | 37, 702, 745 | analysis |
| `tests/unit/test_nbp_lag_census.py` | 13 | analysis |
| `tests/unit/test_nbp_market_comparison.py` | 18 | analysis |
| `tests/unit/test_nbp_shadow_parity_live.py` | 28, 53, 54 | analysis |
| `tests/unit/test_nbp_shadow_parity_load.py` | 15, 22, 133, 189, 345 | analysis |
| `tests/unit/test_nbp_shadow_parity_no_side_synthetic.py` | 46, 47 | analysis |
| `tests/unit/test_nbp_shadow_parity_pure.py` | 27 | analysis |
| `tests/unit/test_nbp_skill_study.py` | 36 (already inserts the dir) | analysis |
| `tests/unit/test_nbp_window_available_at.py` | 13 | analysis |
| `tests/unit/test_no_longshot_pooled_test.py` | 34, 35 | analysis |
| `tests/unit/test_no_longshot_r32_rulings.py` | 17, 18 | analysis |
| `tests/unit/test_prereg_amendment_check.py` | 31–34, 66, 169, 501 | analysis |
| `tests/unit/test_prereg_precommit_check.py` | 17, 289 | analysis |
| `tests/unit/test_release_census.py` | 27 | analysis |
| `tests/unit/test_release_timing_b0.py` | 24 | analysis |
| `tests/unit/test_us_source_backfill.py` | 37, 38 | analysis, archive |
| `tests/unit/test_us_source_pfm_history.py` | 19 | archive |

- **Contract test (binding).** `tests/contract/test_fq_loss_stop_writer_allowlist.py` changes in its import line and gains one template block, nothing else. Its assertion code, `_WRITERS`, `_NEW_CALLERS`, `_GRANDFATHERED_CALLERS` and scan roots are AST-unchanged (§5.0 checker), and it must pass unmodified. Its `tests.support.*` import is not a script import and is untouched.
- **Not changed (code):** the qualified **strings** in `test_runtime_import_isolation.py:82-156`, `test_unit_execstart_imports.py`, `test_discovery_pull_exec_import.py`, `test_polymarket_us_readonly_guard.py:1196` and `test_registry_resolver_guards.py:151`. They model production child-process invocation or guard behaviour, and are not patch targets.
- **Negative import** `tests/unit/test_position_reporting_lag.py:113` → `importlib.import_module("breezy.runtime.position_reporting_lag")`. The assertion and semantics are the same.

### 5.5 Ratchet constants and pins (`tests/unit/test_mypy_ratchet.py`)

- **Lower each changed ceiling** to the measured value. The ratchet's "lower the ceiling to N" message is the authority, and the §4.1 projections are cross-checks only. Use the dated comment `# CF-12-W3 <exec date> (base <sha>, post-CF-12-STAGE 66d7fe74): sibling-script imports resolved`. Keep STAGE's comment (`:396-399`).
- **No value may exceed today's ceiling** (§4.1 ceiling-rise STOP).
- **Add `"scripts/ops": <m>`** with the comment `# CF-12-W3 <exec date>: scripts/ops (decisions_retention.py:140 attr-defined x2 + unused-ignore[call-arg]; ambig_latch_phase_a_check.py <file:line list>); measured at Stage 0, HEAD <sha>, PYTHONPATH=<wt>/src. Fixes owned by CF-12-W3c (decisions_retention) and CF-12-W3g (ambig_latch_phase_a_check). Exact multiset pinned by R4.` If `ambig_latch_phase_a_check.py` reports 0, drop its clause and W3g.
- **Add `"scripts/collect": <c>`** only if `<c>` > 0, with the same comment form and follow-up CF-12-W3f.
- **`W3_PINNED_ERRORS: Final[dict[str, tuple[tuple[str, str, int], ...]]]`**, one key per new entry. It maps each key to a sorted tuple of `(error_code, message, count)`, a **multiset** with line numbers excluded. Populate it verbatim from Stage 0. The counts per key must sum to `CEILINGS[key]` (asserted in R4).
- `CLEAN` is unchanged.

### 5.6 Docs and stale comments

- **Test docstrings:** `tests/unit/test_discovery_pull_exec_import.py` (module docstring, `:1-27`) and `tests/unit/test_unit_execstart_imports.py` (module docstring, `:6` and `:25`). Each gets a dated sentence appended: "CF-12-W3 (<date>): the script now imports its siblings bare and self-bootstraps `scripts/analysis` and `scripts/venue`; this guard still models the unit's `-m` invocation unchanged." This is docstring-only, and the checker strips docstrings only in these two files.
- `pyproject.toml:397-411` comment: rewritten in §5.1.
- `deploy/systemd/breezy-discovery-pull.service` comment: deferred to **CF-12-W3d** (unit edits are out of scope by goal 3).
- **`PROGRESS.md`:** close CF-12-W3 with the SHA and measured counts. Add CF-12-W3c (`decisions_retention` opener), CF-12-W3d (unit comment), and, if they are measured non-empty, CF-12-W3f (`scripts/collect` seam) and CF-12-W3g (`ambig_latch_phase_a_check` errors). **No W3b.** If the §4.1 ceiling-rise STOP fired, add CF-12-W3e instead and do not close W3.
- **CF-12 Rev2 execution log:** append the W3 entry covering the §5.0 carve-out claim, checker result, R6 and G5 results, the `scripts/analysis` 351 explanation (§4.0), and the §5.2 provenance blob hashes (old → new).

---

## §6 RED → GREEN tests

| ID | Test (in `tests/unit/test_mypy_ratchet.py` unless noted) | RED at HEAD | GREEN after |
|---|---|---|---|
| R1a | `test_import_not_found_lines_are_extracted_with_their_module_names`: pure parser test on fake mypy text, for a new helper `parse_import_not_found(output) -> list[tuple[str, str]]`. It drops notes and keeps only `[import-not-found]` lines. | Fails (helper absent) | Passes |
| R1b | `test_full_config_mypy_reports_zero_import_not_found`. A new module-scoped `mypy_output` fixture holds STAGE's subprocess call verbatim (`:423-432`: `_mypy_subprocess_env()`, `check_mypy_exit`) and returns `output`. `mypy_report` becomes `parse_mypy_report(mypy_output)`. It is still **one** mypy run. Exit 2, a crash, or `(errors prevented further checking)` raises before any parse. STAGE's ported hardening tests (`:256-279`) are the evidence for that guard; no duplicate is added. The test asserts `parse_import_not_found(mypy_output) == []`. | **Fails with 310 entries** | 0 |
| R2 | `tests/unit/test_scripts_import_convention.py::test_no_package_qualified_sibling_script_import`. It AST-scans **exactly** `sorted((_REPO_ROOT/"scripts").rglob("*.py")) + sorted((_REPO_ROOT/"tests").rglob("*.py"))`, skipping `__pycache__`. A parse error fails the test, and a file count > 0 is asserted as a vacuity guard. It flags `Import`/`ImportFrom` of `scripts.{analysis,venue,archive,ops}[.…]` and `from scripts import <dir>`. It also flags a string first argument with those prefixes in calls to `monkeypatch.setattr`, `monkeypatch.delattr`, `patch`, `mock.patch` and `unittest.mock.patch`. Other strings are legal. Positive controls: one synthetic import and one synthetic `monkeypatch.setattr("scripts.venue.x.y", …)` each produce a hit; a synthetic `subprocess.run([... "-m", "scripts.analysis.x"])` produces none. | **Fails: 274 import statements in 83 files + 3 patch strings** (HEAD inventory; Stage 0 records R2's own AST count) | 0 |
| R3 | `test_mypy_stays_within_the_cf12_clean_set_and_ceilings` (existing). | Passes at HEAD. After §5.1–5.4 without §5.5, it fails with one "lower the ceiling" message per changed group, plus "no CLEAN or CEILINGS entry" for each `scripts/ops` file (and `scripts/collect`, if non-zero). Any `src/breezy/app` message is a STOP (wrong env). Any "above ceiling" message is a STOP (§4.1). | Passes after §5.5 |
| R4 | `test_w3_pinned_packages_carry_exactly_the_pinned_errors`. A pure helper `pinned_fingerprint(output, prefix) -> Counter[tuple[str, str]]` (notes and line numbers dropped). For each `W3_PINNED_ERRORS` key, the test asserts multiset equality with the pin and `sum(n) == CEILINGS[key]`, and prints the missing and surplus `Counter`s on failure. Helper controls: (i) exact match passes; (ii) a swapped `(code, message)` fails; (iii) **duplicate-message control:** a fixed error replaced by a duplicate of another pinned entry fails; (iv) a count decrement fails. | Fails (pin absent) | Passes |
| R5 | `tests/unit/test_scripts_import_convention.py::test_script_basenames_are_unique_and_unshadowed`. It covers **exactly** `sorted((_REPO_ROOT/"scripts"/d).glob("*.py"))` for `d` in (`analysis`, `venue`, `archive`, `ops`, **`collect`**): the five mypy bases, non-recursive, `_`-prefixed files included, `__init__.py` excluded, with a vacuity guard. Checks: (a) basenames are pairwise unique across dirs; (b) none is in `sys.stdlib_module_names`; (c) **hard check:** none is in the committed `R5_DECLARED_DEP_TOPLEVELS` snapshot (the top-level import names of declared dependencies, generated at Stage 0); (c′) **advisory only:** a live-venv scan raises `R5VenvShadowWarning` for any collision not in `R5_VENV_SHADOW_ALLOWLIST = frozenset()`. Positive controls on `tmp_path`: a cross-dir duplicate, `json.py`, and a snapshot member each fail; a venv-only name only warns. | Passes at HEAD (168 files, 0 collisions); RED is the positive controls | Passes |
| **R6 (new, r5)** | `tests/unit/test_scripts_import_convention.py::test_rewritten_script_imports_under_its_qualified_name`, parametrized over a committed `W3_REWRITTEN_SCRIPTS: Final[tuple[str, ...]]` (the 36 §5.2 files, from Stage 0). For each file it runs a child `/home/jon/breezy/.venv/bin/python` (it actually uses `sys.executable`) with `-c "import scripts.analysis.<x>"`, with `cwd=_REPO_ROOT` and the scrubbed env of `test_unit_execstart_imports.py:171-182` (`PATH`, `HOME`, `PYTHONPATH=<root>/src`). It asserts rc 0 and prints stderr on failure. This proves that every rewritten script, including the 19 without a repo-root bootstrap and the `features_build` named exception, still imports by the qualified name that `-m` uses. The test file imports no `breezy.adapters.polymarket_us.exec` module. **Cost budget:** Stage 0 times the 36 children at HEAD (where qualified imports already work), and if the total exceeds 90 s, STOP and return to review. | Passes at HEAD (qualified resolves through the CWD). **Required RED:** with the own-dir block omitted from `fq_loss_floor_mc_draw.py`, its parameter fails with `ModuleNotFoundError`; with the archive block omitted from `multisource_blend_inputs_forecast.py`, both `…inputs_forecast` and `…features_build` fail. Record both, then restore. | Passes |
| G1 | `test_unit_execstart_imports.py` and `test_discovery_pull_exec_import.py` (existing, assertion code unmodified). | Pass | Must still pass. **Required RED:** with the own-dir bootstrap omitted from `discovery_venue_pull.py`, `test_unit_execstart_imports` fails with `ModuleNotFoundError: … discovery_set_equality`. Record, then restore. G1 cannot see the venue leg (`:444` is lazy); G4b covers it. |
| G2 | `test_runtime_import_isolation.py::test_entry_module_imports_cleanly` (existing, unmodified). | Pass | Still passes for every listed entry. Same omit-bootstrap RED for `nbp_shadow_parity`. |
| G3 | Each of the 47 §5.4 files run **alone** (`pytest <file>`) from `<wt>` with `PYTHONPATH=<wt>/src`. | — | Pass (no order dependence). |
| G4 | Smoke of the `-m` path **in the worktree**: `cd <wt> && env -i PATH=/usr/bin HOME=$HOME PYTHONPATH=<wt>/src /home/jon/breezy/.venv/bin/python -m scripts.analysis.discovery_venue_pull --help`. | — | Exit 0. Repeated after merge from `/home/jon/breezy` without `PYTHONPATH`, exactly as the unit runs it. |
| G4b | **Real-resolution check of the `:444` path, worktree** (r3 E2 design; line numbers re-based). Run `cd <wt> && env -i PATH=/usr/bin:/bin HOME="$HOME" PYTHONPATH=<wt>/src BREEZY_USER_AGENT=cf12-w3-g4b-placeholder /home/jon/breezy/.venv/bin/python -c "$(cat <scratch>/g4b_probe.py)"`. The probe:<br>1. asserts `sys.path[0] in ('', os.getcwd())`;<br>2. imports `scripts.analysis.discovery_venue_pull` as `m`;<br>3. runs `asyncio.run(m._main_async([...empty node-log dir, scratch out dir, user agent...], now=datetime(2026,1,1,18,0,tzinfo=UTC)))`.<br>That executes `:444`, then `build_default_client(...)` at `:448` (construction only). `run_discovery_pull` finds no trigger, and because the real clock (`time.time_ns`) is past that day's deadline, it returns NO-PULL at `:348-360`, **before** `build_discovery_provider` (`:368`) and `load_all_async` (`:371`). **No network I/O.**<br>The probe then asserts:<br>- `sys.modules['fee_drift_evidence_pull'].__file__ == '<wt>/scripts/venue/fee_drift_evidence_pull.py'`;<br>- `'scripts.venue.fee_drift_evidence_pull'` and `'scripts.analysis.discovery_set_equality'` are absent from `sys.modules`;<br>- `discovery_set_equality` resolves under `<wt>/scripts/analysis/`;<br>- rc 0, and the NO-PULL artifact exists.<br>It prints `G4B-OK`. **Venue-leg RED:** with only the venue append removed, G1 passes and G4b fails with `ModuleNotFoundError: No module named 'fee_drift_evidence_pull'`. Record both, then restore. | — | `G4B-OK`. **Post-merge repeat** via `systemd-run --user --wait --pipe --collect`, using the unit's `WorkingDirectory`, `EnvironmentFile=` (`breezy.env`, `-alerts.env`), `ProtectHome=read-only`, `MemoryMax=256M` and `UMask=0077`, with scratch paths outside `$HOME` and never the live evidence dir. Env-file values are never read or printed. |
| **G5 (new, r5)** | **NO-SEND classification invariance** (scratchpad, not committed). For every touched `.py` file, compute `is_venue_touching(path, tree)` and `find_probe_importers(path, source)` (imported read-only from `tests/unit/test_polymarket_us_readonly_guard.py`) on `before` and `after`, and assert they are identical. Rationale: those classifiers key on the SDK root, `breezy.adapters.*` packages, host and name strings, and the probe module's bare or dotted name (`:340-390`, `:1170-1197`), never on `scripts.<dir>` qualification. So W3 must leave every classification unchanged. Also run `test_polymarket_us_readonly_guard.py` in full. | — | Identical; guard passes |

**Order.** Write R1a, R1b, R2, the R4 helper (with the duplicate-message control), the R5 positive controls and R6 first, and capture RED. Then do §5.1–5.4, then §5.5. Finally run the full gate `scripts/ci/run_tests_no_egress.sh` and read `EXIT=0` **before** any push.

Cost: R1b and R4 share the one fixture mypy run (about 30 s CPU at HEAD). R2 and R5 take under a second. R6 is bounded at 90 s by its Stage 0 budget.

---

## §7 Build sequence

0. **Stage 0 (re-measure, read-only)** in `<wt>`. Every mypy run uses the header command with `PYTHONPATH=<wt>/src` and a fresh cache, and starts only when `free -g` shows ≥ 6 GB available and no heavy job is running.
   - **Precondition.** All of these must hold:
     - `git merge-base --is-ancestor 66d7fe74 HEAD`;
     - `check_mypy_exit` is defined and called by the fixture;
     - `CEILINGS` reads `src/breezy/analysis` 3, `scripts/analysis` 351, `scripts/archive` 8, `scripts/venue` 23, `tests/contract` 7, `tests/integration` 1, `tests/strategy` 6, `tests/support` 2, `tests/unit` 1288, or lower values pinned by a later recorded slice, in which case re-derive §4.1 from the new values;
     - `mypy_path` reads `"src:scripts/collect"`.

     Otherwise STOP.
   - **Baseline at `<wt>` HEAD:** exit 1, 0 `[unused-ignore]`, `src/breezy/app` = 0, 310 `[import-not-found]`, and per-group counts equal to `CEILINGS`.
   - **Inventories:** re-generate R2's AST count (HEAD 274 + 3), the §5.3 ignore list (HEAD 40), the §5.2 bootstrap list (HEAD 33 + 4), and `W3_REWRITTEN_SCRIPTS` (HEAD 36). Confirm `multisource_blend_features_build.py` is ≤ 797 lines and that its `:85` import precedes its archive import.
   - **T2 twice** (§5.1/5.2/5.4 applied on a scratch copy of `<wt>`, with that copy's own `PYTHONPATH`): the two runs must be identical. Then **FIN twice** (T2 + §5.3 + §5.4 negative import): also identical. Record per-group counts, the `scripts/ops` and `scripts/collect` `(code, message, count)` multisets, and the STAGE-resurfacing set (r4: 8 lines, 16 errors).
   - Generate the `R5_DECLARED_DEP_TOPLEVELS` snapshot. Time R6's 36 children at HEAD.
   - Re-run the §5.2 provenance search and record `git hash-object` for the two provenance-recorded files.
   - Run the G4b dry-run at HEAD.
   - **STOP and return to plan review** if any of these hold:
     - the precondition fails;
     - any `src/breezy/app` error appears in any run;
     - **any FIN group exceeds its current ceiling** (§4.1);
     - a group without a part (c) component differs from its §4.1 projection by more than ±2;
     - a group with a part (c) component differs by more than ±2 and the excess is not fully attributed by file and line to a named seam;
     - the T2 or FIN double runs differ;
     - an uncovered path appears outside `scripts/ops` and `scripts/collect`;
     - any basename collides with the snapshot;
     - the features_build line or order constraint fails;
     - R6 exceeds 90 s;
     - a working-tree verifier of the provenance blobs exists;
     - mypy exits 2 on T2 (a qualified import was missed).
1. Write R1a, R1b, R2, the R4 helper test, R5 and R6; capture RED.
2. §5.1 config, §5.2 scripts, §5.4 tests. R2 GREEN.
3. Run mypy, do the §5.3 ignore removal from the report, and re-run mypy.
4. §5.5 ceilings, new keys and `W3_PINNED_ERRORS`. R1b, R3 and R4 GREEN.
5. G1/G2/R6 omit-bootstrap RED checks and the G4b venue-leg RED check; restore. G1–G4b, R6 and G5 GREEN; G3 per file. `ruff check` and `ruff format --check` on touched files only (then `git status` for stray reformatting). `lint-imports` from `<wt>` must print "N kept, 0 broken".
6. §5.0 checker: positive controls first, then every touched `.py` file; record both outputs.
7. §5.6 docstring and comment updates; re-run the §5.0 checker.
8. **Focused gate** (with `PYTHONPATH=<wt>/src` and `--basetemp` under `~/.cache`; read the exit code of every run):
   - `tests/unit/test_mypy_ratchet.py`
   - `tests/unit/test_scripts_import_convention.py`
   - all of `tests/contract/`
   - `tests/unit/test_autonomy_*.py`
   - `tests/unit/test_polymarket_us_readonly_guard.py`
   - `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` (exec pin)
   - `tests/unit/analysis/stats/test_moved_source_pinned.py`
   - `tests/unit/test_runtime_import_isolation.py`
   - `tests/unit/test_unit_execstart_imports.py`
   - `tests/unit/test_discovery_pull_exec_import.py`
   - `tests/unit/test_prereg_amendment_check.py`
   - `tests/unit/test_prereg_precommit_check.py`
   - the multisource_blend source-shape tests named in §5.2
   - every edited test module, plus the test module of every edited script

   Then the **full gate** `scripts/ci/run_tests_no_egress.sh`, which must give EXIT=0.
9. **Independent review:**
   - `python-reviewer` on the diff, with `PYTHONPATH=<wt>/src` in its brief.
   - `security-reviewer`: **trigger met in r5, narrowly.** Run it on the G5 evidence and the bootstrap blocks only. W3 now edits a contract test and 36 scripts adjacent to F5 prereg provenance, though no permit, egress, credential or `src/` code.
10. Commit by explicit path (never `git add -A`), with the commit body carrying the per-group table, inventories and provenance hashes. Merge. Update the PROGRESS and Rev2 log (§5.6).

**Activation:** no restart. The supervisor and node never import `scripts/`. `breezy-discovery-pull` is a timer-fired oneshot: after merge, run the G4 primary-tree smoke and the G4b `systemd-run` check, then confirm the next scheduled run exits 0 (`systemctl --user status breezy-discovery-pull.service`; journal). The unit is LIVE only once its first scheduled success has been seen.

---

## §8 Rollback

- **W3 is the only open plan; STAGE has landed.** A bare `git revert` of W3 conflicts on the `CEILINGS` lines and the fixture split. The rollback is therefore always the **manual re-pin**:
  1. In a worktree, run `git revert --no-commit <W3 sha>`.
  2. Resolve `test_mypy_ratchet.py` by hand, keeping STAGE's `check_mypy_exit` and blocker guard.
  3. Re-measure mypy with `PYTHONPATH=<wt>/src`.
  4. Set every `CEILINGS` value to the measured N, and drop `scripts/ops`, `scripts/collect` and `W3_PINNED_ERRORS`.
  5. Run the full gate and read `EXIT=0` before any push.

  The measured ceilings return to today's values (§4.0). None may be raised above its measured value, and `CLEAN` is unchanged.
- No unit, wrapper, data, state DB or venv change, so no `daemon-reload` and no restart.
- If `breezy-discovery-pull` fails after merge with `ModuleNotFoundError`, roll back as above. The next timer run self-heals. A missed run loses one evidence snapshot and has no trading impact.

---

## §9 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The `-m` discovery unit loses a sibling import (09-26 repeat) | Low | One evidence run lost | G1 + G4 (worktree and post-merge) + omit-bootstrap RED |
| The lazy `:444` venue import fails only on a real run | Low | One evidence run lost | G4b (worktree + post-merge `systemd-run`); venue-leg RED |
| **One of the 19 `-m`-only scripts loses a sibling import** (r5) | Medium (36 new bootstraps) | Operator or agent analysis run fails | **R6** child import of every rewritten script, with RED controls |
| **A newly opened seam pushes a group above its ceiling** (r5; most likely `scripts/archive`, 18 seams) | Medium | Ratchet red; temptation to raise | §4.1 ceiling-rise STOP; remedy is a preceding typing slice (W3e), never a raise |
| **The rewrite scope grows before build** (r5; 67 files in 3 days) | High | Stale inventories; larger diff | Inventories regenerate at Stage 0; R2's AST count is authoritative; land W3 promptly once approved |
| **The `< 800`-line source-shape test on `features_build`** (r5) | Measured (797) | Test red, or pressure to relax it | Named transitive exception, proven by R6; Stage 0 line and order STOP; the test is never relaxed |
| **Provenance blob hashes of the F5 MC files change** (r5) | Certain (by design) | Recorded hashes become historical | No working-tree verifier exists (searched); evidence, amendment and `PREREG.json` untouched; old → new hashes recorded; Stage 0 STOP if a verifier appears; peer review rules on it |
| **A contract test is edited** (r5) | Certain (import only) | Weakened contract | Import plus template block only, proven AST-equal by the §5.0 checker; assertions unmodified; must pass |
| **NO-SEND guard coverage shifts with the import form** (r5) | Low | Weakened egress firewall | G5 classification invariance + full readonly guard; no `src/` or `scripts/venue/` edit |
| Exec client touched | None (by scope) | Pin breaks | Excluded; `git diff --stat -- src/ scripts/venue/` empty; no new test imports exec |
| A pinned error is replaced by a duplicate `(code, message)` | Low | Masked defect | R4 multiset with the duplicate-message control |
| A dependency bump fails R5 in an unrelated slice | Low | Spurious red | Committed snapshot; venv scan is advisory |
| The AST checker misses a deletion or a non-template bootstrap | Low | Untested runtime change | Normalize-never-delete, multiset compare, closed allowlist, exact templates, pre-existing bootstraps frozen, positive controls |
| A test passes only because another test inserted `sys.path` | Medium | Hidden fragility | G3 runs each touched file alone |
| A patch string still targets the qualified module | Low | False GREEN | R2 scans patch and setattr string targets (3 at HEAD) |
| A mypy run without `PYTHONPATH` pins phantom `trade.py` errors | Medium | Bogus ceiling | `PYTHONPATH` on every run; STOP on any `src/breezy/app` error |
| mypy nondeterminism | Low | Flaky ratchet | Double T2 and FIN runs at Stage 0 |
| `scripts/collect` gains errors through its newly resolved venue import | Medium | Uncovered-path failure | Pre-identified candidate key with multiset pin (W3f) |
| A `ruff format` run reformats untouched files | Medium (history) | Pin or byte drift | Format touched files only; `git status` check before commit |

**Invariants honoured:**
- Nautilus is untouched.
- **No `src/` edit; the exec client is excluded.** No `scripts/venue/` edit.
- No `ExecStart`, wrapper or unit edits.
- No test is weakened or deleted: the negative-import assertion is kept; guard and contract assertions are unmodified (docstrings only in two guard files); source-shape caps are untouched.
- `CLEAN` is unchanged. **Ceilings only go down or are new**, with exact-multiset pins.
- No forbidden forms: no blanket `type: ignore`, `ignore_errors`, `disable_error_code`, `files` removal, or `Any`/`cast` silencing.
- No operator-reserved control (daily budget, per-position cap), no NO-SEND firewall, no `allow_short`, no permit, and no live-enablement setting is touched.
- No evidence, amendment or `PREREG.json` file is edited.

---

## §10 Open questions for the r5 review

1. **Provenance blobs (§5.2).** Is it acceptable that the F5 MC and NP-stat modules' working-tree blobs diverge from their recorded `script_git_sha`/`stat_blob_sha`, given that no verifier reads them and reproduction is through `mc_git_head`? The alternative, keeping those two files qualified, is impossible under Option B (exit 2). Recommended answer: yes, with old → new hashes recorded.
2. **R6 placement and cost.** Should R6 stay in `test_scripts_import_convention.py`, or be merged into `test_runtime_import_isolation.py`'s parametrization? Recommended: keep it separate, because isolation asserts different semantics.
3. **The `features_build` transitive exception.** Is relying on the import order of one module, proven by R6, acceptable, or should a follow-up split that 797-line file instead? Recommended: accept now, with a follow-up row only if the file grows.
4. **Measure before review?** r5's post-W3 numbers are projections. Should a T2/FIN scratch measurement run before peer review rather than at Stage 0? Recommended: yes, if budget allows. It turns §4.1 into measured values and removes the dominant deduction below.

---

## §R2 / §R3 / §R4 Disposition

Unchanged; see `CF-12-W3_plan_r4.md`. All r2–r4 items remain resolved, and their mechanisms are carried into r5 (re-based line numbers only), except where §R5 says otherwise.

## §R5 Disposition

| Item | Source | Disposition | Where |
|---|---|---|---|
| R5-1 Ceilings re-based | STAGE merged 10-09 (`66d7fe74`, via `1462514d`); brief | Measured on HEAD `316b50c4`. All groups equal `CEILINGS` (3/351/8/23/7/1/6/2/1288, total 1689). `scripts/analysis` is 351, not 352 (`8e6e77c6`). The W3 seam (310 errors / 75 modules) is unchanged. | header, §0, §4.0, §7 step 0 |
| R5-2 Rewrite scope | HEAD inventory | 28/16 → **274 statements / 83 files**; patch strings 1 → 3; per-file tables re-built; R2 RED count updated | §0, §5.2, §5.4, §6 R2 |
| R5-3 Ignored seams | HEAD inventory | 12 → **40** `import-not-found` ignores, now including `scripts/archive` (18) and `scripts/collect` (1); added part (c) to the projection and the ceiling-rise STOP | §4.1, §5.3, §7 |
| R5-4 `scripts/collect` already a base | `pyproject.toml:418,435` | Kept in `mypy_path`; cited as the design precedent; added to R5; candidate pinned key | §1, §5.1, §5.5, §6 R5 |
| R5-5 New `scripts/ops` module | `ambig_latch_phase_a_check.py` (10-09) | Becomes reachable; `scripts/ops` pin expected ≥ 3; follow-up W3g | §4.1, §4.2, §5.5 |
| R5-6 Exec-client exclusion | brief | Stated explicitly; W3 edits nothing under `src/` or `scripts/venue/`; close-out diff assertion; no test imports exec | header, §0 goal 4, §9 |
| R5-7 `-m`-only scripts | HEAD inventory (19/36 lack a root bootstrap) | Uniform guarded own-dir append; **R6** qualified-name child import with RED controls | §2, §5.2, §6 R6 |
| R5-8 `< 800` source-shape cap | `test_multisource_blend_featbuild_review_fixes.py:456`; file at 797 lines | Named transitive exception; Stage 0 STOP; never relax the test | §5.2, §7, §9 |
| R5-9 Provenance blobs | `docs/evidence/f5/*.json`; amendment A1 | Disposition plus open question; Stage 0 verifier search STOP | §5.2, §10 |
| R5-10 NO-SEND invariance | readonly guard `:340-390` | G5 before/after classification equality; full guard in focused gate | §6 G5, §7 |
| R5-11 Contract test edited | `tests/contract/test_fq_loss_stop_writer_allowlist.py:33` | Import plus template only; checker-proven; assertions unmodified | §5.4, §9 |
| R5-12 Checker extensions | new import shapes | Multi-alias `from scripts.<dir> import a, b` split per alias; `<R>` may be a pre-existing repo-root name; cross-dir `archive` template; pre-existing bootstrap tuples frozen | §5.0 |
| R5-13 Security review | scope change | Narrow trigger met (G5 evidence + bootstrap blocks) | §7 step 9 |

## Self-score

**89/100** (r5).
- Strengths:
  - the HEAD baseline is measured with the ratchet's own code and matches every ceiling;
  - the r4 → r5 drift is explained mechanistically (the 351 cause, why the qualified form spreads);
  - every new hazard found at HEAD has a mechanical guard and a STOP: `scripts/collect`, the new `scripts/ops` module, the `< 800` cap, provenance blobs, the contract-test edit, and the 19 `-m`-only scripts;
  - the exec client and the NO-SEND firewall are excluded by scope and proven by G5.
- Deductions:
  - −6: post-W3 counts are projections. T2/FIN were not measured at r5, and 28 of the 40 ignored seams are unmeasured. Stage 0 binds, and §10 Q4 recommends measuring before review.
  - −2: the scope grows daily, so the inventories go stale between review and build.
  - −2: the `features_build` exception relies on intra-module import order (R6-proven, but indirect).
  - −1: the rollback is a procedure that has not been rehearsed.
