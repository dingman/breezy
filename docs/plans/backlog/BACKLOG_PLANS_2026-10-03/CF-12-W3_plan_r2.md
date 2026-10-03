# CF-12-W3: sibling-script `import-not-found`, plan r2 (2026-10-03)

- Backlog row: `docs/core/PROGRESS.md:83` (CF-12-W3, LOW).
- Parent plan: `docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md`. Its execution log (`:119-121`) records the failed config-only trial and requires a separate plan plus peer review. This is that plan.
- Status: **r2, revised against `reviews/CF-12-W3-r1-merged.md` (r1 scored 90: python-reviewer 91, architect 90, no CRITICAL/HIGH).** No code has changed. Every r1 number was measured on 2026-10-03 at HEAD `f45f5a65` with the shared interpreter (`/home/jon/breezy/.venv/bin/python -m mypy`, mypy 2.3.1) and a fresh `--cache-dir`, on a scratch **copy** of `src/ scripts/ tests/ pyproject.toml`. The repo was never touched. The r2 C1 triage (§4.1) is a read-only code reading at the same HEAD.
- Evidence files from r1 are in that session's scratchpad, `.../scratchpad/cf12w3/`: `baseline.txt` (HEAD), `t1.txt` (config-only), `t2.txt` (chosen design), `t3.txt` (rewrite only, control). Stage 0 re-measures everything; nothing below depends on those files surviving.
- r2 changes are summarised in **§R2 Disposition** at the end.

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
- **1** is `breezy.runtime.position_reporting_lag`, a *deliberate* negative import inside `pytest.raises(ModuleNotFoundError)` at `tests/unit/test_position_reporting_lag.py:113`. It is not a sibling-script import.

At runtime every one of these imports works, because each importer puts the sibling directory on `sys.path` first (109 `sys.path` sites in `scripts/`, 121 in `tests/`; direct execution `python scripts/analysis/x.py` also puts `scripts/analysis` on `sys.path[0]`). mypy cannot see this, so each import becomes `Any` and the code across that seam goes **unchecked**.

**Why the config-only fix fails (reproduced, T1).** `mypy_path = ["src", "scripts/analysis", "scripts/venue", "scripts/archive", "scripts/ops"]` makes mypy exit 2:
`scripts/analysis/discovery_set_equality.py: error: Source file found twice under different module names: "discovery_set_equality" and "scripts.analysis.discovery_set_equality"`

Cause: `explicit_package_bases = true` (`pyproject.toml:249`) names each file from its closest base. Once `scripts/analysis` is a base, every file under it is named bare (`x`), but **28 import statements in 16 files** still use `scripts.analysis.x` / `scripts.venue.x`. One file has one module name, so no configuration satisfies both conventions.

**Goal state (acceptance test).**
1. A full-config mypy run reports **0** `[import-not-found]` errors anywhere (the one negative test is converted in §5.4).
2. The `CLEAN`/`CEILINGS` ratchet (`tests/unit/test_mypy_ratchet.py:323-364`) is re-pinned to the measured post-change counts and passes; the two newly visible packages are pinned by **exact error fingerprint** (R4), not only by count.
3. Every live systemd unit, wrapper and test invokes every script **exactly as today**. No `ExecStart=`, wrapper `.sh`, `WorkingDirectory=` or unit-file edits. No new runtime behaviour beyond import resolution (§5.0 carve-out).
4. `scripts/ci/run_tests_no_egress.sh` exits 0.

---

## §1 Null-hypothesis check (L-1): does an existing mechanism already solve this?

None of these solves the problem alone. The design combines native `mypy_path` with the repo's existing bare-import convention.

| Mechanism | Verdict | Evidence |
|---|---|---|
| `mypy_path` += script dirs (config only) | **Necessary, not sufficient** | T1: exit 2, duplicate module name. |
| `explicit_package_bases` | Already on | It *causes* the bare naming once script dirs are bases. Turning it off reintroduces the `src.breezy.*` vs `breezy.*` collision (`pyproject.toml:250-254`). |
| `namespace_packages` | Default (mypy >=0.991) | It is why `scripts.analysis.x` resolves today, and why it collides once the dirs are bases. |
| Per-module `ignore_missing_imports` (74 modules) | **Rejected** | Turns ~309 seams into `Any`: the silencing CF-12 forbids (Rev2 `:126-135`), and never reaches "checked". |
| `scripts/__init__.py` + `scripts/<dir>/__init__.py` | **Rejected** | Forces Option Q or Option I everywhere; the `__init__`-free layout is deliberate (`pyproject.toml:233-235`). |
| `python -m scripts.…` for every unit | **Rejected** | ~20 live `ExecStart`/wrapper edits; violates goal 3. |
| pytest `pythonpath = [...]` (native) | **Deferred (YAGNI)** | Session-wide `sys.path` change can mask an order-dependent import bug. The 12 touched test files follow the per-file idiom; Option P is a one-line separable follow-up. |
| Existing per-script self-bootstrap | **Exists, reused** | `scripts/analysis/score_live_trials.py:160`; guarded loop at `nbp_market_comparison.py:20-25`, `nbp_learning_nightly.py:24-29`. `test_runtime_import_isolation.py:136-145` depends on it. |
| **import-linter** | **Does not cover `scripts/`** | `pyproject.toml:71` `root_packages = ["breezy", "nautilus_trader"]`. `scripts/` and `tests/` are outside every import-linter contract, so `lint-imports` can neither enforce nor break the bare-import convention. R2 (§6) is therefore the **only** mechanical guard of the convention; `lint-imports` is still run (it must stay "N kept, 0 broken") but is not evidence for W3's seam. |

**Basename-collision check.** At r1 HEAD the 112 `.py` basenames under `scripts/*/` were pairwise unique, shadowed no `sys.stdlib_module_names` entry and nothing importable from the venv. r1 left this as a one-off measurement; r2 makes it a permanent test (R5, §6), because the flat bare namespace is only safe while it holds.

---

## §2 Invocation inventory (every path that imports or executes a script)

**Live systemd units (`deploy/systemd/`; all `WorkingDirectory=/home/jon/breezy`):**

| Unit | Invocation | Affected by W3? |
|---|---|---|
| `breezy-discovery-pull.service:67` | `.venv/bin/python -m scripts.analysis.discovery_venue_pull …` | **Yes.** Only `-m` script unit. Its 3 qualified imports become bare, so the script self-bootstraps `scripts/analysis` and `scripts/venue` (§5.2). The unit file itself is not edited; its explanatory comment `:55-66` becomes stale and is deferred (CF-12-W3d, §5.6). |
| `breezy-fee-evidence-pull.service:55` | direct file `scripts/venue/fee_drift_evidence_pull.py` | No: no sibling imports. |
| `breezy-nbp-learning-nightly.service:26` | direct file `scripts/analysis/nbp_learning_nightly.py` | Bare imports unchanged; only now-`unused-ignore` comments removed if mypy reports them (§5.3). |
| `asos-refresh-run.sh:86,102,116,133` | direct file | No. |
| `capital-flow-pull-run.sh:33`, `decision-funnel-digest-run.sh:82`, `decisions-retention-run.sh:45`, `exit-window-study-run.sh:140`, `family-tally-v2-run.sh:328`, `hypothesis-triage-run.sh:42`, `live-tally-run.sh:254`, `portfolio-roi-run.sh:110`, `position-monitor-report-run.sh:193`, `replay-daily-run.sh:82,181,201,217`, `score-live-trials-run.sh:217,266,339`, `station-candidate-register-run.sh:47,49` | direct file | No. |
| `family-tally-v2-run.sh:180,188`, `live-tally-run.sh:142`, `score-live-trials-run.sh:137` | `-m breezy.runtime.*` | No. |
| trade supervisor, node, quote-tape, NWS ingest | `breezy.*` only | No. `src/` never imports `scripts`. |

- **Crontab:** no Breezy entries.
- `scripts/analysis/aud07_m1c_sweep.sh` manipulates `sys.path` but never invokes `-m scripts`.

**Tests:**
- ~100 test files insert `scripts/analysis` (or venue/archive) and import bare: unaffected.
- **12 test files** import the qualified name (§5.4). They resolve today only because `python -m pytest` puts the repo root on `sys.path`.
- Subprocess guards (W3's runtime safety net):
  - `tests/unit/test_unit_execstart_imports.py`: runs each venv-python `ExecStart` under its own `WorkingDirectory` with a scrubbed env (`PATH`, `HOME`, `PYTHONPATH=<repo_root>/src` only, `:160-171`). It maps the host root `/home/jon/breezy` to the checkout's own `_REPO_ROOT` (`:86-88`), so it exercises the **worktree** copy when run there;
  - `tests/unit/test_discovery_pull_exec_import.py`;
  - `tests/unit/test_runtime_import_isolation.py::test_entry_module_imports_cleanly` (`:81-128`).

**Incident precedent (binding).** 2026-09-26 16:52Z, `breezy-discovery-pull` died with `ModuleNotFoundError: No module named 'scripts'` (`test_unit_execstart_imports.py:25-34`). W3 touches the same seam; the subprocess guards are mandatory GREEN evidence.

---

## §3 Options

| # | Option | Sites touched | Runtime risk | Verdict |
|---|---|---|---|---|
| **B** | **Normalize to bare imports (majority convention)** + 4 script dirs in `mypy_path` | 28 statements in 16 files; append-bootstrap in 3 scripts; 1 config line | Low. Direct-file units unchanged; the 1 `-m` unit gets a bootstrap guarded by 3 subprocess tests + G4. | **CHOSEN** |
| Q | Qualified `scripts.analysis.x` everywhere | ~309 sites in ~75 files + repo-root bootstrap in ~20 direct-file scripts | **High** (09-26 class, ~20×) | Rejected |
| I | `python -m` for all units + `__init__.py` | ~20 `ExecStart` edits | High; violates goal 3 | Rejected |
| C | Per-module `ignore_missing_imports` | 1 block | None | Rejected: forbidden silencing |
| P | B, with pytest `pythonpath` instead of per-file test inserts | B minus test inserts + 1 ini line | Session-wide `sys.path` | Deferred |

**Why B.** Bare imports cover 74/75 modules and ~300/~330 sites; Python supports them natively for direct-file execution (19/20 script units). B moves the 28-site minority. It also removes a latent **double-module-identity** hazard: one pytest process can today hold `discovery_set_equality` and `scripts.analysis.discovery_set_equality` as distinct module objects, so a monkeypatch on one misses the other.

---

## §4 Measured effect of the chosen design (T2), and what it exposes

T2 = scratch copy + §5 rewrite + the 4-dir `mypy_path`. Result: **exit 1**, `Found 1624 errors in 171 files` (baseline 1875 in 240).

- **`[import-not-found]`: 310 → 1** (the `position_reporting_lag` negative test, handled in §5.4).
- Ratchet against the real `assess_ratchet`:
  - **lower ceilings:** `scripts/analysis` 360 → **158**; `scripts/archive` 8 → **3**; `scripts/venue` 23 → **11**; `tests/contract` 11 → **9**; `tests/unit` 1451 → **1412**;
  - **two newly visible paths with no CLEAN/CEILINGS entry:**
    1. `scripts/ops/decisions_retention.py:140`: 3 errors (`attr-defined` on `opener: object`; the existing `# type: ignore[call-arg]` becomes `unused-ignore`). Newly reachable because tests import it bare.
    2. **`src/breezy/app/trade.py`: 6 errors at `:1188-1207`** — `arg-type` (settings: `SettingsLike` members are settable, `BreezyTradeSettings` provides read-only attributes), `arg-type` (`permit: LiveTradingPermit | None` passed to `live_trading_permit=`), 4× `union-attr` (`permit.expires_at_ns`/`permit.issued_at_ns` at `:1203`, `:1206`, `:1207`).
- Control T3 (rewrite with original `mypy_path`) also shows the `trade.py` errors, so the import-graph change, not `mypy_path`, unmasks them.
- **Mechanism not yet explained.** `trade.py` and `order_enablement.py` are byte-identical across runs; consistent with mypy SCC processing order deferring a type to `Any`. Stage 0 re-measures twice for determinism.
- Error-code mix after T2: `arg-type` 296 → 332, `attr-defined` 156 → 212 — previously-`Any` seams now checked, not a code regression.

### 4.1 C1 reachability triage of the `trade.py` errors (r2, read-only, codegraph `projectPath=/home/jon/breezy`, HEAD `f45f5a65`)

**Verdict: NOT REACHABLE as a runtime defect. The six errors are type-level only. W3b stays a normal (LOW/MEDIUM) typing follow-up, not HIGH, and does not block W3.**

Evidence, in boot order (`src/breezy/app/trade.py::main`):

| Step | File:line | Fact |
|---|---|---|
| 1 | `trade.py:1140-1155` | `permit = None`; `issue_live_trading_permit(...)` may raise `LiveTradingPermissionError`, which is caught and alerted, leaving `permit is None` (the shadow-mode degrade path). **So `None` can reach the call at `:1188-1192`.** |
| 2 | `trade.py:1157-1175` | If settings fail to load and `BREEZY_ORDERS_ENABLED=1`, `main` returns `EXIT_RUNTIME_ERROR` before any permit use. Otherwise `settings` is either `None` (skip) or loaded. |
| 3 | `trade.py:1186-1192` | Only when `settings.orders_enabled_requested` is true is `OrderSubmissionPermit.issue(settings=..., live_trading_permit=permit, ...)` called. |
| 4 | `src/breezy/runtime/order_enablement.py:198-202` | `issue` runs `if not isinstance(live_trading_permit, LiveTradingPermit): raise LiveTradingPermitNotValidError(...)` before any attribute access. `isinstance(None, LiveTradingPermit)` is false, so `None` is **refused at the door**. (The only earlier dereference, `:203` `live_trading_permit.expires_at_ns`, sits after this guard.) |
| 5 | `order_enablement.py:99`, `:86` | `LiveTradingPermitNotValidError` subclasses `OrderSubmissionRefused`. |
| 6 | `trade.py:1193-1195` | `except OrderSubmissionRefused` logs the class name and returns `EXIT_RUNTIME_ERROR` — a fatal, loud refusal (the docstring contract at `:1110-1116`). |
| 7 | `trade.py:1196-1209` | The four `permit.*` dereferences are in the `else:` of that `try`, executed **only if `issue` returned**, which by step 4 requires `permit` to be a genuine `LiveTradingPermit`. With `permit is None` they are unreachable. |
| 8 | `trade.py:1219` | `run(live_trading_permit=permit, ...)` receives `None` on the shadow path; mypy does not flag it (not among the six), i.e. `run` already accepts `Optional`. |
| Pin | `tests/unit/test_order_submission_permit_issuance.py:131-140` | `test_live_trading_permit_wrong_type_refuses` calls `issue(live_trading_permit=None, ...)` and asserts `LiveTradingPermitNotValidError`. The runtime guard that makes step 7 unreachable is already test-pinned. |
| Settings `arg-type` | `order_enablement.py:125-144`, `:190-191` | `SettingsLike` is `@runtime_checkable`; for data members `isinstance` checks attribute **presence** only, so read-only `BreezyTradeSettings` attributes pass the runtime check. The `arg-type` is a Protocol-variance (settable vs read-only) typing mismatch, not a runtime path. |

**Consequence for W3b.** The fix is pure narrowing: an explicit `if permit is None:` refusal branch before `:1188` (or make the `SettingsLike` members read-only properties), which mypy can see. Because it edits `app/trade.py` on the live permit path, W3b keeps its own plan, a RED test for the `permit is None and orders requested` boot path through `main` (not only through `issue`), and a security-reviewer pass. It is **not** a pre-merge blocker for W3.

**Handling inside W3.** CF-12 forbids runtime edits in a typing wave (Rev2 `:135`), and W3's carve-out (§5.0) covers only import resolution, not `trade.py`. So W3 pins `"src/breezy/app": 6` and `"scripts/ops": 3` as new `CEILINGS` entries, each with a dated file-and-line comment, **and** with an exact-fingerprint pin (R4) so that a newly introduced error cannot silently replace a fixed one under an unchanged count. Follow-ups:
- **CF-12-W3b** (`trade.py` permit narrowing + read-only `SettingsLike` members; triage verdict: unreachable; own plan, security-reviewer, full gate);
- **CF-12-W3c** (type the `decisions_retention` opener as a `Callable`, same pattern as `trial_day_latch` in CF-12 W1).

Re-pinning a ceiling for newly *visible* errors in existing code is the ratchet's sanctioned mechanism; `CLEAN` is untouched and every ceiling only goes down or is new.

---

## §5 Chosen design: file-by-file changes

Build in a worktree from `feat/data-capture-and-risk` (fast-forward onto its tip first; agent worktrees can start stale). Every command runs with `cd <wt>` and `PYTHONPATH=<wt>/src`. mypy exactly as `/home/jon/breezy/.venv/bin/python -m mypy --cache-dir <wt-private>`. **Never `uv run`, `uv sync`, `pip`, or `git stash`.** `lint-imports` via the console script from `<wt>` (demand "N kept, 0 broken").

### 5.0 Runtime-edit carve-out (claimed explicitly, C4)

CF-12 Rev2 forbids "runtime edits under CF-12" (`docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md:135`) and routes any AST difference to the bug-ticket path (`:58-64`). The same plan's execution log (`:121`) rules that W3 is "a design decision, not a config change" whose only two choices — "normalizing qualified imports" or "changing how scripts are invoked" — are both runtime edits, and sends W3 to "its own plan and peer review". **This plan claims that carve-out, narrowly:**

Permitted AST differences (and only these):
1. `Import`/`ImportFrom` nodes whose module changes from `scripts.<dir>.x` to `x` (§5.2, §5.4);
2. one guarded, append-only `sys.path` bootstrap block per file in §5.2 (and the existing test idiom in §5.4), plus its `Path`/`sys` imports if absent;
3. the one monkeypatch target string at `tests/unit/test_discovery_venue_pull.py:279`;
4. the negative-import rewrite at `tests/unit/test_position_reporting_lag.py:113` (+ `import importlib` if absent);
5. removal of `# type: ignore` comments (comments are not in the AST; covered by the comment-only rule `:61`);
6. docstring text in the files named in §5.6 (stale-comment updates).

**Mechanical check (required close-out evidence).** A scratchpad checker (not committed, per Rev2 `:60`) parses every touched `.py` file before and after, removes from both trees (a) all `Import`/`ImportFrom` nodes, (b) the bootstrap block (identified as the module-level `if`/`for` statements whose body only mutates `sys.path`, and the `_SCRIPTS_*_DIR`/`_REPO_ROOT` assignments feeding them), (c) module/function docstrings in the §5.6 files, and (d) the two literal sites in items 3–4, then asserts `ast.dump(before) == ast.dump(after)` per file. Any other difference stops the slice and goes to the bug-ticket path. `pyproject.toml` and `test_mypy_ratchet.py` are outside the checker (config and ratchet constants/new tests, reviewed directly).

### 5.1 Config
- `pyproject.toml` `[tool.mypy]` (`:255`): `mypy_path = ["src", "scripts/analysis", "scripts/venue", "scripts/archive", "scripts/ops"]`.
- **Rewrite the now-stale comment `pyproject.toml:233-248`** (LOW). Today it says both paths "agree on `scripts.analysis.discovery_set_equality`" (`:243-246`), which W3 makes false. New text: script dirs are mypy bases because scripts import siblings by bare name (the convention); `explicit_package_bases` therefore names them bare; a package-qualified `scripts.<dir>.x` import would recreate the duplicate-module error and is forbidden (guarded by R2); basenames across the four dirs must be unique (guarded by R5). Keep the `src` paragraph (`:250-254`) unchanged.
- `files` unchanged. `scripts/ops` is a *base* only. `scripts/operator`, `scripts/ci` not added (YAGNI: nothing imports them).

### 5.2 Scripts: 4 files, imports plus append-bootstrap where `-m` or a child import needs it

**Bootstrap form (C2).** New bootstraps **append** (`sys.path.append`) and are guarded (`if str(d) not in sys.path`). Rationale: under `-m` the repo root (CWD) is `sys.path[0]` and the venv follows; appending the sibling dir means it can never shadow the stdlib or an installed package, and R5 guarantees no bare sibling name exists earlier on the path for it to be shadowed by. Under direct-file execution the dir is already `sys.path[0]`, so the guard makes it a no-op. The pre-existing `insert(0)` bootstraps (`nbp_market_comparison.py:20-25`, `score_live_trials.py:160`, `nbp_learning_nightly.py:24-29`) and the per-test `insert(0)` idiom are **not** changed (minimal diff); R5 is the collision guard that makes their `insert(0)` safe, as the review requires for any insert.

| File | Lines | Change |
|---|---|---|
| `scripts/analysis/discovery_venue_pull.py` | 29, 250, 373 | `from scripts.analysis.discovery_set_equality import …` → `from discovery_set_equality import …` (×2); `from scripts.venue.fee_drift_evidence_pull import build_default_client` → `from fee_drift_evidence_pull import …`. **Add the guarded append-bootstrap** of `Path(__file__).resolve().parent` and `…parents[1] / "venue"` before line 29. Required: the live unit runs it with `-m`. |
| `scripts/analysis/nbp_shadow_parity.py` | 86 | → `from nbp_shadow_parity_pure import`. **Add the guarded append-bootstrap of its own dir.** Required by `test_runtime_import_isolation` (child `import scripts.analysis.nbp_shadow_parity`). |
| `scripts/analysis/nbp_backfill.py` | 105 | → `from nbp_lag_census import`. **Add the guarded append-bootstrap.** |
| `scripts/analysis/nbp_market_comparison.py` | 53, 54, 64 | Rewrite to bare. Existing bootstrap `:20-25` unchanged. |

- No logic, argument or output change (§5.0 checker proves it). `# noqa: E402` only where ruff reports it.

### 5.3 Remove now-unused `# type: ignore[import-not-found]` (comment-only), driven by the report (LOW)

The edit list is **generated from the implementer's own post-§5.1/5.2/5.4 mypy report**: every `[unused-ignore]` line whose unused code is `import-not-found` is an edit target; nothing else is. The r1 expectation (7 files: `scripts/analysis/{whole_tape_paper_replay,replay_sufficiency_census,tape_instruments,nbp_learning_nightly,current_rung_hold_paper_replay,nbp_skill_study}.py`, `tests/unit/test_nbp_skill_study.py`) is a cross-check only; a mismatch is recorded, not reconciled by hand. Where an ignore lists other codes, drop only `import-not-found`. Re-run mypy after; the `unused-ignore` count for `import-not-found` must be 0 and no other count may rise. The `decisions_retention.py:140` `unused-ignore[call-arg]` is **not** touched (W3c owns it; it stays inside the `scripts/ops` pin).

### 5.4 Tests: 12 files, imports plus `sys.path`

Each file gets the existing module-level idiom (`_SCRIPTS_ANALYSIS_DIR = …; if str(...) not in sys.path: sys.path.insert(0, ...)`, as at `tests/unit/test_structural_dead_stop.py:32-33`) before its bare import, then the qualified imports are rewritten:

| File | Lines |
|---|---|
| `tests/unit/test_discovery_set_equality.py` | 16, 725 |
| `tests/unit/test_discovery_venue_pull.py` | 19, plus the **string** monkeypatch target `:279` `"scripts.venue.fee_drift_evidence_pull.build_default_client"` → `"fee_drift_evidence_pull.build_default_client"` (must match the module object `discovery_venue_pull` now imports). Also inserts `scripts/venue`. |
| `tests/unit/test_nbp_backfill.py` | 36 |
| `tests/unit/test_nbp_lag_census.py` | 13 |
| `tests/unit/test_nbp_market_comparison.py` | 18: `from scripts.analysis import nbp_market_comparison as m` → `import nbp_market_comparison as m` |
| `tests/unit/test_nbp_shadow_parity_live.py` | 28, 53, 54 |
| `tests/unit/test_nbp_shadow_parity_load.py` | 15, 22, 133, 189, 345 |
| `tests/unit/test_nbp_shadow_parity_no_side_synthetic.py` | 46, 47 |
| `tests/unit/test_nbp_shadow_parity_pure.py` | 27 |
| `tests/unit/test_nbp_skill_study.py` | 36 (already inserts the dir) |
| `tests/unit/test_fq_live_analysis_point_cdf_parity.py` | 65 |
| `tests/strategy/forecast_quantile_ladder/test_lst_margin_horizon.py` | 25 |

- **Not changed (code):** the qualified **strings** in `test_runtime_import_isolation.py:81-145`, `test_unit_execstart_imports.py`, `test_discovery_pull_exec_import.py`, `test_polymarket_us_readonly_guard.py:1196`. They model how production invokes the entry in a child process; they must keep passing with unmodified assertion code. (Only their stale docstrings change, §5.6.)
- **Negative import** `tests/unit/test_position_reporting_lag.py:113`: `import breezy.runtime.position_reporting_lag` inside `pytest.raises(ModuleNotFoundError)` → `importlib.import_module("breezy.runtime.position_reporting_lag")`. Same assertion and semantics.

### 5.5 Ratchet constants and pins (`tests/unit/test_mypy_ratchet.py:354-364`)
- Lower the 5 ceilings to the implementer's measured values (T2 expectation 158, 3, 11, 9, 1412; re-measure).
- Add `"src/breezy/app": 6` with the comment: `# CF-12-W3 2026-10-03: 6 latent errors newly visible at src/breezy/app/trade.py:1188-1207 (settings arg-type; permit arg-type; 4x union-attr on permit at :1203,:1206,:1207). Triage (W3 plan r2 §4.1): unreachable at runtime -- order_enablement.py:198-202 refuses None first. Fix owned by CF-12-W3b. Exact set pinned by R4.`
- Add `"scripts/ops": 3` with the comment: `# CF-12-W3 2026-10-03: scripts/ops/decisions_retention.py:140 (attr-defined on opener: object; unused-ignore[call-arg]). Fix owned by CF-12-W3c. Exact set pinned by R4.`
- Add `W3_PINNED_ERRORS: Final[dict[str, frozenset[tuple[str, str]]]]` (path → set of `(error_code, message)`; **line numbers deliberately excluded** so unrelated edits elsewhere in `trade.py` do not churn the pin, while the comment carries file:line for humans). Populated from the implementer's measured report, verbatim.
- `CLEAN` unchanged.

### 5.6 Docs and stale comments
- **Test docstrings (LOW):** `tests/unit/test_discovery_pull_exec_import.py:1-27` and `tests/unit/test_unit_execstart_imports.py:24-33` describe `discovery_venue_pull.py` as *currently* doing `from scripts.analysis.discovery_set_equality import ...`. Append a dated sentence to each (history preserved): "CF-12-W3 (2026-10-03): the script now imports its siblings bare and self-bootstraps `scripts/analysis` and `scripts/venue`; this guard still models the unit's `-m` invocation unchanged." Docstring-only; the §5.0 checker strips docstrings in exactly these two files and proves the code is AST-equal.
- **`pyproject.toml:233-248`** comment: rewritten in §5.1.
- **`deploy/systemd/breezy-discovery-pull.service:55-66`** comment becomes stale (it says the script does a qualified import). Goal 3 forbids unit-file edits in W3, so **log a deferred doc row CF-12-W3d** in PROGRESS: "refresh the discovery-pull unit comment after W3; comment-only, bundle with the next unit edit that already requires a daemon-reload".
- `PROGRESS.md`: close CF-12-W3 with SHA and measured counts; add CF-12-W3b (`trade.py` permit narrowing; triage verdict unreachable; security-reviewer required), CF-12-W3c (`decisions_retention` opener), CF-12-W3d (unit comment).
- Append a W3 execution-log entry to CF-12 Rev2, recording the §5.0 carve-out claim and the checker result.

---

## §6 RED → GREEN tests

| ID | Test (in `tests/unit/test_mypy_ratchet.py` unless noted) | RED at HEAD | GREEN after |
|---|---|---|---|
| R1a | `test_import_not_found_lines_are_extracted_with_their_module_names`: pure parser test on fake mypy text for a new helper `parse_import_not_found(output) -> list[tuple[str, str]]` (drops notes; keeps only `[import-not-found]`). | Fails (helper absent) | Passes |
| R1b | `test_full_config_mypy_reports_zero_import_not_found`: reuses the module-scoped `mypy_report` fixture, extended to keep the raw text and the return code (still **one** mypy run). **First asserts `returncode in {0, 1}`, failing loudly with the stderr/stdout tail otherwise (LOW)** — exit 2 or a crash is never parsed as "0 errors". Then asserts `parse_import_not_found(...) == []`, listing `path → module` on failure. | **Fails with 310 entries** | 0 |
| R2 | `tests/unit/test_scripts_import_convention.py::test_no_package_qualified_sibling_script_import`: AST scan of `scripts/**/*.py` and `tests/**/*.py` for `Import`/`ImportFrom` whose module starts with `scripts.analysis`, `scripts.venue`, `scripts.archive`, `scripts.ops`, or `from scripts import <dir>`. **Extended (LOW):** also flags a string-literal first argument beginning with those prefixes in calls to `monkeypatch.setattr`, `monkeypatch.delattr`, `patch`, `mock.patch`, `unittest.mock.patch` (matched on the call's `func` attribute/name). Other string literals are ignored, so the production-modelling guards (§5.4) stay legal. Positive controls: one synthetic import source and one synthetic `monkeypatch.setattr("scripts.venue.x.y", ...)` source each produce a hit; one synthetic `subprocess.run([... "-m", "scripts.analysis.x"])` produces none. | **Fails: 28 import sites in 16 files + 1 patch string (`test_discovery_venue_pull.py:279`)** | 0 |
| R3 | `test_mypy_stays_within_the_cf12_clean_set_and_ceilings` (existing) | Passes at HEAD; after §5.1–5.4 without §5.5 it fails with 5 "lower the ceiling" + 2 "no CLEAN or CEILINGS entry" messages | Passes after §5.5 |
| R4 | `test_w3_pinned_packages_carry_exactly_the_pinned_errors` (C1): from the shared fixture's raw text, for each path in `W3_PINNED_ERRORS`, the multiset of `(code, message)` must **equal** the pin. A new error with a fixed one removed fails (same count, different set), as does any drift. When W3b/W3c fix their errors, the pin and the ceiling shrink together. Pure helper unit-tested with fake text (positive control: swap one error → fails). | Fails (pin absent / errors not yet visible) | Passes |
| R5 | `tests/unit/test_scripts_import_convention.py::test_script_basenames_are_unique_and_unshadowed` (C2): over `scripts/{analysis,venue,archive,ops}/*.py` (the four mypy bases): (a) basenames pairwise unique across dirs — failure lists each colliding name with both paths; (b) none in `sys.stdlib_module_names`; (c) none is a top-level importable name in the venv, computed from `pkgutil.iter_modules` over the interpreter's `site.getsitepackages()` dirs plus `importlib.metadata.packages_distributions()` keys (the repo's own `breezy` excluded). Positive controls on a `tmp_path` tree: a cross-dir duplicate, a file named `json.py`, and a file named after a known installed top-level (e.g. `msgspec.py`) each fail the helper. | Passes at HEAD (0/112 measured) — RED is the positive controls | Passes |
| G1 | `test_unit_execstart_imports.py` and `test_discovery_pull_exec_import.py` (existing, assertion code unmodified) | Pass | **Must still pass** with the new bootstrap. **Required RED evidence:** with the bootstrap temporarily omitted from `discovery_venue_pull.py`, `test_unit_execstart_imports` must fail with `ModuleNotFoundError: … discovery_set_equality`. Record, then restore. |
| G2 | `test_runtime_import_isolation.py::test_entry_module_imports_cleanly` (existing, unmodified) | Pass | Still passes for `discovery_venue_pull`, `nbp_shadow_parity`, `nbp_shadow_parity_pure`, `nbp_market_comparison`. Same omit-bootstrap RED check for `nbp_shadow_parity`. |
| G3 | Each of the 12 §5.4 files run **alone** (`pytest <file>`) from `<wt>` with `PYTHONPATH=<wt>/src` | — | Pass (no order dependence). |
| G4 | Manual smoke of the live `-m` import path, **in the worktree (C3)**: `cd <wt> && env -i PATH=/usr/bin HOME=$HOME PYTHONPATH=<wt>/src /home/jon/breezy/.venv/bin/python -m scripts.analysis.discovery_venue_pull --help` | — | Exit 0. Must run from `<wt>` (never `cd /home/jon/breezy`, which would smoke the primary tree's unchanged code). `PYTHONPATH=<wt>/src` matches the guard's scrubbed env (`test_unit_execstart_imports.py:160-171`) and keeps `breezy` resolving to the worktree. Repeated as a post-merge check from `/home/jon/breezy` (primary tree, no `PYTHONPATH`, exactly as the unit runs). |

**Ordering:** R1a, R1b, R2, R4 (helper part) and R5 positive controls are written first and RED captured. Then §5.1–5.4, then §5.5. Final step: full gate `scripts/ci/run_tests_no_egress.sh`, reading `EXIT=0` **before** any push.

Cost: R1b and R4 share the one fixture mypy run; R2 and R5 are sub-second.

---

## §7 Build sequence
0. **Stage 0 (re-measure, read-only)**, in `<wt>`: baseline mypy, then T2, fresh caches; T2 **twice** to confirm the `trade.py` 6 and `decisions_retention` 3 are deterministic. Re-confirm the §4.1 triage still holds at the worktree HEAD (`trade.py:1185-1209` and `order_enablement.py:198-202` unchanged; if either moved, re-run the triage before proceeding). **STOP and return to plan review** if any ceiling differs from §4 by more than ±5%, any uncovered path appears beyond the two named, or the triage verdict changes.
1. Write R1a, R1b, R2, R4 helper test, R5; capture RED.
2. §5.1 config, §5.2 scripts, §5.4 tests. R2 GREEN.
3. Run mypy; §5.3 ignore removal from the report; re-run mypy.
4. §5.5 ceilings + `W3_PINNED_ERRORS`. R1b, R3, R4 GREEN.
5. G1/G2 omit-bootstrap RED checks, restore; G1–G4 GREEN; G3 per file; `ruff check` + `ruff format --check` on touched files; `lint-imports` from `<wt>` ("N kept, 0 broken").
6. §5.0 AST-equality checker over every touched `.py` file; record its output.
7. §5.6 docstring/comment updates; re-run the §5.0 checker.
8. Full gate `scripts/ci/run_tests_no_egress.sh`, EXIT=0.
9. Independent review: `python-reviewer` on the diff (with `PYTHONPATH=<wt>/src` in its brief). `security-reviewer` trigger **not met**: W3 does not edit `trade.py` or any permit code (W3b will).
10. Commit by explicit path; merge; PROGRESS/Rev2 log (§5.6).

**Activation:** no restart. Supervisor and node never import `scripts/`. `breezy-discovery-pull` is a timer-fired oneshot: after merge run the G4 primary-tree smoke, then confirm the next timer run exits 0 (`systemctl --user status breezy-discovery-pull.service`; journal).

---

## §8 Rollback
- One commit/merge; `git revert <sha>` restores qualified imports, old `mypy_path`, old ceilings and removes R2/R4/R5 atomically.
- No unit, wrapper, data, state DB or venv change: no `daemon-reload`, no restart.
- If `breezy-discovery-pull` fails post-merge with `ModuleNotFoundError`, revert; next timer run self-heals. A missed run loses one evidence snapshot; no trading impact.

---

## §9 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The `-m` discovery unit loses a sibling import (09-26 repeat) | Low | One evidence run lost | G1 + G4 (worktree and post-merge primary tree) + omit-bootstrap RED proof |
| Test passes only because another test inserted `sys.path` | Medium | Hidden fragility | G3 runs each touched file alone |
| A monkeypatch/patch string still targets the qualified module | Low | False GREEN | **R2 now scans `monkeypatch.setattr`/`patch` string targets** (r1 relied on reviewer grep) |
| A new error in `src/breezy/app` replaces a fixed one under an unchanged count | Low–Medium | Masked live-path type defect | **R4 exact-fingerprint pin**; ceiling comment names file:line |
| Newly visible `trade.py` errors read as "W3 broke trading" | Medium (perception) | Mis-triage | §4.1 triage: unreachable, file:line evidence; T3 control; W3 edits no `trade.py` byte |
| mypy SCC-order nondeterminism | Low–Medium | Flaky ratchet / flaky R4 | Stage 0 double run; STOP if not reproducible |
| Concurrent merges move ceilings before W3 lands | High | Stale pins | Re-measure; R3 reports the exact value |
| Script basename collides across dirs, with stdlib, or with a venv package | Low (0/112 today) | mypy exit 2 or wrong module at runtime | **R5 (now, not deferred)**; new bootstraps append, never insert |
| §5.3 strips an ignore that still suppresses something | Low | New error | Edit list generated from the `unused-ignore` report only |
| A "typing" edit smuggles behaviour change | Low | Untested runtime change | §5.0 AST-equality checker; any other diff → bug-ticket path |
| R1b passes on a crashed/exit-2 mypy | Low | False GREEN | R1b asserts exit code ∈ {0,1} first |

**Invariants honoured:** Nautilus untouched; no `ExecStart`/wrapper/unit edits; no test weakened or deleted (negative-import assertion kept; guard assertions unmodified, docstrings only; `CLEAN` unchanged; ceilings only go down or are new, now with exact-set pins); no forbidden forms (no blanket `type: ignore`, `ignore_errors`, `disable_error_code`, `files` removal, `Any`/`cast` silencing); no operator-reserved control, NO-SEND firewall, `allow_short`, or live enablement touched.

---

## §10 Open questions (resolved in r2)
1. `trade.py` 6: ceiling in W3, fix in W3b — **confirmed** by the §4.1 triage (unreachable), with R4 so the ceiling cannot hide substitution.
2. Per-file test inserts vs pytest `pythonpath`: per-file (reviewers did not object); Option P stays a separable follow-up.
3. Basename-uniqueness test: **now** (R5), per C2.

---

## §R2 Disposition

| Item | Source | Disposition | Where |
|---|---|---|---|
| C1 triage possibly-None permit | both | **Done, read-only via codegraph.** Verdict: `permit=None` reaches the `issue(...)` call (`trade.py:1140-1155` → `:1188-1192`) but is refused at `order_enablement.py:198-202` (`LiveTradingPermitNotValidError` ⊂ `OrderSubmissionRefused`, `:99`) and caught at `trade.py:1193-1195` → `EXIT_RUNTIME_ERROR`; the dereferences `:1203-1207` are in the `else:` and unreachable with `None`. Pinned by `test_order_submission_permit_issuance.py:131-140`. Settings `arg-type` is Protocol variance only (`runtime_checkable` checks presence). **W3b not HIGH; no own pre-merge row; W3 not blocked.** Ceiling pinned with file:line comment **plus** R4 exact-fingerprint test. | §4.1, §5.5, §6 R4, §9 |
| C2 basename-uniqueness test now; append bootstrap | both | R5 added (cross-dir, stdlib, venv top-level; positive controls). New bootstraps use guarded `sys.path.append`; pre-existing `insert(0)` sites left as-is and covered by R5, as the review allows. | §1, §5.2, §6 R5, §9 |
| C3 G4 in worktree | architect | G4 now `cd <wt> && env -i … PYTHONPATH=<wt>/src … -m …`; primary-tree repeat moved to post-merge. Global rule: every command runs from `<wt>` with `PYTHONPATH=<wt>/src`. | §5 preamble, §6 G4, §7 |
| C4 claim the runtime-edit carve-out | architect | §5.0 cites Rev2 `:121` (W3's sanctioned choice is itself a runtime edit) against `:135` (prohibition) and `:58-64` (mechanical neutrality); enumerates the 6 permitted diff kinds; requires a per-file AST-equality checker outside import + bootstrap (+ 2 literal sites + named docstrings). | §5.0, §7 step 6–7 |
| LOW: R2 scans `monkeypatch.setattr`/`patch` strings | python | Done, with positive and negative controls. | §6 R2 |
| LOW: R1b fails loudly unless exit 0/1 | python | Done. | §6 R1b |
| LOW: drive `unused-ignore` removal from the report | python | §5.3 edit list generated from `[unused-ignore]` lines; r1 list is a cross-check only. | §5.3 |
| LOW: stale test docstring + `pyproject.toml:243-246` | architect | Both guard-test docstrings get a dated sentence; `pyproject.toml:233-248` comment rewritten. | §5.1, §5.6 |
| LOW: deferred doc row for `breezy-discovery-pull.service:55-66` | architect | CF-12-W3d row (unit edits are out of W3 scope by goal 3). | §2, §5.6 |
| LOW: state `scripts/` is outside import-linter `root_packages` | architect | Added to §1 with `pyproject.toml:71`; R2 named as the only convention guard. | §1 |

## Self-score
**94/100.**
- Strengths: failure reproduced (T1), design measured end-to-end with a control (T3); C1 settled with a file:line reachability chain and an existing pinning test; the ceiling is now enforced by exact fingerprint, not count; the carve-out is claimed against the parent plan's own lines and proved mechanically; basename safety is now a permanent test.
- Deductions: the `trade.py` masking mechanism (SCC order) is measured but still unexplained (−3); ceilings and the R4 message strings will drift before execution and must be re-measured (−2); the r1 regex-copy trial may surface ruff E402/I001 noise not yet measured (−1).
