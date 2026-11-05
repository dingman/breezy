**Verdict: REQUEST_CHANGES.** The wrapper and snapshot design is mostly sound. Two defects need fixing before build: the phase-2 gate as written cannot run, and the self-probe breaks the invariant it protects.

| Dimension | Score |
|---|---|
| Correctness vs errata | 7 |
| Security | 5 |
| Test coverage | 7 |
| Risk mitigation | 6 |
| Scope minimality | 8 |
| Feasibility | 5 |

## Verification I ran (read-only, no writes)

```
$ bwrap --unshare-net --dev-bind / / bwrap --ro-bind / / true
bwrap: No permissions to create a new namespace, ...        nested_rc=1
$ bwrap --ro-bind / / --dev /dev --proc /proc true          flat_rc=0
$ bwrap --unshare-net --ro-bind / / ... python3 (connect 198.51.100.7:80)
net: [Errno 101] Network is unreachable
```
ER-B1 is real. Nesting is denied, and a single level works from outside the gate.

```
$ bwrap --ro-bind / / --tmpfs ~/.config --dev /dev --proc /proc --unshare-pid python3 -c "connect('/run/user/1000/systemd/private')"
systemd private socket CONNECT OK
home listing includes: .aws ... ; os.path.exists(~/.ssh) -> True
```
The sandbox can reach the user systemd manager. `~/.aws` and `~/.ssh` stay visible.

`tests/conftest.py:292-325` and `:359-380` (`execution_egress_abort_reason`): with execution-egress modules present and `BREEZY_TEST_OS_EGRESS_BLOCK` unset, `pytest_sessionstart` calls `pytest.exit(..., returncode=2)`.

`bwrap --help` lists `--bind-fd`, `--ro-bind-fd` and `--disable-userns`.

## Findings

**1. CRITICAL (Phase-2 gate, §Architecture and R2). Phase 2 cannot run as specified, and the obvious fix weakens the NO-SEND barrier.**
- Problem:
  - Phase 2 exports only `BREEZY_BWRAP_HOST_PHASE=1`, so the pytest parent has no egress attestation.
  - Barrier N2 in the root conftest then aborts the session at start with exit 2. The plan defers this to a V0 check, after merge.
  - The only quick ways to make it run are two. One sets `BREEZY_TEST_OS_EGRESS_BLOCK=1` falsely, which N3's real-connect canary catches. The other adds a bypass to the safety conftest.
  - "Every child has `--unshare-net` plus the in-process block" is not enough for the parent. The conftest comment says the Python block does not constrain the native pyo3 `reqwest` client. Phase 2 is the only place the parent runs with real network and execution-egress modules importable.
- Fix:
  - Make N2 a design item of WP-B2, in phase 1, with RED→GREEN tests. Do not leave it to V0.
  - Add one narrow conftest rule: a distinct `BREEZY_BWRAP_HOST_PHASE=1` is accepted in place of attestation only when all of the following hold.
    - Every collected nodeid is under `tests/integration/autonomy_sandbox/`.
    - The grimp import closure of those test modules, plus their conftests and support modules, contains zero `find_execution_egress_modules()` hits and no `nautilus_trader` or `adapters`.
    - The credential-env gate still runs.
    - `BREEZY_TEST_OS_EGRESS_BLOCK` is absent.
  - Add negative tests: a collection that includes any other path exits 2; a test module that imports an adapter exits 2.
  - Phase-2 tests must import only `breezy.runtime.autonomy_sandbox` and stdlib. Add a runtime assertion that `sys.modules` has no `nautilus_trader*` and no `breezy.adapters*`.
  - Stronger alternative: replace the pytest parent with a stdlib-only runner that spawns the bwrap children and has no Nautilus loaded. Phase 1 can then parse its JSON output. This removes the need for the N2 exception.
  - Do not use systemd `PrivateNetwork`, because E-7 shows user-unit directives are no-ops here.

**2. HIGH (AC-2 and `self_probe.py` row). The self-probe writes into the live `state/` on the failure path.**
- Problem:
  - Negative probes use `O_WRONLY|O_CREAT|O_EXCL` under `state/`, the data root and the repo. If the sandbox is broken, this creates a file in the exec-store directory and then unlinks it.
  - That violates "autonomy code must never write the live exec store". It happens exactly when containment has already failed.
  - The V10 claim "no new files in state/" cannot hold in the failure case.
  - Separately, a crash between create and unlink leaves litter in `state/`.
- Fix:
  - Use `os.open(dir, O_TMPFILE|O_WRONLY)` for negative probes. It creates no name, so nothing can leak.
  - Ext4 works (E-7a, "Not part of E-7a: O_TMPFILE"). The unwritable-directory case gives EROFS/EACCES.
  - Where O_TMPFILE is unsupported, fall back to `statvfs(...).f_flag & ST_RDONLY` plus a `/proc/self/mountinfo` `ro` flag check, never a named create under `state/`.
  - Keep `O_CREAT|O_EXCL` only for the positive probes inside binds.
  - Add a test that runs the probe against a writable fake `state/` and asserts the directory listing is unchanged (an inotify or `listdir` before/after check).

**3. HIGH (AC-1.2 and AC-1.3, TOCTOU on binds). Validation is by path string; bwrap re-resolves the path later.**
- Problem:
  - A bind swapped for a symlink to `state/` between validation and `execv` yields a writable `state/`.
  - `--bind` follows symlinks.
  - The same-uid race is narrow. The self-probe is the only backstop, and it runs only if the entry point calls it.
- Fix:
  - In the wrapper, open each bind with `O_PATH|O_DIRECTORY|O_NOFOLLOW` per path component, or `openat2(RESOLVE_NO_SYMLINKS)`.
  - Compare `st_dev` and `st_ino` against `state/` and every state ancestor. Passing the data root alone is not sufficient.
  - Pass the fd with `--bind-fd FD DEST` (supported by 0.11) and keep the fd inheritable across `execv`.
  - Also verify that each bind's `st_dev` is the data-root device. Unit-test the swap with a symlink-to-state fixture.
  - Add to the AC-2 negatives that the `state` inode is never writable via any bind.

**4. HIGH (AC-1.3 and the Edge Cases env row). Credential and escape surface is wider than `~/.config/breezy`.**
- Problem:
  - I measured `~/.aws` and `~/.ssh` readable under the proposed mounts.
  - With network not unshared on most rows, any code that is compromised or buggy can read them.
  - The systemd private socket (and `/run/user/UID/bus`) is connectable. A sandboxed process can run `systemd-run --user` and start an unsandboxed unit, which defeats the whole E-7 write scope. The `subprocess` lint denylist is the only barrier.
- Fix:
  - Mount `--tmpfs /run/user/<uid>` on every row. Re-bind only the `NOTIFY_SOCKET` path for `Type=notify` rows, read-only.
  - Hide `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.netrc` and any `*.env` under the repo and data root. Derive the list from a live listing, per L-14, and put it in `self_probe_plan` as ENOENT negatives.
  - Add `--disable-userns` with `--assert-userns-disabled` on every non-selftest row.
  - Add a test that connects to `/run/user/UID/systemd/private` inside a phase-2 row and expects failure.
  - Document that the sandbox protects against bugs, not a malicious same-uid process, and keep the lint as the second layer.

**5. HIGH (AC-1.3, `config_ro_binds`). The credential-hiding rule is a string-prefix check, so a symlink defeats it.**
- Problem:
  - A `config_ro_binds` entry like `foo` that is a symlink to `~/.config/breezy/creds` passes the `^breezy` test, and bwrap binds the real credential file.
  - AC-1.2 validates directories only. Nothing specifies file validation.
- Fix:
  - Open each config file with `O_NOFOLLOW`, then take `realpath`/`fstat`. Refuse if the final path is under `~/.config/breezy`, if any component is a symlink, or if `st_nlink > 1` and the inode matches a file under `~/.config/breezy`.
  - Add the fixture tests: symlink to breezy, a hardlink, and `..`.

**6. MEDIUM (AC-3 step 4 and the Edge Cases tick row). Torn reads are still possible inside one mtime tick.**
- Problem:
  - The header digest covers the first 32 bytes of `-wal` and the first 100 bytes of the db.
  - A checkpoint rewrites db pages with the same size and the same coarse mtime tick (about 4 ms), and the db header can be unchanged. That is a silent torn copy.
  - `quick_check` verifies structure only, not that the db and WAL pair is consistent.
  - R4's mitigation is partly rhetorical: V13 only measures that the tick exists.
- Fix:
  - Add a quiescence guard. If any fingerprinted file has `mtime_ns > clock_ns() - 20 ms`, sleep and re-fingerprint before copying. This forces the tick to have passed.
  - Hash the WAL tail (the last 4 KiB) and the db size. Fingerprint the db header bytes 24–40 (change counter, version-valid-for).
  - Add a test whose fake writer rewrites within one tick, using an injected clock and mtime that is frozen.
  - Mark every non-flocked result as advisory (already done in AC-3.3). State in the AC that `advisory=False` is only valid with the flock held through the copy.

**7. MEDIUM (AC-3.2 and the snapshot data flow). The helper's flock can collide with node boot.**
- Problem:
  - `hold_submit_intent_process_lock` (`submit_intent.py:556-580`) takes `LOCK_EX|LOCK_NB` and raises `SubmitIntentLockHeld` on contention. The supervisor's `intent_lock_is_free` also takes `LOCK_EX|LOCK_NB`.
  - If the helper holds the flock while the node boots or the supervisor probes, the node refuses and the supervisor mis-reads "held".
  - The 2026-09-24 "launch deadlock" memory shows this class of failure is costly.
  - The helper bounds its hold time (≤1 s plus 5 s sleeps between attempts). It does not bound the interaction with a launch.
- Fix:
  - State in the AC that `take_flock=True` is only legal in the pre-launch pass (the allowlist test already says that).
  - Add a phase-1 test where a simulated node start runs concurrently with the helper's hold and does not deadlock or crash.
  - Document that the 16:48:00 deadline must precede the node launch time.

**8. MEDIUM (AC-1.1 and `main`). The cgroup unit binding is a misconfiguration check, not a security control. The plan frames it as stronger.**
- Problem:
  - Any same-uid process can `systemd-run --user --unit=breezy-autonomy-engine@daily ...` and get a row's binds.
  - Confusion is also possible when a unit's cgroup path nests (for example a `.slice`), since only the last component is read.
  - A cgroup-v1 or hybrid file with no `0::` line is not specified.
- Fix:
  - State "integrity against misconfiguration, not an authorisation boundary" in the AC and the README.
  - Require exit 78 for a missing `0::` line, multiple lines, or a non-`.service` leaf. Add tests for each.
  - Add a `test_main_cgroup_scope_and_slice_leaf_refused` case.

**9. MEDIUM (AC-1.5, notifier fallback and R7). The unwrapped fallback scope is unbounded as written.**
- Problem:
  - A degraded notifier runs with full user write, including `state/`. It does not run `require_sandbox`, because there is no sandbox.
  - The only protection is "residual stated".
  - `BREEZY_AUTONOMY_SANDBOX_DEGRADED=<code>` is an env variable and can be forged, but the forgery gives nothing extra.
- Fix:
  - Allow the fallback only for rows whose lint closure has zero judged write sites outside the alerts bind.
  - Make the lint enforce an exact-set allowlist for `notifier_fallback` rows, with a named test.
  - Skip `require_sandbox` only when `BREEZY_AUTONOMY_SANDBOX_DEGRADED` is set, and have the notifier call a no-write-to-`state/` hard assertion (resolve each write target and refuse anything under `state/`).
  - Use the preflight exit code only after bind validation, so config errors (78) never fall back. State this in a test.

**10. MEDIUM (AC-1.5). The preflight needs bounds.**
- Problem: `subprocess.run(..., timeout=10)` runs `/bin/true` under the same mount argv. A bwrap hang adds 10 s to every notifier start.
- Fix: cap it at 2 s, and cache the verdict by writing nothing. Keep it list-argv.

**11. LOW (AC-1.2 and AC-3.8). Directory-permission checks should be on `fstat` of the opened fd, not `lstat` of the path.**
- Fix: open the cache dir with `O_DIRECTORY|O_NOFOLLOW`, then `fstat` the fd. Use `dir_fd` for the snapshot copies (`openat`) so a parent swap cannot redirect them.

**12. LOW (Wrapper script). The shebang `-I` still resolves the repo from an editable install pointing at the primary tree.**
- Problem: a branch checkout in the primary tree changes the live wrapper code.
- Fix: V11 (blob sha) checks only the script file, not `src/`. Add the sha of `bwrap.py` and `table.py` to V11.

**13. LOW (Coverage gaps).** Add these tests:
- `test_phase2_aborts_when_collected_outside_dir` (finding 1).
- A bind swapped for a symlink to `state/` (finding 3).
- A config-file symlink to a credential (finding 5).
- The systemd private socket is not connectable (finding 4).
- A probe against a writable `state/` leaves the directory unchanged (finding 2).
- A malformed cgroup input (finding 8).
- `ROW` containing newline, NUL, or `--`.
- A command argv[0] starting with `-` goes through `--` verbatim.
- Concurrent wrappers that share the same `tmpfs` binds.
- The "bwrap child sees no `BREEZY_TEST_OS_EGRESS_BLOCK`" check.

## Direct answers to the focus questions

1. **Egress hole:** The children are safe (`--unshare-net`, measured ENETUNREACH). The pytest parent is not covered. Finding 1 gives the tighter alternative: a stdlib-only runner, or a scoped N2 rule with closure proof.
2. **Wrapper:**
   - Argv injection: the list-argv and `--` design is sound.
   - Weaknesses: binds are path-checked (3), file binds follow symlinks (5), cgroup binding is not a boundary (8), credential and bus exposure (4), fallback scope (9).
3. **Snapshot helper:**
   - It creates nothing in `state/`. The `O_RDONLY` lock open avoids creation, and `-shm` is never copied. The copy never opens the source in place, so there is no source checkpoint.
   - The self-probe does write to `state/` on failure (2). Torn reads are possible inside a tick (6). Flock contention with node boot is possible (7).
4. **ER-B1:** Real, with the exact error above.
5. **Missing:** see finding 13.

Files: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r1.md`, `/home/jon/breezy/tests/conftest.py`, `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`, `/home/jon/breezy/src/breezy/runtime/submit_intent.py`, `/home/jon/breezy/src/breezy/runtime/trade_supervisor.py`.