**Verdict: REQUEST_CHANGES**
**ER-B1: AMEND · ER-B2: ADOPT with amendments**

The phase-2 gate as written cannot start: the repo's own conftest stops it before any test is collected. Even once that is fixed, it would not run the consumer plans' real-namespace tests. The other blockers are a lint design that contradicts a standing coordinator ruling (AC6), and a self-probe that breaks AUT-6's O-5 constraint. The placement, the snapshot algorithm, the bwrap facts the author measured, and the C4.1 filing are sound.

| Axis | Score |
|---|---|
| Correctness | 6 |
| Architecture fit | 7 |
| Test coverage | 6 |
| Risk mitigation | 6 |
| Scope minimality | 6 |
| Feasibility | 5 |

## Erratum requests

**ER-B1: AMEND.** The diagnosis (nested bwrap is denied by apparmor) is credible, and AUT-5 r7 l.287 already expected this case. AUT-5's prescribed remedy is "a separate un-nested step of **the same script**, never skipped". The plan's remedy has three problems:
1. **It cannot start (finding 1).** The N2 barrier rejects any session that lacks the no-egress attestation.
2. **It only collects `tests/integration/autonomy_sandbox` (finding 2).** AUT-5's, AUT-6's and AUT-4's real-namespace tests live elsewhere.
3. **It splits "the gate" into two commands.** ARCH §5.1, L-43 and every brief name `run_tests_no_egress.sh` as the full gate.

Amended text should say:
- Phase 2 is run by `run_tests_no_egress.sh` itself, both exit codes read.
- The `bwrap_host` marker and its skip/fail logic are registered from root `tests/conftest.py`.
- The N2 barrier gets an exact-set, security-reviewed widening (L-12) for phase 2 only.

**ER-B2: ADOPT with amendments.** PROGRESS row 4 already puts the wrapper and the snapshot helper in ARCH-0, so the move matches the queue. The plan keeps every consumer call shape. Before filing, the erratum also needs:
- (a) AUT-5's write-authority allowlist rows (r7 l.292) re-pointed from `autonomy_engine/{exec_snapshot,sandbox_probe}.py` to the new modules. The caller-supplied `cache_dir` must be allowed only when the caller passes one of its own module constants.
- (b) The consumer changes in findings 7, 8 and 9.
- (c) The header-digest addition recorded as an E-8 amendment, not as "not an erratum" (finding 12).

## Findings

**1. CRITICAL — Phase-2 gate / AC-7 / V0: phase 2 aborts before collecting anything.**
- **Problem:**
  - `tests/conftest.py:359-380` calls `execution_egress_abort_reason` (`:292-319`). That function returns an abort whenever execution-egress modules exist and `BREEZY_TEST_OS_EGRESS_BLOCK` is unset. Those modules do exist, and the phase-2 script deliberately leaves the variable unset (its line 291 refuses to run when it is set).
  - So `pytest -m bwrap_host` exits 2 at session start.
  - The plan defers this to V0, which runs after merge. Its R2 mitigation also relies on "the pytest parent keeps conftest's in-process block", which assumes this conftest runs normally.
- **Fix:**
  - Move this check to a verify-first step 0 of WP-B2, before any code is written.
  - Specify, with security-reviewer sign-off filed inside ER-B1:
    - an `importlib` meta-path blocker in phase 2 that refuses `breezy.adapters*` and `nautilus_trader*` before collection (prevention, not detection);
    - a narrow N2 widening that accepts `BREEZY_BWRAP_HOST_PHASE=1` only when that blocker is installed and collection is restricted to `bwrap_host` items;
    - a session-end check that `sys.modules` holds neither prefix.
  - Consumer real-namespace tests must then put Nautilus work in bwrap children only. State this as an obligation on the consumers.

**2. HIGH — Phase-2 gate / conftest row: consumer namespace tests are never run.**
- **Problem:** The script collects only `tests/integration/autonomy_sandbox`, and the marker plus the skip logic live in that directory's conftest. The consumers' tests are elsewhere:
  - AUT-5 `tests/integration/test_engine_bwrap_sandbox.py` and `test_exec_snapshot.py`;
  - AUT-6 `test_every_aut6_row_self_probe_both_directions_under_real_bwrap`, its sidecars test and its EXDEV control;
  - AUT-4's fixture row (r11 l.893).
  
  Those tests would not be skipped in phase 1, so they fail on the denied nesting. They would never be collected in phase 2. ER-B1 claims to solve their problem but does not.
- **Fix:**
  - Register `bwrap_host` and its phase-1 skip / phase-2 fail-not-skip in root `tests/conftest.py`, or in a `tests/support` plugin loaded from it. L-54 applies: grep the pins first, and treat it as a safety-reviewed item.
  - Phase 2 runs `-m bwrap_host tests/`.
  - `BWRAP_HOST_MIN_TESTS` becomes an exact literal that consumers widen.
  - Rewrite `test_phase2_script_targets_only_bwrap_host_dir`, which currently pins the wrong behaviour.
  - Make `run_tests_no_egress.sh` run both phases. This means dropping `exec` in `run_bwrap`; search the pins first per L-54.

**3. HIGH — AC-4 / shared lint: the denylist contradicts coordinator ruling AC6.**
- **Problem:**
  - `reviews/AUT-6-r9-merged.md:11-15` replaced the forbidden-construct denylist with an **allowlist**, binding on AUT-1, AUT-5 and AUT-6. AUT-5 r7 l.288 has adopted it. The plan's `DENYLIST` brings back the "growing denylist" that ruling retired.
  - No consumer row calls `judge()`. E-7a rule 4 makes each plan's own closure test the lint.
  - `subprocess.*` would flag AUT-1 capture-audit's literal `journalctl` and `systemctl` argvs (r12 l.939).
- **Fix:**
  - Drop AC-4 and the lint parts of WP-B3.
  - Export `SHARED_WRITE_SITES: Final`, the (module, function, call) entries for `wal_snapshot` and `self_probe`, for consumers' allowlists to import.
  - If a shared lint is kept, rebuild it as the AC6 allowlist and add consumer rows to ER-B2.

**4. HIGH — AC-2 / `self_probe.py`: the positive probe puts named files into consumer binds.**
- **Problem:**
  - AUT-6 r15 l.260-261 requires that positives go in a `.bwrap_probe/` subdirectory for `evidence/` and `cache/` binds, and use `O_TMPFILE` for `registry/demand/` and `derived/verdicts/`, so that no listing ever sees a probe name (O-5).
  - It also requires negatives to fail with exactly `EROFS`.
  - The plan creates `.autonomy_probe_*` in each bind root, including AUT-5's whole `registry/`, beside the C5 store that the watch actor lists. It also accepts `EACCES` and `EPERM`, so an unwrapped run against a mode-0500 directory would pass.
- **Fix:**
  - Add a per-bind positive mode, `tmpfile` (default; E-7a confirmed ext4) or `subdir`, derived in `self_probe_plan`.
  - Require exactly `EROFS` on negatives.
  - Use AUT-6's reason vocabulary: `negative`, `negative_registry`, `positive_<bind>`, `probe_residue`.
  - Check the env row before any open, so an unwrapped run never writes into `state/`.

**5. MEDIUM — AC-1.5 / AC-2: notifier "degraded" semantics are unspecified.**
- **Problem:** The plan does not say what `require_sandbox` does when `BREEZY_AUTONOMY_SANDBOX_DEGRADED` is set, and that variable can be forged.
- **Fix:**
  - Honour it only for rows with `notifier_fallback=True`. The probe then returns `ok=False, degraded=True` and never `ok=True`.
  - Other rows ignore the variable and raise.
  - R7 must also state that degraded mode exposes the `~/.config/breezy` credentials, not only a wider write scope.

**6. MEDIUM — AC-5: the unit-lint scope is a filename glob.**
- **Problem:**
  - `breezy-autonomy-*` misses autonomy-owned units with other names: AUT-1 `breezy-capture-audit`, AUT-2's reconcile units and `breezy-aut2-recon-failed@`. E-7a rule 1 says "every autonomy-owned unit".
  - The glob also matches the wrapper script `deploy/systemd/breezy-autonomy-bwrap`, which is not a unit. AUT-5's unit parsers and `live_proof_paths()` use the same prefix.
- **Fix:** Lint the union of every table row's `units` and an exact `AUTONOMY_OWNED_UNITS` set (L-12). Filter to `*.service`, `*.timer` and `*.d/*.conf`. Add a test that the wrapper is excluded from unit parsing.

**7. MEDIUM — AC-1.1 cgroup check vs AUT-5's E-6 transient fallback.**
- **Problem:**
  - AUT-5 r7 l.275's fallback for the one-time L1 bootstrap is a transient service, named `run-u*.service` unless `--unit=` is given. Its name will not be in the engine row, so the wrapper exits 78 on that one-shot run.
  - The plan also does not define what happens when the cgroup line's last component is a sub-cgroup (`Delegate=`).
- **Fix:**
  - Keep the check; it is the literal reading of E-7a's "resolves its row by unit name".
  - Flag a consumer change: AUT-5's fallback must pass `--unit=<name listed in the bootstrap row>`.
  - Add `test_main_transient_run_unit_exits_78` and a test for the sub-cgroup case, and document both in the README.

**8. MEDIUM — Consumer table, AUT-6 row: an unflagged directory re-bind.**
- **Problem:**
  - `breezy-autonomy-producer-daily` re-binds the directory `~/.config/systemd/user` (r15 l.249).
  - The plan describes `config_ro_binds` as regular files (E-7: "files"; AUT-5 l.278: "never a directory"), but `validate_table` never checks the type.
- **Fix:** Rule on one of two options and check the type at runtime in `main`:
  - files only, flagged as an AUT-6 change; or
  - a named exception, `E7_CONFIG_DIR`, with no-symlink and not-under-`breezy/` checks.

**9. MEDIUM — Consumer table, AUT-5 row: a missed rule-3 violation.**
- **Problem:** AUT-5 r7 l.386 says the 15:30Z daily and every intraday advisory read use the G6 `mode=ro` URI inside bwrap. That violates E-7a rule 3 and E-8a.
- **Fix:** Flag it exactly as AUT-2 is flagged: `exec_snapshot(take_flock=False)`, advisory. Add it to ER-B2 and R9.

**10. MEDIUM — Fidelity to E-13 / AUT-4 test names.**
- **Problem:**
  - AUT-4 r11 l.1648 names `tests/contract/test_autonomy_units.py::test_wrapper_malformed_tmpfs_size_fails_closed` (inputs `"2G"`, `0`, `-1`, `True`, and a value above the maximum; "exits non-zero before bwrap runs") and `::test_wrapper_applies_default_tmpfs_size_to_rows_without_one`. E-13 adopts these.
  - The plan uses different files and names, and tests `validate_table` rather than the wrapper exit.
- **Fix:** Use AUT-4's paths and names. Drive the tests through `main()` with a sentinel `bwrap_path`, and assert that exec was never reached.

**11. MEDIUM — V11 (AUT-4 l.875): the deployed-blob sha check is hollow.**
- **Problem:** The script is four lines; all the logic is in `src/breezy/runtime/autonomy_sandbox/*.py`. Hashing the script proves nothing about the code that runs.
- **Fix:** V11 hashes the script plus every package module as a manifest. Export `WRAPPER_CODE_FILES` so AUT-4's check covers them; tell AUT-4.

**12. LOW-MED — AC-3 / snapshot data flow.**
- **(a) Sweep relies on an unchecked invariant.** Sweeping `snap.*` depends on the caller keeping one writer per cache dir (L-50).
  - Fix: `flock(LOCK_EX|LOCK_NB)` an `O_RDONLY|O_DIRECTORY` fd of the cache dir before sweeping and `mkdtemp`. Contention gives a new reason, `CACHE_BUSY`.
- **(b) Copy order is unstated.**
  - Fix: specify db, then `-wal`, then `-journal`.
- **(c) The header digest is load-bearing.** For `take_flock=False`, a checkpoint plus WAL reset between the db copy and the wal copy changes neither size nor (often) the coarse mtime, but it does change the WAL salts.
  - Fix: strike "removable by deleting one field" and record the digest as an E-8 amendment, because AUT-5 r7 l.391 restates the bare triple.

**13. LOW — AC-1.2: no runtime test for a symlinked bind component.**
- **Problem:** bwrap follows the source symlink. A link such as `cache/x → ../state` is the main way out of the sandbox, and only table-level validation is tested.
- **Fix:** Add `test_main_symlinked_bind_component_exits_78` and a test for a symlinked data root. State the validate-then-mount TOCTOU as a same-uid residual (E-7a rule 5).

**14. LOW — `build_bwrap_argv(extra_namespace_flags=…)` is reachable in production.**
- **Fix:** Restrict it to the exact set `{"--unshare-net"}`. Add an AST test that `main` never passes it.

**15. LOW — AC-6 filing note.**
- **Problem:** The `file:line` citations outside the markers will rot, and in a file AUT-3 and AUT-4 cite by name they read as an annotation of the ruling.
- **Fix:** Move them to the commit message (YAGNI).

**16. LOW — `validate_table` label `E7A_R2_PROC_LOCKS`.**
- **Problem:** AUT-6 `breezy-autonomy-health` drops `--unshare-pid` for `/proc/<pid>` RSS, not for `/proc/locks`.
- **Fix:** Rename the label `E7A_R2_PROC` (or use two labels). The rule-2 test should scan `/proc/<pid>` references too.

**17. LOW — V-steps.**
- **Problem:** If the sandbox is broken, V6 leaves `.v6` in `state/` and V7 leaves `.v7` in the repo. V10's "state unchanged" will be flaky while the node writes there.
- **Fix:** Put an `rm -f` in the same step and record it. In V10, assert only that no `snap.*` or probe names appear in `state/`.

## Other review questions

- **Placement (Q3): sound.**
  - `runtime` sits below `analysis` in the layers contract (`pyproject.toml:74-101`), so both AUT-1's runtime CLIs and the analysis engines can import it.
  - `breezy/runtime/__init__.py` is import-free by contract (`test_runtime_import_isolation.py:1-41`).
  - A new top-level package would have to edit the `exhaustive=true` layers contract.
  - The 392 ms Nautilus import cost of `persistence` is a valid, measured reason. Document the deviation from ARCH §3 in ER-B2.
- **YAGNI (Q4):**
  - Header digest: keep; it is load-bearing (finding 12c).
  - Notifier fallback: keep; E-7a rule 1 mandates it.
  - Cgroup binding: keep; it is E-7a's literal requirement (with finding 7).
  - Shared lint: drop (finding 3).
  - Filing note: drop (finding 15).
- **Sequencing (Q5):**
  - WP-B2 must open with the N2/V0 verify-first step and the root-conftest marker plumbing (L-54, safety-reviewed). Both are hidden dependencies today.
  - WP-B3 is on the critical path for AUT-1a, AUT-5a and AUT-6 (row 4 → rows 5, 6, 7), and shrinks once the lint is dropped.
  - WP-B1 can run fully in parallel.
  - Seam B has no seam-A dependency (it is stdlib only). State that explicitly, because nothing records an A/B split anywhere.

## LESSONS violations (headers grepped)

- **L-46 (rule 1):** the gate surface's contract tests were not searched. The N2 barrier (`tests/conftest.py:292-380`, `tests/unit/test_execution_egress_firewall_guard.py`) breaks phase 2, and it is missing from the plan's L-46 row.
- **L-47 (rule 2):** R2 and V0 assume conftest behaves normally in an unattested session (keeps its in-process block). The repo's own conftest refuses that session.
- **L-54:** the plan avoids editing shared config, but that avoidance is what leaves consumer tests uncollected. The fix needs a pin-searched, safety-reviewed edit to root conftest and the gate script.
- **No violations of L-1, L-12, L-14, L-22, L-33, L-42, L-43, L-50, L-51 or L-55.** The L-1 null-hypothesis table is adequate.

## Path hygiene

Clean. Every path is repo-relative or absolute under `/home/jon/breezy`, and none is plugin-namespaced.

## Files cited

- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r1.md`
- `/home/jon/breezy/tests/conftest.py`
- `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-6-r9-merged.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/pyproject.toml`
- `/home/jon/breezy/docs/core/PROGRESS.md`