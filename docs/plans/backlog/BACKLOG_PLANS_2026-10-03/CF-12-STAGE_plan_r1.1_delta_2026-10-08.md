# CF-12-STAGE plan r1.1: DELTA against `CF-12-STAGE_plan_r1.md` (HEAD `bd32de69`, 2026-10-08)

r1 and `reviews/CF-12-STAGE-r1-final.md` stay in force. This delta replaces only the sections named below.

## Verified at bd32de69
- `CEILINGS` (`tests/unit/test_mypy_ratchet.py:354-364`):
  - `src/breezy/analysis` 13
  - `scripts/analysis` 359
  - `scripts/archive` 8
  - `scripts/venue` 23
  - `tests/contract` 11
  - `tests/integration` 1
  - `tests/strategy` 6
  - `tests/support` 2
  - `tests/unit` 1451
- `check_mypy_exit` is still absent.
- `pyproject.toml:418` sets `mypy_path = "src:scripts/collect"`, a string. `scripts/collect` is in `files` (`:436`) and has no CLEAN or CEILINGS entry, so its error count is 0.
- No module under `src/breezy/{runtime,app,strategy,adapters,persistence,domain,ingest,normalize,registry,settlement}` imports `breezy.analysis`. There are two indirect execution paths:
  - bwrap `entry_modules` in `runtime/autonomy_sandbox/table.py:264,276,286,315`;
  - timers that run `deploy/systemd/*.sh` → `scripts/analysis/*.py`.
- Byte/source pins:
  - `tests/contract/test_us_source_ingest_egress_guard.py:145-175`, which covers `scripts/venue/*` and `src/breezy/ingest/*`;
  - `tests/unit/analysis/stats/test_moved_source_pinned.py`;
  - the exec-client pin (`test_forecast_quantile_ladder_manifest_and_markers.py:115`);
  - `archive_table.py`, which is FROZEN.

## (a) The Stage 0 drift STOP is re-ruled (replaces §5 step 0.3–0.4 bullet 5 and §3 "set equality")
- **D** is the `d4bc9ac4` removal multiset, keyed by (path, stripped line), 185 entries in 39 files. **R** is the regenerated `[unused-ignore]` set on the build HEAD.
- **The STOP check covers D's 39 files only:**
  - only_branch = D − R;
  - only_head_in_D = (R restricted to D's files) − D;
  - STOP if |only_branch| + |only_head_in_D| > 18.
- **Unused ignores outside D's files are IN SCOPE.** They are removed, AST-checked and re-pinned like D. They do not count toward the STOP.
- **Additional hard STOPs:**
  - any R entry under a CLEAN path or under `scripts/collect`;
  - a partial-code unused-ignore message;
  - |R − D| > 185 (most likely a wrong environment).
- **Record** `<scratch>/s0_unused_ignore.tsv` with columns path, line, ratchet_group, ignore_codes, provenance ∈ {D, NEW} and disposition ∈ {REMOVE, EXCLUDED:<reason>}.
- **Commit B's body** carries a per-group table: group | D carried | NEW | EXCLUDED | removed | old→new ceiling. It also carries the both / only_branch / only_head_in_D / outside_D counts and the HEAD SHA.

## (b) Stale numbers become "measured at build time"
- Every fixed expectation (185/39, 3/352/7/1288/1690, "exactly four lower-the-ceiling messages") is replaced by N_removed, files_touched and the per-group ceilings measured on the build SHA.
- **Expected ratchet RED:** exactly one `<group>: lower the ceiling to <N>` per group with a nonzero REMOVE count, and nothing else.
- **Commit subject:** `fix(types): CF-12 Wave 2 — remove <N> unused type: ignore across <F> files (regenerated against <sha>)`.
- **CEILINGS comment:** `# CF-12 Wave 2 (CF-12-STAGE r1.1, <date>, base <sha>): <n_group> unused ignores removed`.
- W3 artifacts are not edited. W3's Stage 0 re-measures on the post-STAGE HEAD.

## (c) Positive control (replaces §5 step 1.4)
- Temporarily set `mypy_path = "src:scripts/collect:scripts/analysis:scripts/venue:scripts/archive:scripts/ops"`. This must produce exit 2.
- Fallback control: append the nonexistent `"scripts/__cf12_absent__"` to `files`.
- Restore with `git checkout -- pyproject.toml`. Run `git diff --stat` twice: right after the restore, and right before commit A.

## (d) Branch (replaces §5 "Build location")
- Build on the fresh branch `backlog/cf12-stage-r1-1-2026-10-08`, cut from the tip of `feat/data-capture-and-risk`.
- Assert that HEAD equals the tip.
- Read D via `git diff -U0 d4bc9ac4^ d4bc9ac4`.
- Do not modify d4bc9ac4, its worktree `cf12-wave2`, or the 09-29 cf12 branches.
- Port `70bcb7e1` by hand. Keep `_mypy_subprocess_env()` and the current CLEAN entries.

## (e) Focused tests
Run with `PYTHONPATH=<wt>/src`, using `/home/jon/breezy/.venv/bin/python`. Read the exit code of every run.
- `tests/unit/test_mypy_ratchet.py`
- `tests/contract/test_us_source_ingest_egress_guard.py`
- `tests/unit/analysis/stats/test_moved_source_pinned.py`
- `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`
- `tests/unit/test_autonomy_*.py` and all of `tests/contract/`
- every edited test module, plus the test module of every edited source file
- `lint-imports`, run from the worktree: must print "N kept, 0 broken"
- `ruff check` and `ruff format --check` on touched files only

The full gate remains binding before merge.

## (f) No activation
- No restart, no daemon-reload, and no `deploy/` edit. The merge is the activation.

## (g) Live-import and pin exclusion rule (new §3 rule, Stage 0)
1. **EXCLUDED:live-import** — the file is imported by any live package listed above. Positive control: the same grep on `src/breezy/analysis` must return matches. Expected count today: 0.
2. **EXCLUDED:pin** — any of the following:
   - the path is a key in a sha256 pin map under `tests/`;
   - the file is under `src/breezy/analysis/stats/`;
   - the file is the exec client or `archive_table.py`.
3. **Backstop** — if any of the four pin/contract tests above fails after a removal, revert that file, mark it EXCLUDED:pin and re-measure. Never update a pin.
4. **Accounting** — EXCLUDED ignores stay in place. The goal-state count of `[unused-ignore]` equals |EXCLUDED|, each with its reason. Ceilings are pinned to the measured counts.

## Verdict
READY as r1 + r1.1. The planner authored this delta; the coordinator adopted it on 2026-10-08.
