# Build plan r5: ARCH-0 seam B (sandbox wrapper, bus snapshot handoff, WAL snapshot helper, C4.1 holdout ruling)

**Round r5.** This round only consolidates text. Seam B CONVERGED in round 4: both r4 reviews returned APPROVE, and the coordinator says no further design round follows. r5 applies rulings B5-R1..B5-R7 and changes nothing else in the design.

**Basis**
- **Frozen sources.**
  - ARCH Rev 9.2: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` (= `reviews/snapshots/ARCH_rev9_2.md`, sha `1b288d0e0172b233…`).
  - Errata E-7, E-7a, E-7b, E-7c, E-8, E-8a, E-9, E-11 and E-13 (`reviews/ARCH-ERRATA-rev9_2.md`).
  - The AC6 ruling (`reviews/AUT-6-r9-merged.md:11-15`).
- **Binding rulings.** B-R1..B-R8, B3-R1..B3-R10, B4-R1..B4-R8 and **B5-R1..B5-R7**, all in `reviews/ARCH-0-r1-merged.md` (lines 6-41, 58-99, 145-191 and **209-219**).
- **Inputs to r5.**
  - The r4 plan.
  - `reviews/ARCH-0-seamB-r4-security.md`: APPROVE; E-7d ADOPT; E-7e ADOPT-WITH-AMENDMENT; N1–N3.
  - `reviews/ARCH-0-seamB-r4-architect.md`: APPROVE; every score ≥ 8; E-7d ADOPT; E-7e ADOPT-WITH-AMENDMENT (B-1, B-2); the L-46 miss; non-blocking items 1–5.
- **Consumer plans** (all in the same directory):
  - `AUT-1-data-capture_plan_r12.md`
  - `AUT-2-outcome-labeling_plan_r7.md`
  - `AUT-3-retraining_plan_r6.md`
  - `AUT-4-evaluation_plan_r11.md`
  - `AUT-5-promotion-demotion_plan_r7.md`
  - `AUT-6-drift-health_plan_r15.md`
  - `AUT-7-rollback_plan_r5.md`
- **Repo state.** HEAD `d231497d` on `feat/data-capture-and-risk`. Code facts are carried from r4, which re-read them at HEAD. r5 read only plan markdown. That covers the B5-R3 lines, ARCH l.1065-1066 and l.1089, AUT-3 l.271, AUT-4 l.642, AUT-5 l.259 and AUT-6 l.1027-1064, and an L-46 re-run over AUT-1..7.
- **What I touched.** No repo file, no systemd unit and no scratch file. I only read files, with `/usr/bin/grep -n` and `sed -n`.

**MEASURED (carried from r4; r5 adds no host probe)**

| # | Fact |
|---|---|
| M1–M13 (r2) | Nested bwrap is denied in the gate. The phase-2 parent loads no Nautilus. Egress hits are only under `breezy.adapters.polymarket_us`. `--disable-userns` needs `--unshare-user`. A home tmpfs hides credentials. `--tmpfs` over an absent path fails. `--bind-fd` works. A ro notify socket delivers. The interpreter prefix is under home. `cache/` is absent, and the data root is ext4. |
| M14–M32 (r3) | **PROC shape** (`--unshare-pid`, no `--proc`): host locks and status are readable; environ and root give EACCES; kill gives ESRCH (M26). Without `--unshare-pid`, a same-uid SIGTERM succeeds (M25).<br>**Host `/run`**: it holds the docker, snapd and system-bus sockets, and `/var/run` → `/run` (M15). `--tmpfs /run` hides them (M17). The DNS re-bind needs only the resolv target (M18). `--remount-ro /run` (M19).<br>**Notify** is delivered (M20). **The user bus** works only without `--unshare-pid` (M21), and then allows a `systemd-run` escape (M22).<br>**ExecStartPre handoff** works, and `INVOCATION_ID` is shared (M23). journalctl works in-sandbox (M24).<br>**Studies lock**: two inodes exist; the `/run/user/1000/breezy-studies.lock` re-bind excludes both ways (M27).<br>**Other**: the `LoadCredential` dir is 0500 and its files 0400 (M28). The phase-1 shape reaches the user bus (M29). `SuccessExitStatus`/`ExecCondition` cannot gate (M30). The pytest early hook and ignore-collect behave as needed (M31). 3 abstract listeners exist (M32). |
| M33 | `touch` keeps the inode: on an absent path it creates one, and on an existing file ino and nlink are unchanged. `flock(1)` creates a missing lock file itself. The real lock `/run/user/1000/breezy-studies.lock` has ino 69, nlink 1, mode 0600 and owner jon. |
| M34 | ExecStartPre with the `-` prefix (systemd 259.5): a failing, timeout-killed or self-SIGKILLed `-` pre step is ignored, and `ExecStart` runs. Without `-`, the timeout-killed pre step skips `ExecStart` and the unit fails. |
| M35 | `TimeoutStartSec` re-arms per command (two 3 s pre steps plus a 3 s main under 5 s succeed in 9.05 s). `-` does not survive systemd's own timeout: a pre step longer than `TimeoutStartSec` gives `Result=timeout`, and `ExecStart` never runs. So every pre-step bound must be < `TimeoutStartSec`. |
| M36 | `%t` is not expanded in a `systemd-run -p ExecStartPre=` property. It is expanded in unit-file context (`systemd-analyze --user condition` resolves it to `/run/user/1000/…`). The service env carries `XDG_RUNTIME_DIR` and `INVOCATION_ID`. |
| M37 | Every `deploy/systemd/*.{service,timer}` name starts with `breezy-`. Instance names contain `@` and `_`; `breezy-study-failed@breezy-family-tally@pm_us_crh_v4.service.service` resolves. |
| M38 | Hung-reader budget (`Popen(start_new_session=True)`, `communicate(timeout=min(10, remaining−1))`, `killpg(SIGKILL)`, 1 s drain, no start below 0.5 s remaining). Budget 6 s over [hang+grandchild, hang, ok, ok]: 5.01 s, file written, 3 reads `skipped`, 0 stubs left. `subprocess.run(timeout=2)` orphans the grandchild. |
| M39 | pytest 9.1.1: a `-p` plugin also listed in `pytest_plugins` loads once. `-k --co` is a usage error (rc 4). `-p no:<plugin>` blocks a `-p` plugin. `PYTEST_PLUGINS=<mod>` imports before `pytest_load_initial_conftests`. |
| M40 | `show -- 'run-*'` also matches mounts, while `'run-*.service'` matches exactly the failed transient. `show -- 'breezy-*'` matches timers and slices. `--` works for `show`, `list-units` and `list-timers`. `show -- '-all'` is treated as a unit. |
| M41 | `openat(base_fd, ".bus_snapshot", O_RDONLY\|O_DIRECTORY\|O_NOFOLLOW)` on a symlinked subdirectory gives ENOTDIR. |
| M42 | `load_polymarket_us_credentials(…, require_key_file_mode=DEFAULT_KEY_FILE_MODE, require_owner_uid=None)` is at `src/breezy/adapters/polymarket_us/env.py:94-99` (`DEFAULT_KEY_FILE_MODE = 0o600` at `:87`). An inline key plus the file variable is refused as "Ambiguous" (`:150-152`). |
| M43 | `list-units --failed --all --plain --no-legend` lists `run-*`/`breezy-*` services one per line. `show -p ActiveState,SubState,NRestarts,Result,InvocationID -- <instance>` returns all 5 properties for an `@` instance. |

---

## §R5 Disposition

| r4 finding | Ruling | Applied at |
|---|---|---|
| **Sec N1 (LOW):** `credential_env` key denylist | **B5-R4.** E-7e(c) and `validate_table`: `credential_env` keys must not be `PATH`, `HOME`, `TMPDIR`, `XDG_*`, `LD_*`, `PYTHON*` or `BREEZY_AUTONOMY_*`. Test `test_credential_env_key_denylist`, plus a mutation. | `validate_table`; E-7e(c); Test Strategy; WP-B2b-1 |
| **Sec N2 (LOW):** phase 2 runs without `-I` | **B5-R5.** The E-7d Residual gains the ruled sentence verbatim. | E-7d Residual; R2 |
| **Sec N3 (INFO):** `touch` updates the lock mtime | **B5-R7.** Recorded as benign, because nothing depends on that mtime. No change. | Edge Cases |
| **Arch B-1 (blocking for filing):** AUT-3 reproduce-am has zero margin, and `touch` adds 5 s | **B5-R1.** The E-7e(f) AUT-3 parenthetical is replaced verbatim with the architect's text: 4139 → 4134; 09:35:00 + 1 + 5 + 4134 + 60 = 10:45:00Z; `runtime_s ≤ 2945`; K8 sums pre lines. | E-7e(f) AUT-3 and AUT-4; Consumer Surface (AUT-3 l.271, AUT-4 l.642) |
| **Arch B-2 (blocking for filing):** AUT-6 health exceeds ARCH l.1089, and the install bound was missing | **B5-R2.** The E-7e(f) health clause is replaced verbatim with the architect's text: ≤ start + 145 s; ARCH §5.2 l.1089 `aut6.health` is amended to "≤ 145 s \| start + 145 s"; passes end ≤ slot + 146 s; `HEALTH_PASS_BUDGET_S=90` is unchanged. | E-7e(f) AUT-6; Consumer Surface |
| **Arch L-46 miss:** AUT-2 l.1199 and 9 unclassified AUT-1 hits | **B5-R3.** "Every plan" gains the supersede sentence for ARCH §5.2 l.1066. AUT-2 l.1199 joins the Consumer Surface table. AUT-1 l.147, 167, 222, 602, 738, 1015, 1044, 1579 and 1598 are classified. I widened the regex and re-ran it over AUT-1..7, and classified every extra hit, so "every hit classified" is now true. | E-7e(f) "Every plan" and AUT-2; Consumer Surface; L-46 |
| **Arch non-blocking 1:** V11 sits in the wrong WP | **B5-R6(1).** V11 moves to WP-B2b-3. | WP table; WP-B2b-2/-3 Done |
| **Arch non-blocking 2:** AC-5 snapshot form claimed by two WPs | **B5-R6(2).** WP-B2b-2 owns the form, its test and its mutation. B2c's scope drops it. | WP table; WP-B2b-2, WP-B2c |
| **Arch non-blocking 3:** basis of the AUT-1 audit E-9 sum | **B5-R6(3).** The `flock -w` runs inside ExecStart's `timeout` (≤ 1500), so it is not added. AUT-1 l.881 is restated. | E-7e(f) AUT-1; Consumer Surface |
| **Arch non-blocking 4:** `install -d` missing from the daily and failed@ sums | **B5-R6(4).** Derivations are shown. Daily is ≤ 05:55:36Z and ≤ 13:25:36Z; r4's 05:56:30Z figure is superseded. failed@ is "≤ 20 s before its page". | E-7e(f) AUT-6; Consumer Surface |
| **Arch non-blocking 5:** `show -- 'breezy-*'` returns timers and slices | **B5-R6(5).** The AUT-6 health consumer filters on `Id` ending `.service` (M40). | E-7e(f) AUT-6; Consumer Surface; consumer tests |

**WP sizes are unchanged.** Moving V11 moves no code. The AC-5 snapshot-form lint (`unit_lint.py`), its test and its mutation were already counted in B2b-2, so B2c's mention was a duplicate scope label. The B5-R4 test and mutation are ~20 lines and fit inside B2b-1's ~950.

## Earlier dispositions (one line per round)

| Round | Outcome |
|---|---|
| r4 (B4-R1..R8) | **Bus-snapshot directory:** `mkdirat` + `openat O_DIRECTORY\|O_NOFOLLOW`, fstat checks, `dir_fd` create, regex/`S_ISREG` sweep under a non-blocking flock (sec F1). **Gate:** confirm file (C-1); `env -u PYTEST_PLUGINS -u PYTEST_ADDOPTS` with a condition-6 backstop (C-2). **Instances:** re-validated, with `--` before units (F3). Writes only after checks (F4). **Studies lock:** `touch` pre line (F5/N4). **Statements:** DNS/cmdline residuals and the pid-namespace rule (F6, F8). **`--bus-action` removed;** the drill and guard are an unwrapped residual (ruling (d)). AUT-2 `credential_env` (N11). Snapshot budget plus `-` prefix plus mapping (N1). L-46 re-search: AUT-2 l.408/953, AUT-3 l.267, AUT-6 l.1046 (N2). `RUN_TRANSIENT_SHOW_ARGV` and the `-p` grammar (N3). Per-unit E-9 table (N6). Three-way B2b split (N10). S-5 `IN_PROCESS_STUDIES_LOCK_UNITS`; S-6 per-command bound lint; S-7 literal-path transients; S-8 AUT-6 V-6 rewrite; S-9 cite `env.py:94-99`. |
| r3 (B3-R1..R10) | `--tmpfs /run` with exact re-binds and `--remount-ro /run`. No bus in any sandbox, so the ExecStartPre handoff is used. PROC shape `--unshare-pid` without `--proc`. Early hook plus ignore-collect with 7 conditions; elif chain; exact tokens. Import deny-list. Supervisor 16:45–16:48 interplay. Witness file; E-7d filed first. L-46 consumer search. `XDG_CACHE_HOME`; `mktemp` basetemp. S-1..S-4. |
| r2 (B-R1..B-R8, Sec-6..13, Arch-5..17) | Two-phase gate; blocker; `SHARED_WRITE_SITES`; `O_TMPFILE` probe; nofollow and fd binds; home tmpfs; placement `runtime/autonomy_sandbox/`; stdlib-only contract. Digests and quiescence; fstat walks; `WRAPPER_CODE_FILES`; notifier fallback set; lint scope; G6 → `exec_snapshot(False)`; E-13 tests at AUT-4 paths. |

---

## Acceptance Criteria

**AC-1: shared wrapper (E-7a rule 1, E-7c, E-13 ER-1, E-7e(c))**
1. **Invocation.** `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap ROW CMD [ARGS…]`, or `… --bus-snapshot ROW`.
   - `ROW` must fullmatch `^breezy-[a-z0-9-]+(@[a-z0-9-]*)?([.#][a-z0-9-]+)?$`, else exit 64. An unknown row exits 78.
   - **Unit check.** Read `/proc/self/cgroup`; it must contain exactly one `0::<path>` line. The leaf must end `.service` and either:
     - equal a `units` entry, or
     - for a `name@` entry, be `name@<instance>.service` with the instance fullmatching `^[a-z0-9][a-z0-9@_.-]{0,200}$`.

     Anything else exits 78.
   - The README states that the unit check is integrity against misconfiguration, not an authorisation boundary.
2. **Bind integrity.**
   - Base-relative binds resolve against `SandboxRoots.data_root`, or against `ALTERNATE_BIND_BASES[row.bind_base]` for `E7_FIXTURE_ROOT` rows.
   - Each path is walked per component with `O_PATH|O_DIRECTORY|O_NOFOLLOW`. Each bind must have a dev/ino distinct from `state/`, its ancestors and the data root, sit on the base's device, and not nest. Binds are passed with `--bind-fd`.
   - Config files and dirs use `--ro-bind-fd` with the r2 checks.
   - Any violation exits 78. The wrapper never creates a bind source.
3. **Argv.** `os.execv("/usr/bin/bwrap", argv)`, no shell, in this order:
   1. `--unshare-user --disable-userns --assert-userns-disabled --unshare-pid`
   2. `--ro-bind / /`
   3. `--tmpfs /run`
   4. `--dev /dev`; `--proc /proc` except on `host_proc` rows (M26)
   5. `--size N --tmpfs /tmp`
   6. `--tmpfs <home>`, then `--ro-bind` each `HOME_REBINDS` entry: the repo, the interpreter prefix if it is under home, the data root, and the fixture base on `E7_FIXTURE_ROOT` rows
   7. `/run` re-binds `run_rebinds(row, roots, environ)`, exactly:
      - (a) DNS rows: the `/etc/resolv.conf` target, if it is under `/run/` and regular, via `--ro-bind-fd`;
      - (b) `E7A_R2_NOTIFY`: `$NOTIFY_SOCKET` under `/run/user/<uid>/systemd/`, `S_ISSOCK`, owned by uid;
      - (c) `E7_STUDIES_LOCK`: `/run/user/<uid>/breezy-studies.lock`, `lstat` regular, owned by uid, `st_nlink == 1`, via `--ro-bind-fd`. A missing file exits 78, and the wrapper never creates it (the unit's `touch` line does, AC-5);
      - (d) `E7A_R2_RECONCILE`: `$CREDENTIALS_DIRECTORY` must equal `/run/user/<uid>/credentials/<cgroup leaf>`, be mode 0500 and owned by uid, and contain exactly the `credential_names` as 0400 regular files; bound via `--ro-bind-fd`.
   8. `--remount-ro /run`
   9. `--ro-bind-fd` config
   10. `--bind-fd` binds
   11. `--remount-ro <home>`
   12. `--new-session --die-with-parent`
   13. `--chdir`: the cwd if it is inside the repo or the base, else `/`
   14. `--setenv TMPDIR /tmp --setenv XDG_CACHE_HOME /tmp/.cache --setenv BREEZY_AUTONOMY_BWRAP_ROW <row> --unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`, then for each `credential_env` item `--setenv <VAR> <$CREDENTIALS_DIRECTORY>/<name>`, sorted by VAR. The VAR keys are denylist-checked by `validate_table` (B5-R4).
   15. `--`, then the command.
4. `--size` precedes `--tmpfs /tmp`. A malformed `tmpfs_size_bytes` fails closed (E-13).
5. **Exits and fallback.**
   - Exits 126 and 127 behave as in r2.
   - Fallback applies only to `NOTIFIER_FALLBACK_ROWS` (empty in seam B), only after every 64/78 check, with a 2 s preflight.
   - `degraded_write_target` is invoked by the caller, and the consumers' closure tests enforce its use.
6. The wrapper file and every package module lie outside every bind.

**AC-2: self-probe (E-7 rule 2, B-R4, B3-R1; AUT-6 r15 l.260-263 vocabulary).** `run_self_probe(row, *, roots=None, environ=os.environ)`:
1. `environ["BREEZY_AUTONOMY_BWRAP_ROW"] == row` must hold before any open, else `env_row`.
2. **Degraded:** notifier rows return `ok=False, degraded=True`; other rows give `degraded_forged`.
3. **Negatives, from the table only:** `state/`, `registry/` if unbound, the data root, the repo root, and the unbound ancestors of each bind.
   - Each must be a directory owned by euid.
   - `O_TMPFILE|O_WRONLY` must fail with exactly EROFS; on EOPNOTSUPP, fall back to statvfs plus mountinfo.
   - Codes: `negative`, `negative_registry`, `negative_unverifiable`.
4. **Positives:** `tmpfile`/`subdir` per bind. Failures give `positive_<bind>` or `probe_residue`.
5. **Credentials:** `~/.config/breezy`, `~/.ssh`, `~/.aws`, `~/.gnupg` and `~/.netrc` must give ENOENT, and the home listing must be ⊆ the re-binds; otherwise `credentials_visible`.
6. **`/run`:**
   - the docker, snapd, lxd and system-bus connects must give ENOENT, else `host_socket_visible`;
   - the user bus and `systemd/private` must give ENOENT, else `user_bus_visible`;
   - a nofollow walk of `/run` must be ⊆ `run_rebinds` and their ancestors; an extra socket gives `host_socket_visible`, and any other extra gives `run_not_private`;
   - `O_TMPFILE` on `/run` must give EROFS, else `run_not_readonly`.
7. `/tmp` must be a tmpfs on which `O_TMPFILE` succeeds, else `tmp_not_private`.
8. **Pid namespace:** `/proc/1/comm == "bwrap"`, or on `host_proc` rows `int(readlink("/proc/self")) != getpid()`; else `pid_ns`. This is an integrity check, not a boundary.
- **Caller contract.** `require_sandbox(row)` raises `SandboxIntegrityError(code)`. Codes carry no path. The caller prints `<UNIT> INTEGRITY bwrap_probe_failed direction=<code>`, delivers CRITICAL and exits 3.

**AC-3: WAL snapshot helper (E-8 as amended by E-7e(b), E-8a, E-7a rule 3).** Unchanged from r3: the API, the copy order, recovery, the exact `SnapshotFailureReason` set, and the supervisor interplay at 16:45–16:48.
- **Interplay cases.**
  - (i) A STOP_PRIOR poll that is already running reads "not free" within its 20 bounded attempts.
  - (ii) A STOP_PRIOR that starts during the hold gives one false CRITICAL `TRADE_SUPERVISOR_STOP_PRIOR_REFUSED` and no SIGTERM.
  - LAUNCH and boot retry cannot run in this window.
- **Mitigation.** AUT-5's `take_flock=True` runs only after the day's STOP_PRIOR decision line exists.
- **Residual.** A supervisor restart inside [16:45, 16:48). The hold is ≤ 1 s.

**AC-4: shared write sites (B-R3).** `SHARED_WRITE_SITES` holds exactly:
- the `self_probe` sites (B2b-3);
- the `bus_handoff` sites: `mkdirat`, the snapshot create, the in-sandbox read-unlink and the sweep unlink (B2c);
- the `wal_snapshot` sites (B3).

`cache_dir_is_own_module_constant` is unchanged from r2.

**AC-5: unit-file lint (E-7a rule 1)**
- **Scope.**
  - Units: (⋃ `row.units` ∪ `AUTONOMY_OWNED_UNITS`), plus every unit file naming the wrapper, plus the exact `UNWRAPPED_RESIDUAL_UNITS: Final[Mapping[str, str]]` (unit → E-7a rule-5 citation; empty in seam B).
  - `UNWRAPPED_RESIDUAL_UNITS` is disjoint from the owned and row units, and its units must not name the wrapper.
  - Files: `*.service`, `*.timer` and `*.d/*.conf`. The tripwire check and the owned-units-have-files check are kept.
- **Units that only name the wrapper** (for example the recorder): only their wrapper lines are linted, as `timeout -k` → wrapper → a row listing that unit. A recorder-shaped control is included.
- **Owned and row units:**
  - every `ExecStart=`/`ExecStopPost=` goes `timeout -k` → (`flock -w`) → wrapper → row, with no `+` or `!` prefix;
  - there is no `ExecStartPost=`;
  - every `OnFailure=` target is in scope and wrapped; an owned unit naming `breezy-study-failed@` is red, with that name in the message;
  - `E7A_R2_NOTIFY` units carry `NotifyAccess=all`;
  - `E7A_R2_RECONCILE` units carry exactly one `LoadCredential=` per `credential_names` entry.
- **`ExecStartPre=` lines are only these, in this order:**
  1. bounded `install -d`/`chmod` lines (AUT-5 r7 l.259 shape, `timeout -k 1 4`, so T+K = 5 s);
  2. iff `row.studies_lock`: exactly `-/usr/bin/timeout -k 1 4 /usr/bin/touch %t/breezy-studies.lock`. `install` is refused for the lock because it replaces the inode;
  3. iff `row.bus_reads`: exactly `-/usr/bin/timeout -k 2 <B+3> /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap --bus-snapshot <row>`, with `B = row.bus_snapshot_budget_s`, as the **last** pre line. A missing `-` is red. WP-B2b-2 owns this form, its test and its mutation (B5-R6(2)).
- **Bounds (M35).**
  - Each pre line's `bound = T + K` must be `< TimeoutStartSec`.
  - The unit's start-phase sum is exported as `start_phase_bound_s(unit)` for the E-9 owners.

**AC-6: C4.1 ruling.** As in r2: a byte-identical slice of `ARCH_rev9_2.md` lines 379–392, sha-pinned.

**AC-7: gate (E-7d).**
- Phase 1 runs, then phase 2, once each. The summary line is `[breezy] gate: phase1 rc=X phase2 rc=Y`, and the gate exits with the first non-zero code.
- Phase 2 is omitted only on an exact token plus a confirm file reading exactly `collect-only`.
- Phase 2 passes exactly `BWRAP_HOST_EXPECTED_TESTS` tests, with 0 skipped.
- `lint-imports` reports "N kept, 0 broken".

**AC-8: real host.** V0–V21 pass on the primary tree after the WP that enables them, and before any consumer row is filed.

**AC-9: bus snapshot handoff (B3-R2, B4-R1..R4)**
1. **Grammar.** `bus_reads: tuple[BusRead, ...]` with `BusRead(name, argv)`.
   - `argv[:3] == ("/usr/bin/systemctl", "--user", v)` with `v ∈ {"show", "list-units", "list-timers"}`.
   - Option tokens come only from this set:
     - `-p` followed by exactly one token fullmatching `^[A-Za-z,]+$`;
     - `--property=<[A-Za-z,]+>`;
     - `--all`, `--plain`, `--no-legend`, `--no-pager`, `--failed`, `--value`;
     - `--state=<[a-z]+>`, `--type=<[a-z]+>`.
   - If unit tokens are present, a single `--` precedes them and only unit tokens follow. Each must fullmatch `^breezy-[a-z0-9@._*-]+$` or be exactly `{instance}`.
   - The only `run-*` form is the exact tuple `RUN_TRANSIENT_SHOW_ARGV` (M40).
   - `bus_snapshot_bind` must be in `binds` and start with `cache/`. It is required iff `bus_reads` is non-empty, together with `bus_snapshot_budget_s ∈ [1, 25]`.
   - journalctl is not a bus read; it runs in-sandbox (M24).
2. **`--bus-snapshot ROW`** runs unsandboxed in `ExecStartPre`.
   - These must pass before anything runs or is written: AC-1 checks 1–5 (syntax 64, `validate_table`, row, cgroup, and `open_validated_binds` on `bus_snapshot_bind` only), and `INVOCATION_ID` fullmatching `^[0-9a-f]{32}$`. `os.execv` is never reached in this mode.
   - `{instance}` is substituted from the validated leaf, and each substituted token is re-checked against the unit-token regex.
   - `BUS_ENV = {PATH:/usr/bin:/bin, XDG_RUNTIME_DIR:/run/user/<uid>, LANG:C.UTF-8, SYSTEMD_PAGER:"", SYSTEMD_COLORS:"0"}`.
   - Output: `bus_snapshot/v1 {invocation_id, unit, ts_ns, budget_s, reads:[{name, argv, rc, timed_out, skipped, oversize, stdout}]}`. A stdout above 4 MiB is recorded `oversize` with an empty stdout.
   - Exit codes: 0 when written; 64/78 on a config error; 73 on a write failure.
3. **`read_bus_snapshot(row, *, environ)`** runs in-sandbox.
   - It opens `.bus_snapshot` with `O_DIRECTORY|O_NOFOLLOW`, then `<INVOCATION_ID>.json` nofollow via `dir_fd`, and reads the file once.
   - It requires the `invocation_id` and unit to match, unlinks the file via `dir_fd`, and returns `BusSnapshot`.
   - Otherwise it raises `BusSnapshotError("bus_snapshot_missing" | "bus_snapshot_stale")`. It never returns an empty snapshot.
4. **Budget (M38).**
   - `deadline = monotonic() + B`. Each read gets `min(BUS_READ_TIMEOUT_S=10, deadline − now − 1.0)`. A read with less than 0.5 s left is `skipped`.
   - Each read is `Popen(argv, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, env=BUS_ENV, start_new_session=True, close_fds=True)`, then `communicate(timeout)`. On expiry: `killpg(pid, SIGKILL)`, a 1 s drain, then close.
   - The file is always written when the config is valid. If the outer `timeout` kills the mode itself, the `-` prefix lets `ExecStart` run (M34), and the reader raises `bus_snapshot_missing`.
5. **Directory discipline (M41).**
   - `mkdirat(bind_fd, ".bus_snapshot", 0o700)` (EEXIST is accepted), then `openat(bind_fd, ".bus_snapshot", O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC)`.
   - `fstat` must show `S_ISDIR`, `st_uid == euid`, `st_mode & 0o077 == 0`, `st_dev == bind.st_dev`, and `(dev, ino) ∉ forbidden_dirs(roots)`. Otherwise exit 78, with nothing written and nothing swept.
   - The file is created as `<ID>.json` with `O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW|O_CLOEXEC, 0o600, dir_fd`, then fsynced.
   - **Sweep:**
     - take `flock(dir_fd, LOCK_EX|LOCK_NB)`; on contention, skip the sweep;
     - list with `scandir(dir_fd)`;
     - delete only names matching `^[0-9a-f]{32}\.json$` whose `lstat` shows `S_ISREG` and whose `mtime` is older than 24 h, via `unlink(name, dir_fd=)`.
6. **Consumer mapping contract** (binding in E-7e(f)).
   - A whole-snapshot `bus_snapshot_missing` or `_stale` gives health UNKNOWN: `passes_unknown_streak` increments, and health never reports zero failures. failed@ and daily give a CRITICAL page.
   - A per-read `rc≠0`, `timed_out`, `skipped` or `oversize` keeps each consumer's existing failed-read semantics (AUT-6 r15 l.488, l.957).
   - There is no state-changing bus call: the grammar refuses `kill`, `start`, `stop`, `restart`, `try-restart` and `systemd-run`.

## Edge Cases and NFRs

| Case | Handling |
|---|---|
| Node up and holding the intent flock | `take_flock=True` gives `LOCK_HELD` after 3 tries; `False` gives an advisory result. |
| Helper holds while the node boots or a supervisor probes | The node fails fast. The supervisor behaves as in AC-3. |
| Docker, snapd, lxd or bus sockets | Hidden by `--tmpfs /run` (M17). |
| DNS row | Only the resolv target is re-bound (M18). `127.0.0.53` is reachable (R15). |
| `/proc/locks`, `/proc/<pid>` reader | `host_proc` row (M26). Never index `/proc` by a namespace pid. |
| User manager hung | Reads time out inside the budget and are recorded `timed_out`/`skipped` (M38). If the mode itself dies, `-` lets the main step run and the snapshot is `missing`. AC-9.6 applies. |
| Pre step outlives `TimeoutStartSec` | Forbidden by the lint (`B + 5 < TimeoutStartSec`, M35). |
| Sandbox plants a symlink at `.bus_snapshot` | ENOTDIR gives 78. Nothing is written or swept (M41). |
| Sandbox plants non-matching files | The sweep ignores them. |
| Snapshot from an earlier invocation | `bus_snapshot_stale`; swept after 24 h. |
| Two invocations of a template row share the bind | Each writes a unique `<ID>.json`, and the sweep flock is non-blocking. |
| Failed `run-*` transient (AUT-6 health) | `RUN_TRANSIENT_SHOW_ARGV` (M40). |
| `show -- 'breezy-*'` returns timers and slices (M40) | The AUT-6 health consumer filters on `Id` ending `.service` (B5-R6(5)). |
| Studies lock missing after reboot | The `touch` pre line creates it (M33). If that fails, the wrapper gives 78, the unit fails, and `OnFailure=` pages. |
| `touch` updates the lock's mtime (sec r4 N3) | Benign: nothing depends on that mtime (B5-R7). |
| AUT-1 drill and guard | Unwrapped residual (`UNWRAPPED_RESIDUAL_UNITS`, filled by AUT-1). |
| Credential file (AUT-2) | `LoadCredential=` plus `credential_env` `--setenv`. An inline key fails closed (M42). Keys on the denylist are refused by `validate_table` (B5-R4). |
| Phase 2 run by hand without `-p` | No early witness, so rc 2. |
| `PYTEST_PLUGINS`/`PYTEST_ADDOPTS` set in the shell | Scrubbed for phase 2. Condition 6 refuses if either is present (M39). |
| Phase-2 caller sets `PYTHONPATH`/`sitecustomize` | Operator-controlled environment, the same exposure as phase 1. Stated in the E-7d Residual (B5-R5). |
| Phase-1 plugin disabled | The confirm file lacks `collect-only`, so phase 2 runs. |

**NFRs**
- Wrapper overhead p95 ≤ 50 ms (V9).
- `--bus-snapshot` wall ≤ B, and ≤ B + 5 including the outer kill.
- The package is stdlib-only.
- A snapshot of today's store takes ≤ 1 s.
- Phase 2 takes ≤ 120 s per lane.
- No absolute path appears in stderr or in reason codes.

## Architecture and Data Flow

**Placement (B-R8).** The package lives at `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/`.
- Import-linter contract: `"ARCH-0 seam B: the autonomy sandbox package is stdlib-only"`. It forbids `nautilus_trader`, `breezy.adapters` and `breezy.strategy`, with `allow_indirect_imports=false`.
- There is no seam-A dependency.

**Native reuse (L-1).** Reused:
- bubblewrap;
- systemd: `ExecStartPre` with the `-` prefix (M34), `$INVOCATION_ID` (M23), `%t` (M36), `LoadCredential=` (M28) and `MONITOR_*`;
- `touch(1)`/`flock(1)` (M33);
- pytest `-p`, `pytest_load_initial_conftests` and `pytest_ignore_collect`;
- stdlib `sqlite3`.

New code exists only for the handoff file, because `StandardOutput=` applies to the whole unit.

```python
# table.py
KNOWN_EXCEPTIONS: Final = frozenset({"E7A_R2_PROC","E7A_R2_NOTIFY","E7A_R2_RECONCILE",
    "E7B_EVAL_OFFLINE_ADAPTER_MODULES","E7_CONFIG_DIR","E7_STUDIES_LOCK","E7_FIXTURE_ROOT"})      # 7 labels
ALTERNATE_BIND_BASES: Final = MappingProxyType({"aut4_fixture": ".local/share/breezy-autonomy-fixture"})
NOTIFIER_FALLBACK_ROWS: Final[frozenset[str]] = frozenset(); AUTONOMY_OWNED_UNITS: Final[frozenset[str]] = frozenset()
UNWRAPPED_RESIDUAL_UNITS: Final[Mapping[str, str]] = MappingProxyType({})
CREDENTIAL_ENV_DENIED_EXACT: Final = frozenset({"PATH","HOME","TMPDIR"})                        # B5-R4
CREDENTIAL_ENV_DENIED_PREFIXES: Final = ("XDG_","LD_","PYTHON","BREEZY_AUTONOMY_")               # B5-R4
RUN_TRANSIENT_SHOW_ARGV: Final = ("/usr/bin/systemctl","--user","show","-p",
    "Id,Description,ExecStart,InvocationID,Result,Transient","--","run-*.service")
@dataclass(frozen=True, slots=True) class BusRead: name: str; argv: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class SandboxRoots: home: Path; data_root: Path; repo_root: Path; python_prefix: Path; uid: int; run_user: Path
@dataclass(frozen=True, slots=True)
class BwrapRow:
    name: str; owner_plan: str; units: frozenset[str]; binds: tuple[str, ...]; entry_modules: tuple[str, ...]
    resolves_dns: bool                                         # required
    bind_base: str = "data_root"; host_proc: bool = False; studies_lock: bool = False
    credential_names: tuple[str, ...] = (); credential_env: Mapping[str, str] = MappingProxyType({})
    config_ro_binds: tuple[str, ...] = (); config_ro_dirs: tuple[str, ...] = ()
    bus_reads: tuple[BusRead, ...] = (); bus_snapshot_bind: str | None = None; bus_snapshot_budget_s: int | None = None
    tmpfs_size_bytes: int | None = None; exceptions: frozenset[str] = frozenset(); notifier_fallback: bool = False
    positive_probe: Mapping[str, PositiveProbe] = MappingProxyType({})
def validate_table(table=AUTONOMY_BWRAP_TABLE) -> None
def self_probe_plan(row, roots) -> SelfProbePlan
# binds.py       open_validated_binds(row, roots) -> ctx[OpenedBinds]; walk_nofollow(path, *, kind); forbidden_dirs(roots)
# run_mounts.py  run_rebinds(row, roots, environ) -> tuple[RunRebind, ...]
# bwrap.py       build_bwrap_argv(row, command, *, roots, opened, environ, cwd) -> list[str]; current_unit_name(cgroup_text)
#                main(argv, *, roots=None, cgroup_path=..., bwrap_path=BWRAP_PATH, execv=os.execv, snapshot=None) -> int
# unit_lint.py   lint_units(unit_dir, table) -> tuple[LintError, ...]; start_phase_bound_s(unit) -> int
# self_probe.py  run_self_probe / require_sandbox / degraded_write_target
# bus_handoff.py write_bus_snapshot(row, *, roots, environ, unit, popen=subprocess.Popen, clock=time.monotonic) -> int
#                read_bus_snapshot(row, *, environ, roots=None) -> BusSnapshot
# wal_snapshot.py wal_snapshot / exec_snapshot / connect_snapshot_readonly
# write_sites.py SHARED_WRITE_SITES; WRAPPER_CODE_FILES
# selftest_cli.py python -I -m breezy.runtime.autonomy_sandbox.selftest_cli [--bus-snapshot] [--proc-checks] [--exec-snapshot N]
```

**`validate_table`** (exact sets; widened only per L-12)
- **Each exception flag corresponds to exactly one label:**
  - `host_proc` ⇔ `E7A_R2_PROC`;
  - `studies_lock` ⇔ `E7_STUDIES_LOCK`;
  - non-empty `credential_names` ⇔ `E7A_R2_RECONCILE` ⇔ non-empty `credential_env`. The `credential_env` values must equal `set(credential_names)`, and its keys must fullmatch `^[A-Z][A-Z0-9_]*$`;
  - **(B5-R4)** a key must not be in `CREDENTIAL_ENV_DENIED_EXACT` (`PATH`, `HOME`, `TMPDIR`) or start with a `CREDENTIAL_ENV_DENIED_PREFIXES` entry (`XDG_*`, `LD_*`, `PYTHON*`, `BREEZY_AUTONOMY_*`). The reason: `--setenv` runs after the fixed environment, so a table edit could otherwise override it;
  - `bind_base != "data_root"` ⇔ `E7_FIXTURE_ROOT`.
- **Bus rules** follow AC-9.1:
  - read names are unique;
  - `bus_snapshot_bind` is in `binds` and is a `cache/` bind;
  - the budget is in [1, 25] iff `bus_reads` is non-empty.
- There is no user-bus label and no bus-action label.

**Seam B rows** (run only as transient `systemd-run --unit=<name>` units)

| Row | Binds | Flags |
|---|---|---|
| `breezy-autonomy-selftest` | `cache/autonomy_selftest` | `resolves_dns=True`; `bus_reads=(BusRead("self_show", ("/usr/bin/systemctl","--user","show","-p","Id,ActiveState","--","breezy-autonomy-selftest.service")),)`; `bus_snapshot_bind="cache/autonomy_selftest"`; `bus_snapshot_budget_s=10` |
| `breezy-autonomy-selftest-notify` | `cache/autonomy_selftest` | `E7A_R2_NOTIFY`, `resolves_dns=False` |
| `breezy-autonomy-selftest-proc` | `cache/autonomy_selftest` | `E7A_R2_PROC` + `E7_STUDIES_LOCK`, `host_proc=True`, `studies_lock=True`, `resolves_dns=False` |

**Data flow (wrapped unit)**
1. `ExecStartPre=` lines, in AC-5 order:
   - `install -d`;
   - `-…touch %t/breezy-studies.lock` (studies rows);
   - `-/usr/bin/timeout -k 2 <B+3> /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap --bus-snapshot <row>` (bus rows).
2. `ExecStart=/usr/bin/timeout -k … [flock -w …] /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap <row> <cmd…>`. The shebang `/home/jon/breezy/.venv/bin/python3 -I` calls `bwrap.main`.
3. Checks, in order: ROW 64 → `validate_table` 78 → row 78 → cgroup 78 → binds 78 → `run_rebinds` 78 → command 127/126 → bwrap present → notifier preflight → `execv`.
4. Inside the sandbox: `require_sandbox(row)`, then optionally `read_bus_snapshot(row)`.

**Gate (E-7d; WP-B2a)**
- **`/home/jon/breezy/tests/support/bwrap_host_phase.py`:**
  - **Constants and members:** `BWRAP_HOST_PHASE_ENV_VAR`, `COLLECT_ONLY_CLAIM_ENV_VAR`, `COLLECT_ONLY_CONFIRM_FILE_ENV_VAR = "BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE"`, `BWRAP_HOST_TEST_FILES`, `BWRAP_HOST_EXPECTED_TESTS`, `Phase2ImportBlocker`, `phase2_admission(...)`, `module_name_for_path`.
  - **`pytest_load_initial_conftests`:** in phase 2, the witness and condition-6 checks (`SystemExit(2)`). In phase 1 it does nothing.
  - **`pytest_ignore_collect(tryfirst)`:** active in phase 2.
  - **`pytest_configure`:**
    - registers the marker;
    - in phase 1 with the confirm-file variable set, opens that path `O_WRONLY|O_TRUNC|O_NOFOLLOW` and writes `collect-only` iff `config.option.collectonly`, else `run`;
    - in phase 1, a claim of `"1"` while collect-only is false gives rc 2.
  - **`modifyitems`, `runtest_logreport` and `sessionfinish`:** as in r3.
- **Admission requires all seven conditions:**
  1. the variable is exactly `"1"`;
  2. there is no attestation;
  3. the blocker is at `meta_path[0]`;
  4. every egress hit is refused;
  5. no refused module is loaded;
  6. the early witness exists; positional args come only from the registry; there is no widening option (`--rootdir`≠repo, `--confcutdir`, `--noconftest`, `--pyargs`, `-c`/`--config-file`, a non-default `--import-mode`, an extra `-p`); and `PYTEST_PLUGINS` and `PYTEST_ADDOPTS` are absent from `os.environ`;
  7. ignore-collect is active.
- **Root conftest:** exactly C1–C4, as in r3.
- **Script `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`:**
  ```bash
  unset BREEZY_BWRAP_HOST_PHASE BREEZY_GATE_COLLECT_ONLY_CLAIM BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE
  GATE_DIR="${BREEZY_GATE_DIR:-$HOME/.cache/breezy-gate}"; install -d -m 0700 "$GATE_DIR"
  P1_CONFIRM=$(mktemp "$GATE_DIR/p1-confirm.XXXXXX"); P2_BT=""; trap 'rm -rf -- "$P1_CONFIRM" ${P2_BT:+"$P2_BT"}' EXIT
  collect_only=0; for a in "$@"; do case "$a" in --collect-only|--co|--collectonly) collect_only=1;; esac; done
  export BREEZY_GATE_COLLECT_ONLY_CLAIM="$collect_only" BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE="$P1_CONFIRM"; phase1_rc=0
  if bwrap_ok; then echo "[breezy] OS egress block: bubblewrap network namespace" >&2; run_bwrap -p tests.support.bwrap_host_phase "$@" || phase1_rc=$?
  elif unshare_ok; then echo "[breezy] OS egress block: unshare network namespace" >&2; run_unshare -p tests.support.bwrap_host_phase "$@" || phase1_rc=$?
  else refuse_message; exit 3; fi
  if [[ "$collect_only" == 1 && "$(cat -- "$P1_CONFIRM")" == "collect-only" ]]; then
    echo "[breezy] gate: phase1 rc=$phase1_rc phase2 omitted (collect-only confirmed)" >&2; exit "$phase1_rc"; fi
  phase2_rc=0; run_phase2 || phase2_rc=$?
  echo "[breezy] gate: phase1 rc=$phase1_rc phase2 rc=$phase2_rc" >&2
  [[ "$phase1_rc" -ne 0 ]] && exit "$phase1_rc"; exit "$phase2_rc"
  ```
  - `run_bwrap` and `run_unshare` lose `exec`.
  - `run_phase2`:
    1. refuses with 3 on an attestation, an absent bwrap or a failed precheck;
    2. loads the registry via `"$PYTHON" -I -c` and refuses an empty one;
    3. sets `P2_BT=$(mktemp -d "$GATE_DIR/phase2-bt.XXXXXX")`;
    4. runs `env -u BREEZY_TEST_OS_EGRESS_BLOCK -u BREEZY_GATE_COLLECT_ONLY_CLAIM -u BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE -u PYTEST_PLUGINS -u PYTEST_ADDOPTS BREEZY_BWRAP_HOST_PHASE=1 "$PYTHON" -m pytest -p tests.support.bwrap_host_phase -p no:randomly -p no:cacheprovider -m bwrap_host --basetemp="$P2_BT" "${files[@]}"`.

    It runs without `-I`, because worktrees need `PYTHONPATH`; see the E-7d Residual.
  - User args never reach phase 2. The N5 pin text is kept.
- **Harness `/home/jon/breezy/tests/support/bwrap_harness.py`:** `run_raw_true()` (B2a); `run_in_row` and `make_roots` (B2b-3). Every child gets `--unshare-net` and an explicit env.

## Consumer Surface (source for E-7e(f))

**L-46 re-search, r5 (B5-R3).**
- **Search.** `/usr/bin/grep -n -E "OnFailure=|systemctl|run-\*|systemd-run|studies\.lock"` over the seven plans in Basis. This regex is broader than r4's.
- **Classification.** Every hit is now classified. A hit that is not in the table below is one of three things, and is unaffected:
  - a host or verification step run unwrapped by a human or an agent;
  - descriptive text;
  - a line that already names `breezy-autonomy-failed@`.
- **Unaffected hits, per plan:**
  - **AUT-1:**
    - l.91, 104, 105, 124, 546, 692, 697, 708, 1058, 1132, 1209, 1314, 1394, 1416, 1621 (r4).
    - **r5 (B5-R3):**
      - l.147 is descriptive: the recorder liveness design row, whose "`OnFailure=` reaches AUT-6's notifier" is already X-4.
      - l.167 is descriptive: the stop-hook rationale. The hook itself is the stop-hook row below.
      - l.222 is descriptive: the WP dependency row.
      - l.602 is descriptive: a relay of AUT-6-owned contract tests ("`OnFailure=` on every member"), already X-4.
      - l.738 is descriptive.
      - l.1015 is descriptive: WP3 step-2 sequencing that already names `breezy-autonomy-failed@`.
      - l.1044 is a host step: V-8 runs on a scratch unwrapped `claude-aut1wp0-*` unit with a scratch `OnFailure=` target.
      - l.1579 and 1598 are descriptive disposition rows, already `breezy-autonomy-failed@%n.service`.
      - Also from the wider regex: l.15, 260, 595, 660, 896 and 1240 already name `breezy-autonomy-failed@%n.service` on the recorder; l.857 and 858 are descriptive (the architect confirmed these).
  - **AUT-2:**
    - l.12, 848, 851, 1023, 1026, 1166, 1169 (r4).
    - **r5:** l.196, 415, 421, 950, 1045, 1047, 1057, 1088 and 1192 are descriptive (exit-path and notifier text). l.171, 469 and 954 are covered by the `breezy-aut2-recon-failed@` row. l.1188 is covered by the slot-guard row (not owned).
  - **AUT-3:** l.17, 73, 287, 360, 398, 412, 428, 441, 457.
  - **AUT-4:** l.593, 640-641, 905, 1063-1065, 1276, 1452, 1461, 1464, 1493, 1798.
  - **AUT-5:** l.16, 34, 211, 253, 451, 718, 911, 937, 1079, 1140, 1164.
  - **AUT-6:**
    - l.12, 23-72, 84, 108, 162, 448, 471, 528, 605, 747, 758, 925, 932, 997-998, 1010, 1255, 1267, 1293, 1313, 1317, 1534-1551, 1618, 1704-1767 (r14 errata text quoting the replaced ARCH wording, including the l.1729 `try-restart` argv), 1951, 1985, 2236, 2303, 2316.
    - **r5:** these lines are descriptive or are member-config text that already names `breezy-autonomy-failed@` (X-4): l.9, 10, 16, 122, 157, 253, 255, 438, 473, 669, 718, 739, 770, 778, 790, 1087, 1179, 1252, 1256, 1278, 1282, 1469, 1486, 1518, 1552, 1593, 1598, 1603, 1637, 1644, 1645, 1649, 1672, 1673, 1684, 1685, 1700, 1806, 1817, 1826, 2081, 2099, 2208, 2288, 2298, 2299, 2337, 2362.
    - l.644 and l.1073 (the #24/#31 `systemctl --user show` reads) are covered by the daily row below.
  - **AUT-7:** 0 hits.
- **Frozen ARCH, cited by consumers:**
  - l.1066 is superseded for autonomy-owned studies; see the table and E-7e(f).
  - l.1089 is amended; see E-7e(f).

| Plan:line | Today | Change (binding build item) |
|---|---|---|
| **ARCH §5.2 l.1066** | "`breezy-studies.slice` with `OnFailure=breezy-study-failed@`" | **Superseded for autonomy-owned studies** (E-7a rule 1; B5-R3). Owned studies name `breezy-autonomy-failed@%n.service`. |
| AUT-1 l.662, 710, 1112 | Stop-hook row `breezy-quote-tape.stop-hook` | AC-5 lints the wrapper line only. `resolves_dns=False`. |
| AUT-1 l.768-769, 939 | Audit `journalctl --user` | Runs in-sandbox (M24). |
| AUT-1 l.770, 939 | Audit `systemctl --user show -p … breezy-quote-tape.service` | Becomes a bus read with `--` before the unit, `bus_snapshot_bind="cache/<audit E-8 cache dir>"` and budget 10. A missing snapshot takes the audit's existing read-failure outcome (never a pass). |
| AUT-1 l.731, 733, 741, 883-884, 941 | Drill and guard | **Unwrapped residual.** Both units go into `UNWRAPPED_RESIDUAL_UNITS` with the citation "E-7a rule 5". l.875 is amended to except them. The socket bind is dropped. Re-wrapping re-files under the sec (d) conditions. |
| AUT-1 l.1045 (V-9) | (b) assumes bus reads across the ro bind | Replaced by the handoff (M23, V17). (a) is covered by M20/V12. |
| AUT-1 l.905-906 | `OnFailure=breezy-study-failed@`; `alerts.env` re-bound | `OnFailure=breezy-autonomy-failed@%n.service`. The re-bind is dropped. |
| AUT-1 l.881 | Audit `flock -w 600`; Ends-by 14:25 = 13:50 + 600 + 1500 (flock added separately, as at l.874) | Path becomes `%t/breezy-studies.lock`, outside the wrapper; no pre-create (M33). **E-9 basis (B5-R6(3)):** the `flock -w` runs inside ExecStart's `timeout` (≤ 1500, l.876), so it is not added. The end is ≤ 13:50 + 60 + [install ≤ 5] + 15 + 1500 + 5 ≤ 14:16:25, so l.881 is restated on that basis and 14:25 still holds. |
| AUT-1 l.125, 886 / l.124, 694, 887 | Rotate and register | **No change.** Not owned and not wrapped. |
| AUT-1 l.1343 | "sd_notify blocked under bwrap" | Text becomes: delivered (M20). |
| AUT-2 l.180, 468 | Reconcile reads the key file under `~/.config/breezy` | `E7A_R2_RECONCILE` with `LoadCredential=polymarket_us_secret_key:%h/.config/breezy/<keyfile>`, `credential_names=("polymarket_us_secret_key",)` and `credential_env={"POLYMARKET_US_SECRET_KEY_FILE": "polymarket_us_secret_key"}`; the key is not on the denylist. The caller passes `require_key_file_mode=0o400` (`env.py:98`). The inline var must be absent. No `env.py` or firewall-test edit. A GET-only consumer test. `resolves_dns=True`. |
| AUT-2 l.171, 469, 470, 485, 954, 1054 | `breezy-aut2-recon-failed@` | Wrapped; joins `NOTIFIER_FALLBACK_ROWS`; alerts-only closure test. |
| AUT-2 l.408, 953 | Label unit `OnFailure=breezy-study-failed@%n.service` | **`breezy-autonomy-failed@%n.service`**. |
| **AUT-2 l.1199** | "The label unit keeps `OnFailure=breezy-study-failed@` (the §5.2 studies rule)" | **Amended (B5-R3):** the label unit names `breezy-autonomy-failed@%n.service`. E-7e(f) supersedes ARCH §5.2 l.1066 for autonomy-owned studies. |
| AUT-2 l.423, 463, 953 (slot-guard part), 1188 | `slot_guard` 255 → `OnFailure=` on `breezy-score-live-trials.service` | **No change.** Not autonomy-owned. |
| AUT-2 l.467 | Label `flock -w` on the studies lock | `%t/breezy-studies.lock`. |
| AUT-2 (wrapped G6 reads) | In-place exec-store reads | `exec_snapshot(take_flock=False)`. |
| AUT-3 l.267 | Refit `NotifyAccess=main`; `OnFailure=breezy-study-failed@%n.service` | `NotifyAccess=all`; `OnFailure=breezy-autonomy-failed@%n.service` on refit and both repro units. |
| **AUT-3 l.271** | reproduce-am `TimeoutStartSec=4139`, worst end exactly 10:45:00Z | **4134** (B5-R1). 09:35:00 + 1 + 5 + 4134 + 60 = 10:45:00Z. AM eligibility becomes `runtime_s × 1.2 + 600 ≤ 4134` (`runtime_s ≤ 2945`). |
| AUT-3 l.279-283, 292 | In-process Python flock on the studies lock | `E7_STUDIES_LOCK` rows; open `/run/user/<uid>/breezy-studies.lock` `O_RDONLY\|O_CLOEXEC`; the `touch` pre line. |
| AUT-3 l.296 | Repro extract in `~/.cache/…` | Data-root `cache/refit-repro/` bind (or `/tmp`). |
| AUT-3 l.190, 282-283 | Transient drill and WP0 runs | If wrapped, pass `--unit=<row unit>` and use the literal lock path (M36). |
| AUT-4 l.661, 1228, 1401 | Fixture row | `E7_FIXTURE_ROOT`, `bind_base="aut4_fixture"`. |
| **AUT-4 l.642 (K8)** | `start + AccuracySec + TimeoutStartSec + TimeoutStopSec ≤ 10:45:00Z` | `test_pre_offline_studies_units_end_by_1045z` sums pre lines at `T + K` (B5-R1). |
| AUT-4 l.848, 871, 888, 892, 898 | `test_aut4_bwrap_rows.py`, `test_aut4_wal_reads.py` | Join the registry and count; obey E-7d R5. |
| AUT-4 l.875-884 | Blob and argv checks | `WRAPPER_CODE_FILES`; `build_bwrap_argv`. |
| AUT-4 l.634-635, 664 | `flock -w` on the studies lock | `%t/breezy-studies.lock`; no pre-create. |
| AUT-4 l.637, 848, 1311 | `OnFailure=breezy-autonomy-failed@%n` | Already correct. |
| AUT-5 l.202, 286 | `sandbox_probe` | `require_sandbox`. |
| AUT-5 l.277 | `OnFailure=breezy-study-failed@%n.service` | `breezy-autonomy-failed@%n.service` (M37). |
| AUT-5 l.259, 279 | Bounded `install -d`/`chmod` pre lines | AC-5 form 1; no change. |
| AUT-5 l.278-282, 284-285, 292, 386-388, 405, 879-880 | Engine rows, stage-S, config test, tests, allowlist, G6 | Exact-instance rows; table-derived argv test; registry; `SHARED_WRITE_SITES`; `exec_snapshot(False)`. |
| AUT-5 l.273-275 | Transient timer → installed bootstrap instance | No change. |
| AUT-5 (E-8 pass) | `take_flock=True` at 16:45 | STOP_PRIOR-line precondition. |
| AUT-6 l.203-207, 644, 802, 958, 966, 1073 | daily, health and failed@ `systemctl` reads in-sandbox | **Mechanism.** `--bus-snapshot`, with `--` in every argv.<br>**Budgets.** health 15, failed@ 10, daily 15.<br>**Binds.** New `cache/aut6_health_bus` and `cache/aut6_failed_bus` via the `install -d` pre line; daily uses `cache/aut6_daily_exec_snapshot`.<br>**Health reads:** `list-units --failed --all --plain --no-legend`; `list-units --all --type=timer --plain -- 'breezy-family-tally@*'`; `list-timers --all --plain`; `show -p <fixed set> -- 'breezy-*'`. The consumer **filters the `show` result on `Id` ending `.service`** (M40; B5-R6(5)).<br>**failed@ read:** `show -p ActiveState,SubState,NRestarts,Result,InvocationID -- {instance}`.<br>**Daily reads:** the #24/#31 shows.<br>Mapping per AC-9.6. "List before journal read" (l.958) is preserved. |
| AUT-6 l.961-962 | Failed `run-*.service` in health scope | `RUN_TRANSIENT_SHOW_ARGV`. |
| AUT-6 l.1174 (V-6) | In-row `systemctl` expected to equal outside | Rewritten: in-row `systemctl` fails; the snapshot equals the outside reads; `/proc/<node pid>/status` is readable on the PROC row. |
| AUT-6 l.247, 250 | `#evaluate` and health "no `--unshare-pid`" | `host_proc=True` (`E7A_R2_PROC`). |
| AUT-6 l.249, 671 | Daily locks `~/.local/share/breezy/breezy-studies.lock` | `E7_STUDIES_LOCK` on `/run/user/<uid>/breezy-studies.lock` plus the `touch` line; path test. |
| AUT-6 l.1071 | `IN_PROCESS_STUDIES_LOCK_UNITS` = {producer-daily} | Derived from the table rows with `studies_lock=True`. |
| AUT-6 l.249, 1444 | `~/.config/systemd/user` re-bind | `E7_CONFIG_DIR`. |
| AUT-6 l.241-243, 1334 | `--tmpfs ~/.config` assertions | Home allowlist, `--tmpfs /run`, `run_rebinds`. |
| AUT-6 l.260-262 | `O_CREAT` probe names | `O_TMPFILE`; owner precondition kept. |
| AUT-6 l.1335-1338, 1349, 1356-1357, 1375-1376 | Real-bwrap tests in unit | Move to `tests/integration/test_integrity_floor_bwrap_namespace.py` (registry); the l.1357 receiver runs inside the child. |
| AUT-6 l.1150, 1228, 1400 | `test_aut6_bwrap_rows.py` | Registry. |
| AUT-6 l.1377, 1292, 2290 | Scratch-unit `systemd-run` tests | Phase 1 (M29); R24. |
| AUT-6 l.276 vs l.1046 | Producer-daily `OnFailure=breezy-study-failed@%n` | `breezy-autonomy-failed@%n.service`. |
| AUT-6 l.1027 (R-d) | "only the intraday producer has two start commands" | Health has 2 pre lines (install, snapshot), failed@ 2 (install, snapshot) and daily 3 (install, touch, snapshot). Recount via `start_phase_bound_s`. |
| **AUT-6 l.1037, 1061, 1064 and ARCH l.1089** | health ≤ start + 121 s (16:43:01 for the 16:41 pass); daily ≤ 05:55:06Z / 13:25:06Z; ARCH `aut6.health` "≤ 120 s \| start + 120 s" | **Health:** ≤ start + 5 + 20 + 115 + 5 = start + 145 s; ARCH l.1089 is amended (B5-R2); passes end ≤ slot + 146 s (16:43:26 for the 16:41 pass).<br>**Daily:** ≤ 05:55:36Z / 13:25:36Z.<br>**failed@:** ≤ 20 s before its page (B5-R6(4)). |
| AUT-6 l.959 | `HEALTH_PASS_BUDGET_S=90` within `TimeoutStartSec=115` | Unchanged. |
| AUT-6 (notifier) | `breezy-autonomy-failed@` | `NOTIFIER_FALLBACK_ROWS`; closure test. |
| AUT-7 r5 | Inherits the engine rows | Covered. |
| All rows | Alert delivery | `resolves_dns=True` wherever the closure can deliver; a test per row. |

## File-by-File Plan

| Path | N/M | Content | WP |
|---|---|---|---|
| `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` | N | C4.1 slice | B1 |
| `/home/jon/breezy/tests/unit/test_holdout_ruling_filed_verbatim.py` | N | 5 tests | B1 |
| `/home/jon/breezy/tests/support/bwrap_host_phase.py` | N | Plugin, blocker, admission, registry, confirm file | B2a |
| `/home/jon/breezy/tests/support/bwrap_harness.py` | N/M | `run_raw_true` (B2a); `run_in_row`, `make_roots` (B2b-3) | B2a, B2b-3 |
| `/home/jon/breezy/tests/conftest.py` | M | Exactly C1–C4 | B2a |
| `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` | M | Phase chain, `-p` in phase 1, confirm file, `run_phase2`, env scrub | B2a |
| `/home/jon/breezy/tests/integration/test_bwrap_host_phase_witness.py` | N | 3 witness tests | B2a |
| `/home/jon/breezy/tests/fixtures/bwrap_host_phase/{p2_outside_registry.py,p2_imports_nautilus.py,witness_dir/conftest.py,witness_dir/p2_import_witness.py,pytest_plugins_witness.py}` | N | Child controls | B2a |
| `/home/jon/breezy/tests/unit/test_bwrap_host_phase_barrier.py`, `/home/jon/breezy/tests/unit/test_run_tests_no_egress_phases.py` | N | Gate tests | B2a |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/{__init__.py,table.py,binds.py,run_mounts.py}` | N | AC-1.1/1.2/1.3(7), `validate_table` (incl. the B5-R4 denylist) | B2b-1 |
| `/home/jon/breezy/tests/unit/{test_autonomy_sandbox_table.py,test_autonomy_bind_integrity.py,test_autonomy_run_mounts.py}` | N | Phase-1 tests | B2b-1 |
| `/home/jon/breezy/pyproject.toml` | M | One additive import-linter contract | B2b-1 |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/{bwrap.py,unit_lint.py}` | N | AC-1.3/1.4/1.5; AC-5, including the snapshot pre-line form | B2b-2 |
| `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap` | N 0755 | Shebang `-I`, `sys.exit(main(sys.argv[1:]))` | B2b-2 |
| `/home/jon/breezy/tests/unit/{test_autonomy_bwrap_argv.py,test_autonomy_units_wrapped.py}`, `/home/jon/breezy/tests/contract/test_autonomy_units.py` | N | Argv, lint, E-13 | B2b-2 |
| `/home/jon/breezy/deploy/systemd/README.md` | M | Wrapper section (B2b-2); handoff (B2c) | B2b-2, B2c |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/{self_probe.py,selftest_cli.py,write_sites.py}` | N | AC-2, AC-4 | B2b-3 |
| `/home/jon/breezy/tests/support/autonomy_write_sites.py` | N | AC6 predicate | B2b-3 |
| `/home/jon/breezy/tests/unit/{test_autonomy_self_probe.py,test_autonomy_write_sites.py}`, `/home/jon/breezy/tests/integration/test_autonomy_sandbox_namespace.py` | N | AC-2 tests; phase 2 | B2b-3 |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/bus_handoff.py` | N | AC-9 | B2c |
| `/home/jon/breezy/tests/unit/test_autonomy_bus_handoff.py`, `/home/jon/breezy/tests/integration/test_bus_handoff_namespace.py` | N | AC-9 tests | B2c |
| `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/wal_snapshot.py` | N | AC-3 | B3 |
| `/home/jon/breezy/tests/unit/test_wal_snapshot.py`, `/home/jon/breezy/tests/integration/test_wal_snapshot_namespace.py` | N | AC-3 tests | B3 |

## Test Strategy

Phase-1 files run in gate phase 1, and registry files run in phase 2. WAL fixtures go through `SqliteStateStore` (L-42). The r5 addition is tagged **(r5)**. Each test sits in the WP that lands the last code it exercises.

| File (WP) | Tests | Failure proven |
|---|---|---|
| `test_bwrap_host_phase_barrier.py` (B2a) | The r3 set, plus:<br>- `test_p2_pytest_plugins_or_addopts_env_not_admitted`;<br>- `test_p2_option_widening_refused`, with the `PYTEST_PLUGINS`/`PYTEST_ADDOPTS` cases;<br>- `test_phase1_plugin_writes_confirm_file_collect_only_or_run`;<br>- `test_phase1_plugin_loaded_once_with_dash_p_and_pytest_plugins` (M39);<br>- `test_bwrap_host_expected_tests_equals_collected_count` (+1 mutation → red). | Prevention before import |
| `test_run_tests_no_egress_phases.py` (B2a) | The r3 set, plus:<br>- `test_collect_only_claim_with_noconftest_exits_nonzero_and_runs_phase2` (`--noconftest -k --co` → rc 4, and phase 2 ran);<br>- `test_collect_only_with_plugin_disabled_runs_phase2`;<br>- `test_collect_only_confirmed_omits_phase2`;<br>- `test_phase2_env_scrubs_pytest_plugins_and_addopts`;<br>- `test_confirm_file_mode_0600_and_removed`. | Dispatch, omission |
| `test_bwrap_host_phase_witness.py` (B2a, phase 2) | 3 witness tests | B2a green at its own sha |
| `test_autonomy_sandbox_table.py` (B2b-1) | The r3 set without the bus-action tests, plus:<br>- `test_known_exceptions_exact` (7);<br>- `test_no_bus_action_or_user_bus_surface`;<br>- `test_bus_read_dash_p_takes_one_property_token`;<br>- `test_bus_read_units_follow_double_dash`;<br>- `test_run_transient_show_argv_is_only_run_form`;<br>- `test_bus_snapshot_bind_must_be_cache_bind`;<br>- `test_bus_snapshot_budget_range_and_required_with_reads`;<br>- `test_credential_env_biconditional_and_values_equal_names`;<br>- **(r5)** `test_credential_env_key_denylist`: each of `PATH`, `HOME`, `TMPDIR`, `XDG_RUNTIME_DIR`, `LD_PRELOAD`, `PYTHONPATH` and `BREEZY_AUTONOMY_BWRAP_ROW` is red, and `POLYMARKET_US_SECRET_KEY_FILE` is valid;<br>- `test_unwrapped_residual_units_disjoint_and_cited`. | Each rule has a failing fixture |
| `test_autonomy_bind_integrity.py` / `test_autonomy_run_mounts.py` (B2b-1) | The r3 set, plus `test_studies_lock_missing_is_78_never_created` and `test_cgroup_instance_leading_dash_refused`. | Alias and escape cases |
| `test_autonomy_bwrap_argv.py` (B2b-2) | The r3 set, plus `test_credential_env_emitted_as_setenv_after_fixed_env`. | Mutants as in r3 |
| `test_autonomy_units_wrapped.py` (B2b-2) | The r3 set without the `ExecStartPost` form, plus:<br>- `test_bus_snapshot_execstartpre_requires_dash_prefix_budget_timeout_and_last` (owned by B2b-2, B5-R6(2));<br>- `test_studies_lock_rows_precreate_with_touch_not_install`;<br>- `test_execstartpre_bound_below_timeoutstartsec`;<br>- `test_no_execstartpost_on_owned_units`;<br>- `test_owned_unit_naming_study_failed_notifier_is_red`;<br>- `test_start_phase_bound_sums_pre_lines`. | Non-vacuous |
| `tests/contract/test_autonomy_units.py` (B2b-2) | The two E-13 tests | E-13 |
| `test_autonomy_self_probe.py` (B2b-3) | The r3 set | No-write proof |
| `test_autonomy_write_sites.py` (B2b-3) | The r3 set | `WRAPPER_CODE_FILES` / `SHARED_WRITE_SITES` exact |
| `test_autonomy_sandbox_namespace.py` (B2b-3, phase 2) | The r3 set, plus `test_proc_row_child_namespace_pid_names_other_host_process`. | Enforcement without directives |
| `test_autonomy_bus_handoff.py` (B2c) | The r3 set without the bus-action tests, plus:<br>- `test_bus_snapshot_budget_below_outer_timeout_always_writes`;<br>- `test_bus_snapshot_hung_read_kills_process_group`;<br>- `test_bus_snapshot_dir_symlink_refused_writes_nothing_and_sweeps_nothing`;<br>- `test_bus_snapshot_dir_owner_mode_device_and_forbidden_inode_refused`;<br>- `test_bus_snapshot_sweep_deletes_only_matching_regular_files`;<br>- `test_bus_snapshot_sweep_contention_skips_sweep_not_write`;<br>- `test_bus_snapshot_instance_revalidated_and_double_dash`;<br>- `test_bus_snapshot_writes_only_after_all_checks_never_execv`;<br>- `test_read_bus_snapshot_missing_raises_never_empty`;<br>- `test_bus_handoff_production_default_runner_is_list_argv_popen_new_session` (L-55). | Stale, forged, hung, planted |
| `test_bus_handoff_namespace.py` (B2c, phase 2) | `test_in_row_systemctl_fails_and_snapshot_readable`; `test_in_row_symlink_plant_then_unsandboxed_snapshot_refuses` | End to end |
| `test_wal_snapshot.py` / `test_wal_snapshot_namespace.py` (B3) | The r3 sets (supervisor interplay ×3; r1's four) | E-8, E-7a rule 3 |

**Consumer-owned tests** (listed in E-7e(f); not seam B code):
- `test_health_bus_snapshot_missing_is_unknown` (AUT-6)
- `test_failed_notifier_pages_when_bus_snapshot_missing` (AUT-6)
- `test_daily_pages_when_bus_snapshot_missing` (AUT-6)
- **(r5)** `test_health_show_breezy_glob_filters_service_ids` (AUT-6, B5-R6(5))
- `test_in_process_studies_lock_units_derive_from_table` (AUT-6)
- `test_reconcile_is_get_only` (AUT-2)
- AUT-4 K8 `test_pre_offline_studies_units_end_by_1045z` sums pre lines (B5-R1).

**Real-host verification** (primary tree, `-I`; L-51)
- **V0.** `systemd-run --user --wait --pipe --collect -p LimitNOFILE=524288 /home/jon/breezy/scripts/ci/run_tests_no_egress.sh --basetemp=/home/jon/.cache/breezy-gate/full-bt` → exit 0, `phase1 rc=0 phase2 rc=0`, and passed = `BWRAP_HOST_EXPECTED_TESTS`. Record the wall time.
- **V1.** `install -d -m 0700 /home/jon/.local/share/breezy/cache /home/jon/.local/share/breezy/cache/autonomy_selftest`
- **V2.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest -p TimeoutStartSec=60 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap breezy-autonomy-selftest /home/jon/breezy/.venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli` → `"ok": true`, `tmp_size_kib` 262144, `home_listing` `[".local","breezy"]`.
- **V3–V8.** As in r3:
  - the `/tmp` marker is absent on the host;
  - an unknown row gives 78;
  - a unit mismatch gives 78;
  - writes to `/home/jon/.local/share/breezy/state` and `/home/jon/breezy` give EROFS;
  - `/proc/1/comm` is `bwrap`.
- **V9.** p95 ≤ 50 ms over 20 runs.
- **V10.** With the node up, `--exec-snapshot 20`; no `snap.*` appears in `state/`.
- **V11.** `WRAPPER_CODE_FILES` sha256 equals the merge sha's blobs. **(r5: enabled by WP-B2b-3.)**
- **V12.** Notify (M20 shape).
- **V13.** mtime tick.
- **V14.** The home listing is exact; `unshare -U true` fails; `/home/jon/.ssh` is absent.
- **V15.** `/run` lists `systemd`; resolv is the only file; the docker, snapd, system-bus and user-bus connects give ENOENT; `touch /run/x` gives EROFS.
- **V16.** `getaddrinfo("api.weather.gov", 443)` resolves (no request is sent).
- **V17.** `systemd-run --user --wait --pipe --collect --unit=breezy-autonomy-selftest -p TimeoutStartSec=60 -p "ExecStartPre=-/usr/bin/timeout -k 2 13 /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap --bus-snapshot breezy-autonomy-selftest" /home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap breezy-autonomy-selftest /home/jon/breezy/.venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli --bus-snapshot`. Expected:
  - `"bus_snapshot": {"self_show": {"rc": 0}}`;
  - `"in_row_systemctl": "failed"`;
  - `.bus_snapshot` is mode 0700 and holds no `<ID>.json` afterwards.
- **V18.** `--unit=breezy-autonomy-selftest-proc` with `-p "ExecStartPre=-/usr/bin/timeout -k 1 4 /usr/bin/touch /run/user/1000/breezy-studies.lock"` and `… --proc-checks`. Expected:
  - `/proc/locks` within ±5 of the host;
  - supervisor `kill(pid, 0)` → ESRCH, and `environ` → EACCES;
  - the lock inode inside equals the host's and is unchanged by `touch`.
- **V19.** Record `ss -xlH | grep -c ' @'`.
- **V20.** `systemd-analyze --user condition 'ConditionPathExists=%t/breezy-studies.lock'` → succeeded (M36).
- **V21.** V17 with the pre line replaced by `-p "ExecStartPre=-/usr/bin/timeout -k 2 3 /bin/sleep 30"` → `ExecStart` ran and printed `"bus_snapshot": "bus_snapshot_missing"` (M34).

## Work Packages

**Order:** WP-B1 ‖ WP-B2a → WP-B2b-1 → WP-B2b-2 → WP-B2b-3 → WP-B2c → WP-B3 (serial after B2a).
- E-7d is filed **before WP-B2a merges**. E-7e is filed **before WP-B2b-1 merges**.
- Each WP is gated on its own: both phases green, plus `lint-imports`.

| WP | Scope (summary) | Est. lines (code + tests) | Registry delta | Depends on | Enables V |
|---|---|---|---|---|---|
| B1 | C4.1 ruling and test | ~120 | — | — | — |
| B2a | Gate: plugin, conftest C1–C4, script, `run_raw_true`, witness, fixtures, 2 test files | ~1,000 | +1 file (witness); count = 3 | — | V0 |
| B2b-1 | `table` (incl. the B5-R4 denylist), `binds`, `run_mounts`, contract, 3 test files | ~950 | — | B2a | — |
| B2b-2 | `bwrap` (argv, cgroup, `main`), `unit_lint` (incl. the AC-5 snapshot pre-line form, its test and its mutation), wrapper script, E-13 contract tests, README, 2 test files | ~900 | — | B2b-1 | V4, V5, V9 |
| B2b-3 | `self_probe`, `selftest_cli`, `write_sites`, harness `run_in_row`/`make_roots`, AC6 predicate, 2 unit tests + 1 phase-2 file | ~950 | +1 file | B2b-2 | V1–V3, V6–V8, **V11**, V12, V14–V16, V18–V20 |
| B2c | `bus_handoff`, the `--bus-snapshot` mode, selftest `--bus-snapshot`, README, 1 unit + 1 phase-2 file | ~850 | +1 file | B2b-3 | V17, V21 |
| B3 | `wal_snapshot`, its write sites, selftest `--exec-snapshot`, 1 unit + 1 phase-2 file | ~950 | +1 file | B2c | V10, V13 |

**Counts derived from the table.**
- 7 WPs, so 7 gated seams. Total ≈ 5,720 lines; the largest seam is ≈ 1,000 lines (B2a). Sizes are unchanged from r4 (see §R5).
- Critical path: 6 serial merges (B2a → B3); B1 runs in parallel.
- Registry: 4 files after B3. `BWRAP_HOST_EXPECTED_TESTS` = 3 + the namespace-test counts of B2b-3, B2c and B3. Each count is fixed in its WP and pinned by a +1 mutation.
- Deviation (stated): B4-R8 names a two-way B2b split, but the "≤ ~1,000 lines per seam" rule forces three.
- Critical path for consumers: B2b-3 + B3 for AUT-1a/AUT-5a/AUT-6; B2c for the AUT-1 audit and AUT-6.

**WP brief invariants (prepend verbatim to every WP brief)**
> (1) Nautilus Trader is immutable; never modify, patch, fork, bypass or reimplement it. (2) `allow_short` stays `False`. (3) Never weaken or delete a safety, settlement, firewall or contract test to go green. (4) Never name or assign a value to an operator-reserved control (max daily budget, max per position); the repo-root operator file is never read or referenced by name in code or tests. (5) Never touch live-trading enablement or the NO-SEND execution-egress firewall; never write the live exec store; no probe creates a name under `state/`; the wrapper never creates a bind source. (6) Use the exact interpreter `/home/jon/breezy/.venv/bin/python`; never `uv`, `pip` or `git stash`; in a worktree set `PYTHONPATH=<tree>/src`; run the `lint-imports` console script from the tree root and require "N kept, 0 broken". (7) Run the full gate (both phases) after every merge via `systemd-run --user --wait --pipe -p LimitNOFILE=524288 /home/jon/breezy/scripts/ci/run_tests_no_egress.sh` with basetemp under `/home/jon/.cache/breezy-gate`; read EXIT before any push. (8) Read-only unless the task is a write.

**WP-B1 `docs:` C4.1 ruling**
- **Scope:** `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md`, `/home/jon/breezy/tests/unit/test_holdout_ruling_filed_verbatim.py`.
- **RED:** the file is absent. **GREEN:** a byte slice with its sha pinned. The drift note goes in the commit message.
- **Done:** gate green, and `/home/jon/breezy/tests/unit/test_probe_containment.py:550-558` green.

**WP-B2a `test:` gate phases (security-reviewed)**
- **Scope:**
  - `/home/jon/breezy/tests/support/bwrap_host_phase.py`;
  - conftest C1–C4;
  - `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`;
  - `/home/jon/breezy/tests/support/bwrap_harness.py` (`run_raw_true`);
  - the witness and the fixtures;
  - `/home/jon/breezy/tests/unit/test_bwrap_host_phase_barrier.py`, `/home/jon/breezy/tests/unit/test_run_tests_no_egress_phases.py`.
- **Verify-first:** re-run M2, M3, M31 and M39 on a scratch copy at HEAD.
- **Mutations (L-33)**, each turning a named test red:
  - drop C3 exclusivity;
  - make the blocker refuse nothing;
  - restore `exec` on l.37;
  - remove the early-hook args check;
  - make ignore-collect return None;
  - revert to two `if`s;
  - count +1;
  - drop `-p` from phase 1;
  - omit phase 2 on the token alone;
  - drop `-u PYTEST_PLUGINS`.
- **Done:** security sign-off; both phases green at this sha; N2/N3/N5/X1 unchanged and green.
- **WP-specific:** the N2 change is the exact-set addition whose absent-input path is byte-identical (`test_n2_rule_without_phase_evidence_is_unchanged`). N3, N5, X1–X3 and E0 are untouched.

**WP-B2b-1 `feat:` table, binds, `/run` set**
- **Scope:**
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/__init__.py`, `table.py`, `binds.py` and `run_mounts.py` (same directory);
  - the `/home/jon/breezy/pyproject.toml` contract;
  - `/home/jon/breezy/tests/unit/test_autonomy_sandbox_table.py`, `test_autonomy_bind_integrity.py` and `test_autonomy_run_mounts.py`.
- **Mutations:**
  - accept `run-*`;
  - accept a non-`cache/` snapshot bind;
  - create the missing lock;
  - skip the nlink check;
  - accept `credential_env` values ≠ names;
  - **(r5)** accept a denylisted `credential_env` key.
- **Done:** both phases green; lint-imports; E-7e filed.

**WP-B2b-2 `feat:` argv, wrapper entry, unit lint**
- **Scope:**
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/bwrap.py`;
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/unit_lint.py`, which owns the AC-5 snapshot pre-line form (B5-R6(2));
  - `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap`;
  - `/home/jon/breezy/tests/unit/test_autonomy_bwrap_argv.py`, `/home/jon/breezy/tests/unit/test_autonomy_units_wrapped.py`, `/home/jon/breezy/tests/contract/test_autonomy_units.py`;
  - `/home/jon/breezy/deploy/systemd/README.md`.
- **Mutations:**
  - put `--size` after `--tmpfs`;
  - drop `--tmpfs <home>`, `--tmpfs /run`, `--remount-ro /run` or `--unshare-pid`;
  - add `--proc` on a PROC row;
  - use a path `--bind`;
  - drop the cgroup check;
  - accept the snapshot pre line without `-`;
  - accept `install` for the lock;
  - drop the `bound < TimeoutStartSec` check.
- **Done:** both phases green; lint-imports; V4, V5, V9.

**WP-B2b-3 `feat:` self-probe, selftest, phase-2 namespace**
- **Scope:**
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/self_probe.py`, `selftest_cli.py` and `write_sites.py` (same directory);
  - `/home/jon/breezy/tests/support/bwrap_harness.py` (`run_in_row`, `make_roots`);
  - `/home/jon/breezy/tests/support/autonomy_write_sites.py`;
  - `/home/jon/breezy/tests/unit/test_autonomy_self_probe.py`, `/home/jon/breezy/tests/unit/test_autonomy_write_sites.py`;
  - `/home/jon/breezy/tests/integration/test_autonomy_sandbox_namespace.py` (registry + count).
- **Mutations:** accept EACCES on a negative; skip the env-row check; skip the `/run` walk.
- **Done:** both phases green; V1–V3, V6–V8, **V11**, V12, V14–V16 and V18–V20 pass on the primary tree before any consumer row.

**WP-B2c `feat:` bus snapshot handoff**
- **Scope:**
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/bus_handoff.py`;
  - the `bwrap.main` `--bus-snapshot` mode;
  - selftest `--bus-snapshot`;
  - README;
  - `/home/jon/breezy/tests/unit/test_autonomy_bus_handoff.py`, `/home/jon/breezy/tests/integration/test_bus_handoff_namespace.py` (registry + count).

  The AC-5 snapshot form is owned by B2b-2.
- **Mutations:**
  - skip the invocation check;
  - allow verb `kill` or `start`;
  - drop the budget;
  - use `subprocess.run` in place of the process-group kill;
  - drop `O_NOFOLLOW` on the subdirectory;
  - sweep without the name regex;
  - skip the instance re-check;
  - exit non-zero on a failed read.
- **Done:** both phases green; V17, V21.
- **WP-specific:** no bus call other than the AC-9.1 read verbs. Never `kill`, `start`, `stop`, `restart`, `try-restart` or `systemd-run`. No `--bus-action` surface.

**WP-B3 `feat:` WAL snapshot helper**
- **Scope:**
  - `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/wal_snapshot.py` and its `write_sites`;
  - selftest `--exec-snapshot`;
  - `/home/jon/breezy/tests/unit/test_wal_snapshot.py`, `/home/jon/breezy/tests/integration/test_wal_snapshot_namespace.py` (registry + count).
- **Mutations:**
  - remove the re-fingerprint, the tail digest, the quiescence wait or the cache flock;
  - copy `-shm`;
  - move the deadline past 16:50.
- **Done:** both phases green; lint-imports; V10, V13.
- **WP-specific:** only the cache copy is opened read-write. `intent_lock_is_free` is not changed (E-8).

## Risk Register

| # | Risk | Sev | Mitigation |
|---|---|---|---|
| R1 | Nested bwrap is impossible (M1) | HIGH | Two-phase gate |
| R2 | The phase-2 parent has host network; a caller's `PYTHON*`/`sitecustomize` imports before the blocker (phase 2 runs without `-I`) | MED | Blocker; 7 conditions incl. the env scrub; deny-list lint; `--unshare-net` children. The `PYTHON*` exposure is operator-controlled, as in phase 1, and is stated in the E-7d Residual (B5-R5). |
| R3 | Ownership move | MED | E-7e(f) with plan:line |
| R4–R6 | mtime; `--size` order; cgroup naming | LOW–MED | Digests; argv tests; 78 |
| R7 | Degraded notifier runs unwrapped | MED | Exact fallback set |
| R8 | AUT-2 credential copy inside the sandbox | LOW (stated) | `credential_env` plus `LoadCredential`; key denylist (B5-R4); GET-only test |
| R9 | G6 in-place reads | MED | `exec_snapshot(False)` |
| R10 | `OnFailure=breezy-study-failed@` on owned units (AUT-1, 2, 3, 5, 6); ARCH l.1066 and AUT-2 l.1199 cite the old rule | MED | AC-5 red with the name; E-7e(f) supersede clause (B5-R3) |
| R11–R14 | Startup; worktree verification; table edits; bwrap upgrade | LOW | V9; primary tree; `validate_table` |
| R15 | Not a hostile-same-uid boundary. The ro-bound repo exposes git-ignored repo-root files, including the operator caps file (never read). Abstract sockets are shared (M32). DNS rows reach `127.0.0.53:53`. | MED (stated) | AC6 allowlists |
| R16 | sd_notify under userns | LOW | M20, V12 |
| R17 | Home path outside the re-binds | LOW | Fails closed |
| R18 | Phase 2 per lane | LOW | Unique basetemp |
| R19 | Wrapped units leave `test_unit_execstart_imports.py:143` | LOW | Consumer tests |
| R20 | Stale, forged or planted snapshot | LOW | Invocation key; directory discipline (M41) |
| R21 | PROC rows read same-uid `status` and `cmdline`; a namespace pid ≠ a host pid | LOW (stated) | ESRCH; rule in E-7e(c) |
| R22 | Studies-lock inode mismatch | HIGH (consumer) | `E7_STUDIES_LOCK`; path test |
| R23 | Drill and guard unwrapped | LOW (stated) | `UNWRAPPED_RESIDUAL_UNITS`; re-file conditions |
| R24 | Phase-1 user units outside the netns | MED (stated) | Literal stdlib argvs |
| R25 | False STOP_PRIOR CRITICAL | LOW | AC-3 precondition |
| R26 | Hung user manager | MED | Budget plus `-` (M34, M38); AC-9.6 mapping |
| R27 | A pre line killed by `TimeoutStartSec` skips the main step | MED | Lint `bound < TimeoutStartSec` (M35) |
| R28 | AUT-6 `IN_PROCESS_STUDIES_LOCK_UNITS` drift | MED | Derive from the table |
| R29 | Added pre lines break the consumers' E-9 bounds (AUT-3 10:45Z, AUT-6 health) | MED | reproduce-am 4134 (B5-R1); ARCH l.1089 amended to start + 145 s (B5-R2); K8 and `start_phase_bound_s` sum the pre lines |

## LESSONS Compliance

Headers were checked in `/home/jon/breezy/docs/core/LESSONS.md` (r3 grep): L-1 :8, L-12 :620, L-14 :685, L-22 :1017, L-23 :1038, L-33 :1282, L-42 :1419, L-43 :1433, L-46 :1495, L-47 :1512, L-50 :1563, L-51 :1583, L-54 :1647, L-55 :1664.

| Lesson | How it is met |
|---|---|
| L-1 | Native first: the `-` prefix, `%t`, `touch`/`flock(1)`, `LoadCredential`, `MONITOR_*` and pytest hooks. New code exists only for the handoff file. |
| L-12 | Exact sets: `KNOWN_EXCEPTIONS` (7), `ALTERNATE_BIND_BASES`, `NOTIFIER_FALLBACK_ROWS`, `AUTONOMY_OWNED_UNITS`, `UNWRAPPED_RESIDUAL_UNITS`, `RUN_TRANSIENT_SHOW_ARGV`, the `credential_env` denylist, the registry, the count and the pre-line forms. |
| L-14 | The `/run` allowlist comes from a measured inventory. The grammar refuses `run-*`. |
| L-22 | Keys are identities: the blocker class, the early witness, `INVOCATION_ID` and the validated dir fd. |
| L-23 | Real probes only (M33–M43). r5 adds no host claim. |
| L-33 | Mutations per WP, including the `O_NOFOLLOW`, budget, `-` and denylist mutants. |
| L-42 | `SqliteStateStore` fixtures. |
| L-43 | Both phases run after every merge, and each split seam is gated. |
| L-46 | Re-searched over AUT-1..7 with a broader regex. Every hit is classified with plan:line, including AUT-1's nine and AUT-2 l.1199 (B5-R3). |
| L-47 | r4's "every hit classified" overclaim is corrected. r4's daily 05:56:30Z figure is replaced by a derivation. |
| L-50 | Non-blocking sweep flock on the validated fd; cache flock. |
| L-51 | Exact interpreter; V-steps on the primary tree. |
| L-54 | The conftest and script edit is its own security-reviewed WP. |
| L-55 | `test_main_production_default_reads_real_cgroup_and_refuses`, `test_production_home_mount_args_hide_real_home`, `test_bus_handoff_production_default_runner_is_list_argv_popen_new_session`. |

## Trade-offs

- **Per-row snapshot budget vs a global constant.** E-9 differs per unit, and the lint ties `B` to the `timeout` literal and to `TimeoutStartSec`.
- **Process-group kill vs `subprocess.run(timeout)`.** `subprocess.run` returns on time but orphans grandchildren (M38).
- **The `touch` line vs the wrapper creating the lock.** The `touch` line keeps "never creates a bind source", and `touch` preserves the inode (M33).
- **`credential_env` vs a reconcile-only env file.** No extra file and no ordering premise. The denylist closes the override path.
- **Drill and guard unwrapped vs `--bus-action`.** No state-changing path ships without a consumer.
- **Confirm file vs a pytest-only check.** Every miss falls toward running phase 2.
- **Three-way B2b split.** One more merge, in exchange for seams of ≤ ~1,000 lines.
- **Amending ARCH l.1089 (health 120 → 145 s) vs shrinking the health pass.** The pass is read-only and ends before the next slot, so `HEALTH_PASS_BUDGET_S=90` stays as measured.

## Confidence Self-Assessment

**96/100.**
- Both r4 reviews APPROVE. Every B5 ruling is applied at a named location. The E-9 arithmetic now includes every pre line, with the derivation shown. The L-46 classification is complete under a broader regex.
- −2: `%t` is proven through `systemd-analyze condition`, not through a deployed unit (V20 checks it at build).
- −1: the `install -d` bound (5 s) assumes the AUT-5 r7 l.259 `timeout -k 1 4` shape in each consumer. `start_phase_bound_s` recomputes it from the real unit file.
- −1: the exact `BWRAP_HOST_EXPECTED_TESTS` value is fixed only at build.

---

## §ERRATA-REQUEST (final text, ready to file verbatim)

> **E-7d (coordinator, 2026-10-03, from ARCH-0 seam B r5): the gate runs real-namespace tests in an un-nested second phase.**
> - **Evidence.** Nested bwrap inside the gate fails ("No permissions to create a new namespace", apparmor `bwrap-userns-restrict`), while one level works. On pytest 9.1.1:
>   - a `-p` plugin's `pytest_load_initial_conftests` runs before any conftest import and can exit rc 2;
>   - `pytest_ignore_collect` keeps non-registry conftests and modules unimported;
>   - a `-p` plugin also named in `pytest_plugins` loads once;
>   - `PYTEST_PLUGINS` imports its module before the early hook;
>   - `-p no:<plugin>` blocks a `-p` plugin.
>
>   With the blocker and four conftest edits, the phase-2 parent loaded no `nautilus_trader*` or `breezy.adapters*` module.
> - **Rule 1: one gate, two phases.** `scripts/ci/run_tests_no_egress.sh` remains the gate.
>   - Phase 1 is the existing egress-blocked pytest, run with `-p tests.support.bwrap_host_phase`, selected by one `if bwrap / elif unshare / else exit 3` chain and run exactly once.
>   - Phase 2 then runs un-nested. The gate prints both exit codes and exits with the first non-zero.
>   - Phase 2 is omitted only when an exact argument token is `--collect-only`, `--co` or `--collectonly` **and** the mode-0600 confirm file that the script created with `mktemp` under the gate dir reads exactly `collect-only`. Phase 1's plugin writes that file from pytest's parsed `collectonly` option.
>   - A missing, empty or `run` confirm file runs phase 2, so disabling the plugin by any means (`--noconftest`, `-p no:…`, `PYTEST_ADDOPTS`) cannot skip phase 2. A token claim while pytest is not in collect-only mode exits rc 2.
>   - On a host where only `unshare` works, phase 1 runs and phase 2 refuses with rc 3, so the gate is red there by design.
>   - Phase 2's basetemp is a fresh `mktemp -d` under the gate dir; it and the confirm file are removed on exit.
> - **Rule 2: what phase 2 runs.**
>   - Exactly `tests.support.bwrap_host_phase.BWRAP_HOST_TEST_FILES` with `-m bwrap_host`. The set is exact and equals the AST-derived set of marker users.
>   - The passed count must equal the mutation-pinned literal `BWRAP_HOST_EXPECTED_TESTS`. A plan adding a real-namespace test widens both in the same commit (L-12).
>   - Phase 1 skips `bwrap_host` items with a reason naming phase 2. In phase 2, any skip, any item outside the set, or a count mismatch fails the session.
>   - The first merge ships a self-contained witness file as the only member.
> - **Rule 3: prevention in the parent.**
>   - Phase 2 runs with `BREEZY_BWRAP_HOST_PHASE=1` and `-p tests.support.bwrap_host_phase`, under `env -u` of `BREEZY_TEST_OS_EGRESS_BLOCK`, `BREEZY_GATE_COLLECT_ONLY_CLAIM`, `BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE`, `PYTEST_PLUGINS` and `PYTEST_ADDOPTS`. User arguments are never forwarded.
>   - The plugin puts a meta-path blocker at `sys.meta_path[0]` before any conftest loads. The blocker refuses `nautilus_trader*`, `breezy.adapters*` and the module of every `find_execution_egress_modules()` hit.
> - **Rule 4: N2, widened as an exact set.** `execution_egress_abort_reason` gains one keyword-only input; when it is absent, the rule is unchanged. An unattested session is admitted only if:
>   - (1) the variable is exactly `"1"`;
>   - (2) the attestation is absent;
>   - (3) the blocker (exact class) is at `meta_path[0]`;
>   - (4) every egress hit maps to a refused module;
>   - (5) no refused module is loaded;
>   - (6) the plugin was loaded with `-p`, and before any conftest import it found every positional argument inside the registry, no option that widens collection (`--rootdir` other than the repo, `--confcutdir`, `--noconftest`, `--pyargs`, `-c`/`--config-file`, a non-default `--import-mode`, or any `-p` beyond the plugin, `no:randomly` and `no:cacheprovider`), and neither `PYTEST_PLUGINS` nor `PYTEST_ADDOPTS` in the environment;
>   - (7) `pytest_ignore_collect` excludes every non-registry file and every directory that is not an ancestor of one.
>
>   Anything else aborts with rc 2. A variable set to any other value, including `""`, `"true"` or `"1 "`, aborts with rc 2; this differs from today only when the variable is set. Attested plus the phase variable aborts with rc 2. The credential gate runs first and is unchanged. The session end re-checks `sys.modules`. No canary is sent in phase 2.
> - **Rule 5: children and imports.** Every bwrap child a phase-2 test spawns goes through `tests/support/bwrap_harness.py`, which adds `--unshare-net` and an explicit environment. An AST lint covers the registry files and every `tests.support` module they import:
>   - denied imports: `socket`, `http*`, `urllib*`, `requests`, `httpx`, `aiohttp`, `websockets`, `ctypes`, `runpy`, `nautilus_trader*`, `breezy.adapters*`, `breezy.strategy*`, and `subprocess` except in the harness;
>   - denied calls: `os.exec*`, `os.spawn*`, `os.system`, `os.popen`, `os.fork`, `importlib.util.spec_from_file_location` and `SourceFileLoader`.
> - **Consumer obligation.**
>   - Nautilus work in a phase-2 test runs only inside a bwrap child.
>   - Phase-2 files live outside `tests/unit/` and `tests/contract/`.
>   - A receiver a child must reach runs inside that child's namespace.
>   - A phase-1 test may start bwrap through `systemd-run --user`; such a unit runs outside the gate's network namespace, so its argv is literal, stdlib-only and imports no `breezy` module.
> - **Residual.** The phase-2 parent has host network for native non-Nautilus code. Python sockets stay blocked by the conftest fixture. File-path module loading is covered by the Rule 5 lint. A `PYTEST_PLUGINS` module set by a caller who bypasses the script imports before any check; the script's scrub is the control. Phase 2 runs `python -m pytest` without `-I` because worktrees need `PYTHONPATH`; a caller-controlled `PYTHON*` variable or `sitecustomize` imports before the blocker. This is operator-controlled environment, the same exposure as phase 1.
> - **Supersedes** B-R1's "Phase 2 collects `-m bwrap_host tests/`" and AUT-5 r7 l.287's verify-first branch. **Security sign-off:** ARCH-0 seam B r3 security review, YES-WITH-CONDITIONS, with C-1 and C-2 folded in above; seam B r4 security and architect reviews, ADOPT, with the r4 security N2 residual sentence added above. **Filed before** WP-B2a merges.

> **E-7e (coordinator, 2026-10-03, from ARCH-0 seam B r5): ARCH-0 owns the shared wrapper, table, self-probe, bus snapshot handoff and E-8 helper.**
> - **Ownership.** ARCH-0 seam B owns `deploy/systemd/breezy-autonomy-bwrap`, `AUTONOMY_BWRAP_TABLE` and its validation, the self-probe, the bus snapshot handoff, the E-8 helper (`wal_snapshot`, `exec_snapshot`) and the E-7a rule-1 unit lint. They live in `src/breezy/runtime/autonomy_sandbox/`, under the forbidden contract `breezy.runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy` (`allow_indirect_imports=false`). This is a stated deviation from ARCH §3's "types live in persistence/autonomy". AUT-5 keeps the halt and intent decode, the 16:48:00 value, the E-8 test names and its rows. In the E-7/E-8 consumption table, the AUT-5 "owns" entries move to ARCH-0.
> - **(a) Write-authority allowlists.** AUT-5 r7 l.292's `exec_snapshot.py` and `sandbox_probe.py` rows are replaced by `SHARED_WRITE_SITES`, admitted only when every snapshot call passes `cache_dir=` a module-level `Final` constant of the caller.
> - **(b) E-8 amendment.**
>   - Fingerprint: (inode, size, `mtime_ns`) plus sha256 of db bytes 0–99, `-wal` bytes 0–31 and its last 4096, `-journal` bytes 0–511; a 20 ms quiescence wait.
>   - Copy order db, `-wal`, `-journal`, fd-relative, into `snap.*` under an `O_RDONLY|O_DIRECTORY` cache-dir flock; contention gives `cache_busy`.
>   - Non-advisory only if the intent flock was held throughout.
>   - `take_flock=True` only in the AUT-5 16:45 pass, after the day's STOP_PRIOR decision line, with a deadline before 16:50. A STOP_PRIOR that starts during the hold refuses with one false CRITICAL and no signal (residual).
> - **(c) Mount-set amendment to E-7 rule 2 and E-7a rules 1, 2 and 5.** Every row runs:
>   - `--unshare-user --disable-userns --assert-userns-disabled --unshare-pid`;
>   - `--ro-bind / /`, `--tmpfs /run`, `--dev /dev`;
>   - `--proc /proc` except on `E7A_R2_PROC` rows, which keep `--unshare-pid` and see the host procfs read-only through the root bind (locks, status and cmdline readable; environ and root EACCES; signals to host pids ESRCH);
>   - `--size N --tmpfs /tmp`;
>   - `--tmpfs ~` with ro re-binds of exactly the repo, the data root, the interpreter prefix and, on `E7_FIXTURE_ROOT` rows, the alternate base;
>   - the exact per-row `/run` re-binds: resolv target (`resolves_dns`), `NOTIFY_SOCKET` (`E7A_R2_NOTIFY`), `/run/user/<uid>/breezy-studies.lock` (`E7_STUDIES_LOCK`) and `$CREDENTIALS_DIRECTORY` (`E7A_R2_RECONCILE`), then `--remount-ro /run`;
>   - `--bind-fd` binds after a nofollow walk, distinct from `state/` and its ancestors; `--ro-bind-fd` config; `~/.config/systemd/user` only under `E7_CONFIG_DIR`;
>   - `--remount-ro ~`;
>   - `--setenv TMPDIR /tmp --setenv XDG_CACHE_HOME /tmp/.cache`, `--unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`, and on `E7A_R2_RECONCILE` rows `--setenv <VAR> $CREDENTIALS_DIRECTORY/<name>` for each `credential_env` item. `credential_env` keys must additionally not be `PATH`, `HOME`, `TMPDIR`, `XDG_*`, `LD_*`, `PYTHON*` or `BREEZY_AUTONOMY_*`; `validate_table` rejects them.
>
>   This replaces E-7a rule 2's "drop `--unshare-pid`". **E-7a rule 2's test sentence becomes:** "A test fails if a wrapped unit's code references `/proc/locks` or `/proc/<pid>` while its row lacks `host_proc`." **Rule:** on `E7A_R2_PROC` rows, never index `/proc` by a namespace pid (`os.getpid()`, `Popen.pid`); those name other host processes. Rule 5's `/proc/<pid>` residual narrows to read-only status and cmdline visibility. No row exposes `/run/user/<uid>/bus`, `/run/user/<uid>/systemd/private`, docker, snapd, lxd or the system bus. The unit check is integrity against misconfiguration, not an authorisation boundary. The wrapper never creates a bind source, including the studies lock.
> - **(d) Self-probe amendment to E-7 rule 2.**
>   - The env-row check runs before any open.
>   - Negatives come from the table only, with an owned-directory precondition and exactly EROFS on `O_TMPFILE|O_WRONLY`; no named file is created under `state/`, the data root or the repo.
>   - Positives are `tmpfile`/`subdir`.
>   - Credential paths give ENOENT, and the home listing is ⊆ the re-binds.
>   - Host and bus sockets give ENOENT; `/run` is allowlisted and read-only.
>   - pid namespace: `/proc/1/comm == "bwrap"`, or on `E7A_R2_PROC` rows `/proc/self` ≠ `getpid()`. This is an integrity check, not a boundary.
>   - Vocabulary: AUT-6's codes plus `env_row`, `degraded_forged`, `credentials_visible`, `user_bus_visible`, `host_socket_visible`, `run_not_private`, `run_not_readonly`, `tmp_not_private`, `pid_ns`, `negative_unverifiable`.
> - **(e) Labels.** `KNOWN_EXCEPTIONS = {E7A_R2_PROC, E7A_R2_NOTIFY, E7A_R2_RECONCILE, E7B_EVAL_OFFLINE_ADAPTER_MODULES, E7_CONFIG_DIR, E7_STUDIES_LOCK, E7_FIXTURE_ROOT}`. There is no user-bus label and no bus-action label.
> - **(f) Consumer changes (binding build items).**
>   - **Every plan:**
>     - an owned unit's `OnFailure=` names `breezy-autonomy-failed@%n.service`, never `breezy-study-failed@`. This supersedes ARCH §5.2 l.1066's `OnFailure=breezy-study-failed@` for autonomy-owned studies (E-7a rule 1); AUT-2 l.1199 is amended accordingly;
>     - `resolves_dns=True` on every row that can deliver an alert, each with a test;
>     - E-9 sums count every pre line at `T + K` (`TimeoutStartSec` re-arms per command), and each pre line's bound is below the unit's `TimeoutStartSec`. In the AC-5 form-1 shape (`timeout -k 1 4`, AUT-5 r7 l.259) an `install -d` line counts 5 s; the `touch` line counts 5 s; a bus-snapshot line counts `B + 5`.
>   - **AUT-1 r12:**
>     - l.770/939: the audit's `systemctl --user show` becomes a bus read (budget 10, a `cache/` bind; a missing snapshot is never a pass); l.768-769: journalctl in-sandbox;
>     - l.731/733/741/883-884/941: the drill and guard run **unwrapped**, listed in `UNWRAPPED_RESIDUAL_UNITS` as an E-7a rule-5 residual, with no socket bind. Re-wrapping re-files with `--kill-whom=main`, the bus-snapshot directory discipline, SIGCONT on every exit path and a target set with plan:line;
>     - l.875 is amended accordingly; l.1045: V-9(b) becomes the handoff;
>     - l.905-906: `OnFailure=breezy-autonomy-failed@%n.service`, and the `alerts.env` re-bind is removed;
>     - l.881: `flock -w %t/breezy-studies.lock`;
>     - the stop-hook unit is linted on its wrapper line only; l.125/886 rotate is unchanged;
>     - E-9: audit latest end 13:50 + 60 s + 15 s + 1500 s + 5 s = 14:16:20 (plus `T + K` of any `install -d` pre line, ≤ 5 s: ≤ 14:16:25) ≤ 14:25. The `flock -w 600` runs inside ExecStart's `timeout` (≤ 1500), so it is not added; AUT-1 l.881 is restated on this basis.
>   - **AUT-2 r7:**
>     - l.180/468: reconcile is `E7A_R2_RECONCILE` with `LoadCredential=`, `credential_names=("polymarket_us_secret_key",)` and `credential_env={"POLYMARKET_US_SECRET_KEY_FILE": "polymarket_us_secret_key"}`, and the caller passes the existing `require_key_file_mode=0o400` (`env.py:98`). The inline-key variable is absent (otherwise the loader fails closed). No `env.py` or firewall-test change is permitted. Reconcile stays GET-only (consumer test). `resolves_dns=True`.
>     - l.408/953: label unit `OnFailure=breezy-autonomy-failed@%n.service`; l.1199's "The label unit keeps `OnFailure=breezy-study-failed@` (the §5.2 studies rule)" is amended to `breezy-autonomy-failed@%n.service` per "Every plan"; l.423/463/1188: the `breezy-score-live-trials` slot-guard path is unchanged (not owned).
>     - l.470/485/1054: `breezy-aut2-recon-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
>     - l.467: `%t/breezy-studies.lock`; wrapped G6 reads use `exec_snapshot(take_flock=False)`.
>   - **AUT-3 r6:**
>     - l.267: `NotifyAccess=all` and `OnFailure=breezy-autonomy-failed@%n.service` on refit and both repro units;
>     - l.279-283/292: `E7_STUDIES_LOCK` with `ExecStartPre=-/usr/bin/timeout -k 1 4 /usr/bin/touch %t/breezy-studies.lock` (+5 s; reproduce-am `TimeoutStartSec` 4139 → **4134**, so 09:35:00 + 1 + 5 + 4134 + 60 = 10:45:00Z, and the AM eligibility threshold becomes `runtime_s × 1.2 + 600 ≤ 4134`, i.e. `runtime_s ≤ 2945`; AUT-4's K8 test sums pre lines.)
>     - l.296: the repro extract moves to `cache/refit-repro/`;
>     - l.190/282-283: wrapped transients pass `--unit=<row unit>` and use the literal lock path.
>   - **AUT-4 r11:**
>     - l.661/1228/1401: `E7_FIXTURE_ROOT`;
>     - l.848/871/888/892/898: both integration files join the registry;
>     - l.875-884: `WRAPPER_CODE_FILES` and `build_bwrap_argv`;
>     - l.634-635/664: `%t/breezy-studies.lock` via `flock -w` (no pre-create);
>     - l.642 (K8): `test_pre_offline_studies_units_end_by_1045z` sums every pre line at `T + K`;
>     - l.637/848/1311: unchanged;
>     - E-13 tests are delivered by ARCH-0 at AUT-4's paths.
>   - **AUT-5 r7:**
>     - l.278-282: wrapper rows `breezy-autonomy-engine@<mode>` with exact instance names, the bootstrap `derived/artefacts`, and the stage-S rows;
>     - l.202/286: `require_sandbox`;
>     - l.277: `OnFailure=breezy-autonomy-failed@%n.service`;
>     - l.284: the table-derived config test;
>     - l.285/405/879-880: registry;
>     - l.292: `SHARED_WRITE_SITES`;
>     - l.386-388: `exec_snapshot(False)`;
>     - E-8: the STOP_PRIOR-line precondition;
>     - l.259/279/273-275: unchanged.
>   - **AUT-6 r15:**
>     - l.203-207/802/958/966: `systemctl` reads become `--bus-snapshot` with `--` before units, on new `cache/aut6_health_bus` and `cache/aut6_failed_bus` binds plus daily's `cache/aut6_daily_exec_snapshot`; budgets health 15, failed@ 10, daily 15. The health `show -p <fixed set> -- 'breezy-*'` result also lists timers and slices, so the consumer filters on `Id` ending `.service` (with a consumer test).
>     - l.961-962: failed `run-*` transients through `RUN_TRANSIENT_SHOW_ARGV`.
>     - Mapping: `bus_snapshot_missing`/`_stale` → health UNKNOWN (`passes_unknown_streak` increments); failed@ and daily page CRITICAL. A per-read failure keeps l.488/l.957. Tests `test_health_bus_snapshot_missing_is_unknown`, `test_failed_notifier_pages_when_bus_snapshot_missing`, `test_daily_pages_when_bus_snapshot_missing`.
>     - E-9:
>       - health ≤ start + `T+K`(install) + 20 + 115 + 5 s (≤ start + 145 s); **this erratum amends ARCH §5.2 l.1089 `aut6.health` to '≤ 145 s | start + 145 s'**. The 16:31/16:41/16:51/17:01 passes end ≤ +146 s from the slot, before the next slot, and the pass is read-only. `HEALTH_PASS_BUDGET_S=90` is unchanged. (ARCH l.1089 today reads "≤ 120 s | start + 120 s". AUT-6 l.1037 and l.1061 are restated to slot + 146 s, and l.1064 to 05:55:36Z / 13:25:36Z, e.g. the 16:41 pass ends ≤ 16:43:26.)
>       - failed@ runs `T+K`(install) 5 s + snapshot (`timeout -k 2 13`) 15 s = ≤ 20 s before its page; AUT-6 l.1053's 'ends ≤ start + 61 s' becomes '≤ start + 81 s' (the AUT-6 owner re-derives it from the unit file via `start_phase_bound_s`).
>       - daily ends ≤ 05:30:00 + 1 (accuracy) + 5 (install) + 5 (touch) + 20 (snapshot, `timeout -k 2 18`) + 1500 (ExecStart; the 300 s lock deadline is inside it) + 5 (`TimeoutStopSec`) = 05:55:36Z, and likewise ≤ 13:25:36Z, inside "ends ≤ 06:00Z and ≤ 13:30Z".
>     - l.1174: V-6 expects in-row `systemctl` to fail and the snapshot to equal the outside reads.
>     - l.247/250: `E7A_R2_PROC`.
>     - l.249/671: `E7_STUDIES_LOCK` on `/run/user/<uid>/breezy-studies.lock` with the `touch` line and a path test; l.1071: `IN_PROCESS_STUDIES_LOCK_UNITS` derived from the table rows with `studies_lock=True`.
>     - l.249/1444: `E7_CONFIG_DIR`; l.241-243/1334: home-allowlist and `/run`-set assertions; l.260-262: `O_TMPFILE` negatives.
>     - l.1335-1338/1349/1356-1357/1375-1376: move to `tests/integration/test_integrity_floor_bwrap_namespace.py` (registry), with the l.1357 receiver in the child; l.1150/1228/1400: registry; l.1377/1292/2290: phase 1.
>     - l.276/1046: producer-daily `OnFailure=breezy-autonomy-failed@%n.service`; l.1027: recount the multi-command units (health 2 pre lines, failed@ 2, daily 3) via `start_phase_bound_s`.
>     - `breezy-autonomy-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
> - **(g) Notifier fallback.** Only rows in `NOTIFIER_FALLBACK_ROWS` may fall back, only after every configuration check, with a 2 s preflight. `degraded_write_target` refuses `state/` and anything outside the binds, and the consumers' closure tests enforce its use. Degraded mode exposes `~/.config/breezy` (residual).
> - **(h) Bus snapshot handoff.**
>   - **No bus inside any sandbox, and no state-changing bus call anywhere in ARCH-0.**
>   - A row's literal `systemctl --user show|list-units|list-timers` argvs, which must follow the grammar (`-p` + one `^[A-Za-z,]+$` token; `--` before unit tokens; unit tokens `^breezy-[a-z0-9@._*-]+$` or a re-validated `{instance}`; `run-*` only as the exact `RUN_TRANSIENT_SHOW_ARGV`), run unsandboxed through `ExecStartPre=-/usr/bin/timeout -k 2 <B+3> …/breezy-autonomy-bwrap --bus-snapshot <row>` as the last pre line, with `B + 5 < TimeoutStartSec`. They run only after every wrapper configuration check.
>   - A monotonic budget `B ∈ [1, 25]` bounds all reads; each read runs in its own session and is process-group killed on timeout; unstarted reads are recorded `skipped`; the file is always written.
>   - The file is created through a validated `O_DIRECTORY|O_NOFOLLOW` fd on `.bus_snapshot` inside a `cache/` bind (owner, mode, device and forbidden-inode checks). It is keyed by `$INVOCATION_ID`, read and unlinked by the sandboxed step, and swept after 24 h only for regular files named `^[0-9a-f]{32}\.json$`.
>   - A failed pre step never skips the main step (`-` prefix), and the main step maps a missing or stale snapshot per (f).
> - **(i) Residuals.**
>   - Same-uid hostile processes are out of scope.
>   - `E7A_R2_PROC` rows read other same-uid processes' `/proc/<pid>/status` and `cmdline`, at parity with unwrapped (no `hidepid`).
>   - Abstract unix sockets and loopback are shared, because the network namespace is shared; DNS rows reach the `127.0.0.53:53` stub.
>   - The ro-bound repo exposes git-ignored repo-root files, including the operator caps file (no credential, never read).
>   - `E7A_R2_RECONCILE` rows see their own loaded credential copy.
>   - AUT-1's drill and guard run unwrapped (`UNWRAPPED_RESIDUAL_UNITS`).
>   - The studies-lock `touch` line updates the lock's mtime; nothing depends on it.
> - **Sign-off:** ARCH-0 seam B r3 security rulings (a)–(c) and (e)–(g) accepted, (d) applied by removal; architect r3 AMEND items applied; seam B r4 security and architect reviews ADOPT-WITH-AMENDMENT, with the amendments applied above (architect B-1 and B-2 verbatim, the ARCH l.1066 supersede clause, the security N1 key denylist). **Filed before** WP-B2b-1 merges.

Files relevant to this plan:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r4.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r4-security.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r4-architect.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-r1-merged.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` (l.1065-1066, l.1089)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md` (l.1199)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-3-retraining_plan_r6.md` (l.271)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md` (l.642)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md` (l.259)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md` (l.1027-1064)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-7-rollback_plan_r5.md`
- `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`
- `/home/jon/breezy/tests/conftest.py`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/env.py`