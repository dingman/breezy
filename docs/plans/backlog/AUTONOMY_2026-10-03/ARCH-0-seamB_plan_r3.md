# Build plan r3: ARCH-0 seam B (sandbox wrapper, bus handoff, WAL snapshot helper, C4.1 holdout ruling)

**Basis**
- **Frozen sources.** ARCH Rev 9.2 is frozen. `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` and `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md` both hash to `1b288d0e0172b233…` this session.
- **Errata and rulings.** Errata E-7, E-7a, E-7b, E-7c, E-8, E-8a, E-9 and E-13 apply, plus the AC6 ruling (`reviews/AUT-6-r9-merged.md:11-15`). The binding coordinator rulings are B-R1..B-R8 and B3-R1..B3-R10 (`reviews/ARCH-0-r1-merged.md:6-41, 58-99`).
- **Repo state.** HEAD is `d231497d` on `feat/data-capture-and-risk`.
- **What I touched.** I wrote no repo file. Probes wrote scratch only, under `/tmp/claude-1000/seamb3/`. The transient units (`seamb3-probe-*`) ran `--collect`, and none remains afterwards (`systemctl --user list-units --all 'seamb3*'` lists 0). Credential files were read for variable names only, never values.

**MEASURED this session (M14–M32); r2's M1–M13 are carried in condensed form**

| # | Fact |
|---|---|
| M1–M13 (r2) | M1: nested bwrap is denied inside the gate. M2/M3: the phase-2 parent loads no Nautilus under the blocker plus conftest edits C2/C4. M4: 9 egress hits, all under `breezy.adapters.polymarket_us`. M5: `--disable-userns` needs `--unshare-user`. M6: the home tmpfs plus ro re-binds hide credentials. M7: `--tmpfs` over an absent path fails. M8: `--bind-fd` and `--ro-bind-fd` work. M10: an ro-bound notify socket delivers. M11: the interpreter prefix is under home. M12: >30 credential dot-entries in home. M13: `cache/` is absent and the data root is ext4. |
| M14 | **PROC-row argv** (B3-R3). `--unshare-user --disable-userns --assert-userns-disabled --ro-bind / / --dev /dev --proc /proc` without `--unshare-pid` gives rc 0. The procfs is the host superblock (dev `0:25`): `/proc/locks` is 155 lines (host 157), and `/proc/1/comm` is `systemd`. For 3 host pids (including `breezy-trade` 529436), `/proc/<pid>/environ` and `/proc/<pid>/root` give **EACCES** and `status` is readable. The same holds with `--proc` omitted. |
| M15 | **Host `/run`.** It is a tmpfs holding 35 path sockets, among them `/run/docker.sock` (root:docker 0660), `/run/snapd.socket` and `/run/snapd-snap.socket` (0666), `/run/dbus/system_bus_socket`, `/run/lxd-installer.socket` and 18 systemd varlink sockets. **`/var/run` is a symlink to `/run`** (`readlink` gives `/run`). This user is in the `docker` and `lxd` groups. `/var/snap/lxd/common/lxd/unix.socket` is absent on this host. |
| M16 | **Control (r2 mount set: root bind plus `--tmpfs /run/user/1000`).** `connect` succeeds on `/var/run/docker.sock`, `/run/snapd.socket` and `/run/dbus/system_bus_socket`. This reproduces security F1. |
| M17 | **r3 set (`--tmpfs /run` after `--ro-bind / /`).** All 11 probed sockets give ENOENT, including `/var/run/docker.sock`, `/run/user/1000/bus` and `/run/user/1000/systemd/private`. There are 0 `S_ISSOCK` entries under `/run`, the `/run` listing is empty, and DNS fails (`gaierror -3`). |
| M18 | **DNS needs.** `/etc/resolv.conf` links to `/run/systemd/resolve/stub-resolv.conf`, and nsswitch has `hosts: files dns` (no nss-resolve). Re-binding that one file read-only is enough for `getaddrinfo` to resolve. `/run` then lists only `systemd`, and both `io.systemd.Resolve*` sockets stay ENOENT. |
| M19 | **`--remount-ro /run` after the re-binds.** Writes to `/run/x` and `/run/user/1000/x` give EROFS. DNS still resolves, and a datagram to a socket re-bound at `/run/user/1000/systemd/notify` is still delivered (the host received `READY=1`). |
| M20 | **Notify.** A real transient `Type=notify`, `NotifyAccess=all` unit ran the r3 set with `--unshare-user --unshare-pid` and the `$NOTIFY_SOCKET` ro re-bind. The result was "Started". One cosmetic line appears: `$MANAGERPID is set to an invalid PID`. |
| M21 | **User bus in the sandbox.** Under the r3 set, `systemctl --user show` fails with ENOENT. With only `/run/user/1000/systemd/private` re-bound, it fails "No data available" while `--unshare-pid` is set (also without `--unshare-user`). It succeeds only without `--unshare-pid`. A raw `AF_UNIX` connect succeeds either way. |
| M22 | **Escape.** In the M21 working shape, `systemd-run --user --collect /bin/true` returned rc 0 and created a transient unit **outside** the sandbox. |
| M23 | **Handoff.** In a real transient unit, an unwrapped `ExecStartPre` ran `systemctl --user show` into a file, and the wrapped `ExecStart` read it while its own `systemctl` failed. `$INVOCATION_ID` is identical in `ExecStartPre` and the wrapped `ExecStart`. |
| M24 | **Journal reads inside the r3 set.** `journalctl --user -u <unit>` works. A system-unit read of `systemd-logind` over 7 days returned 102 lines in the sandbox and 102 on the host: unmapped supplementary groups still count for DAC. |
| M25 | **Signal residual.** From the M14 shape (no `--unshare-pid`), `/bin/kill -TERM <host scratch pid>` returned rc 0 and the process died. With `--unshare-pid` the same call gets ESRCH. |
| M26 | **r3 PROC shape: `--unshare-pid` and no `--proc`** (host procfs through the recursive ro root bind). `getpid()` is 2 while `/proc/self` points to the host pid. `/proc/1/comm` is `systemd`. `/proc/locks` has 154 lines (host 154). The `breezy-trade` `status` (Name, VmRSS) is readable and its `environ` gives EACCES. `kill(host pid)` and `kill(node pid)` give **ESRCH**. Killing its own child works. `/proc` is mounted `ro`. |
| M27 | **Studies lock.** The studies take `$XDG_RUNTIME_DIR/breezy-studies.lock` (`/home/jon/breezy/deploy/systemd/replay-daily-run.sh:94-101`), and the user manager's `XDG_RUNTIME_DIR` is `/run/user/1000`. **Two distinct inodes exist:** `/run/user/1000/breezy-studies.lock` (69) and `/home/jon/.local/share/breezy/breezy-studies.lock` (3806292). A ro file re-bind at `/run/user/1000/breezy-studies.lock` under `--tmpfs /run` excludes in both directions: inside gets EAGAIN while the host holds it, and the host gets EWOULDBLOCK while inside holds it. |
| M28 | **AUT-2 credentials.** `/home/jon/.config/breezy/polymarket.env` defines `POLYMARKET_US_SECRET_KEY_FILE`, and its value lies under `/home/jon/.config/breezy/` (names only were read). `_read_secret_key_file` (`src/breezy/adapters/polymarket_us/env.py:175-216`) opens that path and requires mode 0600 (`:87`). `LoadCredential=` in a user unit gives `$CREDENTIALS_DIRECTORY=/run/user/1000/credentials/<unit>` (directory 0500, file **0400**). It can be re-bound read-only, is readable inside, and writes get EROFS. |
| M29 | **Phase-1 shape (`bwrap --unshare-net --dev-bind / /`).** It reaches the user bus (`systemctl --user show` rc 0) and nested bwrap is denied (M1 again). A bwrap started from inside it through `systemd-run --user` runs (rc 0), because its parent is the user manager. |
| M30 | **systemd 259 exit semantics.** An exit listed in `SuccessExitStatus=75` still runs `ExecStartPost`. `ExecCondition` exits 1 and 78 both skip `ExecStart`, so a 78 there would look like a skip. |
| M31 | **pytest 9.1.1.** A `-p` plugin's `pytest_load_initial_conftests` runs before any initial conftest is imported (witness absent). `SystemExit(2)` there exits rc 2; `pytest.exit` gives rc 1 plus a traceback. A tryfirst `pytest_ignore_collect` returning True for non-ancestor directories and non-registry files keeps both their conftest and their module unimported. |
| M32 | **Abstract sockets in the shared netns.** There are 3 listeners: `@ISCSIADM_ABSTRACT_NAMESPACE`, `@/org/kernel/linux/storage/multipathd` and one anonymous hex name. `/dev/shm` under `--dev /dev` is private and empty. |

**Gate surface** (verified at HEAD; the r2 citations are re-checked)
- **Gate script.** `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh:36-43` (`exec bwrap`, l.37) and `:50-52` (`exec unshare`, l.51). Dispatch is two independent `if` blocks at `:54-62`, then an unconditional `exit 3` at `:64-70`.
- **Root conftest** (`/home/jon/breezy/tests/conftest.py`):
  - `pytest_configure` `:247` (pyo3 block `:275`, Nautilus pin `:280`);
  - N2 rule `:292-326`; session evaluation `:329-356`; `pytest_sessionstart` `:359`; abort `:370`;
  - `pytest_collection_modifyitems` `:411`; `_is_real_network_test` `:461`.
- **Firewall pins.** N2/N3/N5/X1 pins as r2 (`tests/unit/test_execution_egress_firewall_guard.py:458-1498`). No test pins `exec`.
- **Lanes.** `/home/jon/breezy/scripts/ci/run_t1_lanes.sh:20-26` derives the partition proof from `--collect-only`, and `:64-65` runs lanes **concurrently** (`&`).
- **Supervisor lock probes.** `ports.intent_lock_free` is called at exactly 3 sites in `src/breezy/runtime/trade_supervisor.py`:
  - `:1186`, STOP_PRIOR's post-SIGTERM poll (20 attempts);
  - `:1225`, `_do_launch`;
  - `:1593`, the boot-retry precheck (`TRADE_SUPERVISOR_MIDDAY_WATCH`).
  - The schedule constants are `STOP_PRIOR_UTC` 16:40 and `LAUNCH_UTC` 16:50 (`trade_supervisor_core.py:37-38`); phase dispatch is at `:1102-1126`.

---

## §R3 Disposition

| Finding (r2 review / ruling) | Verdict | Where |
|---|---|---|
| **Sec F1 / B3-R1 (HIGH): root-equivalent sockets in `/run` and `/var/run`** | **FIXED and measured.** Every row gets `--tmpfs /run` right after `--ro-bind / /` (M17; the M16 control shows the r2 exposure). The ro re-binds are an exact set derived per row: the resolv target file (DNS rows, M18), `NOTIFY_SOCKET`, the studies lock and the credentials dir. `--remount-ro /run` follows (M19). The `/var/run` symlink is verified (M15). New self-probe negatives: docker, snapd, lxd, system-bus and user-bus connects must give ENOENT, a `/run` walk finds no `S_ISSOCK` outside the allowlist (`host_socket_visible`), and `/run` is EROFS (`run_not_readonly`). Phase-2 test and V15 added; README and E-7e(c) updated. | AC-1.3, AC-2, V15 |
| **Arch F1 / B3-R2 (HIGH): user-bus consumers** | **FIXED: no bus in any sandbox.** The `--bus-snapshot` handoff (AC-9) is measured (M23). `E7A_R2_USER_BUS` is **rejected on evidence**: it works only without `--unshare-pid` (M21), which reopens host-pid signalling (M25), and it allows `systemd-run` escapes (M22). journalctl stays in-sandbox (M24). The per-consumer choices are listed in E-7e(f). The drill's state-changing argvs use `--bus-action` (AC-9.4), which needs the r3 security ruling. | AC-9, E-7e(f)(h) |
| **Arch F2 / B3-R3 (HIGH): PROC-row argv unmeasured** | **MEASURED and redesigned.** The r2 shape mounts (M14), but it can SIGTERM any same-uid host process, including the trade node (M25). The r3 PROC shape keeps `--unshare-pid` and omits `--proc /proc`, so the host procfs arrives read-only through the root bind (M26). Locks and pid status are readable; environ and root give EACCES; host kill gives ESRCH. **This amends E-7a rule 2** ("drop `--unshare-pid`"), and E-7a rule 5's `/proc/<pid>` residual narrows. Tests: `test_argv_proc_rows_omit_proc_mount_keep_unshare_pid`, `test_bwrap_proc_row_reads_host_proc_locks_and_pid_status`, `test_bwrap_proc_row_host_pid_environ_root_eacces_kill_esrch`. | AC-1.3, E-7e(c) |
| **Sec C-1 / F2 / B3-R4: admission ran after import** | **FIXED and measured (M31).** Condition 6 checks args and options in `pytest_load_initial_conftests` before any conftest is imported, and exits with `SystemExit(2)`. Condition 7 adds `pytest_ignore_collect` (tryfirst) over non-ancestor dirs and non-registry files. The plugin must have been loaded with `-p`. `modifyitems` stays as a backstop. Test `test_p2_args_outside_registry_abort_before_import` uses witness module and witness conftest fixtures. | Gate, E-7d R4 |
| **Sec F3 / Arch F4 / B3-R5: script dispatch** | **FIXED.** Phase 1 is one `if bwrap / elif unshare / else exit 3` chain, tested to run exactly once. Collect-only is an exact-token hint (`--collect-only`, `--co`, `--collectonly`) that pytest's own parse confirms: the claim env var is checked in phase 1's `pytest_configure`, and a mismatch gives rc 2. `-k --co` is tested. Unshare-only hosts: phase 1 runs, then phase 2 refuses with rc 3, so the gate is red there (stated in E-7d R1). | Gate, E-7d R1 |
| **Sec C-2 / F5 / B3-R6: phase-2 import lint** | **FIXED.** `test_bwrap_host_files_import_policy` applies a deny-list over the registry files plus every `tests.support` module they import transitively. `subprocess` is allowed only in `tests/support/bwrap_harness.py`, whose argv[0] must be `BWRAP_PATH` with `--unshare-net`. Positive controls are included. The file-path-loading residual is stated. | Tests, E-7d R5 |
| **Sec F4 / B3-R7: supervisor `intent_lock_is_free`** | **FIXED.** AC-3.2 states the 16:45–16:48 behaviour, including the measured interplay: a STOP_PRIOR started while the hold is up sees the engine pid as holder and gives `REFUSE_ALERT` (`trade_supervisor_core.decide_stop_prior_action`). That is one false CRITICAL with no SIGTERM and no launch effect. Mitigation: an AUT-5 precondition (E-7e(f)). Three tests. | AC-3.2 |
| **Arch F8 / B3-R8: B2a not green at its own sha** | **FIXED.** B2a ships `tests/integration/test_bwrap_host_phase_witness.py` as the registry's only member, with the count = its tests. B2b, B2c and B3 only widen. E-7d is filed **before** B2a merges. | WPs |
| **Arch F3/F5/F7/F9 / B3-R9: E-7e(f) incomplete** | **FIXED by a full L-46 search.** Every plan was searched for real-bwrap tests, systemctl/journalctl, config re-binds and home paths; each break carries plan:line. New items found: the AUT-6 studies-lock inode (M27); the AUT-2 credential *file* (M28); the AUT-4 fixture root outside the data root; AUT-3 `NotifyAccess=main`; the AUT-6 loopback receiver vs `--unshare-net`; AUT-1 V-9(b) refuted (M21); AUT-5 deadman stage-S. | §Consumer Surface, E-7e(f) |
| **Arch F6 / B3-R10: live-listing negatives** | **FIXED.** Dropped. AUT-6's precondition ("directory owned by this uid") is kept (AUT-6 r15 l.260). | AC-2 |
| B3-R10: `XDG_CACHE_HOME` | **FIXED.** `--setenv XDG_CACHE_HOME /tmp/.cache` on every row. | AC-1.3 |
| Arch F11 / B3-R10: basetemp litter | **FIXED.** `mktemp -d "$GATE_DIR/phase2-bt.XXXXXX"` plus `trap` removal. It is unique per concurrent lane (`run_t1_lanes.sh:64-65`). | Gate |
| Sec F6 / B3-R10: the operator caps file is visible through the ro-bound repo; abstract sockets | **STATED.** R15 names neither a control nor a value, and nothing reads the file. Abstract listeners are measured (M32) and residual, because the network namespace is shared by E-7 rule 2. | R15 |
| Sec F7 / B3-R10: mutation-pin `BWRAP_HOST_EXPECTED_TESTS` | **FIXED.** L-33 mutation: literal +1 must turn `test_bwrap_host_expected_tests_equals_collected_count` red, for every WP that widens the registry. | WPs |
| Sec focus 1: env var present but not `"1"` | **STATED and tested.** Any set value other than exactly `"1"` gives rc 2. This differs from today only when the variable is set. `test_p2_admission_env_present_but_not_exact_one_aborts` includes attested + `"true"`. | E-7d R4 |
| Sec focus 5: `degraded_write_target` is caller-invoked | **STATED** in AC-1.5. Enforcement is the consumers' closure tests. | AC-1.5 |
| Arch F10: XDG cache | See B3-R10 above. | — |
| Arch F12 / B3-R10: hygiene | **FIXED.** No preamble; every path is a literal absolute path. | — |
| Arch E-7d "Supersedes" | **FIXED.** It names B-R1's `-m bwrap_host tests/` wording and AUT-5 r7 l.287. | E-7d |
| **S-1 (self, L-47): r2's AUT-5 "l.275 `-p` fallback" premise was wrong** | **WITHDRAWN.** AUT-5 r7 l.273-275 is a transient *timer* that triggers the installed `breezy-autonomy-engine@bootstrap.service`, so its cgroup leaf already matches. No `--unit=` change is needed. | E-7e(f) |
| S-2 (self): AUT-6 daily locks the wrong studies-lock inode | **FLAGGED (M27).** Fixed with the `E7_STUDIES_LOCK` re-bind plus a path change. | E-7e(f) AUT-6 |
| S-3 (self): AUT-2 reconcile cannot authenticate under the wrapper (R8 resolved) | **FLAGGED (M28).** Fix: `LoadCredential=` plus a ro re-bind of `$CREDENTIALS_DIRECTORY` (`E7A_R2_RECONCILE`); r3 security rules on it. | E-7e(f) AUT-2 |
| S-4 (self): AUT-4 fixture row binds outside the data root | **FIXED in the schema.** New `E7_FIXTURE_ROOT` with an exact `ALTERNATE_BIND_BASES`. | AC-1.2 |

## §R2 Disposition (carried, condensed)

| r1 finding | r2 outcome (unchanged in r3 unless noted) |
|---|---|
| B-R1 / Sec-1 / Arch-1: phase 2 aborts at N2 | One script, two phases; blocker; exact N2 admission (**r3: 7 conditions**); session-end `sys.modules`; `--unshare-net` children |
| Sec-1 alternative (stdlib runner) | Rejected: it would re-implement pytest |
| Arch-2: marker in a subdir conftest | `tests/support/bwrap_host_phase.py` via root `pytest_plugins`; exact file registry |
| B-R3 / Arch-3: shared denylist | Dropped; `SHARED_WRITE_SITES` plus `cache_dir_is_own_module_constant` |
| B-R4 / Sec-2 / Arch-4: probe names in `state/` | `O_TMPFILE`, exactly EROFS; env-row check first (**r3: owner precondition, no live listing**) |
| B-R5 / Sec-3 / Sec-5 / Arch-8/13: bind and config TOCTOU | Nofollow walk; dev/ino checks; `--bind-fd`/`--ro-bind-fd`; `E7_CONFIG_DIR` |
| B-R6 / Sec-4: credentials, bus, nested userns | Home tmpfs plus exact re-binds; userns disabled on every row (**r3: `--tmpfs /run` replaces `--tmpfs /run/user/<uid>`**) |
| B-R8: placement and contract | `runtime/autonomy_sandbox/`; forbidden contract; fresh-subprocess import test |
| Sec-6 / Arch-12: torn read, copy order | Quiescence, header/salt/tail digests, db → `-wal` → `-journal`, cache flock |
| Sec-7: flock vs node boot | Node fails fast; deadline before 16:50 (**r3 adds the supervisor side**) |
| Sec-8: cgroup is not a boundary | "Misconfiguration integrity, not authorisation"; exact parse → 78 |
| Sec-9/10 / Arch-5: notifier fallback | Exact `NOTIFIER_FALLBACK_ROWS` (empty); after validation only; 2 s preflight; forged degraded is unset and raises |
| Sec-11: fstat | Nofollow walk, `fstat`, `dir_fd` copies |
| Sec-12 / Arch-11: V11 hashes 4 lines | `WRAPPER_CODE_FILES` manifest |
| Arch-6: lint scope | Exact set plus tripwire (**r3: wrapper-naming-only units lint their wrapper lines only**) |
| Arch-7: transient unit | 78 kept (**r3: the AUT-5 consequence is withdrawn, S-1**) |
| Arch-9 / Arch-10 / Arch-14 / Arch-15 / Arch-16 / Arch-17 | G6 → `exec_snapshot(False)`; E-13 tests at AUT-4's paths; `--unshare-net` is the only extra flag; filing note in the commit message; `E7A_R2_PROC`; V6/V7 use `O_TMPFILE` |

---

## Acceptance Criteria

**AC-1: shared wrapper (E-7a rule 1, E-7c, E-13 ER-1, E-7e(c))**
1. **Invocation.** `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap ROW CMD [ARGS…]` (or `--bus-snapshot ROW`, or `--bus-action ROW NAME`, AC-9).
   - `ROW` must fullmatch `^breezy-[a-z0-9-]+(@[a-z0-9-]*)?([.#][a-z0-9-]+)?$`, else exit 64.
   - An unknown row gives 78.
   - The unit check reads `/proc/self/cgroup`. It requires exactly one line `0::<path>` whose leaf ends `.service` and equals a `units` entry, or matches `name@<instance>.service` for a `name@` entry. Anything else gives 78.
   - README and docstring: "integrity against misconfiguration, not an authorisation boundary."
2. **Bind integrity** (r2 AC-1.2, kept).
   - Binds are base-relative. The base is `SandboxRoots.data_root`, or for `E7_FIXTURE_ROOT` rows exactly `ALTERNATE_BIND_BASES[row.bind_base]` (seam B ships `{"aut4_fixture": ".local/share/breezy-autonomy-fixture"}`, home-relative).
   - Each bind is opened by a per-component `O_PATH|O_DIRECTORY|O_NOFOLLOW` walk from `/`.
   - Its dev/ino must differ from `state/`, from every ancestor of `state/` and from the data root. It must be on the base's device and must not nest within the row. It is passed with `--bind-fd`.
   - Config files and `E7_CONFIG_DIR` keep the r2 checks and `--ro-bind-fd`.
   - Any violation gives 78; bind sources are never created by the wrapper.
3. **Argv** (a list to `os.execv("/usr/bin/bwrap", argv)`, no shell), in this order:
   1. `--unshare-user --disable-userns --assert-userns-disabled --unshare-pid`. **Every** row unshares pid (M25, M26).
   2. `--ro-bind / /`
   3. `--tmpfs /run` (M17)
   4. `--dev /dev`, then `--proc /proc`. `--proc` is omitted **only** on `host_proc` rows (`E7A_R2_PROC`); the host procfs arrives read-only through step 2 (M26).
   5. `--size N --tmpfs /tmp`
   6. `--tmpfs <home>`, then `--ro-bind` each `HOME_REBINDS` entry: the repo root; the interpreter prefix if under home; the data root; the fixture base on `E7_FIXTURE_ROOT` rows.
   7. **`/run` re-binds**, the exact set `run_rebinds(row, roots, environ)`:
      - (a) `resolves_dns` rows: the target of `realpath("/etc/resolv.conf")`, if it lies under `/run/`. It must be a regular file, walked nofollow, passed with `--ro-bind-fd` (M18).
      - (b) `E7A_R2_NOTIFY` rows: `$NOTIFY_SOCKET`. It must be absolute, under `/run/user/<uid>/systemd/`, `lstat` `S_ISSOCK` and owned by uid; passed with `--ro-bind`.
      - (c) `E7_STUDIES_LOCK` rows: `/run/user/<uid>/breezy-studies.lock`. It must be a regular file owned by uid with `st_nlink == 1`; passed with `--ro-bind-fd` (M27).
      - (d) `E7A_R2_RECONCILE` rows: `$CREDENTIALS_DIRECTORY`. It must equal `/run/user/<uid>/credentials/<cgroup leaf>`, be mode 0500 and owned by uid, and contain exactly the row's `credential_names` as regular files of mode 0400; passed with `--ro-bind-fd` (M28).
      - A missing or malformed source on a row that needs it gives 78.
   8. `--remount-ro /run` (M19)
   9. `--ro-bind-fd` config files and dirs
   10. `--bind-fd` binds
   11. `--remount-ro <home>`
   12. `--new-session --die-with-parent`
   13. `--chdir`: cwd if inside the repo or the bind base, else `/`
   14. `--setenv TMPDIR /tmp --setenv XDG_CACHE_HOME /tmp/.cache --setenv BREEZY_AUTONOMY_BWRAP_ROW <row> --unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`
   15. `--`, then the command verbatim.
4. **`--size`** precedes `--tmpfs /tmp`. A malformed `tmpfs_size_bytes` fails closed before exec (E-13).
5. **Exit codes and fallback** (r2 AC-1.5, kept).
   - Exits 126 and 127 as r2.
   - Fallback applies only to rows in `NOTIFIER_FALLBACK_ROWS` (empty in seam B), after every 64/78 check, with a 2 s list-argv preflight.
   - `degraded_write_target` is a caller-invoked convention. Its enforcement is the consumers' alerts-only closure tests.
6. The wrapper file and every package module lie outside every bind.

**AC-2: self-probe (E-7 rule 2, B-R4, B3-R1, B3-R10; AUT-6 r15 l.260-263 vocabulary)**

`run_self_probe(row, *, roots=None, environ=os.environ)` runs these steps in order.
1. `environ["BREEZY_AUTONOMY_BWRAP_ROW"] == row`, else `env_row`. The probe returns before any open.
2. Degraded handling as r2: notifier rows return `ok=False, degraded=True`; any other row gets `degraded_forged`.
3. **Negatives** come only from the table (no live listing): `state/`, `registry/` if unbound, the data root, the repo root and every unbound ancestor of a bind.
   - Each target must pass an `os.stat` precondition: a directory **owned by euid** (AUT-6 r15 l.260).
   - Then `os.open(dir, O_TMPFILE|O_WRONLY, 0o600)` must raise exactly EROFS.
   - A failure is `negative` (`negative_registry` for `registry/`). EOPNOTSUPP falls back to `statvfs` plus mountinfo `ro`.
4. **Positives** per bind mode, as r2: `tmpfile` (default) or `subdir`; a failure is `positive_<bind>` or `probe_residue`.
5. **Credentials.** `~/.config/breezy`, `~/.ssh`, `~/.aws`, `~/.gnupg` and `~/.netrc` must give ENOENT. The home listing must be ⊆ the first components of the re-binds (∪ `.config` iff config binds). Otherwise `credentials_visible`.
6. **`/run`** (B3-R1):
   - connects to `/var/run/docker.sock`, `/run/docker.sock`, `/run/snapd.socket`, `/run/snapd-snap.socket`, `/var/snap/lxd/common/lxd/unix.socket`, `/run/lxd-installer.socket` and `/run/dbus/system_bus_socket` must each give ENOENT, else `host_socket_visible`;
   - `/run/user/<uid>/bus` and `/run/user/<uid>/systemd/private` must give ENOENT, else `user_bus_visible`;
   - a nofollow walk of `/run`: every entry must be a `run_rebinds` path or an ancestor directory of one; an extra socket is `host_socket_visible`, any other extra entry is `run_not_private`;
   - `O_TMPFILE` on `/run` must give EROFS, else `run_not_readonly`.
7. `/tmp` must be a tmpfs where `O_TMPFILE` succeeds, else `tmp_not_private`.
8. **pid namespace.** On a non-`host_proc` row, `/proc/1/comm == "bwrap"`. On a `host_proc` row, `int(os.readlink("/proc/self")) != os.getpid()`. Otherwise `pid_ns`.
- **Interface.** `require_sandbox(row)` raises `SandboxIntegrityError(code)`. Codes carry no path. The caller prints `<UNIT> INTEGRITY bwrap_probe_failed direction=<code>`, delivers a CRITICAL and exits 3. No probe ever creates a directory entry under `state/`, the data root, the repo, `registry/demand/` or `derived/verdicts/`.

**AC-3: WAL snapshot helper (E-8 as amended by E-7e(b), E-8a, E-7a rule 3).** The API, the copy, the recovery and the exact `SnapshotFailureReason` set are as r2 AC-3.1–3.8. AC-3.2 now also says:
- **Supervisor interplay, 16:45–16:48 (B3-R7).** Only STOP_PRIOR can be due in that interval: its window is [16:40, 16:50) while not done (`trade_supervisor_core.py:1102-1103`).
  - **LAUNCH cannot run.** `LAUNCH_UTC` is 16:50 (`:38`), later than the 16:48:00 release deadline.
  - **Boot retry cannot run.** Its precheck (`trade_supervisor.py:1582-1607`) runs only inside the midday-watch phase, which opens after SELF_CHECK (`:1118-1128` of the core).
  - **(i) Poll already running.** If STOP_PRIOR's post-SIGTERM poll (`trade_supervisor.py:1185-1188`) runs during the hold, `intent_lock_is_free` reads "not free" and the poll only continues within its 20 bounded attempts. There is no signal, no launch and no retire.
  - **(ii) STOP_PRIOR starting during the hold** (possible only if the supervisor restarts inside the window). With the node already down, `resolve_intent_lock_holder` returns the engine's host pid and `decide_stop_prior_action(None, holder)` gives `REFUSE_ALERT`. Result: one false CRITICAL `TRADE_SUPERVISOR_STOP_PRIOR_REFUSED`, no SIGTERM. The 16:50 launch is unaffected, because the hold is released by 16:48:00.
  - **Mitigation (AUT-5 build item, E-7e(f)).** `take_flock=True` runs only after the day's supervisor STOP_PRIOR decision line exists.
  - **Stated residual.** A supervisor restart inside [16:45, 16:48).
  - The hold stays ≤ fingerprint + copy + re-fingerprint (≤ 1 s measured in r1).

**AC-4: shared write sites (B-R3).** `SHARED_WRITE_SITES` holds the exact sites of `wal_snapshot`, `self_probe` and `bus_handoff` (snapshot writer, snapshot unlink, request write, request unlink). The equality scan and `cache_dir_is_own_module_constant` are as r2.

**AC-5: unit-file lint (E-7a rule 1, Arch-6, Arch F5)**
- **Scope.** (⋃ `row.units` ∪ `AUTONOMY_OWNED_UNITS`) plus every unit file that names the wrapper. Files are `*.service`, `*.timer` and `*.d/*.conf`. The tripwire and the owned-units-have-files checks are kept.
- **Units in scope only because they name the wrapper** (not owned, not a row unit; for example the recorder `breezy-quote-tape.service`): only their wrapper-naming lines are linted. Each such line must be `timeout -k` → wrapper → a row whose `units` lists that unit. There is a recorder-shaped positive-control fixture.
- **Owned and row units:**
  - every `ExecStart=`/`ExecStopPost=` goes `timeout -k` → (`flock -w`) → wrapper → row → command;
  - no `+` or `!` prefix;
  - every `OnFailure=` target is in scope and wrapped;
  - `E7A_R2_NOTIFY` row units carry `NotifyAccess=all`;
  - `ExecStartPre=` is only a bounded `install -d`/`chmod`, or `timeout -k` → wrapper `--bus-snapshot <row>` (or `--bus-action <row> <name>` for an `unconditional` action);
  - `ExecStartPost=` is only `timeout -k` → wrapper `--bus-action <row> <name>`;
  - `E7A_R2_RECONCILE` units carry exactly one `LoadCredential=` per `credential_names` entry.

**AC-6: C4.1 ruling.** As r2: a byte-identical slice of `ARCH_rev9_2.md` lines 379–392, sha-pinned, with no filing note.

**AC-7: gate (E-7d).**
- Phase 1, then phase 2, exactly once each. The summary line is `[breezy] gate: phase1 rc=X phase2 rc=Y`, and the gate exits with the first non-zero.
- Phase 2 is omitted only on a pytest-confirmed collect-only run.
- Phase 2 passes exactly `BWRAP_HOST_EXPECTED_TESTS` with 0 skipped.
- `lint-imports` reports "N kept, 0 broken" (console script, from the tree).

**AC-8: real host.** V0–V19 pass on the primary tree after each WP's merge, before any consumer row is filed.

**AC-9: bus handoff (B3-R2; new)**
1. **Rows.** `bus_reads: tuple[BusRead, ...]` with `BusRead(name, argv)`.
   - `argv[0] == "/usr/bin/systemctl"`, `argv[1] == "--user"`, and `argv[2] ∈ {"show", "list-units", "list-timers"}`.
   - Every further token is one of: `-p`, `--property=<A-Za-z,>`, `--all`, `--plain`, `--no-legend`, `--no-pager`, `--failed`, `--state=<a-z>`, `--type=<a-z>`, `--value`, a unit name or glob fullmatching `^breezy-[a-z0-9@.*_-]+$`, or the literal `{instance}`.
   - `bus_snapshot_bind` must be one of `binds`, and is required iff `bus_reads` is non-empty.
   - journalctl is **not** a bus read; it runs in-sandbox (M24).
2. **`--bus-snapshot ROW`** runs unsandboxed in `ExecStartPre`.
   - Checks 64/78 as AC-1, including the cgroup match; the row must have `bus_reads`; `INVOCATION_ID` must be present and match `^[0-9a-f]{32}$`.
   - `{instance}` is substituted from the validated cgroup leaf.
   - Each read runs through `subprocess.run(list, timeout=BUS_READ_TIMEOUT_S=10, env=BUS_ENV)`, where `BUS_ENV = {PATH:/usr/bin:/bin, XDG_RUNTIME_DIR:/run/user/<uid>, LANG:C.UTF-8, SYSTEMD_PAGER:"", SYSTEMD_COLORS:"0"}`. stdout is capped at 4 MiB.
   - Output is JSON `bus_snapshot/v1 {invocation_id, unit, ts_ns, reads:[{name, argv, rc, timed_out, stdout}]}`. It is written via the validated bind fd into `.bus_snapshot/<INVOCATION_ID>.json` (`O_CREAT|O_EXCL|O_NOFOLLOW`, 0600, fsync), after sweeping entries older than 24 h under a flock of that directory.
   - A failed **read** is recorded (rc/timed_out) and the mode exits 0, so the consumer keeps its own UNKNOWN semantics (AUT-6 r15 l.488, l.957). Config errors give 64/78; a write failure gives 73.
3. **`read_bus_snapshot(row, *, environ)`** (in-sandbox). It does a single-read nofollow open, requires `invocation_id == environ["INVOCATION_ID"]` and the unit to match, returns `BusSnapshot`, then unlinks the file. A missing or mismatched file raises `BusSnapshotError("bus_snapshot_missing" | "bus_snapshot_stale")`.
4. **`--bus-action ROW NAME`** (`E7A_R2_BUS_ACTION`; ships unused).
   - `BusAction(name, argv, gate)` requires argv exactly `("/usr/bin/systemctl", "--user", "kill", "--signal=SIGSTOP" | "--signal=SIGCONT", <unit>)`, with `<unit>` ∈ `BUS_ACTION_TARGET_UNITS`. That set is exact and **empty** in seam B.
   - `gate="request"` fires only if the sandboxed step wrote `.bus_action/<INVOCATION_ID>.<name>.request` through `request_bus_action(row, name)` in the same invocation. `gate="unconditional"` always fires.
   - The request is consumed by unlink. There is never a start, stop, restart or `systemd-run`.
   - It lands in WP-B2c but stays unusable until the r3 security review accepts E-7e(h); otherwise it is deleted before merge.

## Edge Cases and NFRs

| Case | Handling |
|---|---|
| Node up and holding the intent flock | `take_flock=True` gives `LOCK_HELD` after 3 tries; `False` gives an advisory result. |
| Helper holding while the node boots, or a supervisor probe | Node fails fast (r2 test). Supervisor per AC-3.2 (three tests). |
| Torn WAL, a lock-ignoring writer, two cache users | As r2: digests, quiescence, `FINGERPRINT_UNSTABLE`, `CACHE_BUSY`. |
| Docker, snapd, lxd, system-bus sockets | Hidden by `--tmpfs /run` (M17). `/var/run` resolves into the tmpfs (M15, M17). |
| Row needs DNS (alert webhook, AUT-2 GET) | `resolves_dns=True` re-binds only the resolv target file (M18). `resolves_dns` is a required field with no default, so every row states it. |
| Host where `/etc/resolv.conf` is not under `/run` | No re-bind is needed; `--ro-bind / /` covers it. |
| `Type=notify` row | `NOTIFY_SOCKET` ro re-bind (M19, M20). The lint requires `NotifyAccess=all`. |
| `/proc/locks`, `/proc/<pid>` reader | `host_proc` row (M26). Host pids are readable, environ and root give EACCES, signals give ESRCH. |
| Bus read (`systemctl --user show`/`list-*`) | `--bus-snapshot` in `ExecStartPre` (M23). In-sandbox systemctl fails (M21), and the self-probe proves the bus is absent. |
| Snapshot from an earlier invocation left behind | `INVOCATION_ID` mismatch raises `bus_snapshot_stale`. A 24 h sweep runs under the directory flock. |
| Drill SIGSTOP/SIGCONT | `--bus-action` (`ExecStartPost` request-gated, or `ExecStartPre` unconditional). M30 shows `SuccessExitStatus` and `ExecCondition` cannot gate safely. |
| In-sandbox studies lock (AUT-3, AUT-6) | `E7_STUDIES_LOCK` re-binds the real inode (M27). Holders that use `flock -w` outside the wrapper are unaffected. |
| Credential *file* consumer (AUT-2) | `E7A_R2_RECONCILE`: `LoadCredential=` copy plus a ro re-bind of `$CREDENTIALS_DIRECTORY` (M28). `~/.config/breezy` itself stays hidden. |
| Writes to the XDG cache | `/tmp/.cache` (private tmpfs). |
| Phase-1 test that starts a user unit | Allowed (M29). That unit runs outside the gate's netns (R24). |
| Phase 2 run by hand without `-p` | Condition 6's early witness is absent, so rc 2. |
| Shell-leaked `BREEZY_BWRAP_HOST_PHASE` in phase 1 | The script unsets it. If it is set by hand (any value) together with the attestation, rc 2. |

**NFRs**
- Wrapper overhead p95 ≤ 50 ms (V9); fallback is shebang `-IS`.
- `--bus-snapshot` ≤ 30 s (`timeout -k 2 30`), counted under E-9 by each consumer.
- The package is stdlib-only.
- A snapshot of today's store takes ≤ 1 s.
- Phase 2 takes ≤ 120 s per lane.
- No absolute path appears in stderr or in reason codes.

## Architecture and Data Flow

**Placement (B-R8).** `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/`, for the seam-A Q5 reasons:
- writing the copy inside `persistence/` would need a write-scan exception;
- every caller sits at runtime or above;
- the table is deploy configuration;
- `runtime/__init__.py` is import-free.

The import-linter contract is `"ARCH-0 seam B: the autonomy sandbox package is stdlib-only"`, forbidding `nautilus_trader`, `breezy.adapters` and `breezy.strategy` with `allow_indirect_imports=false`. Seam B has no seam-A dependency.

**Modules and API** (signatures; bodies follow the ACs)
```python
# table.py
KNOWN_EXCEPTIONS: Final = frozenset({"E7A_R2_PROC","E7A_R2_NOTIFY","E7A_R2_RECONCILE","E7A_R2_BUS_ACTION",
    "E7B_EVAL_OFFLINE_ADAPTER_MODULES","E7_CONFIG_DIR","E7_STUDIES_LOCK","E7_FIXTURE_ROOT"})
ALTERNATE_BIND_BASES: Final[Mapping[str, str]] = MappingProxyType({"aut4_fixture": ".local/share/breezy-autonomy-fixture"})
NOTIFIER_FALLBACK_ROWS: Final[frozenset[str]] = frozenset();  AUTONOMY_OWNED_UNITS: Final[frozenset[str]] = frozenset()
BUS_ACTION_TARGET_UNITS: Final[frozenset[str]] = frozenset()
@dataclass(frozen=True, slots=True) class BusRead: name: str; argv: tuple[str, ...]
@dataclass(frozen=True, slots=True) class BusAction: name: str; argv: tuple[str, ...]; gate: Literal["request","unconditional"]
@dataclass(frozen=True, slots=True)
class SandboxRoots:   # production(): pwd home, repo = package parents[4], sys.base_prefix, uid, run_user=/run/user/<uid>
    home: Path; data_root: Path; repo_root: Path; python_prefix: Path; uid: int; run_user: Path
    def home_rebinds(self, row: "BwrapRow") -> tuple[Path, ...]
@dataclass(frozen=True, slots=True)
class BwrapRow:
    name: str; owner_plan: str; units: frozenset[str]; binds: tuple[str, ...]; entry_modules: tuple[str, ...]
    resolves_dns: bool                                   # required, no default (B3-R1 row-by-row)
    bind_base: str = "data_root"; host_proc: bool = False; studies_lock: bool = False
    credential_names: tuple[str, ...] = (); config_ro_binds: tuple[str, ...] = (); config_ro_dirs: tuple[str, ...] = ()
    bus_reads: tuple[BusRead, ...] = (); bus_snapshot_bind: str | None = None; bus_actions: tuple[BusAction, ...] = ()
    tmpfs_size_bytes: int | None = None; exceptions: frozenset[str] = frozenset(); notifier_fallback: bool = False
    positive_probe: Mapping[str, PositiveProbe] = MappingProxyType({})
def validate_table(table=AUTONOMY_BWRAP_TABLE) -> None
def self_probe_plan(row, roots) -> SelfProbePlan
# binds.py: open_validated_binds(row, roots) -> ctx[OpenedBinds]; walk_nofollow(path, *, kind)
# run_mounts.py: run_rebinds(row, roots, environ) -> tuple[RunRebind, ...]; RUN_ALLOWLIST derivation for the probe
# bwrap.py: build_bwrap_argv(row, command, *, roots, opened, environ, cwd, extra_namespace_flags=()) -> list[str]
#           current_unit_name(cgroup_text) -> str | None
#           main(argv, *, roots=None, cgroup_path=..., bwrap_path=BWRAP_PATH, execv=os.execv, run=subprocess.run) -> int
# self_probe.py: run_self_probe / require_sandbox / degraded_write_target (AC-2)
# bus_handoff.py: write_bus_snapshot(row, *, roots, environ, unit, run) -> int; read_bus_snapshot(row, *, environ, roots=None) -> BusSnapshot
#                 request_bus_action(row, name, *, environ, roots=None) -> None; fire_bus_action(row, name, *, roots, environ, unit, run) -> int
# wal_snapshot.py: wal_snapshot / exec_snapshot / connect_snapshot_readonly (AC-3)
# write_sites.py: SHARED_WRITE_SITES; WRAPPER_CODE_FILES
# selftest_cli.py: python -I -m breezy.runtime.autonomy_sandbox.selftest_cli [--exec-snapshot N] [--bus-snapshot] [--proc-checks]
```

**`validate_table` rules (exact sets; widened only per L-12)**
- **r2 rules are kept,** except that `unshare_pid` is replaced by `host_proc`.
- **Each exception flag matches exactly one label:**
  - `host_proc` ⇔ `E7A_R2_PROC`;
  - `studies_lock` ⇔ `E7_STUDIES_LOCK`;
  - `credential_names` non-empty ⇔ `E7A_R2_RECONCILE`;
  - `bus_actions` non-empty ⇔ `E7A_R2_BUS_ACTION`;
  - `bind_base != "data_root"` ⇔ `E7_FIXTURE_ROOT`, with `bind_base ∈ ALTERNATE_BIND_BASES`.
- **Bus reads and actions:**
  - every `BusRead` and `BusAction` matches AC-9;
  - names are unique within a row;
  - `bus_snapshot_bind ∈ binds`.
- **There is no user-bus label.**

**Seam B rows** (transient `systemd-run --unit=<name>`, no unit files)

| Row | Unit | Binds | Flags |
|---|---|---|---|
| `breezy-autonomy-selftest` | `breezy-autonomy-selftest.service` | `cache/autonomy_selftest` | `resolves_dns=True`; `bus_reads=(BusRead("self_show", ("/usr/bin/systemctl","--user","show","-p","Id,ActiveState","breezy-autonomy-selftest.service")),)`; `bus_snapshot_bind="cache/autonomy_selftest"` |
| `breezy-autonomy-selftest-notify` | `breezy-autonomy-selftest-notify.service` | `cache/autonomy_selftest` | `E7A_R2_NOTIFY`, `resolves_dns=False` |
| `breezy-autonomy-selftest-proc` | `breezy-autonomy-selftest-proc.service` | `cache/autonomy_selftest` | `E7A_R2_PROC` and `E7_STUDIES_LOCK`, `host_proc=True`, `studies_lock=True`, `resolves_dns=False` |

**Data flow (wrapped unit)**
1. `ExecStartPre=/usr/bin/timeout -k 2 30 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap --bus-snapshot <row>` (only if the row has bus reads).
2. `ExecStart=/usr/bin/timeout -k … [flock -w …] /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap <row> <cmd…>`.
3. The shebang `/home/jon/breezy/.venv/bin/python3 -I` calls `bwrap.main`.
4. Checks run in this order:
   1. ROW syntax (64);
   2. `validate_table` (78);
   3. row lookup (78);
   4. cgroup match (78);
   5. `open_validated_binds` (78);
   6. `run_rebinds` (78);
   7. command present and executable (127/126);
   8. bwrap present;
   9. notifier preflight;
   10. `execv`.
5. Inside, the entry point calls `require_sandbox(row)` first, then optionally `read_bus_snapshot(row)`, then optionally `request_bus_action`.
6. Optional `ExecStartPost=… --bus-action <row> <name>`.

**Gate (E-7d; WP-B2a)**
- **`/home/jon/breezy/tests/support/bwrap_host_phase.py`** (stdlib + pytest).
  - Contents: `BWRAP_HOST_PHASE_ENV_VAR`, `COLLECT_ONLY_CLAIM_ENV_VAR = "BREEZY_GATE_COLLECT_ONLY_CLAIM"`, `BWRAP_HOST_TEST_FILES` (exact), `BWRAP_HOST_EXPECTED_TESTS` (exact literal), `Phase2ImportBlocker` (installed at import when the variable is exactly `"1"`), `phase2_admission(...)` (pure function), `module_name_for_path`.
  - `pytest_load_initial_conftests` (`-p` only): records the early witness, then runs the condition-6 checks before any conftest import; a refusal is `SystemExit(2)` with a `[breezy] phase-2 not admitted: <reason>` line (M31).
  - `pytest_ignore_collect(tryfirst)` in phase 2: True for any non-ancestor directory or non-registry file (M31).
  - `pytest_configure`: registers `bwrap_host`. In phase 1, if the claim is `"1"` and `config.option.collectonly` is false, it exits rc 2 ("collect-only claim mismatch").
  - `modifyitems(tryfirst)`: in phase 1 it skips `bwrap_host` items with a reason naming phase 2; in phase 2 it is the backstop (an unmarked item or one outside the registry exits rc 2).
  - `pytest_runtest_logreport` counts outcomes, and `pytest_sessionfinish` applies the verdict.
- **Admission** (all 7 must hold):
  1. the variable is exactly `"1"`;
  2. `BREEZY_TEST_OS_EGRESS_BLOCK` is absent;
  3. the blocker (exact class) is at `meta_path[0]`;
  4. every egress hit maps to a refused module;
  5. no refused module is loaded;
  6. the early witness is present, and the args and options were clean: every positional arg (realpath, inside the repo, `file` or `file::node`) is in the registry, and the options include no `--rootdir` ≠ the repo, no `--confcutdir`, `--noconftest`, `--pyargs`, `-c`/`--config-file` or non-default `--import-mode`, and no `-p` beyond {the plugin, `no:randomly`, `no:cacheprovider`};
  7. ignore-collect is active.
- **Root conftest, exactly C1–C4 (as r2):**
  - C1: `pytest_plugins`;
  - C2: skip the Nautilus pin when the phase is active;
  - C3: a keyword-only `bwrap_host_phase` on `execution_egress_abort_reason` whose `None` path is byte-identical;
  - C4: admission computed only when the variable is present.
- **Script** (`/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`):
  ```bash
  unset BREEZY_BWRAP_HOST_PHASE BREEZY_GATE_COLLECT_ONLY_CLAIM
  collect_only=0; for a in "$@"; do case "$a" in --collect-only|--co|--collectonly) collect_only=1;; esac; done
  export BREEZY_GATE_COLLECT_ONLY_CLAIM="$collect_only"; phase1_rc=0
  if bwrap_ok; then echo "[breezy] OS egress block: bubblewrap network namespace" >&2; run_bwrap "$@" || phase1_rc=$?
  elif unshare_ok; then echo "[breezy] OS egress block: unshare network namespace" >&2; run_unshare "$@" || phase1_rc=$?
  else refuse_message; exit 3; fi
  if [[ "$collect_only" == 1 ]]; then echo "[breezy] gate: phase1 rc=$phase1_rc phase2 omitted (collect-only)" >&2; exit "$phase1_rc"; fi
  phase2_rc=0; run_phase2 || phase2_rc=$?
  echo "[breezy] gate: phase1 rc=$phase1_rc phase2 rc=$phase2_rc" >&2
  [[ "$phase1_rc" -ne 0 ]] && exit "$phase1_rc"; exit "$phase2_rc"
  ```
  - `run_bwrap` and `run_unshare` lose `exec`.
  - `run_phase2`:
    1. refuse with 3 if the attestation is set, or bwrap is absent, or the precheck `bwrap --unshare-user --disable-userns --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc true` fails;
    2. load the registry through `"$PYTHON" -I -c`, refusing an empty one;
    3. `P2_BT=$(mktemp -d "${BREEZY_GATE_DIR:-$HOME/.cache/breezy-gate}/phase2-bt.XXXXXX")` with `trap 'rm -rf -- "$P2_BT"' EXIT`;
    4. run `env -u BREEZY_TEST_OS_EGRESS_BLOCK -u BREEZY_GATE_COLLECT_ONLY_CLAIM BREEZY_BWRAP_HOST_PHASE=1 "$PYTHON" -m pytest -p tests.support.bwrap_host_phase -p no:randomly -p no:cacheprovider -m bwrap_host --basetemp="$P2_BT" "${files[@]}"`.
  - User args are never forwarded to phase 2. The N5 pin text is kept.
- **Harness** (`/home/jon/breezy/tests/support/bwrap_harness.py`).
  - `run_raw_true()` arrives in B2a.
  - `run_in_row(row, command, *, roots, timeout_s=30)` and `make_roots(tmp_path)` arrive in B2b, with test-only source substitutes for the run re-binds (`roots.run_user` → a scratch directory).
  - Every child gets `--unshare-net` and an explicit environment.

## Consumer Surface (the source for E-7e(f); L-46 search: real-bwrap tests, systemctl/journalctl, config re-binds, home paths)

| Plan:line | Today | Change (binding build item) |
|---|---|---|
| AUT-1 r12 l.662, 710, 1112 | Stop-hook row `breezy-quote-tape.stop-hook` | Kept. AC-5 lints only its wrapper line. `resolves_dns=False`. |
| AUT-1 r12 l.768-769, 939 | Audit `journalctl --user` argvs | Run **in-sandbox** (M24); no change. |
| AUT-1 r12 l.770, 939 | Audit `systemctl --user show -p … breezy-quote-tape.service` | The audit row gets `bus_reads` plus `bus_snapshot_bind=evidence/capture/audit` and `ExecStartPre --bus-snapshot`. AC6 row: `read_bus_snapshot` replaces the argv. |
| AUT-1 r12 l.733, 741, 883-884, 941 | Drill and guard run SIGSTOP/SIGCONT argvs "plus the user-bus socket if V-9 requires it" | No socket bind (M21, M22). Drill: `E7A_R2_BUS_ACTION`, `ExecStartPost --bus-action <row> sigstop` (gate `request`), with the sandboxed step calling `request_bus_action` only after writing `evidence/capture/drill/<date>.json`. Guard: `ExecStartPre --bus-action <row> sigcont` (`unconditional`), then the wrapped check. `BUS_ACTION_TARGET_UNITS` widened to `{"breezy-quote-tape.service"}`. Needs the r3 security ruling; else the drill and guard run unwrapped as a stated E-7a rule-5 residual. |
| AUT-1 r12 l.1045 (V-9) | (b) assumes `systemctl --user` works across a ro bind | Refuted (M21). V-9(b) becomes the `--bus-snapshot` handoff (M23); (a) is covered by M20/V12. |
| AUT-1 r12 l.905-906 | `OnFailure=breezy-study-failed@`; `alerts.env` "re-bound … inside `--tmpfs ~/.config`" | Switch to `OnFailure=breezy-autonomy-failed@%n.service`. Drop the re-bind: `EnvironmentFile` is read by systemd, and `validate_table` refuses `breezy/` paths. |
| AUT-1 r12 l.881 | Audit `flock -w` on `breezy-studies.lock` | The lock path is `%t/breezy-studies.lock` (M27), outside the wrapper. |
| AUT-1 r12 l.1343 | Risk row "sd_notify blocked under bwrap" | Text updated: M20 shows it is delivered under the r3 set. |
| AUT-2 r7 l.180, 468 | Reconcile reads the key *file* under `~/.config/breezy` (M28) | `E7A_R2_RECONCILE` gets `LoadCredential=polymarket_us_secret_key:%h/.config/breezy/<keyfile>` and `credential_names=("polymarket_us_secret_key",)`. Inside, `POLYMARKET_US_SECRET_KEY_FILE` points to `$CREDENTIALS_DIRECTORY/polymarket_us_secret_key`; the caller passes `require_key_file_mode=0o400` (M28). `EnvironmentFile=` overrides `Environment=`, so the variable is set by a reconcile-only env file (verify-first). `resolves_dns=True`. Alternative: unwrapped, as a residual. r3 security rules. |
| AUT-2 r7 l.468 | `OnFailure=breezy-aut2-recon-failed@` | Joins `NOTIFIER_FALLBACK_ROWS` with an alerts-only closure test. |
| AUT-2 r7 l.467 | Label `flock -w` on the studies lock | `%t/breezy-studies.lock`. |
| AUT-2 r7 (E-8 "G6 URI") | Wrapped G6 reads | `exec_snapshot(take_flock=False)`. |
| AUT-2 r7 l.1017, 1026 | Host verification `journalctl`/`systemctl` | Unwrapped host steps; no change. |
| AUT-3 r6 l.265-267 | Refit `Type=notify`, **`NotifyAccess=main`** | `NotifyAccess=all` (E-7a rule 2; under bwrap the main PID is bwrap). Rows carry `E7A_R2_NOTIFY`, and the AC-5 lint enforces it. |
| AUT-3 r6 l.279-281, 292 | Refit/repro "Python flock" on the studies lock, in-process | `E7_STUDIES_LOCK` rows; open `/run/user/<uid>/breezy-studies.lock` `O_RDONLY\|O_CLOEXEC` (M27). |
| AUT-3 r6 l.296 | Repro extract to `~/.cache/breezy/refit-repro/` (hidden by `--tmpfs ~`) | Move to the data root `cache/refit-repro/` as a row bind (or use the `/tmp` tmpfs, sized by E-13). |
| AUT-3 r6 l.190, 282-283 | Transient `systemd-run --user` drill/WP0 runs | If wrapped, pass `--unit=<row-listed name>`, else 78. |
| AUT-4 r11 l.661, 1228, 1401 | Fixture row binds `/home/jon/.local/share/breezy-autonomy-fixture/` | `E7_FIXTURE_ROOT`, `bind_base="aut4_fixture"`. An AUT-5 engine pass against the fixture root needs its own fixture engine row with the same label. |
| AUT-4 r11 l.848, 871, 888, 892 | Real-bwrap tests in `tests/integration/autonomy/test_aut4_bwrap_rows.py` | Join `BWRAP_HOST_TEST_FILES`, widen the count, obey E-7d R5. |
| AUT-4 r11 l.898 | `tests/integration/autonomy/test_aut4_wal_reads.py` (both sidecar cases) | Join the registry. |
| AUT-4 r11 l.875-884 | Deployed-blob check; "the wrapper source passes `--size`…" | The blob check covers `WRAPPER_CODE_FILES`; the assertion reads `build_bwrap_argv` output. |
| AUT-4 r11 l.634-635 | Eval `flock -w` on the studies lock | `%t/breezy-studies.lock`. |
| AUT-5 r7 l.202, 286 | `sandbox_probe` accepts EACCES; "probe file unlinked" | `require_sandbox` (`O_TMPFILE`, exactly EROFS, no names). |
| AUT-5 r7 l.277 | `OnFailure=breezy-study-failed@` | `breezy-autonomy-failed@`. |
| AUT-5 r7 l.278-279 | Inline bwrap `ExecStart` with `--tmpfs %h/.config` | Wrapper with row `breezy-autonomy-engine@%i`; rows use exact instance names (`breezy-autonomy-engine@{daily,intraday,prelaunch,bootstrap}`, units `{…@<mode>.service}`), so a daily unit cannot select the bootstrap row. `resolves_dns=True`. |
| AUT-5 r7 l.281 | Bootstrap drop-in adds `derived/artefacts` | Row `breezy-autonomy-engine@bootstrap` carries that bind; the drop-in passes the row only. |
| AUT-5 r7 l.282 | Stage-S drop-ins (daily, intraday, prelaunch, deadman) add `registry-shadow` | Rows `breezy-autonomy-engine@<mode>#stage-s` and `breezy-autonomy-deadman#stage-s`; the drop-ins name them; removed at the L1 repoint. |
| AUT-5 r7 l.284 | `test_engine_unit_sandbox_config_covers_every_writer` asserts `--tmpfs %h/.config` | Derive each mode's argv from the table via `build_bwrap_argv`; assert the home allowlist and `--tmpfs /run`. |
| AUT-5 r7 l.285, 405, 879-880 | `tests/integration/test_engine_bwrap_sandbox.py`, `tests/integration/test_exec_snapshot.py` | Join the registry; Nautilus only in bwrap children. |
| AUT-5 r7 l.287 | Verify-first "un-nested step" | Superseded by E-7d. |
| AUT-5 r7 l.292 | Allowlist `exec_snapshot.py`, `sandbox_probe.py` | `SHARED_WRITE_SITES` plus `cache_dir_is_own_module_constant`. |
| AUT-5 r7 l.386-388 | G6 advisory reads in bwrap | `exec_snapshot(take_flock=False)`. |
| AUT-5 r7 (E-8 pass) | `take_flock=True` at 16:45 | Precondition: the day's supervisor STOP_PRIOR decision line exists (AC-3.2). |
| AUT-5 r7 l.273-275 | Transient timer for the bootstrap | **No change** (r2's item withdrawn, S-1). |
| AUT-6 r15 l.203-207, 802, 948-998 | daily/health/failed@ run `systemctl --user show`/`list-units`/`list-timers` in-sandbox | `--bus-snapshot` in `ExecStartPre`. Health: `list-units --failed --all --plain --no-legend`, `list-units --all --type=timer --plain 'breezy-family-tally@*'`, `list-timers --all --plain`, `show -p <fixed set> 'breezy-*'` (globs measured). failed@: `show -p ActiveState,SubState,NRestarts,Result,InvocationID {instance}`. Daily: the #24/#31 shows. A failed read → UNKNOWN (l.488, l.957). The ordering "list before journal read" (l.958) is preserved. journalctl stays in-sandbox (M24). |
| AUT-6 r15 l.247, 251 | `#evaluate` and health "no `--unshare-pid`" | `host_proc=True` (`E7A_R2_PROC`). Pid readers use host pids from `/proc` (M26). |
| AUT-6 r15 l.249, 671 | Daily locks `~/.local/share/breezy/breezy-studies.lock` in-process: **a different inode from the studies' lock** (M27) | `E7_STUDIES_LOCK`; open `/run/user/<uid>/breezy-studies.lock`. New test: path equals `$XDG_RUNTIME_DIR/breezy-studies.lock`. |
| AUT-6 r15 l.249, 1444 | `~/.config/systemd/user` re-bind | `E7_CONFIG_DIR`. |
| AUT-6 r15 l.241-243, 1334 | Text and test assert `--tmpfs ~/.config`; "AUT-5 owns the wrapper" | Assert the home allowlist, `--tmpfs /run` and the `run_rebinds` set; ARCH-0 owns the wrapper. |
| AUT-6 r15 l.260-262 | Negatives `.aut6_bwrap_probe_<id>` `O_CREAT` | `O_TMPFILE`; owner precondition kept; `AUT6_SELF_PROBE_PATHS` equal to `self_probe_plan`. |
| AUT-6 r15 l.1335-1338, 1349, 1356, 1357, 1375-1376 | Real-bwrap tests in `tests/unit/test_integrity_floor_bwrap.py` (cannot nest, M1) | Move to `tests/integration/test_integrity_floor_bwrap_namespace.py` (registry). The parse-only l.1334 test stays in unit. l.1357: the loopback receiver must start **inside** the child (`--unshare-net`, E-7d R5). |
| AUT-6 r15 l.1377 (AB10), 1292, 2290 | Scratch-unit tests via `systemd-run` | Stay in phase 1 (M29); residual R24. |
| AUT-6 r15 l.1150, 1228, 1400 | `tests/integration/test_aut6_bwrap_rows.py` | Join the registry. l.1228 becomes "health reads its bus snapshot and the journal inside its row". |
| AUT-6 r15 l.1269 (V-W6) | Notifier journal read under its row | Works (M24); no change. |
| AUT-6 r15 (notifier) | `breezy-autonomy-failed@` | Joins `NOTIFIER_FALLBACK_ROWS`; alerts-only closure test. |
| AUT-7 r5 | Inherits the engine row | Covered by the engine rows. |
| All rows | Webhook delivery | `resolves_dns=True` on every row whose entry closure can deliver an alert; each consumer has a test. |

## File-by-File Plan

| Path | N/M | Content | WP |
|---|---|---|---|
| `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` | N | C4.1 byte slice (r2) | B1 |
| `/home/jon/breezy/tests/unit/test_holdout_ruling_filed_verbatim.py` | N | 5 tests (r2) | B1 |
| `/home/jon/breezy/tests/support/bwrap_host_phase.py` | N | Plugin, blocker, admission, registry, early hook, ignore-collect, claim check | B2a |
| `/home/jon/breezy/tests/support/bwrap_harness.py` | N | `run_raw_true` (B2a); `run_in_row`, `make_roots` (B2b) | B2a/B2b |
| `/home/jon/breezy/tests/conftest.py` | M | Exactly C1–C4 | B2a |
| `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` | M | Chain, claim, `run_phase2`, mktemp/trap, header paragraph | B2a |
| `/home/jon/breezy/tests/integration/test_bwrap_host_phase_witness.py` | N | 3 witness tests; the initial registry | B2a |
| `/home/jon/breezy/tests/fixtures/bwrap_host_phase/p2_outside_registry.py`, `/home/jon/breezy/tests/fixtures/bwrap_host_phase/p2_imports_nautilus.py`, `/home/jon/breezy/tests/fixtures/bwrap_host_phase/witness_dir/conftest.py`, `/home/jon/breezy/tests/fixtures/bwrap_host_phase/witness_dir/p2_import_witness.py` | N | Child-pytest controls (not `test_*`) | B2a |
| `/home/jon/breezy/tests/unit/test_bwrap_host_phase_barrier.py`, `/home/jon/breezy/tests/unit/test_run_tests_no_egress_phases.py` | N | Gate tests | B2a |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/__init__.py` | N | Docstring only | B2b |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/table.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/binds.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/run_mounts.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/bwrap.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/self_probe.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/selftest_cli.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/write_sites.py` | N | AC-1, AC-2, AC-4 | B2b |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/bus_handoff.py` | N | AC-9 | B2c |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/wal_snapshot.py` | N | AC-3 | B3 |
| `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap` | N 0755 | 4 lines: shebang `-I`, `sys.exit(main(sys.argv[1:]))` | B2b |
| `/home/jon/breezy/tests/support/autonomy_write_sites.py` | N | `cache_dir_is_own_module_constant`, AC6 predicate | B2b |
| `/home/jon/breezy/tests/unit/test_autonomy_sandbox_table.py`, `/home/jon/breezy/tests/unit/test_autonomy_bwrap_argv.py`, `/home/jon/breezy/tests/unit/test_autonomy_bind_integrity.py`, `/home/jon/breezy/tests/unit/test_autonomy_units_wrapped.py`, `/home/jon/breezy/tests/unit/test_autonomy_self_probe.py`, `/home/jon/breezy/tests/unit/test_autonomy_write_sites.py` | N | Phase-1 tests | B2b |
| `/home/jon/breezy/tests/contract/test_autonomy_units.py` | N | E-13 tests (AUT-4 names) | B2b |
| `/home/jon/breezy/tests/integration/test_autonomy_sandbox_namespace.py` | N | Phase 2 | B2b |
| `/home/jon/breezy/tests/unit/test_autonomy_bus_handoff.py`, `/home/jon/breezy/tests/integration/test_bus_handoff_namespace.py` | N | AC-9 tests | B2c |
| `/home/jon/breezy/tests/unit/test_wal_snapshot.py`, `/home/jon/breezy/tests/integration/test_wal_snapshot_namespace.py` | N | AC-3 tests | B3 |
| `/home/jon/breezy/pyproject.toml` | M | One additive contract; no `addopts`/`markers` edit | B2b |
| `/home/jon/breezy/deploy/systemd/README.md` | M | Wrapper section: misconfiguration-not-authorisation; home allowlist; `/run` set; PROC shape; bus handoff; residuals; V-steps | B2b, B2c |

## Test Strategy

Phase-1 tests run under gate phase 1; registry files run in phase 2. WAL fixtures go through `SqliteStateStore` (L-42).

| File | Tests (r3 additions in bold; r2 sets kept unless noted) | Failure proven |
|---|---|---|
| `test_bwrap_host_phase_barrier.py` | r2 set, **plus:** `test_p2_args_outside_registry_abort_before_import` (witness module and witness conftest absent, rc 2); `test_p2_without_dash_p_plugin_not_admitted`; `test_p2_option_widening_refused` (`--rootdir`, `--confcutdir`, `--noconftest`, `--pyargs`, `-c`, extra `-p`); `test_p2_ignore_collect_skips_non_ancestor_dirs`; `test_p2_admission_env_present_but_not_exact_one_aborts` (`""`, `"true"`, `"1 "`, attested + `"true"`); `test_collect_only_claim_mismatch_exits_2`; `test_bwrap_host_files_import_policy` (deny-list, transitive `tests.support`, planted positive controls); `test_harness_is_only_subprocess_site_and_argv_is_bwrap_with_unshare_net`; `test_bwrap_host_expected_tests_equals_collected_count` (L-33 mutation +1 → red) | Prevention before import; non-widening |
| `test_run_tests_no_egress_phases.py` | r2 set, **plus:** `test_phase1_runs_exactly_once_when_bwrap_and_unshare_both_usable` (stub counters); `test_unshare_only_host_runs_phase1_then_phase2_refuses_3`; `test_collect_only_exact_tokens` (`--collect-only`, `--co`, `--collectonly`; `-k --co` → pytest usage error → red); `test_phase2_basetemp_unique_and_removed`; `test_lane_collect_ids_unaffected` | Dispatch, exit codes |
| `test_bwrap_host_phase_witness.py` (phase 2) | `test_witness_blocker_at_meta_path_head`; `test_witness_no_refused_module_loaded`; `test_witness_raw_bwrap_child_true` | B2a green at its own sha |
| `test_autonomy_sandbox_table.py` | r2 set, **plus:** `test_known_exceptions_exact`; `test_no_user_bus_exception_label`; `test_flag_label_biconditionals`; `test_resolves_dns_has_no_default`; `test_bus_reads_literal_readonly_verbs_only`; `test_bus_actions_exact_kill_signals_and_targets`; `test_alternate_bind_bases_exact`; `test_seam_b_rows_exact` | Each rule has a failing fixture |
| `test_autonomy_bwrap_argv.py` | r2 set (r2's `…run_user_tmpfs` is replaced), **plus:** `test_argv_every_row_unshares_pid`; `test_argv_tmpfs_run_after_root_bind`; `test_argv_run_rebinds_exact_then_remount_ro_run`; `test_argv_proc_rows_omit_proc_mount_keep_unshare_pid`; `test_dns_rebind_is_resolv_target_file_only`; `test_argv_setenv_xdg_cache_home`; `test_main_production_default_reads_real_cgroup_and_refuses` (L-55) | Mutants: drop `--tmpfs /run`; drop `--remount-ro /run`; `--proc` on a PROC row; drop `--unshare-pid` |
| `test_autonomy_bind_integrity.py` | r2 set, **plus:** `test_studies_lock_rebind_regular_owned_nlink1`; `test_credentials_dir_must_equal_unit_leaf_modes_and_names`; `test_notify_socket_must_be_socket_under_run_user_systemd`; `test_fixture_base_row_binds_only_under_alternate_base` | Alias and escape cases |
| `test_autonomy_units_wrapped.py` | r2 set, **plus:** `test_wrapper_naming_only_unit_lints_wrapper_lines_only` (recorder-shaped control); `test_execstartpre_bus_snapshot_and_execstartpost_bus_action_forms`; `test_notify_rows_require_notifyaccess_all`; `test_reconcile_units_loadcredential_per_name` | Non-vacuous |
| `test_autonomy_self_probe.py` | r2 set (live-listing tests removed), **plus:** `test_negative_requires_owner_uid_precondition`; `test_run_walk_unlisted_socket_is_host_socket_visible`; `test_run_writable_is_run_not_readonly`; `test_proc_row_pid_ns_uses_proc_self` | No-write proof kept |
| `tests/contract/test_autonomy_units.py` | `test_wrapper_malformed_tmpfs_size_fails_closed`; `test_wrapper_applies_default_tmpfs_size_to_rows_without_one` | E-13 |
| `test_autonomy_sandbox_namespace.py` (phase 2) | r2 set (`…systemd_private…` widened), **plus:** `test_bwrap_run_has_no_host_sockets` (docker, snapd, lxd, system bus, user bus → ENOENT); `test_bwrap_run_readonly_and_allowlisted_entries_only`; `test_bwrap_dns_row_has_only_resolv_file_and_hosts_lookup_works`; `test_bwrap_proc_row_reads_host_proc_locks_and_pid_status`; `test_bwrap_proc_row_host_pid_environ_root_eacces_kill_esrch`; `test_bwrap_studies_lock_rebind_excludes_both_ways`; `test_bwrap_credentials_dir_readonly_only_listed_names`; `test_bwrap_xdg_cache_home_is_private_tmp` | Directive-free enforcement |
| `test_autonomy_bus_handoff.py` | `test_bus_snapshot_writes_invocation_keyed_file_via_bind_fd`; `…records_rc_timeout_per_read_and_exits_0`; `…config_error_exits_78_writes_nothing`; `…env_is_minimal`; `…instance_placeholder_from_cgroup_leaf`; `…sweeps_stale_under_dir_flock`; `test_read_bus_snapshot_rejects_other_invocation_and_unlinks_own`; `test_bus_action_request_gate_fires_only_same_invocation`; `test_bus_action_unconditional_fires`; `test_bus_handoff_production_default_runner_is_list_argv_subprocess` (L-55) | Stale and forged handoff |
| `test_bus_handoff_namespace.py` (phase 2) | `test_in_row_systemctl_fails_and_snapshot_readable`; `test_in_row_request_then_fake_fire` | Handoff end to end |
| `test_wal_snapshot.py` | r2 set, **plus:** `test_take_flock_true_hold_is_read_as_busy_by_supervisor_probe_and_released` (child runs the real `intent_lock_is_free`); `test_prelaunch_release_deadline_precedes_supervisor_launch_utc`; `test_stop_prior_started_during_hold_refuses_without_signal` | Supervisor interplay |
| `test_wal_snapshot_namespace.py` (phase 2) | r1's four | E-7a rule 3 |

**Real-host verification** (primary tree, after each WP merge, `-I`; L-51)
- **V0.** `systemd-run --user --wait --pipe --collect -p LimitNOFILE=524288 /home/jon/breezy/scripts/ci/run_tests_no_egress.sh --basetemp=/home/jon/.cache/breezy-gate/full-bt` must exit 0 and print `phase1 rc=0 phase2 rc=0`, with passed = `BWRAP_HOST_EXPECTED_TESTS`. Record the wall time.
- **V1.** `install -d -m 0700 /home/jon/.local/share/breezy/cache /home/jon/.local/share/breezy/cache/autonomy_selftest /home/jon/.local/share/breezy/cache/autonomy_selftest/.bus_snapshot`
- **V2.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest -p TimeoutStartSec=60 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap breezy-autonomy-selftest /home/jon/breezy/.venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli` must print `"ok": true`, `tmp_size_kib` 262144 and `home_listing` `[".local","breezy"]`.
- **V3–V8 (r2).**
  - V3: the `/tmp` marker is absent on the host.
  - V4: an unknown row gives 78. V5: a unit mismatch gives 78.
  - V6/V7: `O_TMPFILE` on `/home/jon/.local/share/breezy/state` and on `/home/jon/breezy` gives EROFS.
  - V8: `/proc/1/comm` is `bwrap`.
- **V9.** Overhead p95 ≤ 50 ms over 20 runs.
- **V10.** Node up, `--exec-snapshot 20`. Record ok/unstable; no `snap.*` appears in `state/`.
- **V11.** For every `WRAPPER_CODE_FILES` path, `sha256sum` equals `git show <merge_sha>:<path> | sha256sum`.
- **V12.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest-notify -p Type=notify -p NotifyAccess=all -p TimeoutStartSec=30 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap breezy-autonomy-selftest-notify /bin/sh -c 'systemd-notify --ready; sleep 1'` must succeed (M20 shape).
- **V13.** Measure the mtime tick.
- **V14.** In the selftest row: `ls -A /home/jon` gives exactly the re-binds; `unshare -U true` fails; `test -e /home/jon/.ssh` fails.
- **V15.** In the selftest row: `ls -A /run` gives `systemd`; the only file is `/run/systemd/resolve/stub-resolv.conf`; connects to `/var/run/docker.sock`, `/run/snapd.socket`, `/run/dbus/system_bus_socket` and `/run/user/1000/bus` give ENOENT; `touch /run/x` gives EROFS.
- **V16.** In the selftest row: `getaddrinfo("api.weather.gov", 443)` resolves (DNS only, no request).
- **V17.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest -p "ExecStartPre=/usr/bin/timeout -k 2 30 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap --bus-snapshot breezy-autonomy-selftest" /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap breezy-autonomy-selftest /home/jon/breezy/.venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli --bus-snapshot` must print `"bus_snapshot": {"self_show": {"rc": 0}}` and `"in_row_systemctl": "failed"`.
- **V18.** `--unit=breezy-autonomy-selftest-proc … --proc-checks` must report:
  - `/proc/locks` line count within ±5 of the host's;
  - `kill(<supervisor pid>, 0)` → ESRCH and `/proc/<supervisor pid>/environ` → EACCES;
  - `fstat` of `/run/user/1000/breezy-studies.lock` with the same inode as `stat -c %i /run/user/1000/breezy-studies.lock` (no flock taken).
- **V19.** Record `ss -xlH | grep -c ' @'` (residual, no assertion).

## Work Packages

**Order:** WP-B1 ‖ WP-B2a → WP-B2b → (WP-B2c ‖ WP-B3).
- E-7d is filed before WP-B2a merges; E-7e is filed before WP-B2b merges.
- WP-B2c's `--bus-action` lands only if the r3 security review accepts E-7e(h).
- B2c and B3 both widen `BWRAP_HOST_EXPECTED_TESTS`. The merge conflict is on one literal, so it is visible.
- B2b and B3 are on the critical path for AUT-1a, AUT-5a and AUT-6; B2c is on it for AUT-1 and AUT-6.

**WP-B1 `docs:` C4.1 ruling**
- **Scope:** the ruling file and its test.
- **RED:** the file is absent. **GREEN:** a byte slice with the block sha pinned. The drift note goes in the commit message.
- **Done:** full gate green; `tests/unit/test_probe_containment.py:550-558` green.
- **Brief invariants (verbatim):**
  - (1) Nautilus Trader is immutable; never modify, patch, fork, bypass or reimplement it.
  - (2) `allow_short` stays `False`.
  - (3) Never weaken or delete a safety, settlement, firewall or contract test to go green.
  - (4) Never name or assign an operator-reserved control (max daily budget, max per position).
  - (5) Never touch live-trading enablement or the NO-SEND execution-egress firewall; never write the live exec store.
  - (6) Use the exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv`, `pip` or `git stash`; use `PYTHONPATH=<tree>/src` in a worktree.
  - (7) Run the full gate (both phases) after every merge, via `systemd-run --user --wait --pipe -p LimitNOFILE=524288`, with basetemp under `/home/jon/.cache/breezy-gate`; read EXIT before any push.
  - (8) Read-only unless the task is a write.

**WP-B2a `test:` gate phases (security-reviewed)**
- **Scope:**
  - `/home/jon/breezy/tests/support/bwrap_host_phase.py`;
  - conftest C1–C4;
  - the script;
  - `/home/jon/breezy/tests/support/bwrap_harness.py` (`run_raw_true` only);
  - the witness file;
  - the fixtures;
  - `/home/jon/breezy/tests/unit/test_bwrap_host_phase_barrier.py`;
  - `/home/jon/breezy/tests/unit/test_run_tests_no_egress_phases.py`.
- **Registry and count:** registry = {witness}; `BWRAP_HOST_EXPECTED_TESTS` = 3.
- **Verify-first:** re-run M2, M3 and M31 on a scratch copy at HEAD; re-grep the Basis pins.
- **RED:** barrier and script tests.
- **Mutations (L-33):**
  - drop C3's mutual exclusion;
  - make the blocker refuse nothing;
  - restore `exec` on l.37;
  - remove the early-hook args check;
  - return None from ignore-collect for every path;
  - turn the elif chain back into two ifs;
  - bump the count by one.
  - Each turns a named test red.
- **Done:** security sign-off; both phases green **at this sha**; every existing N2/N3/N5/X1 test unchanged and green.
- **Brief invariants (verbatim):**
  - (1) Nautilus Trader is immutable; never modify, patch, fork, bypass or reimplement it.
  - (2) `allow_short` stays `False`.
  - (3) The NO-SEND firewall and its tests are never weakened. The N2 change is an exact-set, security-reviewed addition whose absent-input path is byte-identical (`test_n2_rule_without_phase_evidence_is_unchanged`). N3, N5, X1–X3 and E0 are untouched.
  - (4) Never name or assign an operator-reserved control.
  - (5) Never touch live-trading enablement; never write the live exec store.
  - (6) Use the exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv`, `pip` or `git stash`; worktree `PYTHONPATH`; `lint-imports` from the tree root.
  - (7) Full gate after every merge (`systemd-run --user --wait --pipe -p LimitNOFILE=524288`, basetemp under `/home/jon/.cache/breezy-gate`); read EXIT before push.
  - (8) Read-only unless the task is a write.

**WP-B2b `feat:` wrapper, `/run` set, PROC shape**
- **Scope:**
  - the modules `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/table.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/binds.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/run_mounts.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/bwrap.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/self_probe.py`, `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/selftest_cli.py` and `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/write_sites.py`;
  - the script `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap`;
  - the harness `run_in_row`, the unit lint, the E-13 tests, the phase-2 sandbox file, the README and the import-linter contract.
- **Registry:** widened by `/home/jon/breezy/tests/integration/test_autonomy_sandbox_namespace.py`, with the count updated.
- **Mutations:**
  - `--size` after `--tmpfs`;
  - drop `--tmpfs <home>`;
  - drop `--tmpfs /run`;
  - drop `--remount-ro /run`;
  - `--proc` on a PROC row;
  - drop `--unshare-pid`;
  - path `--bind` instead of `--bind-fd`;
  - accept EACCES in the negative probe;
  - drop the cgroup check.
- **Done:** both phases green; lint-imports "N kept, 0 broken"; V0–V9, V11, V12, V14–V16 and V18 on the primary tree before any consumer row.
- **Brief invariants (verbatim):**
  - (1) Nautilus Trader is immutable; never modify, patch, fork, bypass or reimplement it.
  - (2) `allow_short` stays `False`.
  - (3) Never weaken or delete a safety, settlement, firewall or contract test to go green.
  - (4) Never name or assign an operator-reserved control. The repo-root operator file is never read or referenced by name in code or tests.
  - (5) Never touch live-trading enablement or the NO-SEND firewall; never write the live exec store; no probe creates a name under `state/`; the wrapper never creates a bind source.
  - (6) Use the exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv`, `pip` or `git stash`; worktree `PYTHONPATH`.
  - (7) Full gate after every merge (`systemd-run --user --wait --pipe -p LimitNOFILE=524288`, basetemp under `/home/jon/.cache/breezy-gate`); read EXIT before push.
  - (8) Read-only unless the task is a write.

**WP-B2c `feat:` bus handoff**
- **Scope:**
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/bus_handoff.py`;
  - the `bwrap.main` `--bus-snapshot` and `--bus-action` modes;
  - the AC-5 lint forms;
  - `/home/jon/breezy/tests/unit/test_autonomy_bus_handoff.py`;
  - `/home/jon/breezy/tests/integration/test_bus_handoff_namespace.py` (registry and count).
- **Mutations:**
  - skip the invocation check;
  - allow the verb `start`;
  - fire without a request;
  - exit non-zero on a failed read.
- **Done:** both phases green; V17. `--bus-action` lands only if E-7e(h) is accepted, otherwise it is removed with its tests before merge.
- **Brief invariants (verbatim):**
  - (1) Nautilus Trader is immutable; never modify, patch, fork, bypass or reimplement it.
  - (2) `allow_short` stays `False`.
  - (3) Never weaken or delete a safety, settlement, firewall or contract test to go green.
  - (4) Never name or assign an operator-reserved control.
  - (5) Never touch live-trading enablement or the NO-SEND firewall. No bus call other than the exact AC-9 forms; never `start`, `stop`, `restart` or `systemd-run`. `BUS_ACTION_TARGET_UNITS` ships empty.
  - (6) Use the exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv`, `pip` or `git stash`; worktree `PYTHONPATH`.
  - (7) Full gate after every merge (`systemd-run --user --wait --pipe -p LimitNOFILE=524288`, basetemp under `/home/jon/.cache/breezy-gate`); read EXIT before push.
  - (8) Read-only unless the task is a write.

**WP-B3 `feat:` WAL snapshot helper**
- **Scope:**
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/wal_snapshot.py`;
  - the remaining `write_sites`;
  - `/home/jon/breezy/tests/support/autonomy_write_sites.py` predicate use;
  - `/home/jon/breezy/tests/unit/test_wal_snapshot.py`;
  - `/home/jon/breezy/tests/integration/test_wal_snapshot_namespace.py` (registry and count);
  - `selftest_cli --exec-snapshot`.
- **Mutations:**
  - remove the re-fingerprint, the tail digest, quiescence or the cache flock;
  - copy `-shm`;
  - move the deadline past 16:50.
- **Done:** both phases green; lint-imports; V10 and V13 in the merge evidence.
- **Brief invariants (verbatim):**
  - (1) Nautilus Trader is immutable; never modify, patch, fork, bypass or reimplement it.
  - (2) `allow_short` stays `False`.
  - (3) Never weaken or delete a safety, settlement, firewall or contract test to go green.
  - (4) Never name or assign an operator-reserved control.
  - (5) Never touch live-trading enablement or the NO-SEND firewall. **The live exec store is never written**: only the cache copy is opened read-write. `intent_lock_is_free` is not changed (E-8).
  - (6) Use the exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv`, `pip` or `git stash`; worktree `PYTHONPATH`.
  - (7) Full gate after every merge (`systemd-run --user --wait --pipe -p LimitNOFILE=524288`, basetemp under `/home/jon/.cache/breezy-gate`); read EXIT before push.
  - (8) Read-only unless the task is a write.

## Risk Register

| # | Risk | Sev | Mitigation / owner |
|---|---|---|---|
| R1 | Nested bwrap is impossible (M1) | HIGH | E-7d two-phase gate; never skipped except on confirmed collect-only |
| R2 | Phase-2 parent has host network | MED | Blocker; 7-condition admission before import (M31); deny-list lint; `--unshare-net` children; session-end check. Residual: file-path loading, covered by the lint. |
| R3 | Ownership move | MED | Call shapes kept; E-7e(f) complete with plan:line |
| R4 | Coarse mtime | MED | Digests, quiescence, V13 |
| R5 | `--size` order | MED | Argv test, E-13 tests |
| R6 | Cgroup naming | LOW | Exact parse; 78; V4/V5 |
| R7 | Degraded notifier runs unwrapped (`~/.config/breezy` visible) | MED | Exact fallback set; closure tests; never after a 78 |
| R8 | AUT-2 credential file hidden (M28) | MED | `LoadCredential` re-bind (E-7e(f)), or an unwrapped residual; r3 security rules |
| R9 | G6 in-place reads under the wrapper | MED | `exec_snapshot(False)` |
| R10 | `OnFailure=breezy-study-failed@` in AUT-1/AUT-5 | LOW | Flagged; AC-5 red until switched |
| R11 | Wrapper startup | LOW | V9, `-IS` |
| R12 | Verification from a worktree | MED | V-steps only on the primary tree |
| R13 | One table literal edited by many plans | LOW | Sorted rows; `validate_table` |
| R14 | apparmor/bwrap upgrade | LOW | Exit codes; AUT-6 health |
| R15 | Not a hostile-same-uid boundary. The ro-bound repo exposes git-ignored repo-root files, including the operator caps file (no credential; never read). Abstract sockets are shared (M32). `NOTIFY_SOCKET` is a path bind. | MED (stated) | AC6 allowlists are the second layer |
| R16 | sd_notify under `--unshare-user` | LOW | M20 measured; V12 |
| R17 | A row needs a home path outside the re-binds | LOW | Fails closed; widening is a reviewed schema change (`ALTERNATE_BIND_BASES` is the precedent) |
| R18 | Phase 2 runs once per lane | LOW | ≤ 120 s; unique basetemp |
| R19 | Wrapped units leave `test_unit_execstart_imports.py:143` | LOW | Consumers keep their entry-module tests |
| R20 | Stale or forged bus snapshot | LOW | Invocation-keyed; unlink on read; sweep |
| R21 | PROC rows read same-uid `/proc/<pid>/status` and `cmdline` | LOW (stated) | environ/root EACCES, kill ESRCH (M26) |
| R22 | Studies-lock inode mismatch (AUT-6) | HIGH (consumer) | `E7_STUDIES_LOCK`; path test (E-7e(f)) |
| R23 | `--bus-action` is a state-changing call driven by sandbox output | MED | Literal argv; exact targets; request bound to the invocation; security ruling |
| R24 | Phase-1 tests that start user units run outside the gate's netns (M29) | MED (stated) | Consumer obligation: literal stdlib-only unit argvs that import no `breezy` (E-7d) |
| R25 | False STOP_PRIOR CRITICAL during the 16:45 hold | LOW | AC-3.2 precondition; residual stated |

## LESSONS Compliance

Headers grepped in `/home/jon/breezy/docs/core/LESSONS.md` this session: L-1 :8, L-12 :620, L-14 :685, L-22 :1017, L-23 :1038, L-33 :1282, L-42 :1419, L-43 :1433, L-46 :1495, L-47 :1512, L-50 :1563, L-51 :1583, L-54 :1647, L-55 :1664.

| Lesson | How it is met |
|---|---|
| L-1 | bubblewrap, `systemd` `LoadCredential=`, `ExecStartPre`/`$INVOCATION_ID` (M23), pytest's `-p` and `pytest_load_initial_conftests` and `pytest_ignore_collect`, and stdlib `sqlite3` are all reused. New code exists only where no native piece fits: the handoff file, because `StandardOutput=` is unit-wide. |
| L-12 | `KNOWN_EXCEPTIONS`, `ALTERNATE_BIND_BASES`, `BUS_ACTION_TARGET_UNITS`, `NOTIFIER_FALLBACK_ROWS`, `AUTONOMY_OWNED_UNITS`, the registry, the count and `run_rebinds` are exact sets. N2 gains an input and is not relaxed. |
| L-14 | The `/run` allowlist is derived from a measured inventory (M15) and enforced as "what is visible". Home is hidden wholesale. |
| L-22 | Admission keys on the blocker's identity, the early witness and `sys.modules`; the degraded variable is unset; snapshot and request files are bound to `INVOCATION_ID`. |
| L-23 | Real probes only. |
| L-33 | Mutations per WP, including the count +1. |
| L-42 | WAL fixtures via `SqliteStateStore`. |
| L-43 | Both phases after every merge; B2a green at its own sha. |
| L-46 | All six consumer plans were searched for real-bwrap tests, bus and journal calls, config re-binds and home paths (§Consumer Surface, with plan:line). Contract tests searched: `test_runtime_import_isolation.py:357-369`, `test_probe_containment.py:550-558`, `test_unit_execstart_imports.py:143`, `test_operator_control_assignment_scan.py:525`, `test_test_safety_tooling_config.py:49-65`. |
| L-47 | Every host claim is measured (M14–M32). The r2 premise errors are corrected (S-1; M5's "152 lines" was host-pid-namespace procfs, M14). |
| L-50 | Cache-dir flock; `.bus_snapshot` sweep under a directory flock. |
| L-51 | Exact interpreter; primary-tree V-steps. |
| L-54 | Pins re-searched; the conftest and script edit is its own security-reviewed WP. |
| L-55 | `test_main_production_default_reads_real_cgroup_and_refuses`, `test_production_home_mount_args_hide_real_home`, `test_bus_handoff_production_default_runner_is_list_argv_subprocess`. |

## Trade-offs

- **Bus handoff vs a user-bus exception.** The exception needs the host pid namespace (M21), which re-enables signalling (M25) and allows `systemd-run` escapes (M22). The handoff costs one `ExecStartPre` line per row plus an E-9 bound.
- **PROC rows: host procfs under a private pid namespace, rather than dropping `--unshare-pid`.** Same reads, no signals (M26). The cost is that `/proc/self` resolves to the host pid; consumers already use host pids.
- **`resolves_dns` is required.** It forces a per-row decision (B3-R1) instead of a silent default that could drop alert delivery.
- **`LoadCredential` for AUT-2.** It is native and exposes one file copy, never `~/.config/breezy`. The loader's mode-0400 requirement is a caller change only.
- **Collect-only as a shell hint confirmed by pytest.** No argv parser to keep in sync, and the mismatch direction is fail-closed.
- r2's trade-offs are kept: pytest phase 2 over a runner, the exact registry, hiding all of home, `--bind-fd`, the digests.

## Confidence Self-Assessment

**90/100.**
- **High confidence:**
  - every r2 finding and every B3 ruling has a measured disposition (M14–M32);
  - the consumer search is exhaustive, with plan:line;
  - four latent consumer defects were surfaced (S-1..S-4).
- **Deductions:**
  - −3: `--bus-action` and the AUT-2 `LoadCredential` route await the r3 security ruling;
  - −3: the PROC-shape change amends adopted E-7a text;
  - −2: V12, V15–V18 on the real wrapper are still to run (their shapes are hand-measured);
  - −2: the exact `BWRAP_HOST_EXPECTED_TESTS` value is fixed only at build.

---

## §ERRATA-REQUEST

> **E-7d (coordinator, 2026-10-03, from ARCH-0 seam B r3): the gate runs real-namespace tests in an un-nested second phase.**
> - **Evidence.** Nested bwrap inside the gate fails with "No permissions to create a new namespace" (rc 1, apparmor `bwrap-userns-restrict`). One level works from outside. A `-p` plugin's `pytest_load_initial_conftests` runs before any conftest import and can exit rc 2 with `SystemExit(2)`. `pytest_ignore_collect` over non-ancestor directories keeps their conftest and modules unimported (pytest 9.1.1). With the blocker and four conftest edits, the phase-2 parent ran with no `nautilus_trader*` or `breezy.adapters*` module loaded.
> - **Rule 1: one gate, two phases.** `scripts/ci/run_tests_no_egress.sh` remains the gate.
>   - Phase 1 is the existing egress-blocked pytest, selected by a single `if bwrap / elif unshare / else exit 3` chain and run exactly once.
>   - Phase 2 then runs un-nested. The gate prints both exit codes and exits with the first non-zero.
>   - Phase 2 is omitted only when an exact argument token is `--collect-only`, `--co` or `--collectonly` **and** phase 1's pytest confirms collect-only mode (`BREEZY_GATE_COLLECT_ONLY_CLAIM`; a mismatch gives rc 2). No variable or flag disables it.
>   - On a host where only `unshare` works, phase 1 runs and phase 2 refuses with rc 3, so the gate is red there by design.
>   - Phase 2's basetemp is a fresh `mktemp -d` under the gate dir, removed on exit.
> - **Rule 2: what phase 2 runs.**
>   - Exactly `tests.support.bwrap_host_phase.BWRAP_HOST_TEST_FILES`, with `-m bwrap_host`. That set is exact and equals the AST-derived set of files that use the marker.
>   - The passed count must equal the literal `BWRAP_HOST_EXPECTED_TESTS`, which is mutation-pinned.
>   - A plan adding a real-namespace test widens both in the same commit (L-12).
>   - Phase 1 skips `bwrap_host` items with a reason naming phase 2. In phase 2, any skip, any item outside the set, or a count mismatch fails the session.
>   - The first merge ships a self-contained witness file as the only member, so the gate change is green at its own sha.
> - **Rule 3: prevention in the parent.** Phase 2 runs with `BREEZY_BWRAP_HOST_PHASE=1`, without `BREEZY_TEST_OS_EGRESS_BLOCK`, and with `-p tests.support.bwrap_host_phase`. That plugin puts a meta-path blocker at `sys.meta_path[0]` before any conftest loads. The blocker refuses `nautilus_trader*`, `breezy.adapters*` and the module of every `find_execution_egress_modules()` hit.
> - **Rule 4: N2, widened as an exact set.** `execution_egress_abort_reason` gains one keyword-only input; when it is absent, the rule is unchanged. An unattested session is admitted only if all of these hold:
>   - (1) the variable is exactly `"1"`;
>   - (2) the attestation is absent;
>   - (3) the blocker (exact class) is at `meta_path[0]`;
>   - (4) every egress hit maps to a refused module;
>   - (5) no refused module is loaded;
>   - (6) the plugin was loaded with `-p` and, before any conftest import, found every positional argument inside the registry and no option that widens collection (`--rootdir` other than the repo, `--confcutdir`, `--noconftest`, `--pyargs`, `-c`, a non-default `--import-mode`, or any extra `-p`);
>   - (7) `pytest_ignore_collect` excludes every non-registry file and every directory that is not an ancestor of one.
>
>   Anything else aborts with rc 2. A variable set to any other value, including `""`, `"true"` or `"1 "`, aborts with rc 2; this differs from today's behaviour only when the variable is set. Attested plus the phase variable aborts with rc 2. The credential gate runs first and is unchanged. The session end re-checks `sys.modules`. No canary is sent in phase 2.
> - **Rule 5: children and imports.** Every bwrap child a phase-2 test spawns goes through `tests/support/bwrap_harness.py`, which adds `--unshare-net` and passes an explicit environment. An AST lint covers the registry files and every `tests.support` module they import:
>   - denied imports: `socket`, `http*`, `urllib*`, `requests`, `httpx`, `aiohttp`, `websockets`, `ctypes`, `runpy`, `nautilus_trader*`, `breezy.adapters*`, `breezy.strategy*`, and `subprocess` except in the harness;
>   - denied calls: `os.exec*`, `os.spawn*`, `os.system`, `os.popen`, `os.fork`, `importlib.util.spec_from_file_location` and `SourceFileLoader`.
> - **Consumer obligation.**
>   - Nautilus work in a phase-2 test runs only inside a bwrap child.
>   - Phase-2 files live outside `tests/unit/` and `tests/contract/`.
>   - A receiver or server a child must reach runs inside that child's namespace.
>   - A phase-1 test may start bwrap through `systemd-run --user`, which is not nested. Such a unit runs outside the gate's network namespace, so its argv is literal and stdlib-only and imports no `breezy` module.
> - **Residual.** The phase-2 parent has host network for native non-Nautilus code. Python sockets stay blocked by the conftest fixture. File-path module loading bypasses the blocker and is covered by the Rule 5 lint.
> - **Supersedes** B-R1's "Phase 2 collects `-m bwrap_host tests/`" and AUT-5 r7 l.287's verify-first branch. **Security sign-off:** ARCH-0 seam B r3 security review. **Filed before** WP-B2a merges.

> **E-7e (coordinator, 2026-10-03, from ARCH-0 seam B r3): ARCH-0 owns the shared wrapper, table, self-probe, bus handoff and E-8 helper.**
> - **Ownership.** ARCH-0 seam B owns:
>   - `deploy/systemd/breezy-autonomy-bwrap`;
>   - `AUTONOMY_BWRAP_TABLE` and its validation;
>   - the self-probe;
>   - the bus handoff;
>   - the E-8 helper (`wal_snapshot`, `exec_snapshot`);
>   - the E-7a rule-1 unit lint.
>
>   They live in `src/breezy/runtime/autonomy_sandbox/`, under the forbidden contract `breezy.runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy` (`allow_indirect_imports=false`). This is a stated deviation from ARCH §3's "types live in persistence/autonomy". AUT-5 keeps the halt and intent decode, the 16:48:00 value, the E-8 test names and its rows. In the E-7/E-8 consumption table, the AUT-5 "owns" entries move to ARCH-0.
> - **(a) Write-authority allowlists.** AUT-5 r7 l.292's `exec_snapshot.py` and `sandbox_probe.py` rows are replaced by `SHARED_WRITE_SITES`. An AC6 allowlist admits those sites only when every snapshot call passes `cache_dir=` a module-level `Final` constant of the calling module.
> - **(b) E-8 amendment.**
>   - **Fingerprint.** (inode, size, `mtime_ns`) plus sha256 of db bytes 0–99, of `-wal` bytes 0–31 and of its last 4096 bytes; `-journal` adds its first 512 bytes. Any file whose `mtime_ns` is within 20 ms of now forces a 20 ms wait first.
>   - **Copy.** Order is db, `-wal`, `-journal`, fd-relative, into a `snap.*` directory created under an `O_RDONLY|O_DIRECTORY` flock of the cache dir. Contention gives `cache_busy`. The cache dir and its parent are checked by `fstat` of a nofollow-walked fd.
>   - **Advisory flag.** A result is non-advisory only if the intent flock was held from the first fingerprint to the last.
>   - **`take_flock=True`.** Legal only in the AUT-5 16:45 pass, after the day's supervisor STOP_PRIOR decision line exists, with its deadline before 16:50. Between 16:45 and 16:48 a supervisor STOP_PRIOR poll reads "not free" and only keeps polling. A STOP_PRIOR that *starts* during the hold refuses with one false CRITICAL and no signal (stated residual).
> - **(c) Mount-set amendment to E-7 rule 2 and E-7a rules 1, 2 and 5.** Every row runs:
>   - `--unshare-user --disable-userns --assert-userns-disabled --unshare-pid`;
>   - `--ro-bind / /`, then `--tmpfs /run`;
>   - `--dev /dev`;
>   - `--proc /proc`, except on `E7A_R2_PROC` rows. Those keep `--unshare-pid` and get the host procfs read-only through the root bind: `/proc/locks` and `/proc/<pid>/status` are readable, `environ` and `root` give EACCES, and signals to host pids give ESRCH. **This replaces "drop `--unshare-pid`"**, and narrows rule 5's `/proc/<pid>` residual to read-only status visibility;
>   - `--size N --tmpfs /tmp`;
>   - `--tmpfs ~` (replacing `--tmpfs ~/.config`), with read-only re-binds of exactly the repo, the data root, the interpreter prefix (if under home), and on `E7_FIXTURE_ROOT` rows the exact alternate base;
>   - an exact per-row `/run` re-bind set, then `--remount-ro /run`:
>     - the resolv target file (rows with `resolves_dns`);
>     - `NOTIFY_SOCKET` (`E7A_R2_NOTIFY`);
>     - `/run/user/<uid>/breezy-studies.lock` (`E7_STUDIES_LOCK`);
>     - `$CREDENTIALS_DIRECTORY` (`E7A_R2_RECONCILE`);
>   - binds via `--bind-fd` after a nofollow walk, with dev/ino distinct from `state/` and its ancestors;
>   - config files via `--ro-bind-fd` (nofollow, `st_nlink == 1`, no alias under `~/.config/breezy`); `~/.config/systemd/user` only under `E7_CONFIG_DIR`;
>   - `--remount-ro ~`;
>   - `--setenv TMPDIR /tmp --setenv XDG_CACHE_HOME /tmp/.cache`, `--unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`.
>
>   No row exposes `/run/user/<uid>/bus`, `/run/user/<uid>/systemd/private`, docker, snapd, lxd or the system bus; `/var/run` resolves into the tmpfs. The unit check is integrity against misconfiguration, not an authorisation boundary.
> - **(d) Self-probe amendment to E-7 rule 2.**
>   - The env-row check runs before any open.
>   - Negatives come from the table only. Each has an "owned by this uid" directory precondition and `O_TMPFILE|O_WRONLY` must fail with exactly EROFS. No named file is ever created under `state/`, the data root or the repo.
>   - Positives are `tmpfile` or `subdir` per bind.
>   - Credential paths give ENOENT, and the home listing is ⊆ the re-binds.
>   - The named host and bus sockets give ENOENT; `/run` holds only allowlisted entries and is read-only.
>   - pid namespace: `/proc/1/comm == "bwrap"`, or on `E7A_R2_PROC` rows `/proc/self` ≠ `getpid()`.
>   - Vocabulary: AUT-6's codes plus `env_row`, `degraded_forged`, `credentials_visible`, `user_bus_visible`, `host_socket_visible`, `run_not_private`, `run_not_readonly`, `tmp_not_private`, `pid_ns`, `negative_unverifiable`.
> - **(e) Labels.** `KNOWN_EXCEPTIONS = {E7A_R2_PROC, E7A_R2_NOTIFY, E7A_R2_RECONCILE, E7A_R2_BUS_ACTION, E7B_EVAL_OFFLINE_ADAPTER_MODULES, E7_CONFIG_DIR, E7_STUDIES_LOCK, E7_FIXTURE_ROOT}`. There is no user-bus label: a user-bus row would need the host pid namespace and could start units outside the sandbox.
> - **(f) Consumer changes (binding build items).**
>   - **AUT-1 r12:**
>     - l.770/939: the audit's `systemctl --user show` becomes a `--bus-snapshot` read;
>     - l.768-769: journalctl stays in-sandbox;
>     - l.733/741/883-884/941: the drill and guard use `--bus-action` (request-gated SIGSTOP; unconditional SIGCONT) with no socket bind, else they run unwrapped as a stated residual;
>     - l.1045: V-9(b) is replaced by the handoff;
>     - l.905-906: `OnFailure=breezy-autonomy-failed@%n.service`, and the `alerts.env` re-bind is removed;
>     - l.881: `flock -w %t/breezy-studies.lock`;
>     - its units join `AUTONOMY_OWNED_UNITS`;
>     - the stop-hook unit is linted on its wrapper line only.
>   - **AUT-2 r7:**
>     - l.180/468: reconcile uses `E7A_R2_RECONCILE` with `LoadCredential=`, the key file path under `$CREDENTIALS_DIRECTORY`, `require_key_file_mode=0o400`, and a reconcile-only env file (verify-first) — or runs unwrapped as a stated residual;
>     - `resolves_dns=True`;
>     - wrapped G6 reads use `exec_snapshot(take_flock=False)`;
>     - `breezy-aut2-recon-failed@` joins `NOTIFIER_FALLBACK_ROWS`;
>     - l.467: `%t/breezy-studies.lock`.
>   - **AUT-3 r6:**
>     - l.267: `NotifyAccess=all`;
>     - l.279-281/292: `E7_STUDIES_LOCK` on `/run/user/<uid>/breezy-studies.lock`;
>     - l.296: the repro extract moves to `cache/refit-repro/` under the data root;
>     - l.190/282-283: wrapped transient runs pass `--unit=<row unit>`.
>   - **AUT-4 r11:**
>     - l.661/1228/1401: the fixture row uses `E7_FIXTURE_ROOT`, and any engine pass on that root uses a fixture engine row with the same label;
>     - l.848/871/888/892: `tests/integration/autonomy/test_aut4_bwrap_rows.py` joins the registry;
>     - l.898: `tests/integration/autonomy/test_aut4_wal_reads.py` joins the registry;
>     - l.875-884: the blob check covers `WRAPPER_CODE_FILES` and the argv check reads `build_bwrap_argv`;
>     - l.634-635: `%t/breezy-studies.lock`;
>     - the E-13 tests are delivered by ARCH-0 at AUT-4's paths.
>   - **AUT-5 r7:**
>     - l.278-279: the wrapper with rows `breezy-autonomy-engine@<mode>` using exact instance names;
>     - l.281: the bootstrap row carries `derived/artefacts`;
>     - l.282: rows `breezy-autonomy-engine@<mode>#stage-s` and `breezy-autonomy-deadman#stage-s`;
>     - l.202/286: `require_sandbox` replaces `sandbox_probe`;
>     - l.277: `OnFailure=breezy-autonomy-failed@`;
>     - l.284: the config test is derived from the table;
>     - l.285/405/879-880: real-namespace tests join the registry;
>     - l.292: `SHARED_WRITE_SITES`;
>     - l.386-388: `exec_snapshot(take_flock=False)`;
>     - E-8: the STOP_PRIOR-line precondition;
>     - l.273-275: unchanged.
>   - **AUT-6 r15:**
>     - l.203-207/802/958/966: `systemctl` reads become `--bus-snapshot` (a failed read is UNKNOWN); journalctl stays in-sandbox;
>     - l.247/251: `#evaluate` and health use `E7A_R2_PROC` (host procfs, private pid namespace);
>     - l.249/671: the daily lock uses `E7_STUDIES_LOCK` on `/run/user/<uid>/breezy-studies.lock` (today's path is a different inode), with a path test;
>     - l.249/1444: `E7_CONFIG_DIR`;
>     - l.241-243/1334: the `--tmpfs ~/.config` assertions become home-allowlist and `/run`-set assertions;
>     - l.260-262: `O_TMPFILE` negatives with the owner precondition kept;
>     - l.1335-1338/1349/1356-1357/1375-1376: real-bwrap tests move to `tests/integration/test_integrity_floor_bwrap_namespace.py` and join the registry; l.1357's receiver runs inside the child;
>     - l.1150/1228/1400: `tests/integration/test_aut6_bwrap_rows.py` joins the registry;
>     - l.1377/1292/2290: scratch-unit tests stay in phase 1;
>     - `breezy-autonomy-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
>   - **Every plan:** `resolves_dns=True` on every row that can deliver an alert, each with a test.
> - **(g) Notifier fallback.** Only rows in `NOTIFIER_FALLBACK_ROWS` may fall back, and only after every configuration check, with a 2 s preflight. Degraded mode is honoured only for those rows. `degraded_write_target` refuses `state/` and anything outside the binds, and the consumers' closure tests enforce that callers use it. Degraded mode exposes `~/.config/breezy` (stated residual).
> - **(h) Bus handoff.**
>   - **No bus inside any sandbox.** A row's literal read-only `systemctl --user show|list-units|list-timers` argvs run unsandboxed through `ExecStartPre=timeout -k … breezy-autonomy-bwrap --bus-snapshot <row>`. The output goes into a file keyed by `$INVOCATION_ID` in one of the row's binds, which the sandboxed step reads and unlinks. A failed read is recorded, not fatal.
>   - **State-changing calls.** Only `systemctl --user kill --signal=SIGSTOP|SIGCONT <unit>`, with `<unit>` in the exact `BUS_ACTION_TARGET_UNITS`, run through `--bus-action <row> <name>`, either request-gated (the same invocation's request file) or unconditional. They are never `start`, `stop`, `restart` or `systemd-run`.
>   - **Residual.** The sandbox chooses only whether a fixed action fires.
> - **(i) Residuals.**
>   - Same-uid hostile processes are out of scope.
>   - `E7A_R2_PROC` rows read other same-uid processes' `/proc/<pid>/status` and `cmdline`.
>   - Abstract unix sockets are shared, because the network namespace is shared.
>   - The ro-bound repo exposes git-ignored repo-root files, including the operator caps file (no credential, never read).
>   - `E7A_R2_RECONCILE` rows see their own loaded credential copies.

Files relevant to this plan:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r2-security.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r2-architect.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-r1-merged.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-3-retraining_plan_r6.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md`
- `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`
- `/home/jon/breezy/scripts/ci/run_t1_lanes.sh`
- `/home/jon/breezy/tests/conftest.py`
- `/home/jon/breezy/src/breezy/runtime/trade_supervisor.py`
- `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/env.py`
- `/home/jon/breezy/deploy/systemd/replay-daily-run.sh`