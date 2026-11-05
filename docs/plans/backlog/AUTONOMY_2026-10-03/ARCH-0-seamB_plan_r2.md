Evidence is complete. All three verify-first surfaces are cited, and nine host facts are measured (scratch under `/tmp/claude-1000/seamb` only, no repo writes). The complete r2 plan follows.

# Build plan r2: ARCH-0 seam B (sandbox wrapper, WAL snapshot helper, C4.1 holdout ruling)

**Basis**
- Frozen ARCH Rev 9.2. `AUTONOMY_ARCHITECTURE.md` and `reviews/snapshots/ARCH_rev9_2.md` both re-hash to `1b288d0e…2f42` in this session.
- Errata E-7, E-7a, E-7b, E-7c, E-8, E-8a and E-13; the AC6 ruling (`reviews/AUT-6-r9-merged.md:11-15`); coordinator rulings B-R1..B-R8 (`reviews/ARCH-0-r1-merged.md:6-41`).
- HEAD `d231497d` on `feat/data-capture-and-risk`.
- I wrote no repo file and changed no state. Probes ran only against scratch under `/tmp/claude-1000/seamb/`, using `-B` and `-p no:cacheprovider` so nothing was written into the repo.

**MEASURED this session**

Each fact below is cited elsewhere as M-n.

| # | Fact | How |
|---|---|---|
| M1 | Nested bwrap is denied ("No permissions to create a new namespace", rc 1). One level outside the gate works. | r1 probe, repeated by security |
| M2 | Under a meta-path blocker that refuses `nautilus_trader*` and `breezy.adapters*`, `tests/conftest.py:280` fails `pytest_configure` with `ModuleNotFoundError: nautilus_trader` (via `tests/support/nautilus_log_capture.py:33,40`). | Scratch pytest run: `-p <blocker> -p tests.conftest` |
| M3 | A scratch copy of the root conftest with two edits (skip the Nautilus logger pin in phase 2; admit phase 2 at N2) gave a pytest parent that passed 2 tests with **zero** `nautilus_trader*` and `breezy.adapters*` entries in `sys.modules`. Importing `tests.unit.test_execution_egress_firewall_guard` under the blocker succeeds. | Scratch copy only |
| M4 | `find_execution_egress_modules()` reports 9 paths today, all under `src/breezy/adapters/polymarket_us/` (`exec/*`, `factories.py`, `write_transport.py`). | Read-only import |
| M5 | `--disable-userns` requires `--unshare-user` (rc 1 without it). With it: nested `unshare -U` fails ENOSPC, uid stays 1000, and `/proc/1/comm` is `bwrap` under `--unshare-pid`. `/proc/locks` shows 0 lines with `--unshare-pid` and 152 without (host 152). | bwrap 0.11.1 |
| M6 | `--tmpfs ~` + ro re-binds of the repo, data root and interpreter prefix + `--remount-ro ~`. Home lists `['.config','.local','breezy']`; `~/.ssh` and `~/.config/breezy` are absent. `O_TMPFILE` gives EROFS on home, `state/` and the repo, and succeeds on a `--bind-fd` bind (that bind stays writable after the remount). Host config files re-bound after the home tmpfs are readable. | Scratch fake bind source |
| M7 | `--tmpfs` over a path that does not exist fails ("Can't mkdir … Read-only file system"). A hide-by-name list therefore breaks on hosts where a listed name is absent; `~/.gnupg` and `~/.netrc` are absent here. | Probe |
| M8 | `--bind-fd` with an `O_PATH\|O_DIRECTORY\|O_NOFOLLOW` fd works, and so does `--ro-bind-fd` with an `O_PATH\|O_NOFOLLOW` regular-file fd. | Probe |
| M9 | Under `--tmpfs /run/user/1000` the directory is empty, so neither `systemd/private` nor `bus` can be reached. | Probe |
| M10 | A unix datagram socket ro-bound at `/run/user/1000/systemd/notify` under `--unshare-user --unshare-pid` accepts connect and send; the host receives `READY=1`. | Scratch socket |
| M11 | The venv interpreter resolves to `~/.local/share/uv/python/cpython-3.13.13…`, which is under home, so it must be re-bound. | `readlink -f` |
| M12 | A live listing of home dot-entries has more than 30 credential-bearing entries, among them `.claude*`, `.codex`, `.grok`, `.git-credentials`, `.mcp-auth`, `.cmp-prod-db-url`, `.cmp-seo-token`, `.docker`, `.wrangler`, `.serverlessrc`, `.ssh`, `.aws` and `.config/gh`. | Names only; no contents read |
| M13 | `~/.local/share/breezy/cache` does not exist on the host. The data root is ext4 (`findmnt`). | `ls`, `findmnt` |

**Gate surface (verify-first; file:line at HEAD)**
- `scripts/ci/run_tests_no_egress.sh:36-43`: `run_bwrap` uses **`exec bwrap`** (l.37). `:50-52`: `run_unshare` uses **`exec unshare`** (l.51). Dispatch is at `:54-62` and the refuse-exit 3 at `:64-70`. Nothing can run after phase 1 today.
- `tests/conftest.py`:
  - N2 rule: `execution_egress_abort_reason` `:292-326`;
  - session evaluation, which lazily imports the guard module (`:341-345`): `:329-356`;
  - `pytest_sessionstart`, credential gate first: `:359-367`;
  - abort with rc 2: `:370-380`;
  - `pytest_configure`, with the pyo3 block at `:275` (tolerates ImportError, `:131-136`) and the Nautilus logger pin at `:280-282`: `:247-282`.
- `tests/unit/test_execution_egress_firewall_guard.py` pins:
  - N3: `:458-461` (exact `"1"`), `:493-516`;
  - N2: `:567-572` (live), `:575-600`, `:969-986` (unattested child aborts before collection, rc 2), `:989-1023`, `:1026-1075` (three-kwarg calls of `execution_egress_abort_reason`);
  - N5: `:1078-1083` (launcher exists, is executable, contains `BREEZY_TEST_OS_EGRESS_BLOCK`) and `:1086-1118`;
  - X1: `:1474-1498` (reads the conftest AST to pin the marker set of `_is_real_network_test`, `conftest.py:461-467`);
  - `_child_pytest_env` (`:911-938`) pops only `BREEZY_TEST_OS_EGRESS_BLOCK`.
- Other pins:
  - `tests/unit/test_polymarket_us_phase0_safety.py:281-287` pins `OS_EGRESS_BLOCK_COMMAND`;
  - `tests/unit/test_tier_infra.py:91` pins the wrapper name in `run_tier.sh`;
  - `scripts/ci/run_t1_lanes.sh:22-26` derives its partition proof from `"$WRAPPER" --collect-only` output, and `:64-65,:81` run the wrapper per lane;
  - `tests/unit/test_operator_control_assignment_scan.py:525` scans `tests/conftest.py`;
  - `tests/unit/test_test_safety_tooling_config.py:49-65` reads import-linter contracts by name.
- No test pins `exec bwrap` or `exec unshare`: grep of `tests/` for `exec bwrap`, `run_bwrap` and `dev-bind` finds only `:1108`, the N5 probe argv, which is unaffected.
- Sub-conftests that load Nautilus: `tests/unit/conftest.py:20-21` (`breezy.strategy`) and `tests/contract/conftest.py:16`. `tests/integration/` has no conftest.

**Erratum requests (texts in §ERRATA-REQUEST)**
- **ER-B1 (amended per B-R1):** one gate in two phases, inside `run_tests_no_egress.sh`. Phase 2 has an exact-set N2 admission, a meta-path blocker and an exact registry of test files.
- **ER-B2 (ADOPT with amendments, per B-R2):** the ownership move, plus amendments (a)–(g).

---

## §R2 Disposition

| Finding | Verdict | Where (r2 §) |
|---|---|---|
| **B-R1 / Sec-1 / Arch-1** Phase 2 aborts at N2; the parent is not prevented from loading order code | FIXED. One script runs both phases. Phase 2 has: the meta-path blocker loaded with `-p` before conftest; an exact N2 admission (5 conditions; the three-kwarg call is byte-identical); a credential gate unchanged and first; a session-end `sys.modules` check; `--unshare-net` on every child. M2 and M3 measured. This is WP-B2a with security sign-off. | AC-7, Arch "Gate", ER-B1 |
| Sec-1 alternative (stdlib-only runner) | REJECTED. B-R1 allows it only if it still runs the consumers' pytest tests (fixtures, `tmp_path`, parametrize), which would mean re-implementing pytest. M3 proves the ruled design works with two conftest edits. | Trade-offs |
| **Arch-2** Consumer namespace tests never collected; the marker lives in a subdir conftest | FIXED. `bwrap_host` plus the phase-1 skip and phase-2 fail-not-skip live in the `tests/support/bwrap_host_phase.py` plugin, loaded by root conftest `pytest_plugins`. Phase 2 runs the exact `BWRAP_HOST_TEST_FILES` (AST-equality test). The exact literal `BWRAP_HOST_EXPECTED_TESTS` replaces the "minimum". The script is rewritten without `exec`. `test_phase2_script_targets_only_bwrap_host_dir` is removed (it pinned the wrong behaviour). Not `-m bwrap_host tests/`: collection would import every test module, and the blocker would error on `tests/unit/conftest.py` (M2). | AC-7, File plan |
| **B-R3 / Arch-3** The shared denylist contradicts AC6 | FIXED. AC-4 and the shared lint are dropped. `SHARED_WRITE_SITES: Final` is exported, with a self-consistency test, together with the B-R2(a) cache-dir predicate. | AC-4, File plan |
| **B-R4 / Sec-2 / Arch-4** The probe writes named files into `state/` and bind roots; EACCES is accepted | FIXED. Env-row check before any open. Negatives are `O_TMPFILE` and require exactly EROFS (M6). Fallback is `statvfs` plus mountinfo, never a named create. Positives are `tmpfile` (default) or `subdir` per bind. AUT-6 reason vocabulary. A listing-unchanged test. | AC-2 |
| **B-R5 / Sec-3 / Arch-13** Bind TOCTOU; symlinked bind component | FIXED. Per-component `O_PATH\|O_DIRECTORY\|O_NOFOLLOW` walk from `/`; `st_dev`/`st_ino` checked against `state/` and every ancestor; data-root device check; `--bind-fd` (M8). Tests for a swapped symlink, a symlinked component and a symlinked data root. The residual narrows to "the walk itself is same-uid racy", which only produces a fail-closed refusal. | AC-1.2 |
| **B-R5 / Sec-5** `config_ro_binds` symlink or hardlink | FIXED. Nofollow walk; regular file; `st_nlink == 1`; dev/ino not equal to any entry under `~/.config/breezy`; `--ro-bind-fd` (M8). Fixtures for a symlink, a hardlink and `..`. | AC-1.2 |
| **B-R5 / Arch-8** AUT-6 directory re-bind of `~/.config/systemd/user` | FIXED. Named exception `E7_CONFIG_DIR` with the same checks plus "contains no entry resolving under `breezy/`"; type checked at runtime in `main`. | AC-1.2, ER-B2(c) |
| **B-R6 / Sec-4** `~/.ssh`/`~/.aws` readable; systemd bus reachable; nested userns | FIXED, and stronger than the ruling. M12 (30+ credential entries) and M7 (`--tmpfs` over an absent name fails) show a pinned hide list is a recalled barrier (L-14), so r2 hides **all of home** and re-binds only the pinned exact set `HOME_REBINDS` = {repo, data root, interpreter prefix if under home} plus per-row config files (M6). `--tmpfs /run/user/<uid>` (M9); notify rows re-bind only the `NOTIFY_SOCKET` path (M10). `--unshare-user --disable-userns --assert-userns-disabled` on **every** row (M5). The four ruled names are explicit ENOENT negatives. The bugs-not-hostile-uid residual is stated. | AC-1.3, AC-2, R15 |
| **B-R8** Placement rationale; forbidden contract | FIXED. Rationale replaced by the seam-A Q5 reasons (`ARCH-0-seamA-r1-architect.md:48-56`). New contract `breezy.runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy`, `allow_indirect_imports=false`; fresh-subprocess import test. The 392 ms argument is struck. | Architecture, Trade-offs |
| **B-R2 / Arch ER-B2 (a)(b)(c)** | FIXED. (a) Allowlist re-point plus the module-constant `cache_dir` predicate. (b) Consumer changes for Arch-7/8/9. (c) The header digest becomes an E-8 amendment. | ER-B2 |
| Sec-6 Torn read inside one mtime tick | FIXED. Quiescence guard of 20 ms; db header bytes 0–99 (covers 24–40); `-wal` bytes 0–31 plus the last 4 KiB; size; frozen-clock test; `advisory=False` only with the flock held from first to last fingerprint. | AC-3.4 |
| Sec-7 Flock vs node boot | FIXED. AC: `take_flock=True` only in the AUT-5 pre-launch pass, and its deadline must precede the 16:50 launch. Test: while the helper holds, `hold_submit_intent_process_lock` in a child fails fast (no block); after release it succeeds. | AC-3.2, Tests |
| Sec-8 The cgroup check is not a boundary; parse gaps | FIXED. The AC and README say "misconfiguration integrity, not authorisation". Exit 78 for: missing `0::` line, more than one line, a non-`.service` leaf, scope, slice, sub-cgroup. | AC-1.1 |
| Sec-9 Unbounded notifier fallback | FIXED. `NOTIFIER_FALLBACK_ROWS` is an exact set (empty in seam B). Fallback runs only after all validation, so a 78 never falls back. Degraded mode is honoured only for notifier rows. `degraded_write_target()` refuses any path outside the row's binds and anything under `state/`. Consumers' closure tests prove alerts-only writes. | AC-1.5, AC-2 |
| Sec-10 Preflight bounds | FIXED. `timeout=2`, list argv, no cached verdict written anywhere. | AC-1.5 |
| Sec-11 Use `fstat` of an fd, not `lstat` | FIXED. Cache dir via a nofollow walk plus `fstat`; copies via `dir_fd`/`openat`. | AC-3 |
| Sec-12 / Arch-11 V11 hashes only the 4-line script | FIXED. `WRAPPER_CODE_FILES` manifest (script plus every package module); V11 compares the manifest against the merge sha; AUT-4 is told (ER-B2(f)). | V11 |
| Sec-13 Coverage gaps | FIXED. All ten tests are added and named in the Test Strategy. | Tests |
| Arch-5 Degraded semantics; forgeable env | FIXED. Notifier rows only, `ok=False, degraded=True`; other rows raise `degraded_forged`. The wrapper `--unsetenv`s the variable inside every sandbox (L-22). R7 now states that degraded mode exposes `~/.config/breezy`. | AC-1.5, AC-2, R7 |
| Arch-6 Unit lint scope is a glob that matches the wrapper | FIXED. Lint set = (row `units` ∪ exact `AUTONOMY_OWNED_UNITS`) restricted to `*.service`, `*.timer` and `*.d/*.conf`. Tripwire: every `breezy-autonomy-*.service` file is in the set. Test that the wrapper is excluded. | AC-5 |
| Arch-7 Transient `run-u*` bootstrap; sub-cgroup leaf | FIXED. The check is kept. Consumer change: AUT-5's `-p` fallback (r7 l.275) passes `--unit=breezy-autonomy-engine-l1-bootstrap.service`, listed in the bootstrap row. Tests: `test_main_transient_run_unit_exits_78` and the sub-cgroup case. | AC-1.1, ER-B2(f) |
| Arch-9 AUT-5 l.386 G6 in place under bwrap | FIXED (flagged). Becomes `exec_snapshot(take_flock=False)`, advisory. | Consumer table, R9 |
| Arch-10 E-13 test names and paths | FIXED. `tests/contract/test_autonomy_units.py::test_wrapper_malformed_tmpfs_size_fails_closed` and `::test_wrapper_applies_default_tmpfs_size_to_rows_without_one`, driven through `main()` with a sentinel `bwrap_path`; they assert exec is never reached. | Tests |
| Arch-12a/b/c | FIXED. Cache-dir flock gives `CACHE_BUSY`; copy order db → `-wal` → `-journal`; "removable" claim struck, digest becomes an E-8 amendment. | AC-3, ER-B2(b) |
| Arch-14 `extra_namespace_flags` reachable in production | FIXED. Exact set `{"--unshare-net"}`, otherwise `ValueError`. AST test that `main` never passes it and that only `tests/support/bwrap_harness.py` does. | Tests |
| Arch-15 Filing note rots | FIXED. Moved to the WP-B1 commit message. | File plan |
| Arch-16 `E7A_R2_PROC_LOCKS` mislabels `/proc/<pid>` | FIXED. Renamed `E7A_R2_PROC`; the reference test scans `/proc/locks` and `/proc/<pid>`/`/proc/{`/`/proc/" +` literals. | AC-1, Tests |
| Arch-17 V6/V7 litter; V10 flaky | FIXED. V6/V7 use `O_TMPFILE`, so no name can be created. V10 asserts only that no `snap.*` or probe names appear in `state/`. | V-steps |
| Arch L-46/L-47/L-54 violations | FIXED. Gate surface verified with file:line above; pins searched (no `exec` pin; X1 conftest-AST pin untouched); conftest and script edits are a separate safety-reviewed WP (B2a). | LESSONS |
| Arch Q5 "no seam-A dependency" | FIXED. Stated: seam B is stdlib plus `breezy.runtime` only and imports nothing from `persistence/autonomy`. | Work Packages |

---

## Acceptance Criteria

**AC-1: shared wrapper (E-7a rule 1, E-7c, E-13 ER-1, ER-B2(c))**
1. `deploy/systemd/breezy-autonomy-bwrap ROW CMD [ARGS…]`:
   - `ROW` must fullmatch `^breezy-[a-z0-9-]+(@[a-z0-9-]*)?([.#][a-z0-9-]+)?$`, else 64. This rejects newline, `--` and empty strings.
   - An unknown row gives 78; there is no default.
   - The unit check reads `/proc/self/cgroup`. It must contain exactly one line, `0::<path>`, whose leaf ends `.service`. The leaf must equal a `units` entry, or match a `name@` entry as `name@<instance>.service`. Otherwise 78. Scope, slice, sub-cgroup (`Delegate=`), cgroup-v1/hybrid and empty inputs all give 78.
   - The README and the module docstring state: **"integrity against misconfiguration, not an authorisation boundary."** Any same-uid process can start a unit with a row's name.
2. **Bind integrity:**
   - Each bind is data-root-relative and resolved under `SandboxRoots.data_root`.
   - It is opened by walking each component from `/` with `O_PATH|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`, so any symlinked component, including the data root itself, fails.
   - The final fd's `(st_dev, st_ino)` must differ from those of `state/`, of every ancestor of `state/` up to `/`, and of the data root. Its `st_dev` must equal the data root's.
   - Binds within a row may not nest.
   - The fd is made inheritable and passed as `--bind-fd FD DEST`.
   - `config_ro_binds` are files relative to `~/.config`, never under `breezy/`. Each is walked nofollow and must be a regular file with `st_nlink == 1`, whose (dev, ino) matches no entry under `~/.config/breezy` (walked nofollow at validation). It is passed as `--ro-bind-fd`.
   - `E7_CONFIG_DIR` rows may add exactly one directory in `config_ro_dirs`. It gets the same checks, plus "no entry inside resolves under `~/.config/breezy`".
   - Any violation gives 78. Bind sources are never created by the wrapper.
3. **Argv.** A list is passed to `os.execv("/usr/bin/bwrap", argv)`; there is no shell. The fixed order:
   1. `--unshare-user --disable-userns --assert-userns-disabled`
   2. `--ro-bind / /`, `--dev /dev`, `--proc /proc`
   3. `--size N --tmpfs /tmp`
   4. `--tmpfs <home>`, then `--ro-bind` each `HOME_REBINDS` entry (repo root; `Path(sys.base_prefix).resolve()` if under home; data root)
   5. `--tmpfs /run/user/<uid>`, plus `--ro-bind <NOTIFY_SOCKET> <same>` only for `E7A_R2_NOTIFY` rows, when the variable is an absolute path under `/run/user/<uid>/systemd/` and `lstat` says socket. An abstract `@` socket needs no bind (the net namespace is shared).
   6. `--ro-bind-fd` config files and dirs
   7. `--bind-fd` binds
   8. `--remount-ro <home>`
   9. `--unshare-pid` (omitted only for `E7A_R2_PROC` rows), `--new-session`, `--die-with-parent`
   10. `--chdir <cwd if inside repo or data root, else />`
   11. `--setenv TMPDIR /tmp`, `--setenv BREEZY_AUTONOMY_BWRAP_ROW <row>`, `--unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`
   12. `--`, then the command verbatim (an argv[0] starting with `-` is safe after `--`)
4. `--size` precedes `--tmpfs /tmp` (r1 MEASURED). The size is `tmpfs_size_bytes` or `DEFAULT_TMPFS_SIZE_BYTES` (256 MiB). A malformed value fails closed before exec (E-13).
5. **Exit codes and fallback:**
   - A missing command gives 127; present but not executable gives 126; bwrap missing gives 127 (all checked before exec).
   - **Fallback** applies only to rows in the exact set `NOTIFIER_FALLBACK_ROWS` (empty in seam B), and only **after** every 64/78 check has passed.
   - The fallback preflight is the same argv with `/bin/true`, run as a list-argv subprocess with `pass_fds` and `timeout=2`. No cached verdict is written.
   - If the preflight fails, times out, or bwrap is missing, the command is exec'd unwrapped with `BREEZY_AUTONOMY_SANDBOX_DEGRADED=<preflight_rc_<n>|preflight_timeout|bwrap_missing>`.
6. The wrapper file and every package module sit outside every bind. The repo is ro-bound.

**AC-2: self-probe (E-7 rule 2, B-R4, AUT-6 r15 l.260-262 vocabulary)**
- `run_self_probe(row, *, roots=None, environ=os.environ)` runs these steps in order:
  1. `environ["BREEZY_AUTONOMY_BWRAP_ROW"] == row`, else failure `env_row`, and the probe **returns before any open**.
  2. If `BREEZY_AUTONOMY_SANDBOX_DEGRADED` is set: a notifier-fallback row gets `SelfProbeResult(ok=False, degraded=True)` with no opens; any other row gets the failure `degraded_forged`.
  3. **Negatives** (from `self_probe_plan`):
     - targets: `state/`, `registry/` if unbound, the data root, the repo root, every unbound ancestor of a bind, and every top-level data-root directory not covered by a bind (live listing, directories only, not symlinks);
     - each must pass an `os.stat` dir precondition, then `os.open(dir, O_TMPFILE|O_WRONLY, 0o600)` must raise **exactly EROFS**;
     - a success closes the fd at once (an unnamed inode, no name) and fails `negative` (`negative_registry` for `registry/`); any other errno fails `negative`;
     - EOPNOTSUPP falls back to `statvfs` `ST_RDONLY` **and** the mountinfo `ro` flag; never a named create.
  4. **Positives**, per bind mode:
     - `tmpfile` (default): an `O_TMPFILE` success;
     - `subdir`: `<bind>/.bwrap_probe/` must exist (walked nofollow), then an `O_CREAT|O_EXCL|O_NOFOLLOW` probe file inside it is unlinked; an unlink failure gives `probe_residue`;
     - any failure gives `positive_<bind-label>`.
  5. Credentials:
     - `~/.config/breezy`, `~/.ssh`, `~/.aws`, `~/.gnupg` and `~/.netrc` all give ENOENT;
     - the home listing ⊆ `{first component of each HOME_REBINDS entry} ∪ {".config" iff config binds}`;
     - otherwise `credentials_visible`.
  6. `/run/user/<uid>` listing ⊆ the notify path components. A connect to `/run/user/<uid>/systemd/private` gives ENOENT, otherwise `user_bus_visible`.
  7. `/tmp` is a tmpfs in mountinfo and an `O_TMPFILE` there succeeds, otherwise `tmp_not_private`.
  8. `unshare_pid` rows: `/proc/1/comm == "bwrap"`, otherwise `pid_ns`.
- `require_sandbox(row)` raises `SandboxIntegrityError(reason_code)` unless `ok`. Codes carry no absolute path. The caller prints `<UNIT> INTEGRITY bwrap_probe_failed direction=<code>`, delivers the CRITICAL and exits 3.
- **No probe ever creates a directory entry under `state/`, the data root, the repo, `registry/demand/` or `derived/verdicts/`.**
- `degraded_write_target(row, path, *, roots)` resolves a path and refuses anything outside the row's binds or under `state/`. Notifier code calls it before every write in degraded mode.

**AC-3: WAL snapshot helper (E-8 as amended by ER-B2(b), E-8a, E-7a rule 3)**
1. API:
   - `wal_snapshot(db_path, *, cache_dir, take_flock, lock_path, release_deadline_ns=None, …)`;
   - `exec_snapshot(*, cache_dir, take_flock, lock_path=None, data_root=None, **kw)`. This is byte-compatible with AUT-6 r15 l.262 and AUT-5 r7 l.388.
2. `take_flock=True`:
   - legal only in the AUT-5 16:45 pre-launch pass (AST allowlist starts empty);
   - its `release_deadline_ns` must precede the 16:50 `_do_launch` intent-lock check (E-8 step 6);
   - `lock_path` must equal `<db>.intent.lock`;
   - the lock is opened `O_RDONLY|O_CLOEXEC|O_NOFOLLOW`, then `fstat` must show a regular file; a missing file gives `LOCK_FILE_MISSING` and is never created;
   - `flock(LOCK_EX|LOCK_NB)` × 3, 5 s apart, then `LOCK_HELD`.
3. `take_flock=False` never opens `lock_path`, and the result is `advisory=True`. **`advisory=False` exists only when the intent flock was held from the first fingerprint through the last re-fingerprint.**
4. **Copy step:**
   - Cache dir: walked nofollow; `fstat` must show a directory, the caller's euid, and mode 0700 for both it and its parent, else `CACHE_DIR_MODE`.
   - `flock(LOCK_EX|LOCK_NB)` on an `O_RDONLY|O_DIRECTORY` fd of the cache dir, else `CACHE_BUSY`.
   - Sweep `snap.*` via `dir_fd`, without following symlinks.
   - Quiescence: if any present file has `mtime_ns > clock_ns() − 20 ms`, sleep 20 ms and re-fingerprint (bounded by attempts and the deadline).
   - Fingerprint = (present, inode, size, `mtime_ns`, sha256 of db bytes 0–99, sha256 of `-wal` bytes 0–31, sha256 of the last 4096 bytes of `-wal`). The `-journal` uses the triple plus its first 512 bytes.
   - Copy into `os.mkdir("snap.<token_hex>", 0o700, dir_fd=cache_fd)` in the order **db → `-wal` → `-journal`**. Sources are opened `O_RDONLY|O_NOFOLLOW` with an `fstat` inode check; destinations via `openat` with `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW`, 0600. Never `-shm`.
   - Re-fingerprint: on equality stop; otherwise remove and retry. After `copy_attempts` the result is `FINGERPRINT_UNSTABLE`.
5. Check the deadline (`DEADLINE`), then release the flock before the copy is opened.
6. Recover the copy:
   - `sqlite3.connect` read-write, path asserted under `realpath(cache_dir)`;
   - `PRAGMA quick_check == [("ok",)]`, otherwise `QUICK_CHECK`;
   - `journal_mode=DELETE`; close; assert no `-wal`/`-shm` remain;
   - `connect_snapshot_readonly` then opens it `mode=ro` with `query_only=ON`.
7. The result is `WalSnapshot | SnapshotReadFailure(reason)`. No exception is raised for an expected failure. `finally` releases both flocks and `rmtree(dir_fd=…)`s the snapshot directory.
8. `SnapshotFailureReason` = {`CACHE_DIR_MODE`, `CACHE_BUSY`, `LOCK_PATH_INVALID`, `LOCK_FILE_MISSING`, `LOCK_HELD`, `LOCK_ERROR`, `SOURCE_INVALID`, `FINGERPRINT_UNSTABLE`, `COPY_ERROR`, `QUICK_CHECK`, `DEADLINE`}. This is an exact set.

**AC-4: shared write sites (B-R3; replaces r1's lint)**
- `breezy.runtime.autonomy_sandbox.write_sites.SHARED_WRITE_SITES: Final[frozenset[WriteSite]]` holds the exact (module, function, call) sites of `wal_snapshot` and `self_probe`.
- `test_shared_write_sites_equal_package_scan` asserts equality with an AC6-allowlist AST scan of the package. Any call outside the AC6 read-only allowlist is a write site.
- `tests/support/autonomy_write_sites.py::cache_dir_is_own_module_constant(call, module_ast) -> bool` implements B-R2(a), with positive controls. No denylist and no `judge()`.

**AC-5: unit-file lint (E-7a rule 1, Arch-6)**
- **Scope:** `(⋃ row.units ∪ AUTONOMY_OWNED_UNITS)`, an exact set that seam B ships as `frozenset()` and consumers widen, matched to files `*.service`, `*.timer` and `*.d/*.conf`. The wrapper is never parsed.
- Every `breezy-autonomy-*.service` file must be in scope (tripwire). Every `AUTONOMY_OWNED_UNITS` member must have a file. Every unit naming the wrapper is in scope.
- Rules:
  - every `ExecStart=` and `ExecStopPost=` goes `timeout -k` → (`flock -w`) → wrapper → row → command;
  - no `+` or `!` prefix;
  - the row exists and lists the unit;
  - every `OnFailure=` target is in scope and wrapped;
  - `E7A_R2_NOTIFY` rows' units carry `NotifyAccess=all`;
  - `ExecStartPre` is only a bounded `install -d`/`chmod`.

**AC-6: C4.1 ruling.**
- `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` exists, and its marked block is byte-identical to `ARCH_rev9_2.md` lines 379–392.
- The snapshot sha and the block sha are pinned.
- No filing note appears in the file (Arch-15).

**AC-7: gate (ER-B1)**
- `scripts/ci/run_tests_no_egress.sh` runs phase 1 (unchanged scope), then phase 2 (un-nested). It prints `[breezy] gate: phase1 rc=X phase2 rc=Y` and exits with the first non-zero.
- Phase 2 is omitted only for `--collect-only`/`--co`.
- Phase 2 passes exactly `BWRAP_HOST_EXPECTED_TESTS` tests with 0 skipped. `lint-imports` reports "N kept, 0 broken" (console script, run from the tree).

**AC-8: real host.** V0–V14 pass on the primary tree after merge, before any consumer row is filed.

## Edge Cases & NFRs

| Case | Handling |
|---|---|
| Node up and holding the intent flock (`app/trade.py:990`, E-8) | `take_flock=True` gives `LOCK_HELD` after 3 tries. `take_flock=False` is fingerprint-only and advisory. |
| Helper holds the flock while a node boots | The node's `hold_submit_intent_process_lock` (`submit_intent.py:556-580`, `LOCK_NB`) fails fast and never blocks. The hold is ≤ fingerprint + copy (≤ 1 s measured r1) per attempt. The deadline must precede the 16:50 launch (AC-3.2). Tested (Sec-7). |
| `-wal` absent / stale `-wal` after SIGKILL | Absent fingerprints as absent. A stale one is recovered on the read-write open of the copy, then `quick_check`. |
| Checkpoint plus WAL reset inside one mtime tick | Salt, tail and db header digests plus quiescence (Sec-6, Arch-12c). A frozen-clock test. |
| Writer that ignores the lock (`trade_supervisor.py:2418`, 17:05Z) | Re-fingerprint, retry, `FINGERPRINT_UNSTABLE`. Never a silent tear. |
| Two runs share one cache dir | Cache-dir flock gives `CACHE_BUSY`. The sweep runs only under that flock (L-50). |
| Bind swapped for a symlink to `state/` between validation and mount | Impossible: bwrap mounts the validated fd, never re-resolves the path (M8). The walk fails closed on any symlinked component. |
| Config file is a symlink or hardlink to a credential | 78 (nofollow walk, `st_nlink`, dev/ino scan of `~/.config/breezy`). |
| Bind source missing (`cache/` absent today, M13) | 78 with the row and a reason code. Units create sources in a bounded unwrapped `ExecStartPre=install -d -m 0700`. V1 creates the selftest's. |
| A credential entry not named anywhere (`.codex`, `.git-credentials`, M12) | Hidden by `--tmpfs ~`. Only `HOME_REBINDS` and config binds are visible (M6). |
| Sandboxed process tries `systemd-run --user` | `/run/user/<uid>` is an empty tmpfs (M9). Nested userns is disabled (M5). |
| Hand run in a terminal (`.scope`), transient `run-u*` unit, `Delegate=` sub-cgroup | 78. Real-host runs use `systemd-run --user --unit=<listed name>`. |
| `ExecStopPost` hook in a non-autonomy unit (AUT-1 l.662) | Row `breezy-quote-tape.stop-hook` lists `breezy-quote-tape.service`. The lint scope includes every unit naming the wrapper. |
| `/proc/locks`, `/proc/<pid>` consumers | `E7A_R2_PROC` rows omit `--unshare-pid` (M5: 152 lines vs 0). |
| `Type=notify` rows | Only the `NOTIFY_SOCKET` path is re-bound, read-only (M10). V12 proves systemd accepts it under `--unshare-user`. |
| User unit `WorkingDirectory` defaults to home (hidden) | `--chdir`: cwd if inside the repo or data root, else `/`. |
| Env-borne credentials (AUT-2 `EnvironmentFile`) | Env passes through (E-7a rule 2). File credentials are always hidden. AUT-2 verify-first (R8). |
| Forged `BREEZY_AUTONOMY_SANDBOX_DEGRADED` | Unset inside every sandbox. Ignored, and raised on, for non-notifier rows (L-22). |
| apparmor or bwrap change breaks userns | Notifier rows degrade. Every other row fails, so `OnFailure` fires. AUT-6 health. |
| Phase 2 invoked by hand without `-p` | Root conftest `pytest_plugins` loads the plugin, which installs the blocker at import when the env is set. That still precedes Nautilus, and admission re-checks `sys.modules`. |
| Phase-1 run with `BREEZY_BWRAP_HOST_PHASE` leaked from the shell | The script `unset`s it before phase 1. Admission requires the OS-block var absent, so both set gives rc 2. |

**NFRs**
- Wrapper overhead p95 ≤ 50 ms (E-7a rule 5, V9). Fallback if exceeded: shebang `-IS` with an explicit `src` path.
- Package is stdlib-only (forbidden contract plus a subprocess import test).
- Snapshot of today's store in ≤ 1 s; the flock is held only for fingerprint, copy and re-fingerprint.
- Phase 2 ≤ 120 s wall (measured in V0). Tier lanes run phase 2 once per lane (trade-off stated).
- No network, no alert payload content, no absolute paths in stderr or reason codes.

## Architecture & Data Flow

**Layer and placement (B-R8).** `src/breezy/runtime/autonomy_sandbox/`. The reasons, per `ARCH-0-seamA-r1-architect.md:48-56`:
1. The E-8 helper opens a copy read-write. Placing it in `persistence/autonomy` would need an exception in seam A's write-site scan and in E-7 rule 3's lint, and that exception is a guard weakening (L-46).
2. Every caller sits at runtime or above (AUT-1 runtime CLIs; `analysis` engines).
3. The table and wrapper are deployment and process configuration.
4. `runtime/__init__.py` is import-free (`test_runtime_import_isolation.py:357-369`).

New import-linter contract: `"ARCH-0 seam B: the autonomy sandbox package is stdlib-only"`, `source_modules=["breezy.runtime.autonomy_sandbox"]`, `forbidden_modules=["nautilus_trader","breezy.adapters","breezy.strategy"]`, `allow_indirect_imports=false`. Additive; existing contracts are read by name (`test_test_safety_tooling_config.py:49-65`). No seam-A dependency.

**Modules and API** (signatures; the bodies follow the ACs)

```python
# table.py
DEFAULT_TMPFS_SIZE_BYTES: Final = 256 * 1024**2;  MAX_TMPFS_SIZE_BYTES: Final = 16 * 1024**3
KNOWN_EXCEPTIONS: Final = frozenset({"E7A_R2_PROC","E7A_R2_NOTIFY","E7A_R2_RECONCILE",
                                     "E7B_EVAL_OFFLINE_ADAPTER_MODULES","E7_CONFIG_DIR"})
NOTIFIER_FALLBACK_ROWS: Final[frozenset[str]] = frozenset()      # exact; consumers widen (L-12)
AUTONOMY_OWNED_UNITS: Final[frozenset[str]] = frozenset()        # exact; consumers widen
PositiveProbe = Literal["tmpfile", "subdir"]
class TableError(ValueError): ...
@dataclass(frozen=True, slots=True)
class SandboxRoots:
    home: Path; data_root: Path; repo_root: Path; python_prefix: Path; uid: int
    @classmethod
    def production(cls) -> "SandboxRoots"   # pwd home (never $HOME); repo = package path parents[4]; sys.base_prefix resolved
    def home_rebinds(self) -> tuple[Path, ...]   # (repo_root, python_prefix if under home, data_root): exact, test-pinned
@dataclass(frozen=True, slots=True)
class BwrapRow:
    name: str; owner_plan: str; units: frozenset[str]; binds: tuple[str, ...]; entry_modules: tuple[str, ...]
    config_ro_binds: tuple[str, ...] = (); config_ro_dirs: tuple[str, ...] = ()
    unshare_pid: bool = True; tmpfs_size_bytes: int | None = None
    exceptions: frozenset[str] = frozenset(); notifier_fallback: bool = False
    positive_probe: Mapping[str, PositiveProbe] = MappingProxyType({})   # bind -> mode; default tmpfile
AUTONOMY_BWRAP_TABLE: Final[Mapping[str, BwrapRow]]   # seam B: "breezy-autonomy-selftest", "breezy-autonomy-selftest-notify"
def validate_table(table=AUTONOMY_BWRAP_TABLE) -> None
def self_probe_plan(row: BwrapRow, roots: SandboxRoots) -> SelfProbePlan   # negatives, positives(mode), named ENOENTs

# binds.py
@dataclass(frozen=True) class OpenedBinds: bind_fds: tuple[tuple[int, Path], ...]; config_fds: tuple[tuple[int, Path], ...]
@contextmanager
def open_validated_binds(row: BwrapRow, roots: SandboxRoots) -> Iterator[OpenedBinds]   # raises BindError(reason_code); closes fds on exit
def walk_nofollow(path: Path, *, directory: bool) -> int                                  # O_PATH per component from "/"

# bwrap.py
EXIT_USAGE, EXIT_CONFIG, EXIT_NOT_EXECUTABLE, EXIT_NOT_FOUND = 64, 78, 126, 127
BWRAP_PATH: Final = "/usr/bin/bwrap";  ALLOWED_EXTRA_NAMESPACE_FLAGS: Final = frozenset({"--unshare-net"})
def build_bwrap_argv(row, command, *, roots, opened: OpenedBinds, environ: Mapping[str, str],
                     cwd: Path, extra_namespace_flags: Sequence[str] = ()) -> list[str]
def current_unit_name(cgroup_text: str) -> str | None        # None on any shape other than exactly one "0::…*.service"
def main(argv, *, roots=None, cgroup_path=Path("/proc/self/cgroup"), bwrap_path=BWRAP_PATH,
         execv=os.execv, run=subprocess.run) -> int

# self_probe.py
class SandboxIntegrityError(RuntimeError): reason_code: str
@dataclass(frozen=True, slots=True) class SelfProbeResult: ok: bool; degraded: bool; failures: tuple[str, ...]
def run_self_probe(row_name, *, roots=None, environ=os.environ) -> SelfProbeResult
def require_sandbox(row_name, *, roots=None) -> SelfProbeResult
def degraded_write_target(row_name, path, *, roots=None) -> Path

# wal_snapshot.py   (API as AC-3; EXEC_STORE_FILENAME, INTENT_LOCK_SUFFIX, QUIESCENCE_NS = 20_000_000)
def exec_store_paths(data_root: Path | None = None) -> tuple[Path, Path]
def connect_snapshot_readonly(snap: WalSnapshot) -> sqlite3.Connection

# write_sites.py
@dataclass(frozen=True, slots=True) class WriteSite: module: str; function: str; call: str
SHARED_WRITE_SITES: Final[frozenset[WriteSite]]
WRAPPER_CODE_FILES: Final[tuple[str, ...]]    # repo-relative: the script + every autonomy_sandbox/*.py (V11, AUT-4)

# selftest_cli.py   (python -I -m breezy.runtime.autonomy_sandbox.selftest_cli [--exec-snapshot N])
def main(argv=None) -> int   # require_sandbox(row from env); /tmp marker; JSON line: ok, tmp_marker, tmp_size_kib, home_listing, snap{ok,unstable}
```

**Seam B's rows**
- `breezy-autonomy-selftest`: units `{breezy-autonomy-selftest.service}`, binds `("cache/autonomy_selftest",)`, entry module `selftest_cli`.
- `breezy-autonomy-selftest-notify`: same bind, units `{breezy-autonomy-selftest-notify.service}`, exceptions `{"E7A_R2_NOTIFY"}` (V12 only).
- Both are transient (`systemd-run`), so neither has a unit file.

**Data flow (wrapper)**
1. systemd runs `ExecStart=/usr/bin/timeout -k … [flock -w … <lock>] /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap <row> <cmd…>`.
2. The shebang `/home/jon/breezy/.venv/bin/python3 -I` calls `bwrap.main`. Checks run in order:
   1. ROW syntax (64);
   2. `validate_table` (78);
   3. row lookup (78);
   4. cgroup unit match (78);
   5. `open_validated_binds` (78);
   6. command present and executable (127/126);
   7. bwrap present (127, or fallback for notifier rows);
   8. notifier preflight (2 s);
   9. `os.execv(bwrap, argv)` with the bind fds inheritable.
3. Inside, the entry point calls `require_sandbox(row)` first. On failure it delivers the CRITICAL through AUT-6's `deliver_with_proof` (consumer side) and exits 3.

**Data flow (snapshot).** As in AC-3: cache-dir walk and flock → sweep → [intent flock] → quiescent fingerprint → fd-relative copy (db → `-wal` → `-journal`) → re-fingerprint → deadline → release intent flock → recover, `quick_check`, `DELETE` → yield → finally release and remove.

**Gate (ER-B1; WP-B2a)**
- `tests/support/bwrap_host_phase.py` (stdlib + pytest only) contains:
  - `BWRAP_HOST_PHASE_ENV_VAR = "BREEZY_BWRAP_HOST_PHASE"`;
  - `BWRAP_HOST_TEST_FILES: Final[frozenset[str]]`, exact, seam B: `{"tests/integration/test_autonomy_sandbox_namespace.py", "tests/integration/test_wal_snapshot_namespace.py"}`;
  - `BWRAP_HOST_EXPECTED_TESTS: Final[int]`, the exact collected count, pinned at build;
  - `class Phase2ImportBlocker(importlib.abc.MetaPathFinder)` with `refuses(name)` and `refuse(names)` (add-only); base prefixes `{"nautilus_trader", "breezy.adapters"}`;
  - at import, if the env var is exactly `"1"`, the blocker is installed at `sys.meta_path[0]`;
  - hooks:
    - `pytest_configure` registers `bwrap_host`;
    - `pytest_collection_modifyitems(tryfirst=True)`: in phase 1 it skips `bwrap_host` items with reason `phase-2 (nested userns denied: bwrap-userns-restrict); run by scripts/ci/run_tests_no_egress.sh`; in phase 2, an item outside the registry or unmarked gives `pytest.exit(rc=2)`;
    - `pytest_runtest_logreport` counts outcomes;
    - `pytest_sessionfinish` sets `exitstatus=1` unless `phase2_session_verdict(passed, skipped, failed, expected, loaded_refused)` is clean;
  - `phase2_admission(*, environ, meta_path, modules, egress_paths) -> Phase2Admission(admitted: bool, reason: str)`, a pure function;
  - `module_name_for_path(path) -> str | None` (`src/x/y.py` → `x.y`, `scripts/a.py` → `scripts.a`; anything else None, which means not admitted).
- **Root conftest edits (exactly four, WP-B2a):**
  - (C1) `pytest_plugins = ("tests.support.bwrap_host_phase",)`.
  - (C2) In `pytest_configure`, before `:280`: `if _bwrap_host_phase_active(): return`. This skips only the Nautilus logger pin, which cannot load in phase 2. The marker lines and the pyo3 block (`:254-275`) are unchanged.
  - (C3) `execution_egress_abort_reason(…, bwrap_host_phase: Phase2Admission | None = None)`. With `None` the body is today's. With a value:
    - attested and phase evidence both present gives the abort reason `"…: phase 1 attestation and phase 2 are mutually exclusive"`;
    - unattested and `admitted` gives `None`;
    - unattested and not admitted gives `"…: bwrap_host phase not admitted: <reason>"`.
  - (C4) `_execution_egress_abort_reason_for_this_session` computes the admission only when the env var is present. It first `refuse()`s the module of each egress hit, then calls the rule. No canary is sent in phase 2.
  - `_is_real_network_test` and the marker set (X1 pin, `:1474-1498`) are untouched. No operator control is named (`:525` scan).
- **Script (`run_tests_no_egress.sh`, WP-B2a):**
  - `unset BREEZY_BWRAP_HOST_PHASE` at the top;
  - `run_bwrap` and `run_unshare` lose `exec`;
  - `phase1_rc=0; run_bwrap "$@" || phase1_rc=$?`;
  - the `--collect-only`/`--co` check;
  - `run_phase2`:
    1. refuse with 3 if `BREEZY_TEST_OS_EGRESS_BLOCK` is set or bwrap is absent;
    2. a namespace precheck, `bwrap --unshare-user --disable-userns --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc true`, else 3;
    3. `mapfile` the registry from `"$PYTHON" -c 'from tests.support.bwrap_host_phase import registry_paths; …'`, refusing if empty;
    4. `mkdir -p "${BREEZY_GATE_DIR:-$HOME/.cache/breezy-gate}"`;
    5. run `env -u BREEZY_TEST_OS_EGRESS_BLOCK BREEZY_BWRAP_HOST_PHASE=1 "$PYTHON" -m pytest -p tests.support.bwrap_host_phase -p no:randomly -p no:cacheprovider -m bwrap_host --basetemp="$GATE_DIR/phase2-bt-$$" "${files[@]}"`;
  - summary line; first non-zero exit.
  - The header comment gains a phase-2 paragraph. The N5 pin (`BREEZY_TEST_OS_EGRESS_BLOCK` in the text) still holds.
- **Children:** `tests/support/bwrap_harness.run_in_row(row, command, *, roots, timeout_s=30)` always passes `extra_namespace_flags=("--unshare-net",)` and an explicit env (`PATH`, `HOME=roots.home`, `LANG`). It never forwards `BREEZY_TEST_OS_EGRESS_BLOCK` or credentials. `make_roots(tmp_path)` builds a fake home, data root (`state/`, `registry/`, `cache/` 0700) and repo.

## Consumer Surface

| Consumer plan § | Call it makes | Delivered here / change flagged |
|---|---|---|
| AUT-1 r12 l.662, 710, 1112 (stop hook) | `ExecStopPost=-/usr/bin/timeout -k 2 10 …/breezy-autonomy-bwrap breezy-quote-tape.stop-hook …` | Wrapper; row/unit decoupling; AC-5 scope includes units that name the wrapper. AUT-1 files the row and widens `AUTONOMY_OWNED_UNITS` (`breezy-capture-audit`, …). |
| AUT-1 r12 l.767, 875, 939 | Every unit wrapped; capture-audit reads the exec store advisory | `exec_snapshot(cache_dir=<module Final>, take_flock=False)`. The `journalctl`/`systemctl` argvs are judged by AUT-1's own AC6 allowlist (no shared denylist). |
| AUT-2 r7 l.180, 227, 254, 448, 467-470 | Reconcile units with GET egress; `EnvironmentFile`; G6 reads; `breezy-aut2-recon-failed@` notifier | **Changes flagged:** wrapped G6 in-place reads become `exec_snapshot(take_flock=False)` (R9); credentials must be env-only (R8 verify-first); the notifier joins `NOTIFIER_FALLBACK_ROWS` with an alerts-only closure test; units join `AUTONOMY_OWNED_UNITS`. Label `E7A_R2_RECONCILE`. |
| AUT-3 r6 (E-7a rule 2) | `Type=notify` refit, `reproduce-pm` | `E7A_R2_NOTIFY`: the `NOTIFY_SOCKET` path is re-bound ro (M10); V12; lint requires `NotifyAccess=all`. |
| AUT-4 r11 l.873-875, 893, 1648 | Rows with `tmpfs_size_bytes`; `timeout → flock → wrapper`; deployed-blob check; E-13 tests; root substitution | `tmpfs_size_bytes`/default/fail-closed; the two E-13 tests at AUT-4's exact paths and names; `SandboxRoots` plus `bwrap_harness`; label `E7B_EVAL_OFFLINE_ADAPTER_MODULES`. **Change flagged:** step 2's sha check uses the `WRAPPER_CODE_FILES` manifest (V11). AUT-4 real-namespace tests join `BWRAP_HOST_TEST_FILES` under `tests/integration/`. |
| AUT-4 r11 l.898 | Advisory snapshot of the exec store and WAL inputs | `wal_snapshot(..., take_flock=False, lock_path=None)` and `exec_snapshot`. |
| AUT-5 r7 l.124, 202, 270-292, 384-405 | Engine rows; self-probe; E-8 at 16:45; advisory reads; write-authority allowlist; `-p` bootstrap fallback | Rows (AUT-5 files them); `require_sandbox`; `exec_snapshot(cache_dir=ENGINE_EXEC_SNAPSHOT_DIR, take_flock=True, lock_path=exec_store_paths()[1], release_deadline_ns=<16:48:00>)`; reasons map 1:1 (`CACHE_BUSY` is new and maps to `read_failure`). **Changes flagged:** inline bwrap ExecStart becomes the wrapper; `sandbox_probe.py` is deleted in favour of `require_sandbox` (the EACCES acceptance is removed; negatives use `O_TMPFILE`); `OnFailure=breezy-study-failed@` becomes `breezy-autonomy-failed@`; l.275 fallback passes `--unit=breezy-autonomy-engine-l1-bootstrap.service` (listed in the bootstrap row); l.386 G6 advisory reads become `exec_snapshot(take_flock=False)`; l.292 allowlist rows are re-pointed to `SHARED_WRITE_SITES` plus `cache_dir_is_own_module_constant`. Real-namespace tests (`tests/integration/test_engine_bwrap_sandbox.py`, `test_exec_snapshot.py`) join the registry and run Nautilus work only in bwrap children. |
| AUT-6 r15 l.241-266, 1485 | Seven rows (two without `unshare_pid`); `AUT6_SELF_PROBE_PATHS` derived; `exec_snapshot(... take_flock=False, lock_path=None)`; `~/.config/systemd/user` re-bind | `self_probe_plan()`; `positive_probe` modes (`subdir` for evidence/ and cache/, `tmpfile` for demand/verdicts, as r15 specifies); `E7A_R2_PROC`; `E7_CONFIG_DIR`; `NOTIFIER_FALLBACK_ROWS` (AUT-6 adds `breezy-autonomy-failed@`). **Changes flagged:** negatives are `O_TMPFILE` (no `.aut6_bwrap_probe_*` names); the `--tmpfs ~/.config` text becomes the home allowlist. |
| AUT-7 r5 | Inherits the engine row; `registry/drill/` | Covered by the engine's `registry` bind; nested binds refused. |
| AUT-3, AUT-4 (C4.1) | Cite the ruling by name | WP-B1 files it before any AUT-3 fit or AUT-4 screen (ARCH §5.1 l.1043-1044). |

## File-by-File Plan

| Path | N/M | Content | Deps |
|---|---|---|---|
| `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` | N | Header (status, source path and sha, "changing this is an ARCH change"), then `<!-- BEGIN VERBATIM ARCH Rev 9.2 §C4.1 -->` + byte-slice of lines 379–392 + END marker. **No filing note.** The `nbp_calibration.py:273-278/:334/:353-399` drift note goes in the commit message. | snapshot |
| `/home/jon/breezy/tests/unit/test_holdout_ruling_filed_verbatim.py` | N | As r1 (5 tests); pattern `test_live_orders_ruling_deploy_copy_matches_evidence.py:22-60` | stdlib |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/__init__.py` | N | Docstring only | — |
| `…/autonomy_sandbox/{table,binds,bwrap,self_probe,wal_snapshot,write_sites,selftest_cli}.py` | N | API above | stdlib |
| `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap` | N (0755) | 4-line script, as r1 (shebang `-I`, `sys.exit(main(sys.argv[1:]))`) | `bwrap.main` |
| `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` | **M (WP-B2a)** | `exec` dropped on l.37 and l.51; `unset BREEZY_BWRAP_HOST_PHASE`; `run_phase2`; rc combination; header paragraph | bwrap |
| `/home/jon/breezy/tests/conftest.py` | **M (WP-B2a)** | Exactly C1–C4 | plugin |
| `/home/jon/breezy/tests/support/bwrap_host_phase.py` | N | Plugin, blocker, admission, registry, verdict | stdlib, pytest |
| `/home/jon/breezy/tests/support/bwrap_harness.py` | N | `run_in_row`, `make_roots` | package |
| `/home/jon/breezy/tests/support/autonomy_write_sites.py` | N | `cache_dir_is_own_module_constant`; the AC6 read-only allowlist predicate reused by `test_shared_write_sites_equal_package_scan` | ast |
| `/home/jon/breezy/tests/fixtures/bwrap_host_phase/{p2_outside_registry,p2_imports_nautilus}.py` | N | Child-pytest controls. The names do not match `test_*.py`, so phase 1 never collects them; explicit paths are collected. | — |
| `/home/jon/breezy/tests/unit/test_bwrap_host_phase_barrier.py` | N | Gate tests (WP-B2a) | plugin |
| `/home/jon/breezy/tests/unit/test_run_tests_no_egress_phases.py` | N | Script tests with a stub `bwrap` on `PATH` and a stub `BREEZY_PYTHON` | — |
| `/home/jon/breezy/tests/unit/test_autonomy_sandbox_table.py`, `test_autonomy_bwrap_argv.py`, `test_autonomy_bind_integrity.py`, `test_autonomy_units_wrapped.py`, `test_autonomy_self_probe.py`, `test_wal_snapshot.py`, `test_autonomy_write_sites.py` | N | Phase-1 tests | — |
| `/home/jon/breezy/tests/contract/test_autonomy_units.py` | N | The two E-13 tests (AUT-4 names) | — |
| `/home/jon/breezy/tests/integration/test_autonomy_sandbox_namespace.py`, `test_wal_snapshot_namespace.py` | N | Phase-2 tests: `pytestmark = pytest.mark.bwrap_host`; import only stdlib, pytest, the package and the harness | harness |
| `/home/jon/breezy/pyproject.toml` | M | One additive import-linter contract (B-R8); no `addopts`/`markers` edit (L-54) | — |
| `/home/jon/breezy/deploy/systemd/README.md` | M | Section "Autonomy bwrap wrapper (E-7/E-7a)": misconfiguration-not-authorisation; home allowlist; the gate's two phases; V0–V14; consumer obligations | — |

**`validate_table` rules (exact sets; widened only per L-12)**
- Key equals `row.name` and matches the ROW regex.
- `units`: each matches `^breezy-[a-z0-9@.-]+(\.service|@)$`.
- `binds`: non-empty, relative, no `..` or empty segment, not starting with `state`, not nested.
- `positive_probe` keys ⊆ `binds`.
- `config_ro_binds`: relative, not starting with `breezy`, no `..`.
- `config_ro_dirs` non-empty only with `E7_CONFIG_DIR`, length ≤ 1.
- `tmpfs_size_bytes`: None, or an `int` that is not a `bool`, with 0 < v ≤ max.
- `exceptions` ⊆ `KNOWN_EXCEPTIONS`.
- `unshare_pid=False` ⇔ `E7A_R2_PROC` ∈ exceptions.
- `notifier_fallback=True` ⇔ name ∈ `NOTIFIER_FALLBACK_ROWS`.
- `E7B_EVAL_OFFLINE_ADAPTER_MODULES` only on a row whose name contains `eval-offline`.

## Test Strategy

Phase-1 tests run under `run_tests_no_egress.sh` phase 1; `bwrap_host` tests run in phase 2. WAL fixtures are written through `SqliteStateStore` (`sqlite_store.py:117-126`), per L-42.

| File | Tests | Failure path proven |
|---|---|---|
| `test_holdout_ruling_filed_verbatim.py` | r1's five | Missing file, drift, variant, vacuous comparator |
| `test_bwrap_host_phase_barrier.py` (WP-B2a) | `test_p2_admission_requires_exact_env_one` (`"true"`, `""`, `"1 "` rejected); `test_p2_admission_refused_when_phase1_attestation_also_set`; `test_p2_admission_refused_without_blocker_at_meta_path_head`; `test_p2_admission_refused_when_refused_module_already_loaded`; `test_p2_admission_refuses_unmappable_egress_path`; `test_p2_every_live_egress_hit_maps_to_a_refused_module` (M4); `test_n2_rule_without_phase_evidence_is_unchanged` (all four attested/outcome combinations equal today's verdict strings: the non-weakening proof); `test_n2_rule_phase_and_attestation_mutually_exclusive`; `test_p2_blocker_refuses_nautilus_adapters_and_planted_egress_module`; `test_p2_child_admitted_collects_registry_and_loads_no_refused_module` (child pytest `--collect-only -v`, witness id present, rc 0); `test_p2_child_with_nautilus_preloaded_aborts_before_collection` (`-p tests.support.nautilus_log_capture` before the plugin → rc 2, marker text, no witness); `test_p2_child_outside_registry_exits_2` (`p2_outside_registry.py`); `test_p2_child_test_importing_nautilus_is_refused_at_import` (`p2_imports_nautilus.py` → blocker message, no test ran, rc ≠ 0); `test_phase2_session_verdict_fails_on_skip_count_mismatch_or_loaded_module`; `test_phase1_skips_bwrap_host_items_naming_phase2`; `test_bwrap_host_registry_equals_marked_files` (AST over `tests/`); `test_bwrap_host_registry_outside_unit_and_contract_dirs`; `test_bwrap_host_files_import_no_subprocess_nautilus_or_adapters`; `test_bwrap_host_expected_tests_equals_collected_count`; `test_conftest_marker_set_unchanged_by_plugin` (re-runs the X1 derivation) | Each admission clause; prevention rather than detection; non-weakening of N2 |
| `test_run_tests_no_egress_phases.py` (WP-B2a) | `test_gate_runs_phase2_after_phase1_failure_and_exits_phase1_rc`; `test_gate_exits_phase2_rc_when_phase1_green`; `test_gate_omits_phase2_only_for_collect_only` (`--collect-only`, `--co`); `test_phase2_env_has_phase_var_and_no_attestation`; `test_phase2_argv_loads_plugin_and_registry_files_only`; `test_phase2_refuses_when_attestation_set`; `test_phase2_refuses_empty_registry`; `test_phase1_unsets_phase2_var`; `test_script_has_no_exec_before_phase2` (text); `test_lane_collect_ids_unaffected` (wrapper `--collect-only` output has no phase-2 ids) | Exit-code semantics; lanes partition proof |
| `test_autonomy_sandbox_table.py` | r1 table tests, with renamed labels and new rules; `test_home_rebinds_exact_set`; `test_notifier_fallback_rows_exact`; `test_eval_offline_label_row_scoped`; `test_wrapper_and_package_outside_every_bind`; `test_autonomy_sandbox_imports_stdlib_only` (fresh `python -I` child); `test_autonomy_sandbox_init_is_import_free` | Each rule has a failing fixture |
| `test_autonomy_bwrap_argv.py` | r1 order tests updated to AC-1.3: `…userns_flags_first`, `…home_tmpfs_then_rebinds_then_remount_ro`, `…run_user_tmpfs`, `…notify_socket_only_for_notify_rows`, `…unsetenv_degraded`, `…chdir_rule`; `test_extra_namespace_flags_exact_set`; `test_main_never_passes_extra_namespace_flags` (AST); `test_only_harness_passes_extra_namespace_flags` (AST over `src/` and `tests/`); `test_main_row_with_newline_or_dashdash_exits_64`; `test_command_starting_with_dash_after_double_dash_verbatim`; cgroup tests `…missing_0_line`, `…multiple_lines`, `…scope_and_slice_leaf_refused`, `…sub_cgroup_leaf_refused`, `test_main_transient_run_unit_exits_78`; `test_notifier_preflight_after_validation_never_falls_back_on_78`; `test_notifier_preflight_timeout_is_2s`; `test_non_notifier_never_falls_back`; `test_main_production_default_reads_real_cgroup_and_refuses` (L-55); `test_bwrap_module_has_no_shell` | Each exit code; mutants: `--size` after `--tmpfs`, dropping `--tmpfs <home>`, dropping the cgroup check |
| `test_autonomy_bind_integrity.py` | `test_main_symlinked_bind_component_exits_78`; `test_main_symlinked_data_root_exits_78`; `test_bind_swapped_for_symlink_to_state_after_walk_is_not_followed` (the fd is still the original dir); `test_bind_equal_to_state_ancestor_inode_exits_78`; `test_bind_on_other_device_exits_78`; `test_config_file_symlink_to_breezy_exits_78`; `test_config_file_hardlink_alias_exits_78`; `test_config_dotdot_exits_78`; `test_config_dir_requires_e7_config_dir_and_rejects_breezy_entry`; `test_bind_fds_closed_after_exec_failure` | TOCTOU and alias escapes |
| `test_autonomy_units_wrapped.py` | r1 lint tests with Arch-6 scope; `test_wrapper_file_never_parsed_as_unit`; `test_every_autonomy_service_file_in_scope` (tripwire); `test_owned_units_have_files`; positive-control fixture units | Non-vacuous via controls |
| `tests/contract/test_autonomy_units.py` | `test_wrapper_malformed_tmpfs_size_fails_closed` (`"2G"`, 0, −1, `True`, > max → non-zero via `main()`, sentinel `bwrap_path`, `execv` never called); `test_wrapper_applies_default_tmpfs_size_to_rows_without_one` | E-13 |
| `test_autonomy_self_probe.py` | `test_env_row_checked_before_any_open` (audit hook: zero `open` events); `test_negative_uses_o_tmpfile_and_requires_exactly_erofs` (EACCES on a 0500 dir is a failure); `test_probe_against_writable_state_leaves_listing_unchanged` (listdir before = after; reports `negative`); `test_positive_tmpfile_and_subdir_modes`; `test_subdir_unlink_failure_is_probe_residue`; `test_degraded_honoured_only_for_notifier_rows`; `test_degraded_forged_raises_for_other_rows`; `test_degraded_write_target_refuses_state_and_outside_binds`; `test_self_probe_plan_derived_from_table`; `test_reason_codes_vocabulary_exact_and_pathless` | Unwrapped run detected with no state write |
| `test_wal_snapshot.py` | r1's set, plus `test_cache_dir_flock_contention_is_cache_busy`; `test_copy_order_db_wal_journal`; `test_quiescence_waits_out_recent_mtime` (frozen clock); `test_same_tick_rewrite_detected_by_tail_and_salt_digest` (frozen `mtime_ns`, same size); `test_db_change_counter_bytes_in_fingerprint`; `test_advisory_false_only_with_flock_through_last_fingerprint`; `test_take_flock_true_hold_bounded_node_lock_fails_fast_not_blocks` (child `hold_submit_intent_process_lock` raises `SubmitIntentLockHeld` while held, succeeds after); `test_cache_dir_checked_by_fstat_not_path`; `test_copies_are_dir_fd_relative`; `test_take_flock_true_call_sites_allowlisted` (allowlist starts empty) | Every `SnapshotFailureReason` value |
| `test_autonomy_write_sites.py` | `test_shared_write_sites_equal_package_scan`; `test_cache_dir_predicate_accepts_module_final_constant`; `…rejects_literal_param_attribute_and_call`; `test_wrapper_code_files_manifest_covers_package` | Allowlist exactness |
| `tests/integration/test_autonomy_sandbox_namespace.py` (phase 2) | r1's ten, plus `test_bwrap_home_listing_is_rebinds_only`; `test_bwrap_ssh_aws_gnupg_netrc_enoent`; `test_bwrap_systemd_private_socket_not_connectable`; `test_bwrap_nested_userns_disabled`; `test_bwrap_notify_row_sends_to_rebound_socket` (scratch socket, M10); `test_bwrap_bind_fd_mount_survives_path_swap`; `test_concurrent_wrappers_share_binds_private_tmp`; `test_bwrap_child_env_has_no_egress_attestation`; `test_production_home_mount_args_hide_real_home` (L-55: real home, `SandboxRoots.production()` home prefix only, no binds); `test_self_probe_passes_inside_row_and_fails_with_wrong_row`; `test_harness_children_have_no_network` | Directive-free enforcement |
| `tests/integration/test_wal_snapshot_namespace.py` (phase 2) | r1's four | E-7a rule 3 |

**Real-host verification** (primary tree, after merge, `-I`; L-51)
- **V0.** `systemd-run --user --wait --pipe --collect -p LimitNOFILE=524288 /home/jon/breezy/scripts/ci/run_tests_no_egress.sh --basetemp=$HOME/.cache/breezy-gate/full-bt` must exit 0 and print `phase1 rc=0 phase2 rc=0`. Phase-2 passed equals `BWRAP_HOST_EXPECTED_TESTS`; record the wall time.
- **V1.** `install -d -m 0700 ~/.local/share/breezy/cache ~/.local/share/breezy/cache/autonomy_selftest` (M13).
- **V2.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest -p TimeoutStartSec=60 …/breezy-autonomy-bwrap breezy-autonomy-selftest /home/jon/breezy/.venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli` must exit 0 with `"ok": true`, `tmp_size_kib` = 262144, and `home_listing` = `[".local","breezy"]`.
- **V3.** `/tmp/breezy_selftest_<id>` is absent on the host.
- **V4.** Unknown row gives `status=78`. **V5.** Unit mismatch gives `status=78`.
- **V6.** In the selftest row, `python3 -I -c 'import os;os.open("/home/jon/.local/share/breezy/state",os.O_TMPFILE|os.O_WRONLY,0o600)'` fails with EROFS. `O_TMPFILE` cannot leave a name (Arch-17).
- **V7.** The same against `/home/jon/breezy` fails with EROFS.
- **V8.** `/proc/1/comm` is `bwrap`.
- **V9.** Overhead p95 ≤ 50 ms over 20 runs, otherwise the `-IS` fallback.
- **V10.** Node up, `--exec-snapshot 20`: record `ok/unstable` (input to AUT-6 R-34). `ls -A state | grep -E '^(snap\.|\.autonomy_probe)'` counts 0.
- **V11.** For each path in `WRAPPER_CODE_FILES`, the local `sha256sum` equals `git show <merge_sha>:<path> | sha256sum`.
- **V12.** `systemd-run … --unit=breezy-autonomy-selftest-notify -p Type=notify -p NotifyAccess=all …/breezy-autonomy-bwrap breezy-autonomy-selftest-notify /bin/sh -c 'systemd-notify --ready; sleep 1'` must report success with `--unshare-user`. If it fails, no `E7A_R2_NOTIFY` row is filed (R16).
- **V13.** mtime tick measured; the guards stay either way.
- **V14.** In the selftest row: `ls -A ~` gives exactly the rebinds; `ls -A /run/user/1000` is empty; `unshare -U true` fails; `test -e ~/.ssh` fails.

## Work Packages

**Order:** WP-B1 ‖ WP-B2a → WP-B2b → WP-B3.
- Seam B has **no seam-A dependency** (stdlib plus `breezy.runtime` only).
- Four WPs rather than r1's three, because L-54 requires the conftest and gate-script edit to be its own safety-reviewed item, never a side effect of a feature.
- WP-B3 is on the critical path for AUT-1a, AUT-5a and AUT-6.

| WP | Scope | RED → GREEN | Done when |
|---|---|---|---|
| **WP-B1** `docs:` C4.1 | Ruling file plus its test | RED: file absent. GREEN: byte-slice; block sha pinned. Drift note goes in the commit message. | Full gate green; `test_probe_containment.py:550-558` green |
| **WP-B2a** `test:` gate phases (**security-reviewed**) | `bwrap_host_phase.py`; conftest C1–C4; script; fixtures; `test_bwrap_host_phase_barrier.py`; `test_run_tests_no_egress_phases.py`. The registry starts with the two seam-B paths, which do not exist yet, so the registry-equality test lands RED and WP-B2b turns it green; alternatively seam B lands B2a with an empty registry plus a one-line refusal (`registry empty` → phase-2 rc 3) **and** B2b in a single merge. **Chosen:** a single merge commit sequence, B2a then B2b, gated together, so that main never has a phase 2 that exits 3. | **Verify-first step 0:** re-run M2/M3 on a scratch copy against current HEAD; re-grep the pins listed in Basis; confirm the `-p` load order. RED: the barrier tests, plus the script tests showing `exec` stops phase 2. Mutation (L-33): drop C3's mutual-exclusion clause; make the blocker refuse nothing; restore `exec` on l.37. Each turns a named test red. | Security sign-off filed in the r2 review; full gate both phases green; every existing N2/N3/N5/X1 test unchanged and green |
| **WP-B2b** `feat:` wrapper | `table`, `binds`, `bwrap`, `self_probe`, `selftest_cli`, `write_sites` (probe sites), the script, the harness, the unit lint, the E-13 contract tests, the phase-2 sandbox file, README, the import-linter contract | RED first. Mutations: `--size` after `--tmpfs`; drop `--tmpfs <home>`; drop the cgroup check; replace `--bind-fd` with a path `--bind`; accept EACCES in the negative probe. Each turns a named test red. | Both phases green; `lint-imports` "N kept, 0 broken" (`cd` into the tree; worktree `PYTHONPATH`); V0–V9, V11, V12 and V14 on the primary tree, before any consumer row |
| **WP-B3** `feat:` snapshot | `wal_snapshot`, the remaining `write_sites`, `autonomy_write_sites.py`, snapshot unit and phase-2 tests, `--exec-snapshot` | RED first. Mutations: remove the re-fingerprint, the tail digest, quiescence or the cache flock; copy `-shm`. Each turns a named test red. | Both phases green; lint-imports; V10 and V13 in the merge evidence |

**Every WP brief carries, verbatim:**
- Nautilus Trader is immutable. Never modify, patch, fork or reimplement it.
- The NO-SEND firewall and its tests are never weakened. The N2 change is an exact-set, security-reviewed **addition** whose absent-input behaviour is byte-identical (proved by `test_n2_rule_without_phase_evidence_is_unchanged`), never a relaxation. N3, N5, X1–X3 and E0 are untouched.
- `allow_short` stays `False`.
- No operator-reserved control is ever named or assigned.
- The live exec store is never written; no probe ever creates a name under `state/`.
- Use the exact interpreter `/home/jon/breezy/.venv/bin/python`. Never use `uv`, `pip` or `git stash`.
- `systemd-run -p LimitNOFILE=524288` for unit-launched gates; basetemp under `~/.cache`.
- Full gate, both phases, after every merge (L-43).
- Read-only unless the task is a write.

## Risk Register

| # | Risk | Sev | Mitigation / owner |
|---|---|---|---|
| R1 | ER-B1: nested bwrap impossible (M1) | HIGH | Phase 2 in the same script, never skipped except for `--collect-only`; exact registry and count. Coordinator files ER-B1. |
| R2 | Phase-2 parent has host network | MED | The blocker prevents Nautilus and adapter loads (M3); exact N2 admission; Python socket block (`conftest.py:508-532`); `--unshare-net` children; no `subprocess` in phase-2 files; session-end check. Residual: non-Nautilus native code in the parent. Security sign-off. |
| R3 | ER-B2 ownership move | MED | Call shapes kept; consumer changes enumerated in ER-B2(f). |
| R4 | Coarse mtime gives a false-stable fingerprint | MED | Salt, tail and header digests plus quiescence; frozen-clock test; V13. |
| R5 | `--size` order silently ignored | MED | Argv test, mountinfo test, E-13 tests. |
| R6 | Cgroup naming (templates, transient, Delegate) | LOW | Exact parse; 78; AUT-5 `--unit=` change; V2/V5. |
| R7 | Degraded notifier runs unwrapped: wider write scope **and** `~/.config/breezy` credentials visible | MED | Exact `NOTIFIER_FALLBACK_ROWS`; alerts-only closure test (consumer); `degraded_write_target`; never after a 78; degraded flag in the CRITICAL. |
| R8 | AUT-2 reconcile reads a credential *file* (`POLYMARKET_US_SECRET_KEY_FILE` is a known credential var) | MED | Hidden by design. AUT-2 verify-first must show env-only credentials; otherwise a coordinator ruling is needed (no table path can expose `~/.config/breezy`). |
| R9 | G6 in-place reads under the wrapper (AUT-2, AUT-5 l.386) | MED | E-7a governs; `test_mode_ro_in_place_fails_under_bwrap_without_sidecars`; flagged in ER-B2(f). |
| R10 | AUT-5 `OnFailure=breezy-study-failed@` | LOW | Flagged; AC-5 fails until switched. |
| R11 | Wrapper startup cost | LOW | V9; `-IS`. |
| R12 | Verification from a worktree checks the primary tree | MED | V-steps only after merge, on the primary tree. |
| R13 | Many plans editing one table literal | LOW | Rows sorted; `validate_table` in phase 1. |
| R14 | apparmor or bwrap upgrade | LOW | Exit codes; AUT-6 health; notifier fallback. |
| R15 | Sandbox is not a hostile-same-uid boundary (cgroup naming, user-manager-started units outside it) | MED (stated) | Stated residual (E-7a rule 5); the AC6 allowlists are the second layer. |
| R16 | `--unshare-user` breaks `sd_notify` credential checks | LOW | M10 shows delivery works; V12 proves acceptance before any notify row is filed. |
| R17 | A consumer row needs a home path outside `HOME_REBINDS` | LOW | Fails closed (ENOENT) at V-steps. Widening `HOME_REBINDS` is a reviewed seam-B schema change. |
| R18 | Phase 2 runs once per T1 lane | LOW | Bounded at ≤ 120 s; tiers are not the gate. Accepted (Trade-offs). |
| R19 | Wrapped units drop out of `test_unit_execstart_imports.py:143`'s venv-python check | LOW | Consumers keep entry-module import tests (`test_runtime_import_isolation.py` derivation). Noted for consumers. |

## LESSONS Compliance

Headers grepped in `docs/core/LESSONS.md` this session: L-1 :8, L-12 :620, L-14 :685, L-22 :1017, L-23 :1038, L-33 :1282, L-42 :1419, L-43 :1433, L-46 :1495, L-47 :1512, L-50 :1563, L-51 :1583, L-54 :1647, L-55 :1664.

| Lesson | How it is met |
|---|---|
| L-1 | Null-hypothesis table below. |
| L-12 | `KNOWN_EXCEPTIONS`, `NOTIFIER_FALLBACK_ROWS`, `AUTONOMY_OWNED_UNITS`, `BWRAP_HOST_TEST_FILES`, `BWRAP_HOST_EXPECTED_TESTS`, `HOME_REBINDS` and `SHARED_WRITE_SITES` are exact sets, widened in the same commit. N2 gains an input; its comparison is not relaxed. |
| L-14 | Home hiding is derived from "what is visible", an allowlist, after a live listing (M12) showed that a recalled hide list misses 30+ entries. Negatives come from the table plus a live data-root listing. |
| L-22 | Admission keys on the blocker's class identity at `meta_path[0]` plus `sys.modules`, not on an env var alone. `BREEZY_AUTONOMY_SANDBOX_DEGRADED` is unset inside every sandbox. |
| L-23 | Real probes only; directives are configuration. |
| L-33 | Mutation evidence listed per WP. |
| L-42 | Fixtures go through `SqliteStateStore`. |
| L-43 | Both phases after every merge. |
| L-46 | Contract tests searched for the new paths: `test_runtime_import_isolation.py` (`:357-369` `__init__`; systemd `-m` derivation — seam B ships no unit file); `test_probe_containment.py:550-558`; `test_unit_execstart_imports.py:143`; `test_analysis_units_serialized.py:398`; `test_operator_control_assignment_scan.py:525`; the N2/N3/N5/X1 pins cited in Basis. None is contradicted. |
| L-47 | Every host claim is MEASURED (M1–M13) or carries file:line. M2 corrects r1's premise that "the pytest parent keeps conftest's block" in an unattested session. |
| L-50 | Cache-dir flock; one writer per cache dir; sweep only under the flock. |
| L-51 | Exact interpreter; never `uv`; V-steps on the primary tree. |
| L-54 | Pins searched before the conftest and script edits: no `exec` pin, X1's AST pin untouched, `addopts` untouched. The edit is its own safety-reviewed WP (B2a). |
| L-55 | `test_main_production_default_reads_real_cgroup_and_refuses`, `test_exec_store_paths_default_is_pwd_home_data_root`, `test_production_home_mount_args_hide_real_home`. |

**L-1 null-hypothesis rows** (r1 evidence kept: Nautilus has no bwrap, sqlite, flock or backup helpers; the existing Breezy candidates are disqualified at the r1-cited lines)
- Wrapper and table: reuse of bubblewrap 0.11.1 behind a thin wrapper.
- Self-probe: new (E-7).
- Snapshot: stdlib copy plus `sqlite3` recovery; `SubmitIntent.from_bytes` reused by AUT-5.
- Phase-2 plugin: reuses pytest's `-p`, `pytest_plugins` and `importlib.abc.MetaPathFinder`; no runner is re-implemented.
- Write sites: data plus one AST predicate; reuses the AC6 allowlist.
- Ruling: precedent test pattern.

## Trade-offs

- **Blocker-admitted pytest phase 2 over a stdlib runner.** It keeps the consumers' pytest tests runnable as written. The costs are four conftest edits (measured feasible, M3) and the plugin. The runner was rejected for re-implementing fixtures.
- **Exact file registry rather than `-m bwrap_host tests/`.** Collecting `tests/` would import every module, and the blocker would error on `tests/unit/conftest.py:20-21`. The registry is AST-pinned to the marked files, so nothing can be silently omitted.
- **Phase 2 omitted only for `--collect-only`; no opt-out flag.** It runs once per T1 lane (R18) instead of adding a skip switch.
- **Hide all of home rather than a pinned name list.** Stronger and derived (M12, M7). The cost is that a row needing another home path must widen `HOME_REBINDS`.
- **Every row unshares the user namespace** (`--disable-userns` requires it, M5). uid stays 1000; V12 covers notify.
- **`--bind-fd` over path binds.** Closes the swap TOCTOU at the cost of fd plumbing.
- **Header and tail digests plus quiescence** (an E-8 amendment). About 4.2 KiB of extra reads and ≤ 20 ms of delay.
- **`journal_mode=DELETE` on the copy, cgroup binding, env pass-through, seam B ships only selftest rows.** As r1.
- **Placement.** Runtime, for the Q5 reasons; the 392 ms argument is struck.

## Confidence Self-Assessment

**91/100.**
- **High confidence:**
  - the gate design is measured end to end on a scratch copy (M2, M3) and every pin is cited;
  - the mount design is measured (M5–M11);
  - every finding in both reviews has a disposition;
  - consumer call shapes are unchanged.
- **Deductions:**
  - −3: the conftest and N2 change needs security sign-off, and the exact `BWRAP_HOST_EXPECTED_TESTS` value is fixed only at build.
  - −2: `sd_notify` acceptance under `--unshare-user` (V12) and wrapper overhead with the larger argv (V9) are not yet run.
  - −2: AUT-2's credential path (R8) is unverified.
  - −2: the home-allowlist deviation from E-7's literal `--tmpfs ~/.config` needs ER-B2(c) adoption.

---

## §ERRATA-REQUEST

**ER-B1 (amended per B-R1). Proposed E-7d: the gate's un-nested bwrap phase**

> **E-7d (coordinator, 2026-10-03, from ARCH-0 seam B r2 ER-B1): the gate runs real-namespace tests in an un-nested second phase.**
> - **Evidence.** A bwrap namespace cannot be created inside the gate's own bwrap: `bwrap --unshare-net --dev-bind / / bwrap --ro-bind / / true` fails with "No permissions to create a new namespace" (rc 1; apparmor profile `bwrap-userns-restrict`). One level works from outside the gate. Under an import blocker for `nautilus_trader*`, the root conftest fails at `tests/conftest.py:280` unless phase 2 skips the Nautilus logger pin; with that skip and the admission below, a pytest parent ran with no `nautilus_trader*` or `breezy.adapters*` module loaded.
> - **Rule 1: one gate, two phases.** `scripts/ci/run_tests_no_egress.sh` remains the gate. It runs phase 1 (the existing egress-blocked pytest), then phase 2 un-nested. It prints both exit codes and exits with the first non-zero. Phase 2 is omitted only when the invocation passes `--collect-only` or `--co`. No variable or flag disables it.
> - **Rule 2: what phase 2 runs.** Exactly the files in `tests.support.bwrap_host_phase.BWRAP_HOST_TEST_FILES`, with `-m bwrap_host`. That set is exact and equals the AST-derived set of test files that use the `bwrap_host` marker. The passed count must equal the exact literal `BWRAP_HOST_EXPECTED_TESTS`. A plan that adds a real-namespace test widens both in the same commit (L-12). In phase 1, `bwrap_host` items are skipped with a reason naming phase 2. In phase 2, any skip, any item outside the set, or a count mismatch fails the session.
> - **Rule 3: prevention in the phase-2 parent.** Phase 2 runs pytest with `BREEZY_BWRAP_HOST_PHASE=1`, without `BREEZY_TEST_OS_EGRESS_BLOCK`, and with `-p tests.support.bwrap_host_phase`. That plugin installs a meta-path import blocker at `sys.meta_path[0]` before any conftest loads. The blocker refuses `nautilus_trader*`, `breezy.adapters*` and the module of every `find_execution_egress_modules()` hit.
> - **Rule 4: N2, widened as an exact set.** `execution_egress_abort_reason` gains one keyword-only input, the phase-2 admission; with it absent, the rule is unchanged. An unattested session is admitted only when all of these hold: the variable is exactly `"1"`; `BREEZY_TEST_OS_EGRESS_BLOCK` is absent; the blocker (exact class) is at `sys.meta_path[0]`; every egress hit maps to a refused module; and no refused module is loaded at session start. Anything else, including both phases' variables set together, aborts before collection with rc 2. The credential gate runs first, unchanged. At session end the plugin re-asserts that no refused module is loaded. No canary is sent in phase 2.
> - **Rule 5: children.** Every bwrap child that a phase-2 test spawns goes through `tests/support/bwrap_harness.py`, which adds `--unshare-net` and passes an explicit environment. Phase-2 test modules import no `subprocess`, `nautilus_trader` or `breezy.adapters`.
> - **Consumer obligation.** Nautilus work in a phase-2 test runs only inside a bwrap child. Phase-2 files live outside `tests/unit/` and `tests/contract/`, whose conftests import Nautilus.
> - **Residual.** The phase-2 parent has host network for native code other than Nautilus. Python sockets stay blocked by the conftest autouse fixture.
> - **Supersedes** the verify-first branch wording of AUT-5 r7 l.287 ("a separate un-nested step of the same script") with this rule. **Security sign-off:** the ARCH-0 seam B r2 security review.

**ER-B2 (ADOPT with amendments, per B-R2). Ownership of the shared sandbox and snapshot**

> **E-7e (coordinator, 2026-10-03, from ARCH-0 seam B r2 ER-B2): ARCH-0 owns the shared wrapper, table, self-probe and E-8 helper.**
> - **Ownership.** ARCH-0 seam B owns `deploy/systemd/breezy-autonomy-bwrap`, `AUTONOMY_BWRAP_TABLE` and its validation, the self-probe, the E-8 snapshot helper (`wal_snapshot`, `exec_snapshot`) and the E-7a rule-1 unit lint. They live in `src/breezy/runtime/autonomy_sandbox/`, with the forbidden contract `breezy.runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy` (`allow_indirect_imports=false`). This is a stated deviation from ARCH §3's "types live in persistence/autonomy": the package is infrastructure, not a C1–C5 type. AUT-5 keeps `exec_snapshot.snapshot_exec_store` (the halt and intent decode, the 16:48:00 deadline value), the E-8 `test_exec_snapshot_*` names, and its rows. In the "E-7/E-8 consumption by plan" table, the AUT-5 row's "Owns bwrap and the self-probe / Owns E-8" moves to ARCH-0. Consumer text that says "AUT-5 owns the wrapper" reads as ARCH-0.
> - **(a) Write-authority allowlists.** AUT-5 r7 l.292's entries `autonomy_engine/exec_snapshot.py` and `autonomy_engine/sandbox_probe.py` are replaced by `breezy.runtime.autonomy_sandbox.write_sites.SHARED_WRITE_SITES`. Any AC6 allowlist (AUT-1, AUT-5, AUT-6) may admit those sites only when every `exec_snapshot`/`wal_snapshot` call in the closure passes `cache_dir=` a module-level `Final` constant of the calling module (`tests/support/autonomy_write_sites.cache_dir_is_own_module_constant`).
> - **(b) E-8 amendment.**
>   - Step 3's fingerprint is (inode, size, `mtime_ns`) plus the sha256 of db bytes 0–99 and of `-wal` bytes 0–31 and its last 4096 bytes. `-journal` adds its first 512 bytes.
>   - Before fingerprinting, any file whose `mtime_ns` is within 20 ms of now forces a 20 ms wait.
>   - Step 4 copies in the order db, `-wal`, `-journal`, fd-relative, into a `snap.*` directory created under an `O_RDONLY|O_DIRECTORY` flock of the cache dir. Contention gives the read failure `cache_busy`.
>   - The cache dir and its parent are checked by `fstat` of a nofollow-walked fd.
>   - A result is non-advisory only if the intent flock was held from the first fingerprint through the last re-fingerprint.
>   - `take_flock=True` is legal only in the AUT-5 16:45 pass, and its deadline precedes the 16:50 launch.
> - **(c) Mount-set amendment to E-7 rule 2 and E-7a rule 1.**
>   - Every row runs `--unshare-user --disable-userns --assert-userns-disabled`.
>   - `--tmpfs ~` replaces `--tmpfs ~/.config`, followed by read-only re-binds of exactly the repo, the data root and the interpreter prefix when it is under home. Then `--remount-ro ~`.
>   - `--tmpfs /run/user/<uid>`. Rows with exception `E7A_R2_NOTIFY` re-bind only their `NOTIFY_SOCKET` path, read-only.
>   - Binds are passed with `--bind-fd`, after a per-component `O_PATH|O_NOFOLLOW` walk, with dev/ino distinct from `state/` and its ancestors and on the data root's device.
>   - Config files are passed with `--ro-bind-fd`: nofollow, `st_nlink == 1`, no alias under `~/.config/breezy`.
>   - The directory re-bind of `~/.config/systemd/user` is the named exception `E7_CONFIG_DIR`, with the same checks.
>   - `--unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`.
>   - The wrapper's unit check is integrity against misconfiguration, not an authorisation boundary.
> - **(d) Self-probe amendment to E-7 rule 2.**
>   - The env-row check runs before any open.
>   - Negatives are `O_TMPFILE|O_WRONLY` and must fail with exactly EROFS; no named file is ever created under `state/`, the data root or the repo.
>   - Positives are `tmpfile` (default) or `subdir` (`.bwrap_probe/`) per bind.
>   - Credential negatives: `~/.config/breezy`, `~/.ssh`, `~/.aws`, `~/.gnupg` and `~/.netrc` give ENOENT; the home listing ⊆ the re-binds; `/run/user/<uid>/systemd/private` cannot be reached.
>   - Reason vocabulary: AUT-6's (`negative`, `negative_registry`, `positive_<bind>`, `probe_residue`) plus `env_row`, `degraded_forged`, `credentials_visible`, `user_bus_visible`, `tmp_not_private`, `pid_ns` and `negative_unverifiable`.
> - **(e) Exception labels.** `KNOWN_EXCEPTIONS = {E7A_R2_PROC, E7A_R2_NOTIFY, E7A_R2_RECONCILE, E7B_EVAL_OFFLINE_ADAPTER_MODULES, E7_CONFIG_DIR}`. `E7A_R2_PROC` replaces the `/proc/locks` label and covers `/proc/locks` and `/proc/<pid>`.
> - **(f) Consumer changes (binding build items).**
>   - **AUT-5 r7:**
>     - the inline bwrap `ExecStart` becomes the wrapper;
>     - `sandbox_probe.py` is replaced by `require_sandbox` (l.202: EACCES is no longer accepted, and negatives use `O_TMPFILE`);
>     - `OnFailure=breezy-study-failed@%n` (l.276) becomes `breezy-autonomy-failed@`;
>     - the l.275 transient-service fallback passes `--unit=breezy-autonomy-engine-l1-bootstrap.service`, which is listed in the bootstrap row;
>     - the l.386 advisory reads use `exec_snapshot(take_flock=False)`, not the G6 URI;
>     - its real-namespace tests join `BWRAP_HOST_TEST_FILES`.
>   - **AUT-6 r15:** l.260 negatives use `O_TMPFILE`; l.249's directory re-bind uses `E7_CONFIG_DIR`; `breezy-autonomy-failed@` joins `NOTIFIER_FALLBACK_ROWS`, with an alerts-only closure test.
>   - **AUT-2 r7:**
>     - wrapped G6 in-place reads use `exec_snapshot(take_flock=False)`, superseding E-8's "unwrapped AUT-2 keeps the G6 URI";
>     - reconcile credentials must arrive as environment variables via `EnvironmentFile` (verify-first), since no row can expose `~/.config/breezy`;
>     - `breezy-aut2-recon-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
>   - **AUT-4 r11:**
>     - l.875's deployed-blob check covers every path in `WRAPPER_CODE_FILES`;
>     - the E-13 tests are delivered by ARCH-0 at AUT-4's named paths;
>     - its fixture-row namespace tests join `BWRAP_HOST_TEST_FILES`.
>   - **AUT-1 r12:** its units join `AUTONOMY_OWNED_UNITS`.
> - **(g) Notifier fallback.**
>   - Only rows in the exact set `NOTIFIER_FALLBACK_ROWS` may fall back.
>   - The fallback is taken only after every configuration check has passed (exit 64/78 never falls back), with a 2 s preflight.
>   - In degraded mode, `require_sandbox` returns `ok=False, degraded=True` for those rows only and raises for any other row. Every degraded write passes `degraded_write_target`, which refuses `state/` and anything outside the row's binds.
>   - Degraded mode exposes `~/.config/breezy`; this is a stated residual.

Files relevant to this plan:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r1.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r1-security.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r1-architect.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-r1-merged.md`
- `/home/jon/breezy/tests/conftest.py`
- `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`
- `/home/jon/breezy/tests/unit/test_execution_egress_firewall_guard.py`
- `/home/jon/breezy/scripts/ci/run_t1_lanes.sh`
- `/home/jon/breezy/tests/support/nautilus_log_capture.py`