**Verdict: REQUEST_CHANGES.** One HIGH finding (F1) blocks. It is a small fix inside the plan and needs no redesign.

**E-7d sign-off: YES-WITH-CONDITIONS.**
- C-1 is F2 below.
- C-2 is the PYTEST_PLUGINS / PYTEST_ADDOPTS scrub (F7).
- Both are small edits to the script and plugin text.

**E-7e: not signed as written.** It needs F1, and (d) removed from (h).

## Scores (1–10)
| Dimension | Score |
|---|---|
| Correctness vs errata | 8 |
| Security | 7 |
| Test coverage | 8 |
| Risk mitigation | 8 |
| Scope minimality | 6 (the unused `--bus-action`) |
| Feasibility | 7 |

## r2 findings, checked against the r3 text
- **F1 (root-equivalent sockets in `/run`): fixed.**
  - `--tmpfs /run` with exact re-binds and `--remount-ro /run` is in AC-1.3 steps 3, 7 and 8.
  - The AC-2 step-6 negatives and the phase-2 tests are specified.
  - I re-measured that no socket exists outside `/run`, `/proc`, `/sys`, `/home` and `/tmp` on this host (probe 3). There is no `/var/lib/lxd` and no `/var/snap/lxd`.
- **F2 / C-1 (admission after import): fixed in design.** There is a new gap, F2 below (the collect-only claim bypass).
- **F3 (script dispatch): fixed.** One `if / elif / else exit 3` chain, exact collect-only tokens, and a claim confirmed by pytest.
- **F4 (supervisor probe): fixed.** AC-3.2 states the 16:45–16:48 behaviour and carries three tests.
- **F5 / C-2 (import lint): fixed.** The deny-list and its transitive scope are in E-7d R5.
- **F6 (operator caps file, abstract sockets): stated in R15.** Acceptable. The text names no value and no control.
- **F7 (count pin): fixed.** The +1 mutation is in the WP-B2a list.

## Rulings on the new r3 items

**(a) `--tmpfs /run`, exact re-binds, `--remount-ro /run`: ACCEPT.**
- I could not find a socket on this host that survives it.
- Residuals stated or accepted: abstract sockets and loopback TCP, because the network namespace is shared (R15, M32).
- Residual to add: the DNS re-bind exposes `127.0.0.53:53`, which is a network path and not a mount.

**(b) PROC row (`--unshare-pid`, no `--proc`, host procfs read-only via the root bind): ACCEPT.**
- I re-measured the shape inside the r3 mount set (probe 2):
  - `getpid()` returns 2, and `/proc/self` resolves to the host pid.
  - `subprocess` with `close_fds=True` works.
  - The sandbox can read its own `/proc/self/environ`.
- Leak size, measured: the `cmdline` of `breezy-trade` (529436), the supervisor (1373663) and the recorder (3373411) is readable.
  - The `cmdline` contains only interpreter and console-script paths plus the supervisor mode argument `breezy-trade-supervisor-daily`.
  - `environ` and `root` give EACCES (M26, and r2's own probe).
  - There is no `hidepid` on this host (`proc … rw,nosuid,nodev,noexec,relatime`). An unwrapped process sees the same, so the wrapper adds no exposure.
- R21 and E-7e(i) already say "status and cmdline". Add the statement that `cmdline` of other users' processes is also visible, on the same footing as unwrapped.
- Signalling is closed, because host pids give ESRCH under `--unshare-pid` (M26).

**(c) `--bus-snapshot` handoff: ACCEPT, conditional on F1. I agree with rejecting `E7A_R2_USER_BUS`.**
- M21 and M22 are decisive. The bus works only without `--unshare-pid`, which reopens signalling (M25), and it then lets `systemd-run` create units outside the sandbox.
- The literal verb allow-list (`show`, `list-units`, `list-timers`) is tight.
- The `INVOCATION_ID` binding is sound.
- A failed read is recorded and does not abort. This matches the UNKNOWN semantics in the consumer plans.

**(d) `--bus-action`: REJECT for seam B.** The AUT-1 drill and guard run unwrapped as a stated E-7a rule-5 residual until AUT-1 re-files it. Reasons:
1. It is a state-changing path, `systemctl --user kill`, driven by a file the sandbox writes. In seam B it ships empty (`BUS_ACTION_TARGET_UNITS` is empty) and unused, with no consumer to review it against. That is dead code in the most security-critical module.
2. The AC-9.4 argv has no `--kill-whom=main`. The default is `all`, so SIGSTOP freezes every process in the recorder's cgroup, not only its main process.
3. It has the same unprotected directory-follow as F1, and F1 compounds the problem.
4. The residual is no worse than today. The drill and guard are stdlib scripts that already run with full home.
5. When AUT-1 files it, the E-7f text should require:
   - `--kill-whom=main` or an explicit rationale for `all`;
   - the F1 directory discipline;
   - a SIGCONT guarantee on every exit path;
   - a target set added with a plan:line.

   Delete AC-9.4, the `BusAction` type, `E7A_R2_BUS_ACTION`, `BUS_ACTION_TARGET_UNITS` and `--bus-action` from B2c, and delete E-7e(h) paragraph 2, including its Residual line.

**(e) AUT-2 reconcile via `LoadCredential` and a read-only re-bind of `$CREDENTIALS_DIRECTORY`: ACCEPT, with conditions.**
- The wrapped process sees only a copy of the key file. It cannot see `~/.config/breezy`. That is strictly narrower than the unwrapped run.
- `require_key_file_mode` already exists as a keyword on `load_polymarket_us_credentials` (`env.py:75-81`), so no loader edit is needed.
  - Say so in E-7e(f).
  - Add that no `env.py` change and no firewall-test change is permitted.
  - The loader still enforces owner uid.
- The AC-1.3 7(d) checks are right: the exact path under `/run/user/<uid>/credentials/<cgroup leaf>`, mode 0500, and exactly the listed names at 0400.
- Conditions:
  1. The reconcile-only env file (verify-first) must set only `POLYMARKET_US_SECRET_KEY_FILE`. The inline-key variable must be absent, because the loader requires exactly one source.
  2. The row ships unused in seam B, as written.
  3. Keep the stated residual that the sandbox holds a copy of the venue key and a shared network.
  4. AUT-2 must keep reconcile GET-only. That is a consumer test and not wrapper code.

**(f) `E7_STUDIES_LOCK` re-bind of `/run/user/<uid>/breezy-studies.lock`: ACCEPT, with a feasibility fix (F5).**
- The mutual exclusion measured in both directions (M27).
- The two-inode finding is correct. `replay-daily-run.sh:94-101` resolves the lock to `$XDG_RUNTIME_DIR/breezy-studies.lock`.

**(g) Phase-2 admission conditions 6 and 7, collect-only claim, import lint: ACCEPT, conditional on F2 and F7.**
- `pytest_load_initial_conftests` runs before any initial conftest import, and the `ignore_collect` result is as measured (M31).
- I checked the project addopts. They are `-q --strict-markers --strict-config -m 'not live and not venue_live and not real_money'`. They contain no `-p`, so the "no extra `-p`" rule works. The phase-2 `-m` comes later and wins.
- The import lint is adequate. The file-path-loading residual is stated and covered by the denied `spec_from_file_location` and `SourceFileLoader`.

## Findings

**F1 — HIGH, blocking. AC-9.2 and AC-9.4, unsandboxed writer and sweeper follow a sandbox-planted symlink.**
- Problem: the unsandboxed `--bus-snapshot` and `--bus-action` modes write `.bus_snapshot/<ID>.json` and `.bus_action/…` inside a bind that the sandbox mounts read-write.
  - `O_NOFOLLOW` constrains the final component only. A sandbox that replaces `.bus_snapshot` with a symlink to `state/` makes the next run, which is not sandboxed, create files in the live state directory. I reproduced it: `openat(base_fd, ".bus_snapshot/x.json", O_CREAT|O_EXCL|O_NOFOLLOW)` created the file through a symlinked directory (probe 3).
  - The "sweep entries older than 24 h" step would then unlink files in `state/`. That violates "the live exec store is never written". The sandbox can reach the paths because `state/` is visible read-only.
- Fix:
  1. Open the subdirectory with `openat(bind_fd, ".bus_snapshot", O_DIRECTORY|O_NOFOLLOW|O_RDONLY)`.
  2. `fstat` it. Require a directory owned by this uid, with `st_dev` equal to the base's device and `(st_dev, st_ino)` different from `state/`, from every ancestor of `state/`, and from the data root. Reuse the AC-1.2 checks.
  3. Create with `dir_fd`.
  4. In the sweep, list with `os.scandir(dirfd)`. Delete only names that fullmatch `^[0-9a-f]{32}\.json$`, with `lstat(follow_symlinks=False)` giving `S_ISREG`. Use `unlinkat(dir_fd)`.
  5. Take the flock on the validated fd, not on a path.
  6. Add tests `test_bus_snapshot_dir_symlink_refused_writes_nothing_and_sweeps_nothing` and `test_bus_snapshot_sweep_deletes_only_matching_regular_files`, plus a mutation that drops `O_NOFOLLOW` on the subdirectory.

**F2 — MEDIUM, blocking only as E-7d C-1. Gate, collect-only claim bypassed by flags that disable the root conftest.**
- Problem: the claim check lives in `pytest_configure` of a plugin that is loaded through root-conftest `pytest_plugins` (C1).
  - `run_tests_no_egress.sh … -k --co --noconftest` (or `-c` / `--confcutdir`) sets the shell hint to 1, so phase 2 is skipped.
  - pytest treats `--co` as the `-k` value and runs tests, but the conftest and the claim check never load.
  - So "no flag disables it" is false.
- Fix: load the plugin in phase 1 with `-p tests.support.bwrap_host_phase` too, which `--noconftest` does not defeat, and keep C1 as is.
  - Better, have the plugin write the confirmation to a file the script reads, using a mode-0600 file under `$GATE_DIR`. The script then omits phase 2 only if that file says collect-only.
  - Add test `test_collect_only_claim_with_noconftest_exits_nonzero_and_runs_phase2`.

**F3 — MEDIUM, non-blocking. AC-9.2, `{instance}` is substituted into an argv without a post-substitution check.**
- Problem: for a `name@` row the cgroup leaf matches any instance of the form `[a-z0-9-]*`. An instance that starts with `-` becomes an option token for systemctl.
- Fix: after substitution, re-apply the unit-token regex `^breezy-[a-z0-9@.*_-]+$` to the result. Require the instance to be non-empty and to start with `[a-z0-9]`. Insert `--` before the unit tokens. Test with `breezy-x@-all.service`.

**F4 — MEDIUM, non-blocking. `--bus-snapshot` is unsandboxed and reads `{instance}` and an environment value, so a missing `INVOCATION_ID` or other config problem must not fall through.**
- The plan already says exit 64/78. Add the explicit statement that the snapshot write happens only after all of the AC-1 checks, and that `os.execv` is never used in this mode.

**F5 — MEDIUM, non-blocking. AC-1.3 7(c), the studies lock does not exist after a reboot.**
- Problem: `/run/user/<uid>` is a tmpfs, and the studies create the lock on demand. The wrapper "never creates a bind source", so an `E7_STUDIES_LOCK` row gets 78 until a study has run.
  - For AUT-6 daily that is a CRITICAL "wrapper refused" after every boot.
- Fix: for `E7_STUDIES_LOCK` rows only, `open(O_CREAT|O_RDWR|O_NOFOLLOW|O_CLOEXEC, 0o600)` in the wrapper before the nlink and owner checks. This matches the studies' own `exec 9>` behaviour. Add the exception to the L-12 text and add a test.

**F6 — LOW, non-blocking. E-7e(i) and R21.**
- Add that `/proc/<pid>/cmdline` of every process is readable on PROC rows, at parity with unwrapped. Add the `127.0.0.53` DNS note to R15.

**F7 — LOW, E-7d C-2. `run_phase2` environment.**
- `python -I` ignores `PYTHON*` variables but not `PYTEST_PLUGINS` or `PYTEST_ADDOPTS`. `PYTEST_PLUGINS` imports an arbitrary module before the early hook.
- Fix: `env -u PYTEST_PLUGINS -u PYTEST_ADDOPTS …` in step 4, and admit the early witness only if neither is set. Add them to `test_p2_option_widening_refused`.

**F8 — LOW, non-blocking. E-7e(c) and AC-2 step 8.**
- The self-probe pid check `readlink("/proc/self") != getpid()` is an integrity check only. State it, so no consumer treats it as a boundary.

## Probes I ran (verbatim, abbreviated)
```
1. grep addopts pyproject.toml
   addopts = "-q --strict-markers --strict-config -m 'not live and not venue_live and not real_money'"
2. bwrap --unshare-user --disable-userns --assert-userns-disabled --unshare-pid --ro-bind / / \
        --tmpfs /run --dev /dev --tmpfs /tmp --bind $S $S /usr/bin/python3 p.py
   pid 2 self-> 1207134 ; subprocess rc 0 ; self environ readable: True
   529436 breezy-trade   cmdline '/home/jon/breezy/.venv/bin/python\0…/breezy-trade\0'
   1373663 breezy-trade-su  …breezy-trade-supervisor\0breezy-trade-supervisor-daily\0
   3373411 …breezy-quote-tape
   grep ' /proc ' /proc/mounts -> proc /proc proc rw,nosuid,nodev,noexec,relatime  (no hidepid)
3. find / -xdev ( -path /proc -o /sys -o /run -o /home -o /tmp ) -prune -o -type s -print -> (none)
   ls /var/lib/lxd /var/snap/lxd -> absent
   symlinked-dir demo: openat(base_fd, ".bus_snapshot/x.json", O_CREAT|O_EXCL|O_NOFOLLOW)
   -> created via symlinked dir; in tgt: ['x.json']
4. sed replay-daily-run.sh:90-102 -> LOCK="${XDG_RUNTIME_DIR}/breezy-studies.lock" after mkdir -p (created on demand)
5. env.py:75-81 -> require_key_file_mode keyword already exists; default 0o600
6. pytest --version -> pytest 9.1.1
```

Not re-measured: M17–M19 (verified for sockets only), M27 and M28 (taken from the plan), and M31 (taken from the plan and r2). These need V15, V18 and the `LoadCredential` check at build.

Files:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r3.md`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/env.py`
- `/home/jon/breezy/deploy/systemd/replay-daily-run.sh`
- `/home/jon/breezy/pyproject.toml`