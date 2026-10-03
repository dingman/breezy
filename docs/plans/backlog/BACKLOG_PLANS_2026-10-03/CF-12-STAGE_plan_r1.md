# CF-12-STAGE: land CF-12 Wave 2 on the current tree, plan r1 (2026-10-03)

- Backlog row: `docs/core/PROGRESS.md:82` (CF-12-STAGE, LOW).
- Parent plan: `docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md` (Wave 2 = row 2 at `:79`; execution log `:116-118`).
- Sibling: CF-12-W3, APPROVED at `BACKLOG_PLANS_2026-10-03/CF-12-W3_plan_r3.md` (`reviews/CF-12-W3-r3-final.md`, 96/96). §4 below sets the order between them.
- Status: **r1, not yet peer-reviewed.** Every number below was measured read-only on 2026-10-03 at HEAD `f45f5a65` (`feat/data-capture-and-risk`). The tools were: `git merge-base` / `diff` / `merge-tree`; `/home/jon/breezy/.venv/bin/python -m mypy` (2.3.1) with a fresh scratchpad `--cache-dir`, run in the primary tree and on scratch copies; and `lint-imports` from the primary tree. No repo file, branch or worktree was changed.

---

## §0 Problem and goal state

**Problem.** CF-12 Wave 2 has been staged on `backlog/stage-cf12-w2-2026-09-29` @ `4b0b4f65` since 09-29. It contains three things:
1. `d4bc9ac4`: removes 185 unused `# type: ignore` comments across 39 files. The change is comment-only, AST-verified and Codex-authored.
2. `70bcb7e1`: hardens the ratchet. It adds `check_mypy_exit`, which accepts only exit codes 0 and 1, plus a `(errors prevented further checking)` blocker guard and three unit tests.
3. `4b0b4f65`: re-pins the ratchet ceilings.

The gate passed on it (`~/.cache/breezy-gate/stage-cf12.log`: `start … head=4b0b4f6` … `EXIT=0`). That pass was against base `1792e8c9`, which is now stale, so it is **not evidence for the current tree**.

**Goal state (acceptance test).**
1. On `feat/data-capture-and-risk`, full-config mypy reports **0** `[unused-ignore]` errors. Today it reports 185.
2. `tests/unit/test_mypy_ratchet.py` rejects any mypy exit code other than 0 or 1, and rejects any `(errors prevented further checking)` summary.
3. `CEILINGS` are re-pinned to the measured post-change counts and the ratchet passes.
4. Every edited non-ratchet `.py` file is AST-identical to HEAD.
5. `scripts/ci/run_tests_no_egress.sh` exits 0 on the exact SHA that is pushed.

---

## §1 Measurements (2026-10-03, HEAD `f45f5a65`)

### 1.1 Staleness and conflicts
| Fact | Value |
|---|---|
| `git merge-base HEAD backlog/stage-cf12-w2-2026-09-29` | `1792e8c9` |
| Commits on HEAD since the merge base | **136** |
| Commits on the branch since the merge base | 5 (`d4bc9ac4`, `70bcb7e1`, two merges, `4b0b4f65`) |
| Files changed by the branch | 40 (39 by `d4bc9ac4`, plus `tests/unit/test_mypy_ratchet.py`) |
| Branch files that HEAD also changed since the merge base | **7**: `scripts/analysis/replay_sufficiency_census.py`, `tests/contract/test_boot_halt_alert_contract.py`, `tests/contract/test_trade_node_lifecycle_contract.py`, `tests/unit/test_aud07_live_rule_crossing_sim.py`, `tests/unit/test_current_rung_hold_exit_window_study.py`, `tests/unit/test_no_side_s5c_flip_2026_09_14.py`, `tests/unit/test_mypy_ratchet.py` |
| Branch files deleted on HEAD | 0 |
| `git merge-tree --write-tree HEAD <branch>` | The other 6 files auto-merge. **1 content conflict: `tests/unit/test_mypy_ratchet.py`.** HEAD has since added the colour-off child env (`8f6575c5`) and moved the CEILINGS (for example `scripts/analysis` 364→360, `tests/unit` 1466→1451). |
| `70bcb7e1` (exit-code hardening) on HEAD? | **No** (`git merge-base --is-ancestor` is false). HEAD's fixture still parses mypy output without checking the exit code. |

### 1.2 Are the 185 ignores still present and still unused?
Full-config mypy in the primary tree at HEAD gives `Found 1875 errors in 240 files`, exit 1, with **185** `[unused-ignore]` errors. All 185 have the form `Unused "type: ignore" comment`, so each is a whole-comment removal; none removes a single code from a list.

I keyed each reported line by `(path, stripped line text)` and compared that multiset with the lines `d4bc9ac4` removed (`git diff -U0 d4bc9ac4^ d4bc9ac4`):

| Set | Count |
|---|---|
| In both | **185** |
| Only on the branch (since removed or now needed) | **0** |
| Only on HEAD (new unused ignores since 09-29) | **0** |

So, today, the regenerated set equals Wave 2's set exactly. None of the removed lines carries a second trailing comment, so stripping the ignore leaves no residue.

By package: `src/breezy/analysis` 10, `scripts/analysis` 8, `tests/contract` 4, `tests/unit` 163. This is the same split as the branch's ceiling deltas.

By code: `arg-type` 67, `method-assign` 57, `attr-defined` 33, `index` 10, `assignment` 6, `union-attr` 4, `override` 4, `return-value` 2, `call-overload` 1, `call-arg` 1. **No `import-not-found` ignores.**

### 1.3 Expected ratchet after the removal (HEAD `f45f5a65`)
| Group | HEAD ceiling | Delta | New ceiling |
|---|---|---|---|
| `src/breezy/analysis` | 13 | −10 | **3** |
| `scripts/analysis` | 360 | −8 | **352** (the branch's 356 is stale) |
| `tests/contract` | 11 | −4 | **7** |
| `tests/unit` | 1451 | −163 | **1288** (the branch's 1303 is stale) |
| Others (`scripts/archive` 8, `scripts/venue` 23, `tests/integration` 1, `tests/strategy` 6, `tests/support` 2) | unchanged | 0 | unchanged |
| **Total** | 1875 | −185 | **1690** |

These numbers are expectations. Stage 0 re-measures them, and the ratchet's "lower the ceiling to N" messages are the authority.

### 1.4 Measurement hazard (binding for this plan and relevant to W3)
mypy run **outside the primary tree without `PYTHONPATH=<tree>/src`** (a `git archive` copy, and a `cp -a` copy, both under the scratchpad) reports `Found 1881 errors in 241 files`. The 6 extra errors are all in `src/breezy/app/trade.py:1189-1207` (`arg-type` ×2, `union-attr` ×4). The same copy **with** `PYTHONPATH=<copy>/src` gives exactly 1875 and 0 `src/breezy/app` errors.

Cause: `.venv/lib/python3.13/site-packages/breezy.pth` contains `/home/jon/breezy/src`. mypy reads the interpreter's `sys.path`, so a non-primary tree without `PYTHONPATH` resolves part of `breezy` against the **primary** tree.

`~/.cache/breezy-gate/gate.sh` already sets `PYTHONPATH=$WT/src`, and the 10-02 worktree gates (`final-4b8347a6.log` and others) passed the ratchet. **Rule:** every mypy measurement in this plan runs from `<wt>` with `PYTHONPATH=<wt>/src`. A non-zero `src/breezy/app` count means the environment is wrong; it is not a finding.

### 1.5 Other facts
- `lint-imports` from the primary tree: `Contracts: 7 kept, 0 broken.` One of the contracts is "the live import graph never reaches into the hypothesis ledger".
- Supervisor reach: the 3 `src/` files in the set are `src/breezy/analysis/{hypothesis_ledger,instance_span_cache,replay_sufficiency}.py`. No module under `src/breezy/{runtime,app,strategy,adapters}` imports them (`/usr/bin/grep` of `breezy.analysis.<name>` and `from breezy.analysis import`; codegraph shows callers only in `scripts/analysis/replay_sufficiency_census.py` and tests). The supervisor unit runs `breezy-trade-supervisor` (`deploy/systemd/breezy-trade-supervisor.service:139`).

---

## §2 Null hypothesis (L-1)
Nautilus is not involved: this is repo-local typing hygiene with no runtime surface. mypy's own `warn_unused_ignores` is the native mechanism. It is on via `strict = true` (`pyproject.toml [tool.mypy]`) and it **produces** the edit list. No new tool, config key or abstraction is introduced. The existing ratchet (`tests/unit/test_mypy_ratchet.py`) is the enforcement.

---

## §3 Method: regenerate against HEAD, never replay the stale diff
Replaying the old diff, by merging or cherry-picking `d4bc9ac4`, is **rejected as the primary method**. That diff was computed against `1792e8c9`. Equality with HEAD's set holds today (§1.2), but nothing guarantees it at execution time: 136 commits have landed and others may land concurrently. The removal set is therefore **regenerated from mypy's own report on the build worktree's HEAD**, and `d4bc9ac4` is used only as a cross-check.

The ratchet hardening (`70bcb7e1`) is **ported by hand** onto HEAD's `test_mypy_ratchet.py`, keeping HEAD's colour-off env and HEAD's `CLEAN` entries (SL-7, SL-8). Merging it would conflict anyway (§1.1).

**Removal tool.** A scratchpad script, not committed:
1. Parse the worktree mypy report for lines matching `^(?P<path>[^:]+):(?P<line>\d+): error: Unused "type: ignore(\[[^\]]*\])?" comment  \[unused-ignore\]$`.
2. For each `(path, line)`, assert that the line contains exactly one match of `\s*#\s*type:\s*ignore(\[[^\]]*\])?\s*$` and nothing after it. Then remove that match, and only that match.
3. **Hard-fail, never guess**, on any of these:
   - an `Unused "type: ignore[x]" comment` message. That form is a partial-code removal; it is absent today, and if it appears it needs a reviewed rule.
   - an ignore followed by another comment (for example `# noqa`).
   - a reported line without an ignore.
   - a path outside `src/`, `scripts/` or `tests/`.

---

## §4 Relationship to CF-12-W3, and ordering

**Decision: CF-12-STAGE lands first, and W3 builds on top.**

| Consideration | Finding |
|---|---|
| Line overlap | **None.** STAGE removes no `import-not-found` ignore (§1.2). W3 §5.3 removes only ignores that *become* unused `import-not-found` after its import rewrite. |
| File overlap | Two files. (a) `scripts/analysis/replay_sufficiency_census.py`: STAGE removes 1 unused ignore; W3 §5.3 lists it as a cross-check target for a different, `import-not-found`, ignore. The lines are disjoint and textual conflict is unlikely. (b) `tests/unit/test_mypy_ratchet.py`: both edit `CEILINGS` and the fixture. This is a sequential conflict, which landing one first resolves. |
| Ratchet hardening overlap | W3 R1b requires the fixture to "assert `returncode in {0, 1}` first, failing loudly with the stderr/stdout tail". That is exactly `check_mypy_exit`. If STAGE lands first, W3 R1b **reuses `check_mypy_exit`** instead of re-implementing it (DRY), and the W3 implementer brief must say so. |
| Why not W3 first | 25 of STAGE's 185 ignores sit in 13 files that carry `import-not-found` today (8 in `scripts/analysis/forecast_conditional_{corpus,report}.py` and `replay_sufficiency_census.py`; 17 in `tests/unit`). Those ignores sit next to `Any` values from unresolved imports. Once W3 resolves the imports, some may become *needed*, so a post-W3 regeneration would keep them as live ignores and **silence real errors**. CF-12 forbids that (Rev2 `:126-135`). Removing them now, while they are provably unused, means W3 sees and counts any such error instead. STAGE is also ready, small and mechanical, while W3 is a larger build. |
| W3 Stage 0 STOP rule | W3 r3 §7 step 0 stops if any ceiling differs from its §4 T2 values by more than ±5%. After STAGE those values shift. Corrected bounds: `scripts/analysis` T2 158 → **[150, 158]**; `tests/contract` 9 → **5**, since none of its 4 removed ignores is in an `import-not-found` file; `tests/unit` 1412 → **[1249, 1266]**, where the upper bound adds back all 17 resurfacing candidates; `scripts/archive` 3 and `scripts/venue` 11 unchanged. Without a note, W3's Stage 0 would trip mechanically. |
| W3 measurement hazard | §1.4: W3 r3's T2/T3 finding of 6 `trade.py` errors (`src/breezy/app` pin, W3b) matches exactly the phantom produced by a copy without `PYTHONPATH`. W3's Stage 0 already re-measures twice. It **must** do so with `PYTHONPATH=<wt>/src`, and should treat the `src/breezy/app` pin as unconfirmed until it does. This plan does not re-open W3; it hands W3 this measured fact. |

**Deliverable for W3, docs only:** at STAGE close-out, append a dated "Post-CF-12-STAGE note" to `reviews/CF-12-W3-r3-final.md`. It records:
- the STAGE merge SHA;
- the corrected Stage 0 bounds above;
- the `check_mypy_exit` reuse;
- the §1.4 `PYTHONPATH` hazard.

The approved W3 plan text is not edited. The W3 build brief must cite the note.

---

## §5 Exact steps

Before step 0:
- **Build location:** a fresh worktree created through the operator-approved execute-backlog flow, on a new branch `backlog/cf12-stage-r1-2026-10-03` cut from the **current tip** of `feat/data-capture-and-risk`. Agent worktrees can start stale, so verify `git rev-parse HEAD` equals `git rev-parse feat/data-capture-and-risk`, and fast-forward first if it does not.
- **Every command** runs as `cd <wt> && PYTHONPATH=<wt>/src …`, with the interpreter `/home/jon/breezy/.venv/bin/python`.
- **Never** run `uv run`, `uv sync`, `pip` or `git stash`, and never use `git add -A` or `-am`. Briefs are written with Write, not heredocs.

### Step 0: Stage 0 re-measure (read-only)
1. `cd <wt> && PYTHONPATH=<wt>/src env -u FORCE_COLOR NO_COLOR=1 MYPY_FORCE_COLOR=0 /home/jon/breezy/.venv/bin/python -m mypy --cache-dir <scratch>/s0a > <scratch>/s0a.txt 2>&1; echo rc=$?`. Repeat with a fresh cache (`s0b`).
2. Record: exit code (must be 1); the summary line; per-group counts with the ratchet's own `parse_mypy_report` and `_matching_entry` grouping; the `[unused-ignore]` count; and the `src/breezy/app` count (must be **0**).
3. Cross-check the regenerated set against `d4bc9ac4` with the `(path, stripped text)` multiset method of §1.2. Record `both / only_branch / only_head`.
4. **STOP and return to plan review if:**
   - the two runs differ;
   - the exit code is not 1;
   - `src/breezy/app` > 0 (environment wrong, §1.4);
   - any `Unused "type: ignore[x]"` (partial-code) message appears;
   - `only_branch + only_head` > 10% of the set.

   Smaller drift does not stop the work: the regenerated set wins, and the drift is recorded in the commit body.

### Step 1: ratchet hardening, RED first (commit A)
1. Port the three tests from `70bcb7e1` into HEAD's `tests/unit/test_mypy_ratchet.py`, verbatim:
   - `test_mypy_exit_code_two_raises_parse_error`
   - `test_mypy_exit_codes_zero_and_one_are_accepted` (parametrized over 0 and 1)
   - `test_a_summary_with_errors_prevented_further_checking_raises_parse_error`
2. **RED:** `PYTHONPATH=<wt>/src /home/jon/breezy/.venv/bin/python -m pytest tests/unit/test_mypy_ratchet.py -k "exit_code or prevented_further" -p no:cacheprovider`. The new tests must fail, because `check_mypy_exit` does not exist (NameError) and the blocker summary parses. Record the output and the exit code; do not use `-q` (it doubles into `-qq`, so read the exit code).
3. **GREEN:** port the following from `70bcb7e1`:
   - `_BLOCKER_SUMMARY_TEXT` and `_OUTPUT_TAIL_LINES`;
   - `check_mypy_exit`;
   - the blocker-line guard at the top of `parse_mypy_report`'s loop;
   - in the fixture: `output = result.stdout + result.stderr; check_mypy_exit(result.returncode, output); return parse_mypy_report(output)`.

   **Keep** HEAD's `env=_mypy_subprocess_env()` and HEAD's fixture docstring sentence about colour. Re-run: the focused tests pass, and the whole file passes with ceilings still at HEAD values, because nothing is removed yet.
4. **Real-fixture RED (positive control, not committed):** in `<wt>`, temporarily set `mypy_path = ["src", "scripts/analysis", "scripts/venue", "scripts/archive", "scripts/ops"]`. That is W3's reproduced T1, which makes mypy exit 2. Run `pytest tests/unit/test_mypy_ratchet.py::test_mypy_stays_within_the_cf12_clean_set_and_ceilings` and confirm it fails with `mypy exited with 2; expected 0 or 1`. Then `git checkout -- pyproject.toml`, confirm with `git diff --stat` that `pyproject.toml` is clean, and record both outputs. This proves the hardening fires on the real subprocess path and not only on fake text.
5. Commit A, by explicit path: `test(cf12): ratchet rejects mypy exit≠0/1 and blocker summaries (port of 70bcb7e1 onto <sha>)`.

### Step 2: regenerated removal plus re-pin (commit B, one commit so every commit is ratchet-green)
1. Run the §3 removal tool against `<scratch>/s0a.txt`. Record the file count (expected 39) and the edit count (expected 185).
2. **AST-identity check** (scratchpad, not committed): for each touched `.py` file except `test_mypy_ratchet.py`, assert `ast.dump(ast.parse(git show HEAD:<f>)) == ast.dump(ast.parse(<wt>/<f>))`.
   - Positive controls: a one-token logic change and a deleted statement must each fail the check.
   - Assert `git diff --numstat` reports equal insertions and deletions per file.
   - Assert every removed line differs from its replacement only by the trailing ignore comment (`git diff -U0`, line-pair check).
3. Re-run mypy in `<wt>` (fresh cache). It must show **0** `[unused-ignore]`, exit 1, and per-group counts equal to Stage 0 minus the removal deltas. **No count may rise in any group or file.** A rise would mean a removed ignore was not actually unused; STOP.
4. **Ratchet RED:** `pytest tests/unit/test_mypy_ratchet.py::test_mypy_stays_within_the_cf12_clean_set_and_ceilings` must fail with exactly four `lower the ceiling to N` messages (expected `src/breezy/analysis` 3, `scripts/analysis` 352, `tests/contract` 7, `tests/unit` 1288) and nothing else. Record it.
5. Lower those four `CEILINGS` values to the **measured** N, with a dated comment: `# CF-12 Wave 2 (CF-12-STAGE, <date>, base <sha>): 185 unused ignores removed`. `CLEAN` is unchanged and no ceiling is raised.
6. **Ratchet GREEN:** the whole `tests/unit/test_mypy_ratchet.py` passes.
7. Commit B, by explicit path (the 39 files plus the ratchet file): `fix(types): CF-12 Wave 2 — remove <N> unused type: ignore (regenerated against <sha>; comment-only, AST-identical)`. The body records Stage 0 numbers and the d4bc9ac4 cross-check result.

### Step 3: lint
- `cd <wt> && /home/jon/breezy/.venv/bin/lint-imports`. Demand `Contracts: 7 kept, 0 broken.` (or the current N, with 0 broken). Never use `python -m importlinter`, which is a no-op.
- `cd <wt> && /home/jon/breezy/.venv/bin/ruff check <touched files>` and `ruff format --check <touched files>`. Neither may report a violation that is not also present at HEAD on the same files (compare against a HEAD run).

### Step 4: full gate (fails closed)
1. `systemd-run --user --unit=breezy-gate-cf12-stage-r1 --collect -p LimitNOFILE=524288 /home/jon/.cache/breezy-gate/gate.sh <wt> cf12-stage-r1`
   - `gate.sh` runs `scripts/ci/run_tests_no_egress.sh` with `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`, `PYTHONPATH=<wt>/src` and `--basetemp` under `~/.cache` (never the scratchpad).
   - Baseline wall time is about 17–23 minutes.
2. Arm a watch in the same turn. Wait on `systemctl --user show -p ActiveState breezy-gate-cf12-stage-r1` leaving `{active, activating}`, never on `is-active`.
3. **Read `~/.cache/breezy-gate/cf12-stage-r1.exit` and the `GATE_EXIT=… head=…` line before anything else.**
   - Required: `GATE_EXIT=0`, and `head` = commit B's SHA.
   - Never chain a push or cleanup after the readout.
   - Non-zero means: no merge. Triage the failures by name. A failure outside `test_mypy_ratchet.py` on a comment-only diff is either a concurrency or flake signal (re-run once and compare) or a real defect in the AST check. Never weaken a test to go green.

### Step 5: independent review (before merge)
- `python-reviewer` on `git diff feat/data-capture-and-risk...backlog/cf12-stage-r1-2026-10-03`. Its brief carries `PYTHONPATH=<wt>/src`, the AST-check output and the RED/GREEN evidence.
- The security-reviewer trigger is **not met**: no auth, permit, order, settlement, user-data or egress code changes.

### Step 6: merge and push
1. Re-check: `git rev-parse feat/data-capture-and-risk` must still be the base the gate ran on. Then `git merge --ff-only backlog/cf12-stage-r1-2026-10-03`. Run it from the primary tree, which is checked out on `feat/data-capture-and-risk`, and commit/merge only by explicit ref.
2. **If the tip moved** (it is not ff-able): rebase the branch onto the new tip. Then:
   - re-run step 0.1–0.3 (the regenerated set must still be 0 `unused-ignore` after the rebase; any new unused ignore introduced by an intervening commit is **left alone**, since it is out of scope, but it will surface as a ceiling message);
   - re-run step 2.6 and step 4 on the rebased SHA;
   - read the EXIT, then merge.
3. `git push origin feat/data-capture-and-risk` **only after** reading `GATE_EXIT=0` for that exact SHA.
4. Post-merge, in the primary tree: run the ratchet test once (`PYTHONPATH` unset, as the primary gate runs) and require a pass.

### Step 7: docs (separate `docs(...)` commit, explicit paths)
- `docs/core/PROGRESS.md`: close CF-12-STAGE with the commit A and B SHAs and the measured ceilings. Under CF-12-W3, add a pointer to the Post-STAGE note.
- `docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md` execution log (after `:118`): record that W2 landed as regenerated, with the actual post-W2 ceilings (3 / 352 / 7 / 1288; the 09-29 projection of 356 / 1303 was stale) and the new total.
- `reviews/CF-12-W3-r3-final.md`: append the Post-CF-12-STAGE note (§4).

---

## §6 Evidence required before "done"
| ID | Evidence | Kind |
|---|---|---|
| E0 | Stage 0: two identical mypy reports (exit 1, `src/breezy/app` = 0), and the d4bc9ac4 cross-check counts | measurement |
| E1 | RED: the 3 ported hardening tests fail before the port; GREEN after | RED→GREEN |
| E2 | Real-fixture control: `mypy exited with 2` under the T1 config; config restored, `git diff` clean | positive control |
| E3 | AST identity of all touched non-ratchet files, plus the checker's 2 positive controls | invariant |
| E4 | Post-removal mypy: 0 `unused-ignore`, no group or file count rising | ratchet |
| E5 | Ratchet RED with exactly 4 `lower the ceiling` messages, then GREEN after re-pin | RED→GREEN |
| E6 | `lint-imports` `N kept, 0 broken`; ruff no new violations | lint |
| E7 | `GATE_EXIT=0 … head=<pushed sha>`, read before push | gate |
| E8 | `python-reviewer` verdict with no CRITICAL or HIGH findings | review |

Agent "tests pass" claims are not evidence. The coordinator re-reads the `.exit` file and the diff.

---

## §7 Invariants
- **Nautilus is unmodified.** No file under the venv or `nautilus_trader` is touched.
- **No behaviour change.** Commit B is comment-only (E3 proves AST identity). Commit A touches only a test module.
- **No test weakened.** `CLEAN` is unchanged and ceilings only go down. The ratchet gains guards (exit code and blocker summary) and loses none. No safety, settlement or contract test assertion changes. The 4 `tests/contract` edits are comment removals, AST-identical.
- **Not touched:** the operator caps (`operator.env`), live enablement or the permit, the NO-SEND firewall (`run_tests_no_egress.sh` is executed, not edited), and `allow_short`.
- No `type: ignore` is added, and no `ignore_errors` / `disable_error_code` / `files` change.

## §8 Activation and supervisor restart
**No supervisor restart is required.** No supervisor-loaded module changes:
- the only `src/` files edited are three `src/breezy/analysis` modules that nothing under `runtime/`, `app/`, `strategy/` or `adapters/` imports (§1.5; one of them is also fenced by an import-linter contract);
- the edit is comment-only (bytecode-equivalent: trailing comments do not move line numbers).

The node, the timers and `daemon-reload` are untouched. "Activate immediately" is therefore satisfied by the merge itself, with no restart window needed.

## §9 Rollback
- `git revert <B> <A>` (in that order) on `feat/data-capture-and-risk`, then gate and push.
- This restores the ignores and the old ceilings atomically per commit. Reverting B alone is self-consistent; reverting A alone is also consistent, because its ceilings are unchanged.
- There is no runtime, unit, data or venv state to undo.

## §10 The stale branches
- **Kept, untouched:**
  - `backlog/stage-cf12-w2-2026-09-29` @ `4b0b4f65`
  - `backlog/cf12-wave2-unused-ignore-2026-09-29` @ `d4bc9ac4`
  - `backlog/cf12-w0-exitcode-2026-09-29` @ `70bcb7e1`
  - their worktrees `.claude/worktrees/{stage-cf12,cf12-wave2,cf12-w0fix}`

  They are the provenance of the Codex work and the cross-check reference (§3). This plan deletes nothing.
- PROGRESS marks them **superseded by `<A>`/`<B>`**. A later prune by any session needs a one-line heads-up and `git cherry`/content evidence that the change landed. The branches were created by a prior session, not by this build.
- Do not merge the stale branch; its ceiling commit would re-pin stale values (356 / 1303).

## §11 Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Phantom `trade.py` errors from a worktree without `PYTHONPATH` | Medium (measured) | §1.4 rule; Stage 0 STOP when `src/breezy/app` > 0 |
| HEAD moves during the ~20 min gate (concurrent merges) | High | ff-only; rebase, re-measure and re-gate on any move |
| A concurrent slice adds or removes an unused ignore | Medium | Regenerated set; ratchet reports the exact N; out-of-scope ignores are left alone |
| A removed ignore was masking something (the count rises) | Very low (mypy marks them unused) | Step 2.3 "no count rises" STOP |
| Removal tool mangles a line | Low | Strict single-match regex, hard-fail rules, AST identity, line-pair diff check |
| W3 Stage 0 trips on shifted ceilings | Certain without the note | §4 Post-STAGE note with corrected bounds |
| mypy nondeterminism | Low | Two Stage 0 runs must match |

## Self-score
**93/100.**
- Strengths: every claim is measured at `f45f5a65`, including an exact 185/185 set match, the conflict map and the corrected ceilings. The method regenerates from mypy rather than replaying the diff. RED→GREEN covers both the hardening (fake text plus a real exit-2 positive control) and the ceilings. Ordering against W3 is argued from the 25 ignores that could become needed, with corrected W3 bounds. The `breezy.pth`/`PYTHONPATH` phantom-error hazard was found and its cause measured.
- Deductions:
  - −3: the W3 resurfacing upper bounds assume at most one error per previously ignored line.
  - −2: a Post-STAGE note appended to an approved W3 review artifact is a process choice that this plan's own peer review should confirm.
  - −2: the §1.4 finding implies W3 r3's `src/breezy/app` pin may be an artifact. This plan flags it but does not re-measure W3 T2 with `PYTHONPATH` set.
