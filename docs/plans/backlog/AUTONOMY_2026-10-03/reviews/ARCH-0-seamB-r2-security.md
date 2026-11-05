SIGN-OFF on E-7d: **YES-WITH-CONDITIONS** (C-1 and C-2 below). Overall: **REQUEST_CHANGES**. Both conditions are small and fixable inside r2 without redesign.

## Scores (1–10)
| Dimension | Score |
|---|---|
| Correctness vs errata | 8 |
| Security | 7 |
| Test coverage | 8 |
| Risk mitigation | 7 |
| Scope minimality | 7 |
| Feasibility | 8 |

## r1 security findings, verified rather than taken from the table
- **Sec-1 (phase-2 gate): fixed in design, with a gap.**
  - The blocker at `meta_path[0]`, the exact registry and the session-end check close the r1 hole.
  - The admission is not enforced before collection (F2).
- **Sec-2 (probe writes into `state/`): fixed.**
  - A `O_TMPFILE` negative on a read-only bind returned EROFS even for a mode-0500 directory, so there is no EACCES ordering trap.
  - The fallback never creates a name.
- **Sec-3 (bind TOCTOU): fixed.**
  - `--bind-fd` closes the fd inside the sandbox. My `openat(fd, "../../state/x")` from inside got EBADF, and the sandbox saw only fds 0–3.
- **Sec-4 (credential and bus exposure): partly fixed.**
  - Hiding all of home and `/run/user/uid` is correct.
  - The `/run` and `/var/run` sockets are still reachable (F1).
- **Sec-5 (config-file symlink): fixed on paper.**
  - The nofollow, `st_nlink` and dev/ino design is sound, but I could not test it because the code does not exist yet.
- **Sec-6 to Sec-13: fixed as designed.**
  - Sec-7 (flock vs node boot) is only partly covered, because the supervisor also probes the lock (F4).

## Focus (1): gate change
- **Absent-input N2 is byte-identical.**
  - `bwrap_host_phase=None` falls through to today's body (`conftest.py:292-326`).
  - C4 computes the admission only when the env var is present, and C2 returns early only when the phase is active.
  - Condition: the env var counts as "present" if it is set to any value, including `""`, `"true"` or `"1 "`. In that case the run aborts with rc 2 and the not-admitted message. That differs from today's output only when the var is set, which is acceptable. State it, and test attested+`"true"` explicitly.
- **Order-path code cannot load in the phase-2 parent, with caveats.**
  - The parent installs the blocker first (via `-p` and `pytest_plugins`), and entry-point plugins load after `-p`.
  - Installed `pytest11` plugins are `respx`, `pytest_cov`, `hypothesispytest`, `randomly`, `asyncio` and `anyio`. None imports Nautilus. `nautilus_pyo3` is not a top-level module here (`find_spec` returned None).
  - All 9 egress hits are under `breezy.adapters`, so the blocker covers them. The session-end `sys.modules` check is a good backstop.
  - Caveats: F2, and file-path loading is not intercepted (F5).
- **A phase-1 run cannot be tricked into running unattested.**
  - The script unsets the phase var, and attested plus phase evidence gives rc 2.
  - The only way in is a direct `pytest` run with the var set, which is the phase-2 semantics. That route is not safe until F2 is fixed.
- **Native non-Nautilus network paths are an acceptable residual, on conditions.**
  - Condition C-2: the AST lint described under F5.
  - `respx` pulls `httpx` into the parent, so the Python socket block (a per-test autouse fixture) does not cover import time. The residual stays acceptable only because the registry is a closed, AST-pinned set.

## Focus (2): mount design (my probes)
- **M5 holds.** `--unshare-user --disable-userns` on every row works, and `/proc/1/comm` is `bwrap` under `--unshare-pid`.
- **Rows without `--unshare-pid` do not escape through `/proc`.**
  - Without `--unshare-pid`, `/proc/locks` has 154 lines, which matches the claim.
  - With `--unshare-user`, `/proc/<hostpid>/root/home/jon` and `/proc/<pid>/environ` both returned "Permission denied". Keep `--unshare-user` mandatory for those rows, and add that as a phase-2 test.
- **M8 holds** (see Sec-3 above).
- **Not re-run by me:** M6, M9 and M10. They are plausible, and V12 and V14 will check them on the host.
- **F1 is the exposure left in the mount design.**

## Focus (3): self-probe
- **O_TMPFILE with exactly EROFS holds.** `root/m500`, `root/m700` and `root/state` all returned EROFS on a read-only bind.
- **The "never a name under `state/`" claim holds on every path,** including the EOPNOTSUPP fallback (statvfs plus the mountinfo `ro` flag, no create).
  - The `subdir` positive creates a file only inside `<bind>/.bwrap_probe/`. Binds are fd-validated to differ from `state/`, and the env-row check returns before any open on a forged or absent row.
- **One real hazard.** On a writable directory O_TMPFILE succeeds, which is correct (it is a failure signal). It leaves no name, only an orphan inode that the kernel reclaims on close.

## Focus (4) and (5): snapshot helper, notifier fallback
- Quiescence, digests, the flock order (cache flock, then intent flock, no cycle) and `CACHE_BUSY` are sound.
- The one gap is the supervisor's lock probe (F4).
- `NOTIFIER_FALLBACK_ROWS` is empty in seam B, which is the safe default.
  - `degraded_write_target` is a caller-invoked convention, so enforcement lives in the consumers' closure tests. Say so in the AC.
  - Env credentials such as `alerts.env` arrive through `EnvironmentFile` and pass through the sandbox, so the notifier keeps working under the wrapper.

## Findings
1. **HIGH, §AC-1.3 argv, step 2 (`--ro-bind / /`): root-equivalent sockets are reachable from every row.**
   - Problem: this user is in the `docker` and `lxd` groups. From inside the sandbox, `connect` to `/var/run/docker.sock` succeeded, and so did `/run/snapd.socket`. Docker is a full escape and bypasses the write scope. M12 and the `--tmpfs /run/user/uid` fix cover only the user runtime directory.
   - Fix:
     - Add `--tmpfs /run` after `--ro-bind / /`, then re-bind read-only only what rows need: `/run/systemd/resolve` (DNS) and the `NOTIFY_SOCKET` path.
     - Add self-probe negatives: `connect` to `/var/run/docker.sock`, `/run/snapd.socket` and `/var/snap/lxd/common/lxd/unix.socket` must give ENOENT. Add a derived check that `/run` contains no `S_ISSOCK` entry beyond the allowlist, with reason `host_socket_visible`.
     - Add a phase-2 test for it.
     - Add this to ER-B2(c) and the README.

2. **MEDIUM (C-1), Gate, N2 admission: the "outside registry" check runs after collection.**
   - Problem: `pytest_collection_modifyitems` runs after test modules have been imported. `BREEZY_BWRAP_HOST_PHASE=1 pytest tests/...` therefore executes module-level code of any non-registry test that does not import Nautilus, in an unattested, networked parent.
   - Fix:
     - Add admission condition 6: at `pytest_sessionstart`, every `config.args` entry must resolve to a registry file or directory, and `-k`, `--rootdir` and `--noconftest` must not widen the set. Otherwise exit rc 2.
     - Add `pytest_ignore_collect` (tryfirst) returning True for any non-registry path in phase 2. Keep the `modifyitems` check as a backstop.
     - Add test `test_p2_args_outside_registry_abort_before_import`, using a fixture module with an import-time side-effect witness.

3. **MEDIUM, §Gate script (drop `exec`): control flow is under-specified.**
   - Problem: `exec` currently stops the fall-through into the `unshare` branch and the rc-3 exit. Dropping it can run phase 1 twice, or run phase 1 and then exit 3, unless each branch is closed. Also, `--collect-only` or `--co` is matched anywhere in `"$@"`, so `-k --co` skips phase 2 while pytest actually runs tests. That breaks "no flag disables it".
   - Fix:
     - Restructure as `if bwrap-ok; then p1_run; elif unshare-ok; then p1_run; else exit 3; fi`, with the phase-2 call after the single if-chain.
     - Match collect-only only on exact argument tokens, and exclude values consumed by `-k`, `-m`, `-p` and `-o`. Alternatively, pass `--collect-only` as the only recognised form and also catch `--collectonly`.
     - Add a test for the `-k --co` case.

4. **MEDIUM, §AC-3.2 and Edge Cases: the supervisor's intent-lock probe is untested.**
   - Problem: `intent_lock_is_free` (`trade_supervisor.py:310-330`) opens `O_RDWR` and takes `LOCK_EX|LOCK_NB`. While the helper holds the lock, the supervisor reads "not free". Only the node-boot side is tested in r2.
   - Fix:
     - Add a test `test_take_flock_true_hold_is_read_as_busy_by_supervisor_probe_and_released`.
     - State in the AC what the supervisor does on "not free" at 16:45–16:48 (hold, do not launch or retire).
     - Keep the hold under 1 s (the r2 AC already bounds it).

5. **LOW (C-2), Gate, residuals: the phase-2 parent has host network and no tripwire for non-Nautilus network code.**
   - Fix:
     - Extend `test_bwrap_host_files_import_no_subprocess_nautilus_or_adapters` to also deny `ctypes`, `socket`, `http*`, `urllib*`, `requests`, `httpx`, `aiohttp`, `websockets`, `runpy`, `os.exec*`/`os.system`/`os.popen` and `importlib.util.spec_from_file_location`.
     - Apply it to the registry files and to any support module they import, including the harness.
     - State in E-7d's residual that file-path loading bypasses the blocker and that it is covered by this lint.

6. **LOW, §AC-1.3 / R15: the ro-bound repo exposes git-ignored files.**
   - Problem: `/home/jon/breezy/operator.env` is readable in every row. It holds only the two caps and no credentials. Abstract unix sockets are also shared on rows that do not unshare the net namespace (several `@…/bus/…` entries exist). My connect to `bus-api-user` was refused, so this is unproven.
   - Fix: state both in R15. Do not name or assign operator controls anywhere in the plan or tests. If the lint wants a visible-file negative, use a generic `*.env` listing check with no values read.

7. **LOW, §AC-7 count pin: `BWRAP_HOST_EXPECTED_TESTS` is "fixed at build".**
   - Fix: land B2a with the literal pinned in the same commit that adds the registry files, as the plan already says. Add a mutation (L-33) that bumps the literal by one and must fail.

## Probes I ran (verbatim, abbreviated)
```
$ bwrap ... --bind-fd 3 ... python p1.py 3    -> open fds: ['0','1','2','3']; fd probe: [Errno 9] Bad file descriptor
$ bwrap --unshare-user --disable-userns --ro-bind / / ... --ro-bind $R $R  p2.py (with and without --unshare-pid)
  root/m500 EROFS | root/m700 EROFS | root/state EROFS | /proc EACCES | /dev/shm SUCCESS
  /var/run/docker.sock CONNECT OK | /run/snapd.socket CONNECT OK
  locks: 0 (unshare-pid) / 154 (without) ; /proc/1/comm: bwrap / systemd
$ id -nG -> ... docker lxd ; ls -l /var/run/docker.sock -> srw-rw---- root docker
$ bwrap --unshare-user ... --tmpfs /home/jon sh -c 'ls /proc/$P/root/home/jon; cat /proc/$P/environ'
  -> Permission denied (both)
$ importlib find_spec('nautilus_pyo3') -> None ; pytest11 entry points: respx, pytest_cov, hypothesispytest, randomly, asyncio, anyio
$ intent_lock_is_free: trade_supervisor.py:310-330 opens O_RDWR, flock(LOCK_EX|LOCK_NB)
$ ls repo root -> operator.env present (git-ignored; keys: two caps only)
```

Files:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r2.md`
- `/home/jon/breezy/tests/conftest.py`
- `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`
- `/home/jon/breezy/src/breezy/runtime/trade_supervisor.py`